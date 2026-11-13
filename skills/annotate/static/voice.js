// skills/annotate/static/voice.js
/* Dictation into annotate's comment boxes, through Azure speech-to-text.
 *
 * The 🎤 sits in every comment box (the section card's submit row and the
 * span comment box). Words still being recognised show in grey beside the
 * field; when Azure finalises a phrase it is inserted at the caret and an
 * `input` event is dispatched, so draft saving, auto-grow and the span box's
 * Submit lock behave exactly as if it had been typed. The page's glossary
 * terms are given to Azure as a phrase list, so the document's own vocabulary
 * is recognised.
 *
 * Azure replaces the browser's SpeechRecognition, which only Chrome had and
 * which refused the .mac domains.
 */
(function () {
  "use strict";

  const SETUP_HINT = "Dictation needs Azure set up — run `webcompanion doctor`";
  // The token lasts 540 s. While listening, it is looked at every 30 s and
  // replaced once less than 90 s of it is left, so a long session keeps going.
  const REFRESH_EVERY_MS = 30000, REFRESH_WITHIN_MS = 90000;
  let active = null;   // {rec, btn, ta, interim, timer}
  let attempt = 0;     // bumped by every press, so a slow start can tell it was cancelled

  // Azure wants a full locale. A browser can say only "el" or "fr": those
  // get the country most of their speakers dictate in, and a bare code
  // Azure is not known to take falls back to US English.
  const FULL = {
    el: "el-GR", en: "en-US", fr: "fr-FR", de: "de-DE", es: "es-ES", it: "it-IT", pt: "pt-PT",
    nl: "nl-NL", sv: "sv-SE", da: "da-DK", nb: "nb-NO", fi: "fi-FI", pl: "pl-PL", cs: "cs-CZ",
    ru: "ru-RU", uk: "uk-UA", tr: "tr-TR", ja: "ja-JP", ko: "ko-KR", zh: "zh-CN", ar: "ar-SA",
    he: "he-IL", hi: "hi-IN",
  };
  function fullLocale(l) {
    if (!l) return "en-US";
    if (l.includes("-")) return l;
    return FULL[l.toLowerCase()] || "en-US";
  }
  function language() {
    let v = null;
    try { v = localStorage.getItem("annotate.view:dictationlang"); } catch (_) {}
    if (v && v !== "auto") return fullLocale(v);
    return fullLocale(navigator.language);
  }

  function insertAtCaret(ta, text) {
    const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? ta.value.length;
    const before = ta.value.slice(0, s), after = ta.value.slice(e);
    const padL = before && !/\s$/.test(before) ? " " : "";
    const padR = after && !/^\s/.test(after) ? " " : "";
    // setRangeText keeps the textarea's own undo stack where the browser has one.
    ta.setRangeText(padL + text + padR, s, e, "end");
    if (padR) ta.setSelectionRange(ta.selectionEnd - 1, ta.selectionEnd - 1);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // Why a running recognizer stopped. A refused or missing microphone
  // reaches the SDK as getUserMedia's NotAllowedError / NotFoundError inside
  // its details ("Error occurred during microphone initialization: …"),
  // whatever code it is filed under, so the details are read first. Every
  // other CancellationErrorCode is Azure's side.
  const MIC = /NotAllowedError|NotFoundError|NotReadableError|SecurityError|Permission denied|microphone|getUserMedia|audio context/i;
  const AZURE_CODES = ["AuthenticationFailure", "BadRequestParameters", "TooManyRequests", "ConnectionFailure",
    "ServiceTimeout", "ServiceError", "Forbidden"];
  // CancellationErrorCode's values in the vendored SDK (1.x), for a code
  // that arrives without the enum to hand.
  const CODE_NAMES = { 1: "AuthenticationFailure", 2: "BadRequestParameters", 3: "TooManyRequests",
    4: "ConnectionFailure", 5: "ServiceTimeout", 6: "ServiceError", 7: "RuntimeError", 8: "Forbidden" };
  function explainCancel(SDK, details, code) {
    const enumName = SDK && SDK.CancellationErrorCode && code != null ? SDK.CancellationErrorCode[code] : null;
    const name = (typeof enumName === "string" && enumName) || CODE_NAMES[code] || "";
    if (!details && !name) return "Microphone blocked — the microphone was refused";
    if (MIC.test(details)) return "Microphone blocked — " + details;
    const why = details || name;
    if (AZURE_CODES.includes(name)) return "Azure didn't answer — " + why + " · press 🎤 to retry";
    return "Dictation stopped — " + why + " · press 🎤 to retry";
  }

  function note(interim, text) { interim.textContent = text; interim.classList.add("voice-note"); }

  // A press that is still loading the SDK and token: a second press cancels it.
  let pending = null;   // the button whose start has not finished

  function stopActive() {
    attempt++;
    pending = null;
    if (!active) return;
    const a = active;
    active = null;
    clearInterval(a.timer);
    clearInterval(a.live);
    try { a.rec.stopContinuousRecognitionAsync(() => a.rec.close(), () => a.rec.close()); } catch (_) {}
    a.btn.classList.remove("listening");
    a.btn.setAttribute("aria-pressed", "false");
    a.interim.textContent = "";
  }

  // The box went away under the recognizer (Submit, Cancel, a rewrite): the
  // microphone must not stay open for a field nobody can see.
  function stopIfOrphaned() { if (active && !active.ta.isConnected) stopActive(); }

  async function start(ta, btn, interim) {
    stopActive();
    // Read-aloud and dictation do not talk over each other.
    try { window.AnnotateSpeech?.stop(); } catch (_) {}
    const mine = attempt;
    pending = btn;
    interim.textContent = "";
    interim.classList.remove("voice-note");
    const C = window.AnnotateSpeechClient;
    const say = (text) => { note(interim, text); btn.title = text; };
    let SDK, rec, cfg, tok;
    try {
      SDK = await C.loadSdk();
      tok = await C.token();
    } catch (e) {
      if (mine !== attempt) return;
      pending = null;
      say("Azure didn't answer — " + ((e && (e.message || e.name)) || String(e)) + " · press 🎤 to retry");
      return;
    }
    if (mine !== attempt) return;            // pressed again while Azure was loading
    try {
      cfg = SDK.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
      cfg.speechRecognitionLanguage = language();
      rec = new SDK.SpeechRecognizer(cfg, SDK.AudioConfig.fromDefaultMicrophoneInput());
      const phrases = SDK.PhraseListGrammar.fromRecognizer(rec);
      const section = ta.closest("section.block");
      for (const g of (C.pageContext(section).glossary || [])) if (g && g.term) phrases.addPhrase(g.term);
    } catch (e) {
      if (mine !== attempt) return;
      pending = null;
      say("Dictation could not start — " + ((e && (e.message || e.name)) || String(e)));
      try { rec && rec.close(); } catch (_) {}
      return;
    }
    if (!ta.isConnected) { try { rec.close(); } catch (_) {} pending = null; return; }
    pending = null;
    rec.recognizing = (_r, e) => { if (ta.isConnected) interim.textContent = e.result.text; };
    rec.recognized = (_r, e) => {
      if (!ta.isConnected) return stopActive();
      interim.textContent = "";
      if (e.result.reason === SDK.ResultReason.RecognizedSpeech && e.result.text) insertAtCaret(ta, e.result.text);
    };
    // Only for the recognizer still listening: a cancel that arrives after
    // it was stopped, or replaced by a newer press, says nothing.
    const fail = (why, code) => {
      if (!active || active.rec !== rec) return;
      stopActive();
      say(explainCancel(SDK, why, code));
    };
    rec.canceled = (_r, e) => fail(e.errorDetails || "", e.errorCode);
    const timer = setInterval(async () => {
      try {
        const fresh = await C.token(REFRESH_WITHIN_MS);
        if (active && active.rec === rec && rec.authorizationToken !== fresh.token) rec.authorizationToken = fresh.token;
      } catch (_) { /* the next tick tries again; the old token may still have time */ }
    }, REFRESH_EVERY_MS);
    const live = setInterval(stopIfOrphaned, 1000);
    active = { rec, btn, ta, interim, timer, live };
    btn.classList.add("listening");
    btn.setAttribute("aria-pressed", "true");
    btn.title = "Stop dictating";
    rec.startContinuousRecognitionAsync(null, (err) => fail(String(err && (err.message || err))));
  }

  function makeMic(ta) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "voice-mic-btn";
    btn.textContent = "🎤";
    btn.title = "Dictate (speech to text)";
    btn.setAttribute("aria-label", "Dictate comment");
    btn.setAttribute("aria-pressed", "false");
    const interim = document.createElement("span");
    interim.className = "voice-interim";
    interim.setAttribute("aria-live", "polite");
    const off = (why) => { btn.disabled = true; btn.title = why || SETUP_HINT; };
    const C = window.AnnotateSpeechClient;
    if (C) C.status().then((s) => { if (!s.configured) off(); })
      .catch((e) => off(`Dictation isn't available here (${e.status || e.message || e})`));
    else off();
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if ((active && active.btn === btn) || pending === btn) stopActive(); else start(ta, btn, interim);
    });
    return { btn, interim };
  }

  function attach(row) {
    if (row.querySelector(".voice-mic-btn")) return;
    const box = row.closest(".comment-window");
    const ta = box && box.querySelector("textarea");
    if (!ta) return;
    const { btn, interim } = makeMic(ta);
    const submit = row.querySelector(".card-submit-btn");
    row.insertBefore(interim, row.firstChild ? row.firstChild.nextSibling : null);
    if (submit) row.insertBefore(btn, submit); else row.appendChild(btn);
  }

  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.matches(".card-submit-row, .sel-row")) attach(root);
    root.querySelectorAll(".card-submit-row, .sel-row").forEach(attach);
  }
  new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) scan(n); stopIfOrphaned(); })
    .observe(document.body, { childList: true, subtree: true });
  scan(document.body);
  window.addEventListener("pagehide", stopActive);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") stopActive(); });
})();
