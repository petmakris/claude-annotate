// annotate — which parts a fold hides.
//
// The page reads as one document, so folding goes by heading, as in any
// document: a heading folds its own part and every untitled part after it,
// up to the next heading. A part with no heading above it never folds, and
// a page with no headings folds nothing, whatever an older visit stored.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateFolds = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function foldPlan(blocks) {
    const folded = new Set(), hidden = new Set();
    let owner = null;
    for (const b of blocks || []) {
      if (b.heading) {
        owner = b;
        if (b.collapsed) folded.add(b.id);
      } else if (owner && owner.collapsed) {
        hidden.add(b.id);
      }
    }
    return { folded, hidden };
  }

  function ownerOf(blocks, id) {
    let owner = null;
    for (const b of blocks || []) {
      if (b.heading) owner = b.id;
      if (b.id === id) return owner;
    }
    return null;
  }

  return { foldPlan, ownerOf };
});
