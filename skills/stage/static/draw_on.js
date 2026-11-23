// An arrow arriving draws in along its length, its head put back once it is drawn: the map's arrows and
// route steps, as scene.js applies a frame.
export function drawOn(path, delay) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const len = path.getTotalLength();
  const marker = path.getAttribute("marker-end");
  if (marker) { path.dataset.marker = marker; path.removeAttribute("marker-end"); }
  path.style.transition = "none";
  path.style.strokeDasharray = String(len);
  path.style.strokeDashoffset = String(len);
  path.getBoundingClientRect();
  path.style.transition = `stroke-dashoffset 360ms ease-out ${delay}ms`;
  path.style.strokeDashoffset = "0";
  const done = () => { if (path.style.strokeDasharray) resetDraw(path); };
  path.addEventListener("transitionend", done, { once: true });
  setTimeout(done, delay + 600);
}

export function resetDraw(path) {
  path.style.transition = "";
  path.style.strokeDasharray = "";
  path.style.strokeDashoffset = "";
  if (path.dataset.marker) { path.setAttribute("marker-end", path.dataset.marker); delete path.dataset.marker; }
}
