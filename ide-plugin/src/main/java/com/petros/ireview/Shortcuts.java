package com.petros.ireview;

import com.intellij.openapi.actionSystem.ActionManager;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.Shortcut;
import com.intellij.openapi.keymap.KeymapUtil;
import org.jetbrains.annotations.NotNull;

/**
 * The one place that turns an action id into the keys currently bound to it.
 *
 * Always ask the live keymap; never print a fixed string. A shortcut declared
 * in plugin.xml is only a default — the user can rebind it, and reassigning a
 * key strips whatever held it before without warning. Anything that shows a key
 * to the user has to read what is actually bound, or it will confidently name a
 * key that does nothing.
 *
 * Returns empty for an action that does not exist in this IDE and for one that
 * exists with no binding; callers decide how to say "unassigned".
 */
public final class Shortcuts {

    private Shortcuts() {}

    /** The first bound shortcut in the platform's own notation ("⌥D", "Ctrl+Alt+D"), or empty. */
    public static @NotNull String text(@NotNull String actionId) {
        AnAction action = ActionManager.getInstance().getAction(actionId);
        if (action == null) return "";
        Shortcut[] shortcuts = action.getShortcutSet().getShortcuts();
        return shortcuts.length == 0 ? "" : KeymapUtil.getShortcutText(shortcuts[0]);
    }
}
