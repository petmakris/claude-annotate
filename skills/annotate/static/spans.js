// annotate — a mark that covers words in more than one part.
//
// A selection may cross a heading. Each part it touches gives one anchor
// (anchors.js anchorsAcross); together they are one mark, and one reaction
// in the round that names every block it covers. A mark on one part keeps
// exactly the shape and key it always had, so nothing stored or sent before
// changes meaning.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateSpans = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function partsOf(m) {
    return m && Array.isArray(m.spans) && m.spans.length ? m.spans : [m];
  }
  function partKey(p) {
    return `${p.block_id}::__span__::${p.prefix || ""}␟${p.selected_text}␟${p.suffix || ""}`;
  }
  function markKey(parts) {
    return parts.map(partKey).join("⁞");
  }
  function joinQuote(parts) {
    return parts.map((p) => p.selected_text).join("\n");
  }
  function blockIdsOf(m) {
    return [...new Set(partsOf(m).map((p) => p.block_id))];
  }
  function withSpans(parts) {
    if (parts.length === 1) return parts[0];
    return { block_id: parts[0].block_id, selected_text: joinQuote(parts),
             prefix: parts[0].prefix || "", suffix: parts[parts.length - 1].suffix || "",
             spans: parts };
  }
  function textOnly(parts, kindOf, wholeOnly) {
    return parts.filter((p) => !wholeOnly.includes(kindOf(p.block_id)));
  }

  // Whether two marks share words. Each is given as its parts already found
  // on the page, `{ block_id, span: [start, end] }` (span null when a part's
  // words are gone). They share words when some part of one and some part of
  // the other sit in the same block and their character ranges cross; ranges
  // that only touch do not. A new mark replaces every mark this is true of.
  function overlaps(a, b) {
    return a.some((x) => x.span && b.some((y) => y.span && x.block_id === y.block_id
      && y.span[0] < x.span[1] && x.span[0] < y.span[1]));
  }

  return { partsOf, partKey, markKey, joinQuote, blockIdsOf, withSpans, textOnly, overlaps };
});
