/* dataflow — renders dataflow.json as a board of nodes and keeps it live.
 *
 * Two rules shape this file:
 *   1. Everything the reader needs is inside a node. There is no reference
 *      section, so an edge scrolls to its target instead of navigating away.
 *   2. Nothing Claude wrote is ever inserted as HTML. `summary`, `note` and
 *      member text go through `inline()`, which builds text nodes and honours
 *      exactly two markers — `code` and **bold**. A generator that emits a tag
 *      gets a visible tag, not an injection.
 */
(() => {
  "use strict";

  const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
  const KEY = decodeURIComponent((BASE.match(/^\/s\/([^/]+)\//) || [])[1] || "");

  let FLOW = null;
  let THREADS = {};                 // anchor -> {latest_synthesis, question, ...}
  const PENDING = new Set();        // anchors whose question is queued
  const OPEN = new Set();           // node ids expanded, preserved across renders

  /* ------------------------------------------------------------- helpers */
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  // `code` and **bold**, nothing else. Everything is a text node otherwise.
  function inline(text) {
    const frag = document.createDocumentFragment();
    const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
    let last = 0, m;
    while ((m = re.exec(String(text ?? ""))) !== null) {
      if (m.index > last) frag.append(String(text).slice(last, m.index));
      frag.append(el(m[1] != null ? "code" : "b", null, m[1] ?? m[2]));
      last = re.lastIndex;
    }
    frag.append(String(text ?? "").slice(last));
    return frag;
  }

  // Claude writes summaries with newlines; they are the node's shape, so they
  // must survive as line breaks rather than collapse into one run-on line.
  function multiline(text) {
    const frag = document.createDocumentFragment();
    String(text ?? "").split("\n").forEach((line, i) => {
      if (i) frag.append(el("br"));
      frag.append(inline(line));
    });
    return frag;
  }

  const anchorOf = (id) => "node:" + id;

  // Claude writes replies as raw markdown. `html: false` makes markdown-it
  // escape any tag in the source, so the rendered string is safe to assign —
  // the same setting annotate uses for comment bodies.
  const MD = (typeof window.markdownit === "function")
    ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: true })
    : null;

  // A link whose href is a repository-relative `path:line` is an editor
  // target, not a web address. Rewriting it to open through the server keeps
  // a citation in a reply as clickable as a member row.
  const EDITOR_HREF = /^(?!\w+:)([^\s?#]+\.[A-Za-z0-9]+):(\d+)$/;

  function markdown(text) {
    const box = el("div", "md");
    if (!MD) { box.textContent = String(text ?? ""); return box; }
    box.innerHTML = MD.render(String(text ?? ""));
    box.querySelectorAll("a[href]").forEach((a) => {
      const m = EDITOR_HREF.exec(a.getAttribute("href") || "");
      if (!m) {
        // A real URL: never navigate the page away from the diagram.
        a.target = "_blank";
        a.rel = "noreferrer noopener";
        return;
      }
      a.classList.add("editor-link");
      a.href = "#";
      a.title = "open " + m[1] + ":" + m[2];
      a.onclick = (ev) => { ev.preventDefault(); openInEditor(a, m[1], Number(m[2])); };
    });
    return box;
  }

  function toast(msg, bad) {
    let t = document.getElementById("toast");
    if (!t) { t = el("div"); t.id = "toast"; document.body.append(t); }
    t.textContent = msg;
    t.classList.toggle("bad", !!bad);
    t.classList.add("on");
    clearTimeout(t._x);
    t._x = setTimeout(() => t.classList.remove("on"), 3600);
  }

  /* ---------------------------------------------------------------- open */
  // The page cannot open a file itself: file:// is refused from an http origin
  // and jetbrains:// had to guess the project name. The server just runs the
  // opener. Failures show the server's own reason, never a guess.
  async function openInEditor(btn, file, line) {
    btn.disabled = true;
    try {
      const res = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: KEY, file, line }),
      });
      if (!res.ok) {
        btn.classList.add("failed");
        setTimeout(() => btn.classList.remove("failed"), 3000);
        toast((await res.text()) || "could not open", true);
      }
    } catch (_) {
      toast("server unreachable", true);
    }
    btn.disabled = false;
  }

  /* --------------------------------------------------------------- nodes */
  function nodeEl(n) {
    const wrap = el("div", "node" + (n.implicit ? " implicit" : ""));
    wrap.id = "n-" + n.id;
    wrap.dataset.layer = n.layer;
    wrap.dataset.nodeId = n.id;
    if (OPEN.has(n.id)) wrap.classList.add("open");

    /* head ------------------------------------------------------------- */
    const head = el("div", "nhead");
    const left = el("div");
    const role = el("div", "role");
    role.append(el("span", null, n.role));
    if ((n.edges || []).some((e) => e.join)) role.append(el("span", "pill join", "◆ JOIN"));
    if (n.flag) role.append(el("span", "pill flag", n.flag));
    left.append(role);
    const nm = el("div", "nm");
    nm.append(multiline(n.name));
    left.append(nm);
    if (n.summary) {
      const s = el("div", "sum");
      s.append(multiline(n.summary));
      left.append(s);
    }

    const acts = el("div", "acts");
    const jump = el("button", "ic idea", "⌘");
    jump.title = "open " + n.file + ":" + n.line + " in the editor";
    jump.onclick = (ev) => { ev.stopPropagation(); openInEditor(jump, n.file, n.line); };
    const anchor = anchorOf(n.id);
    const ask = el("button", "ic ask" + (THREADS[anchor] || PENDING.has(anchor) ? " has" : ""), "✻");
    ask.title = "ask Claude about this node";
    ask.onclick = (ev) => { ev.stopPropagation(); expand(wrap, true); openAskForm(wrap, n); };
    acts.append(jump, ask, el("span", "chev", "▸"));

    head.append(left, acts);
    head.onclick = () => expand(wrap, !wrap.classList.contains("open"));

    /* body ------------------------------------------------------------- */
    const body = el("div", "nbody");

    // The header's ⌘ already opens this file at this line, and every member row
    // opens its own. A third opener here was the same action in a third style.
    // The path's remaining job is telling you which module you are in, so it is
    // one quiet line, tail-truncated, with the whole path on hover.
    const path = el("div", "path");
    const segs = n.file.split("/");
    path.textContent = segs.length > 4 ? "…/" + segs.slice(-4).join("/") : n.file;
    path.title = n.file + ":" + n.line;
    body.append(path);

    if ((n.members || []).length) {
      const box = el("div", "members");
      n.members.forEach((m) => {
        // One row per member, carrying its real signature. A row with a
        // `detail` opens underneath itself: the reader stays on the line they
        // were reading instead of being sent to a panel about it.
        // A row with neither a badge nor a detail is supporting cast — an
        // injected field next to an endpoint. Structural, not a guess about
        // its text.
        const secondary = !m.tag && !m.detail;
        const row = el("div", "mem" + (m.detail ? " has-detail" : "")
                              + (secondary ? " secondary" : ""));
        const head = el("div", "mem-head");

        // The affordance goes where the eye starts, not in the far gutter.
        head.append(el("span", "mem-chev", m.detail ? "▸" : ""));

        const txt = el("span", "mem-sig");
        if (m.tag) {
          const tag = el("span", "mem-tag", m.tag);
          // An HTTP verb is what you scan a controller for; a `class` or
          // `record` badge is only structure. They should not look alike.
          if (/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(m.tag.trim())) {
            tag.classList.add("verb", "verb-" + m.tag.trim().toLowerCase());
          }
          txt.append(tag);
        }
        txt.append(inline(m.text));
        head.append(txt);

        const tools = el("span", "mem-tools");
        if (m.line) {
          const b = el("button", "ln", ":" + m.line);
          b.title = "open " + n.file + ":" + m.line;
          b.onclick = (ev) => { ev.stopPropagation(); openInEditor(b, n.file, m.line); };
          tools.append(b);
        }
        head.append(tools);
        row.append(head);

        if (m.detail) {
          const d = el("div", "mem-detail");
          d.append(markdown(m.detail));
          row.append(d);
          head.onclick = () => row.classList.toggle("open");
        }
        box.append(row);
      });
      body.append(box);
    }

    if ((n.edges || []).length) {
      const box = el("div", "edges");
      box.append(el("span", "lb", "reaches"));
      n.edges.forEach((e) => {
        const b = el("button", "edge" + (e.join ? " join" : ""), e.label + " → " + e.to);
        b.onclick = () => goTo(e.to);
        box.append(b);
      });
      body.append(box);
    }

    if (n.note) {
      const note = el("div", "note");
      note.append(inline(n.note));
      body.append(note);
    }

    const thread = el("div", "thread");
    thread.dataset.thread = n.id;
    body.append(thread);
    renderThread(thread, n);

    wrap.append(head, body);
    return wrap;
  }

  function expand(wrap, on) {
    wrap.classList.toggle("open", on);
    if (on) OPEN.add(wrap.dataset.nodeId); else OPEN.delete(wrap.dataset.nodeId);
  }

  function goTo(id) {
    const target = document.getElementById("n-" + id);
    if (!target) return;
    expand(target, true);
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("hit");
    setTimeout(() => target.classList.remove("hit"), 1600);
  }

  /* ------------------------------------------------------------- threads */
  function renderThread(box, n) {
    const anchor = anchorOf(n.id);
    const info = THREADS[anchor];
    const form = box.querySelector(".ask-form");
    box.replaceChildren();
    if (info) {
      if (info.question) {
        const q = el("div", "msg user");
        q.append(el("div", "who", "you"), document.createTextNode(info.question));
        box.append(q);
      }
      const a = el("div", "msg claude");
      a.append(el("div", "who", "✻ claude" + (info.title ? " — " + info.title : "")),
               markdown(info.latest_synthesis || ""));
      box.append(a);
    }
    if (PENDING.has(anchor)) {
      const p = el("div", "pending");
      p.append(el("i"), document.createTextNode("queued — waking Claude…"));
      box.append(p);
    }
    box.style.display = (info || PENDING.has(anchor) || form) ? "" : "none";
    if (form) box.append(form);
  }

  function openAskForm(wrap, n) {
    const box = wrap.querySelector("[data-thread]");
    box.style.display = "";
    if (box.querySelector(".ask-form")) {
      box.querySelector("textarea").focus();
      return;
    }
    const form = el("div", "ask-form");
    const ta = el("textarea");
    ta.placeholder = "ask about " + n.name.replace(/\s+/g, " ") + "…";
    const send = el("button", null, "ask");
    const submit = async () => {
      const text = ta.value.trim();
      if (!text) return;
      send.disabled = true;
      try {
        const res = await fetch(BASE + "api/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ anchor: anchorOf(n.id), type: "comment", text }),
        });
        if (!res.ok) {
          toast((await res.text()) || "could not send", true);
          send.disabled = false;
          return;
        }
      } catch (_) {
        toast("server unreachable", true);
        send.disabled = false;
        return;
      }
      PENDING.add(anchorOf(n.id));
      form.remove();
      renderThread(box, n);
      wrap.querySelector(".ic.ask").classList.add("has");
    };
    send.onclick = submit;
    // Enter sends, Shift+Enter breaks the line — the shape every chat box has.
    ta.onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
    };
    form.append(ta, send);
    box.append(form);
    ta.focus();
  }

  /* --------------------------------------------------------------- board */
  function render() {
    const doc = FLOW || {};
    const app = document.getElementById("app");
    app.replaceChildren();

    /* header */
    const header = el("header");
    const hdr = el("div", "hdr");
    const h1 = el("h1");
    h1.append(document.createTextNode("Dataflow — "), el("span", "seed", doc.seed || ""));
    const meta = el("div", "meta");
    const nodes = (doc.slices || []).reduce((a, s) => a + (s.nodes || []).length, 0);
    meta.append(document.createTextNode(
      nodes + " nodes · " + (doc.slices || []).length + " slices"), el("br"));
    const live = el("span", "live off");
    live.id = "live";
    live.append(el("i"), document.createTextNode("connecting…"));
    meta.append(live);
    hdr.append(h1, meta);

    const bar = el("div", "bar");
    const mk = (label, fn, on) => { const b = el("button", "tb" + (on ? " on" : ""), label); b.onclick = () => fn(b); return b; };
    bar.append(
      mk("expand all", () => document.querySelectorAll(".node").forEach((x) => expand(x, true))),
      mk("collapse all", () => document.querySelectorAll(".node").forEach((x) => expand(x, false))));
    const filter = el("input");
    filter.placeholder = "filter…";
    filter.oninput = () => {
      const q = filter.value.toLowerCase();
      document.querySelectorAll(".node").forEach((x) =>
        x.classList.toggle("dim", !!q && !x.textContent.toLowerCase().includes(q)));
    };
    bar.append(filter, el("span", "sp"));
    bar.append(mk("gotchas", (b) => {
      b.classList.toggle("on");
      const on = b.classList.contains("on");
      document.querySelectorAll(".note").forEach((x) => { x.style.display = on ? "" : "none"; });
    }, true));
    header.append(hdr, bar);
    app.append(header);

    const wrap = el("div", "wrap");

    /* the model — the claims this diagram makes, stated not implied */
    if ((doc.model || []).length) {
      const box = el("div", "model");
      box.append(el("h2", null, "The model this dataflow asserts"));
      const ol = el("ol");
      doc.model.forEach((claim) => { const li = el("li"); li.append(inline(claim)); ol.append(li); });
      box.append(ol);
      wrap.append(box);
    }

    /* the board */
    const board = el("div", "board");
    (doc.slices || []).forEach((sl, i) => {
      const col = el("div", "slice");
      const hd = el("div", "slice-hd");
      hd.append(el("span", "n", String(i + 1)), el("h3", null, sl.title));
      if (sl.question) hd.append(el("span", "q", sl.question));
      col.append(hd);
      (sl.nodes || []).forEach((n, j) => {
        // A mapper hangs off the arrow between its neighbours, the way it was
        // drawn on the whiteboard: it is not another box in the column.
        if (n.layer === "mapper") {
          const hop = el("div", "hop");
          const arrows = el("div", "arrows");
          arrows.append(el("span", "dn", "↓"), el("span", "up", "↑"));
          const slot = el("div");
          slot.append(nodeEl(n));
          hop.append(arrows, slot);
          col.append(hop);
        } else {
          if (j) {
            const hop = el("div", "hop");
            const arrows = el("div", "arrows");
            arrows.append(el("span", "dn", "↓"), el("span", "up", "↑"));
            hop.append(arrows, el("div"));
            col.append(hop);
          }
          col.append(nodeEl(n));
        }
      });
      board.append(col);
    });
    wrap.append(board);

    /* legend */
    const legend = el("div", "legend");
    const swatch = (color, label) => {
      const s = el("span");
      const i = el("i", "sw");
      i.style.background = "var(--" + color + ")";
      s.append(i, document.createTextNode(label));
      return s;
    };
    ["api", "application", "domain", "infra", "db"].forEach((l) => legend.append(swatch(l, l)));
    const solid = el("span"); solid.append(el("i", "sw solid"), document.createTextNode("mapper with a file"));
    const dash = el("span"); dash.append(el("i", "sw dash"), document.createTextNode("mapping a framework does — no file"));
    legend.append(solid, dash,
      el("span", null, "⌘ opens the file in your editor"),
      el("span", null, "✻ asks Claude about that node"));
    wrap.append(legend);

    app.append(wrap);
  }

  /* ---------------------------------------------------------------- live */
  function setLive(on, label) {
    const l = document.getElementById("live");
    if (!l) return;
    l.className = "live" + (on ? "" : " off");
    l.replaceChildren(el("i"), document.createTextNode(label));
  }

  function applyThread(anchor, info) {
    THREADS[anchor] = info;
    PENDING.delete(anchor);
    const id = anchor.slice("node:".length);
    const wrap = document.getElementById("n-" + id);
    if (!wrap) return;
    const node = findNode(id);
    if (!node) return;
    renderThread(wrap.querySelector("[data-thread]"), node);
    wrap.querySelector(".ic.ask").classList.add("has");
  }

  const findNode = (id) =>
    (FLOW.slices || []).flatMap((s) => s.nodes || []).find((n) => n.id === id);

  async function refetchFlow() {
    const res = await fetch(BASE + "dataflow.json");
    FLOW = await res.json();
    render();
  }

  function connect() {
    const es = new EventSource(BASE + "stream");
    es.addEventListener("connected", () => setLive(true, "claude connected"));
    es.addEventListener("heartbeat", () => setLive(true, "claude connected"));
    es.addEventListener("flow-changed", () => refetchFlow());
    es.addEventListener("thread-changed", (e) => {
      const d = JSON.parse(e.data);
      applyThread(d.anchor, d);
    });
    es.addEventListener("thread-deleted", (e) => {
      const d = JSON.parse(e.data);
      delete THREADS[d.anchor];
      const node = findNode(d.anchor.slice("node:".length));
      const wrap = document.getElementById("n-" + (node ? node.id : ""));
      if (node && wrap) renderThread(wrap.querySelector("[data-thread]"), node);
    });
    es.addEventListener("session-ended", () => { setLive(false, "closed"); es.close(); });
    // The browser reconnects an EventSource on its own; saying "reconnecting"
    // rather than "dead" keeps the badge honest about what is happening.
    es.onerror = () => setLive(false, "reconnecting…");
  }

  async function boot() {
    const [f, t] = await Promise.all([
      fetch(BASE + "dataflow.json").then((r) => r.json()),
      fetch(BASE + "threads.json").then((r) => r.json()),
    ]);
    FLOW = f;
    THREADS = t || {};
    render();
    connect();
  }

  boot().catch((e) => {
    document.getElementById("app").append(
      el("div", "splash", "Could not load this dataflow: " + e));
  });
})();
