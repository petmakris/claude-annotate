// ---- the floor: one call talks at a time ----------------------------------
// Pressing Talk, sending text or playing an answer takes the floor for this call. Every other call's
// page then pauses its voice and stops its recording, and this page does the same when another call
// takes it. Pages in this browser hear it at once on a BroadcastChannel; a page on another device
// hears it on its next poll. floorN is the count of floor changes this page has seen; floorEpoch
// counts the takes made here, so a poll that left before a take cannot undo it.
let floorN = 0, floorEpoch = 0, heardSent = null;
const floorChannel = "BroadcastChannel" in window ? new BroadcastChannel("talk-floor") : null;
let floorTakenAt = -Infinity;
const FLOOR_CROSS_MS = 2000;
function takeFloor(heard) {
  const epoch = ++floorEpoch;
  floorTakenAt = performance.now();
  if (floorChannel) floorChannel.postMessage({call: CFG.call});
  api("/api/floor", {method: "POST", body: JSON.stringify(heard == null ? {} : {heard}), headers: {"Content-Type": "application/json"}})
    .then(r => r.ok ? r.json() : null).then(b => { if (b && epoch === floorEpoch) { floorN = b.floor_n; if (wake) wake(); } }).catch(() => {});
}
function topicOf(id) { const c = (view.calls || []).find(x => x.id === id); return c ? c.topic : ""; }
function yieldFloor(id) {
  const busyHere = !audio.paused || !!recorder || listening();
  if (!audio.paused) audio.pause();
  if (recorder) { stopRecording(); setMode("idle"); }
  if (live) parkLive("floor");
  if (busyHere) { const t = topicOf(id); showError("Paused: you are talking in " + (t ? "“" + t + "”" : "another call") + "."); }
}
// Two calls that hear one voice claim the floor at once, and each hears the other's claim. Yielding to
// it here would leave neither listening; the server keeps the later claim, and the next poll yields.
if (floorChannel) floorChannel.onmessage = ev => {
  const id = ev.data && ev.data.call;
  if (id && id !== CFG.call && performance.now() - floorTakenAt > FLOOR_CROSS_MS) yieldFloor(id);
};
audio.addEventListener("play", () => {
  if (current && (current.id !== heardSent || view.floor_call !== CFG.call)) { heardSent = current.id; takeFloor(current.id); }
});

// The other calls open on this machine: a new answer in one shows as a dot on the pill's button.
function callState(c) {
  if (c.unheard) return c.unheard === 1 ? "new answer" : c.unheard + " new answers";
  if (c.ended) return "ended";
  if (c.working) return "working";
  return c.floor ? "talking now" : "open";
}
function paintCalls() {
  const list = view.calls || [], nav = $("calls");
  const sig = JSON.stringify(list.map(c => [c.id, c.topic, callState(c)]));
  if (nav.dataset.sig === sig) return;
  nav.dataset.sig = sig;
  const rows = list.map(c => {
    const a = document.createElement("a"); a.href = "/c/" + encodeURIComponent(c.id);
    a.className = "callrow" + (c.unheard ? " new" : "") + (c.ended ? " ended" : "");
    const dot = document.createElement("span"); dot.className = "live";
    const t = document.createElement("span"); t.className = "t"; t.textContent = c.topic;
    const s = document.createElement("span"); s.className = "s"; s.textContent = callState(c);
    a.title = c.topic + " · " + callState(c); a.append(dot, t, s); return a;
  });
  const all = document.createElement("a"); all.href = "/"; all.className = "callrow all"; all.textContent = "All calls";
  nav.replaceChildren(...rows, all);
}

// ---- the hooks this file owns (R) -----------------------------------------------
// The Calls button and its dot, painted from paintPill().
function paintCallsButton() {
  const calls = view.calls || [];
  $("callsbtn").hidden = !calls.length;
  $("callsdot").hidden = $("raildot").hidden = !calls.some(c => c.unheard);
}
registerPop("callsbtn", "pCalls");
// A new view arrived: `before` is the one it replaces. The tab's title and icon, the Next waiting target.
function callsOnView(before) {}
