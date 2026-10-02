package com.petros.ireview;

import com.intellij.icons.AllIcons;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import org.jetbrains.annotations.NotNull;

/**
 * Title-bar zoom controls for the "Review Annotations" tool window — bumps
 * {@link PanelZoom}'s persisted delta, which every open
 * {@link ThreadConversationView} picks up immediately via its zoom listener.
 */
final class ZoomActions {

    private ZoomActions() {}

    static final class In extends AnAction {
        In() { super("Increase Content Font Size", "Make the reply text bigger", AllIcons.General.ZoomIn); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { PanelZoom.increase(); }

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(PanelZoom.canIncrease());
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }

    static final class Out extends AnAction {
        Out() { super("Decrease Content Font Size", "Make the reply text smaller", AllIcons.General.ZoomOut); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { PanelZoom.decrease(); }

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(PanelZoom.canDecrease());
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }

    static final class Reset extends AnAction {
        Reset() { super("Reset Content Font Size", "Back to the default size", AllIcons.Actions.Rollback); }

        @Override public void actionPerformed(@NotNull AnActionEvent e) { PanelZoom.reset(); }

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(PanelZoom.delta() != 0);
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() { return ActionUpdateThread.EDT; }
    }
}
