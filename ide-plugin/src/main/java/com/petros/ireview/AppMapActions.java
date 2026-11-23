package com.petros.ireview;

import com.intellij.ide.IdeEventQueue;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.Disposable;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.openapi.wm.WindowManager;
import org.jetbrains.annotations.NotNull;

import javax.swing.*;
import java.awt.*;
import java.awt.event.KeyEvent;
import java.nio.file.Path;
import java.util.List;

/**
 * Cmd+Shift+M: show the app map over the IDE with the open file's part lit.
 *
 * A tap (the key released within {@link #TAP_MS}) leaves the map open until
 * Escape, Cmd+Shift+M again, a click outside the drawing, or Close. A hold closes it
 * when Cmd, Shift or M is released. While open, every key press is taken by the map:
 * Enter opens the file's detail map, Backspace goes back, and F, B, T, U and W pick what it lights (this file, the
 * branch, the open tabs, who uses the file, the walkthrough). While a walkthrough runs the map opens on its steps.
 */
public final class AppMapActions {

    private AppMapActions() {}

    public static final String SHOW_ID = "com.petros.ireview.AppMapShow";
    static final long TAP_MS = 300;

    private static final Logger LOG = Logger.getInstance(AppMapActions.class);
    static final AppMapStore STORE = new AppMapStore(AppMapStore.defaultHome());

    /** What one showing needs to know about its key: pressed at, and whether it was a tap. */
    static final class Gesture {
        private final long shownAtNanos;
        private boolean decided;
        private boolean sticky;

        Gesture(long shownAtNanos, boolean byKey) {
            this.shownAtNanos = shownAtNanos;
            this.decided = !byKey;
            this.sticky = !byKey;
        }

        /** A release of alt or M. True when the map should close now (a hold ending). */
        boolean released(long nowNanos) {
            if (decided) return false;
            decided = true;
            sticky = (nowNanos - shownAtNanos) / 1_000_000 < TAP_MS;
            return !sticky;
        }

        /** Whether the map now stays until closed, so another Cmd+Shift+M closes it. */
        boolean sticky() { return sticky; }
    }

    private static final class Session {
        AppMapOverlay overlay;
        Disposable scope;
        Gesture gesture;
    }

    private static Session current;

    public static final class Show extends AnAction {
        @Override public void actionPerformed(@NotNull AnActionEvent e) {
            Project project = e.getProject();
            if (project == null) return;
            if (current != null) {
                if (current.gesture.sticky()) close(current);
                return; // a held key repeating, not a second press
            }
            JRootPane root = rootPaneFor(project);
            if (root == null) return;
            VirtualFile file = e.getData(CommonDataKeys.VIRTUAL_FILE);
            if (file == null) {
                VirtualFile[] selected = FileEditorManager.getInstance(project).getSelectedFiles();
                if (selected.length > 0) file = selected[0];
            }
            show(project, root, file, e.getInputEvent() instanceof KeyEvent);
        }

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(e.getProject() != null);
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() {
            return ActionUpdateThread.BGT;
        }
    }

    /** Opens the map as a click does (it stays until closed), from the editor's pill. */
    static void open(Project project, VirtualFile file) {
        if (current != null) return;
        JRootPane root = rootPaneFor(project);
        if (root != null) show(project, root, file, false);
    }

    private static JRootPane rootPaneFor(Project project) {
        Component focus = KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
        JRootPane root = focus == null ? null : SwingUtilities.getRootPane(focus);
        if (root != null) return root;
        JFrame frame = WindowManager.getInstance().getFrame(project);
        return frame == null ? null : frame.getRootPane();
    }

    private static void show(Project project, JRootPane root, VirtualFile file, boolean byKey) {
        long shownAt = System.nanoTime();
        String base = project.getBasePath();
        AppMapOverlay.Input input;
        try {
            var found = base == null ? java.util.Optional.<AppMapStore.Found>empty() : STORE.find(Path.of(base));
            if (found.isEmpty()) {
                input = new AppMapOverlay.Input(null, null,
                    "No app map for this project. Run /app-map in Claude Code in this repo.", null, List.of(), null);
            } else {
                AppMapStore.Found f = found.get();
                String rel = file == null ? null : repoRelative(f.repoRoot(), file.getPath());
                String repo = f.map().repoNameFor(f.remote());
                AppMapFile.Place place = rel == null ? null : f.map().place(rel, repo);
                List<String> owners = rel == null ? List.of() : CodeOwners.at(f.repoRoot()).owners(rel);
                String module = rel == null ? null : f.map().module(rel, repo);
                AppMapSources sources = new AppMapSources(project, STORE, f, file);
                AppMapOverlay.Mode start = sources.has(AppMapOverlay.Mode.WALK) ? AppMapOverlay.Mode.WALK : AppMapOverlay.Mode.FILE;
                input = new AppMapOverlay.Input(file == null ? null : file.getName(), f.map(), null, place, owners, module,
                    sources, start);
            }
        } catch (AppMapFile.Unreadable u) {
            LOG.warn("The app map could not be read: " + u.getMessage(), u);
            input = new AppMapOverlay.Input(null, null,
                "The app map could not be read: " + u.getMessage() + ". Run /app-map to rebuild it.", null, List.of(), null);
        } catch (RuntimeException ex) {
            LOG.warn("The app map failed to load", ex);
            input = new AppMapOverlay.Input(null, null,
                "The app map could not be read: " + ex.getMessage() + ". Run /app-map to rebuild it.", null, List.of(), null);
        }

        Session s = new Session();
        s.scope = Disposer.newDisposable("app map overlay");
        Disposer.register(project, s.scope);
        s.gesture = new Gesture(shownAt, byKey);
        s.overlay = new AppMapOverlay(root.getLayeredPane(), input, () -> end(s));
        current = s;
        IdeEventQueue.getInstance().addDispatcher(ev -> dispatch(s, ev), s.scope);
        s.overlay.open();
    }

    /** Repo-relative path with forward slashes, or null when the file is outside the repo. */
    static String repoRelative(Path repoRoot, String filePath) {
        try {
            Path rel = repoRoot.toAbsolutePath().normalize().relativize(Path.of(filePath).toAbsolutePath().normalize());
            if (rel.startsWith("..") || rel.isAbsolute()) return null;
            return rel.toString().replace('\\', '/');
        } catch (IllegalArgumentException ex) {
            return null;
        }
    }

    private static boolean dispatch(Session s, AWTEvent ev) {
        if (!(ev instanceof KeyEvent ke)) return false;
        int id = ke.getID();
        if (id == KeyEvent.KEY_RELEASED) {
            int c = ke.getKeyCode();
            if ((c == KeyEvent.VK_M || c == KeyEvent.VK_META || c == KeyEvent.VK_SHIFT) && s.gesture.released(System.nanoTime())) close(s);
            return false;
        }
        if (id != KeyEvent.KEY_PRESSED && id != KeyEvent.KEY_TYPED) return false;
        if (id == KeyEvent.KEY_PRESSED) {
            switch (ke.getKeyCode()) {
                case KeyEvent.VK_ESCAPE -> close(s);
                case KeyEvent.VK_ENTER -> s.overlay.enter();
                case KeyEvent.VK_BACK_SPACE -> s.overlay.back();
                case KeyEvent.VK_M -> { if (ke.isMetaDown() && ke.isShiftDown() && s.gesture.sticky()) close(s); }
                default -> {
                    if (!ke.isMetaDown() && !ke.isControlDown() && !ke.isAltDown()) s.overlay.mode(AppMapOverlay.Mode.forKey(ke.getKeyCode()));
                }
            }
        }
        ke.consume();
        return true;
    }

    private static void close(Session s) {
        s.overlay.close(); // calls end(s)
    }

    private static void end(Session s) {
        if (current == s) current = null;
        Disposer.dispose(s.scope);
    }
}
