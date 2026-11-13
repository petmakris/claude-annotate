package com.petros.ireview;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SynthesisHtmlRendererTest {

    @Test
    void gfmTableRendersAsTableElement() {
        String md = "| a | b |\n|---|---|\n| 1 | 2 |\n";
        String html = SynthesisHtmlRenderer.toBodyHtml(md);
        assertTrue(html.contains("<table"), html);
        assertTrue(html.contains("<th"), html);
        assertTrue(html.contains("<td"), html);
    }

    @Test
    void pathLinkIsRewrittenToIreviewNavScheme() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[Foo](src/Foo.java:18)");
        assertTrue(html.contains("href=\"ireview-nav://src/Foo.java:18\""), html);
    }

    @Test
    void httpLinkStaysExternal() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[t](https://example.com/x)");
        assertTrue(html.contains("href=\"https://example.com/x\""), html);
        assertFalse(html.contains("ireview-nav://"), html);
    }

    @Test
    void inlineCodeBecomesSymbolLink() {
        String html = SynthesisHtmlRenderer.toBodyHtml("call `Foo` now");
        assertTrue(html.contains("href=\"ireview-sym://Foo\""), html);
        assertTrue(html.contains("<code>Foo</code>"), html);
    }

    @Test
    void inlineCodeWithAngleBracketsIsEscaped() {
        String html = SynthesisHtmlRenderer.toBodyHtml("see `Map<K,V>`");
        assertTrue(html.contains("ireview-sym://Map&lt;K,V&gt;"), html);
        assertTrue(html.contains("<code>Map&lt;K,V&gt;</code>"), html);
    }

    @Test
    void inlineCodeWithDoubleQuoteIsEscapedInAttribute() {
        String html = SynthesisHtmlRenderer.toBodyHtml("via `f(\"x\")`");
        assertTrue(html.contains("ireview-sym://f(&quot;x&quot;)"), html);
    }

    @Test
    void fencedCodeBlockIsPreAndNotASymbolLink() {
        String html = SynthesisHtmlRenderer.toBodyHtml("```\nint x = 1;\n```\n");
        assertTrue(html.contains("<pre>"), html);
        assertFalse(html.contains("ireview-sym://"), html);
    }

    @Test
    void unorderedListRenders() {
        String html = SynthesisHtmlRenderer.toBodyHtml("- one\n- two\n");
        assertTrue(html.contains("<ul>"), html);
        assertTrue(html.contains("<li>one</li>"), html);
    }

    @Test
    void headingRenders() {
        String html = SynthesisHtmlRenderer.toBodyHtml("# Title\n");
        assertTrue(html.contains("<h1>Title</h1>"), html);
    }

    @Test
    void emptyMarkdownIsEmptyBody() {
        assertEquals("", SynthesisHtmlRenderer.toBodyHtml(""));
        assertEquals("", SynthesisHtmlRenderer.toBodyHtml(null));
    }

    @Test
    void documentWrapsBodyWithThemeAndScript() {
        String doc = SynthesisHtmlRenderer.toDocument("# Hi\n", theme(), NAV_MARKER);
        assertTrue(doc.contains("<html>"), doc);
        assertTrue(doc.contains("<h1>Hi</h1>"), doc);
        assertTrue(doc.contains("#1e1f22"), doc);
        assertTrue(doc.contains(NAV_MARKER), doc);
    }

    @Test
    void documentOmitsNavScriptWhenNull() {
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertFalse(doc.contains(NAV_MARKER), doc);
    }

    @Test
    void rawHtmlScriptIsEscaped() {
        String html = SynthesisHtmlRenderer.toBodyHtml("<script>alert(1)</script>");
        assertFalse(html.contains("<script>"), html);
        assertTrue(html.contains("&lt;script&gt;"), html);
    }

    @Test
    void rawHtmlImgIsEscaped() {
        String html = SynthesisHtmlRenderer.toBodyHtml("text <img src=x onerror=alert(1)> more");
        assertFalse(html.contains("<img"), html);
    }

    @Test
    void markdownImageDoesNotEmitImgTagAndKeepsAltText() {
        String html = SynthesisHtmlRenderer.toBodyHtml("![logo](https://evil/track.png)");
        assertFalse(html.contains("<img"), html);
        assertFalse(html.contains("track.png"), html);
        assertTrue(html.contains("logo"), html);
    }

    @Test
    void javascriptLinkIsNeutralizedToNavScheme() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[x](javascript:alert(1))");
        assertFalse(html.contains("href=\"javascript:"), html);
        assertTrue(html.contains("ireview-nav://"), html);
    }

    @Test
    void pathLinkStillRewrittenAfterEscapeHtml() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[Foo](src/Foo.java:18)");
        assertTrue(html.contains("href=\"ireview-nav://src/Foo.java:18\""), html);
    }

    @Test
    void httpLinkStillExternalAfterEscapeHtml() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[t](https://example.com/x)");
        assertTrue(html.contains("href=\"https://example.com/x\""), html);
    }

    @Test
    void inlineCodeDoubleQuoteEscapedInCodeText() {
        String html = SynthesisHtmlRenderer.toBodyHtml("via `f(\"x\")`");
        assertTrue(html.contains("<code>f(&quot;x&quot;)</code>"), html);
    }

    // ---- theme / document shell -------------------------------------------

    /** A nav script no bundled asset could plausibly contain, so "the nav script
     *  is absent" is provable against a document that also inlines highlight.js. */
    private static final String NAV_MARKER = "__ireviewNavProbe__();";

    /** A theme with distinguishable values, so a CSS assertion can prove which
     *  slot a colour landed in rather than just that some hex is present. */
    private static SynthesisHtmlRenderer.Theme theme() {
        return new SynthesisHtmlRenderer.Theme(
            "#1e1f22", "#bcbec4", "#e8eaed", "#7a7e85",
            "'Inter'", 14,
            "'Source Code Pro'", 13,
            "#548af7", "#232427", "#393b40",
            new SynthesisHtmlRenderer.Tokens(
                "#cf8e6d", "#6aab73", "#2aacb8", "#5f826b", "#b3ae60",
                "#56a8f5", "#b5b6e3", "#c77dbb", "#bcbec4", "#c77dbb"));
    }

    // ---- link affordances --------------------------------------------------

    @Test
    void pathLinkGetsNavClass() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[Foo](src/Foo.java:18)");
        assertTrue(html.contains("class=\"nav\""), html);
        assertFalse(html.contains("class=\"url\""), html);
    }

    @Test
    void httpLinkGetsUrlClass() {
        String html = SynthesisHtmlRenderer.toBodyHtml("[t](https://example.com/x)");
        assertTrue(html.contains("class=\"url\""), html);
        assertFalse(html.contains("class=\"nav\""), html);
    }

    @Test
    void inlineCodeAnchorGetsSymClassAndStillNavigates() {
        String html = SynthesisHtmlRenderer.toBodyHtml("call `Foo` now");
        assertTrue(html.contains("class=\"sym\""), html);
        assertTrue(html.contains("href=\"ireview-sym://Foo\""), html);
        assertTrue(html.contains("<code>Foo</code>"), html);
    }

    // ---- syntax highlighting ----------------------------------------------

    @Test
    void fencedCodeBlockCarriesLanguageClassForTheHighlighter() {
        String html = SynthesisHtmlRenderer.toBodyHtml("```java\nint x = 1;\n```\n");
        assertTrue(html.contains("language-java"), html);
    }

    @Test
    void documentInlinesTheBundledHighlighterAndRunsIt() {
        String doc = SynthesisHtmlRenderer.toDocument("```java\nint x = 1;\n```\n", theme(), null);
        assertTrue(doc.contains("hljs"), "highlight.js should be inlined");
        assertTrue(doc.contains("highlightElement"), "highlighter should be invoked on load");
    }

    @Test
    void documentDefinesEveryTokenColourAsACssVariable() {
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains("--tk-keyword:#cf8e6d"), doc);
        assertTrue(doc.contains("--tk-string:#6aab73"), doc);
        assertTrue(doc.contains("--tk-number:#2aacb8"), doc);
        assertTrue(doc.contains("--tk-comment:#5f826b"), doc);
        assertTrue(doc.contains("--tk-metadata:#b3ae60"), doc);
        assertTrue(doc.contains("--tk-function:#56a8f5"), doc);
        assertTrue(doc.contains("--tk-type:#b5b6e3"), doc);
        assertTrue(doc.contains("--tk-field:#c77dbb"), doc);
    }

    @Test
    void hljsTokenClassesAreBoundToTheThemeVariables() {
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains(".hljs-keyword"), doc);
        assertTrue(doc.contains("var(--tk-keyword)"), doc);
        assertTrue(doc.contains(".hljs-comment"), doc);
    }

    @Test
    void wrappedInlineCodeRepaintsItsBoxOnBothFragments() {
        // A chip that wraps at a hyphen loses its right-hand border without this.
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains("box-decoration-break:clone"), doc);
    }

    @Test
    void hljsDefaultBackgroundIsNeutralisedSoTheCardKeepsItsOwn() {
        // No hljs stylesheet is bundled, but highlightElement still stamps the
        // .hljs class; without this rule a future hljs theme could repaint the
        // block behind our own background.
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains(".hljs{background:none"), doc);
    }

    // ---- typography --------------------------------------------------------

    @Test
    void proseUsesTheUiFontAndCodeUsesTheEditorFont() {
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains("font-family:'Inter'"), doc);
        assertTrue(doc.contains("'Source Code Pro'"), doc);
        assertTrue(doc.contains("font-size:14px"), doc);
    }

    @Test
    void codeBlocksWrapInsteadOfScrollingLongLinesOutOfView() {
        String doc = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        assertTrue(doc.contains("white-space:pre-wrap"), doc);
        assertTrue(doc.contains("overflow-wrap:break-word"), doc);
        assertFalse(doc.contains("overflow-wrap:anywhere"),
                    "anywhere splits identifiers mid-token; break-word takes a space first");
    }

    @Test
    void preFontFamilyIsSetExplicitlyBecauseTheUaRuleBeatsInheritance() {
        // Chromium's UA stylesheet declares pre{font-family:monospace} directly
        // on the element, which wins over anything inherited from body. Without
        // an explicit rule the code block silently ignores the editor font.
        String css = SynthesisHtmlRenderer.toDocument("hi", theme(), null);
        int pre = css.indexOf("pre code{");
        assertTrue(pre > 0, css);
        assertTrue(css.substring(pre, pre + 200).contains("font-family"), css.substring(pre, pre + 200));
    }
}
