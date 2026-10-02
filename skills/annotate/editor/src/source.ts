import { StateField, type EditorState, type Range, type Extension } from '@codemirror/state';
import { EditorView, Decoration, lineNumbers, highlightActiveLine, highlightActiveLineGutter, type DecorationSet } from '@codemirror/view';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { HighlightStyle, syntaxHighlighting, foldGutter, ensureSyntaxTree } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';
import { calloutTone } from './stubs';
import { TICKET_KEY_RE } from './stubs';

/**
 * Source view: every byte visible, for when the document needs to be
 * controlled directly. Highlighting uses the app's tokens, so a callout is
 * still red and a ticket key still reads as a reference (ADR 0046).
 */
const mdHighlight = HighlightStyle.define([
  { tag: t.heading1, fontWeight: '750', color: 'var(--text)', fontSize: '1.14em' },
  { tag: t.heading2, fontWeight: '700', color: 'var(--text)', fontSize: '1.07em' },
  { tag: [t.heading3, t.heading4, t.heading5, t.heading6], fontWeight: '700', color: 'var(--text)' },
  { tag: t.processingInstruction, color: 'var(--n-300)', fontWeight: '500' },
  { tag: t.strong, fontWeight: '700', color: 'var(--text)' },
  { tag: t.emphasis, fontStyle: 'italic', color: 'var(--text)' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: t.link, color: 'var(--accent)' },
  { tag: t.url, color: 'var(--text-muted)', textDecoration: 'underline' },
  { tag: t.monospace, color: 'var(--pink)' },
  { tag: [t.quote, t.list], color: 'var(--n-700)' },
  { tag: [t.contentSeparator, t.meta], color: 'var(--n-400)' },
]);

export function buildSourceDecorations(state: EditorState): DecorationSet {
  const doc = state.doc;
  const out: Range<Decoration>[] = [];
  const everyLine = (from: number, to: number, cls: string) => {
    for (let n = doc.lineAt(from).number; n <= doc.lineAt(to).number; n++) out.push(Decoration.line({ class: cls }).range(doc.line(n).from));
  };
  ensureSyntaxTree(state, doc.length, 500)?.iterate({
    enter: (n) => {
      if (n.name === 'Blockquote') {
        const tone = calloutTone(doc.sliceString(n.from, Math.min(n.to, n.from + 160))) ?? 'plain';
        everyLine(n.from, n.to, `cm-src-bq cm-src-bq--${tone}`);
      } else if (n.name === 'ATXHeading1' || n.name === 'ATXHeading2') {
        out.push(Decoration.line({ class: 'cm-src-hline' }).range(doc.lineAt(n.from).from));
      } else if (n.name === 'Table') {
        everyLine(n.from, n.to, 'cm-src-table');
        return false;
      }
    },
  });
  const text = doc.toString();
  TICKET_KEY_RE.lastIndex = 0;
  for (let m; (m = TICKET_KEY_RE.exec(text)); ) out.push(Decoration.mark({ class: 'cm-src-ref' }).range(m.index, m.index + m[0].length));
  return Decoration.set(out, true);
}

const sourceField = StateField.define<DecorationSet>({
  create: buildSourceDecorations,
  update: (d, tr) => (tr.docChanged ? buildSourceDecorations(tr.state) : d),
  provide: (f) => EditorView.decorations.from(f),
});

export function sourceView(): Extension {
  return [
    markdown({ base: markdownLanguage }),
    lineNumbers(),
    foldGutter({ openText: '▾', closedText: '▸' }),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    syntaxHighlighting(mdHighlight),
    sourceField,
  ];
}
