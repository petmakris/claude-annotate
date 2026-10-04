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
 * Minimal stand-in for the webcompanion daemon, serving the routes the IDE
 * clients call: {@code /api/sessions}, and per session {@code /items},
 * {@code /threads}, {@code /poll}, {@code /stream}, {@code /api/submit},
 * {@code /api/cancel} and {@code /api/threads/delete}.
 */
public final class FakeReviewServer implements AutoCloseable {
    private final HttpServer server;
    private final int port;
    public final List<HttpExchange> requests = new ArrayList<>();
    public final ConcurrentLinkedQueue<String> sseQueue = new ConcurrentLinkedQueue<>();
    public volatile String sessionsJson = "[]";
    /**
     * Body returned by the bulk {@code GET /s/<sid>/threads} route:
     * {@code {anchor: {anchor, version, messages: [...], title}}}.
     */
    public volatile String bulkThreadsJson = "{}";
    /** Delay (ms) before answering the bulk {@code GET /s/<sid>/threads} route
     *  — simulates a slow seed or thread-changed re-fetch. The body is captured
     *  BEFORE the delay, so a test can change {@link #bulkThreadsJson}
     *  mid-flight and the delayed response still carries the old content. */
    public volatile long bulkThreadsDelayMs = 0;
    /** Count of GETs that reached the bulk {@code /s/<sid>/threads} route. */
    public final java.util.concurrent.atomic.AtomicInteger bulkThreadsCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /** Count of GETs that reached the bulk {@code /s/<sid>/items} route. */
    public final java.util.concurrent.atomic.AtomicInteger itemsCount =
        new java.util.concurrent.atomic.AtomicInteger();
    /**
     * When true (the daemon's behaviour), every {@code /stream} connection
     * opens with one {@code "initial": true} frame per item and per thread,
     * echoing the versions a client's own first GET already saw: an
     * {@code item-changed} for {@code __steps__} (and {@code __meta__} when
     * set), then a {@code thread-changed} per anchor in {@link #bulkThreadsJson}.
     */
    public volatile boolean replayInitialFrames = true;
    /** Overrides the versions the initial {@code thread-changed} frames carry,
     *  per anchor — simulates a thread that changed between a client's seed
     *  and its stream opening. Null → the versions in {@link #bulkThreadsJson}. */
    public volatile java.util.Map<String, Integer> initialThreadVersions = null;
    /** Body of the {@code __steps__} item in the bulk {@code /s/<sid>/items}
     *  route's response. */
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
    /** The {@code __steps__} item's version, in the {@code /items} route and in
     *  {@code /poll}'s {@code items} map; null → 0. */
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
     *  immediately; the body is captured before the delay, as with {@link
     *  #bulkThreadsDelayMs}. */
    public volatile long itemsDelayMs = 0;
    /** When true, /poll reports the session terminal: {@code finished} or
     *  {@code cancelled}, whichever {@link #endedReason} names. */
    public volatile boolean ended = false;
    /** {@code "finished"} or {@code "cancelled"} — which marker /poll sets
     *  while {@link #ended}. */
    public volatile String endedReason = null;
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
        // The bulk threads route. A per-anchor /threads/<anchor> shape exists
        // on the daemon too, but no client calls it.
        if (path.endsWith("/threads")) {
            bulkThreadsCount.incrementAndGet();
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
            itemsCount.incrementAndGet();
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
            long stepsVersion = stepsGeneratedAt != null ? stepsGeneratedAt : 0;
            // The daemon's poll shape: {finished, cancelled, watcher_seen_at,
            // items, threads}. It carries no ended verdict of its own.
            boolean finished = ended && "finished".equals(endedReason);
            boolean cancelled = ended && "cancelled".equals(endedReason);
            byte[] body = ("{\"threads\":{},\"watcher_seen_at\":" + seen
                + ",\"finished\":" + finished + ",\"cancelled\":" + cancelled
                + ",\"items\":{\"__steps__\":" + stepsVersion + "}}").getBytes(StandardCharsets.UTF_8);
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
                if (replayInitialFrames) {
                    os.write(initialFrames().getBytes(StandardCharsets.UTF_8));
                    os.flush();
                }
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

    /** The opening snapshot the daemon sends on every stream connect. */
    private String initialFrames() {
        StringBuilder sb = new StringBuilder();
        long stepsVersion = stepsGeneratedAt != null ? stepsGeneratedAt : 0;
        sb.append(frame("item-changed",
            "{\"anchor\":\"__steps__\",\"version\":" + stepsVersion + ",\"initial\":true}"));
        if (metaJson != null) {
            sb.append(frame("item-changed", "{\"anchor\":\"__meta__\",\"version\":1,\"initial\":true}"));
        }
        java.util.Map<String, Integer> overrides = initialThreadVersions;
        var threads = com.google.gson.JsonParser.parseString(bulkThreadsJson).getAsJsonObject();
        for (var e : threads.entrySet()) {
            int version = overrides != null && overrides.containsKey(e.getKey())
                ? overrides.get(e.getKey())
                : e.getValue().getAsJsonObject().get("version").getAsInt();
            sb.append(frame("thread-changed", "{\"anchor\":\"" + e.getKey() + "\",\"version\":"
                + version + ",\"initial\":true}"));
        }
        return sb.toString();
    }

    private static String frame(String name, String data) {
        return "event: " + name + "\ndata: " + data + "\n\n";
    }

    public void pushSseEvent(String name, String data) {
        sseQueue.offer(frame(name, data));
    }

    @Override public void close() {
        server.stop(0);
    }
}
