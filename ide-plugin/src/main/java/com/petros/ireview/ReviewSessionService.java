package com.petros.ireview;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.components.Service;
import com.intellij.openapi.project.Project;

import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Project-level holder of one {@link ReviewSessionClient}.
 *
 * Lifecycle: created on first {@link #get} call, disposed when the project
 * closes (via IntelliJ's Service framework). The held client begins polling
 * for sessions matching the project's base path immediately.
 */
@Service(Service.Level.PROJECT)
public final class ReviewSessionService implements Disposable {

    private final ReviewSessionClient client;

    /** How long after a pending-cleared a thread-changed still counts as "the
     *  answer to the question the user just asked" for the balloon. */
    private static final long ANSWER_WINDOW_MS = 5_000;

    public ReviewSessionService(Project project) {
        String cwd = project.getBasePath();
        // The URL supplier re-reads on every failed discovery poll, so a
        // server restart (or the webcompanion daemon appearing where the
        // legacy per-skill server used to be) is picked up without an IDE
        // restart.
        this.client = new ReviewSessionClient(
            () -> ServerDiscovery.resolve(
                Path.of(System.getProperty("user.home")),
                legacyServerJsonPath(),
                "http://127.0.0.1:54620"),
            cwd != null ? cwd : System.getProperty("user.home"),
            Duration.ofSeconds(5)
        );
        // Repaint diff gutters whenever a thread is added/deleted or a question
        // goes in/out of flight, so the annotation / answering icons appear and
        // disappear immediately instead of waiting for the user's next hover.
        this.client.addListener(new ReviewSessionClient.Listener() {
            /** Anchors whose pending flag just cleared, with the clear time.
             *  handleSseEvent clears pending immediately before firing
             *  onThreadChanged on the same thread, so an answer shows up here
             *  microseconds before its thread-changed. Failure paths also land
             *  here but never fire onThreadChanged, so they age out. */
            private final Map<String, Long> justAnswered = new ConcurrentHashMap<>();
            /** Anchors with a question in flight from this IDE. */
            private final java.util.Set<String> awaiting = ConcurrentHashMap.newKeySet();

            @Override public void onThreadChanged(String anchor, String synthesis, int version) {
                Long clearedAt = justAnswered.remove(anchor);
                if (clearedAt != null
                        && System.currentTimeMillis() - clearedAt < ANSWER_WINDOW_MS
                        && !SynthesisPopup.isOpenFor(project, anchor)) {
                    notifyAnswered(project, client, anchor);
                }
                repaintGutters();
            }
            @Override public void onThreadDeleted(String anchor) {
                repaintGutters();
            }
            @Override public void onPendingChanged(String anchor, boolean pending) {
                if (pending) {
                    awaiting.add(anchor);
                } else if (awaiting.remove(anchor)) {
                    justAnswered.put(anchor, System.currentTimeMillis());
                }
                repaintGutters();
            }
            @Override public void onDetached() {
                awaiting.clear();
                justAnswered.clear();
            }
            private void repaintGutters() {
                com.intellij.openapi.application.ApplicationManager.getApplication()
                    .invokeLater(SpikeDiffExtension::repaintAllGutters);
            }
        });
        this.client.start();
    }

    public static ReviewSessionService get(Project project) {
        return project.getService(ReviewSessionService.class);
    }

    public ReviewSessionClient client() { return client; }

    @Override public void dispose() { client.stop(); }

    /**
     * Balloon "Claude answered · <file>:<line>" when an answer lands for an
     * anchor that has no popup on screen — otherwise the answer arrives
     * invisibly and the user keeps waiting. Clicking the action focuses the
     * thread (diff editor + popup if the viewer is open, else drives the PR
     * diff there).
     */
    private static void notifyAnswered(Project project, ReviewSessionClient client, String anchor) {
        String[] parts = anchor.split(":", 3);
        String where = parts.length >= 3
            ? lastSegment(parts[0]) + ":" + parts[2]
            : (ReviewAnchor.isGeneral(anchor) ? "whole PR" : anchor);
        com.intellij.notification.Notification n = new com.intellij.notification.Notification(
            "Interactive Review",
            "Claude answered",
            where,
            com.intellij.notification.NotificationType.INFORMATION);
        n.addAction(com.intellij.notification.NotificationAction.createSimple(
            "Open thread", () -> {
                openThread(project, client, anchor);
                n.expire();
            }));
        com.intellij.notification.Notifications.Bus.notify(n, project);
    }

    /** Focus the thread's line: reuse the registered diff viewer when there is
     *  one, else drive the GitHub PR diff to the file + line. */
    private static void openThread(Project project, ReviewSessionClient client, String anchor) {
        String[] parts = anchor.split(":", 3);
        if (parts.length < 3) {
            // Whole-PR thread: no file to open. The action used to do nothing
            // at all — show the thread over the IDE frame, as the panel does.
            com.intellij.openapi.wm.IdeFrame frame =
                com.intellij.openapi.wm.WindowManager.getInstance().getIdeFrame(project);
            if (frame != null) SynthesisPopup.showDetached(project, frame.getComponent(), anchor);
            return;
        }
        String path = parts[0];
        String side = parts[1];
        int start = ReviewAnchor.startLine(parts[2]);
        if (start < 0) return;
        int line0 = Math.max(0, start - 1);
        com.intellij.openapi.editor.ex.EditorEx editor =
            SpikeDiffExtension.editorFor(path + ":" + side);
        if (editor != null) {
            int display = SpikeDiffExtension.displayLineFor(path + ":" + side, line0);
            editor.getCaretModel().moveToLogicalPosition(
                new com.intellij.openapi.editor.LogicalPosition(display, 0));
            editor.getScrollingModel().scrollToCaret(
                com.intellij.openapi.editor.ScrollType.CENTER);
            java.awt.Window window = javax.swing.SwingUtilities
                .getWindowAncestor(editor.getContentComponent());
            if (window != null) {
                window.toFront();
                window.requestFocus();
            }
            editor.getContentComponent().requestFocusInWindow();
            SynthesisPopup.show(project, editor, anchor, display);
            return;
        }
        client.currentSession().ifPresent(s ->
            GhPrDiffOpener.openAt(project, s, path, side, line0));
    }

    private static String lastSegment(String path) {
        int slash = path.lastIndexOf('/');
        return slash < 0 ? path : path.substring(slash + 1);
    }

    /**
     * The legacy ask_diff server's discovery file,
     * ~/.claude/interactive-review/server.json — the skill writes it on
     * server start and rewrites it on every restart. {@link ServerDiscovery}
     * tries the webcompanion daemon's own config first and falls back to this.
     */
    private static Path legacyServerJsonPath() {
        return Path.of(System.getProperty("user.home"), ".claude", "interactive-review", "server.json");
    }
}
