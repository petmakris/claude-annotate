package com.petros.ireview;

import com.intellij.icons.AllIcons;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.popup.JBPopup;
import com.intellij.openapi.ui.popup.JBPopupFactory;
import com.intellij.openapi.util.SystemInfo;
import com.intellij.ui.InplaceButton;
import com.intellij.ui.JBColor;
import com.intellij.ui.components.JBLabel;
import com.intellij.util.ui.JBUI;
import com.intellij.util.ui.UIUtil;
import org.jetbrains.annotations.NotNull;

import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JComponent;
import javax.swing.JPanel;
import javax.swing.JSeparator;
import javax.swing.SwingConstants;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.FontMetrics;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.GridLayout;
import java.awt.RenderingHints;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * The Keyboard Shortcuts card: every key this plugin adds, plus the stock git
 * keys it sits next to, each read from the live keymap.
 *
 * Reading the keymap rather than printing fixed strings is the feature. A
 * binding taken by something else is stripped silently, and a row that says
 * "unassigned" is the only cheap way to find out — {@code Compare.SameVersion}
 * loses ⌘D to multi-cursor the moment anyone rebinds it.
 *
 * Swing, not JCEF: the card is read-only, and the JS-to-Java bridge is dead
 * under IU-261 (see {@link SynthesisPopup}).
 */
public final class ShortcutsPanel {

    private ShortcutsPanel() {}

    // Measured against the IDE's own popup chrome rather than invented: caps
    // sit a shade off the panel background in both themes, never pure white.
    private static final JBColor CAP_BACKGROUND =
        new JBColor(new Color(0xF2F3F5), new Color(0x3C3F41));
    private static final JBColor CAP_BORDER =
        new JBColor(new Color(0xDCDFE3), new Color(0x4E5254));
    private static final JBColor CAP_FOREGROUND =
        new JBColor(new Color(0x3C3F41), new Color(0xC0C4C8));

    public static void show(@NotNull Project project) {
        AtomicReference<JBPopup> handle = new AtomicReference<>();
        JComponent content = build(() -> {
            JBPopup popup = handle.get();
            if (popup != null) popup.cancel();
        });

        JBPopup popup = JBPopupFactory.getInstance()
            .createComponentPopupBuilder(content, content)
            .setTitle(null)
            .setRequestFocus(true)
            .setFocusable(true)
            .setMovable(true)
            .setResizable(false)
            .setCancelOnClickOutside(true)
            .setCancelKeyEnabled(true)
            .createPopup();

        handle.set(popup);
        popup.showCenteredInCurrentWindow(project);
    }

    // ---- layout -----------------------------------------------------------

    private static JComponent build(Runnable onClose) {
        JPanel root = new JPanel(new BorderLayout());
        root.setBackground(UIUtil.getPanelBackground());
        root.add(header(onClose), BorderLayout.NORTH);
        root.add(body(), BorderLayout.CENTER);
        root.add(footer(), BorderLayout.SOUTH);
        return root;
    }

    private static JComponent header(Runnable onClose) {
        JBLabel title = new JBLabel("Keyboard Shortcuts");
        title.setFont(JBUI.Fonts.label(22f).asBold());

        InplaceButton close = new InplaceButton("Close", AllIcons.Actions.Close, e -> onClose.run());

        JPanel row = new JPanel(new BorderLayout());
        row.setOpaque(false);
        row.setBorder(JBUI.Borders.empty(24, 32, 20, 24));
        row.add(title, BorderLayout.WEST);
        row.add(close, BorderLayout.EAST);

        JPanel wrapper = new JPanel(new BorderLayout());
        wrapper.setOpaque(false);
        wrapper.add(row, BorderLayout.CENTER);
        wrapper.add(new JSeparator(SwingConstants.HORIZONTAL), BorderLayout.SOUTH);
        return wrapper;
    }

    private static JComponent body() {
        List<List<String>> columns = ShortcutCatalog.columns();
        JPanel grid = new JPanel(new GridLayout(1, columns.size(), JBUI.scale(72), 0));
        grid.setOpaque(false);
        grid.setBorder(JBUI.Borders.empty(26, 32, 28, 32));
        for (List<String> groups : columns) {
            grid.add(column(groups));
        }
        return grid;
    }

    private static JComponent column(List<String> groups) {
        JPanel column = new JPanel();
        column.setOpaque(false);
        column.setLayout(new BoxLayout(column, BoxLayout.Y_AXIS));
        boolean first = true;
        for (String group : groups) {
            if (!first) column.add(Box.createVerticalStrut(JBUI.scale(30)));
            first = false;
            column.add(caption(group));
            column.add(Box.createVerticalStrut(JBUI.scale(12)));
            for (ShortcutCatalog.Row row : ShortcutCatalog.rowsIn(group)) {
                column.add(row(row));
            }
        }
        column.add(Box.createVerticalGlue());
        return column;
    }

    private static JComponent caption(String group) {
        JBLabel label = new JBLabel(group.toUpperCase());
        label.setFont(JBUI.Fonts.label(13f).asBold());
        label.setForeground(UIUtil.getContextHelpForeground());
        label.setAlignmentX(0f);
        return label;
    }

    private static JComponent row(ShortcutCatalog.Row row) {
        JBLabel label = new JBLabel(row.label());
        label.setFont(JBUI.Fonts.label(16f));

        JPanel line = new JPanel(new BorderLayout(JBUI.scale(40), 0));
        line.setOpaque(false);
        line.setAlignmentX(0f);
        line.setBorder(JBUI.Borders.empty(7, 0));
        line.add(label, BorderLayout.WEST);
        line.add(caps(row.actionId()), BorderLayout.EAST);
        // A BoxLayout hands out the maximum height, which would stretch every
        // row to fill the column; pin it to what the row actually needs.
        line.setMaximumSize(new Dimension(Integer.MAX_VALUE, line.getPreferredSize().height));
        return line;
    }

    private static JComponent caps(String actionId) {
        JPanel keys = new JPanel(new FlowLayout(FlowLayout.RIGHT, JBUI.scale(5), 0));
        keys.setOpaque(false);
        List<String> caps = ShortcutCatalog.caps(Shortcuts.text(actionId), SystemInfo.isMac);

        if (caps.isEmpty()) {
            JBLabel unassigned = new JBLabel("unassigned");
            unassigned.setFont(JBUI.Fonts.label(15f));
            unassigned.setForeground(UIUtil.getContextHelpForeground());
            keys.add(unassigned);
            return keys;
        }
        for (String cap : caps) {
            if ("then".equals(cap)) {
                JBLabel then = new JBLabel("then");
                then.setFont(JBUI.Fonts.label(13f));
                then.setForeground(UIUtil.getContextHelpForeground());
                keys.add(then);
            } else {
                keys.add(new Cap(cap));
            }
        }
        return keys;
    }

    private static JComponent footer() {
        JPanel row = new JPanel(new FlowLayout(FlowLayout.CENTER, JBUI.scale(8), 0));
        row.setOpaque(false);
        row.setBorder(JBUI.Borders.empty(18, 0, 20, 0));

        JBLabel before = new JBLabel("Press");
        JBLabel after = new JBLabel("to close");
        for (JBLabel label : List.of(before, after)) {
            label.setFont(JBUI.Fonts.label(15f));
            label.setForeground(UIUtil.getContextHelpForeground());
        }
        row.add(before);
        row.add(new Cap("Esc"));
        row.add(after);

        JPanel wrapper = new JPanel(new BorderLayout());
        wrapper.setOpaque(false);
        wrapper.add(new JSeparator(SwingConstants.HORIZONTAL), BorderLayout.NORTH);
        wrapper.add(row, BorderLayout.CENTER);
        return wrapper;
    }

    // ---- the key cap ------------------------------------------------------

    /** One rounded key cap. Painted rather than styled: Swing has no border radius. */
    private static final class Cap extends JComponent {

        private final String text;

        Cap(String text) {
            this.text = text;
            setFont(JBUI.Fonts.label(15f));
        }

        @Override public Dimension getPreferredSize() {
            FontMetrics metrics = getFontMetrics(getFont());
            int width = Math.max(JBUI.scale(36), metrics.stringWidth(text) + JBUI.scale(20));
            return new Dimension(width, JBUI.scale(33));
        }

        @Override public Dimension getMaximumSize() {
            return getPreferredSize();
        }

        @Override protected void paintComponent(Graphics g) {
            Graphics2D g2 = (Graphics2D) g.create();
            try {
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                int arc = JBUI.scale(9);
                int w = getWidth() - 1;
                int h = getHeight() - 1;
                g2.setColor(CAP_BACKGROUND);
                g2.fillRoundRect(0, 0, w, h, arc, arc);
                g2.setColor(CAP_BORDER);
                g2.drawRoundRect(0, 0, w, h, arc, arc);
                g2.setColor(CAP_FOREGROUND);
                g2.setFont(getFont());
                FontMetrics metrics = g2.getFontMetrics();
                g2.drawString(text,
                    (getWidth() - metrics.stringWidth(text)) / 2f,
                    (getHeight() - metrics.getHeight()) / 2f + metrics.getAscent());
            } finally {
                g2.dispose();
            }
        }
    }

    // ---- the action that opens it -----------------------------------------

    public static final class Show extends AnAction {

        @Override public void actionPerformed(@NotNull AnActionEvent e) {
            Project project = e.getProject();
            if (project != null) ShortcutsPanel.show(project);
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() {
            return ActionUpdateThread.BGT;
        }
    }
}
