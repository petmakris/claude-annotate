package com.petros.ireview;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.util.Disposer;
import com.intellij.ui.JBColor;
import com.intellij.ui.jcef.JBCefApp;
import com.intellij.util.ui.JBUI;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import javax.swing.AbstractAction;
import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JEditorPane;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.KeyStroke;
import javax.swing.SwingUtilities;
import java.awt.BorderLayout;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.event.ActionEvent;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.util.function.Supplier;

/**
 * The reusable core of a single thread's conversation: rendered synthesis
 * (or "no annotation yet"), a "Claude is answering…" card, an error/retry
 * card, and the question input + Ask button. Shared by {@link SynthesisPopup}
 * (floating, anchored to a diff line) and the "Review Annotations" tool
 * window's detail view (docked/floating/window, embedded inline) — the two
 * only differ in the header/chrome around this component, not in how a
 * thread is rendered or answered.
 */
final class ThreadConversationView implements Disposable {

    /** How long the "Claude is answering…" card may spin before flipping to a
     *  "still waiting" state — mirrors ReviewSessionClient's pending timeout. */
    private static final int STILL_WAITING_AFTER_MS = 120_000;

    /** Visible rows in the question box. Enter still inserts a newline in a
     *  JTextArea — only Cmd/Ctrl+Enter submits. */
    private static final int INPUT_ROWS = 3;

    /** Told when the surrounding chrome should react to something happening
     *  to this thread from outside (session gone, or this exact thread
     *  deleted) — a popup cancels itself; the tool window's detail view
     *  navigates back to the list. Either callback may be a no-op. */
    interface Callbacks {
        void onSessionGone();
        void onThreadDeleted();
    }

    private final ReviewSessionClient client;
    private final String anchor;
    private final ReviewSessionClient.Listener listener;
    private final SynthesisBrowser browser;
    private final JPanel component;
    private final JTextArea input;

    private final java.util.concurrent.atomic.AtomicReference<Boolean> thinking =
        new java.util.concurrent.atomic.AtomicReference<>(false);
    private final java.util.concurrent.atomic.AtomicReference<String> lastQuestion =
        new java.util.concurrent.atomic.AtomicReference<>();
    private javax.swing.Timer elapsedTimer;
    private javax.swing.Timer stillWaitingTimer;
    private long startedAt;
    private Runnable zoomListenerRunnable;

    ThreadConversationView(@NotNull Project project,
                           @NotNull String anchor,
                           @NotNull Supplier<String> anchorTextSupplier,
                           @NotNull Callbacks callbacks) {
        this.client = ReviewSessionService.get(project).client();
        this.anchor = anchor;

        JEditorPane synthesisPane = new JEditorPane("text/html", "");
        synthesisPane.setEditable(false);
        synthesisPane.setOpaque(false);
        synthesisPane.setBorder(JBUI.Borders.empty(2, 4));
        synthesisPane.addHyperlinkListener(e -> {
            if (e.getEventType() != javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) return;
            SynthesisLinkRouter.route(project, e.getDescription());
        });
        JScrollPane synthesisScroll = new JScrollPane(synthesisPane);
        synthesisScroll.setBorder(BorderFactory.createLineBorder(JBColor.border(), 1, true));
        synthesisScroll.setPreferredSize(new Dimension(520, 130));

        JPanel thinkingCard = new JPanel(new java.awt.GridBagLayout());
        thinkingCard.setBorder(BorderFactory.createLineBorder(JBColor.border(), 1, true));
        JPanel thinkingInner = new JPanel();
        thinkingInner.setLayout(new javax.swing.BoxLayout(thinkingInner, javax.swing.BoxLayout.Y_AXIS));
        thinkingInner.setOpaque(false);
        JLabel thinkingQuestion = new JLabel();
        thinkingQuestion.setForeground(JBColor.GRAY);
        thinkingQuestion.setFont(thinkingQuestion.getFont().deriveFont(Font.ITALIC, 11.5f));
        thinkingQuestion.setAlignmentX(Component.CENTER_ALIGNMENT);
        JPanel spinnerRow = new JPanel(new java.awt.FlowLayout(java.awt.FlowLayout.CENTER, 8, 0));
        spinnerRow.setOpaque(false);
        spinnerRow.setAlignmentX(Component.CENTER_ALIGNMENT);
        com.intellij.util.ui.AsyncProcessIcon spinner = new com.intellij.util.ui.AsyncProcessIcon("answering");
        spinner.resume();
        JLabel thinkingText = new JLabel("Claude is answering…");
        thinkingText.setForeground(JBColor.GRAY);
        spinnerRow.add(spinner);
        spinnerRow.add(thinkingText);
        JButton waitDismissBtn = makeAccentButton("Dismiss");
        waitDismissBtn.setAlignmentX(Component.CENTER_ALIGNMENT);
        waitDismissBtn.setVisible(false);
        thinkingInner.add(thinkingQuestion);
        thinkingInner.add(javax.swing.Box.createVerticalStrut(6));
        thinkingInner.add(spinnerRow);
        thinkingInner.add(javax.swing.Box.createVerticalStrut(10));
        thinkingInner.add(waitDismissBtn);
        thinkingCard.add(thinkingInner);

        JPanel errorCard = new JPanel(new java.awt.GridBagLayout());
        errorCard.setBorder(BorderFactory.createLineBorder(JBColor.border(), 1, true));
        JPanel errorInner = new JPanel();
        errorInner.setLayout(new javax.swing.BoxLayout(errorInner, javax.swing.BoxLayout.Y_AXIS));
        errorInner.setOpaque(false);
        JLabel errorMsg = new JLabel("Couldn't reach Claude — your question was kept.");
        errorMsg.setForeground(new JBColor(new java.awt.Color(0xc0, 0x32, 0x21), new java.awt.Color(0xf8, 0x73, 0x71)));
        errorMsg.setAlignmentX(Component.CENTER_ALIGNMENT);
        JButton retryBtn = makeAccentButton("Retry");
        retryBtn.setAlignmentX(Component.CENTER_ALIGNMENT);
        errorInner.add(errorMsg);
        errorInner.add(javax.swing.Box.createVerticalStrut(10));
        errorInner.add(retryBtn);
        errorCard.add(errorInner);

        this.browser = tryCreateBrowser(project);
        JComponent synthesisCard = browser != null ? (JComponent) browser.getComponent() : synthesisScroll;
        java.awt.CardLayout cards = new java.awt.CardLayout();
        JPanel centerCards = new JPanel(cards);
        centerCards.add(synthesisCard, "synthesis");
        centerCards.add(thinkingCard, "thinking");
        centerCards.add(errorCard, "error");
        centerCards.setPreferredSize(new Dimension(520, 130));

        input = new JTextArea(INPUT_ROWS, 50);
        input.setLineWrap(true);
        input.setWrapStyleWord(true);
        // Stock JTextArea falls back to a bare Monospaced default on most
        // look-and-feels — visibly detached from the Inter-derived UI font
        // everywhere else in this panel. Match it explicitly.
        input.setFont(JBUI.Fonts.label(13f + PanelZoom.delta() * 0.5f));
        JScrollPane inputScroll = new JScrollPane(input);
        inputScroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED);
        inputScroll.setBorder(BorderFactory.createLineBorder(JBColor.border(), 1, true));

        Runnable renderCurrent = () -> {
            if (thinking.get()) {
                cards.show(centerCards, "thinking");
                return;
            }
            cards.show(centerCards, "synthesis");
            var cached = client.threadFor(anchor);
            if (browser != null) {
                browser.render(cached.isEmpty()
                    ? "*No annotation yet. Ask a question to start.*"
                    : cached.get().synthesis());
                return;
            }
            if (cached.isEmpty()) {
                synthesisPane.setText(wrapHtml("<i style='color:#7a7e85'>No annotation yet. Ask a question to start.</i>"));
            } else {
                synthesisPane.setText(wrapHtml(MarkdownLinkRenderer.toHtml(cached.get().synthesis())));
            }
            synthesisPane.setCaretPosition(0);
        };
        renderCurrent.run();

        Runnable zoomListener = () -> {
            input.setFont(JBUI.Fonts.label(13f + PanelZoom.delta() * 0.5f));
            renderCurrent.run();
        };
        PanelZoom.addListener(zoomListener);
        this.zoomListenerRunnable = zoomListener;

        Runnable stopElapsed = () -> {
            if (elapsedTimer != null) { elapsedTimer.stop(); elapsedTimer = null; }
            if (stillWaitingTimer != null) { stillWaitingTimer.stop(); stillWaitingTimer = null; }
            waitDismissBtn.setVisible(false);
        };
        Runnable startElapsed = () -> {
            stopElapsed.run();
            startedAt = System.currentTimeMillis();
            thinkingText.setText("Claude is answering…");
            elapsedTimer = new javax.swing.Timer(1000, e -> {
                long secs = (System.currentTimeMillis() - startedAt) / 1000;
                thinkingText.setText("Claude is answering… " + secs + "s");
            });
            elapsedTimer.start();
            stillWaitingTimer = new javax.swing.Timer(STILL_WAITING_AFTER_MS, e -> {
                if (!thinking.get()) return;
                if (elapsedTimer != null) { elapsedTimer.stop(); elapsedTimer = null; }
                thinkingText.setText("Still waiting — Claude may be busy");
                waitDismissBtn.setVisible(true);
                thinkingCard.revalidate();
                thinkingCard.repaint();
            });
            stillWaitingTimer.setRepeats(false);
            stillWaitingTimer.start();
        };
        waitDismissBtn.addActionListener(e -> {
            thinking.set(false);
            stopElapsed.run();
            renderCurrent.run();
        });
        this.stopElapsedRunnable = stopElapsed;

        JButton askBtn = makeAccentButton("Ask");
        askBtn.setMnemonic(KeyEvent.VK_A);
        java.util.function.Consumer<String> submitText = raw -> {
            ReviewSessionClient.State st = client.state();
            if (st == ReviewSessionClient.State.PAUSED || st == ReviewSessionClient.State.ENDED
                    || st == ReviewSessionClient.State.DORMANT
                    || st == ReviewSessionClient.State.OFFLINE) return;
            if (raw == null) return;
            String q = raw.trim();
            if (q.isEmpty()) return;
            lastQuestion.set(q);
            input.setText("");
            thinkingQuestion.setText("“" + truncate(q, 72) + "”");
            thinking.set(true);
            renderCurrent.run();
            startElapsed.run();
            String anchorText = anchorTextSupplier.get();
            client.postComment(anchor, q, anchorText).whenComplete((v, t) -> SwingUtilities.invokeLater(() -> {
                if (t != null) {
                    thinking.set(false);
                    stopElapsed.run();
                    input.setText(q);
                    cards.show(centerCards, "error");
                }
            }));
        };
        Runnable submit = () -> submitText.accept(input.getText());
        askBtn.addActionListener(e -> submit.run());
        retryBtn.addActionListener(e -> submitText.accept(lastQuestion.get()));

        java.util.function.Consumer<ReviewSessionClient.State> applyLiveness = st -> {
            boolean frozen = st == ReviewSessionClient.State.PAUSED
                    || st == ReviewSessionClient.State.ENDED
                    || st == ReviewSessionClient.State.DORMANT
                    || st == ReviewSessionClient.State.OFFLINE;
            input.setEnabled(!frozen);
            askBtn.setEnabled(!frozen);
            if (frozen) {
                if (thinking.get()) { thinking.set(false); stopElapsed.run(); renderCurrent.run(); }
                input.setToolTipText(switch (st) {
                    case ENDED -> "Session ended — read-only";
                    case PAUSED -> "Paused — reconnecting…";
                    case OFFLINE -> "Review server offline";
                    default -> "No active review session";
                });
            } else {
                input.setToolTipText(null);
            }
        };
        applyLiveness.accept(client.state());

        input.getInputMap(JComponent.WHEN_FOCUSED).put(
                KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.META_DOWN_MASK), "submit");
        input.getInputMap(JComponent.WHEN_FOCUSED).put(
                KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.CTRL_DOWN_MASK), "submit");
        input.getActionMap().put("submit", new AbstractAction() {
            @Override public void actionPerformed(ActionEvent e) { submit.run(); }
        });

        input.setRows(INPUT_ROWS);
        input.setBorder(JBUI.Borders.empty(2, 6));
        askBtn.setMargin(JBUI.emptyInsets());
        askBtn.setBorder(JBUI.Borders.empty(0, 10));

        JPanel south = new JPanel(new BorderLayout(4, 0));
        south.setBorder(JBUI.Borders.emptyTop(4));
        south.add(inputScroll, BorderLayout.CENTER);
        south.add(askBtn, BorderLayout.EAST);

        component = new JPanel(new BorderLayout());
        component.add(centerCards, BorderLayout.CENTER);
        component.add(south, BorderLayout.SOUTH);

        listener = new ReviewSessionClient.Listener() {
            @Override public void onStateChanged(ReviewSessionClient.State st) {
                SwingUtilities.invokeLater(() -> applyLiveness.accept(st));
            }
            @Override public void onDetached() {
                SwingUtilities.invokeLater(callbacks::onSessionGone);
            }
            @Override public void onThreadChanged(String changedAnchor, String synthesis, int version) {
                if (!changedAnchor.equals(anchor)) return;
                SwingUtilities.invokeLater(() -> {
                    thinking.set(false);
                    stopElapsed.run();
                    renderCurrent.run();
                });
            }
            @Override public void onThreadDeleted(String deletedAnchor) {
                if (!deletedAnchor.equals(anchor)) return;
                SwingUtilities.invokeLater(callbacks::onThreadDeleted);
            }
        };
        client.addListener(listener);
    }

    /** Set once in the constructor so {@link #dispose()} can stop the timers
     *  without re-declaring the closure. */
    private Runnable stopElapsedRunnable = () -> {};

    JComponent getComponent() {
        return component;
    }

    JTextArea getInputField() {
        return input;
    }

    @Override
    public void dispose() {
        client.removeListener(listener);
        if (zoomListenerRunnable != null) PanelZoom.removeListener(zoomListenerRunnable);
        stopElapsedRunnable.run();
        if (browser != null) Disposer.dispose(browser);
    }

    private static SynthesisBrowser tryCreateBrowser(@NotNull Project project) {
        try {
            return JBCefApp.isSupported() ? new SynthesisBrowser(project) : null;
        } catch (LinkageError | RuntimeException e) {
            return null;
        }
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max - 1) + "…";
    }

    private static String wrapHtml(String body) {
        var scheme = com.intellij.openapi.editor.colors.EditorColorsManager
                .getInstance().getGlobalScheme();
        String editorFont = scheme.getEditorFontName();
        int editorFontSize = Math.max(9, Math.min(40, scheme.getEditorFontSize() - 1 + PanelZoom.delta()));
        String fontFamily = "'" + editorFont.replace("'", "\\'") + "', monospace";
        return "<html><head><style>"
             + "body { font-family: " + fontFamily
             +        "; color: #d8d8d8; font-size: " + editorFontSize + "px;"
             +        " line-height: 1.45; margin: 0; padding: 4px 6px; }"
             + "b { color: #e4e4e4; }"
             + "a.ref-code { color: #ce9178; text-decoration: none; }"
             + "a.ref-ticket { color: #b5b6e3; text-decoration: none; }"
             + "a.ref-sym { color: #ce9178; text-decoration: none; }"
             + "a.ref-sym:hover { text-decoration: underline dashed; }"
             + "pre.code-block { background: #1e1f22; color: #d8d8d8; padding: 6px 10px;"
             +                 " margin: 4px 0; border: 1px solid #393b40;"
             +                 " font-size: " + (editorFontSize - 1) + "px; }"
             + "</style></head><body>"
             + body + "</body></html>";
    }

    /**
     * Build a button that visibly looks like a button: explicit accent
     * background, white text, hover/pressed states. Bypasses macOS Aqua
     * L&F which silently ignores setBackground on stock JButtons.
     */
    private static JButton makeAccentButton(String text) {
        final java.awt.Color base = new java.awt.Color(0x3b, 0x72, 0xe8);
        final java.awt.Color hover = new java.awt.Color(0x4f, 0x83, 0xed);
        final java.awt.Color pressed = new java.awt.Color(0x2c, 0x5f, 0xd0);
        JButton b = new JButton(text);
        b.setUI(new javax.swing.plaf.basic.BasicButtonUI());
        b.setOpaque(true);
        b.setContentAreaFilled(true);
        b.setBorderPainted(false);
        b.setFocusPainted(false);
        b.setBackground(base);
        b.setForeground(java.awt.Color.WHITE);
        b.setFont(b.getFont().deriveFont(java.awt.Font.BOLD));
        b.setBorder(JBUI.Borders.empty(6, 18));
        b.setCursor(java.awt.Cursor.getPredefinedCursor(java.awt.Cursor.HAND_CURSOR));
        b.addMouseListener(new java.awt.event.MouseAdapter() {
            @Override public void mouseEntered(java.awt.event.MouseEvent e) { b.setBackground(hover); }
            @Override public void mouseExited(java.awt.event.MouseEvent e) { b.setBackground(base); }
            @Override public void mousePressed(java.awt.event.MouseEvent e) { b.setBackground(pressed); }
            @Override public void mouseReleased(java.awt.event.MouseEvent e) {
                b.setBackground(b.contains(e.getPoint()) ? hover : base);
            }
        });
        return b;
    }
}
