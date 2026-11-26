// ---- the stage ---------------------------------------------------------
// A veil covers the stage until it has loaded; one that does not load in time says so and offers buttons.
let stageTimer = null;
function stageReady() { clearTimeout(stageTimer); $("veil").hidden = true; }
function stageFailed() { $("veilwait").hidden = true; $("veilfail").hidden = false; }
function loadStage() {
  stageUp = false;
  $("veil").hidden = false; $("veilwait").hidden = false; $("veilfail").hidden = true;
  clearTimeout(stageTimer); stageTimer = setTimeout(stageFailed, window.__stageTimeoutMs || 10000);
  $("stage").src = CFG.stageUrl;
}
if (CFG.stageUrl) {
  $("openstage").href = CFG.stageUrl;
  // Only the stage saying it is ready counts: a page that failed to load fires "load" too (Chrome's own
  // error page), and that must show the Reload box, not an empty frame.
  $("stage").addEventListener("load", () => {
    if (!$("stage").getAttribute("src") || stageUp) return;
    clearTimeout(stageTimer); stageTimer = setTimeout(() => { if (!stageUp) stageFailed(); }, window.__stageReadyMs || 4000);
  });
  $("reloadstage").onclick = loadStage;
  loadStage();
} else { $("stagewrap").remove(); $("nostage").hidden = false; }

// ---- talk and stage talk to each other -----------------------------------
// The protocol, also described at the top of stage.js. Talk to stage, posted to the stage's origin:
//   {type:'stage:front', view, manual, answer}  bring a board to the front; manual: a chip was pressed
//   {type:'stage:frame', view, n, animate, answer}  show frame n of the scene answer number `answer` said the
//                                       board with (each answer keeps its own), animated when it is the next one
//   {type:'stage:state', front, frames, keys, answer}  after a jump: the board in front, every scene's frame
//                                       (of that answer's scenes), the key point lit
//   {type:'stage:answer', n, follow}    answer n started playing; follow:false when the reader started it
//   {type:'stage:rest', views, answer}  that answer ended a moment ago: these boards, still on its scenes, show whole
//   {type:'stage:key', view, index}     key point number index (from 1) was just said: light it up
//   {type:'stage:theme', theme}         'light' or 'dark': the theme chosen here
//   {type:'stage:follow', on, front}    the gear's switch (or Back to the voice) turned following on or off; with front
//                                       the stage also fronts the board the voice fronted last (a board picked by hand,
//                                       Key points among them, stops holding it)
//   {type:'stage:lang', lang}           'en' or 'el': the page's language, said on load and on every change; the stage's
//                                       own words (toolbar, counters, Copy, step control) follow it
//   {type:'stage:caption', text, answer}  the sentence being said, of an answer that has boards ('' clears it)
// Stage to talk: {type:'stage:ready'}, {type:'stage:views', list:[{name, title, kind, answer}]} on every
// change, {type:'stage:changed', name, title, isNew}, and {type:'stage:follow', on} when following
// changes inside the stage (a tab tap, a chip or a step by hand turns it off, Back to the voice or a new answer
// on; a play of the board in front turns it on from here), {type:'stage:key', key} for Space, ← or →
// pressed on the stage with nothing there taking them, and {type:'stage:missing', view} when a chip
// asked for a view it does not hold: such chips are struck through. Only messages from the embedded stage's own
// window and origin are read. Until the stage says it is ready, what talk sends waits in a short queue.
var stageUp = false;
const stageOrigin = CFG.stageUrl ? new URL(CFG.stageUrl, location.href).origin : null;
const stageOutbox = [];
function toStage(msg) {
  if (!stageOrigin || !$("stage")) return;
  if (!stageUp) { stageOutbox.push(msg); if (stageOutbox.length > 20) stageOutbox.shift(); return; }
  try { $("stage").contentWindow.postMessage(msg, stageOrigin); } catch {}
}
// The stage says its own words (Back to the voice, Board 2 of 3, Copy, the step control) in the page's language: it is told on
// load and whenever the page's language changes (applyLang sets <html lang>, which is the one event that says so).
let langSent = "";
function sendStageLang() {
  const lang = typeof uiLang === "string" ? uiLang : "en";
  if (lang === langSent) return;
  langSent = lang;
  toStage({type: "stage:lang", lang});
}
new MutationObserver(sendStageLang).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
window.addEventListener("message", ev => {
  if (!stageOrigin || !$("stage") || ev.source !== $("stage").contentWindow || ev.origin !== stageOrigin) return;
  const m = ev.data;
  if (!m || typeof m !== "object") return;
  if (m.type === "stage:ready") {
    // Every ready, a first load or a stage page loaded again, starts from the page's own state: the
    // theme and following go first, and the queue's older copies of them are dropped.
    stageUp = true; stageReady();
    toStage({type: "stage:theme", theme: document.documentElement.dataset.theme});
    langSent = ""; sendStageLang();
    toStage({type: "stage:zoom", zoom: screenMode === "tv" ? TV_ZOOM : 1});
    toStage({type: "stage:follow", on: follow});
    for (const msg of stageOutbox.splice(0)) if (msg.type !== "stage:theme" && msg.type !== "stage:follow" && msg.type !== "stage:lang") toStage(msg);
    resync();
  }
  else if (m.type === "stage:follow") { follow = !!m.on; paintSettings(); paintFollow(); if (follow) resync(); }
  else if (m.type === "stage:views") {
    stageList = m.list || [];
    stageViews = new Set((m.list || []).map(v => String(v.name)));
    boardAnswer = new Map((m.list || []).map(v => [String(v.name), v.answer]));
    paintMissing(); paintFollow(); paintTransport(); paintStageTitle();
  }
  else if (m.type === "stage:shown") {
    const was = frontBoard;
    frontBoard = String(m.view || ""); paintFront(); paintFollow(); paintTransport(); paintStageTitle();
    // the stage moves in a frame the page cannot read: say which board it is on, for a screen reader
    const title = frontBoard && frontBoard !== was ? boardTitle(frontBoard) : "";
    if (title) announce(tr("st.shows", {title}));
  }
  else if (m.type === "stage:missing") paintMissing(String(m.view));
  else if (m.type === "stage:key" && MEDIA_KEYS.has(m.key)) mediaKey(m.key);
  else if (m.type === "stage:play") playFrame(String(m.view || ""), Number(m.answer), Number(m.n));
  else if (m.type === "stage:ask") askAbout(String(m.text || ""));
  else if (m.type === "stage:pick" && stopped && stopped.n === Number(m.answer) && stopped.i === Number(m.i)) pickStop(Number(m.choice));
});
// Play from here, in a sequence step's popup on the stage: the answer plays from the word where that frame begins.
function playFrame(board, n, frameNo) {
  const e = view.entries.find(x => x.who === "claude" && x.n === n);
  if (!e || e.speech !== "ready" || !e.words || !e.words.length) return;
  const cue = (e.cues || []).find(c => c.kind === "frame" && c.view === board && c.n === frameNo);
  if (!cue) return;
  release();
  const w = e.words.find(w => w[0] >= cue.at) || e.words[e.words.length - 1];
  playFrom(e, w[2], true);
}

// A chip brings its board to the front by hand. The board already in front sends no change, so while the reader's
// text covers the stage the page turns following off itself (what a chip tap does on the stage) and shows the board.
function chipTap(view) {
  toStage({type: "stage:front", view, manual: true});
  if (follow) { follow = false; toStage({type: "stage:follow", on: false}); paintSettings(); }
  const title = boardTitle(view);
  if (title) announce(tr("st.pinned", {title}));
  paintReader(); paintFollow();
}
// Keep the stage on the board in front: following the voice off, said on the card's strip.
function pinBoard() {
  if (!follow) return;
  follow = false; toStage({type: "stage:follow", on: false}); paintSettings(); paintReader(); paintFollow();
  const title = boardTitle(frontBoard);
  announce(title ? tr("st.pinned", {title}) : tr("st.pinned.bare"));
}
let stageViews = null;
let stageList = [];            // the boards the stage holds, in the order it counts them: {name, title, kind, answer}
// The frame's name is the board in front, so a screen reader that lands on it hears which one it is and where it is in the list.
function paintStageTitle() {
  const i = stageList.findIndex(v => String(v.name) === frontBoard), b = stageList[i];
  $("stage").title = b ? tr("st.frame", {title: b.title, kind: b.kind || tr("st.board"), i: i + 1, n: stageList.length}) : tr("stage.title");
}
let boardAnswer = new Map();   // board -> the number of the answer that showed it
let frontBoard = "";           // the board in front of the stage
const chipSeen = new Map();
const MISSING_AFTER_MS = 8000;
function paintMissing(gone) {
  const now = Date.now();
  for (const el of document.querySelectorAll("button.chip.board[data-view]")) {
    const v = el.dataset.view;
    if (!v) continue;
    if (!chipSeen.has(v)) chipSeen.set(v, now);
    const missing = v === gone || (!!stageViews && !stageViews.has(v) && now - chipSeen.get(v) > MISSING_AFTER_MS);
    el.classList.toggle("missing", missing);
    if (missing) { el.title = tr("st.missing"); el.dataset.noStage = "1"; }
    else if (el.dataset.noStage) { el.removeAttribute("title"); delete el.dataset.noStage; }
  }
}
setInterval(() => { if (stageViews) paintMissing(); }, MISSING_AFTER_MS / 2);
// The chip of the board in front of the stage is drawn as chosen, wherever it is in the conversation.
function paintFront() {
  $("app").toggleAttribute("data-board", !!frontBoard);   // a phone gives the stage more height while a board is up
  for (const el of document.querySelectorAll("button.chip.board[data-view]")) {
    const on = !!frontBoard && el.dataset.view === frontBoard;
    el.classList.toggle("front", on); el.setAttribute("aria-pressed", String(on));
  }
}

// ---- following the voice: the stage keeps it, the gear shows it -------------
let follow = true;
$("follow").onclick = () => { follow = !follow; toStage({type: "stage:follow", on: follow, front: follow}); paintSettings(); paintFollow(); if (follow) resync(); };

// ---- the reader: the answer being said, in large type on the stage ----------------------------
// Each sentence appears as it is said, and the word being said is lit; a tap on a word plays from there. When
// the voice reaches a board (its front cue), the board takes the stage and the sentence stays under it on a
// strip. A board the reader picked by hand (following off) stays in front. Before any answer, the stage shows.
// (var and function: the conversation is drawn before the script reaches these lines)
function readerOn() { return !!document.getElementById("reader"); }
var readerSig = "", rSents = [], rWords = [], rPaint = "";
function buildReader(e) {
  const rtextEl = $("rtext");
  rtextEl.replaceChildren(); rSents = []; rWords = [];
  if (!e) return;
  // which answer this is (the panel's card names the same one)
  const head = document.createElement("div"); head.className = "rhead"; head.textContent = tr("s.answer", {n: e.n || ""}); rtextEl.append(head);
  const ss = sentenceSpans(e);
  if (!ss.length) { const s = document.createElement("span"); s.className = "rs"; s.textContent = e.text; rtextEl.append(s); rSents.push({el: s, first: 0, last: -1}); return; }
  if (ss[0].a > 0) rtextEl.append(e.text.slice(0, ss[0].a));
  let wi = 0;
  ss.forEach((sen, j) => {
    const span = document.createElement("span"); span.className = "rs";
    const first = wi;
    let pos = sen.a;
    while (wi < e.words.length && e.words[wi][0] < sen.b) {
      const w = e.words[wi], t = w[2];
      if (w[0] > pos) span.append(e.text.slice(pos, w[0]));
      const ws = document.createElement("span"); ws.className = "w"; ws.textContent = e.text.slice(w[0], w[1]);
      ws.onclick = () => playFrom(e, t);
      span.append(ws); rWords.push(ws); pos = w[1]; wi++;
    }
    if (pos < sen.b) span.append(e.text.slice(pos, sen.b));
    rtextEl.append(span); rSents.push({el: span, first, last: wi - 1});
    const next = j + 1 < ss.length ? ss[j + 1].a : e.text.length;
    if (sen.b < next) rtextEl.append(e.text.slice(sen.b, next));
  });
}
function paintReader() {
  const readerEl = $("reader");
  if (!readerEl) return;
  const e = current ? (view.entries.find(x => x.id === current.id) || current) : lastAnswer();
  const sig = e ? `${e.id}|${e.text.length}|${e.words?.length || 0}` : "";
  if (sig !== readerSig) { readerSig = sig; buildReader(e); rPaint = ""; }
  const t = audio.currentTime || 0;
  const active = !!e && !!current && current.id === e.id && !!e.words?.length && !audio.ended && t > 0;
  const k = active ? wordAt(e, t) : -1;
  // a board is in front once the voice has reached its front cue, at rest when the answer has one, and always
  // when the reader picked one by hand
  // (before the first word the voice is at the start of the text: a board the answer opens with is already in front)
  const pos = active ? (k >= 0 ? e.words[k][0] : 0) : Infinity;
  const onBoard = !!e && !!CFG.stageUrl && (!follow || (e.cues || []).some(c => c.kind === "front" && c.at <= pos));
  // an answer with no board of its own leaves the board in front where it is (its words are on the strip, and the card holds the text)
  const keeps = !!e && !!CFG.stageUrl && !!frontBoard && !(e.cues || []).some(c => c.kind === "front");
  const mode = !e ? "off" : onBoard || keeps ? (active ? "strip" : "off") : "text";
  // following off, the board in front is not one this answer put up (the reader picked it, or an older answer's): the strip's
  // sentence is of another answer than the board over it, so it is named and dimmed until Back to the voice (also while following,
  // when this answer has no board and the stage stays on an earlier one: the Following strip says "Stage still on")
  const foreign = mode === "strip" && (!follow || keeps) && !!frontBoard && !!e && !(e.cues || []).some(c => c.view === frontBoard);
  const j = k < 0 ? -1 : rSents.findIndex(s => k >= s.first && k <= s.last);
  const paint = `${mode}|${active}|${k}|${sig}|${foreign ? 1 : 0}`;
  if (paint === rPaint) return;
  const [was, wasOn] = rPaint.split("|"), movedSentence = !rPaint.startsWith(`${mode}|${active}|`) || rSents[j]?.el.className.indexOf("cur") < 0;
  rPaint = paint;
  readerEl.className = "reader " + mode;
  readerEl.toggleAttribute("data-foreign", foreign);
  readerEl.style.opacity = foreign ? "0.62" : "";
  const rhead = readerEl.querySelector(".rhead");
  if (rhead) { rhead.textContent = tr("s.answer", {n: e.n || ""}) + (foreign ? ":" : ""); rhead.style.display = foreign ? "inline" : ""; rhead.style.margin = foreign ? "0 .6em 0 0" : ""; rhead.style.textTransform = foreign ? "none" : ""; rhead.style.letterSpacing = foreign ? "0" : ""; }
  rSents.forEach((s, i) => { s.el.className = "rs" + (!active ? "" : i < j ? " past" : i === j ? " cur" : " future"); });
  rWords.forEach((w, i) => { w.classList.toggle("said", active && i < k); w.classList.toggle("now-word", active && i === k); });
  if (mode === "text" && active && j >= 0 && movedSentence) {
    // the sentence being said stays in the upper middle of the stage
    const r = rSents[j].el.getBoundingClientRect(), box = readerEl.getBoundingClientRect();
    if (r.top < box.top + box.height * 0.15 || r.bottom > box.top + box.height * 0.6) {
      readerEl.scrollTo({top: readerEl.scrollTop + r.top - box.top - box.height * 0.3, behavior: was === "text" && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "auto"});
    }
  }
  // an answer read in full goes back to its first sentence when it ends (a pause keeps its place: it stays active)
  if (mode === "text" && !active && (was !== "text" || (wasOn === "true" && audio.ended))) readerEl.scrollTop = 0;
  if (mode === "strip" && active && k >= 0) keepWordInStrip(readerEl, rWords[k]);
}
// The strip shows one sentence in a box of three lines: a longer one scrolls so the word being said stays in it.
function keepWordInStrip(box, word) {
  const more = () => box.classList?.toggle("more", box.scrollHeight > box.clientHeight + 2 && box.scrollTop + box.clientHeight < box.scrollHeight - 2);
  if (!word) { more(); return; }
  const b = box.getBoundingClientRect(), r = word.getBoundingClientRect();
  if (r.top < b.top || r.bottom > b.bottom) box.scrollTop = Math.max(0, box.scrollTop + (r.top + r.bottom) / 2 - (b.top + b.bottom) / 2);
  // a word wider than the box (a long path or identifier) is brought into view across as well
  if (r.left < b.left || r.right > b.right) box.scrollLeft = Math.max(0, box.scrollLeft + (r.left + r.right) / 2 - (b.left + b.right) / 2);
  more();   // a sentence longer than the strip says so: its cut line fades into an ellipsis instead of showing half a line
}

// ---- the sentence being said, shown on the stage -------------------------------
// Each sentence of an answer: its start in seconds and its span in the text.
// The sentences of an answer as runs of its words: [first word, last word]. The server's `starts` (character
// offsets into the text where a sentence begins, abbreviation-aware) when the answer carries them; else the
// page's own splitter, which cuts after any word ending in . ! or ?.
function sentenceRuns(e) {
  const words = e.words || [], runs = [];
  if (!words.length) return runs;
  if (Array.isArray(e.starts) && e.starts.length && e.starts.every(n => Number.isFinite(n))) {
    const bounds = [...new Set([0, ...e.starts])].sort((a, b) => a - b);
    bounds.forEach((b, j) => {
      const hi = j + 1 < bounds.length ? bounds[j + 1] : Infinity;
      const first = words.findIndex(w => w[0] >= b && w[0] < hi);
      if (first < 0) return;
      let last = first;
      while (last + 1 < words.length && words[last + 1][0] < hi) last++;
      runs.push([first, last]);
    });
    return runs;
  }
  let first = 0;
  words.forEach((w, i) => {
    const t = e.text.slice(w[0], w[1]);
    // A Greek question mark is a semicolon: it ends a sentence only before a Greek letter (the server's rule).
    const greekMark = /;[)\]"'”’]*$/.test(t) && i + 1 < words.length && /^[\u0370-\u03ff\u1f00-\u1fff]/.test(e.text.slice(words[i + 1][0], words[i + 1][1]));
    if (i === words.length - 1 || /[.!?…\u037e][)\]"'”’]*$/.test(t) || greekMark) { runs.push([first, i]); first = i + 1; }
  });
  return runs;
}
function sentenceSpans(e) { return sentenceRuns(e).map(([f, l]) => ({t: e.words[f][2], a: e.words[f][0], b: e.words[l][1]})); }
let captionShown = "";  // the caption on the stage now: sent only when it changes
function caption(e, t) {
  let text = "";
  // the sentence being said is on the reader's strip under the board, so the stage itself shows no caption
  if (e && staged(e) && !readerOn()) { const s = sentenceSpans(e).filter((x) => x.t <= t + 0.05).pop(); text = s ? e.text.slice(s.a, s.b).trim() : ""; }
  if (text === captionShown) return;
  captionShown = text;
  toStage({type: "stage:caption", text, answer: e ? e.n || null : null});
}

// ---- stops: the answer asks, and waits ----------------------------------------
// A stop ([[check]], [[guess]], [[say back]], [[deeper]]) pauses the voice right after its question, on a card of
// buttons: on the stage for a staged answer, else in the panel. Play at a stop is its first button. A stop the
// play went by is not stopped at again until the reader plays from before it (`passed`, set again on a seek).
let stopped = null;      // the stop the answer waits at: {id, n, i, stop, picked}
let passed = new Set();  // "<answer id>:<stop index>"
let slowTill = null;     // Again, slower: {id, i}: the stop where the speed comes back
let answering = null;    // the [[say back]] question the text field answers
const GUESS_SHOWN_MS = 1600;
const stopsOf = (e) => (e.cues || []).filter((c) => c.kind === "stop");
// Just after the question's last word, before the next word starts; Infinity for a stop at the end.
function stopTime(e, c) {
  const words = e.words || [], next = words.find((w) => w[0] >= c.at);
  if (!next) return Infinity;
  const prev = words.filter((w) => w[1] <= c.at).pop();
  return Math.min(next[2] - 0.02, prev ? prev[3] + 0.25 : next[2]);
}
// The stage runs a little ahead of the voice, but never past a stop it has not passed (or waits at): what
// comes after a guess would give its answer away.
function heldAt(e) {
  if (stopped && stopped.id === e.id) return stopsOf(e)[stopped.i].at;
  const ahead = stopsOf(e).filter((c, i) => !passed.has(e.id + ":" + i)).map((c) => c.at);
  return ahead.length ? Math.min(...ahead) : Infinity;
}
function markPassed(e, t) {
  passed = new Set(stopsOf(e).flatMap((c, i) => (stopTime(e, c) < t + 0.05 ? [e.id + ":" + i] : [])));
}
function checkStop(e) {
  if (stopped || audio.paused || !e.words || !e.words.length) return;
  stopsOf(e).some((c, i) => {
    if (passed.has(e.id + ":" + i) || audio.currentTime < stopTime(e, c)) return false;
    stopAt(e, i); return true;
  });
}
function stopAt(e, i) {
  const c = stopsOf(e)[i];
  passed.add(e.id + ":" + i);
  if (slowTill && slowTill.id === e.id && slowTill.i === i) { audio.playbackRate = speed; slowTill = null; }
  stopped = {id: e.id, n: e.n || 0, i, stop: c.stop, picked: null};  // before the pause, which paints the stage
  if (!audio.paused) audio.pause();
  if (c.stop.type === "sayback") {
    answering = c.stop.question;
    const t = $("text"); t.placeholder = tr("st.sayback"); t.focus();
  }
  showStop();
}
function showStop() {
  const e = stopped && view.entries.find((x) => x.id === stopped.id);
  const onStage = !!e && staged(e);
  toStage({type: "stage:stop", answer: stopped ? stopped.n : null, i: stopped ? stopped.i : null,
           stop: onStage ? {...stopped.stop, picked: stopped.picked} : null});
  paintStopCard(e && !onStage ? e : null);
}
function clearStop() {
  if (!stopped) return;
  stopped = null; showStop();
}
// The panel's card, for an answer with no board.
function paintStopCard(e) {
  const card = $("stopcard");
  card.hidden = !e;
  if (!e) { card.replaceChildren(); return; }
  const {stop, picked} = stopped;
  card.dataset.type = stop.type;
  const q = document.createElement("p"); q.className = "sq"; q.textContent = stop.question || tr("st.more");
  const row = document.createElement("div"); row.className = "sbtns";
  stop.choices.forEach((label, k) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "btn"; b.textContent = label;
    if (picked !== null) {
      b.disabled = true;
      if (stop.right === k) b.classList.add("right");
      else if (picked === k) b.classList.add("wrong");
    }
    b.onclick = () => pickStop(k);
    row.append(b);
  });
  if (stop.type === "sayback") { const h = document.createElement("p"); h.className = "shint"; h.textContent = tr("st.hint"); row.append(h); }
  card.replaceChildren(q, row);
}
function goOn() {
  clearStop();
  if (!audio.ended) { readerPlays(current); audio.play().catch(() => {}); }
}
function pickStop(k) {
  if (!stopped) return;
  const {id, n, i, stop} = stopped, e = view.entries.find((x) => x.id === id);
  if (!e) return;
  if (stop.type === "guess") {
    if (stopped.picked !== null) return;
    stopped.picked = k; showStop();
    api("/api/pick", {method: "POST", body: JSON.stringify({answer: n, i, choice: k}), headers: {"Content-Type": "application/json"}}).catch(() => {});
    setTimeout(() => { if (stopped && stopped.id === id && stopped.i === i) goOn(); }, GUESS_SHOWN_MS);
  } else if (k === 0) goOn();
  else if (stop.type === "check" && k === 1) {
    // Again, slower: the stretch since the stop before plays again at 0.8×, and stops here again.
    const before = stopsOf(e).slice(0, i).map((c) => stopTime(e, c)).filter((t) => t !== Infinity).pop();
    clearStop(); slowTill = {id, i};
    playFrom(e, before === undefined ? 0 : before + 0.01);
    audio.playbackRate = speed * 0.8;
  }
  else if (stop.type === "check" && k === 2) { clearStop(); $("text").value = tr("st.another"); sendText(); }
  else if (stop.type === "deeper" && k === 1) {  // That's enough: the answer ends here
    clearStop(); audio.currentTime = audio.duration || audio.currentTime;
    syncStage(e, Infinity); restBoards(e); caption(null, 0);
  }
}

// ---- the board follows the voice ------------------------------------------
const LEAD_S = 0.12;
let cueSync = true, sent = null;
function stateAt(e, pos) {
  // Before its first cue the answer's first board is in front: the one it put up as it arrived.
  const cues = e.cues || [], st = {front: cues.find(c => c.kind === "front")?.view ?? null, frames: {}, key: null};
  for (const c of cues) if (c.kind === "frame") st.frames[c.view] = 0;
  let lo = 0, hi = cues.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (cues[m].at <= pos) lo = m + 1; else hi = m; }
  for (const c of cues.slice(0, lo)) {
    if (c.kind === "key") st.key = c;
    else { st.front = c.view; if (c.kind === "frame") st.frames[c.view] = c.n; }
  }
  return st;
}
function syncStage(e, pos) {
  const st = stateAt(e, pos);
  if (st.front) voiceFront = {view: st.front, answer: e.n || null};
  if (cueSync || !sent || sent.id !== e.id) {
    toStage({type: "stage:state", front: st.front, frames: st.frames, keys: st.key ? st.key.index : 0, answer: e.n || null});
  } else {
    if (st.front && st.front !== sent.front) toStage({type: "stage:front", view: st.front, manual: false, answer: e.n || null});
    for (const [view, n] of Object.entries(st.frames)) {
      if (sent.frames[view] !== n) toStage({type: "stage:frame", view, n, animate: n === sent.frames[view] + 1, answer: e.n || null});
    }
    if (st.key && (!sent.key || st.key.at !== sent.key.at || st.key.index !== sent.key.index)) toStage({type: "stage:key", view: st.key.view, index: st.key.index});
  }
  cueSync = false;
  sent = {id: e.id, ...st};
}
function resync() { cueSync = true; highlight(); }
// A play the reader starts sends the whole picture with its next frame, and leaves following as it is: a board
// the reader picked (a tab, a chip, a step by hand) stays in front until they press Back to the voice on the
// stage or the gear's switch, play the board in front, or the next answer starts by itself.
let readerAnswer = null;  // the answer the reader last started: its start never turns following on
function readerPlays(e) {
  cueSync = true;
  if (e) readerAnswer = e.id;
}
// `front`: the stage also goes back to the board the voice fronted last (Back to the voice, the gear, the key), so a board the
// reader picked by hand, Key points among them, does not keep the stage; a play of the board in front passes false.
function followAgain(front = true) {
  cueSync = true;
  if (!follow) { follow = true; toStage({type: "stage:follow", on: true, front}); paintSettings(); paintFollow(); }
}
// The latest real board a front cue fronted (never Key points, which no cue fronts): {view, answer, title}, or null when the
// stage does not hold it. The Following strip can offer it ("Show <board>") when the stage is on something else.
let voiceFront = null;     // {view, answer}
function voiceBoard() {
  if (!voiceFront || !stageViews || !stageViews.has(voiceFront.view)) return null;
  return {view: voiceFront.view, answer: voiceFront.answer, title: boardTitle(voiceFront.view), shown: frontBoard === voiceFront.view};
}
// Brings it to the front and follows the voice again; nothing when there is none.
function showVoiceBoard() {
  if (!voiceBoard()) return false;
  followAgain(true);
  if (follow && frontBoard !== voiceFront.view) toStage({type: "stage:front", view: voiceFront.view, manual: false, answer: voiceFront.answer});
  resync();
  return true;
}
// An answer played to its end holds its last frame a moment, then each of its boards shows whole, undimmed.
const REST_HOLD_MS = 1500;
let restTimer = 0;
function restBoards(e) {
  const views = [...new Set((e.cues || []).filter(c => c.kind === "frame").map(c => c.view))];
  if (views.length) toStage({type: "stage:rest", views, answer: e.n || null});
}
let failedShown = null;
function showFailedAnswer() {
  const e = lastAnswer();
  if (!e || e.speech !== "failed" || failedShown === e.id) return;
  failedShown = e.id; cueSync = true; syncStage(e, Infinity); restBoards(e);  // no voice to hold for
}
let answerSent = null;
audio.addEventListener("play", () => {
  if (current && current.id !== answerSent) {
    answerSent = current.id;
    toStage({type: "stage:answer", n: current.n || 0, follow: current.id !== readerAnswer});
  }
});
// The frame loop runs only while audio plays; a pause, an end or a seek while paused paints once.
let raf = 0;
function frame() { raf = 0; highlight(); if (!audio.paused) raf = requestAnimationFrame(frame); }
function startHighlight() { if (!raf) raf = requestAnimationFrame(frame); }
function stopHighlight() { if (raf) cancelAnimationFrame(raf); raf = 0; highlight(); }
audio.addEventListener("ended", () => {
  if (!current) return;
  const e = view.entries.find(x => x.id === current.id) || current;
  syncStage(e, Infinity);
  const last = stopsOf(e).findIndex((c, i) => stopTime(e, c) === Infinity && !passed.has(e.id + ":" + i));
  if (last >= 0) stopAt(e, last);
  clearTimeout(restTimer);
  restTimer = setTimeout(() => { if (current && current.id === e.id && audio.ended) { restBoards(e); caption(null, 0); } }, REST_HOLD_MS);
});
// A pause left for a long time shows each board whole, as the end of an answer does; Play sends the whole picture again.
// Not at a stop: what comes after its question must not be shown before it is answered.
const REST_PAUSE_MS = 30000;
let pauseRestTimer = 0;
audio.addEventListener("pause", () => {
  clearTimeout(pauseRestTimer);
  if (!current || audio.ended) return;
  const e = current;
  pauseRestTimer = setTimeout(() => {
    if (current && current.id === e.id && audio.paused && !audio.ended && !stopped) { restBoards(e); cueSync = true; }
  }, REST_PAUSE_MS);
});
audio.addEventListener("play", () => clearTimeout(pauseRestTimer));
audio.addEventListener("seeking", () => { cueSync = true; if (current) markPassed(current, audio.currentTime); });
audio.addEventListener("play", () => {
  if (stopped) clearStop();
  if (answering) { answering = null; $("text").placeholder = tr("ph.talk"); }  // the say back was left
});
