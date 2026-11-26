// ---- the player --------------------------------------------------------
function audioUrl(path) { return location.pathname.replace(/\/$/, "") + "/" + path; }
function setSrc(path) { const url = audioUrl(path); if (audio.dataset.src !== url) { audio.src = url; audio.dataset.src = url; } }
// Why a play() was refused: only a NotAllowedError is the browser blocking playback; a pause before playback
// starts (AbortError) is nothing; anything else is the file or the player, and says so.
function playFailed(err) {
  const name = err && err.name;
  if (name === "AbortError") return;
  if (name === "NotAllowedError") showError(tr("pl.blocked"));
  else if (name === "NotSupportedError") { audioFailed = current ? current.id : null; showError(tr("pl.unsupported")); }
  else showError(err && err.message ? tr("pl.failed.why", {why: err.message}) : tr("pl.failed"));
}
// The audio element could not load its file (gone, damaged, the connection dropped): said so, with Retry.
audio.addEventListener("error", () => {
  if (!current || !audio.dataset.src) return;
  const code = audio.error && audio.error.code;
  audioFailed = current.id;
  showError(code === 2 ? tr("pl.load.net") : code === 3 ? tr("pl.load.bad")
    : code === 4 ? tr("pl.load.missing") : tr("pl.load"));
});
audio.addEventListener("loadeddata", () => { if (audioFailed !== null) { audioFailed = null; showError(""); } });
function retryAudio() {
  const e = current; audioFailed = null; showError("");
  if (!e) return;
  const at = audio.currentTime || 0;
  audio.src = audioUrl(e.audio); audio.dataset.src = audioUrl(e.audio);
  if (audio.load) audio.load();
  if (at) audio.currentTime = at;
  audio.playbackRate = speed;
  audio.play().catch(playFailed);
}
function load(e, play) {
  current = e; cueSync = true;
  if (queued && queued.id === e.id) queued = null;
  setSrc(e.audio);
  audio.playbackRate = speed; audio.preservesPitch = true;
  // A pause before playback starts (another call took the floor) rejects with AbortError: not a block.
  if (play) audio.play().catch(playFailed);
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({title: tr("s.answer", {n: e.n || ""}), artist: "Claude", album: CFG.topic});
  paintAll();
}
// One page of a call speaks. Two pages of one call (a laptop and the TV) would otherwise both start each
// answer. The server holds the claim: POST /api/player {page, take} names the page that plays, /api/state
// carries it as `player`, and this page plays only when `player` is its own id. A page that opens claims
// it when nobody holds it; one where the user presses play takes it (the other pauses at its next poll).
// When the claim cannot be made (an older server, the request failed) the page falls back to a lock in
// this origin's storage, renewed while it plays: pages on other devices do not share it.
const PAGE_ID = Math.random().toString(36).slice(2, 10);  // this page among the call's pages (live mode too)
const LOCK_KEY = "playing." + CFG.call, LOCK_MS = 3000;
let claimOk = false;        // the server answered a claim: its holder is the truth, the storage lock is not used
let holder = null;          // the page the server says plays: an id, or null when none
let tookAt = 0;             // when this page last took the claim: a poll older than that cannot say otherwise
async function claimPlayer(take) {
  const sent = Date.now();
  try {
    const r = await api("/api/player", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({page: PAGE_ID, take: !!take})});
    if (!r.ok) throw new Error("HTTP " + r.status);
    const b = await r.json();
    if (b && (b.player === null || typeof b.player === "string")) { claimOk = true; holder = b.player; if (take) tookAt = sent; return; }
  } catch (err) { /* the lock below stays the fallback */ }
  claimOk = false;
}
function takeVoice() { if (claimOk) { holder = PAGE_ID; tookAt = Date.now(); } claimPlayer(true); }
// A poll's `player`: another page took the voice, so this page stops playing and says so.
function seeHolder(p) {
  if (!claimOk || p === undefined || Date.now() - tookAt < 3000) return;
  holder = p;
  if (p === null) { claimPlayer(false); return; }
  if (p !== PAGE_ID && !audio.paused) { elsewhere = true; audio.pause(); paintAll(); }
}
function playingElsewhere() {
  if (claimOk) return holder !== null && holder !== PAGE_ID;
  const l = store.get(LOCK_KEY, null);
  return !!l && l.id !== PAGE_ID && Date.now() - l.at < LOCK_MS;
}
function holdPlayLock() { store.set(LOCK_KEY, {id: PAGE_ID, at: Date.now()}); }
function dropPlayLock() { const l = store.get(LOCK_KEY, null); if (l && l.id === PAGE_ID) store.set(LOCK_KEY, null); }
setInterval(() => { if (!audio.paused && !audio.ended) holdPlayLock(); }, 1000);
audio.addEventListener("play", () => { elsewhere = false; holdPlayLock(); });
for (const ev of ["pause", "ended"]) audio.addEventListener(ev, dropPlayLock);
let elsewhere = false;      // a new answer was not played here: another page of this call holds the voice
let queued = null;          // a new answer that came while another played: it starts when that one ends
function startQueued() {
  if (!queued || stopped) return;   // an answer waiting at a question keeps the next one waiting
  const e = view.entries.find(x => x.id === queued.id) || queued; queued = null;
  const at = view.entries.findIndex(x => x.id === e.id);
  if (at < 0 || e.superseded || view.entries.slice(at + 1).some(x => x.who === "you" && !x.withdrawn)) { paintAll(); return; }
  if (userBusy() || recorder || !autoplay) { paintAll(); return; }
  if (playingElsewhere()) { elsewhere = true; load(e, false); paintAll(); return; }
  load(e, true); paintAll();
}
audio.addEventListener("ended", () => { setTimeout(startQueued, 0); });
function maybeAutoplay() {
  const fresh = view.entries.filter(e => e.who === "claude" && e.speech === "ready" && !seen.has(e.id));
  if (!fresh.length) return;
  for (const e of fresh) seen.add(e.id);
  // An answer to a question the user has since replaced or added to is kept unspoken (the server never read it aloud): it
  // plays only when the reader asks for it (playAnyway), never by itself and never into the queue.
  const asked = fresh.find(e => e.superseded && e.id === playAnywayId);
  if (asked) { playAnywayId = null; readerPlays(asked); takeVoice(); load(asked, true); return; }
  const last = fresh.filter(e => !e.superseded).pop();
  if (!last) return;
  // An answer the user has already spoken or typed past (its voice was still being made) never starts by
  // itself: it would play the old board after they moved on, and hold the player from the newer answer.
  const at = view.entries.findIndex(e => e.id === last.id);
  if (view.entries.slice(at + 1).some(e => e.who === "you" && !e.withdrawn)) return;
  // Only the call the user is talking in reads new answers aloud; another call's wait, marked new.
  const mine = !view.floor_call || view.floor_call === CFG.call;
  if (userBusy()) { if (mine && autoplay) deferred = last; return; }  // played once they are done (settle)
  // An answer that comes while another plays waits its turn: it is announced in the foot and starts at the end.
  if (current && !audio.paused && !audio.ended) { if (mine && autoplay) queued = last; return; }
  // A tab out of sight never starts talking: the answer waits in the player and plays when the tab is back.
  const away = document.visibilityState === "hidden";
  const other = mine && autoplay && !recorder && playingElsewhere();
  elsewhere = other;
  hiddenHeld = away && autoplay && !recorder && mine && !other ? last.id : null;
  load(last, autoplay && !recorder && mine && !away && !other);
}
let hiddenHeld = null;      // the id of a new answer that came while the tab was hidden: it plays when the tab is seen
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || hiddenHeld === null) return;
  const id = hiddenHeld; hiddenHeld = null;
  if (current && current.id === id && audio.paused && !audio.ended && audio.currentTime === 0 && !userBusy() && !recorder) {
    audio.play().catch(() => {});
  }
});
// ---- the word being said ------------------------------------------------
function playFrom(e, t, board = false) {
  // Play the answer from time `t` seconds in. `board`: it plays the board in front, so the stage follows again.
  e = view.entries.find(x => x.id === e.id) || e;
  if (e.speech !== "ready") return;
  readerPlays(e);
  if (board) followAgain();
  load(e, false); audio.currentTime = t;
  audio.playbackRate = speed; takeVoice(); audio.play().catch(playFailed);
}
function wordAt(e, t) {
  // The last word that has started by time t, or -1.
  let lo = 0, hi = e.words.length - 1, k = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (e.words[m][2] <= t) { k = m; lo = m + 1; } else hi = m - 1; }
  return k;
}
function skip(by) { audio.currentTime = Math.min(Math.max(0, audio.currentTime + by), audio.duration || 0); paintPill(); }
// Play plays the answer the card shows. Only when the reader pinned the stage by hand (following off) does Play
// play the board in front instead: when the voice is not on that board (it came from an earlier answer, or this
// answer has moved past it), Play plays the board's explanation, from the sentence it came in with, and the board
// unfolds again, and the Play button says "Play answer N" in a word. A board no answer explains (a page, the key
// points) leaves Play as it is.
function boardStart() {
  if (!frontBoard || (!audio.paused && !audio.ended)) return null;
  const n = boardAnswer.get(frontBoard);
  const e = n ? view.entries.find(x => x.who === "claude" && x.n === n) : null;
  if (!e || e.speech !== "ready" || !e.words || !e.words.length) return null;
  const cue = (e.cues || []).find(c => c.view === frontBoard);
  if (!cue) return null;
  const onIt = current && current.id === e.id && !audio.ended && stateAt(e, wordCharAt(e, audio.currentTime)).front === frontBoard;
  if (onIt) return null;
  const w = e.words.find(w => w[0] >= cue.at) || e.words[e.words.length - 1];
  return {e, t: cue.at === 0 ? 0 : w[2]};
}
function wordCharAt(e, t) { const k = wordAt(e, t); return k < 0 ? -1 : e.words[k][0]; }
function togglePlay() {
  release();
  if (stopped && audio.paused) { if (stopped.stop.type === "deeper" || stopped.stop.type === "check") pickStop(0); else goOn(); return; }
  const b = follow ? null : boardStart();
  if (b) { playFrom(b.e, b.t, true); return; }
  if (!current) { const e = lastAnswer(); if (e) { readerPlays(e); takeVoice(); load(e, true); } return; }
  if (audio.paused) { readerPlays(current); takeVoice(); audio.play().catch(playFailed); } else audio.pause();
}
// ---- the keyboard: Space pauses and plays, ← and → move by a sentence ------------------
// An answer's sentence starts, in seconds: its first word and every word after one that ends a sentence.
function sentenceTimes(e) {
  if (!e.words || !e.words.length) return null;
  return sentenceRuns(e).map(([f]) => e.words[f][2]);
}
const AGAIN_S = 1.0;   // ← this soon after a sentence starts goes to the one before, as a player's previous track does
const SKIP_S = 5;      // an answer with no word timings moves by this much instead
function jump(dir) {
  if (!current) return;
  const e = view.entries.find(x => x.id === current.id) || current, t = audio.currentTime || 0;
  const starts = sentenceTimes(e);
  if (!starts) { skip(dir * SKIP_S); return; }
  let to;
  if (dir < 0) {
    const i = starts.findLastIndex(s => s <= t + 0.05);
    to = i < 0 ? 0 : i > 0 && t - starts[i] < AGAIN_S * (audio.playbackRate || 1) ? starts[i - 1] : starts[i];
  } else to = starts.find(s => s > t + 0.05) ?? (audio.duration || t);
  cueSync = true;
  audio.currentTime = to; paintPill();
  if (audio.paused) highlight();
}
