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
 * Three parts, kept apart on purpose. {@link DiffHistory} decides what a given
 * depth shows. {@link DiffWalk} decides which depth the next press lands on, and
 * when a walk is stale enough to restart. This class is the only one that talks
 * to git and to the IDE.
 *
 * Splitting the second part out is not tidiness. The rule for resuming a walk is
 * where the reported bug lived, and it could not be tested while it sat inside a
 * class that needs a running IDE to instantiate.
 */
public final class SmartDiffService {

    /** Deep enough that walking hits the wrap-around long before the limit. */
    private static final int MAX_REVISIONS = 200;

    private static final String NOTIFY_GROUP = "Claude IDE Review";

    private final Project project;
    /** Where each file's walk stands. The rule for reading it is {@link DiffWalk}. */
    private final Map<String, DiffWalk.Stop> walks = new ConcurrentHashMap<>();

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

            long now = System.currentTimeMillis();
            int depth = DiffWalk.nextDepth(walks.get(file.getPath()), history, dirty, forward, now);
            walks.put(file.getPath(), new DiffWalk.Stop(depth, dirty, now));

            DiffHistory.Step step = history.at(depth);
            show(file, DiffHistory.describe(depth),
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
                info("No base branch found. Tried " + BaseBranchResolver.PIN
                    + ", origin/HEAD and "
                    + String.join(", ", BaseBranchResolver.candidates())
                    + ". Pin one with `@git pr-base --pin`, or name one in"
                    + " Settings → Tools → Claude IDE Review.");
                return;
            }
            show(file, "base branch", contentAt(path, base.get()), base.get(), null, "Working copy");
        });
    }

    /**
     * One press of Compare with HEAD: the committed version of this file against
     * the working copy, with no walk and no memory.
     *
     * Deliberately does not touch {@link #walks}. Its whole value is being the
     * one diff key whose answer does not depend on which keys were pressed
     * before it. A clean file is reported rather than shown: two identical sides
     * in a diff viewer look like a broken tool, and "no uncommitted changes" is
     * the answer the person was actually after.
     */
    public void diffAgainstHead(@NotNull VirtualFile file) {
        background("Diffing " + file.getName() + " against HEAD", () -> {
            GitRepository repo = GitUtil.getRepositoryForFile(project, file);
            FilePath path = VcsUtil.getFilePath(file);
            List<String> revisions = revisions(repo, path);

            if (revisions.isEmpty()) {
                info(file.getName() + " has never been committed — there is no HEAD version to compare against.");
                return;
            }
            if (!isDirty(file)) {
                info(file.getName() + " has no uncommitted changes — it already matches HEAD.");
                return;
            }
            show(file, "uncommitted", contentAt(path, revisions.get(0)), "HEAD", null, "Working copy");
        });
    }

    // ---- reading the file's state -----------------------------------------

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

    /**
     * A null {@code rightBytes} means the live working copy, which stays editable in the viewer.
     *
     * {@code where} names the position the walk is at — "uncommitted", "last
     * commit", "3 commits back", "base branch". Two commit hashes alone never
     * told anyone whether they were looking at their own change or somewhere the
     * walk had drifted to, which is the whole reason this parameter exists.
     */
    private void show(VirtualFile file, String where,
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
                    file.getName() + " — " + where + " — " + leftTitle + " → " + rightTitle,
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
