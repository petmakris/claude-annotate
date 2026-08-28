package com.petros.ireview;

/**
 * Parsing for the anchor strings the review server stores.
 *
 * Two shapes exist (see interactive_review/SKILL.md):
 *   <path>:<L|R>:<line>            a single diff line
 *   <path>:<L|R>:<start>-<end>     a range of diff lines
 * plus the whole-PR anchor {@code __general__}, which has no location at all.
 *
 * Pure and Swing-free. Every caller that needs "which line is this?" goes
 * through {@link #startLine} — hand-rolled {@code Integer.parseInt} on the tail
 * silently dropped every range anchor from the gutter and the stale check.
 */
public final class ReviewAnchor {

    /** The anchor the server uses for a comment on the PR as a whole. */
    public static final String GENERAL = "__general__";

    private ReviewAnchor() {}

    /**
     * First line of an anchor tail ({@code "42"} or {@code "42-48"}),
     * 1-based as stored, or -1 when the tail names no line.
     */
    public static int startLine(String tail) {
        if (tail == null || tail.isEmpty()) return -1;
        int dash = tail.indexOf('-');
        String head = dash < 0 ? tail : tail.substring(0, dash);
        try {
            int n = Integer.parseInt(head);
            return n > 0 ? n : -1;
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** True when the anchor names a file, a side and at least one line. */
    public static boolean isLineAnchor(String anchor) {
        if (anchor == null) return false;
        String[] p = anchor.split(":", 3);
        return p.length == 3 && !p[0].isEmpty() && startLine(p[2]) > 0;
    }

    /** True for the whole-PR anchor, which has no diff line to sit on. */
    public static boolean isGeneral(String anchor) {
        return GENERAL.equals(anchor);
    }
}
