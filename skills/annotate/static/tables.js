/* tables.js — every row of a table in a markdown part is a comment target.
 *
 * Each body row gets a stable `data-annotate-id` (its first cell's words,
 * slugged; `row-N` when that gives nothing), so a selection inside the row
 * reaches Claude as `step_id` through the same path as any authored region
 * (anchors.js anchorFor). A small button on the row comments on it without
 * selecting words: it opens the same comment window a diagram step uses
 * (openAnnotation, script.js) and pins a step mark.
 *
 * The button holds no text node, so it never enters a part's text (the offsets
 * a selection is anchored by, anchors.js walker).
 */
(function () {
  "use strict";

  const MAX_SLUG = 40;

  function slug(text) {
    return String(text || "").toLowerCase()
      .normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
      .slice(0, MAX_SLUG).replace(/-+$/g, "");
  }

  // The id of each body row of every table under `root`: first cell's slug,
  // made unique within the part, else `row-N` (N counts the part's rows).
  // A row that already carries a data-annotate-id (authored HTML) keeps it.
  function decorate(root) {
    if (!root || !root.querySelectorAll) return;
    const used = new Set();
    root.querySelectorAll("[data-annotate-id]").forEach((el) => used.add(el.dataset.annotateId));
    let n = 0;
    root.querySelectorAll("table tbody tr").forEach((tr) => {
      n++;
      if (tr.querySelector(".row-comment")) return;
      let id = tr.dataset.annotateId;
      if (!id) {
        const base = slug(tr.children[0] ? tr.children[0].textContent : "") || `row-${n}`;
        id = base;
        for (let k = 2; used.has(id); k++) id = `${base}-${k}`;
        tr.dataset.annotateId = id;
        used.add(id);
      }
      const last = tr.children[tr.children.length - 1];
      if (!last) return;
      last.appendChild(button(id, false));
    });
  }

  // The wordless comment button, for a table row and for a decision or job
  // (spec-parts.js). It holds no text node, so it never enters a part's text.
  function button(id, item) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = item ? "item-comment" : "row-comment";
    btn.setAttribute("aria-label", `Comment on ${item ? "this item" : "this row"} (${id})`);
    btn.title = item ? "Comment on this" : "Comment on this row";
    btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" '
      + 'fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>';
    return btn;
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest && ev.target.closest("button.row-comment, button.item-comment");
    if (!btn) return;
    const tr = btn.closest("[data-annotate-id]");
    const section = btn.closest("section.block");
    if (!tr || !section || typeof openAnnotation !== "function") return;
    ev.preventDefault();
    openAnnotation(section, "comment", { stepId: tr.dataset.annotateId });
  });

  window.AnnotateTables = { decorate, slug, button };
})();
