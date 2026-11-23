// annotate — where the comment window opens, as plain numbers.
//
// Beside the text when there is room, level with the first selected line.
// Otherwise at the right edge if that does not cover the selected words,
// else below them, else above them. On a screen under 600px wide it is full
// width less a 16px gutter. Always fully on screen.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AnnotateWindowPlace = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const GAP = 16, NEAR = 12, NARROW = 600;
  const MIN = { w: 300, h: 200 };

  function clamp(box, view) {
    const width = Math.min(Math.max(box.width, MIN.w), view.w - 2 * GAP);
    const height = Math.min(Math.max(box.height, MIN.h), view.h - 2 * GAP);
    const left = Math.min(Math.max(box.left, GAP), view.w - GAP - width);
    const top = Math.min(Math.max(box.top, GAP), view.h - GAP - height);
    return { left, top, width, height };
  }

  function covers(b, s) {
    return b.left < s.right && s.left < b.left + b.width && b.top < s.bottom && s.top < b.top + b.height;
  }

  function vertical(sel, height, view) {
    const below = sel.bottom + NEAR;
    if (below + height <= view.h - GAP) return below;
    return sel.top - NEAR - height;
  }

  function place({ sel, content, view, size }) {
    let width = Math.max(size.w, MIN.w), height = Math.max(size.h, MIN.h);
    if (view.w < NARROW) {
      width = view.w - 2 * GAP;
      return clamp({ left: GAP, top: vertical(sel, height, view), width, height }, view);
    }
    const level = sel.top - 10;
    if (view.w - content.right - GAP >= width + GAP) {
      return clamp({ left: content.right + GAP, top: level, width, height }, view);
    }
    const edge = clamp({ left: view.w - GAP - width, top: level, width, height }, view);
    if (!covers(edge, sel)) return edge;
    return clamp({ left: Math.max(sel.left, GAP), top: vertical(sel, height, view), width, height }, view);
  }

  return { place, clamp, MIN };
});
