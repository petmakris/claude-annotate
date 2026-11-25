// The call page: the stage beside a panel that holds the conversation, the player, the text field and
// the mic; the panel collapses to a rail; a gear holds the settings. talk.py serves it with window.CFG filled in for one call.
//
// The page is one program in several classic scripts that share one global scope, loaded in this order by call.html
// (and by skills/talk/tests/call_page.py, which reads the order from the HTML). Each file has one owner, a feature
// batch; the map, the hooks and the DOM are in the run's design notes and summed up here:
//   call.js         core, shared: CFG, $, store, api, fmt; popovers, the toast, the shared state, paintAll, the poll
//   call-calls.js   R: the floor and the other calls (callState, paintCalls, the Calls popover, the tab's title and icon)
//   call-wait.js    W: the foot's status line, the voice being made, sending text, Undo, the wait card, queued answers' Skip
//   call-player.js  shared: playing an answer (the claim, autoplay, the queue, load, playFrom, wordAt, togglePlay, jump)
//   call-stage.js   C: the stage bridge (messages, chips, following), the reader, stops, the board following the voice
//   call-shell.js   C: the conversation: the Now card, the list of earlier answers, search, the transport
//   call-return.js  R: the welcome-back card, the since-you-left divider, the state strip, the live region
//   call-input.js   I: settings, the theme, the panel, keys, the Type / Talk / Live switch, recording
//   call-live.js    I: live mode (the open microphone)
//   call-boot.js    core: starts the page
// A file declares its own state with let/const at its top, adds its markup to the slots call.html names, and reaches
// another file's part only through the hook functions listed under "hooks" in the design: a hook is an empty or tiny
// function in its owner's file, called from the place the event happens. Top-level statements run in file order, so a
// file never calls another file's function or reads its let/const while it loads: only inside functions and handlers.
const CFG = window.CFG;
const $ = id => document.getElementById(id);
const SPEEDS = [0.75, 0.85, 1, 1.25, 1.5];
const store = {get(k, d){ try { const v = localStorage.getItem("talk." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
               set(k, v){ try { localStorage.setItem("talk." + k, JSON.stringify(v)); } catch {} }};
const api = (path, opts = {}) => fetch(path, {...opts, headers: {"X-Talk-Token": CFG.token, ...(opts.headers || {})}});
const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

$("topic").textContent = CFG.topic; $("topic").title = CFG.topic; document.title = "Talk · " + CFG.topic;
const audio = $("audio");

// ---- popovers: one open at a time ---------------------------------------------
const POPS = {};
let openPop = null;
function showPop(pop) {
  const was = openPop;
  openPop = pop && openPop !== pop ? pop : null;
  for (const id of new Set(Object.values(POPS))) $(id).hidden = id !== openPop;
  for (const [btn, id] of Object.entries(POPS)) $(btn).setAttribute("aria-expanded", String(id === openPop));
  popChanged(openPop, was);
}
// A button that opens a layer: call-calls.js registers the Calls button, call-input.js the gear and the Keys button.
function registerPop(btn, id) { POPS[btn] = id; $(btn).onclick = ev => { ev.stopPropagation(); showPop(id); }; }
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && openPop) showPop(null); });
// A click anywhere else closes the open layer: the buttons that open layers stop their own click.
document.addEventListener("click", ev => {
  if (openPop && !ev.target.closest(".pop, .toast")) showPop(null);
});

// ---- the toast: an error for a while, or a lost connection until it is back ----
let errText = "", errTimer = null, connText = "", connDown = false;
let spoken = false;         // the text field holds words said with Talk: sent as spoken, not typed
let unsent = null;          // a recording the server did not take: kept, so the user never says it twice
function paintToast() {
  const text = connText || errText || (unsent ? "Your recording was not sent." : "");
  $("toast").hidden = !text; $("toasttext").textContent = text;
  const audioBad = audioFailed !== null;   // an entry id can be 0
  $("retry").hidden = !connDown && !unsent && !audioBad; $("retry").textContent = connDown || (!unsent && audioBad) ? "Retry" : "Send again";
}
let audioFailed = null;     // the answer whose audio file would not load: the toast offers Retry
function showError(text) {
  errText = text || ""; clearTimeout(errTimer);
  if (errText) errTimer = setTimeout(() => { errText = ""; audioFailed = null; paintToast(); }, 12000);
  paintToast();
}

// ---- state -------------------------------------------------------------
let view = {v: -1, entries: [], working: false, stalled: false, activity: [], ended: null, calls: [], floor_call: null, floor_n: 0};
let seen = null;            // ids of answers that existed when the page loaded: never auto-played
let current = null;         // the entry in the player
// A language the launch named wins; with none named, the one the user last picked on this origin.
let language = CFG.language && CFG.language !== "auto" ? CFG.language : store.get("language", "auto");
let speed = store.get("speed", 1);
let autoplay = store.get("autoplay", true);
let recorder = null;
let starting = false;       // the microphone is being asked for: a second press must not open a second one
let busy = false;           // the recording is being turned into text
let closed = false;         // the ended call was closed from here
let talkMode = store.get("talkMode", "manual") === "live" ? "live" : "manual";  // live: the microphone stays open
let barge = store.get("barge", "talk") === "keyword" ? "keyword" : "talk";    // how live speech interrupts an answer
let endPause = [800, 1200, 2000].includes(store.get("endPause", 1200)) ? store.get("endPause", 1200) : 1200;
let live = null;            // the open microphone of live mode, while it listens
let held = null;            // the answer the user's speech is over: ducked, paused, or waiting after a cue word
let deferred = null;        // a new answer that came while the user was talking: it plays once they are done
let liveNote = "";          // why live mode is not listening, when it stopped by itself
let liveFlash = null;       // a short-lived line: {text, until}
let screenMode = store.get("screen", "desk") === "tv" ? "tv" : "desk";  // tv: everything read from across the room
const TV_ZOOM = 1.35;
let undoable = null;        // {entry, until}: the live turn the Undo button can still take back
let fillerFor = null, turnSentAt = 0;  // "One moment." is said once per turn, when Claude takes a while
let clockSkew = 0;          // the server's clock less this page's, in seconds, from the last view that carried `now`
const serverNow = () => Date.now() / 1000 + clockSkew;  // the server's time now, in seconds: compare it with a server timestamp

function appState() {
  if (recorder || (live && live.speech)) return "listening";
  if (busy || (view.working && !view.ended)) return "working";
  if (current && !audio.paused) return "speaking";
  return "idle";
}
// The foot's and the rail's controls, each part painted by its owner: the mic and the text field (call-input.js), the
// player (call-shell.js), the Calls button (call-calls.js).
function paintPill() {
  const ended = !!view.ended;
  paintMic(); paintTransport(); paintCallsButton();
  $("live").classList.toggle("off", ended); $("raillive").classList.toggle("off", ended);
  paintNowLine(); paintJump();
}
function paintAll() {
  if (view.ended && live) { stopLive(); return; }  // stopLive paints again
  paintInfo(); paintPill(); paintSettings();
  $("app").dataset.state = appState(); $("app").toggleAttribute("data-ended", !!view.ended);
  $("app").toggleAttribute("data-live", listening());
  $("app").toggleAttribute("data-tv", screenMode === "tv");
  paintModeChip(); paintUndo();
  // The paint hooks, one per feature, each in its owner's file (empty until that batch fills it). Order: the card of the
  // current turn and what waits on it, then the list and the strips, then what is said for a screen reader.
  paintNowCard(); paintWait(); paintEarlier(); paintInputMode(); paintStateStrip(); paintWelcome(); paintAnnounce();
}

// ---- the connection ------------------------------------------------------
let fails = 0, failingSince = 0, wake = null, backUntil = 0, backTimer = null;
const BACK_MS = 4000;
async function pollOnce() {
  try {
    const epoch = floorEpoch;
    const r = await api("/api/state?v=" + view.v + "&page=" + PAGE_ID);
    if (r.status === 403 || r.status === 410) {
      if (!view.ended) { view = {...view, ended: "the talk server no longer holds this call", working: false}; render(); }
      return true;
    }
    if (!r.ok) return false;
    const body = await r.json();
    if (!body.same) {
      const before = view;
      view = body;
      seeHolder(body.player);
      if (view.now) clockSkew = view.now - Date.now() / 1000;
      // A floor taken here after this poll left is newer than what it brought back.
      if (epoch === floorEpoch && view.floor_n > floorN) {
        floorN = view.floor_n;
        if (view.floor_call && view.floor_call !== CFG.call) yieldFloor(view.floor_call);
      }
      if (seen === null) seen = new Set(view.entries.filter(e => e.who === "claude").map(e => e.id));
      let n = 0; for (const e of view.entries) if (e.who === "claude") e.n = ++n;
      if (current) current = view.entries.find(e => e.id === current.id) || current;
      // A new view arrived (`before` is the one it replaces): each owner reads what changed, before anything is painted.
      waitOnView(before); callsOnView(before); returnOnView(before); shellOnView(before);
      maybeAutoplay();
      showFailedAnswer();
      render();
    }
    return true;
  } catch (err) { return false; }
}
function paintConn() {
  // An ended call says so under the stage; its server going away is expected then.
  connDown = fails >= 2 && !view.ended;
  connText = connDown ? (Date.now() - failingSince > 30000 ? "The call server is not answering. Still trying…" : "Reconnecting to the call…")
    : Date.now() < backUntil && !view.ended ? "Reconnected." : "";
  paintToast();
}
async function poll() {
  for (;;) {
    const ok = await pollOnce();
    if (ok && fails >= 2) {
      backUntil = Date.now() + BACK_MS; clearTimeout(backTimer); backTimer = setTimeout(paintConn, BACK_MS + 50);
    }
    if (ok) { fails = 0; failingSince = 0; } else { fails += 1; failingSince = failingSince || Date.now(); }
    paintConn();
    const delay = ok ? 800 : [1000, 2000, 5000][Math.min(fails, 3) - 1];
    await new Promise(r => { wake = r; setTimeout(r, delay); });
    wake = null;
  }
}
// A tab out of sight keeps polling (the loop never checks): a call that ended meanwhile is found, and the tab
// polls at once when it is seen again, since a browser slows the timers of a hidden tab.
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && wake) wake(); });
$("retry").onclick = () => { if (connDown) { if (wake) wake(); } else if (unsent) sendWav(unsent); else if (audioFailed !== null) retryAudio(); };

