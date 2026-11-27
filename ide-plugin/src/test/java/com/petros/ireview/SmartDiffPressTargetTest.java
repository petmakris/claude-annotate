package com.petros.ireview;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Which file a Smart Diff press means. The first press puts the focus in the diff
 * it opens; a second press there must keep walking the same file.
 */
class SmartDiffPressTargetTest {

    @Test
    void aPressInsideTheDiffTabMeansTheFileItShows() {
        assertEquals("RetryPolicy.java",
            SmartDiffService.pressTarget("diff-tab", "diff-tab", "RetryPolicy.java"));
    }

    @Test
    void aPressInAnEditorMeansThatEditorsFile() {
        assertEquals("FlowService.java",
            SmartDiffService.pressTarget("FlowService.java", "diff-tab", "RetryPolicy.java"));
    }

    @Test
    void withNoDiffOpenThePressKeepsItsOwnFile() {
        assertEquals("FlowService.java", SmartDiffService.pressTarget("FlowService.java", null, null));
        assertNull(SmartDiffService.pressTarget(null, null, null));
    }
}
