package com.petros.ireview;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.components.Service;
import com.intellij.openapi.project.Project;

import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;

/**
 * Project-level holder of one walkthrough client + controller.
 *
 * The client discovers a session by the project's base path; when steps arrive
 * they are pushed into the controller, which activates step 1 and drives
 * whichever renderer is currently attached.
 */
@Service(Service.Level.PROJECT)
public final class WalkthroughService implements Disposable {

    private static final String INLINE_VISIBLE_KEY = "com.petros.ireview.walkthrough.inline.visible";
    /** The sid of the tour the user dismissed, so a restart does not bring it back. */
    private static final String DISMISSED_SID_KEY = "com.petros.ireview.walkthrough.dismissed.sid";

    private final Project project;

    private final WalkthroughSessionClient client;
    private final WalkthroughController controller;
    private final WalkthroughInlay inline;

    public WalkthroughService(Project project) {
        this.project = project;
        String cwd = project.getBasePath();
        // The URL supplier re-reads the daemon config on every failed
        // discovery poll, so a daemon restart on a new port is picked up
        // without an IDE restart.
        this.client = new WalkthroughSessionClient(
            () -> ServerDiscovery.resolve(Path.of(System.getProperty("user.home"))),
            cwd != null ? cwd : System.getProperty("user.home"),
            Duration.ofSeconds(5));
        this.controller = new WalkthroughController(new WalkthroughNavigator.Ide(project));
        this.inline = new WalkthroughInlay(project, controller, client);
        this.controller.setInlineVisible(com.intellij.ide.util.PropertiesComponent
            .getInstance(project).getBoolean(INLINE_VISIBLE_KEY, true));
        this.controller.addListener(new WalkthroughController.Listener() {
            @Override public void onInlineVisibleChanged(boolean visible) {
                com.intellij.ide.util.PropertiesComponent.getInstance(project)
                    .setValue(INLINE_VISIBLE_KEY, visible, true);
                applyInlineVisible(visible);
            }
        });
        this.client.addListener(new WalkthroughSessionClient.Listener() {
            @Override public void onStepsChanged(WalkthroughDoc doc) {
                // setDoc activates step 1, which opens an editor. A poll that lands
                // while the platform is still in restoreEditors puts a tab in the main
                // splitter before it expects one, and the frame allocator throws
                // "Tab count expected to be zero". runAfterOpened defers the first doc
                // past editor restore; once the project is open it runs inline, so
                // later polls are unaffected.
                com.intellij.openapi.startup.StartupManager.getInstance(project)
                    .runAfterOpened(() -> com.intellij.openapi.application.ApplicationManager.getApplication()
                        .invokeLater(() -> controller.setDoc(doc), project.getDisposed()));
            }
        });
        this.client.ignoreSid(com.intellij.ide.util.PropertiesComponent
            .getInstance(project).getValue(DISMISSED_SID_KEY));
        this.client.start();
        applyInlineVisible(controller.inlineVisible());
    }

    public static WalkthroughService get(Project project) {
        return project.getService(WalkthroughService.class);
    }

    public WalkthroughSessionClient client() { return client; }

    public WalkthroughController controller() { return controller; }

    public WalkthroughInlay inline() { return inline; }

    /** Post a question on the currently active step. */
    public CompletableFuture<Void> askCurrentStep(String text) {
        return controller.current()
            .map(step -> client.postAsk(step.id(), text))
            .orElseGet(() -> CompletableFuture.failedFuture(
                new IllegalStateException("no active step")));
    }

    /**
     * Takes the tour off the panel and the editor, and keeps it off. A tour
     * Claude still watches is ended too, after the user agrees, so Claude
     * hears it was cancelled. Runs on the UI thread.
     */
    public void dismiss() {
        var session = client.currentSession();
        if (session.isEmpty() && controller.doc().isEmpty()) return;
        boolean live = client.state() != WalkthroughSessionClient.State.ENDED;
        if (session.isPresent() && live) {
            int choice = com.intellij.openapi.ui.Messages.showYesNoDialog(project,
                "Claude is still watching this walkthrough. Dismissing it ends the "
                    + "session, and questions on its steps can no longer be asked.",
                "Dismiss Walkthrough", "Dismiss", "Keep it",
                com.intellij.openapi.ui.Messages.getQuestionIcon());
            if (choice != com.intellij.openapi.ui.Messages.YES) return;
        }
        client.dismiss().whenComplete((v, err) -> {
            String sid = client.dismissedSid();
            if (sid != null) {
                com.intellij.ide.util.PropertiesComponent.getInstance(project)
                    .setValue(DISMISSED_SID_KEY, sid);
            }
            if (err != null) {
                com.intellij.notification.Notifications.Bus.notify(
                    new com.intellij.notification.Notification("Claude IDE Review",
                        "Walkthrough dismissed, but Claude was not told",
                        "The session could not be ended: " + err.getMessage(),
                        com.intellij.notification.NotificationType.WARNING),
                    project);
            }
        });
    }

    /** The rail panel is always live; the inline card layers on top when visible. */
    private void applyInlineVisible(boolean visible) {
        com.intellij.openapi.application.ApplicationManager.getApplication().invokeLater(() -> {
            if (visible) {
                inline.attach();
            } else {
                inline.detach();
            }
        });
    }

    @Override public void dispose() {
        inline.detach();
        client.stop();
    }
}
