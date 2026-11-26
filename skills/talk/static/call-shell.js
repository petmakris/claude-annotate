// ---- the conversation: the Now card over the list of earlier answers --------------------------
// The panel shows one answer in full, the one in the player (else the newest): its question, its text with the word
// being said lit, its boards as named chips, the player's controls, and whether the stage follows the voice. Every
// other answer is a row of the list under it: number, question and gist, boards, time, Play. A row opens in place; a
// search finds an answer by its question, its words or its boards. What the page draws comes from `turnsOf`, which
// pairs each answer with the question that asked it and the boards it showed; progress notes ("thinking it
// through") are not part of the conversation: the foot says what Claude is doing now.
const staged = (e) => !!CFG.stageUrl && (e.cues || []).some((c) => c.kind === "front");

// ---- what the conversation is made of ------------------------------------------
// Each answer with the question it answers, the boards it showed (the board entries before it) and the notes it
// saved. The questions the user has put since the last answer are kept as a list: an answer takes the last one (and
// shows the others it was merged with), but a reply kept as superseded answers the question it was written for. That
// is the one the correction names (`replaces`), else the first one the server set aside, and for an addition the first
// one asked; the later question stays open for the answer that follows.
function turnsOf(entries) {
  const turns = [];
  let open = [], boards = [], notes = [];
  for (const e of entries) {
    if (e.who === "you") { if (!e.withdrawn) open.push(e); }
    else if (e.who === "board") boards.push(e);
    else if (e.who === "note") notes.push(e);
    else if (e.who === "claude") {
      let q = null, also = [];
      if (e.superseded) {
        const fix = e.superseded_kind === "addition" ? null : open.find((x) => Number.isFinite(x.replaces) && open.some((y) => y.id === x.replaces));
        q = (fix && open.find((y) => y.id === fix.replaces)) || (e.superseded_kind === "addition" ? null : open.find((x) => x.superseded)) || open[0] || null;
        open = open.filter((x) => x !== q);
      } else {
        q = open.length ? open[open.length - 1] : null;
        also = open.slice(0, -1).filter((x) => !x.superseded);
        open = [];
      }
      turns.push({a: e, q, also, boards, notes}); boards = []; notes = [];
    }
  }
  return turns;
}
// The time an entry was made at, by the server's clock: "09:52" today, "Yesterday 09:52", else "24 Nov 09:52" (the year
// too when it is not this one), so an answer from another day is never taken for this morning's.
const monthName = (i) => tr("s.months").split(",")[i];
function clockOf(at) {
  if (!at) return "";
  const d = new Date(at * 1000), now = new Date(serverNow() * 1000);
  const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const ago = Math.round((day(now) - day(d)) / 86400000);
  if (ago <= 0) return hm;
  if (ago === 1) return tr("s.yesterday", {hm});
  return d.getDate() + " " + monthName(d.getMonth()) + (d.getFullYear() !== now.getFullYear() ? " " + d.getFullYear() : "") + " " + hm;
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
const boardName = (b) => b.kind === "points" ? tr("s.keypoints") : b.text;
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
  sequence: '<path d="M4 1.5v13M12 1.5v13M4 5h8M9.5 2.8 12 5l-2.5 2.2M12 11H4M6.5 8.8 4 11l2.5 2.2"/>',
  bars: '<path d="M2 14h12M4.5 14V8M8 14V3.5M11.5 14V6"/>',
  graph: '<path d="M2 2v12h12"/><path d="m4.5 10.5 3-3.5 2.5 2 3.5-5"/>',
  screen: '<rect x="1.5" y="2.5" width="13" height="9" rx="1.6"/><path d="M5.5 14h5M8 11.5V14"/>',
};
KIND_ICONS.flowchart = KIND_ICONS.map = KIND_ICONS.diagram;   // every board kind has its own icon: no chip falls back to the page icon
const kindIcon = (kind, size = 13) => `<svg viewBox="0 0 16 16" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${KIND_ICONS[kind] || KIND_ICONS.page}</svg>`;
const ICON = (d, size = 14) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;

// A board's chip: icon and its name; a press brings the board to the front of the stage (and pins it).
function buildChip(b) {
  const el = document.createElement("button"); el.type = "button"; el.className = "chip board"; el.dataset.view = b.view || "";
  el.innerHTML = kindIcon(b.kind);
  const t = document.createElement("span"); t.className = "cl"; t.textContent = boardName(b); el.append(t);
  let said = boardName(b);
  if (b.kind === "points" && b.added) {
    const s = document.createElement("small"); s.textContent = trn("s.chip.added", b.added); el.append(s); said += ", " + s.textContent;
  }
  el.setAttribute("aria-label", tr("s.chip.show", {name: said}));
  el.setAttribute("aria-pressed", "false");
  if (!CFG.stageUrl || !b.view) { el.disabled = true; el.title = tr("s.chip.na"); }
  else { el.title = tr("s.chip.tip"); el.onclick = () => chipTap(b.view); }
  return el;
}
// A note the user asked to be kept: a row with a check and the word Saved, the note whole on as many lines as it takes.
// It is a line of this call's transcript, not a board, so it is not a chip and links to nothing.
function buildNote(n) {
  const row = document.createElement("div"); row.className = "note-row"; row.title = tr("s.note.tip");
  const mark = document.createElement("span"); mark.className = "note-mark"; mark.innerHTML = ICON('<path d="M5 12l5 5L20 7"/>', 14);
  const word = document.createElement("b"); word.textContent = tr("s.saved");
  const text = document.createElement("span"); text.className = "note-text"; text.textContent = n.text;
  row.append(mark, word, text);
  return row;
}
// The chips of one answer, with the notes it saved, as one labelled group.
function buildChips(t) {
  const frag = document.createDocumentFragment();
  if (t.boards.length) {
    const l = document.createElement("span"); l.className = "clbl"; l.textContent = tr("s.onstage"); frag.append(l);
    for (const b of t.boards) frag.append(buildChip(b));
  }
  for (const n of t.notes) frag.append(buildNote(n));
  return frag;
}
const chipsSig = (t) => uiLang + "|" + t.boards.map((b) => `${b.view}|${b.text}|${b.added || 0}|${boardWords(b).length}`).join(";") + "#" + t.notes.map((n) => n.text).join(";");

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
  if (wait) {   // the wait card's own step, so the eyebrow never says Working over a card that says Sent
    const w = waitModel(), step = w ? w.step : "";
    if (step === "sent") return {key: "working", word: tr("s.st.sent")};
    if (step === "notpicked") return {key: "slow", word: tr("s.st.notpicked")};
    if (step === "silent") return {key: "slow", word: tr("s.st.quiet")};
    return step === "slow" || view.stalled ? {key: "slow", word: tr("s.st.slow")} : {key: "working", word: tr("s.st.working")};
  }
  if (!e) return null;
  if (e.speech === "pending" || e.speech === "making") return {key: "voice", word: tr("s.st.voice")};
  if (e.speech === "failed") return {key: "silent", word: tr("s.st.failed")};
  const mine = !!current && current.id === e.id;
  if (mine && !audio.paused) return {key: "playing", word: tr("s.st.playing")};
  if (mine && audio.paused && elsewhere) return {key: "elsewhere", word: tr("s.st.elsewhere")};
  if (mine && (audio.ended || (audio.duration && audio.currentTime >= audio.duration))) return {key: "played", word: tr("s.st.played")};
  if (mine && audio.currentTime > 0) return {key: "paused", word: tr("s.st.paused")};
  return {key: "ready", word: tr(e.id > (view.heard_upto ?? -1) ? "s.st.new" : "s.st.ready")};
}
// the card's eyebrow is the heading of its answer (the earlier rows are headings too), so heading navigation lists the answers
$("nownum").setAttribute("role", "heading"); $("nownum").setAttribute("aria-level", "3");
let nowSig = "", nowChipsSig = "", nowHeadSig = "", nowShown = null;   // the answer whose text the card holds
let readSpans = [];
function buildNowText(e) {
  const box = $("nowtext");
  box.replaceChildren(...wordSpans(e));
  readSpans = [...box.querySelectorAll(".w")];
  lastWord = null; lastK = -2;
  nowShown = e.id;
  paintTextFades();
}
// The card's text window says when more of the text is above or below it: a fade at that edge (CSS reads the two
// attributes), so a window that begins mid-line or ends mid-line never looks like all there is.
function paintTextFades() {
  const tx = $("nowtext");
  tx.toggleAttribute("data-above", tx.scrollTop > 2);
  tx.toggleAttribute("data-below", tx.scrollHeight - tx.scrollTop - tx.clientHeight > 2);
}
$("nowtext").addEventListener("scroll", paintTextFades, {passive: true});
// The window is sized in whole lines by the height the panel has free: what is on the card besides the text (head, question,
// chips, transport, Following strip) and, while earlier answers wait, the head of their list and two rows come off the panel's
// height, so a laptop screen shows the list under the card and the window never ends mid-line. Show all lifts the cap (the
// word being said stays in view); the control is there only when the text is longer than the window.
const NT_MIN = 3, NT_TIGHT = 2, NT_SHORT = 560, NT_MAX = 16, NT_BUTTON = 36, ROW_H = 68, LIST_GAP = 12;
let ntAll = false;                       // the reader lifted the cap for the answer on the card
const ntMore = document.createElement("button"); ntMore.type = "button"; ntMore.id = "ntmore"; ntMore.className = "nq-more"; ntMore.hidden = true;
$("nowbody").insertBefore(ntMore, $("nowchips"));
ntMore.onclick = () => { ntAll = !ntAll; fitNowText(); followVoice(true); };
// whole lines that fit in `free` pixels at `lh` pixels a line
const ntLines = (free, lh, tight) => Math.max(tight ? NT_TIGHT : NT_MIN, Math.min(NT_MAX, Math.floor(free / lh)));
function fitNowText() {
  const tx = $("nowtext"), card = $("nowcard"), box = $("convo");
  if (card.hidden) return;
  const lh = parseFloat(getComputedStyle(tx).lineHeight) || 25, cs = getComputedStyle(box);
  const earlier = box.classList.contains("has-earlier") && !$("earlier").hidden;
  const reserve = earlier ? LIST_GAP + Math.max(40, $("tlhead").offsetHeight) + 2 * ROW_H : 0;
  const others = card.offsetHeight - tx.offsetHeight - (ntMore.hidden ? 0 : ntMore.offsetHeight + 8) + NT_BUTTON;
  const free = box.clientHeight - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0) - others - reserve;
  const lines = ntLines(free, lh, box.clientHeight < NT_SHORT && matchMedia("(min-width: 761px)").matches);   // a short laptop panel gives the list its head before it gives the text a third line; a phone keeps three
  if (tx.style.getPropertyValue("--nt-lines") !== String(lines)) tx.style.setProperty("--nt-lines", lines);
  tx.toggleAttribute("data-all", ntAll);
  ntMore.hidden = !ntAll && !(tx.scrollHeight > lines * lh + 2);
  const label = tr(ntAll ? "s.less" : "s.more");
  if (ntMore.textContent !== label) ntMore.textContent = label;
  ntMore.setAttribute("aria-expanded", String(ntAll));
  paintTextFades();
}
window.addEventListener("resize", fitNowText);
if (typeof ResizeObserver === "function") {   // what is free changes with the panel, the card's other parts (chips, the strip when the stage reports) and the list's head
  const watch = new ResizeObserver(fitNowText);
  for (const id of ["convo", "nowcard", "tlhead"]) watch.observe($(id));
}
// An answer played to its end shows from its first line again; a paused one keeps its place, and a tap on a word scrolls to it.
audio.addEventListener("ended", () => {
  const tx = $("nowtext");
  if (current && nowShown === current.id && tx.scrollTop > 0) tx.scrollTop = 0;
  paintTextFades();
});
// A question the user typed, as typed: its breaks kept, at the weight of the text, held to three lines with Show all
// when it is longer (the clamped form squeezes runs of blank lines so paragraphs do not use up the three lines; Show all gives the text whole).
const qOpen = new Set();      // the questions whose full text the reader opened
const squeezed = (text) => text.replace(/\n[ \t]*(?:\n[ \t]*)+/g, "\n");   // the clamped form: blank lines do not use up its lines
const longQuestion = (text) => text.length > 140 || (text.match(/\n/g) || []).length >= 3;
function buildQuestion(q) {
  const box = document.createElement("div"); box.className = "nq";
  const open = qOpen.has(q.id);
  const text = document.createElement("span"); text.className = "nq-text" + (open ? "" : " clamped"); text.textContent = open ? q.text : squeezed(q.text);
  const more = document.createElement("button"); more.type = "button"; more.className = "nq-more";
  more.textContent = tr(open ? "s.less" : "s.more"); more.setAttribute("aria-expanded", String(open));
  more.hidden = !open && !longQuestion(q.text);
  more.onclick = () => { if (qOpen.has(q.id)) qOpen.delete(q.id); else qOpen.add(q.id); $("nowq").dataset.sig = ""; paintNowCard(); };
  box.append(text, more);
  return box;
}
// A question the browser lays out in fewer than three lines needs no Show all: only the long ones keep it (where layout is measured).
function measureQuestions() {
  for (const box of document.querySelectorAll("#nowq .nq")) {
    const text = box.querySelector(".nq-text"), more = box.querySelector(".nq-more");
    if (text.classList.contains("clamped") && text.scrollHeight > text.clientHeight + 1) more.hidden = false;
  }
}
window.addEventListener("resize", measureQuestions);
// The card of the current turn, from paintAll(). While a turn is in flight the card shows the wait card (W) instead of the answer.
function paintNowCard() {
  const e = shownAnswer(), wait = waitActive(), card = $("nowcard");
  card.hidden = !e && !wait;
  if (card.hidden) { nowShown = null; return; }
  const turns = turnsOf(view.entries), total = turns.length, t = e ? turns.find((x) => x.a.id === e.id) : null;
  // the head: state, which answer, when it was made
  const st = nowState(e, wait), num = wait ? tr("s.answer", {n: total + 1}) : total > 1 ? tr("s.answer.of", {n: e.n, total}) : tr("s.answer", {n: e.n});
  const tag = e && e.superseded ? tr("s.corrected") : "";
  const headSig = [uiLang, st && st.key, st && st.word, num, tag, e && e.at].join("|");
  if (headSig !== nowHeadSig) {
    nowHeadSig = headSig;
    $("nowstate").innerHTML = st ? STATE_ICONS[st.key] + "<b></b>" : ""; if (st) $("nowstate").lastChild.textContent = st.word;
    $("nowstate").dataset.state = st ? st.key : "";
    $("nownum").textContent = num; $("nownum").dataset.tag = tag;
    $("nowclock").textContent = !wait && e ? clockOf(e.at) : ""; $("nowclock").title = $("nowclock").textContent ? tr("s.answered", {t: $("nowclock").textContent}) : "";
    $("nowhead").classList.toggle("replaced", !!tag);
    let tagEl = $("nowhead").querySelector(".now-tag");
    if (tag) { if (!tagEl) { tagEl = document.createElement("span"); tagEl.className = "now-tag"; $("nowclock").before(tagEl); } tagEl.textContent = tag; }
    else if (tagEl) tagEl.remove();
  }
  card.dataset.state = st ? st.key : "";
  $("nowcopy").hidden = !e || wait;
  if (!e) return;
  // the question asked (or the questions this answer was merged from), the full text, the boards
  const asked = t && t.q ? t.q : null, qs = asked ? [...(t.also || []), asked] : [];
  $("nowq").hidden = !asked;
  const qsig = uiLang + qs.map((q) => q.id + "|" + q.text + "|" + (qOpen.has(q.id) ? 1 : 0) + "|" + clockOf(q.at)).join("§");
  if ($("nowq").dataset.sig !== qsig) {
    $("nowq").dataset.sig = qsig;
    const small = document.createElement("small"); small.textContent = tr("s.asked", {t: clockOf(qs[0] && qs[0].at)});
    $("nowq").replaceChildren(small, ...qs.map(buildQuestion));
    measureQuestions();
  }
  const sig = `${uiLang}|${e.id}|${e.text.length}|${e.words?.length || 0}`;
  if (sig !== nowSig) {
    nowSig = sig;
    const wasShown = nowShown;
    buildNowText(e);
    if (wasShown !== e.id) { card.classList.remove("reading"); $("nowtext").scrollTop = 0; lastTurn = null; ntAll = false; }
  }
  const csig = uiLang + e.id + "#" + (t ? chipsSig(t) : "");
  if (csig !== nowChipsSig) {
    nowChipsSig = csig;
    $("nowchips").replaceChildren(t ? buildChips(t) : document.createDocumentFragment());
    paintFront(); paintMissing();
  }
  $("nowchips").hidden = !$("nowchips").childNodes.length;
  let bad = card.querySelector(".now-bad");
  if (e.speech === "failed") {
    if (!bad) { bad = document.createElement("div"); bad.className = "now-bad"; $("nowbody").append(bad); }
    bad.textContent = tr("s.notread", {why: e.speech_error || tr("s.speechfailed")});
  } else if (bad) bad.remove();
  paintFollow();
  fitNowText();
}

// ---- the Following strip ---------------------------------------------------------------
// Whether the stage follows the voice, always on the card. Following: "Following the voice", the stage goes where the voice
// goes. Pinned: "You chose this", a board picked by hand stays in front, with its board and answer named, which answer the
// voice is on and, when Play would start another one, which. One button switches: Keep this board, or Back to the voice. The
// stage's own button says Back to the voice too, so the card, the stage and the keys name one thing. Nothing is clamped: the
// answer numbers are the point of the words.
let followSig = "";
// With the stage pinned by hand and the voice paused, Play starts the answer that owns the board in front: that answer when it is not the card's own.
function pinnedOther() {
  const shown = shownAnswer(), b = shown && !follow && audio.paused ? boardStart() : null;
  return b && b.e.id !== shown.id ? b.e : null;
}
function paintFollow() {
  paintTransport();   // Play's word depends on whether the stage follows: every change of it lands here
  const box = $("nowfollow");
  const has = !!CFG.stageUrl && (!!frontBoard || (!!stageViews && stageViews.size > 0));
  box.hidden = !has;
  if (!has) { followSig = ""; return; }
  const front = boardTitle(frontBoard), fa = boardAnswer.get(frontBoard);
  const shown = shownAnswer(), n = shown ? shown.n : null, other = pinnedOther();
  let label, text, note = "", still = false;
  if (follow) {
    label = tr("s.fol.following");
    still = !!front && !!fa && !!n && fa !== n;   // the shown answer has no board of its own: the stage keeps an older one
    text = still ? tr("s.fol.still", {front, fa}) : tr("s.fol.reading");
  } else {
    label = tr("s.fol.chose");
    text = (front ? (fa ? tr("s.fol.from", {front, fa}) : tr("s.fol.shows", {front})) : tr("s.fol.chosen")) + "." + (n ? tr("s.fol.voice", {n}) : "");
    note = other ? tr("s.play.n.board", {n: other.n}) : "";   // the words of the transport's button
  }
  const btnText = tr(follow ? "s.fol.keep" : "s.fol.back");
  const sig = [uiLang, follow, label, text, note, btnText, still ? 1 : 0, other && n].join("|");
  if (sig === followSig) return;
  followSig = sig;
  const state = document.createElement("span"); state.className = "fl-state";
  state.innerHTML = follow ? ICON('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>') : ICON('<path d="M12 17v5M9 3h6l-1 7 3 3H7l3-3z"/>');
  const word = document.createElement("b"); word.textContent = label; state.append(word);
  if (follow && !still) state.title = text;   // the bare sentence is the tooltip: the label says it, and the strip stays one line
  const msg = document.createElement("span"); msg.className = "fl-text"; msg.textContent = text;
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "fl-btn";
  btn.textContent = btnText; btn.setAttribute("aria-label", btnText);
  btn.title = tr(follow ? "s.fol.keep.tip" : "s.fol.back");
  btn.onclick = () => { if (follow) pinBoard(); else { followAgain(); resync(); } };
  box.dataset.mode = follow ? "following" : "pinned"; box.dataset.text = still || !follow ? "board" : "plain";
  const parts = [state, btn, msg];
  if (still) { const hint = document.createElement("span"); hint.className = "fl-hint"; hint.textContent = tr("s.fol.keep.hint"); parts.push(hint); }   // what Keep this board does, in words (the tooltip is not seen on touch)
  if (note) {
    const nt = document.createElement("span"); nt.className = "fl-note"; nt.textContent = note; parts.push(nt);
    // the card's own answer stays playable from the card while the transport's Play names the board's answer
    const own = document.createElement("button"); own.type = "button"; own.className = "fl-btn"; own.classList.add("fl-own");
    own.textContent = tr("s.fol.playown", {n}); own.onclick = () => playAnswer(shown, true);
    parts.push(own);
  }
  box.replaceChildren(...parts);
}

// ---- the list of earlier answers ---------------------------------------------------
const opened = new Set();     // the answers whose row the reader opened
let tlQuery = "", searchOpen = false;
const SEARCH_AFTER = 12;      // more rows than this show the search field without being asked
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
// The turn's searchable words: its question (and the ones it was merged from), its text, its boards' names and what its boards
// show (their cells, labels and values, as the server flattened them into the board entry's `search`).
const boardWords = (b) => (typeof b.search === "string" ? b.search : "");
function turnMatches(t, q) {
  return !!(t.q && matchAt(t.q.text, q)) || (t.also || []).some((x) => matchAt(x.text, q)) || !!matchAt(t.a.text, q)
    || t.boards.some((b) => matchAt(boardName(b), q) || matchAt(boardWords(b), q));
}
// Text with the search's match marked (nodes, never markup).
function marked(text, q) {
  const m = q ? matchAt(text, q) : null;
  if (!m) return [document.createTextNode(text)];
  const mk = document.createElement("mark"); mk.textContent = text.slice(m.from, m.to);
  return [document.createTextNode(text.slice(0, m.from)), mk, document.createTextNode(text.slice(m.to))];
}
// The words round a match, cut at both ends with an ellipsis and never in the middle of a word at the start.
function around(text, m, lead = 14) {
  let a = Math.max(0, m.from - lead);
  while (a > 0 && a < m.from && /\S/.test(text[a - 1])) a++;
  const b = Math.min(text.length, m.to + 70);
  return (a > 0 ? "…" : "") + text.slice(a, b).replace(/\s+/g, " ") + (b < text.length ? "…" : "");
}
// The gist line; when the search matches only the answer's words, the words around the match; when only a board's words,
// "in <board>:" with the board's icon and the words round the match.
function gistLine(t, q) {
  const e = t.a;
  if (q && !(t.q && matchAt(t.q.text, q))) {
    const other = (t.also || []).find((x) => matchAt(x.text, q));
    if (other) return marked(around(other.text, matchAt(other.text, q)), q);
    if (matchAt(e.text, q)) return marked(around(e.text, matchAt(e.text, q)), q);
    const b = t.boards.find((x) => matchAt(boardName(x), q) || matchAt(boardWords(x), q));
    if (b) {
      const ic = document.createElement("span"); ic.className = "in-board"; ic.innerHTML = kindIcon(b.kind, 13);
      const name = document.createElement("span"); name.className = "in-name"; name.textContent = tr("s.in", {name: boardName(b)});
      const m = matchAt(boardWords(b), q);
      return [ic, name, ...(m ? marked(around(boardWords(b), m, 6), q) : [])];
    }
  }
  return marked(gistOf(e), q);
}
// Copy text to the clipboard, said on the button and to a screen reader.
function copyText(text, done) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => { done(); announce(tr("s.copied")); }, () => showError(tr("s.copy.fail")));
}
// An answer was picked to play: the card takes it. A press made on a row of the list loses that row (the card shows the answer
// now), so focus goes where the reader's hands are next: the player's button, or the same row's button when the row stayed.
function playAnswer(e, own) {
  e = view.entries.find((x) => x.id === e.id) || e;
  if (current && current.id === e.id && !audio.paused) { audio.pause(); return; }
  const from = document.activeElement, inList = !!from && $("tllist").contains(from);
  let rowEl = from; while (rowEl && !(rowEl.classList && rowEl.classList.contains("tlrow"))) rowEl = rowEl.parentNode;
  const rowId = inList && rowEl ? rowEl.dataset.id : null;
  readerPlays(e);
  if (!own) followAgain();   // another answer was picked: its boards are what the reader wants to see
  takeVoice(); load(e, true);
  convoFollow = true; scrollConvo(0);
  if (inList && !(document.activeElement && $("tllist").contains(document.activeElement))) {
    const row = rowId === null ? null : [...$("tllist").children].find((r) => r.dataset && r.dataset.id === rowId);
    const again = row && row.querySelector("button.play");
    (again || $(rail ? "railpp" : "playpause")).focus();
  }
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
  if ((t.q && !(open && !q)) || (q && !matchAt(gistOf(e), q))) { const g = document.createElement("span"); g.className = "tl-gist"; g.append(...gistLine(t, q)); qq.append(g); }
  main.append(n, qq);
  main.onclick = () => { if (opened.has(e.id)) { opened.delete(e.id); paintEarlier(); } else { opened.add(e.id); paintEarlier(); rowToTop(e.id); } };
  const bd = document.createElement("button"); bd.type = "button"; bd.className = "tl-b";
  const boards = t.boards;
  if (boards.length) {
    const first = boards.find((b) => b.kind !== "points") || boards[0];
    bd.innerHTML = kindIcon(first.kind, 16);
    if (boards.length > 1) { const c = document.createElement("span"); c.textContent = boards.length; bd.append(c); }
    const shows = !!CFG.stageUrl && !!first.view;   // the click puts the first board on the stage; with several, it opens the row too
    const name = boardName(first), names = boards.map(boardName).join(", ");
    bd.setAttribute("aria-label", boards.length === 1 ? tr("s.show.board", {name}) : tr(shows ? "s.boards.show" : "s.boards.open", {n: boards.length, name}));
    bd.title = boards.length > 1 && shows ? tr("s.boards.tip", {name, names}) : names;
    bd.onclick = () => {
      if (boards.length === 1 && shows) { chipTap(first.view); return; }
      if (boards.length === 1) { main.click(); return; }
      opened.add(e.id); paintEarlier(); rowToTop(e.id);   // opens the row if it is closed, never closes it
      if (shows) chipTap(first.view);
    };
    if (!CFG.stageUrl && boards.length === 1) bd.disabled = true;
  } else { bd.disabled = true; bd.tabIndex = -1; bd.setAttribute("aria-hidden", "true"); }
  const tm = document.createElement("span"); tm.className = "tl-t"; tm.textContent = clockOf(e.at); tm.title = tr("s.answered", {t: tm.textContent});
  const play = document.createElement("button"); play.type = "button"; play.className = "play";
  const playing = !!current && current.id === e.id && !audio.paused;
  play.disabled = e.speech !== "ready";
  play.innerHTML = ICON(playing ? '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>' : '<path d="M7 5v14l12-7z"/>', 14) + "<span></span>";
  play.lastChild.textContent = tr(playing ? "s.pause" : "s.hear");
  play.setAttribute("aria-label", tr(playing ? "s.pause.n" : "s.hear.n", {n: e.n}));
  play.onclick = () => playAnswer(e, !!isNow);
  const head = document.createElement("div"); head.className = "tl-h"; head.setAttribute("role", "heading"); head.setAttribute("aria-level", "3");
  head.append(main);   // heading navigation lists the answers; the button inside keeps its own role
  row.append(head, bd, tm, play);
  if (e.superseded) { const tg = document.createElement("span"); tg.className = "tl-tag"; tg.textContent = tr("s.replaced"); qq.append(tg); }
  if (open) {
    const body = document.createElement("div"); body.className = "tl-body";
    const text = document.createElement("div"); text.className = "tl-text"; text.replaceChildren(...wordSpans(e));
    body.append(text);
    const chips = document.createElement("div"); chips.className = "chips"; chips.setAttribute("role", "group"); chips.setAttribute("aria-label", tr("s.onstage"));
    chips.append(buildChips(t)); chips.hidden = !chips.childNodes.length;
    if (e.speech === "failed") { const bad = document.createElement("div"); bad.className = "now-bad"; bad.textContent = tr("s.notread", {why: e.speech_error || tr("s.speechfailed")}); body.append(bad); }
    const acts = document.createElement("div"); acts.className = "tl-acts";
    const again = document.createElement("button"); again.type = "button"; again.className = "btn"; again.textContent = tr("s.hear"); again.disabled = e.speech !== "ready";
    again.onclick = () => { playAnswer(e, false); };
    const copy = document.createElement("button"); copy.type = "button"; copy.className = "btn"; copy.textContent = tr("s.copy");
    copy.onclick = () => copyText(e.text, () => { copy.textContent = tr("s.copied"); setTimeout(() => { copy.textContent = tr("s.copy"); }, 1500); });
    acts.append(again, copy);
    body.append(chips, acts);
    row.append(body);
  }
  return row;
}
const rowSig = (t, q, isNow) => [uiLang, t.a.id, t.a.n, t.a.text.length, t.a.speech, t.a.speech_error || "", t.a.words?.length || 0, t.q ? t.q.id + t.q.text : "", (t.also || []).map((x) => x.id + x.text).join("§"), t.a.superseded ? 1 : 0,
  t.a.id > (view.heard_upto ?? -1) ? 1 : 0, opened.has(t.a.id) && !isNow ? 1 : 0, chipsSig(t), q, isNow ? 1 : 0, !!current && current.id === t.a.id && !audio.paused ? 1 : 0, CFG.stageUrl ? 1 : 0].join("|");
// The list of earlier answers (#earlier, rows .tlrow in #tllist), its search and Expand all, from paintAll(). After it has
// placed its rows it calls returnMarkEarlier(#tllist) so call-return.js can put the since-you-left divider in.
function paintEarlier() {
  const list = $("tllist"), turns = turnsOf(view.entries), shown = shownAnswer(), q = foldCached(tlQuery.trim()).out;
  list.classList.toggle("searching", !!q);   // a search shows the words round its match on two lines, also on a phone
  const rest = turns.filter((t) => !shown || t.a.id !== shown.id);
  // A search looks through every answer, the one on the card too.
  const items = q ? turns.filter((t) => turnMatches(t, q)) : rest;
  const showSearch = searchOpen || !!q || rest.length > SEARCH_AFTER;   // a few rows are seen at a glance: the search icon opens the field
  $("earlier").hidden = !rest.length && !q && !searchOpen;
  $("searchbtn").hidden = !turns.length; $("searchbtn").setAttribute("aria-expanded", String(showSearch && searchOpen));
  $("tlsearch").hidden = !showSearch;
  // while a search filters the list the count line says so in words, with the way back to every answer
  $("tlcount").textContent = q ? tr("s.filtered", {n: items.length, total: turns.length}) : trn("s.earlier", rest.length);
  $("tlcount").classList.toggle("filtered", !!q); $("tlclear").hidden = !q;
  $("convo").classList.toggle("has-earlier", rest.length > 0);   // the card's text window is shorter while earlier answers wait under it
  const allOpen = rest.length > 0 && rest.every((t) => opened.has(t.a.id));
  $("tlexpand").hidden = !rest.length;
  const label = tr(allOpen ? "s.collapse" : "s.expand");
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
  if (q && !items.length) { if (!none) { none = document.createElement("p"); none.className = "tl-none"; list.append(none); } none.textContent = tr("s.none", {q: tlQuery.trim()}); }
  else if (none) none.remove();
  // the call's own lines (it ended) close the list
  let sys = list.querySelector(".tl-sys");
  const ends = view.entries.filter((e) => e.who === "system").map((e) => e.text).join(" ");
  if (ends && !q) { if (!sys) { sys = document.createElement("p"); sys.className = "tl-sys"; list.append(sys); } sys.textContent = ends; }
  else if (sys) sys.remove();
  paintFront(); paintMissing();
  returnMarkEarlier(list);
  paintMore();
  fitNowText();   // has-earlier and the search field changed what is free for the card's text window
}
// A row that opens comes to the top of the panel: its text starts in view, not under the card or below the fold.
function rowToTop(id) {
  const row = [...$("tllist").children].find((r) => r.dataset && r.dataset.id === String(id));
  if (!row) return;
  const box = $("convo");
  convoFollow = false;   // the reader is reading this row, not following the voice
  scrollConvo(Math.max(0, box.scrollTop + row.getBoundingClientRect().top - box.getBoundingClientRect().top - 4));
}
// The search field at the top of the view, so its results (on a phone, a short window) are all in sight.
const searchToTop = () => $("convo").scrollTo({top: $("earlier").offsetTop - $("convo").offsetTop, behavior: "auto"});
// The search is a way to find one answer, not a state of the call: it is cleared when a question is sent or a new answer comes,
// so the list never stays filtered unnoticed. Opening a row from a result keeps it.
function clearSearch() { tlQuery = ""; $("tlsearch").value = ""; searchOpen = false; }
const clearBtn = document.createElement("button"); clearBtn.type = "button"; clearBtn.id = "tlclear"; clearBtn.className = "tl-clear"; clearBtn.hidden = true;
clearBtn.textContent = tr("s.more"); clearBtn.setAttribute("aria-label", tr("s.showall.aria"));
$("tlhead").insertBefore(clearBtn, $("tlcount").nextSibling);
clearBtn.onclick = () => { tlQuery = ""; $("tlsearch").value = ""; paintEarlier(); $("tlsearch").focus(); };
$("tlsearch").addEventListener("input", () => { tlQuery = $("tlsearch").value; paintEarlier(); if (tlQuery.trim()) searchToTop(); });
$("tlsearch").addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && (tlQuery || searchOpen)) { ev.stopPropagation(); clearSearch(); paintEarlier(); $("searchbtn").focus(); }
});
$("searchbtn").onclick = () => {
  searchOpen = !searchOpen;
  if (!searchOpen && tlQuery) { tlQuery = ""; $("tlsearch").value = ""; }
  paintEarlier();
  if (searchOpen) { searchToTop(); $("tlsearch").focus(); }
};
// Expand all opens every row and brings the list's head to the top of the panel: the rows are the point, not the card above.
$("tlexpand").onclick = () => {
  const shown = shownAnswer(), rest = turnsOf(view.entries).filter((t) => !shown || t.a.id !== shown.id);
  const closing = rest.every((t) => opened.has(t.a.id));
  if (closing) opened.clear(); else for (const t of rest) opened.add(t.a.id);
  paintEarlier();
  if (!closing) searchToTop();
};

// ---- the conversation as a whole ---------------------------------------------------
$("empty").replaceChildren(...(() => {
  const a = document.createElement("span"); a.className = "e1"; a.textContent = tr("list.empty");
  const b = document.createElement("span"); b.className = "e2"; b.textContent = tr("s.empty2");
  return [a, b];
})());
// The words this file built once at load, in the page's language again (called from relabelPage()).
function relabelShell() {
  copyBtn.setAttribute("aria-label", tr("s.copyans")); copyBtn.dataset.tip = tr("s.copyans");
  if (!copyBtn.classList.contains("done")) copyBtn.innerHTML = copyHtml();
  fitNowText();
  clearBtn.textContent = tr("s.more"); clearBtn.setAttribute("aria-label", tr("s.showall.aria"));
  $("empty").querySelector(".e1").textContent = tr("list.empty"); $("empty").querySelector(".e2").textContent = tr("s.empty2");
}
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
  const sent = asked(view) > asked(before), answered = count(view) > count(before);
  if (answered || sent) { convoFollow = true; scrollConvo(0); }
  // a question sent, or an answer that came while the reader was not typing in the search, ends the search
  if ((tlQuery || searchOpen) && (sent || (answered && document.activeElement !== $("tlsearch")))) clearSearch();
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
  } else if (word && ntAll) {   // the cap is lifted: the panel scrolls to keep the word in view
    const r = word.getBoundingClientRect(), b = box.getBoundingClientRect();
    if (force || r.top < b.top + 12 || r.bottom > b.bottom - 12) scrollConvo(Math.max(0, box.scrollTop + r.top - b.top - b.height * 0.4));
  }
}
// The conversation says when more lies below its edge: a fade over the bottom of the panel (the sticky #convofade), so a list
// that goes on under the foot is never mistaken for the whole of it.
const fade = document.createElement("div"); fade.id = "convofade"; fade.className = "convo-fade"; fade.setAttribute("aria-hidden", "true");
$("convo").append(fade);
function paintMore() {
  const box = $("convo");
  box.toggleAttribute("data-more", box.scrollHeight - box.scrollTop - box.clientHeight > 6);
}
window.addEventListener("resize", paintMore);
$("convo").addEventListener("scroll", () => {
  paintMore();
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
// Play's visible word, for the one time it names another answer than the card's (see paintTransport).
const ppWord = document.createElement("span"); ppWord.className = "pp-word"; $("playpause").append(ppWord);
// Copy answer: the text of the answer the card shows, on the card. The word Copied shows on the button and goes to the live region.
const copyBtn = document.createElement("button"); copyBtn.type = "button"; copyBtn.id = "nowcopy"; copyBtn.className = "ib nowcopy"; copyBtn.hidden = true;
const COPY_ICON = ICON('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>', 18), COPIED_ICON = ICON('<path d="M5 12l5 5L20 7"/>', 16);
// the word Copy sits beside the icon when the card is wide (CSS shows .cp-word); the icon alone when it is narrow
const copyHtml = () => COPY_ICON + '<span class="cp-word">' + tr("s.copy") + "</span>";
copyBtn.setAttribute("aria-label", tr("s.copyans")); copyBtn.dataset.tip = tr("s.copyans"); copyBtn.innerHTML = copyHtml();
let copyTimer = null;
copyBtn.onclick = () => {
  const e = shownAnswer();
  if (!e) return;
  copyText(e.text, () => {
    copyBtn.classList.add("done"); copyBtn.innerHTML = COPIED_ICON + "<span>" + tr("s.copied") + "</span>"; copyBtn.setAttribute("aria-label", tr("s.copied"));
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copyBtn.classList.remove("done"); copyBtn.innerHTML = copyHtml(); copyBtn.setAttribute("aria-label", tr("s.copyans")); }, 1500);
  });
};
$("nowhead").append(copyBtn);   // in the card's head, by the time: the transport row has no room for another button on a phone
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
// acts on the answer the card names. Only a stage the reader pinned by hand sends Play to the answer that owns the board in
// front; then the button says so in a word beside its icon, not only in its name and tooltip.
function paintTransport() {
  const rec = !!recorder, shown = shownAnswer();
  const playable = !rec && !!shown && shown.speech === "ready";
  $("player").hidden = !playable; $("ring").hidden = !playable;
  $("back").disabled = !current; $("next").disabled = !current; $("railback").hidden = !playable || !current;
  const other = pinnedOther();
  const base = tr(!audio.paused ? "s.pp.pause" : (current && (audio.ended || audio.currentTime >= (audio.duration || 1)) ? "s.pp.again" : "s.pp.play"));
  const label = other ? tr("s.play.n.board", {n: other.n}) : base;   // the reason is in the words: the board the reader chose is another answer's
  const word = other ? label : "";
  if (ppWord.textContent !== word) ppWord.textContent = word;
  $("playpause").classList.toggle("has-word", !!word); $("player").classList.toggle("names-answer", !!word);
  for (const id of ["playpause", "railpp"]) {
    $(id).setAttribute("aria-label", label); $(id).dataset.tip = label + " · Space"; $(id).classList.toggle("playing", !audio.paused);
  }
  const d = audio.duration || 0, p = d ? 100 * audio.currentTime / d : 0;
  $("seek").max = d; $("seek").value = audio.currentTime || 0;
  $("seek").style.setProperty("--p", p + "%"); $("ring").style.setProperty("--p", p + "%");
  $("seek").setAttribute("aria-label", shown ? tr("s.seek.n", {n: shown.n}) : tr("player.seek"));
  $("seek").setAttribute("aria-valuetext", current ? fmt(audio.currentTime) + " of " + fmt(d) : "");
  $("time").textContent = current ? fmt(audio.currentTime) + " / " + fmt(d) : "";
  $("speedchip").textContent = speed + "×";
}
