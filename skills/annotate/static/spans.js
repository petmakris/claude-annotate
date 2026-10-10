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

  return { partsOf, partKey, markKey, joinQuote, blockIdsOf, withSpans, textOnly };
});
