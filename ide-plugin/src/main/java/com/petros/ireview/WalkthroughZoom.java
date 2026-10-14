package com.petros.ireview;

import com.intellij.icons.AllIcons;
import com.intellij.ide.util.PropertiesComponent;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import org.jetbrains.annotations.NotNull;

import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Persisted size of everything in the Walkthrough panel, as a percentage of
 * the IDE's own label font. {@link WalkthroughPanel} multiplies every font,
 * padding and disc size by {@link #factor()}, and rebuilds when it changes.
 * Stored once per IDE, like {@link PanelZoom} for the review panel.
 */
final class WalkthroughZoom {

    private static final String KEY = "ireview.walkthrough.zoom.percent";
    static final int DEFAULT = 100;
    private static final int MIN = 60;
    private static final int MAX = 200;
    private static final int STEP = 10;

    private static final CopyOnWriteArrayList<Runnable> listeners = new CopyOnWriteArrayList<>();

    private WalkthroughZoom() {}

    static final String IN_ID = "com.petros.ireview.WalkthroughZoomIn";
    static final String OUT_ID = "com.petros.ireview.WalkthroughZoomOut";
    static final String RESET_ID = "com.petros.ireview.WalkthroughZoomReset";

    static int percent() {
        return PropertiesComponent.getInstance().getInt(KEY, DEFAULT);
    }

    static float factor() {
        return percent() / 100f;
    }

    private static void set(int value) {
        int v = Math.max(MIN, Math.min(MAX, value));
        if (v == percent()) return;
        PropertiesComponent.getInstance().setValue(KEY, v, DEFAULT);
        for (Runnable l : listeners) l.run();
    }

    static void addListener(Runnable r) { listeners.add(r); }

    static void removeListener(Runnable r) { listeners.remove(r); }

    static final class In extends AnAction {
        In() { super("Walkthrough: Bigger Text", "Make the walkthrough panel's text bigger", AllIcons.General.ZoomIn); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { set(percent() + STEP); }

        @Override public void update(@NotNull AnActionEvent e) { e.getPresentation().setEnabled(percent() < MAX); }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }

    static final class Out extends AnAction {
        Out() { super("Walkthrough: Smaller Text", "Make the walkthrough panel's text smaller", AllIcons.General.ZoomOut); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { set(percent() - STEP); }

        @Override public void update(@NotNull AnActionEvent e) { e.getPresentation().setEnabled(percent() > MIN); }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }

    static final class Reset extends AnAction {
        Reset() { super("Walkthrough: Reset Text Size", "Back to the IDE's own font size", AllIcons.Actions.Rollback); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { set(DEFAULT); }

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(percent() != DEFAULT);
            e.getPresentation().setText("Walkthrough: Reset Text Size (now " + percent() + "%)");
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }
}
