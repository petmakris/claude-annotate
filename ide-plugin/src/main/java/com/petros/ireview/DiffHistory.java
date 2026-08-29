package com.petros.ireview;

import java.util.List;

/**
 * What the Smart Diff key shows on its Nth press, as arithmetic over one file's
 * revision list. No git, no IDE — the service supplies the hashes and the dirty
 * flag; this decides which two sides to put on screen.
 *
 * A <em>stop</em> is one press-worth of diff, addressed by its <em>depth</em>:
 *
 *  - depth 0 is the working copy against HEAD's version of the file;
 *  - depth N (N >= 1) is revision N against revision N-1, newest first.
 *
 * A clean file has nothing to show at depth 0 — both sides would be identical —
 * so its walk starts at depth 1. That is the whole trick behind "show me the
 * uncommitted change, or the last commit if there isn't one".
 *
 * Walking off either end wraps, so the key never dead-ends and never needs a
 * reset gesture.
 */
public final class DiffHistory {

    /**
     * One stop. {@code left} is the older side; {@code right} is the newer.
     * A null {@code right} means the working copy on disk rather than a commit.
     */
    public record Step(String left, String right) {}

    private final List<String> revisions;
    private final boolean dirty;

    /** @param revisions commit hashes that touched this file, newest first. */
    public DiffHistory(List<String> revisions, boolean dirty) {
        this.revisions = List.copyOf(revisions);
        this.dirty = dirty;
    }

    /** Number of stops in the walk, counting from depth 0 whether or not it is reachable. */
    public int levels() {
        return revisions.size();
    }

    /** Depth the walk starts at: the working copy when dirty, the last commit when clean. */
    public int firstDepth() {
        return dirty ? 0 : 1;
    }

    /** True when there is no pair of sides worth showing — an untracked file, or a clean file with a single commit. */
    public boolean isEmpty() {
        return firstDepth() > levels() - 1;
    }

    /** Pull a remembered depth back into range; commits landing since it was stored can shrink the walk. */
    public int clamp(int depth) {
        if (isEmpty()) return firstDepth();
        return Math.min(Math.max(depth, firstDepth()), levels() - 1);
    }

    /** One step further back in history, wrapping to the start past the oldest commit. */
    public int advance(int depth) {
        if (isEmpty()) return firstDepth();
        int next = clamp(depth) + 1;
        return next > levels() - 1 ? firstDepth() : next;
    }

    /** One step back toward the working copy, wrapping to the oldest commit past the start. */
    public int back(int depth) {
        if (isEmpty()) return firstDepth();
        int prev = clamp(depth) - 1;
        return prev < firstDepth() ? levels() - 1 : prev;
    }

    /** The two sides to show at {@code depth}. */
    public Step at(int depth) {
        if (isEmpty() || depth < firstDepth() || depth > levels() - 1) {
            throw new IndexOutOfBoundsException(
                "depth " + depth + " is outside this file's walk ["
                    + firstDepth() + ".." + (levels() - 1) + "]");
        }
        return depth == 0
            ? new Step(revisions.get(0), null)
            : new Step(revisions.get(depth), revisions.get(depth - 1));
    }
}
