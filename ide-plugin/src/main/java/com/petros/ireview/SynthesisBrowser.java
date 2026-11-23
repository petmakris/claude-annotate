package com.petros.ireview;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors;
import com.intellij.openapi.editor.colors.EditorColorsManager;
import com.intellij.openapi.editor.colors.EditorColorsScheme;
import com.intellij.openapi.editor.colors.TextAttributesKey;
import com.intellij.openapi.editor.markup.TextAttributes;
import com.intellij.openapi.util.Disposer;
import com.intellij.openapi.project.Project;
import com.intellij.ui.jcef.JBCefBrowser;
import com.intellij.ui.jcef.JBCefBrowserBase;
import com.intellij.ui.jcef.JBCefJSQuery;
import com.intellij.util.ui.JBUI;
import org.jetbrains.annotations.NotNull;

import javax.swing.JComponent;
import javax.swing.SwingUtilities;
import java.awt.Color;
import java.awt.Font;

/**
 * Embedded Chromium (JCEF) view of the synthesis markdown. Renders via
 * {@link SynthesisHtmlRenderer} and intercepts every <a> click through a
 * {@link JBCefJSQuery} bridge, routing the href via {@link SynthesisLinkRouter}.
 *
 * Only constructed when {@code JBCefApp.isSupported()}; the popup falls back to
 * the JEditorPane renderer otherwise.
 */
public final class SynthesisBrowser implements Disposable {

    private final Project project;
    private final JBCefBrowser browser;
    private final String navScript;

    public SynthesisBrowser(@NotNull Project project) {
        this.project = project;
        // Off-screen rendering: without it, this is a heavyweight native
        // Chromium window, and Swing's CardLayout — used by SynthesisPopup to
        // flip between this card and the "thinking" spinner card — cannot
        // reliably paint a lightweight sibling over a heavyweight one. The
        // browser can stay visually on top of the spinner even after
        // cards.show() hides it. OSR paints into an ordinary Swing-managed
        // bitmap instead, so it behaves like any other component here.
        this.browser = JBCefBrowser.createBuilder().setOffScreenRendering(true).build();
        Disposer.register(this, browser);

        JBCefJSQuery linkQuery = JBCefJSQuery.create((JBCefBrowserBase) browser);
        linkQuery.addHandler(href -> {
            SwingUtilities.invokeLater(() -> SynthesisLinkRouter.route(project, href));
            return new JBCefJSQuery.Response(null);
        });

        // Intercept all link clicks; getAttribute('href') returns the raw,
        // un-resolved scheme value (e.g. ireview-sym://Foo), not a percent-
        // encoded absolute URL.
        this.navScript =
            "document.addEventListener('click',function(e){"
          + "var a=e.target.closest('a');if(!a)return;"
          + "e.preventDefault();"
          + "var href=a.getAttribute('href');"
          + linkQuery.inject("href")
          + "},true);";
    }

    public JComponent getComponent() {
        return browser.getComponent();
    }

    public void render(@NotNull String markdown) {
        browser.loadHTML(SynthesisHtmlRenderer.toDocument(markdown, currentTheme(project), navScript));
    }

    @Override
    public void dispose() {
        // browser (and the JS query created from it) are disposed via Disposer.
    }

    /**
     * Builds the popup's theme. Fonts and sizes always follow the live editor
     * (see below), but the colours are either read from the editor scheme or,
     * when {@link DiffSettings#useMaterialTheme()} is on (the default), a
     * fixed high-contrast Material-style palette that stays legible and
     * distinct regardless of which editor theme is currently active.
     */
    private static SynthesisHtmlRenderer.Theme currentTheme(@NotNull Project project) {
        EditorColorsScheme scheme = EditorColorsManager.getInstance().getGlobalScheme();

        // Sizing follows the EDITOR font size, not the UI label font. The popup
        // sits beside the diff and is read like the code it discusses, so the
        // editor size is the size the user has already said they read at; the
        // label font (13 by default) leaves the popup visibly smaller than the
        // editor next to it, which is the one thing users report about it.
        // A point below the editor because a proportional face at a given px
        // reads larger than a monospaced one.
        Font uiFont = JBUI.Fonts.label();
        int editorSize = scheme.getEditorFontSize();
        int baseProseSize = clampInt(editorSize - 1, Math.max(13, uiFont.getSize()), 26);
        int proseSize = clampInt(baseProseSize + PanelZoom.delta(), 9, 40);
        int monoSize = clampInt(proseSize - 1, 8, 38);
        String proseFont = quote(uiFont.getFamily());
        String monoFont = quote(scheme.getEditorFontName());

        if (DiffSettings.get(project).useMaterialTheme()) {
            return materialTheme(proseFont, proseSize, monoFont, monoSize);
        }

        Color bg = scheme.getDefaultBackground();
        Color fg = scheme.getDefaultForeground();
        return new SynthesisHtmlRenderer.Theme(
            hex(bg),
            hex(fg),
            hex(contrast(fg, bg, 26)),
            hex(blend(fg, bg, 0.42f)),
            proseFont, proseSize,
            monoFont, monoSize,
            "#4f83ed",
            hex(shift(bg, 12)),
            hex(shift(bg, 36)),
            tokens(scheme, fg));
    }

    /**
     * A fixed dark, high-contrast palette in the spirit of Material Theme /
     * One Dark Pro: an elevated near-black surface, near-white prose text, and
     * saturated (not desaturated-to-match-editor) syntax colours. Independent
     * of {@code EditorColorsScheme} on purpose — the popup is meant to read as
     * its own surface next to the code, not blend into it.
     */
    private static SynthesisHtmlRenderer.Theme materialTheme(
            String proseFont, int proseSize, String monoFont, int monoSize) {
        return new SynthesisHtmlRenderer.Theme(
            "#1a1d23",              // background — elevated dark surface
            "#eceff4",              // foreground — near-white prose text
            "#ffffff",              // strongForeground — headings/bold at full white
            "#9aa4b2",              // mutedForeground — list markers, rules
            proseFont, proseSize,
            monoFont, monoSize,
            "#6ea8fe",              // accent — bright, high-contrast link blue
            "#252a33",              // codeBackground — one step up from the surface
            "#3a4150",              // border
            new SynthesisHtmlRenderer.Tokens(
                "#c792ea",          // keyword — violet
                "#a2e57b",          // string — green
                "#f78c6c",          // number — orange
                "#7b8496",          // comment — blue-grey, italic
                "#ffcb6b",          // metadata — amber
                "#82aaff",          // function — blue
                "#ffcb6b",          // type — amber
                "#f07178",          // field — coral
                "#eceff4",          // variable — prose foreground
                "#89ddff"));        // constant — cyan
    }

    /**
     * One {@code DefaultLanguageHighlighterColors} key per token class. The
     * fallbacks are IntelliJ's own Dark scheme values, used only when a scheme
     * leaves a key without an explicit foreground.
     */
    private static SynthesisHtmlRenderer.Tokens tokens(EditorColorsScheme scheme, Color fg) {
        return new SynthesisHtmlRenderer.Tokens(
            token(scheme, DefaultLanguageHighlighterColors.KEYWORD,        "#cf8e6d"),
            token(scheme, DefaultLanguageHighlighterColors.STRING,         "#6aab73"),
            token(scheme, DefaultLanguageHighlighterColors.NUMBER,         "#2aacb8"),
            token(scheme, DefaultLanguageHighlighterColors.LINE_COMMENT,   "#7a7e85"),
            token(scheme, DefaultLanguageHighlighterColors.METADATA,       "#b3ae60"),
            token(scheme, DefaultLanguageHighlighterColors.FUNCTION_CALL,  "#56a8f5"),
            token(scheme, DefaultLanguageHighlighterColors.CLASS_NAME,     hex(fg)),
            token(scheme, DefaultLanguageHighlighterColors.INSTANCE_FIELD, "#c77dbb"),
            token(scheme, DefaultLanguageHighlighterColors.LOCAL_VARIABLE, hex(fg)),
            token(scheme, DefaultLanguageHighlighterColors.STATIC_FIELD,   "#c77dbb"));
    }

    private static String token(EditorColorsScheme scheme, TextAttributesKey key, String fallback) {
        TextAttributes attrs = scheme.getAttributes(key);
        Color c = attrs == null ? null : attrs.getForegroundColor();
        return c == null ? fallback : hex(c);
    }

    /** Single-quote for CSS, escaping any apostrophe in the family name. */
    private static String quote(String fontFamily) {
        return "'" + fontFamily.replace("'", "\\'") + "'";
    }

    /** Nudge a color lighter (dark themes) or darker (light themes) by delta. */
    private static Color shift(Color c, int delta) {
        int d = isDark(c) ? delta : -delta;
        return new Color(clampInt(c.getRed() + d, 0, 255),
                         clampInt(c.getGreen() + d, 0, 255),
                         clampInt(c.getBlue() + d, 0, 255));
    }

    /**
     * Push fg further from bg — brighter on a dark theme, darker on a light one.
     * Direction comes from the background, not from fg: {@link #shift} reads the
     * colour it is given, which is the wrong signal for a foreground.
     */
    private static Color contrast(Color fg, Color bg, int delta) {
        int d = isDark(bg) ? delta : -delta;
        return new Color(clampInt(fg.getRed() + d, 0, 255),
                         clampInt(fg.getGreen() + d, 0, 255),
                         clampInt(fg.getBlue() + d, 0, 255));
    }

    /** Mix fg toward bg; ratio 0 = fg, 1 = bg. */
    private static Color blend(Color fg, Color bg, float ratio) {
        return new Color(mix(fg.getRed(), bg.getRed(), ratio),
                         mix(fg.getGreen(), bg.getGreen(), ratio),
                         mix(fg.getBlue(), bg.getBlue(), ratio));
    }

    private static int mix(int a, int b, float ratio) {
        return clampInt(Math.round(a + (b - a) * ratio), 0, 255);
    }

    private static boolean isDark(Color c) {
        return (c.getRed() + c.getGreen() + c.getBlue()) / 3 < 128;
    }

    private static int clampInt(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    private static String hex(Color c) {
        return String.format("#%02x%02x%02x", c.getRed(), c.getGreen(), c.getBlue());
    }
}
