// The page's one polite live region (#announcer): what happens while nobody watches the panel, said in short sentences.
const answerNumber = e => e && e.n ? e.n : (e && view.entries.filter(x => x.who === "claude" && x.id <= e.id).length) || 0;
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
function announceOnView(before) {
  if (before.v === -1) { for (const e of view.entries) if (e.who === "claude") announced.add(e.id); return; }
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

