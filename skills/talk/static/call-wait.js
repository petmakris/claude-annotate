// The foot's line: what Claude is doing, the voice being made, Undo; the rail's line: the sentence being said.
function paintInfo() {
  const s = statusText(), e = shownAnswer();
  $("status").hidden = !s;
  if (s) { $("status").textContent = s.text; $("status").className = "status" + (s.shimmer ? " shimmer" : "") + (s.warn ? " warn" : ""); }
  paintPrep(recorder ? null : e);
  $("wave").hidden = !recorder;
}
// The line in the foot while there is no answer to read: the first that applies. The wait for an answer has its own
// card (paintWait) and the answer waiting to play its own row (paintQueue), so neither is a line here.
function statusText() {
  if (recorder) return null;
  if (live && live.speech) return {text: "Hearing you…"};
  if (live && live.suspended) return {text: "Click anywhere to start listening.", warn: true};
  if (live && live.parked) return {text: live.parked === "floor" ? "Listening in another call. Press the mic to listen here."
    : "Listening on another screen. Press the mic to listen here."};
  if (held && held.armed && !busy) return {text: "Listening. Go ahead."};
  if (elsewhere && audio.paused && current) return {text: "Playing on another screen."};
  if (liveFlash && Date.now() < liveFlash.until && !busy) return {text: liveFlash.text};
  if (busy) return {text: "Turning your words into text…", shimmer: true};
  if (view.ended) return {text: closed ? "Closed. You can close this tab." : "The call has ended: " + view.ended + ". Answers can still be replayed."};
  // A question in flight (sent, picked up, working, slow or not picked up) is the wait card's: see paintWait().
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

// `replace`: the draft is a correction, so the question in flight is set aside (the server takes it back or marks it
// replaced, and the answer to it is shown but never read aloud) instead of the draft being added to it.
async function sendText(replace = false) {
  const text = $("text").value.trim(); if (!text) return;
  if (!replace && typedCommand(text)) return;   // I: "slower" and the like move the voice, they are not a question
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
      if (target) noteSend(body.replaced === false ? "Sent. The earlier question was answered already." : "Replaced. Claude will answer this one.");
      $("text").value = ""; spoken = false; fitText(); release(); if (!audio.paused) audio.pause(); view.v = -1;
      if (answering) { answering = null; $("text").placeholder = "Type, or press the mic"; clearStop(); }
      if (wake) wake();
    }
    else { showError(body.error || "Sending failed: HTTP " + resp.status); noteSend("Not sent. Your draft is kept.", "warn"); }
  } catch (err) { showError("Sending failed: " + err.message); noteSend("Not sent. Your draft is kept.", "warn"); }
  $("sendtext").disabled = !$("text").value.trim();
}
// The text field grows with what is typed, up to a few lines, and Send waits for something to send.
function fitText() {
  const t = $("text"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px";
  if (!t.value.trim()) spoken = false;
  $("sendtext").disabled = !t.value.trim();
  paintWait();
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
$("sendtext").onclick = () => sendText();
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendText(); } });


// ---- the wait card ----------------------------------------------------------------
// From Send until the answer lands, the Now card holds this card instead of the answer: where the question stands (sent,
// picked up, working, slow, not picked up), a clock the page counts itself from the question's own time (`entry.at`, read
// through serverNow(), so a reload keeps it), the step the session reports, and the way out of each state. What stands
// where comes from the server: `view.turn.entries` lists the questions in flight, each "sent" (no doorbell has collected it)
// or "picked" (the session has it, no answer yet); `view.stalled` says nothing has moved for too long (20 s for a question
// nobody collected, 180 s for one the session went quiet on), so the page keeps no stall timer of its own.
const SLOW_AFTER = 90;       // seconds after the question: "Taking longer than usual" (the server's stalled flag comes later)
let waitTick = 0;            // the clock's interval, running only while the card is shown
let waitSig = "";            // what the card was built from: it is rebuilt only when that changes, never each second
let waitFor = null;          // the id of the first question the card was last built for: a new one scrolls the card into view
let waitSaid = null;         // the step a screen reader was last told: it hears each change of step once, never the clock
let sendNoteNow = null;      // {text, tone, until}: what happened to the last send, take back or copy
let playAnywayId = null;     // a replaced answer the reader asked to hear: it plays when its voice is ready

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
// What the card says now: null when nothing is in flight. The wait counts from the first send, so a question sent again
// keeps the time it has already waited.
function waitModel() {
  const fl = inflight(); if (!fl.length) return null;
  const t = view.turn || {}, picked = fl.some(x => x.state === "picked");
  const again = resendOf(fl[0].entry);
  const sentAt = again ? again.first.at : fl[0].entry.at, elapsed = Math.max(0, serverNow() - sentAt);
  const quiet = t.alive_at ? Math.max(0, serverNow() - t.alive_at) : null;
  const step = !picked ? (view.stalled ? "notpicked" : "sent")
    : view.stalled ? "silent" : elapsed >= SLOW_AFTER ? "slow" : "working";
  const acts = (view.activity || []).slice(-4);
  const run = acts.filter(a => a.state === "running").pop();
  return {fl, picked, step, elapsed, quiet, run, acts, sentAt, text: fl.map(x => x.entry.text).join("\n"),
    again: again ? {...again, at: fl[0].entry.at} : null, rows: fl.flatMap(x => heldTexts(x.entry)),
    pickedAt: picked && t.collected_at ? Math.max(0, t.collected_at - sentAt) : null,
    earlier: (t.earlier || 0) > 0};
}
const WAIT_TITLE = {sent: "Sent", notpicked: "Not picked up", working: "Claude is working", slow: "Taking longer than usual",
  silent: "Claude has gone quiet"};
function waitSub(m) {
  if (m.step === "sent") return m.earlier ? "Claude is finishing the earlier question. This one comes next." : "Waiting for Claude to pick it up.";
  if (m.step === "notpicked") return "Claude has not picked this up yet.";
  if (m.step === "silent") return "No sign of life for " + fmt(m.quiet === null ? m.elapsed : m.quiet) + ".";
  if (m.step === "slow") return m.run ? "Still on the step below." : m.quiet === null ? "Still working on it." : "Last sign of life " + stepClock(m.quiet) + " ago.";
  return m.run ? "" : "Claude has your question.";  // a step running is a row of its own
}
// The line that stays on a card whose question was sent again: how long ago, and that several questions went as one.
function againText(m) {
  const a = m.again, ago = fmt(Math.max(0, serverNow() - a.at));
  return (a.tries > 1 ? "Sent again " + a.tries + " times, the last " + ago + " ago" : "Sent again " + ago + " ago")
    + (a.count > 1 ? ", " + a.count + " questions as one." : ".");
}
const WAIT_STEPS = ["Sent", "Picked up", "Working", "Answer"];
// Where the stepper stands: 0 Sent, 1 Picked up, 2 Working (the session has reported a step).
const waitReach = m => !m.picked ? 0 : (view.activity || []).length ? 2 : 1;
const WAIT_ICON = {
  sent: '<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8.5"/>',
  working: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4h-4"/>',
  warn: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.01"/>',
  copy: '<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  again: '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  back: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  check: '<path d="M5 12l5 5L20 7"/>',
  skip: '<path d="M6 5v14l10-7z"/><path d="M19 5v14"/>',
  queue: '<path d="M4 6h10M4 11h10M4 16h6"/><path d="M15 14l5 3-5 3z"/>',
  swap: '<path d="M7 7h12M15 3l4 4-4 4M17 17H5M9 13l-4 4 4 4"/>',
};
const svgIcon = (name, size = 16) => '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + WAIT_ICON[name] + '</svg>';
function waitButton(icon, label, onclick, primary) {
  const b = document.createElement("button"); b.type = "button"; b.className = "wt-btn" + (primary ? " primary" : "");
  b.innerHTML = svgIcon(icon); const w = document.createElement("span"); w.textContent = label; b.append(w);
  b.setAttribute("aria-label", label); b.title = label; b.onclick = onclick; return b;
}
// The card's actions for its step, as [icon, label, handler, primary].
function waitActions(m) {
  const newest = m.fl[m.fl.length - 1], collected = m.fl.find(x => x.state === "picked");
  const copy = ["copy", "Copy question", copyQuestion], again = ["again", "Send again", sendAgain, true];
  // Before pickup Take back withdraws every question the card shows, all that nobody has collected, and puts them in the box in order.
  const unpicked = m.fl.filter(x => x.state === "sent").map(x => x.id), many = unpicked.length > 1;
  const takeBack = ["back", many ? "Take back all" : "Take back", () => cancelTurn(unpicked.length ? unpicked : [newest.id])];
  const cancel = ["x", "Cancel", () => cancelTurn([collected ? collected.id : newest.id])];
  return {sent: [takeBack, copy], notpicked: [again, copy, takeBack], working: [cancel], slow: [cancel, copy], silent: [again, copy, cancel]}[m.step];
}
// Build the card for a model: the title and clock, the sub line, the question, the stepper, the steps the session reports, the actions.
function buildWait(m) {
  const card = $("waitcard");
  card.className = "wait-card step-" + m.step + (m.step === "working" || m.step === "sent" ? "" : " warn");
  const head = document.createElement("div"); head.className = "wt-head";
  const icon = document.createElement("span"); icon.className = "wt-icon";
  icon.innerHTML = svgIcon(m.step === "sent" ? "sent" : m.step === "working" ? "working" : "warn", 20);
  const title = document.createElement("span"); title.className = "wt-title";
  title.textContent = WAIT_TITLE[m.step];
  const clock = document.createElement("span"); clock.className = "wt-clock"; clock.setAttribute("aria-hidden", "true");
  head.append(icon, title, clock);
  const sub = document.createElement("p"); sub.className = "wt-sub";
  // One row for each question in flight (each one a sent-again question holds too), each with its own clamp; with more than one, each says which it is.
  const qs = document.createElement("div"); qs.className = "wt-qs";
  m.rows.forEach((text, i) => {
    const q = document.createElement("p"); q.className = "wt-q";
    if (m.rows.length > 1) {
      q.classList.add("multi");
      const n = document.createElement("small"); n.className = "wt-qn"; n.textContent = "Question " + (i + 1) + " of " + m.rows.length;
      const t = document.createElement("span"); t.className = "wt-qt"; t.textContent = text; q.append(n, t);
    } else q.textContent = text;
    qs.append(q);
  });
  const again = document.createElement("p"); again.className = "wt-again"; again.hidden = !m.again;
  const stepper = document.createElement("ol"); stepper.className = "wt-steps"; stepper.setAttribute("aria-label", "Where your question stands");
  const reach = waitReach(m);
  WAIT_STEPS.forEach((label, i) => {
    const li = document.createElement("li"); li.className = i < reach ? "done" : i === reach ? "now" : "todo";
    const bar = document.createElement("i"), name = document.createElement("b"), at = document.createElement("small");
    name.textContent = label; at.className = "wt-at";
    li.append(bar, name, at); stepper.append(li);
  });
  card.replaceChildren(head, sub, again, qs, stepper);
  if (m.acts.length) {
    const list = document.createElement("ul"); list.className = "wt-acts";
    for (const a of m.acts) {
      const li = document.createElement("li"); li.className = a.state === "running" ? "run" : "done";
      const mark = document.createElement("span"); mark.className = "wt-mark"; mark.innerHTML = svgIcon(a.state === "running" ? "working" : "check", 14);
      const name = document.createElement("span"); name.className = "wt-act"; name.textContent = a.label;
      const sec = document.createElement("small"); sec.className = "wt-sec";
      li.append(mark, name, sec); list.append(li);
    }
    card.append(list);
  }
  const acts = document.createElement("div"); acts.className = "wt-actions";
  for (const [ic, label, fn, primary] of waitActions(m)) acts.append(waitButton(ic, label, fn, primary));
  card.append(acts);
  if (m.step !== "working") {
    const lost = document.createElement("p"); lost.className = "wt-lost"; lost.textContent = "Nothing is lost: your question is saved in the call.";
    card.append(lost);
  }
  card.hidden = false;
}
// What the card was built from: change any of it and the card is rebuilt; the seconds and the clock are not in it.
function waitSigOf(m) {
  return [m.step, m.fl.map(x => x.id + x.state).join(","), m.text, m.again ? m.again.tries + "/" + m.again.count : "", m.acts.map(a => a.label + a.state).join("|"), m.earlier, waitReach(m)].join("§");
}
// The numbers on the card: the clock, each step's time, the seconds of each reported step, the sub line. They change each second.
function tickWait(m) {
  const card = $("waitcard");
  card.querySelector(".wt-clock").textContent = fmt(m.elapsed);
  card.querySelector(".wt-sub").textContent = waitSub(m);
  card.querySelector(".wt-again").textContent = m.again ? againText(m) : "";
  const times = [0, m.pickedAt];
  card.querySelectorAll(".wt-at").forEach((el, i) => { el.textContent = i < 2 && times[i] !== null && i <= waitReach(m) ? fmt(times[i]) : ""; });
  card.querySelectorAll(".wt-acts li").forEach((li, i) => { if (m.acts[i]) li.querySelector(".wt-sec").textContent = stepClock(m.acts[i].seconds || 0); });
}
// The clock repaints the card each second while it shows, and stops by itself when nothing is in flight.
function waitClock(on) {
  if (on && !waitTick) waitTick = setInterval(paintWait, 1000);
  else if (!on && waitTick) { clearInterval(waitTick); waitTick = 0; }
}

// ---- the card's actions -----------------------------------------------------------
function copyQuestion() {
  const m = waitModel(); if (!m) return;
  const done = () => noteSend("Copied.");
  const old = () => {
    const t = document.createElement("textarea"); t.value = m.text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.append(t); t.select();
    try { document.execCommand("copy"); done(); } catch { showError("Could not copy. Select the question and copy it."); }
    t.remove();
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(m.text).then(done, old); else old();
}
// Take back (not collected) or Cancel (collected): the server takes each question back or cancels the turn and tells the
// session. `ids` are the questions the card shows that this acts on: Take back names every one nobody has collected (the
// server takes back one entry for each call), Cancel names the collected turn (the server cancels all of it). The words
// go back into the box, in the order they were sent, so nothing said is lost; the note says how many came back.
async function cancelTurn(ids) {
  const fl = inflight().filter(x => ids.includes(x.id)); if (!fl.length) return;
  const back = [], got = [];
  let how = "withdrawn";
  try {
    for (const f of fl) {
      if (got.includes(f.id)) continue;   // a collected turn's cancel took this one with it
      const r = await api("/api/cancel", {method: "POST", body: JSON.stringify({entry: f.id}), headers: {"Content-Type": "application/json"}});
      const b = await r.json().catch(() => ({}));
      if (!b.cancelled) continue;
      if (b.how === "cancelled") how = "cancelled";
      for (const id of (b.entries || [f.id])) { if (!got.includes(id)) { got.push(id); back.push((view.entries.find(e => e.id === id) || f.entry).text); } }
    }
    const words = back.filter(Boolean).join("\n");
    if (got.length) {
      const t = $("text");
      t.value = t.value.trim() ? words + "\n" + t.value : words; spoken = false; fitText();
      if (matchMedia("(hover: hover)").matches) t.focus();
    }
    if (!got.length) noteSend("Too late: Claude already answered it.", "warn");
    else if (got.length < fl.length) noteSend("Took back " + got.length + " of " + fl.length + " questions. Claude has picked up the rest. Your words are back in the box.", "warn");
    else if (got.length > 1) noteSend((how === "cancelled" ? "Cancelled " : "Took back ") + got.length + " questions. Your words are back in the box, in order.");
    else noteSend(how === "cancelled" ? "Cancelled. Your words are back in the box." : "Taken back. Your words are back in the box.");
    view.v = -1; if (wake) wake();
  } catch { showError("Could not take it back: the call server did not answer."); }
}
// Send the question again as a new one that replaces the first: the server takes the first back, or marks it replaced if
// the session has it, so only one is answered. The draft in the box is left alone.
async function sendAgain() {
  const m = waitModel(); if (!m) return;
  try {
    const r = await api("/api/say", {method: "POST", body: JSON.stringify({text: m.text, replaces: m.fl[0].id}), headers: {"Content-Type": "application/json"}});
    const b = await r.json().catch(() => ({}));
    if (!r.ok) { showError(b.error || "Sending failed: HTTP " + r.status); return; }
    turnSent({via: "typed", text: m.text, entry: b.entry ? b.entry.id : null});
    noteSend(b.replaced === false ? "Sent. The first one was answered already." : "Sent again.");
    view.v = -1; if (wake) wake();
  } catch (err) { showError("Sending failed: " + err.message); }
}
// What happened, for a few seconds, in the line above the box.
function noteSend(text, tone) { sendNoteNow = {text, tone: tone || "", until: Date.now() + 7000}; paintWait(); setTimeout(paintWait, 7100); }

// ---- the queued answer ------------------------------------------------------------
// An answer that came while another plays waits for it to end. It is a row with Skip: Skip drops it from the queue (the
// answer stays in the list, unplayed and still new) and touches nothing else: not following, not the player's claim.
function skipQueued() { queued = null; paintAll(); }
function paintQueue() {
  const row = $("queuerow"), e = queued && !stopped ? (view.entries.find(x => x.id === queued.id) || queued) : null;
  row.hidden = !e;
  if (!e) { row.dataset.sig = ""; return; }
  const sig = e.id + ":" + (e.n || "");
  if (row.dataset.sig === sig) return;
  row.dataset.sig = sig;
  const icon = document.createElement("span"); icon.className = "qr-icon"; icon.innerHTML = svgIcon("queue", 16);
  const text = document.createElement("span"); text.className = "qr-text";
  text.textContent = "Next: answer " + (e.n || "") + ". It plays when this one ends.";
  const skip = waitButton("skip", "Skip", skipQueued); skip.classList.add("qr-skip");
  row.replaceChildren(icon, text, skip);
}
// "Play anyway": a replaced answer is kept unspoken. The reader asks for it: its voice is made (the server's /api/speak) and
// it plays as a reader's own play, like any other.
async function playAnyway(entry) {
  const e = view.entries.find(x => x.id === entry.id) || entry;
  if (e.speech === "ready") { readerPlays(e); takeVoice(); load(e, true); return; }
  playAnywayId = e.id;
  try {
    const r = await api("/api/speak", {method: "POST", body: JSON.stringify({entry: e.id}), headers: {"Content-Type": "application/json"}});
    if (!r.ok) { playAnywayId = null; const b = await r.json().catch(() => ({})); showError(b.error || "Could not read the answer aloud."); }
    else { view.v = -1; if (wake) wake(); }
  } catch { playAnywayId = null; showError("Could not read the answer aloud: the call server did not answer."); }
}

// ---- the hooks this file owns (W) -----------------------------------------------
// The Undo button of a live turn, from paintAll(). While the wait card shows its own Take back, Undo steps aside.
function paintUndo() {
  const canUndo = !!undoable && Date.now() < undoable.until && !view.ended && !waitActive();
  $("undo").hidden = !canUndo;
}
// The wait card (#waitcard in the Now card), the note under the field (#sendnote) and the queued answer's row (#queuerow),
// from paintAll(). waitActive() is true while a turn of this call is in flight (sent, collected, not answered), so the
// Now card stays up for it; the wait card shows, and the card's answer part hides, while it is.
function paintWait() {
  const m = waitModel(), card = $("waitcard");
  waitClock(!!m);
  if (m) {
    $("nowcard").hidden = false;
    const sig = waitSigOf(m);
    if (sig !== waitSig || card.hidden) { waitSig = sig; buildWait(m); }
    tickWait(m);
    if (waitFor !== m.fl[0].id) { waitFor = m.fl[0].id; $("convo").scrollTop = 0; }
    // The live region is the page's one (announce), since this card is rebuilt: a change of step is said once. "Sent" is
    // said by turnSent.
    if (waitSaid !== m.step) {
      if (waitSaid !== null || m.step !== "sent") { const sub = waitSub(m); announce(WAIT_TITLE[m.step] + "." + (sub ? " " + sub : "")); }
      waitSaid = m.step;
    }
  } else if (!card.hidden) { card.hidden = true; card.replaceChildren(); waitSig = ""; waitFor = null; waitSaid = null; }
  // The placeholder says what the field does while a question is in flight.
  if (!answering && !recorder) $("text").placeholder = m ? WAIT_PLACEHOLDER : modePlaceholder();
  paintSendNote(m);
  paintQueue();
}
// The line above the box: what just happened, else that a draft is kept while a question is in flight.
function paintSendNote(m) {
  const note = $("sendnote"), now = sendNoteNow && Date.now() < sendNoteNow.until ? sendNoteNow : null, draft = $("text").value.trim();
  const keep = !now && !!m && !!draft;
  note.hidden = !now && !keep;
  if (note.hidden) { note.dataset.sig = ""; return; }
  const sig = now ? "n:" + now.text : "draft";
  if (note.dataset.sig === sig) return;
  note.dataset.sig = sig; note.className = "sendnote" + (now && now.tone === "warn" ? " warn" : "");
  const text = document.createElement("span"); text.className = "sn-text";
  if (now) text.textContent = now.text;
  else { text.append("Draft kept."); const more = document.createElement("span"); more.className = "sn-more"; more.textContent = " Send adds it to your question."; text.append(more); }
  note.replaceChildren(text);
  if (keep) note.append(waitButton("swap", "Replace question", () => sendText(true)));
}
function waitActive() { return inflight().length > 0; }
// A new view arrived: `before` is the one it replaces. An answer is here: what was said about the last send is old news.
function waitOnView(before) {
  if (!inflight().length && sendNoteNow && /^(Sent|Replaced|Copied)/.test(sendNoteNow.text)) sendNoteNow = null;
}
// A turn was sent from this page: info is {via: "typed" | "spoken" | "live", text, entry: the new entry's id or null}. Called
// by sendText() here and by sendLive() in call-live.js, at the moment the server took the turn.
function turnSent(info) {
  announce("Your question was sent.");
}
