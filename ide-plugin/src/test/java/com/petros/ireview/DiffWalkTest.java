package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Which depth the next press of Smart Diff lands on.
 *
 * The reported bug is the first test here, written from the real case: a file
 * with three commits, pressed several times over an afternoon, answering "show
 * me what changed" with a diff between two commits from the year before last.
 */
class DiffWalkTest {

    /** The real file from the report: newest first, the top one being the user's own commit. */
    private static final List<String> THREE_COMMITS =
        List.of("751c22135f", "37751fbdd9", "d7c2d6fbe0");

    private static DiffHistory clean() {
        return new DiffHistory(THREE_COMMITS, false);
    }

    private static DiffHistory dirty() {
        return new DiffHistory(THREE_COMMITS, true);
    }

    // ---- the bug ----------------------------------------------------------

    @Test
    void aPressAfterAPauseStartsOverInsteadOfRatchetingDeeper() {
        // Where the old rule left the walk: two commits down, set long ago.
        DiffWalk.Stop stranded = new DiffWalk.Stop(2, false, 0L);
        long muchLater = DiffWalk.RESUME_MILLIS * 10;

        assertEquals(clean().firstDepth(),
            DiffWalk.nextDepth(stranded, clean(), false, true, muchLater),
            "a press after a pause is a new question and must start at the newest change");
    }

    @Test
    void theOldRuleIsWhatWouldHaveHappened() {
        // Same stop, pressed straight away: this is the behaviour being kept,
        // and the test is here so the fix cannot be mistaken for removing it.
        DiffWalk.Stop justNow = new DiffWalk.Stop(2, false, 1_000L);
        assertEquals(3, THREE_COMMITS.size());
        assertEquals(clean().advance(2),
            DiffWalk.nextDepth(justNow, clean(), false, true, 1_500L));
    }

    // ---- the window -------------------------------------------------------

    @Test
    void aWalkIsResumableRightUpToTheWindowAndNotAfterIt() {
        DiffWalk.Stop stop = new DiffWalk.Stop(1, false, 0L);
        assertTrue(DiffWalk.resumable(stop, false, DiffWalk.RESUME_MILLIS),
            "the boundary itself must still resume, or a press can fail on timing alone");
        assertFalse(DiffWalk.resumable(stop, false, DiffWalk.RESUME_MILLIS + 1));
    }

    @Test
    void theWindowIsLongEnoughToReadADiffBeforePressingAgain() {
        // A window that expired while you were still looking at the result would
        // break "press again to go further back" — the opposite failure.
        assertTrue(DiffWalk.RESUME_MILLIS >= 60_000,
            "under a minute is shorter than it takes to read a screen of diff");
    }

    @Test
    void aFileWithNoWalkStartsAtTheTop() {
        assertEquals(clean().firstDepth(), DiffWalk.nextDepth(null, clean(), false, true, 0L));
        assertEquals(dirty().firstDepth(), DiffWalk.nextDepth(null, dirty(), true, true, 0L));
        assertFalse(DiffWalk.resumable(null, false, 0L));
    }

    // ---- the older half of the rule, kept -----------------------------------

    @Test
    void editingOrCommittingTheFileRestartsTheWalk() {
        DiffWalk.Stop wasClean = new DiffWalk.Stop(2, false, 0L);
        assertEquals(dirty().firstDepth(),
            DiffWalk.nextDepth(wasClean, dirty(), true, true, 10L),
            "after you edit it, the thing you want to see is that edit");

        DiffWalk.Stop wasDirty = new DiffWalk.Stop(0, true, 0L);
        assertEquals(clean().firstDepth(),
            DiffWalk.nextDepth(wasDirty, clean(), false, true, 10L),
            "after you commit it, the thing you want to see is that commit");
    }

    // ---- stepping back ------------------------------------------------------

    @Test
    void steppingBackWithinTheWindowWalksTowardTheWorkingCopy() {
        DiffWalk.Stop stop = new DiffWalk.Stop(2, false, 0L);
        assertEquals(clean().back(2), DiffWalk.nextDepth(stop, clean(), false, false, 10L));
    }

    @Test
    void steppingBackOutOfAnExpiredWalkLandsAtTheNewestChange() {
        // Not a wrap to the oldest commit. There is no walk left to step back
        // through, and the newest change is as far toward the working copy as a
        // walk goes — which is what the back key is for.
        DiffWalk.Stop stale = new DiffWalk.Stop(2, false, 0L);
        long later = DiffWalk.RESUME_MILLIS + 1;
        assertEquals(clean().firstDepth(), DiffWalk.nextDepth(stale, clean(), false, false, later));
        assertNotEquals(clean().back(clean().firstDepth()),
            DiffWalk.nextDepth(stale, clean(), false, false, later),
            "an expired back-press must not wrap to the oldest commit");
    }

    // ---- saying where you are -----------------------------------------------

    @Test
    void everyDepthDescribesItselfForTheDiffTitle() {
        assertEquals("uncommitted", DiffHistory.describe(0));
        assertEquals("last commit", DiffHistory.describe(1));
        assertEquals("2 commits back", DiffHistory.describe(2));
        assertEquals("11 commits back", DiffHistory.describe(11));
    }

    @Test
    void theDescriptionIsNeverBlank() {
        // It goes into the diff tab's title between two hashes; a blank would
        // render as a stray pair of dashes.
        for (int depth = 0; depth <= 20; depth++) {
            assertFalse(DiffHistory.describe(depth).isBlank(), "depth " + depth);
        }
    }
}
