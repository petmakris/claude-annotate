package com.petros.ireview;

import com.intellij.diff.DiffContentFactory;
import com.intellij.diff.DiffManager;
import com.intellij.diff.contents.DiffContent;
import com.intellij.diff.requests.SimpleDiffRequest;
import com.intellij.notification.NotificationGroupManager;
import com.intellij.notification.NotificationType;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.fileEditor.FileDocumentManager;
import com.intellij.openapi.progress.ProgressIndicator;
import com.intellij.openapi.progress.ProgressManager;
import com.intellij.openapi.progress.Task;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vcs.FilePath;
import com.intellij.openapi.vcs.VcsException;
import com.intellij.openapi.vcs.changes.ChangeListManager;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.vcsUtil.VcsUtil;
import git4idea.GitFileRevision;
import git4idea.GitRevisionNumber;
import git4idea.GitUtil;
import git4idea.commands.Git;
import git4idea.commands.GitCommand;
import git4idea.commands.GitCommandResult;
import git4idea.commands.GitLineHandler;
import git4idea.repo.GitRepository;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Drives the Smart Diff keys: works out which two versions of a file to show,
 * loads them, and hands them to the platform's diff viewer.
 *
 * The walk itself is {@link DiffHistory}; this class is the part that talks to
 * git and the IDE. Each file's position in its walk is remembered for the life
 * of the project, so repeated presses step further back through history rather
 * than re-showing the same diff.
 *
 * One deliberate exception to remembering: when a file's modified state has
 * flipped since we last showed it — you edited it, or you committed it — the
 * walk restarts. After changing something, the thing you want to see is that
 * change, not the next commit down from wherever you left off.
 */
public final class SmartDiffService {

    /** Deep enough that walking hits the wrap-around long before the limit. */
    private static final int MAX_REVISIONS = 200;

    private static final String NOTIFY_GROUP = "Claude IDE Review";

    /** Where a file's walk stood, and the modified state it stood in. */
    private record Walk(int depth, boolean dirty) {}

    private final Project project;
    private final Map<String, Walk> walks = new ConcurrentHashMap<>();

    public SmartDiffService(@NotNull Project project) {
        this.project = project;
    }

    public static SmartDiffService get(@NotNull Project project) {
        return project.getService(SmartDiffService.class);
    }

    // ---- the two entry points --------------------------------------------

    /** One press of Smart Diff. {@code forward} walks back through history; false walks toward the working copy. */
    public void step(@NotNull VirtualFile file, boolean forward) {
        background("Diffing " + file.getName(), () -> {
            GitRepository repo = GitUtil.getRepositoryForFile(project, file);
            FilePath path = VcsUtil.getFilePath(file);
            boolean dirty = isDirty(file);
            DiffHistory history = new DiffHistory(revisions(repo, path), dirty);

            if (history.isEmpty()) {
                info(history.levels() == 0
                    ? file.getName() + " has never been committed — there is no earlier version to compare against."
                    : file.getName() + " is unchanged and has only one commit — nothing to compare.");
                return;
            }

            int depth = nextDepth(file, history, dirty, forward);
            walks.put(file.getPath(), new Walk(depth, dirty));

            DiffHistory.Step step = history.at(depth);
            show(file,
                 contentAt(path, step.left()), shortRef(step.left()),
                 step.right() == null ? null : contentAt(path, step.right()),
                 step.right() == null ? "Working copy" : shortRef(step.right()));
        });
    }

    /** One press of Diff against Base Branch: working copy versus the resolved base ref, no picker. */
    public void diffAgainstBase(@NotNull VirtualFile file) {
        background("Diffing " + file.getName() + " against base branch", () -> {
            GitRepository repo = GitUtil.getRepositoryForFile(project, file);
            FilePath path = VcsUtil.getFilePath(file);

            Optional<String> base = BaseBranchResolver.resolve(
                DiffSettings.get(project).baseBranch(), originHead(repo), branchNames(repo));

            if (base.isEmpty()) {
                info("No base branch found. Tried origin/HEAD and "
                    + String.join(", ", BaseBranchResolver.candidates())
                    + ". Name one in Settings → Tools → Claude IDE Review.");
                return;
            }
            show(file, contentAt(path, base.get()), base.get(), null, "Working copy");
        });
    }

    // ---- deciding where the walk goes next --------------------------------

    private int nextDepth(VirtualFile file, DiffHistory history, boolean dirty, boolean forward) {
        Walk previous = walks.get(file.getPath());
        if (previous == null || previous.dirty() != dirty) {
            return history.firstDepth();
        }
        return forward ? history.advance(previous.depth()) : history.back(previous.depth());
    }

    /**
     * Modified relative to HEAD. Unsaved editor content counts: the diff should
     * show what is on screen, which is what the user just typed.
     */
    private boolean isDirty(VirtualFile file) {
        return ChangeListManager.getInstance(project).getChange(file) != null
            || FileDocumentManager.getInstance().isFileModified(file);
    }

    // ---- git ---------------------------------------------------------------

    private List<String> revisions(GitRepository repo, FilePath path) throws VcsException {
        GitLineHandler handler = new GitLineHandler(project, repo.getRoot(), GitCommand.LOG);
        handler.addParameters("--max-count=" + MAX_REVISIONS, "--format=%H", "--", relativePath(repo, path));
        GitCommandResult result = Git.getInstance().runCommand(handler);
        if (!result.success()) {
            throw new VcsException(result.getErrorOutputAsJoinedString());
        }
        return result.getOutput().stream().map(String::trim).filter(s -> !s.isEmpty()).toList();
    }

    /** What origin/HEAD points at, or empty — a clone made with --single-branch has none. */
    private String originHead(GitRepository repo) {
        GitLineHandler handler = new GitLineHandler(project, repo.getRoot(), GitCommand.REV_PARSE);
        handler.addParameters("--abbrev-ref", "origin/HEAD");
        GitCommandResult result = Git.getInstance().runCommand(handler);
        return result.success() ? result.getOutputAsJoinedString().trim() : "";
    }

    private Set<String> branchNames(GitRepository repo) {
        Set<String> names = new LinkedHashSet<>();
        repo.getBranches().getLocalBranches().forEach(b -> names.add(b.getName()));
        repo.getBranches().getRemoteBranches().forEach(b -> names.add(b.getName()));
        return names;
    }

    private byte[] contentAt(FilePath path, String revision) throws VcsException {
        return new GitFileRevision(project, path, new GitRevisionNumber(revision)).loadContent();
    }

    private static String relativePath(GitRepository repo, FilePath path) {
        String relative = GitUtil.getRelativePath(repo.getRoot().getPath(), path);
        return relative == null ? path.getPath() : relative;
    }

    /** Commit hashes shorten; branch names are already short and must not be truncated. */
    private static String shortRef(String revision) {
        boolean looksLikeAHash = revision.length() == 40 && revision.chars().allMatch(
            c -> (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));
        return looksLikeAHash ? revision.substring(0, 8) : revision;
    }

    // ---- showing it ---------------------------------------------------------

    /** A null {@code rightBytes} means the live working copy, which stays editable in the viewer. */
    private void show(VirtualFile file,
                      byte[] leftBytes, String leftTitle,
                      @Nullable byte[] rightBytes, String rightTitle) {
        ApplicationManager.getApplication().invokeLater(() -> {
            try {
                DiffContentFactory factory = DiffContentFactory.getInstance();
                DiffContent left = factory.createFromBytes(project, leftBytes, file);
                DiffContent right = rightBytes == null
                    ? factory.create(project, file)
                    : factory.createFromBytes(project, rightBytes, file);
                DiffManager.getInstance().showDiff(project, new SimpleDiffRequest(
                    file.getName() + " — " + leftTitle + " → " + rightTitle,
                    left, right, leftTitle, rightTitle));
            } catch (Exception e) {
                warn(message(e));
            }
        }, project.getDisposed());
    }

    // ---- plumbing ------------------------------------------------------------

    @FunctionalInterface
    private interface GitWork {
        void run() throws Exception;
    }

    private void background(String title, GitWork work) {
        ProgressManager.getInstance().run(new Task.Backgroundable(project, title, true) {
            @Override public void run(@NotNull ProgressIndicator indicator) {
                try {
                    work.run();
                } catch (Exception e) {
                    warn(message(e));
                }
            }
        });
    }

    private static String message(Exception e) {
        return e.getMessage() == null || e.getMessage().isBlank() ? e.toString() : e.getMessage();
    }

    private void info(String text) {
        notify(text, NotificationType.INFORMATION);
    }

    private void warn(String text) {
        notify(text, NotificationType.WARNING);
    }

    private void notify(String text, NotificationType type) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup(NOTIFY_GROUP)
            .createNotification(text, type)
            .notify(project);
    }
}
