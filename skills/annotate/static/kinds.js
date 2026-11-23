/* kinds.js — the page's reader of the block-kind registry.
 *
 * The registry is static/block-kinds.json, the same file kinds.py reads.
 * entry.js fetches it and leaves it on window.__annotateKindData before any
 * script runs; this file turns it into the one question the page asks:
 * `AnnotateKinds.is(kind, "framed")`. No other file lists kinds.
 */
(function () {
  "use strict";
  const data = window.__annotateKindData || { kinds: {}, retired: {} };
  const kinds = data.kinds || {};
  const retired = data.retired || {};

  // Does `kind` have `trait`? A retired kind answers for the traits it keeps
  // (an old page still names it); an unknown kind has none, like markdown.
  function is(kind, trait) {
    const k = kinds[kind || "markdown"] || retired[kind];
    return !!(k && k[trait]);
  }

  // The trait's value itself (for the non-boolean ones: renderer, code).
  function get(kind, trait) {
    const k = kinds[kind || "markdown"];
    return k ? k[trait] : undefined;
  }

  window.AnnotateKinds = { is, get, names: () => Object.keys(kinds) };
})();
