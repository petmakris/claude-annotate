package com.petros.ireview;

import com.intellij.diff.DiffDialogHints;
import com.intellij.diff.DiffManagerEx;
import com.intellij.diff.chains.DiffRequestChain;
import com.intellij.diff.chains.SimpleDiffRequestChain;
import com.intellij.diff.editor.ChainDiffVirtualFile;
import com.intellij.diff.editor.DiffEditorTabFilesManager;
import com.intellij.diff.requests.DiffRequest;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.options.advanced.AdvancedSettings;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.WindowWrapper;
import com.intellij.openapi.util.registry.Registry;
import com.intellij.openapi.vfs.VirtualFile;
import org.jetbrains.annotations.NotNull;

import java.util.concurrent.atomic.AtomicReference;

/**
 * The one place a Smart Diff result is shown, replaced on every press.
 *
 * <b>Why this is not just {@code DiffManager.showDiff}.</b> That call cannot
 * reuse anything. Following it down, {@code DiffManagerImpl.showDiffBuiltin}
 * either constructs a brand new {@link ChainDiffVirtualFile} and hands it to
 * {@code FileEditorManagerImpl.openFile}, or constructs a brand new
 * {@code DiffWindow}. A second press therefore has no way to land on the
 * surface the first one opened — a new tab or a new window every time, until
 * the screen is full of them.
 *
 * So the surface is owned here: the previous one is closed before the next is
 * opened, and a session of walking a file's history leaves exactly one diff on
 * screen rather than one per keystroke.
 *
 * <b>The user's window-or-tab preference is respected.</b> {@link #prefersTab}
 * repeats the platform's own test, and that duplication is the cost of owning
 * the surface — the platform is still the source of truth, and this has to be
 * rechecked if that routing changes. It leaves out one term of the platform's
 * condition, {@code isFromDialog}, which is private and only fires for a diff
 * opened from inside a modal dialog. Every key here comes from the editor, so
 * that term is always false for us.
 *
 * Note the two branches are not interchangeable: passing a window consumer to
 * {@code showDiffBuiltin} forces the window path, which is why the tab branch
 * cannot use one and has to build its own {@link ChainDiffVirtualFile}.
 */
final class DiffSurface {

    /** IntelliJ's setting, Settings → Advanced Settings → Version Control. */
    private static final String AS_EDITOR_TAB = "show.diff.as.editor.tab";
    /** IntelliJ's registry key for "show diffs in a frame, never a tab". */
    private static final String AS_FRAME = "show.diff.as.frame";

    private final Project project;
    private final AtomicReference<WindowWrapper> window = new AtomicReference<>();
    private final AtomicReference<VirtualFile> tab = new AtomicReference<>();

    DiffSurface(@NotNull Project project) {
        this.project = project;
    }

    /** Close whatever the last press opened, then show this. Must run on the EDT. */
    void replaceWith(@NotNull DiffRequest request) {
        closePrevious();

        DiffRequestChain chain = new SimpleDiffRequestChain(request);
        String title = request.getTitle() == null ? "Diff" : request.getTitle();

        if (prefersTab()) {
            ChainDiffVirtualFile file = new ChainDiffVirtualFile(chain, title);
            tab.set(file);
            DiffEditorTabFilesManager.getInstance(project).showDiffFile(file, true);
        } else {
            DiffManagerEx.getInstance().showDiffBuiltin(project, chain,
                new DiffDialogHints(DiffDialogHints.DEFAULT.getMode(), null, window::set));
        }
    }

    /**
     * Closing is best-effort on purpose. The person may have closed the diff
     * themselves, or moved its tab to another split, and neither is a fault
     * worth interrupting them over — the next press simply opens a fresh one.
     */
    private void closePrevious() {
        WindowWrapper previousWindow = window.getAndSet(null);
        if (previousWindow != null && !previousWindow.isDisposed()) {
            previousWindow.close();
        }
        VirtualFile previousTab = tab.getAndSet(null);
        if (previousTab != null) {
            FileEditorManager.getInstance(project).closeFile(previousTab);
        }
    }

    private static boolean prefersTab() {
        return AdvancedSettings.getBoolean(AS_EDITOR_TAB) && !Registry.is(AS_FRAME);
    }
}
