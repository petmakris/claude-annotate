package com.petros.ireview;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/**
 * {@link GhPrDiffOpener#parseNumber} decides which pull request the plugin
 * shells out against, from free-form text the user typed. Getting it wrong is
 * silent: a real but unrelated PR opens.
 */
class GhPrDiffOpenerTest {

    @Test void bareNumber() {
        assertEquals(6272, GhPrDiffOpener.parseNumber("6272"));
        assertEquals(6272, GhPrDiffOpener.parseNumber("  6272 "));
    }

    @Test void ownerRepoHashRef() {
        assertEquals(6272, GhPrDiffOpener.parseNumber("owner/repo#6272"));
        assertEquals(6272, GhPrDiffOpener.parseNumber("#6272"));
    }

    @Test void pullRequestUrl() {
        assertEquals(6416, GhPrDiffOpener.parseNumber("https://github.com/evooq/montblanc/pull/6416"));
        assertEquals(6416, GhPrDiffOpener.parseNumber("https://github.com/evooq/montblanc/pull/6416/files"));
    }

    @Test void branchNameNamesNoPullRequest() {
        // The regression: the first run of digits anywhere used to win, so a
        // branch — the third shape a ref is allowed to be — opened someone
        // else's PR. -1 routes to the caller's "No PR number" warning.
        assertEquals(-1, GhPrDiffOpener.parseNumber("release-2024"));
        assertEquals(-1, GhPrDiffOpener.parseNumber("PMP-272-external-pre-trade-checks"));
        assertEquals(-1, GhPrDiffOpener.parseNumber("main"));
        assertEquals(-1, GhPrDiffOpener.parseNumber(""));
    }

    @Test void zeroAndOverlongDigitsAreNotPullRequests() {
        assertEquals(-1, GhPrDiffOpener.parseNumber("0"));
        assertEquals(-1, GhPrDiffOpener.parseNumber("99999999999999999999999"));
    }
}
