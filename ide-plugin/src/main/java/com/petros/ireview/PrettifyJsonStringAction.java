package com.petros.ireview;

import com.intellij.codeInsight.hint.HintManager;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.command.WriteCommandAction;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.editor.Document;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.TextRange;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.PsiLiteralExpression;
import com.intellij.psi.util.PsiTreeUtil;
import org.jetbrains.annotations.NotNull;

import java.util.Optional;

/**
 * Reformats the JSON inside the Java text block under the caret, preserving
 * {@code {{placeholder}}} tokens. Enabled only when the caret sits in a text block
 * ({@code """ ... """}); single-line string literals can't hold multi-line JSON.
 */
public class PrettifyJsonStringAction extends AnAction {

    private static final Logger LOG = Logger.getInstance(PrettifyJsonStringAction.class);

    @Override
    public @NotNull ActionUpdateThread getActionUpdateThread() {
        return ActionUpdateThread.BGT;
    }

    @Override
    public void update(@NotNull AnActionEvent e) {
        boolean enabled;
        try {
            PsiFile file = e.getData(CommonDataKeys.PSI_FILE);
            Editor editor = e.getData(CommonDataKeys.EDITOR);
            enabled = file != null && editor != null && findTextBlockAtCaret(file, editor) != null;
        } catch (Throwable t) {
            LOG.warn("[PrettifyJSON] update() threw", t);
            enabled = false;
        }
        e.getPresentation().setEnabledAndVisible(enabled);
    }

    @Override
    public void actionPerformed(@NotNull AnActionEvent e) {
        Project project = e.getProject();
        PsiFile file = e.getData(CommonDataKeys.PSI_FILE);
        Editor editor = e.getData(CommonDataKeys.EDITOR);
        if (project == null || file == null || editor == null) {
            return;
        }
        PsiLiteralExpression literal = findTextBlockAtCaret(file, editor);
        if (literal == null) {
            HintManager.getInstance().showInformationHint(editor, "Put the caret inside a \"\"\" text block");
            return;
        }
        if (!(literal.getValue() instanceof String content)) {
            HintManager.getInstance().showInformationHint(editor, "Could not read text block content");
            return;
        }
        Optional<String> formatted = JsonStringPrettifier.prettify(content);
        if (formatted.isEmpty()) {
            HintManager.getInstance().showInformationHint(editor, "Not valid JSON — nothing to format");
            return;
        }

        String baseIndent = closingDelimiterIndent(literal.getText());
        String replacement = buildTextBlock(formatted.get(), baseIndent);
        TextRange range = literal.getTextRange();
        Document document = editor.getDocument();
        WriteCommandAction.runWriteCommandAction(project, "Prettify JSON String", null,
            () -> document.replaceString(range.getStartOffset(), range.getEndOffset(), replacement),
            file);
    }

    /** The text block literal at the caret, or null if the caret isn't inside one. */
    private static PsiLiteralExpression findTextBlockAtCaret(PsiFile file, Editor editor) {
        int offset = editor.getCaretModel().getOffset();
        PsiElement element = file.findElementAt(offset);
        if (element == null && offset > 0) {
            element = file.findElementAt(offset - 1);
        }
        PsiLiteralExpression literal = PsiTreeUtil.getParentOfType(element, PsiLiteralExpression.class, false);
        if (literal == null) {
            return null;
        }
        return literal.getText().startsWith("\"\"\"") ? literal : null;
    }

    /** Leading whitespace of the text block's closing-delimiter line — the indent to re-apply. */
    private static String closingDelimiterIndent(String rawLiteralText) {
        int lastNewline = rawLiteralText.lastIndexOf('\n');
        if (lastNewline < 0) {
            return "";
        }
        String lastLine = rawLiteralText.substring(lastNewline + 1);
        int i = 0;
        while (i < lastLine.length() && (lastLine.charAt(i) == ' ' || lastLine.charAt(i) == '\t')) {
            i++;
        }
        return lastLine.substring(0, i);
    }

    /**
     * Java source for a text block whose value is {@code json} plus a trailing
     * newline. {@code json} is the block's value, not its source: the action
     * read it through {@code getValue()}, which has already interpreted the
     * escapes, so it must be escaped again on the way back or {@code \n} inside
     * a JSON string turns into a real line break and the value changes.
     */
    static String buildTextBlock(String json, String baseIndent) {
        StringBuilder sb = new StringBuilder("\"\"\"\n");
        for (String line : json.split("\n", -1)) {
            sb.append(baseIndent).append(escapeTextBlockLine(line)).append('\n');
        }
        sb.append(baseIndent).append("\"\"\"");
        return sb.toString();
    }

    /** Escapes one line of a text block's value: every backslash is doubled, and
     *  every third quote in a run is escaped so no {@code """} closes the block. */
    private static String escapeTextBlockLine(String line) {
        StringBuilder sb = new StringBuilder(line.length());
        int quoteRun = 0;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') {
                quoteRun++;
                if (quoteRun == 3) {
                    sb.append("\\\"");
                    quoteRun = 0;
                } else {
                    sb.append('"');
                }
                continue;
            }
            quoteRun = 0;
            if (c == '\\') {
                sb.append("\\\\");
            } else {
                sb.append(c);
            }
        }
        return sb.toString();
    }
}
