package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The walk the Smart Diff key performs, as pure arithmetic over a file's
 * revision list. Nothing here touches git or the IDE — the service layer
 * supplies the revision hashes and the dirty flag, this decides what the Nth
 * press should put on screen.
 *
 * Vocabulary: a "stop" is one press-worth of diff. Depth 0 is the working copy
 * against the newest commit; depth N (N >= 1) is commit N against commit N-1,
 * newest-first. A clean file has no depth 0 worth showing, so its walk starts
 * at depth 1.
 */
class DiffHistoryTest {

    private static final List<String> THREE = List.of("c0", "c1", "c2");

    // ---- where the walk starts -------------------------------------------

    @Test
    void dirtyFileStartsOnTheWorkingCopy() {
        DiffHistory h = new DiffHistory(THREE, true);
        assertEquals(0, h.firstDepth());
        assertEquals(new DiffHistory.Step("c0", null), h.at(0),
            "first press on a modified file diffs the working copy against HEAD's version");
    }

    @Test
    void cleanFileSkipsStraightToThePreviousCommit() {
        DiffHistory h = new DiffHistory(THREE, false);
        assertEquals(1, h.firstDepth(),
            "a clean file at depth 0 would diff identical content — the whole point is to skip it");
        assertEquals(new DiffHistory.Step("c1", "c0"), h.at(1));
    }

    // ---- walking forward --------------------------------------------------

    @Test
    void eachPressStepsOneCommitFurtherBack() {
        DiffHistory h = new DiffHistory(THREE, true);
        assertEquals(1, h.advance(0));
        assertEquals(new DiffHistory.Step("c1", "c0"), h.at(1));
        assertEquals(2, h.advance(1));
        assertEquals(new DiffHistory.Step("c2", "c1"), h.at(2));
    }

    @Test
    void advancingPastTheOldestCommitWrapsToTheStart() {
        DiffHistory dirty = new DiffHistory(THREE, true);
        assertEquals(0, dirty.advance(2), "wraps back to the working copy");

        DiffHistory clean = new DiffHistory(THREE, false);
        assertEquals(1, clean.advance(2), "a clean file has no depth 0, so it wraps to depth 1");
    }

    // ---- walking back -----------------------------------------------------

    @Test
    void backStepsOneLevelTowardTheWorkingCopy() {
        DiffHistory h = new DiffHistory(THREE, true);
        assertEquals(1, h.back(2));
        assertEquals(0, h.back(1));
    }

    @Test
    void backFromTheStartWrapsToTheOldestCommit() {
        DiffHistory dirty = new DiffHistory(THREE, true);
        assertEquals(2, dirty.back(0));

        DiffHistory clean = new DiffHistory(THREE, false);
        assertEquals(2, clean.back(1), "clean file's start is depth 1, not depth 0");
    }

    // ---- degenerate histories --------------------------------------------

    @Test
    void modifiedFileWithASingleCommitHasExactlyOneStop() {
        DiffHistory h = new DiffHistory(List.of("c0"), true);
        assertFalse(h.isEmpty());
        assertEquals(0, h.firstDepth());
        assertEquals(0, h.advance(0), "nowhere else to go — stays put rather than wrapping onto nothing");
        assertEquals(0, h.back(0));
    }

    @Test
    void cleanFileWithASingleCommitHasNothingToShow() {
        // Its only revision is what is already on disk, and there is no
        // earlier revision to compare that against.
        DiffHistory h = new DiffHistory(List.of("c0"), false);
        assertTrue(h.isEmpty());
    }

    @Test
    void fileWithNoCommitsHasNothingToShow() {
        // An untracked file: git has never stored a version of it, so there is
        // no previous content to diff against, modified or not.
        assertTrue(new DiffHistory(List.of(), true).isEmpty());
        assertTrue(new DiffHistory(List.of(), false).isEmpty());
    }

    @Test
    void askingForAStopOutsideTheWalkIsRejected() {
        DiffHistory h = new DiffHistory(THREE, false);
        assertThrows(IndexOutOfBoundsException.class, () -> h.at(0),
            "depth 0 is not part of a clean file's walk");
        assertThrows(IndexOutOfBoundsException.class, () -> h.at(3));
    }

    // ---- clamping ---------------------------------------------------------

    @Test
    void aRememberedDepthIsClampedWhenNewCommitsShrinkTheWalk() {
        // The service remembers a depth per file. Commit something, and the
        // revision list changes underneath that number — it must not throw.
        DiffHistory h = new DiffHistory(List.of("c0", "c1"), true);
        assertEquals(1, h.clamp(7));
        assertEquals(0, h.clamp(-3));
    }

    @Test
    void clampingACleanFileNeverReturnsTheWorkingCopyStop() {
        DiffHistory h = new DiffHistory(THREE, false);
        assertEquals(1, h.clamp(0));
    }
}
