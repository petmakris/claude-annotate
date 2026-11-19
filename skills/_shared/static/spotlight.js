// The spotlight a screen is explained with, one part at a time: everything dimmed except the parts in focus,
// each ringed, and a dashed line from the lit part to the heading that explains it. Shared by the explainer's
// single-file page (its build pastes this file in) and the stage's screen board (a copy in skills/stage/static,
// kept identical by skills/tests/test_shared_static_copies.py). A classic script: it sets window.Spotlight.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  let uid = 0;

  function el(name, attrs) {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }

  // Dims all of `svg` (width x height, in the frame's pixels) except `rects` ({x, y, w, h}), and rings each.
  // No rects: nothing is dimmed.
  function shade(svg, width, height, rects) {
    svg.textContent = "";
    if (!rects || !rects.length) return;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const id = "spot" + (++uid);
    const mask = el("mask", { id });
    mask.append(el("rect", { width, height, fill: "#fff" }));
    for (const r of rects) mask.append(el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 6, fill: "#000" }));
    const defs = el("defs", {});
    defs.append(mask);
    svg.append(defs, el("rect", { class: "dim", width, height, mask: `url(#${id})` }));
    for (const cls of ["ring halo", "ring"]) {
      for (const r of rects) svg.append(el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 6, class: cls }));
    }
  }

  // Draws the dashed line in `path` (and its end `dot`) from the right edge of the lit rects, inside `frame`,
  // to the left of `heading`, all in `container`'s coordinates. Returns false (and draws nothing) when there is
  // no room between the two, as on a narrow screen where the text sits under the picture.
  function link(container, frame, rects, heading, path, dot) {
    path.setAttribute("d", "");
    dot.setAttribute("r", 0);
    if (!rects || !rects.length || !heading) return false;
    const box = container.getBoundingClientRect(), fr = frame.getBoundingClientRect();
    const right = Math.min(fr.right, fr.left + Math.max(...rects.map((r) => r.x + r.w))) - box.left;
    const top = Math.max(fr.top, fr.top + Math.min(...rects.map((r) => r.y)));
    const bottom = Math.min(fr.bottom, fr.top + Math.max(...rects.map((r) => r.y + r.h)));
    const mid = (top + bottom) / 2 - box.top;
    const h = heading.getBoundingClientRect();
    const x1 = right + 6, x2 = h.left - box.left - 12, y2 = h.top + Math.min(h.height, 40) / 2 - box.top;
    if (x2 - x1 < 12 || h.top >= fr.bottom) return false;
    const cx = (x1 + x2) / 2;
    path.setAttribute("d", `M${x1},${mid} C${cx},${mid} ${cx},${y2} ${x2},${y2}`);
    dot.setAttribute("cx", x1);
    dot.setAttribute("cy", mid);
    dot.setAttribute("r", 5);
    return true;
  }

  // An image screen's boxes ([x, y, w, h] in the drawn screen's pixels) as rects in the image's laid-out size.
  function boxRects(img, w, h, boxes) {
    const kx = img.clientWidth / w, ky = img.clientHeight / h;
    return (boxes || []).map(([x, y, bw, bh]) => ({ x: x * kx, y: y * ky, w: bw * kx, h: bh * ky }));
  }

  // An HTML screen's parts, found by selector, as rects in the frame's coordinates, with a little room round them.
  function focusRects(frame, focus) {
    const fr = frame.getBoundingClientRect(), out = [];
    for (const sel of [].concat(focus || [])) {
      for (const e of frame.querySelectorAll(sel)) {
        const r = e.getBoundingClientRect();
        if (r.width || r.height) out.push({ x: r.left - fr.left - 4, y: r.top - fr.top - 4, w: r.width + 8, h: r.height + 8 });
      }
    }
    return out;
  }

  window.Spotlight = { shade, link, boxRects, focusRects };
})();
