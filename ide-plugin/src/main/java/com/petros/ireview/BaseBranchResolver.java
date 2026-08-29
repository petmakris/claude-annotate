package com.petros.ireview;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

/**
 * Picks the ref that "Diff vs Base Branch" compares against, so the key can go
 * straight to a diff instead of opening a branch picker. Pure: the service
 * supplies what git reported, this decides which ref wins.
 *
 * Order, first hit wins:
 *
 *  1. the ref typed into Settings — accepted as given, because a ref can be
 *     valid and absent from our listing (an unfetched remote, a tag), and
 *     rejecting it here would be us second-guessing git;
 *  2. {@code origin/HEAD}, the repository's own declared default branch, but
 *     only when it still names a ref that exists — it survives the deletion of
 *     the branch it points at;
 *  3. {@link #candidates()}, in order.
 *
 * Resolving to nothing is a real outcome, not an error: the caller reports
 * which refs were tried rather than diffing against a guess.
 */
public final class BaseBranchResolver {

    private BaseBranchResolver() {}

    private static final List<String> CANDIDATES =
        List.of("origin/main", "origin/master", "main", "master");

    /** The guesses tried when Settings is empty and origin/HEAD is unusable, in order. */
    public static List<String> candidates() {
        return CANDIDATES;
    }

    /**
     * @param override   the Settings value; blank or null means "not set"
     * @param symbolicRef what {@code git symbolic-ref refs/remotes/origin/HEAD} printed, or empty
     * @param knownRefs  branch names that exist in this repository, short form
     */
    public static Optional<String> resolve(String override, String symbolicRef, Collection<String> knownRefs) {
        if (override != null && !override.isBlank()) {
            return Optional.of(override.trim());
        }
        String head = shortName(symbolicRef);
        if (!head.isEmpty() && knownRefs.contains(head)) {
            return Optional.of(head);
        }
        return CANDIDATES.stream().filter(knownRefs::contains).findFirst();
    }

    /** {@code refs/remotes/origin/main} and {@code refs/heads/main} down to the branch name. */
    public static String shortName(String ref) {
        if (ref == null) return "";
        String s = ref.trim();
        if (s.startsWith("refs/remotes/")) return s.substring("refs/remotes/".length());
        if (s.startsWith("refs/heads/")) return s.substring("refs/heads/".length());
        return s;
    }
}
