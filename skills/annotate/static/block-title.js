// annotate skill — what a card's header calls a block.
//
// Extracted from script.js so it can be executed and asserted on
// (tests/block_title.test.cjs). A source-string check cannot tell "flowchart
// falls through to the markdown branch" from "flowchart has a branch of its
// own" — both contain the word — and that is precisely the defect this file
// was pulled out to fix.
//
// The rule, in priority order:
//
//   1. `blk.title`      — the author named it; nothing overrides that.
//   2. `blk.spec.title` — a diagram names itself inside its spec. Flowchart,
//      sequence and choice all carry one, and a flowchart's was authored and
//      then ignored: the card said "Section" while the spec said "Outbound:
//      every id montblanc puts on the wire". With one diagram per dimension of
//      a topic, that is a page of identically-named cards.
//   3. the first heading or first line of `blk.markdown`.
//   4. a per-kind fallback — "Diagram", "Decision", "Section" — which is the
//      last resort and not, as it was, where every flowchart landed.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateBlockTitle = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Kinds whose content is a spec rather than prose. Each names itself under a
  // different key, and each needs a fallback that says what the card IS —
  // "Section" is what a card is called when nothing could name it, and a
  // diagram that failed to name itself is not a section.
  const SPEC_TITLED = {
    sequence:  { keys: ["title"],    fallback: "Diagram" },
    flowchart: { keys: ["title"],    fallback: "Diagram" },
    choice:    { keys: ["question"], fallback: "Decision" },
  };

  const MAX_LEN = 60;

  function clean(s) {
    return String(s == null ? "" : s).trim();
  }

  function blockTitle(blk) {
    blk = blk || {};
    const own = clean(blk.title);
    if (own) return own;

    const kind = blk.kind || "markdown";
    const rule = SPEC_TITLED[kind];
    if (rule) {
      const spec = blk.spec || {};
      for (const key of rule.keys) {
        const t = clean(spec[key]);
        if (t) return t;
      }
      return rule.fallback;
    }

    const md = blk.markdown || "";
    const heading = md.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/m);
    let t = heading
      ? heading[1]
      : (md.split(/\n/).map((s) => s.replace(/^[#>*\-\s`]+/, "").trim()).find(Boolean) || "");
    t = t.replace(/[*_`]/g, "").replace(/\s+/g, " ").trim();
    if (t.length > MAX_LEN) t = t.slice(0, MAX_LEN - 1).trimEnd() + "…";
    return t || "Section";
  }

  return { blockTitle, MAX_LEN };
});
