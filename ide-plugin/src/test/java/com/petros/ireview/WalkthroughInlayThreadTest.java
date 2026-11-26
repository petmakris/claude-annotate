package com.petros.ireview;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class WalkthroughInlayThreadTest {

    @Test
    void answerWithoutQuestionHasNoYouLabel() {
        assertEquals("Step.\n\nThe same key charges once.",
            WalkthroughInlay.withThread("Step.", "", "The same key charges once."));
    }

    @Test
    void questionIsShownAboveTheAnswer() {
        assertEquals("Step.\n\nYou · Why?\nBecause.",
            WalkthroughInlay.withThread("Step.", "Why?", "Because."));
    }
}
