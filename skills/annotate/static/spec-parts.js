/* spec-parts.js — the parts painted from a checked spec: decisions, facts, jobs.
 *
 * Which kinds use which painter is the registry's `painter` trait
 * (block-kinds.json); blocks.py checks each spec at push time, and everything
 * below is written with textContent, never HTML.
 *
 * A decision and a job is its own comment target: it carries
 * data-annotate-id (its id), so words selected inside it report that id as
 * step_id, and a small button (the one a table row has, tables.js) comments on
 * it without words. A facts strip is commented whole, through its title.
 */
(function () {
  "use strict";

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // The children of `parent`, a line break between each (whitespace-only, so
  // nothing shifts on screen): a part's text reads as lines, as a markdown
  // part's does, and the words round a selection stay apart in its context.
  function lines(parent, ...kids) {
    kids.forEach((k, i) => { if (i) parent.append(document.createTextNode("\n")); parent.append(k); });
    return parent;
  }

  // The same comment button a table row has; tables.js owns the click.
  function commentButton(id) {
    return window.AnnotateTables ? window.AnnotateTables.button(id, true) : el("span");
  }

  function decisions(content, blk) {
    const list = el("div", "dec-list");
    let first = true;
    for (const d of (blk.spec && blk.spec.decisions) || []) {
      if (!first) list.append(document.createTextNode("\n"));
      first = false;
      const answered = d.status === "answered";
      const item = el("div", "dec");
      item.dataset.annotateId = d.id;
      item.dataset.status = answered ? "answered" : "open";
      const head = el("div", "dec-head");
      lines(head, el("span", "dec-id", d.id),
            el("span", "dec-status", answered ? "Answered" : "Open"), commentButton(d.id));
      const q = el("p", "dec-q", d.question);
      const rec = el("p", "dec-rec");
      rec.append(el("span", "dec-k", "Recommended"), document.createTextNode(" " + d.recommendation + " "),
                 el("span", "dec-why", d.why));
      const kids = [head, q, rec];
      if (answered) {
        const ans = el("p", "dec-ans");
        ans.append(el("span", "dec-k", "Your answer"), document.createTextNode(" " + d.answer));
        kids.push(ans);
      }
      lines(item, ...kids);
      list.append(item);
    }
    content.replaceChildren(list);
  }

  function facts(content, blk) {
    const strip = el("div", "facts-strip");
    for (const f of (blk.spec && blk.spec.facts) || []) {
      if (strip.childNodes.length) strip.append(document.createTextNode("\n"));
      strip.append(lines(el("div", "fact"), el("div", "fact-value", f.value), el("div", "fact-label", f.label)));
    }
    content.replaceChildren(strip);
  }

  function jobs(content, blk) {
    const list = el("ol", "job-list");
    const all = (blk.spec && blk.spec.jobs) || [];
    let first = true;
    for (const j of all) {
      if (!first) list.append(document.createTextNode("\n"));
      first = false;
      const item = el("li", "job");
      item.dataset.annotateId = j.id;
      item.dataset.status = j.status;
      const head = el("div", "job-head");
      lines(head, el("span", "job-id", j.id), el("span", "job-title", j.title),
            el("span", "job-status", j.status), commentButton(j.id));
      const after = j.after || [];
      lines(item, head, el("p", "job-does", j.does),
            el("p", "job-after", after.length ? "Waits on " + after.join(", ") : "Starts first"));
      list.append(item);
    }
    content.replaceChildren(list);
  }

  const painters = { decisions, facts, jobs };

  window.AnnotateSpecParts = {
    paint(painter, content, blk) { if (painters[painter]) painters[painter](content, blk); },
  };
})();
