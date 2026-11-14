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

// More Lucide 0.460.0 (ISC) icons for the views' headers, tabs and empty states.
Object.assign(ICONS, {
  "users": [["path", { d: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" }], ["circle", { cx: "9", cy: "7", r: "4" }], ["path", { d: "M22 21v-2a4 4 0 0 0-3-3.87" }], ["path", { d: "M16 3.13a4 4 0 0 1 0 7.75" }]],
  "inbox": [["polyline", { points: "22 12 16 12 14 15 10 15 8 12 2 12" }], ["path", { d: "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" }]],
  "history": [["path", { d: "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" }], ["path", { d: "M3 3v5h5" }], ["path", { d: "M12 7v5l4 2" }]],
  "settings-2": [["path", { d: "M20 7h-9" }], ["path", { d: "M14 17H5" }], ["circle", { cx: "17", cy: "17", r: "3" }], ["circle", { cx: "7", cy: "7", r: "3" }]],
  "list-todo": [["rect", { x: "3", y: "5", width: "6", height: "6", rx: "1" }], ["path", { d: "m3 17 2 2 4-4" }], ["path", { d: "M13 6h8" }], ["path", { d: "M13 12h8" }], ["path", { d: "M13 18h8" }]],
  "messages-square": [["path", { d: "M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" }], ["path", { d: "M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" }]],
  "search": [["circle", { cx: "11", cy: "11", r: "8" }], ["path", { d: "m21 21-4.3-4.3" }]],
  "plus": [["path", { d: "M5 12h14" }], ["path", { d: "M12 5v14" }]],
  "send": [["path", { d: "M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" }], ["path", { d: "m21.854 2.147-10.94 10.939" }]],
  "moon": [["path", { d: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" }]],
});
const VIEW_ICONS = { fleet: "users", foryou: "inbox", history: "history", profiles: "settings-2" };

// A list's empty state: an icon and one line.
const empty = (ic, text) => el("div", { class: "empty-box" }, sicon(ic, "empty-ic"), el("p", {}, text));
const pill = (state, text) => el("span", { class: "pill " + state }, el("span", { class: "dot" }), text || state);
// A member may run on another machine with another home folder, so its own home is collapsed, whatever it is.
const homeless = (p) => (p || "").replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
const machineTag = (m) => (m ? el("span", { class: "tag" }, m) : null);
function headCount(id, n, extra) {
  const c = document.getElementById(id);
  if (c) c.replaceChildren(...(n ? [el("span", { class: "n" }, String(n))] : []), ...(extra || []));
}

const SELF = { machine: "" };
const target = (m) => (!m.machine || m.machine === SELF.machine ? m.name : m.name + "@" + m.machine);
const M = { open: null, showLeft: false };  // { key, kind } of the compose row that is open; the left members shown

// A notice above a view. A success fades after 6 s; an error stays until the next notice or a successful reload.
const FLASH = {};
function flash(id, text, bad) {
  const m = document.getElementById(id);
  clearTimeout(FLASH[id]);
  m.className = "h-msg toast" + (bad ? " bad" : "") + (text ? " on" : "");
  m.textContent = text || "";
  if (text && !bad) FLASH[id] = setTimeout(() => { if (m.textContent === text) flash(id, ""); }, 6000);
}
const mmsg = (text, bad) => flash("m-msg", text, bad);

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

function composeBox(m) {
  const ask = M.open.kind === "ask";
  const t = el("textarea", { rows: "3", class: "h-input", "aria-label": (ask ? "Question for " : "Instruction for ") + m.name, placeholder: ask ? "Ask " + m.name + " a question" : "Tell " + m.name + " what to do" });
  t.value = M.open.draft || "";
  t.addEventListener("input", () => { M.open.draft = t.value; });
  const send = el("button", { type: "button", class: "act primary ic-btn" }, sicon("send"), ask ? "Send question" : "Send instruction");
  const cancel = el("button", { type: "button", class: "act" }, "Cancel");
  const go = async () => {
    if (!t.value.trim() || send.disabled) return;
    send.disabled = true;
    try {
      const d = await post("/api/tell", { target: target(m), text: t.value, kind: M.open.kind });
      const last = (d.output || "").split("\n").pop();
      // the CLI ends with the delivery state; a failed post is not a success, whatever the request answered
      if (/: failed\b/.test(last)) mmsg("Not delivered to " + m.name + " (" + last + "). The message is kept and sent again if " + m.name + " rejoins within a day.", true);
      else mmsg("Sent to " + m.name + " as you. " + last);
      M.open = null; renderMembersNow(); refresh(true);
    } catch (e) { mmsg(e.message, true); send.disabled = false; }
  };
  send.addEventListener("click", go);
  cancel.addEventListener("click", () => { M.open = null; renderMembersNow(); });
  t.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(); });
  return el("div", { class: "compose" }, el("div", { class: "compose-head" }, sicon(ask ? "message-circle-question" : "message-square"), ask ? "Ask " + m.name : "Tell " + m.name, el("span", { class: "dim" }, "as you, ⌘ Enter sends")),
    t, el("div", { class: "row-actions" }, send, cancel));
}

let lastMembers = null;
// What a member is doing now, worked out by the server when it read the page's data (never stored): the raw status
// Claude Code gives it, what it holds and what it owes, and "free" only when all of that is known and empty.
const ACTIVITY = { busy: ["ok", "Working on a turn"], idle: ["dimc", "Between turns"], waiting: ["warn", "A prompt is open: it waits for an answer or a permission"], unknown: ["bad", "Claude Code did not say; treat it as busy"] };
function nowLine(m, now) {
  const kids = [];
  if (m.status === "alive") {
    const a = m.activity || "unknown";
    const [cls, what] = ACTIVITY[a] || ["dimc", "Status reported by Claude Code"];
    const read = m.as_of ? "Read at " + new Date(m.as_of * 1000).toLocaleTimeString() + (m.machine ? " on " + m.machine : "") : "";
    kids.push(el("span", { class: "pill " + cls, title: what + (read ? ". " + read : "") }, el("span", { class: "dot" }), a));
    if (m.free) kids.push(el("span", { class: "tag free" }, "free"));
  }
  for (const t of m.held || []) kids.push(el("span", { class: "tag", title: t.title }, "holds #" + t.id + " " + t.title));
  for (const u of m.unanswered || []) kids.push(el("span", { class: "tag ghost", title: when(u.created_at) }, u.kind + " " + u.id + " from " + u.sender + " unanswered, " + ago(u.created_at, now)));
  return kids.length ? el("div", { class: "ml-now" }, kids) : null;
}

function renderMembersNow() { if (lastMembers) renderMembers(lastMembers.data, lastMembers.now, true); }

function renderMembers(data, now, force) {
  if (data.machine) SELF.machine = data.machine;
  if (data.home && !H.home) H.home = data.home;
  lastMembers = { data, now };
  if (!force && (document.querySelector("#members .compose textarea") || document.querySelector("#members button[data-sure]"))) return;  // never wipe what is being typed or a pending confirmation
  const order = { alive: 0, dead: 1, left: 2 };
  const rows = data.members.slice().sort((a, b) => order[a.status] - order[b.status] || (b.joined_at || 0) - (a.joined_at || 0));
  const here = rows.filter((m) => m.status !== "left"), left = rows.filter((m) => m.status === "left");
  const alive = here.filter((m) => m.status === "alive").length;
  const read = rows.find((m) => m.as_of && (!m.machine || m.machine === SELF.machine));
  headCount("n-members", here.length, rows.length ? [el("span", { class: "dim" }, alive + " alive"),
    read ? el("span", { class: "dim" }, "· state read " + new Date(read.as_of * 1000).toLocaleTimeString()) : null].filter(Boolean) : []);
  const box = document.getElementById("members");
  if (!rows.length) return box.replaceChildren(empty("users", "No sessions have joined this fleet yet. Run /fleet join in a session."));
  const row = (m) => {
    const li = el("li", { class: "row ml-row " + m.status },
      el("span", { class: "ml-status" }, pill(m.status)),
      el("span", { class: "ml-name" }, el("strong", {}, m.name), el("code", { class: "dim" }, m.session_id.slice(0, 8))),
      el("span", { class: "ml-machine" }, machineTag(m.machine)),
      el("code", { class: "ml-folder", title: m.cwd }, !m.machine || m.machine === SELF.machine ? tilde(m.cwd || "") : homeless(m.cwd)),
      el("span", { class: "ml-when dim", title: when(m.joined_at) }, ago(m.joined_at, now)),
      memberActions(m), nowLine(m, now));
    if (M.open && M.open.key === m.machine + "/" + m.session_id) li.append(composeBox(m));
    return li;
  };
  const parts = [here.length ? el("ul", { class: "list ml" }, here.map(row))
    : empty("users", "No session is in the fleet right now. Run /fleet join in a session.")];
  if (left.length) {
    // Sessions that ended or ran /fleet leave: closed by default, opened only for a respawn. Kept open across polls.
    const label = el("summary", { class: "dim" });
    const d = el("details", { class: "ml-left" }, label, el("ul", { class: "list ml" }, left.map(row)));
    const say = () => { label.textContent = (d.open ? "Hide " : "Show ") + left.length + " left"; };
    d.open = M.showLeft; say();
    d.addEventListener("toggle", () => { M.showLeft = d.open; say(); });
    parts.push(d);
  }
  box.replaceChildren(...parts);
}

function renderTodos(data) {
  const rows = data.todos;
  const live = rows.filter((t) => t.state !== "done").length;
  headCount("n-todos", live, rows.length > live ? [el("span", { class: "dim" }, (rows.length - live) + " done")] : []);
  const box = document.getElementById("todos");
  if (!rows.length) return box.replaceChildren(empty("list-todo", "The backlog is empty."));
  const item = (t) => el("li", { class: "row td-row " + t.state },
    el("span", { class: "td-id dim" }, "#" + t.id),
    el("span", { class: "td-main" }, el("span", { class: "td-title" }, t.title),
      t.notes ? el("details", { class: "td-notes" }, el("summary", { class: "dim" }, "Notes"), el("div", { class: "dim" }, t.notes)) : null),
    el("span", { class: "td-holder" }, t.claimed_by ? el("span", { class: "tag" }, t.claimed_by) : t.reserved_for ? el("span", { class: "tag ghost" }, "for " + t.reserved_for) : null,
      t.owner && t.owner !== t.claimed_by ? el("span", { class: "tag" + (t.owner_gone ? " gone" : ""), title: t.owner_gone ? "No live member has this name" : "Meant for this member" }, "for " + t.owner + (t.owner_gone ? " (gone)" : "")) : null,
      t.state !== "done" && (t.waits_on || []).length ? el("span", { class: "tag ghost" }, "waits on " + t.waits_on.map((i) => "#" + i).join(", "))
        : t.state === "open" && (t.after || []).length ? el("span", { class: "tag free" }, "ready") : null),
    t.ref ? el("code", { class: "td-ref dim", title: t.ref }, t.ref) : el("span", {}),
    el("span", { class: "td-machine" }, machineTag(t.machine)));
  const group = (state, label) => {
    const g = rows.filter((t) => t.state === state);
    return g.length ? el("div", { class: "group" }, el("div", { class: "group-head" }, pill(state, label), el("span", { class: "dim" }, String(g.length))), el("ul", { class: "list" }, g.map(item))) : null;
  };
  const done = rows.filter((t) => t.state === "done");
  box.replaceChildren(...[group("open", "Open"), group("claimed", "Claimed"),
    done.length ? el("details", { class: "group" }, el("summary", {}, pill("done", "Done"), el("span", { class: "dim" }, String(done.length))), el("ul", { class: "list" }, done.map(item))) : null].filter(Boolean));
}

function initTodoForm() {
  document.getElementById("todo-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = (id) => document.getElementById(id);
    try {
      const d = await post("/api/todos/add", { title: f("todo-title").value, ref: f("todo-ref").value, notes: f("todo-notes").value });
      flash("todo-msg", "Added to-do " + d.id + ".");
      for (const id of ["todo-title", "todo-ref", "todo-notes"]) f(id).value = "";
      refresh(true);
    } catch (err) { flash("todo-msg", err.message, true); }
  });
}

// ---------------------------------------------------------------- For you

const Y = { items: [], drafts: new Map(), answering: null };
const fymsg = (text, bad) => flash("fy-msg", text, bad);

function setBadge(n) {
  const b = document.querySelector('#tabs button[data-view="foryou"]');
  if (!b) return;
  b.replaceChildren(sicon(VIEW_ICONS.foryou), "For you", n ? el("span", { class: "badge", "aria-label": n + " waiting for you" }, String(n)) : "");
  document.title = n ? "(" + n + ") Fleet" : "Fleet";
}

function lungoItem(i, now) {  // read from Lungo when the page loaded; acted on in Lungo, never here
  return el("li", { class: "fy-item k-lungo" },
    el("div", { class: "fy-head" }, el("span", { class: "kind k-lungo" }, i.lungo_kind || i.attention),
      el("strong", {}, i.title), machineTag(i.machine),
      i.created_at ? el("span", { class: "dim", title: when(i.created_at) }, ago(i.created_at, now)) : null),
    el("div", { class: "msg-body" }, i.body),
    el("div", { class: "fy-reply" }, "From Lungo (job " + i.job + "). Act on it in Lungo."));
}

function fyItem(i, now) {
  if (i.kind === "lungo") return lungoItem(i, now);
  const done = i.answered_at !== null;
  const kind = i.kind === "notify" ? "notice" : i.kind;
  const kids = [el("div", { class: "fy-head" }, el("span", { class: "kind k-" + i.kind }, kind),
    el("strong", {}, i.sender), SELF.machine && i.machine !== SELF.machine ? machineTag(i.machine) : null,
    el("span", { class: "dim", title: when(i.created_at) }, ago(i.created_at, now))),
    el("div", { class: "msg-body" }, i.body)];
  if (done) { kids.push(el("div", { class: "fy-reply" }, i.reply ? "You answered: " + i.reply : "Dismissed")); return el("li", { class: "fy-item done" }, kids); }
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
  kids.push(el("div", { class: "fy-answer" }, input, el("div", { class: "row-actions" }, send, dismiss)));
  return el("li", { class: "fy-item k-" + i.kind }, kids);
}

function renderInbox(data) {
  if (data.machine) SELF.machine = data.machine;
  Y.items = data.items; Y.open = data.open;
  setBadge(data.open);
  headCount("n-foryou", data.open);
  const box = document.getElementById("foryou");
  if (box.querySelector("textarea:focus")) return;  // never wipe what is being typed
  const now = Date.now();
  const open = data.items.filter((i) => i.answered_at === null), done = data.items.filter((i) => i.answered_at !== null);
  const kids = [];
  if (data.lungo) kids.push(el("p", { class: "fy-source " + (data.lungo.ok ? "dim" : "bad") }, data.lungo.line));
  kids.push(open.length ? el("ul", { class: "list fy" }, open.map((i) => fyItem(i, now)))
    : empty("inbox", data.lungo && !data.lungo.ok ? "Nothing from the fleet. Lungo could not be read." : "Nothing is waiting for you."));
  if (done.length) kids.push(el("details", { class: "group" }, el("summary", {}, "Answered or dismissed", el("span", { class: "dim" }, String(done.length))), el("ul", { class: "list fy" }, done.map((i) => fyItem(i, now)))));
  box.replaceChildren(...kids);
}

async function loadInbox() {
  try { renderInbox(await getJSON("/api/inbox")); }
  catch (e) { fymsg("Cannot load your inbox: " + e.message, true); }
}

// ---------------------------------------------------------------- History

const H = { rows: [], counts: { total: 0, described: 0 }, home: "", folder: null, q: "", found: null, open: null, shown: 100, loaded: false, busy: false, closed: null, renaming: null };
const PAGE = 100;

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || path + " " + r.status);
  return data;
}

const say = (text, bad) => flash("h-msg", text, bad);

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
  return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : tilde(p || "") || "(none)";
}

// The History tree draws like the Profiles tree: connector lines, a folder icon, and a session count per row.
function renderTree() {
  const box = document.getElementById("h-tree");
  const { top, base } = folderTree(H.rows);
  if (!H.closed) {
    H.closed = new Set();
    const walk = (n, depth) => { if (depth > 1) H.closed.add(n.path); n.kids.forEach((k) => walk(k, depth + 1)); };
    base.kids.forEach((k) => walk(k, 0));
  }
  const sorted = (n) => [...n.kids.values()].sort((a, b) => b.count - a.count || a.seg.localeCompare(b.seg));
  const sel = (path) => { H.folder = H.folder === path ? null : path; H.shown = PAGE; renderHistory(); };
  const item = (n) => {
    const kids = sorted(n);
    const inside = H.folder && H.folder.startsWith(n.path + "/");
    const closed = H.closed.has(n.path) && !inside;
    const tog = kids.length ? el("button", { type: "button", class: "t-tog", "aria-label": (closed ? "Open " : "Fold ") + n.seg, "aria-expanded": closed ? "false" : "true" }, sicon(closed ? "chevron-right" : "chevron-down"))
      : el("span", { class: "t-tog t-none" });
    if (kids.length) tog.addEventListener("click", () => { H.closed.has(n.path) ? H.closed.delete(n.path) : H.closed.add(n.path); renderTree(); });
    const row = el("button", { type: "button", class: "t-row" + (H.folder === n.path ? " sel" : ""), "aria-pressed": H.folder === n.path ? "true" : "false", title: n.path.replace(/^\/~/, "~") },
      sicon("folder", "t-ic"), el("span", { class: "t-name" }, ...slashBreaks(n.seg || "/")), el("span", { class: "t-n" }, String(n.count)));
    row.addEventListener("click", () => sel(n.path));
    return el("li", { class: inside || H.folder === n.path ? "on-path" : "" }, el("div", { class: "t-line" }, tog, row), kids.length && !closed ? el("ul", {}, kids.map(item)) : null);
  };
  const all = el("button", { type: "button", class: "t-row t-all" + (H.folder === null ? " sel" : ""), "aria-pressed": H.folder === null ? "true" : "false" },
    sicon("layers", "t-ic"), el("span", { class: "t-name" }, "All sessions"), el("span", { class: "t-n" }, String(top.count)));
  all.addEventListener("click", () => { H.folder = null; H.shown = PAGE; renderHistory(); });
  const prefix = base.seg && base !== top ? el("div", { class: "t-root mono", title: base.seg }, base.seg) : null;
  const own = base.own ? el("div", { class: "t-root" }, base.own + " directly in " + base.path.replace(/^\/~/, "~")) : null;
  box.replaceChildren(...[all, prefix, el("ul", { class: "t-tree" }, sorted(base).map(item)), own].filter(Boolean));
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

function nameBox(r) {
  const box = el("div", { class: "hs-name" });
  if (H.renaming === r.id) {
    const input = el("input", { type: "text", value: r.name, "aria-label": "New name", class: "h-input" });
    const save = el("button", { type: "button", class: "act primary" }, "Save");
    const cancel = el("button", { type: "button", class: "act" }, "Cancel");
    const go = () => act(async () => { await post("/api/history/rename", { id: r.id, name: input.value }); H.renaming = null; await loadHistory(); });
    save.addEventListener("click", go);
    cancel.addEventListener("click", () => { H.renaming = null; renderRows(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") { H.renaming = null; renderRows(); } });
    box.append(input, el("div", { class: "row-actions" }, save, cancel));
    setTimeout(() => { input.focus(); input.select(); });
    return box;
  }
  const label = r.name || r.about || "(unnamed)";
  const open = el("button", { type: "button", class: "link" + (r.name ? "" : " muted"), title: label, "aria-expanded": H.open === r.id ? "true" : "false" }, label);
  open.addEventListener("click", () => { H.open = H.open === r.id ? null : r.id; renderRows(); });
  box.append(open, el("code", { class: "dim" }, r.id.slice(0, 8)));
  return box;
}

function historyActions(r) {
  const box = el("div", { class: "actions" });
  const mk = ibtn;
  box.append(
    mk("message-circle-question", "Ask", () => { H.open = r.id; renderRows(); const q = document.getElementById("ask-" + r.id); if (q) q.focus(); }),
    mk("pencil", "Rename", () => { H.renaming = r.id; renderRows(); }),
    mk("copy", "Copy resume", (b) => copy(r.resume, b)),
    mk("trash-2", "Delete", (b) => {
      if (b.dataset.sure) return act(async () => { await post("/api/history/delete", { id: r.id }); if (H.open === r.id) H.open = null; await loadHistory(); }, "Removed from the history. The transcript is untouched.");
      b.dataset.sure = "1"; b.classList.add("confirming"); b.replaceChildren(icon("trash-2"), el("span", {}, "Confirm"));
      b.setAttribute("aria-label", "Confirm delete"); b.title = "Press again to delete";
      setTimeout(() => { if (b.isConnected) { delete b.dataset.sure; b.classList.remove("confirming"); b.replaceChildren(icon("trash-2")); b.setAttribute("aria-label", "Delete"); b.title = "Delete"; } }, 4000);
    }, "danger-hover"));
  return box;
}

function detailBox(r) {
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
  return el("div", { class: "detail" },
    r.description ? el("p", { class: "h-desc" }, r.description) : el("p", { class: "dim" }, "No description yet. fleet history describe writes one."),
    r.about ? el("p", { class: "dim" }, "Opened with: " + r.about) : null,
    el("code", { class: "dim d-path" }, r.transcript || "no transcript path"),
    el("div", { class: "h-ask" }, q, ask), answer);
}

function renderRows() {
  const rows = visibleRows();
  const box = document.getElementById("h-rows");
  const found = H.found;
  const head = found ? el("p", { class: "h-found" }, found.hits.length ? "Matches by meaning, best first (" + found.hits.length + ")" : "No description matches that.") : null;
  if (!rows.length) {
    return box.replaceChildren(...[head, H.rows.length ? (found ? null : empty("search", "No session matches.")) : empty("history", "No sessions recorded yet. They appear as sessions run, or import an old store with fleet history import.")].filter(Boolean));
  }
  const now = Date.now();
  const list = el("ul", { class: "list hs" }, rows.slice(0, H.shown).map((r) => el("li", { class: "row hs-row" + (H.open === r.id ? " open" : "") },
    nameBox(r),
    el("div", { class: "hs-about dim" }, found ? r.why : (r.description || r.about)),
    el("code", { class: "hs-folder", title: tilde(r.folder || "") }, shortFolder(r.folder)),
    el("span", { class: "hs-when dim", title: "Started " + when(r.started) + ", last seen " + when(r.last_seen) }, ago(r.last_seen || r.started, now)),
    historyActions(r),
    H.open === r.id ? detailBox(r) : null)));
  const more = rows.length > H.shown ? el("button", { type: "button", class: "act more" }, "Show " + Math.min(PAGE, rows.length - H.shown) + " more of " + (rows.length - H.shown)) : null;
  if (more) more.addEventListener("click", () => { H.shown += PAGE; renderRows(); });
  box.replaceChildren(...[head, list, more].filter(Boolean));
}

function renderHistory() {
  const c = H.counts;
  headCount("n-history", c.total);
  document.getElementById("h-note").textContent = c.total
    ? c.described + " of " + c.total + " sessions have a description, which search by meaning reads. fleet history describe writes the rest."
      + (c.unreadable ? " Warning: " + c.unreadable + " transcript" + (c.unreadable === 1 ? "" : "s") + " could not be read: has the transcript format changed?" : "")
    : "";
  document.getElementById("h-clear").hidden = !H.found;
  const crumb = document.getElementById("h-crumb");
  crumb.textContent = H.folder ? H.folder.replace(/^\/~/, "~") : "All sessions";
  crumb.className = H.folder ? "mono" : "";
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

// P.folder: a listed folder's absolute path, or null for every folder. P.editing: the profile whose switches show.
// P.draft: the switches as edited and not yet saved, or null. P.closed: tree nodes folded by hand (or by default).
const P = { data: null, folder: null, editing: null, draft: null, busy: false, closed: null };
const GROUPS = [
  { kind: "pluginDir", title: "Plugin folders", icon: "folder", note: "Loaded with --plugin-dir: skills, commands and hooks from a local checkout." },
  { kind: "mcp", title: "MCP servers", icon: "server", note: "Off means denied in the profile's settings." },
  { kind: "plugin", title: "Marketplace plugins", icon: "package", note: "Installed plugins; off means disabled for this profile." },
];
// Lucide 0.460.0 (ISC) path data, as the icons above.
Object.assign(ICONS, {
  "folder": [["path", { d: "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" }]],
  "chevron-down": [["path", { d: "m6 9 6 6 6-6" }]],
  "chevron-right": [["path", { d: "m9 18 6-6-6-6" }]],
  "lock": [["rect", { width: "18", height: "11", x: "3", y: "11", rx: "2", ry: "2" }], ["path", { d: "M7 11V7a5 5 0 0 1 10 0v4" }]],
  "server": [["rect", { width: "20", height: "8", x: "2", y: "2", rx: "2", ry: "2" }], ["rect", { width: "20", height: "8", x: "2", y: "14", rx: "2", ry: "2" }], ["line", { x1: "6", x2: "6.01", y1: "6", y2: "6" }], ["line", { x1: "6", x2: "6.01", y1: "18", y2: "18" }]],
  "package": [["path", { d: "M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" }], ["path", { d: "M12 22V12" }], ["path", { d: "m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7" }], ["path", { d: "m7.5 4.27 9 5.15" }]],
  "layers": [["path", { d: "m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" }], ["path", { d: "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" }], ["path", { d: "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" }]],
  "refresh-cw": [["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" }], ["path", { d: "M21 3v5h-5" }], ["path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" }], ["path", { d: "M8 16H3v5" }]],
});
const sicon = (name, cls) => { const s = icon(name); s.setAttribute("class", "ic" + (cls ? " " + cls : "")); return s; };

const pmsg = (text, bad) => flash("p-msg", text, bad);

const isOn = (d, t) => (t.kind === "pluginDir" ? d.pluginDirs.includes(t.id) : t.kind === "mcp" ? !d.denied.includes(t.id) : !d.disabledPlugins.includes(t.id));
const flip = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : list.concat([id]));
const draftOf = (p) => ({ pluginDirs: p.pluginDirs.slice(), denied: p.denied.slice(), disabledPlugins: p.disabledPlugins.slice() });
const profileNamed = (name) => (P.data ? P.data.profiles.find((p) => p.name === name) || null : null);
const usersOf = (name) => P.data.folders.filter((f) => f.source.profile === name);

// The tools whose switch differs between the saved profile and the draft.
function changed() {
  const p = profileNamed(P.editing);
  if (!p || !P.draft) return [];
  return P.data.tools.filter((t) => isOn(p, t) !== isOn(P.draft, t));
}
const isDirty = () => changed().length > 0;

function leaveDraft() {
  if (!isDirty()) return true;
  if (!confirm("Discard unsaved changes to " + P.editing + "?")) return false;
  P.draft = null;
  return true;
}

// A profile's colour: a hue from its name, so "evooq" is the same colour everywhere and forever.
function hue(name) { let h = 0; for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0; return (h % 24) * 15; }
const chip = (name, cls) => el("span", { class: "chip" + (cls ? " " + cls : ""), style: "--h:" + hue(name) }, name);

// A select that is not the browser's: a button showing the choice, and a list that opens under it.
// options: [{ value, title, sub, chip }]. Arrow keys move, Enter or Space picks, Escape closes.
function dropdown(label, value, options, onPick, disabled) {
  const box = el("div", { class: "dd" });
  const cur = options.find((o) => o.value === value) || options[0];
  const face = (o) => [o.chip ? chip(o.chip) : el("span", { class: "dd-title" }, o.title), o.sub ? el("span", { class: "dd-sub" }, o.sub) : null];
  const btn = el("button", { type: "button", class: "dd-btn", "aria-haspopup": "listbox", "aria-expanded": "false", "aria-label": label + ": " + cur.title, disabled }, ...face(cur), sicon("chevron-down", "dd-chev"));
  const menu = el("ul", { class: "dd-menu", role: "listbox", "aria-label": label, hidden: true });
  const items = options.map((o) => {
    const li = el("li", { role: "option", tabindex: "-1", "aria-selected": o.value === value ? "true" : "false", class: o.value === value ? "sel" : "" },
      el("span", { class: "dd-check" }, o.value === value ? sicon("check") : null), el("span", { class: "dd-col" }, ...face(o)));
    li.addEventListener("click", () => { close(); if (o.value !== value) onPick(o.value); });
    menu.append(li);
    return li;
  });
  const outside = (e) => { if (!box.contains(e.target)) close(); };
  function open() {
    menu.hidden = false; btn.setAttribute("aria-expanded", "true"); box.classList.add("open");
    (items.find((li) => li.classList.contains("sel")) || items[0]).focus();
    document.addEventListener("mousedown", outside);
  }
  function close(focus) {
    menu.hidden = true; btn.setAttribute("aria-expanded", "false"); box.classList.remove("open");
    document.removeEventListener("mousedown", outside);
    if (focus) btn.focus();
  }
  btn.addEventListener("click", () => (menu.hidden ? open() : close()));
  btn.addEventListener("keydown", (e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); } });
  menu.addEventListener("keydown", (e) => {
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(items.length - 1, i + 1)].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[Math.max(0, i - 1)].focus(); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (i >= 0) items[i].click(); }
    else if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") close();
  });
  box.append(btn, menu);
  return box;
}

function sourceLine(s) {
  if (s.kind === "here") return [el("span", {}, "New sessions here run"), chip(s.profile), el("span", { class: "dim" }, "set in this folder")];
  if (s.kind === "inherited" && s.profile) return [el("span", {}, "New sessions here run"), chip(s.profile), el("span", { class: "dim" }, "inherited from "), el("code", {}, s.from)];
  if (s.kind === "inherited") return [el("span", {}, "A hand-written file in "), el("code", {}, s.from), el("span", {}, " decides.")];
  if (s.kind === "custom") return [el("span", {}, "A hand-written .claude-launch in this folder decides its tools.")];
  return [el("span", {}, "No profile applies here, so new sessions get the launcher's defaults.")];
}

// ---- the folder tree: connector lines, a folder icon per row, the profile as a coloured chip

function renderProfilesTree() {
  const box = document.getElementById("p-tree");
  const folders = P.data.folders;
  const byKey = new Map(folders.map((f) => [folderKey({ folder: f.path }), f]));
  const { top, base } = folderTree(folders.map((f) => ({ folder: f.path })));
  const used = (n) => folders.reduce((sum, x) => { const k = folderKey({ folder: x.path }); return sum + (k === n.path || k.startsWith(n.path + "/") ? x.sessions : 0); }, 0);
  const byUse = (list) => list.map((n) => [used(n), n]).sort((a, b) => b[0] - a[0] || a[1].seg.localeCompare(b[1].seg)).map((x) => x[1]);
  if (!P.closed) {  // a folder with many subfolders (a pile of scratch runs) starts folded
    P.closed = new Set();
    const walk = (n) => { if (n.kids.size > 8) P.closed.add(n.path); n.kids.forEach(walk); };
    walk(base);
  }
  const selKey = P.folder ? folderKey({ folder: P.folder }) : null;
  const pick = (f) => { if (!f || !leaveDraft()) return; P.folder = f.path; P.editing = f.source.profile; P.draft = null; renderProfiles(); };
  const item = (n) => {
    const f = byKey.get(n.path);
    const kids = byUse([...n.kids.values()]);
    const closed = P.closed.has(n.path) && !(selKey && selKey.startsWith(n.path + "/"));
    const onPath = selKey && (selKey === n.path || selKey.startsWith(n.path + "/"));
    const tog = kids.length ? el("button", { type: "button", class: "t-tog", "aria-label": (closed ? "Open " : "Fold ") + n.seg, "aria-expanded": closed ? "false" : "true" }, sicon(closed ? "chevron-right" : "chevron-down"))
      : el("span", { class: "t-tog t-none" });
    if (kids.length) tog.addEventListener("click", () => { P.closed.has(n.path) ? P.closed.delete(n.path) : P.closed.add(n.path); renderProfilesTree(); });
    const s = f ? f.source : null;
    const right = s && s.profile ? chip(s.profile, s.kind === "here" ? "" : "ghost") : kids.length && closed ? el("span", { class: "t-n" }, String(kids.length)) : null;
    const row = el("button", { type: "button", class: "t-row" + (f && P.folder === f.path ? " sel" : "") + (f ? "" : " pass"), disabled: !f, title: f ? f.display + (s.kind === "inherited" && s.profile ? ", inherits " + s.profile : "") : null, "aria-current": f && P.folder === f.path ? "true" : null },
      sicon("folder", "t-ic"), el("span", { class: "t-name" }, ...slashBreaks(n.seg)), right);
    row.addEventListener("click", () => pick(f));
    return el("li", { class: onPath ? "on-path" : "" }, el("div", { class: "t-line" }, tog, row), kids.length && !closed ? el("ul", {}, kids.map(item)) : null);
  };
  const all = el("button", { type: "button", class: "t-row t-all" + (P.folder === null ? " sel" : ""), "aria-current": P.folder === null ? "true" : null },
    sicon("layers", "t-ic"), el("span", { class: "t-name" }, "All folders"), el("span", { class: "t-n" }, P.data.profiles.length + " profiles"));
  all.addEventListener("click", () => { if (!leaveDraft()) return; P.folder = null; P.editing = null; P.draft = null; renderProfiles(); });
  const rootLabel = base.seg && base !== top ? el("div", { class: "t-root mono", title: base.seg }, base.seg.replace(/^\/?/, "")) : null;
  box.replaceChildren(all, ...(rootLabel ? [rootLabel] : []), el("ul", { class: "t-tree" }, byUse([...base.kids.values()]).map(item)));
}

// ---- writes

async function setFolderProfile(name) {
  if (P.busy) return;
  P.busy = true; pmsg("");
  try {
    const d = await post("/api/profiles/folder", { folder: P.folder, profile: name });
    const f = P.data.folders.find((x) => x.path === P.folder);
    pmsg((f ? f.display : P.folder) + (name ? " now uses " + name + "." : " now inherits."));
    P.editing = d.source.profile; P.draft = null;
  } catch (e) { pmsg(e.message, true); }
  P.busy = false;  // before the reload, which draws the select: drawn while busy, it would stay disabled
  await loadProfiles();
}

async function saveProfile(btn) {
  if (P.busy || !P.draft) return;
  const p = profileNamed(P.editing);
  P.busy = true; btn.disabled = true; btn.textContent = "Saving"; pmsg("");
  try {
    const tools = P.data.tools;
    const r = await post("/api/profiles/save", { name: p.name, denied: P.draft.denied, disabledPlugins: P.draft.disabledPlugins,
      pluginDirs: tools.filter((t) => t.kind === "pluginDir" && isOn(P.draft, t)).map((t) => t.id).concat(P.draft.pluginDirs.filter((d) => !tools.some((t) => t.id === d))) });
    if (!r.committed) pmsg("No change to save.");
    else if (r.pushed) pmsg("Saved and pushed: " + r.message);
    else if (!r.hasRemote) pmsg("Saved and committed " + r.commit + ". The repository has no remote to push to.");
    else pmsg("Committed " + r.commit + ", but the push failed: " + r.pushError, true);
    P.draft = null;
    P.busy = false;
    await loadProfiles();
  } catch (e) { pmsg(e.message, true); btn.disabled = false; btn.textContent = "Save and push"; } finally { P.busy = false; }
}

// ---- the right-hand side

const profileOptions = () => P.data.profiles.map((p) => {
  const n = usersOf(p.name).length;
  return { value: p.name, title: p.name, chip: p.name, sub: p.repo + " · " + (n ? n + (n === 1 ? " folder" : " folders") : "no folder") };
});

function scopeCard() {
  const d = P.data;
  const f = P.folder ? d.folders.find((x) => x.path === P.folder) : null;
  if (!f) {
    const rows = d.profiles.map((p) => {
      const users = usersOf(p.name);
      const li = el("li", { class: "pl-row" + (P.editing === p.name ? " sel" : "") },
        el("button", { type: "button", class: "pl-pick", "aria-pressed": P.editing === p.name ? "true" : "false" },
          chip(p.name), el("code", { class: "pl-repo" }, p.repo),
          el("span", { class: "pl-n" }, users.length ? users.length + (users.length === 1 ? " folder" : " folders") : "unused")),
        users.length ? el("div", { class: "pl-users" }, users.map((u) => el("span", { class: "tag mono" }, u.display))) : null);
      li.querySelector("button").addEventListener("click", () => { if (!leaveDraft()) return; P.editing = p.name; P.draft = null; renderProfiles(); });
      return li;
    });
    return el("section", { class: "card" }, el("div", { class: "card-head" }, el("h3", {}, "Every profile"), el("span", { class: "dim" }, "Pick one to see and change its switches.")),
      el("ul", { class: "pl" }, rows));
  }
  const s = f.source;
  const crumbs = f.display.split("/").filter(Boolean);
  const head = el("div", { class: "card-head" }, el("h3", { class: "crumb mono" }, crumbs.map((c, i) => el("span", { class: i === crumbs.length - 1 ? "last" : "" }, (i ? "/" : "") + c))),
    el("span", { class: "dim" }, f.sessions ? f.sessions + (f.sessions === 1 ? " session" : " sessions") : "no session yet"));
  const body = el("div", { class: "src" }, el("div", { class: "src-line" }, sourceLine(s)));
  if (s.kind !== "custom") {
    const opts = [{ value: "", title: "inherit", sub: "use the profile of the nearest folder above" }].concat(profileOptions());
    body.append(el("div", { class: "src-set" }, el("span", { class: "dim" }, "Profile for this folder"),
      dropdown("Profile for this folder", s.kind === "here" ? s.profile : "", opts, (v) => { if (leaveDraft()) setFolderProfile(v || null); }, P.busy)));
  }
  if (s.content) body.append(el("pre", { class: "mono p-pre" }, s.content));
  return el("section", { class: "card" }, head, body);
}

function editorCard(p) {
  if (!P.draft) P.draft = draftOf(p);
  const users = usersOf(p.name);
  const head = el("div", { class: "card-head" }, el("h3", {}, "Switches of"),
    dropdown("Profile to edit", p.name, profileOptions(), (v) => { if (!leaveDraft()) return; P.editing = v; P.draft = null; renderProfiles(); }),
    el("span", { class: "dim" }, "kept in ", el("code", {}, p.repo)));
  const kids = [head];
  if (users.length > 1) kids.push(el("p", { class: "shared" }, "Shared by " + users.length + " folders: a change here applies to all of them."));
  const diff = new Set(changed().map((t) => t.id));
  for (const g of GROUPS) {
    const tools = P.data.tools.filter((t) => t.kind === g.kind);
    if (!tools.length) continue;
    const on = tools.filter((t) => isOn(P.draft, t)).length;
    const list = el("ul", { class: "tl" });
    for (const t of tools) {
      const v = isOn(P.draft, t);
      const sw = el("button", { type: "button", role: "switch", class: "sw" + (v ? " on" : ""), "aria-checked": v ? "true" : "false", "aria-label": t.label, disabled: t.locked },
        el("span", { class: "sw-track" }, el("span", { class: "sw-knob" })), el("span", { class: "sw-text" }, v ? "On" : "Off"));
      sw.addEventListener("click", () => {
        if (t.kind === "pluginDir") P.draft.pluginDirs = flip(P.draft.pluginDirs, t.id);
        else if (t.kind === "mcp") P.draft.denied = flip(P.draft.denied, t.id);
        else P.draft.disabledPlugins = flip(P.draft.disabledPlugins, t.id);
        renderProfiles();
      });
      list.append(el("li", { class: "tl-row" + (v ? "" : " off") + (diff.has(t.id) ? " changed" : "") },
        el("span", { class: "tl-label" }, t.label),
        el("code", { class: "tl-id" }, t.id),
        t.locked ? el("span", { class: "badge-lock", title: "Always on" }, sicon("lock"), "always on") : diff.has(t.id) ? el("span", { class: "badge-chg" }, "changed") : el("span", {}),
        sw));
    }
    kids.push(el("div", { class: "tg" }, el("div", { class: "tg-head" }, sicon(g.icon, "tg-ic"), el("h4", {}, g.title), el("span", { class: "tg-n" }, on + " of " + tools.length + " on")),
      el("p", { class: "tg-note dim" }, g.note), list));
  }
  const n = diff.size;
  const revert = el("button", { type: "button", class: "act", disabled: !n }, "Revert");
  revert.addEventListener("click", () => { P.draft = null; renderProfiles(); });
  const save = el("button", { type: "button", class: "act primary", disabled: !n }, "Save and push");
  save.addEventListener("click", () => saveProfile(save));
  kids.push(el("div", { class: "savebar" + (n ? " dirty" : "") }, el("span", {}, n ? n + (n === 1 ? " unsaved change" : " unsaved changes") + " to " + p.name : "No unsaved changes"), el("span", { class: "grow" }), revert, save));
  return el("section", { class: "card editor" }, kids);
}

function renderProfiles() {
  const main = document.getElementById("p-main");
  const d = P.data;
  if (!d.configured) {
    document.getElementById("p-tree").replaceChildren();
    return main.replaceChildren(el("section", { class: "card" }, el("p", {}, "Profiles are not set up on this machine. Write profiles.json in the fleet's folder, for example:"),
      el("pre", { class: "mono p-pre" }, '{"roots": ["~/projects/my-env"], "default_dirs": [], "locked": {}, "hidden": []}'),
      el("p", { class: "dim" }, "roots are the repositories whose claude/profiles/ hold <name>.args and <name>.json.")));
  }
  document.getElementById("n-profiles").textContent = d.folders.length ? String(d.folders.length) : "";
  if (P.folder && !d.folders.some((x) => x.path === P.folder)) P.folder = null;
  if (!P.editing && !P.folder) P.editing = d.profiles.length ? d.profiles[0].name : null;
  renderProfilesTree();
  const refreshBtn = el("button", { type: "button", class: "act ic-btn" }, sicon("refresh-cw"), "Refresh tools");
  refreshBtn.addEventListener("click", async () => { refreshBtn.disabled = true; await loadProfiles(true); });
  const kids = [el("div", { class: "p-bar" },
    el("span", { class: "dim" }, "Which tools new sessions get in each folder. Running sessions keep theirs until restarted."),
    d.auditFindings ? el("span", { class: "warn-chip" }, d.auditFindings + (d.auditFindings === 1 ? " cleanup finding" : " cleanup findings") + (d.auditHint ? ": run " + d.auditHint : "")) : null,
    el("span", { class: "grow" }), refreshBtn)];
  if (d.toolsError) kids.push(el("p", { class: "h-msg bad" }, "MCP servers unavailable: " + d.toolsError));
  kids.push(scopeCard());
  const p = profileNamed(P.editing);
  if (p) kids.push(editorCard(p));
  else if (P.editing) kids.push(el("section", { class: "card" }, el("p", { class: "h-msg bad" }, "No " + P.editing + ".args was found in any root, so new sessions here fail to start until it exists.")));
  const focused = document.activeElement && document.activeElement.getAttribute("aria-label");
  main.replaceChildren(...kids);
  if (focused) { const again = [...main.querySelectorAll("[aria-label]")].find((x) => x.getAttribute("aria-label") === focused); if (again) again.focus(); }
}

async function loadProfiles(refresh) {
  const main = document.getElementById("p-main");
  if (!P.data) main.replaceChildren(el("p", { class: "dim" }, "Reading the profiles. The MCP server list can take a few seconds."));
  try {
    P.data = await getJSON("/api/profiles" + (refresh ? "?refresh=1" : ""));
    const shown = document.getElementById("p-msg");
    if (refresh && shown.classList.contains("bad")) pmsg("");  // a fresh tool list answers the old error
    if (!H.home) H.home = P.data.home;
    renderProfiles();
  } catch (e) { pmsg("Cannot load the profiles: " + e.message, true); }
}

function initProfiles() {
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
    const [m, t] = await Promise.all([getJSON("/api/members"), getJSON("/api/todos")]);
    const now = Date.now();
    renderMembers(m, now); renderTodos(t, now); renderNotices([m, t]);
    loadInbox();
    stamp.className = "live"; stamp.title = "Refreshed every " + REFRESH / 1000 + " s";
    stamp.textContent = "Live, updated " + new Date(now).toLocaleTimeString();
  } catch (e) {
    stamp.className = "down"; stamp.textContent = "Cannot reach the server (" + e.message + "), retrying";
  } finally { busy = false; }
}

function showView(id) {
  if (!VIEWS.some((v) => v.id === id)) id = VIEWS[0].id;
  if (id === "history" && !H.loaded) loadHistory();
  if (id === "profiles" && !P.data) loadProfiles();
  document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== id));
  if (id !== "foryou") setBadge(Y.open || 0);
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
  document.querySelectorAll(".head-ic[data-icon]").forEach((s) => s.replaceWith(sicon(s.dataset.icon, "head-svg")));
  document.querySelector(".logo").append(sicon("users"));
  initTheme();
  initHistory();
  initProfiles();
  initTodoForm();
  const tabs = document.getElementById("tabs");
  VIEWS.forEach((v) => tabs.append(el("button", { type: "button", "data-view": v.id }, sicon(VIEW_ICONS[v.id]), v.label)));
  tabs.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.view; }));
  addEventListener("hashchange", () => showView(location.hash.slice(1)));
  showView(location.hash.slice(1));
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, REFRESH);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
}
start();
