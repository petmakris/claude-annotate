// Layout audit for a 1280x720 deck. Every slide is `overflow:hidden`, so anything
// that runs past the canvas disappears silently instead of failing loudly — and a
// block that stops 300px short looks like a mistake nobody reported. This measures
// both, plus a third failure neither one sees: two positioned siblings occupying the
// same space. All in the only place the answer is real: a browser that has done the
// layout.
//
// The third check exists because it caught a real bug the other two missed. A
// two-line `.dname` on a divider printed straight through the `.drule` and the
// `.dtag` beneath it — nothing overflowed the canvas, no gap opened, and the slide
// was broken. Anything absolutely positioned against a fixed canvas can collide with
// its neighbour, and the deck's components assume a height they do not enforce.
//
// Paste as the `function` argument of a Playwright `browser_evaluate` call, or in
// DevTools wrap the paste in `( ... )()` to run it.
//
// Three exclusions are deliberate, not oversights:
//   .num    — the gutter marker, pinned at left:-46px OUTSIDE the canvas on purpose
//   .pg     — the page counter, injected at runtime
//   .ghost  — the divider's giant background numeral, deliberately bled off the canvas
//             at top:-66px AND deliberately sitting behind .dname
// Counting any of them reports a problem on every slide in every deck that has one.

() => {
  const OVERFLOW_TOLERANCE = 1;   // px — sub-pixel rounding, not a real overflow
  const DEAD_BAND = 60;           // px — a gap larger than this is worth a look
  const OVERLAP_TOLERANCE = 2;    // px — borders and shadows touch; real collisions are bigger

  const deck = document.querySelector('.deck');
  deck.style.zoom = '1';          // the harness fits the deck to the window; undo it

  const skip = el => el.classList.contains('num')
                  || el.classList.contains('pg')
                  || el.classList.contains('ghost');
  const name = el => (el.className || el.tagName).toString().trim().slice(0, 30);

  const report = [];

  document.querySelectorAll('.slide').forEach((slide, i) => {
    const s = slide.getBoundingClientRect();
    const overflow = [];
    const blocks = [];

    // 1 · overflow — every descendant, against the slide rect
    slide.querySelectorAll('*').forEach(el => {
      if (skip(el)) return;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;          // display:none, empty spacers
      const out = {
        left:   Math.round(s.left - r.left),
        right:  Math.round(r.right - s.right),
        top:    Math.round(s.top - r.top),
        bottom: Math.round(r.bottom - s.bottom),
      };
      const worst = Math.max(out.left, out.right, out.top, out.bottom);
      if (worst > OVERFLOW_TOLERANCE) overflow.push({ el: name(el), ...out });
    });

    // 2 · dead bands — direct children only, sorted top to bottom
    Array.from(slide.children).forEach(el => {
      if (skip(el)) return;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      blocks.push({
        el: name(el),
        top: Math.round(r.top - s.top),
        bottom: Math.round(r.bottom - s.top),
      });
    });
    blocks.sort((a, b) => a.top - b.top);

    const gaps = [];
    let prev = null;
    for (const b of blocks) {
      if (prev && b.top - prev.bottom > DEAD_BAND) {
        gaps.push({ between: `${prev.el} → ${b.el}`, px: b.top - prev.bottom });
      }
      if (!prev || b.bottom > prev.bottom) prev = b;   // track the lowest edge so far
    }
    if (prev && 720 - prev.bottom > DEAD_BAND) {
      gaps.push({ between: `${prev.el} → floor`, px: 720 - prev.bottom });
    }

    // 3 · collisions — positioned siblings sharing space
    const boxes = [];
    slide.querySelectorAll('*').forEach(el => {
      if (skip(el)) return;
      if (getComputedStyle(el).position !== 'absolute') return;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) boxes.push({ el, r });
    });

    const collisions = [];
    for (let a = 0; a < boxes.length; a++) {
      for (let b = a + 1; b < boxes.length; b++) {
        const A = boxes[a], B = boxes[b];
        if (A.el.contains(B.el) || B.el.contains(A.el)) continue;   // nesting is not collision
        const x = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
        const y = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
        if (x > OVERLAP_TOLERANCE && y > OVERLAP_TOLERANCE) {
          collisions.push({
            between: `${name(A.el)} × ${name(B.el)}`,
            px: `${Math.round(x)}×${Math.round(y)}`,
          });
        }
      }
    }

    report.push({ slide: i + 1, overflow, gaps, collisions });
  });

  return JSON.stringify(report, null, 1);
}
