package com.petros.ireview;

import com.intellij.openapi.components.PersistentStateComponent;
import com.intellij.openapi.components.State;
import com.intellij.openapi.components.Storage;
import com.intellij.openapi.options.Configurable;
import com.intellij.openapi.project.Project;
import com.intellij.ui.components.JBCheckBox;
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
 * Per-project settings for the diff actions and the synthesis popup.
 */
@State(name = "ClaudeIdeReviewDiffSettings", storages = @Storage("claude-ide-review.xml"))
public final class DiffSettings implements PersistentStateComponent<DiffSettings.Values> {

    /** Serialised shape. Public fields, because that is what the XML serialiser reads. */
    public static final class Values {
        public String baseBranch = "";
        /** Default true: the popup should read distinctly from the code editor
         *  behind it, not blend into whatever editor scheme happens to be
         *  active — see {@link SynthesisBrowser}'s material palette. */
        public boolean useMaterialTheme = true;
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

    public boolean useMaterialTheme() {
        return values.useMaterialTheme;
    }

    public void setUseMaterialTheme(boolean use) {
        values.useMaterialTheme = use;
    }

    /** Settings → Tools → Claude IDE Review. */
    public static final class Ui implements Configurable {

        private final Project project;
        private final JBTextField field = new JBTextField();
        private final JBCheckBox materialThemeCheckBox =
                new JBCheckBox("Use a fixed high-contrast theme for the synthesis popup");

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

            JBLabel themeHint = new JBLabel("<html>Off: the popup mirrors your live editor color scheme.</html>");
            themeHint.setForeground(JBUI.CurrentTheme.ContextHelp.FOREGROUND);

            JPanel panel = new JPanel(new BorderLayout());
            panel.add(FormBuilder.createFormBuilder()
                .addLabeledComponent("Base branch for diff:", field)
                .addComponentToRightColumn(hint)
                .addComponent(materialThemeCheckBox)
                .addComponentToRightColumn(themeHint)
                .addComponentFillVertically(new JPanel(), 0)
                .getPanel(), BorderLayout.CENTER);
            return panel;
        }

        @Override public boolean isModified() {
            DiffSettings settings = DiffSettings.get(project);
            return !Objects.equals(field.getText().trim(), settings.baseBranch())
                || materialThemeCheckBox.isSelected() != settings.useMaterialTheme();
        }

        @Override public void apply() {
            DiffSettings settings = DiffSettings.get(project);
            settings.setBaseBranch(field.getText());
            settings.setUseMaterialTheme(materialThemeCheckBox.isSelected());
        }

        @Override public void reset() {
            DiffSettings settings = DiffSettings.get(project);
            field.setText(settings.baseBranch());
            materialThemeCheckBox.setSelected(settings.useMaterialTheme());
        }
    }
}
