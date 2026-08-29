package com.petros.ireview;

import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vfs.VirtualFile;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

/**
 * The three diff keys. All of them act on the file in the active editor, which
 * is the whole point — the question being answered is "how has THIS file
 * changed", asked without leaving it.
 */
public final class SmartDiffActions {

    private SmartDiffActions() {}

    public static final String FORWARD_ID = "com.petros.ireview.SmartDiff";
    public static final String BACK_ID = "com.petros.ireview.SmartDiffBack";
    public static final String BASE_ID = "com.petros.ireview.DiffAgainstBase";

    private abstract static class Base extends AnAction {

        @Override public void update(@NotNull AnActionEvent e) {
            e.getPresentation().setEnabled(e.getProject() != null && fileIn(e) != null);
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() {
            return ActionUpdateThread.BGT;
        }

        /** Directories and files outside the local filesystem have no diff worth showing. */
        static @Nullable VirtualFile fileIn(AnActionEvent e) {
            VirtualFile file = e.getData(CommonDataKeys.VIRTUAL_FILE);
            return file != null && !file.isDirectory() && file.isInLocalFileSystem() ? file : null;
        }

        @Override public void actionPerformed(@NotNull AnActionEvent e) {
            Project project = e.getProject();
            VirtualFile file = fileIn(e);
            if (project != null && file != null) {
                run(SmartDiffService.get(project), file);
            }
        }

        abstract void run(SmartDiffService service, VirtualFile file);
    }

    /** Uncommitted change if there is one, else the last commit, else one further back each press. */
    public static final class Forward extends Base {
        @Override void run(SmartDiffService service, VirtualFile file) {
            service.step(file, true);
        }
    }

    /** One step back toward the working copy. */
    public static final class Back extends Base {
        @Override void run(SmartDiffService service, VirtualFile file) {
            service.step(file, false);
        }
    }

    /** Working copy against the resolved base branch, with no branch picker. */
    public static final class AgainstBase extends Base {
        @Override void run(SmartDiffService service, VirtualFile file) {
            service.diffAgainstBase(file);
        }
    }
}
