package com.petros.ireview;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ReviewAnchorTest {

    @Test void singleLineTailIsItsOwnStart() {
        assertEquals(42, ReviewAnchor.startLine("42"));
    }

    @Test void rangeTailStartsAtItsFirstLine() {
        // The regression: Integer.parseInt("111-117") throws, and every caller
        // treated that as "not a line" — dropping range threads from the gutter
        // and from the stale check.
        assertEquals(111, ReviewAnchor.startLine("111-117"));
    }

    @Test void nonNumericTailHasNoLine() {
        assertEquals(-1, ReviewAnchor.startLine("__general__"));
        assertEquals(-1, ReviewAnchor.startLine(""));
        assertEquals(-1, ReviewAnchor.startLine(null));
        assertEquals(-1, ReviewAnchor.startLine("-5"));
        assertEquals(-1, ReviewAnchor.startLine("0"));
    }

    @Test void bothAnchorShapesAreLineAnchors() {
        assertTrue(ReviewAnchor.isLineAnchor("src/Foo.java:R:42"));
        assertTrue(ReviewAnchor.isLineAnchor("src/Foo.java:R:111-117"));
    }

    @Test void generalAnchorIsNotALineAnchor() {
        assertFalse(ReviewAnchor.isLineAnchor("__general__"));
        assertTrue(ReviewAnchor.isGeneral("__general__"));
        assertFalse(ReviewAnchor.isGeneral("src/Foo.java:R:42"));
    }
}
