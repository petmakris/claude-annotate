package com.petros.ireview;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * Talks to the shared webcompanion daemon under {@code kind=interactive-review}:
 * discovers a session by cwd, opens an SSE stream, caches per-anchor
 * syntheses, and pushes events to listeners.
 *
 * Thread-safe. Listeners are invoked on the SSE consumer thread; bridge
 * to the EDT in the UI components.
 */
public final class ReviewSessionClient {

    public record SessionInfo(String sid, String prRef, String title) {}
    public record ThreadState(String synthesis, int version, String anchorText,
                              String title, String question, long updatedAt) {
        /** Compat constructor for callers that don't carry a timestamp. */
        public ThreadState(String synthesis, int version, String anchorText,
                           String title, String question) {
            this(synthesis, version, anchorText, title, question, 0L);
        }
    }

    public interface Listener {
        default void onAttached(SessionInfo info) {}
        default void onDetached() {}
        default void onThreadChanged(String anchor, String synthesis, int version) {}
        default void onThreadDeleted(String anchor) {}
        default void onPendingChanged(String anchor, boolean pending) {}
        default void onStateChanged(State state) {}
        /** A non-fatal problem worth surfacing to the user (e.g. the thread
         *  seed gave up after retries and the panel may be incomplete). */
        default void onWarning(String message) {}
    }

    /**
     * Session lifecycle, in precedence order ENDED > PAUSED > DISCONNECTED >
     * ACTIVE. PAUSED = watcher silent past STALE_AFTER but recoverable (the
     * user may re-arm). ENDED = the server reported the session terminal
     * (cancelled/finished), or the watcher heartbeat has gone stale past the
     * hard {@link #REAP_AFTER_MS} cutoff; it is a one-way latch — the panel
     * freezes read-only and never un-freezes for the same sid. OFFLINE means
     * discovery cannot reach the server at all (as opposed to DORMANT: server
     * reachable, no session for this cwd).
     */
    public enum State { DORMANT, CONNECTING, ACTIVE, DISCONNECTED, PAUSED, ENDED, OFFLINE }

    /**
     * How long the watcher heartbeat may age before we treat the Claude
     * session as merely PAUSED. The watcher rewrites it every ~1s (even while
     * blocked on an ack), so anything past this is gone, not slow. The
     * authoritative ENDED decision is either a marker file on disk
     * ({@code finished}/{@code cancelled}, reported straight through /poll) or
     * the hard {@link #REAP_AFTER_MS} cutoff below.
     */
    private static final Duration STALE_AFTER = Duration.ofSeconds(15);

    /**
     * Hard end-of-life cutoff on watcher-heartbeat age, distinct from the soft
     * {@link #STALE_AFTER}-driven PAUSED state above. The daemon's /poll has
     * no {@code ended}/{@code ended_reason} verdict of its own — only the raw
     * {@code finished}/{@code cancelled} marker booleans and
     * {@code watcher_seen_at} — so unlike the old per-skill server (which used
     * to INFER a "dead" verdict server-side from one heartbeat sample, flaky
     * enough that this client once needed a confirmation count before trusting
     * it), there is nothing left to confirm: this value is read directly and
     * deterministically every poll. Reproduces client-side the same 180s value
     * the old per-skill server enforced server-side, matching {@link
     * WalkthroughSessionClient}'s identical {@code REAP_AFTER_MS}.
     */
    private static final long REAP_AFTER_MS = Duration.ofSeconds(180).toMillis();

    /**
     * One-way latch: once the server says the attached session is ENDED, the
     * panel freezes read-only. Reset only when we attach a different session
     * or fully detach. A returning heartbeat must never un-freeze it.
     */
    private volatile boolean endedLatched = false;

    /**
     * Consecutive {@link #fetchNewestSession()} failures (timeout, connection
     * refused, server restart) required before a discovery blip is treated as
     * a real detach — same pattern as {@link WalkthroughSessionClient}. One
     * dropped poll must not wipe the cache and blank the panel.
     */
    private static final int DISCOVERY_FAILURE_THRESHOLD = 3;

    /**
     * How long an anchor may stay pending without an answer before the spinner
     * is cleared — no ack is coming if Claude is wedged or the event was lost,
     * and a forever-spinner blocks the gutter's ask affordance.
     */
    private static final Duration PENDING_TIMEOUT = Duration.ofSeconds(120);

    /** Re-resolved on discovery failure — the server may have restarted on a
     *  new port and rewritten server.json (see {@link #refreshBaseUrl()}). */
    private volatile String baseUrl;
    private final java.util.function.Supplier<String> baseUrlSupplier;
    private final String projectCwd;
    private final Duration pollInterval;
    private volatile int discoveryFailures = 0;
    private static final com.google.gson.Gson GSON = new com.google.gson.Gson();

    /** Discriminator field ("v") in the anchor_text JSON envelope postComment
     *  sends inside the submit payload's text field — lets a reader (Task
     *  4's SKILL.md) tell this structured shape apart from a plain comment
     *  string. Bump only in lockstep with SKILL.md's parser. */
    private static final int ANCHOR_TEXT_ENVELOPE_VERSION = 1;

    /** Per-request read timeout for the synchronous polls — without it a
     *  server that accepts the socket but stalls pins a discovery-pool thread
     *  indefinitely and survives project close. */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2)).build();
    /** Short, non-blocking polls + reconnect scheduling only. */
    private final ScheduledExecutorService exec = Executors.newScheduledThreadPool(2);
    /** The blocking SSE stream lives here, never on {@link #exec}, so a stream
     *  that blocks for its whole lifetime (or stalls) can't starve discovery /
     *  liveness polling. Cached so a session switch never wedges behind a
     *  not-yet-closed prior stream. */
    private final ExecutorService sseExec = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "ireview-sse");
        t.setDaemon(true);
        return t;
    });
    /** Single-flight guard for the SSE stream. Every openSse bumps it; a stream
     *  whose generation is stale ignores its events and never reconnects, so a
     *  reconnect or session switch can't leave two live streams writing the
     *  cache. */
    private final java.util.concurrent.atomic.AtomicLong sseGen =
        new java.util.concurrent.atomic.AtomicLong();
    /** Guards the state check-and-set so two threads can't both pass the guard
     *  and drop/duplicate a transition. */
    private final Object stateLock = new Object();
    private final java.util.List<Listener> listeners = new CopyOnWriteArrayList<>();
    private final Map<String, ThreadState> cache = new ConcurrentHashMap<>();
    /** Bumped on every cache mutation so consumers (e.g. the gutter index) can
     *  memoize against a cheap version stamp instead of rebuilding each paint. */
    private final java.util.concurrent.atomic.AtomicLong cacheVersion =
        new java.util.concurrent.atomic.AtomicLong();
    /** Anchors with an in-flight Claude reply (post-submit, pre-SSE-confirmation),
     *  mapped to the submit token that set them. A later submit on the same
     *  anchor supersedes the token, so a stale failure can't clear a newer
     *  in-flight reply's spinner. */
    private final Map<String, Long> pending = new ConcurrentHashMap<>();
    private final java.util.concurrent.atomic.AtomicLong submitSeq =
        new java.util.concurrent.atomic.AtomicLong();
    private volatile boolean closed = false;
    private volatile State state = State.DORMANT;
    private volatile SessionInfo current = null;
    private volatile Future<?> sseTask = null;
    private volatile ScheduledFuture<?> discoverTask = null;
    /** The live SSE connection handle, so teardown paths can actually close the
     *  stream (server sees EOF) instead of only cancelling the worker's join. */
    private volatile SseClient.Connection sseConnection = null;

    public ReviewSessionClient(String baseUrl, String projectCwd, Duration pollInterval) {
        this(() -> baseUrl, projectCwd, pollInterval);
    }

    /**
     * @param baseUrlSupplier resolves the server's base URL; re-invoked after a
     *        failed discovery poll so a server restart on a new port (which
     *        rewrites server.json) is picked up without an IDE restart.
     */
    public ReviewSessionClient(java.util.function.Supplier<String> baseUrlSupplier,
                               String projectCwd, Duration pollInterval) {
        this.baseUrlSupplier = baseUrlSupplier;
        this.baseUrl = baseUrlSupplier.get();
        this.projectCwd = projectCwd;
        this.pollInterval = pollInterval;
    }

    public void start() {
        discoverTask = exec.scheduleWithFixedDelay(this::pollDiscover,
            0, pollInterval.toMillis(), TimeUnit.MILLISECONDS);
    }

    public void stop() {
        closed = true;
        sseGen.incrementAndGet();
        if (discoverTask != null) discoverTask.cancel(true);
        cancelSse();
        exec.shutdownNow();
        sseExec.shutdownNow();
        setState(State.DORMANT);
    }

    /**
     * Cancels the SSE worker task AND closes the underlying stream.
     * {@code sseTask.cancel(true)} alone only interrupts the worker's join;
     * the TCP connection and the HttpClient's consumer thread stay alive until
     * the server hangs up. Closing the {@link SseClient.Connection} cancels
     * the body subscription so the server sees EOF immediately. Used on every
     * teardown path: {@link #stop()}, {@link #latchEnded()},
     * {@link #handleNoSession()}, and reconnect ({@link #openSse(String)}).
     */
    private void cancelSse() {
        if (sseTask != null) { sseTask.cancel(true); sseTask = null; }
        SseClient.Connection conn = sseConnection;
        if (conn != null) conn.close();
    }

    public void addListener(Listener l) { listeners.add(l); }

    public void removeListener(Listener l) { listeners.remove(l); }

    /** Monotonic counter bumped on every cache mutation; use to memoize. */
    public long cacheVersion() { return cacheVersion.get(); }

    public Optional<SessionInfo> currentSession() { return Optional.ofNullable(current); }

    public State state() { return state; }

    public Optional<ThreadState> threadFor(String anchor) {
        return Optional.ofNullable(cache.get(anchor));
    }

    public Map<String, ThreadState> snapshotCache() {
        return new java.util.HashMap<>(cache);
    }

    public boolean isPending(String anchor) { return pending.containsKey(anchor); }

    /** POST a comment event to /s/<sid>/api/submit. */
    public CompletableFuture<Void> postComment(String anchor, String text, String anchorText) {
        SessionInfo s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        if (state == State.PAUSED || state == State.ENDED) {
            return CompletableFuture.failedFuture(new IllegalStateException(
                "Claude session is gone — re-run /ask-diff to resume"));
        }
        long token = submitSeq.incrementAndGet();
        markPending(anchor, token);
        // The daemon's /api/submit handler (_submit) keeps only anchor/text/
        // images from the payload and drops everything else — confirmed
        // against server.py directly. anchor_text has nowhere else to ride,
        // so it travels JSON-encoded inside text itself; SKILL.md's Mode D
        // parses this identical {"v", "anchor_text", "comment"} envelope back
        // out. "v" discriminates this structured envelope from a plain
        // comment string (the daemon's own web page never sets it, and it
        // also lets Mode D refuse a pathological user comment that merely
        // happens to look like a JSON object with anchor_text/comment keys).
        java.util.Map<String, Object> envelope = new java.util.LinkedHashMap<>();
        envelope.put("v", ANCHOR_TEXT_ENVELOPE_VERSION);
        envelope.put("anchor_text", anchorText == null ? "" : anchorText);
        envelope.put("comment", text);
        java.util.Map<String, String> payload = new java.util.LinkedHashMap<>();
        payload.put("anchor", anchor);
        payload.put("text", GSON.toJson(envelope));
        String body = GSON.toJson(payload);
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + s.sid() + "/api/submit?kind=" + KIND))
            .header("Content-Type", "application/json")
            .timeout(REQUEST_TIMEOUT)
            .POST(HttpRequest.BodyPublishers.ofString(body)))
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .whenComplete((resp, err) -> {
                if (err != null || (resp != null && resp.statusCode() / 100 != 2)) {
                    clearPendingIfToken(anchor, token);
                }
            })
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("submit failed: HTTP " + resp.statusCode());
                }
            });
    }

    /**
     * POST to /s/<sid>/api/cancel — ends the review session. The server marks
     * it terminal; a live watcher picks up the marker and emits
     * WEBCOMPANION_CANCELLED. On success we detach immediately rather than
     * waiting for the next discovery poll to notice the session is gone.
     */
    public CompletableFuture<Void> cancelSession() {
        SessionInfo s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + s.sid() + "/api/cancel?kind=" + KIND))
            .timeout(REQUEST_TIMEOUT)
            .POST(HttpRequest.BodyPublishers.noBody()))
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("cancel failed: HTTP " + resp.statusCode());
                }
                handleNoSession();
            });
    }

    /** POST a delete request to /s/<sid>/api/threads/delete. */
    public CompletableFuture<Void> deleteThread(String anchor) {
        SessionInfo s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        String body = "{\"anchor\":" + jsonEscape(anchor) + "}";
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + s.sid() + "/api/threads/delete?kind=" + KIND))
            .header("Content-Type", "application/json")
            .timeout(REQUEST_TIMEOUT)
            .POST(HttpRequest.BodyPublishers.ofString(body)))
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("delete failed: HTTP " + resp.statusCode());
                }
            });
    }

    /** Mark an anchor pending under a submit token; notify only on the
     *  not-pending → pending transition. Arms a timeout that clears the
     *  pending state if no answer ever lands — token-guarded, so a newer
     *  submit on the same anchor keeps its own spinner and its own clock. */
    private void markPending(String anchor, long token) {
        if (pending.put(anchor, token) == null) {
            for (Listener l : listeners) l.onPendingChanged(anchor, true);
        }
        if (!exec.isShutdown()) {
            try {
                exec.schedule(() -> clearPendingIfToken(anchor, token),
                    PENDING_TIMEOUT.toMillis(), TimeUnit.MILLISECONDS);
            } catch (java.util.concurrent.RejectedExecutionException ignored) {
                // stop() raced us — the pending map dies with the client anyway.
            }
        }
    }

    /** Clear pending regardless of token — used when the reply is confirmed or
     *  the session freezes/pauses. */
    private void clearPending(String anchor) {
        if (pending.remove(anchor) != null) {
            for (Listener l : listeners) l.onPendingChanged(anchor, false);
        }
    }

    /** Clear pending only if this exact submit is still the latest one — a
     *  newer submit on the same anchor must keep its spinner. */
    private void clearPendingIfToken(String anchor, long token) {
        if (pending.remove(anchor, token)) {
            for (Listener l : listeners) l.onPendingChanged(anchor, false);
        }
    }

    // --- internal ---

    private void pollDiscover() {
        // This runs under scheduleWithFixedDelay: if ANY exception escapes
        // this method, the JDK silently cancels all future executions of
        // this task — no log line, no crash, the reconnect loop is just gone
        // forever until the IDE restarts. Every code path below (attach(),
        // pollLiveness(), handleNoSession(), and the listener notifications
        // they trigger via setState()) must never be allowed to propagate
        // out of here. The inner try/catch around fetchNewestSession() below
        // is deliberately narrower — it exists to distinguish "server
        // unreachable" from other failures — so it does not cover this.
        try {
            pollDiscoverUnguarded();
        } catch (Exception e) {
            System.err.println("[claude-ide-review] pollDiscover failed; will retry on the next tick: " + e);
            e.printStackTrace();
        }
    }

    private void pollDiscoverUnguarded() {
        SessionInfo found;
        try {
            found = fetchNewestSession();
        } catch (Exception e) {
            // Server unreachable. It may have restarted on a new port —
            // re-resolve server.json (cheap file read) before the next try.
            refreshBaseUrl();
            // A single blip must not wipe the cache/panel: require several
            // consecutive failures before detaching (mirrors
            // WalkthroughSessionClient). A frozen (ENDED) panel is never
            // wiped by unreachability at all.
            discoveryFailures++;
            if (!endedLatched && discoveryFailures >= DISCOVERY_FAILURE_THRESHOLD) {
                handleNoSession(State.OFFLINE);
            }
            return;
        }
        discoveryFailures = 0;
        if (endedLatched) {
            // Frozen read-only. Discovery only reaps dead sessions, so the
            // ONLY thing that replaces a frozen panel is a genuinely new, LIVE
            // session (a different sid). Never fall back to a zombie, never
            // clear on our own.
            if (found != null && (current == null || !current.sid().equals(found.sid()))) {
                attach(found);
            }
            return;
        }
        if (found == null) {
            // Discovery has nothing for this cwd. If we were attached, the
            // session most likely just ended (terminal/dead → reaped) — freeze
            // it on its own findings rather than blanking the panel. Only blank
            // when the session is genuinely gone (poll fails / not ended).
            if (current != null) {
                pollLiveness(current.sid());
                if (!endedLatched) handleNoSession();
            } else {
                handleNoSession();
            }
            return;
        }
        if (current == null || !current.sid().equals(found.sid())) {
            attach(found);
        }
        pollLiveness(found.sid());
    }

    private SessionInfo fetchNewestSession() throws Exception {
        String url = baseUrl + "/api/sessions?kind=" + KIND + "&cwd="
            + URLEncoder.encode(projectCwd, StandardCharsets.UTF_8);
        HttpRequest req = WebCompanionHttp.withContract(
                HttpRequest.newBuilder(URI.create(url)).timeout(REQUEST_TIMEOUT).GET()).build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        // A non-200 is a failure, not "no session" — it must count against
        // DISCOVERY_FAILURE_THRESHOLD like a socket failure would. A null
        // return is reserved for "the server answered 200 and the list is
        // empty" (mirrors WalkthroughSessionClient).
        if (resp.statusCode() != 200) throw new java.io.IOException("HTTP " + resp.statusCode());
        return parseFirstSession(resp.body());
    }

    /** Re-resolve the server URL after a failed discovery poll: the server may
     *  have restarted on a new port and rewritten server.json. Cheap (one file
     *  read behind the supplier), so every failed poll re-checks. */
    private void refreshBaseUrl() {
        try {
            String next = baseUrlSupplier.get();
            if (next != null && !next.equals(baseUrl)) baseUrl = next;
        } catch (RuntimeException ignored) {
            // keep the current URL; the next failure retries the read
        }
    }

    /** Freeze the current session read-only. One-way: only attach() clears it. */
    private void latchEnded() {
        endedLatched = true;
        sseGen.incrementAndGet();
        for (String a : new java.util.ArrayList<>(pending.keySet())) clearPending(a);
        cancelSse();
        setState(State.ENDED);
    }

    /**
     * Reachability of the HTTP server (it answers /api/sessions and keeps the
     * SSE stream open) does NOT mean the Claude session is alive — the server
     * is a long-lived process that outlives the session. The only liveness
     * signal is the watcher heartbeat, which the session rewrites every ~1s.
     * Poll it; if it has gone stale, flip to STALE so the UI stops claiming
     * "live" and submissions are refused.
     *
     * The daemon's real /poll shape ({@code {finished, cancelled,
     * watcher_seen_at, items, threads}}) carries no {@code ended}/{@code
     * ended_reason} verdict of its own — unlike the old per-skill server,
     * which pre-computed and named one. {@code ended} here is recomputed
     * client-side: {@code finished}/{@code cancelled} are authoritative
     * marker-file facts (one poll is proof, latch immediately), and a watcher
     * gone stale past {@link #REAP_AFTER_MS} is this client's own hard
     * cutoff, matching {@link WalkthroughSessionClient}'s identical
     * reasoning. No downstream UI text in this plugin distinguishes
     * cancelled/finished/a stale watcher from one another (grepped for
     * "ended_reason"/"cancelled"/"finished"/"dead" across every consumer
     * class — none), so collapsing all three into one boolean loses nothing.
     */
    private void pollLiveness(String sid) {
        if (endedLatched) return; // frozen; nothing un-freezes the same sid
        long seenAt;
        boolean finished;
        boolean cancelled;
        try {
            HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                    URI.create(baseUrl + "/s/" + sid + "/poll?kind=" + KIND))
                .timeout(REQUEST_TIMEOUT).GET()).build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) return;
            com.google.gson.JsonObject o = com.google.gson.JsonParser.parseString(resp.body()).getAsJsonObject();
            seenAt = o.has("watcher_seen_at") && !o.get("watcher_seen_at").isJsonNull()
                ? o.get("watcher_seen_at").getAsLong() : 0;
            finished = o.has("finished") && !o.get("finished").isJsonNull() && o.get("finished").getAsBoolean();
            cancelled = o.has("cancelled") && !o.get("cancelled").isJsonNull() && o.get("cancelled").getAsBoolean();
        } catch (Exception e) {
            return; // transient — leave state as-is, next poll retries
        }
        long ageMs = seenAt > 0 ? System.currentTimeMillis() - seenAt * 1000 : -1;
        boolean ended = finished || cancelled || (seenAt > 0 && ageMs > REAP_AFTER_MS);
        if (ended) { latchEnded(); return; }
        // No heartbeat written yet (session just armed) → not dead, leave alone.
        if (seenAt <= 0) return;
        if (ageMs > STALE_AFTER.toMillis()) {
            if (state != State.PAUSED) {
                // Clear pending so spinners and the side-panel × recover —
                // no ack is coming until the watcher returns.
                for (String a : new java.util.ArrayList<>(pending.keySet())) clearPending(a);
                setState(State.PAUSED);
            }
        } else if (state == State.PAUSED) {
            // Watcher came back (user re-ran /ask-diff).
            setState(State.ACTIVE);
        }
    }

    private void handleNoSession() { handleNoSession(State.DORMANT); }

    /** @param finalState DORMANT when the server answered and has no session;
     *                    OFFLINE when the server itself is unreachable. */
    private void handleNoSession(State finalState) {
        endedLatched = false;
        if (current != null) {
            current = null;
            cache.clear();
            cacheVersion.incrementAndGet();
            pending.clear();
            sseGen.incrementAndGet();
            cancelSse();
            for (Listener l : listeners) l.onDetached();
        }
        setState(finalState);
    }

    private void attach(SessionInfo s) {
        endedLatched = false;
        current = s;
        // Switching sessions: drop any cached state from the previous SID.
        // Otherwise the side panel keeps showing dead threads from the old
        // session and × clicks on them return HTTP 409 from the server.
        cache.clear();
        cacheVersion.incrementAndGet();
        pending.clear();
        setState(State.CONNECTING);
        for (Listener l : listeners) l.onAttached(s);
        // No I/O above this line — see loadPrRef()'s javadoc for why the
        // __meta__ fetch that used to run right here (blocking, before
        // openSse() had bumped the generation or closed the previous
        // stream) was a real bug, not just a style preference.
        openSse(s.sid());
    }

    /**
     * Bounded-retry fetch of {@code __meta__.body.pr_ref}, mirroring {@link
     * #seedCache}'s own 3-attempts/500ms-backoff shape exactly. Called from
     * {@link #runSse}, never from {@link #attach} — a prior version of this
     * file called an earlier, single-shot version of this fetch directly
     * from {@code attach()}, blocking it for up to {@link #REQUEST_TIMEOUT}
     * BEFORE {@link #openSse} had bumped {@link #sseGen} or closed the
     * previous session's stream. That left a window, for the whole fetch
     * duration, where the OLD stream was still open and its {@code
     * session-ended} frame's generation check still passed against the
     * not-yet-bumped generation — exactly the moment {@code push.py}'s
     * {@code create_or_attach(..., supersede=True)} fires {@code
     * session-ended} on the old session, i.e. the ordinary
     * supersede-on-new-review flow, not an edge case. Fixed by moving the
     * fetch here: {@code runSse} only starts running AFTER {@code openSse}
     * has already bumped the generation and closed the previous stream, so
     * a stale frame from the old stream can no longer land inside this
     * fetch's window — the generation it would need to match has already
     * moved on before this method's first line runs.
     *
     * <p>Also fixes the separate "permanently empty prRef" bug the old
     * single-shot version had: {@code push.py} creates the session row
     * ({@code create_or_attach}) and writes {@code __meta__} in a SEPARATE,
     * later call ({@code put_items}, which uploads the whole diff) — a
     * discovery poll landing in that gap finds a real session with no
     * {@code __meta__} yet. The retry loop below absorbs a miss within the
     * same attach; skipping this method entirely once {@code prRef} is
     * already known (it never changes for a session's lifetime — see {@code
     * sync.py}'s resync, which always preserves it) means a miss that
     * outlasts even the retry loop still gets one more attempt on every
     * subsequent SSE reconnect, since {@code runSse} runs again each time.
     */
    private void loadPrRef(String sid, long gen) {
        SessionInfo snapshot = current;
        if (snapshot == null || !snapshot.sid().equals(sid) || !snapshot.prRef().isEmpty()) return;
        for (int attempt = 0; attempt < 3 && !closed && gen == sseGen.get(); attempt++) {
            String prRef = fetchPrRef(sid);
            if (!prRef.isEmpty()) {
                // Re-check AFTER the round trip, BEFORE publishing — the
                // same guard handleSseEvent's own post-fetch mutations
                // already use for their HTTP round trips.
                if (closed || gen != sseGen.get()) return; // superseded mid-fetch
                SessionInfo latest = current;
                // Re-read (not the captured `snapshot`) and check its sid
                // too: a switch landing between the fetch returning and this
                // write must not stamp THIS fetch's answer (for `sid`) onto
                // whatever session is current now.
                if (latest == null || !latest.sid().equals(sid)) return;
                current = new SessionInfo(sid, prRef, latest.title());
                return;
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        // Gave up for this attempt — no onWarning (unlike seedCache's
        // exhausted-retry warning): an empty prRef degrades gracefully via
        // GhPrDiffOpener's own "No PR number" message rather than making the
        // whole panel look broken. The next SSE reconnect (a fresh runSse()
        // call, hence a fresh call to this method) tries again from scratch.
    }

    /**
     * Single GET of {@code __meta__.body.pr_ref}. Never called from {@link
     * #attach} — see {@link #loadPrRef}'s javadoc. Falls back to "" on any
     * failure (non-200, unparsable body, absent __meta__ item, or a
     * __meta__ with no pr_ref yet) — matching this file's existing "never
     * let a missing field crash discovery" posture; {@link #loadPrRef}
     * retries this, and {@code GhPrDiffOpener} already handles an empty
     * prRef with its own "No PR number" warning.
     */
    private String fetchPrRef(String sid) {
        try {
            HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                    URI.create(baseUrl + "/s/" + sid + "/items?kind=" + KIND))
                .timeout(REQUEST_TIMEOUT).GET()).build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) return "";
            com.google.gson.JsonObject root = com.google.gson.JsonParser.parseString(resp.body()).getAsJsonObject();
            if (!root.has("__meta__") || !root.get("__meta__").isJsonObject()) return "";
            com.google.gson.JsonObject metaItem = root.getAsJsonObject("__meta__");
            if (!metaItem.has("body") || !metaItem.get("body").isJsonObject()) return "";
            return str(metaItem.getAsJsonObject("body"), "pr_ref");
        } catch (Exception e) {
            return "";
        }
    }

    /**
     * Seed (or re-seed) the per-anchor cache from the bulk threads endpoint.
     * Retries a few times so a transient blip on attach doesn't leave the panel
     * empty until the next SSE event; dedups against the current cache so a
     * re-seed on reconnect doesn't churn listeners for unchanged threads.
     */
    private void seedCache(String sid, long gen) {
        for (int attempt = 0; attempt < 3 && !closed && gen == sseGen.get(); attempt++) {
            try {
                Map<String, ThreadState> fetched = deriveThreads(sid);
                applySeed(fetched, gen);
                // Clear any earlier "didn't load" warning: runSse() re-runs
                // this on every SSE (re)connect, so a seed that failed once
                // (a slow moment right after IDE startup, say) but then
                // succeeds on the automatic 2s reconnect must retract the
                // warning — otherwise the footer keeps telling the user the
                // panel is incomplete forever, even once every thread is
                // actually back. AnnotationsPanel treats a null message as
                // "no warning" the same way onAttached/onDetached already do.
                if (!closed && gen == sseGen.get()) {
                    for (Listener l : listeners) l.onWarning(null);
                }
                return;
            } catch (Exception ignored) {
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        // Gave up. An empty "live" panel with no explanation reads as "no
        // findings" — tell the listeners so the UI can show a warning instead
        // of silently lying. Only when this seed is still the current attach.
        if (!closed && gen == sseGen.get()) {
            for (Listener l : listeners) {
                l.onWarning("Couldn't load existing threads from the review server — "
                    + "the panel may be incomplete until the connection recovers.");
            }
        }
    }

    /** Writes the fetched threads into the cache — but only while {@code gen}
     *  is still the current attach generation. A session switch during the
     *  bulk-threads HTTP call (the initial seed, or a thread-changed frame's
     *  re-fetch — see {@link #handleSseEvent}) must not write the old
     *  session's threads into the new session's cache, so the generation is
     *  re-checked before every mutation, not just once up front. Used by both
     *  {@link #seedCache} and {@link #handleSseEvent}'s thread-changed branch —
     *  the daemon's frame carries only {anchor, version}, so learning the rest
     *  always means re-fetching the same bulk shape the seed already knows how
     *  to apply. */
    private void applySeed(Map<String, ThreadState> seeded, long gen) {
        for (var e : seeded.entrySet()) {
            if (closed || gen != sseGen.get()) return; // superseded mid-seed
            ThreadState existing = cache.get(e.getKey());
            ThreadState incoming = e.getValue();
            if (existing != null
                    && existing.synthesis().equals(incoming.synthesis())
                    && existing.version() == incoming.version()) {
                continue; // unchanged — don't re-fire listeners on a reconnect re-seed
            }
            cache.put(e.getKey(), incoming);
            cacheVersion.incrementAndGet();
            // A version bump with identical text is still an answer (metadata-
            // only synthesis update): pending must clear and listeners must
            // repaint, otherwise the spinner spins forever on a deduped reply.
            // Harmless no-op during the initial seed, since attach() already
            // cleared pending before seedCache() runs.
            clearPending(e.getKey());
            for (Listener l : listeners) {
                l.onThreadChanged(e.getKey(), incoming.synthesis(), incoming.version());
            }
        }
    }

    /**
     * GET {@code /s/&lt;sid&gt;/threads?kind=interactive-review} (bulk shape:
     * {@code {anchor: {anchor, version, messages: [{text, role, ts}], title?,
     * anchor_text?}}}) and derive each anchor's {@link ThreadState} the same
     * way {@code skills/_shared/static/wc-threads.js}'s {@code derive()} does,
     * plus this skill's own {@code anchor_text} field that walkthrough's
     * equivalent thread shape has no use for.
     */
    private Map<String, ThreadState> deriveThreads(String sid) throws Exception {
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + sid + "/threads?kind=" + KIND))
            .timeout(REQUEST_TIMEOUT).GET()).build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) throw new java.io.IOException("HTTP " + resp.statusCode());
        com.google.gson.JsonObject root = com.google.gson.JsonParser.parseString(resp.body()).getAsJsonObject();
        Map<String, ThreadState> out = new java.util.LinkedHashMap<>();
        for (var e : root.entrySet()) {
            if (!e.getValue().isJsonObject()) continue;
            ThreadState state = toThreadState(e.getValue().getAsJsonObject());
            if (state != null) out.put(e.getKey(), state);
        }
        return out;
    }

    /**
     * Converts one entry of the bulk {@code /threads} route's response into a
     * {@link ThreadState}, or {@code null} if the thread has no {@code
     * role == "agent"} message yet — omitted entirely, matching {@code
     * wc-threads.js}'s {@code derive()} (the page owns "pending" state for a
     * question it just submitted; an empty entry would overwrite that with
     * nothing). {@code role == "agent"} is the daemon's own default role and
     * the value {@code sync.py} replays messages under — see this file's own
     * report for the cross-check against Task 1/2's actual choice. The last
     * "agent" message is the synthesis (and its {@code ts} is {@code
     * updated_at}); the last "user" message is the question. {@code
     * anchor_text} and {@code title} are thread-level fields, not per-message.
     */
    private static ThreadState toThreadState(com.google.gson.JsonObject t) {
        com.google.gson.JsonElement messagesEl = t.get("messages");
        String synthesis = null;
        String question = "";
        long updatedAt = 0L;
        if (messagesEl != null && messagesEl.isJsonArray()) {
            for (com.google.gson.JsonElement el : messagesEl.getAsJsonArray()) {
                if (!el.isJsonObject()) continue;
                com.google.gson.JsonObject m = el.getAsJsonObject();
                String role = str(m, "role");
                if ("agent".equals(role)) {
                    synthesis = str(m, "text");
                    updatedAt = m.has("ts") && !m.get("ts").isJsonNull() ? m.get("ts").getAsLong() : 0L;
                } else if ("user".equals(role)) {
                    question = str(m, "text");
                }
            }
        }
        if (synthesis == null) return null; // no agent reply yet — omit
        int version = t.has("version") && !t.get("version").isJsonNull()
            ? t.get("version").getAsInt() : 0;
        return new ThreadState(synthesis, version, str(t, "anchor_text"), str(t, "title"), question, updatedAt);
    }

    private void openSse(String sid) {
        if (closed || sseExec.isShutdown()) return;
        URI uri = URI.create(baseUrl + "/s/" + sid + "/stream?kind=" + KIND);
        long gen = sseGen.incrementAndGet();
        cancelSse();
        try {
            sseTask = sseExec.submit(() -> runSse(sid, uri, gen));
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // stop() raced us between the guard and the submit — nothing to do.
        }
    }

    /** The blocking stream body. Runs on {@link #sseExec}. Only the current
     *  generation acts on events / reconnects; a superseded stream is inert. */
    private void runSse(String sid, URI uri, long gen) {
        // Load pr_ref, if not already known, on every (re)connect — see
        // loadPrRef()'s javadoc for why it lives here rather than in
        // attach(): this runs strictly AFTER openSse() has already bumped
        // sseGen and closed the previous stream, and a miss here self-heals
        // on the next reconnect rather than staying "" forever.
        loadPrRef(sid, gen);
        if (gen != sseGen.get() || closed) return; // superseded while fetching pr_ref
        // Seed on every (re)connect: covers a failed initial seed and an outage
        // where SSE events were missed while disconnected. Its retry-sleeps are
        // on sseExec, so they never starve discovery polling.
        seedCache(sid, gen);
        if (gen != sseGen.get() || closed) return; // superseded while seeding
        // Respect the documented precedence ENDED > PAUSED > DISCONNECTED >
        // ACTIVE. A live SSE stream says nothing about whether the watcher is
        // alive, so connecting must not clear PAUSED — only the discovery poll
        // owns that transition, and it restores ACTIVE once the heartbeat is
        // fresh again. Without this guard an SSE (re)connect races the poll and
        // can flip a watcher-dead session back to ACTIVE, letting the user
        // submit comments that nothing will ever ack.
        if (!endedLatched && state != State.PAUSED) setState(State.ACTIVE);
        SseClient.Connection conn = SseClient.connect(http, uri,
            ev -> handleSseEvent(sid, ev, gen),
            t -> { if (gen == sseGen.get() && !endedLatched && state == State.ACTIVE)
                       setState(State.DISCONNECTED); });
        sseConnection = conn;
        // A concurrent cancelSse() that ran between connect() returning and the
        // assignment above saw the stale field and couldn't close THIS stream.
        // Re-check now that it's published.
        if (closed || gen != sseGen.get()) conn.close();
        try {
            conn.done().join();
        } catch (Throwable ignored) {
            // Task cancelled/interrupted, or an unexpected join failure — fall
            // through to the single reconnect guard below.
        } finally {
            // Only clear it if it's still ours — a newer openSse() may have
            // already replaced (and closed) it.
            //noinspection ObjectEquality
            if (sseConnection == conn) sseConnection = null;
        }
        // Stream ended (clean close or post-error). This is the SOLE reconnect
        // path, so an error frame can't double-schedule. Reconnect only if this
        // stream is still current and we're not shutting down or frozen.
        if (gen == sseGen.get() && !closed && !endedLatched) {
            if (state == State.ACTIVE) setState(State.DISCONNECTED);
            scheduleReconnect(sid, gen);
        }
    }

    /** Reschedule a reconnect unless we're shutting down or this stream was
     *  already superseded — guards against a stale callback resurrecting a dead
     *  generation after stop()/detach/attach. */
    private void scheduleReconnect(String sid, long gen) {
        if (closed || exec.isShutdown() || gen != sseGen.get()) return;
        try {
            exec.schedule(() -> { if (gen == sseGen.get() && !closed) openSse(sid); },
                2, TimeUnit.SECONDS);
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // stop() raced us between the guard and the schedule — nothing to do.
        }
    }

    /** Applies one SSE event to the cache. {@code gen} is re-checked right
     *  before each mutation — the caller's check alone leaves a window where a
     *  session switch lands between the check and the write. */
    private void handleSseEvent(String sid, SseClient.Event e, long gen) {
        String name = e.name();
        com.google.gson.JsonObject data;
        try {
            data = com.google.gson.JsonParser.parseString(e.data()).getAsJsonObject();
        } catch (Exception ex) {
            return; // non-JSON heartbeat/connected frames
        }
        if ("session-ended".equals(name)) {
            // The server sends this only when a `finished`/`cancelled` marker
            // exists on disk — the authoritative end (same tier pollLiveness's
            // own finished/cancelled check treats as immediate), so it
            // latches immediately. Without handling it the server closed the
            // stream, this client saw only "stream ended", and reconnected
            // every 2s until the next poll happened to latch.
            if (gen != sseGen.get() || closed) return; // superseded stream
            // Hop to the polling pool: latchEnded() closes the very stream this
            // callback is running inside, and every other caller already
            // latches from there.
            if (!exec.isShutdown()) {
                try {
                    exec.execute(this::latchEnded);
                } catch (java.util.concurrent.RejectedExecutionException ignored) {
                    // stop() raced us — the session is going away anyway.
                }
            }
            return;
        }
        if ("thread-deleted".equals(name)) {
            String anchor = str(data, "anchor");
            if (anchor.isEmpty()) return;
            if (gen != sseGen.get() || closed) return; // superseded stream
            cache.remove(anchor);
            cacheVersion.incrementAndGet();
            clearPending(anchor);
            for (Listener l : listeners) l.onThreadDeleted(anchor);
            return;
        }
        if (!"thread-changed".equals(name)) return;
        // The daemon's real frame carries only {anchor, version[, initial]} —
        // unlike the old per-skill server's frame, which inlined the whole
        // synthesis/anchor_text/title/question. Learning the rest means
        // re-fetching the bulk shape and re-deriving every anchor in it;
        // applySeed's own version/synthesis-equality check already no-ops
        // anything unchanged, so applying every anchor (not just the one this
        // frame named) is simpler and no less correct.
        if (gen != sseGen.get() || closed) return; // cheap check before a wasted fetch
        try {
            Map<String, ThreadState> fetched = deriveThreads(sid);
            // Important-1 (Phase 3's fix-round lesson, applied from the start
            // here): re-check generation/closed AFTER the round trip and
            // BEFORE touching the cache — a session switch that lands while
            // this GET is in flight must not let a superseded session's
            // response overwrite the new session's cache. applySeed's own
            // per-entry loop re-checks this again on top, belt-and-braces.
            if (closed || gen != sseGen.get()) return;
            applySeed(fetched, gen);
        } catch (Exception ignored) {
            // Transient GET failure — the next thread-changed event, or the
            // next reconnect's seedCache(), retries.
        }
    }

    private void setState(State s) {
        synchronized (stateLock) {
            if (state == s) return;
            state = s;
        }
        // Notify outside the lock; listeners bridge to the EDT and re-read
        // state() there, so they always converge on the latest value.
        // Each listener is isolated: this loop runs inside pollDiscover(),
        // which runs on a scheduleWithFixedDelay task — one listener
        // throwing must not stop the others from being notified, and must
        // never escape to kill that scheduled task (see pollDiscover()).
        for (Listener l : listeners) {
            try {
                l.onStateChanged(s);
            } catch (Exception e) {
                System.err.println("[claude-ide-review] a Listener threw from onStateChanged(" + s + "), continuing: " + e);
                e.printStackTrace();
            }
        }
    }

    // --- json helpers ---

    private static String jsonEscape(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    /**
     * The shared webcompanion daemon (preferred by ServerDiscovery when its
     * config.json exists) hosts every skill's sessions in one registry,
     * tagged by "kind" — "show-diff", "walkthrough", "interactive-review",
     * etc. The legacy per-skill server (the fallback) only ever returns its
     * own kind and never tags it at all. array[0] used to be trusted blindly:
     * on a daemon with other skills' sessions for the same project (e.g. a
     * pile of leftover show-diff sessions from reviewing this same PR), that
     * silently attached to someone else's dead session instead of this
     * skill's live one — same symptom as a genuinely dead session (frozen
     * heartbeat, permanently PAUSED) but for a completely different reason,
     * and with none of this skill's fields (pr_ref/title) populated on the
     * wrong entry either. Filter to our own kind (or an untagged legacy
     * response) before taking the newest — sid's leading yyMMdd-HHmmss makes
     * plain string ordering also chronological ordering.
     */
    private static final String KIND = "interactive-review";

    private static SessionInfo parseFirstSession(String json) {
        com.google.gson.JsonElement root = com.google.gson.JsonParser.parseString(json);
        if (!root.isJsonArray()) return null;
        com.google.gson.JsonObject newest = null;
        for (com.google.gson.JsonElement el : root.getAsJsonArray()) {
            com.google.gson.JsonObject o = el.getAsJsonObject();
            String kind = o.has("kind") && !o.get("kind").isJsonNull() ? o.get("kind").getAsString() : null;
            if (kind != null && !KIND.equals(kind)) continue;
            if (newest == null || str(o, "sid").compareTo(str(newest, "sid")) > 0) newest = o;
        }
        if (newest == null) return null;
        // The daemon's session row has a FIXED shape ({sid, slug, kind, cwd,
        // title, url}) — no pr_ref field at all, unlike the legacy server's
        // own shape (which this used to read pr_ref straight off of). title
        // is present and safe to read here unchanged; prRef starts empty and
        // is populated by loadPrRef(), called from runSse() — see its javadoc.
        return new SessionInfo(str(newest, "sid"), "", str(newest, "title"));
    }

    /** Null-safe string field read; returns "" when absent or null. */
    private static String str(com.google.gson.JsonObject o, String key) {
        com.google.gson.JsonElement v = o.get(key);
        return (v == null || v.isJsonNull()) ? "" : v.getAsString();
    }
}
