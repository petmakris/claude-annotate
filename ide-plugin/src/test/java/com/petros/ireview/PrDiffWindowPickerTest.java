package com.petros.ireview;

import com.petros.ireview.PrDiffWindowPicker.Window;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PrDiffWindowPickerTest {

    private static final String MB = "git@github.com:acme/shop.git";

    private static final Window MAIN = new Window("/ws/main/shop", "master", List.of(MB), false);
    private static final Window TICKET291 = new Window("/ws/ticket-291/shop", "TICKET-291-archival", List.of(MB), false);
    private static final Window REVIEW = new Window("/ws/review/shop", "TICKET-314-bought", List.of(MB), false);
    private static final Window OTHER = new Window("/x/annotate", "main", List.of("https://github.com/petmakris/claude-annotate"), true);

    private static Optional<String> picked(List<Window> open, String path, String branch, String repo) {
        return PrDiffWindowPicker.pick(open, path, branch, repo).map(Window::basePath);
    }

    @Test
    void aPathPicksTheWindowOfThatCheckoutOverOneOnTheBranch() {
        assertEquals(Optional.of("/ws/ticket-291/shop"),
            picked(List.of(REVIEW, TICKET291), "/ws/ticket-291/shop/", "TICKET-314-bought", "acme/shop"));
    }

    @Test
    void aPathNoWindowHoldsPicksNothingSoTheCallerOpensIt() {
        assertEquals(Optional.empty(),
            picked(List.of(MAIN, REVIEW), "/ws/new/shop", "TICKET-314-bought", "acme/shop"));
    }

    @Test
    void withoutAPathTheWindowOnThePrBranchWinsOverTheFocusedOne() {
        Window focusedMain = new Window(MAIN.basePath(), MAIN.branch(), MAIN.remoteUrls(), true);
        assertEquals(Optional.of("/ws/review/shop"),
            picked(List.of(focusedMain, TICKET291, REVIEW), null, "TICKET-314-bought", "acme/shop"));
    }

    @Test
    void withNoWindowOnTheBranchTheLastFocusedWindowOfTheRepoWins() {
        Window focusedTicket = new Window(TICKET291.basePath(), TICKET291.branch(), TICKET291.remoteUrls(), true);
        assertEquals(Optional.of("/ws/ticket-291/shop"),
            picked(List.of(MAIN, focusedTicket, OTHER), null, "TICKET-999-nowhere", "acme/shop"));
    }

    @Test
    void aFocusedWindowOfAnotherRepoIsNeverPicked() {
        assertEquals(Optional.of("/ws/main/shop"),
            picked(List.of(OTHER, MAIN), null, "TICKET-999-nowhere", "acme/shop"));
    }

    @Test
    void noWindowOfTheRepoPicksNothing() {
        assertEquals(Optional.empty(), picked(List.of(OTHER), null, "x", "acme/shop"));
    }

    @Test
    void remotesMatchInSshAndHttpsFormButNotByRepoSuffix() {
        assertTrue(PrDiffWindowPicker.remoteMatches("git@github.com:acme/shop.git", "acme/shop"));
        assertTrue(PrDiffWindowPicker.remoteMatches("https://github.com/Acme/shop/", "acme/shop"));
        assertFalse(PrDiffWindowPicker.remoteMatches("https://github.com/acme/shop-config", "acme/shop"));
        assertFalse(PrDiffWindowPicker.remoteMatches("https://github.com/other/acme/shop-x", "acme/shop"));
    }
}
