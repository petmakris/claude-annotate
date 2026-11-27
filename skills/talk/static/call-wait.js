// ---- the line above the field, and the wait for an answer ------------------------------------
// One quiet line (#note) says the one thing worth saying now: what just happened to a send, why a recording gave no words,
// why the voice or the open microphone is not on, that the call ended. From Send until the answer lands, the end of the
// conversation shows Claude thinking (#thinking): three dots, the step in a few words, a clock, and one way out.
let noteNow = null;         // {text, warn, until}: what just happened, for a few seconds
function noteSend(text, tone, fades) { noteNow = {text, warn: tone === "warn", until: Date.now() + 7000}; paintNote(); setTimeout(paintNote, 7100); }
function showMicNote(text) { micNote = text || ""; paintNote(); if (text) announce(text); }
let micNote = "";           // why the last recording gave no words, until the next press or the next words typed
// What the line says: the first that applies.
function noteText() {
  if (recorder) return null;
  if (noteNow && Date.now() < noteNow.until) return noteNow;
  if (micNote) return {text: micNote, warn: true};
  if (live && live.speech) return {text: tr("w.hearing")};
  if (live && live.suspended) return {text: tr("w.suspended"), warn: true};
  if (live && live.noSignal && !live.muted) return {text: tr("turn.nosound"), warn: true};
  if (live && live.parked) return {text: live.parked === "floor" ? tr("w.parked.floor") : tr("w.parked.screen")};
  if (held && held.armed && !busy) return {text: tr("w.listening")};
  if (liveFlash && Date.now() < liveFlash.until && !busy) return {text: liveFlash.text};
  if (busy) return {text: tr("w.busy")};
  if (view.ended) return {text: closed ? tr("w.closed") : tr("w.ended", {why: view.ended})};
  if (floorNote) return {text: floorWords(floorNote)};
  if (elsewhere && audio.paused && current) return {text: tr("w.elsewhere")};
  if (talkMode === "live" && !live && liveNote) return {text: liveNote, warn: true};
  return null;
}
function paintNote() {
  const n = noteText(), el = $("note");
  el.hidden = !n;
  if (!n) return;
  if (el.textContent !== n.text) el.textContent = n.text;
  el.classList.toggle("warn", !!n.warn);
  $("wave").hidden = !recorder;
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

// `replace`: the draft is a correction, so the question in flight is set aside (the server takes it back or marks it
// replaced, and the answer to it is shown but never read aloud) instead of the draft being added to it.
let sendingText = false;   // a send is on its way: Enter pressed twice must not send the words twice
async function sendText(replace = false) {
  const text = $("text").value.trim(); if (!text || sendingText) return;
  if (!replace && typedCommand(text)) return;   // I: "slower" and the like move the voice, they are not a question
  sendingText = true;
  $("sendtext").disabled = true;
  takeFloor(null);
  const target = replace === true ? inflight()[0] : null;
  try {
    const body0 = spoken ? {text, spoken} : {text};
    if (answering) body0.answering = answering;
    if (target) body0.replaces = target.id;
    const resp = await api("/api/say", {method: "POST", body: JSON.stringify(body0), headers: {"Content-Type": "application/json"}});
    const body = await resp.json().catch(() => ({}));
    // What you send moves the call on: the answer still playing stops, so the reply plays when it comes,
    // as it does when you press Talk.
    if (resp.ok) {
      turnSent({via: spoken ? "spoken" : "typed", text, entry: body.entry ? body.entry.id : null});
      if (target) noteSend(body.replaced === false ? tr("w.sent.old") : tr("w.replaced"), "", true);
      showMicNote("");   // the note about the last recording is old news once a typed message went through
      $("text").value = ""; spoken = false; fitText(); release(); if (!audio.paused) audio.pause(); view.v = -1;
      if (answering) { answering = null; $("text").placeholder = tr("ph.talk"); clearStop(); }
      if (wake) wake();
    }
    else { showError(body.error || tr("w.fail.http", {code: resp.status})); noteSend(tr("w.notsent"), "warn"); }
  } catch (err) { showError(tr("w.fail", {why: err.message})); noteSend(tr("w.notsent"), "warn"); }
  sendingText = false;
  $("sendtext").disabled = !$("text").value.trim();
}
// The text field grows with what is typed, up to a few lines, and Send waits for something to send.
function fitText() {
  const t = $("text"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px";
  if (!t.value.trim()) spoken = false;
  $("sendtext").disabled = !t.value.trim();
  saveDraft();
  paintMic();
}
// The words typed and not sent are kept for this call in the tab's session storage, so a reload brings them back; a send, the
// end of the call and an empty field clear them. Never put back over a say-back question's placeholder.
const DRAFT_KEY = "talk.draft." + CFG.call;
function saveDraft() {
  try { const v = $("text").value; if (v.trim() && !view.ended) sessionStorage.setItem(DRAFT_KEY, v); else sessionStorage.removeItem(DRAFT_KEY); } catch {}
}
function clearDraft() { try { sessionStorage.removeItem(DRAFT_KEY); } catch {} }
function restoreDraft() {
  let kept = null; try { kept = sessionStorage.getItem(DRAFT_KEY); } catch {}
  const t = $("text");
  if (!kept || t.value || answering || view.ended) return;
  t.value = kept; fitText();
}
$("text").addEventListener("input", fitText);
$("text").addEventListener("input", () => { if (micNote) showMicNote(""); });   // typing is the answer to "Nothing was heard": the note goes
$("text").placeholder = tr("ph.talk");
// "One moment.": once per live turn, when Claude has worked a few seconds and nothing is playing.
const fillerAudio = new Audio();
setInterval(() => {
  if (talkMode !== "live" || !view.filler || !turnSentAt || fillerFor === turnSentAt) return;
  if (!view.working || Date.now() - turnSentAt < 3000 || !audio.paused || userBusy()) return;
  fillerFor = turnSentAt;
  fillerAudio.src = audioUrl(view.filler); fillerAudio.volume = 0.8; fillerAudio.play().catch(() => {});
}, 500);
$("sendtext").onclick = () => sendText();
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); sendText(); } });


// The questions in flight: [{id, state: "sent" | "picked", entry}], oldest first. An older server sends no `view.turn`:
// then the newest question nothing has answered yet stands for it.
function inflight() {
  if (view.ended) return [];
  const t = view.turn;
  if (t && Array.isArray(t.entries)) {
    return t.entries.map(x => ({id: x.id, state: x.state, entry: view.entries.find(e => e.id === x.id)})).filter(x => x.entry);
  }
  const you = [...view.entries].reverse().find(e => e.who === "you" && !e.withdrawn);
  const answered = you && view.entries.some(e => e.who === "claude" && e.id > you.id);
  return you && !answered && (view.working || view.stalled) ? [{id: you.id, state: view.working ? "picked" : "sent", entry: you}] : [];
}
// One number for a step's seconds: 8s, 1:12.
const stepClock = s => s < 60 ? Math.round(s) + "s" : fmt(s);
// A question the card's Send again made: the new entry names (`replaces`) the oldest question it set aside, and its text is
// the words of everything set aside, in order, joined as one. Read from the entries, so a reload keeps it: {tries: how many
// times it was sent again, count: how many questions the last send held, first: the question first sent}. null for any
// other entry (a correction typed in the box has other words).
function resendOf(e) {
  let cur = e, tries = 0;
  const held = x => { const r = resendSet(x); return r ? r.set.reduce((n, y) => n + held(y), 0) : 1; };   // the questions a sent-again entry holds
  while (cur) { const r = resendSet(cur); if (!r) break; tries++; cur = r.from; }
  return tries ? {tries, count: held(e), first: cur} : null;
}
// The questions an entry holds, one text each: a sent-again entry holds the ones it set aside, so the card still shows each.
function heldTexts(e) { const r = resendSet(e); return r ? r.set.flatMap(heldTexts) : [e.text]; }
// The entries a sent-again entry set aside (and the oldest of them), or null when it is no resend.
function resendSet(e) {
  if (!e || typeof e.replaces !== "number") return null;
  const from = view.entries.find(x => x.id === e.replaces); if (!from) return null;
  const set = view.entries.filter(x => x.who === "you" && x.superseded && x.id >= from.id && x.id < e.id);
  return set.length && set.map(x => x.text).join("\n") === e.text ? {from, set} : null;
}
// Take back (not collected) or Cancel (collected): the server takes each question back or cancels the turn and tells the
// session. `ids` are the questions the card shows that this acts on: Take back names every one nobody has collected (the
// server takes back one entry for each call), Cancel names the collected turn (the server cancels all of it). The words
// go back into the box, in the order they were sent, so nothing said is lost; the note says how many came back.
async function cancelTurn(ids) {
  const fl = inflight().filter(x => ids.includes(x.id)); if (!fl.length) return;
  const back = [], got = [];
  let how = "withdrawn", questions = 0;   // `questions`: how many put back (a sent-again entry holds several)
  try {
    for (const f of fl) {
      if (got.includes(f.id)) continue;   // a collected turn's cancel took this one with it
      const r = await api("/api/cancel", {method: "POST", body: JSON.stringify({entry: f.id}), headers: {"Content-Type": "application/json"}});
      const b = await r.json().catch(() => ({}));
      if (!b.cancelled) continue;
      if (b.how === "cancelled") how = "cancelled";
      for (const id of (b.entries || [f.id])) {
        if (got.includes(id)) continue;
        const e = view.entries.find(x => x.id === id) || f.entry;
        got.push(id); back.push(e.text); questions += heldTexts(e).length;
      }
    }
    const words = back.filter(Boolean).join("\n");
    if (got.length) {
      const t = $("text");
      t.value = t.value.trim() ? words + "\n" + t.value : words; spoken = false; fitText();
      if (matchMedia("(hover: hover)").matches) t.focus();
      t.scrollTop = 0;   // the caret is at the end of the words; the box shows them from the first line
    }
    if (!got.length) noteSend(tr("w.late"), "warn");
    else if (got.length < fl.length) noteSend(tr("w.back.some", {n: got.length, m: fl.length}), "warn");
    else if (questions > 1) noteSend(tr(how === "cancelled" ? "w.cancelled.many" : "w.tookback.many", {n: questions}));
    else noteSend(tr(how === "cancelled" ? "w.cancelled.one" : "w.tookback.one"));
    view.v = -1; if (wake) wake();
  } catch { showError(tr("w.back.fail")); }
}
// Send the question again as a new one that replaces the first: the server takes the first back, or marks it replaced if
// the session has it, so only one is answered. The draft in the box is left alone.
async function sendAgain() {
  const m = waitModel(); if (!m) return;
  try {
    const r = await api("/api/say", {method: "POST", body: JSON.stringify({text: m.text, replaces: m.fl[0].id}), headers: {"Content-Type": "application/json"}});
    const b = await r.json().catch(() => ({}));
    if (!r.ok) { showError(b.error || tr("w.fail.http", {code: r.status})); return; }
    turnSent({via: "typed", text: m.text, entry: b.entry ? b.entry.id : null});
    noteSend(b.replaced === false ? tr("w.sent.first") : tr("w.sent.again"), "", true);
    view.v = -1; if (wake) wake();
  } catch (err) { showError(tr("w.fail", {why: err.message})); }
}
// "Play anyway": a replaced answer is kept unspoken. The reader asks for it: its voice is made (the server's /api/speak) and
// it plays as a reader's own play, like any other.
async function playAnyway(entry) {
  const e = view.entries.find(x => x.id === entry.id) || entry;
  if (e.speech === "ready") { readerPlays(e); takeVoice(); load(e, true); return; }
  playAnywayId = e.id;
  try {
    const r = await api("/api/speak", {method: "POST", body: JSON.stringify({entry: e.id}), headers: {"Content-Type": "application/json"}});
    if (!r.ok) { playAnywayId = null; const b = await r.json().catch(() => ({})); showError(b.error || tr("w.speak.fail")); }
    else { view.v = -1; if (wake) wake(); }
  } catch { playAnywayId = null; showError(tr("w.speak.fail.srv")); }
}


// ---- Claude thinking -----------------------------------------------------------------
// What stands where comes from the server: `view.turn.entries` lists the questions in flight, each "sent" (no doorbell has
// collected it) or "picked" (the session has it); `view.stalled` says nothing has moved for too long. The clock counts from
// the first send, by the server's time, so a reload keeps it.
const SLOW_AFTER = 90;       // seconds after the question: "Taking longer than usual"
let waitTick = 0, waitSig = "", waitSaid = null;
function waitModel() {
  const fl = inflight(); if (!fl.length) return null;
  const picked = fl.some(x => x.state === "picked"), again = resendOf(fl[0].entry);
  const sentAt = again ? again.first.at : fl[0].entry.at, elapsed = Math.max(0, serverNow() - sentAt);
  const step = !picked ? (view.stalled ? "notpicked" : "sent") : view.stalled ? "silent" : elapsed >= SLOW_AFTER ? "slow" : "working";
  const run = (view.activity || []).filter(a => a.state === "running").pop();
  return {fl, picked, step, elapsed, run, text: fl.map(x => x.entry.text).join("\n")};
}
const WAIT_TITLE = {sent: "w.title.sent", notpicked: "w.title.notpicked", working: "w.title.working", slow: "w.title.slow", silent: "w.title.silent"};
const waitTitle = step => tr(WAIT_TITLE[step]);
// The one way out of each step: Send again when nothing moves, else Cancel (the words go back into the field).
function waitAction(m) {
  if (m.step === "notpicked" || m.step === "silent") return [tr("w.again"), sendAgain];
  const unpicked = m.fl.filter(x => x.state === "sent").map(x => x.id), collected = m.fl.find(x => x.state === "picked");
  return [tr("w.cancel"), () => cancelTurn(collected ? [collected.id] : unpicked)];
}
function paintWait() {
  const m = waitModel(), box = $("thinking");
  if (m && !waitTick) waitTick = setInterval(paintWait, 1000);
  else if (!m && waitTick) { clearInterval(waitTick); waitTick = 0; }
  if (!m) { if (!box.hidden) { box.hidden = true; box.replaceChildren(); waitSig = ""; waitSaid = null; } return; }
  const warn = !["sent", "working"].includes(m.step);
  const words = m.run && !warn ? m.run.label : waitTitle(m.step);
  const sig = [uiLang, m.step, words].join("§");
  if (sig !== waitSig || box.hidden) {
    const first = box.hidden;
    waitSig = sig;
    box.className = "thinking" + (warn ? " warn" : "");
    const dots = document.createElement("span"); dots.className = "dots"; dots.setAttribute("aria-hidden", "true"); dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    const what = document.createElement("span"); what.className = "what"; what.textContent = words;
    const clock = document.createElement("span"); clock.className = "clock"; clock.setAttribute("aria-hidden", "true");
    const [label, fn] = waitAction(m), act = document.createElement("button"); act.type = "button"; act.className = "more"; act.textContent = label; act.onclick = fn;
    box.replaceChildren(dots, what, clock, act);
    box.hidden = false;
    if (first) { convoFollow = true; requestAnimationFrame(toBottom); }
  }
  box.querySelector(".clock").textContent = fmt(m.elapsed);
  // A change of step is said once to a screen reader; "Sent" is said by turnSent.
  if (waitSaid !== m.step) { if (waitSaid !== null || m.step !== "sent") announce(waitTitle(m.step)); waitSaid = m.step; }
}
function waitActive() { return inflight().length > 0; }
function waitOnView(before) { if (!inflight().length && noteNow) noteNow = null; }
// A turn was sent from this page: info is {via: "typed" | "spoken" | "live", text, entry}. Called by sendText() here and by sendLive().
function turnSent(info) { announce(tr("w.announce.sent")); }
// Kept for the live code: an answer that waits for another to end plays by itself; nothing to paint.
function skipQueued() { queued = null; paintAll(); }
