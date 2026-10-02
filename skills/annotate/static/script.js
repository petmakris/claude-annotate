// annotate skill — client-side incremental rendering and per-block submission
(function () {
  // Base path of the page, e.g. "/" or "/s/<sid>/". Relative fetches use this.
  const BASE = (() => {
    const p = window.location.pathname;
    return p.endsWith("/") ? p : p + "/";
  })();

  // The slug (or sid) this page is served under — "/s/<key>/" — which the server
  // resolves either way. Empty on the index, which renders no code panes.
  // A hue from a name, stable forever. djb2 over the code units, folded to a
  // degree — no randomness and no counter, so "benzene" is the same colour in
  // every pane of every page, which is the only property that makes the tint
  // worth having. Saturation and lightness stay with the theme (see .cp-proj
  // in style.css); only the hue travels, so a dark theme is not handed a pale
  // pill it cannot paint text on.
  // A curated wheel rather than `hash % 360`, and the reason is a real result:
  // taking the hash straight to a degree put `app-worktrees` on hue 14
  // and the skills repository (under its old name) on hue 15. One degree apart reads as a
  // rendering fault, not as two projects — the worst outcome, because it is
  // neither "the same" nor "different". Landing on a fixed set of separated
  // hues means two projects are either plainly distinct or exactly equal, and
  // an honest collision is easier to live with than a near-miss.
  const PILL_HUES = [210, 145, 25, 275, 190, 45, 330, 95, 250, 5, 165, 300, 65, 230];
  const hueFromName = (name) => {
    let h = 5381;
    for (let i = 0; i < name.length; i++) h = ((h * 33) ^ name.charCodeAt(i)) >>> 0;
    return PILL_HUES[h % PILL_HUES.length];
  };

  // Inline SVG rather than a glyph font or an emoji: the header is 11px and
  // needs to line up with text, and an icon that inherits `currentColor`
  // recolours itself with the theme instead of needing one rule per theme.
  const icon = (paths, label) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "13");
    svg.setAttribute("height", "13");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.6");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    paths.forEach(d => {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    });
    if (label) svg.setAttribute("data-icon", label);
    return svg;
  };
  const ICON_OPEN   = ["M13.5 8.5v4a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h4",
                       "M9.5 2.5h4v4", "M7 9l6.5-6.5"];

  const workspaceKey = () => {
    const m = BASE.match(/^\/s\/([^/]+)\//);
    return m ? decodeURIComponent(m[1]) : "";
  };

  const proseEl = document.querySelector("main.prose");
  // `let`: a new response in the same session moves the drafts to a new key.
  let STORAGE_KEY = `annotate.drafts.${document.body.dataset.responseId || ""}`;

  // Pending rounds, drafts and unsent general comments are kept per response
  // or per session, and every response ever opened used to leave its keys
  // behind for good. Each write stamps its key here; a key not written for
  // STALE_AFTER_MS is removed on the next load of any annotate page. Keys from
  // before the stamps existed are stamped the first time they are seen, so
  // they are retired on the same clock rather than all at once today.
  window.AnnotateStorage = (() => {
    const INDEX = "annotate.touched";
    const STALE_AFTER_MS = 30 * 24 * 3600 * 1000;
    const SWEPT = /^annotate\.(round|drafts|general|inflight)\./;
    // Collapse, per-response view and highlighter state. Written on every
    // click and never stamped, so these age by the last time their RESPONSE
    // was opened, kept in OPENED. Global settings (`annotate.view:<name>`,
    // one colon) do not match and are never swept.
    const PER_RESPONSE =
      /^annotate\.(view|read|collapsed|flavour|flowview):([^:]+):/;
    // Keys nothing reads any more, removed on sight: the old diagram-choice
    // keys (one per block id, shared by every document); the per-pane widen
    // state and the code-pane layout, from when a pane could sit beside the
    // prose; the prose font, from when there was more than one; and the
    // pre-rename page width, whose every value is narrower than Normal now.
    const RETIRED = new RegExp([
      "^annotate\\.(flavour|view)\\.[^:]+$",
      "^annotate\\.codewide:",
      "^annotate\\.view:prosefont$",
      "^annotate\\.view:[^:]+:codelayout$",
      "^annotate\\.view:[^:]+:width$",
    ].join("|"));
    const OPENED = "annotate.opened";
    const read = () => {
      try { return JSON.parse(localStorage.getItem(INDEX) || "{}") || {}; }
      catch (_) { return {}; }
    };
    const write = (idx) => {
      try { localStorage.setItem(INDEX, JSON.stringify(idx)); } catch (_) {}
    };
    function touch(key) {
      const idx = read();
      idx[key] = Date.now();
      write(idx);
    }
    function sweep() {
      const idx = read();
      const now = Date.now();
      let keys = [];
      try { keys = Object.keys(localStorage); } catch (_) { return; }
      for (const key of keys) {
        if (!SWEPT.test(key)) continue;
        if (!(key in idx)) { idx[key] = now; continue; }
        if (now - idx[key] > STALE_AFTER_MS) {
          try { localStorage.removeItem(key); } catch (_) {}
          delete idx[key];
        }
      }
      for (const key of Object.keys(idx)) if (!keys.includes(key)) delete idx[key];
      write(idx);

      let opened = {};
      try { opened = JSON.parse(localStorage.getItem(OPENED) || "{}") || {}; }
      catch (_) {}
      const rid = document.body.dataset.responseId;
      if (rid) opened[rid] = now;
      for (const key of keys) {
        if (RETIRED.test(key)) {
          try { localStorage.removeItem(key); } catch (_) {}
          continue;
        }
        const m = PER_RESPONSE.exec(key);
        if (!m) continue;
        // Unknown response: its keys predate this record, so start its clock.
        if (!(m[2] in opened)) { opened[m[2]] = now; continue; }
        if (now - opened[m[2]] > STALE_AFTER_MS) {
          try { localStorage.removeItem(key); } catch (_) {}
        }
      }
      for (const r of Object.keys(opened)) {
        if (now - opened[r] > STALE_AFTER_MS) delete opened[r];
      }
      try { localStorage.setItem(OPENED, JSON.stringify(opened)); } catch (_) {}
    }
    return { touch, sweep };
  })();
  window.AnnotateStorage.sweep();

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
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      // An empty draft does not survive the session that opened it. It holds
      // nothing the reader typed — `selected_text` is scope, not content — so
      // restoring one only paints an engaged bar on a block nobody is
      // commenting on. Dropped here rather than in renderComments, which
      // cannot tell a draft that was abandoned last week from the one being
      // opened right now.
      for (const [id, a] of Object.entries(stored)) {
        if (isEmptyDraft(a)) delete stored[id];
      }
      return stored;
    } catch { return {}; }
  }

  function saveDrafts() {
    try {
      if (Object.keys(annotations).length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations));
        window.AnnotateStorage.touch(STORAGE_KEY);
      } else localStorage.removeItem(STORAGE_KEY);
    } catch {}
  }

  // ── Rendering ──────────────────────────────────────────────────────────────
  const PLACEHOLDER_TEXT = { comment: "Your comment…" };

  // A draft the user never wrote anything into. It carries no information —
  // `selected_text` is scope, not content — so it must never outlive the click
  // that made it: it paints the engaged bar on a block nobody is commenting on,
  // and because only one draft may exist at a time it also silently blocks
  // every other block from opening a comment.
  function isEmptyDraft(a) {
    return a && !(a.comment || "").trim()
        && !(a.images || []).length;
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
    const text = (clone.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    return text.length > 60 ? text.slice(0, 59).trimEnd() + "…" : text;
  }

  // Open (or reuse) the inline comment editor for a block (optionally scoped to
  // a data-annotate-id region by stepId). Shared by the selection menu and
  // mockup iframe clicks (where a data-annotate-id slug is forwarded via
  // postMessage). `selection`, when given, is cleared
  // once the draft is created.
  function openAnnotation(block, type, opts) {
    opts = opts || {};
    const stepId = opts.stepId != null ? opts.stepId : null;
    const selectedText = opts.selectedText || "";
    const sel = opts.selection || null;
    // Single input per target: if a draft already exists for this
    // (block, step), reuse it instead of stacking a second card, keeping any
    // text already typed. There is no comment↔reject intent switch: Claude
    // weighs every comment on its merits, so disagreement is just words.
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
    if (!existingId) {
      // Drop any empty draft first — otherwise a stray click on one block
      // makes every other block unclickable until its × is found and pressed.
      for (const [k, v] of Object.entries(annotations)) {
        if (isEmptyDraft(v)) delete annotations[k];
      }
      if (Object.keys(annotations).length > 0) {
        revealOpenDraft();
        return;
      }
    }

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

  // Syntax-highlight fenced code, through CodePaint (Shiki). Returning a full
  // `<pre><code class="sk-fence">` makes markdown-it use it verbatim (it only
  // wraps when the hook returns a non-<pre> string). An untagged fence, or a
  // tag no grammar claims, is shown plain on the same dark ground: Shiki does
  // not guess a language, and a guess is what used to paint prose as code.
  // An empty return falls back to markdown-it's own escaped rendering — only
  // when the highlighter itself failed to load.
  function highlightFence(str, lang) {
    if (!window.CodePaint) return "";
    const tag = String(lang || "").trim().split(/\s+/)[0];
    const painted = CodePaint.paint(str.replace(/\n$/, ""), { lang: tag });
    const inner = painted !== null ? painted
      : str.replace(/\n$/, "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const cls = "sk-fence" + (tag ? " language-" + tag.replace(/[^\w-]/g, "") : "");
    return '<pre><code class="' + cls + '">' + inner + "</code></pre>";
  }

  const blockMd = (typeof window.markdownit === "function")
    ? window.markdownit({ html: true, linkify: true, typographer: false,
                          breaks: false, highlight: highlightFence })
    : null;

  // Indented code blocks are disabled on purpose.  With html:true, Claude
  // writes free-form HTML into blocks, and readable HTML is indented — but
  // CommonMark turns any line indented 4+ spaces into a code block, so a
  // hand-formatted <div> tree renders as its own source.  A blank line makes
  // it worse: it closes the HTML block, and everything after it is indented,
  // so half a diagram silently becomes a listing.  Nothing here needs
  // indented code — every code sample we emit is fenced (see highlightFence),
  // and fences are a separate rule that stays enabled.
  if (blockMd) blockMd.disable("code");

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
    refreshPageState();
    proseEl.replaceChildren();
    for (const blk of (data.blocks || [])) {
      const section = createBlockSection(blk);
      proseEl.appendChild(section);
    }
    // A pending block mark is painted onto its section, and every section
    // above was built detached, where painting finds nothing. Paint now.
    window.AnnotateSubunits?.repaintBlocks();
    renderComments();
    applyEngagedStyling();
    document.dispatchEvent(new CustomEvent("annotate:rendered"));
  }

  // Header title for a block's card. Claude may author a `title`; otherwise we
  // derive one from the content (first heading, else first sentence/line).
  // The rule lives in block-title.js so it can be executed by a test; see the
  // header there for why a source-string check could not catch the defect it
  // fixes. entry.js loads that file before this one.
  function blockTitle(blk) {
    return window.AnnotateBlockTitle.blockTitle(blk);
  }

  function setCardTitle(section, blk) {
    const el = section.querySelector(".card-title");
    if (el) el.textContent = blockTitle(blk);
  }

  // Render a choice block's interactive body: selectable option cards and an
  // optional note field. A card click toggles selection (single-select moves
  // it). There is no Submit here: the answer is a round mark, kept in step
  // with every click and keystroke, and it goes to Claude with everything
  // else when the round dock's Submit is pressed. That is what lets one page
  // ask several questions and get all the answers back in one go. Note-only
  // means "none of these — here's my direction".
  function renderChoice(section, content, blk) {
    const spec = blk.spec || {};
    const multi = !!spec.multiSelect;
    const options = Array.isArray(spec.options) ? spec.options : [];
    // A queue is a run of choice sections sharing this; choice-queue.js reads it.
    if (typeof spec.group === "string" && spec.group.trim()) section.dataset.group = spec.group;
    else delete section.dataset.group;

    const wrap = document.createElement("div");
    wrap.className = "choice-block";

    // The question is shown in the card header (derived from spec.question by
    // blockTitle) — don't repeat it in the body.

    const list = document.createElement("div");
    list.className = "choice-options";
    list.setAttribute("role", multi ? "group" : "radiogroup");
    const titleId = section.querySelector(".card-title")?.id;
    if (titleId) list.setAttribute("aria-labelledby", titleId);
    const cards = [];
    const selected = new Set();

    const setChecked = (card, on) => {
      card.classList.toggle("selected", on);
      card.setAttribute("aria-checked", String(on));
    };
    const toggleAt = (idx, { advance = true } = {}) => {
      const opt = options[idx];
      if (selected.has(opt.id)) {
        selected.delete(opt.id);
        setChecked(cards[idx], false);
      } else {
        if (!multi) {
          selected.clear();
          cards.forEach(c => setChecked(c, false));
        }
        selected.add(opt.id);
        setChecked(cards[idx], true);
      }
      syncRoving();
      saveAnswer();
      // A pick, not a clear: the queue moves on to the next undecided question.
      // A multi-select question is not answered by its first pick, so it waits for Next.
      // Arrows pass advance:false: they move through the answers, not past the question.
      if (advance && !multi && selected.has(opt.id)) {
        document.dispatchEvent(new CustomEvent("annotate:choice-picked",
          { detail: { blockId: blk.id } }));
      }
    };
    // A single-select is a radio group, and a radio group is ONE tab stop:
    // the checked option, or the first when none is. Each option used to be
    // its own stop, so Tab walked every answer to a question on the way past
    // it. Checkboxes keep one stop each, which is what a checkbox group is.
    function syncRoving() {
      if (multi) return;
      const at = Math.max(0, options.findIndex(o => selected.has(o.id)));
      cards.forEach((c, j) => { c.tabIndex = j === at ? 0 : -1; });
    }
    // Arrows in a radio group move the selection with the focus; in a
    // checkbox group they only move the focus. A click still toggles, so a
    // single-select can be cleared by clicking its choice again.
    const arrowTo = (to) => {
      if (!multi && !selected.has(options[to].id)) toggleAt(to, { advance: false });
      cards[to].focus();
    };

    options.forEach((opt, idx) => {
      const card = document.createElement("div");
      card.className = "choice-option";
      card.tabIndex = 0;
      card.setAttribute("role", multi ? "checkbox" : "radio");
      card.setAttribute("aria-checked", "false");
      const textWrap = document.createElement("div");
      textWrap.className = "choice-option-text";
      const head = document.createElement("span");
      head.className = "choice-option-head";
      const label = document.createElement("span");
      label.className = "choice-option-label";
      label.textContent = opt.label || opt.id;
      head.appendChild(label);
      if (opt.recommended) {
        const badge = document.createElement("span");
        badge.className = "choice-badge";
        badge.textContent = "recommended";
        head.appendChild(badge);
      }
      textWrap.appendChild(head);
      if (opt.description) {
        const desc = document.createElement("span");
        desc.className = "choice-option-desc";
        desc.textContent = opt.description;
        textWrap.appendChild(desc);
      }
      // An option may carry content: code, a table, prose. It renders through
      // the same markdown-it and Shiki path as a markdown block, so a fenced
      // java sample in an option looks exactly like one in the page.
      if (typeof opt.markdown === "string" && opt.markdown.trim() && blockMd) {
        const optBody = document.createElement("div");
        optBody.className = "choice-option-body";
        optBody.id = `choice-body-${blk.id}-${opt.id}`;
        optBody.innerHTML = blockMd.render(opt.markdown);
        sanitizeFreeHtml(optBody);
        textWrap.appendChild(optBody);
        card.classList.add("has-body");
        card.setAttribute("aria-describedby", optBody.id);
      }
      card.appendChild(textWrap);
      // The body is content the reader reads and copies from. A click in it
      // that ends a selection, selects a word, or lands on a link, is not a
      // pick. The label and head always pick: they are user-select:none, so a
      // click there leaves an earlier selection standing.
      card.addEventListener("click", (e) => {
        const inBody = e.target.closest && e.target.closest(".choice-option-body");
        if (inBody) {
          if (e.target.closest("a[href]")) return;
          if (e.detail > 1) return;
          const sel = window.getSelection && window.getSelection();
          if (sel && !sel.isCollapsed) return;
        }
        toggleAt(idx);
      });
      card.addEventListener("keydown", (e) => {
        // A focused link in the body keeps its own Enter and Space.
        if (e.target !== card) return;
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          toggleAt(idx);
        } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          arrowTo((idx + 1) % cards.length);
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          arrowTo((idx - 1 + cards.length) % cards.length);
        }
      });
      cards.push(card);
      list.appendChild(card);
    });
    wrap.appendChild(list);

    // Digit shortcuts 1..9 toggle the corresponding option while focus is
    // anywhere in the block except the note field (typing digits there is
    // just typing).
    wrap.addEventListener("keydown", (e) => {
      if (e.target === note) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= options.length) {
        e.preventDefault();
        toggleAt(n - 1);
      }
    });

    const footer = document.createElement("div");
    footer.className = "choice-footer";
    const note = document.createElement("textarea");
    note.className = "choice-note";
    note.rows = 1;
    note.placeholder = "Add a note (optional) — or answer in your own words";
    // A detached textarea measures scrollHeight 0, and the block is still
    // detached on its first render, so fit only once it is on the page.
    const fitNote = () => {
      note.style.height = "auto";
      if (note.isConnected) note.style.height = note.scrollHeight + "px";
    };
    note.addEventListener("input", () => {
      fitNote();
      saveAnswer();
    });
    note.addEventListener("keydown", (e) => {
      // Cmd/Ctrl+Enter submits the round — plain Enter stays a newline, same
      // convention as the general and card composers (a note may be a
      // multi-line answer, e.g. a numbered list).
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        const btn = document.getElementById("round-submit");
        if (btn && !btn.disabled) btn.click();
      }
    });

    function saveAnswer() {
      const picked = options.filter(o => selected.has(o.id));
      // Untrimmed: the stored note is what repaints the box after a rewrite,
      // and a trimmed copy ate the newline the reader had just typed. The
      // round trims it on the way out.
      window.AnnotateSubunits?.setChoice(blk.id, picked.map(o => o.id),
        picked.map(o => o.label || o.id), note.value);
    }

    // Paint the stored answer. Runs on every render, since a poll re-renders
    // the block, and again when the dock removes the answer.
    function loadAnswer() {
      const m = window.AnnotateSubunits?.choiceMark(blk.id);
      selected.clear();
      const stored = (m && m.selected_options) || [];
      // Claude may rewrite the question with a different slate. An answer
      // naming an option that no longer exists would go out in the round
      // while no card on the page shows it picked.
      const live = new Set(options.map(o => o.id));
      for (const id of stored) if (live.has(id)) selected.add(id);
      options.forEach((o, i) => setChecked(cards[i], selected.has(o.id)));
      syncRoving();
      note.value = (m && m.text) || "";
      requestAnimationFrame(fitNote);
      if (m && selected.size !== stored.length) saveAnswer();
    }
    section.syncChoice = loadAnswer;

    footer.append(note);
    wrap.appendChild(footer);
    content.appendChild(wrap);
    loadAnswer();
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
  // open a comment scoped to that region — iframe clicks don't bubble out.
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

  // ── pflow source pane ──────────────────────────────────────────────────────

  // Highlight pflow source. An empty return means the highlighter is missing,
  // and the caller falls back to plain text rather than showing markup.
  // pflow's tags are comments to Python, so the theme paints them all one
  // comment colour; the tag comments are re-marked so the side-channel
  // (cache/gate/note/ref) reads as a channel.
  const PFLOW_TAG = /^#\s*(?:[!?]|(?:id|cache|gate|note|ref)\s*:)/;
  function highlightPflow(src) {
    if (!window.CodePaint) return "";
    const html = CodePaint.paint(src, {
      lang: "python",
      wrap: (t, text) => (PFLOW_TAG.test(t.content) ? '<span class="pflow-tag">' + text + "</span>" : text),
    });
    return html === null ? "" : html;
  }

  // ── Code anchors ───────────────────────────────────────────────────────────
  // A block's anchors, resolved by the server into real lines. The pane is a
  // reading aid: it links into the IDE and nothing inside it is a click
  // target. Comments come from the card header, the same rule the flowchart
  // source pane adopted after a `ref` that only looked like a link kept
  // opening a comment box for people reaching for a file.

  // ── Page-wide view controls ───────────────────────────────────────────
  // How wide the column is, stored per response, because a preference you
  // must re-set on every reload is worse than not having one.
  // Two stops: Normal, a 1600px column, and Wide, which has no cap and runs
  // the full width of the window less the side gutters. Code panes always
  // sit under the prose, so no stop has to make room for a second column.
  const VIEW_WIDTHS = ["normal", "wide"];
  const VIEW_LABELS = { normal: "Normal", wide: "Wide" };

  function viewKey(name) {
    const rid = (document.body.dataset.responseId || "default");
    return `annotate.view:${rid}:${name}`;
  }
  function readStored(name) {
    try { return localStorage.getItem(viewKey(name)); } catch (_) { return null; }
  }
  // Every new session opens at Normal, code or not. This used to be derived
  // from data-has-code, which made the opening measure depend on something
  // the reader never chose. One default, chosen once; anything else is the
  // reader's own click, and that is what `stored` is for.
  const DEFAULT_WIDTH = "normal";
  // `pagewidth`, not `width`: the stops have been renamed in place before,
  // and the older key's values all name columns narrower than Normal now.
  // AnnotateStorage retires that key rather than mapping it to the default.
  const WIDTH_KEY = "pagewidth";
  function effectiveWidth() {
    const stored = readStored(WIDTH_KEY);
    return VIEW_WIDTHS.indexOf(stored) >= 0 ? stored : DEFAULT_WIDTH;
  }
  // Pane themes. Daylight is the measured light palette the pane shipped
  // with; the others redeclare its variables. An unknown stored value falls
  // back rather than painting an undefined theme.
  //
  // Midnight is the default, not Daylight: the pane is a quotation from a
  // file, and a dark ground is what separates it at a glance from the prose
  // it sits under. The order of PANE_THEMES is the popover's order and says
  // nothing about which one is default — hence the named constant.
  const PANE_THEMES = ["daylight", "midnight", "contrast", "contrast-dark"];
  const DEFAULT_PANE_THEME = "midnight";
  function effectivePaneTheme() {
    const stored = readStored("panetheme");
    return PANE_THEMES.indexOf(stored) >= 0 ? stored : DEFAULT_PANE_THEME;
  }

  // ── Settings ───────────────────────────────────────────────────────────
  // One spec drives the markup, the persistence and the painting, because
  // these all used to live in the header as their own controls: a button that
  // cycled the width, a toggle for the pane layout, a popover for the theme,
  // another for the highlight colour. Four controls, none of them things a
  // reader touches twice, in a bar that also carries search, the highlighter,
  // the composer, the legend, Share and Done. They are one gear now, and the
  // bar is down from twelve controls to nine.
  //
  // `scope` is the only interesting field. "doc" keeps the choice per
  // response — a document that cites code wants a wider measure than a memo,
  // and that is a property of the document, not of the reader. "global" keeps
  // it for the reader across every document: nobody wants to choose their
  // code font again on each one.
  //
  // `attr` is the dataset key, so `width` paints data-width and `codeFont`
  // paints data-code-font. The stylesheet keys off those attributes and
  // nothing else; see the view-controls and typography blocks in style.css.
  const SETTINGS = [
    // First row, and "global": a reader who works in the dark does so in every
    // document, the same way they read in one typeface. Light is the default
    // because it is what shipped and what every existing reader already has.
    { key: "pagetheme", attr: "pageTheme", label: "Page", scope: "global",
      def: "light",
      options: [["light", "Light"], ["dark", "Dark"]] },
    { key: WIDTH_KEY, attr: "width", label: "Page width", scope: "doc",
      read: effectiveWidth,
      options: VIEW_WIDTHS.map((v) => [v, VIEW_LABELS[v]]) },
    { key: "panetheme", attr: "paneTheme", label: "Code theme", scope: "doc",
      read: effectivePaneTheme,
      // Each is a standard editor theme, used as it ships (code-paint.js).
      options: [["daylight", "Light (VS Code Light+)", "#ffffff", "#000000"],
                ["midnight", "Dark (GitHub Dark)", "#0d1117", "#e6edf3"],
                ["contrast", "High contrast light", "#ffffff", "#0e1116"],
                ["contrast-dark", "High contrast dark", "#0a0c10", "#f0f3f6"]] },
    { key: "codefont", attr: "codeFont", label: "Code font", scope: "global",
      def: "jetbrains",
      options: [["jetbrains", "JetBrains"], ["monaspace", "Monaspace"],
                ["system", "System"]] },
    { key: "textsize", attr: "textSize", label: "Reading size", scope: "global",
      def: "medium",
      options: [["small", "Small"], ["medium", "Medium"], ["large", "Large"]] },
    { key: "speechvoice", attr: "speechVoice", label: "Read-aloud voice", scope: "global",
      def: "ava",
      options: [["ava", "Ava (US)"], ["andrew", "Andrew (US)"], ["emma", "Emma (US)"],
                ["brian", "Brian (US)"], ["sonia", "Sonia (UK)"], ["ryan", "Ryan (UK)"]] },
    { key: "dictationlang", attr: "dictationLang", label: "Dictation language", scope: "global",
      def: "auto",
      options: [["auto", "Browser's"], ["en-US", "English (US)"], ["en-GB", "English (UK)"],
                ["el-GR", "Greek"], ["fr-FR", "French"]] },
  ];

  // A global setting drops the response id from the key, which is the whole
  // difference between "this document is wide" and "I read in this typeface".
  function settingKey(s) {
    return s.scope === "global" ? `annotate.view:${s.key}` : viewKey(s.key);
  }

  function settingValue(s) {
    // The two settings that predate this panel keep their own readers, which
    // carry their defaults.
    if (s.read) return s.read();
    let stored = null;
    try { stored = localStorage.getItem(settingKey(s)); } catch (_) {}
    return s.options.some(([v]) => v === stored) ? stored : s.def;
  }

  function setSetting(s, value) {
    try { localStorage.setItem(settingKey(s), value); } catch (_) {}
    applyViewControls();
  }

  // Everything the panel shows, back to its default — including the code font
  // and the reading size, which are the reader's and therefore shared with every
  // other annotate document. That is a deliberate choice and the button's
  // title says so, because nothing on screen otherwise reveals that this one
  // click reaches outside the document you are looking at.
  //
  // Removing the keys rather than writing the defaults into them keeps one
  // meaning for "unset": a stored value is a choice somebody made, and a
  // default that changes later should reach a reader who never chose.
  //
  // What it does NOT touch, all of it deliberate: the highlight MARKS
  // (annotate.read:*), which are reading work and belong to the eraser in the
  // bar; the comment drafts; and the highlighter's own on/off, which is a
  // control in the bar and not a row in this panel.
  function resetSettings() {
    for (const s of SETTINGS) {
      try { localStorage.removeItem(settingKey(s)); } catch (_) {}
    }
    try { localStorage.removeItem(viewKey("highlightcolor")); } catch (_) {}
    applyViewControls();
    // The colour lives on <body> and the swatches' pressed state is painted
    // from it, so clearing the key changes nothing on screen without this.
    window.annotateHighlighter?.syncControls?.();
  }

  // Paints every setting onto <body> and syncs the panel to it. Idempotent,
  // and safe to call on every render: it reads state, it never advances it.
  function applyViewControls() {
    const groups = document.getElementById("settings-groups");
    for (const s of SETTINGS) {
      const value = settingValue(s);
      document.body.dataset[s.attr] = value;
      if (!groups) continue;
      groups.querySelectorAll(`[data-setting="${s.key}"] [data-value]`).forEach((b) => {
        b.setAttribute("aria-pressed", b.dataset.value === value ? "true" : "false");
      });
    }
  }

  function wireViewControls() {
    const groups = document.getElementById("settings-groups");
    if (groups && !groups.childElementCount) {
      for (const s of SETTINGS) {
        const group = document.createElement("div");
        group.className = "set-group";
        group.dataset.setting = s.key;
        const label = document.createElement("span");
        label.className = "set-label";
        label.textContent = s.label;
        const row = document.createElement("div");
        row.className = "set-row";
        for (const [value, text, chipBg, chipFg] of s.options) {
          const b = document.createElement("button");
          b.type = "button";
          b.dataset.value = value;
          b.setAttribute("aria-pressed", "false");
          // The code themes keep the chip the old popover gave them: "Midnight"
          // names the choice, and the chip shows the ground and ink it means.
          if (chipBg) {
            const chip = document.createElement("span");
            chip.className = "pt-chip";
            chip.style.background = chipBg;
            chip.style.color = chipFg;
            chip.textContent = "Aa";
            b.appendChild(chip);
          }
          const name = document.createElement("span");
          name.className = "pt-name";
          name.textContent = text;
          b.appendChild(name);
          b.addEventListener("click", () => setSetting(s, value));
          row.appendChild(b);
        }
        group.append(label, row);
        groups.appendChild(group);
      }
    }
    // The highlighter's own controls are hidden when the browser has no
    // Highlight API (see highlighter.js), and its colour row must go with
    // them — a palette for a feature that cannot run is worse than no palette.
    const hlBtn = document.getElementById("highlighter-toggle");
    const hlGroup = document.getElementById("set-group-highlight");
    if (hlBtn && hlGroup && hlBtn.hidden) hlGroup.hidden = true;
    const reset = document.getElementById("settings-reset");
    // Bound once: wireViewControls is called at parse time and the button is
    // server-rendered, but a second call must not stack a second listener and
    // reset twice.
    if (reset && !reset.dataset.wired) {
      reset.dataset.wired = "1";
      reset.addEventListener("click", resetSettings);
    }
    applyViewControls();
  }

  function renderCodePane(pane) {
    const wrap = document.createElement("div");
    wrap.className = "codepane";

    const head = document.createElement("div");
    head.className = "cp-head";
    const path = document.createElement("span");
    path.className = "cp-path";
    const shown = pane.actual_line || pane.line;
    // A pane whose status isn't "ok"/"moved" has no location to assert — the
    // body text is about to say the anchored line ISN'T there, so a header
    // reading "file:44" would claim the very thing the message disproves.
    // "moved" is the one non-"ok" status that keeps its line: actual_line is
    // real, it's just not where the block originally pointed.
    const resolved = pane.status === "ok" || pane.status === "moved";
    // The filename, not the path. A repo-relative path is routinely 90+
    // characters and the header is ~475px wide, so the full string was
    // ellipsised in the middle of the part that identifies it --
    // `app-worktrees/ABC-272/advisory/.../featuretoggle/Feat...` told the
    // reader the repo (which the prose already said) and hid the filename
    // (which it did not). Leading segment plus basename keeps both ends, and
    // the full path stays one hover away in the title.
    const segments = (pane.file || "").split("/").filter(Boolean);
    const base = segments.length ? segments[segments.length - 1] : (pane.file || "");
    const project = segments.length > 1 ? segments[0] : "";
    const located = (resolved && shown) ? `${base}:${shown}` : base;
    path.title = pane.file || "";

    // The project reads as a pill, tinted from its own name. A page citing four
    // repos otherwise gives every header the same colour, so telling them apart
    // means reading each one; a stable tint makes it a glance. Deterministic by
    // construction — the same name always lands on the same hue, across panes,
    // pages and reloads — so the colour is a property of the project rather
    // than of the order things happened to render in.
    if (project) {
      const pill = document.createElement("span");
      pill.className = "cp-proj";
      pill.textContent = project;
      pill.style.setProperty("--cp-pill-h", String(hueFromName(project)));
      path.appendChild(pill);
    }

    // file:line copies on click. It is the one string in the pane somebody
    // wants in another window -- a message, a commit, a terminal -- and the
    // FULL repo-relative path is what pastes usefully, even though the header
    // shows the short form. Reading the long path off the screen was never
    // possible anyway: it is why the label was shortened.
    const loc = document.createElement("button");
    loc.type = "button";
    loc.className = "cp-loc";
    loc.textContent = located;
    const toCopy = (resolved && shown) ? `${pane.file}:${shown}` : (pane.file || "");
    loc.title = `copy ${toCopy}`;
    loc.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const was = loc.textContent;
      try {
        await navigator.clipboard.writeText(toCopy);
        loc.textContent = "copied";
      } catch (_) {
        // Clipboard access needs a secure context; the shared LAN link is
        // plain http, so this is a normal outcome there, not a defect. Say so
        // rather than looking like the click did nothing.
        loc.textContent = "copy unavailable";
      }
      loc.dataset.flash = "1";
      setTimeout(() => { loc.textContent = was; delete loc.dataset.flash; }, 1200);
    });
    path.appendChild(loc);

    const spacer = document.createElement("span");
    spacer.className = "cp-spacer";
    head.append(path, spacer);

    // Drift rides in the header band as a chip. It used to be a `.cp-status`
    // row under the note, and head + note + status stacked to 101px above the
    // first line of code — more chrome than content on a short pane. The chip
    // has to carry the AUTHORED line, because that is the one fact the header
    // does not: `path` shows where the line is NOW. The full message stays as
    // the title, so nothing is lost, and a pane with no code to show keeps the
    // whole sentence as a row (below) rather than shrinking to this.
    if (pane.status !== "ok") {
      const chip = document.createElement("span");
      chip.className = "cp-chip";
      chip.dataset.status = pane.status;
      chip.textContent = pane.status === "moved" && pane.line
        ? `moved · was ${pane.line}`
        : pane.status;
      if (pane.message) chip.title = pane.message;
      head.appendChild(chip);
    }

    if (pane.status === "ok" || pane.status === "moved") {
      // Opening is asked of the SERVER, not of the operating system. A page has no
      // way to hand a path to a native app -- `file://` is refused from an http
      // origin -- which is why this used to build a `jetbrains://` URI carrying the
      // IDE's project name, guessed from a directory basename. The guess was wrong
      // whenever a project's name differed from its folder's, and the failure was
      // silent. The server is a local process with no such limitation, so it runs
      // the opener itself and the project name stops existing as a concept here.
      const abs = document.body.dataset.repoRoot || "";
      if (abs) {
        const jump = document.createElement("button");
        jump.type = "button";
        jump.className = "cp-jump";
        jump.replaceChildren(icon(ICON_OPEN));
        jump.title = "open in editor";
        jump.setAttribute("aria-label", jump.title);
        // A failure has to stay legible now that the button is an icon: it
        // cannot become its own error message any more. The reason goes into
        // the tooltip and a red state onto the button, so the click is never
        // silent -- which was the entire point of moving opening server-side.
        const failFor = (why) => {
          jump.dataset.failed = "1";
          jump.title = why;
          jump.setAttribute("aria-label", why);
          setTimeout(() => {
            delete jump.dataset.failed;
            jump.title = "open in editor";
            jump.setAttribute("aria-label", jump.title);
            jump.disabled = false;
          }, 4000);
        };
        jump.addEventListener("click", async () => {
          jump.disabled = true;
          try {
            const res = await fetch("/api/open", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ key: workspaceKey(), file: pane.file, line: shown }),
            });
            if (!res.ok) {
              // The reason is the server's, not a guess.
              failFor((await res.text()) || "could not open");
              return;
            }
          } catch (_) {
            failFor("server unreachable");
            return;
          }
          jump.disabled = false;
        });
        head.appendChild(jump);
      }
    }
    wrap.appendChild(head);

    // A pane that could not resolve shows its reason and NO code. Rendering
    // whatever now sits at that line number would be a lie the reader has no
    // way to detect.
    if (pane.status !== "ok" && pane.status !== "moved") {
      const status = document.createElement("div");
      status.className = "cp-status";
      status.dataset.status = pane.status;
      let msg = pane.message || "this anchor could not be resolved";
      // The header already shows the filename; strip it back off the message
      // if it leads with exactly "<file>: " so it isn't said twice. Only an
      // exact match is stripped — an unexpected message shape renders in
      // full rather than being mangled.
      const filePrefix = pane.file ? `${pane.file}: ` : null;
      if (filePrefix && msg.startsWith(filePrefix)) msg = msg.slice(filePrefix.length);
      status.textContent = msg;
      wrap.appendChild(status);
      return wrap;
    }

    const body = document.createElement("div");
    body.className = "cp-body";
    // Painted as one run and cut into rows, for the same reason as the explain
    // pane: a row coloured on its own loses the annotation or comment it
    // continues.
    const lines = pane.lines || [];
    const paintedRows = window.CodePaint
      ? CodePaint.rows(lines.map((l) => l.text), { file: pane.file }) : null;
    lines.forEach((l, i) => {
      const row = document.createElement("div");
      row.className = "cp-row";
      if (l.role === "anchor") row.classList.add("is-anchor");
      if (l.role === "context") row.classList.add("is-context");
      // A blank context line renders nothing at all; at a full row height it
      // reads as a hole in the pane rather than as the blank line it is.
      if (l.role === "context" && !String(l.text || "").trim()) row.classList.add("is-blank");
      const text = document.createElement("span");
      text.className = "cp-line";
      if (paintedRows) text.innerHTML = paintedRows[i];
      else text.textContent = l.text;
      row.appendChild(text);
      body.appendChild(row);
    });
    wrap.appendChild(body);

    if (pane.truncated) {
      const cut = document.createElement("div");
      cut.className = "cp-truncated";
      cut.textContent = `… ${pane.truncated} more lines`;
      wrap.appendChild(cut);
    }
    return wrap;
  }

  // ── kind: explain ─────────────────────────────────────────────────────
  // A pane where the explanation rides on the code. Everything positional is
  // measured in `ch` against columns resolved server-side (explain.py), which
  // is exact because the pane is monospace.
  //
  // The marks are ABSOLUTE OVERLAYS, not wrappers around the text. Wrapping a
  // span would mean splitting the highlighter's output at a character offset — and worse,
  // an inline element inserted into a `white-space: pre` row shifts every
  // glyph after it, so the underline would stop lining up with the thing it is
  // underlining. Overlaying leaves the highlighted line untouched and costs
  // nothing in layout, which is also why a badge here does not nudge the code
  // sideways the way an inline badge would.
  function explainRow(row, n, group, painted, ulines) {
    const div = document.createElement("div");
    div.className = "cp-row ex-row";
    if (row.blank) div.classList.add("is-blank");
    const text = document.createElement("span");
    text.className = "cp-line";
    if (painted != null) text.innerHTML = painted;
    else text.textContent = row.text;
    div.appendChild(text);

    (group ? group.marks : []).forEach((m) => {
      const u = document.createElement("i");
      u.className = "ex-uline";
      u.style.left = `calc(12px + ${m.col}ch)`;
      u.style.width = `${m.len}ch`;
      div.appendChild(u);
      // The walk lights one note's marks at a time and finds them by where
      // they are, which is the only thing a step and a mark both know.
      if (ulines) ulines.set(`${n}:${m.col}`, u);
      // An echo is a second place the same note is true of. It has no label
      // of its own, so a badge on it would number an entry that is not in the
      // list under the line — see explainNotes.
      const onSpanBadge = group.mode === "badge" && !m.echo;
      if (onSpanBadge) {
        const b = document.createElement("i");
        b.className = "ex-badge ex-badge--onspan";
        b.textContent = String(m.n);
        b.style.left = `calc(12px + ${m.col + m.len}ch)`;
        div.appendChild(b);
      }
      // The value chip: the concrete number this example carries at this
      // exact span, so a reader tracks the trace without leaving the code to
      // read a label. Independent of the walk and of echo status — two
      // occurrences of one claim can carry two different numbers.
      //
      // Split the same way `.ex-at`/`.ex-pin` are: the OFFSET-carrying node
      // (`ex-val`) inherits the row's code font untouched, because `ch` is a
      // metric of an element's own font and the column arithmetic above was
      // written in the code font's `ch`. A prose-sized chip styled directly
      // on that node would resolve a narrower `ch` and land back over the
      // span it is meant to follow. The pill's own look lives one level in,
      // on `ex-val-chip`, which carries no position of its own.
      //
      // Badge mode only, NOT on-span: three marks already sit close enough on
      // one line to need numbered badges instead of a ladder (see LADDER_MAX
      // in explain.py), and a value chip wide enough to read overlaps the
      // very next mark's span at that spacing. explainNotes prints it there
      // instead, next to the badge it belongs to, where there is a full row
      // of width to spend on it.
      if (m.valueHtml && group.mode !== "badge") {
        const v = document.createElement("i");
        v.className = "ex-val";
        v.style.left = `calc(12px + ${m.col + m.len}ch)`;
        v.appendChild(explainValueChip(m.valueHtml));
        div.appendChild(v);
      }
    });
    return div;
  }

  function explainLabel(html, extra) {
    const el = document.createElement("div");
    el.className = "ex-lbl" + (extra ? ` ${extra}` : "");
    // Restricted inline markdown, already escaped and rendered by explain.py's
    // label_html — bold and code and nothing else. Not model HTML.
    el.innerHTML = html || "";
    return el;
  }

  // The value chip's look with no positioning node around it — for a context
  // that is already laid out (the notes list), unlike the on-span form in
  // explainRow, which needs one to carry a `ch` offset in the code's font.
  function explainValueChip(html) {
    const el = document.createElement("span");
    el.className = "ex-val-chip";
    el.innerHTML = html || "";
    return el;
  }

  // One or two marks: a ladder. Labels are emitted rightmost-first, the way a
  // compiler stacks them, and every mark to the LEFT of the one being labelled
  // carries a stem down through the row so its own elbow below still reads as
  // coming from its column. Stems are 1px wide with -1px margin, so they draw
  // at exactly their column and consume no width — which is what keeps the
  // gaps expressible as whole `ch` counts with no pixel bookkeeping.
  function explainLadder(group) {
    const lad = document.createElement("div");
    lad.className = "ex-lad";
    // Echoes are underlined on the line and stop there: they carry no label,
    // so a rung for one would be an elbow pointing at nothing.
    const marks = group.marks.filter((m) => !m.echo);
    for (let j = marks.length - 1; j >= 0; j--) {
      const row = document.createElement("div");
      row.className = "ex-lad-row";
      let prev = 0;
      for (let i = 0; i < j; i++) {
        row.appendChild(explainGap(marks[i].col - prev));
        const stem = document.createElement("i");
        stem.className = "ex-stem";
        row.appendChild(stem);
        prev = marks[i].col;
      }
      row.appendChild(explainGap(marks[j].col - prev));
      const elbow = document.createElement("i");
      elbow.className = "ex-elbow";
      row.appendChild(elbow);
      row.appendChild(explainLabel(marks[j].labelHtml));
      lad.appendChild(row);
    }
    return lad;
  }

  function explainGap(ch) {
    const gap = document.createElement("i");
    gap.className = "ex-gap";
    gap.style.width = `${Math.max(0, ch)}ch`;
    return gap;
  }

  // Three or more marks: the ladder becomes a knot, so the labels leave the
  // columns and become a numbered list. The underlines stay on the line, so
  // position is still stated — only the attachment changes.
  function explainNotes(group) {
    const list = document.createElement("div");
    list.className = "ex-notes";
    group.marks.filter((m) => !m.echo).forEach((m) => {
      const item = document.createElement("div");
      item.className = "ex-note";
      const b = document.createElement("i");
      b.className = "ex-badge";
      b.textContent = String(m.n);
      item.appendChild(b);
      item.appendChild(explainLabel(m.labelHtml));
      if (m.valueHtml) item.appendChild(explainValueChip(m.valueHtml));
      list.appendChild(item);
    });
    return list;
  }

  // ── the walk ──────────────────────────────────────────────────────────
  // One note at a time, in the order they were written, with the rest of the
  // pane stepped back. The static pane is built FIRST and in full — every
  // underline, every ladder, every bracket — and the walk is then a layer of
  // state on top of it: `data-walk` on the pane, `.is-now` on the current
  // note's marks, `.is-lit` on its rows. Nothing is built for one mode and
  // missing from the other, which is what lets the export (no JS, no
  // controls) recover the whole pane by deleting three nodes and one
  // attribute rather than re-rendering anything.

  // The pins: a step's number, parked past the end of its first line. They are
  // the pane's table of contents — how many stops there are, where they are,
  // and a way into any of them without walking the ones between.
  function explainPins(step, onPick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ex-pin";
    b.textContent = String(step.n);
    b.title = step.lead ? `step ${step.n} — ${step.lead}` : `step ${step.n}`;
    b.addEventListener("click", () => onPick(step.n - 1));
    return b;
  }

  // A tray that resizes as you step shoves the rest of the page down mid-read,
  // so it is sized once to the longest note and never moves again. Measured
  // AFTER the webfonts land: against the fallback face the reservation comes
  // out a line short, and the pane grows on the first long note anyway —
  // 326px then 344px, measured in Chromium. `border-box` is why the padding
  // is added back in.
  function reserveTray(tray, steps) {
    const settle = () => requestAnimationFrame(() => {
      const keep = [...tray.childNodes];
      let tallest = 0;
      steps.forEach((s) => {
        tray.replaceChildren(explainLabel(s.labelHtml));
        tallest = Math.max(tallest, tray.firstChild.getBoundingClientRect().height);
      });
      tray.replaceChildren(...keep);
      const cs = getComputedStyle(tray);
      tray.style.minHeight = Math.ceil(
        tallest + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)) + "px";
    });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(settle);
    else settle();
  }

  function explainWalk(wrap, body, view, rowEls, ulines) {
    const steps = view.walk || [];
    if (!steps.length) return;

    // `view.walk`'s own marks carry only position — `view.groups` is where a
    // mark's `valueHtml` lives (see explain.py). Cross-referenced by
    // `line:col`, the same key `ulines` already uses to find a mark again
    // after it is painted.
    const groupByLine = new Map((view.groups || []).map((g) => [g.line, g]));
    const valueByPos = new Map();
    (view.groups || []).forEach((g) => g.marks.forEach((m) => {
      if (m.valueHtml) valueByPos.set(`${g.line}:${m.col}`, m.valueHtml);
    }));

    const tray = document.createElement("div");
    tray.className = "ex-tray";

    const bar = document.createElement("div");
    bar.className = "ex-bar";
    const prev = document.createElement("button");
    prev.type = "button"; prev.className = "ex-step"; prev.textContent = "‹";
    prev.setAttribute("aria-label", "previous step");
    const next = document.createElement("button");
    next.type = "button"; next.className = "ex-step"; next.textContent = "›";
    next.setAttribute("aria-label", "next step");
    const count = document.createElement("span");
    count.className = "ex-count";
    const pips = document.createElement("span");
    pips.className = "ex-pips";
    steps.forEach(() => {
      const p = document.createElement("i");
      p.className = "ex-pip";
      pips.appendChild(p);
    });
    bar.append(prev, next, count, pips);

    let at = 0;
    const pins = [];

    function go(i) {
      at = Math.max(0, Math.min(steps.length - 1, i));
      const step = steps[at];

      rowEls.forEach((r) => r.classList.remove("is-lit"));
      ulines.forEach((u) => u.classList.remove("is-now"));

      const lines = step.kind === "range"
        ? Array.from({ length: step.to - step.from + 1 }, (_, k) => step.from + k)
        : (step.marks || []).map((m) => m.line);
      lines.forEach((n) => {
        const row = rowEls[n - 1];
        if (row) row.classList.add("is-lit");
      });
      (step.marks || []).forEach((m) => {
        const u = ulines.get(`${m.line}:${m.col}`);
        if (u) u.classList.add("is-now");
      });

      const trayKids = [explainLabel(step.labelHtml)];
      // Badge-mode values live in `.ex-notes`, which the walk hides (see
      // .codepane.ex[data-walk] .ex-notes) — without this they would be the
      // one thing on the pane a walking reader never sees. Ladder-mode values
      // stay on the span throughout the walk already, so repeating them here
      // would be the same number printed twice.
      if (step.kind === "span") {
        (step.marks || []).forEach((m) => {
          if ((groupByLine.get(m.line) || {}).mode !== "badge") return;
          const html = valueByPos.get(`${m.line}:${m.col}`);
          if (html) trayKids.push(explainValueChip(html));
        });
      }
      tray.replaceChildren(...trayKids);
      count.textContent = `step ${at + 1} of ${steps.length}` +
        (step.lead ? ` — ${step.lead}` : "");
      prev.disabled = at === 0;
      next.disabled = at === steps.length - 1;
      pins.forEach((p, k) => p.classList.toggle("is-now", k === at));
      pips.querySelectorAll(".ex-pip").forEach((p, k) => p.classList.toggle("on", k === at));

      // Only when the step is genuinely off screen: `block: "nearest"` would
      // still be a no-op most of the time, but a snippet long enough to walk
      // off the bottom is exactly the one this kind is for.
      const first = rowEls[lines[0] - 1];
      if (first) {
        const r = first.getBoundingClientRect();
        if (r.top < 0 || r.bottom > (window.innerHeight || 0)) {
          first.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
    }

    // A pin per step, grouped by the line it sits on so two steps starting on
    // the same line stand side by side instead of on top of each other.
    const byLine = new Map();
    steps.forEach((s) => {
      const line = s.kind === "range" ? s.from : (s.marks[0] && s.marks[0].line);
      if (!line) return;
      if (!byLine.has(line)) byLine.set(line, []);
      byLine.get(line).push(s);
    });
    // A value chip is anchored to its span, which is sometimes the last thing
    // on the line — `priceInReferenceCurrency)` leaves one character before
    // the pin's own reservation. Widen that reservation by the chip's rough
    // width (plain-text length, tags stripped: a `valueHtml` is the same
    // restricted markdown as a label) rather than moving the chip, since the
    // chip's whole point is sitting exactly where the span ends. Badge-mode
    // lines never grow an on-span chip (see explainRow), so they need no
    // overhang here.
    function valueOverhang(line) {
      const group = groupByLine.get(line);
      const base = ((view.rows[line - 1] || {}).text || "").length;
      if (!group || group.mode === "badge") return 0;
      let end = base;
      group.marks.forEach((m) => {
        if (!m.valueHtml) return;
        const plain = m.valueHtml.replace(/<[^>]+>/g, "");
        end = Math.max(end, m.col + m.len + 2 + plain.length + 1);
      });
      return Math.max(0, end - base);
    }
    byLine.forEach((list, line) => {
      const row = rowEls[line - 1];
      if (!row) return;
      const at_ = document.createElement("i");
      at_.className = "ex-at";
      // Past the end of the line, never on top of it. The offset is in `ch`
      // and this element inherits the CODE font, which is the only font whose
      // `ch` the column arithmetic is written in — a pin styled in the prose
      // face resolves a narrower `ch` and lands back among the glyphs.
      at_.style.left = `calc(12px + ${(view.rows[line - 1] || {}).text.length + 2 + valueOverhang(line)}ch)`;
      list.forEach((s) => {
        const pin = explainPins(s, go);
        pins[s.n - 1] = pin;
        at_.appendChild(pin);
      });
      row.appendChild(at_);
    });

    prev.addEventListener("click", () => go(at - 1));
    next.addEventListener("click", () => go(at + 1));
    wrap.tabIndex = 0;
    wrap.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { go(at + 1); ev.preventDefault(); }
      else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { go(at - 1); ev.preventDefault(); }
    });

    wrap.append(tray, bar);
    // Opens already walking: a control nobody finds is a feature nobody has.
    wrap.dataset.walk = "1";
    go(0);
    reserveTray(tray, steps);
  }

  function renderExplain(content, blk) {
    const view = blk.view || {};
    const wrap = document.createElement("div");
    wrap.className = "codepane ex";

    if (view.error) {
      const err = document.createElement("div");
      err.className = "cp-status";
      err.dataset.status = "refused";
      err.textContent = `explain block: ${view.error}`;
      wrap.appendChild(err);
      content.appendChild(wrap);
      return;
    }

    const head = document.createElement("div");
    head.className = "cp-head";
    const path = document.createElement("span");
    path.className = "cp-path";
    if (view.project) {
      const pill = document.createElement("span");
      pill.className = "cp-proj";
      pill.textContent = view.project;
      pill.style.setProperty("--cp-pill-h", String(hueFromName(view.project)));
      path.appendChild(pill);
    }
    if (view.loc) {
      const loc = document.createElement("span");
      loc.className = "cp-loc";
      loc.textContent = view.loc;
      path.appendChild(loc);
    }
    head.appendChild(path);
    wrap.appendChild(head);

    const body = document.createElement("div");
    body.className = "cp-body ex-body";

    const rows = view.rows || [];
    const groups = new Map((view.groups || []).map((g) => [g.line, g]));
    const opens = new Map((view.ranges || []).map((r) => [r.from, r]));

    let sink = body;      // where the next row goes
    let open = null;      // the range being filled, if any
    // The walk needs to find a row and a mark again after they are painted;
    // rebuilding either from the spec would be a second renderer to keep in
    // step with this one.
    const rowEls = [];
    const ulines = new Map();
    // The whole snippet in one pass, cut into rows: see CodePaint.rows.
    const painted = window.CodePaint
      ? CodePaint.rows(rows.map((r) => r.text), { lang: view.lang, file: (view.loc || "").replace(/:\d+$/, "") }) : null;

    for (let n = 1; n <= rows.length; n++) {
      if (!open && opens.has(n)) {
        open = opens.get(n);
        const range = document.createElement("div");
        range.className = "ex-range";
        const side = document.createElement("div");
        side.className = "ex-range-code";
        range.appendChild(side);
        body.appendChild(range);
        open.el = range;
        sink = side;
      }
      const rowEl = explainRow(rows[n - 1], n, groups.get(n),
                               painted ? painted[n - 1] : null, ulines);
      rowEls[n - 1] = rowEl;
      sink.appendChild(rowEl);
      const g = groups.get(n);
      if (g) sink.appendChild(g.mode === "badge" ? explainNotes(g) : explainLadder(g));
      if (open && n === open.to) {
        const brk = document.createElement("i");
        brk.className = "ex-brk";
        open.el.appendChild(brk);
        open.el.appendChild(explainLabel(open.labelHtml, "ex-lbl--range"));
        open = null;
        sink = body;
      }
    }
    wrap.appendChild(body);
    explainWalk(wrap, body, view, rowEls, ulines);
    content.appendChild(wrap);
  }

  // The band of panes under one block's prose, or null when the block cites
  // no code. An anchorless block renders exactly as annotate does today:
  // full-width prose, nothing under it.
  function renderCodeColumn(blk) {
    // I4: check_anchors already refuses a mockup block's anchors at push
    // time, but the render path serves strangers on the read-only link --
    // defence in depth belongs here too, not only in the check. A mockup
    // renders in a sandboxed iframe and has nowhere to put a pane.
    if (blk.kind === "mockup") return null;
    const panes = Array.isArray(blk.code) ? blk.code : [];
    if (!panes.length) return null;

    const col = document.createElement("div");
    col.className = "code-col";
    panes.forEach((p) => col.appendChild(renderCodePane(p)));
    return col;
  }

  // The reading highlighter paints ranges over block prose from outside the
  // DOM, so it has to be re-applied whenever that prose is replaced. Called
  // from here rather than from a MutationObserver inside the highlighter: this
  // is the point where a render is FINISHED, which an observer cannot know.
  function repaintHighlights() {
    const hl = window.annotateHighlighter;
    if (hl && typeof hl.repaint === "function") hl.repaint();
  }

  // Run on every full render and every poll: re-reads the settings (another
  // tab may have changed a global one) and repaints the highlighter.
  function refreshPageState() {
    applyViewControls();
    repaintHighlights();
  }

  // A flowchart authored as pflow ships the source it was compiled from. Render
  // it under the chart, line-addressable: every line that produced a node
  // carries that node's id, so hovering either view lights the other and the
  // reader can see which line drew which shape. The line used to be a comment
  // target too; it is not any more (see the createBlockSection note on why the
  // granular scope was withdrawn from pictures).
  function renderPflowSource(blk) {
    const spec = blk.spec || {};
    const src = String(spec.source || "").replace(/\n+$/, "");
    if (!src) return null;

    const wrap = document.createElement("div");
    wrap.className = "pflow";

    const head = document.createElement("div");
    head.className = "pflow-head";
    const label = document.createElement("span");
    label.className = "pflow-label";
    label.textContent = "source";
    const hint = document.createElement("span");
    hint.className = "pflow-hint";
    hint.textContent = "hover a line to light the step it draws";
    head.append(label, hint);

    const byLine = new Map();
    (spec.nodes || []).forEach((n) => {
      if (n && n.line) byLine.set(Number(n.line), n.id);
    });

    const lines = src.split("\n");
    const painted = highlightPflow(src);
    const paintedLines = painted ? CodePaint.splitRows(painted) : null;

    // `.sk-fence` on the body, not on a <pre><code>: it takes the fence ground
    // and base colour (each token carries its own colour regardless), and it
    // keeps `main.prose pre code.sk-fence` — which sets its own font-size and
    // line-height for fenced code — from reaching in here and breaking the rows.
    const body = document.createElement("div");
    body.className = "pflow-body sk-fence";

    lines.forEach((line, i) => {
      const row = document.createElement("div");
      row.className = "pflow-row";
      const num = document.createElement("span");
      num.className = "pflow-num";
      num.setAttribute("aria-hidden", "true");
      num.textContent = String(i + 1);
      const text = document.createElement("span");
      text.className = "pflow-line";
      if (paintedLines) text.innerHTML = paintedLines[i] || "";
      else text.textContent = line;
      // A line that produced a node carries its id, which is what pairs the
      // row with the shape on hover. Lines that produced nothing stay inert.
      // Neither is clickable: the comment on a picture is whole-block now.
      const nodeId = byLine.get(i + 1);
      if (nodeId) {
        row.dataset.nodeId = nodeId;
        row.classList.add("is-live");
      }
      row.append(num, text);
      body.appendChild(row);
    });

    wrap.append(head, body);
    return wrap;
  }

  // A block that laid out cleanly in more than one way ships every rendering
  // and lets the reader pick. The choice is theirs alone: it lives in
  // localStorage, is never sent to the daemon, and never reaches another
  // viewer. Storage can throw outright in a private window or with site data
  // blocked, so every access is guarded and an unreadable store simply means
  // the block opens on its default.
  //
  // Keyed by response as well as block. Block ids repeat across documents
  // (every document's first block is section-1), so a key of the block id
  // alone carried a layout picked in one document into every other one.
  const FLAVOUR_KEY = "annotate.flavour";
  const VIEW_KEY = "annotate.flowview";

  function choiceKey(prefix, blockId) {
    const rid = document.body.dataset.responseId || "default";
    return `${prefix}:${rid}:${blockId}`;
  }

  function readChoice(prefix, blockId) {
    try {
      return window.localStorage.getItem(choiceKey(prefix, blockId));
    } catch (e) {
      return null;
    }
  }

  function writeChoice(prefix, blockId, name) {
    try {
      window.localStorage.setItem(choiceKey(prefix, blockId), name);
    } catch (e) {
      /* per-viewer convenience only — losing it costs nothing */
    }
  }

  function flavourLabel(name) {
    if (name === "all") return "All";
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  // Paint a flowchart block: the server SVG, plus the source pane when the
  // block was authored as pflow, plus the layout control when it shipped more
  // than one rendering. Shared by create and update so an in-place refresh
  // cannot leave one without the others.
  function paintFlowchart(content, blk) {
    const svgs = blk.svgs || {};
    // Views win over layout flavours when a block ships both: a view changes
    // which edges are drawn, which is a question the reader asked, while a
    // flavour only changes how the same edges are arranged.
    const viewNames = blk.views || [];
    const isViews = viewNames.length > 1;
    const names = isViews ? viewNames : blk.flavours || [];
    const key = isViews ? VIEW_KEY : FLAVOUR_KEY;
    const label = isViews ? "Diagram view" : "Diagram layout";

    function buildControl(current) {
      const wrap = document.createElement("div");
      wrap.className = isViews ? "flow-flavours flow-views" : "flow-flavours";
      wrap.setAttribute("role", "group");
      wrap.setAttribute("aria-label", label);
      names.forEach((name) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = flavourLabel(name);
        if (isViews) b.dataset.view = name;
        else b.dataset.flavour = name;
        if (name === current) b.setAttribute("aria-pressed", "true");
        else b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", () => {
          writeChoice(key, blk.id, name);
          paint(name);
        });
        wrap.appendChild(b);
      });
      return wrap;
    }

    const paint = (name) => {
      // Trusted server output — deliberately bypasses sanitizeFreeHtml so the
      // class/data-* hit targets survive.
      content.innerHTML = (name && svgs[name]) || blk.svg || "";
      if (names.length > 1) content.prepend(buildControl(name));
      const source = renderPflowSource(blk);
      if (source) content.appendChild(source);
    };

    let chosen = names.length > 1 ? readChoice(key, blk.id) : null;
    if (names.indexOf(chosen) === -1) chosen = names[0] || null;
    paint(chosen);
  }

  // Hovering either view lights the other: the id lives on the SVG node and on
  // the source line alike, so one selector reaches both.
  function linkPflowHover(content) {
    const clear = () => {
      content.querySelectorAll(".is-node-active").forEach((el) => {
        el.classList.remove("is-node-active");
      });
    };
    content.addEventListener("mouseover", (ev) => {
      const el = ev.target.closest && ev.target.closest("[data-node-id]");
      clear();
      if (!el || !content.contains(el)) return;
      content.querySelectorAll(`[data-node-id="${cssEsc(el.dataset.nodeId)}"]`)
        .forEach((m) => m.classList.add("is-node-active"));
    });
    content.addEventListener("mouseleave", clear);
  }

  // A sequence block is two halves: the grid (`blk.svg`) and the numbered key
  // beneath it (`blk.key`). The grid carries arrows and badges and no words at
  // all, so painting the svg alone leaves a picture of unexplained circles —
  // both halves go in together, always.
  function paintSequence(content, blk) {
    content.innerHTML = (blk.svg || "") + (blk.key || "");
  }

  // Badge ⇄ key pairing. They pair on data-step-id, which is also what a
  // comment anchors to, so lighting a step lights whatever a comment marked.
  // Delegated from .block-content, which survives updateBlockContent's
  // innerHTML swap — binding to the badges themselves would go stale on the
  // first repaint.
  function linkSequenceKey(content) {
    const clear = () => {
      content.querySelectorAll(".is-linked").forEach((el) => el.classList.remove("is-linked"));
    };
    const select = (stepId, scroll) => {
      const row = content.querySelector(`.seq-key-row[data-step-id="${cssEsc(stepId)}"]`);
      const grid = content.querySelector(`.step-row[data-step-id="${cssEsc(stepId)}"]`);
      // A second click on the same step lets go, so a reader is never stuck
      // with a highlight they cannot dismiss from the thing they clicked.
      if (row && row.classList.contains("is-linked")) { clear(); return; }
      clear();
      if (row) row.classList.add("is-linked");
      if (grid) grid.classList.add("is-linked");
      if (scroll && row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };
    const handle = (ev, el) => {
      ev.stopPropagation();
      select(el.dataset.stepId, el.classList.contains("badge-hit"));
    };
    content.addEventListener("click", (ev) => {
      const el = ev.target.closest && ev.target.closest(".badge-hit, .seq-key-row");
      if (el && content.contains(el)) handle(ev, el);
      else clear();
    });
    content.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { clear(); return; }
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const el = ev.target.closest && ev.target.closest(".badge-hit, .seq-key-row");
      if (!el || !content.contains(el)) return;
      ev.preventDefault();
      handle(ev, el);
    });
  }

  function createBlockSection(blk) {
    const section = document.createElement("section");
    section.className = "block card";
    section.dataset.blockId = blk.id;
    section.dataset.version = String(blk.version ?? 1);
    const kind = blk.kind || "markdown";
    section.dataset.kind = kind;
    // The reader's own words in this block (edit.js paints them).
    section._mine = Array.isArray(blk.mine) ? blk.mine : [];

    // Card header: collapse chevron + title (+ version chip, added by
    // renderVersionBadge). Clicking the header toggles the body.
    const head = document.createElement("div");
    head.className = "card-head";
    const chev = document.createElement("button");
    chev.type = "button";
    chev.className = "card-chevron";
    chev.setAttribute("aria-label", "Collapse section");
    chev.setAttribute("aria-describedby", `card-title-${blk.id}`);
    chev.textContent = "▾";
    const title = document.createElement("span");
    title.className = "card-title";
    title.textContent = blockTitle(blk);
    // A heading to assistive tech: a 40-block document had no headings at
    // all, so there was nothing to jump between. The span stays a span so no
    // prose `h2` rule restyles it. The id is what the header buttons and a
    // choice's option group name themselves by.
    title.setAttribute("role", "heading");
    title.setAttribute("aria-level", "2");
    title.id = `card-title-${blk.id}`;
    const spacer = document.createElement("span");
    spacer.className = "card-head-spacer";
    head.append(chev, title, spacer);
    section.appendChild(head);

    const body = document.createElement("div");
    body.className = "card-body";
    const content = document.createElement("div");
    content.className = "block-content";
    if (kind === "sequence") {
      // Server pre-rendered both halves; inject as-is.
      paintSequence(content, blk);
      linkSequenceKey(content);
      // Still no comment-on-click: a picture is commented as a whole, from the
      // card header, for the same reason flowchart lost its node handler
      // below. What linkSequenceKey binds is not a way into the composer — it
      // pairs a badge with its key entry and nothing else. The `data-step-id`
      // hit targets stay on the rows: they anchor comments made before that
      // rule, and applyEngagedStyling still paints the row they target.
    } else if (kind === "flowchart") {
      // Server pre-rendered the hand-built SVG, plus the pflow source pane when
      // the block carries one. Both views hang their hit targets off
      // data-node-id, so the one listener below serves either.
      paintFlowchart(content, blk);
      linkPflowHover(content);
      // A picture is commented as a whole, from the card header — never per
      // node. The node click handler that used to live here was withdrawn
      // because a node's `ref` line is painted accent-coloured and underlined
      // whether or not the spec gave it an href (`.annotate-flow .flow-ref`),
      // so a file reference with no href reads as a jump-to-source link and
      // behaved as a comment target: the click missed the absent anchor and
      // opened the composer instead. Reaching for a file and getting an
      // editor is the whole complaint, and no amount of hit-target tuning
      // fixes a link that isn't one.
      //
      // What survives is navigation: an in-page cross-block anchor
      // (href="#<block-id>") smooth-scrolls to that block, and any other
      // anchor (e.g. a jetbrains:// code ref) is left to navigate normally.
      // Listener lives on content so updateBlockContent's innerHTML swap
      // doesn't drop it.
      content.addEventListener("click", (ev) => {
        const anchor = ev.target.closest && ev.target.closest("a[href]");
        if (!anchor) return;
        const href = anchor.getAttribute("href");
        if (!href.startsWith("#")) return;
        ev.preventDefault();
        const target = document.querySelector(
          `[data-block-id="${cssEsc(href.slice(1))}"]`
        );
        if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    } else if (kind === "choice") {
      renderChoice(section, content, blk);
    } else if (kind === "mockup") {
      // Trusted Claude HTML in a sandboxed iframe; deliberately bypasses
      // sanitizeFreeHtml (the sandbox is the isolation boundary instead).
      renderMockup(content, blk);
    } else if (kind === "explain") {
      renderExplain(content, blk);
    } else {
      // Markdown path — markdown-it now allows inline HTML (`html: true`);
      // sanitize the rendered tree before glossary decoration.
      content.innerHTML = blockMd ? blockMd.render(blk.markdown || "") : (blk.markdown || "");
      sanitizeFreeHtml(content);
      if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
    }
    body.appendChild(content);

    const codeCol = renderCodeColumn(blk);
    if (codeCol) {
      section.dataset.hasCode = "1";
      body.appendChild(codeCol);
    }

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

  // Resolve a diagram step (or free-HTML data-annotate-id region) to its row node, display
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
  // a section already overlaid is left alone. Its last caller was the choice
  // block's own Submit, which is gone now that answers ride the round.
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

    // For diagram-row / data-annotate-id region comments, head the card with the step it
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

    // ── Add button ─────────────────────────────────────────────────────────
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
        images,
        selected_text: a.selected_text || "",
        prefix: a.prefix,
        suffix: a.suffix,
      });
      delete annotations[id];
      saveDrafts();
      document.body.classList.toggle("is-editing", Object.keys(annotations).length > 0);
      // Re-render the dock in THIS tick. Its Submit button is disabled while
      // `is-editing`, but renderDock otherwise only runs on the 1s poll — so
      // without this there is a window where an editor is open and Submit is
      // still live, which drops the comment the user is mid-way through
      // writing. That window is the bug; a narrower window is not a fix.
      window.AnnotateSubunits?.renderDock();
      // Removing the card took the focused button with it, and focus fell to
      // <body>: the next Tab restarted from the top of the page. Hand it to
      // the section's fold button, and say what happened, since the card
      // vanishing is all a screen reader would otherwise get.
      const home = document.querySelector(
        `section.block[data-block-id="${cssEsc(a.block_id)}"]`);
      card.remove();
      applyEngagedStyling();
      home?.querySelector(".card-chevron")?.focus();
      window.AnnotateA11y?.announce("Comment added to the round");
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
    //
    // isEmptyDraft was a third condition here and had to come out: it made
    // opening a comment impossible. openAnnotation creates the draft, saves
    // it, and calls this to draw its card — but a draft that has just been
    // opened has no text in it yet, so it IS empty, and this pruned it before
    // the card was ever built. Clicking the comment icon wrote the draft to
    // localStorage and deleted it again in the same tick, and the page did
    // not so much as flicker. Empty drafts are still dropped, in the two
    // places that can tell an abandoned one from a live one: openAnnotation,
    // before it opens a different target, and loadDrafts, on the way in.
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
    // Same tick, same reason as the submit path above: the dock's disabled
    // state reads `is-editing`, so it has to be repainted the moment the
    // class moves rather than on the next poll.
    window.AnnotateSubunits?.renderDock();
  }

  function focusComment(id) {
    const card = document.querySelector(`.comment-card[data-id="${id}"]`);
    if (!card) return;
    const ta = card.querySelector("textarea");
    if (ta) ta.focus({ preventScroll: true });
  }

  // One editor at a time is the rule, and it stands. Refusing in SILENCE is
  // what had to go: a comment icon that does nothing when clicked is
  // indistinguishable from a broken one — which is exactly what it was
  // mistaken for, and reported as, when renderComments was deleting these
  // drafts at the moment they were created. The open card is usually the
  // reason, and it is usually somewhere off screen.
  function revealOpenDraft() {
    const openId = Object.keys(annotations)[0];
    if (!openId) return;
    const card = document.querySelector(`.comment-card[data-id="${cssEsc(openId)}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    // Restarted rather than merely added: a second refusal while the class is
    // still on the element would re-add a class it already has and animate
    // nothing, so the one signal the user gets would fire only the first time.
    card.classList.remove("is-calling");
    void card.offsetWidth;
    card.classList.add("is-calling");
    setTimeout(() => card.classList.remove("is-calling"), 1200);
    const ta = card.querySelector("textarea");
    if (ta) ta.focus({ preventScroll: true });
  }

  // ── Done button ────────────────────────────────────────────────────────────

  // Done, and its way back. Finishing a session was a one-way door in the
  // page: the daemon has had POST /s/<sid>/api/unfinish all along and the CLI
  // exposes it as `webcompanion unfinish`, but nothing in the document did —
  // so a Done pressed a moment too early meant dropping to a terminal to
  // recover a session you were looking at.
  //
  // Deliberately NOT a confirm on the way back. Finishing tells Claude to
  // resume and so asks first; reopening only puts the controls back, and the
  // round that was already submitted stays submitted either way.
  const doneBtn = document.getElementById("done-btn");
  if (doneBtn) {
    doneBtn.addEventListener("click", async () => {
      if (document.body.classList.contains("session-finished")) {
        doneBtn.disabled = true;
        const r = await fetch("api/unfinish", { method: "POST" }).catch(() => null);
        if (r && r.ok) window.location.reload();
        else doneBtn.disabled = false;
        return;
      }
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

  // The button is server-rendered as "Done"; only the page knows the session
  // has since ended, so the label follows the state rather than the markup.
  (function trackFinishedState() {
    const btn = document.getElementById("done-btn");
    if (!btn) return;
    const sync = () => {
      const finished = document.body.classList.contains("session-finished");
      btn.textContent = finished ? "Reopen" : "Done";
      btn.title = finished
        ? "This round is closed. Reopen it to mark or comment on more blocks."
        : "Mark this round as done — Claude resumes";
      btn.disabled = false;
    };
    new MutationObserver(sync).observe(document.body,
      { attributes: true, attributeFilter: ["class"] });
    sync();
  })();

  // ── General composer (page-level, non-block comment) ────────────────────────
  // A persistent textarea that sends a block_id-null comment straight to Claude
  // Code. Unlike block comments it leaves no inline card; status is reported in
  // the composer's own status line and resolved when Claude acks the event.
  (function initGeneralComposer() {
    const input = document.getElementById("general-input");
    const sendBtn = document.getElementById("general-send");
    const statusEl = document.getElementById("general-status");
    if (!input || !sendBtn) return;

    // Per session, not per response: an unsent general comment is a turn in
    // the conversation, and a new response arriving must not lose it.
    const KEY = `annotate.general.${location.pathname}`;
    try { input.value = localStorage.getItem(KEY) || ""; } catch {}

    const sync = () => {
      sendBtn.disabled = input.value.trim() === "";
      try {
        if (input.value) {
          localStorage.setItem(KEY, input.value);
          window.AnnotateStorage.touch(KEY);
        } else localStorage.removeItem(KEY);
      } catch {}
    };
    sync();

    function send() {
      const text = input.value.trim();
      if (!text) return;
      sendBtn.disabled = true;
      // Read before sending: the page locks itself the moment the daemon has
      // this comment, so asking afterwards always answered "busy", and every
      // comment was reported as queued behind some other update.
      const queued = document.body.classList.contains("is-busy");
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
          statusEl.textContent = queued
            ? "queued — Claude will get to it after the current update…"
            : "sent — Claude is responding…";
        }
      }).catch(() => {
        sendBtn.disabled = false;
        if (statusEl) statusEl.textContent = "send failed — try again";
      });
    }

    input.addEventListener("input", sync);
    // A pending comment whose whole block Claude removed has no block left to
    // go to in a round. It comes here rather than vanishing (subunits.js
    // pruneMarks), quoting what it was about, one press away from sending.
    document.addEventListener("annotate:orphan-comment", (ev) => {
      const { text, quote } = ev.detail || {};
      if (!text) return;
      const quoted = quote ? quote.split("\n").map(l => "> " + l).join("\n") + "\n\n" : "";
      input.value = (input.value.trim() ? input.value.trimEnd() + "\n\n" : "") + quoted + text;
      sync();
      if (statusEl) {
        statusEl.textContent =
          "A section you commented on was removed; your comment moved here.";
      }
    });
    // Same chord as the block cards: Enter is a newline, ⌘/Ctrl+Enter sends.
    // Plain-Enter-to-send once cost a user a multi-line answer mid-compose.
    input.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); send(); }
    });
    sendBtn.addEventListener("click", send);
  })();

  // ── Top-bar panels ───────────────────────────────────────────────────────
  // Two one-shot controls used to hold permanent space above the first word: a
  // full-width "comment on the whole response" trigger row, and a centred
  // legend pill. Both now hang off icon buttons in the page header.
  //
  // They open differently, on purpose, because they are used differently. The
  // composer is somewhere you WRITE, so it opens as a band of the bar with the
  // full column width; pushing the document down for as long as you are typing
  // is fine. The legend is something you GLANCE at, so it opens as a popover
  // over the document — nudging every sentence down to answer "what does the
  // trash button do?" would be absurd. Same shell here, different geometry in
  // the stylesheet; see .general-composer and .legend-pop in style.css.
  // Runs at parse time, alongside initTopPanels below: the controls are
  // server-rendered, so they exist before any block does, and painting the
  // stored preference now avoids a flash of the default measure.
  wireViewControls();

  (function initTopPanels() {
    // Each panel is (toggle button, panel element, what to focus on open).
    const panels = [
      { btn: document.getElementById("composer-toggle"),
        el: document.getElementById("general-composer"),
        focus: () => document.getElementById("general-input") },
      // One panel where there were four: settings, the legend and the resume
      // command are panes of this one now, not popovers of their own. The
      // pane machinery is initMenuPanes below; everything else about opening
      // and closing — Esc, click-outside, one-at-a-time, aria-expanded — is
      // this function's and is unchanged.
      { btn: document.getElementById("menu-toggle"),
        el: document.getElementById("menu-pop"),
        focus: () => null, dismissOnOutsideClick: true },
    ].filter((p) => p.btn && p.el);
    if (!panels.length) return;

    const isOpen = (p) => !p.el.hidden;

    function close(p, { restoreFocus = false } = {}) {
      if (!isOpen(p)) return;
      // Move focus off the panel BEFORE hiding it: blurring a display:none
      // element drops focus to <body>, and the Esc-to-close path is meant to
      // hand the keyboard back to the button you opened it with.
      const inside = p.el.contains(document.activeElement);
      p.el.hidden = true;
      p.btn.setAttribute("aria-expanded", "false");
      if (restoreFocus || inside) p.btn.focus();
    }

    function open(p) {
      // One at a time. Two panels open at once would stack a popover on top of
      // a band and leave two toggles lit with no way to tell which owns what.
      panels.forEach((other) => { if (other !== p) close(other); });
      if (isOpen(p)) return;
      p.el.hidden = false;
      p.btn.setAttribute("aria-expanded", "true");
      p.focus()?.focus();
    }

    const toggle = (p) => (isOpen(p) ? close(p, { restoreFocus: true }) : open(p));

    panels.forEach((p) => {
      p.btn.addEventListener("click", (e) => { e.preventDefault(); toggle(p); });
    });

    // Esc closes whichever panel is open, and takes precedence over the page's
    // other two Esc handlers (search.js clears the query, subunits.js closes a
    // per-unit composer). Capture phase + stopPropagation is what buys that
    // precedence, and it is a deliberate ordering, not just defensiveness: an
    // open panel is the most recent thing the user opened, so it is what they
    // mean by "close this". Both other handlers are already conditional on
    // focus being in their own field, and neither can be reached without a
    // panel ALSO being open, so nothing is stranded — the early return below
    // leaves their Esc untouched whenever no panel is open, which is the
    // overwhelmingly common case.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const open_ = panels.find(isOpen);
      if (!open_) return;
      e.preventDefault();
      e.stopPropagation();
      close(open_, { restoreFocus: true });
    }, true);

    // Click-outside, for the popovers only. The composer is deliberately
    // exempt: it can hold half-written text, and losing that to a stray click
    // on the document would be the worst bug in this file. That exemption is
    // now carried by a per-panel flag rather than by naming the legend, so a
    // new popover opts in instead of being silently left out.
    document.addEventListener("click", (e) => {
      panels.forEach((p) => {
        if (!p.dismissOnOutsideClick) return;
        if (!isOpen(p)) return;
        if (p.el.contains(e.target) || p.btn.contains(e.target)) return;
        close(p);
      });
    });

    // The `/` shortcut in search.js reaches the search field with
    // input.focus() and no click, so the click-outside handler above never
    // fires for it. Left alone, an open panel would only be masked by the
    // takeover's CSS (.header-actions > *:not(.header-search)) — still open
    // underneath — and would resurface the moment the field gives up the
    // takeover. `focusin` bubbles (plain `focus` does not), so one
    // document-level listener catches focus landing on the field however it
    // got there.
    document.addEventListener("focusin", (e) => {
      if (e.target.id !== "block-search") return;
      panels.forEach((p) => { if (isOpen(p)) close(p); });
    });

    // The `g` shortcut, unchanged in behaviour: it opens the composer from
    // anywhere you are not already typing.
    const composer = panels[0];
    document.addEventListener("keydown", (e) => {
      if (e.key !== "g" && e.key !== "G") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active && active.isContentEditable);
      if (typing) return;
      if (!composer || isOpen(composer)) return;
      e.preventDefault();
      open(composer);
    });
  })();

  // ── Menu panes ───────────────────────────────────────────────────────────
  // Settings and the legend used to be popovers with their own toggles in the
  // bar. They are panes of the one menu now, pushed and popped by a data
  // attribute; the stylesheet shows exactly one pane at a time.
  //
  // The reset-to-root hangs off the panel being HIDDEN rather than off the
  // toggle being clicked, and deliberately: initTopPanels closes this panel
  // from four different places (its own toggle, Esc, a click outside, another
  // panel opening), and only one of them is a click on the button. Watching
  // the attribute catches all four without knowing about any of them.
  (function initMenuPanes() {
    const pop = document.getElementById("menu-pop");
    if (!pop) return;
    //
    // The panel is a DISCLOSURE, not a dialog. It carried role="dialog" with
    // no aria-modal and no focus move on open, which is a role claiming three
    // things none of which were true. The honest options were to make it a
    // real dialog or to stop saying it was one; it is a panel hung off a
    // button that already carries aria-expanded and aria-controls, and that
    // needs no role at all. So the role is gone rather than the behaviour
    // being grown to match it.
    //
    // Focus does move between PANES, which is a different question: switching
    // one used to write the attribute and nothing else, so the row you clicked
    // went display:none under the caret and activeElement stayed on a hidden
    // element. Tab recovered (it landed on .menu-back) so nothing was
    // stranded, but nothing announced the pane either.
    pop.querySelectorAll("[data-pane-to]").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.preventDefault();
        const to = b.dataset.paneTo;
        const from = pop.dataset.pane;
        pop.dataset.pane = to;
        if (to === "root") {
          // Back where you came from: the root row that pushed the pane just
          // left, found by the pane it points at rather than by remembering
          // it, so the two can never drift.
          pop.querySelector('.menu-pane[data-pane-name="root"] '
            + '[data-pane-to="' + from + '"]')?.focus();
        } else {
          // The new pane's own header, which is both the first thing in it
          // and the way out of it.
          pop.querySelector('.menu-pane[data-pane-name="' + to + '"] '
            + '.menu-back')?.focus();
        }
      });
    });
    new MutationObserver(() => {
      if (pop.hidden) pop.dataset.pane = "root";
    }).observe(pop, { attributes: true, attributeFilter: ["hidden"] });
  })();

  // ── The highlighter's menu tile ──────────────────────────────────────────
  // The one proxy in the menu, and a proxy precisely because its real element
  // cannot come here: the highlighter is a MODE, so its button stays in the
  // bar as the only indicator that dragging over text now marks it. This tile
  // clicks that button and mirrors it, which keeps highlighter.js the single
  // owner of the state — a second copy of "is it on" would be one more thing
  // to keep in step, and this page has been bitten by that before.
  (function initHighlighterMenuRow() {
    const row = document.getElementById("menu-highlighter");
    const btn = document.getElementById("highlighter-toggle");
    if (!row || !btn) return;
    row.addEventListener("click", (e) => { e.preventDefault(); btn.click(); });
    // The row is a tile now, and a tile says "on" with colour alone (the
    // stylesheet reads aria-pressed): there is no on/off word to keep in step.
    function sync() {
      const on = btn.getAttribute("aria-pressed") === "true";
      row.setAttribute("aria-pressed", on ? "true" : "false");
      // highlighter.js hides the toggle when the browser has no Highlight
      // API. A menu tile for a feature that cannot run is worse than none.
      row.hidden = btn.hidden;
    }
    new MutationObserver(sync).observe(
      btn, { attributes: true, attributeFilter: ["aria-pressed", "hidden"] });
    sync();
  })();


  // ── Keyboard review (j / k / c / f) ──────────────────────────────────────
  // Everything that decides anything in this page started with the mouse: the
  // controls live in a strip that only exists while the pointer is over a
  // 26px band, so working down a twelve-block plan meant twelve hover-and-aim
  // cycles. The page already spoke some keyboard — `/` searches, `g` opens the
  // composer, ⌘K⌘J folds — so what was missing was the middle of the
  // vocabulary: move to the next block, and act on the one you are looking at.
  //
  // The cursor is one attribute, data-kb-focus on the section. Everything else
  // follows from it in CSS, including revealing that block's control strip —
  // which is how a keyboard user reaches controls that are otherwise painted
  // in only by :hover.
  (function initKeyboardReview() {
    let focusId = null;

    // Blocks in document order, minus anything a search has hidden: k and j
    // should walk what is on screen, not what the DOM still holds.
    function blocks() {
      return [...document.querySelectorAll("section.block[data-block-id]")]
        .filter((b) => b.offsetParent !== null);
    }

    function paint() {
      document.querySelectorAll("[data-kb-focus]").forEach((b) => {
        delete b.dataset.kbFocus;
      });
      if (!focusId) return null;
      const el = document.querySelector(
        `section.block[data-block-id="${cssEsc(focusId)}"]`);
      if (!el) { focusId = null; return null; }
      el.dataset.kbFocus = "1";
      return el;
    }

    function move(delta) {
      const list = blocks();
      if (!list.length) return;
      let i = list.findIndex((b) => b.dataset.blockId === focusId);
      // No cursor yet: j starts at the top of what you can see rather than at
      // the top of the document, because the first j after scrolling should
      // not throw you back to block one.
      if (i === -1) {
        const firstVisible = list.findIndex(
          (b) => b.getBoundingClientRect().bottom > 0);
        i = firstVisible === -1 ? 0 : firstVisible;
      } else {
        i = Math.min(list.length - 1, Math.max(0, i + delta));
      }
      focusId = list[i].dataset.blockId;
      const el = paint();
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function focused() {
      return focusId
        ? document.querySelector(`section.block[data-block-id="${cssEsc(focusId)}"]`)
        : null;
    }

    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active && active.isContentEditable);
      if (typing) return;

      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const delta = e.key === "j" ? 1 : -1;
        // Inside a collapsed choice queue, J/K walk its questions first; past
        // either end they fall through to the ordinary block walk.
        const next = focusId && window.AnnotateChoiceQueue?.stepFrom(focusId, delta);
        if (next) {
          focusId = next;
          const el = paint();
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
        move(delta);
        return;
      }
      if (e.key === "c") {
        const el = focused();
        if (!el) return;
        e.preventDefault();
        // Same entry point the selection menu's Comment uses, so the two paths
        // cannot drift: step scoping, selection capture, the one-editor
        // rule and its refusal all behave identically.
        openAnnotation(el, "comment", {});
        return;
      }
      if (e.key === "f") {
        const el = focused();
        if (!el) return;
        e.preventDefault();
        const chev = el.querySelector(".card-chevron");
        const next = !el.classList.contains("collapsed");
        applyCollapsed(el, chev, next);
        try { localStorage.setItem(collapseKey(el.dataset.blockId), next ? "1" : "0"); }
        catch (_) {}
        return;
      }
      if (e.key === "Escape" && focusId) {
        // Last in the chain on purpose: the panel machinery binds Escape in
        // the capture phase and stops the event when a panel is open, so this
        // only ever runs when Escape had nothing else to close.
        focusId = null;
        paint();
      }
    });

    // A block Claude rewrites is replaced, not mutated, so the cursor has to
    // be repainted onto the new element or it silently disappears mid-round.
    window.AnnotateKeyboard = {
      repaint: paint,
      focusedId: () => focusId,
      // Used by the progress pill's "jump to the next untouched block": the
      // cursor and the jump must be the same cursor, or the page would have
      // two ideas of where you are.
      focusBlock: (id) => { focusId = id; paint(); },
    };
  })();

  // ── Fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J) ─────────────────────────
  // The user's VS Code fold bindings, verbatim. ⌘K arms a two-step chord —
  // intercepted so the browser's address-bar focus never fires — and the
  // second key acts on every card through the same applyCollapsed +
  // localStorage path the per-card chevron uses, so a fold-all survives
  // reload and a single chevron click afterwards still toggles one card.
  (function () {
    let armed = null; // timeout id while waiting for the second chord key
    const pill = document.createElement("div");
    pill.className = "chord-pill";
    pill.textContent = "⌘K …";
    pill.hidden = true;
    document.body.appendChild(pill);

    function disarm() {
      if (armed !== null) { clearTimeout(armed); armed = null; }
      pill.hidden = true;
    }

    function foldAll(collapsed) {
      document.querySelectorAll("section.block.card").forEach((section) => {
        const chev = section.querySelector(".card-chevron");
        applyCollapsed(section, chev, collapsed);
        try {
          localStorage.setItem(collapseKey(section.dataset.blockId), collapsed ? "1" : "0");
        } catch (_) {}
      });
    }

    document.addEventListener("keydown", (e) => {
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        (active && active.isContentEditable);
      if (typing) { disarm(); return; }
      if (armed === null) {
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey &&
            (e.key === "k" || e.key === "K")) {
          e.preventDefault();
          pill.hidden = false;
          armed = setTimeout(disarm, 2000);
        }
        return;
      }
      // While armed, the modifier keys themselves (releasing/re-pressing ⌘
      // between the two strokes) neither resolve nor cancel the chord.
      if (e.key === "Meta" || e.key === "Control" || e.key === "Shift" || e.key === "Alt") return;
      if ((e.metaKey || e.ctrlKey) && e.key === "0") {
        e.preventDefault();
        foldAll(true);
      } else if ((e.metaKey || e.ctrlKey) && (e.key === "j" || e.key === "J")) {
        e.preventDefault();
        foldAll(false);
      }
      disarm();
    });
  })();

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
        const timer = document.createElement("span");
        timer.className = "bb-timer";
        // No sub-label node. One was created here for a promised "3 of 5 marks
        // applied" progress line, but nothing could write it: the old
        // PostToolUse hook that once captioned it mapped tool names onto a
        // fixed allowlist ("Editing the response…", "Working…") and knew
        // nothing about mark counts. An empty span still consumed a flex gap.
        banner.append(spin, label, timer);
        banner.dataset.startedAt = String(Date.now());
        // Place the lock ribbon at the top of the content (just under the
        // header, above the composer) so it pins flush to the top of the
        // screen when the page scrolls — not buried below the composer.
        const header = document.querySelector(".page-header");
        if (header) header.insertAdjacentElement("afterend", banner);
        // Fallback for a shell with no header at all. It used to anchor on
        // .general-composer, which is now a band of the top bar — landing the
        // ribbon inside the chrome it is supposed to sit below. The document
        // itself is the only anchor that still means "top of the content".
        else proseEl?.parentNode?.insertBefore(banner, proseEl);
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

  // The statusline strip was here: a live mirror of the terminal's context
  // %, model, rate limits and diff, polled from GET <base>/statusline.
  //
  // It worked because annotate's own server read a snapshot file off the disk
  // on request. The daemon that replaced it is deliberately not allowed to
  // read arbitrary paths, and that restraint is worth more than the widget —
  // so compat.js answered the route with {ok:false} and the strip hid itself
  // for good. This removes ~70 lines of renderer, its CSS and its markup,
  // which had been kept alive only by a shim hard-wired to say "no".
  //
  // Reviving it means giving the daemon a real route with a real source of
  // truth, not restoring this code.

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
          "Claude's session is gone. Your last submission is still queued — " +
          "it will be picked up when a Claude session reattaches to this page. " +
          "Run `/annotate resume` from a Claude session to continue. " +
          "Don't resubmit; it would apply the same round twice.";
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
  // Did the busy window we are currently inside actually contain a ROUND?
  //
  // `data.busy` is true while ANY event is unacked — a general comment or a
  // choice pick raises it exactly like a round does. Without this gate every
  // busy false→true→false cycle computed a change set, and computeChangeSet
  // attributed it against `submittedBlockIds()` — the block ids of whatever
  // round was submitted LAST. So a general comment two exchanges later grew a
  // change bar for a round the user never fired, with "you asked" chips citing
  // that stale round.
  //
  // Recomputed from pendingEvents at the busy START edge, which is
  // authoritative: a round entry is only removed from that map when its ack
  // lands. Also set by registerRoundEvent, because a round's POST can resolve
  // AFTER the poll that first saw busy — in that race the start edge would
  // have found nothing.
  let windowHadRound = false;
  const hasPendingRound = () => {
    for (const p of pendingEvents.values()) if (p.round) return true;
    return false;
  };
  // Set on the ack, consumed after the next reconcile: the diff needs the
  // post-round markdown from /raw and the refreshed sections in the DOM.
  let pendingChangeSet = null;

  // Which blocks moved, and who moved them. The user's own set is whatever
  // they submitted — captured at submit time in subunits.js, because
  // clearRound() wipes the marks on ack and this is the only surviving
  // record. Everything else that moved was the coherence sweep.
  //
  // A block that still reads as this page itself last saved it (the reader's
  // own edit) is nobody's change to report, unless Claude wrote over it.
  // Matched by content (every field the author writes), not by version:
  // under load the daemon's version for a block can run ahead of the one its
  // PUT answered with. Forgotten once a round's change set is applied.
  const pageWrites = new Map();
  const AUTHORED = ["markdown", "title", "change_note"];
  const sameAsWritten = (w, b) => !!b && (w.kind || "markdown") === (b.kind || "markdown")
    && AUTHORED.every((k) => (w[k] ?? "") === (b[k] ?? ""));
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
      // A queued question off screen is display:none and cannot be scrolled to.
      window.AnnotateChoiceQueue?.show(changed[idx].blockId);
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

  // ── The pane ──────────────────────────────────────────────────────────────
  //
  // The diff itself lives in static/diff.js, as pure functions over two
  // strings, and is covered by tests/diff_engine.test.cjs. Everything here is
  // DOM: materialise what the engine returned, wire the three controls, and
  // stay out of the algorithm's way.
  //
  // The pane offers two views of the same rows because they answer different
  // questions and both get asked:
  //
  //   reader  the new text as prose, additions tinted, deletions folded into
  //           a chip. Answers "what does it say now".
  //   diff    paragraph by paragraph, both sides on show, unchanged runs
  //           collapsed. Answers "what exactly moved", and is where you go
  //           the moment you do not trust the reader view.
  //
  // Reader is the default: it is the question people arrive with. The choice
  // is remembered, because someone who wants the diff view wants it for the
  // whole round, not for one card.

  const DIFF_VIEW_KEY = "annotate.diffview";
  const DIFF_VIEWS = [["reader", "reader"], ["diff", "diff"]];
  let diffView = (() => {
    try {
      const v = localStorage.getItem(DIFF_VIEW_KEY);
      return DIFF_VIEWS.some(([id]) => id === v) ? v : "reader";
    } catch { return "reader"; }
  })();

  // vnode -> DOM. A string kid is ALWAYS a text node, which is what keeps
  // arbitrary block markdown from becoming markup: there is no path here that
  // parses HTML, so a block containing "<img onerror=...>" renders those
  // characters and nothing else. diff.js builds the tree; nobody builds an
  // HTML string anywhere along the way.
  function materialize(node) {
    if (typeof node === "string") return document.createTextNode(node);
    const el = document.createElement(node.tag);
    if (node.cls) el.className = node.cls;
    for (const k of Object.keys(node.attrs || {})) el.setAttribute(k, node.attrs[k]);
    for (const kid of node.kids || []) el.appendChild(materialize(kid));
    return el;
  }

  // Recognised change_note line labels, in the order the contract documents
  // them (see references/handling-events.md § "Explaining a change").
  const CHANGE_NOTE_LABELS = ["Why:", "Lost:"];

  // Task 5's per-block change note: free-form text Claude may attach to a
  // rewrite, optionally carrying a `Why:` line and — for a compact that
  // dropped detail — a `Lost:` line. Rendered ABOVE the diff, not below it: a
  // one-line reason makes the marks underneath legible, and on a compact the
  // `Lost:` line is the single most valuable thing in the pane and the one
  // place a user can ever learn what was discarded. It should not be the last
  // thing you scroll to.
  //
  // Each line gets its own row rather than one blob: a fixed leading label
  // would double up against a note that already starts with "Why:", and
  // folding a `Lost:` line into the same paragraph buries it. The field is
  // optional and free-form, so this must still render sensibly with no
  // recognised label, extra blank lines, or only a `Why:` line.
  function renderChangeNote(note) {
    if (typeof note !== "string" || !note.trim()) return null;
    const why = document.createElement("div");
    why.className = "diff-why";
    for (const rawLine of note.trim().split("\n")) {
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
    return why.children.length ? why : null;
  }

  function renderViewSwitch() {
    const wrap = document.createElement("span");
    wrap.className = "diff-views";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "How to show the change");
    for (const [id, label] of DIFF_VIEWS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "diff-view-btn";
      b.dataset.view = id;
      b.textContent = label;
      b.setAttribute("aria-pressed", String(id === diffView));
      wrap.appendChild(b);
    }
    return wrap;
  }

  // Repaint every open pane's switch after a choice, so the setting reads as
  // a document-wide preference rather than a per-card accident.
  function applyDiffView(view) {
    diffView = view;
    try { localStorage.setItem(DIFF_VIEW_KEY, view); } catch { /* private mode */ }
    document.querySelectorAll(".diff-pane").forEach(pane => {
      pane.dataset.view = view;
      pane.querySelectorAll(".diff-view-btn").forEach(b => {
        b.setAttribute("aria-pressed", String(b.dataset.view === view));
      });
    });
  }

  function renderDiffPane(section, c, blk, before) {
    section.querySelector(".diff-pane")?.remove();
    const now = blk.markdown || "";
    if (now === before) return;

    const D = window.AnnotateDiff;
    // No engine (a stale cached page, a blocked asset) is not a reason to
    // lose the attribution chip and the change note as well.
    const rows = D ? D.alignUnits(D.splitUnits(before), D.splitUnits(now)) : null;

    const pane = document.createElement("div");
    pane.className = "diff-pane";
    pane.dataset.view = diffView;

    const h = document.createElement("div");
    h.className = "diff-h";
    const label = document.createElement("span");
    label.textContent = `changed from v${c.from}`
      + (c.bySweep ? " — you did not mark this section" : "");
    const spacer = document.createElement("span");
    spacer.className = "diff-h-space";
    h.append(label, spacer);
    if (rows) h.appendChild(renderViewSwitch());
    pane.appendChild(h);

    const note = renderChangeNote(blk.change_note);
    if (note) pane.appendChild(note);

    if (rows) {
      pane.appendChild(materialize(D.renderReader(rows)));
      pane.appendChild(materialize(D.renderUnified(rows)));
    }

    const body = section.querySelector(".card-body");
    if (body) body.insertAdjacentElement("afterend", pane);
    else section.appendChild(pane);
  }

  // One delegated listener for every pane on the page: panes come and go on
  // every round, and re-binding per pane is how listeners leak.
  document.addEventListener("click", (ev) => {
    const view = ev.target.closest?.(".diff-view-btn");
    if (view) { ev.stopPropagation(); applyDiffView(view.dataset.view); return; }

    // Open a folded deletion in place. One-way on purpose: having asked what
    // was cut, you are reading the answer, and a chip that re-hides it invites
    // clicking twice and losing it again.
    const cut = ev.target.closest?.(".d-cut");
    if (cut) {
      ev.stopPropagation();
      const del = document.createElement("del");
      del.className = "d-cut-open";
      del.textContent = cut.getAttribute("data-cut") || "";
      cut.replaceWith(del);
      return;
    }

    const fold = ev.target.closest?.(".d-fold");
    if (fold) {
      ev.stopPropagation();
      const box = fold.nextElementSibling;
      if (!box || !box.classList.contains("d-fold-body")) return;
      const opening = box.hasAttribute("hidden");
      if (opening) box.removeAttribute("hidden"); else box.setAttribute("hidden", "");
      fold.setAttribute("aria-expanded", String(opening));
      const n = box.children.length;
      fold.textContent = opening
        ? "▾ hide unchanged"
        : "… " + n + " unchanged paragraph" + (n > 1 ? "s" : "");
    }
  });


  // The pre-round snapshot: the document as it stood when the round was
  // queued, which is the only record of what a block used to say. Read-only,
  // so it works on a shared read-only link too.
  //
  // `<base>/prev` is NOT a route on the daemon and 404s if you curl it. It is
  // synthesised in the page by compat.js, which patches window.fetch and reads
  // the __prev__ item push.py writes. That is by design, and testing it from
  // outside the browser has already been mistaken once for three silently
  // broken features — see test_smoke_route_shim.py.
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
      windowHadRound = hasPendingRound();
    } else if (!busyNow && wasBusy) {
      // Only a round earns a change bar. A general comment or a choice pick
      // also opens and closes a busy window, and the blocks Claude rewrites
      // answering one of those were not asked for by any round — attributing
      // them against the last round's block ids is how the bar started lying.
      let changed = [];
      if (windowHadRound) {
        changed = computeChangeSet(roundBaseVersions, data.blocks);
        // The bar has now finished consuming the submitted set: this line is
        // the LAST read of it (applyChangeSet only carries the already-derived
        // `bySweep` flag). Cleared here rather than in clearRound() because
        // that runs on the ack, which can land a poll or more before busy goes
        // false when a second event is still in flight — clearing there would
        // hand computeChangeSet an empty asked-set and label the user's own
        // marked blocks "sweep".
        window.AnnotateSubunits?.clearSubmittedBlockIds?.();
      }
      windowHadRound = false;
      roundBaseVersions = null;
      if (changed.length) pendingChangeSet = changed;
      // Nothing to attribute: the round is answered, so the reader's saves
      // during it are settled too.
      else pageWrites.clear();
    }
    wasBusy = busyNow;
    setBusy(busyNow);
    setAttachedPill(data.attached);
    // 1. Clear spinners for comments Claude finished processing.
    handleConsumedEvents(data.consumed_events);
    if (window.AnnotateSubunits) window.AnnotateSubunits.onPoll(data);
    // 2. Reconcile the DOM against the full document. /raw carries everything
    //    (per-block markdown/svg + version + glossary), so one fetch covers
    //    structure, content, and glossary in a single pass.
    fetch(BASE + "raw", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null)
      .then(doc => {
        if (!doc) return;
        if ((doc.response_id || "") !== (document.body.dataset.responseId || "")) {
          startNewResponse(doc);
        }
        reconcile(doc);
        syncGlossary(doc);
        // Attribution lands only after reconcile: the chips hang off the
        // refreshed sections (a kind flip rebuilds the whole card) and the
        // diff needs this doc's post-round markdown.
        if (pendingChangeSet) {
          const byId = new Map((doc.blocks || []).map(b => [b.id, b]));
          const changed = pendingChangeSet.filter((c) => {
            const w = pageWrites.get(c.blockId);
            return !w || !sameAsWritten(w, byId.get(c.blockId));
          });
          pendingChangeSet = null;
          pageWrites.clear();
          // Not chained into the outer .catch: it is a floating promise, so
          // without this a throw becomes an unhandled rejection. The bar and
          // the panes that did render stay put.
          applyChangeSet(changed, doc)
            .catch(e => console.warn("change attribution failed", e));
        }
      })
      .catch(() => { /* swallow — next tick retries */ });
  }

  // Claude pushed a new response into this session. The page read the
  // response id once, at load, and kept keying marks and drafts by it — so the
  // first response's marks sat in the dock over the second response's
  // same-numbered sections, and Submit would have applied them there.
  function startNewResponse(doc) {
    const rid = doc.response_id || "";
    document.body.dataset.responseId = rid;
    const hdr = document.getElementById("hdr-respid");
    if (hdr) hdr.textContent = rid;
    if (doc.title) {
      document.title = doc.title;
      const t = document.getElementById("hdr-title");
      if (t) t.textContent = doc.title;
    }
    try { localStorage.removeItem(STORAGE_KEY); } catch {}
    STORAGE_KEY = `annotate.drafts.${rid}`;
    annotations = loadDrafts();
    renderComments();
    window.AnnotateSubunits?.resetForResponse(rid);
  }

  function syncGlossary(doc) {
    if (!window.AnnotateGlossary) return;
    const prev = JSON.stringify(window.AnnotateGlossary._lastGlossary || []);
    const next = JSON.stringify(doc.glossary || []);
    if (next !== prev) {
      window.AnnotateGlossary.setGlossary(doc.glossary || []);
      window.AnnotateGlossary._lastGlossary = doc.glossary || [];
      window.AnnotateGlossary.refreshAll();
      // Redecoration rebuilds text nodes: rebuild the span ranges from text.
      window.AnnotateSubunits?.paintSpans?.();
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
    refreshPageState();

    // Remove sections (and their inline-comments wrapper) for deleted blocks,
    // clearing any running updating-timer so it can't leak.
    let orphanedDraft = false;
    let removedAny = false;
    proseEl.querySelectorAll("section.block").forEach(section => {
      if (!serverIds.has(section.dataset.blockId)) {
        // Open in the editor: the reader's text is in there and nowhere else.
        // The section stays until they have copied it and closed.
        if (section.dataset.editing != null) {
          if (!section._removed) {
            section._removed = true;
            window.AnnotateEdit?.removed?.(section.dataset.blockId);
          }
          return;
        }
        clearUpdatingOverlay(section);
        untrackMockupFrames(section);
        const ic = section.nextElementSibling;
        if (ic && ic.classList.contains("inline-comments")) ic.remove();
        section.remove();
        removedAny = true;
        for (const a of Object.values(annotations)) {
          if (a.block_id !== section.dataset.blockId) continue;
          orphanedDraft = true;
          // An open card's typed words go where a pinned comment's do.
          if ((a.comment || "").trim()) {
            document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
              { detail: { text: a.comment.trim(), quote: a.selected_text || "" } }));
          }
        }
      }
    });
    // Pending round marks on a removed block are pruned now, not at the next
    // Submit: the dock must stop listing them, and a comment among them moves
    // to the general box while the reader can still see it happen.
    if (removedAny) window.AnnotateSubunits?.renderDock();
    // The card went with its block, but the draft behind it did not, and one
    // open draft is the page's "someone is editing" lock: every other comment
    // icon refused to open until a reload. renderComments prunes it. Only
    // then, because it rebuilds every card, which would take the caret from a
    // reader typing in some other one.
    if (orphanedDraft) renderComments();

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

    // Sections inserted above were built detached; paint their block marks.
    window.AnnotateSubunits?.repaintBlocks();
    applyEngagedStyling();
    document.dispatchEvent(new CustomEvent("annotate:rendered"));
  }

  // Where the caret is inside a card that is about to be rebuilt. A rebuilt
  // choice block dropped focus to <body>, so the reader's next keystrokes
  // went nowhere, or into the page's own letter shortcuts.
  function focusWithin(section) {
    const el = document.activeElement;
    if (!el || !section.contains(el)) return null;
    if (el.classList.contains("choice-note")) {
      return { note: true, start: el.selectionStart, end: el.selectionEnd };
    }
    const opt = el.closest(".choice-option");
    if (opt) {
      const i = [...section.querySelectorAll(".choice-option")].indexOf(opt);
      return { option: i };
    }
    return null;
  }

  function restoreFocus(section, focus) {
    if (!focus) return;
    if (focus.note) {
      const note = section.querySelector(".choice-note");
      if (!note) return;
      note.focus({ preventScroll: true });
      const end = note.value.length;
      note.setSelectionRange(Math.min(focus.start, end), Math.min(focus.end, end));
    } else if (typeof focus.option === "number") {
      const opts = section.querySelectorAll(".choice-option");
      const el = opts[Math.min(focus.option, opts.length - 1)];
      if (el) el.focus({ preventScroll: true });
    }
  }

  // Refresh one block's content in place. Returns the section now in the DOM
  // (a fresh node when the block's kind flipped). Clears the updating overlay
  // as a fallback for the case where the refreshed block IS the commented one.
  function updateBlockContent(section, blk, srvVer) {
    // A section open in the editor is the reader's until they close it: a
    // rewrite landing now would destroy the editor and their words. The
    // newest server block waits on the section, and edit.js applies it on
    // close when it is newer than what the reader saved.
    if (section.dataset.editing != null) {
      const v = parseInt(blk.version ?? srvVer, 10) || 0;
      const had = section._pendingBlock;
      if (!had || v >= had.version) section._pendingBlock = { block: blk, version: v };
      return section;
    }
    const newKind = blk.kind || "markdown";
    const oldKind = section.dataset.kind || "markdown";
    // A kind flip (markdown↔sequence/diagram/choice) needs a fresh section:
    // the diagram click listener and hover wiring are bound at creation, so an
    // in-place innerHTML swap would leave them inconsistent with the new kind.
    if (newKind !== oldKind || newKind === "choice" || newKind === "mockup") {
      const focus = focusWithin(section);
      const fresh = createBlockSection(blk);
      clearUpdatingOverlay(section);
      untrackMockupFrames(section);
      section.replaceWith(fresh);
      restoreFocus(fresh, focus);
      return fresh;
    }
    const content = section.querySelector(".block-content");
    if (content) {
      if (newKind === "sequence") {
        // Both halves again. The pairing listeners live on .block-content,
        // which survives this swap.
        paintSequence(content, blk);
      } else if (newKind === "flowchart") {
        // Without this a flowchart fell through to the markdown branch below and
        // rendered blk.markdown — which a flowchart does not have — so updating
        // one in place blanked the chart. The click and hover listeners live on
        // .block-content, which survives the repaint.
        paintFlowchart(content, blk);
      } else if (blockMd) {
        content.innerHTML = blockMd.render(blk.markdown || "");
        sanitizeFreeHtml(content);
        if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
      }
    }
    section.dataset.kind = newKind;
    section.dataset.version = String(blk.version ?? srvVer);
    renderVersionBadge(section, blk.version ?? srvVer);
    setCardTitle(section, blk);
    section._mine = Array.isArray(blk.mine) ? blk.mine : [];

    // A rewrite must not leave a card with stale panes: drop whatever was
    // there and repaint fresh from this version's anchors.
    const oldCol = section.querySelector(".code-col");
    if (oldCol) oldCol.remove();
    const freshCol = renderCodeColumn(blk);
    if (freshCol) {
      section.dataset.hasCode = "1";
      (section.querySelector(".card-body") || section).appendChild(freshCol);
    } else {
      delete section.dataset.hasCode;
    }

    clearUpdatingOverlay(section);
    return section;
  }

  // ── Boot ───────────────────────────────────────────────────────────────────

  // subunits.js owns the round; script.js owns the poll loop and pendingEvents.
  // The round has to land in pendingEvents or hasPendingRound() (and
  // handleConsumedEvents' clearing on ack) never see it.
  window.AnnotatePage = {
    // A round is in flight: the page is locked until Claude answers it.
    isBusy: () => document.body.classList.contains("is-busy"),
    // edit.js saved this version of a block: the reader's, not Claude's.
    wrote(blockId, body) { if (blockId && body && typeof body === "object") pageWrites.set(blockId, { ...body }); },
    // The page's own markdown rendering, sanitised as a card's is.
    renderMarkdown(text) {
      const div = document.createElement("div");
      div.innerHTML = blockMd ? blockMd.render(text || "") : "";
      if (!blockMd) div.textContent = text || "";
      sanitizeFreeHtml(div);
      return div.innerHTML;
    },
    // Re-render one section from a block, as a server rewrite would.
    renderBlock(section, block, version) {
      const out = updateBlockContent(section, block, version);
      window.AnnotateSubunits?.repaintBlocks?.();
      document.dispatchEvent(new CustomEvent("annotate:rendered"));
      return out;
    },
    // The selection menu's Comment on a whole section opens the same rich
    // card the keyboard's `c` opens: one door for whole-section comments.
    openComment(blockId) {
      const section = document.querySelector(
        `section.block[data-block-id="${cssEsc(blockId)}"]`);
      if (section) openAnnotation(section, "comment", {});
    },
    registerRoundEvent(eventId, blockIds) {
      if (!eventId) return;
      pendingEvents.set(String(eventId), {
        round: true,
        blockIds: Array.isArray(blockIds) ? blockIds.slice() : [],
      });
      // The submit POST can resolve after the poll that first saw busy, in
      // which case the busy start edge already ran and found no round in
      // pendingEvents. Claim the open window here too.
      windowHadRound = true;
    },
  };

  WebCompanion.init({ onPollDelta });
  loadAndRenderBlocks();
})();
