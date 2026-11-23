package com.petros.ireview;

import com.intellij.openapi.editor.Document;
import com.intellij.openapi.editor.ex.EditorEx;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.TextRange;
import com.intellij.openapi.ui.popup.JBPopup;
import com.intellij.openapi.ui.popup.JBPopupFactory;
import com.intellij.openapi.util.Disposer;
import com.intellij.ui.JBColor;
import com.intellij.util.ui.JBUI;
import org.jetbrains.annotations.NotNull;

import javax.swing.AbstractAction;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTextArea;
import javax.swing.KeyStroke;
import javax.swing.SwingUtilities;
import java.awt.BorderLayout;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Inline popup anchored to a diff line. Owns the popup chrome (drag, close
 * button, version label, Esc-to-close with an unsaved-input guard) around a
 * {@link ThreadConversationView}, which does the actual rendering/asking.
 */
public final class SynthesisPopup {

    /** One open popup per project+anchor; opening a new one cancels the
     *  previous. Keyed by project too — two open projects can review files with
     *  the same relative path, and an anchor-only key would cross-cancel them. */
    private static final java.util.Map<String, JBPopup> OPEN_POPUPS =
            new java.util.concurrent.ConcurrentHashMap<>();

    private static String popupKey(@NotNull Project project, @NotNull String anchor) {
        return project.getLocationHash() + "|" + anchor;
    }

    /** True when a popup for this anchor is currently on screen — used to skip
     *  the "Claude answered" balloon when the user is already looking at it. */
    static boolean isOpenFor(@NotNull Project project, @NotNull String anchor) {
        JBPopup p = OPEN_POPUPS.get(popupKey(project, anchor));
        return p != null && !p.isDisposed() && p.isVisible();
    }

    /** Open the popup for a diff-line anchor, positioned against its editor. */
    public static void show(@NotNull Project project,
                            @NotNull EditorEx editor,
                            @NotNull String anchor,
                            int visualLine) {
        show(project, anchor,
             () -> lineTextAt(editor.getDocument(), visualLine),
             popup -> popup.showInBestPositionFor(editor));
    }

    /**
     * Open the popup for an anchor that has no diff line to sit on — the
     * whole-PR {@code __general__} thread. There is no editor to position
     * against and no line of code to quote, so it opens over {@code owner}
     * (the side-panel list) with an empty anchor text.
     */
    public static void showDetached(@NotNull Project project,
                                    @NotNull Component owner,
                                    @NotNull String anchor) {
        show(project, anchor, () -> "", popup -> popup.showInCenterOf(owner));
    }

    /**
     * @param anchorTextSupplier the code the question is about, echoed back to
     *        Claude so a drifted anchor can still be resolved; empty when the
     *        anchor is not a line.
     * @param shower places the built popup on screen — the only step that needs
     *        to know whether an editor is involved.
     */
    private static void show(@NotNull Project project,
                             @NotNull String anchor,
                             @NotNull java.util.function.Supplier<String> anchorTextSupplier,
                             @NotNull java.util.function.Consumer<JBPopup> shower) {
        ReviewSessionClient client = ReviewSessionService.get(project).client();
        String popupKey = popupKey(project, anchor);

        // Dedupe: if there's already a popup open for this anchor, close it
        // before opening a new one (gives the user the new screen position).
        JBPopup existing = OPEN_POPUPS.remove(popupKey);
        if (existing != null && !existing.isDisposed()) {
            existing.cancel();
        }

        AtomicReference<JBPopup> popupRef = new AtomicReference<>();

        JPanel content = new JPanel(new BorderLayout());
        content.setBorder(JBUI.Borders.empty(4, 6));
        content.setPreferredSize(new Dimension(480, 200));

        // Make any non-input area of the popup draggable. Without a title bar,
        // there's nothing else to grab. We install a drag listener on the
        // content panel and the header — clicks on the synthesisPane / input /
        // buttons still get their own events (this listener fires on the
        // background, not on child components).
        java.awt.event.MouseAdapter dragger = new java.awt.event.MouseAdapter() {
            java.awt.Point pressOnScreen;
            java.awt.Point windowAtPress;
            @Override public void mousePressed(java.awt.event.MouseEvent e) {
                pressOnScreen = e.getLocationOnScreen();
                java.awt.Window w = SwingUtilities.getWindowAncestor(e.getComponent());
                if (w != null) windowAtPress = w.getLocation();
            }
            @Override public void mouseDragged(java.awt.event.MouseEvent e) {
                if (pressOnScreen == null || windowAtPress == null) return;
                java.awt.Window w = SwingUtilities.getWindowAncestor(e.getComponent());
                if (w == null) return;
                java.awt.Point now = e.getLocationOnScreen();
                w.setLocation(windowAtPress.x + (now.x - pressOnScreen.x),
                              windowAtPress.y + (now.y - pressOnScreen.y));
            }
        };
        content.addMouseListener(dragger);
        content.addMouseMotionListener(dragger);

        // Header: native-feeling close button on the right (uses IDEA's standard
        // close icon — themed, has hover/pressed states out of the box).
        JPanel headerRow = new JPanel(new BorderLayout());
        com.intellij.ui.InplaceButton dismissBtn = new com.intellij.ui.InplaceButton(
            new com.intellij.openapi.ui.popup.IconButton(
                "Close annotation",
                com.intellij.icons.AllIcons.Actions.Close,
                com.intellij.icons.AllIcons.Actions.CloseHovered),
            e -> {
                JBPopup p = popupRef.get();
                if (p != null) p.cancel();
            }
        );
        // Pad the button so its hit target is larger than the 16px icon.
        JPanel dismissWrap = new JPanel(new BorderLayout());
        dismissWrap.setOpaque(false);
        dismissWrap.setBorder(JBUI.Borders.empty(2, 4, 2, 2));
        dismissWrap.add(dismissBtn, BorderLayout.CENTER);
        headerRow.add(dismissWrap, BorderLayout.EAST);
        // Version label on the LEFT side of the header (replaces the
        // bottom-row placement; bottom row is now flush against the input).
        JLabel headerVersion = new JLabel(pluginVersionLabel());
        headerVersion.setFont(headerVersion.getFont().deriveFont(java.awt.Font.PLAIN, 10f));
        headerVersion.setForeground(new JBColor(new java.awt.Color(0xa0, 0xa0, 0xa0), new java.awt.Color(0x6a, 0x6e, 0x75)));
        headerVersion.setBorder(JBUI.Borders.empty(0, 6, 0, 0));
        headerRow.add(headerVersion, BorderLayout.WEST);
        headerRow.addMouseListener(dragger);
        headerRow.addMouseMotionListener(dragger);
        content.add(headerRow, BorderLayout.NORTH);

        // The reused core: rendered synthesis + thinking/error cards + the
        // input/Ask row. This popup only owns the header (drag + close +
        // version label) and the JBPopup chrome around it — see
        // ThreadConversationView for everything else.
        ThreadConversationView view = new ThreadConversationView(project, anchor, anchorTextSupplier,
            new ThreadConversationView.Callbacks() {
                @Override public void onSessionGone() {
                    // The session is gone: an open popup would re-enable input that
                    // can only fail. Close it rather than leave a zombie.
                    JBPopup p = popupRef.get();
                    if (p != null && !p.isDisposed()) p.cancel();
                }
                @Override public void onThreadDeleted() {
                    JBPopup p = popupRef.get();
                    if (p != null && !p.isDisposed()) p.cancel();
                }
            });
        content.add(view.getComponent(), BorderLayout.CENTER);
        JTextArea input = view.getInputField();

        // Esc closes the popup, but never silently discards a half-typed
        // question: with non-empty input the first Esc warns (in the header) and
        // a second within 2.5s closes. With empty input Esc closes immediately.
        final long[] escArmedAt = {0L};
        final String versionText = headerVersion.getText();
        final java.awt.Color versionFg = headerVersion.getForeground();
        content.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(
                KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE, 0), "escClose");
        content.getActionMap().put("escClose", new AbstractAction() {
            @Override public void actionPerformed(ActionEvent e) {
                JBPopup p = popupRef.get();
                if (input.getText().trim().isEmpty()) {
                    if (p != null) p.cancel();
                    return;
                }
                long now = System.currentTimeMillis();
                if (now - escArmedAt[0] < 2500) {
                    if (p != null) p.cancel();
                    return;
                }
                escArmedAt[0] = now;
                headerVersion.setText("Esc again to discard");
                headerVersion.setForeground(new java.awt.Color(0xd9, 0x4a, 0x4a));
                javax.swing.Timer t = new javax.swing.Timer(2500, ev -> {
                    headerVersion.setText(versionText);
                    headerVersion.setForeground(versionFg);
                });
                t.setRepeats(false);
                t.start();
            }
        });

        JBPopup popup = JBPopupFactory.getInstance()
                .createComponentPopupBuilder(content, input)
                .setRequestFocus(true)
                .setMovable(true)
                .setResizable(true)
                .setCancelOnClickOutside(false)
                .setCancelOnOtherWindowOpen(false)
                .setCancelOnWindowDeactivation(false)
                .setCancelKeyEnabled(false)  // Esc handled by our guarded binding (see above)
                // No setTitle → no native title bar. The custom MouseAdapter
                // dragger above makes the popup draggable from any background
                // surface in the content/header panels.
                .createPopup();
        // setResizable(true) lets the user drag this bigger, but nothing was
        // resetting it back on the next open — IntelliJ's popup machinery can
        // carry a manual resize forward in-memory for the rest of the IDE
        // session, so a single accidental drag made every later popup open
        // oversized until a full restart. Force the declared size on every
        // open regardless of any such carried-over state.
        popup.setSize(new Dimension(480, 200));
        popupRef.set(popup);
        Disposer.register(popup, view);
        OPEN_POPUPS.put(popupKey, popup);
        popup.addListener(new com.intellij.openapi.ui.popup.JBPopupListener() {
            @Override public void onClosed(@NotNull com.intellij.openapi.ui.popup.LightweightWindowEvent e) {
                OPEN_POPUPS.remove(popupKey, popup);
            }
        });
        shower.accept(popup);
    }

    /** Package-visible: also used by {@link AnnotationsPanel} to build the
     *  anchor-text echo for its inline detail view. */
    static String lineTextAt(Document doc, int line0) {
        if (line0 < 0 || line0 >= doc.getLineCount()) return "";
        int s = doc.getLineStartOffset(line0);
        int en = doc.getLineEndOffset(line0);
        return doc.getText(new TextRange(s, en));
    }

    /**
     * Return "v<version>" derived from the plugin descriptor in plugin.xml.
     * The version uses the running commit count, so v0.1.42 is one commit
     * ahead of v0.1.41 — easy to reason about.
     */
    private static String pluginVersionLabel() {
        try {
            var pluginId = com.intellij.openapi.extensions.PluginId.getId("com.petros.claude-ide-review");
            var descriptor = com.intellij.ide.plugins.PluginManagerCore.getPlugin(pluginId);
            String version = descriptor != null ? descriptor.getVersion() : null;
            return version != null ? "v" + version : "v?";
        } catch (Throwable t) {
            return "v?";
        }
    }

    private SynthesisPopup() {}
}
