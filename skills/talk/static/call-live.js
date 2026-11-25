// ---- live mode: the microphone stays open --------------------------------------------
// A loudness detector notices speech, keeping the moment before it so the first syllable is kept, and
// sends it after a pause. Only voiced time counts, against a noise floor that follows the room.
// Speech over an answer holds it (`held`): with "By talking" the voice drops at once and stops after
// LIVE.pauseMs of real speech; with cue words it plays on unless the words start with "wait",
// "listen" and the like, and a cue alone stops it and waits. Whatever was said settles the hold: a
// turn leaves the answer stopped, nothing (a cough, "mm-hm", its own echo) resumes it from the start
// of its sentence. One page listens per call and one call per browser: the others park.
const LIVE = {chunk: 2048, preMs: 400, minRms: 0.012, startMs: 160, startOverMs: 320, overGain: 1.8, minSpeechMs: 350,
              floorMs: 8000, pauseMs: 700, duck: 0.2, maxMs: 60000, hardMs: 420000, armedMs: 6000, sleepMs: 600000,
              flatRms: 0.0005, flatMs: 10000};   // a stream flat at zero this long is a muted or dead microphone, not a quiet room
const liveQueue = [];
let liveSending = false, wokeAt = 0;
const liveChannel = "BroadcastChannel" in window ? new BroadcastChannel("talk-live") : null;
const listening = () => !!live && !live.suspended && !live.parked && !live.muted;
// The user is talking, or what they said is on its way: new answers wait and the held answer stays held.
const userBusy = () => !!held || !!(live && live.speech) || liveQueue.length > 0 || liveSending;
const later = ms => new Promise(ok => setTimeout(ok, ms));

async function startLive() {
  if (live || view.ended) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showError("This page cannot reach a microphone. Open it over https or on localhost."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}}); }
  catch (err) { showError("No microphone: " + err.message); return; }
  if (live || talkMode !== "live" || view.ended) { stream.getTracks().forEach(t => t.stop()); return; }
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream), node = ctx.createScriptProcessor(LIVE.chunk, 1, 1);
  live = {stream, ctx, source, node, rate: ctx.sampleRate, recent: [], pre: [], loud: 0, quiet: 0, voiced: 0, ms: 0,
          speech: false, chunks: [], floorTaken: false, parked: null, lastVoice: performance.now(),
          suspended: ctx.state === "suspended", muted: false, noSignal: false, flatMs: 0};
  node.onaudioprocess = ev => liveChunk(new Float32Array(ev.inputBuffer.getChannelData(0)));
  source.connect(node); node.connect(ctx.destination);
  const track = stream.getAudioTracks()[0];
  if (track) {
    track.onended = () => { if (live && live.stream === stream) stopLive("The microphone was lost. Press the mic to listen again."); };
    // The browser or the system muted the input (a hardware switch, a privacy setting): said at once, not after the silence watch.
    track.onmute = () => { if (live && live.stream === stream && !live.muted) { live.noSignal = true; paintAll(); } };
    track.onunmute = () => { if (live && live.stream === stream) { live.noSignal = false; live.flatMs = 0; paintAll(); } };
  }
  liveNote = "";
  claimLive();
}
// Mute keeps the stream, the floor and this page's claim, and sends nothing: what is being said is dropped, a held answer goes on.
function setMuted(on) {
  const l = live; if (!l || l.muted === on) return;
  l.muted = on;
  const track = l.stream.getAudioTracks()[0]; if (track) track.enabled = !on;
  if (on) { if (l.speech) { l.speech = false; l.chunks = []; l.ms = 0; l.voiced = 0; l.quiet = 0; } l.loud = 0; levels.fill(0); $("app").style.removeProperty("--lvl"); settle(); }
  else { l.lastVoice = performance.now(); l.recent.length = 0; l.pre.length = 0; l.flatMs = 0; l.noSignal = false; }
  paintAll();
}
function stopLive(note = "") {
  const l = live; live = null;
  if (!l) return;
  l.node.disconnect(); l.source.disconnect(); l.stream.getTracks().forEach(t => t.stop()); l.ctx.close();
  levels.fill(0); $("app").style.removeProperty("--lvl");
  liveQueue.length = 0;           // said but not yet sent: dropped with the microphone
  liveNote = note;
  if (held) held.armed = false;
  settle();                       // an answer the speech was holding goes on
  paintAll();
}
// Chrome starts audio only after a click or key on the page. A click in the stage lands in its frame,
// and shows here only as this window losing focus.
function wakeLive() {
  if (!live || !live.suspended) return;
  wokeAt = performance.now();
  live.ctx.resume().then(() => { if (live && live.ctx.state === "running") { live.suspended = false; paintAll(); } }).catch(() => {});
}
document.addEventListener("pointerdown", wakeLive, true);
document.addEventListener("keydown", wakeLive, true);
window.addEventListener("blur", wakeLive);
// This page listens: other pages of this call stop (a TV and a laptop both open), and other calls yield
// the floor (one voice is never sent to two calls).
let claimedAt = 0;
function claimLive() {
  if (!live) return;
  live.parked = null;
  claimedAt = Date.now();
  if (liveChannel) liveChannel.postMessage({call: CFG.call, page: PAGE_ID, at: claimedAt});
  if (view.floor_call && view.floor_call !== CFG.call) takeFloor(null);
  paintAll();
}
function parkLive(why) {
  if (!live) return;
  if (live.speech) { live.speech = false; live.chunks = []; }
  live.parked = why;
  settle(); paintAll();
}
if (liveChannel) liveChannel.onmessage = ev => {
  const m = ev.data || {};
  // Only a newer claim parks this page, the page id breaking a tie: two pages claiming at once never
  // both stand down.
  const newer = m.at > claimedAt || (m.at === claimedAt && String(m.page) > PAGE_ID);
  if (m.call === CFG.call && m.page !== PAGE_ID && live && !live.parked && newer) parkLive("screen");
};
// Coming back to this page (a tab, a window, the TV's input) is the user choosing to talk here.
window.addEventListener("focus", () => { if (live && live.parked) claimLive(); });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && live && live.parked) claimLive(); });

// The character the voice has reached in the answer being played: how far the user heard.
function heardAt() {
  const e = current && (view.entries.find(x => x.id === current.id) || current);
  if (!e || !e.words || !e.words.length) return 0;
  const k = wordAt(e, audio.currentTime);
  return k < 0 ? 0 : e.words[k][1];
}
// Where an interrupted answer picks up again: the start of the sentence it was in.
function sentenceStart() {
  const e = current && (view.entries.find(x => x.id === current.id) || current), t = audio.currentTime || 0;
  const starts = e && sentenceTimes(e);
  if (!starts) return Math.max(0, t - 2);
  const i = starts.findLastIndex(s => s <= t + 0.05);
  return i < 0 ? 0 : starts[i];
}
function liveChunk(d) {
  const l = live;
  if (!l || l.suspended || l.muted) return;
  let sum = 0; for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
  const lvl = Math.sqrt(sum / d.length), ms = d.length / l.rate * 1000, now = performance.now();
  levels.push(Math.min(1, lvl * 8)); levels.shift();
  // Flat at zero for ten seconds: a muted or dead input, never merely a quiet room (a quiet room still carries noise).
  if (lvl < LIVE.flatRms) { l.flatMs += ms; if (l.flatMs >= LIVE.flatMs && !l.noSignal) { l.noSignal = true; paintAll(); } }
  else { l.flatMs = 0; if (l.noSignal) { l.noSignal = false; paintAll(); } }
  if (!meterRaf) meterRaf = requestAnimationFrame(paintMeter);
  if (l.parked) return;
  // The floor is the quietest moment of the last few seconds: a fan or music switched on raises it,
  // so a louder room never reads as speech that does not end.
  l.recent.push(lvl); if (l.recent.length * ms > LIVE.floorMs) l.recent.shift();
  const over = !!held || (!!current && !audio.paused);
  const thr = Math.max(LIVE.minRms, Math.min(...l.recent) * 3) * (over ? LIVE.overGain : 1);
  if (!l.speech) {
    l.pre.push(d); if (l.pre.length * ms > LIVE.preMs) l.pre.shift();
    if (lvl > thr) { l.loud += ms; if (l.loud >= (over ? LIVE.startOverMs : LIVE.startMs)) speechStarts(); }
    else l.loud = 0;
    if (now - l.lastVoice > LIVE.sleepMs && !userBusy() && !busy) stopLive("Asleep after 10 minutes of quiet. Press the mic to listen.");
    return;
  }
  l.chunks.push(d); l.ms += ms;
  if (lvl >= thr * 0.7) { l.voiced += ms; l.quiet = 0; l.lastVoice = now; } else l.quiet += ms;
  if (!l.floorTaken && l.voiced >= LIVE.minSpeechMs) {   // a cough never takes the floor from another call
    l.floorTaken = true;
    if (view.floor_call !== CFG.call) takeFloor(null);
  }
  if (held && held.ducked && !held.paused && l.voiced >= LIVE.pauseMs) { audio.pause(); held.paused = true; paintAll(); }
  // A long turn is cut only at a pause in it, past the cap; the hard cap keeps the recording under the server's limit.
  if (l.quiet >= endPause || (l.ms >= LIVE.maxMs && l.quiet > 0) || l.ms >= LIVE.hardMs) speechEnds();
}
function speechStarts() {
  const l = live;
  // The loud run that started the speech is speech already: it counts as voiced time.
  l.speech = true; l.chunks = l.pre.splice(0); l.ms = l.loud; l.voiced = l.loud; l.quiet = 0; l.loud = 0; l.floorTaken = false;
  l.lastVoice = performance.now();
  if (held && held.armed) { clearTimeout(held.armTimer); held.armTimer = 0; }   // the question after a cue word
  else if (!held && current && !audio.paused) {
    held = {id: current.id, at: heardAt(), from: sentenceStart(), ducked: false, paused: false, armed: false, armTimer: 0};
  }
  if (held && barge === "talk" && !held.ducked && !held.paused && !audio.paused) { audio.volume = LIVE.duck; held.ducked = true; }
  paintAll();
}
function speechEnds() {
  const l = live;
  const u = {chunks: l.chunks, rate: l.rate, over: held ? {id: held.id, at: held.at} : null,
             gate: barge === "keyword" && !!held && !held.armed};
  const voiced = l.voiced;
  l.speech = false; l.chunks = []; l.ms = 0; l.voiced = 0; l.quiet = 0;
  if (voiced < LIVE.minSpeechMs) { settle(); return; }   // a click or a breath: nothing to send
  liveQueue.push(u); paintAll(); drainLive();
}
async function drainLive() {
  if (liveSending) return;
  liveSending = true;
  while (liveQueue.length) await sendLive(liveQueue.shift());
  liveSending = false;
  settle();
}
// What happens to a held answer once nothing more is being said or sent: a newer answer plays, else the
// held one picks up from the start of its sentence. An answer that was stopped for a question is not held.
function settle() {
  if ((live && live.speech) || liveQueue.length || liveSending || (held && held.armed)) return;
  const h = held; held = null;
  audio.volume = 1;
  if (deferred) { const e = deferred; deferred = null; load(view.entries.find(x => x.id === e.id) || e, true); return; }
  if (h && h.paused && current && current.id === h.id) { audio.currentTime = h.from; audio.play().catch(() => {}); }
  paintAll();
}
// The user took the player in hand (Space, a button): whatever speech was holding lets go of it.
function release() {
  if (!held) return;
  clearTimeout(held.armTimer); held = null; audio.volume = 1;
}
// A soft tone in the headphones: a higher one when a cue word stopped the answer, a lower one when a turn went.
function chime(freq) {
  const ctx = live && live.ctx;
  if (!ctx || ctx.state !== "running") return;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.frequency.value = freq; g.gain.setValueAtTime(0.0001, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
  o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.2);
}
function flash(text) { liveFlash = {text, until: Date.now() + 2500}; setTimeout(paintAll, 2600); }
async function sendLive(u) {
  const q = new URLSearchParams({lang: language, live: "1"});
  if (u.over) { q.set("interrupted", u.over.id); q.set("at", u.over.at); }
  if (u.gate) q.set("keyword", "1");
  const sayingBack = answering;  // the [[say back]] question this utterance may answer: it goes with the turn
  if (sayingBack) q.set("answering", sayingBack);
  if (!u.gate) { busy = true; paintAll(); }
  const wav = toWav(u.chunks, u.rate);
  let body = null;
  // A restarting server (503) or a dropped connection is tried again for a while; what still does not
  // go is kept for Send again, as a recording is in Press to talk.
  for (let tries = 0; ; tries++) {
    try {
      const resp = await api("/api/listen?" + q, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}});
      if (resp.status === 503 && tries < 5) { await later(1000 * 2 ** tries); continue; }
      const got = await resp.json().catch(() => ({}));
      if (resp.ok) body = got;
      else { showError(got.error || "Sending failed: HTTP " + resp.status); if (![410, 413].includes(resp.status) && !u.gate) unsent = wav; }
    } catch (err) {
      if (tries < 3) { await later(1000 * 2 ** tries); continue; }
      showError("Sending failed: " + err.message); if (!u.gate) unsent = wav;
    }
    break;
  }
  busy = false;
  if (body && body.command) {
    runCommand(body.command, body);
  } else if (body && body.held) {
    // A thought left hanging ("so what about the… um"): the server waits for its end, so a turn is coming.
    if (held) { audio.pause(); clearTimeout(held.armTimer); held = null; }
    audio.volume = 1; deferred = null;
  } else if (body && body.keyword) {
    // A cue word alone: the answer stops where it was, and what is said next is the question.
    if (held) {
      audio.pause(); held.paused = true; held.armed = true; audio.volume = 1;
      held.armTimer = setTimeout(() => { if (held && held.armed && !(live && live.speech)) { held.armed = false; settle(); } }, LIVE.armedMs);
    }
    chime(880);
  } else if (body && body.entry) {
    if (held) { audio.pause(); clearTimeout(held.armTimer); held = null; }
    audio.volume = 1; deferred = null;
    chime(520);
    undoable = {entry: body.entry.id, until: Date.now() + 8000}; setTimeout(paintAll, 8100);
    turnSentAt = Date.now();
    turnSent({via: "live", text: "", entry: body.entry.id});
    if (sayingBack && answering === sayingBack) { answering = null; $("text").placeholder = "Type, or press the mic"; clearStop(); }
    view.v = -1; if (wake) wake();
  } else if (body && !body.ignored && !u.over) flash("Didn't catch that.");
  paintAll();
}
// "slower", "faster" and "say that again slower" move the voice speed one step (the player's chip does the same by hand); a held
// answer goes on at the new speed, and the last one also starts the sentence again.
const SPEED_STEP = {slower: -1, faster: 1, repeat_slower: -1};
function speedBySpeech(cmd, h) {
  const at = SPEEDS.indexOf(speed), to = Math.min(SPEEDS.length - 1, Math.max(0, (at < 0 ? SPEEDS.indexOf(1) : at) + SPEED_STEP[cmd]));
  if (to === at) flash(SPEED_STEP[cmd] < 0 ? "Already as slow as it goes." : "Already as fast as it goes.");
  else { setSpeed(SPEEDS[to]); flash((SPEED_STEP[cmd] < 0 ? "Slower: " : "Faster: ") + speed + "×"); }
  if (cmd === "repeat_slower" && current) { readerPlays(current); audio.currentTime = h ? h.from : sentenceStart(); audio.play().catch(() => {}); }
  else if (h && h.paused && current) { audio.currentTime = h.from; audio.play().catch(() => {}); }
}
// A spoken command, acted on here: no turn, no wait for Claude.
function runCommand(cmd, body) {
  chime(700);
  if (cmd === "mute") { stopLive("Stopped listening. Press the mic to listen."); return; }
  if (cmd === "withdraw") { undoable = null; flash("Taken back."); if (held) { held.armed = false; } return; }  // settle resumes a held answer
  const h = held;
  release();
  if (cmd in SPEED_STEP) { speedBySpeech(cmd, h); return; }
  if (cmd === "pause") { audio.pause(); return; }
  // resume, repeat and back all play
  if (!current) { const e = lastAnswer(); if (e && e.speech === "ready") { readerPlays(e); load(e, true); } return; }
  readerPlays(current);
  if (cmd === "resume") { if (h && h.paused) audio.currentTime = h.from; audio.play().catch(() => {}); return; }
  if (cmd === "repeat") { audio.currentTime = h ? h.from : sentenceStart(); audio.play().catch(() => {}); return; }
  if (cmd === "back") { if (h) audio.currentTime = h.from; jump(-1); audio.play().catch(() => {}); }
}
