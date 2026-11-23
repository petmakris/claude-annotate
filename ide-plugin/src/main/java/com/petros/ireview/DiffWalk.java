package com.petros.ireview;

/**
 * Whether a press of Smart Diff continues the last walk or starts a new one.
 *
 * {@link DiffHistory} decides what a given depth shows. This decides which
 * depth the next press lands on, which is a different question and the one that
 * went wrong.
 *
 * <b>The bug this exists to stop.</b> The walk used to be remembered for the
 * life of the project and reset only when the file's modified state flipped. So
 * every press ratcheted one commit deeper, for hours, invisibly. A file whose
 * last three commits were from 2026, 2025 and 2025 would answer the third press
 * of "show me what changed here" with a diff between two commits from the year
 * before last — correctly, by the old rule, and uselessly.
 *
 * <b>The rule.</b> A chain of presses is one gesture: press, read, press again,
 * go deeper. A press after a pause is a new question, and a new question starts
 * at the top. So a walk is resumable only within {@link #RESUME_MILLIS} of the
 * press that set it.
 *
 * The window is deliberately generous. Reading a diff properly takes longer
 * than a keystroke, and a window that expired while you were still looking at
 * the result would break the "press again to go further back" contract — the
 * opposite failure, and just as confusing. Ninety seconds is long enough to
 * read a screen of diff and decide, short enough that the walk cannot follow
 * you into a different task.
 *
 * Expiry sends BOTH directions to {@link DiffHistory#firstDepth()}, not just
 * forward. Stepping back from a walk that no longer exists has no sensible
 * meaning, and the newest change is the furthest toward the working copy a walk
 * can be — which is what the back key is for.
 */
public final class DiffWalk {

    private DiffWalk() {}

    /** How long a walk stays resumable. See the class javadoc for why it is this long. */
    public static final long RESUME_MILLIS = 90_000L;

    /**
     * Where a walk stood, and the state it stood in.
     *
     * @param depth the {@link DiffHistory} depth that was last shown
     * @param dirty whether the file had uncommitted changes at that moment
     * @param at    when the press happened, in milliseconds
     */
    public record Stop(int depth, boolean dirty, long at) {}

    /**
     * Whether {@code previous} may be continued rather than restarted.
     *
     * The dirty check is the older half of the rule and still earns its place:
     * after you edit or commit a file, the thing you want to see is that change,
     * not the next commit down from wherever the walk had wandered.
     */
    public static boolean resumable(Stop previous, boolean dirty, long now) {
        return previous != null
            && previous.dirty() == dirty
            && now - previous.at() <= RESUME_MILLIS;
    }

    /**
     * The depth the next press lands on.
     *
     * @param previous where the walk stood, or null if this file has none
     * @param history  this file's revisions, which bound the walk
     * @param dirty    whether the file has uncommitted changes now
     * @param forward  true to step further back through history, false to step
     *                 back toward the working copy
     * @param now      the current time in milliseconds
     */
    public static int nextDepth(Stop previous, DiffHistory history, boolean dirty, boolean forward, long now) {
        if (!resumable(previous, dirty, now)) {
            return history.firstDepth();
        }
        return forward ? history.advance(previous.depth()) : history.back(previous.depth());
    }
}
