package com.petros.ireview;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * A repo's CODEOWNERS file (GitHub syntax), read at show time and cached by
 * modification time. A GitLab "[Section]" line is skipped. No IntelliJ imports.
 */
public final class CodeOwners {

    private static final String[] PLACES = {".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"};
    private static final CodeOwners EMPTY = new CodeOwners(List.of(), List.of());

    private record Cached(Path file, long modified, CodeOwners owners) {}
    private static final Map<Path, Cached> CACHE = new ConcurrentHashMap<>();

    private final List<String> patterns;
    private final List<List<String>> owners;

    private CodeOwners(List<String> patterns, List<List<String>> owners) {
        this.patterns = patterns;
        this.owners = owners;
    }

    /** The owners rules of {@code repoRoot}; empty when the repo has no CODEOWNERS file. */
    public static CodeOwners at(Path repoRoot) {
        for (String place : PLACES) {
            Path f = repoRoot.resolve(place);
            if (!Files.isRegularFile(f)) continue;
            try {
                long modified = Files.getLastModifiedTime(f).toMillis();
                Cached c = CACHE.get(repoRoot);
                if (c != null && c.file.equals(f) && c.modified == modified) return c.owners;
                CodeOwners parsed = parse(Files.readAllLines(f));
                CACHE.put(repoRoot, new Cached(f, modified, parsed));
                return parsed;
            } catch (IOException | RuntimeException e) {
                return EMPTY;
            }
        }
        CACHE.remove(repoRoot);
        return EMPTY;
    }

    static CodeOwners parse(List<String> lines) {
        List<String> patterns = new ArrayList<>();
        List<List<String>> owners = new ArrayList<>();
        for (String raw : lines) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith("[") || line.startsWith("^[")) continue;
            String[] tokens = line.split("\\s+");
            List<String> who = new ArrayList<>();
            for (int i = 1; i < tokens.length && !tokens[i].startsWith("#"); i++) who.add(tokens[i]);
            patterns.add(tokens[0]);
            owners.add(who);
        }
        return new CodeOwners(patterns, owners);
    }

    /** The owners of a repo-relative file: those of the last matching rule, or none. */
    public List<String> owners(String repoRelPath) {
        int i = AppMapPaths.lastMatch(patterns, repoRelPath);
        return i < 0 ? List.of() : owners.get(i);
    }
}
