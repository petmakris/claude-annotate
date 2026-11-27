// ---- the conversation ------------------------------------------------------------------
// One list, oldest first, like a chat: each question the user asked, then the answer to it. The answer being said lights
// the word being said, and a tap on any word of any answer plays from there. Nothing else lives in the list: no cards,
// no chips, no counters. The boards are on the stage, the settings behind the gear.
const staged = (e) => !!CFG.stageUrl && (e.cues || []).some((c) => c.kind === "front");

// ---- what the conversation is made of ------------------------------------------
// Each answer with the question it answers. The questions the user has put since the last answer are kept as a list: an
// answer takes the last one (and the others it was merged with, `also`), but a reply kept as superseded answers the question
// it was written for: the one the correction names (`replaces`), else the first one the server set aside, and for an addition
// the first one asked; the later question stays open for the answer that follows. Board and note entries are not shown here.
function turnsOf(entries) {
  const turns = [];
  let open = [];
  for (const e of entries) {
    if (e.who === "you") { if (!e.withdrawn) open.push(e); }
    else if (e.who === "claude") {
      let q = null, also = [];
      if (e.superseded) {
        const fix = e.superseded_kind === "addition" ? null : open.find((x) => Number.isFinite(x.replaces) && open.some((y) => y.id === x.replaces));
        q = (fix && open.find((y) => y.id === fix.replaces)) || (e.superseded_kind === "addition" ? null : open.find((x) => x.superseded)) || open[0] || null;
        open = open.filter((x) => x !== q);
      } else {
        q = open.length ? open[open.length - 1] : null;
        also = open.slice(0, -1).filter((x) => !x.superseded);
        open = [];
      }
      turns.push({a: e, q, also});
    }
  }
  return {turns, open};
}
// The name of a board, for the stage's frame title and the live region.
const boardName = (b) => b.kind === "points" ? tr("s.keypoints") : b.text;
function boardTitle(v) {
  const b = v ? view.entries.find((x) => x.who === "board" && x.view === v) : null;
  return b ? boardName(b) : "";
}

// ---- the answer the player holds: the one playing, else the newest ----------------
function lastAnswer() {
  for (let i = view.entries.length - 1; i >= 0; i--) if (view.entries[i].who === "claude") return view.entries[i];
  return null;
}
function shownAnswer() { return current ? (view.entries.find(e => e.id === current.id) || current) : lastAnswer(); }
// An answer's words, each a span a tap plays from. A tap that ends a text selection selects; it does not play.
function wordSpans(e) {
  if (!e.words || !e.words.length) return [document.createTextNode(e.text)];
  const out = [];
  let pos = 0;
  e.words.forEach((w, i) => {
    if (w[0] > pos) out.push(document.createTextNode(e.text.slice(pos, w[0])));
    const span = document.createElement("span"); span.className = "w"; span.dataset.i = i;
    span.textContent = e.text.slice(w[0], w[1]);
    span.onclick = () => { if (String(getSelection() || "").trim()) return; playFrom(e, w[2]); };
    out.push(span); pos = w[1];
  });
  out.push(document.createTextNode(e.text.slice(pos)));
  return out;
}

// ---- the list ----------------------------------------------------------------------
// Each turn's nodes are kept by answer id and rebuilt only when what they show changes, so the spans the voice lights stay put.
const turnNodes = new Map();   // answer id -> {el, sig, spans}
const qOpen = new Set();       // long questions the reader opened
const QUESTION_CHARS = 320;
function buildQuestion(q) {
  const b = document.createElement("div"); b.className = "q"; b.setAttribute("role", "listitem");
  const long = q.text.length > QUESTION_CHARS || q.text.split("\n").length > 6;
  const text = document.createElement("div"); text.className = "qt" + (long && !qOpen.has(q.id) ? " clamped" : ""); text.textContent = q.text;
  b.append(text);
  if (long) {
    const more = document.createElement("button"); more.type = "button"; more.className = "more";
    more.textContent = tr(qOpen.has(q.id) ? "s.less" : "s.more"); more.setAttribute("aria-expanded", String(qOpen.has(q.id)));
    more.onclick = () => { if (qOpen.has(q.id)) qOpen.delete(q.id); else qOpen.add(q.id); turnNodes.clear(); paintConvo(); };
    b.append(more);
  }
  return b;
}
function buildTurn(t) {
  const el = document.createElement("div"); el.className = "turn"; el.dataset.id = t.a.id;
  for (const q of [...t.also, ...(t.q ? [t.q] : [])]) el.append(buildQuestion(q));
  const a = document.createElement("div"); a.className = "a"; a.setAttribute("role", "listitem");
  a.setAttribute("aria-label", tr("s.answer", {n: t.a.n}));
  const text = document.createElement("div"); text.className = "at"; text.append(...wordSpans(t.a));
  a.append(text);
  // A quiet line only when the answer is not an ordinary one: replaced by a correction, or not read aloud.
  let tag = "";
  if (t.a.superseded) tag = tr("s.corrected");
  else if (t.a.speech === "failed") tag = tr("s.notread", {why: t.a.speech_error || tr("s.speechfailed")});
  if (tag) {
    a.classList.add("aside");
    const line = document.createElement("p"); line.className = "tag"; line.textContent = tag;
    if (t.a.superseded) {
      const play = document.createElement("button"); play.type = "button"; play.className = "more"; play.textContent = tr("s.playanyway");
      play.onclick = () => playAnyway(t.a); line.append(" ", play);
    }
    a.append(line);
  }
  el.append(a);
  return {el, spans: [...text.querySelectorAll(".w")]};
}
const turnSig = (t) => [uiLang, t.a.text.length, t.a.words?.length || 0, t.a.superseded ? 1 : 0, t.a.speech === "failed" ? t.a.speech_error || 1 : 0,
  t.q ? t.q.id + ":" + t.q.text.length + ":" + qOpen.has(t.q.id) : "", t.also.map((q) => q.id).join(",")].join("|");
function paintConvo() {
  const {turns, open} = turnsOf(view.entries), list = $("turns");
  const keep = new Set();
  let prev = null;
  for (const t of turns) {
    keep.add(t.a.id);
    const sig = turnSig(t);
    let node = turnNodes.get(t.a.id);
    if (!node || node.sig !== sig) {
      const built = buildTurn(t);
      if (node) node.el.replaceWith(built.el);
      node = {...built, sig}; turnNodes.set(t.a.id, node);
      if (current && current.id === t.a.id) { lastK = -2; lastWord = null; }
    }
    const want = prev ? prev.nextSibling : list.firstChild;
    if (want !== node.el) list.insertBefore(node.el, want);
    prev = node.el;
  }
  for (const [id, node] of turnNodes) if (!keep.has(id)) { node.el.remove(); turnNodes.delete(id); }
  // The questions no answer has taken yet: the last ones in the list, under the newest answer.
  const pending = open.filter((q) => !q.superseded);
  const psig = uiLang + pending.map((q) => q.id + ":" + q.text.length + ":" + qOpen.has(q.id)).join(",");
  let tail = $("openqs");
  if (!tail) { tail = document.createElement("div"); tail.id = "openqs"; tail.className = "turn"; }
  if (tail.dataset.sig !== psig) { tail.dataset.sig = psig; tail.replaceChildren(...pending.map(buildQuestion)); }
  if (list.lastChild !== tail) list.append(tail);
  $("empty").hidden = !!turns.length || !!pending.length || waitActive();
}

// ---- the list follows the voice ---------------------------------------------------
// The word being said stays in view while the reader leaves the list alone. Scrolled away, a small round button brings it back.
let convoFollow = true, ownScroll = 0;
function scrollConvo(top, now = false) {
  const box = $("convo");
  if (Math.abs(box.scrollTop - top) < 2) return;
  ownScroll = performance.now();
  box.scrollTo({top, behavior: now || reduced.matches ? "auto" : "smooth"});
}
const toBottom = (now) => scrollConvo($("convo").scrollHeight, now === true);
function inView(el) {
  const box = $("convo").getBoundingClientRect(), r = el.getBoundingClientRect();
  return r.bottom > box.top + 8 && r.top < box.bottom - 8;
}
function followVoice(force) {
  if (!(convoFollow || force) || !lastWord) return;
  const box = $("convo"), r = lastWord.getBoundingClientRect(), b = box.getBoundingClientRect();
  if (force || r.top < b.top + 24 || r.bottom > b.bottom - 24) scrollConvo(Math.max(0, box.scrollTop + r.top - b.top - b.height * 0.35));
}
$("convo").addEventListener("scroll", () => {
  if (performance.now() - ownScroll < 900) return;   // a scroll this page made
  convoFollow = !lastWord || audio.paused || inView(lastWord);
  paintJump();
}, {passive: true});
function paintJump() { $("jump").hidden = convoFollow || !current || audio.paused; }
$("jump").onclick = () => { convoFollow = true; followVoice(true); paintJump(); };

// ---- the word being said --------------------------------------------------------
let lastWord = null, lastK = -2, lastTurn = null;
function readingSpans() { const n = current && turnNodes.get(current.id); return n ? n.spans : []; }
function highlight() {
  const e = current;
  let k = -1;
  if (e && e.words && e.words.length && !audio.ended) {
    if (audio.currentTime > 0) k = wordAt(e, audio.currentTime);
    const unheard = !sent && e.id > (view.heard_upto ?? -1);
    if (audio.currentTime > 0 || (cueSync && ((sent && sent.id === e.id) || unheard))) {
      const lead = wordAt(e, audio.currentTime + LEAD_S * (audio.playbackRate || 1));
      syncStage(e, Math.min(lead >= 0 ? e.words[lead][0] : -1, heldAt(e) - 1));
    }
    if (audio.currentTime > 0) caption(e, audio.currentTime);
    checkStop(e);
  }
  paintReader();
  const node = current && turnNodes.get(current.id), turn = node ? node.el : null;
  if (lastTurn && lastTurn !== turn) {
    lastTurn.classList.remove("reading");
    for (const w of lastTurn.querySelectorAll(".w.said, .w.now-word")) w.classList.remove("said", "now-word");
    lastK = -2;
  }
  lastTurn = turn;
  const reading = !!turn && k >= 0;
  if (turn) turn.classList.toggle("reading", reading);
  if (!reading) k = -1;
  if (k === lastK) return;
  lastK = k;
  const spans = readingSpans();
  for (let i = 0; i < spans.length; i++) spans[i].classList.toggle("said", i < k);
  if (lastWord) lastWord.classList.remove("now-word");
  lastWord = k >= 0 ? spans[k] || null : null;
  if (lastWord) { lastWord.classList.add("now-word"); followVoice(false); }
}

// ---- the player ---------------------------------------------------------------------
// One round button, the position and the time. It acts on the answer that plays, else the newest; while that answer's voice
// is being made the button turns. Speed, the sentence steps and everything else are keys or settings.
$("playpause").onclick = togglePlay;
$("seek").oninput = () => { audio.currentTime = Number($("seek").value); paintPill(); };
for (const ev of ["play", "pause", "ended", "durationchange", "loadedmetadata"]) audio.addEventListener(ev, paintAll);
audio.addEventListener("timeupdate", paintPill);
// The frame loop does not run in a tab out of sight: the audio's own timeupdate still does, so a hidden tab stops at a check too.
audio.addEventListener("timeupdate", () => { if (current) checkStop(view.entries.find(x => x.id === current.id) || current); });
audio.addEventListener("play", startHighlight);
for (const ev of ["pause", "ended"]) audio.addEventListener(ev, stopHighlight);
audio.addEventListener("seeked", () => { if (audio.paused) highlight(); });
function paintTransport() {
  const e = shownAnswer(), making = !!e && (e.speech === "pending" || e.speech === "making");
  const playable = !recorder && !!e && (e.speech === "ready" || making) && !view.ended;
  $("player").hidden = !playable;
  if (!playable) return;
  const pp = $("playpause");
  pp.disabled = making; pp.classList.toggle("making", making); pp.classList.toggle("playing", !audio.paused);
  const label = making ? tr("s.st.voice") : tr(!audio.paused ? "s.pp.pause" : "s.pp.play");
  if (pp.getAttribute("aria-label") !== label) { pp.setAttribute("aria-label", label); pp.title = label + (making ? "" : " · Space"); }
  const d = current ? audio.duration || 0 : 0, at = current ? audio.currentTime || 0 : 0;
  $("seek").max = d; $("seek").value = at; $("seek").disabled = !current;
  $("seek").style.setProperty("--p", (d ? 100 * at / d : 0) + "%");
  $("seek").setAttribute("aria-valuetext", current ? fmt(at) + " / " + fmt(d) : "");
  // while an answer is under way the time left; before it starts and after it ends its length
  $("time").textContent = !current || !d ? "" : at > 0 && at < d - 0.05 ? "−" + fmt(d - at) : fmt(d);
}

// ---- the hooks -----------------------------------------------------------------------
function relabelShell() { turnNodes.clear(); $("empty").textContent = tr("list.empty"); }
function render() {
  paintFront();
  paintCalls();
  paintAll();
  paintFront();
  if (audio.paused) highlight(); else paintReader();
}
// A new view arrived: `before` is the one it replaces. A question sent or an answer come brings the end of the list into view.
function shellOnView(before) {
  const count = (v, who) => (v.entries || []).filter((e) => e.who === who).length;
  if (count(view, "claude") > count(before, "claude") || count(view, "you") > count(before, "you")) {
    const first = before.v === -1;   // the page just opened: straight to the end, no glide through the whole call
    convoFollow = true; requestAnimationFrame(() => toBottom(first));
  }
}
