package com.petros.ireview;

import com.intellij.openapi.actionSystem.ActionPromoter;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.DataContext;
import org.jetbrains.annotations.NotNull;

import java.util.ArrayList;
import java.util.List;

/**
 * Cmd+Shift+M is also "Move to another changelist" in the stock Mac keymap, in the editor and in the
 * Changes view. When both actions are on the key, the app map goes first.
 */
public final class AppMapPromoter implements ActionPromoter {
    @Override
    public List<AnAction> promote(@NotNull List<? extends AnAction> actions, @NotNull DataContext context) {
        List<AnAction> mine = new ArrayList<>();
        for (AnAction a : actions) if (a instanceof AppMapActions.Show) mine.add(a);
        return mine;
    }
}
