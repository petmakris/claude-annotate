package com.petros.ireview;

import org.commonmark.Extension;
import org.commonmark.ext.gfm.tables.TablesExtension;
import org.commonmark.node.Code;
import org.commonmark.node.Link;
import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.NodeRenderer;
import org.commonmark.renderer.html.AttributeProvider;
import org.commonmark.renderer.html.HtmlNodeRendererContext;
import org.commonmark.renderer.html.HtmlRenderer;
import org.commonmark.renderer.html.HtmlWriter;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Converts synthesis markdown into HTML for the JCEF popup.
 *
 * Three custom rules shape the popup's link and image behavior:
 *  - a markdown link whose destination is NOT http(s) is rewritten to the
 *    ireview-nav:// scheme (file:line navigation) and classed {@code nav};
 *    http(s) links are classed {@code url};
 *  - inline `code` is wrapped in an ireview-sym:// anchor classed {@code sym}
 *    (symbol lookup) — styled as code rather than as a link, so the reader can
 *    tell an actual navigation target from an identifier being named;
 *  - images are reduced to their alt text, so nothing loads remotely.
 *
 * Fenced blocks keep commonmark's {@code language-*} class; the bundled
 * highlight.js (see {@link SynthesisAssets}) colours them in the browser using
 * CSS variables the caller derives from the IDE's editor colour scheme. Nothing
 * here knows about IntelliJ, so the class stays fully unit-testable.
 */
public final class SynthesisHtmlRenderer {

    /**
     * Colours and fonts sourced from the IDE by the caller.
     *
     * @param strongForeground headings and bold — pushed away from the
     *        background so structure reads without a second font
     * @param mutedForeground  list markers and rules
     * @param proseFont        the IDE UI font: prose is prose, not a terminal
     * @param monoFont         the editor font, used only inside code
     */
    public record Theme(String background, String foreground, String strongForeground,
                        String mutedForeground,
                        String proseFont, int proseSize,
                        String monoFont, int monoSize,
                        String accent, String codeBackground, String border,
                        Tokens tokens) {}

    /**
     * Syntax token colours, each read from one
     * {@code DefaultLanguageHighlighterColors} key by the caller, so the popup
     * tracks whatever editor scheme is active.
     */
    public record Tokens(String keyword, String string, String number, String comment,
                         String metadata, String function, String type, String field,
                         String variable, String constant) {}

    private static final List<Extension> EXTENSIONS = List.of(TablesExtension.create());

    private static final Parser PARSER = Parser.builder()
            .extensions(EXTENSIONS)
            .build();

    private static final HtmlRenderer RENDERER = HtmlRenderer.builder()
            .extensions(EXTENSIONS)
            .escapeHtml(true)
            .attributeProviderFactory(ctx -> new NavLinkAttributeProvider())
            .nodeRendererFactory(SymbolCodeRenderer::new)
            .nodeRendererFactory(AltTextImageRenderer::new)
            .build();

    /**
     * Auto-detection candidates. Restricting the set stops highlight.js from
     * confidently mislabelling a three-line unfenced snippet as Perl.
     */
    private static final String DETECT_LANGUAGES =
        "'java','kotlin','python','javascript','typescript','json','yaml',"
      + "'xml','bash','sql','ini','diff','markdown','go','ruby','css'";

    public static String toBodyHtml(String markdown) {
        if (markdown == null || markdown.isEmpty()) return "";
        Node doc = PARSER.parse(markdown);
        return RENDERER.render(doc);
    }

    public static String toDocument(String markdown, Theme theme, String navScript) {
        String body = toBodyHtml(markdown);
        StringBuilder sb = new StringBuilder();
        sb.append("<!doctype html><html><head><meta charset=\"utf-8\"><style>");
        sb.append(css(theme));
        sb.append("</style></head><body>");
        sb.append(body);

        String highlighter = SynthesisAssets.highlighterScript();
        if (!highlighter.isEmpty()) {
            sb.append("<script>").append(highlighter).append("</script>");
            sb.append("<script>").append(highlightScript()).append("</script>");
        }
        if (navScript != null && !navScript.isEmpty()) {
            sb.append("<script>").append(navScript).append("</script>");
        }
        sb.append("</body></html>");
        return sb.toString();
    }

    /**
     * Runs the highlighter over every fenced block. Wrapped in try/catch per
     * block: one grammar throwing must not leave the rest of the answer
     * unstyled, and must not kill the nav script that runs after it.
     */
    private static String highlightScript() {
        return "try{hljs.configure({ignoreUnescapedHTML:true,languages:[" + DETECT_LANGUAGES + "]});"
             + "document.querySelectorAll('pre code').forEach(function(b){"
             + "try{hljs.highlightElement(b);}catch(e){}});}catch(e){}";
    }

    private static String css(Theme t) {
        Tokens k = t.tokens();
        return
          // Token colours as variables: one place to read them, and the rules
          // below stay legible.
            ":root{"
          +   "--tk-keyword:" + k.keyword() + ";--tk-string:" + k.string() + ";"
          +   "--tk-number:" + k.number() + ";--tk-comment:" + k.comment() + ";"
          +   "--tk-metadata:" + k.metadata() + ";--tk-function:" + k.function() + ";"
          +   "--tk-type:" + k.type() + ";--tk-field:" + k.field() + ";"
          +   "--tk-variable:" + k.variable() + ";--tk-constant:" + k.constant() + ";}"

          + "html,body{margin:0;padding:0;}"
          + "body{background:" + t.background() + ";color:" + t.foreground() + ";"
          +   "font-family:" + t.proseFont() + ",-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;"
          +   "font-size:" + t.proseSize() + "px;line-height:1.62;"
          +   "padding:14px 18px 20px;max-width:82ch;"
          +   "-webkit-font-smoothing:antialiased;overflow-wrap:break-word;}"
          + "body>*:first-child{margin-top:0;}"
          + "p{margin:0 0 12px;}"
          + "strong,b{color:" + t.strongForeground() + ";font-weight:620;}"

          // Headings carry the structure, so they get space and a hairline
          // rather than a bigger slab of the same colour.
          + "h1,h2,h3{color:" + t.strongForeground() + ";font-weight:650;line-height:1.35;}"
          + "h1{font-size:1.18em;margin:22px 0 10px;padding-bottom:6px;"
          +   "border-bottom:1px solid " + t.border() + ";}"
          + "h2{font-size:1.08em;margin:22px 0 10px;padding-bottom:5px;"
          +   "border-bottom:1px solid " + t.border() + ";}"
          + "h3{font-size:1em;margin:18px 0 8px;}"
          + "ul,ol{margin:0 0 12px;padding-left:20px;}"
          + "li{margin:0 0 6px;}"
          + "li::marker{color:" + t.mutedForeground() + ";}"

          // Only things that navigate look like links.
          + "a.nav,a.url{color:" + t.accent() + ";text-decoration:none;"
          +   "border-bottom:1px solid " + t.border() + ";}"
          + "a.nav:hover,a.url:hover{border-bottom-color:" + t.accent() + ";}"
          // Symbol lookup keeps its click, but reads as code: the chip below is
          // the whole affordance, and only its border reacts to hover.
          + "a.sym{color:inherit;text-decoration:none;}"
          + "a.sym:hover code{border-color:" + t.accent() + ";}"

          // box-decoration-break:clone so a chip that wraps (long identifiers do,
          // and a hyphen is a break opportunity) paints a complete background and
          // border on BOTH fragments instead of losing the right-hand edge.
          + "code{font-family:" + t.monoFont() + ",ui-monospace,SFMono-Regular,Menlo,monospace;"
          +   "font-size:.885em;background:" + t.codeBackground() + ";"
          +   "border:1px solid " + t.border() + ";border-radius:4px;padding:.1em .38em;"
          +   "-webkit-box-decoration-break:clone;box-decoration-break:clone;}"

          // Chromium's UA stylesheet sets pre{font-family:monospace} directly on
          // the element, and a direct declaration beats an inherited one — so
          // the font has to be restated here or the block ignores monoFont.
          + "pre{background:" + t.codeBackground() + ";border:1px solid " + t.border() + ";"
          +   "border-radius:7px;padding:12px 14px;margin:0 0 14px;overflow-x:auto;}"
          + "pre code{font-family:" + t.monoFont() + ",ui-monospace,SFMono-Regular,Menlo,monospace;"
          +   "font-size:" + t.monoSize() + "px;line-height:1.58;display:block;"
          +   "background:none;border:0;padding:0;color:" + t.foreground() + ";"
          // Wrap rather than clip: a long assertion string scrolled out of view
          // is the one thing the reader came to check. break-word, not anywhere:
          // anywhere lets a line split inside `mockMvc.perform(`, while break-word
          // takes an existing space first and only splits a token that cannot fit.
          +   "white-space:pre-wrap;overflow-wrap:break-word;}"

          // highlightElement stamps .hljs on the block; neutralise its own
          // background so the card keeps the one set above.
          + ".hljs{background:none;color:inherit;}"
          + ".hljs-keyword,.hljs-literal,.hljs-selector-tag,.hljs-doctag{color:var(--tk-keyword);}"
          + ".hljs-string,.hljs-regexp,.hljs-char,.hljs-quote{color:var(--tk-string);}"
          + ".hljs-number{color:var(--tk-number);}"
          + ".hljs-comment{color:var(--tk-comment);font-style:italic;}"
          + ".hljs-meta,.hljs-meta .hljs-string{color:var(--tk-metadata);}"
          + ".hljs-title,.hljs-title.function_,.hljs-built_in,.hljs-section{color:var(--tk-function);}"
          + ".hljs-title.class_,.hljs-type,.hljs-class .hljs-title{color:var(--tk-type);}"
          + ".hljs-attr,.hljs-attribute,.hljs-property,.hljs-name,.hljs-tag{color:var(--tk-field);}"
          + ".hljs-variable,.hljs-params,.hljs-template-variable{color:var(--tk-variable);}"
          + ".hljs-symbol,.hljs-bullet,.hljs-link,.hljs-addition{color:var(--tk-constant);}"
          + ".hljs-deletion{color:var(--tk-comment);}"

          + "table{border-collapse:collapse;margin:0 0 14px;font-size:.95em;}"
          + "th,td{border:1px solid " + t.border() + ";padding:6px 10px;text-align:left;}"
          + "th{background:" + t.codeBackground() + ";color:" + t.strongForeground() + ";font-weight:620;}"
          + "blockquote{margin:0 0 14px;padding:2px 0 2px 12px;"
          +   "border-left:2px solid " + t.border() + ";color:" + t.mutedForeground() + ";}"
          + "hr{border:0;border-top:1px solid " + t.border() + ";margin:20px 0;}";
    }

    /** Rewrites non-http destinations to ireview-nav:// and classes both kinds. */
    private static final class NavLinkAttributeProvider implements AttributeProvider {
        @Override
        public void setAttributes(Node node, String tagName, Map<String, String> attributes) {
            if (!(node instanceof Link)) return;
            String href = attributes.get("href");
            if (href == null) return;
            if (href.startsWith("http://") || href.startsWith("https://")) {
                attributes.put("class", "url");
                return;
            }
            attributes.put("href", "ireview-nav://" + href);
            attributes.put("class", "nav");
        }
    }

    /** Renders inline code as a clickable symbol-lookup link. */
    private static final class SymbolCodeRenderer implements NodeRenderer {
        private final HtmlWriter html;

        SymbolCodeRenderer(HtmlNodeRendererContext context) {
            this.html = context.getWriter();
        }

        @Override
        public Set<Class<? extends Node>> getNodeTypes() {
            return Set.of(Code.class);
        }

        @Override
        public void render(Node node) {
            String literal = ((Code) node).getLiteral();
            Map<String, String> attrs = new LinkedHashMap<>();
            attrs.put("href", "ireview-sym://" + literal);
            attrs.put("class", "sym");
            html.tag("a", attrs);
            html.tag("code");
            html.text(literal);
            html.tag("/code");
            html.tag("/a");
        }
    }

    /** Drops images entirely, keeping only their alt text — no remote <img> loads. */
    private static final class AltTextImageRenderer implements NodeRenderer {
        private final HtmlWriter html;

        AltTextImageRenderer(HtmlNodeRendererContext context) {
            this.html = context.getWriter();
        }

        @Override
        public Set<Class<? extends Node>> getNodeTypes() {
            return Set.of(org.commonmark.node.Image.class);
        }

        @Override
        public void render(Node node) {
            for (Node c = node.getFirstChild(); c != null; c = c.getNext()) {
                if (c instanceof org.commonmark.node.Text t) {
                    html.text(t.getLiteral());
                }
            }
        }
    }

    private SynthesisHtmlRenderer() {}
}
