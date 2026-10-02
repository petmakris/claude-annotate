// skills/annotate/static/speech.js
/* Read-aloud: Explain (a spoken explanation Claude writes) and Read as
 * written (the selection itself), played in a card under the passage.
 *
 * The voice's words are not the page's words, so two things light up: each
 * word of the script as it is heard, and the page sentence the current piece
 * explains. Both are driven by audio.currentTime against Azure's word
 * boundaries, so pause, back-one-sentence and speed stay in sync with what
 * is heard. A wall clock would drift the moment anything paused.
 */
(function () {
  "use strict";

  const VOICES = {
    ava: "en-US-AvaMultilingualNeural", andrew: "en-US-AndrewMultilingualNeural",
    emma: "en-US-EmmaMultilingualNeural", brian: "en-US-BrianMultilingualNeural",
    sonia: "en-GB-SoniaNeural", ryan: "en-GB-RyanNeural",
  };
  const LIMIT = 4000;
  const SETUP_HINT = "Read-aloud needs Azure set up — run `webcompanion doctor`";
  const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
  const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>';
  const ICON_MORE = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

  const C = () => window.AnnotateSpeechClient;
  const A = () => window.AnnotateAnchors;
  let current = null;   // {card, audio, raf, section, t, mode, from, words, bounds, spans, script, starts, lit}

  // The Settings row "Read-aloud voice" (script.js) stores the short key.
  function voiceKey() {
    let v = null;
    try { v = localStorage.getItem("annotate.view:speechvoice"); } catch (_) {}
    return VOICES[v] ? v : "ava";
  }
  const voiceName = () => VOICES[voiceKey()];

  // A section open in the editor shows the editor, not its rendered text:
  // reading that hidden text aloud would read words the reader is changing.
  const CLOSE_EDITOR = "Close the editor to listen";
  const inEditor = (t) => !!(t && t.section && t.section.hasAttribute("data-editing"));

  function selectionText(t) {
    if (t.whole || !t.anchor) return A().textOf(A().contentOf(t.section)).trim();
    return t.anchor.selected_text;
  }

  // ── the menu buttons ────────────────────────────────────────────────────
  // On a phone the sheet leads with the two ways to listen, as wide labelled
  // buttons (spec §3.1); there is no chevron to find Read as written behind.
  function addButtons(t, menu) {
    const text = selectionText(t);
    const sheet = menu.classList.contains("sel-sheet");
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    const make = (act, html, title) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.act = act;
      b.innerHTML = html;
      b.title = title;
      b.setAttribute("aria-label", title);
      b.addEventListener("mousedown", stop);
      return b;
    };
    const explain = make("explain", ICON_PLAY + `<span>${sheet ? "Explain aloud" : "Explain"}</span>`, "Explain aloud (r)");
    explain.addEventListener("click", (e) => { stop(e); window.AnnotateSelection.close(); play(t, "explain"); });
    const makeRead = () => {
      const read = make("read", sheet ? "<span>Read as written</span>" : "Read as written", "Read as written (⇧r)");
      read.addEventListener("click", (ev) => { stop(ev); window.AnnotateSelection.close(); play(t, "read"); });
      return read;
    };
    let others;
    if (sheet) {
      const read = makeRead();
      explain.classList.add("sp-wide");
      read.classList.add("sp-wide");
      const first = menu.querySelector("button[data-act]");
      if (first) first.before(explain, read); else menu.append(explain, read);
      others = [read];
    } else {
      const more = make("voice-more", ICON_MORE, "More ways to listen");
      menu.append(explain, more);
      others = [more];
      more.addEventListener("click", (e) => {
        stop(e);
        if (menu.querySelector('[data-act="read"]')) return;
        const read = makeRead();
        read.tabIndex = -1;
        if (more.disabled) disableOne(read, more.title);
        more.after(read);
      });
    }

    const disableOne = (b, why) => { b.disabled = true; b.title = why; b.setAttribute("aria-label", why); };
    const disable = (why) => { for (const b of [explain, ...others]) disableOne(b, why); };
    if (inEditor(t)) disable(CLOSE_EDITOR);
    else if (text.length > LIMIT) disable("Select less than about a page");
    else C().status().then((s) => {
      if (!s.configured) disable(SETUP_HINT);
      else if (!s.claude) disableOne(explain, s.reason || "claude was not found");
    }).catch((e) => disable(`Read-aloud isn't available here (${e.status || e.message || e})`));
  }

  // ── the card ────────────────────────────────────────────────────────────
  function hostFor(t) {
    const content = A().contentOf(t.section);
    if (t.whole || !t.range) return content;
    const end = t.range.endContainer.nodeType === 1 ? t.range.endContainer : t.range.endContainer.parentElement;
    const block = end && end.closest("li, p, pre, blockquote, table");
    return block && content.contains(block) ? block : content;
  }

  function stop() {
    if (!current) return;
    const m = current;
    current = null;              // first: a synthesis still out sees it is no longer wanted
    cancelAnimationFrame(m.raf);
    try { m.audio.pause(); } catch (_) {}
    try { m.synth && m.synth.close(); } catch (_) {}
    for (const c of m.chunks || []) if (c.url) URL.revokeObjectURL(c.url);
    m.card.remove();
    A().setScope(null, "annotate-speaking");
  }

  // 50 ms of silence (8 kHz, 8-bit WAV). Safari lets an <audio> play later, after awaits, only
  // if it already played inside the reader's gesture: play() and pause() on
  // this, in the click, is that first play. Chromium allows the later play
  // either way (the click gave the page sticky activation), so this costs it
  // nothing. Every chunk plays through this one element, so the unlock holds.
  const SILENCE = "data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";
  function unlockedAudio(rate) {
    const audio = new Audio();
    // A new src resets playbackRate to the default: the default carries the
    // reader's speed from one chunk to the next.
    audio.defaultPlaybackRate = audio.playbackRate = rate;
    audio.src = SILENCE;
    try { audio.play()?.catch(() => {}); audio.pause(); } catch (_) {}
    return audio;
  }

  function buildCard(t, mode) {
    const card = document.createElement("div");
    card.className = "sp-card";
    // Focusable, and focused: Esc and Space reach the card from the moment it
    // opens, before Azure has answered.
    card.tabIndex = -1;
    card.innerHTML =
      `<div class="sp-head"><b>${mode === "explain" ? "Explained aloud" : "Read as written"}</b>`
      + `<span class="sp-voice"></span><button type="button" class="sp-x" aria-label="Stop and close">×</button></div>`
      + `<div class="sp-body"><span class="sp-wait"><i></i><i></i><i></i> `
      + `${mode === "explain" ? "Writing the explanation…" : "Preparing the reading…"}</span></div>`;
    const k = voiceKey();
    card.querySelector(".sp-voice").textContent = "· " + k[0].toUpperCase() + k.slice(1);
    card.querySelector(".sp-x").addEventListener("click", stop);
    const host = hostFor(t);
    if (host === A().contentOf(t.section) || host.tagName === "LI") host.appendChild(card);
    else host.insertAdjacentElement("afterend", card);
    card.focus({ preventScroll: true });
    return card;
  }

  // A line break ends a sentence too: list items and headings rarely carry a
  // full stop.
  function sentenceSplit(text) {
    const out = [];
    for (const line of text.split(/\n+/)) {
      const re = /[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g;
      let m;
      while ((m = re.exec(line))) if (m[0].trim()) out.push(m[0].trim());
    }
    return out;
  }

  // Must be entered synchronously from the reader's click or key: the audio
  // element is made and unlocked before the first await. `rate` carries the
  // speed across Retry and the mode switch.
  async function play(t, mode, rate, check) {
    if (inEditor(t)) { window.AnnotateEdit?.say?.(CLOSE_EDITOR); return; }
    rate = rate || current?.rate || 1;
    stop();
    // The page sentence being explained is lit from here on; a selection
    // left behind would sit over it, and reopen the menu on the next click.
    getSelection()?.removeAllRanges();
    const card = buildCard(t, mode);
    // Where the selection starts in the section's text, so a sentence the
    // section says twice is lit where it was selected.
    const at = t.anchor ? A().locate(t.section, t.anchor) : null;
    current = { card, audio: unlockedAudio(rate), rate, raf: 0, section: t.section, t, mode, from: at ? at[0] : 0 };
    const mine = current;
    const text = selectionText(t);
    const fallback = { sp: "fallback", label: "Read as written instead", run: () => play(t, "read", mine.rate) };
    // A key on a block has no menu button that was already checked: the same
    // checks happen here, and say why in the card.
    if (check) {
      if (text.length > LIMIT) return showError(card, "Too long to read aloud", "Select less than about a page");
      let st;
      try { st = await C().status(); }
      catch (e) {
        if (current === mine) showError(card, `Read-aloud isn't available here (${e.status || e.message || e})`, "");
        return;
      }
      if (current !== mine) return;
      if (!st.configured) return showError(card, SETUP_HINT, "");
      if (mode === "explain" && !st.claude) return showError(card, "Can't explain here", st.reason || "claude was not found", fallback);
    }
    let pieces;
    try {
      if (mode === "explain") {
        const ctx = C().pageContext(t.section);
        pieces = (await C().script({ selection: text, ...ctx })).pieces;
      } else {
        pieces = sentenceSplit(text).map((s) => ({ say: s, src: s }));
      }
    } catch (e) {
      if (current !== mine) return;
      return showError(card, "Couldn't write an explanation", e.message, fallback);
    }
    if (current !== mine) return;
    pieces = (pieces || []).filter((p) => p && typeof p.say === "string" && p.say.trim());
    if (!pieces.length) {
      return mode === "explain"
        ? showError(card, "Claude returned no explanation", "", fallback)
        : showError(card, "Nothing to read", "");
    }
    await speak(pieces, mine);
  }

  // The section a j/k cursor is on, with nothing selected (selection.js's `r`).
  function playSection(section, mode) {
    const t = { section, anchor: null, range: null, whole: true };
    if (inEditor(t)) { window.AnnotateEdit?.say?.(CLOSE_EDITOR); return true; }
    if (!selectionText(t)) return false;
    play(t, mode, null, true);
    return true;
  }

  function showError(card, title, detail, action) {
    const body = card.querySelector(".sp-body");
    const refocus = card.contains(document.activeElement);
    body.innerHTML = `<div class="sp-error"><b></b> <span></span></div>`;
    body.querySelector("b").textContent = title + ".";
    body.querySelector("span").textContent = detail || "";
    if (action) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sp-btn";
      b.dataset.sp = action.sp;
      b.textContent = action.label;
      b.addEventListener("click", action.run);
      body.appendChild(b);
      if (refocus) b.focus({ preventScroll: true });
    }
  }

  // ── chunks ──────────────────────────────────────────────────────────────
  // Azure answers only once all of a text's audio exists, about 8 s per
  // 1,000 characters. So the script goes in chunks cut at sentence ends: a
  // small first one (one or two sentences) that is heard within a couple of
  // seconds, then 600–800 characters at a time, synthesised one after the
  // other in the background while the earlier ones play. Each chunk is at
  // most twice the one before: Azure makes a chunk in about an eighth of the
  // time it takes to hear, so twice the text is ready before the last one
  // ends. A first chunk of 21 characters followed by 660 left 3.4 s of
  // silence at Azure's speed.
  const FIRST_MAX = 200, CHUNK_MAX = 800;

  // Where each sentence of the script starts, read from the script itself
  // (Azure's word boundaries never carry the full stop), and where each piece
  // starts: a piece is a sentence even without one.
  function sentenceStarts(script, spans) {
    const at = new Set([0]);
    for (const m of script.matchAll(/[.!?]+["')\]]*\s+/g)) at.add(m.index + m[0].length);
    for (const s of spans) at.add(s.start);
    return [...at].filter((x) => x < script.length).sort((a, b) => a - b);
  }

  function chunksOf(script, starts) {
    const out = [];
    let cur = null;
    starts.forEach((a, i) => {
      const b = i + 1 < starts.length ? starts[i + 1] : script.length;
      if (cur) {
        const prev = out.length ? out[out.length - 1] : null;
        const fits = !prev
          ? cur.n < 2 && b - cur.start <= FIRST_MAX
          : b - cur.start <= Math.min(CHUNK_MAX, 2 * script.slice(prev.start, prev.end).trimEnd().length);
        if (fits) { cur.end = b; cur.n++; return; }
        out.push(cur);
      }
      cur = { start: a, end: b, n: 1 };
    });
    if (cur) out.push(cur);
    return out.map((c) => ({ start: c.start, text: script.slice(c.start, c.end).trimEnd(), url: "", dur: NaN }));
  }

  // One chunk through Azure: its audio, its length, and its word boundaries
  // in that chunk's own audio clock and text.
  function synthesise(SDK, synth, text) {
    const bounds = [];
    synth.wordBoundary = (_s, e) => {
      // SpeechSynthesisBoundaryType.Word is the string "WordBoundary". Azure
      // sends punctuation as its own boundaries, and its word text carries
      // none; a boundary at no place in the text has nothing to light.
      if (e.boundaryType !== "WordBoundary" || !(e.textOffset >= 0)) return;
      bounds.push({ ms: e.audioOffset / 10000, off: e.textOffset });
    };
    return new Promise((ok, err) => synth.speakTextAsync(text, (r) => {
      if (r.reason === SDK.ResultReason.SynthesizingAudioCompleted) {
        ok({ data: r.audioData, bounds, dur: r.audioDuration > 0 ? r.audioDuration / 10000 : NaN });
      } else err(new Error(r.errorDetails || "synthesis did not complete"));
    }, (e) => err(new Error(String(e)))));
  }

  // A synthesised chunk joins the player: its audio as a blob, its boundaries
  // on the script's offsets, tagged with the chunk they are timed in.
  function accept(m, k, r) {
    const c = m.chunks[k];
    c.url = URL.createObjectURL(new Blob([r.data], { type: "audio/mpeg" }));
    c.dur = r.dur;
    for (const b of r.bounds) m.bounds.push({ k, ms: b.ms, off: c.start + b.off });
    if (!Number.isFinite(c.dur)) {
      // No length from Azure: the browser reads it from the audio itself.
      const probe = new Audio();
      probe.preload = "metadata";
      probe.addEventListener("loadedmetadata", () => {
        if (!Number.isFinite(c.dur) && Number.isFinite(probe.duration)) { c.dur = probe.duration * 1000; progress(m); }
      }, { once: true });
      probe.src = c.url;
    }
  }

  const httpDetail = (e) => {
    const msg = (e && e.message) || String(e);
    return e && e.status && !msg.includes(String(e.status)) ? `${msg} (HTTP ${e.status})` : msg;
  };

  async function speak(pieces, mine) {
    const card = mine.card;
    const retry = { sp: "retry", label: "Retry", run: () => play(mine.t, mine.mode, mine.rate) };
    let SDK, tok;
    try { SDK = await C().loadSdk(); tok = await C().token(); }
    catch (e) {
      if (current === mine) showError(card, "Azure didn't answer", httpDetail(e), retry);
      return;
    }
    if (current !== mine) return;

    let script = "";
    const spans = [];                                   // piece char ranges in the script
    pieces.forEach((p, i) => {
      if (i) script += " ";
      spans.push({ start: script.length, end: script.length + p.say.length, src: p.src });
      script += p.say;
    });
    const starts = sentenceStarts(script, spans);
    const chunks = chunksOf(script, starts);

    const cfg = SDK.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
    cfg.speechSynthesisVoiceName = voiceName();
    // Asked for explicitly, so the blob's type below is known rather than
    // assumed from Azure's default.
    cfg.speechSynthesisOutputFormat = SDK.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3;
    // null: the audio comes back as data for an <audio> element to play,
    // whose clock drives the highlight; the SDK's own speaker output would
    // not. One synthesizer, one connection, for every chunk in turn.
    const synth = new SDK.SpeechSynthesizer(cfg, null);
    Object.assign(mine, { SDK, synth, chunks, bounds: [], spans, script, starts, k: 0, waiting: false });

    let first;
    try { first = await synthesise(SDK, synth, chunks[0].text); }
    catch (e) {
      try { synth.close(); } catch (_) {}
      if (current === mine) showError(card, "Azure didn't answer", e.message, retry);
      return;
    }
    if (current !== mine) return;
    accept(mine, 0, first);

    // The script, one span per word, each knowing its offset in the script.
    const body = card.querySelector(".sp-body");
    body.innerHTML = `<div class="sp-script"></div><div class="sp-ctl"></div>`;
    const box = body.querySelector(".sp-script");
    const words = [];
    for (const m of script.matchAll(/\S+/g)) {
      const w = document.createElement("span");
      w.className = "w";
      w.textContent = m[0];
      if (words.length) box.append(" ");
      box.append(w);
      words.push({ el: w, off: m.index });
    }
    box.classList.add("playing");
    mine.words = words;

    const audio = mine.audio;
    card.appendChild(audio);
    const refocus = card.contains(document.activeElement);
    buildControls(body.querySelector(".sp-ctl"), mine);
    if (refocus) card.querySelector('[data-sp="toggle"]').focus({ preventScroll: true });
    // The rAF loop runs only while the audio plays; paused or ended, the
    // page is painted once and left alone.
    audio.addEventListener("play", () => { setToggle(mine); loop(mine); });
    audio.addEventListener("pause", () => { cancelAnimationFrame(mine.raf); setToggle(mine); if (!audio.ended) frame(mine); });
    audio.addEventListener("seeked", () => { if (audio.paused) frame(mine); });
    audio.addEventListener("loadedmetadata", () => {
      const c = mine.chunks[mine.k];
      if (c && Number.isFinite(audio.duration) && audio.currentSrc === c.url) c.dur = audio.duration * 1000;
      progress(mine);
    });
    // The end of a chunk is the start of the next, at once if it is ready;
    // if it is not, the card waits for it and plays it the moment it is.
    audio.addEventListener("ended", () => {
      if (current !== mine) return;
      const next = mine.k + 1;
      if (next < mine.chunks.length && !mine.chunks[next].failed) {
        if (mine.chunks[next].url) load(mine, next, 0, true);
        else { mine.waiting = true; setToggle(mine); progress(mine); }
        return;
      }
      finish(mine);
    });
    load(mine, 0, 0, true);
    await pump(mine, 1);
  }

  // The rest, one at a time, while the earlier ones play.
  async function pump(mine, from) {
    const chunks = mine.chunks;
    for (let k = from; k < chunks.length; k++) {
      let r;
      try { r = await synthesise(mine.SDK, mine.synth, chunks[k].text); }
      catch (e) {
        if (current !== mine) return;
        try { mine.synth.close(); } catch (_) {}
        mine.synth = null;
        failAt(mine, k, e.message);
        return;
      }
      if (current !== mine) return;          // closed, switched or retried meanwhile
      accept(mine, k, r);
      if (mine.waiting && mine.k + 1 === k) { mine.waiting = false; setToggle(mine); load(mine, k, 0, true); }
      progress(mine);
    }
    try { mine.synth.close(); } catch (_) {}
    mine.synth = null;
  }

  // A later chunk failed: what was heard stays, the total stops at what was
  // made, and Retry carries on from that chunk.
  function failAt(m, k, detail) {
    m.chunks[k].failed = true;
    m.failedAt = k;
    tailError(m, detail, { sp: "retry", label: "Retry", run: () => resume(m, k) });
    if (m.waiting) { m.waiting = false; finish(m); }
    setToggle(m);
    progress(m);
  }

  async function resume(m, k) {
    if (current !== m) return;
    m.card.querySelectorAll(".sp-tail").forEach((e) => e.remove());
    delete m.chunks[k].failed;
    m.failedAt = undefined;
    // Heard up to the failed chunk already: it plays the moment it is made.
    if (m.k === k - 1 && m.audio.ended) m.waiting = true;
    setToggle(m);
    progress(m);
    let tok;
    try { tok = await C().token(); }
    catch (e) { if (current === m) failAt(m, k, httpDetail(e)); return; }
    if (current !== m) return;
    const cfg = m.SDK.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
    cfg.speechSynthesisVoiceName = voiceName();
    cfg.speechSynthesisOutputFormat = m.SDK.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3;
    m.synth = new m.SDK.SpeechSynthesizer(cfg, null);
    await pump(m, k);
  }

  function tailError(m, detail, action) {
    const body = m.card.querySelector(".sp-body");
    const div = document.createElement("div");
    div.className = "sp-error sp-tail";
    div.innerHTML = "<b>Azure stopped answering.</b> <span></span>";
    div.querySelector("span").textContent = `The rest could not be read — ${detail}`;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sp-btn";
    b.dataset.sp = action.sp;
    b.textContent = action.label;
    b.addEventListener("click", action.run);
    div.appendChild(b);
    body.appendChild(div);
  }

  // Chunk k into the one player, at `ms` into it.
  function load(m, k, ms, go) {
    const c = m.chunks[k];
    m.k = k;
    if (m.audio.getAttribute("src") !== c.url) m.audio.src = c.url;
    m.audio.currentTime = (ms || 0) / 1000;
    if (go) m.audio.play().catch(() => {});
    else frame(m);
  }

  const playing = (m) => !m.audio.paused && !m.audio.ended;

  // The last boundary at or before ms into chunk k.
  function boundaryAt(m, k, ms) {
    const before = (b) => b.k < k || (b.k === k && b.ms <= ms);
    let lo = 0, hi = m.bounds.length - 1, idx = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (before(m.bounds[mid])) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
    return idx;
  }
  const here = (m) => boundaryAt(m, m.k, m.audio.currentTime * 1000);

  function light(m, piece) {
    if (piece === m.lit) return;
    m.lit = piece;
    if (!piece || !piece.src) return A().setScope(null, "annotate-speaking");
    // From where the selection starts first, so a sentence said twice in the
    // section is lit where it was selected; anywhere in the section if
    // Claude's src lies outside the selection. locate folds whitespace, so a
    // src copied across a line break still lands.
    const want = { selected_text: piece.src };
    const span = A().locate(m.section, want, m.from) || A().locate(m.section, want);
    A().setScope(span ? A().rangeFrom(A().contentOf(m.section), span[0], span[1]) : null, "annotate-speaking");
  }

  function paint(m, bi) {
    const off = bi >= 0 ? m.bounds[bi].off : -1;
    let wi = -1;
    for (let i = 0; i < m.words.length; i++) if (m.words[i].off <= off) wi = i;
    m.words.forEach((w, i) => { w.el.classList.toggle("now", i === wi); w.el.classList.toggle("done", i < wi); });
    light(m, off >= 0 ? m.spans.find((s) => off >= s.start && off < s.end) : null);
  }

  function finish(m) {
    cancelAnimationFrame(m.raf);
    // Everything up to the end of the last chunk heard; a chunk Azure never
    // sent was not heard.
    const c = m.chunks[m.k];
    const end = c ? c.start + c.text.length : Infinity;
    m.words.forEach((w) => { w.el.classList.remove("now"); w.el.classList.toggle("done", w.off < end); });
    light(m, null);
    setToggle(m);
    progress(m);
  }

  // Elapsed counts every chunk before the one playing. The total grows as
  // chunks arrive and reads "…" until the last one's length is known.
  const mmss = (s) => { s = Math.max(0, s | 0); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  function progress(m) {
    const bar = m.card.querySelector('[data-sp="progress"]');
    if (!bar || !m.chunks) return;
    // Up to a failed chunk, the total is what was made.
    const durs = m.chunks.slice(0, m.failedAt ?? m.chunks.length).map((c) => c.dur);
    const known = durs.every(Number.isFinite);
    const sum = durs.reduce((a, d) => a + (Number.isFinite(d) ? d : 0), 0) / 1000;
    let before = 0;
    for (let i = 0; i < m.k; i++) before += Number.isFinite(durs[i]) ? durs[i] / 1000 : 0;
    const d = Number.isFinite(m.audio.duration) ? m.audio.duration : (durs[m.k] || 0) / 1000;
    const done = known && m.audio.ended && !m.waiting && m.k === durs.length - 1;
    const t = done ? sum : before + (m.audio.ended ? d : Math.min(m.audio.currentTime, d || Infinity));
    bar.querySelector("i").style.width = sum ? `${Math.min(100, 100 * t / sum).toFixed(1)}%` : "0%";
    bar.setAttribute("aria-valuemax", String(Math.round(sum)));
    bar.setAttribute("aria-valuenow", String(Math.floor(t)));
    // Waiting for a chunk: no time is passing, and the card says so.
    m.card.querySelector(".sp-time").textContent = m.waiting ? "…"
      : `${mmss(done ? Math.round(sum) : t)} / ${known ? mmss(Math.round(sum)) : "…"}`;
  }

  // A rewrite can replace the section, or only its contents (and the card
  // with them): either way what was being explained is gone.
  function gone(m) { return !document.contains(m.section) || !document.contains(m.card); }

  function frame(m) {
    if (current !== m) return false;
    if (gone(m)) { stop(); return false; }
    if (!m.words) return true;
    paint(m, here(m));
    progress(m);
    return true;
  }

  function loop(m) {
    cancelAnimationFrame(m.raf);
    const tick = () => {
      if (m.audio.paused || m.audio.ended || !frame(m)) return;
      m.raf = requestAnimationFrame(tick);
    };
    m.raf = requestAnimationFrame(tick);
  }

  function setToggle(m) {
    const b = m.card.querySelector('[data-sp="toggle"]');
    if (!b) return;
    if (m.waiting) { b.innerHTML = "<span>Preparing…</span>"; b.setAttribute("aria-label", "Preparing the next part — press to cancel"); return; }
    b.removeAttribute("aria-label");
    const on = playing(m);
    b.innerHTML = (on ? ICON_PAUSE : ICON_PLAY) + `<span>${on ? "Pause" : "Play"}</span>`;
  }

  function toggle(m) {
    if (playing(m)) m.audio.pause();
    else if (m.waiting) m.waiting = false;              // no longer wanted when it arrives
    else if (m.audio.ended) {
      const next = m.k + 1;
      if (next >= m.chunks.length || m.chunks[next].failed) load(m, 0, 0, true);   // again from the top
      else if (m.chunks[next].url) load(m, next, 0, true);
      else m.waiting = true;
    } else m.audio.play().catch(() => {});
    setToggle(m);
    progress(m);
  }

  // To the start of the sentence being heard, or of the one before it when
  // its first word is the one being heard: so a second press goes further
  // back, into the chunk before if that is where it starts. Counted in
  // words, not milliseconds: at a normal pace a whole second word is under
  // way within half a second.
  function backOneSentence(m) {
    const go = playing(m) || m.waiting;
    m.waiting = false;
    const bi = here(m);
    if (bi < 0) { load(m, 0, 0, go); return; }
    const sentenceOf = (off) => { let k = 0; m.starts.forEach((s, j) => { if (s <= off) k = j; }); return k; };
    const firstWordOf = (k) => { const i = m.bounds.findIndex((b) => b.off >= m.starts[k]); return i < 0 ? 0 : i; };
    const k = sentenceOf(m.bounds[bi].off);
    let s = firstWordOf(k);
    if (s === bi && k > 0) s = firstWordOf(k - 1);
    const b = m.bounds[s];
    if (b.k === m.k && m.audio.getAttribute("src") === m.chunks[b.k].url) {
      m.audio.currentTime = b.ms / 1000;
      if (go && m.audio.paused) m.audio.play().catch(() => {});
    } else load(m, b.k, b.ms, go);
    paint(m, s);
    progress(m);
    setToggle(m);
  }

  function buildControls(ctl, m) {
    const rates = ["0.85", "1", "1.2"];
    ctl.innerHTML =
      `<button type="button" class="sp-btn primary" data-sp="toggle"></button>`
      + `<button type="button" class="sp-btn" data-sp="back" aria-label="Back one sentence" title="Back one sentence">⟲</button>`
      + `<div class="sp-bar" data-sp="progress" role="progressbar" aria-label="Elapsed" aria-valuemin="0"><i></i></div>`
      + `<span class="sp-time">0:00 / …</span>`
      + `<div class="sp-seg" data-sp="speed" role="group" aria-label="Speed">`
      + rates.map((r) => `<button type="button" data-rate="${r}" aria-pressed="${Number(r) === m.rate}">${r}×</button>`).join("")
      + `</div>`
      + `<div class="sp-seg" data-sp="mode" role="group" aria-label="Listen to">`
      + `<button type="button" data-mode="explain">Explain</button>`
      + `<button type="button" data-mode="read">Read as written</button></div>`;
    ctl.querySelector('[data-sp="toggle"]').addEventListener("click", () => toggle(m));
    ctl.querySelector('[data-sp="back"]').addEventListener("click", () => backOneSentence(m));
    ctl.querySelectorAll('[data-sp="speed"] button').forEach((b) => b.addEventListener("click", () => {
      m.rate = Number(b.dataset.rate);
      m.audio.defaultPlaybackRate = m.audio.playbackRate = m.rate;
      ctl.querySelectorAll('[data-sp="speed"] button').forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    }));
    // The same selection the other way, at the same speed. The explanation
    // is cached by the client, so switching back does not ask Claude again.
    ctl.querySelectorAll('[data-sp="mode"] button').forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === m.mode));
      b.addEventListener("click", () => { if (b.dataset.mode !== m.mode) play(m.t, b.dataset.mode, m.rate); });
    });
    setToggle(m);
    progress(m);
  }

  // ── keys ────────────────────────────────────────────────────────────────
  // On window, in the capture phase: ahead of maximize.js (document,
  // capture), so one Esc stops the reading and leaves a maximised card open.
  // Esc is taken only while a card is open, and only from the card or from
  // nowhere in particular (the body, with no selection menu up).
  window.addEventListener("keydown", (ev) => {
    if (!current || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const a = document.activeElement;
    const inCard = current.card.contains(a);
    if (ev.key === "Escape") {
      const idle = (!a || a === document.body) && !window.AnnotateSelection?.isOpen();
      if (!inCard && !idle) return;
      ev.preventDefault();
      ev.stopPropagation();
      stop();
      return;
    }
    // Space on one of the card's buttons is that button's own click.
    if (ev.key === " " && inCard && !(a instanceof HTMLButtonElement)) {
      ev.preventDefault();
      if (current.words) toggle(current);
    }
  }, true);
  document.addEventListener("annotate:rendered", () => { if (current && gone(current)) stop(); });

  if (window.AnnotateSelection) window.AnnotateSelection.registerAction(addButtons);
  window.AnnotateSpeech = { play, playSection, stop, isPlaying: () => !!current };
})();
