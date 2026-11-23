package com.petros.ireview;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;

/**
 * Finds the map that belongs to an IDE project: by the git origin of the folder
 * holding .git (read from the config file, no git process), else by folder. A
 * map is read again only when its map.json changed. No IntelliJ imports.
 */
public final class AppMapStore {

    /** {@code remote} is the checkout's origin URL, or null when it has none. */
    public record Found(AppMapFile map, Path repoRoot, String remote) {}

    private record Entry(long modified, List<List<String>> match, AppMapFile map, AppMapFile.Unreadable error) {}

    private final Path home;
    private final Map<Path, Entry> cache = new ConcurrentHashMap<>();

    public AppMapStore(Path home) { this.home = home; }

    /** APP_MAP_HOME, else ~/.config/claude-annotate/app-map. */
    public static Path defaultHome() {
        String env = System.getenv("APP_MAP_HOME");
        if (env != null && !env.isBlank()) return Paths.get(env);
        return Paths.get(System.getProperty("user.home"), ".config", "claude-annotate", "app-map");
    }

    /**
     * The map for the project whose base folder is given. Empty when no map matches.
     *
     * @throws AppMapFile.Unreadable when the map that matches cannot be read
     */
    public Optional<Found> find(Path projectBase) throws AppMapFile.Unreadable {
        Path base = projectBase.toAbsolutePath().normalize();
        Path repoRoot = repoRootOf(base);
        String remote = repoRoot == null ? null : remoteOf(repoRoot);
        String wanted = remote == null ? null : normaliseRemote(remote);

        Path best = null;
        long bestTime = Long.MIN_VALUE;
        Entry bestEntry = null;
        for (Path file : candidates()) {
            Entry e = entry(file);
            if (e == null || e.match == null) continue;
            boolean byRemote = wanted != null && e.match.get(0).stream()
                .anyMatch(r -> normaliseRemote(r).equals(wanted));
            boolean byFolder = e.match.get(1).stream().anyMatch(f -> folderCovers(f, base));
            if (!byRemote && !byFolder) continue;
            if (e.modified > bestTime) { best = file; bestTime = e.modified; bestEntry = e; }
        }
        if (best == null) return Optional.empty();
        if (bestEntry.error != null) throw bestEntry.error;
        return Optional.of(new Found(bestEntry.map, repoRoot != null ? repoRoot : base, remote));
    }

    private static boolean folderCovers(String folder, Path base) {
        try {
            Path f = Paths.get(folder).toAbsolutePath().normalize();
            return base.startsWith(f);
        } catch (RuntimeException e) {
            return false;
        }
    }

    private List<Path> candidates() {
        List<Path> out = new ArrayList<>();
        if (!Files.isDirectory(home)) return out;
        try (Stream<Path> dirs = Files.list(home)) {
            dirs.map(d -> d.resolve("map.json")).filter(Files::isRegularFile).forEach(out::add);
        } catch (IOException e) {
            // an unreadable home is the same as no maps
        }
        return out;
    }

    private Entry entry(Path file) {
        long modified;
        try {
            modified = Files.getLastModifiedTime(file).toMillis();
        } catch (IOException e) {
            return null;
        }
        Entry c = cache.get(file);
        if (c != null && c.modified == modified) return c;
        List<List<String>> match = AppMapFile.peekMatch(file);
        Entry fresh;
        try {
            fresh = new Entry(modified, match, AppMapFile.read(file), null);
        } catch (AppMapFile.Unreadable u) {
            fresh = new Entry(modified, match, null, u);
        }
        cache.put(file, fresh);
        return fresh;
    }

    /** The folder holding .git (a folder, or a file in a worktree), walking up from {@code base}; null if none. */
    static Path repoRootOf(Path base) {
        for (Path p = base; p != null; p = p.getParent()) {
            if (Files.exists(p.resolve(".git"))) return p;
        }
        return null;
    }

    /** The origin URL from the repo's config; follows a worktree's gitdir and commondir. Null when none. */
    static String remoteOf(Path repoRoot) {
        try {
            Path git = repoRoot.resolve(".git");
            Path gitDir = git;
            if (Files.isRegularFile(git)) {
                String line = Files.readString(git).trim();
                if (!line.startsWith("gitdir:")) return null;
                gitDir = repoRoot.resolve(line.substring("gitdir:".length()).trim()).normalize();
                Path common = gitDir.resolve("commondir");
                if (Files.isRegularFile(common)) {
                    gitDir = gitDir.resolve(Files.readString(common).trim()).normalize();
                }
            }
            Path config = gitDir.resolve("config");
            if (!Files.isRegularFile(config)) return null;
            boolean inOrigin = false;
            for (String raw : Files.readAllLines(config)) {
                String line = raw.trim();
                if (line.startsWith("[")) {
                    inOrigin = line.replaceAll("\\s+", " ").equalsIgnoreCase("[remote \"origin\"]");
                } else if (inOrigin && line.startsWith("url")) {
                    int eq = line.indexOf('=');
                    if (eq > 0 && line.substring(0, eq).trim().equals("url")) return line.substring(eq + 1).trim();
                }
            }
        } catch (IOException | RuntimeException e) {
            // no readable remote
        }
        return null;
    }

    /** "git@github.com:Acme/Shop.git" and its https and ssh:// forms all become "github.com/acme/shop". */
    public static String normaliseRemote(String url) {
        String s = url.trim();
        int scheme = s.indexOf("://");
        if (scheme >= 0) {
            s = s.substring(scheme + 3);
            int slash = s.indexOf('/');
            String authority = slash < 0 ? s : s.substring(0, slash);
            String rest = slash < 0 ? "" : s.substring(slash);
            authority = authority.substring(authority.lastIndexOf('@') + 1).replaceAll(":\\d+$", "");
            s = authority + rest;
        } else {
            s = s.substring(s.lastIndexOf('@') + 1);
            int colon = s.indexOf(':');
            if (colon >= 0) s = s.substring(0, colon) + "/" + s.substring(colon + 1);
        }
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (s.endsWith(".git")) s = s.substring(0, s.length() - 4);
        return s.toLowerCase(Locale.ROOT);
    }
}
