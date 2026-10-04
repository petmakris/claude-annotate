// What typing does: the input rules (markdown typed at the start of a block
// or around words becomes the structure) and the keymap.
import { TextSelection } from "prosemirror-state";
import { keymap } from "prosemirror-keymap";
import { history, undo, redo } from "prosemirror-history";
import { baseKeymap, toggleMark, chainCommands, setBlockType, exitCode } from "prosemirror-commands";
import { inputRules, InputRule, wrappingInputRule, textblockTypeInputRule } from "prosemirror-inputrules";
import { splitListItem, liftListItem, sinkListItem } from "prosemirror-schema-list";
import { goToNextCell, isInTable } from "prosemirror-tables";
import { schema } from "./schema.js";

const S = schema.nodes, M = schema.marks;

// ── input rules ──────────────────────────────────────────────────────────
// `**x**`, `*x*`, `` `x` ``: the delimiters go, the mark stays, and what is
// typed next is plain.
function markRule(re, type) {
  return new InputRule(re, (state, match, start, end) => {
    const inner = match[2];
    const lead = match[1] || "";
    const tr = state.tr;
    const from = start + lead.length;
    tr.replaceWith(from, end, schema.text(inner, [type.create()]));
    tr.removeStoredMark(type);
    return tr;
  });
}

export const rules = inputRules({ rules: [
  textblockTypeInputRule(/^(#{1,6})\s$/, S.heading, (m) => ({ level: m[1].length })),
  wrappingInputRule(/^\s*([-+*])\s$/, S.bullet_list),
  wrappingInputRule(/^(\d+)\.\s$/, S.ordered_list, (m) => ({ order: +m[1] }),
    (m, node) => node.childCount + node.attrs.order === +m[1]),
  wrappingInputRule(/^\s*>\s$/, S.blockquote),
  textblockTypeInputRule(/^```([\w+#-]*)\s$/, S.code_block, (m) => ({ params: m[1] })),
  markRule(/(^|[^*])\*\*([^*\s](?:[^*]*[^*\s])?)\*\*$/, M.strong),
  markRule(/(^|[^*\w])\*([^*\s](?:[^*]*[^*\s])?)\*$/, M.em),
  markRule(/(^|[^`])`([^`]+)`$/, M.code),
] });

// ``` then Enter makes a code block too.
function fenceEnter(state, dispatch) {
  const { $from, empty } = state.selection;
  if (!empty || $from.parent.type !== S.paragraph) return false;
  const m = /^```([\w+#-]*)$/.exec($from.parent.textContent);
  if (!m || $from.parentOffset !== $from.parent.content.size) return false;
  if (dispatch) {
    const start = $from.start();
    const tr = state.tr.delete(start, $from.end()).setBlockType(start, start, S.code_block, { params: m[1] });
    dispatch(tr);
  }
  return true;
}

const hardBreak = chainCommands(exitCode, (state, dispatch) => {
  if (dispatch) dispatch(state.tr.replaceSelectionWith(S.hard_break.create()).scrollIntoView());
  return true;
});

// Tab in a table goes to the next cell with the cursor at the end of its
// words, not with the words selected (typing would replace them).
function cell(dir) {
  return (state, dispatch) => {
    if (!isInTable(state)) return false;
    return goToNextCell(dir)(state, dispatch && ((tr) => {
      dispatch(tr.setSelection(TextSelection.create(tr.doc, tr.selection.to)).scrollIntoView());
    }));
  };
}

// Tab where it means nothing (the first item of a list, the last cell of a
// table) does nothing rather than leave the editor: F6 is the way out.
function inListOrTable(state) {
  const { $from } = state.selection;
  for (let d = $from.depth; d > 0; d--) {
    const t = $from.node(d).type;
    if (t === S.list_item || t === S.table) return true;
  }
  return false;
}

// cb: { onSave(), onDone(), onLink() } — each returns nothing.
export function keys(cb) {
  const link = () => { cb.onLink(); return true; };
  return [
    rules,
    keymap({
      "Mod-z": undo, "Shift-Mod-z": redo, "Mod-y": redo,
      "Mod-b": toggleMark(M.strong), "Mod-i": toggleMark(M.em), "Mod-e": toggleMark(M.code), "Mod-k": link,
      "Mod-s": () => { cb.onSave(); return true; },
      "Escape": () => { cb.onDone(); return true; },
      "Shift-Enter": hardBreak, "Mod-Enter": hardBreak,
      "Enter": chainCommands(fenceEnter, splitListItem(S.list_item)),
      "Tab": chainCommands(cell(1), sinkListItem(S.list_item), inListOrTable),
      "Shift-Tab": chainCommands(cell(-1), liftListItem(S.list_item), inListOrTable),
      "Mod-[": liftListItem(S.list_item), "Mod-]": sinkListItem(S.list_item),
      "Mod-Alt-0": setBlockType(S.paragraph),
    }),
    keymap(baseKeymap),
    history(),
  ];
}
