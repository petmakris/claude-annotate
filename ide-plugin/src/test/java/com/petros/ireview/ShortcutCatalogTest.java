package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The rows of the Keyboard Shortcuts panel, as data. Kept free of IntelliJ
 * imports so the shape of the panel is testable without an IDE fixture — the
 * live key lookup happens in ShortcutsPanel, which is the only part that needs
 * a running keymap.
 *
 * Vocabulary: a "row" is one label plus the action id it displays the key for;
 * a "group" is a captioned block of rows (DIFF & HISTORY, WALKTHROUGH …); a
 * "column" is a list of groups stacked vertically in the dialog.
 */
class ShortcutCatalogTest {

    @Test
    void everyRowNamesAGroupThatIsLaidOut() {
        List<String> laidOut = ShortcutCatalog.columns().stream().flatMap(List::stream).toList();
        for (ShortcutCatalog.Row row : ShortcutCatalog.rows()) {
            assertTrue(laidOut.contains(row.group()),
                "row '" + row.label() + "' is in group '" + row.group()
                    + "', which no column displays — the row would be invisible");
        }
    }

    @Test
    void everyLaidOutGroupHasRows() {
        for (List<String> column : ShortcutCatalog.columns()) {
            for (String group : column) {
                assertTrue(ShortcutCatalog.rows().stream().anyMatch(r -> r.group().equals(group)),
                    "group '" + group + "' is laid out but has no rows — an empty caption");
            }
        }
    }

    @Test
    void thePanelIsLaidOutInTwoColumns() {
        assertEquals(2, ShortcutCatalog.columns().size());
    }

    @Test
    void noActionIsListedTwice() {
        List<String> ids = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        assertEquals(ids.size(), ids.stream().distinct().count(),
            "a duplicated action id means the same key is printed on two rows");
    }

    @Test
    void everyRowHasALabelAndAnActionId() {
        for (ShortcutCatalog.Row row : ShortcutCatalog.rows()) {
            assertFalse(row.label().isBlank(), "a row with no label renders as a bare key cap");
            assertFalse(row.actionId().isBlank(), "a row with no action id can never show a key");
        }
    }

    @Test
    void theStockGitActionsThatMatterAreListed() {
        // These are the actions a user loses silently by rebinding their key to
        // something else — the panel exists largely to make that visible.
        //
        // Compare.SameVersion used to be here and deliberately is not any more.
        // It did the same job as this plugin's own Compare with HEAD, so the
        // card carried two rows with almost the same name, one of them reading
        // "unassigned". That looked like a fault in the plugin rather than like
        // a key stripped from IntelliJ, which is the confusion the whole group
        // split exists to remove.
        List<String> ids = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        assertTrue(ids.containsAll(List.of(
            "Git.CompareWithBranch",
            "Vcs.ShowTabbedFileHistory", "Annotate",
            "Diff.NextChange", "Diff.PrevChange")), ids.toString());
        assertFalse(ids.contains("Compare.SameVersion"),
            "Compare.SameVersion duplicates this plugin's Compare with HEAD row");
    }

    @Test
    void everyActionThisPluginRegistersIsListed() {
        List<String> ids = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        assertTrue(ids.containsAll(List.of(
            SmartDiffActions.FORWARD_ID, SmartDiffActions.BACK_ID,
            SmartDiffActions.BASE_ID, SmartDiffActions.HEAD_ID,
            WalkthroughActions.NEXT_ID, WalkthroughActions.PREV_ID,
            WalkthroughActions.ASK_ID, WalkthroughActions.TOGGLE_ID,
            ShortcutCatalog.PANEL_ID)), ids.toString());
    }

    // ---- telling one diff key from another --------------------------------
    // The reported bug was not a wrong diff. It was four rows whose labels did
    // not say what any of them compared, so the one that had drifted could not
    // be told from the ones that had not.

    @Test
    void everyDiffKeySaysWhatItCompares() {
        for (String id : List.of(SmartDiffActions.FORWARD_ID, SmartDiffActions.BACK_ID,
                                 SmartDiffActions.BASE_ID, SmartDiffActions.HEAD_ID)) {
            ShortcutCatalog.Row row = ShortcutCatalog.rows().stream()
                .filter(r -> r.actionId().equals(id)).findFirst().orElseThrow();
            assertFalse(row.detail().isBlank(),
                "'" + row.label() + "' is one of four diff keys and its label alone "
                    + "does not say which two sides it puts on screen");
        }
    }

    @Test
    void theFourDiffKeysAreInOneGroupWithNothingElse() {
        // Grouping is the other half of it: a stock IntelliJ row sitting among
        // them reads as ours, and its missing key reads as our fault.
        String group = ShortcutCatalog.rows().stream()
            .filter(r -> r.actionId().equals(SmartDiffActions.FORWARD_ID))
            .findFirst().orElseThrow().group();
        for (ShortcutCatalog.Row row : ShortcutCatalog.rowsIn(group)) {
            assertTrue(row.actionId().startsWith("com.petros.ireview."),
                "row '" + row.label() + "' is a stock IntelliJ action sitting in this plugin's own group");
        }
    }

    @Test
    void theStockGroupSaysWhyItIsThere() {
        String group = ShortcutCatalog.rows().stream()
            .filter(r -> r.actionId().equals("Annotate"))
            .findFirst().orElseThrow().group();
        assertFalse(ShortcutCatalog.note(group).isBlank(),
            "the stock group needs a note; without one its rows read as this plugin's");
    }

    // ---- what a click may run ---------------------------------------------

    @Test
    void theDiffNavigationRowsAreNotClickable() {
        // They act on a focused diff viewer, which does not exist while this
        // card is open. Offering them as buttons would be a control that looks
        // live and does nothing.
        for (String id : List.of("Diff.NextChange", "Diff.PrevChange")) {
            ShortcutCatalog.Row row = ShortcutCatalog.rows().stream()
                .filter(r -> r.actionId().equals(id)).findFirst().orElseThrow();
            assertFalse(row.clickable(), id + " cannot work from the card and must not look clickable");
            assertFalse(row.detail().isBlank(), id + " must say why it is not clickable");
        }
    }

    @Test
    void theRowThatOpensThisCardIsNotClickable() {
        ShortcutCatalog.Row row = ShortcutCatalog.rows().stream()
            .filter(r -> r.actionId().equals(ShortcutCatalog.PANEL_ID)).findFirst().orElseThrow();
        assertFalse(row.clickable(), "clicking it would close the card and reopen it");
    }

    @Test
    void everyActionThisPluginAddsCanBeRunByClickingIt() {
        for (ShortcutCatalog.Row row : ShortcutCatalog.rows()) {
            if (!row.actionId().startsWith("com.petros.ireview.")) continue;
            if (row.actionId().equals(ShortcutCatalog.PANEL_ID)) continue;
            assertTrue(row.clickable(),
                "'" + row.label() + "' is ours and works on the current file, so the card should run it");
        }
    }

    // ---- splitting a shortcut into key caps -------------------------------
    // The panel draws one rounded cap per key. Splitting is done against the
    // platform's own rendering of the shortcut, so the caps can never disagree
    // with what IntelliJ prints in its own menus.

    @Test
    void macModifiersEachBecomeTheirOwnCap() {
        assertEquals(List.of("\u2325", "\u2318", "D"), ShortcutCatalog.caps("\u2325\u2318D", true));
        assertEquals(List.of("\u2303", "\u2325", "\u21e7", "\u2192"),
            ShortcutCatalog.caps("\u2303\u2325\u21e7\u2192", true));
    }

    @Test
    void aMacShortcutWithNoModifiersIsASingleCap() {
        assertEquals(List.of("F2"), ShortcutCatalog.caps("F2", true));
    }

    @Test
    void aMacKeyNameLongerThanOneCharacterStaysWhole() {
        assertEquals(List.of("\u2318", "Esc"), ShortcutCatalog.caps("\u2318Esc", true));
    }

    @Test
    void nonMacShortcutsSplitOnThePlusSign() {
        assertEquals(List.of("Ctrl", "Alt", "D"), ShortcutCatalog.caps("Ctrl+Alt+D", false));
        assertEquals(List.of("F2"), ShortcutCatalog.caps("F2", false));
    }

    @Test
    void aTwoStrokeChordIsJoinedByThen() {
        assertEquals(List.of("\u2318", "K", "then", "\u2318", "S"),
            ShortcutCatalog.caps("\u2318K, \u2318S", true));
        assertEquals(List.of("Ctrl", "K", "then", "Ctrl", "S"),
            ShortcutCatalog.caps("Ctrl+K, Ctrl+S", false));
    }

    @Test
    void anUnboundActionHasNoCapsAtAll() {
        // Rendered as the word "unassigned" rather than an empty gap, so a
        // stripped binding reads as a fact instead of a rendering bug.
        assertEquals(List.of(), ShortcutCatalog.caps("", true));
        assertEquals(List.of(), ShortcutCatalog.caps("   ", false));
    }

    @Test
    void aCommaKeyIsNotMistakenForAChordSeparator() {
        // IntelliJ separates the strokes of a chord with ", " \u2014 comma AND space.
        // A comma KEY is a bare trailing comma, so only the two-character form
        // may split, or \u2325, renders as a modifier with no key beside it.
        assertEquals(List.of("\u2325", ","), ShortcutCatalog.caps("\u2325,", true));
        assertEquals(List.of("\u2325", "\u2318", ","), ShortcutCatalog.caps("\u2325\u2318,", true));
    }

    @Test
    void aChordWhoseFirstStrokeIsACommaKeyStillSplits() {
        assertEquals(List.of("\u2318", ",", "then", "\u2318", "S"),
            ShortcutCatalog.caps("\u2318,, \u2318S", true));
    }

    @Test
    void thePanelNeverSizesAFontThroughDeriveFont() throws Exception {
        // The trap this guards: JBUI.scaleFontSize() returns an int, so
        // font.deriveFont(JBUI.scaleFontSize(17f)) binds to deriveFont(int
        // STYLE), not deriveFont(float SIZE). The size is silently discarded —
        // the text never grows — and the number is read as a style bitmask, so
        // 15 becomes BOLD|ITALIC and every key cap renders in italics.
        // It compiles, it runs, and only a screenshot shows it.
        // JBUI.Fonts.label(float) has no int overload and cannot be misread.
        String source = java.nio.file.Files.readString(
            java.nio.file.Path.of("src/main/java/com/petros/ireview/ShortcutsPanel.java"));
        assertFalse(source.contains("deriveFont("),
            "ShortcutsPanel must size fonts with JBUI.Fonts.label(float), never deriveFont(...)");
    }
}
