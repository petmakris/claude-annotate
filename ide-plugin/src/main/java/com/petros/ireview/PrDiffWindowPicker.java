package com.petros.ireview;

import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.nio.file.Path;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

/**
 * Which open project window a PR diff goes to, when one IntelliJ holds a window
 * per checkout and several of them are clones of the same repository.
 *
 * In order: the window whose checkout is {@code path}; a window of the PR's
 * repository with the PR's head branch checked out; the last focused window of
 * that repository; any window of that repository.
 */
final class PrDiffWindowPicker {

    record Window(@NotNull String basePath, @Nullable String branch,
                  @NotNull List<String> remoteUrls, boolean lastFocused) {}

    private PrDiffWindowPicker() {}

    static @NotNull Optional<Window> pick(@NotNull List<Window> open, @Nullable String path,
                                         @Nullable String branch, @Nullable String repo) {
        if (path != null && !path.isBlank()) {
            Path wanted = normalize(path);
            return open.stream().filter(w -> normalize(w.basePath()).equals(wanted)).findFirst();
        }
        List<Window> ofRepo = open.stream().filter(w -> isOfRepo(w, repo)).toList();
        if (branch != null && !branch.isBlank()) {
            Optional<Window> onBranch = ofRepo.stream().filter(w -> branch.equals(w.branch())).findFirst();
            if (onBranch.isPresent()) return onBranch;
        }
        Optional<Window> focused = ofRepo.stream().filter(Window::lastFocused).findFirst();
        return focused.isPresent() ? focused : ofRepo.stream().findFirst();
    }

    static boolean remoteMatches(@NotNull String url, @NotNull String repo) {
        String u = url.trim().toLowerCase(Locale.ROOT);
        if (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        if (u.endsWith(".git")) u = u.substring(0, u.length() - 4);
        String r = repo.trim().toLowerCase(Locale.ROOT);
        return u.endsWith("/" + r) || u.endsWith(":" + r);
    }

    private static boolean isOfRepo(@NotNull Window w, @Nullable String repo) {
        if (repo == null || repo.isBlank()) return true;
        return w.remoteUrls().stream().anyMatch(u -> remoteMatches(u, repo));
    }

    private static @NotNull Path normalize(@NotNull String p) {
        return Path.of(p).toAbsolutePath().normalize();
    }
}
