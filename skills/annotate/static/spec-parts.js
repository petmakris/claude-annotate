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

  // Every option is its own card inside the decision. The recommended one is
  // marked and carries the why; once answered, the chosen one says "Your
  // choice" and the rest are dimmed. While open, each has a Choose button: its
  // words come from CSS (aria-label here), so no text enters the part's text.
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
      const opts = el("div", "dec-opts");
      let firstOpt = true;
      for (const o of d.options || []) {
        if (!firstOpt) opts.append(document.createTextNode("\n"));
        firstOpt = false;
        const rec = o.id === d.recommended;
        const mine = answered && o.id === d.chosen;
        const card = el("div", "dec-opt");
        card.dataset.option = o.id;
        if (rec) card.dataset.recommended = "1";
        if (mine) card.dataset.chosen = "1";
        if (answered && !mine) card.dataset.dim = "1";
        const top = el("div", "opt-head");
        const kids = [el("span", "opt-id", o.id), el("span", "opt-label", o.label)];
        if (rec) kids.push(el("span", "opt-badge opt-rec", "Recommended"));
        if (mine) kids.push(el("span", "opt-badge opt-mine", "Your choice"));
        lines(top, ...kids);
        const parts = [top, el("p", "opt-trade", o.trade)];
        if (rec) parts.push(el("p", "dec-why", d.why));
        lines(card, ...parts);
        if (!answered) {
          const btn = el("button", "dec-choose");
          btn.type = "button";
          btn.dataset.decision = d.id;
          btn.dataset.option = o.id;
          btn.dataset.label = o.label;
          btn.setAttribute("aria-label", `Choose ${o.id}: ${o.label}`);
          card.append(btn);
        }
        opts.append(card);
      }
      const kids = [head, el("p", "dec-q", d.question), opts];
      if (answered && d.answer) {
        const ans = el("p", "dec-ans");
        ans.append(el("span", "dec-k", "Your answer"), document.createTextNode(" " + d.answer));
        kids.push(ans);
      }
      lines(item, ...kids);
      list.append(item);
    }
    content.replaceChildren(list);
  }

  // Pressing Choose pins one comment on that decision, `Choose <id>: <label>`,
  // into the reader's round, as the comment window's Add to round does
  // (pinComment): it goes out with the next Submit round. A decision holds one
  // pending comment, so this replaces an earlier one on the same decision.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest && ev.target.closest("button.dec-choose");
    if (!btn) return;
    const section = btn.closest("section.block");
    if (!section || !window.AnnotateSubunits) return;
    ev.preventDefault();
    window.AnnotateSubunits.pinComment({
      block_id: section.dataset.blockId,
      step_id: btn.dataset.decision,
      text: `Choose ${btn.dataset.option}: ${btn.dataset.label}`,
    });
    if (typeof applyEngagedStyling === "function") applyEngagedStyling();
    if (window.AnnotateA11y) window.AnnotateA11y.announce(`Chose ${btn.dataset.option}, added to the round`);
  });

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
