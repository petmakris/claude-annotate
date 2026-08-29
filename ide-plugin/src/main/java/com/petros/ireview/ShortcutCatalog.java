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
 * Stock IntelliJ actions are listed alongside this plugin's own. That is the
 * point of the panel rather than an afterthought: rebinding a key to something
 * else silently strips whatever held it before, and a row reading "unassigned"
 * is the only cheap way to notice.
 */
public final class ShortcutCatalog {

    private ShortcutCatalog() {}

    public static final String PANEL_ID = "com.petros.ireview.ShortcutsPanel";

    private static final String DIFF = "Diff & history";
    private static final String WALK = "Walkthrough";
    private static final String GENERAL = "General";

    /** One line of the panel: what it does, and the action whose keys it prints. */
    public record Row(String group, String label, String actionId) {}

    private static final List<Row> ROWS = List.of(
        new Row(DIFF, "Smart diff — this file",   SmartDiffActions.FORWARD_ID),
        new Row(DIFF, "Smart diff — step back",   SmartDiffActions.BACK_ID),
        new Row(DIFF, "Diff against base branch", SmartDiffActions.BASE_ID),
        new Row(DIFF, "Compare with HEAD",        "Compare.SameVersion"),
        new Row(DIFF, "Compare with branch…",     "Git.CompareWithBranch"),
        new Row(DIFF, "Show file history",        "Vcs.ShowTabbedFileHistory"),
        new Row(DIFF, "History for selection",    "Vcs.ShowHistoryForBlock"),
        new Row(DIFF, "Git blame",                "Annotate"),
        new Row(DIFF, "Next change in diff",      "Diff.NextChange"),
        new Row(DIFF, "Previous change in diff",  "Diff.PrevChange"),

        new Row(WALK, "Next step",                WalkthroughActions.NEXT_ID),
        new Row(WALK, "Previous step",            WalkthroughActions.PREV_ID),
        new Row(WALK, "Ask about this step",      WalkthroughActions.ASK_ID),
        new Row(WALK, "Show / hide inline card",  WalkthroughActions.TOGGLE_ID),

        new Row(GENERAL, "Keyboard shortcuts",    PANEL_ID)
    );

    /** Groups stacked vertically, per column, left to right. */
    private static final List<List<String>> COLUMNS = List.of(
        List.of(DIFF),
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
     * Split a shortcut into the individual caps the panel draws.
     *
     * The input is the platform's OWN rendering of the shortcut — "\u2325\u2318D" on macOS,
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
    private static final String MAC_MODIFIERS = "\u2303\u2325\u21e7\u2318";

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
