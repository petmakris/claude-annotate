package com.petros.ireview;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.application.ModalityState;
import com.intellij.openapi.application.ReadAction;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.fileEditor.FileEditorManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vfs.LocalFileSystem;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.psi.PsiClass;
import com.intellij.psi.PsiClassOwner;
import com.intellij.psi.PsiFile;
import com.intellij.psi.PsiManager;
import com.intellij.psi.search.GlobalSearchScope;
import com.intellij.psi.search.searches.ReferencesSearch;
import com.intellij.util.concurrency.AppExecutorUtil;
import git4idea.commands.Git;
import git4idea.commands.GitCommand;
import git4idea.commands.GitCommandResult;
import git4idea.commands.GitLineHandler;
import git4idea.repo.GitRepository;
import git4idea.repo.GitRepositoryManager;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;

/**
 * The files behind each mode of the app map, read when the mode is first picked: the branch's changes from git, the
 * open tabs, the files that use the open file's classes (IntelliJ's own usage search, in the background) and the
 * steps of the walkthrough that is running. Each file is placed on the map in its own repo.
 */
final class AppMapSources implements AppMapOverlay.Sources {

    private static final Logger LOG = Logger.getInstance(AppMapSources.class);
    /** The usage search stops after this many files: enough to light every part that uses a class. */
    static final int MAX_USERS = 3000;

    private final Project project;
    private final AppMapStore store;
    private final AppMapStore.Found found;
    private final VirtualFile file;
    private final Map<String, Optional<AppMapStore.Found>> byDir = new HashMap<>();

    AppMapSources(Project project, AppMapStore store, AppMapStore.Found found, VirtualFile file) {
        this.project = project;
        this.store = store;
        this.found = found;
        this.file = file;
    }

    @Override public boolean has(AppMapOverlay.Mode m) {
        return switch (m) {
            case FILE, BRANCH, TABS -> true;
            case USERS -> file != null;
            case WALK -> WalkthroughService.get(project).controller().size() > 0;
        };
    }

    @Override public String loading(AppMapOverlay.Mode m) {
        return switch (m) {
            case BRANCH -> "Reading the branch…";
            case USERS -> "Searching who uses " + (file == null ? "this file" : file.getName()) + "…";
            default -> m.label;
        };
    }

    @Override public void load(AppMapOverlay.Mode m, Consumer<AppMapOverlay.Result> done) {
        switch (m) {
            case FILE -> done.accept(AppMapOverlay.Result.note(null, null));
            case TABS -> done.accept(tabs());
            case WALK -> done.accept(walk());
            case BRANCH -> ApplicationManager.getApplication().executeOnPooledThread(() -> {
                AppMapOverlay.Result r;
                try {
                    r = branch();
                } catch (RuntimeException e) {
                    LOG.warn("Reading the branch for the app map failed", e);
                    r = AppMapOverlay.Result.note("Branch", "could not be read: " + e.getMessage());
                }
                AppMapOverlay.Result out = r;
                ApplicationManager.getApplication().invokeLater(() -> done.accept(out), ModalityState.any());
            });
            case USERS -> users(done);
        }
    }

    // ---- placing files ------------------------------------------------------

    /** Where a file sits on this map, in its own repo; a file of a repo the map does not span is on no part. */
    AppMapFile.Place placeOf(VirtualFile vf) {
        if (vf == null || vf.getParent() == null) return null;
        String dir = vf.getParent().getPath();
        Optional<AppMapStore.Found> f = byDir.computeIfAbsent(dir, d -> {
            try {
                return store.find(Path.of(d));
            } catch (AppMapFile.Unreadable | RuntimeException e) {
                return Optional.empty();
            }
        });
        if (f.isEmpty() || !f.get().map().name().equals(found.map().name())) return null;
        String rel = AppMapActions.repoRelative(f.get().repoRoot(), vf.getPath());
        if (rel == null) return null;
        return found.map().place(rel, found.map().repoNameFor(f.get().remote()));
    }

    private List<AppMapFile.Place> places(Iterable<VirtualFile> files) {
        List<AppMapFile.Place> out = new ArrayList<>();
        for (VirtualFile vf : files) {
            AppMapFile.Place p = placeOf(vf);
            if (p != null && p.part() != null) out.add(p);
        }
        return out;
    }

    // ---- the modes ------------------------------------------------------------

    private AppMapOverlay.Result tabs() {
        VirtualFile[] open = FileEditorManager.getInstance(project).getOpenFiles();
        List<AppMapFile.Place> ps = places(List.of(open));
        return new AppMapOverlay.Result(ps, -1, "Open tabs", ps.isEmpty() ? "none on the map" : "darker with more tabs");
    }

    private AppMapOverlay.Result walk() {
        WalkthroughController c = WalkthroughService.get(project).controller();
        VirtualFile base = project.getBaseDir();
        List<AppMapFile.Place> ps = new ArrayList<>();
        for (WalkthroughStep step : c.doc().steps()) {
            VirtualFile vf = base == null || step.file() == null ? null : base.findFileByRelativePath(step.file());
            AppMapFile.Place p = placeOf(vf);
            ps.add(p == null ? new AppMapFile.Place(null, null, false) : p);
        }
        String title = c.current().map(s -> "Step " + (c.index() + 1) + " of " + c.size() + " · " + s.title()).orElse("Walkthrough");
        return new AppMapOverlay.Result(ps, c.index(), title, null);
    }

    private AppMapOverlay.Result branch() {
        VirtualFile root = LocalFileSystem.getInstance().findFileByNioFile(found.repoRoot());
        GitRepository repo = root == null ? null : GitRepositoryManager.getInstance(project).getRepositoryForRootQuick(root);
        if (repo == null) return AppMapOverlay.Result.note("Branch", "this project is not a git repository");
        Optional<String> base = BaseBranchResolver.resolve(DiffSettings.get(project).baseBranch(),
            SmartDiffService.originHead(project, repo), SmartDiffService.branchNames(repo));
        String name = repo.getCurrentBranchName() == null ? "HEAD" : repo.getCurrentBranchName();
        if (base.isEmpty()) return AppMapOverlay.Result.note("Branch " + name, "no base branch found");
        String against = BaseBranchResolver.shortName(base.get());
        Set<String> rel = new LinkedHashSet<>();
        // Committed and uncommitted changes since the branch left its base, then new files git does not track yet.
        List<String> diff = git(repo, GitCommand.DIFF, "--name-only", "--merge-base", base.get());
        if (diff == null) {
            diff = git(repo, GitCommand.DIFF, "--name-only", base.get() + "...HEAD");
            List<String> local = git(repo, GitCommand.DIFF, "--name-only", "HEAD");
            if (diff == null) return AppMapOverlay.Result.note("Branch " + name, "git diff against " + against + " failed");
            if (local != null) diff.addAll(local);
        }
        rel.addAll(diff);
        List<String> untracked = git(repo, GitCommand.LS_FILES, "--others", "--exclude-standard");
        if (untracked != null) rel.addAll(untracked);
        String repoName = found.map().repoNameFor(found.remote());
        List<AppMapFile.Place> ps = new ArrayList<>();
        for (String r : rel) {
            if (r.isBlank()) continue;
            AppMapFile.Place p = found.map().place(r.trim(), repoName);
            if (p.part() != null) ps.add(p);
        }
        String title = "Branch " + name + " against " + against;
        String note = rel.isEmpty() ? "no changes" : ps.isEmpty() ? "no change is on the map" : null;
        return new AppMapOverlay.Result(ps, -1, title, note);
    }

    private List<String> git(GitRepository repo, GitCommand command, String... params) {
        GitLineHandler h = new GitLineHandler(project, repo.getRoot(), command);
        h.setSilent(true);
        h.addParameters(params);
        GitCommandResult r = Git.getInstance().runCommand(h);
        return r.success() ? new ArrayList<>(r.getOutput()) : null;
    }

    private void users(Consumer<AppMapOverlay.Result> done) {
        String name = file.getName();
        ReadAction.nonBlocking(() -> {
                Set<VirtualFile> seen = new LinkedHashSet<>();
                PsiFile pf = PsiManager.getInstance(project).findFile(file);
                if (!(pf instanceof PsiClassOwner owner)) return null;
                for (PsiClass c : owner.getClasses()) {
                    ReferencesSearch.search(c, GlobalSearchScope.projectScope(project)).forEach(ref -> {
                        PsiFile in = ref.getElement().getContainingFile();
                        VirtualFile vf = in == null ? null : in.getVirtualFile();
                        if (vf != null && !vf.equals(file)) seen.add(vf);
                        return seen.size() < MAX_USERS;
                    });
                }
                return seen;
            })
            .inSmartMode(project)
            .finishOnUiThread(ModalityState.any(), seen -> {
                if (seen == null) {
                    done.accept(AppMapOverlay.Result.note("Who uses " + name, "works on classes only"));
                    return;
                }
                List<AppMapFile.Place> ps = places(seen);
                String here = file == null ? null : AppMapLights.idOn(placeOf(file), null);
                boolean other = ps.stream().anyMatch(p -> !p.part().equals(here));
                done.accept(new AppMapOverlay.Result(ps, -1, "Who uses " + name, other ? null : "no other part uses it"));
            })
            .submit(AppExecutorUtil.getAppExecutorService());
    }
}
