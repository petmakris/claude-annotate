package com.petros.ireview;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;

import static com.petros.ireview.WebCompanionHttp.str;

/**
 * Talks to the shared webcompanion daemon under {@code kind=interactive-review}:
 * follows the newest ask_diff session for the project (see {@link
 * DaemonSessionClient} for the lifecycle), caches per-anchor syntheses, and
 * posts comments. Adds the session's PR reference, read once per session from
 * its {@code __meta__} item.
 */
public final class ReviewSessionClient extends DaemonSessionClient<
        ReviewSessionClient.SessionInfo, ReviewSessionClient.ThreadState, ReviewSessionClient.Listener> {

    public record SessionInfo(String sid, String prRef, String title) implements DaemonSessionClient.Session {}

    public record ThreadState(String synthesis, int version, String anchorText,
                              String title, String question, long updatedAt)
            implements DaemonSessionClient.ThreadView {
        /** Compat constructor for callers that don't carry a timestamp. */
        public ThreadState(String synthesis, int version, String anchorText,
                           String title, String question) {
            this(synthesis, version, anchorText, title, question, 0L);
        }
    }

    public interface Listener extends DaemonSessionClient.SessionListener<SessionInfo> {
        default void onThreadChanged(String anchor, String synthesis, int version) {}
        default void onThreadDeleted(String anchor) {}
    }

    private static final String KIND = "interactive-review";

    /** Three strikes: a review panel holds the user's whole PR conversation. */
    private static final int DISCOVERY_FAILURE_THRESHOLD = 3;

    /** Discriminator field ("v") in the anchor_text JSON envelope postComment
     *  sends inside the submit payload's text field — lets a reader (the
     *  ask_diff SKILL.md) tell this structured shape apart from a plain
     *  comment string. Bump only in lockstep with SKILL.md's parser. */
    private static final int ANCHOR_TEXT_ENVELOPE_VERSION = 1;

    public ReviewSessionClient(String baseUrl, String projectCwd, Duration pollInterval) {
        this(() -> baseUrl, projectCwd, pollInterval);
    }

    /**
     * @param baseUrlSupplier resolves the daemon's base URL; re-invoked after a
     *        failed discovery poll so a daemon restart on a new port is picked
     *        up without an IDE restart.
     */
    public ReviewSessionClient(Supplier<String> baseUrlSupplier, String projectCwd, Duration pollInterval) {
        super(KIND, DISCOVERY_FAILURE_THRESHOLD, "ireview-sse", baseUrlSupplier, projectCwd, pollInterval);
    }

    /** POST a comment event to /s/&lt;sid&gt;/api/submit. */
    public CompletableFuture<Void> postComment(String anchor, String text, String anchorText) {
        // The daemon's /api/submit keeps only anchor/text/images from the
        // payload and drops everything else, so anchor_text travels
        // JSON-encoded inside text itself; SKILL.md's Mode D parses this
        // identical {"v", "anchor_text", "comment"} envelope back out. "v"
        // discriminates it from a plain comment string (the daemon's own web
        // page never sets it, and it lets Mode D refuse a user comment that
        // merely happens to look like a JSON object with those keys).
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("v", ANCHOR_TEXT_ENVELOPE_VERSION);
        envelope.put("anchor_text", anchorText == null ? "" : anchorText);
        envelope.put("comment", text);
        return submit(anchor, GSON.toJson(envelope));
    }

    /** POST a delete request to /s/&lt;sid&gt;/api/threads/delete. */
    public CompletableFuture<Void> deleteThread(String anchor) {
        SessionInfo s = currentSession().orElse(null);
        if (s == null) return CompletableFuture.failedFuture(new IllegalStateException("no session"));
        HttpRequest req = request(s.sid(), "api/threads/delete")
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(Map.of("anchor", anchor))))
            .build();
        return http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
            .thenAccept(resp -> {
                if (resp.statusCode() / 100 != 2) {
                    throw new RuntimeException("delete failed: HTTP " + resp.statusCode());
                }
            });
    }

    // --- lifecycle hooks ---

    /** The daemon's session row ({sid, slug, kind, cwd, title, url}) has no
     *  pr_ref: prRef starts empty and {@link #beforeSeed} fills it in. */
    @Override protected SessionInfo toSession(JsonObject row) {
        return new SessionInfo(str(row, "sid"), "", str(row, "title"));
    }

    @Override protected ThreadState toThread(BulkThread t) {
        return new ThreadState(t.synthesis(), t.version(), t.anchorText(), t.title(),
            t.question(), t.updatedAt());
    }

    @Override protected void notifyThreadChanged(Listener l, String anchor, ThreadState t) {
        l.onThreadChanged(anchor, t.synthesis(), t.version());
    }

    @Override protected void notifyThreadDeleted(Listener l, String anchor) {
        l.onThreadDeleted(anchor);
    }

    @Override protected String resumeCommand() { return "/ask-diff"; }

    @Override protected String threadSeedWarning() {
        return "Couldn't load existing threads from the review server — "
            + "the panel may be incomplete until the connection recovers.";
    }

    /** The seed re-runs on every reconnect, so one that failed once and then
     *  succeeds must retract its warning — otherwise the footer keeps saying
     *  the panel is incomplete after every thread is back. */
    @Override protected void afterSeed(long gen) {
        warn(null, gen);
    }

    /**
     * Loads {@code __meta__.body.pr_ref}, when not already known, with the
     * thread seed's 3-attempts/500ms-backoff shape. It runs here, after the
     * stream generation has moved on, never in attach: a blocking fetch there
     * left the previous session's stream live and passing the generation
     * check for the whole round trip — exactly when {@code push.py}'s
     * supersede fires {@code session-ended} on the old session.
     *
     * <p>{@code push.py} creates the session row and writes {@code __meta__}
     * in two separate calls, so a discovery poll in between finds a session
     * with no {@code __meta__} yet. The retries absorb that; a miss that
     * outlasts them gets another attempt on every reconnect, since this runs
     * on each one, and stops once prRef is known (it never changes for a
     * session's lifetime). An empty prRef degrades through {@code
     * GhPrDiffOpener}'s own "No PR number" message, so a miss does not warn.
     */
    @Override protected void beforeSeed(String sid, long gen) {
        SessionInfo snapshot = currentSession().orElse(null);
        if (snapshot == null || !snapshot.sid().equals(sid) || !snapshot.prRef().isEmpty()) return;
        for (int attempt = 0; attempt < 3 && isCurrent(gen); attempt++) {
            String prRef = fetchPrRef(sid);
            if (!prRef.isEmpty()) {
                if (!isCurrent(gen)) return; // superseded mid-fetch
                updateCurrent(sid, latest -> new SessionInfo(sid, prRef, latest.title()));
                return;
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    /** One GET of {@code __meta__.body.pr_ref}; "" on any failure (non-200,
     *  unparsable body, no __meta__ item yet, or no pr_ref in it). */
    private String fetchPrRef(String sid) {
        try {
            HttpRequest req = request(sid, "items").GET().build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) return "";
            JsonObject root = JsonParser.parseString(resp.body()).getAsJsonObject();
            if (!root.has("__meta__") || !root.get("__meta__").isJsonObject()) return "";
            JsonObject metaItem = root.getAsJsonObject("__meta__");
            if (!metaItem.has("body") || !metaItem.get("body").isJsonObject()) return "";
            return str(metaItem.getAsJsonObject("body"), "pr_ref");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return "";
        } catch (Exception e) {
            return ""; // the caller retries, then the next reconnect does
        }
    }
}
