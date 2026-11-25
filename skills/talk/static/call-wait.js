// The foot's line: what Claude is doing, the voice being made, Undo; the rail's line: the sentence being said.
function paintInfo() {
  const s = statusText(), e = shownAnswer();
  $("status").hidden = !s;
  if (s) { $("status").textContent = s.text; $("status").className = "status" + (s.shimmer ? " shimmer" : "") + (s.warn ? " warn" : ""); }
  paintPrep(recorder ? null : e);
  $("wave").hidden = !recorder;
}
// The line under the stage while there is no answer to read: the first that applies.
function statusText() {
  if (recorder) return null;
  if (live && live.speech) return {text: "Hearing you…"};
  if (live && live.suspended) return {text: "Click anywhere to start listening.", warn: true};
  if (live && live.parked) return {text: live.parked === "floor" ? "Listening in another call. Press the mic to listen here."
    : "Listening on another screen. Press the mic to listen here."};
  if (held && held.armed && !busy) return {text: "Listening. Go ahead."};
  if (queued) return {text: "Next answer ready: it plays when this one ends."};
  if (elsewhere && audio.paused && current) return {text: "Playing on another screen."};
  if (liveFlash && Date.now() < liveFlash.until && !busy) return {text: liveFlash.text};
  if (busy) return {text: "Turning your words into text…", shimmer: true};
  if (view.ended) return {text: closed ? "Closed. You can close this tab." : "The call has ended: " + view.ended + ". Answers can still be replayed."};
  if (view.stalled) return {text: "Claude has not picked this up yet. Check the terminal: the session may be waiting for a permission.", warn: true};
  if (view.working) {
    const run = view.activity.filter(a => a.state === "running").pop();
    return {text: run ? run.label + " · " + Math.round(run.seconds) + "s" : "Claude is working…", shimmer: true};
  }
  // Whether live mode listens shows on the corner chip, the mic and the frame's edge; the card only says
  // why it stopped when it stopped by itself (asleep, the microphone lost).
  if (talkMode === "live" && !live && liveNote) return {text: liveNote};
  return null;
}
// ---- the audio being made -----------------------------------------------
// An answer is read aloud in one piece, so it plays without a pause between sentences. Until its
// audio is ready, a bar in the panel's foot fills toward the server's estimate of how long it takes,
// and holds short of the end until the audio is there.
let prepTimer = 0;
function prepShare(e) {
  if (e.speech !== "making" || !e.speech_started || !e.speech_estimate) return 0;
  const f = (Date.now() / 1000 + clockSkew - e.speech_started) / e.speech_estimate;
  return f < 0.9 ? Math.max(0, f) : 0.9 + 0.08 * (1 - Math.exp(-(f - 0.9) * 2));
}
function paintPrep(e) {
  const on = !!e && (e.speech === "pending" || e.speech === "making");
  $("prep").hidden = !on;
  if (on) {
    const share = prepShare(e), left = e.speech === "making" ? e.speech_estimate * (1 - share / 0.98) : 0;
    $("prepfill").style.width = (100 * share).toFixed(1) + "%";
    $("prepfill").parentElement.classList.toggle("queued", e.speech === "pending");
    $("preplbl").textContent = e.speech === "pending" ? "Waiting for the voice…"
      : share < 0.9 && left >= 1.5 ? "Preparing the voice · about " + Math.ceil(left) + " s" : "Preparing the voice · almost ready";
  }
  if (on && !prepTimer) prepTimer = setInterval(() => paintPrep(shownAnswer()), 200);
  else if (!on && prepTimer) { clearInterval(prepTimer); prepTimer = 0; }
}

// What was said joins anything already typed, and the field takes the keys so Enter sends it.
// Ask about this, on a scene part: the voice pauses and the question starts in the text field, for the reader to
// finish and send. Nothing goes until they press Send.
function askAbout(text) {
  if (!text) return;
  if (!audio.paused) audio.pause();
  const t = $("text"); t.value = text; spoken = false;
  fitText(); t.focus(); t.selectionStart = t.selectionEnd = t.value.length;
}
function writeOut(text) {
  const t = $("text"), before = t.value.trimEnd();
  t.value = before ? before + " " + text : text;
  spoken = true;
  fitText(); t.focus(); t.selectionStart = t.selectionEnd = t.value.length;
}

async function sendText() {
  const text = $("text").value.trim(); if (!text) return;
  $("sendtext").disabled = true;
  takeFloor(null);
  try {
    const body0 = spoken ? {text, spoken} : {text};
    if (answering) body0.answering = answering;
    const resp = await api("/api/say", {method: "POST", body: JSON.stringify(body0), headers: {"Content-Type": "application/json"}});
    const body = await resp.json().catch(() => ({}));
    // What you send moves the call on: the answer still playing stops, so the reply plays when it comes,
    // as it does when you press Talk.
    if (resp.ok) {
      turnSent({via: spoken ? "spoken" : "typed", text, entry: body.entry ? body.entry.id : null});
      $("text").value = ""; spoken = false; fitText(); release(); if (!audio.paused) audio.pause(); view.v = -1;
      if (answering) { answering = null; $("text").placeholder = "Type, or press the mic"; clearStop(); }
    }
    else showError(body.error || "Sending failed: HTTP " + resp.status);
  } catch (err) { showError("Sending failed: " + err.message); }
  $("sendtext").disabled = !$("text").value.trim();
}
// The text field grows with what is typed, up to a few lines, and Send waits for something to send.
function fitText() {
  const t = $("text"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px";
  if (!t.value.trim()) spoken = false;
  $("sendtext").disabled = !t.value.trim();
}
$("text").addEventListener("input", fitText);
$("text").placeholder = "Type, or press the mic";
$("undo").onclick = async () => {
  const u = undoable; undoable = null; paintAll();
  if (!u) return;
  try {
    const r = await api("/api/withdraw", {method: "POST", body: JSON.stringify({entry: u.entry}), headers: {"Content-Type": "application/json"}});
    const b = await r.json().catch(() => ({}));
    flash(b.withdrawn ? "Taken back." : "Too late: Claude already has it.");
    view.v = -1; if (wake) wake();
  } catch { showError("Undo failed: the call server did not answer."); }
};
// "One moment.": once per live turn, when Claude has worked a few seconds and nothing is playing.
const fillerAudio = new Audio();
setInterval(() => {
  if (talkMode !== "live" || !view.filler || !turnSentAt || fillerFor === turnSentAt) return;
  if (!view.working || Date.now() - turnSentAt < 3000 || !audio.paused || userBusy()) return;
  fillerFor = turnSentAt;
  fillerAudio.src = audioUrl(view.filler); fillerAudio.volume = 0.8; fillerAudio.play().catch(() => {});
}, 500);
$("sendtext").onclick = sendText;
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendText(); } });

// ---- the hooks this file owns (W) -----------------------------------------------
// The Undo button of a live turn, from paintAll().
function paintUndo() {
  const canUndo = !!undoable && Date.now() < undoable.until && !view.ended;
  $("undo").hidden = !canUndo;
}
// The wait card (#waitcard in the Now card), the note under the field (#sendnote) and the queued answer's row (#queuerow),
// from paintAll(). waitActive() is true while a turn of this call is in flight (sent, collected, not answered), so the
// Now card stays up for it; the wait card shows, and the card's answer part hides, while it is.
function paintWait() {}
function waitActive() { return false; }
// A new view arrived: `before` is the one it replaces. Where W sees a new turn, an answer, a stall or a correction.
function waitOnView(before) {}
// A turn was sent from this page: info is {via: "typed" | "spoken" | "live", text, entry: the new entry's id or null}. Called
// by sendText() here and by sendLive() in call-live.js, at the moment the server took the turn.
function turnSent(info) {}
