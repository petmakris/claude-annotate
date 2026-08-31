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

    private final WalkthroughSessionClient client;
    private final WalkthroughController controller;
    private final WalkthroughInlay inline;

    public WalkthroughService(Project project) {
        String cwd = project.getBasePath();
        // The URL supplier re-reads on every failed discovery poll, so a
        // server restart (or the webcompanion daemon appearing where the
        // legacy per-skill server used to be) is picked up without an IDE
        // restart. Previously this resolved once here and was baked into the
        // client at construction — a daemon restart on a new port stranded
        // the panel until the IDE itself restarted.
        this.client = new WalkthroughSessionClient(
            () -> ServerDiscovery.resolve(
                Path.of(System.getProperty("user.home")),
                legacyServerJsonPath(),
                "http://127.0.0.1:54660"),
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
                com.intellij.openapi.application.ApplicationManager.getApplication()
                    .invokeLater(() -> controller.setDoc(doc));
            }
        });
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

    /**
     * The legacy walkthrough server's discovery file,
     * ~/.claude/walkthrough/server.json — the skill writes it on server start
     * and rewrites it on every restart. {@link ServerDiscovery} tries the
     * webcompanion daemon's own config first and falls back to this.
     */
    private static Path legacyServerJsonPath() {
        return Path.of(System.getProperty("user.home"), ".claude", "walkthrough", "server.json");
    }
}
