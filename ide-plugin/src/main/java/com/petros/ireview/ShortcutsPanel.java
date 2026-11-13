package com.petros.ireview;

import com.intellij.icons.AllIcons;
import com.intellij.notification.NotificationGroupManager;
import com.intellij.notification.NotificationType;
import com.intellij.openapi.actionSystem.ActionManager;
import com.intellij.openapi.actionSystem.ActionPlaces;
import com.intellij.openapi.actionSystem.ActionUiKind;
import com.intellij.openapi.actionSystem.ActionUpdateThread;
import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.actionSystem.CommonDataKeys;
import com.intellij.openapi.actionSystem.DataContext;
import com.intellij.openapi.actionSystem.ex.ActionUtil;
import com.intellij.openapi.actionSystem.impl.SimpleDataContext;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.popup.JBPopup;
import com.intellij.openapi.ui.popup.JBPopupFactory;
import com.intellij.openapi.util.SystemInfo;
import com.intellij.openapi.vfs.VirtualFile;
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
import java.awt.Cursor;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.FontMetrics;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.GridLayout;
import java.awt.RenderingHints;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * The Keyboard Shortcuts card: every key this plugin adds, plus the stock git
 * keys it sits next to, each read from the live keymap.
 *
 * Reading the keymap rather than printing fixed strings is the feature. A
 * binding taken by something else is stripped silently, and a row that says
 * "unassigned" is the only cheap way to find out.
 *
 * The card is also a launcher: clicking a row runs its action. That is what
 * makes an "unassigned" row useful rather than merely honest — the thing is
 * still reachable, it just has no key. Which rows may be clicked is decided in
 * {@link ShortcutCatalog}, not here.
 *
 * <b>Why the context is captured before the popup opens.</b> The diff actions
 * read {@code CommonDataKeys.VIRTUAL_FILE}, and this popup takes focus. While
 * it is open the focus owner is the card, so a context resolved at click time
 * has no file in it and every action would quietly refuse to run. The context
 * is therefore taken from the event that opened the card and carried for its
 * lifetime, which is seconds.
 *
 * Swing, not JCEF: the JS-to-Java bridge is dead under IU-261 (see
 * {@link SynthesisPopup}).
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
    /** Hover fill for a clickable row. Enough to read as a target, not enough to shout. */
    private static final JBColor ROW_HOVER =
        new JBColor(new Color(0xE9EBEF), new Color(0x393B3D));

    public static void show(@NotNull Project project, @NotNull DataContext context) {
        AtomicReference<JBPopup> handle = new AtomicReference<>();
        Runnable close = () -> {
            JBPopup popup = handle.get();
            if (popup != null) popup.cancel();
        };
        JComponent content = build(context, close);

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

    private static JComponent build(DataContext context, Runnable onClose) {
        JPanel root = new JPanel(new BorderLayout());
        root.setBackground(UIUtil.getPanelBackground());
        root.add(header(onClose), BorderLayout.NORTH);
        root.add(body(context, onClose), BorderLayout.CENTER);
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

    private static JComponent body(DataContext context, Runnable onClose) {
        List<List<String>> columns = ShortcutCatalog.columns();
        JPanel grid = new JPanel(new GridLayout(1, columns.size(), JBUI.scale(72), 0));
        grid.setOpaque(false);
        grid.setBorder(JBUI.Borders.empty(26, 32, 28, 32));
        for (List<String> groups : columns) {
            grid.add(column(groups, context, onClose));
        }
        return grid;
    }

    private static JComponent column(List<String> groups, DataContext context, Runnable onClose) {
        JPanel column = new JPanel();
        column.setOpaque(false);
        column.setLayout(new BoxLayout(column, BoxLayout.Y_AXIS));
        boolean first = true;
        for (String group : groups) {
            if (!first) column.add(Box.createVerticalStrut(JBUI.scale(30)));
            first = false;
            column.add(caption(group));
            String note = ShortcutCatalog.note(group);
            if (!note.isBlank()) {
                column.add(Box.createVerticalStrut(JBUI.scale(4)));
                column.add(note(note));
            }
            column.add(Box.createVerticalStrut(JBUI.scale(12)));
            for (ShortcutCatalog.Row row : ShortcutCatalog.rowsIn(group)) {
                column.add(row(row, context, onClose));
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

    private static JComponent note(String text) {
        JBLabel label = new JBLabel(text);
        label.setFont(JBUI.Fonts.label(14f));
        label.setForeground(UIUtil.getContextHelpForeground());
        label.setAlignmentX(0f);
        return label;
    }

    private static JComponent row(ShortcutCatalog.Row row, DataContext context, Runnable onClose) {
        JBLabel label = new JBLabel(row.label());
        label.setFont(JBUI.Fonts.label(16f));

        JPanel line = new JPanel(new BorderLayout(JBUI.scale(40), 0));
        line.setOpaque(false);
        line.setAlignmentX(0f);
        line.add(label, BorderLayout.WEST);
        line.add(caps(row.actionId()), BorderLayout.EAST);
        // A BoxLayout hands out the maximum height, which would stretch every
        // row to fill the column; pin it to what the row actually needs.
        line.setMaximumSize(new Dimension(Integer.MAX_VALUE, line.getPreferredSize().height));

        JPanel stack = new JPanel();
        stack.setLayout(new BoxLayout(stack, BoxLayout.Y_AXIS));
        stack.setOpaque(false);
        stack.setAlignmentX(0f);
        // The horizontal inset is what the hover fill needs so the text is not
        // flush against the edge of the highlight.
        stack.setBorder(JBUI.Borders.empty(6, 8));
        stack.add(line);
        if (!row.detail().isBlank()) {
            // Only two points below the label, not the usual caption size. This
            // line is the one that says what a key actually compares, which is
            // the thing nobody could tell from the labels — it has to be read,
            // not skimmed past. It stays subordinate by colour, not by size.
            JBLabel detail = new JBLabel(row.detail());
            detail.setFont(JBUI.Fonts.label(15f));
            detail.setForeground(UIUtil.getContextHelpForeground());
            detail.setAlignmentX(0f);
            detail.setBorder(JBUI.Borders.emptyTop(3));
            stack.add(detail);
        }
        stack.setMaximumSize(new Dimension(Integer.MAX_VALUE, stack.getPreferredSize().height));

        if (row.clickable()) makeClickable(stack, row.actionId(), context, onClose);
        return stack;
    }

    /**
     * Turn a row into a button: hand cursor, hover fill, and a click that closes
     * the card before running the action.
     *
     * Closing first is not cosmetic. The action opens a diff, and a modal-ish
     * popup still on screen would sit over it and keep the focus it needs.
     */
    private static void makeClickable(JPanel row, String actionId, DataContext context, Runnable onClose) {
        row.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        row.addMouseListener(new MouseAdapter() {
            @Override public void mouseEntered(MouseEvent e) {
                row.setOpaque(true);
                row.setBackground(ROW_HOVER);
                row.repaint();
            }

            @Override public void mouseExited(MouseEvent e) {
                row.setOpaque(false);
                row.repaint();
            }

            @Override public void mouseClicked(MouseEvent e) {
                onClose.run();
                run(actionId, context);
            }
        });
    }

    /**
     * Run one row's action against the captured context.
     *
     * {@code ActionUtil.performAction} rather than any of the {@code invokeAction}
     * or {@code performDumbAware*} overloads: those are all deprecated in this
     * platform, and this is the one that is not.
     *
     * The action is NOT asked {@code update()} first, even though that would let
     * a refusal be reported instead of looking like a dead button. Every action
     * on this card declares {@link ActionUpdateThread#BGT}, and a click arrives
     * on the EDT — calling {@code update()} here is exactly the thing that
     * declaration forbids. The cheap guard below covers the one case that
     * actually happens: the card opened with no file in the editor, which no row
     * on it can do anything with.
     */
    private static void run(String actionId, DataContext context) {
        AnAction action = ActionManager.getInstance().getAction(actionId);
        if (action == null) return;

        Project project = CommonDataKeys.PROJECT.getData(context);
        if (CommonDataKeys.VIRTUAL_FILE.getData(context) == null) {
            if (project != null) {
                NotificationGroupManager.getInstance()
                    .getNotificationGroup("Claude IDE Review")
                    .createNotification(
                        "Open a file first — every key on this card acts on the file in the editor.",
                        NotificationType.INFORMATION)
                    .notify(project);
            }
            return;
        }
        ActionUtil.performAction(action, AnActionEvent.createEvent(
            action, context, null, ActionPlaces.POPUP, ActionUiKind.POPUP, null));
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

        JBLabel before = new JBLabel("Click a row to run it, or press");
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
            if (project == null) return;
            // Captured here, while the editor is still the focus owner — see the
            // class javadoc. Only the keys the listed actions actually read:
            // the diff actions want the file, git blame wants the editor.
            //
            // Added one at a time rather than through Builder.addAll, which is
            // deprecated for removal. A key is added only when it has a value,
            // because a null recorded in the context is not the same as an
            // absent one — it tells the action to stop looking rather than to
            // fall back to whatever else it would have consulted.
            SimpleDataContext.Builder builder = SimpleDataContext.builder()
                .add(CommonDataKeys.PROJECT, project);
            VirtualFile file = e.getData(CommonDataKeys.VIRTUAL_FILE);
            if (file != null) builder.add(CommonDataKeys.VIRTUAL_FILE, file);
            Editor editor = e.getData(CommonDataKeys.EDITOR);
            if (editor != null) builder.add(CommonDataKeys.EDITOR, editor);

            ShortcutsPanel.show(project, builder.build());
        }

        @Override public @NotNull ActionUpdateThread getActionUpdateThread() {
            return ActionUpdateThread.BGT;
        }
    }
}
