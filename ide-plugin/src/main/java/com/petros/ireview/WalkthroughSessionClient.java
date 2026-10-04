package com.petros.ireview;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

import static com.petros.ireview.WebCompanionHttp.flag;
import static com.petros.ireview.WebCompanionHttp.num;
import static com.petros.ireview.WebCompanionHttp.str;

/**
 * Talks to the webcompanion daemon under {@code kind=walkthrough}: follows
 * the newest walkthrough session for the project (see {@link
 * DaemonSessionClient} for the lifecycle), keeps per-step threads, and posts
 * questions. Adds the tour itself, the {@code __steps__} item off the bulk
 * items route, reloaded whenever its version moves.
 */
public final class WalkthroughSessionClient extends DaemonSessionClient<
        WalkthroughSessionClient.SessionInfo, WalkthroughSessionClient.ThreadState,
        WalkthroughSessionClient.Listener> {

    public record SessionInfo(String sid, String title) implements DaemonSessionClient.Session {}

    public record ThreadState(String synthesis, int version, String title, String question)
            implements DaemonSessionClient.ThreadView {}

    public interface Listener extends DaemonSessionClient.SessionListener<SessionInfo> {
        default void onStepsChanged(WalkthroughDoc doc) {}
        /** {@code thread} is null when the thread was deleted. */
        default void onThreadChanged(String anchor, ThreadState thread) {}
    }

    private static final String KIND = "walkthrough";

    /** Two strikes. A single dropped poll must not detach: detaching clears
     *  the doc, and the next poll's re-attach would publish it afresh, reset
     *  the tour to step 1 and yank the editor for no visible reason. */
    private static final int DISCOVERY_FAILURE_THRESHOLD = 2;

    private final AtomicReference<WalkthroughDoc> doc = new AtomicReference<>(WalkthroughDoc.EMPTY);
    /** The {@code __steps__} item's version as of the last successful {@link
     *  #loadSteps} call — compared against each poll's {@code items.__steps__}
     *  and each {@code item-changed} frame. */
    private volatile int lastStepsVersion = 0;

    public WalkthroughSessionClient(String baseUrl, String projectCwd, Duration pollInterval) {
        this(() -> baseUrl, projectCwd, pollInterval);
    }

    /**
     * @param baseUrlSupplier resolves the daemon's base URL; re-invoked after a
     *        failed discovery poll so a daemon restart on a new port is picked
     *        up without an IDE restart.
     */
    public WalkthroughSessionClient(Supplier<String> baseUrlSupplier, String projectCwd, Duration pollInterval) {
        super(KIND, DISCOVERY_FAILURE_THRESHOLD, "walkthrough-sse", baseUrlSupplier, projectCwd, pollInterval);
    }

    public WalkthroughDoc doc() { return doc.get(); }

    /** POST a question on a step to /s/&lt;sid&gt;/api/submit. */
    public CompletableFuture<Void> postAsk(int stepId, String text) {
        return submit("step:" + stepId, text);
    }

    // --- lifecycle hooks ---

    @Override protected SessionInfo toSession(JsonObject row) {
        return new SessionInfo(str(row, "sid"), str(row, "title"));
    }

    @Override protected ThreadState toThread(BulkThread t) {
        return new ThreadState(t.synthesis(), t.version(), t.title(), t.question());
    }

    @Override protected void notifyThreadChanged(Listener l, String anchor, ThreadState t) {
        l.onThreadChanged(anchor, t);
    }

    @Override protected void notifyThreadDeleted(Listener l, String anchor) {
        l.onThreadChanged(anchor, null);
    }

    @Override protected String resumeCommand() { return "/walkthrough"; }

    @Override protected String threadSeedWarning() {
        return "Couldn't load existing threads from the walkthrough server — "
            + "answers already given may be missing until the connection recovers.";
    }

    /** Every switch resets the version too: push.py writes each session's
     *  {@code __steps__} at version 1, so a stale value would make a new
     *  session's version look already loaded. */
    @Override protected void resetSession() {
        doc.set(WalkthroughDoc.EMPTY);
        lastStepsVersion = 0;
    }

    @Override protected void afterDetach() {
        fire("onStepsChanged", l -> l.onStepsChanged(WalkthroughDoc.EMPTY));
    }

    @Override protected void beforeSeed(String sid, long gen) {
        loadSteps(sid, gen);
    }

    /**
     * Steps freshness rides on the liveness poll: {@code /poll} reports the
     * {@code __steps__} version on every call, and nothing wakes the stream
     * the moment Claude writes a fresh steps document, so this bounds the
     * delay at one poll interval with no extra traffic. Skipped while
     * CONNECTING: the SSE worker's own first load is running then, and two
     * concurrent loads could both see EMPTY and activate the tour twice.
     */
    @Override protected void onPolled(String sid, JsonObject poll) {
        JsonElement items = poll.get("items");
        if (items == null || !items.isJsonObject()) return;
        long stepsVersion = num(items.getAsJsonObject(), "__steps__", -1);
        if (stepsVersion < 0) return;
        if (state() != State.CONNECTING && stepsVersion != lastStepsVersion) {
            loadSteps(sid, currentGen());
        }
    }

    /** {@code item-changed} for {@code __steps__} reloads the tour, except the
     *  connect-time replay of the version the first load has just read. */
    @Override protected void onStreamEvent(String sid, String name, JsonObject data, long gen) {
        if (!"item-changed".equals(name) || !"__steps__".equals(str(data, "anchor"))) return;
        if (flag(data, "initial") && num(data, "version", -1) == lastStepsVersion) return;
        loadSteps(sid, gen);
    }

    /**
     * GET {@code __steps__} off the daemon's bulk items route and publish it
     * if it actually changed. Retries transient failures up to 3x with a
     * 500ms backoff, and warns the listeners on exhaustion rather than going
     * quietly empty. Aborts as soon as {@code gen} is superseded.
     */
    private void loadSteps(String sid, long gen) {
        for (int attempt = 0; attempt < 3 && isCurrent(gen); attempt++) {
            try {
                HttpRequest req = request(sid, "items").GET().build();
                HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() == 200) {
                    // Guard before touching any shared state: a superseded
                    // session's response must not overwrite lastStepsVersion,
                    // the doc or the listeners after a newer attach.
                    if (!isCurrent(gen)) return;
                    JsonObject root = JsonParser.parseString(resp.body()).getAsJsonObject();
                    // No "__steps__" means nothing pushed yet for this session
                    // (a fresh session's /items answers "{}") — parse(null)
                    // degrades that to EMPTY.
                    JsonObject stepsItem = root.has("__steps__") && root.get("__steps__").isJsonObject()
                        ? root.getAsJsonObject("__steps__") : null;
                    String body = stepsItem != null && stepsItem.has("body")
                        ? stepsItem.get("body").toString() : null;
                    WalkthroughDoc next = WalkthroughDoc.parse(body);
                    if (stepsItem != null) {
                        long version = num(stepsItem, "version", -1);
                        if (version >= 0) lastStepsVersion = (int) version;
                    }
                    WalkthroughDoc prev = doc.get();
                    if (prev.generatedTs() == next.generatedTs()
                            && prev.steps().size() == next.steps().size()) {
                        return;
                    }
                    doc.set(next);
                    fire("onStepsChanged", l -> l.onStepsChanged(next));
                    return;
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                // Transient failure or a malformed body — the retry loop is the handling.
            }
            try {
                Thread.sleep(500);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        warn("Couldn't load the walkthrough steps from the server — "
            + "the tour may be empty until the connection recovers.", gen);
    }
}
