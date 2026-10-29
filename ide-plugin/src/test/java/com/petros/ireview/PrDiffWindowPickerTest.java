package com.petros.ireview;

import com.petros.ireview.PrDiffWindowPicker.Window;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PrDiffWindowPickerTest {

    private static final String MB = "git@github.com:evooq/montblanc.git";

    private static final Window MAIN = new Window("/wp/main/montblanc", "master", List.of(MB), false);
    private static final Window PMP291 = new Window("/wp/pmp-291/montblanc", "PMP-291-archival", List.of(MB), false);
    private static final Window REVIEW = new Window("/wp/review/montblanc", "PMP-314-bought", List.of(MB), false);
    private static final Window OTHER = new Window("/x/annotate", "main", List.of("https://github.com/petmakris/claude-annotate"), true);

    private static Optional<String> picked(List<Window> open, String path, String branch, String repo) {
        return PrDiffWindowPicker.pick(open, path, branch, repo).map(Window::basePath);
    }

    @Test
    void aPathPicksTheWindowOfThatCheckoutOverOneOnTheBranch() {
        assertEquals(Optional.of("/wp/pmp-291/montblanc"),
            picked(List.of(REVIEW, PMP291), "/wp/pmp-291/montblanc/", "PMP-314-bought", "evooq/montblanc"));
    }

    @Test
    void aPathNoWindowHoldsPicksNothingSoTheCallerOpensIt() {
        assertEquals(Optional.empty(),
            picked(List.of(MAIN, REVIEW), "/wp/new/montblanc", "PMP-314-bought", "evooq/montblanc"));
    }

    @Test
    void withoutAPathTheWindowOnThePrBranchWinsOverTheFocusedOne() {
        Window focusedMain = new Window(MAIN.basePath(), MAIN.branch(), MAIN.remoteUrls(), true);
        assertEquals(Optional.of("/wp/review/montblanc"),
            picked(List.of(focusedMain, PMP291, REVIEW), null, "PMP-314-bought", "evooq/montblanc"));
    }

    @Test
    void withNoWindowOnTheBranchTheLastFocusedWindowOfTheRepoWins() {
        Window focusedPmp = new Window(PMP291.basePath(), PMP291.branch(), PMP291.remoteUrls(), true);
        assertEquals(Optional.of("/wp/pmp-291/montblanc"),
            picked(List.of(MAIN, focusedPmp, OTHER), null, "PMP-999-nowhere", "evooq/montblanc"));
    }

    @Test
    void aFocusedWindowOfAnotherRepoIsNeverPicked() {
        assertEquals(Optional.of("/wp/main/montblanc"),
            picked(List.of(OTHER, MAIN), null, "PMP-999-nowhere", "evooq/montblanc"));
    }

    @Test
    void noWindowOfTheRepoPicksNothing() {
        assertEquals(Optional.empty(), picked(List.of(OTHER), null, "x", "evooq/montblanc"));
    }

    @Test
    void remotesMatchInSshAndHttpsFormButNotByRepoSuffix() {
        assertTrue(PrDiffWindowPicker.remoteMatches("git@github.com:evooq/montblanc.git", "evooq/montblanc"));
        assertTrue(PrDiffWindowPicker.remoteMatches("https://github.com/Evooq/montblanc/", "evooq/montblanc"));
        assertFalse(PrDiffWindowPicker.remoteMatches("https://github.com/evooq/montblanc-config", "evooq/montblanc"));
        assertFalse(PrDiffWindowPicker.remoteMatches("https://github.com/other/evooq/montblanc-x", "evooq/montblanc"));
    }
}
