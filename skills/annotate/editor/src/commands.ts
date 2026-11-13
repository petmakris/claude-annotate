import type { StateCommand } from '@codemirror/state';

/**
 * Markdown formatting as plain text edits. Nothing here parses: `⌘B` puts
 * `**` either side of the selection and leaves the words selected, exactly as
 * typing it would. The document stays the user's own bytes (ADR 0046).
 */
export function wrapSelection(marker: string, placeholder: string): StateCommand {
  return ({ state, dispatch }) => {
    const r = state.selection.main;
    const text = state.sliceDoc(r.from, r.to) || placeholder;
    const start = r.from + marker.length;
    dispatch(state.update({
      changes: { from: r.from, to: r.to, insert: marker + text + marker },
      selection: { anchor: start, head: start + text.length },
      userEvent: 'input.format',
    }));
    return true;
  };
}

/** `[selection](https://)`, with the url selected so the next keystrokes replace it. */
export const insertLink: StateCommand = ({ state, dispatch }) => {
  const r = state.selection.main;
  const text = state.sliceDoc(r.from, r.to) || 'text';
  const url = 'https://';
  const at = r.from + text.length + 3;
  dispatch(state.update({
    changes: { from: r.from, to: r.to, insert: `[${text}](${url})` },
    selection: { anchor: at, head: at + url.length },
    userEvent: 'input.format',
  }));
  return true;
};

/**
 * The smallest single edit turning `from` into `to`. Used when text arrives
 * from outside the editor (a worker's write, take theirs), so the change lands
 * where it happened and the cursor elsewhere stays put — replacing the whole
 * document would throw it to the end.
 */
export function minimalChange(from: string, to: string): { from: number; to: number; insert: string } | null {
  if (from === to) return null;
  let start = 0;
  const max = Math.min(from.length, to.length);
  while (start < max && from[start] === to[start]) start++;
  let endA = from.length, endB = to.length;
  while (endA > start && endB > start && from[endA - 1] === to[endB - 1]) { endA--; endB--; }
  return { from: start, to: endA, insert: to.slice(start, endB) };
}
