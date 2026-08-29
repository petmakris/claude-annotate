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
        List<String> ids = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        assertTrue(ids.containsAll(List.of(
            "Compare.SameVersion", "Git.CompareWithBranch",
            "Vcs.ShowTabbedFileHistory", "Annotate",
            "Diff.NextChange", "Diff.PrevChange")), ids.toString());
    }

    @Test
    void everyActionThisPluginRegistersIsListed() {
        List<String> ids = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        assertTrue(ids.containsAll(List.of(
            SmartDiffActions.FORWARD_ID, SmartDiffActions.BACK_ID, SmartDiffActions.BASE_ID,
            WalkthroughActions.NEXT_ID, WalkthroughActions.PREV_ID,
            WalkthroughActions.ASK_ID, WalkthroughActions.TOGGLE_ID,
            ShortcutCatalog.PANEL_ID)), ids.toString());
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
