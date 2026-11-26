"use strict";
// Tools: every skill, command, agent, MCP server, hook and output style the sessions of every machine can reach, from
// GET /api/tools (fleet_tools.py: each machine scanned live, joined on the server). The page reads only; it filters
// and sorts in the browser. Loaded after app.js, so el(), sicon(), ICONS and the theme are there; it runs in its own scope.
// Every value reaches the page through textContent, never as markup.

(() => {  // its own scope: app.js's top-level names (chip, T-like state) stay untouched
// Icons: Lucide 1.47.0 (ISC license), path data copied unchanged from lucide-react's icon files.
Object.assign(ICONS, {
  "zap": [["path", { d: "M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z" }]],
  "bot": [["path", { d: "M12 8V4H8" }], ["rect", { width: "16", height: "12", x: "4", y: "8", rx: "2" }], ["path", { d: "M2 14h2" }], ["path", { d: "M20 14h2" }], ["path", { d: "M15 13v2" }], ["path", { d: "M9 13v2" }]],
  "webhook": [["path", { d: "M18 16.98h-5.99c-1.1 0-1.95.94-2.48 1.9A4 4 0 0 1 2 17c.01-.7.2-1.4.57-2" }], ["path", { d: "m6 17 3.13-5.78c.53-.97.1-2.18-.5-3.1a4 4 0 1 1 6.89-4.06" }], ["path", { d: "m12 6 3.13 5.73C15.66 12.7 16.9 13 18 13a4 4 0 0 1 0 8" }]],
  "type": [["path", { d: "M12 4v16" }], ["path", { d: "M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2" }], ["path", { d: "M9 20h6" }]],
  "ban": [["circle", { cx: "12", cy: "12", r: "10" }], ["path", { d: "M4.929 4.929 19.07 19.071" }]],
  "git-compare": [["circle", { cx: "18", cy: "18", r: "3" }], ["circle", { cx: "6", cy: "6", r: "3" }], ["path", { d: "M13 6h3a2 2 0 0 1 2 2v7" }], ["path", { d: "M11 18H8a2 2 0 0 1-2-2V9" }]],
  "circle-off": [["path", { d: "m2 2 20 20" }], ["path", { d: "M8.35 2.69A10 10 0 0 1 21.3 15.65" }], ["path", { d: "M19.08 19.08A10 10 0 1 1 4.92 4.92" }]],
  "triangle-alert": [["path", { d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" }], ["path", { d: "M12 9v4" }], ["path", { d: "M12 17h.01" }]],
  "briefcase": [["path", { d: "M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" }], ["rect", { width: "20", height: "14", x: "2", y: "6", rx: "2" }]],
});

const TK = {  // kind -> icon, plural word
  "skill": ["zap", "skills"], "command": ["terminal", "commands"], "agent": ["bot", "agents"],
  "MCP server": ["server", "MCP servers"], "hook": ["webhook", "hooks"], "output style": ["type", "output styles"],
};
const FINDING = {  // finding kind -> icon, heading
  "duplicate": ["copy", "Same name from several providers"], "no profile": ["circle-off", "Installed but on no profile"],
  "drift": ["git-compare", "Hook copies that drifted from their source"], "denied": ["ban", "Servers denied in every profile"],
};
const T = { data: null, q: "", kind: null, prov: "", prof: "", acct: "", co: false, dup: false, ids: null, idsLabel: "",
  sort: "provider", card: null, loading: false, err: "", openFind: null };
const tmsg = (text, bad) => flash("tt-msg", text, bad);
const kindIcon = (k, cls) => sicon((TK[k] || ["package"])[0], cls);
const shownMachines = () => (T.data ? T.data.shown_machines : []);
const profNames = () => (T.data ? T.data.profiles.map((p) => p.name) : []);

function dupCount(d) { return T.dups.get(d.kind + "|" + d.name.toLowerCase()) - 1; }
function prepare(data) {
  T.dups = new Map();
  for (const d of data.items) {
    const k = d.kind + "|" + d.name.toLowerCase();
    T.dups.set(k, (T.dups.get(k) || 0) + 1);
  }
  for (const d of data.items) d.hay = [d.name, d.purpose, d.provider, d.path, d.invocation, d.repo, d.kind, d.notes, d.scope].join(" ").toLowerCase();
}

function match(d) {
  if (T.ids && !T.ids.has(d.id)) return false;
  if (T.kind && d.kind !== T.kind) return false;
  if (T.prov && d.provider !== T.prov) return false;
  if (T.prof === "__none") { if (d.profiles.length) return false; } else if (T.prof && !d.profiles.includes(T.prof)) return false;
  if (T.acct && !d.accounts.includes(T.acct)) return false;
  if (T.co && !d.company) return false;
  if (T.dup && dupCount(d) < 1) return false;
  if (T.q) for (const w of T.q.split(/\s+/)) if (w && !d.hay.includes(w)) return false;
  return true;
}

// A row of slots: one dot per profile (or machine), filled when on. A missing value keeps its slot.
function slots(names, on, tip) {
  return el("span", { class: "tt-slots" }, ...names.map((n) => {
    const v = on(n);
    const cls = v === true ? "on" : v === null ? "unk" : "";
    return el("i", { class: "tt-s " + cls, title: tip(n, v) });
  }));
}
const profSlots = (d) => slots(profNames(), (p) => d.profiles.includes(p), (p, v) => p + ": " + (v ? "turned on" : "not on"));
const machSlots = (d) => slots(shownMachines(), (m) => (d.machines[m] === undefined ? false : d.machines[m]),
  (m, v) => m + ": " + (v === true ? "has it" : v === null ? "not read" : "does not have it"));

function headRow() {
  const sortBtn = (key, text) => el("button", { type: "button", "data-sort": key, "aria-pressed": String(T.sort === key) }, text);
  return el("div", { class: "tt-row tt-head", role: "row" },
    el("span", { class: "c-kind" }, "Kind"), el("span", { class: "c-name" }, sortBtn("name", "Name")),
    el("span", { class: "c-prov" }, sortBtn("provider", "Provider")),
    el("span", { class: "c-prof", title: profNames().join(", ") }, "Profiles"),
    el("span", { class: "c-mach", title: shownMachines().join(", ") }, "Machines"),
    el("span", { class: "c-co" }, T.data.company_label), el("span", { class: "c-purp" }, "What it is for"));
}

function itemRow(d) {
  const n = dupCount(d);
  const b = el("button", { type: "button", class: "tt-row", "data-id": String(d.id), title: d.provider },
    el("span", { class: "c-kind" }, kindIcon(d.kind), el("span", { class: "w" }, d.kind)),
    el("span", { class: "c-name" }, el("span", { class: "nm" }, d.name),
      n > 0 ? el("span", { class: "tt-dup", title: "Same name in " + n + " other place" + (n > 1 ? "s" : "") }, "+" + n) : null),
    el("span", { class: "c-prov" }, d.provider),
    el("span", { class: "c-prof" }, profSlots(d)),
    el("span", { class: "c-mach" }, machSlots(d)),
    el("span", { class: "c-co" }, d.company ? el("span", { class: "tt-tag co" }, T.data.company_label) : ""),
    el("span", { class: "c-purp" }, d.purpose || ""));
  b.addEventListener("click", () => openTool(d.id, b));
  return b;
}

function sorted(list) {
  const key = T.sort === "name" ? (d) => d.name.toLowerCase() + "|" + d.provider.toLowerCase() : (d) => d.provider.toLowerCase() + "|" + d.name.toLowerCase();
  return list.slice().sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

function renderRows() {
  const list = sorted(T.data.items.filter(match));
  const all = T.data.items.length;
  document.getElementById("tt-count").textContent = list.length + " of " + all + " shown" + (T.ids ? " (" + T.idsLabel + ")" : "");
  const rows = document.getElementById("tt-rows");
  rows.style.setProperty("--np", profNames().length);
  rows.style.setProperty("--nm", shownMachines().length);
  rows.replaceChildren(headRow(), ...(list.length ? list.map(itemRow) : [el("div", { class: "tt-empty" }, "Nothing matches. Clear a filter or change the search.")]));
  rows.querySelectorAll(".tt-head [data-sort]").forEach((b) => b.addEventListener("click", () => { T.sort = b.dataset.sort; renderRows(); }));
  document.querySelectorAll("#tt-kinds .tt-chip").forEach((b) => b.setAttribute("aria-pressed", String(T.kind === b.dataset.k)));
  document.getElementById("tt-co").setAttribute("aria-pressed", String(T.co));
  document.getElementById("tt-dup").setAttribute("aria-pressed", String(T.dup));
}

function select(id, label, options, value, onPick) {
  const s = el("select", { id, "aria-label": label }, ...options.map(([v, t]) => el("option", { value: v }, t)));
  s.value = value;
  s.addEventListener("change", () => onPick(s.value));
  return s;
}

function renderBar() {
  const d = T.data;
  const count = (f) => d.items.filter(f).length;
  const provs = [...new Set(d.items.map((x) => x.provider))].sort((a, b) => a.localeCompare(b));
  const accts = [...new Set(d.items.flatMap((x) => x.accounts))].sort();
  const q = el("input", { id: "tt-q", type: "search", placeholder: "Search name, purpose, provider, path", "aria-label": "Search tools", autocomplete: "off" });
  q.value = T.q;
  q.addEventListener("input", () => { T.q = q.value.trim().toLowerCase(); renderRows(); });
  const bar = document.getElementById("tt-bar");
  bar.replaceChildren(
    el("div", { class: "tt-line" }, q,
      select("tt-prov", "Provider", [["", "Any provider"]].concat(provs.map((p) => [p, p + " (" + count((x) => x.provider === p) + ")"])), T.prov, (v) => { T.prov = v; renderRows(); }),
      select("tt-prof", "Profile", [["", "Any profile"]].concat(profNames().map((p) => [p, p])).concat([["__none", "On no profile"]]), T.prof, (v) => { T.prof = v; renderRows(); }),
      select("tt-acct", "Account", [["", "Any account"]].concat(accts.map((a) => [a, a])), T.acct, (v) => { T.acct = v; renderRows(); })),
    el("div", { class: "tt-line", id: "tt-kinds", role: "group", "aria-label": "Kinds" }, ...d.kinds.map((k) => {
      const b = el("button", { type: "button", class: "tt-chip", "data-k": k, "aria-pressed": "false" }, kindIcon(k), el("span", { class: "w" }, k), el("span", { class: "n" }, String(d.counts[k] || 0)));
      b.setAttribute("aria-label", (TK[k] || [k, k])[1] + ", " + (d.counts[k] || 0));
      b.addEventListener("click", () => { T.kind = T.kind === k ? null : k; renderRows(); });
      return b;
    })),
    el("div", { class: "tt-line" },
      chip("tt-co", "briefcase", d.company_label + " only", () => { T.co = !T.co; renderRows(); }, "co"),
      chip("tt-dup", "copy", "Same name elsewhere", () => { T.dup = !T.dup; renderRows(); }),
      chip("tt-clear", "rotate-ccw", "Clear", clearFilters)));
}
function chip(id, ic, text, fn, cls) {
  const b = el("button", { type: "button", id, class: "tt-chip" + (cls ? " " + cls : ""), "aria-pressed": "false", title: text }, sicon(ic), el("span", { class: "w" }, text));
  if (id === "tt-clear") b.removeAttribute("aria-pressed");
  b.setAttribute("aria-label", text);
  b.addEventListener("click", fn);
  return b;
}
function clearFilters() {
  Object.assign(T, { q: "", kind: null, prov: "", prof: "", acct: "", co: false, dup: false, ids: null, idsLabel: "" });
  renderBar(); renderRows();
}

function renderStats() {
  const d = T.data;
  document.getElementById("tt-stats").replaceChildren(...d.kinds.map((k) => {
    const b = el("button", { type: "button", class: "tt-stat", title: "Show only " + TK[k][1] }, kindIcon(k), el("b", {}, String(d.counts[k] || 0)), el("span", {}, TK[k][1]));
    b.addEventListener("click", () => { T.kind = k; renderRows(); document.getElementById("tt-count").scrollIntoView({ block: "start", behavior: "smooth" }); });
    return b;
  }));
}

function machineWord(m, e) {
  if (e.status === "satellite") return "satellite, nothing of its own";
  if (e.status === "read") return "read " + (e.as_of ? ago(e.as_of, Date.now()) : "now");
  if (e.status === "stale") return "as of " + (e.as_of ? ago(e.as_of, Date.now()) : "never") + (e.reason ? ", " + e.reason : "");
  return "not read" + (e.reason ? ": " + e.reason : "");
}
function renderMachines() {
  const d = T.data;
  document.getElementById("tt-machines").replaceChildren(...Object.entries(d.machines).map(([m, e]) => {
    const cls = e.status === "read" ? "ok" : e.status === "satellite" ? "dimc" : e.status === "stale" ? "warn" : "bad";
    const counts = d.per_machine[m];
    return el("div", { class: "tt-mach", title: machineWord(m, e) }, el("span", { class: "tt-dot " + cls }), el("b", {}, m),
      el("span", { class: "dim" }, machineWord(m, e)),
      counts ? el("span", { class: "dim tt-mach-n" }, d.kinds.map((k) => counts[k] + " " + (counts[k] === 1 ? k : TK[k][1])).join(", ")) : null);
  }));
}

// The overview: one row per provider, one column per profile, a filled dot where the profile turns it on.
const PROV_ORDER = ["plugin dir", "plugin", "profile", "user", "connector", "project", "builtin"];
const PROV_WORD = { "plugin dir": "Plugin folders", "plugin": "Marketplace plugins", "profile": "Profile servers", "user": "Your own", "connector": "claude.ai", "project": "Projects", "builtin": "Built in" };
function renderOverview() {
  const d = T.data;
  const profs = profNames();
  const box = document.getElementById("tt-map");
  box.style.setProperty("--np", profs.length);
  const provs = d.providers.filter((p) => Object.keys(p.counts || {}).length).sort((a, b) =>
    (PROV_ORDER.indexOf(a.type) - PROV_ORDER.indexOf(b.type)) || a.name.localeCompare(b.name));
  const rows = [el("div", { class: "tt-mrow tt-mhead" }, el("span", {}, "Provider"), ...profs.map((p) => el("span", { class: "tt-mp", title: p }, p)), el("span", { class: "tt-mc" }, "Carries"))];
  let group = null;
  for (const p of provs) {
    if (p.type !== group) { group = p.type; rows.push(el("div", { class: "tt-mgroup" }, PROV_WORD[group] || group)); }
    const carries = d.kinds.filter((k) => p.counts[k]).map((k) => p.counts[k] + " " + (p.counts[k] === 1 ? k : TK[k][1])).join(", ");
    const b = el("button", { type: "button", class: "tt-mrow" + (p.company ? " co" : "") + (p.profiles.length ? "" : " off"), title: p.name + ": " + carries },
      el("span", { class: "tt-mn" }, p.name), ...profs.map((x) => el("span", { class: "tt-mp" }, el("i", { class: "tt-s " + (p.profiles.includes(x) ? "on" : ""), title: x + ": " + (p.profiles.includes(x) ? "on" : "off") }))),
      el("span", { class: "tt-mc" }, carries));
    b.addEventListener("click", () => { clearFilters(); T.prov = p.name; renderBar(); renderRows(); document.getElementById("tt-count").scrollIntoView({ block: "start", behavior: "smooth" }); });
    rows.push(b);
  }
  box.replaceChildren(...rows);
  const folders = document.getElementById("tt-folders");
  const by = {};
  for (const [m, list] of Object.entries(d.folders || {})) for (const f of list) if (f.own) (by[f.profile] = by[f.profile] || new Set()).add(f.path.replace(/^~\/projects\//, ""));
  folders.replaceChildren(...Object.entries(by).map(([p, s]) => el("div", { class: "tt-frow" }, el("b", {}, p), el("span", {}, [...s].sort().join(", ")))));
}

function renderFindings() {
  const d = T.data;
  const box = document.getElementById("tt-findings");
  document.getElementById("n-findings").replaceChildren(el("span", { class: "n" }, String(d.findings.length)));
  const groups = {};
  for (const f of d.findings) (groups[f.kind] = groups[f.kind] || []).push(f);
  box.replaceChildren(...Object.keys(FINDING).filter((k) => groups[k]).map((k) => {
    const open = T.openFind === k;
    const head = el("button", { type: "button", class: "tt-fhead", "aria-expanded": String(open) }, sicon(FINDING[k][0]), el("span", { class: "w" }, FINDING[k][1]), el("span", { class: "n" }, String(groups[k].length)), sicon(open ? "chevron-down" : "chevron-right"));
    head.addEventListener("click", () => { T.openFind = open ? null : k; renderFindings(); });
    const list = open ? el("div", { class: "tt-flist" }, ...groups[k].map((f) => {
      const b = el("button", { type: "button", class: "tt-frow2", title: f.detail }, el("span", { class: "tt-ft" }, f.title), el("span", { class: "tt-fd dim" }, f.detail));
      b.addEventListener("click", () => { clearFilters(); T.ids = new Set(f.ids); T.idsLabel = f.title; renderRows(); document.getElementById("tt-count").scrollIntoView({ block: "start", behavior: "smooth" }); });
      return b;
    })) : null;
    return el("div", { class: "tt-fgroup" }, head, list);
  }));
  if (!d.findings.length) box.replaceChildren(el("p", { class: "dim" }, "Nothing flagged."));
}

// The full card: everything the row has no room for. A <dialog>, closed by Close, Escape or a click outside.
function fact(dt, dd) { return dd === null || dd === undefined || dd === "" ? [] : [el("dt", {}, dt), el("dd", {}, dd)]; }
function openTool(id, from) {
  const d = T.data.items.find((x) => x.id === id);
  if (!d) return;
  T.card = { id, from };
  const dlg = document.getElementById("tt-card");
  const n = dupCount(d);
  const close = el("button", { type: "button", class: "act ic-btn" }, sicon("x"), "Close");
  close.addEventListener("click", () => dlg.close());
  const perMachine = shownMachines().map((m) => {
    const on = (d.on || {})[m];
    const v = d.machines[m];
    const word = v === true ? (on && on.profiles && on.profiles.length ? "on " + on.profiles.join(", ") : "installed, on no profile") : v === null ? "not read" : "not there";
    return el("div", {}, el("b", {}, m + ": "), word, on && on.drift ? " (hook " + on.drift + ")" : "");
  });
  const others = n > 0 ? T.data.items.filter((x) => x.id !== d.id && x.kind === d.kind && x.name.toLowerCase() === d.name.toLowerCase()).map((x) => x.provider).join(", ") : "";
  dlg.replaceChildren(
    el("div", { class: "tt-card-head" }, el("span", { class: "tt-card-kind" }, kindIcon(d.kind), d.kind), el("span", { class: "grow" }), close),
    el("h2", {}, d.name),
    el("div", { class: "tt-card-tags" },
      d.company ? el("span", { class: "tt-tag co" }, T.data.company_label) : null,
      d.manual ? el("span", { class: "tt-tag am" }, "Typed by hand only") : null,
      n > 0 ? el("span", { class: "tt-tag am" }, "Same name in " + n + " other place" + (n > 1 ? "s" : "")) : null,
      d.profiles.length ? null : el("span", { class: "tt-tag am" }, "On no profile")),
    el("p", {}, d.purpose || "No description in the source."),
    el("dl", { class: "tt-facts" },
      ...fact("Invoke", el("code", {}, d.invocation || "")), ...fact("Provider", d.provider), ...fact("Repo", d.repo),
      ...fact("Path", d.path ? el("code", {}, d.path) : ""), ...fact("Only in", d.scope ? el("code", {}, d.scope) : ""),
      ...fact("Profiles", d.profiles.length ? d.profiles.join(", ") : "none"), ...fact("Accounts", d.accounts.join(", ")),
      ...fact("Machines", el("div", {}, ...perMachine)), ...fact("Events", (d.events || []).join(", ")),
      ...fact("Transport", d.transport), ...fact("Denied in", (d.denied || []).join(", ")),
      ...fact("Source", d.source ? el("code", {}, d.source) : ""), ...fact("Also from", others), ...fact("Notes", d.notes)));
  if (!dlg.open) dlg.showModal();
  close.focus();
}

function renderTools() {
  if (!T.data) return;
  renderStats(); renderMachines(); renderFindings(); renderOverview(); renderBar(); renderRows();
  document.getElementById("n-tools").replaceChildren(el("span", { class: "n" }, String(T.data.items.length)));
  if (T.data.notes && T.data.notes.length) document.getElementById("tt-notes").replaceChildren(...T.data.notes.map((n) => el("li", {}, n)));
}

async function loadTools(fresh) {
  if (T.loading || (T.data && !fresh)) return;
  T.loading = true;
  const btn = document.getElementById("tt-refresh");
  if (btn) btn.disabled = true;
  if (!T.data) document.getElementById("tt-count").textContent = "Reading every machine…";
  try {
    const data = await getJSON("/api/tools" + (fresh ? "?fresh=1" : ""));
    prepare(data);
    T.data = data;
    renderTools();
    if (fresh) tmsg("Read again from every machine.");
  } catch (e) {
    tmsg("Cannot read the tools: " + e.message, true);
    if (!T.data) document.getElementById("tt-count").textContent = "";
  } finally {
    T.loading = false;
    if (btn) btn.disabled = false;
  }
}

function initTools() {
  const dlg = document.getElementById("tt-card");
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { const from = T.card && T.card.from; T.card = null; if (from && from.isConnected) from.focus(); });
  const r = document.getElementById("tt-refresh");
  r.replaceChildren(sicon("refresh-cw"), el("span", { class: "w" }, "Read again"));
  r.addEventListener("click", () => loadTools(true));
  if (currentView() === "tools") loadTools();
}
window.loadTools = loadTools;  // app.js opens the tab through it
initTools();
})();
