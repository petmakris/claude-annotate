package com.petros.ireview;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;
import java.util.function.Supplier;
import java.util.function.UnaryOperator;

import static com.petros.ireview.WebCompanionHttp.flag;
import static com.petros.ireview.WebCompanionHttp.num;
import static com.petros.ireview.WebCompanionHttp.str;

/**
 * The session lifecycle every webcompanion-daemon client shares: discovers
 * the newest session of one {@code kind} for the project's cwd, follows it
 * over SSE, keeps its threads cached, tracks in-flight questions, and judges
 * liveness from the watcher heartbeat. {@link ReviewSessionClient} and
 * {@link WalkthroughSessionClient} add only what their skill needs on top.
 *
 * <p>Thread-safe. Listeners are invoked on the polling and SSE threads;
 * bridge to the EDT in UI code. A listener that throws is logged and skipped:
 * it never stops the others from being notified, and never escapes into the
 * scheduled discovery task (see {@link #pollDiscover()}).
 *
 * @param <S> the skill's session record
 * @param <T> the skill's thread record
 * @param <L> the skill's listener interface
 */
public abstract class DaemonSessionClient<
        S extends DaemonSessionClient.Session,
        T extends DaemonSessionClient.ThreadView,
        L extends DaemonSessionClient.SessionListener<S>> {

    /** What the lifecycle needs from a skill's session record. */
    public interface Session {
        String sid();
    }

    /** What the cache needs from a skill's thread record to skip unchanged ones. */
    public interface ThreadView {
        String synthesis();
        int version();
    }

    /**
     * Session lifecycle, in precedence order ENDED > PAUSED > DISCONNECTED >
     * ACTIVE. PAUSED = watcher silent past {@link #STALE_AFTER} but
     * recoverable (the user may re-arm). ENDED = the daemon reported the
     * session terminal (cancelled/finished), or the watcher heartbeat has gone
     * stale past the hard {@link #REAP_AFTER_MS} cutoff; it is a one-way latch
     * — the panel freezes read-only and never un-freezes for the same sid.
     * OFFLINE means discovery cannot reach the daemon at all (as opposed to
     * DORMANT: daemon reachable, no session for this cwd).
     */
    public enum State { DORMANT, CONNECTING, ACTIVE, DISCONNECTED, PAUSED, ENDED, OFFLINE }

    public interface SessionListener<S> {
        default void onAttached(S info) {}
        default void onDetached() {}
        default void onPendingChanged(String anchor, boolean pending) {}
        default void onStateChanged(State state) {}
        /** A non-fatal problem worth surfacing to the user (e.g. a seed gave
         *  up after retries and the panel may be incomplete); null retracts it. */
        default void onWarning(String message) {}
    }

    /**
     * One entry of the bulk {@code /threads} route, derived the way {@code
     * skills/_shared/static/wc-threads.js}'s {@code derive()} does: the last
     * {@code role == "agent"} message is the synthesis (its {@code ts} is
     * {@code updatedAt}), the last {@code role == "user"} message is the
     * question. {@code synthesis} is null when no agent reply exists yet —
     * such a thread is kept out of the cache, since the page owns "pending"
     * for a question it just submitted.
     */
    protected record BulkThread(String synthesis, int version, String anchorText,
                                String title, String question, long updatedAt) {}

    /**
     * How long the watcher heartbeat may age before the Claude session counts
     * as merely PAUSED. The watcher rewrites it every ~1s (even while blocked
     * on an ack), so anything past this is gone, not slow.
     */
    private static final Duration STALE_AFTER = Duration.ofSeconds(15);

    /**
     * Hard end-of-life cutoff on watcher-heartbeat age, distinct from the soft
     * {@link #STALE_AFTER}-driven PAUSED state. The daemon's /poll has no
     * {@code ended} verdict of its own — only the {@code finished}/{@code
     * cancelled} marker booleans and {@code watcher_seen_at} — so this client
     * applies the 180s cutoff itself, on every poll.
     */
    private static final long REAP_AFTER_MS = Duration.ofSeconds(180).toMillis();

    /**
     * How long an anchor may stay pending without an answer before the spinner
     * is cleared — no answer is coming if Claude is wedged or the event was
     * lost, and a forever-spinner blocks the ask affordance.
     */
    private static final Duration PENDING_TIMEOUT = Duration.ofSeconds(120);

    /** Per-request timeout for the synchronous calls — without it a daemon
     *  that accepts the socket but stalls pins a pool thread indefinitely and
     *  survives project close. */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);

    private static final long RECONNECT_DELAY_MS = 2_000;

    protected static final Gson GSON = new Gson();

    /** The daemon's session kind; every route is scoped by it. */
    protected final String kind;
    /** Consecutive discovery failures (timeout, connection refused, daemon
     *  restart) needed before a blip counts as a real detach. One dropped
     *  poll must not wipe the cache and blank the panel. */
    private final int discoveryFailureThreshold;
    /** Re-resolved on discovery failure — the daemon may have restarted on a
     *  new port (see {@link #refreshBaseUrl()}). */
    private volatile String baseUrl;
    private final Supplier<String> baseUrlSupplier;
    private final String projectCwd;
    private final Duration pollInterval;
    private volatile Duration pendingTimeout = PENDING_TIMEOUT;

    protected final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2)).build();
    /** Short, non-blocking polls + reconnect scheduling only. */
    private final ScheduledExecutorService exec = Executors.newScheduledThreadPool(2);
    /** The blocking SSE stream lives here, never on {@link #exec}, so a stream
     *  that blocks for its whole lifetime (or stalls) can't starve discovery /
     *  liveness polling. Cached so a session switch never wedges behind a
     *  not-yet-closed prior stream. */
    private final ExecutorService sseExec;
    /** Single-flight guard for the SSE stream. Every openSse bumps it; a stream
     *  whose generation is stale ignores its events and never reconnects, so a
     *  reconnect or session switch can't leave two live streams writing the
     *  cache. */
    private final AtomicLong sseGen = new AtomicLong();
    private final AtomicLong submitSeq = new AtomicLong();
    /** Guards the state check-and-set so two threads can't both pass the guard
     *  and drop/duplicate a transition. */
    private final Object stateLock = new Object();
    private final List<L> listeners = new CopyOnWriteArrayList<>();
    private final Map<String, T> threads = new ConcurrentHashMap<>();
    /** Bumped on every cache mutation so consumers (e.g. the gutter index) can
     *  memoize against a cheap version stamp instead of rebuilding each paint. */
    private final AtomicLong cacheVersion = new AtomicLong();
    /** Every anchor's version as the last bulk fetch returned it, including
     *  threads with no agent reply yet. A thread-changed frame at or below it
     *  names a change that fetch already holds — see {@link #handleSseEvent}. */
    private final Map<String, Integer> fetchedThreadVersions = new ConcurrentHashMap<>();
    /** Anchors with an in-flight Claude reply (post-submit, pre-SSE-confirmation),
     *  mapped to the submit token that set them. A later submit on the same
     *  anchor supersedes the token, so a stale failure or timeout can't clear
     *  a newer in-flight reply's spinner. */
    private final Map<String, Long> pending = new ConcurrentHashMap<>();

    private volatile boolean closed = false;
    /** One-way latch: once the daemon says the attached session is ENDED, the
     *  panel freezes read-only. Reset only when a different session attaches
     *  or the client fully detaches. A returning heartbeat never un-freezes it. */
    private volatile boolean endedLatched = false;
    private volatile State state = State.DORMANT;
    private volatile S current = null;
    private volatile Future<?> sseTask = null;
    private volatile ScheduledFuture<?> discoverTask = null;
    /** The live SSE connection handle, so teardown paths can actually close the
     *  stream (the daemon sees EOF) instead of only cancelling the worker's join. */
    private volatile SseClient.Connection sseConnection = null;
    private volatile int discoveryFailures = 0;

    /**
     * @param baseUrlSupplier resolves the daemon's base URL; re-invoked after
     *        a failed discovery poll so a daemon restart on a new port is
     *        picked up without an IDE restart.
     */
    protected DaemonSessionClient(String kind, int discoveryFailureThreshold, String sseThreadName,
                                  Supplier<String> baseUrlSupplier, String projectCwd,
                                  Duration pollInterval) {
        this.kind = kind;
        this.discoveryFailureThreshold = discoveryFailureThreshold;
        this.baseUrlSupplier = baseUrlSupplier;
        this.baseUrl = baseUrlSupplier.get();
        this.projectCwd = projectCwd;
        this.pollInterval = pollInterval;
        this.sseExec = Executors.newCachedThreadPool(r -> {
            Thread t = new Thread(r, sseThreadName);
            t.setDaemon(true);
            return t;
        });
    }

    // --- what each skill supplies ---

    /** Builds the skill's session record from one {@code /api/sessions} row. */
    protected abstract S toSession(JsonObject row);

    /** Builds the skill's thread record from a thread that has an agent reply. */
    protected abstract T toThread(BulkThread thread);

    protected abstract void notifyThreadChanged(L listener, String anchor, T thread);

    protected abstract void notifyThreadDeleted(L listener, String anchor);

    /** The command that re-arms a session, named when a submit is refused. */
    protected abstract String resumeCommand();

    /** Shown when the thread seed gives up after its retries. */
    protected abstract String threadSeedWarning();

    /** Clears the skill's own per-session state; runs on attach and detach. */
    protected void resetSession() {}

    /** Runs after listeners heard {@code onDetached}. */
    protected void afterDetach() {}

    /** Runs on the SSE worker on every (re)connect, before the thread seed. */
    protected void beforeSeed(String sid, long gen) {}

    /** Runs after a thread seed succeeded for {@code gen}. */
    protected void afterSeed(long gen) {}

    /** Sees each {@code /poll} body of a session that is not ended. */
    protected void onPolled(String sid, JsonObject poll) {}

    /** Sees each SSE frame the lifecycle itself does not handle. */
    protected void onStreamEvent(String sid, String name, JsonObject data, long gen) {}

    // --- public surface ---

    public void start() {
        discoverTask = exec.scheduleWithFixedDelay(this::pollDiscover,
            0, pollInterval.toMillis(), TimeUnit.MILLISECONDS);
    }

    /** Terminal: the client never restarts after this. */
    public void stop() {
        closed = true;
        sseGen.incrementAndGet();
        if (discoverTask != null) discoverTask.cancel(true);
        cancelSse();
        exec.shutdownNow();
        sseExec.shutdownNow();
        setState(State.DORMANT);
        // Clear the listener list so nothing this client still references can
        // keep a Project reachable, even if a stray callback fires after
        // shutdown.
        listeners.clear();
    }

    /** No-op once {@link #stop()} has run, so a late registration can't
     *  re-open the retention path the listener clear in {@code stop()} closes. */
    public void addListener(L l) { if (!closed) listeners.add(l); }

    public void removeListener(L l) { listeners.remove(l); }

    public Optional<S> currentSession() { return Optional.ofNullable(current); }

    public State state() { return state; }

    /** Monotonic counter bumped on every cache mutation; use to memoize. */
    public long cacheVersion() { return cacheVersion.get(); }

    public Optional<T> threadFor(String anchor) {
        return Optional.ofNullable(threads.get(anchor));
    }

    public Map<String, T> snapshotCache() {
        return new HashMap<>(threads);
    }

    public boolean isPending(String anchor) { return pending.containsKey(anchor); }

    /** Overrides {@link #PENDING_TIMEOUT}; tests only. */
    void pendingTimeout(Duration timeout) { pendingTimeout = timeout; }

    /**
     * POST to /s/&lt;sid&gt;/api/cancel — ends the session. The daemon marks it
     * terminal; a live watcher picks up the marker and emits
     * WEBCOMPANION_CANCELLED. On success this detaches immediately rather than
     * waiting for the next discovery poll to notice the session is gone.
     */
    public CompletableFuture<Void> cancelSession() {
        S s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        HttpRequest req = request(s.sid(), "api/cancel")
            .POST(HttpRequest.BodyPublishers.noBody())
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("cancel failed: HTTP " + resp.statusCode());
                }
                handleNoSession(State.DORMANT);
            });
    }

    // --- for subclasses ---

    /** A request builder for one of the session's routes, with the contract
     *  header and the per-request timeout already set. */
    protected final HttpRequest.Builder request(String sid, String route) {
        return WebCompanionHttp.withContract(
            HttpRequest.newBuilder(WebCompanionHttp.sessionUri(baseUrl, sid, route, kind))
                .timeout(REQUEST_TIMEOUT));
    }

    /** True while {@code gen} is still the live attach and the client is open:
     *  re-check after every HTTP round trip, before touching shared state. */
    protected final boolean isCurrent(long gen) {
        return !closed && gen == sseGen.get();
    }

    protected final long currentGen() { return sseGen.get(); }

    /** Replaces the current session record if it is still {@code sid}. */
    protected final void updateCurrent(String sid, UnaryOperator<S> update) {
        S latest = current;
        if (latest != null && latest.sid().equals(sid)) current = update.apply(latest);
    }

    /** Calls every listener, isolating each: one that throws is logged and the
     *  rest are still notified. */
    protected final void fire(String what, Consumer<L> call) {
        for (L l : listeners) {
            try {
                call.accept(l);
            } catch (RuntimeException e) {
                System.err.println("[claude-ide-review] a listener threw from " + what + ", continuing: " + e);
                e.printStackTrace();
            }
        }
    }

    /** Fires onWarning, but only while {@code gen} is still the current attach
     *  — a superseded generation must not warn about a session nobody is on. */
    protected final void warn(String message, long gen) {
        if (isCurrent(gen)) fire("onWarning", l -> l.onWarning(message));
    }

    /**
     * POSTs {@code {anchor, text}} to /s/&lt;sid&gt;/api/submit and marks the
     * anchor pending until its answer lands, the submit fails, or
     * {@link #PENDING_TIMEOUT} passes. Refused while the session is PAUSED or
     * ENDED: nothing would ever answer it.
     */
    protected final CompletableFuture<Void> submit(String anchor, String text) {
        S s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        if (state == State.PAUSED || state == State.ENDED) {
            return CompletableFuture.failedFuture(new IllegalStateException(
                "Claude session is gone — re-run " + resumeCommand() + " to resume"));
        }
        long token = submitSeq.incrementAndGet();
        markPending(anchor, token);
        Map<String, String> payload = new LinkedHashMap<>();
        payload.put("anchor", anchor);
        payload.put("text", text);
        HttpRequest req = request(s.sid(), "api/submit")
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(payload)))
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

    // --- pending ---

    /** Mark an anchor pending under a submit token; notify only on the
     *  not-pending → pending transition. Arms a timeout that clears the
     *  pending state if no answer ever lands — token-guarded, so a newer
     *  submit on the same anchor keeps its own spinner and its own clock. */
    private void markPending(String anchor, long token) {
        if (pending.put(anchor, token) == null) {
            fire("onPendingChanged", l -> l.onPendingChanged(anchor, true));
        }
        if (exec.isShutdown()) return;
        try {
            exec.schedule(() -> clearPendingIfToken(anchor, token),
                pendingTimeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (RejectedExecutionException e) {
            // stop() raced us — the pending map dies with the client anyway.
        }
    }

    /** Clear pending regardless of token — used when the reply is confirmed or
     *  the session freezes/pauses. */
    private void clearPending(String anchor) {
        if (pending.remove(anchor) != null) {
            fire("onPendingChanged", l -> l.onPendingChanged(anchor, false));
        }
    }

    /** Clear pending only if this exact submit is still the latest one — a
     *  newer submit on the same anchor must keep its spinner. */
    private void clearPendingIfToken(String anchor, long token) {
        if (pending.remove(anchor, token)) {
            fire("onPendingChanged", l -> l.onPendingChanged(anchor, false));
        }
    }

    private void clearAllPending() {
        for (String a : new ArrayList<>(pending.keySet())) clearPending(a);
    }

    // --- discovery and liveness ---

    private void pollDiscover() {
        // This runs under scheduleWithFixedDelay: if ANY exception escapes
        // this method, the JDK silently cancels all future executions of the
        // task — no log line, no crash, discovery is just gone until the IDE
        // restarts. Listener callbacks are isolated by fire(), but nothing
        // below may be allowed to propagate out of here either.
        try {
            pollDiscoverUnguarded();
        } catch (RuntimeException e) {
            System.err.println("[claude-ide-review] pollDiscover(" + kind
                + ") failed; will retry on the next tick: " + e);
            e.printStackTrace();
        }
    }

    /**
     * A single failed {@link #fetchNewestSession()} does not detach — it takes
     * {@link #discoveryFailureThreshold} consecutive failures. Detaching on one
     * blip would wipe the cache (and, for a walkthrough, reset the tour to
     * step 1 when the next poll re-attaches). A session that is genuinely gone
     * (the daemon answers with an empty list, or /poll reports it ended) is
     * unaffected by this and still detaches or freezes on the first
     * observation.
     */
    private void pollDiscoverUnguarded() {
        S found;
        try {
            found = fetchNewestSession();
        } catch (Exception e) {
            // Daemon unreachable. It may have restarted on a new port —
            // re-read its config (cheap file read) before the next try.
            refreshBaseUrl();
            discoveryFailures++;
            // A frozen (ENDED) panel is never wiped by unreachability at all.
            if (!endedLatched && discoveryFailures >= discoveryFailureThreshold) {
                handleNoSession(State.OFFLINE);
            }
            return;
        }
        discoveryFailures = 0;
        if (endedLatched) {
            // Frozen read-only. The ONLY thing that replaces a frozen panel is
            // a genuinely new, LIVE session (a different sid). Never fall back
            // to a zombie, never clear on our own.
            if (found != null && (current == null || !current.sid().equals(found.sid()))) {
                attach(found);
            }
            return;
        }
        if (found == null) {
            // Discovery has nothing for this cwd. If we were attached, the
            // session most likely just ended — freeze it on its own content
            // rather than blanking the panel. Only blank when the session is
            // genuinely gone (poll fails / not ended).
            if (current != null) {
                pollLiveness(current.sid());
                if (!endedLatched) handleNoSession(State.DORMANT);
            } else {
                handleNoSession(State.DORMANT);
            }
            return;
        }
        if (current == null || !current.sid().equals(found.sid())) {
            attach(found);
        }
        pollLiveness(found.sid());
    }

    /**
     * The newest session of this client's kind for the project, or null when
     * the daemon answered 200 with none. A non-200 is a failure, not "no
     * session" — it throws, so it counts against the discovery threshold like
     * a socket failure would. The query already filters by kind; rows of any
     * other kind are skipped anyway, and the greatest sid wins rather than
     * array[0]: the array is neither sorted nor guaranteed to exclude terminal
     * sessions, and a sid's leading yyMMdd-HHmmss makes string order
     * chronological.
     */
    private S fetchNewestSession() throws IOException, InterruptedException {
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                WebCompanionHttp.sessionsUri(baseUrl, kind, projectCwd))
            .timeout(REQUEST_TIMEOUT).GET()).build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) throw new IOException("HTTP " + resp.statusCode());
        JsonElement root = JsonParser.parseString(resp.body());
        if (!root.isJsonArray()) return null;
        JsonObject newest = null;
        for (JsonElement el : root.getAsJsonArray()) {
            if (!el.isJsonObject()) continue;
            JsonObject o = el.getAsJsonObject();
            if (!kind.equals(str(o, "kind"))) continue;
            if (newest == null || str(o, "sid").compareTo(str(newest, "sid")) > 0) newest = o;
        }
        return newest == null ? null : toSession(newest);
    }

    /** Re-resolve the daemon URL after a failed discovery poll: it may have
     *  restarted on a new port. Cheap (one file read behind the supplier),
     *  so every failed poll re-checks. */
    private void refreshBaseUrl() {
        try {
            String next = baseUrlSupplier.get();
            if (next != null && !next.equals(baseUrl)) baseUrl = next;
        } catch (RuntimeException e) {
            // Keep the current URL; the next failed poll retries the read.
        }
    }

    /**
     * Reachability of the daemon does NOT mean the Claude session is alive —
     * the daemon outlives every session. The only liveness signal is the
     * watcher heartbeat, which the session rewrites every ~1s. {@code
     * finished}/{@code cancelled} are authoritative marker-file facts (one poll
     * is proof, latch immediately); a heartbeat older than {@link
     * #REAP_AFTER_MS} is this client's own hard cutoff; one older than {@link
     * #STALE_AFTER} pauses the session until the watcher returns.
     */
    private void pollLiveness(String sid) {
        if (endedLatched) return; // frozen; nothing un-freezes the same sid
        JsonObject poll;
        try {
            HttpRequest req = request(sid, "poll").GET().build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) return;
            poll = JsonParser.parseString(resp.body()).getAsJsonObject();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        } catch (Exception e) {
            return; // transient — leave state as-is, the next poll retries
        }
        long seenAt = num(poll, "watcher_seen_at", 0);
        long ageMs = seenAt > 0 ? System.currentTimeMillis() - seenAt * 1000 : -1;
        boolean ended = flag(poll, "finished") || flag(poll, "cancelled")
            || (seenAt > 0 && ageMs > REAP_AFTER_MS);
        if (ended) { latchEnded(); return; }
        onPolled(sid, poll);
        // No heartbeat written yet (session just armed) → not dead, leave alone.
        if (seenAt <= 0) return;
        if (ageMs > STALE_AFTER.toMillis()) {
            if (state != State.PAUSED) {
                // Clear pending so spinners recover — no answer is coming
                // until the watcher returns.
                clearAllPending();
                setState(State.PAUSED);
            }
        } else if (state == State.PAUSED) {
            // The watcher came back (the user re-armed the session).
            setState(State.ACTIVE);
        }
    }

    /** Freeze the current session read-only. One-way: only attach() clears it. */
    private void latchEnded() {
        endedLatched = true;
        sseGen.incrementAndGet();
        clearAllPending();
        cancelSse();
        setState(State.ENDED);
    }

    /** @param finalState DORMANT when the daemon answered and has no session;
     *                    OFFLINE when the daemon itself is unreachable. */
    private void handleNoSession(State finalState) {
        endedLatched = false;
        if (current != null) {
            current = null;
            threads.clear();
            fetchedThreadVersions.clear();
            cacheVersion.incrementAndGet();
            pending.clear();
            resetSession();
            sseGen.incrementAndGet();
            cancelSse();
            fire("onDetached", SessionListener::onDetached);
            afterDetach();
        }
        setState(finalState);
    }

    private void attach(S s) {
        endedLatched = false;
        current = s;
        // Switching sessions: drop everything cached for the previous sid, or
        // the panel keeps showing its dead threads.
        threads.clear();
        fetchedThreadVersions.clear();
        cacheVersion.incrementAndGet();
        pending.clear();
        resetSession();
        setState(State.CONNECTING);
        fire("onAttached", l -> l.onAttached(s));
        // No I/O before openSse(): it is what bumps the generation and closes
        // the previous session's stream, so a blocking fetch here would leave
        // the old stream's frames passing the generation check meanwhile.
        // Per-session fetches belong in beforeSeed(), which runs after it.
        openSse(s.sid());
    }

    // --- threads ---

    /**
     * Seed (or re-seed) the thread cache from the bulk threads route. Retries
     * a few times so a transient blip on attach doesn't leave the panel empty
     * until the next SSE event; warns the listeners when it gives up rather
     * than leaving an empty "live" panel that reads as "no answers".
     */
    private void seedThreads(String sid, long gen) {
        for (int attempt = 0; attempt < 3 && isCurrent(gen); attempt++) {
            try {
                applyThreads(fetchThreads(sid), gen);
                afterSeed(gen);
                return;
            } catch (IOException | RuntimeException e) {
                // Transient failure or a malformed body — the retry loop is the handling.
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        warn(threadSeedWarning(), gen);
    }

    /** GET {@code /s/<sid>/threads} (bulk shape: {@code {anchor: {anchor,
     *  version, messages: [{text, role, ts}], title?, anchor_text?}}}). */
    private Map<String, BulkThread> fetchThreads(String sid) throws IOException, InterruptedException {
        HttpRequest req = request(sid, "threads").GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) throw new IOException("HTTP " + resp.statusCode());
        JsonObject root = JsonParser.parseString(resp.body()).getAsJsonObject();
        Map<String, BulkThread> out = new LinkedHashMap<>();
        for (var e : root.entrySet()) {
            if (e.getValue().isJsonObject()) out.put(e.getKey(), deriveThread(e.getValue().getAsJsonObject()));
        }
        return out;
    }

    private static BulkThread deriveThread(JsonObject t) {
        String synthesis = null;
        String question = "";
        long updatedAt = 0L;
        JsonElement messages = t.get("messages");
        if (messages != null && messages.isJsonArray()) {
            for (JsonElement el : messages.getAsJsonArray()) {
                if (!el.isJsonObject()) continue;
                JsonObject m = el.getAsJsonObject();
                String role = str(m, "role");
                if ("agent".equals(role)) {
                    synthesis = str(m, "text");
                    updatedAt = num(m, "ts", 0L);
                } else if ("user".equals(role)) {
                    question = str(m, "text");
                }
            }
        }
        return new BulkThread(synthesis, (int) num(t, "version", 0), str(t, "anchor_text"),
            str(t, "title"), question, updatedAt);
    }

    /** Writes fetched threads into the cache — but only while {@code gen} is
     *  still the current attach, re-checked before every mutation: a session
     *  switch during the HTTP call must not write the old session's threads
     *  into the new session's cache. Unchanged threads are skipped, so a
     *  re-seed on reconnect doesn't churn listeners. */
    private void applyThreads(Map<String, BulkThread> fetched, long gen) {
        for (var e : fetched.entrySet()) {
            if (!isCurrent(gen)) return; // superseded mid-apply
            String anchor = e.getKey();
            BulkThread bulk = e.getValue();
            fetchedThreadVersions.put(anchor, bulk.version());
            if (bulk.synthesis() == null) continue; // no agent reply yet
            T incoming = toThread(bulk);
            T existing = threads.get(anchor);
            if (existing != null
                    && existing.synthesis().equals(incoming.synthesis())
                    && existing.version() == incoming.version()) {
                continue;
            }
            threads.put(anchor, incoming);
            cacheVersion.incrementAndGet();
            // A version bump with identical text is still an answer (a
            // metadata-only update): pending must clear and listeners must
            // repaint, or the spinner spins forever on a deduped reply.
            clearPending(anchor);
            fire("onThreadChanged", l -> notifyThreadChanged(l, anchor, incoming));
        }
    }

    // --- SSE ---

    /**
     * Cancels the SSE worker task AND closes the underlying stream.
     * {@code sseTask.cancel(true)} alone only interrupts the worker, which is
     * parked in {@code join()} on the stream; the TCP connection and the
     * HttpClient's body-pump thread stay alive until the daemon hangs up.
     * Closing the {@link SseClient.Connection} cancels the body subscription,
     * so the daemon sees EOF immediately and everything behind the subscriber
     * (listeners, the project service, the Project) is released.
     */
    private void cancelSse() {
        if (sseTask != null) { sseTask.cancel(true); sseTask = null; }
        SseClient.Connection conn = sseConnection;
        if (conn != null) conn.close();
    }

    private void openSse(String sid) {
        if (closed || sseExec.isShutdown()) return;
        long gen = sseGen.incrementAndGet();
        cancelSse();
        try {
            sseTask = sseExec.submit(() -> runSse(sid, gen));
        } catch (RejectedExecutionException e) {
            // stop() raced us between the guard and the submit — nothing to do.
        }
    }

    /** The blocking stream body. Runs on {@link #sseExec}. Only the current
     *  generation acts on events / reconnects; a superseded stream is inert. */
    private void runSse(String sid, long gen) {
        beforeSeed(sid, gen);
        if (!isCurrent(gen)) return;
        // Seed on every (re)connect: covers a failed initial seed and an outage
        // where SSE events were missed while disconnected.
        seedThreads(sid, gen);
        if (!isCurrent(gen)) return;
        // Respect the precedence ENDED > PAUSED > DISCONNECTED > ACTIVE. A live
        // stream says nothing about whether the watcher is alive, so connecting
        // must not clear PAUSED — only the liveness poll owns that transition,
        // and it restores ACTIVE once the heartbeat is fresh again. Otherwise a
        // reconnect revives a session nothing will answer.
        if (!endedLatched && state != State.PAUSED) setState(State.ACTIVE);
        URI uri = WebCompanionHttp.sessionUri(baseUrl, sid, "stream", kind);
        SseClient.Connection conn = SseClient.connect(http, uri,
            ev -> handleSseEvent(sid, ev, gen),
            t -> { if (gen == sseGen.get() && !endedLatched && state == State.ACTIVE)
                       setState(State.DISCONNECTED); });
        sseConnection = conn;
        // A concurrent cancelSse() that ran between connect() returning and the
        // assignment above saw the stale field and couldn't close THIS stream.
        // Re-check now that it's published.
        if (!isCurrent(gen)) conn.close();
        try {
            conn.done().join();
        } catch (RuntimeException e) {
            // Cancelled, interrupted, or the stream failed — the single
            // reconnect guard below decides what happens next.
        } finally {
            // Only clear it if it's still ours — a newer openSse() may have
            // already replaced (and closed) it.
            //noinspection ObjectEquality
            if (sseConnection == conn) sseConnection = null;
        }
        // Stream ended (clean close or post-error). This is the SOLE reconnect
        // path, so an error frame can't double-schedule.
        if (isCurrent(gen) && !endedLatched) {
            if (state == State.ACTIVE) setState(State.DISCONNECTED);
            scheduleReconnect(sid, gen);
        }
    }

    /** Reschedule a reconnect unless we're shutting down or this stream was
     *  already superseded — a stale callback must not resurrect a dead
     *  generation after stop()/detach/attach. */
    private void scheduleReconnect(String sid, long gen) {
        if (!isCurrent(gen) || exec.isShutdown()) return;
        try {
            exec.schedule(() -> { if (isCurrent(gen)) openSse(sid); },
                RECONNECT_DELAY_MS, TimeUnit.MILLISECONDS);
        } catch (RejectedExecutionException e) {
            // stop() raced us between the guard and the schedule — nothing to do.
        }
    }

    /**
     * Applies one SSE frame. The daemon's fixed vocabulary: {@code
     * session-ended}, {@code thread-changed} / {@code thread-deleted}
     * ({anchor, version}), {@code item-changed} ({anchor, version}), plus
     * {@code connected}/{@code heartbeat}/{@code event-acked}. On every
     * connect it first replays one {@code "initial": true} frame per item and
     * per thread, echoing the versions a client's own first GET already saw.
     */
    private void handleSseEvent(String sid, SseClient.Event e, long gen) {
        JsonObject data;
        try {
            data = JsonParser.parseString(e.data()).getAsJsonObject();
        } catch (RuntimeException ex) {
            return; // a frame with no JSON object body — nothing to apply
        }
        if (!isCurrent(gen)) return; // superseded stream
        String name = e.name();
        if ("session-ended".equals(name)) {
            // Sent only when a finished/cancelled marker exists — the
            // authoritative end, so it latches at once instead of reconnecting
            // every 2s until a poll notices. Hop to the polling pool:
            // latchEnded() closes the very stream this callback runs inside.
            try {
                exec.execute(this::latchEnded);
            } catch (RejectedExecutionException ex) {
                // stop() raced us — the session is going away anyway.
            }
            return;
        }
        if ("thread-deleted".equals(name)) {
            String anchor = str(data, "anchor");
            if (anchor.isEmpty()) return;
            fetchedThreadVersions.remove(anchor);
            threads.remove(anchor);
            cacheVersion.incrementAndGet();
            clearPending(anchor);
            fire("onThreadDeleted", l -> notifyThreadDeleted(l, anchor));
            return;
        }
        if (!"thread-changed".equals(name)) {
            onStreamEvent(sid, name, data, gen);
            return;
        }
        String anchor = str(data, "anchor");
        if (anchor.isEmpty()) return;
        // The frame carries only {anchor, version[, initial]}; learning the
        // rest means re-fetching the bulk route and applying every thread in
        // it. Skip the fetch when an earlier one already returned this
        // version or newer. That covers the connect-time replay (the seed has
        // just fetched every thread at exactly those versions — one fetch per
        // replayed frame used to make every connect N+1 bulk fetches) and a
        // burst of frames queued behind one fetch, which already holds them
        // all. A replayed frame newer than the seed is a change that landed
        // between the seed and the stream opening, and is fetched.
        long version = num(data, "version", -1);
        Integer fetched = fetchedThreadVersions.get(anchor);
        if (fetched != null && version >= 0 && fetched >= version) return;
        try {
            Map<String, BulkThread> threadsNow = fetchThreads(sid);
            // Re-check AFTER the round trip, BEFORE touching the cache: a
            // session switch that lands while this GET is in flight must not
            // let the superseded session's response into the new cache.
            if (!isCurrent(gen)) return;
            applyThreads(threadsNow, gen);
        } catch (IOException | RuntimeException ex) {
            // Transient failure — the next thread-changed frame, or the next
            // reconnect's seed, retries.
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private void setState(State s) {
        synchronized (stateLock) {
            if (state == s) return;
            state = s;
        }
        // Notify outside the lock; listeners bridge to the EDT and re-read
        // state() there, so they always converge on the latest value.
        fire("onStateChanged(" + s + ")", l -> l.onStateChanged(s));
    }
}
