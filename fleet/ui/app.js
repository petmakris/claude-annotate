"use strict";
// The Fleet view polls its JSON endpoints every REFRESH ms while the tab is visible. The page writes only through
// POSTs to /api/*, which the server accepts from this page only: History (rename, delete, ask, search by meaning),
// and, as the user: add a to-do, tell or ask a member, stop or respawn one, answer or dismiss an item of the
// "For you" inbox.
// Every value reaches the page through textContent, never as markup.
const REFRESH = 5000;
const VIEWS = [{ id: "fleet", label: "Fleet" }, { id: "foryou", label: "For you" }, { id: "history", label: "History" }, { id: "profiles", label: "Profiles" }];

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v; else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : String(c));
  return n;
}


// Icons: Lucide 0.460.0 (ISC license), 24 px grid, stroke 2, path data copied unchanged from lucide-static. Built with createElementNS, no markup strings.
const ICONS = {
  "message-square": [["path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" }]],
  "message-circle-question": [["path", { d: "M7.9 20A9 9 0 1 0 4 16.1L2 22Z" }], ["path", { d: "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" }], ["path", { d: "M12 17h.01" }]],
  "circle-stop": [["circle", { cx: "12", cy: "12", r: "10" }], ["rect", { x: "9", y: "9", width: "6", height: "6", rx: "1" }]],
  "rotate-ccw": [["path", { d: "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" }], ["path", { d: "M3 3v5h5" }]],
  "terminal": [["polyline", { points: "4 17 10 11 4 5" }], ["line", { x1: "12", x2: "20", y1: "19", y2: "19" }]],
  "pencil": [["path", { d: "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" }], ["path", { d: "m15 5 4 4" }]],
  "copy": [["rect", { width: "14", height: "14", x: "8", y: "8", rx: "2", ry: "2" }], ["path", { d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" }]],
  "trash-2": [["path", { d: "M3 6h18" }], ["path", { d: "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" }], ["path", { d: "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" }], ["line", { x1: "10", x2: "10", y1: "11", y2: "17" }], ["line", { x1: "14", x2: "14", y1: "11", y2: "17" }]],
  "reply": [["polyline", { points: "9 17 4 12 9 7" }], ["path", { d: "M20 18v-2a4 4 0 0 0-4-4H4" }]],
  "x": [["path", { d: "M18 6 6 18" }], ["path", { d: "m6 6 12 12" }]],
  "check": [["path", { d: "M20 6 9 17l-5-5" }]],
};
const SVG_NS = "http:" + "//www.w3.org/2000/svg";  // an XML namespace name, not a fetched address
function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) svg.setAttribute(k, v);
  for (const [tag, attrs] of ICONS[name]) {
    const p = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) p.setAttribute(k, v);
    svg.append(p);
  }
  return svg;
}
// A square icon button; the name is both the accessible name and the tooltip. cls: "danger-hover", "primary".
function ibtn(name, label, fn, cls) {
  const b = el("button", { type: "button", class: "ib" + (cls ? " " + cls : ""), "aria-label": label, title: label, "data-icon": name }, icon(name));
  if (fn) b.addEventListener("click", (e) => fn(b, e));
  return b;
}

function ago(t, now) {
  if (!t) return "";
  const s = Math.max(0, Math.round((now - t * 1000) / 1000));
  if (s < 60) return s + " s ago";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
}
const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "");

function copy(text, btn) {
  const name = btn.dataset.icon, label = btn.getAttribute("aria-label");
  const flash = (ic, tip) => { btn.replaceChildren(icon(ic)); btn.title = tip; setTimeout(() => { btn.replaceChildren(icon(name)); btn.title = label; }, 1500); };
  const done = () => flash("check", "Copied");
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, () => fallback());
  fallback();
  function fallback() {
    const ta = el("textarea", { readonly: true, style: "position:fixed;opacity:0" });
    ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { flash("x", "Copy failed"); }
    ta.remove();
  }
}

function table(cols, rows) {
  return el("table", {}, el("thead", {}, el("tr", {}, cols.map((c) => el("th", { style: c.w ? "width:" + c.w : null }, c.head)))),
    el("tbody", {}, rows.map((r) => el("tr", {}, cols.map((c) => c.cell(r))))));
}
const cell = (label, cls, f, w) => ({ head: label, w, cell: (r) => el("td", { "data-label": label, class: cls }, f(r)) });

const SELF = { machine: "" };
const target = (m) => (!m.machine || m.machine === SELF.machine ? m.name : m.name + "@" + m.machine);
const M = { open: null };  // { key, kind } of the compose row that is open

function mmsg(text, bad) {
  const m = document.getElementById("m-msg");
  m.className = "h-msg" + (bad ? " bad" : "");
  m.textContent = text || "";
}

async function control(path, m, okText) {
  try {
    const d = await post(path, { target: target(m) });
    mmsg(okText ? okText(d) : d.output || "Done.");
    refresh(true);
    return d;
  } catch (e) { mmsg(e.message, true); }
}

function sure(btn, label, fn) {  // the first press asks for confirmation (icon + "Confirm" in red), the second acts
  btn.addEventListener("click", () => {
    if (btn.dataset.sure) return fn();
    btn.dataset.sure = "1"; btn.classList.add("confirming"); btn.replaceChildren(icon(btn.dataset.icon), el("span", {}, "Confirm"));
    btn.setAttribute("aria-label", "Confirm " + label.toLowerCase()); btn.title = "Press again to " + label.toLowerCase();
    setTimeout(() => { if (btn.isConnected) { delete btn.dataset.sure; btn.classList.remove("confirming"); btn.replaceChildren(icon(btn.dataset.icon)); btn.setAttribute("aria-label", label); btn.title = label; } }, 4000);
  });
}

function memberActions(m) {
  const box = el("div", { class: "actions m-actions" });
  const act = (name, label, fn, cls) => { const b = ibtn(name, label, fn && (() => fn(b)), cls); box.append(b); return b; };
  const key = m.machine + "/" + m.session_id;
  const open = (kind) => { M.open = M.open && M.open.key === key && M.open.kind === kind ? null : { key, kind, draft: "" }; renderMembersNow(); const t = document.querySelector("#members .compose textarea"); if (t) t.focus(); };
  if (m.status === "alive") {
    act("message-square", "Tell", () => open("tell"));
    act("message-circle-question", "Ask", () => open("ask"));
    sure(act("circle-stop", "Stop", null, "danger-hover"), "Stop", () => control("/api/members/stop", m, (d) => d.action === "stopped" ? "Stopped " + m.name + ". Its conversation is kept." : m.name + " is an interactive session, so it was asked to wrap up and leave."));
  } else {
    sure(act("rotate-ccw", "Respawn"), "Respawn", () => control("/api/members/respawn", m, (d) => "Started " + m.name + " again in the background."));
  }
  act("terminal", "Copy attach", async (b) => {
    try { const d = await post("/api/members/attach", { target: target(m) }); copy(d.command, b); mmsg(d.note || ""); }
    catch (e) { mmsg(e.message, true); }
  });
  return box;
}

function composeRow(m, cols) {
  const t = el("textarea", { rows: "3", class: "h-input", "aria-label": (M.open.kind === "ask" ? "Question for " : "Instruction for ") + m.name, placeholder: M.open.kind === "ask" ? "Ask " + m.name + " a question" : "Tell " + m.name + " what to do" });
  t.value = M.open.draft || "";
  t.addEventListener("input", () => { M.open.draft = t.value; });
  const send = el("button", { type: "button", class: "act primary" }, M.open.kind === "ask" ? "Send question" : "Send instruction");
  const cancel = el("button", { type: "button", class: "act" }, "Cancel");
  const go = async () => {
    if (!t.value.trim() || send.disabled) return;
    send.disabled = true;
    try {
      const d = await post("/api/tell", { target: target(m), text: t.value, kind: M.open.kind });
      mmsg("Sent to " + m.name + " as you. " + (d.output || "").split("\n").pop());
      M.open = null; renderMembersNow(); refresh(true);
    } catch (e) { mmsg(e.message, true); send.disabled = false; }
  };
  send.addEventListener("click", go);
  cancel.addEventListener("click", () => { M.open = null; renderMembersNow(); });
  t.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(); });
  return el("tr", { class: "detail compose" }, el("td", { colspan: cols }, t, el("div", { class: "row-actions" }, send, cancel)));
}

let lastMembers = null;
function renderMembersNow() { if (lastMembers) renderMembers(lastMembers.data, lastMembers.now, true); }

function renderMembers(data, now, force) {
  if (data.machine) SELF.machine = data.machine;
  lastMembers = { data, now };
  if (!force && (document.querySelector("#members .compose textarea") || document.querySelector("#members button[data-sure]"))) return;  // never wipe what is being typed or a pending confirmation
  const order = { alive: 0, dead: 1, left: 2 };
  const rows = data.members.slice().sort((a, b) => order[a.status] - order[b.status] || (b.joined_at || 0) - (a.joined_at || 0));
  document.getElementById("n-members").textContent = rows.length ? String(rows.length) : "";
  const box = document.getElementById("members");
  if (!rows.length) return box.replaceChildren(el("p", { class: "empty" }, "No sessions have joined this fleet yet."));
  const heads = ["Name", "Status", "Machine", "Folder", "Session", "Joined", "Actions"];
  const body = el("tbody", {});
  for (const m of rows) {
    body.append(el("tr", {},
      el("td", { class: "name" }, m.name),
      el("td", { "data-label": "Status" }, el("span", { class: "pill " + m.status }, m.status)),
      el("td", { "data-label": "Machine" }, m.machine),
      el("td", { "data-label": "Folder", class: "mono" }, m.cwd),
      el("td", { "data-label": "Session", class: "mono" }, m.session_id.slice(0, 8)),
      el("td", { "data-label": "Joined", class: "dim" }, el("span", { title: when(m.joined_at) }, ago(m.joined_at, now))),
      el("td", {}, memberActions(m))));
    if (M.open && M.open.key === m.machine + "/" + m.session_id) body.append(composeRow(m, heads.length));
  }
  box.replaceChildren(el("table", { class: "m-table" }, el("thead", {}, el("tr", {}, heads.map((h) => el("th", {}, h)))), body));
}

function renderTodos(data) {
  const rows = data.todos;
  document.getElementById("n-todos").textContent = rows.length ? String(rows.length) : "";
  const box = document.getElementById("todos");
  if (!rows.length) return box.replaceChildren(el("p", { class: "empty" }, "The backlog is empty."));
  const cols = [
    cell("State", "", (t) => el("span", { class: "pill " + t.state }, t.state), "90px"),
    cell("Title", "", (t) => t.title),
    cell("Holder", "", (t) => t.claimed_by || (t.reserved_for ? "reserved for " + t.reserved_for : ""), "170px"),
    cell("Ref", "mono", (t) => t.ref || "", "110px"),
    cell("Machine", "dim", (t) => t.machine, "110px"),
  ];
  const kids = [];
  const group = (state, label) => {
    const g = rows.filter((t) => t.state === state);
    if (!g.length) return null;
    return el("div", {}, el("div", { class: "state-group" }, label + " (" + g.length + ")"), table(cols, g));
  };
  kids.push(group("open", "Open"), group("claimed", "Claimed"));
  const done = group("done", "Done");
  if (done) kids.push(el("details", {}, el("summary", {}, "Done (" + rows.filter((t) => t.state === "done").length + ")"), done));
  box.replaceChildren(...kids.filter(Boolean));
}

function renderThreads(data, now) {
  const rows = data.threads;
  document.getElementById("n-threads").textContent = rows.length ? String(rows.length) : "";
  const box = document.getElementById("threads");
  if (!rows.length) return box.replaceChildren(el("p", { class: "empty" }, "No messages have been sent yet."));
  box.replaceChildren(...rows.map((t) => el("div", { class: "thread" },
    el("div", { class: "thread-head" }, el("span", { class: "mono" }, t.thread),
      t.open ? el("span", { class: "pill claimed" }, t.open + " waiting") : el("span", { class: "pill done" }, "answered"),
      el("span", { class: "dim", title: when(t.updated) }, ago(t.updated, now))),
    t.messages.map((m) => el("div", { class: "msg " + m.kind },
      el("div", { class: "msg-meta" }, el("span", { class: "kind" }, m.kind), " " + m.sender + " to " + m.recipient,
        " · ", el("span", { title: when(m.created_at) }, ago(m.created_at, now))),
      el("div", { class: "msg-body" }, m.body))))));
}

function initTodoForm() {
  const msg = document.getElementById("todo-msg");
  document.getElementById("todo-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = (id) => document.getElementById(id);
    try {
      const d = await post("/api/todos/add", { title: f("todo-title").value, ref: f("todo-ref").value, notes: f("todo-notes").value });
      msg.className = "h-msg"; msg.textContent = "Added to-do " + d.id + ".";
      for (const id of ["todo-title", "todo-ref", "todo-notes"]) f(id).value = "";
      refresh(true);
    } catch (err) { msg.className = "h-msg bad"; msg.textContent = err.message; }
  });
}

// ---------------------------------------------------------------- For you

const Y = { items: [], drafts: new Map(), answering: null };
const fymsg = (text, bad) => { const m = document.getElementById("fy-msg"); m.className = "h-msg" + (bad ? " bad" : ""); m.textContent = text || ""; };

function setBadge(n) {
  const b = document.querySelector('#tabs button[data-view="foryou"]');
  if (!b) return;
  b.replaceChildren("For you", n ? el("span", { class: "badge", "aria-label": n + " waiting for you" }, String(n)) : "");
  document.title = n ? "(" + n + ") Fleet" : "Fleet";
}

function fyItem(i, now) {
  const done = i.answered_at !== null;
  const kids = [el("div", { class: "fy-head" }, el("span", { class: "pill " + (i.kind === "ask" ? "open" : i.kind === "notify" ? "claimed" : "left") }, i.kind === "notify" ? "notice" : i.kind),
    el("strong", {}, i.sender), SELF.machine && i.machine !== SELF.machine ? el("span", { class: "dim" }, "on " + i.machine) : null,
    el("span", { class: "dim", title: when(i.created_at) }, ago(i.created_at, now))),
    el("div", { class: "msg-body" }, i.body)];
  if (done) { kids.push(el("div", { class: "dim fy-reply" }, i.reply ? "You answered: " + i.reply : "Dismissed")); return el("div", { class: "fy-item done" }, kids); }
  const input = el("textarea", { rows: "2", class: "h-input", "aria-label": "Your answer to " + i.sender, placeholder: i.kind === "ask" ? "Your answer" : "Reply to " + i.sender + " (optional)" });
  input.value = Y.drafts.get(i.ref) || "";
  input.addEventListener("input", () => Y.drafts.set(i.ref, input.value));
  const send = ibtn("reply", i.kind === "ask" ? "Answer" : "Reply", null, "primary");
  const dismiss = ibtn("x", "Dismiss");
  const run = async (path, body, ok) => {
    send.disabled = dismiss.disabled = true;
    try { await post(path, body); Y.drafts.delete(i.ref); fymsg(ok); await loadInbox(); refresh(true); }
    catch (e) { fymsg(e.message, true); send.disabled = dismiss.disabled = false; }
  };
  send.addEventListener("click", () => { if (input.value.trim()) run("/api/inbox/answer", { ref: i.ref, text: input.value }, "Answered. " + i.sender + " has it."); });
  dismiss.addEventListener("click", () => run("/api/inbox/dismiss", { ref: i.ref }, i.kind === "ask" ? "Dismissed. " + i.sender + " was told you did not answer." : "Dismissed."));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send.click(); });
  kids.push(input, el("div", { class: "row-actions" }, send, dismiss));
  return el("div", { class: "fy-item" }, kids);
}

function renderInbox(data) {
  if (data.machine) SELF.machine = data.machine;
  Y.items = data.items;
  setBadge(data.open);
  document.getElementById("n-foryou").textContent = data.open ? String(data.open) : "";
  const box = document.getElementById("foryou");
  if (box.querySelector("textarea:focus")) return;  // never wipe what is being typed
  const now = Date.now();
  const open = data.items.filter((i) => i.answered_at === null), done = data.items.filter((i) => i.answered_at !== null);
  const kids = [];
  if (!open.length) kids.push(el("p", { class: "empty" }, "Nothing is waiting for you."));
  kids.push(...open.map((i) => fyItem(i, now)));
  if (done.length) kids.push(el("details", {}, el("summary", {}, "Answered or dismissed (" + done.length + ")"), ...done.map((i) => fyItem(i, now))));
  box.replaceChildren(...kids);
}

async function loadInbox() {
  try { renderInbox(await getJSON("/api/inbox")); fymsg(""); }
  catch (e) { fymsg("Cannot load your inbox: " + e.message, true); }
}

// ---------------------------------------------------------------- History

const H = { rows: [], counts: { total: 0, described: 0 }, home: "", folder: null, q: "", found: null, open: null, shown: 100, loaded: false, busy: false };
const PAGE = 100;

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || path + " " + r.status);
  return data;
}

function say(text, bad) {
  const m = document.getElementById("h-msg");
  m.className = "h-msg" + (bad ? " bad" : "");
  m.textContent = text || "";
}

const tilde = (p) => (H.home && (p === H.home || p.startsWith(H.home.replace(/\/+$/, "") + "/")) ? "~" + p.slice(H.home.replace(/\/+$/, "").length) : p);

// A tree of folders: one node per path segment, a chain of single-child folders with no sessions of its own is
// shown as one node ("work/shop/api"), and a count is every session at or below the node.
const folderParts = (r) => (r.folder ? tilde(r.folder) : "(no folder)").split("/").filter(Boolean);
const folderKey = (r) => "/" + folderParts(r).join("/");

function folderTree(rows) {
  const root = { seg: "", path: "", kids: new Map(), own: 0, count: 0 };
  for (const r of rows) {
    let n = root;
    n.count++;
    let path = "";
    for (const seg of folderParts(r)) {
      path += "/" + seg;
      if (!n.kids.has(seg)) n.kids.set(seg, { seg, path, kids: new Map(), own: 0, count: 0 });
      n = n.kids.get(seg); n.count++;
    }
    n.own++;
  }
  const merge = (n) => {
    n.kids = new Map([...n.kids.values()].map((k) => { const m = merge(k); return [m.seg, m]; }));
    while (n.kids.size === 1 && n.own === 0 && n.seg) {
      const [k] = n.kids.values();
      n = { seg: n.seg + "/" + k.seg, path: k.path, kids: k.kids, own: k.own, count: k.count };
    }
    return n;
  };
  const top = merge(root);
  // the shared leading folders (the home folder, say) are not worth a node of their own
  let n = top;
  while (n.kids.size === 1 && n.own === 0) { const [k] = n.kids.values(); n = { seg: (n.seg ? n.seg + "/" : "") + k.seg, path: k.path, kids: k.kids, own: k.own, count: k.count }; }
  return { top, base: n };
}

// Text with a break opportunity after each slash, so a path wraps between segments and never inside one.
function slashBreaks(text) {
  const out = [];
  text.split("/").forEach((part, i, all) => { out.push(part + (i < all.length - 1 ? "/" : "")); if (i < all.length - 1) out.push(document.createElement("wbr")); });
  return out;
}

// The last two segments of a folder, for a column that cannot hold the whole path.
function shortFolder(p) {
  const parts = tilde(p || "").split("/").filter(Boolean);
  return parts.length > 2 ? "\u2026/" + parts.slice(-2).join("/") : tilde(p || "") || "(none)";
}

function renderTree() {
  const box = document.getElementById("h-tree");
  const { top, base } = folderTree(H.rows);
  const sel = (path) => { H.folder = H.folder === path ? null : path; H.shown = PAGE; renderHistory(); };
  const node = (n, depth) => {
    const kids = [...n.kids.values()].sort((a, b) => b.count - a.count || a.seg.localeCompare(b.seg));
    const head = el("button", { type: "button", class: "f-node" + (H.folder === n.path ? " on" : ""), "aria-pressed": H.folder === n.path ? "true" : "false" },
      el("span", { class: "f-name mono" }, ...slashBreaks(n.seg || "/")), el("span", { class: "f-count" }, n.count));
    head.addEventListener("click", () => sel(n.path));
    if (!kids.length) return el("div", { class: "f-leaf" }, head);
    const d = el("details", { class: "f-dir", open: depth < 2 || (H.folder && H.folder.startsWith(n.path)) }, el("summary", {}, head));
    d.append(...kids.map((k) => node(k, depth + 1)));
    return d;
  };
  const all = el("button", { type: "button", class: "f-node" + (H.folder === null ? " on" : ""), "aria-pressed": H.folder === null ? "true" : "false" },
    el("span", { class: "f-name" }, "All sessions"), el("span", { class: "f-count" }, top.count));
  all.addEventListener("click", () => { H.folder = null; H.shown = PAGE; renderHistory(); });
  const prefix = base.seg && base !== top ? el("div", { class: "f-prefix dim mono", title: base.seg }, "/" + base.seg) : null;
  box.replaceChildren(...[all, prefix, ...[...base.kids.values()].sort((a, b) => b.count - a.count || a.seg.localeCompare(b.seg)).map((k) => node(k, 1)),
    base.own ? el("div", { class: "dim f-own" }, base.own + " directly in " + base.path.replace(/^\/~/, "~")) : null].filter(Boolean));
}

function visibleRows() {
  if (H.found) return H.found.hits;
  const q = H.q.trim().toLowerCase();
  return H.rows.filter((r) => (!H.folder || folderKey(r) === H.folder || folderKey(r).startsWith(H.folder + "/"))
    && (!q || (r.name + " " + r.folder + " " + r.about).toLowerCase().includes(q)));
}

async function act(fn, okText) {
  if (H.busy) return;
  H.busy = true; say("");
  try { await fn(); if (okText) say(okText); } catch (e) { say(e.message, true); } finally { H.busy = false; }
}

function nameCell(r) {
  const td = el("td", { "data-label": "Name", class: "name" });
  const label = r.name || r.about || "(unnamed)";
  const open = el("button", { type: "button", class: "link" + (r.name ? "" : " muted"), title: label, "aria-expanded": H.open === r.id ? "true" : "false" }, label);
  open.addEventListener("click", () => { H.open = H.open === r.id ? null : r.id; renderRows(); });
  td.append(open, el("div", { class: "mono dim id" }, r.id.slice(0, 8)));
  return td;
}

function renameInto(td, r) {
  const input = el("input", { type: "text", value: r.name, "aria-label": "New name", class: "h-input" });
  const save = el("button", { type: "button", class: "act primary" }, "Save");
  const cancel = el("button", { type: "button", class: "act" }, "Cancel");
  const go = () => act(async () => { await post("/api/history/rename", { id: r.id, name: input.value }); await loadHistory(); });
  save.addEventListener("click", go);
  cancel.addEventListener("click", renderRows);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") renderRows(); });
  td.replaceChildren(input, el("div", { class: "row-actions" }, save, cancel));
  input.focus(); input.select();
}

function actionsCell(r, tr) {
  const td = el("td", {});
  const box = el("div", { class: "actions" });
  const mk = ibtn;
  box.append(
    mk("message-circle-question", "Ask", () => { H.open = r.id; renderRows(); const q = document.getElementById("ask-" + r.id); if (q) q.focus(); }),
    mk("pencil", "Rename", () => renameInto(tr.querySelector("td.name"), r)),
    mk("copy", "Copy resume", (b) => copy(r.resume, b)),
    mk("trash-2", "Delete", (b) => {
      if (b.dataset.sure) return act(async () => { await post("/api/history/delete", { id: r.id }); if (H.open === r.id) H.open = null; await loadHistory(); }, "Removed from the history. The transcript is untouched.");
      b.dataset.sure = "1"; b.classList.add("confirming"); b.replaceChildren(icon("trash-2"), el("span", {}, "Confirm"));
      b.setAttribute("aria-label", "Confirm delete"); b.title = "Press again to delete";
      setTimeout(() => { if (b.isConnected) { delete b.dataset.sure; b.classList.remove("confirming"); b.replaceChildren(icon("trash-2")); b.setAttribute("aria-label", "Delete"); b.title = "Delete"; } }, 4000);
    }, "danger-hover"));
  td.append(box);
  return td;
}

function detailRow(r, cols) {
  const answer = el("div", { class: "h-answer", role: "status" });
  const q = el("input", { type: "text", id: "ask-" + r.id, class: "h-input", placeholder: "Ask a question about this session", "aria-label": "Question about this session" });
  const ask = el("button", { type: "button", class: "act primary" }, "Ask");
  const go = () => {
    if (!q.value.trim() || ask.disabled) return;
    ask.disabled = true; answer.className = "h-answer dim"; answer.textContent = "Reading the transcript, about 10 seconds";
    post("/api/history/ask", { id: r.id, question: q.value }).then((d) => { answer.className = "h-answer"; answer.textContent = d.answer; },
      (e) => { answer.className = "h-answer bad"; answer.textContent = e.message; }).finally(() => { ask.disabled = false; });
  };
  ask.addEventListener("click", go);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return el("tr", { class: "detail" }, el("td", { colspan: cols },
    r.description ? el("p", { class: "h-desc" }, r.description) : el("p", { class: "dim" }, "No description yet. fleet history describe writes one."),
    r.about ? el("p", { class: "dim" }, "Opened with: " + r.about) : null,
    el("p", { class: "mono dim" }, r.transcript || "no transcript path"),
    el("div", { class: "h-ask" }, q, ask), answer));
}

function renderRows() {
  const rows = visibleRows();
  const box = document.getElementById("h-rows");
  const found = H.found;
  const head = found ? el("p", { class: "h-found" }, found.hits.length ? "Matches by meaning, best first (" + found.hits.length + ")" : "No description matches that.") : null;
  if (!rows.length) {
    return box.replaceChildren(...[head, el("p", { class: "empty" }, H.rows.length ? (found ? "" : "No session matches.") : "No sessions recorded yet. They appear as sessions run, or import an older store with fleet history import.")].filter(Boolean));
  }
  const cols = [
    { head: "Name" },
    { head: found ? "Why" : "About" }, { head: "Folder" }, { head: "Started" }, { head: "Last seen" }, { head: "" },
  ];
  const body = el("tbody", {});
  for (const r of rows.slice(0, H.shown)) {
    const tr = el("tr", { class: H.open === r.id ? "expanded" : "" });
    tr.append(nameCell(r),
      el("td", { "data-label": found ? "Why" : "About" }, el("div", { class: "about" }, found ? r.why : (r.description || r.about))),
      el("td", { "data-label": "Folder", class: "mono" }, el("span", { class: "folder", title: tilde(r.folder || "") }, shortFolder(r.folder))),
      el("td", { "data-label": "Started", class: "dim nw" }, el("span", { title: when(r.started) }, ago(r.started, Date.now()))),
      el("td", { "data-label": "Last seen", class: "dim nw" }, el("span", { title: when(r.last_seen) }, ago(r.last_seen, Date.now()))),
      actionsCell(r, tr));
    body.append(tr);
    if (H.open === r.id) body.append(detailRow(r, cols.length));
  }
  const more = rows.length > H.shown ? el("button", { type: "button", class: "act more" }, "Show " + Math.min(PAGE, rows.length - H.shown) + " more of " + (rows.length - H.shown)) : null;
  if (more) more.addEventListener("click", () => { H.shown += PAGE; renderRows(); });
  box.replaceChildren(...[head, el("table", { class: "h-table" }, el("thead", {}, el("tr", {}, cols.map((c) => el("th", {}, c.head)))), body), more].filter(Boolean));
}

function renderHistory() {
  const c = H.counts;
  document.getElementById("n-history").textContent = c.total ? String(c.total) : "";
  document.getElementById("h-note").textContent = c.total
    ? c.described + " of " + c.total + " sessions have a description, which search by meaning reads. fleet history describe writes the rest."
      + (c.unreadable ? " Warning: " + c.unreadable + " transcript" + (c.unreadable === 1 ? "" : "s") + " could not be read: has the transcript format changed?" : "")
    : "";
  document.getElementById("h-clear").hidden = !H.found;
  renderTree(); renderRows();
}

async function loadHistory() {
  try {
    const d = await getJSON("/api/history");
    Object.assign(H, { rows: d.rows, counts: d.counts, home: d.home, loaded: true });
    if (H.found) H.found = null;
    renderHistory();
  } catch (e) { say("Cannot load the history: " + e.message, true); }
}

function initHistory() {
  if (matchMedia("(max-width: 720px)").matches) document.getElementById("h-tree-box").open = false;  // the folders fold away on a phone
  const q = document.getElementById("h-q");
  q.addEventListener("input", () => { H.q = q.value; H.found = null; H.shown = PAGE; renderHistory(); });
  document.getElementById("h-clear").addEventListener("click", () => { H.found = null; H.q = ""; q.value = ""; say(""); renderHistory(); });
  document.getElementById("h-search").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = q.value.trim();
    if (!text) return;
    const b = document.getElementById("h-meaning");
    b.disabled = true; say("Reading " + H.counts.described + " descriptions, about 10 seconds");
    post("/api/history/search", { query: text }).then((d) => {
      H.found = { hits: d.hits }; H.counts = { total: d.total, described: d.described }; say(""); renderHistory();
    }, (err) => say(err.message, true)).finally(() => { b.disabled = false; });
  });
}

// ---------------------------------------------------------------- Profiles

// P.folder: a listed folder's absolute path, or null for every folder. P.editing: the profile the switches show.
// P.draft: the switches as edited and not yet saved, or null.
const P = { data: null, folder: null, editing: null, draft: null, busy: false };
const GROUPS = [{ kind: "pluginDir", title: "Plugin folders" }, { kind: "mcp", title: "MCP servers" }, { kind: "plugin", title: "Marketplace plugins" }];

function pmsg(text, bad) {
  const m = document.getElementById("p-msg");
  m.className = "h-msg" + (bad ? " bad" : "");
  m.textContent = text || "";
}

const isOn = (d, t) => (t.kind === "pluginDir" ? d.pluginDirs.includes(t.id) : t.kind === "mcp" ? !d.denied.includes(t.id) : !d.disabledPlugins.includes(t.id));
const flip = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : list.concat([id]));
const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));
const draftOf = (p) => ({ pluginDirs: p.pluginDirs.slice(), denied: p.denied.slice(), disabledPlugins: p.disabledPlugins.slice() });
const profileNamed = (name) => (P.data ? P.data.profiles.find((p) => p.name === name) || null : null);
const usersOf = (name) => P.data.folders.filter((f) => f.source.profile === name);

function isDirty() {
  const p = profileNamed(P.editing);
  return !!(p && P.draft) && !(sameSet(p.pluginDirs, P.draft.pluginDirs) && sameSet(p.denied, P.draft.denied) && sameSet(p.disabledPlugins, P.draft.disabledPlugins));
}

// Leaving unsaved switches asks first.
function leaveDraft() {
  if (!isDirty()) return true;
  if (!confirm("Discard unsaved changes to " + P.editing + "?")) return false;
  P.draft = null;
  return true;
}

function sourceText(s) {
  if (s.kind === "here") return "Runs " + s.profile + ", set here.";
  if (s.kind === "inherited") return s.profile ? "Runs " + s.profile + ", inherited from " + s.from + "." : "A hand-written file in " + s.from + " decides.";
  if (s.kind === "custom") return "A hand-written .claude-launch decides this folder's tools.";
  return "No profile applies here, so new sessions get the launcher's defaults.";
}

function renderProfilesTree() {
  const box = document.getElementById("p-tree");
  const folders = P.data.folders;
  const byKey = new Map(folders.map((f) => [folderKey({ folder: f.path }), f]));
  const { top, base } = folderTree(folders.map((f) => ({ folder: f.path })));
  // busiest first, by the sessions at or below a node, as History orders its tree
  const used = (n) => folders.reduce((sum, x) => { const k = folderKey({ folder: x.path }); return sum + (k === n.path || k.startsWith(n.path + "/") ? x.sessions : 0); }, 0);
  const byUse = (list) => list.map((n) => [used(n), n]).sort((a, b) => b[0] - a[0] || a[1].seg.localeCompare(b[1].seg)).map((x) => x[1]);
  const keyOf = (path) => { const f = folders.find((x) => folderKey({ folder: x.path }) === path); return f ? f.path : null; };
  const sel = (n) => {
    const f = byKey.get(n.path);
    if (!f || !leaveDraft()) return;
    P.folder = f.path; P.editing = f.source.profile; P.draft = null; renderProfiles();
  };
  const node = (n, depth) => {
    const f = byKey.get(n.path);
    const kids = byUse([...n.kids.values()]);
    const on = f && P.folder === f.path;
    const head = el("button", { type: "button", class: "f-node" + (on ? " on" : "") + (f ? "" : " f-pass"), "aria-pressed": on ? "true" : "false", disabled: !f, title: f ? f.display : null },
      el("span", { class: "f-name mono" }, ...slashBreaks(n.seg || "/")), el("span", { class: "f-count" }, f && f.source.profile ? f.source.profile : ""));
    head.addEventListener("click", () => sel(n));
    if (!kids.length) return el("div", { class: "f-leaf" }, head);
    // a folder with many subfolders (a pile of scratch runs) starts folded, unless the selection is inside it
    const d = el("details", { class: "f-dir", open: kids.length <= 8 || (P.folder && folderKey({ folder: P.folder }).startsWith(n.path + "/")) }, el("summary", {}, head));
    d.append(...kids.map((k) => node(k, depth + 1)));
    return d;
  };
  const all = el("button", { type: "button", class: "f-node" + (P.folder === null ? " on" : ""), "aria-pressed": P.folder === null ? "true" : "false" },
    el("span", { class: "f-name" }, "All folders"), el("span", { class: "f-count" }, P.data.profiles.length + " profiles"));
  all.addEventListener("click", () => { if (!leaveDraft()) return; P.folder = null; P.editing = null; P.draft = null; renderProfiles(); });
  const prefix = base.seg && base !== top ? el("div", { class: "f-prefix dim mono", title: base.seg }, "/" + base.seg) : null;
  const ownBase = keyOf(base.path) ? [node(Object.assign({}, base, { kids: new Map() }), 1)] : [];
  box.replaceChildren(...[all, prefix, ...ownBase, ...byUse([...base.kids.values()]).map((k) => node(k, 1))].filter(Boolean));
}

async function setFolderProfile(name) {
  if (P.busy) return;
  P.busy = true; pmsg("");
  try {
    const d = await post("/api/profiles/folder", { folder: P.folder, profile: name });
    const f = P.data.folders.find((x) => x.path === P.folder);
    pmsg((f ? f.display : P.folder) + (name ? " now uses " + name + "." : " now inherits."));
    P.editing = d.source.profile; P.draft = null;
    await loadProfiles();
  } catch (e) { pmsg(e.message, true); } finally { P.busy = false; }
}

async function saveProfile(btn) {
  if (P.busy || !P.draft) return;
  const p = profileNamed(P.editing);
  P.busy = true; btn.disabled = true; pmsg("Saving " + p.name + ", then committing and pushing it");
  try {
    const tools = P.data.tools;
    const r = await post("/api/profiles/save", { name: p.name, denied: P.draft.denied, disabledPlugins: P.draft.disabledPlugins,
      pluginDirs: tools.filter((t) => t.kind === "pluginDir" && isOn(P.draft, t)).map((t) => t.id).concat(P.draft.pluginDirs.filter((d) => !tools.some((t) => t.id === d))) });
    if (!r.committed) pmsg("No change to save.");
    else if (r.pushed) pmsg("Saved and pushed: " + r.message);
    else if (!r.hasRemote) pmsg("Saved and committed " + r.commit + ". The repository has no remote to push to.");
    else pmsg("Committed " + r.commit + ", but the push failed: " + r.pushError, true);
    P.draft = null;
    await loadProfiles();
  } catch (e) { pmsg(e.message, true); } finally { P.busy = false; btn.disabled = false; }
}

function switchesPanel(p) {
  if (!P.draft) P.draft = draftOf(p);
  const users = usersOf(p.name);
  const pick = el("select", { class: "p-select", "aria-label": "Profile to edit" }, P.data.profiles.map((x) => el("option", { value: x.name, selected: x.name === p.name }, x.name)));
  pick.addEventListener("change", () => { if (!leaveDraft()) { pick.value = p.name; return; } P.editing = pick.value; P.draft = null; renderProfiles(); });
  const kids = [el("div", { class: "p-head" }, pick,
    el("span", { class: "dim" }, "Kept in ", el("code", {}, p.repo), ", where a save commits. ",
      users.length ? "Used by " + users.length + (users.length === 1 ? " folder: " : " folders: ") + users.map((f) => f.display).join(", ") + "." : "No listed folder uses it."))];
  for (const g of GROUPS) {
    const tools = P.data.tools.filter((t) => t.kind === g.kind);
    if (!tools.length) continue;
    kids.push(el("h3", { class: "p-group" }, g.title));
    const list = el("div", { class: "p-tools" });
    for (const t of tools) {
      const on = isOn(P.draft, t);
      const sw = el("button", { type: "button", role: "switch", class: "sw" + (on ? " on" : ""), "aria-checked": on ? "true" : "false", "aria-label": t.label, disabled: t.locked, title: t.locked ? "Always on" : t.id }, el("span", { class: "sw-knob" }), on ? "On" : "Off");
      sw.addEventListener("click", () => {
        if (t.kind === "pluginDir") P.draft.pluginDirs = flip(P.draft.pluginDirs, t.id);
        else if (t.kind === "mcp") P.draft.denied = flip(P.draft.denied, t.id);
        else P.draft.disabledPlugins = flip(P.draft.disabledPlugins, t.id);
        renderProfiles();
      });
      list.append(el("div", { class: "p-tool" }, el("span", { class: "p-label", title: t.id }, t.label), t.locked ? el("span", { class: "dim p-lock" }, "always on") : null, sw));
    }
    kids.push(list);
  }
  const dirty = isDirty();
  const revert = el("button", { type: "button", class: "act", disabled: !dirty }, "Revert");
  revert.addEventListener("click", () => { P.draft = null; renderProfiles(); });
  const save = el("button", { type: "button", class: "act primary", disabled: !dirty }, "Save and push");
  save.addEventListener("click", () => saveProfile(save));
  kids.push(el("div", { class: "row-actions p-actions" }, revert, save));
  return el("section", { class: "p-panel" }, kids);
}

function renderProfiles() {
  const main = document.getElementById("p-main");
  const d = P.data;
  if (!d.configured) {
    document.getElementById("p-tree").replaceChildren();
    return main.replaceChildren(el("p", {}, "Profiles are not set up on this machine. Write profiles.json in the fleet's folder, for example:"),
      el("pre", { class: "mono p-pre" }, '{"roots": ["~/projects/my-env"], "default_dirs": [], "locked": {}, "hidden": []}'),
      el("p", { class: "dim" }, "roots are the repositories whose claude/profiles/ hold <name>.args and <name>.json."));
  }
  document.getElementById("n-profiles").textContent = d.folders.length ? String(d.folders.length) : "";
  renderProfilesTree();
  const kids = [];
  const f = P.folder ? d.folders.find((x) => x.path === P.folder) : null;
  if (P.folder && !f) P.folder = null;
  if (f) {
    const s = f.source;
    const head = el("div", { class: "p-source" }, el("strong", { class: "mono" }, f.display), el("span", {}, sourceText(s)));
    if (s.kind !== "custom") {
      const pick = el("select", { class: "p-select", "aria-label": "Profile for " + f.display, disabled: P.busy },
        el("option", { value: "" }, "inherit"), d.profiles.map((p) => el("option", { value: p.name, selected: s.kind === "here" && s.profile === p.name }, p.name)));
      pick.addEventListener("change", () => { if (!leaveDraft()) { pick.value = s.kind === "here" ? s.profile : ""; return; } setFolderProfile(pick.value || null); });
      head.append(pick);
    }
    kids.push(head);
    if (s.content) kids.push(el("pre", { class: "mono p-pre" }, s.content));
  } else {
    const list = el("div", { class: "p-list" });
    for (const p of d.profiles) {
      const b = el("button", { type: "button", class: "link" }, p.name);
      b.addEventListener("click", () => { if (!leaveDraft()) return; P.editing = p.name; P.draft = null; renderProfiles(); });
      const users = usersOf(p.name);
      list.append(el("div", { class: "p-row" + (P.editing === p.name ? " on" : "") }, b, el("code", { class: "dim" }, p.repo),
        el("span", { class: "dim" }, users.length ? users.map((x) => x.display).join(", ") : "No listed folder uses it.")));
    }
    kids.push(list);
  }
  const refreshBtn = el("button", { type: "button", class: "act" }, "Refresh tools");
  refreshBtn.addEventListener("click", async () => { refreshBtn.disabled = true; refreshBtn.textContent = "Refreshing"; await loadProfiles(true); });
  kids.push(el("div", { class: "p-bar" },
    d.auditFindings ? el("span", { class: "dim" }, d.auditFindings + (d.auditFindings === 1 ? " cleanup finding" : " cleanup findings") + (d.auditHint ? ": run " + d.auditHint : "")) : el("span", {}),
    refreshBtn));
  if (d.toolsError) kids.push(el("p", { class: "h-msg bad" }, "MCP servers unavailable: " + d.toolsError));
  if (!P.editing && !f) P.editing = d.profiles.length ? d.profiles[0].name : null;
  const p = profileNamed(P.editing);
  if (p) kids.push(switchesPanel(p));
  else if (P.editing) kids.push(el("p", { class: "h-msg bad" }, "No " + P.editing + ".args was found in any root, so new sessions here fail to start until it exists."));
  main.replaceChildren(...kids);
}

async function loadProfiles(refresh) {
  const main = document.getElementById("p-main");
  if (!P.data) main.replaceChildren(el("p", { class: "dim" }, "Reading the profiles. The MCP server list can take a few seconds."));
  try {
    P.data = await getJSON("/api/profiles" + (refresh ? "?refresh=1" : ""));
    if (!H.home) H.home = P.data.home;
    renderProfiles();
  } catch (e) { pmsg("Cannot load the profiles: " + e.message, true); }
}

function initProfiles() {
  if (matchMedia("(max-width: 720px)").matches) document.getElementById("p-tree-box").open = false;
  addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
}

function renderNotices(lists) {
  const seen = new Map();
  for (const l of lists) for (const n of (l && l.notices) || []) seen.set(n.text, n);
  document.getElementById("notices").replaceChildren(...[...seen.values()].map((n) => el("div", { class: "notice" }, n.text)));
}

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) {
    let why = "";
    try { why = (await r.json()).error || ""; } catch (e) {}
    throw new Error(why || path + " " + r.status);
  }
  return r.json();
}

let busy = false;
async function refresh(withInbox) {
  if (busy) return;
  busy = true;
  const stamp = document.getElementById("stamp");
  try {
    const [m, t, th] = await Promise.all([getJSON("/api/members"), getJSON("/api/todos"), getJSON("/api/threads")]);
    const now = Date.now();
    renderMembers(m, now); renderTodos(t, now); renderThreads(th, now); renderNotices([m, t, th]);
    loadInbox();
    stamp.textContent = "Updated " + new Date(now).toLocaleTimeString() + ", every " + REFRESH / 1000 + " s";
  } catch (e) {
    stamp.textContent = "Cannot reach the server (" + e.message + "), retrying";
  } finally { busy = false; }
}

function showView(id) {
  if (!VIEWS.some((v) => v.id === id)) id = VIEWS[0].id;
  if (id === "history" && !H.loaded) loadHistory();
  if (id === "profiles" && !P.data) loadProfiles();
  document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== id));
  document.querySelectorAll("#tabs button").forEach((b) => (b.dataset.view === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
}

function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("fleet-theme", t) : localStorage.removeItem("fleet-theme"); } catch (e) {}
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("fleet-theme"); } catch (e) {}
  if (saved) setTheme(saved);
  document.getElementById("theme").addEventListener("click", () => {
    const dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
    setTheme(dark ? "light" : "dark");
  });
}

function start() {
  initTheme();
  initHistory();
  initProfiles();
  initTodoForm();
  const tabs = document.getElementById("tabs");
  VIEWS.forEach((v) => tabs.append(el("button", { type: "button", "data-view": v.id, onclick: null }, v.label)));
  tabs.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.view; }));
  addEventListener("hashchange", () => showView(location.hash.slice(1)));
  showView(location.hash.slice(1));
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, REFRESH);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}
start();
