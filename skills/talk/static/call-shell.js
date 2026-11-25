// ---- the conversation: the Now card over the list of earlier answers --------------------------
// The panel shows one answer in full, the one in the player (else the newest): its question, its text with the word
// being said lit, its boards as named chips, the player's controls, and whether the stage follows the voice. Every
// other answer is a row of the list under it: number, question and gist, boards, time, Play. A row opens in place; a
// search finds an answer by its question, its words or its boards. What the page draws comes from `turnsOf`, which
// pairs each answer with the question that asked it and the boards it showed; progress notes ("thinking it
// through") are not part of the conversation: the foot says what Claude is doing now.
const staged = (e) => !!CFG.stageUrl && (e.cues || []).some((c) => c.kind === "front");

// ---- what the conversation is made of ------------------------------------------
// Each answer with the question it answers (the last thing the user said before it, unless taken back), the boards
// it showed (the board entries before it) and the notes it saved.
function turnsOf(entries) {
  const turns = [];
  let q = null, boards = [], notes = [];
  for (const e of entries) {
    if (e.who === "you") { if (!e.withdrawn) q = e; }
    else if (e.who === "board") boards.push(e);
    else if (e.who === "note") notes.push(e);
    else if (e.who === "claude") { turns.push({a: e, q, boards, notes}); q = null; boards = []; notes = []; }
  }
  return turns;
}
// The server's time of day an entry was made at: "09:52".
function clockOf(at) {
  if (!at) return "";
  const d = new Date(at * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
// What an answer was about, in one line: its first sentence, cut at a word.
function gistOf(e, max = 90) {
  let s = e.text.replace(/\s+/g, " ").trim();
  const run = sentenceRuns(e)[0];
  if (run) s = e.text.slice(e.words[run[0]][0], e.words[run[1]][1]).replace(/\s+/g, " ").trim();
  else { const m = /^.*?[.!?…\u037e](?=\s|$)/.exec(s); if (m) s = m[0]; }
  if (s.length <= max) return s;
  s = s.slice(0, max);
  const sp = s.lastIndexOf(" ");
  return (sp > max / 2 ? s.slice(0, sp) : s).replace(/[,;:\s]+$/, "") + "…";
}
// The name a board chip shows: the Key points board is named, whatever number the server's label carries.
const boardName = (b) => b.kind === "points" ? "Key points" : b.text;
function boardTitle(view) {
  const b = view ? view_entries().find((x) => x.who === "board" && x.view === view) : null;
  return b ? boardName(b) : "";
}
const view_entries = () => view.entries;
// The answer a board was shown with, as the page numbers it.
const answerNo = (b) => (Number.isFinite(b.answer) ? b.answer : null);

const KIND_ICONS = {
  code: '<path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4"/>',
  diagram: '<rect x="1.5" y="1.5" width="6" height="4.5" rx="1.2"/><rect x="8.5" y="10" width="6" height="4.5" rx="1.2"/><path d="M4.5 6v3a1.5 1.5 0 0 0 1.5 1.5h2.5"/>',
  table: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.6"/><path d="M1.5 6.5h13M6 6.5v7"/>',
  change: '<path d="M4.5 2v6M1.5 5h6M8.5 12.5h6"/>',
  points: '<path d="M6 4h8M6 8h8M6 12h8"/><circle cx="2.6" cy="4" r=".9"/><circle cx="2.6" cy="8" r=".9"/><circle cx="2.6" cy="12" r=".9"/>',
  page: '<path d="M3.5 1.5h6l3 3v10h-9z"/><path d="M9.5 1.5v3h3M5.5 8.5h5M5.5 11h5"/>',
  scene: '<rect x="1.5" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="9" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="1.5" y="10" width="13" height="3.5" rx="1.2"/>',
};
const kindIcon = (kind, size = 13) => `<svg viewBox="0 0 16 16" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${KIND_ICONS[kind] || KIND_ICONS.page}</svg>`;
const ICON = (d, size = 14) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;

// A board's chip: icon and its name; a press brings the board to the front of the stage (and pins it).
function buildChip(b) {
  const el = document.createElement("button"); el.type = "button"; el.className = "chip board"; el.dataset.view = b.view || "";
  el.innerHTML = kindIcon(b.kind);
  const t = document.createElement("span"); t.className = "cl"; t.textContent = boardName(b); el.append(t);
  let said = boardName(b);
  if (b.kind === "points" && b.added) {
    const s = document.createElement("small"); s.textContent = b.added + " new"; el.append(s); said += ", " + s.textContent;
  }
  el.setAttribute("aria-label", "Show on the stage: " + said);
  el.setAttribute("aria-pressed", "false");
  if (!CFG.stageUrl || !b.view) { el.disabled = true; el.title = "The stage is not available"; }
  else { el.title = "Show this board on the stage"; el.onclick = () => chipTap(b.view); }
  return el;
}
// The chips of one answer, with the notes it saved, as one labelled group.
function buildChips(t) {
  const frag = document.createDocumentFragment();
  if (t.boards.length) {
    const l = document.createElement("span"); l.className = "clbl"; l.textContent = "On the stage"; frag.append(l);
    for (const b of t.boards) frag.append(buildChip(b));
  }
  for (const n of t.notes) { const c = document.createElement("div"); c.className = "chip note"; c.textContent = "Noted: " + n.text; frag.append(c); }
  return frag;
}
const chipsSig = (t) => t.boards.map((b) => `${b.view}|${b.text}|${b.added || 0}`).join(";") + "#" + t.notes.map((n) => n.text).join(";");

// ---- the answer being read: the one in the player, else the last one -------------
function lastAnswer() {
  for (let i = view.entries.length - 1; i >= 0; i--) if (view.entries[i].who === "claude") return view.entries[i];
  return null;
}
function shownAnswer() { return current ? (view.entries.find(e => e.id === current.id) || current) : lastAnswer(); }
function wordSpans(e) {
  if (!e.words || !e.words.length) return [document.createTextNode(e.text)];
  const out = [];
  let pos = 0;
  e.words.forEach((w, i) => {
    if (w[0] > pos) out.push(document.createTextNode(e.text.slice(pos, w[0])));
    const span = document.createElement("span"); span.className = "w"; span.dataset.i = i;
    span.textContent = e.text.slice(w[0], w[1]); span.onclick = () => playFrom(e, w[2]);
    out.push(span); pos = w[1];
  });
  out.push(document.createTextNode(e.text.slice(pos)));
  return out;
}

// ---- the Now card ------------------------------------------------------------------
// What the eyebrow says: an icon and a word, so playing, paused, ready, working and slow are told apart at a glance.
const STATE_ICONS = {
  playing: '<span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>',
  paused: ICON('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>', 12),
  ready: ICON('<path d="M7 5v14l12-7z"/>', 12),
  played: ICON('<path d="M5 12l5 5L20 7"/>', 12),
  working: '<span class="spin" aria-hidden="true"></span>',
  slow: ICON('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 13),
  voice: '<span class="spin" aria-hidden="true"></span>',
  silent: ICON('<path d="M11 5 6 9H3v6h3l5 4zM22 9l-6 6M16 9l6 6"/>', 13),
  elsewhere: ICON('<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>', 13),
};
function nowState(e, wait) {
  if (wait) return view.stalled ? {key: "slow", word: "Slow"} : {key: "working", word: "Working"};
  if (!e) return null;
  if (e.speech === "pending" || e.speech === "making") return {key: "voice", word: "Preparing the voice"};
  if (e.speech === "failed") return {key: "silent", word: "Not read aloud"};
  const mine = !!current && current.id === e.id;
  if (mine && !audio.paused) return {key: "playing", word: "Playing"};
  if (mine && audio.paused && elsewhere) return {key: "elsewhere", word: "Playing on another screen"};
  if (mine && (audio.ended || (audio.duration && audio.currentTime >= audio.duration))) return {key: "played", word: "Played"};
  if (mine && audio.currentTime > 0) return {key: "paused", word: "Paused"};
  return {key: "ready", word: e.id > (view.heard_upto ?? -1) ? "New" : "Ready"};
}
let nowSig = "", nowChipsSig = "", nowHeadSig = "", nowShown = null;   // the answer whose text the card holds
let readSpans = [];
function buildNowText(e) {
  const box = $("nowtext");
  box.replaceChildren(...wordSpans(e));
  readSpans = [...box.querySelectorAll(".w")];
  lastWord = null; lastK = -2;
  nowShown = e.id;
}
// The card of the current turn, from paintAll(). While a turn is in flight the card shows the wait card (W) instead of the answer.
function paintNowCard() {
  const e = shownAnswer(), wait = waitActive(), card = $("nowcard");
  card.hidden = !e && !wait;
  if (card.hidden) { nowShown = null; return; }
  const turns = turnsOf(view.entries), total = turns.length, t = e ? turns.find((x) => x.a.id === e.id) : null;
  // the head: state, which answer, when it was made
  const st = nowState(e, wait), num = wait ? "Answer " + (total + 1) : "Answer " + e.n + (total > 1 ? " of " + total : "");
  const tag = e && e.superseded ? "Replaced by your correction" : "";
  const headSig = [st && st.key, st && st.word, num, tag, e && e.at].join("|");
  if (headSig !== nowHeadSig) {
    nowHeadSig = headSig;
    $("nowstate").innerHTML = st ? STATE_ICONS[st.key] + "<b></b>" : ""; if (st) $("nowstate").lastChild.textContent = st.word;
    $("nowstate").dataset.state = st ? st.key : "";
    $("nownum").textContent = num; $("nownum").dataset.tag = tag;
    $("nowclock").textContent = !wait && e ? clockOf(e.at) : ""; $("nowclock").title = $("nowclock").textContent ? "Answered at " + $("nowclock").textContent : "";
    $("nowhead").classList.toggle("replaced", !!tag);
    let tagEl = $("nowhead").querySelector(".now-tag");
    if (tag) { if (!tagEl) { tagEl = document.createElement("span"); tagEl.className = "now-tag"; $("nowclock").before(tagEl); } tagEl.textContent = tag; }
    else if (tagEl) tagEl.remove();
  }
  card.dataset.state = st ? st.key : "";
  if (!e) return;
  // the question asked, the full text, the boards
  const asked = t && t.q ? t.q : null;
  $("nowq").hidden = !asked;
  const qsig = asked ? asked.id + "|" + asked.text : "";
  if ($("nowq").dataset.sig !== qsig) {
    $("nowq").dataset.sig = qsig;
    const small = document.createElement("small"); small.textContent = "You asked, " + clockOf(asked && asked.at);
    const b = document.createElement("strong"); b.textContent = asked ? asked.text : "";
    $("nowq").replaceChildren(small, b);
  }
  const sig = `${e.id}|${e.text.length}|${e.words?.length || 0}`;
  if (sig !== nowSig) {
    nowSig = sig;
    const wasShown = nowShown;
    buildNowText(e);
    if (wasShown !== e.id) { card.classList.remove("reading"); $("nowtext").scrollTop = 0; lastTurn = null; }
  }
  const csig = e.id + "#" + (t ? chipsSig(t) : "");
  if (csig !== nowChipsSig) {
    nowChipsSig = csig;
    $("nowchips").replaceChildren(t ? buildChips(t) : document.createDocumentFragment());
    paintFront(); paintMissing();
  }
  $("nowchips").hidden = !$("nowchips").childNodes.length;
  let bad = card.querySelector(".now-bad");
  if (e.speech === "failed") {
    if (!bad) { bad = document.createElement("div"); bad.className = "now-bad"; $("nowbody").append(bad); }
    bad.textContent = "Not read aloud: " + (e.speech_error || "speech failed");
  } else if (bad) bad.remove();
  paintFollow();
}

// ---- the Following strip ---------------------------------------------------------------
// Whether the stage follows the voice, always on the card: Following (the stage goes where the voice goes) or Pinned (a
// board picked by hand stays in front), with the board named and one button to switch. A pinned stage also says which
// answer the voice is on and which Play would start, so the stage, the card and the keys name one thing.
let followSig = "";
function paintFollow() {
  const box = $("nowfollow");
  const has = !!CFG.stageUrl && (!!frontBoard || (!!stageViews && stageViews.size > 0));
  box.hidden = !has;
  if (!has) { followSig = ""; return; }
  const front = boardTitle(frontBoard), fa = boardAnswer.get(frontBoard);
  const shown = shownAnswer(), b = shown ? boardStart() : null;
  const voiceOn = current && sent && sent.id === current.id && sent.front && sent.front !== frontBoard ? boardTitle(sent.front) : "";
  const plays = b && shown && b.e.id !== shown.id ? "Play starts answer " + b.e.n : "";
  let text;
  if (follow) text = front ? "Stage shows " + front : "Stage follows the voice";
  else text = (front ? "Stage is on " + front + (fa ? ", answer " + fa : "") : "Stage is held on a board") + (voiceOn ? ". The voice is on " + voiceOn : "") + (plays ? ". " + plays : "") + ".";
  if (follow && plays) text += ". " + plays;
  const sig = [follow, text].join("|");
  if (sig === followSig) return;
  followSig = sig;
  const state = document.createElement("span"); state.className = "fl-state";
  state.innerHTML = follow ? ICON('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>') : ICON('<path d="M12 17v5M9 3h6l-1 7 3 3H7l3-3z"/>');
  const word = document.createElement("b"); word.textContent = follow ? "Following" : "Pinned"; state.append(word);
  const msg = document.createElement("span"); msg.className = "fl-text"; msg.textContent = text; msg.title = text;
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "fl-btn";
  btn.textContent = follow ? "Pin board" : "Follow";
  btn.title = follow ? "Keep the stage on this board" : "Put the stage back on the voice";
  btn.onclick = () => { if (follow) pinBoard(); else { followAgain(); resync(); } };
  box.dataset.mode = follow ? "following" : "pinned";
  box.replaceChildren(state, msg, btn);
}

// ---- the list of earlier answers ---------------------------------------------------
const opened = new Set();     // the answers whose row the reader opened
let tlQuery = "", searchOpen = false;
const rowNodes = new Map();   // answer id -> {el, sig}
// Letters compared without accents or case, so a search finds "Ελλάδα" typed as "ελλαδα".
function folded(s) {
  let out = "", map = [];
  for (let i = 0; i < s.length; i++) {
    const f = s[i].normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    for (const c of f) { out += c; map.push(i); }
  }
  return {out, map};
}
const FOLD_CACHE = new Map();
function foldCached(s) { let f = FOLD_CACHE.get(s); if (!f) { f = folded(s); if (FOLD_CACHE.size > 800) FOLD_CACHE.clear(); FOLD_CACHE.set(s, f); } return f; }
function matchAt(text, q) { const f = foldCached(text), i = f.out.indexOf(q); return i < 0 ? null : {from: f.map[i], to: f.map[Math.min(f.map.length - 1, i + q.length - 1)] + 1}; }
// The turn's searchable words: its question, its text and its boards' names.
function turnMatches(t, q) {
  return !!(t.q && matchAt(t.q.text, q)) || !!matchAt(t.a.text, q) || t.boards.some((b) => matchAt(boardName(b), q));
}
// Text with the search's match marked (nodes, never markup).
function marked(text, q) {
  const m = q ? matchAt(text, q) : null;
  if (!m) return [document.createTextNode(text)];
  const mk = document.createElement("mark"); mk.textContent = text.slice(m.from, m.to);
  return [document.createTextNode(text.slice(0, m.from)), mk, document.createTextNode(text.slice(m.to))];
}
// The gist line; when the search matches only the answer's words, the words around the match.
function gistLine(t, q) {
  const e = t.a;
  if (q && !(t.q && matchAt(t.q.text, q)) && matchAt(e.text, q)) {
    const m = matchAt(e.text, q), a = Math.max(0, m.from - 28), b = Math.min(e.text.length, m.to + 56);
    const snip = (a > 0 ? "…" : "") + e.text.slice(a, b).replace(/\s+/g, " ") + (b < e.text.length ? "…" : "");
    return marked(snip, q);
  }
  return marked(gistOf(e), q);
}
function playAnswer(e, own) {
  e = view.entries.find((x) => x.id === e.id) || e;
  if (current && current.id === e.id && !audio.paused) { audio.pause(); return; }
  readerPlays(e);
  if (!own) followAgain();   // another answer was picked: its boards are what the reader wants to see
  takeVoice(); load(e, true);
  convoFollow = true; scrollConvo(0);
}
function buildRow(t, q, isNow) {
  const e = t.a, row = document.createElement("div");
  const open = opened.has(e.id) && !isNow, unheard = e.id > (view.heard_upto ?? -1);
  row.className = "tlrow" + (open ? " open" : "") + (unheard ? " unheard" : "") + (isNow ? " is-now" : "") + (e.superseded ? " replaced" : "");
  row.dataset.id = e.id; row.setAttribute("role", "listitem");
  const main = document.createElement("button"); main.type = "button"; main.className = "tl-main";
  main.setAttribute("aria-expanded", String(open));
  const n = document.createElement("span"); n.className = "tl-n"; n.textContent = e.n;
  const qq = document.createElement("span"); qq.className = "tl-q";
  const title = document.createElement("span"); title.className = "tl-title";
  if (t.q) title.append(...marked(t.q.text, q)); else title.append(...marked(gistOf(e), q));
  qq.append(title);
  if (t.q) { const g = document.createElement("span"); g.className = "tl-gist"; g.append(...gistLine(t, q)); qq.append(g); }
  main.append(n, qq);
  main.onclick = () => { if (opened.has(e.id)) opened.delete(e.id); else opened.add(e.id); paintEarlier(); };
  const bd = document.createElement("button"); bd.type = "button"; bd.className = "tl-b";
  const boards = t.boards;
  if (boards.length) {
    const first = boards.find((b) => b.kind !== "points") || boards[0];
    bd.innerHTML = kindIcon(first.kind, 16);
    if (boards.length > 1) { const c = document.createElement("span"); c.textContent = boards.length; bd.append(c); }
    bd.setAttribute("aria-label", boards.length === 1 ? "Show " + boardName(first) + " on the stage" : boards.length + " boards, open the answer");
    bd.title = boards.map(boardName).join(", ");
    bd.onclick = () => { if (boards.length === 1 && CFG.stageUrl && first.view) chipTap(first.view); else main.click(); };
    if (!CFG.stageUrl && boards.length === 1) bd.disabled = true;
  } else { bd.disabled = true; bd.tabIndex = -1; bd.setAttribute("aria-hidden", "true"); }
  const tm = document.createElement("span"); tm.className = "tl-t"; tm.textContent = clockOf(e.at);
  const play = document.createElement("button"); play.type = "button"; play.className = "play";
  const playing = !!current && current.id === e.id && !audio.paused;
  play.disabled = e.speech !== "ready";
  play.innerHTML = ICON(playing ? '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>' : '<path d="M7 5v14l12-7z"/>', 14) + "<span></span>";
  play.lastChild.textContent = playing ? "Pause" : "Play";
  play.setAttribute("aria-label", (playing ? "Pause answer " : "Play answer ") + e.n);
  play.onclick = () => playAnswer(e, !!isNow);
  row.append(main, bd, tm, play);
  if (e.superseded) { const tg = document.createElement("span"); tg.className = "tl-tag"; tg.textContent = "Replaced"; qq.append(tg); }
  if (open) {
    const body = document.createElement("div"); body.className = "tl-body";
    const text = document.createElement("div"); text.className = "tl-text"; text.replaceChildren(...wordSpans(e));
    body.append(text);
    const chips = document.createElement("div"); chips.className = "chips"; chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "On the stage");
    chips.append(buildChips(t)); chips.hidden = !chips.childNodes.length;
    if (e.speech === "failed") { const bad = document.createElement("div"); bad.className = "now-bad"; bad.textContent = "Not read aloud: " + (e.speech_error || "speech failed"); body.append(bad); }
    const acts = document.createElement("div"); acts.className = "tl-acts";
    const again = document.createElement("button"); again.type = "button"; again.className = "btn"; again.textContent = "Play from the start"; again.disabled = e.speech !== "ready";
    again.onclick = () => { playAnswer(e, false); };
    const copy = document.createElement("button"); copy.type = "button"; copy.className = "btn"; copy.textContent = "Copy";
    copy.onclick = () => { (navigator.clipboard ? navigator.clipboard.writeText(e.text) : Promise.reject()).then(() => { copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy"; }, 1500); }, () => showError("Copying failed.")); };
    acts.append(again, copy);
    body.append(chips, acts);
    row.append(body);
  }
  return row;
}
const rowSig = (t, q, isNow) => [t.a.id, t.a.n, t.a.text.length, t.a.speech, t.a.speech_error || "", t.a.words?.length || 0, t.q ? t.q.id + t.q.text : "", t.a.superseded ? 1 : 0,
  t.a.id > (view.heard_upto ?? -1) ? 1 : 0, opened.has(t.a.id) && !isNow ? 1 : 0, chipsSig(t), q, isNow ? 1 : 0, !!current && current.id === t.a.id && !audio.paused ? 1 : 0, CFG.stageUrl ? 1 : 0].join("|");
// The list of earlier answers (#earlier, rows .tlrow in #tllist), its search and Expand all, from paintAll(). After it has
// placed its rows it calls returnMarkEarlier(#tllist) so call-return.js can put the since-you-left divider in.
function paintEarlier() {
  const list = $("tllist"), turns = turnsOf(view.entries), shown = shownAnswer(), q = foldCached(tlQuery.trim()).out;
  const rest = turns.filter((t) => !shown || t.a.id !== shown.id);
  // A search looks through every answer, the one on the card too.
  const items = q ? turns.filter((t) => turnMatches(t, q)) : rest;
  const showSearch = searchOpen || !!q || rest.length >= 3;
  $("earlier").hidden = !rest.length && !q && !searchOpen;
  $("searchbtn").hidden = !turns.length; $("searchbtn").setAttribute("aria-expanded", String(showSearch && searchOpen));
  $("tlsearch").hidden = !showSearch;
  $("tlcount").textContent = q ? `${items.length} of ${turns.length} answers` : `Earlier, ${rest.length} answer${rest.length === 1 ? "" : "s"}`;
  const allOpen = rest.length > 0 && rest.every((t) => opened.has(t.a.id));
  $("tlexpand").hidden = !rest.length;
  const label = allOpen ? "Collapse all" : "Expand all";
  if ($("tlexpand").dataset.label !== label) {
    $("tlexpand").dataset.label = label;
    $("tlexpand").innerHTML = ICON(allOpen ? '<path d="M7 10l5-5 5 5M7 14l5 5 5-5"/>' : '<path d="M7 5l5 5 5-5M7 19l5-5 5 5"/>', 16) + "<span></span>";
    $("tlexpand").lastChild.textContent = label; $("tlexpand").setAttribute("aria-label", label); $("tlexpand").title = label;
  }
  $("tlexpand").setAttribute("aria-pressed", String(allOpen));
  const live = new Set();
  let prev = null;
  for (const t of items) {
    const isNow = !!shown && t.a.id === shown.id, sig = rowSig(t, q, isNow);
    live.add(t.a.id);
    let rec = rowNodes.get(t.a.id);
    if (!rec) { rec = {el: buildRow(t, q, isNow), sig}; rowNodes.set(t.a.id, rec); }
    else if (rec.sig !== sig) { const el = buildRow(t, q, isNow); rec.el.replaceWith(el); rec.el = el; rec.sig = sig; }
    let ref = prev ? prev.nextElementSibling : list.firstElementChild;
    while (ref && !ref.classList.contains("tlrow") && ref.id === "sinceleft") ref = ref.nextElementSibling;
    if (ref !== rec.el) list.insertBefore(rec.el, ref);
    prev = rec.el;
  }
  for (const [id, rec] of rowNodes) if (!live.has(id)) { rec.el.remove(); rowNodes.delete(id); }
  let none = list.querySelector(".tl-none");
  if (q && !items.length) { if (!none) { none = document.createElement("p"); none.className = "tl-none"; list.append(none); } none.textContent = `No answer mentions “${tlQuery.trim()}”.`; }
  else if (none) none.remove();
  // the call's own lines (it ended) close the list
  let sys = list.querySelector(".tl-sys");
  const ends = view.entries.filter((e) => e.who === "system").map((e) => e.text).join(" ");
  if (ends && !q) { if (!sys) { sys = document.createElement("p"); sys.className = "tl-sys"; list.append(sys); } sys.textContent = ends; }
  else if (sys) sys.remove();
  paintFront(); paintMissing();
  returnMarkEarlier(list);
}
$("tlsearch").addEventListener("input", () => { tlQuery = $("tlsearch").value; paintEarlier(); });
$("tlsearch").addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && (tlQuery || searchOpen)) { ev.stopPropagation(); tlQuery = ""; $("tlsearch").value = ""; searchOpen = false; paintEarlier(); $("searchbtn").focus(); }
});
$("searchbtn").onclick = () => {
  searchOpen = !searchOpen;
  if (!searchOpen && tlQuery) { tlQuery = ""; $("tlsearch").value = ""; }
  paintEarlier();
  if (searchOpen) { $("convo").scrollTo({top: $("earlier").offsetTop - $("convo").offsetTop, behavior: "auto"}); $("tlsearch").focus(); }
};
$("tlexpand").onclick = () => {
  const shown = shownAnswer(), rest = turnsOf(view.entries).filter((t) => !shown || t.a.id !== shown.id);
  if (rest.every((t) => opened.has(t.a.id))) opened.clear(); else for (const t of rest) opened.add(t.a.id);
  paintEarlier();
};

// ---- the conversation as a whole ---------------------------------------------------
$("empty").replaceChildren(...(() => {
  const a = document.createElement("span"); a.className = "e1"; a.textContent = "Nothing has been said yet.";
  const b = document.createElement("span"); b.className = "e2"; b.textContent = "Type below or press the mic. For example: “Give me the short version.”";
  return [a, b];
})());
function render() {
  $("empty").hidden = !!view.entries.length;
  paintFront();
  paintCalls();
  paintAll();
  paintFront(); paintMissing();
  if (audio.paused) highlight(); else paintReader();
}
// A new view arrived: `before` is the one it replaces. A new answer, or a question just sent, brings the card into view.
function shellOnView(before) {
  const count = (v) => (v.entries || []).filter((e) => e.who === "claude").length, asked = (v) => (v.entries || []).filter((e) => e.who === "you").length;
  if (count(view) > count(before) || asked(view) > asked(before)) { convoFollow = true; scrollConvo(0); }
}

// The conversation follows the voice: the word being said stays in view, until the reader scrolls
// away from it. Then "Back to the voice" brings it back, and following goes on.
let convoFollow = true, ownScroll = 0;
function scrollConvo(top) {
  const box = $("convo");
  if (Math.abs(box.scrollTop - top) < 2) return;
  ownScroll = performance.now();
  box.scrollTo({top, behavior: reduced.matches ? "auto" : "smooth"});
}
function inView(el) {
  const box = $("convo").getBoundingClientRect(), r = el.getBoundingClientRect();
  return r.bottom > box.top + 8 && r.top < box.bottom - 8;
}
// The word being said stays in the card's text window; the card itself comes back into the conversation's view on request.
function followVoice(force) {
  if (rail || !(convoFollow || force)) return;
  const box = $("convo"), tx = $("nowtext"), word = lastWord;
  if (force && box.scrollTop > 0) scrollConvo(0);
  if (word && tx.scrollHeight > tx.clientHeight + 2) {
    const r = word.getBoundingClientRect(), b = tx.getBoundingClientRect();
    if (force || r.top < b.top + 12 || r.bottom > b.bottom - 12) tx.scrollTo({top: Math.max(0, tx.scrollTop + r.top - b.top - b.height * 0.4), behavior: reduced.matches ? "auto" : "smooth"});
  }
}
$("convo").addEventListener("scroll", () => {
  if (performance.now() - ownScroll < 900) return;   // a scroll this page made
  const reading = !!current && !audio.paused && !!lastWord;
  convoFollow = !reading || inView(lastWord);
  paintJump();
}, {passive: true});
function paintJump() { $("jump").hidden = convoFollow || rail || !current || audio.paused; }
$("jump").onclick = () => { convoFollow = true; followVoice(true); paintJump(); };
// The word being said is lit in the card's text, the words before it are full ink, and the card keeps it in view. A
// paused answer keeps its place; one played to its end reads in full.
let lastWord = null, lastK = -2, lastTurn = null;
const readingTurn = () => (current && nowShown === current.id ? $("nowcard") : null);
function highlight() {
  const e = current;
  let k = -1;
  if (e && e.words && e.words.length && !audio.ended) {
    if (audio.currentTime > 0) k = wordAt(e, audio.currentTime);
    const unheard = !sent && e.id > (view.heard_upto ?? -1);
    if (audio.currentTime > 0 || (cueSync && ((sent && sent.id === e.id) || unheard))) {
      const lead = wordAt(e, audio.currentTime + LEAD_S * (audio.playbackRate || 1));
      syncStage(e, Math.min(lead >= 0 ? e.words[lead][0] : -1, heldAt(e) - 1));
    }
    if (audio.currentTime > 0) caption(e, audio.currentTime);
    checkStop(e);
  }
  paintReader();
  const turn = readingTurn();
  if (lastTurn && lastTurn !== turn) {
    lastTurn.classList.remove("reading");
    for (const w of lastTurn.querySelectorAll(".w.said, .w.now-word")) w.classList.remove("said", "now-word");
  }
  lastTurn = turn;
  const reading = !!turn && k >= 0;
  if (turn) turn.classList.toggle("reading", reading);
  if (!reading) k = -1;
  if (k === lastK) return;
  lastK = k;
  for (let i = 0; i < readSpans.length; i++) readSpans[i].classList.toggle("said", i < k);
  if (lastWord) lastWord.classList.remove("now-word");
  lastWord = k >= 0 ? readSpans[k] || null : null;
  if (lastWord) { lastWord.classList.add("now-word"); followVoice(false); }
  if (!audio.paused) paintNowLine();
}
function paintNowLine() {
  const e = current && (view.entries.find(x => x.id === current.id) || current);
  let text = "";
  if (e && e.words && e.words.length && !audio.paused) {
    const starts = sentenceTimes(e), t = audio.currentTime || 0;
    const i = Math.max(0, starts.findLastIndex(x => x <= t + 0.05));
    const from = e.words.findIndex(w => w[2] >= starts[i]);
    const to = i + 1 < starts.length ? e.words.findIndex(w => w[2] >= starts[i + 1]) : e.words.length;
    text = e.text.slice(e.words[from][0], e.words[Math.max(from, to - 1)][1]);
  }
  if ($("nowline").textContent !== text) { $("nowline").textContent = text; $("nowline").title = text; }
}

// ---- the player's controls, on the card --------------------------------------------
$("playpause").onclick = $("railpp").onclick = togglePlay;
$("back").onclick = () => jump(-1);
$("next").onclick = () => jump(1);
$("railback").onclick = () => skip(-10);
$("seek").oninput = () => { audio.currentTime = Number($("seek").value); paintPill(); };
for (const ev of ["play", "pause", "ended", "durationchange", "loadedmetadata"]) audio.addEventListener(ev, paintAll);
audio.addEventListener("timeupdate", paintPill);
// The frame loop does not run in a tab out of sight: the audio's own timeupdate still does, so a hidden tab
// stops at a check or guess too.
audio.addEventListener("timeupdate", () => { if (current) checkStop(view.entries.find(x => x.id === current.id) || current); });
audio.addEventListener("play", startHighlight);
for (const ev of ["pause", "ended"]) audio.addEventListener(ev, stopHighlight);
audio.addEventListener("seeked", () => { if (audio.paused) highlight(); });

// ---- the hooks this file owns (C) -----------------------------------------------
// The player's controls, painted from paintPill(): the card's transport and the rail's ring and buttons. Every control
// acts on the answer the card names; when Play would start another one (the board in front belongs to it), the button says so.
function paintTransport() {
  const rec = !!recorder, shown = shownAnswer();
  const playable = !rec && !!shown && shown.speech === "ready";
  $("player").hidden = !playable; $("ring").hidden = !playable;
  $("back").disabled = !current; $("next").disabled = !current; $("railback").hidden = !playable || !current;
  const target = shown ? boardStart() : null, other = target && target.e.id !== shown.id ? target.e : null;
  const base = !audio.paused ? "Pause" : (current && (audio.ended || audio.currentTime >= (audio.duration || 1)) ? "Play again" : "Play");
  const label = other && audio.paused ? "Play answer " + other.n : base;
  for (const id of ["playpause", "railpp"]) {
    $(id).setAttribute("aria-label", label); $(id).dataset.tip = label + " · Space"; $(id).classList.toggle("playing", !audio.paused);
  }
  const d = audio.duration || 0, p = d ? 100 * audio.currentTime / d : 0;
  $("seek").max = d; $("seek").value = audio.currentTime || 0;
  $("seek").style.setProperty("--p", p + "%"); $("ring").style.setProperty("--p", p + "%");
  $("seek").setAttribute("aria-label", shown ? "Position in answer " + shown.n : "Position in the answer");
  $("seek").setAttribute("aria-valuetext", current ? fmt(audio.currentTime) + " of " + fmt(d) : "");
  $("time").textContent = current ? fmt(audio.currentTime) + " / " + fmt(d) : "";
  $("speedchip").textContent = speed + "×";
}
