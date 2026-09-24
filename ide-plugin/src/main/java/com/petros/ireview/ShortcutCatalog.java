package com.petros.ireview;

import java.util.List;

/**
 * The rows of the Keyboard Shortcuts panel, as data.
 *
 * Deliberately free of IntelliJ imports: the panel's shape is then testable
 * without an IDE fixture, and the one part that genuinely needs a running
 * keymap — turning an action id into the keys currently bound to it — stays in
 * {@link ShortcutsPanel}.
 *
 * Three things the panel has to make obvious, because not doing so was the bug:
 *
 *  1. <b>Which rows are ours.</b> Stock IntelliJ actions are listed beside this
 *     plugin's own, and nothing used to say so. A row reading "unassigned" then
 *     looks like this plugin is broken rather than like a key you stripped from
 *     IntelliJ. The {@code group} does that job, and {@link #note} says why a
 *     group is here at all.
 *  2. <b>What a diff key actually compares.</b> "Smart diff — this file" names
 *     no sides. {@code detail} is the one line that does, and it is the reason
 *     someone can tell these four keys apart without asking.
 *  3. <b>What can be clicked.</b> The panel runs an action when its row is
 *     clicked, so a key you cannot remember is still reachable. Two rows cannot
 *     work that way — see {@code clickable}.
 */
public final class ShortcutCatalog {

    private ShortcutCatalog() {}

    public static final String PANEL_ID = "com.petros.ireview.ShortcutsPanel";

    private static final String MINE = "What this plugin adds";
    private static final String WALK = "Walkthrough";
    private static final String STOCK = "IntelliJ's own git keys";
    private static final String GENERAL = "General";

    /**
     * One line of the panel.
     *
     * @param group     the captioned block it belongs to
     * @param label     what it does, in the fewest words that are still true
     * @param actionId  the action whose currently-bound keys the row prints
     * @param detail    the two sides a diff key compares, or blank when the
     *                  label already says everything — "Git blame" needs no gloss
     * @param clickable whether clicking the row runs the action from the card.
     *                  False for the two diff-navigation rows, which act on a
     *                  focused diff viewer that does not exist while this card
     *                  is open, and for the row that opens this card
     */
    public record Row(String group, String label, String actionId, String detail, boolean clickable) {}

    private static final List<Row> ROWS = List.of(
        new Row(MINE, "Smart diff — this file", SmartDiffActions.FORWARD_ID,
            "your edits against the last commit — press again to step further back", true),
        new Row(MINE, "Smart diff — step back", SmartDiffActions.BACK_ID,
            "undo one press of the key above", true),
        new Row(MINE, "Compare with HEAD", SmartDiffActions.HEAD_ID,
            "your uncommitted edits, always — this one never steps", true),
        new Row(MINE, "Diff against base branch", SmartDiffActions.BASE_ID,
            "your whole branch against where it forked — the GitHub PR view", true),

        new Row(WALK, "Next step", WalkthroughActions.NEXT_ID, "", true),
        new Row(WALK, "Previous step", WalkthroughActions.PREV_ID, "", true),
        new Row(WALK, "Ask about this step", WalkthroughActions.ASK_ID, "", true),
        new Row(WALK, "Show / hide inline card", WalkthroughActions.TOGGLE_ID, "", true),

        new Row(STOCK, "Compare with branch…", "Git.CompareWithBranch", "", true),
        new Row(STOCK, "Show file history", "Vcs.ShowTabbedFileHistory", "", true),
        new Row(STOCK, "History for selection", "Vcs.ShowHistoryForBlock", "", true),
        new Row(STOCK, "Git blame", "Annotate", "", true),
        new Row(STOCK, "Next change in diff", "Diff.NextChange",
            "only inside an open diff", false),
        new Row(STOCK, "Previous change in diff", "Diff.PrevChange",
            "only inside an open diff", false),

        new Row(GENERAL, "Prettify JSON in a text block", "com.petros.ireview.PrettifyJsonStringAction",
            "the Java text block under the caret — {{placeholders}} survive", true),
        new Row(GENERAL, "Keyboard shortcuts", PANEL_ID, "", false)
    );

    /** Groups stacked vertically, per column, left to right. */
    private static final List<List<String>> COLUMNS = List.of(
        List.of(MINE, STOCK),
        List.of(WALK, GENERAL)
    );

    public static List<Row> rows() {
        return ROWS;
    }

    public static List<List<String>> columns() {
        return COLUMNS;
    }

    public static List<Row> rowsIn(String group) {
        return ROWS.stream().filter(r -> r.group().equals(group)).toList();
    }

    /**
     * Why a group is on the card, shown small under its caption. Blank when the
     * caption already answers it.
     *
     * The stock group is the one that needs saying. Those actions are not ours,
     * we cannot assign their keys, and they are listed only so that a binding
     * you lost to something else is visible in the same place as the ones that
     * work.
     */
    public static String note(String group) {
        return STOCK.equals(group)
            ? "Not ours — listed so a key you lost to something else is visible here."
            : "";
    }

    /**
     * Split a shortcut into the individual caps the panel draws.
     *
     * The input is the platform's OWN rendering of the shortcut — "⌥⌘D" on macOS,
     * "Ctrl+Alt+D" elsewhere — so the caps can never disagree with the keys
     * IntelliJ prints in its menus. On macOS each modifier is a single glyph and
     * the key name is whatever follows them; everywhere else the parts are
     * separated by "+". A two-stroke chord arrives as ", "-separated strokes and
     * is rejoined with the word "then"; a bare trailing comma is a key, not a
     * separator.
     *
     * An action with no binding yields no caps at all; the panel renders that as
     * the word "unassigned", so a stripped binding reads as a fact rather than
     * as a gap in the drawing.
     */
    public static List<String> caps(String shortcutText, boolean mac) {
        if (shortcutText == null || shortcutText.isBlank()) return List.of();

        List<String> caps = new java.util.ArrayList<>();
        // A chord separates its strokes with ", " — comma AND whitespace. Splitting
        // on a bare comma would swallow the comma KEY, which is a real binding.
        String[] strokes = shortcutText.trim().split(",\\s+");
        for (int i = 0; i < strokes.length; i++) {
            if (i > 0) caps.add("then");
            caps.addAll(mac ? macCaps(strokes[i]) : List.of(strokes[i].split("\\+")));
        }
        return List.copyOf(caps);
    }

    /** The four macOS modifier glyphs, in the order the platform prints them. */
    private static final String MAC_MODIFIERS = "⌃⌥⇧⌘";

    private static List<String> macCaps(String stroke) {
        List<String> caps = new java.util.ArrayList<>();
        int i = 0;
        while (i < stroke.length() && MAC_MODIFIERS.indexOf(stroke.charAt(i)) >= 0) {
            caps.add(String.valueOf(stroke.charAt(i)));
            i++;
        }
        String key = stroke.substring(i);
        if (!key.isEmpty()) caps.add(key);
        return caps;
    }
}
