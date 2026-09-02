package com.petros.ireview;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
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
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Talks to the webcompanion daemon: discovers a session by cwd, loads the
 * {@code __steps__} item off its bulk-items route, opens an SSE stream for
 * per-step threads, and posts questions. Every request carries
 * {@code kind=walkthrough}, since every daemon route is kind-scoped.
 *
 * <p>Same lifecycle model as {@link ReviewSessionClient} — DORMANT → CONNECTING →
 * ACTIVE, with PAUSED when the watcher heartbeat goes stale and ENDED as a
 * one-way latch once the server reports the session terminal. Listeners fire on
 * the SSE / poll threads; bridge to the EDT in UI code.
 */
public final class WalkthroughSessionClient {

    public record SessionInfo(String sid, String title) {}
    public record ThreadState(String synthesis, int version, String title, String question) {}

    public enum State { DORMANT, CONNECTING, ACTIVE, DISCONNECTED, PAUSED, ENDED }

    public interface Listener {
        default void onAttached(SessionInfo info) {}
        default void onDetached() {}
        default void onStepsChanged(WalkthroughDoc doc) {}
        default void onThreadChanged(String anchor, ThreadState thread) {}
        default void onPendingChanged(String anchor, boolean pending) {}
        default void onStateChanged(State state) {}
        /** A non-fatal problem worth surfacing to the user (e.g. the steps or
         *  thread seed gave up after retries and the tour may be incomplete).
         *  Mirrors {@link ReviewSessionClient.Listener#onWarning} — without it
         *  an exhausted seed left an empty "live" panel that read as "Claude
         *  produced no steps". */
        default void onWarning(String message) {}
    }

    private static final Duration STALE_AFTER = Duration.ofSeconds(15);
    /** Hard end-of-life cutoff on watcher-heartbeat age, distinct from the soft
     *  {@link #STALE_AFTER}-driven PAUSED state above. The daemon's poll has no
     *  equivalent of this today (no default retention/expiry sweep exists yet —
     *  a separate, not-yet-built initiative), so this reproduces client-side the
     *  value the old per-skill server used to enforce server-side:
     *  {@code skills/_shared/web_companion/server.py}'s {@code REAP_AFTER}
     *  (180s) — a file this migration deletes. */
    private static final long REAP_AFTER_MS = Duration.ofSeconds(180).toMillis();
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);
    private static final com.google.gson.Gson GSON = new com.google.gson.Gson();
    /**
     * Consecutive {@link #fetchNewestSession()} failures (timeout, connection
     * refused, server restart) required before a discovery blip is treated as
     * a real detach. One dropped poll must not reset an in-progress tour —
     * see {@link #pollDiscover()}.
     */
    private static final int DISCOVERY_FAILURE_THRESHOLD = 2;

    /** Re-resolved on discovery failure — the server may have restarted on a
     *  new port and rewritten server.json (see {@link #refreshBaseUrl()}). */
    private volatile String baseUrl;
    private final java.util.function.Supplier<String> baseUrlSupplier;
    private final String projectCwd;
    private final Duration pollInterval;

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2)).build();
    private final ScheduledExecutorService exec = Executors.newScheduledThreadPool(2);
    private final ExecutorService sseExec = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "walkthrough-sse");
        t.setDaemon(true);
        return t;
    });

    private final AtomicLong sseGen = new AtomicLong();
    private final AtomicLong submitSeq = new AtomicLong();
    private final Object stateLock = new Object();
    private final List<Listener> listeners = new CopyOnWriteArrayList<>();
    private final Map<String, ThreadState> threads = new ConcurrentHashMap<>();
    private final Map<String, Long> pending = new ConcurrentHashMap<>();
    private final AtomicReference<WalkthroughDoc> doc = new AtomicReference<>(WalkthroughDoc.EMPTY);
    /** The {@code __steps__} item's version as of the last successful {@link
     *  #loadSteps} call — set only when the daemon reports one, so {@link
     *  #pollLiveness} can compare it against a poll's {@code items.__steps__}
     *  version instead of the old {@code steps_generated_at}. */
    private volatile int lastStepsVersion = 0;

    private volatile boolean closed = false;
    private volatile boolean endedLatched = false;
    private volatile State state = State.DORMANT;
    private volatile SessionInfo current = null;
    private volatile Future<?> sseTask = null;
    private volatile ScheduledFuture<?> discoverTask = null;
    /** The live SSE connection handle, so teardown paths can actually close the
     *  stream (server sees EOF) instead of only unblocking the worker's join(). */
    private volatile SseClient.Connection sseConnection = null;
    private volatile int discoveryFailures = 0;

    public WalkthroughSessionClient(String baseUrl, String projectCwd, Duration pollInterval) {
        this(() -> baseUrl, projectCwd, pollInterval);
    }

    /**
     * @param baseUrlSupplier resolves the server's base URL; re-invoked after a
     *        failed discovery poll so a server restart on a new port (which
     *        rewrites server.json) is picked up without an IDE restart.
     */
    public WalkthroughSessionClient(java.util.function.Supplier<String> baseUrlSupplier,
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
        // stop() is terminal (see addListener's closed check below and
        // WalkthroughService#dispose, its only caller): clear the listener list
        // so nothing this client still references can keep a Project reachable,
        // even if some stray callback fires after shutdown.
        listeners.clear();
    }

    /**
     * Cancels the current SSE worker's task AND closes the underlying stream.
     * {@code sseTask.cancel(true)} alone only interrupts the worker thread;
     * the thread is parked in {@code join()} on the SSE stream, and the TCP
     * connection plus the HttpClient's body-pump thread stay alive until the
     * server happens to hang up. Closing the {@link SseClient.Connection}
     * closes the lines stream, which cancels the HTTP body subscription — the
     * server sees EOF immediately and the whole object graph behind the
     * subscriber (listeners, the project service, the Project) is released.
     * Used on every teardown path: final shutdown ({@link #stop()}), the
     * ENDED latch ({@link #latchEnded()}), detach ({@link #handleNoSession()}),
     * and reconnect ({@link #openSse(String)}).
     */
    private void cancelSse() {
        if (sseTask != null) { sseTask.cancel(true); sseTask = null; }
        SseClient.Connection conn = sseConnection;
        if (conn != null) conn.close();
    }

    /** No-op once {@link #stop()} has run — belt-and-braces alongside the listener clear
     *  in {@code stop()} so a late/misplaced registration can't re-open the retention path
     *  Finding 3 closes. Nothing in this codebase currently calls addListener after stop(),
     *  but the client offers no other way to enforce that invariant. */
    public void addListener(Listener l) { if (!closed) listeners.add(l); }

    public void removeListener(Listener l) { listeners.remove(l); }

    public Optional<SessionInfo> currentSession() { return Optional.ofNullable(current); }

    public State state() { return state; }

    public WalkthroughDoc doc() { return doc.get(); }

    public Optional<ThreadState> threadFor(String anchor) {
        return Optional.ofNullable(threads.get(anchor));
    }

    public boolean isPending(String anchor) { return pending.containsKey(anchor); }

    /** POST a question on a step to /s/&lt;sid&gt;/api/submit. */
    public CompletableFuture<Void> postAsk(int stepId, String text) {
        SessionInfo s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        if (state == State.PAUSED || state == State.ENDED) {
            return CompletableFuture.failedFuture(new IllegalStateException(
                "Claude session is gone — re-run /walkthrough to resume"));
        }
        String anchor = "step:" + stepId;
        long token = submitSeq.incrementAndGet();
        markPending(anchor, token);
        Map<String, String> payload = new java.util.LinkedHashMap<>();
        payload.put("anchor", anchor);
        payload.put("text", text);
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + s.sid() + "/api/submit?kind=walkthrough"))
            .header("Content-Type", "application/json")
            .timeout(REQUEST_TIMEOUT)
            .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(payload))))
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .whenComplete((resp, err) -> {
                if (err != null || (resp != null && resp.statusCode() / 100 != 2)) {
                    clearPendingIfToken(anchor, token);
                }
            })
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("ask failed: HTTP " + resp.statusCode());
                }
            });
    }

    /** POST to /s/&lt;sid&gt;/api/cancel — ends the walkthrough. */
    public CompletableFuture<Void> cancelSession() {
        SessionInfo s = current;
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + s.sid() + "/api/cancel?kind=walkthrough"))
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

    // --- internal ---

    private void markPending(String anchor, long token) {
        if (pending.put(anchor, token) == null) {
            for (Listener l : listeners) l.onPendingChanged(anchor, true);
        }
    }

    private void clearPending(String anchor) {
        if (pending.remove(anchor) != null) {
            for (Listener l : listeners) l.onPendingChanged(anchor, false);
        }
    }

    private void clearPendingIfToken(String anchor, long token) {
        if (pending.remove(anchor, token)) {
            for (Listener l : listeners) l.onPendingChanged(anchor, false);
        }
    }

    /**
     * A single failed {@link #fetchNewestSession()} (timeout, momentary
     * connection refusal, server restart) does not detach — it takes
     * {@link #DISCOVERY_FAILURE_THRESHOLD} consecutive failures. Detaching on
     * one blip would clear {@link #doc} to EMPTY; the next successful poll
     * would then publish a fresh (non-EMPTY) doc past the unchanged-guard in
     * {@link #loadSteps}, resetting the controller's step index to 0 and
     * yanking the editor for no user-visible reason. A session that is
     * genuinely gone (the server successfully answers with an empty list, or
     * pollLiveness's /poll reports ended) is unaffected by this and still
     * detaches on the first observation — see the {@code found == null}
     * branch below and {@link #latchEnded()}.
     */
    private void pollDiscover() {
        SessionInfo found;
        try {
            found = fetchNewestSession();
        } catch (Exception e) {
            // Server unreachable. It may have restarted on a new port —
            // re-resolve server.json (cheap file read) before the next try.
            refreshBaseUrl();
            discoveryFailures++;
            if (!endedLatched && discoveryFailures >= DISCOVERY_FAILURE_THRESHOLD) handleNoSession();
            return;
        }
        discoveryFailures = 0;
        if (endedLatched) {
            if (found != null && (current == null || !current.sid().equals(found.sid()))) attach(found);
            return;
        }
        if (found == null) {
            if (current != null) {
                pollLiveness(current.sid());
                if (!endedLatched) handleNoSession();
            } else {
                handleNoSession();
            }
            return;
        }
        if (current == null || !current.sid().equals(found.sid())) attach(found);
        pollLiveness(found.sid());
    }

    private SessionInfo fetchNewestSession() throws Exception {
        String url = baseUrl + "/api/sessions?kind=walkthrough&cwd="
            + URLEncoder.encode(projectCwd, StandardCharsets.UTF_8);
        HttpRequest req = WebCompanionHttp.withContract(
                HttpRequest.newBuilder(URI.create(url)).timeout(REQUEST_TIMEOUT).GET()).build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        // A non-200 (transient 500/503 while the server restarts or the registry is being
        // rewritten) is a failure, not "no session" — it must count against
        // DISCOVERY_FAILURE_THRESHOLD in pollDiscover's catch block like a socket failure
        // would. Returning null here would instead take the found==null branch and detach
        // on the very first blip. A null return is reserved strictly for "the server
        // answered 200 and the list is empty".
        if (resp.statusCode() != 200) throw new IOException("HTTP " + resp.statusCode());
        var root = JsonParser.parseString(resp.body());
        if (!root.isJsonArray()) return null;
        // Belt-and-braces: re-check "kind" ourselves even though the query already
        // filtered — and pick the lexicographically greatest "sid", not array[0]:
        // Task 1's supersede=True guarantees the newest sid for this (kind, cwd) is
        // the only one still live, but the array is neither sorted nor guaranteed to
        // exclude terminal sessions.
        SessionInfo newest = null;
        for (var el : root.getAsJsonArray()) {
            JsonObject o = el.getAsJsonObject();
            if (!"walkthrough".equals(str(o, "kind"))) continue;
            String sid = str(o, "sid");
            if (newest == null || sid.compareTo(newest.sid()) > 0) {
                newest = new SessionInfo(sid, str(o, "title"));
            }
        }
        return newest;
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

    /**
     * Polls liveness AND — the cheap fix for the "tour invisible for up to
     * 30s" gap — steps freshness. {@code /poll} returns the {@code __steps__}
     * item's version (under {@code items}) on every call; nothing on the
     * server wakes the SSE stream the moment Claude writes a fresh steps
     * document (only an {@code item-changed} frame does, fired on submit/
     * delete), so without this the IDE would only learn about new steps from
     * the next SSE event, which can lag behind the waiter's timeout. This
     * discovery loop already runs every {@code pollInterval} (~5s in
     * production), so reading the field here and reloading on change bounds
     * the delay at ~one poll interval with no new network traffic. The
     * reload goes through {@link #loadSteps}, using the *current* SSE
     * generation read fresh right before the call — that keeps the same
     * stale-publish guard the SSE path relies on: if a reconnect bumps the
     * generation while this call is in flight, loadSteps's loop condition
     * sees the mismatch and aborts without publishing. Publishing twice
     * (once from here, once from a concurrent SSE item-changed) is harmless
     * — loadSteps no-ops when generatedTs and step count already match.
     */
    private void pollLiveness(String sid) {
        if (endedLatched) return;
        long seenAt;
        boolean finished;
        boolean cancelled;
        Integer stepsVersion;
        try {
            HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                    URI.create(baseUrl + "/s/" + sid + "/poll?kind=walkthrough"))
                .timeout(REQUEST_TIMEOUT).GET()).build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) return;
            JsonObject o = JsonParser.parseString(resp.body()).getAsJsonObject();
            seenAt = o.has("watcher_seen_at") && !o.get("watcher_seen_at").isJsonNull()
                ? o.get("watcher_seen_at").getAsLong() : 0;
            finished = o.has("finished") && !o.get("finished").isJsonNull()
                && o.get("finished").getAsBoolean();
            cancelled = o.has("cancelled") && !o.get("cancelled").isJsonNull()
                && o.get("cancelled").getAsBoolean();
            stepsVersion = null;
            if (o.has("items") && o.get("items").isJsonObject()) {
                JsonObject items = o.getAsJsonObject("items");
                if (items.has("__steps__") && !items.get("__steps__").isJsonNull()) {
                    stepsVersion = items.get("__steps__").getAsInt();
                }
            }
        } catch (Exception e) {
            return;
        }
        long ageMs = seenAt > 0 ? System.currentTimeMillis() - seenAt * 1000 : -1;
        // finished/cancelled are the daemon's own authoritative markers; the third
        // disjunct reproduces the old server's hard REAP_AFTER cutoff — see
        // REAP_AFTER_MS's javadoc — since the daemon has no equivalent of its own.
        boolean ended = finished || cancelled || (seenAt > 0 && ageMs > REAP_AFTER_MS);
        if (ended) { latchEnded(); return; }
        // Skip the freshness reload while CONNECTING: attach() calls openSse(), whose
        // worker runs its own loadSteps() as the first thing it does, before the state
        // moves past CONNECTING. pollDiscover calls pollLiveness right after attach()
        // returns, on a different thread — without this guard both loadSteps() calls can
        // read doc as EMPTY before either has published, so the tour activates twice (two
        // openTextEditor + scrollToCaret, two full gutter repaints). Once the SSE worker's
        // initial load has run and the state has moved on, this reload is legitimate again.
        if (state != State.CONNECTING && stepsVersion != null && stepsVersion != lastStepsVersion) {
            loadSteps(sid, sseGen.get());
        }
        if (seenAt <= 0) return;
        if (ageMs > STALE_AFTER.toMillis()) {
            if (state != State.PAUSED) {
                for (String a : new java.util.ArrayList<>(pending.keySet())) clearPending(a);
                setState(State.PAUSED);
            }
        } else if (state == State.PAUSED) {
            setState(State.ACTIVE);
        }
    }

    private void latchEnded() {
        endedLatched = true;
        sseGen.incrementAndGet();
        for (String a : new java.util.ArrayList<>(pending.keySet())) clearPending(a);
        cancelSse();
        setState(State.ENDED);
    }

    private void handleNoSession() {
        endedLatched = false;
        if (current != null) {
            current = null;
            threads.clear();
            pending.clear();
            doc.set(WalkthroughDoc.EMPTY);
            lastStepsVersion = 0;
            sseGen.incrementAndGet();
            cancelSse();
            for (Listener l : listeners) l.onDetached();
            for (Listener l : listeners) l.onStepsChanged(WalkthroughDoc.EMPTY);
        }
        setState(State.DORMANT);
    }

    private void attach(SessionInfo s) {
        endedLatched = false;
        current = s;
        threads.clear();
        pending.clear();
        doc.set(WalkthroughDoc.EMPTY);
        lastStepsVersion = 0;
        setState(State.CONNECTING);
        for (Listener l : listeners) l.onAttached(s);
        openSse(s.sid());
    }

    /**
     * GET {@code __steps__} off the daemon's generic bulk-items route and
     * publish it if it actually changed. Retries transient failures up to 3x
     * with a 500ms backoff — same as {@link ReviewSessionClient
     * #seedCache} — so a blip on the initial seed doesn't leave the tour empty
     * until the next SSE event. On exhaustion it fires {@link Listener#onWarning},
     * exactly as seedCache does, rather than going quietly empty. Aborts early if the client is closed or {@code
     * gen} has been superseded by a newer attach/reconnect.
     */
    private void loadSteps(String sid, long gen) {
        for (int attempt = 0; attempt < 3 && !closed && gen == sseGen.get(); attempt++) {
            try {
                HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                        URI.create(baseUrl + "/s/" + sid + "/items?kind=walkthrough"))
                    .timeout(REQUEST_TIMEOUT).GET()).build();
                HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() == 200) {
                    // Guard before touching any shared state: a superseded session's
                    // in-flight response must not overwrite lastStepsVersion (or
                    // doc/listeners) after a newer attach()/handleNoSession() has
                    // already moved on — that reopened a narrower variant of the
                    // same stuck-empty-panel bug this method's gen check exists to
                    // prevent, caught in this phase's own fix-round re-review.
                    if (closed || gen != sseGen.get()) return;
                    JsonObject root = JsonParser.parseString(resp.body()).getAsJsonObject();
                    // Absent "__steps__" means nothing pushed yet for this session
                    // (confirmed live: a freshly-created session's /items answers
                    // "{}") — WalkthroughDoc.parse(null) already degrades that to EMPTY.
                    JsonObject stepsItem = root.has("__steps__") && root.get("__steps__").isJsonObject()
                        ? root.getAsJsonObject("__steps__") : null;
                    String body = stepsItem != null && stepsItem.has("body")
                        ? stepsItem.get("body").toString() : null;
                    WalkthroughDoc next = WalkthroughDoc.parse(body);
                    if (stepsItem != null && stepsItem.has("version")
                            && !stepsItem.get("version").isJsonNull()) {
                        lastStepsVersion = stepsItem.get("version").getAsInt();
                    }
                    WalkthroughDoc prev = doc.get();
                    if (prev.generatedTs() == next.generatedTs()
                            && prev.steps().size() == next.steps().size()) {
                        return;
                    }
                    doc.set(next);
                    for (Listener l : listeners) l.onStepsChanged(next);
                    return;
                }
            } catch (Exception ignored) {
                // Transient GET failure — the retry loop is the handling.
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        warnListeners("Couldn't load the walkthrough steps from the server — "
            + "the tour may be empty until the connection recovers.", gen);
    }

    /**
     * GET the bulk threads route and seed the thread cache. Same bounded
     * retry as {@link #loadSteps} for the same reason — a transient blip on
     * attach shouldn't leave every step's thread pane empty.
     */
    private void seedThreads(String sid, long gen) {
        for (int attempt = 0; attempt < 3 && !closed && gen == sseGen.get(); attempt++) {
            try {
                Map<String, ThreadState> fetched = deriveThreads(sid);
                if (closed || gen != sseGen.get()) return;
                for (var e : fetched.entrySet()) {
                    applyThread(e.getKey(), e.getValue());
                }
                return;
            } catch (Exception ignored) {
                // Transient GET failure — the retry loop is the handling.
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        warnListeners("Couldn't load existing threads from the walkthrough server — "
            + "answers already given may be missing until the connection recovers.", gen);
    }

    /**
     * GET {@code /s/&lt;sid&gt;/threads?kind=walkthrough} (bulk shape:
     * {@code {anchor: {anchor, version, messages: [{text, role, ts}], title}}})
     * and derive each anchor's {@link ThreadState} the same way {@code
     * skills/_shared/static/wc-threads.js}'s {@code derive()} does. A thread
     * with no {@code role == "agent"} message yet is omitted entirely —
     * matching that same {@code derive()} function's behavior — so the
     * caller's own pending-spinner state isn't overwritten with nothing.
     */
    private Map<String, ThreadState> deriveThreads(String sid) throws Exception {
        HttpRequest req = WebCompanionHttp.withContract(HttpRequest.newBuilder(
                URI.create(baseUrl + "/s/" + sid + "/threads?kind=walkthrough"))
            .timeout(REQUEST_TIMEOUT).GET()).build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) throw new IOException("HTTP " + resp.statusCode());
        JsonObject root = JsonParser.parseString(resp.body()).getAsJsonObject();
        Map<String, ThreadState> out = new java.util.LinkedHashMap<>();
        for (var e : root.entrySet()) {
            ThreadState state = toThreadState(e.getValue().getAsJsonObject());
            if (state != null) out.put(e.getKey(), state);
        }
        return out;
    }

    /** Fire onWarning, but only while this seed is still the current attach —
     *  a superseded generation must not warn about a session nobody is on. */
    private void warnListeners(String message, long gen) {
        if (closed || gen != sseGen.get()) return;
        for (Listener l : listeners) l.onWarning(message);
    }

    private void openSse(String sid) {
        if (closed || sseExec.isShutdown()) return;
        URI uri = URI.create(baseUrl + "/s/" + sid + "/stream?kind=walkthrough");
        long gen = sseGen.incrementAndGet();
        cancelSse();
        try {
            sseTask = sseExec.submit(() -> runSse(sid, uri, gen));
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // stop() raced us between the guard above and the submit — the
            // stream we would have opened has nothing left to feed.
        }
    }

    private void runSse(String sid, URI uri, long gen) {
        loadSteps(sid, gen);
        seedThreads(sid, gen);
        if (gen != sseGen.get() || closed) return;
        if (!endedLatched) setState(State.ACTIVE);
        SseClient.Connection conn = SseClient.connect(http, uri,
            ev -> { if (gen == sseGen.get()) handleSseEvent(sid, ev, gen); },
            t -> { if (gen == sseGen.get() && !endedLatched && state == State.ACTIVE)
                       setState(State.DISCONNECTED); }
        );
        sseConnection = conn;
        // A concurrent stop()/cancelSse() that ran between SseClient.connect() returning
        // and the assignment above saw the stale (pre-assignment) sseConnection — null,
        // or a previous generation's — and so could not close *this* stream. Re-check
        // now that the field is published: if the client closed or a newer attach/reconnect
        // already moved the generation on, close here instead of parking in join() forever.
        if (closed || gen != sseGen.get()) conn.close();
        try {
            conn.done().join();
        } catch (Throwable ignored) {
            // Task cancelled/interrupted, or an unexpected join failure — fall
            // through to the single reconnect guard below, which decides.
        } finally {
            // Only clear it if it's still ours — a newer openSse() may have
            // already replaced (and closed) it.
            //noinspection ObjectEquality
            if (sseConnection == conn) sseConnection = null;
        }
        if (gen == sseGen.get() && !closed && !endedLatched) {
            if (state == State.ACTIVE) setState(State.DISCONNECTED);
            scheduleReconnect(sid, gen);
        }
    }

    private void scheduleReconnect(String sid, long gen) {
        if (closed || exec.isShutdown() || gen != sseGen.get()) return;
        try {
            exec.schedule(() -> { if (gen == sseGen.get() && !closed) openSse(sid); },
                2, TimeUnit.SECONDS);
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // stop() raced us between the guard and the schedule — nothing to do.
        }
    }

    /**
     * There is no {@code steps-changed} or per-skill custom frame under the
     * daemon — only its generic {@code item-changed} ({anchor, version,
     * initial?}) and {@code thread-changed}/{@code thread-deleted} frames.
     * The JSON parse happens once here and is shared by every branch below.
     */
    private void handleSseEvent(String sid, SseClient.Event e, long gen) {
        String name = e.name();
        JsonObject data;
        try {
            data = JsonParser.parseString(e.data()).getAsJsonObject();
        } catch (Exception ex) {
            return;
        }
        if ("item-changed".equals(name)) {
            if ("__steps__".equals(str(data, "anchor"))) loadSteps(sid, gen);
            return;
        }
        String anchor = str(data, "anchor");
        if (anchor.isEmpty()) return;
        if ("thread-deleted".equals(name)) {
            threads.remove(anchor);
            clearPending(anchor);
            for (Listener l : listeners) l.onThreadChanged(anchor, null);
            return;
        }
        if (!"thread-changed".equals(name)) return;
        // The frame itself only carries {anchor, version} — re-fetch the bulk
        // shape and apply every anchor in it; applyThread's own version/
        // synthesis-equality check already no-ops anything unchanged, so this
        // is simpler and no less correct than threading the single anchor
        // through (walkthrough tours are 5-12 steps — cheap either way).
        try {
            Map<String, ThreadState> fetched = deriveThreads(sid);
            if (closed || gen != sseGen.get()) return;
            for (var entry : fetched.entrySet()) {
                applyThread(entry.getKey(), entry.getValue());
            }
        } catch (Exception ignored) {
            // Transient GET failure — the next thread-changed event or poll retries.
        }
    }

    /**
     * Converts one entry of the bulk {@code /threads} route's response
     * ({@code {anchor, version, messages: [{text, role, ts}], title}}) into a
     * {@link ThreadState}, or {@code null} if the thread has no {@code
     * role == "agent"} message yet (omitted by the caller — see {@link
     * #deriveThreads}).
     */
    private ThreadState toThreadState(JsonObject t) {
        JsonElement messagesEl = t.get("messages");
        String synthesis = null;
        String question = "";
        if (messagesEl != null && messagesEl.isJsonArray()) {
            for (JsonElement el : messagesEl.getAsJsonArray()) {
                if (!el.isJsonObject()) continue;
                JsonObject m = el.getAsJsonObject();
                String role = str(m, "role");
                if ("agent".equals(role)) synthesis = str(m, "text");
                else if ("user".equals(role)) question = str(m, "text");
            }
        }
        if (synthesis == null) return null;
        int version = t.has("version") && !t.get("version").isJsonNull()
            ? t.get("version").getAsInt() : 0;
        return new ThreadState(synthesis, version, str(t, "title"), question);
    }

    private void applyThread(String anchor, ThreadState next) {
        ThreadState existing = threads.get(anchor);
        if (existing != null && existing.version() == next.version()
                && existing.synthesis().equals(next.synthesis())) {
            return;
        }
        threads.put(anchor, next);
        clearPending(anchor);
        for (Listener l : listeners) l.onThreadChanged(anchor, next);
    }

    private void setState(State s) {
        synchronized (stateLock) {
            if (state == s) return;
            state = s;
        }
        for (Listener l : listeners) l.onStateChanged(s);
    }

    private static String str(JsonObject o, String key) {
        var v = o.get(key);
        return (v == null || v.isJsonNull()) ? "" : v.getAsString();
    }
}
