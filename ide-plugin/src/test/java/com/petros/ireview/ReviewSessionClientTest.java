package com.petros.ireview;

import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.BooleanSupplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import static org.junit.jupiter.api.Assertions.*;

class ReviewSessionClientTest {

    private static final String KIND = "interactive-review";

    private static void await(BooleanSupplier cond) throws Exception {
        long deadline = System.currentTimeMillis() + 5000;
        while (System.currentTimeMillis() < deadline) {
            if (cond.getAsBoolean()) return;
            Thread.sleep(25);
        }
        fail("condition not met within 5s");
    }

    /** prRef is fetched asynchronously off runSse(), not synchronously inside
     *  attach() — see loadPrRef()'s javadoc — so tests that need the fetched
     *  value poll {@link ReviewSessionClient#currentSession()} rather than
     *  reading it straight off an onAttached callback. */
    private static void awaitPrRef(ReviewSessionClient client, String expected) throws Exception {
        await(() -> client.currentSession().map(ReviewSessionClient.SessionInfo::prRef)
            .orElse("").equals(expected));
    }

    /** The daemon's real session-row shape: {sid, slug, kind, cwd, title, url} —
     *  no pr_ref, no state_dir (both legacy-server-only fields this client no
     *  longer reads off the row; pr_ref instead comes from a one-time __meta__
     *  fetch — see {@link #metaJsonFor}). */
    private static String sessionRowObj(String sid, String title, String kind) {
        return "{\"sid\":\"" + sid + "\",\"title\":\"" + title + "\",\"kind\":\"" + kind + "\"}";
    }

    private static String sessionsRow(String sid) {
        return "[" + sessionRowObj(sid, "t", KIND) + "]";
    }

    /** The {@code __meta__} item's body — daemon items shape wraps this as
     *  {@code {"__meta__":{"body": <this>, "version": 1}}}, which {@link
     *  FakeReviewServer#metaJson} handles. */
    private static String metaJsonFor(String prRef) {
        return "{\"pr_ref\":\"" + prRef + "\"}";
    }

    /** Builds the bulk {@code /threads?kind=interactive-review} shape for one
     *  anchor with a single agent message (and, optionally, a preceding user
     *  question and/or a thread-level anchor_text). Values passed here must
     *  already be JSON-safe (no embedded quotes) — tests needing tricky
     *  characters build the JSON inline instead. */
    private static String bulkThreadRow(String anchor, String question, String synthesis,
                                        int version, String title, String anchorText) {
        StringBuilder messages = new StringBuilder("[");
        if (question != null) {
            messages.append("{\"role\":\"user\",\"text\":\"").append(question).append("\",\"ts\":1},");
        }
        messages.append("{\"role\":\"agent\",\"text\":\"").append(synthesis).append("\",\"ts\":2}]");
        return "{\"" + anchor + "\":{\"anchor\":\"" + anchor + "\",\"version\":" + version
            + ",\"messages\":" + messages + ",\"title\":\"" + title + "\""
            + (anchorText != null ? ",\"anchor_text\":\"" + anchorText + "\"" : "") + "}}";
    }

    @Test
    void emitsAttachedWhenDiscoverFindsSession() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("abc", "Order dashboard", KIND) + "]";
            server.metaJson = metaJsonFor("TCK-171");
            CountDownLatch attached = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(),
                "/proj/acme-shop",
                Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    // prRef is not necessarily known yet at the moment of
                    // attach itself — attach() is deliberately non-blocking
                    // (see loadPrRef()'s javadoc); it's fetched moments later
                    // from runSse(), off this callback entirely.
                    assertEquals("abc", info.sid());
                    attached.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS), "should attach within 2s");
            awaitPrRef(client, "TCK-171");
            client.stop();
        }
    }

    @Test
    void pausedWatcherHeartbeatBlocksSubmission() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            // Watcher last beat 100s ago, but server does not (yet) report
            // ended → recoverable PAUSED tier.
            server.watcherSeenAt = System.currentTimeMillis() / 1000 - 100;
            CountDownLatch paused = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(),
                "/proj/acme-shop",
                Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onStateChanged(ReviewSessionClient.State state) {
                    if (state == ReviewSessionClient.State.PAUSED) paused.countDown();
                }
            });
            client.start();
            assertTrue(paused.await(2, TimeUnit.SECONDS), "should detect paused watcher");

            // A submission while paused must fail fast and never reach the server.
            var f = client.postComment("foo:R:1", "hi", "");
            assertThrows(Exception.class, () -> f.get(1, TimeUnit.SECONDS));
            assertEquals(0, server.submitCount.get(),
                "paused session must not POST submits");
            assertFalse(client.isPending("foo:R:1"), "must not leave a pending spinner");
            client.stop();
        }
    }

    @Test
    void serverEndedLatchesIntoFrozenReadOnly() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000; // fresh → ACTIVE
            CountDownLatch attached = new CountDownLatch(1);
            CountDownLatch ended = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(80));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) { attached.countDown(); }
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.ENDED) ended.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS));

            // Server now reports the session ended via the daemon's real
            // "finished" marker boolean (the daemon has no separate "dead"
            // verdict of its own — see pollLiveness's own comment).
            server.endedReason = "finished";
            server.ended = true;
            assertTrue(ended.await(2, TimeUnit.SECONDS), "should latch ENDED from /poll");

            // Frozen: still attached (findings preserved), but submits are blocked.
            assertTrue(client.currentSession().isPresent(), "ENDED freezes, does not detach");
            var f = client.postComment("foo:R:1", "hi", "");
            assertThrows(Exception.class, () -> f.get(1, TimeUnit.SECONDS));
            assertEquals(0, server.submitCount.get(), "ended session must not POST");

            // Latch: a returning heartbeat / ended=false must NOT un-freeze.
            server.ended = false;
            server.endedReason = null;
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            Thread.sleep(400); // several poll cycles
            assertEquals(ReviewSessionClient.State.ENDED, client.state(),
                "ENDED is a one-way latch");
            client.stop();
        }
    }

    @Test
    void frozenSessionStaysWhenDiscoveryEmpties() throws Exception {
        // The reported bug: cancelling/ending must not blank the panel nor fall
        // back to another session. A frozen session keeps showing its own
        // findings when discovery goes empty (the dead session is reaped).
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch ended = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(80));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.ENDED) ended.countDown();
                }
            });
            client.start();
            server.endedReason = "cancelled";
            server.ended = true;
            assertTrue(ended.await(2, TimeUnit.SECONDS));

            // Discovery now empties (real server reaps terminal/dead sessions).
            server.sessionsJson = "[]";
            Thread.sleep(400); // several poll cycles
            assertEquals(ReviewSessionClient.State.ENDED, client.state(),
                "frozen panel must not blank when discovery empties");
            assertTrue(client.currentSession().isPresent(), "must keep its own session");
            assertEquals("abc", client.currentSession().get().sid());
            client.stop();
        }
    }

    @Test
    void sessionEndedSseFrameLatchesWithoutWaitingForAPoll() throws Exception {
        // The server sends `session-ended` only when a finished/cancelled
        // marker exists — authoritative. Ignoring it meant the client saw only
        // "the stream ended" and reconnected on its 2s timer until a /poll
        // happened to latch.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attached = new CountDownLatch(1);
            CountDownLatch ended = new CountDownLatch(1);
            // Poll slowly, so only the SSE frame can produce a timely latch.
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofSeconds(30));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) { attached.countDown(); }
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.ENDED) ended.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(3, TimeUnit.SECONDS));

            server.pushSseEvent("session-ended", "{}");
            assertTrue(ended.await(3, TimeUnit.SECONDS),
                "session-ended must freeze the panel without waiting for a poll");

            // And it must stop reconnecting rather than churn a new stream
            // every 2s while frozen.
            int opens = server.streamOpens.get();
            Thread.sleep(2500);
            assertEquals(opens, server.streamOpens.get(),
                "a frozen session must not reopen the stream");
            client.stop();
        }
    }

    @Test
    void newLiveSessionSupersedesFrozenPanel() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("abc", "t", KIND) + "]";
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch ended = new CountDownLatch(1);
            CountDownLatch attachedDef = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(80));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    if ("def".equals(info.sid())) attachedDef.countDown();
                }
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.ENDED) ended.countDown();
                }
            });
            client.start();
            server.endedReason = "finished";
            server.ended = true;
            assertTrue(ended.await(2, TimeUnit.SECONDS), "freeze abc first");

            // A brand-new live review appears (different sid) → it supersedes.
            server.ended = false;
            server.endedReason = null;
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            server.sessionsJson = "[" + sessionRowObj("def", "t2", KIND) + "]";
            assertTrue(attachedDef.await(2, TimeUnit.SECONDS),
                "a different LIVE session should supersede the frozen one");
            assertEquals("def", client.currentSession().orElseThrow().sid());
            client.stop();
        }
    }

    @Test
    void cancelSessionPostsCancelAndDetaches() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000; // fresh → active
            CountDownLatch attached = new CountDownLatch(1);
            CountDownLatch detached = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(),
                "/proj/acme-shop",
                Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
                @Override public void onDetached() { detached.countDown(); }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS), "should attach first");

            client.cancelSession().get(2, TimeUnit.SECONDS);
            assertEquals(1, server.cancelCount.get(), "should POST /api/cancel once");
            assertTrue(detached.await(2, TimeUnit.SECONDS),
                "cancel should detach the session");
            assertTrue(client.currentSession().isEmpty(), "no current session after cancel");
            client.stop();
        }
    }

    @Test
    void deleteThreadPostsToThreadsDelete() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000; // fresh → active
            CountDownLatch attached = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(),
                "/proj/acme-shop",
                Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS), "should attach first");

            client.deleteThread("foo:R:1").get(2, TimeUnit.SECONDS);
            assertEquals(1, server.deleteThreadCount.get(),
                "should POST /api/threads/delete once");
            assertTrue(server.lastDeleteThreadBody.contains("foo:R:1"),
                "delete body should carry the anchor");
            client.stop();
        }
    }

    @Test
    void receivesThreadChangedEvent() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            CountDownLatch gotEvent = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(),
                "/proj/acme-shop",
                Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onThreadChanged(String anchor, String synthesis, int version) {
                    if ("foo:R:1".equals(anchor) && "hello".equals(synthesis)) {
                        gotEvent.countDown();
                    }
                }
            });
            client.start();
            Thread.sleep(300); // let it attach + open SSE
            // The daemon's real frame carries only {anchor, version} — the
            // client must re-fetch the bulk shape to learn the rest.
            server.bulkThreadsJson = bulkThreadRow("foo:R:1", null, "hello", 1, "", null);
            server.pushSseEvent("thread-changed", "{\"anchor\":\"foo:R:1\",\"version\":1}");
            assertTrue(gotEvent.await(3, TimeUnit.SECONDS));
            client.stop();
        }
    }

    @Test
    void exposesAnchorTextAndParsesTrickySynthesis() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            // Synthesis text full of JSON-hostile characters; anchor_text present.
            server.bulkThreadsJson =
                "{\"foo:R:1\":{\"anchor\":\"foo:R:1\",\"version\":3,"
              + "\"anchor_text\":\"  return foo(bar);\","
              + "\"messages\":[{\"role\":\"agent\",\"text\":"
              + "\"a \\\"quote\\\" and {brace}\\nline2\",\"ts\":1}]}}";
            CountDownLatch seeded = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onThreadChanged(String anchor, String synthesis, int version) {
                    if ("foo:R:1".equals(anchor)) seeded.countDown();
                }
            });
            client.start();
            assertTrue(seeded.await(2, TimeUnit.SECONDS));
            var ts = client.threadFor("foo:R:1").orElseThrow();
            assertEquals("  return foo(bar);", ts.anchorText());
            assertEquals("a \"quote\" and {brace}\nline2", ts.synthesis());
            assertEquals(3, ts.version());
            client.stop();
        }
    }

    @Test
    void exposesTitleAndQuestion() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.bulkThreadsJson = bulkThreadRow("foo:R:1", "why null-checked?",
                "because **foo** is null", 2, "Null check on foo", "return foo();");
            CountDownLatch seeded = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onThreadChanged(String anchor, String synthesis, int version) {
                    if ("foo:R:1".equals(anchor)) seeded.countDown();
                }
            });
            client.start();
            assertTrue(seeded.await(2, TimeUnit.SECONDS));
            var ts = client.threadFor("foo:R:1").orElseThrow();
            assertEquals("Null check on foo", ts.title());
            assertEquals("why null-checked?", ts.question());
            client.stop();
        }
    }

    @Test
    void discoveryBlipsBelowThresholdDoNotDetach() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attached = new CountDownLatch(1);
            AtomicInteger detaches = new AtomicInteger();
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
                @Override public void onDetached() { detaches.incrementAndGet(); }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS));

            // Two consecutive failures — below the 3-strike threshold. The
            // pre-fix behaviour detached (and wiped the cache) on the FIRST one.
            server.sessionsFailuresRemaining.set(2);
            Thread.sleep(700); // several poll cycles: fail, fail, recover
            assertEquals(0, detaches.get(), "blips below the threshold must not detach");
            assertTrue(client.currentSession().isPresent(), "session must survive the blips");
            client.stop();
        }
    }

    @Test
    void consecutiveDiscoveryFailuresDetachAndGoOffline() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attached = new CountDownLatch(1);
            CountDownLatch detached = new CountDownLatch(1);
            CountDownLatch offline = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
                @Override public void onDetached() { detached.countDown(); }
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.OFFLINE) offline.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS));

            // Discovery now fails on every poll — a real outage.
            server.sessionsFailuresRemaining.set(Integer.MAX_VALUE);
            assertTrue(detached.await(3, TimeUnit.SECONDS),
                "a sustained outage must eventually detach");
            assertTrue(offline.await(2, TimeUnit.SECONDS),
                "an unreachable server must surface as OFFLINE, not idle");
            client.stop();
        }
    }

    @Test
    void reResolvesServerUrlAfterRestartOnNewPort() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            Path cfg = Files.createTempFile("ireview-server", ".json");
            try {
                // server.json initially points at a dead port (the "old" server).
                Files.writeString(cfg, "{\"url\":\"http://127.0.0.1:9\"}");
                CountDownLatch attached = new CountDownLatch(1);
                ReviewSessionClient client = new ReviewSessionClient(
                    () -> readUrl(cfg, "http://127.0.0.1:9"),
                    "/proj/acme-shop", Duration.ofMillis(100));
                client.addListener(new ReviewSessionClient.Listener() {
                    @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                        attached.countDown();
                    }
                });
                client.start();
                Thread.sleep(300); // a few polls against the dead URL
                assertTrue(client.currentSession().isEmpty(), "dead URL can't attach");

                // The server "restarts" on its real port and rewrites server.json.
                Files.writeString(cfg, "{\"url\":\"" + server.baseUrl() + "\"}");
                assertTrue(attached.await(3, TimeUnit.SECONDS),
                    "a failed poll must re-resolve server.json and pick up the new URL");
                client.stop();
            } finally {
                Files.deleteIfExists(cfg);
            }
        }
    }

    /** Same shape as ReviewSessionService's supplier: regex the url field. */
    private static String readUrl(Path cfg, String fallback) {
        try {
            Matcher m = Pattern.compile("\"url\"\\s*:\\s*\"([^\"]+)\"")
                .matcher(Files.readString(cfg));
            if (m.find()) return m.group(1);
        } catch (java.io.IOException ignored) {
        }
        return fallback;
    }

    @Test
    void sessionSwitchDuringSlowSeedDoesNotPolluteNewCache() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("abc", "t", KIND) + "]";
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            // The old session's seed answers slowly, with the OLD threads (the
            // fake captures the body before the delay).
            server.bulkThreadsJson = bulkThreadRow("old.java:R:1", null, "stale answer", 1, "", null);
            server.bulkThreadsDelayMs = 700;
            CountDownLatch attachedAbc = new CountDownLatch(1);
            CountDownLatch attachedDef = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    if ("abc".equals(info.sid())) attachedAbc.countDown();
                    if ("def".equals(info.sid())) attachedDef.countDown();
                }
            });
            client.start();
            assertTrue(attachedAbc.await(2, TimeUnit.SECONDS));

            // Switch sessions while abc's seed request is still in flight.
            Thread.sleep(150);
            server.bulkThreadsDelayMs = 0;
            server.bulkThreadsJson = "{}"; // def has no threads
            server.sessionsJson = "[" + sessionRowObj("def", "t2", KIND) + "]";
            assertTrue(attachedDef.await(2, TimeUnit.SECONDS));

            // Let abc's delayed seed response land (and be discarded).
            Thread.sleep(900);
            assertFalse(client.threadFor("old.java:R:1").isPresent(),
                "old session's slow seed must not write into the new session's cache");
            client.stop();
        }
    }

    @Test
    void threadChangedRefetchDuringSessionSwitchDoesNotPolluteNewCache() throws Exception {
        // Phase 3's Important-1 lesson (generation re-checked AFTER an
        // in-handler HTTP round trip, BEFORE applying results), applied here
        // to the thread-changed frame's own bulk re-fetch — a second, distinct
        // HTTP round trip inside an SSE-event handler from the initial seed
        // covered by sessionSwitchDuringSlowSeedDoesNotPolluteNewCache above.
        // A session switch landing while THIS fetch is in flight must not let
        // the superseded session's response write into the new session's cache.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("abc", "t", KIND) + "]";
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attachedAbc = new CountDownLatch(1);
            CountDownLatch attachedDef = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    if ("abc".equals(info.sid())) attachedAbc.countDown();
                    if ("def".equals(info.sid())) attachedDef.countDown();
                }
            });
            client.start();
            assertTrue(attachedAbc.await(2, TimeUnit.SECONDS));
            Thread.sleep(200); // let the initial (fast, empty) seed finish

            // A thread-changed frame arrives for abc; its bulk re-fetch answers
            // slowly, with abc's OWN thread content (captured before the delay).
            server.bulkThreadsJson = bulkThreadRow("stale.java:R:1", null, "stale reply", 1, "", null);
            server.bulkThreadsDelayMs = 700;
            server.pushSseEvent("thread-changed", "{\"anchor\":\"stale.java:R:1\",\"version\":1}");
            Thread.sleep(150); // let the re-fetch start, still in flight

            // Switch sessions while abc's thread-changed re-fetch is still in flight.
            server.bulkThreadsDelayMs = 0;
            server.bulkThreadsJson = "{}"; // def has no threads
            server.sessionsJson = "[" + sessionRowObj("def", "t2", KIND) + "]";
            assertTrue(attachedDef.await(2, TimeUnit.SECONDS));

            // Let abc's delayed re-fetch response land (and be discarded).
            Thread.sleep(900);
            assertFalse(client.threadFor("stale.java:R:1").isPresent(),
                "abc's superseded thread-changed re-fetch must not write into def's cache");
            client.stop();
        }
    }

    @Test
    void sessionSwitchFetchesFreshPrRefNotStale() throws Exception {
        // Regression guard for Step 2's one-time __meta__ fetch. SessionInfo
        // has no version field to reset the way WalkthroughSessionClient's
        // lastStepsVersion is reset on switch (this file's own Step 2 found
        // there is no diff/meta-content-loading method here to mirror that
        // lesson against) — but prRef is exactly the per-session state that
        // COULD leak across a switch if attach() ever reused the previous
        // session's SessionInfo instead of fetching fresh. A switch to a
        // session whose own __meta__ says "PR2" must never show abc's "PR1".
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("abc", "t", KIND) + "]";
            server.metaJson = metaJsonFor("PR1");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attachedAbc = new CountDownLatch(1);
            CountDownLatch attachedDef = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    if ("abc".equals(info.sid())) attachedAbc.countDown();
                    if ("def".equals(info.sid())) attachedDef.countDown();
                }
            });
            client.start();
            assertTrue(attachedAbc.await(2, TimeUnit.SECONDS));
            awaitPrRef(client, "PR1");

            server.metaJson = metaJsonFor("PR2");
            server.sessionsJson = "[" + sessionRowObj("def", "t2", KIND) + "]";
            assertTrue(attachedDef.await(2, TimeUnit.SECONDS));
            awaitPrRef(client, "PR2");
            assertEquals("def", client.currentSession().orElseThrow().sid());
            client.stop();
        }
    }

    @Test
    void attachesToTheLexicographicallyGreatestSidNotArrayZero() throws Exception {
        // Task 1's supersede=True guarantees the newest sid for a (kind, cwd)
        // is the only one still live (cross-referencing Task 1 Step 1's
        // settled ruling — not re-derived here), but the daemon's array is
        // neither sorted nor guaranteed to exclude terminal sessions. This
        // logic (parseFirstSession's max-sid selection) was already correct
        // going into this task, built by an earlier partial-daemon-shaping
        // session — this test pins it rather than re-deriving it.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("260901-100000-aaa", "t", KIND)
                + "," + sessionRowObj("260902-100000-bbb", "t", KIND) + "]";
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.start();
            try {
                await(() -> client.currentSession().isPresent());
                assertEquals("260902-100000-bbb", client.currentSession().orElseThrow().sid());
            } finally {
                client.stop();
            }
        }
    }

    @Test
    void ignoresARowWhoseKindIsNotInteractiveReview() throws Exception {
        // Belt-and-braces re-check: even though the query already filters by
        // kind, a row the daemon (hypothetically) failed to filter must still
        // be ignored client-side.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = "[" + sessionRowObj("sd1", "t", "show-diff") + "]";
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(50));
            client.start();
            try {
                await(() -> server.requests.size() >= 3);
                assertTrue(client.currentSession().isEmpty());
                assertEquals(ReviewSessionClient.State.DORMANT, client.state());
            } finally {
                client.stop();
            }
        }
    }

    @Test
    void metadataOnlyVersionBumpClearsPendingAndNotifies() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch gotV1 = new CountDownLatch(1);
            CountDownLatch gotV2 = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onThreadChanged(String anchor, String synthesis, int version) {
                    if (!"foo:R:1".equals(anchor)) return;
                    if (version == 1) gotV1.countDown();
                    if (version == 2) gotV2.countDown();
                }
            });
            client.start();
            Thread.sleep(300); // let it attach + open SSE
            server.bulkThreadsJson = bulkThreadRow("foo:R:1", null, "hello", 1, "", null);
            server.pushSseEvent("thread-changed", "{\"anchor\":\"foo:R:1\",\"version\":1}");
            assertTrue(gotV1.await(3, TimeUnit.SECONDS));

            // Ask a question, then the server dedups the reply: same synthesis
            // text, only the version bumps. Pending must clear and listeners
            // must still be notified — otherwise the spinner spins forever.
            client.postComment("foo:R:1", "again?", "").get(2, TimeUnit.SECONDS);
            assertTrue(client.isPending("foo:R:1"));
            server.bulkThreadsJson = bulkThreadRow("foo:R:1", null, "hello", 2, "", null);
            server.pushSseEvent("thread-changed", "{\"anchor\":\"foo:R:1\",\"version\":2}");
            assertTrue(gotV2.await(3, TimeUnit.SECONDS),
                "a version-only bump must notify listeners");
            assertFalse(client.isPending("foo:R:1"),
                "a version-only bump must clear pending");
            assertEquals(2, client.threadFor("foo:R:1").orElseThrow().version());
            client.stop();
        }
    }

    @Test
    void postCommentSendsAnchorText() throws Exception {
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            CountDownLatch attached = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS));
            client.postComment("foo:R:1", "why?", "  return foo(bar);").get(2, TimeUnit.SECONDS);
            assertNotNull(server.lastSubmitBody);
            assertFalse(server.lastSubmitBody.contains("\"type\""),
                "submit body must not carry a dead type field");

            // The daemon's /api/submit keeps only anchor/text/images —
            // anchor_text travels JSON-encoded INSIDE text as
            // {"v","anchor_text","comment"}, not as a sibling top-level key.
            // Parse both layers to pin the exact envelope shape Task 4's
            // SKILL.md must parse identically. "v" discriminates this
            // structured envelope from a plain comment string.
            var outer = com.google.gson.JsonParser.parseString(server.lastSubmitBody).getAsJsonObject();
            assertEquals("foo:R:1", outer.get("anchor").getAsString());
            assertFalse(outer.has("anchor_text"), "anchor_text must not be a top-level submit field");
            var envelope = com.google.gson.JsonParser.parseString(outer.get("text").getAsString()).getAsJsonObject();
            assertEquals(1, envelope.get("v").getAsInt());
            assertEquals("  return foo(bar);", envelope.get("anchor_text").getAsString());
            assertEquals("why?", envelope.get("comment").getAsString());
            client.stop();
        }
    }

    @Test
    void slowPrRefFetchDoesNotDelayAttachOrGetStuckConnecting() throws Exception {
        // Critical-1 regression: fetchPrRef() used to run SYNCHRONOUSLY
        // inside attach(), BEFORE openSse() -- the one place in this file
        // that bumps sseGen and closes the previous session's stream. That
        // left the generation bump (and hence the moment a stale frame from
        // an OLD stream starts failing its gen check) waiting on a full HTTP
        // round trip -- wide open during push.py's
        // create_or_attach(supersede=True) flow, where the daemon fires
        // session-ended on the OLD session at almost the same moment
        // discovery finds the new one. The fetch now lives in runSse(),
        // which only starts running AFTER openSse() has already bumped
        // sseGen and closed the previous stream -- so onAttached (and the
        // generation bump) fire immediately regardless of how slow /items
        // answers, closing that window by construction rather than by
        // timing.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.metaJson = metaJsonFor("PR9");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            server.itemsDelayMs = 2000; // far longer than attach() should ever take
            long start = System.currentTimeMillis();
            AtomicLong attachedAt = new AtomicLong(-1);
            CountDownLatch attached = new CountDownLatch(1);
            CountDownLatch active = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attachedAt.set(System.currentTimeMillis());
                    attached.countDown();
                }
                @Override public void onStateChanged(ReviewSessionClient.State s) {
                    if (s == ReviewSessionClient.State.ACTIVE) active.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(1, TimeUnit.SECONDS),
                "attach() must not block on the slow __meta__ fetch");
            assertTrue(attachedAt.get() - start < 1000,
                "onAttached fired after " + (attachedAt.get() - start) + "ms; must be prompt");
            // The fetch is still in flight -- prRef starts empty, never
            // reused from a stale prior session.
            assertEquals("", client.currentSession().orElseThrow().prRef());

            assertTrue(active.await(4, TimeUnit.SECONDS),
                "must still reach ACTIVE once the slow fetch completes");
            assertEquals("PR9", client.currentSession().orElseThrow().prRef());
            client.stop();
        }
    }

    @Test
    void prRefSelfHealsAfterAFailedFetchAttempt() throws Exception {
        // Important-1 regression: push.py writes the session row
        // (create_or_attach) and __meta__ (a separate, later put_items call
        // that uploads the whole diff) in two separate daemon calls -- a
        // discovery poll landing in that gap finds a real session with no
        // __meta__ yet. fetchPrRef used to have no retry at all, so a single
        // miss permanently left prRef="" for the session's whole lifetime.
        // loadPrRef now retries the same bounded 3x/500ms shape seedCache
        // already uses, so a miss on the first attempt or two still resolves
        // within the same attach cycle.
        try (FakeReviewServer server = new FakeReviewServer()) {
            server.sessionsJson = sessionsRow("abc");
            server.metaJson = metaJsonFor("PR7");
            server.watcherSeenAt = System.currentTimeMillis() / 1000;
            // The first two /items GETs (loadPrRef's first two attempts)
            // fail; metaJson is already set, so the third attempt succeeds.
            server.itemsHttpErrorsRemaining.set(2);
            CountDownLatch attached = new CountDownLatch(1);
            ReviewSessionClient client = new ReviewSessionClient(
                server.baseUrl(), "/proj/acme-shop", Duration.ofMillis(100));
            client.addListener(new ReviewSessionClient.Listener() {
                @Override public void onAttached(ReviewSessionClient.SessionInfo info) {
                    attached.countDown();
                }
            });
            client.start();
            assertTrue(attached.await(2, TimeUnit.SECONDS));
            // The retry loop needs room for up to two 500ms backoffs before
            // its third, successful attempt.
            awaitPrRef(client, "PR7");
            client.stop();
        }
    }
}
