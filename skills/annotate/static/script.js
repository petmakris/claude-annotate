// annotate skill — client-side incremental rendering and per-block submission
(function () {
  // Base path of the page, e.g. "/" or "/s/<sid>/". Relative fetches use this.
  const BASE = (() => {
    const p = window.location.pathname;
    return p.endsWith("/") ? p : p + "/";
  })();

  const proseEl = document.querySelector("main.prose");
  const STORAGE_KEY = `annotate.drafts.${document.body.dataset.responseId || ""}`;

  const commentMd = (typeof window.markdownit === "function")
    ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: true })
    : null;

  // ── Drafts ─────────────────────────────────────────────────────────────────
  // annotations: { [annotId]: { block_id, type, selected_text, comment, images? } }
  let annotations = loadDrafts();

  // Submitted comments awaiting Claude's ack: event_id -> { blockId } for a
  // block/diagram/choice comment, or { general: true } for a page-level one.
  // The block "updating" overlay / composer status line resolves when the
  // matching event_id appears in /poll's consumed_events — the real done-signal,
  // which does NOT depend on Claude rewriting the commented block specifically.
  const pendingEvents = new Map();

  // CSS.escape fallback (older engines): block/step/annotate ids can be
  // Claude-authored, so a raw `[data-block-id="${id}"]` would throw on a quote.
  const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\\]]/g, "\\$&");

  function loadDrafts() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
    catch { return {}; }
  }

  function saveDrafts() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations)); }
    catch {}
  }

  // ── Rendering ──────────────────────────────────────────────────────────────
  const PLACEHOLDER_TEXT = { comment: "Your comment…" };

  // Feather-style line icons for the card-header strip. The four controls are
  // the same four the sub-unit strip offers (AnnotateSubunits.CONTROLS) —
  // scope is communicated by WHERE the strip lives (header = whole block,
  // body = one paragraph), never by giving the two scopes different verbs.
  const ICON = {
    comment: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
    keep: '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    compact: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
  };
  const ACTION_TYPES = [
    { id: "delete",  title: "Delete — removed for good (undo until you submit)" },
    { id: "keep",    title: "Keep — don't rewrite this section" },
    { id: "comment", title: "Comment — fold a response into this section" },
    { id: "compact", title: "Compact — take this section off the page; its point is folded into what stays" },
  ];

  const HOVER_LINGER_MS = 500;

  function renderHoverActions() {
    // The block-scope strip lives in the CARD HEADER and appears only when the
    // header is hovered. That is load-bearing, not cosmetic: the card body is
    // reserved exclusively for per-sentence feedback, so the two scopes can
    // never fight for the same pixels or leave the user guessing which one a
    // click will hit. Position teaches scope.
    //
    // Every block kind gets this strip — including sequence/diagram/flowchart/
    // choice, which previously had none and so could not be deleted at all.
    // Their bodies keep their own click behaviour (step comments, option
    // picks); only the whole-block controls live up here.
    //
    // We still have to skip SVG <g class="step-row"> elements: they carry
    // data-block-id too (for the submit payload) but are not block containers.
    const HEADING_TAGS = new Set(["H1", "H2", "H3", "H4", "H5", "H6"]);
    document.querySelectorAll("[data-block-id]").forEach(block => {
      if (block.tagName !== "SECTION") return;
      if (HEADING_TAGS.has(block.tagName)) return;
      if (block.querySelector(".hover-actions")) return;
      const head = block.querySelector(".card-head");
      if (!head) return;
      const wrap = document.createElement("div");
      wrap.className = "hover-actions";
      let hideTimer = null;
      const show = () => {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        wrap.dataset.visible = "1";
      };
      const scheduleHide = () => {
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(() => { delete wrap.dataset.visible; hideTimer = null; }, HOVER_LINGER_MS);
      };
      // The whole header row is the trigger. Scoping it to the title alone
      // was tried and rejected: it makes a bold-text-width target that the
      // pointer keeps missing. That scoping only existed because the strip
      // used to sit at the far right, which is no longer true — the buttons
      // now mount beside the title (below), so a band-wide trigger reveals
      // controls the user is already looking at.
      const titleEl = head.querySelector(".card-title") || head;
      head.addEventListener("mouseenter", show);
      head.addEventListener("mouseleave", scheduleHide);
      wrap.addEventListener("mouseenter", show);
      wrap.addEventListener("mouseleave", scheduleHide);
      for (const t of ACTION_TYPES) {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.type = t.id;
        b.innerHTML = ICON[t.id];
        b.title = t.title;
        b.addEventListener("click", (ev) => {
          // The header toggles collapse on click — a control click must not
          // also fold the card away under the cursor.
          ev.stopPropagation();
          ev.preventDefault();
          show();
          // No is-busy guard: all four kinds are local until Submit (see the
          // matching comment in subunits.js's unit-strip click handler).
          if (t.id === "comment") onHoverAction(block, "comment", ev);
          else window.AnnotateSubunits?.toggleBlockMark(block.dataset.blockId, t.id);
        });
        wrap.appendChild(b);
      }
      // Directly after the title, not at the far right of the header: the
      // title is what reveals the strip, and a trigger 600px from the thing
      // it reveals reads as nothing happening.
      titleEl.insertAdjacentElement("afterend", wrap);
    });
  }

  function applyEngagedStyling() {
    document.querySelectorAll("[data-block-id][data-engaged-type]").forEach(b => {
      delete b.dataset.engagedType;
    });
    for (const a of Object.values(annotations)) {
      if (!a.block_id) continue;
      // querySelector returns the first match in document order — the
      // <section>. For sequence diagrams, the SVG <g class="step-row">
      // children also carry data-block-id, so an explicit second query is
      // needed to flag the specific step that has the draft.
      const block = document.querySelector(`[data-block-id="${cssEsc(a.block_id)}"]`);
      if (block) block.dataset.engagedType = a.type;
      if (a.step_id) {
        const step = document.querySelector(
          `[data-block-id="${cssEsc(a.block_id)}"][data-step-id="${cssEsc(a.step_id)}"]`
        );
        if (step) step.dataset.engagedType = a.type;
      }
    }
  }

  function closestBlock(node) {
    let n = node;
    while (n && n.nodeType !== 1) n = n.parentNode;
    while (n && !n.dataset?.blockId) n = n.parentElement;
    return n;
  }

  function occurrences(haystack, needle) {
    if (!needle) return 0;
    let n = 0, i = 0;
    while ((i = haystack.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
    return n;
  }

  function blockSnippet(blockId) {
    if (!blockId) return "";
    const block = document.querySelector(`[data-block-id="${cssEsc(blockId)}"]`);
    if (!block) return "";
    const clone = block.cloneNode(true);
    for (const ha of clone.querySelectorAll(".hover-actions")) ha.remove();
    const text = (clone.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    return text.length > 60 ? text.slice(0, 59).trimEnd() + "…" : text;
  }

  function onHoverAction(block, type, event) {
    const sel = window.getSelection();
    let selectedText = "";
    if (sel && !sel.isCollapsed) {
      const range = sel.getRangeAt(0);
      const startBlock = closestBlock(range.startContainer);
      if (startBlock === block) {
        selectedText = sel.toString().split("\n")[0];
      }
    }
    // Sub-unit lookup: prefer the closest data-step-id/data-node-id (used by
    // the diagram and flowchart renderers respectively) and otherwise fall
    // back to data-annotate-id (the convention Claude uses inside free-HTML
    // markdown blocks). Both step and node scopes share the annotation
    // schema's step_id field — no separate node_id field is needed.
    let stepId = null;
    const stepNode = event?.target?.closest("[data-step-id],[data-node-id]");
    if (stepNode && block.contains(stepNode)) {
      stepId = stepNode.dataset.stepId || stepNode.dataset.nodeId;
    } else {
      const annotNode = event?.target?.closest("[data-annotate-id]");
      if (annotNode && block.contains(annotNode)) {
        stepId = annotNode.dataset.annotateId;
      }
    }
    openAnnotation(block, type, { stepId, selectedText, selection: sel });
  }

  // Open (or reuse) the inline comment editor for a block (optionally scoped to
  // a sub-unit by stepId). Shared by hover-strip DOM clicks (which derive
  // stepId from the event) and mockup iframe clicks (where a data-annotate-id
  // slug is forwarded via postMessage). `selection`, when given, is cleared
  // once the draft is created.
  function openAnnotation(block, type, opts) {
    opts = opts || {};
    const stepId = opts.stepId != null ? opts.stepId : null;
    const selectedText = opts.selectedText || "";
    const sel = opts.selection || null;
    // Single input per target: if a draft already exists for this
    // (block, step), reuse it instead of stacking a second card, keeping any
    // text already typed. There is no longer a comment↔reject intent switch —
    // disagreement is a checkbox on the one card, because both outcomes keep
    // the content and both make Claude rewrite it.
    const blockId = block.dataset.blockId;
    const norm = (s) => (s == null ? null : s);
    const existingId = Object.keys(annotations).find((k) => {
      const x = annotations[k];
      return x.block_id === blockId && norm(x.step_id) === norm(stepId);
    });

    // Single-flight: refuse to open a second editor while one is already open
    // for a different target. Not gated on BUSY — the editor pins its
    // comment into the local round via AnnotateSubunits.pinComment(), which
    // never touches the network, so an in-flight round is not a reason to
    // refuse opening it.
    if (!existingId && Object.keys(annotations).length > 0) return;

    const id = existingId || `a-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const annot = annotations[id] || { block_id: blockId, step_id: stepId, comment: "" };
    annot.type = type;
    // A fresh selection re-scopes the card; otherwise keep the existing scope.
    if (selectedText) {
      annot.selected_text = selectedText;
      const blockText = block.textContent;
      delete annot.prefix;
      delete annot.suffix;
      if (occurrences(blockText, selectedText) > 1) {
        const idx = blockText.indexOf(selectedText);
        annot.prefix = blockText.slice(Math.max(0, idx - 20), idx);
        annot.suffix = blockText.slice(idx + selectedText.length, idx + selectedText.length + 20);
      }
    } else if (!existingId) {
      annot.selected_text = "";
    }
    annotations[id] = annot;
    saveDrafts();
    renderComments();
    applyEngagedStyling();
    if (sel) sel.removeAllRanges();
    focusComment(id);
  }

  // ── Block loading and rendering ────────────────────────────────────────────

  // Syntax-highlight fenced code via highlight.js. Returning a full
  // `<pre><code class="hljs …">` makes markdown-it use it verbatim (it only
  // wraps when the hook returns a non-<pre> string), so `code.hljs` gets the
  // theme background from code-theme.css. hljs.highlight() HTML-escapes its
  // input; an empty return falls back to markdown-it's own escaped rendering
  // (e.g. if highlight.min.js failed to load).
  function highlightFence(str, lang) {
    if (typeof window.hljs !== "object" || !window.hljs) return "";
    let inner;
    try {
      if (lang && hljs.getLanguage(lang)) {
        inner = hljs.highlight(str, { language: lang, ignoreIllegals: true }).value;
      } else if (str.length > 20000) {
        return ""; // skip ~35-grammar auto-detect on a huge untagged fence
      } else {
        inner = hljs.highlightAuto(str).value; // Claude often omits the lang tag
      }
    } catch (_) {
      return "";
    }
    const cls = "hljs" + (lang ? " language-" + lang.replace(/[^\w-]/g, "") : "");
    return '<pre><code class="' + cls + '">' + inner + "</code></pre>";
  }

  const blockMd = (typeof window.markdownit === "function")
    ? window.markdownit({ html: true, linkify: true, typographer: false,
                          breaks: false, highlight: highlightFence })
    : null;

  // Conservative sanitizer for HTML that lands in a block via markdown-it
  // (now html: true so Claude can emit free-form HTML).  Threat model is
  // "defend against accidents", not a hostile author — Claude is the only
  // writer of blocks.json — but we strip the obvious script/handler vectors
  // so a broken response can't break the page.
  const SAN_DISALLOWED_TAGS = new Set([
    "SCRIPT", "IFRAME", "OBJECT", "EMBED", "LINK", "META", "STYLE", "BASE", "FORM",
  ]);
  function sanitizeFreeHtml(root) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    const toRemove = [];
    let node;
    while ((node = walker.nextNode())) {
      // tagName is uppercase for HTML elements but lowercase for SVG
      // descendants (different namespace) — normalise before checking
      // so `<svg><script>` is caught the same as a top-level `<script>`.
      if (SAN_DISALLOWED_TAGS.has(node.tagName.toUpperCase())) {
        toRemove.push(node);
        continue;
      }
      for (const attr of [...node.attributes]) {
        const name = attr.name.toLowerCase();
        if (name.startsWith("on")) {
          node.removeAttribute(attr.name);
          continue;
        }
        if ((name === "href" || name === "src" || name === "xlink:href") &&
            /^\s*javascript:/i.test(attr.value)) {
          node.removeAttribute(attr.name);
        }
      }
    }
    for (const n of toRemove) n.remove();
  }

  async function loadAndRenderBlocks() {
    if (!proseEl || !blockMd) return;
    let data;
    try {
      const r = await fetch(BASE + "raw", { cache: "no-store" });
      if (!r.ok) return;
      data = await r.json();
    } catch (_) {
      return;
    }
    if (window.AnnotateGlossary) {
      window.AnnotateGlossary.setGlossary(data.glossary || []);
      // Seed the poll-loop's change-detector so the first tick doesn't see
      // undefined→[...] and fire a needless refreshAll() that collapses any
      // in-progress text selection.
      window.AnnotateGlossary._lastGlossary = data.glossary || [];
    }
    proseEl.replaceChildren();
    for (const blk of (data.blocks || [])) {
      const section = createBlockSection(blk);
      proseEl.appendChild(section);
    }
    renderHoverActions();
    renderComments();
    applyEngagedStyling();
    renderMapRail();
    renderDiscoverHint();
  }

  // Header title for a block's card. Claude may author a `title`; otherwise we
  // derive one from the content (first heading, else first sentence/line).
  function blockTitle(blk) {
    if (blk.title && String(blk.title).trim()) return String(blk.title).trim();
    const k = blk.kind || "markdown";
    if (k === "sequence" || k === "diagram") {
      const t = blk.spec && blk.spec.title;
      return (t && String(t).trim()) || "Diagram";
    }
    if ((blk.kind || "markdown") === "choice") {
      const q = blk.spec && blk.spec.question;
      return (q && String(q).trim()) || "Decision";
    }
    const md = blk.markdown || "";
    const heading = md.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/m);
    let t = heading
      ? heading[1]
      : (md.split(/\n/).map(s => s.replace(/^[#>*\-\s`]+/, "").trim()).find(Boolean) || "");
    t = t.replace(/[*_`]/g, "").replace(/\s+/g, " ").trim();
    if (t.length > 60) t = t.slice(0, 59).trimEnd() + "…";
    return t || "Section";
  }

  function setCardTitle(section, blk) {
    const el = section.querySelector(".card-title");
    if (el) el.textContent = blockTitle(blk);
  }

  // Render a choice block's interactive body: question, radio/checkbox
  // options, and a Submit button. On submit, POST the selection and show the
  // same "updating" overlay the comment path uses.
  function renderChoice(section, content, blk) {
    const spec = blk.spec || {};
    const multi = !!spec.multiSelect;
    const options = Array.isArray(spec.options) ? spec.options : [];
    const groupName = `choice-${blk.id}`;

    const wrap = document.createElement("div");
    wrap.className = "choice-block";

    // The question is shown in the card header (derived from spec.question by
    // blockTitle) — don't repeat it in the body.

    const list = document.createElement("div");
    list.className = "choice-options";
    const inputs = [];
    for (const opt of options) {
      const row = document.createElement("label");
      row.className = "choice-option";
      const input = document.createElement("input");
      input.type = multi ? "checkbox" : "radio";
      input.name = groupName;
      input.value = opt.id;
      inputs.push(input);
      const textWrap = document.createElement("span");
      textWrap.className = "choice-option-text";
      const label = document.createElement("span");
      label.className = "choice-option-label";
      label.textContent = opt.label || opt.id;
      textWrap.appendChild(label);
      if (opt.description) {
        const desc = document.createElement("span");
        desc.className = "choice-option-desc";
        desc.textContent = opt.description;
        textWrap.appendChild(desc);
      }
      row.append(input, textWrap);
      list.appendChild(row);
    }
    wrap.appendChild(list);

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "choice-submit-btn";
    submitBtn.textContent = "Submit";
    submitBtn.disabled = true;
    const refreshDisabled = () => {
      submitBtn.disabled = !inputs.some(i => i.checked);
    };
    inputs.forEach(i => i.addEventListener("change", refreshDisabled));

    submitBtn.addEventListener("click", () => {
      const selected = inputs.filter(i => i.checked).map(i => i.value);
      if (!selected.length) return;
      submitBtn.disabled = true;
      const payload = {
        block_id: blk.id,
        step_id: null,
        type: "choice",
        selected_options: selected,
        text: "",
        selected_text: "",
        images: [],
      };
      WebCompanion.api.submit(payload).then((res) => {
        const eventId = res && res.event_id;
        if (eventId) pendingEvents.set(String(eventId), { blockId: blk.id });
        startUpdatingOverlay(section);
      }).catch(() => {
        refreshDisabled();
      });
    });
    wrap.appendChild(submitBtn);
    content.appendChild(wrap);
  }

  // ── Mockup kind: full-fidelity HTML in a sandboxed iframe ───────────────────
  // Live registry of mockup iframes, so the single boot-level message handler
  // can match an inbound postMessage to the iframe that sent it by object
  // identity. The frame's origin is the string "null" and must NOT be trusted.
  const mockupFrames = new Set();

  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || (d.type !== "annotate:height" && d.type !== "annotate:click")) return;
    // Authenticate by object identity: a sandboxed srcdoc frame's origin is the
    // string "null" and must NOT be trusted. Find which still-connected mockup
    // iframe actually sent this message.
    let target = null;
    for (const f of Array.from(mockupFrames)) {
      if (!f.isConnected) { mockupFrames.delete(f); continue; }  // prune stale
      if (f.contentWindow === ev.source) target = f;             // identity gate
    }
    if (!target) return;
    if (d.type === "annotate:height") {
      const h = Number(d.h);
      if (!Number.isFinite(h)) return;                           // ignore garbage
      target.style.height = Math.min(Math.max(h, 20), 20000) + "px"; // clamp
      return;
    }
    // annotate:click — a click on a [data-annotate-id] region inside the mock.
    // Opens a comment scoped to that slug, reusing the whole free-HTML contract.
    if (typeof d.id !== "string" || !d.id.trim() || d.id.length > 256) return;
    const section = target.closest("section.block");
    if (section) openAnnotation(section, "comment", { stepId: d.id });
  });

  const MOCKUP_CSP =
    '<meta http-equiv="Content-Security-Policy" content="' +
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; " +
    "script-src 'unsafe-inline'; font-src data:; connect-src 'none'; " +
    "form-action 'none'; base-uri 'none'\">";

  // Trusted, host-injected. (1) Reports content height up so the host can size
  // the iframe (on observe, DOMContentLoaded, load, and late <img> loads).
  // (2) Forwards clicks on [data-annotate-id] regions up to the host so it can
  // open a comment scoped to that sub-unit — iframe clicks don't bubble out.
  const MOCKUP_BRIDGE =
    "<scr" + "ipt>(function(){function p(){parent.postMessage(" +
    "{type:'annotate:height',h:document.documentElement.scrollHeight},'*');}" +
    "try{new ResizeObserver(p).observe(document.documentElement);}catch(e){}" +
    "document.addEventListener('DOMContentLoaded',p);" +
    "window.addEventListener('load',p,true);" +
    "document.addEventListener('click',function(e){" +
    "var el=e.target&&e.target.closest&&e.target.closest('[data-annotate-id]');" +
    "if(el)parent.postMessage({type:'annotate:click'," +
    "id:el.getAttribute('data-annotate-id')},'*');});" +
    "p();})();</scr" + "ipt>";

  // Drop any mockup iframes under `root` from the registry before the node is
  // detached, so the Set never holds stale frames between message sweeps.
  function untrackMockupFrames(root) {
    root.querySelectorAll("iframe.mockup-frame").forEach((f) => mockupFrames.delete(f));
  }

  function renderMockup(content, blk) {
    const html = (blk.spec && blk.spec.html) || "";
    if (!html) {
      content.innerHTML = '<div class="mockup-missing">mockup unavailable</div>';
      return;
    }
    const iframe = document.createElement("iframe");
    iframe.className = "mockup-frame";
    iframe.setAttribute("sandbox", "allow-scripts");   // NEVER allow-same-origin
    iframe.setAttribute("scrolling", "no");
    iframe.style.height = "60px";                       // placeholder until bridge reports
    iframe.srcdoc =
      '<!DOCTYPE html><html><head><meta charset="utf-8">' + MOCKUP_CSP +
      "<style>html,body{margin:0;padding:0}</style></head><body>" +
      html + MOCKUP_BRIDGE + "</body></html>";
    mockupFrames.add(iframe);
    content.appendChild(iframe);
  }

  function createBlockSection(blk) {
    const section = document.createElement("section");
    section.className = "block card";
    section.dataset.blockId = blk.id;
    section.dataset.version = String(blk.version ?? 1);
    const kind = blk.kind || "markdown";
    section.dataset.kind = kind;

    // Card header: collapse chevron + title (+ version chip, added by
    // renderVersionBadge). Clicking the header toggles the body.
    const head = document.createElement("div");
    head.className = "card-head";
    const chev = document.createElement("button");
    chev.type = "button";
    chev.className = "card-chevron";
    chev.setAttribute("aria-label", "Collapse section");
    chev.textContent = "▾";
    const title = document.createElement("span");
    title.className = "card-title";
    title.textContent = blockTitle(blk);
    const spacer = document.createElement("span");
    spacer.className = "card-head-spacer";
    head.append(chev, title, spacer);
    section.appendChild(head);

    const body = document.createElement("div");
    body.className = "card-body";
    const content = document.createElement("div");
    content.className = "block-content";
    if (kind === "sequence") {
      // Server pre-rendered the SVG; inject as-is.
      content.innerHTML = blk.svg || "";
      // Diagram blocks skip the hover-actions strip (it would overlap the
      // chart). Instead any click inside the SVG opens a comment scoped to
      // the step that was clicked; onHoverAction extracts step_id from
      // event.target.closest("[data-step-id]"). Listener lives on content
      // so updateBlockContent's innerHTML swap doesn't drop it.
      content.addEventListener("click", (ev) => {
        onHoverAction(section, "comment", ev);
      });
    } else if (kind === "diagram") {
      // Server pre-rendered the Mermaid SVG; inject as-is. This is trusted
      // server output and deliberately bypasses sanitizeFreeHtml so Mermaid's
      // inline <style> survives. v1 has no per-node hit targets, so there is
      // no step-click listener — whole-diagram comments come from the
      // hover-actions strip (renderHoverActions does not skip "diagram").
      content.innerHTML = blk.svg || "";
    } else if (kind === "flowchart") {
      // Server pre-rendered the hand-built SVG; inject as-is — trusted
      // server output, deliberately bypasses sanitizeFreeHtml so the
      // class/data-* hit targets survive.
      content.innerHTML = blk.svg || "";
      // Any click inside the SVG either follows an in-page cross-block
      // anchor (href="#<block-id>") by smooth-scrolling to that block, or
      // opens a comment scoped to the node that was clicked; onHoverAction
      // extracts the scope id from event.target.closest via data-step-id or
      // data-node-id. Listener lives on content so updateBlockContent's
      // innerHTML swap doesn't drop it.
      content.addEventListener("click", (ev) => {
        const anchor = ev.target.closest && ev.target.closest("a[href]");
        if (anchor) {
          const href = anchor.getAttribute("href");
          if (href.startsWith("#")) {
            ev.preventDefault();
            const targetId = href.slice(1);
            const target = document.querySelector(
              `[data-block-id="${cssEsc(targetId)}"]`
            );
            if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
          }
          // Any other anchor (e.g. a jetbrains:// code-ref link) is left to
          // navigate normally — never also open a node comment on top of it.
          return;
        }
        onHoverAction(section, "comment", ev);
      });
    } else if (kind === "choice") {
      renderChoice(section, content, blk);
    } else if (kind === "mockup") {
      // Trusted Claude HTML in a sandboxed iframe; deliberately bypasses
      // sanitizeFreeHtml (the sandbox is the isolation boundary instead).
      renderMockup(content, blk);
    } else {
      // Markdown path — markdown-it now allows inline HTML (`html: true`);
      // sanitize the rendered tree before glossary decoration.
      content.innerHTML = blockMd ? blockMd.render(blk.markdown || "") : (blk.markdown || "");
      sanitizeFreeHtml(content);
      if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
      if (window.AnnotateSubunits) window.AnnotateSubunits.decorate(content, section);
    }
    body.appendChild(content);
    section.appendChild(body);

    renderVersionBadge(section, blk.version ?? 1);
    setupCollapse(section, head, chev, blk);
    return section;
  }

  function collapseKey(blockId) {
    const rid = (document.body.dataset.responseId || "default");
    return `annotate.collapsed:${rid}:${blockId}`;
  }

  function setupCollapse(section, head, chev, blk) {
    let collapsed = false;
    try { collapsed = localStorage.getItem(collapseKey(blk.id)) === "1"; } catch (_) {}
    applyCollapsed(section, chev, collapsed);
    // Only the chevron collapses. The rest of the header carries the title
    // (a hover trigger) and the control strip, so a click anywhere else used
    // to fold the card away under the pointer that was reaching for it.
    chev.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const next = !section.classList.contains("collapsed");
      applyCollapsed(section, chev, next);
      try { localStorage.setItem(collapseKey(blk.id), next ? "1" : "0"); } catch (_) {}
    });
  }

  function applyCollapsed(section, chev, collapsed) {
    section.classList.toggle("collapsed", collapsed);
    if (chev) {
      chev.textContent = collapsed ? "▸" : "▾";
      chev.setAttribute("aria-label", collapsed ? "Expand section" : "Collapse section");
    }
  }

  function renderVersionBadge(section, version) {
    // Composite gutter pill: left = section number (parsed from the block id,
    // e.g. "section-3" → 3), right = version. Always visible; the version half
    // lights up accent only once the block has been rewritten (v > 1).
    const v = Math.max(1, parseInt(version, 10) || 1);
    const idMatch = String(section.dataset.blockId || "").match(/(\d+)$/);
    const sectionNo = idMatch ? idMatch[1] : "·";
    let pill = section.querySelector(".section-pill");
    if (!pill) {
      pill = document.createElement("span");
      pill.className = "section-pill";
      const sec = document.createElement("span");
      sec.className = "sp-sec";
      const ver = document.createElement("span");
      ver.className = "sp-ver";
      pill.append(sec, ver);
      (section.querySelector(".card-head") || section).appendChild(pill);
    }
    pill.querySelector(".sp-sec").textContent = sectionNo;
    pill.querySelector(".sp-ver").textContent = `v${v}`;
    pill.classList.toggle("bumped", v > 1);
    pill.title = v > 1 ? `Section ${sectionNo} · rewritten (v${v})` : `Section ${sectionNo}`;
  }

  // ── Comment cards ──────────────────────────────────────────────────────────

  // Resolve a diagram step (or free-HTML sub-unit) to its row node, display
  // label, and 1-based ordinal — so a comment card can name the row it targets.
  function stepContextFor(blockId, stepId) {
    if (!blockId || !stepId) return null;
    const section = document.querySelector(`section.block[data-block-id="${cssEsc(blockId)}"]`);
    if (!section) return null;
    let node = section.querySelector(`[data-step-id="${cssEsc(stepId)}"]`);
    let ordinal = null;
    if (node) {
      ordinal = [...section.querySelectorAll("[data-step-id]")].indexOf(node) + 1;
    } else {
      node = section.querySelector(`[data-annotate-id="${cssEsc(stepId)}"]`);
    }
    if (!node) return null;
    const labelNode = node.querySelector ? node.querySelector(".arrow-label") : null;
    let label = ((labelNode ? labelNode.textContent : node.textContent) || "")
      .replace(/\s+/g, " ").trim();
    if (label.length > 48) label = label.slice(0, 47).trimEnd() + "…";
    return { node, ordinal, label };
  }

  // Add the "updating" spinner overlay + timer to a block section. Idempotent:
  // a section already overlaid is left alone. Mirrors the inline logic the
  // comment-submit path uses.
  function startUpdatingOverlay(section) {
    if (!section) return;
    section.classList.add("is-updating");
    if (section.querySelector(".updating-overlay")) return;
    const overlay = document.createElement("div");
    overlay.className = "updating-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    const pill = document.createElement("div");
    pill.className = "updating-pill";
    const spinner = document.createElement("span");
    spinner.className = "updating-spinner";
    pill.appendChild(spinner);
    const label = document.createElement("span");
    label.className = "updating-label";
    label.textContent = "updating";
    pill.appendChild(label);
    const timer = document.createElement("span");
    timer.className = "updating-timer";
    timer.textContent = "0:00";
    pill.appendChild(timer);
    overlay.appendChild(pill);
    section.appendChild(overlay);
    const startedAt = Date.now();
    section._updatingTimerId = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      const m = Math.floor(elapsed / 60);
      const s = String(elapsed % 60).padStart(2, "0");
      timer.textContent = `${m}:${s}`;
    }, 1000);
  }

  function buildCard(id, a, onSubmitCb) {
    const card = document.createElement("div");
    card.className = "comment-card";
    card.dataset.id = id;
    card.dataset.type = a.type;

    // For diagram-row / sub-unit comments, head the card with the step it
    // targets, and wire a focus/hover link that highlights the matching row.
    const stepCtx = a.step_id ? stepContextFor(a.block_id, a.step_id) : null;

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "card-close";
    closeBtn.dataset.type = a.type;
    closeBtn.title = "Remove";
    closeBtn.setAttribute("aria-label", "Remove annotation");
    closeBtn.textContent = "×";
    closeBtn.addEventListener("click", () => {
      delete annotations[id];
      saveDrafts();
      renderComments();
      applyEngagedStyling();
    });
    card.appendChild(closeBtn);

    if (a.step_id) {
      const head = document.createElement("div");
      head.className = "card-step-head";
      const chip = document.createElement("span");
      chip.className = "card-step-chip";
      chip.textContent = stepCtx && stepCtx.ordinal ? `STEP ${stepCtx.ordinal}` : a.step_id;
      head.appendChild(chip);
      if (stepCtx && stepCtx.label) {
        const lbl = document.createElement("span");
        lbl.className = "card-step-label";
        lbl.textContent = stepCtx.label;
        head.appendChild(lbl);
      }
      card.appendChild(head);

      // Card ↔ row link: focusing or hovering the card lights up its row.
      const row = stepCtx && stepCtx.node;
      if (row) {
        const on = () => { row.dataset.cardFocus = "1"; };
        const off = () => { delete row.dataset.cardFocus; };
        card.addEventListener("mouseenter", on);
        card.addEventListener("mouseleave", off);
        card.addEventListener("focusin", on);
        card.addEventListener("focusout", off);
      }
    }

    if (a.selected_text) {
      const quote = document.createElement("div");
      quote.className = "quote";
      quote.dataset.type = a.type;
      quote.textContent = a.selected_text;
      card.appendChild(quote);
    }

    const wrap = document.createElement("div");
    wrap.className = "editor-wrap";

    const ta = document.createElement("textarea");
    const pasteState = {
      pastes: (annotations[id].images || []).map(img => ({
        token: img.token,
        path: img.path,
        thumbUrl: null,
      })),
      nextIndex: ((annotations[id].images || []).length) + 1,
    };

    const pasteStrip = document.createElement("div");
    pasteStrip.className = "paste-strip";
    if (pasteState.pastes.length === 0) pasteStrip.dataset.empty = "1";

    function renderStrip() {
      pasteStrip.replaceChildren();
      if (pasteState.pastes.length === 0) {
        pasteStrip.dataset.empty = "1";
        return;
      }
      delete pasteStrip.dataset.empty;
      for (const p of pasteState.pastes) {
        const tile = document.createElement("div");
        tile.className = "paste-thumb";
        tile.dataset.token = p.token;
        const img = document.createElement("img");
        img.alt = p.token;
        if (p.thumbUrl) img.src = p.thumbUrl;
        else tile.classList.add("no-thumb");
        const label = document.createElement("span");
        label.className = "paste-label";
        label.textContent = p.token;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "paste-remove";
        remove.title = "Remove";
        remove.textContent = "×";
        remove.addEventListener("click", (ev) => {
          ev.stopPropagation();
          pasteState.pastes = pasteState.pastes.filter(x => x.token !== p.token);
          persistImages();
          renderStrip();
        });
        tile.appendChild(img);
        tile.appendChild(label);
        tile.appendChild(remove);
        pasteStrip.appendChild(tile);
      }
    }

    function persistImages() {
      if (pasteState.pastes.length === 0) {
        delete annotations[id].images;
      } else {
        annotations[id].images = pasteState.pastes.map(p => ({ token: p.token, path: p.path }));
      }
      saveDrafts();
    }

    const placeholder = PLACEHOLDER_TEXT[a.type] || PLACEHOLDER_TEXT.comment;
    ta.placeholder = placeholder;
    ta.value = a.comment || "";
    ta.addEventListener("input", () => {
      annotations[id].comment = ta.value;
      saveDrafts();
      autoGrow();
    });

    const autoGrow = () => {
      if (wrap.dataset.userSized === "1") return;
      ta.style.height = "auto";
      const cap = Math.max(160, Math.round(window.innerHeight * 0.5));
      ta.style.height = Math.min(ta.scrollHeight + 2, cap) + "px";
    };

    ta.addEventListener("focus", autoGrow);

    const handle = document.createElement("div");
    handle.className = "editor-resize";
    handle.title = "Drag to resize · double-click to reset";
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = ta.offsetHeight;
      handle.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const newH = Math.max(60, startH + (ev.clientY - startY));
        ta.style.height = newH + "px";
        wrap.dataset.userSized = "1";
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      // pointercancel fires if capture is lost (e.g. the card is replaced by a
      // poll-driven update mid-drag); without this the move listener would leak
      // on a detached node, pinning the textarea/wrap closures.
      handle.addEventListener("pointercancel", up);
    });
    handle.addEventListener("dblclick", () => {
      delete wrap.dataset.userSized;
      ta.style.height = "";
      autoGrow();
    });

    wrap.appendChild(ta);
    wrap.appendChild(handle);
    card.appendChild(wrap);
    card.appendChild(pasteStrip);
    renderStrip();
    // Auto-grow once on initial render so a card with prior content shows it all.
    queueMicrotask(autoGrow);

    // ── Stance + Add button ────────────────────────────────────────────────
    // "I disagree" is a flag on the comment rather than a separate control:
    // both keep the content and both make Claude rewrite it, and the only
    // real difference is whether Claude may treat the note as agreement.
    const stanceRow = document.createElement("label");
    stanceRow.className = "card-stance";
    const stanceBox = document.createElement("input");
    stanceBox.type = "checkbox";
    stanceBox.checked = !!annotations[id]?.disagree;
    stanceBox.addEventListener("change", () => {
      annotations[id].disagree = stanceBox.checked;
      saveDrafts();
    });
    stanceRow.append(stanceBox, document.createTextNode(" I disagree with this"));
    card.appendChild(stanceRow);

    const submitRow = document.createElement("div");
    submitRow.className = "card-submit-row";
    const hint = document.createElement("span");
    hint.className = "card-submit-hint";
    // The button pins into the round; nothing is sent until the round dock's
    // Submit, so the label must not promise delivery.
    hint.innerHTML = '<kbd>⌘</kbd><kbd>↩</kbd> to add · paste an image to attach';
    submitRow.appendChild(hint);
    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "card-submit-btn";
    submitBtn.textContent = "Add to round";
    // ⌘/Ctrl+Enter submits from the textarea.
    ta.addEventListener("keydown", (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
        ev.preventDefault();
        if (!submitBtn.disabled) submitBtn.click();
      }
    });
    submitBtn.addEventListener("click", () => {
      const text = annotations[id]?.comment || "";
      const images = annotations[id]?.images || [];
      if (!text.trim()) return;
      // Pin into the review round instead of submitting. Nothing wakes Claude
      // until the round dock's Submit — one timing model for every piece of
      // content feedback, so a click never has an invisible "this one sends
      // now" exception.
      window.AnnotateSubunits?.pinComment({
        block_id: a.block_id,
        step_id: a.step_id ?? null,
        text,
        disagree: !!annotations[id]?.disagree,
        images,
        selected_text: a.selected_text || "",
        prefix: a.prefix,
        suffix: a.suffix,
      });
      delete annotations[id];
      saveDrafts();
      document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
      card.remove();
      applyEngagedStyling();
    });
    submitRow.appendChild(submitBtn);
    card.appendChild(submitRow);

    // ── Image paste ────────────────────────────────────────────────────────
    ta.addEventListener("paste", async (ev) => {
      const items = ev.clipboardData?.items;
      if (!items) return;
      let imageItem = null;
      for (const it of items) {
        if (it.kind === "file" && it.type.startsWith("image/")) { imageItem = it; break; }
      }
      if (!imageItem) return;
      ev.preventDefault();
      const blob = imageItem.getAsFile();
      if (!blob) return;
      const token = `paste-${pasteState.nextIndex++}`;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const insertion = `![${token}]`;
      ta.value = ta.value.slice(0, start) + insertion + ta.value.slice(end);
      const caret = start + insertion.length;
      ta.setSelectionRange(caret, caret);
      annotations[id].comment = ta.value;
      saveDrafts();
      try {
        const result = await WebCompanion.api.pasteImage(blob);
        pasteState.pastes.push({ token, path: result.path, thumbUrl: URL.createObjectURL(blob) });
        persistImages();
        renderStrip();
      } catch (_) {
        showPasteError("upload failed");
      }
    });

    let errorChipTimer = null;
    function showPasteError(msg) {
      let chip = pasteStrip.querySelector(".paste-error");
      if (!chip) {
        chip = document.createElement("span");
        chip.className = "paste-error";
        pasteStrip.appendChild(chip);
      }
      chip.textContent = msg;
      if (errorChipTimer) clearTimeout(errorChipTimer);
      errorChipTimer = setTimeout(() => { chip.remove(); errorChipTimer = null; }, 4000);
    }

    return card;
  }

  function renderComments() {
    // Prune orphan drafts: a block-scoped draft whose block no longer exists
    // (Claude removed it) can never render its card — and thus can never be
    // closed — so it would linger in localStorage forever. Also drop any
    // legacy block_id-null drafts from the retired general-comments UI; the
    // page-level composer no longer renders cards for them.
    let pruned = false;
    for (const [id, a] of Object.entries(annotations)) {
      if (!a.block_id ||
          !document.querySelector(`section.block[data-block-id="${cssEsc(a.block_id)}"]`)) {
        delete annotations[id];
        pruned = true;
      }
    }
    if (pruned) saveDrafts();

    document.querySelectorAll(".inline-comments").forEach(el => el.remove());

    const byBlock = {};
    for (const [id, a] of Object.entries(annotations)) {
      (byBlock[a.block_id] ||= []).push([id, a]);
    }

    for (const [blockId, items] of Object.entries(byBlock)) {
      // Insert after the <section.block> that wraps the block.
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(blockId)}"]`);
      if (!section) continue;
      const wrap = document.createElement("div");
      wrap.className = "inline-comments";
      wrap.dataset.forBlock = blockId;
      for (const [id, a] of items) wrap.appendChild(buildCard(id, a));
      section.insertAdjacentElement("afterend", wrap);
    }

    // EDITING lock: any open comment card means one editor is active.
    document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
  }

  function focusComment(id) {
    const card = document.querySelector(`.comment-card[data-id="${id}"]`);
    if (!card) return;
    const ta = card.querySelector("textarea");
    if (ta) ta.focus({ preventScroll: true });
  }

  // ── Done button ────────────────────────────────────────────────────────────

  const doneBtn = document.getElementById("done-btn");
  if (doneBtn) {
    doneBtn.addEventListener("click", async () => {
      if (!window.confirm("Mark this annotation round as done? Claude will resume.")) return;
      doneBtn.disabled = true;
      const ok = await WebCompanion.api.finish();
      if (ok) {
        window.location.reload();
      } else {
        doneBtn.disabled = false;
      }
    });
  }

  // ── General composer (page-level, non-block comment) ────────────────────────
  // A persistent textarea that sends a block_id-null comment straight to Claude
  // Code. Unlike block comments it leaves no inline card; status is reported in
  // the composer's own status line and resolved when Claude acks the event.
  (function initGeneralComposer() {
    const input = document.getElementById("general-input");
    const sendBtn = document.getElementById("general-send");
    const statusEl = document.getElementById("general-status");
    if (!input || !sendBtn) return;

    const KEY = `annotate.general.${document.body.dataset.responseId || ""}`;
    try { input.value = localStorage.getItem(KEY) || ""; } catch {}

    const sync = () => {
      sendBtn.disabled = input.value.trim() === "";
      try { localStorage.setItem(KEY, input.value); } catch {}
    };
    sync();

    function send() {
      const text = input.value.trim();
      if (!text) return;
      sendBtn.disabled = true;
      const payload = { block_id: null, step_id: null, type: "comment", text, selected_text: "", images: [] };
      WebCompanion.api.submit(payload).then((res) => {
        const eventId = res && res.event_id;
        if (eventId) pendingEvents.set(String(eventId), { general: true });
        input.value = "";
        try { localStorage.removeItem(KEY); } catch {}
        sync();
        // The server queues events, so a send while Claude is mid-update is
        // safe — but say so, instead of implying an immediate response.
        if (statusEl) {
          statusEl.textContent = document.body.classList.contains("is-busy")
            ? "queued — Claude will get to it after the current update…"
            : "sent — Claude is responding…";
        }
      }).catch(() => {
        sendBtn.disabled = false;
        if (statusEl) statusEl.textContent = "send failed — try again";
      });
    }

    input.addEventListener("input", sync);
    // Same chord as the block cards: Enter is a newline, ⌘/Ctrl+Enter sends.
    // Plain-Enter-to-send once cost a user a multi-line answer mid-compose.
    input.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); send(); }
    });
    sendBtn.addEventListener("click", send);
  })();

  // ── Collapsed general composer ───────────────────────────────────────────
  // The composer used to open as a full textarea above the fold — the least-
  // used input holding the most valuable space. It now starts collapsed to a
  // single trigger row; opening it is one click (or the `g` shortcut) away.
  (function initComposerCollapse() {
    const openBtn = document.getElementById("composer-open");
    const section = document.querySelector(".general-composer");
    if (!openBtn || !section) return;
    function open() {
      section.hidden = false;
      openBtn.hidden = true;
      document.getElementById("general-input")?.focus();
    }
    openBtn.addEventListener("click", open);
    document.addEventListener("keydown", (e) => {
      if (e.key !== "g" && e.key !== "G") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active && active.isContentEditable);
      if (typing) return;
      if (openBtn.hidden) return;
      e.preventDefault();
      open();
    });
  })();

  // ── First-run discovery hint ─────────────────────────────────────────────
  // Every marking control is hover-only and the legend starts collapsed, so a
  // first-time reader sees a static document and never learns the page is
  // interactive. Shown once per response, dismissal remembered in
  // localStorage so it doesn't nag on every visit.
  function renderDiscoverHint() {
    const key = "annotate.hint." + (document.body.dataset.responseId || "");
    try { if (localStorage.getItem(key)) return; } catch { return; }
    if (!proseEl) return;
    const hint = document.createElement("div");
    hint.className = "discover-hint";
    const glyphs = document.createElement("span");
    glyphs.className = "dh-glyphs";
    for (const g of ["🗑", "✓", "💬"]) {
      const s = document.createElement("span"); s.textContent = g; glyphs.appendChild(s);
    }
    const eye = document.createElement("span");
    eye.innerHTML = window.AnnotateSubunits?.COMPACT_ICON || "";
    glyphs.appendChild(eye);
    const txt = document.createElement("span");
    txt.textContent = "Hover any sentence to mark it. Marks batch up — nothing reaches Claude until you submit.";
    const x = document.createElement("button");
    x.type = "button"; x.className = "dh-x"; x.textContent = "×";
    x.title = "Dismiss";
    x.addEventListener("click", () => {
      try { localStorage.setItem(key, "1"); } catch {}
      hint.remove();
    });
    hint.append(glyphs, txt, x);
    proseEl.parentNode?.insertBefore(hint, proseEl);
  }

  // ── Document map rail ─────────────────────────────────────────────────────
  // A long plan has no shape without it: fuzzy search finds a section you
  // already know exists, this orients you in one you don't. Rebuilt (not
  // patched) on every call, so it can never accumulate stale entries or
  // listeners across re-renders — the elements it rebuilds are fresh each
  // time, so binding click handlers on them each call is safe; nothing is
  // ever attached to the rail element itself or to `document` here.
  function renderMapRail() {
    if (!proseEl) return;
    let rail = document.getElementById("map-rail");
    if (!rail) {
      rail = document.createElement("nav");
      rail.id = "map-rail";
      rail.className = "map-rail";
      // main.prose starts as a lone, self-centering child of <body> (see
      // style.css). Wrap it and the rail in a shared flex shell exactly
      // once — later calls find `rail` above and skip this whole branch,
      // so the shell is never duplicated across re-renders.
      const shell = document.createElement("div");
      shell.className = "reading-shell";
      proseEl.parentNode?.insertBefore(shell, proseEl);
      shell.appendChild(rail);
      shell.appendChild(proseEl);
    }
    const sections = [...document.querySelectorAll("section.block[data-block-id]")];
    const frag = document.createDocumentFragment();
    const head = document.createElement("div");
    head.className = "map-rail-head";
    const h1 = document.createElement("span"); h1.textContent = "Document";
    const h2 = document.createElement("span");
    h2.className = "map-count";
    h2.textContent = `${sections.length} section${sections.length === 1 ? "" : "s"}`;
    head.append(h1, h2);
    frag.appendChild(head);
    sections.forEach((s, i) => {
      const item = document.createElement("div");
      item.className = "map-item";
      const n = document.createElement("span");
      n.className = "map-n"; n.textContent = String(i + 1);
      const t = document.createElement("span");
      t.className = "map-t";
      // Section titles are Claude-authored content — textContent only, never
      // innerHTML, so an authored title can never inject markup here.
      t.textContent = s.querySelector(".card-title")?.textContent || s.dataset.blockId;
      const dots = document.createElement("span");
      dots.className = "map-dots";
      // One dot per distinct mark kind pending in this section, plus one for
      // a section changed by the last round.
      const kinds = new Set();
      s.querySelectorAll(".sub-unit[data-mark]").forEach(u => kinds.add(u.dataset.mark));
      if (s.dataset.blockMark) kinds.add(s.dataset.blockMark);
      for (const k of kinds) {
        const d = document.createElement("span");
        d.className = "map-dot d-" + k;
        dots.appendChild(d);
      }
      if (s.dataset.diff !== undefined && s.querySelector(".attr-chip")) {
        const d = document.createElement("span");
        d.className = "map-dot " + (s.querySelector(".a-sweep") ? "d-swept" : "d-changed");
        dots.appendChild(d);
      }
      item.append(n, t, dots);
      item.addEventListener("click", () =>
        s.scrollIntoView({ behavior: "smooth", block: "start" }));
      frag.appendChild(item);
    });
    rail.replaceChildren(frag);
  }

  // ── Polling / block refresh ────────────────────────────────────────────────

  function clearUpdatingOverlay(section) {
    section.classList.remove("is-updating");
    if (section._updatingTimerId) {
      clearInterval(section._updatingTimerId);
      section._updatingTimerId = null;
    }
    section.querySelector(".updating-overlay")?.remove();
  }

  // Clear the "updating" UI for every comment whose event Claude has acked.
  // This is the real done-signal: it fires whether Claude answered by
  // rewriting the commented block, a neighbour, a new block, or nothing —
  // none of which the old "same-block version bump" check could detect.
  function handleConsumedEvents(consumed) {
    if (!Array.isArray(consumed) || pendingEvents.size === 0) return;
    for (const eid of consumed) {
      const key = String(eid);
      const pend = pendingEvents.get(key);
      if (!pend) continue;
      pendingEvents.delete(key);
      if (pend.blockId) {
        const section = document.querySelector(`section.block[data-block-id="${cssEsc(pend.blockId)}"]`);
        if (section) clearUpdatingOverlay(section);
      } else if (pend.general) {
        const statusEl = document.getElementById("general-status");
        if (statusEl) statusEl.textContent = "responded";
      }
    }
  }

  // Caption the spinner with the live label the PostToolUse hook published
  // for each in-flight event ("Reading files…", "Editing the response…").
  // No entry → the label stays "updating". The label is one of a fixed
  // server-side allowlist, so nothing sensitive can land here.
  function applyProgress(progress) {
    if (!progress || pendingEvents.size === 0) return;
    for (const [eid, pend] of pendingEvents) {
      const label = progress[eid];
      if (!label) continue;
      if (pend.blockId) {
        const section = document.querySelector(
          `section.block[data-block-id="${cssEsc(pend.blockId)}"]`);
        const el = section && section.querySelector(".updating-label");
        if (el) el.textContent = label;
      }
      if (pend.round) {
        const b = document.getElementById("busy-banner");
        if (b) {
          const el = b.querySelector(".bb-label");
          if (el && label) el.textContent = label;
        }
        continue;
      }
      if (pend.general) {
        const statusEl = document.getElementById("general-status");
        if (statusEl) statusEl.textContent = label;
      }
    }
  }

  // Ticking timer for the busy banner's .bb-timer, started when the banner
  // is created and cleared when it's removed.
  let busyTimer = null;

  // Server-authoritative page lock. `data.busy` is true while any submitted
  // event is unacked; reflect it as body.is-busy + a banner. Survives reload
  // and is consistent across devices because it is recomputed each poll.
  function setBusy(busy) {
    document.body.classList.toggle("is-busy", !!busy);
    let banner = document.getElementById("busy-banner");
    if (busy) {
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "busy-banner";
        banner.className = "busy-banner";
        banner.setAttribute("role", "status");
        banner.setAttribute("aria-live", "polite");
        const spin = document.createElement("span");
        spin.className = "busy-spinner";
        const label = document.createElement("span");
        label.className = "bb-label";
        label.textContent = "Claude is applying your round…";
        const sub = document.createElement("span");
        sub.className = "bb-sub";
        const timer = document.createElement("span");
        timer.className = "bb-timer";
        banner.append(spin, label, sub, timer);
        banner.dataset.startedAt = String(Date.now());
        // Place the lock ribbon at the top of the content (just under the
        // header, above the composer) so it pins flush to the top of the
        // screen when the page scrolls — not buried below the composer.
        const header = document.querySelector(".page-header");
        if (header) header.insertAdjacentElement("afterend", banner);
        else (document.querySelector(".general-composer") || proseEl)
          ?.parentNode?.insertBefore(banner, document.querySelector(".general-composer") || proseEl);
      }
      if (!busyTimer) {
        busyTimer = setInterval(() => {
          const b = document.getElementById("busy-banner");
          if (!b) return;
          const t = Math.floor((Date.now() - Number(b.dataset.startedAt || Date.now())) / 1000);
          const el = b.querySelector(".bb-timer");
          if (el) el.textContent = `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
        }, 1000);
      }
    } else if (banner) {
      if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
      banner.remove();
    }
  }

  // ── Statusline strip ───────────────────────────────────────────────────
  // Live mirror of the terminal statusline (context %, model, rate limits,
  // diff, cost), polled alongside the document. Source is /statusline, which
  // the server reads from a per-session snapshot statusline.sh writes each
  // render. Rebuilds only when the payload actually changes.
  let lastStatuslineJSON = null;

  function slTone(p) { return p >= 75 ? "tone-hot" : p >= 50 ? "tone-warn" : "tone-ok"; }

  function slFmtTok(n) {
    if (n >= 1e6) { const m = n / 1e6; return (m % 1 === 0 ? m : m.toFixed(1)) + "M"; }
    if (n >= 1000) { const k = n / 1000; return (n < 10000 ? k.toFixed(1) : Math.round(k)) + "k"; }
    return String(n);
  }

  function buildStatstrip(data) {
    const strip = document.getElementById("statstrip");
    if (!strip) return;
    if (!data || !data.ok) { strip.hidden = true; strip.replaceChildren(); return; }

    const frag = document.createDocumentFragment();
    const seg = (cls) => { const s = document.createElement("span"); s.className = "sl-seg" + (cls ? " " + cls : ""); return s; };
    const lbl = (t) => { const e = document.createElement("span"); e.className = "sl-lbl"; e.textContent = t; return e; };
    const val = (t) => { const e = document.createElement("span"); e.className = "sl-val"; e.textContent = t; return e; };

    if (data.context) {
      const c = data.context, s = seg(slTone(c.pct));
      const dot = document.createElement("span"); dot.className = "sl-dot";
      const bar = document.createElement("span"); bar.className = "sl-bar";
      const fill = document.createElement("i"); fill.style.width = Math.min(100, Math.max(0, c.pct)) + "%"; bar.appendChild(fill);
      const sub = document.createElement("span"); sub.className = "sl-sub"; sub.textContent = slFmtTok(c.used) + " / " + slFmtTok(c.total);
      s.append(dot, lbl("context"), bar, val(c.pct + "%"), sub);
      frag.appendChild(s);
    }
    if (data.model) {
      const s = seg();
      const m = document.createElement("span"); m.className = "sl-model"; m.textContent = data.model.label;
      s.append(lbl("model"), m);
      if (data.model.badge) { const b = document.createElement("span"); b.className = "sl-badge"; b.textContent = data.model.badge; s.appendChild(b); }
      frag.appendChild(s);
    }

    const spacer = document.createElement("span"); spacer.className = "sl-spacer"; frag.appendChild(spacer);

    if (data.rate_limits) {
      for (const [key, short] of [["five_hour", "5h"], ["seven_day", "7d"]]) {
        const p = data.rate_limits[key];
        if (typeof p === "number") {
          const s = seg(slTone(p));
          const dot = document.createElement("span"); dot.className = "sl-dot";
          s.append(dot, lbl(short), val(p + "%"));
          frag.appendChild(s);
        }
      }
    }
    if (data.diff && (typeof data.diff.added === "number" || typeof data.diff.removed === "number")) {
      const s = seg(); s.appendChild(lbl("diff"));
      if (typeof data.diff.added === "number") { const a = document.createElement("span"); a.className = "sl-add"; a.textContent = "+" + slFmtTok(data.diff.added); s.appendChild(a); }
      if (typeof data.diff.removed === "number") { const d = document.createElement("span"); d.className = "sl-del"; d.textContent = "−" + slFmtTok(data.diff.removed); s.appendChild(d); }
      frag.appendChild(s);
    }

    strip.replaceChildren(frag);
    strip.hidden = false;
  }

  function refreshStatusline() {
    fetch(BASE + "statusline", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const j = JSON.stringify(data);
        if (j === lastStatuslineJSON) return;
        lastStatuslineJSON = j;
        buildStatstrip(data);
      })
      .catch(() => { /* swallow — next tick retries */ });
  }

  // A heartbeat older than this means the watcher (and the Claude session
  // that owns it) is dead, not slow — the watcher writes every ~1s, including
  // while it blocks on an ack.
  const WATCHER_DEAD_AFTER_S = 15;

  // The session behind this page died mid-event (crash, closed terminal).
  // Without this, the unacked event keeps busy=true forever and the page
  // stays locked with a spinner that lies. Show the truth and unlock.
  function setWatcherDead(dead) {
    let banner = document.getElementById("watcher-dead-banner");
    if (dead) {
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "watcher-dead-banner";
        banner.className = "watcher-dead-banner";
        banner.setAttribute("role", "alert");
        banner.setAttribute("aria-live", "assertive");
        const label = document.createElement("span");
        label.textContent =
          "Claude's session is gone — your last submission was not processed. " +
          "Re-run annotate from a Claude session to pick this page back up.";
        banner.append(label);
        const header = document.querySelector(".page-header");
        if (header) header.insertAdjacentElement("afterend", banner);
        else document.body.insertBefore(banner, document.body.firstChild);
      }
    } else if (banner) {
      banner.remove();
    }
  }

  // Advisory-only: more than one live Claude session (watcher) is heartbeating
  // on this workspace at once — e.g. two terminals reopened the same slug.
  // Purely informational, doesn't gate anything the way setBusy/setWatcherDead
  // do. The pill lives in the header title and is created once, then just
  // toggled — unlike the busy/watcher-dead banners it isn't inserted/removed
  // per poll.
  function setAttachedPill(count) {
    let pill = document.getElementById("attached-pill");
    if (!pill) {
      const title = document.querySelector(".header-title");
      if (!title) return; // header not rendered (yet); try again next poll
      pill = document.createElement("span");
      pill.id = "attached-pill";
      pill.className = "attached-pill";
      title.appendChild(pill);
    }
    const show = typeof count === "number" && count > 1;
    pill.textContent = show ? `${count} sessions attached` : "";
    pill.classList.toggle("show", show);
  }

  // ── What changed, and who changed it ───────────────────────────────────────
  //
  // When a round is acked the page grows a bar reading
  //   "<n> sections changed — <a> you marked, <b> by the coherence sweep"
  // and every changed card grows an attribution chip plus a "what changed"
  // word diff against the pre-round snapshot (GET <base>/prev, Task 1).
  //
  // Attribution is DERIVED, never reported: any block whose version bumped
  // that was NOT in the round this client submitted was moved by the sweep.
  // Nothing on the wire has to tell us that, so nothing can drift or lie.

  // Per-block versions as they stood when the current round was submitted.
  // Sourced from the `lastVersions` map core.js already threads into this
  // callback — a second version ledger kept here is exactly how the
  // attribution would start lying — and captured at the busy false→true edge,
  // the same instant the server writes blocks.prev.json. So the bar, the
  // chips, and the diff all describe one moment.
  let roundBaseVersions = null;
  let wasBusy = false;
  // Set on the ack, consumed after the next reconcile: the diff needs the
  // post-round markdown from /raw and the refreshed sections in the DOM.
  let pendingChangeSet = null;

  // Which blocks moved, and who moved them. The user's own set is whatever
  // they submitted — captured at submit time in subunits.js, because
  // clearRound() wipes the marks on ack and this is the only surviving
  // record. Everything else that moved was the coherence sweep.
  function computeChangeSet(prevVersions, nextVersions) {
    const asked = new Set(window.AnnotateSubunits?.submittedBlockIds?.() || []);
    const changed = [];
    for (const [bid, v] of Object.entries(nextVersions || {})) {
      const before = prevVersions ? prevVersions[bid] : undefined;
      if (before !== undefined && v > before) {
        changed.push({ blockId: bid, bySweep: !asked.has(bid), from: before });
      }
    }
    return changed;
  }

  function renderChangeBar(changed) {
    document.getElementById("change-bar")?.remove();
    if (!changed.length) return;
    const swept = changed.filter(c => c.bySweep).length;
    const asked = changed.length - swept;
    const bar = document.createElement("div");
    bar.id = "change-bar";
    bar.className = "change-bar";
    bar.setAttribute("role", "status");
    const dot = document.createElement("span");
    dot.className = "cb-dot";
    const txt = document.createElement("span");
    const parts = [];
    if (asked) parts.push(`${asked} you marked`);
    if (swept) parts.push(`${swept} by the coherence sweep`);
    txt.innerHTML = `<b>${changed.length} section${changed.length > 1 ? "s" : ""} changed</b>`
      + (parts.length ? ` — <span class="cb-split">${parts.join(", ")}</span>` : "");
    const nav = document.createElement("span");
    nav.className = "cb-nav";
    let idx = -1;
    const go = (d) => {
      if (!changed.length) return;
      idx = (idx + d + changed.length) % changed.length;
      document.querySelector(
        `section.block[data-block-id="${cssEsc(changed[idx].blockId)}"]`
      )?.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    for (const [label, d] of [["↑ prev", -1], ["next ↓", 1]]) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.addEventListener("click", () => go(d));
      nav.appendChild(b);
    }
    const dis = document.createElement("button");
    dis.type = "button"; dis.textContent = "dismiss";
    dis.addEventListener("click", () => bar.remove());
    nav.appendChild(dis);
    bar.append(dot, txt, nav);
    const header = document.querySelector(".page-header");
    if (header) header.insertAdjacentElement("afterend", bar);
  }

  // Wipe last round's verdict. Called when the next round starts, so a card
  // can never carry attribution earned two rounds ago.
  function clearChangeAttribution() {
    // Drop the un-applied set too, not just the painted DOM. Otherwise: the
    // ack poll's /raw fetch fails, the set survives, and round 2's busy edge
    // clears the cards and then hands round 1's set to the very next /raw —
    // chips and a pane appear mid-round, labelled with round-1 versions but
    // diffed against round 2's snapshot, and they sit there until round 3.
    pendingChangeSet = null;
    document.getElementById("change-bar")?.remove();
    document.querySelectorAll("section.block").forEach(section => {
      section.querySelector(".attr-chip")?.remove();
      section.querySelector(".card-diff-toggle")?.remove();
      section.querySelector(".diff-pane")?.remove();
      delete section.dataset.diff;
    });
  }

  function markChangedCard(section, c) {
    const head = section.querySelector(".card-head");
    if (!head) return;
    head.querySelector(".attr-chip")?.remove();
    head.querySelector(".card-diff-toggle")?.remove();
    const chip = document.createElement("span");
    chip.className = "attr-chip " + (c.bySweep ? "a-sweep" : "a-you");
    chip.textContent = c.bySweep ? "sweep" : "you asked";
    chip.title = c.bySweep
      ? "Rewritten by the coherence sweep — you did not mark this section"
      : "Rewritten because you marked it in this round";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "card-diff-toggle";
    toggle.textContent = "what changed";
    toggle.setAttribute("aria-pressed", "false");
    toggle.addEventListener("click", (ev) => {
      // The header carries the collapse chevron and the control strip; don't
      // let a diff toggle also trip whatever else listens up there.
      ev.stopPropagation();
      const open = section.dataset.diff === "open";
      section.dataset.diff = open ? "" : "open";
      toggle.setAttribute("aria-pressed", open ? "false" : "true");
    });
    const pill = head.querySelector(".section-pill");
    if (pill) {
      head.insertBefore(chip, pill);
      head.insertBefore(toggle, pill);
    } else {
      head.append(chip, toggle);
    }
  }

  // Cells of the LCS table we are willing to allocate. The table is
  // (n+1)·(m+1) Uint32s, so 2,000,000 cells is ~8 MB and a couple of
  // milliseconds. Tokens are word-plus-separator, so the cap bites at roughly
  // 700 words per side — above a typical prose block, below the long code
  // listings and wide tables Claude sometimes writes. Uncapped, a 2000-word
  // block asks for ~61 MB and a 4000-word one for ~244 MB, and applyChangeSet
  // runs this over every changed block so the peaks stack into a frozen tab
  // or a RangeError.
  const DIFF_MAX_CELLS = 2000000;

  // Word-level LCS. Small documents, runs once per changed block, so an
  // O(n·m) table is fine and keeps the whole thing dependency-free.
  function wordDiff(a, b) {
    const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
    const n = A.length, m = B.length;
    // Too big to align word by word. Fall back to one whole-text replacement:
    // it loses the "which words moved" precision the pane exists for, but it
    // is still a correct description of the change and it always renders.
    if (n * m > DIFF_MAX_CELLS) return [["-", a], ["+", b]];
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1
                                 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { out.push(["=", A[i]]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(["-", A[i]]); i++; }
      else { out.push(["+", B[j]]); j++; }
    }
    while (i < n) out.push(["-", A[i++]]);
    while (j < m) out.push(["+", B[j++]]);
    return out;
  }

  // Recognised change_note line labels, in the order the contract documents
  // them (see references/handling-events.md § "Explaining a change").
  const CHANGE_NOTE_LABELS = ["Why:", "Lost:"];

  // Block markdown is arbitrary user-and-model text, so every run is a text
  // node inside its element. Never string-concatenated into innerHTML.
  function renderDiffPane(section, c, blk, before) {
    section.querySelector(".diff-pane")?.remove();
    const now = blk.markdown || "";
    if (now === before) return;
    const pane = document.createElement("div");
    pane.className = "diff-pane";
    const h = document.createElement("div");
    h.className = "diff-h";
    h.textContent = `changed from v${c.from}`
      + (c.bySweep ? " — you did not mark this section" : "");
    pane.appendChild(h);
    const p = document.createElement("p");
    for (const [op, token] of wordDiff(before, now)) {
      const el = document.createElement(op === "-" ? "del" : op === "+" ? "ins" : "span");
      el.appendChild(document.createTextNode(token));
      p.appendChild(el);
    }
    pane.appendChild(p);
    // Task 5's per-block change note: free-form text Claude may attach to a
    // rewrite, optionally carrying a `Why:` line and — for a compact that
    // dropped detail — a `Lost:` line. Render each line of the note on its
    // own row rather than as one blob: a fixed leading label here would
    // double up against a note that already starts with "Why:", and folding
    // a `Lost:` line into the same paragraph buries the one place a user can
    // ever learn what a compact discarded. The field is optional and
    // free-form, so this must still render sensibly with no recognised
    // label, extra blank lines, or only a `Why:` line.
    if (typeof blk.change_note === "string" && blk.change_note.trim()) {
      const why = document.createElement("div");
      why.className = "diff-why";
      for (const rawLine of blk.change_note.trim().split("\n")) {
        const line = rawLine.trim();
        if (!line) continue;
        const row = document.createElement("div");
        row.className = "diff-why-line";
        const label = CHANGE_NOTE_LABELS.find(l => line.startsWith(l));
        if (label) {
          row.classList.add(label === "Lost:" ? "diff-lost" : "diff-reason");
          const lbl = document.createElement("b");
          lbl.textContent = label + " ";
          row.append(lbl, document.createTextNode(line.slice(label.length).trim()));
        } else {
          row.appendChild(document.createTextNode(line));
        }
        why.appendChild(row);
      }
      pane.appendChild(why);
    }
    const body = section.querySelector(".card-body");
    if (body) body.insertAdjacentElement("afterend", pane);
    else section.appendChild(pane);
  }

  // The pre-round snapshot: the document as it stood when the round was
  // queued, which is the only record of what a block used to say. Read-only
  // route (GET <base>/prev), so it works on a shared read-only link too.
  async function loadPrev() {
    try {
      const r = await fetch(BASE + "prev", { cache: "no-store" });
      if (!r.ok) return null;
      const d = await r.json();
      return d && d.ok ? d.blocks : null;
    } catch { return null; }
  }

  async function applyChangeSet(changed, doc) {
    renderChangeBar(changed);
    const byId = new Map((doc.blocks || []).map(b => [b.id, b]));
    const prev = await loadPrev();
    for (const c of changed) {
      // Per block, so one pathological block (a diff that still blows up
      // despite the cell cap) costs its own pane and nothing else's.
      try {
        const section = document.querySelector(
          `section.block[data-block-id="${cssEsc(c.blockId)}"]`);
        if (!section) continue;
        markChangedCard(section, c);
        const blk = byId.get(c.blockId);
        const before = prev ? prev[c.blockId] : null;
        // No snapshot (first round on an old session, or a non-markdown block)
        // means no diff — the chip and the bar still stand on their own.
        if (blk && typeof before === "string") renderDiffPane(section, c, blk, before);
      } catch (e) {
        console.warn("diff failed for block", c.blockId, e);
      }
    }
    // markChangedCard just painted the attr-chips the rail's changed/swept
    // dots read — refresh after, not before, or the rail lags one round
    // behind what the cards themselves show.
    renderMapRail();
  }

  function onPollDelta(data, lastVersions) {
    const watcherDead = typeof data.watcher_age_s === "number"
      && data.watcher_age_s > WATCHER_DEAD_AFTER_S;
    setWatcherDead(watcherDead);
    // A dead watcher means no ack is ever coming — don't keep the page
    // locked on its behalf.
    const busyNow = !!(data.busy && !watcherDead);
    if (busyNow && !wasBusy) {
      // A new round just started: last round's verdict is stale now.
      clearChangeAttribution();
      roundBaseVersions = lastVersions ? { ...lastVersions } : null;
    } else if (!busyNow && wasBusy) {
      const changed = computeChangeSet(roundBaseVersions, data.blocks);
      roundBaseVersions = null;
      if (changed.length) pendingChangeSet = changed;
    }
    wasBusy = busyNow;
    setBusy(busyNow);
    setAttachedPill(data.attached);
    refreshStatusline();
    // 1. Clear spinners for comments Claude finished processing.
    handleConsumedEvents(data.consumed_events);
    // 1b. Caption any still-running spinner with the live progress label.
    applyProgress(data.progress);
    if (window.AnnotateSubunits) window.AnnotateSubunits.onPoll(data);
    // 2. Reconcile the DOM against the full document. /raw carries everything
    //    (per-block markdown/svg + version + glossary), so one fetch covers
    //    structure, content, and glossary in a single pass.
    fetch(BASE + "raw", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null)
      .then(doc => {
        if (!doc) return;
        reconcile(doc);
        syncGlossary(doc);
        // Attribution lands only after reconcile: the chips hang off the
        // refreshed sections (a kind flip rebuilds the whole card) and the
        // diff needs this doc's post-round markdown.
        if (pendingChangeSet) {
          const changed = pendingChangeSet;
          pendingChangeSet = null;
          // Not chained into the outer .catch: it is a floating promise, so
          // without this a throw becomes an unhandled rejection. The bar and
          // the panes that did render stay put.
          applyChangeSet(changed, doc)
            .catch(e => console.warn("change attribution failed", e));
        }
      })
      .catch(() => { /* swallow — next tick retries */ });
  }

  function syncGlossary(doc) {
    if (!window.AnnotateGlossary) return;
    const prev = JSON.stringify(window.AnnotateGlossary._lastGlossary || []);
    const next = JSON.stringify(doc.glossary || []);
    if (next !== prev) {
      window.AnnotateGlossary.setGlossary(doc.glossary || []);
      window.AnnotateGlossary._lastGlossary = doc.glossary || [];
      window.AnnotateGlossary.refreshAll();
    }
  }

  // Bring the rendered block list in line with the server document: insert
  // newly-added blocks (in order), drop removed ones, and refresh blocks whose
  // version bumped. Surgical on purpose — it touches comment wrappers only for
  // removed blocks, so a draft the user is mid-typing on an unchanged block is
  // never rebuilt out from under them.
  function reconcile(doc) {
    if (!proseEl) return;
    const serverBlocks = doc.blocks || [];
    const serverIds = new Set(serverBlocks.map(b => b.id));

    // Remove sections (and their inline-comments wrapper) for deleted blocks,
    // clearing any running updating-timer so it can't leak.
    proseEl.querySelectorAll("section.block").forEach(section => {
      if (!serverIds.has(section.dataset.blockId)) {
        clearUpdatingOverlay(section);
        untrackMockupFrames(section);
        const ic = section.nextElementSibling;
        if (ic && ic.classList.contains("inline-comments")) ic.remove();
        section.remove();
      }
    });

    // Walk server order; insert missing blocks at the right spot, refresh
    // version-bumped ones. `anchor` trails the last placed section (past its
    // comment wrapper) so an inserted block lands in document order.
    let anchor = null;
    for (const blk of serverBlocks) {
      let section = proseEl.querySelector(`section.block[data-block-id="${cssEsc(blk.id)}"]`);
      if (!section) {
        section = createBlockSection(blk);
        if (anchor) anchor.insertAdjacentElement("afterend", section);
        else proseEl.insertBefore(section, proseEl.firstChild);
      } else {
        const domVer = parseInt(section.dataset.version || "1", 10);
        const srvVer = parseInt(blk.version, 10) || 1;
        if (srvVer > domVer) section = updateBlockContent(section, blk, srvVer);
      }
      const ic = section.nextElementSibling;
      anchor = (ic && ic.classList.contains("inline-comments")) ? ic : section;
    }

    renderHoverActions();
    applyEngagedStyling();
    renderMapRail();
  }

  // Refresh one block's content in place. Returns the section now in the DOM
  // (a fresh node when the block's kind flipped). Clears the updating overlay
  // as a fallback for the case where the refreshed block IS the commented one.
  function updateBlockContent(section, blk, srvVer) {
    const newKind = blk.kind || "markdown";
    const oldKind = section.dataset.kind || "markdown";
    // A kind flip (markdown↔sequence/diagram/choice) needs a fresh section:
    // the diagram click listener and hover wiring are bound at creation, so an
    // in-place innerHTML swap would leave them inconsistent with the new kind.
    if (newKind !== oldKind || newKind === "choice" || newKind === "mockup") {
      const fresh = createBlockSection(blk);
      clearUpdatingOverlay(section);
      untrackMockupFrames(section);
      section.replaceWith(fresh);
      return fresh;
    }
    const content = section.querySelector(".block-content");
    if (content) {
      if (newKind === "sequence" || newKind === "diagram") {
        content.innerHTML = blk.svg || "";
      } else if (blockMd) {
        content.innerHTML = blockMd.render(blk.markdown || "");
        sanitizeFreeHtml(content);
        if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
        if (window.AnnotateSubunits) window.AnnotateSubunits.decorate(content, section);
      }
    }
    section.dataset.kind = newKind;
    section.dataset.version = String(blk.version ?? srvVer);
    renderVersionBadge(section, blk.version ?? srvVer);
    setCardTitle(section, blk);
    clearUpdatingOverlay(section);
    return section;
  }

  // ── Boot ───────────────────────────────────────────────────────────────────

  // subunits.js owns the round; script.js owns the poll loop and the progress
  // map. The round has to land in pendingEvents or applyProgress skips it —
  // that omission is why round progress was computed and discarded.
  window.AnnotatePage = {
    // subunits.js funnels every mark mutation through its own renderDock(),
    // and calls this from there — one hook, so the rail never drifts out of
    // sync with pending marks without a listener on every click handler
    // that can change a mark.
    onMarkChange: renderMapRail,
    registerRoundEvent(eventId, blockIds) {
      if (!eventId) return;
      pendingEvents.set(String(eventId), {
        round: true,
        blockIds: Array.isArray(blockIds) ? blockIds.slice() : [],
      });
    },
  };

  WebCompanion.init({ onPollDelta });
  loadAndRenderBlocks();
})();
