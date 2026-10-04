import { EditorView, keymap, drawSelection } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { history, historyKeymap, defaultKeymap, indentWithTab } from '@codemirror/commands';
import { foldKeymap } from '@codemirror/language';
import { sourceView } from './source';
import { wrapSelection, insertLink } from './commands';

/**
 * The dashboard's DocEditor without React, for annotate's no-bundler page.
 *
 * Source view only: every byte visible. Rich editing is ProseMirror, in
 * edit.js's own bundle; Split is assembled there from a Source editor plus
 * annotate's own preview.
 */

export interface MountOptions {
  doc: string;
  onSave?: () => void;
  onDone?: () => void;
  onChange?: (text: string) => void;
  onToggleMode?: () => void;
}

export interface EditorHandle {
  /** The document exactly as written, CRLF included. */
  getText(): string;
  /** `offset` counts characters of getText(), so a CRLF counts as two. */
  focusAt(offset: number): void;
  destroy(): void;
  view: EditorView;
}

/** CodeMirror splits on any line break, and Text.toString() always joins
 *  with "\n". A document written with CRLF keeps CRLF only when the state is
 *  told that is its separator and is read back through state.sliceDoc(),
 *  which joins with state.lineBreak; typed newlines then match. The same
 *  holds for a document whose lines end in a lone CR. */
function lineSeparatorOf(doc: string): string | null {
  if (doc.includes('\r\n')) return '\r\n';
  if (doc.includes('\r')) return '\r';       // old Mac line endings
  return null;
}

export function mount(host: HTMLElement, opts: MountOptions): EditorHandle {
  const noop = () => {};
  const cb = {
    onSave: opts.onSave ?? noop,
    onDone: opts.onDone ?? noop,
    onChange: opts.onChange ?? noop,
    onToggleMode: opts.onToggleMode ?? noop,
  };
  const sep = lineSeparatorOf(opts.doc);
  const view = new EditorView({
    parent: host,
    state: EditorState.create({
      doc: opts.doc,
      extensions: [
        sep ? EditorState.lineSeparator.of(sep) : [],
        sourceView(),
        history(),
        drawSelection(),
        EditorView.lineWrapping,
        keymap.of([
          { key: 'Mod-b', run: (v) => wrapSelection('**', 'bold')(v) },
          { key: 'Mod-i', run: (v) => wrapSelection('*', 'italic')(v) },
          { key: 'Mod-e', run: (v) => wrapSelection('`', 'code')(v) },
          { key: 'Mod-k', run: (v) => insertLink(v) },
          { key: 'Mod-s', preventDefault: true, run: () => { cb.onSave(); return true; } },
          { key: 'Mod-/', preventDefault: true, run: () => { cb.onToggleMode(); return true; } },
          { key: 'Escape', run: () => { cb.onDone(); return true; } },
          ...foldKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.updateListener.of((u) => { if (u.docChanged) cb.onChange(u.state.sliceDoc()); }),
      ],
    }),
  });
  // Every key typed in the editor is the editor's. The page's own shortcuts
  // (j, k, c, d, x, r, e) listen on document in the bubble phase; stopping
  // here keeps them from firing while typing, and stopping handled keys (⌘S,
  // ⌘/, ⌘K, Esc) keeps the page from acting on them twice. Default actions
  // are untouched, so the browser still sees what the editor did not handle.
  const keep = (e: KeyboardEvent) => { e.stopPropagation(); };
  host.addEventListener('keydown', keep);

  return {
    view,
    getText: () => view.state.sliceDoc(),
    focusAt(offset: number) {
      // CodeMirror counts a line break as one position whatever its bytes,
      // so an offset into getText() drops (sep.length - 1) for every
      // separator before it: one per CRLF, none per lone CR.
      let pos = Math.max(0, offset | 0);
      if (sep) pos -= (view.state.sliceDoc().slice(0, pos).split(sep).length - 1) * (sep.length - 1);
      pos = Math.min(pos, view.state.doc.length);
      view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) });
      view.focus();
    },
    destroy() {
      host.removeEventListener('keydown', keep);
      view.destroy();
    },
  };
}
