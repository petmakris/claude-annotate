(function () {
  const slides = Array.from(document.querySelectorAll('.slide'));
  const deck = document.querySelector('.deck');
  let i = 0, on = false;

  slides.forEach((sl, k) => {
    const pg = document.createElement('div');
    pg.className = 'pg';
    pg.textContent = (k + 1) + ' / ' + slides.length;
    sl.appendChild(pg);
    const num = sl.querySelector('.num');
    if (num) num.textContent = (k + 1);
  });

  function fit() {
    const s = Math.min(window.innerWidth / 1280, window.innerHeight / 720);
    document.documentElement.style.setProperty('--present-scale', s);
  }
  function applyZoom() {
    if (on) { deck.style.zoom = '1'; return; }
    const byW = (window.innerWidth - 80) / 1280;
    const byH = (window.innerHeight - 80) / 720;
    deck.style.zoom = Math.max(0.5, Math.min(byW, byH, 1.5));
  }
  // Progressive reveal. In present mode a `.frag` element stays hidden until
  // its step comes up. `data-frag="n"` sets the step; elements sharing a number
  // appear together (a callout and its legend line). Without it, each .frag is
  // its own step in document order. The scrolling view and the PDF export never
  // hide anything: the rule in deck.css only applies under body.present.
  const fragSteps = slides.map(sl => {
    const frags = Array.from(sl.querySelectorAll('.frag'));
    frags.forEach((f, k) => { f._fragKey = f.dataset.frag !== undefined ? parseFloat(f.dataset.frag) : 1e6 + k; });
    const keys = Array.from(new Set(frags.map(f => f._fragKey))).sort((a, b) => a - b);
    frags.forEach(f => { f._fragStep = keys.indexOf(f._fragKey); });
    return { frags, total: keys.length };
  });
  let step = 0;
  function applyFrags() {
    const fs = fragSteps[i];
    fs.frags.forEach(f => {
      f.classList.toggle('frag-on', f._fragStep < step);
      f.classList.toggle('frag-current', f._fragStep === step - 1);
    });
  }
  function show(n, revealAll) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((sl, k) => sl.classList.toggle('current', k === i));
    step = revealAll ? fragSteps[i].total : 0;
    applyFrags();
  }
  function advance() {
    if (step < fragSteps[i].total) { step++; applyFrags(); return; }
    if (i < slides.length - 1) show(i + 1);
  }
  function retreat() {
    if (step > 0) { step--; applyFrags(); return; }
    if (i > 0) show(i - 1, true);
  }
  // Previous/next slide outside present mode: there is no single "current"
  // slide in the normal scrolling view, so step from whichever slide is
  // nearest the viewport centre and scroll smoothly to the next one.
  function stepSlide(delta) {
    if (on) { delta > 0 ? advance() : retreat(); return; }
    const next = Math.max(0, Math.min(slides.length - 1, nearestToViewportCenter() + delta));
    slides[next].scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  function nearestToViewportCenter() {
    const mid = window.innerHeight / 2;
    let best = 0, bestD = Infinity;
    slides.forEach((sl, k) => {
      const r = sl.getBoundingClientRect();
      const d = Math.abs(r.top + r.height / 2 - mid);
      if (d < bestD) { bestD = d; best = k; }
    });
    return best;
  }
  function enter(at) {
    const start = at === undefined ? nearestToViewportCenter() : at;
    on = true;
    document.body.classList.add('present');
    deck.style.zoom = '1';
    fit();
    show(start);
    const el = document.documentElement;
    if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
  }
  function exit() {
    on = false;
    document.body.classList.remove('present');
    slides.forEach(sl => sl.classList.remove('current'));
    applyZoom();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    slides[i] && slides[i].scrollIntoView({ block: 'center' });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      // Present mode without fullscreen (opened at #present) goes fullscreen
      // first; only a second F leaves.
      if (on && !document.fullscreenElement && document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => exit());
      } else { on ? exit() : enter(); }
      return;
    }
    // All four arrows move to the previous/next slide everywhere, not just in
    // full-screen present mode — outside it, stepSlide() scrolls instead of
    // switching a "current" slide. Skipped while typing (e.g. a comment box)
    // so the deck doesn't steal the keystroke from a text field. Up/Down also
    // give up the browser's native small-scroll nudge on the plain page —
    // deliberate: mouse wheel, trackpad and Page Up/Down are unaffected, and
    // every arrow meaning the same thing matches how Keynote/PowerPoint/
    // reveal.js already behave.
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    if (!typing && (e.key === 'ArrowRight' || e.key === 'ArrowDown' ||
                     e.key === 'ArrowLeft' || e.key === 'ArrowUp')) {
      e.preventDefault();
      stepSlide((e.key === 'ArrowRight' || e.key === 'ArrowDown') ? 1 : -1);
      return;
    }
    if (!on) return;
    if (e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); advance(); }
    else if (e.key === 'PageUp') { e.preventDefault(); retreat(); }
    else if (e.key === 'Home') { e.preventDefault(); show(0); }
    else if (e.key === 'End') { e.preventDefault(); show(slides.length - 1); }
    else if (e.key === 'Escape') { exit(); }
  });
  window.addEventListener('resize', () => { on ? fit() : applyZoom(); });
  applyZoom();
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && on) exit();
  });

  const btn = document.createElement('button');
  btn.className = 'present-btn';
  btn.textContent = '▶ Present';
  btn.title = 'Full-screen present (F). ←/→ or Space to move (one reveal at a time), Esc to exit.';
  btn.onclick = () => enter();
  document.body.appendChild(btn);

  // Opened as deck.html#present or #present-4: straight into present mode at
  // that slide. Fullscreen needs a user gesture, so it is refused here and the
  // presentation fills the window instead; F or the browser's own fullscreen
  // key takes it the rest of the way.
  const start = location.hash.match(/^#present(?:-(\d+))?$/);
  if (start) enter(Math.max(0, Math.min(slides.length - 1, (Number(start[1]) || 1) - 1)));
})();
