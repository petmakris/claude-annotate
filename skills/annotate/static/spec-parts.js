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
 *
 * Decisions: a pick is only ever a pending comment in the reader's round
 * (AnnotateSubunits.pinComment, step_id = the decision id), so the page's own
 * Submit round is the one way anything is sent, and a decision nobody pressed
 * a button on stays open. What a card shows (not decided, picked, sent,
 * answered) is worked out each time from three things: the spec (Claude's
 * status), the pending comment on that decision, and whether the page is busy.
 * Nothing about it is stored in the spec.
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

  // Page chrome inside a decision (counts, buttons, states): not the part's
  // words, so a selection's text and its context leave it out (anchors.js SKIP).
  const ui = (node) => { node.classList.add("dec-ui"); return node; };

  const busy = () => document.body.classList.contains("is-busy");
  const subunits = () => window.AnnotateSubunits;

  // ── Decisions ─────────────────────────────────────────────────────────
  // What the reader has opened (other ways, the text box, technical detail),
  // so a repaint does not close it; keyed by block and decision.
  const reveal = new Map();
  const revealOf = (key) => {
    if (!reveal.has(key)) reveal.set(key, { alts: false, write: false, reopen: false, text: "", detail: {} });
    return reveal.get(key);
  };
  // Decisions the reader answered in their own words this visit (a pick the
  // page can tell from a plain comment), and picks made while the page was
  // already busy (they wait for the next round, so they are not "sent").
  const ownWords = new Set();
  const queued = new Set();
  // Every decisions part on the page, to repaint when pending comments or the
  // busy state change.
  const mounted = new Set();

  const PICK = /^Choose ([a-d]): /;
  const WORDS = {
    open: "Not decided", picked: "Picked, not sent", sent: "Sent, Claude is updating",
    answered: "Answered",
  };

  function stateOf(blockId, d) {
    const key = blockId + "|" + d.id;
    const R = revealOf(key);
    const mark = subunits() && subunits().stepMark ? subunits().stepMark(blockId, d.id) : null;
    const pick = mark ? PICK.exec(mark.text) : null;
    const option = pick ? (d.options || []).find((o) => o.id === pick[1]) : null;
    if (mark && (option || ownWords.has(key))) {
      if (!busy()) queued.delete(key);
      return { st: busy() && !queued.has(key) ? "sent" : "picked", option, own: option ? null : mark.text, key, R };
    }
    queued.delete(key);
    const note = !!mark;   // a plain comment is waiting; the decision is still open
    if (d.status === "answered" && !R.reopen) return { st: "answered", key, R, note };
    return { st: "open", key, R, note };
  }

  function order(list) {
    const hard = list.filter((d) => d.change === "hard");
    const easy = list.filter((d) => d.change !== "hard");
    return { hard, easy, all: hard.concat(easy), grouped: hard.length > 0 && easy.length > 0 };
  }

  function gainCost(o) {
    if (o.gain && o.cost) {
      const dl = el("dl", "dec-gc");
      dl.append(el("dt", null, "You get"), el("dd", null, o.gain), el("dt", null, "It costs"), el("dd", null, o.cost));
      return dl;
    }
    return el("p", "dec-trade", o.trade || "");
  }

  function technical(o, R, key) {
    if (!o.detail) return null;
    const dt = el("details", "dec-detail");
    if (R.detail[o.id]) dt.open = true;
    dt.addEventListener("toggle", () => { R.detail[o.id] = dt.open; });
    dt.append(ui(el("summary", null, "Technical detail")), el("p", null, o.detail));
    return dt;
  }

  // A button that pins `Choose <id>: <label>`; the delegated handler below
  // does the pinning, so it carries what it needs.
  function pickButton(d, o, text, cls) {
    const b = ui(el("button", "dec-btn dec-choose " + cls, text));
    b.type = "button";
    b.dataset.decision = d.id;
    b.dataset.option = o.id;
    b.dataset.label = o.label;
    return b;
  }

  function button(text, cls, fn) {
    const b = ui(el("button", "dec-btn " + cls, text));
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }

  function cardBody(blockId, d, S, shown, ctx) {
    const { st, R, key } = S;
    const rec = (d.options || []).find((o) => o.id === d.recommended);
    const alts = (d.options || []).filter((o) => o.id !== d.recommended);
    const head = ui(el("div", "dec-top"));
    const kids = [];
    if (ctx.many) kids.push(el("span", "dec-no", "Question " + (ctx.index + 1)));
    kids.push(el("span", "dec-chip " + (d.change === "hard" ? "hard" : "easy"),
                 d.change === "hard" ? "Hard to undo" : "Easy to change later"),
              el("span", "dec-state", WORDS[st]), commentButton(d.id));
    lines(head, ...kids);
    const out = [head, el("p", "dec-q", d.question)];

    if (st === "open") {
      const box = el("div", "dec-rec");
      const parts = [ui(el("div", "dec-k", "Claude suggests")), el("div", "dec-lab", rec.label), gainCost(rec),
                     el("p", "dec-why", "Why: " + d.why)];
      const dt = technical(rec, R, key);
      if (dt) parts.push(dt);
      lines(box, ...parts);
      out.push(box);
      if (d.change === "hard") out.push(el("p", "dec-hard", d.change_note));
      if (alts.length) {
        const others = el("div", "dec-others");
        lines(others, ...alts.map((a) => {
          const row = el("div", "dec-oth");
          row.append(ui(el("b", null, "Other way")), el("span", null, a.label));
          return row;
        }));
        out.push(others);
      }
      const acts = ui(el("div", "dec-acts"));
      const kidsA = [pickButton(d, rec, "Go with Claude's suggestion", "pri")];
      if (alts.length) {
        kidsA.push(button(R.alts ? "Hide the other way" : (alts.length > 1 ? `See other ways (${alts.length})` : "See other way"),
                          "ghost", () => { R.alts = !R.alts; refreshAll(); }));
      }
      kidsA.push(button("Write my own", "ghost", () => { R.write = !R.write; refreshAll(); }));
      acts.append(...kidsA);
      out.push(acts);
      if (R.alts) {
        const wrap = el("div", "dec-alts");
        for (const a of alts) {
          const card = el("div", "dec-alt");
          const parts = [ui(el("div", "dec-k", "Other way")), el("div", "dec-lab", a.label), gainCost(a)];
          const dt2 = technical(a, R, key);
          if (dt2) parts.push(dt2);
          if (d.switch_if) parts.push(el("p", "dec-if", "Pick this way if: " + d.switch_if));
          parts.push(pickButton(d, a, "Pick this one instead", ""));
          lines(card, ...parts);
          wrap.append(card);
        }
        out.push(wrap);
      }
      if (R.write) {
        const own = ui(el("div", "dec-own"));
        const ta = el("textarea");
        ta.setAttribute("aria-label", "Your own answer");
        ta.placeholder = "Write your answer in your own words";
        ta.value = R.text;
        ta.addEventListener("input", () => { R.text = ta.value; });
        own.append(ta, button("Use my answer", "pri", () => {
          const text = ta.value.trim();
          if (!text) { ta.focus(); return; }
          useWords(blockId, d, S, text);
        }));
        out.push(own);
      }
      if (S.note) out.push(ui(el("p", "dec-next", "Your comment is in the round. This question is still open.")));
      if (d.next) out.push(ui(el("p", "dec-next", "After you send: " + d.next)));
    } else {
      const box = ui(el("div", "dec-mine"));
      const answeredOpt = st === "answered" ? (d.options || []).find((o) => o.id === d.chosen) : null;
      const opt = st === "answered" ? answeredOpt : S.option;
      const words = st === "answered" ? d.answer : S.own;
      if (opt) {
        box.append(document.createTextNode((st === "answered" ? "You chose: " : "Your pick: ") + opt.label));
        if (st !== "answered") {
          box.append(el("small", null, opt.id === d.recommended ? "This is Claude's suggestion."
            : `Not Claude's suggestion. Claude suggested "${rec.label}".`));
        }
        if (st === "answered" && words) box.append(el("small", null, "Your own words: " + words));
      } else {
        box.append(document.createTextNode("Your own words: " + words));
      }
      out.push(box);
      if (st === "answered" && d.outcome) out.push(ui(el("p", "dec-outc", "Claude changed the plan: " + d.outcome)));
      if (st === "picked") {
        out.push(ui(el("p", "dec-next", "Not sent yet. It goes to Claude when you press Submit round.")));
        out.push(button("Change my mind", "ghost sm", () => { subunits().removeStepMark(blockId, d.id); }));
      } else if (st === "sent") {
        out.push(ui(el("p", "dec-next", "Sent. Claude is writing your answer into the plan.")));
      } else {
        out.push(button("Change my answer", "ghost sm", () => { R.reopen = true; refreshAll(); }));
      }
    }
    return out;
  }

  // Pin the reader's own words as a plain comment on the decision.
  function useWords(blockId, d, S, text) {
    S.R.write = false; S.R.text = ""; S.R.reopen = false;
    ownWords.add(S.key);
    if (busy()) queued.add(S.key);
    subunits().pinComment({ block_id: blockId, step_id: d.id, text });
    if (window.AnnotateA11y) window.AnnotateA11y.announce("Your words were added to the round");
    refreshAll();
  }

  function chipLabel(i, d, S) {
    return `Question ${i + 1}, ${d.change === "hard" ? "hard to undo" : "easy to change later"}, ${WORDS[S.st].toLowerCase()}`;
  }

  function summary(blockId, list, states, ord, part) {
    const n = (k) => list.filter((d) => states.get(d.id).st === k).length;
    const strip = ui(el("div", "dec-sum"));
    const count = el("div", "dec-sum-count", `${n("answered")} of ${list.length} answered`);
    const sent = n("sent"), picked = n("picked");
    const sub = [];
    if (picked) sub.push(`${picked} picked, not sent`);
    if (sent) sub.push(`${sent} sent`);
    sub.push(`${n("open")} not decided`);
    const subline = el("div", "dec-sum-sub", sub.join(". ") + ". Tap a number to jump to that question.");
    const chips = el("div", "dec-chips");
    ord.all.forEach((d, i) => {
      const S = states.get(d.id);
      const b = el("button", "dec-nchip", String(i + 1));
      b.type = "button";
      b.dataset.s = S.st;
      b.dataset.hard = d.change === "hard" ? "1" : "0";
      b.setAttribute("aria-label", chipLabel(i, d, S));
      b.addEventListener("click", () => {
        const card = part.querySelector(`.dec[data-annotate-id="${d.id}"]`);
        if (card) card.scrollIntoView({ block: "start" });
      });
      chips.append(b);
    });
    const key = el("div", "dec-key", "Red underline: hard to undo. Grey: not decided. Amber: picked. Blue: sent. Green: answered.");
    strip.append(count, subline, chips, key);
    return strip;
  }

  function paintDecisions(entry) {
    const { content, blk } = entry;
    const blockId = blk.id;
    const list = (blk.spec && blk.spec.decisions) || [];
    const ord = order(list);
    const many = list.length > 1;
    const states = new Map(list.map((d) => [d.id, stateOf(blockId, d)]));
    const part = el("div", "dec-list");
    const kids = [];
    if (many) kids.push(summary(blockId, list, states, ord, part));
    const section = (decs, title) => {
      const items = [];
      if (ord.grouped) items.push(ui(el("div", "dec-group", `${title} (${decs.length})`)));
      for (const d of decs) {
        const S = states.get(d.id);
        const card = el("div", "dec");
        card.dataset.annotateId = d.id;
        card.dataset.status = S.st;
        if (S.st === "picked" || S.st === "sent" || S.note) card.dataset.rowMark = "comment";
        lines(card, ...cardBody(blockId, d, S, true, { many, index: ord.all.indexOf(d) }));
        items.push(card);
      }
      return items;
    };
    if (ord.grouped) {
      kids.push(...section(ord.hard, "Read these first. Hard to undo"),
                ...section(ord.easy, "Easy to change later. A wrong pick costs little"));
    } else {
      kids.push(...section(ord.all, ""));
    }
    lines(part, ...kids);
    content.replaceChildren(part);
  }

  function decisions(content, blk) {
    const entry = { content, blk };
    mounted.add(entry);
    paintDecisions(entry);
  }

  function refreshAll() {
    for (const e of [...mounted]) {
      if (!e.content.isConnected && e.painted) { mounted.delete(e); continue; }
      if (e.content.isConnected) e.painted = true;
      paintDecisions(e);
    }
  }
  document.addEventListener("annotate:marks", refreshAll);
  document.addEventListener("annotate:busy", refreshAll);

  // Pressing a pick button pins `Choose <option id>: <label>` on that
  // decision into the reader's round, as the comment window's Add to round
  // does (pinComment): it goes out with the next Submit round, and nothing
  // goes out without it. A decision holds one pending comment, so a second
  // pick replaces the first.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest && ev.target.closest("button.dec-choose");
    if (!btn) return;
    const section = btn.closest("section.block");
    if (!section || !subunits()) return;
    ev.preventDefault();
    const blockId = section.dataset.blockId;
    const key = blockId + "|" + btn.dataset.decision;
    const R = revealOf(key);
    R.alts = false; R.write = false; R.reopen = false;
    ownWords.delete(key);
    if (busy()) queued.add(key);
    subunits().pinComment({
      block_id: blockId,
      step_id: btn.dataset.decision,
      text: `Choose ${btn.dataset.option}: ${btn.dataset.label}`,
    });
    if (typeof applyEngagedStyling === "function") applyEngagedStyling();
    if (window.AnnotateA11y) window.AnnotateA11y.announce(`Picked ${btn.dataset.label}, added to the round`);
    refreshAll();
  });

  // ── Facts and jobs ────────────────────────────────────────────────────
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
