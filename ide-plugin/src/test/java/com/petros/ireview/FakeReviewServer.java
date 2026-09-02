package com.petros.ireview;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executors;

/**
 * Minimal HTTP server for tests. Lets us script /api/sessions, /threads.json,
 * and /stream responses without a real Python server.
 */
public final class FakeReviewServer implements AutoCloseable {
    private final HttpServer server;
    private final int port;
    public final List<HttpExchange> requests = new ArrayList<>();
    public final ConcurrentLinkedQueue<String> sseQueue = new ConcurrentLinkedQueue<>();
    public volatile String sessionsJson = "[]";
    public volatile String threadsJson = "{}";
    /**
     * Body returned by the daemon's bulk {@code /s/<sid>/threads?kind=walkthrough}
     * route: {@code {anchor: {anchor, version, messages: [...], title}}}. Kept
     * separate from {@link #threadsJson} (the old flat-blob {@code
     * /threads.json} route, still served for {@code ReviewSessionClientTest})
     * since the two routes' response shapes are unrelated.
     */
    public volatile String bulkThreadsJson = "{}";
    /** Delay (ms) before answering the daemon-shaped bulk {@code GET
     *  /s/<sid>/threads} route — simulates a slow thread-changed re-fetch for
     *  ReviewSessionClientTest's generation-guard regression test. The body is
     *  captured BEFORE the delay, mirroring {@link #threadsDelayMs}, so a test
     *  can change {@link #bulkThreadsJson} mid-flight and the delayed response
     *  still carries the old content. */
    public volatile long bulkThreadsDelayMs = 0;
    /** Body returned by GET /s/<sid>/steps.json. */
    public volatile String stepsJson = "{\"steps\":[]}";
    /**
     * Body of the {@code __meta__} item's {@code body} field in the daemon-
     * shaped bulk {@code GET /s/<sid>/items} route response — ReviewSessionClient's
     * one-time {@code pr_ref} fetch on attach. {@code null} → the response has
     * no {@code __meta__} key at all, matching a session with nothing pushed
     * yet. Kept separate from {@link #stepsJson}/{@link #stepsGeneratedAt}
     * (WalkthroughSessionClientTest's own {@code __steps__} fixture on this
     * same route) since the two items are unrelated.
     */
    public volatile String metaJson = null;
    /** Epoch seconds of the last watcher heartbeat returned by /poll; null → none yet (0). */
    public volatile Long watcherSeenAt = null;
    /** {@code steps_generated_at} returned by /poll; also doubles as the
     *  {@code __steps__} item's version for the daemon-shaped {@code /items}
     *  route and {@code /poll}'s {@code items} map; null → 0. */
    public volatile Long stepsGeneratedAt = null;
    /**
     * Remaining number of /api/sessions requests to answer with a malformed
     * (unparsable) body instead of {@link #sessionsJson}, simulating a
     * transient discovery failure. Decrements per request; 0 → respond
     * normally.
     */
    public final java.util.concurrent.atomic.AtomicInteger sessionsFailuresRemaining =
        new java.util.concurrent.atomic.AtomicInteger();
    /**
     * Remaining number of /api/sessions requests to answer with a non-200 status
     * (no body) instead of {@link #sessionsJson}, simulating a transient server
     * error (e.g. 503 while the registry is being rewritten). Checked before
     * {@link #sessionsFailuresRemaining}; decrements per request; 0 → respond
     * normally. Status code is {@link #sessionsHttpErrorStatus}.
     */
    public final java.util.concurrent.atomic.AtomicInteger sessionsHttpErrorsRemaining =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Status code sent while {@link #sessionsHttpErrorsRemaining} is positive. */
    public volatile int sessionsHttpErrorStatus = 503;
    /**
     * Remaining number of GET /s/&lt;sid&gt;/items requests to answer with a
     * non-200 status (no body) instead of the real {@code __steps__} payload,
     * simulating a transient blip on {@code loadSteps()}'s own bounded retry
     * (e.g. right after a session switch). Decrements per request; 0 → respond
     * normally.
     */
    public final java.util.concurrent.atomic.AtomicInteger itemsHttpErrorsRemaining =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Delay (ms) before answering a successful GET /s/<sid>/items response —
     *  simulates a slow __meta__ fetch for ReviewSessionClient's
     *  loadPrRef()/fetchPrRef() regression tests. Applied AFTER the
     *  itemsHttpErrorsRemaining check, so a scripted failure still answers
     *  immediately; the body is captured before the delay, mirroring {@link
     *  #bulkThreadsDelayMs}/{@link #threadsDelayMs}. */
    public volatile long itemsDelayMs = 0;
    /** When true, /poll reports ended=true (terminal or watcher-dead past reap). */
    public volatile boolean ended = false;
    /** ended_reason returned by /poll when ended; null → JSON null. */
    public volatile String endedReason = null;
    /**
     * Remaining number of /poll requests to answer with
     * {@code ended=true, ended_reason="dead"} regardless of {@link #ended},
     * simulating the server's INFERRED death verdict flickering on for a poll
     * or two (a heartbeat file read while it was being rewritten). Decrements
     * per /poll; 0 → answer from {@link #ended} / {@link #endedReason}.
     */
    public final java.util.concurrent.atomic.AtomicInteger deadPollsRemaining =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Count of GETs that reached /poll. */
    public final java.util.concurrent.atomic.AtomicInteger pollCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Count of POSTs that reached /api/submit. */
    public final java.util.concurrent.atomic.AtomicInteger submitCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Raw body of the last POST that reached /api/submit. */
    public volatile String lastSubmitBody = null;
    /** Count of POSTs that reached /api/cancel. */
    public final java.util.concurrent.atomic.AtomicInteger cancelCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Count of POSTs that reached /api/threads/delete. */
    public final java.util.concurrent.atomic.AtomicInteger deleteThreadCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Raw body of the last POST that reached /api/threads/delete. */
    public volatile String lastDeleteThreadBody = null;
    /** Count of SSE /stream connections opened. */
    public final java.util.concurrent.atomic.AtomicInteger streamOpens =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Count of SSE /stream connections the SERVER saw end (write failed →
     *  the client actually closed the TCP connection, not just a future). */
    public final java.util.concurrent.atomic.AtomicInteger streamCloses =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Delay (ms) before answering GET /threads.json — simulates a slow seed.
     *  The body is captured BEFORE the delay, so a test can change
     *  {@link #threadsJson} mid-flight and the delayed response still carries
     *  the old content. */
    public volatile long threadsDelayMs = 0;

    public FakeReviewServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        port = server.getAddress().getPort();
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/api/sessions", this::handleSessions);
        server.createContext("/s/", this::handleSession);
        server.start();
    }

    public String baseUrl() { return "http://127.0.0.1:" + port; }

    private void handleSessions(HttpExchange ex) throws IOException {
        requests.add(ex);
        if (sessionsHttpErrorsRemaining.getAndUpdate(n -> n > 0 ? n - 1 : 0) > 0) {
            ex.sendResponseHeaders(sessionsHttpErrorStatus, -1);
            ex.close();
            return;
        }
        byte[] body;
        if (sessionsFailuresRemaining.getAndUpdate(n -> n > 0 ? n - 1 : 0) > 0) {
            // Deliberately unparsable JSON (unterminated object) — the client
            // must throw on this, not silently treat it as "no session".
            body = "{".getBytes(StandardCharsets.UTF_8);
        } else {
            body = sessionsJson.getBytes(StandardCharsets.UTF_8);
        }
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(body); }
    }

    private void handleSession(HttpExchange ex) throws IOException {
        requests.add(ex);
        String path = ex.getRequestURI().getPath();
        if (path.endsWith("/steps.json")) {
            byte[] body = stepsJson.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(200, body.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body); }
            return;
        }
        if (path.endsWith("/threads.json")) {
            byte[] body = threadsJson.getBytes(StandardCharsets.UTF_8);
            long delay = threadsDelayMs;
            if (delay > 0) {
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(200, body.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body); }
            return;
        }
        // The daemon's real bulk threads route: no trailing path segment, distinct
        // from /threads.json above and from a per-anchor /threads/<anchor> shape
        // neither this fixture nor any client currently needs.
        if (path.endsWith("/threads")) {
            byte[] body = bulkThreadsJson.getBytes(StandardCharsets.UTF_8);
            long delay = bulkThreadsDelayMs;
            if (delay > 0) {
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(200, body.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body); }
            return;
        }
        // The daemon's real bulk items route: GET /s/<sid>/items?kind=walkthrough
        // returns {"__steps__": {"body": <stepsJson>, "version": <int>}}; for
        // ReviewSessionClientTest (kind=interactive-review) it also carries
        // {"__meta__": {"body": <metaJson>, "version": 1}} when metaJson is set.
        if (path.endsWith("/items")) {
            if (itemsHttpErrorsRemaining.getAndUpdate(n -> n > 0 ? n - 1 : 0) > 0) {
                ex.sendResponseHeaders(500, -1);
                ex.close();
                return;
            }
            long version = stepsGeneratedAt != null ? stepsGeneratedAt : 0;
            StringBuilder sb = new StringBuilder("{\"__steps__\":{\"body\":").append(stepsJson.trim())
                .append(",\"version\":").append(version).append("}");
            if (metaJson != null) {
                sb.append(",\"__meta__\":{\"body\":").append(metaJson.trim()).append(",\"version\":1}");
            }
            sb.append("}");
            byte[] body = sb.toString().getBytes(StandardCharsets.UTF_8);
            long delay = itemsDelayMs;
            if (delay > 0) {
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(200, body.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body); }
            return;
        }
        if (path.endsWith("/poll")) {
            pollCount.incrementAndGet();
            long seen = watcherSeenAt != null ? watcherSeenAt : 0;
            long stepsTs = stepsGeneratedAt != null ? stepsGeneratedAt : 0;
            boolean flickerDead = deadPollsRemaining.getAndUpdate(n -> n > 0 ? n - 1 : 0) > 0;
            boolean isEnded = flickerDead || ended;
            String reason = flickerDead ? "dead" : endedReason;
            String reasonJson = reason == null ? "null" : "\"" + reason + "\"";
            // finished/cancelled mirror the daemon's real poll shape, derived from
            // the same ended/endedReason fields ReviewSessionClientTest already
            // drives; ended/ended_reason/steps_generated_at stay for that test.
            boolean finished = isEnded && "finished".equals(reason);
            boolean cancelled = isEnded && "cancelled".equals(reason);
            byte[] body = ("{\"threads\":{},\"watcher_seen_at\":" + seen
                + ",\"steps_generated_at\":" + stepsTs
                + ",\"finished\":" + finished + ",\"cancelled\":" + cancelled
                + ",\"items\":{\"__steps__\":" + stepsTs + "}"
                + ",\"ended\":" + (isEnded ? "true" : "false")
                + ",\"ended_reason\":" + reasonJson + "}").getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(200, body.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body); }
            return;
        }
        if (path.endsWith("/api/submit")) {
            lastSubmitBody = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            submitCount.incrementAndGet();
            ex.sendResponseHeaders(202, -1);
            ex.close();
            return;
        }
        if (path.endsWith("/api/cancel")) {
            cancelCount.incrementAndGet();
            // A cancelled session goes terminal — the real server drops it
            // from /api/sessions, so mirror that here.
            sessionsJson = "[]";
            ex.sendResponseHeaders(200, -1);
            ex.close();
            return;
        }
        if (path.endsWith("/api/threads/delete")) {
            lastDeleteThreadBody = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            deleteThreadCount.incrementAndGet();
            ex.sendResponseHeaders(200, -1);
            ex.close();
            return;
        }
        if (path.endsWith("/stream")) {
            streamOpens.incrementAndGet();
            ex.getResponseHeaders().add("Content-Type", "text/event-stream");
            ex.sendResponseHeaders(200, 0);
            try (OutputStream os = ex.getResponseBody()) {
                while (!Thread.currentThread().isInterrupted()) {
                    String chunk;
                    while ((chunk = sseQueue.poll()) != null) {
                        os.write(chunk.getBytes(StandardCharsets.UTF_8));
                        os.flush();
                    }
                    // Heartbeat comment (ignored by the SSE parser) so a client
                    // that closed its end surfaces here as a failed write.
                    os.write(": hb\n".getBytes(StandardCharsets.UTF_8));
                    os.flush();
                    try { Thread.sleep(20); } catch (InterruptedException e) { break; }
                }
            } catch (IOException ignored) {
                // Client disconnected — the server-side view of EOF.
                streamCloses.incrementAndGet();
            }
            return;
        }
        ex.sendResponseHeaders(404, -1);
    }

    public void pushSseEvent(String name, String data) {
        sseQueue.offer("event: " + name + "\ndata: " + data + "\n\n");
    }

    @Override public void close() {
        server.stop(0);
    }
}
