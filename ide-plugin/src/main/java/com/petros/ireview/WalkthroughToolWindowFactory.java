package com.petros.ireview;

import com.intellij.openapi.actionSystem.ActionManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowFactory;
import com.intellij.ui.content.Content;
import com.intellij.ui.content.ContentFactory;
import org.jetbrains.annotations.NotNull;

import java.util.List;

public final class WalkthroughToolWindowFactory implements ToolWindowFactory {
    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        WalkthroughPanel panel = new WalkthroughPanel(project);
        Content content = ContentFactory.getInstance()
            .createContent(panel.getComponent(), "", false);
        content.setDisposer(panel);
        toolWindow.getContentManager().addContent(content);

        ActionManager actions = ActionManager.getInstance();
        toolWindow.setTitleActions(List.of(
            actions.getAction(WalkthroughZoom.OUT_ID),
            actions.getAction(WalkthroughZoom.IN_ID),
            actions.getAction(WalkthroughZoom.RESET_ID)));
    }
}
