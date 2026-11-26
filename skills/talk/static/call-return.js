// Return and place (R): the welcome-back card (#welcome), the since-you-left divider (#sinceleft) in the list of earlier
// answers, the state-in-words strip (#statestrip), and the polite live region (#announcer). The batch R owns this file.
// What the other files own is reached only through the hooks the design names: C's paintEarlier() calls returnMarkEarlier(),
// the poll calls returnOnView(), paintAll() calls the three paint hooks, and anyone calls announce().

// ---- leaving and coming back ------------------------------------------------------------------
// A tab that goes out of sight writes when, and the newest answer it had, to this origin's storage (a reload or a closed tab
// then still knows). Back after AWAY_MIN_MS the answers that came meanwhile and were not played are "since you left"
// (the divider); back after AWAY_MS the welcome-back card offers them (Play the new, Read them).
const AWAY_MS = 5 * 60 * 1000, AWAY_MIN_MS = 30 * 1000, AWAY_CLEAR_MS = 60 * 1000;
let hiddenAt = 0, leftUpto = -1;    // when this tab left sight (ms, 0 while in sight) and the newest answer it held then
let absence = null;                 // {ms, upto, back, seen}: the user came back; answers after `upto` were missed
let welcomeOpen = false;            // the card may show: a real absence, not yet dismissed or played from
function newestAnswerId() { let id = -1; for (const e of view.entries) if (e.who === "claude" && e.id > id) id = e.id; return id; }
function leaving() {
  hiddenAt = Date.now(); leftUpto = newestAnswerId();
  store.set("away." + CFG.call, {at: hiddenAt, upto: leftUpto});
}
function returned(ms, upto) {
  store.set("away." + CFG.call, null);
  if (ms < AWAY_MIN_MS) return false;
  absence = {ms, upto, back: Date.now(), seen: false};
  welcomeOpen = ms >= AWAY_MS;
  return true;
}
let hadAwayNote = false;            // this origin held a note when the page opened (even one too short to count as an absence)
{ // a reload or a reopened tab: the last page left a note (nothing is painted while the files load)
  const rec = store.get("away." + CFG.call, null);
  hadAwayNote = !!(rec && rec.at);
  if (rec && rec.at) returned(Date.now() - rec.at, typeof rec.upto === "number" ? rec.upto : -1);
  store.set("away." + CFG.call, null);
}
// A browser that never saw this call (a new profile, another device, cleared storage) has no note, yet the call may have been
// waiting a long time: the newest answer not heard is old. Page only, from the first view: the answers before that one are not
// counted, so the card offers the one that came while nobody listened.
function absenceFromAge() {
  if (absence || hadAwayNote || view.ended) return false;
  const heard = view.heard_upto ?? -1;
  let at = -1;
  for (let i = view.entries.length - 1; i >= 0; i--) { const e = view.entries[i]; if (e.who === "claude" && e.id > heard) { at = i; break; } }
  if (at < 0 || typeof view.entries[at].at !== "number") return false;
  const ms = (serverNow() - view.entries[at].at) * 1000;
  if (ms < AWAY_MS) return false;
  let upto = -1;
  for (let i = at - 1; i >= 0; i--) if (view.entries[i].who === "claude") { upto = view.entries[i].id; break; }
  return returned(ms, upto);
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") { if (!hiddenAt) leaving(); return; }
  if (!hiddenAt) return;
  const ms = Date.now() - hiddenAt, upto = leftUpto; hiddenAt = 0;
  if (returned(ms, upto)) paintAll();
});
window.addEventListener("pagehide", () => { if (!hiddenAt) leaving(); });
// The answers that came while the user was away and are still not played, oldest first.
function newAnswers() {
  if (!absence) return [];
  const from = Math.max(view.heard_upto ?? -1, absence.upto);
  return view.entries.filter(e => e.who === "claude" && e.id > from);
}
function dropAbsence() {
  if (!absence) return;
  if (newAnswers().length) absence.seen = true;
  else if (absence.seen || Date.now() - absence.back > AWAY_CLEAR_MS) { absence = null; welcomeOpen = false; }
}
function awayText(ms) {
  const min = Math.max(1, Math.round(ms / 60000));
  if (min < 60) return t("t.min", {n: min});
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 24) return t("t.h", {n: h}) + (m ? " " + t("t.min", {n: m}) : "");
  const d = Math.floor(h / 24), hh = h % 24;
  return t("t.d", {n: d}) + (hh ? " " + t("t.h", {n: hh}) : "");
}
function audioText(seconds) {
  const s = Math.round(seconds);
  return s < 60 ? t("t.s", {n: s}) : t("t.min", {n: Math.floor(s / 60)}) + (s % 60 ? " " + t("t.s", {n: s % 60}) : "");
}
// What the card says: the answers not heard, their boards and spoken length, and whether Claude is still working.
function welcomeFacts() {
  const fresh = newAnswers(), ns = new Set(fresh.map(e => e.n));
  const boards = view.entries.filter(e => e.who === "board" && ns.has(e.answer)).length;
  const seconds = fresh.reduce((sum, e) => sum + (e.words && e.words.length ? e.words[e.words.length - 1][3] : 0), 0);
  return {count: fresh.length, ready: fresh.filter(e => e.speech === "ready").length, boards, seconds};
}
// Play the new: the answers that came while the user was away play one after another, from the first. The first is the user's
// play (readerPlays, so a board they picked stays in front); the rest follow by themselves, like any answer that starts by itself.
// An answer that arrives meanwhile waits its turn in the player's own queue, which is held back until the list is played.
let catchUp = [], catchPlaying = null, catchStash = null;
function playTheNew() {
  const list = newAnswers().filter(e => e.speech === "ready");
  if (!list.length) return;
  welcomeOpen = false;
  catchUp = list.slice(1).map(e => e.id); catchPlaying = list[0].id; catchStash = null;
  readerPlays(list[0]); takeVoice(); load(list[0], true);
  paintAll();
}
function endCatchUp() {
  catchPlaying = null; catchUp = [];
  if (catchStash) { queued = catchStash; catchStash = null; }
}
// Runs in the `ended` event itself, before the player's own timer starts a queued answer: the next of the list goes first.
audio.addEventListener("ended", () => {
  if (catchPlaying === null) return;
  if (!current || current.id !== catchPlaying) { endCatchUp(); return; }   // the reader went elsewhere
  while (catchUp.length) {
    const id = catchUp.shift(), e = view.entries.find(x => x.id === id);
    if (!e || e.speech !== "ready") continue;
    if (userBusy() || recorder || stopped) break;
    if (queued) { catchStash = queued; queued = null; }
    catchPlaying = e.id; load(e, true); return;
  }
  endCatchUp();
});
// Read them: the page scrolls to where the new answers start and nothing plays.
function readThem() {
  welcomeOpen = false;
  const to = $("sinceleft") || $("nowcard");
  if (to) { to.setAttribute("tabindex", "-1"); to.focus(); to.scrollIntoView({block: "start", behavior: reduced.matches ? "auto" : "smooth"}); }
  paintAll();
}
audio.addEventListener("play", () => { if (welcomeOpen) { welcomeOpen = false; paintAll(); } });
$("wbplay").onclick = playTheNew;
$("wbread").onclick = readThem;
$("wbx").onclick = () => { welcomeOpen = false; paintAll(); };

// ---- the state in words ----------------------------------------------------------------------
// The newest question the call has not answered, in the server's time: the clock of a wait runs from it, so it survives a reload.
function openTurnAt() {
  for (let i = view.entries.length - 1; i >= 0; i--) {
    const e = view.entries[i];
    if (e.who === "claude") return null;
    if (e.who === "you" && !e.withdrawn) return typeof e.at === "number" ? e.at : null;
  }
  return null;
}
function openQuestion() {
  for (let i = view.entries.length - 1; i >= 0; i--) { const e = view.entries[i]; if (e.who === "claude") return ""; if (e.who === "you" && !e.withdrawn) return e.text; }
  return "";
}
const elapsedOf = at => at == null ? "" : fmt(serverNow() - at);
const answerNumber = e => e && e.n ? e.n : (e && view.entries.filter(x => x.who === "claude" && x.id <= e.id).length) || 0;
// The first that applies. `clock`: the server time its clock counts from, or null.
function stripInfo() {
  const shown = shownAnswer(), n = answerNumber(shown), board = !!(CFG.stageUrl && frontBoard);
  if (floorNote) return {key: "paused", text: floorWords(floorNote), warn: true, act: t("strip.resume"), clock: null};
  if (view.ended) return {key: "ended", text: t(closed ? "s.closed" : "s.ended"), clock: null};
  if (recorder || (live && live.speech)) return {key: "talking", text: t("s.listening"), clock: null};
  if (busy) return {key: "answering", text: t("s.transcribing"), clock: null};
  // The wait card's model is the one source for where a question stands: its step is the word and its first send the clock, so
  // the strip, the Now card and the card itself never disagree (a question sent again keeps the time it has waited).
  const w = waitModel(), clock = w ? w.sentAt : openTurnAt();
  if (view.stalled) return {key: "stalled", text: t(w && w.step === "silent" ? "s.silent" : "s.stalled"), warn: true, clock};
  if (view.working || waitActive()) return {key: "answering", text: t(w && w.step === "sent" ? "s.sent" : "s.answering"), clock};
  if (queued) return {key: "new", text: t("s.next", {n: answerNumber(queued)}), clock: null};
  if (elsewhere && audio.paused && current) return {key: "paused", text: t("s.elsewhere"), clock: null};
  if (current && !audio.paused) return {key: "playing", text: t("s.playing", {n}) + (board ? t(follow ? "s.following" : "s.pinned") : ""), clock: null};
  if (current && audio.paused && !audio.ended && audio.currentTime > 0) return {key: "paused", text: t("s.paused", {n}), clock: null};
  const missed = newAnswers().length || unheardHere().length;
  if (missed) return {key: "new", text: tn("answers.unheard", missed), clock: null};
  return {key: "waiting", text: t(view.entries.some(e => e.who === "claude") ? "s.waiting" : "s.first"), clock: null};
}
let stripTimer = 0, stripSig = "";
function paintStateStrip() {
  const strip = $("statestrip");
  strip.hidden = view.v === -1;
  if (strip.hidden) return;
  const info = stripInfo(), need = callsNeedingYou();
  const text = info.text + (info.clock != null ? " · " + elapsedOf(info.clock) : "");
  const more = otherCallsText(need.length);
  const auto = !!autoplay;
  const sig = [info.key, text, info.warn ? 1 : 0, info.act || "", more, auto ? 1 : 0, uiLang].join("|");
  if (sig !== stripSig) {
    stripSig = sig;
    strip.dataset.key = info.key; strip.classList.toggle("warn", !!info.warn);
    $("ssico").innerHTML = glyphOf(info.key);
    $("sstext").textContent = text; $("ssmore").textContent = more; $("ssmore").hidden = !more;
    $("ssmore").title = need.length ? t("others.list", {list: need.map(x => "“" + x.c.topic + "”").join(", ")}) : "";
    $("ssact").hidden = $("ssx").hidden = !info.act; if (info.act) $("ssact").textContent = info.act;
    // the name is set here too: the page's own English is in the markup, which applyLang leaves alone while the language is English
    $("ssauto").setAttribute("aria-pressed", String(auto)); $("ssauto").setAttribute("aria-label", t("strip.autoplay.aria")); $("ssnote").hidden = auto;
    $("ssauto").dataset.tip = t(auto ? "strip.autoplay.on.tip" : "strip.autoplay.off.tip");
    $("ssautolbl").textContent = t(auto ? "strip.autoplay.on" : "strip.autoplay.off");
  }
  // A wait counts seconds; the strip repaints each second only while it shows a clock.
  if (info.clock != null && !stripTimer) stripTimer = setInterval(() => { paintStateStrip(); paintWelcome(); }, 1000);
  else if (info.clock == null && stripTimer && !welcomeWorking()) { clearInterval(stripTimer); stripTimer = 0; }
}
$("ssact").onclick = resumeHere;
$("ssx").onclick = () => { floorNote = null; paintAll(); };
$("ssauto").onclick = () => { $("autoplay").click(); paintStateStrip(); };
// Either switch (the strip's drives the settings row's) says what it did once through the live region. The state is also on the
// control as aria-pressed; its name stays the visible word (strip.autoplay.aria starts with it), so a voice command by name finds it.
// The settings row's own handler (call-input.js) runs after this listener was added, so the new state is read a moment later.
$("autoplay").addEventListener("click", () => setTimeout(() => announce(t(autoplay ? "strip.autoplay.on.tip" : "strip.autoplay.off.tip")), 0));
// "1 other call needs you" is a button for the Calls menu (the header's Calls button opens the same one).
{
  const more = $("ssmore");
  more.setAttribute("role", "button"); more.tabIndex = 0;
  const open = ev => { ev.stopPropagation(); $("callsbtn").click(); };
  more.addEventListener("click", open);
  more.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(ev); } });
}

// ---- the welcome-back card ---------------------------------------------------------------------
function welcomeWorking() { return welcomeOpen && !$("welcome").hidden && !!view.working && !view.ended; }
let welcomeSig = "";
function paintWelcome() {
  dropAbsence();
  const card = $("welcome"), facts = absence && welcomeOpen && view.v !== -1 && audio.paused ? welcomeFacts() : null;
  card.hidden = !facts || !facts.count;
  if (card.hidden) { welcomeSig = ""; return; }
  const working = !!view.working && !view.ended, q = openQuestion();
  const work = working ? t("away.working") + (q ? t("away.on", {q: q.length > 70 ? q.slice(0, 70) + "…" : q}) : "") + (openTurnAt() != null ? " · " + elapsedOf(openTurnAt()) : "") : "";
  const sig = JSON.stringify([absence.ms, facts, work, uiLang]);
  if (sig === welcomeSig) return;
  welcomeSig = sig;
  $("wbaway").textContent = t("away.text", {t: awayText(absence.ms)});
  const parts = [tn("answers.unheard", facts.count)];
  if (facts.boards) parts.push(tn("boards", facts.boards));
  if (facts.seconds >= 1) parts.push(t("away.audio", {t: audioText(facts.seconds)}));
  $("wbfacts").replaceChildren(...parts.map(text => { const s = document.createElement("span"); s.textContent = text; return s; }));
  $("wbwork").hidden = !work; $("wbwork").textContent = work;
  $("wbplay").disabled = !facts.ready;
  $("wbplaytext").textContent = !facts.ready ? t("away.making") : tn("away.play", facts.ready);
}

// ---- the since-you-left divider -----------------------------------------------------------------
// The list of earlier answers has placed its rows: the divider goes before the first one that came while the user was away
// and has not been played, with how many are left; it goes when none is. Its Play starts the same walk as the welcome card.
function returnMarkEarlier(list) {
  const fresh = new Set(newAnswers().map(e => String(e.id)));
  let first = null, count = 0;
  for (const row of list.querySelectorAll(".tlrow")) if (fresh.has(row.dataset.id)) { first = first || row; count++; }
  let div = list.querySelector("#sinceleft");
  if (!first) { if (div) div.remove(); return; }
  if (!div) {
    div = document.createElement("div"); div.id = "sinceleft"; div.className = "sinceleft"; div.setAttribute("role", "listitem");
    const label = document.createElement("span"); label.className = "slabel";
    const n = document.createElement("span"); n.className = "scount";
    const b = document.createElement("button"); b.type = "button"; b.className = "splay"; b.onclick = playTheNew;
    b.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z"/></svg><span></span>';
    label.textContent = "";
    div.append(label, n, b);
  }
  div.querySelector(".slabel").textContent = t("since.left"); div.querySelector(".splay span").textContent = t("since.play");
  div.querySelector(".scount").textContent = t("since.count", {n: count});
  if (div.nextElementSibling !== first) first.before(div);
}

// ---- the live region ---------------------------------------------------------------------------
// One polite region says what happens while nobody watches the panel: Claude starts or changes what it works on, a call stalls or
// ends, an answer arrives, a board changes. announce(text) queues one short sentence; the same sentence is not said twice within
// ten seconds, a burst is said as one, a second apart at least, and nothing is said while the user is typing a message.
const ANNOUNCE_GAP_MS = 1500, ANNOUNCE_SAME_MS = 10000, ANNOUNCE_LIFE_MS = 20000, ANNOUNCE_BATCH = 3;
// A sentence said stays as text in the region, and a reader browsing the page would find it as if it were current: it is cleared
// this long after it is set (a generous margin over the voice, so a long sentence is not cut), and at once when a new one comes.
const ANNOUNCE_CLEAR_MS = ANNOUNCE_GAP_MS + 12000;
let annQueue = [], annTimer = 0, annSaid = 0, annClear = 0;
const annHeard = new Map();   // each sentence said, and when: the same one is not said again within ANNOUNCE_SAME_MS
function typingNow() { const t = $("text"); return document.activeElement === t && t.value.trim() !== ""; }
function announce(text) {
  text = String(text || "").replace(/\s+/g, " ").trim();
  if (!text) return;
  const now = Date.now();
  if (annQueue.some(q => q.text === text) || now - (annHeard.get(text) || -Infinity) < ANNOUNCE_SAME_MS) return;
  annQueue.push({text, at: now});
  if (annQueue.length > 6) annQueue.shift();
  flushAnnounce();
}
function flushAnnounce() {
  clearTimeout(annTimer); annTimer = 0;
  const now = Date.now();
  annQueue = annQueue.filter(q => now - q.at < ANNOUNCE_LIFE_MS);
  if (!annQueue.length) return;
  const wait = ANNOUNCE_GAP_MS - (now - annSaid);
  if (wait > 0 || typingNow()) { annTimer = setTimeout(flushAnnounce, Math.max(wait, 500)); return; }
  const batch = annQueue.splice(0, ANNOUNCE_BATCH), text = batch.map(q => q.text).join(" ");
  for (const q of batch) annHeard.set(q.text, now);
  annSaid = now;
  // Cleared first, so the same words said again are a change a screen reader notices.
  $("announcer").textContent = ""; clearTimeout(annClear);
  setTimeout(() => {
    $("announcer").textContent = text;
    clearTimeout(annClear); annClear = setTimeout(() => { $("announcer").textContent = ""; annClear = 0; }, ANNOUNCE_CLEAR_MS);
  }, 50);
  if (annQueue.length) annTimer = setTimeout(flushAnnounce, ANNOUNCE_GAP_MS);
}
// A new view arrived: what a screen reader would otherwise miss (the wait card says its own steps, call-wait.js). The first view only learns what is there.
let announced = new Set();
const ARRIVAL_HOLD_MS = 15000;
const arrivalHeld = [];   // {id, line, at}: "Answer N arrived" lines waiting for the voice to be heard or to be known not to come
// Said once the voice is silent and the answer did not play, said no more once it did (the listener heard it): the live region
// never talks over an answer. Called from the paint hook and from a timer at the end of the hold.
function releaseArrivals() {
  for (let i = arrivalHeld.length - 1; i >= 0; i--) {
    const h = arrivalHeld[i], e = view.entries.find(x => x.id === h.id);
    const heard = !!current && current.id === h.id && (!audio.paused || audio.currentTime > 0 || audio.ended);
    const coming = autoplay && !!e && e.speech !== "failed" && !view.ended && Date.now() - h.at < ARRIVAL_HOLD_MS;
    if (heard || (audio.paused && !coming)) { arrivalHeld.splice(i, 1); if (!heard) announce(h.line); }
  }
}
function questionBefore(i) {
  for (let k = i - 1; k >= 0; k--) { const e = view.entries[k]; if (e.who === "claude") return ""; if (e.who === "you" && !e.withdrawn) return e.text; }
  return "";
}
function returnOnView(before) {
  if (before.v === -1) { absenceFromAge(); for (const e of view.entries) if (e.who === "claude") announced.add(e.id); return; }
  view.entries.forEach((e, i) => {
    if (e.who !== "claude" || announced.has(e.id)) return;
    announced.add(e.id);
    const q = questionBefore(i), short = q.length > 70 ? q.slice(0, 70) + "…" : q;
    const line = t("ann.arrived", {n: answerNumber(e)}) + (short ? ": " + short : "") + ".";
    // An answer that is about to autoplay is heard in a moment: the line waits (arrivalHeld), as a board's does, and is never
    // said over the voice. A voice that does not come (autoplay off, no audio) lets it go.
    if (autoplay) arrivalHeld.push({id: e.id, line, at: Date.now()}); else announce(line);
  });
  if (arrivalHeld.length) { releaseArrivals(); setTimeout(releaseArrivals, ARRIVAL_HOLD_MS + 50); }
  if (view.ended && !before.ended) announce(t("ann.ended"));
}
// Board changes come from the stage, not the poll. They are said only while the voice is silent: with an answer playing the
// reader hears the answer, and a screen reader on top of it would talk over it.
let boardSaid = null;
function paintAnnounce() {
  if (arrivalHeld.length) releaseArrivals();
  if (annQueue.length && !annTimer) flushAnnounce();
  if (boardSaid === null) { boardSaid = frontBoard; return; }
  if (frontBoard === boardSaid) return;
  boardSaid = frontBoard;
  if (!frontBoard || !audio.paused) return;
  const b = view.entries.find(e => e.who === "board" && e.view === frontBoard);
  if (b && b.text) announce(t("ann.board", {text: b.text}));
}

// ---- a way to the newest answer -------------------------------------------------------------------
// The first stop of the panel for the keyboard and a screen reader: it jumps to the newest answer (the Now card, else the last turn).
function jumpLatest() {
  const turns = document.querySelectorAll("#convo .turn.claude");
  const to = (!$("nowcard").hidden && $("nowcard")) || turns[turns.length - 1] || $("convo");
  to.setAttribute("tabindex", "-1"); to.focus(); to.scrollIntoView({block: "start"});
}
$("skiplatest").onclick = ev => { ev.preventDefault(); jumpLatest(); };
