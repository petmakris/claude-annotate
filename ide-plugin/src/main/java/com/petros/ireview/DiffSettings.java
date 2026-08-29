package com.petros.ireview;

import com.intellij.openapi.components.PersistentStateComponent;
import com.intellij.openapi.components.State;
import com.intellij.openapi.components.Storage;
import com.intellij.openapi.options.Configurable;
import com.intellij.openapi.project.Project;
import com.intellij.ui.components.JBLabel;
import com.intellij.ui.components.JBTextField;
import com.intellij.util.ui.FormBuilder;
import com.intellij.util.ui.JBUI;
import com.intellij.util.xmlb.XmlSerializerUtil;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import javax.swing.JComponent;
import javax.swing.JPanel;
import java.awt.BorderLayout;
import java.util.Objects;

/**
 * Per-project settings for the diff actions. One field, so one class: the ref
 * that "Diff against base branch" compares against when the automatic guess is
 * wrong. Blank means guess — see {@link BaseBranchResolver} for the order.
 */
@State(name = "ClaudeIdeReviewDiffSettings", storages = @Storage("claude-ide-review.xml"))
public final class DiffSettings implements PersistentStateComponent<DiffSettings.Values> {

    /** Serialised shape. Public fields, because that is what the XML serialiser reads. */
    public static final class Values {
        public String baseBranch = "";
    }

    private Values values = new Values();

    public static DiffSettings get(@NotNull Project project) {
        return project.getService(DiffSettings.class);
    }

    @Override public Values getState() {
        return values;
    }

    @Override public void loadState(@NotNull Values loaded) {
        XmlSerializerUtil.copyBean(loaded, values);
    }

    public String baseBranch() {
        return values.baseBranch == null ? "" : values.baseBranch;
    }

    public void setBaseBranch(String ref) {
        values.baseBranch = ref == null ? "" : ref.trim();
    }

    /** Settings → Tools → Claude IDE Review. */
    public static final class Ui implements Configurable {

        private final Project project;
        private final JBTextField field = new JBTextField();

        public Ui(@NotNull Project project) {
            this.project = project;
        }

        @Override public String getDisplayName() {
            return "Claude IDE Review";
        }

        @Override public @Nullable JComponent createComponent() {
            JBLabel hint = new JBLabel("<html>Leave blank to resolve automatically: origin/HEAD, then "
                + String.join(", ", BaseBranchResolver.candidates()) + ".</html>");
            hint.setForeground(JBUI.CurrentTheme.ContextHelp.FOREGROUND);

            JPanel panel = new JPanel(new BorderLayout());
            panel.add(FormBuilder.createFormBuilder()
                .addLabeledComponent("Base branch for diff:", field)
                .addComponentToRightColumn(hint)
                .addComponentFillVertically(new JPanel(), 0)
                .getPanel(), BorderLayout.CENTER);
            return panel;
        }

        @Override public boolean isModified() {
            return !Objects.equals(field.getText().trim(), DiffSettings.get(project).baseBranch());
        }

        @Override public void apply() {
            DiffSettings.get(project).setBaseBranch(field.getText());
        }

        @Override public void reset() {
            field.setText(DiffSettings.get(project).baseBranch());
        }
    }
}
