const NODE_ID = /(?:^|-)flowchart-(.+)-\d+$/;

export function isEdgePath(el) {
  return el.tagName.toLowerCase() === "path" && /^L_/.test(el.dataset.id || "");
}

export function nodeElements(svg, id) {
  if (!svg) return [];
  const want = String(id);
  return [...svg.querySelectorAll("g.node")].filter((g) => {
    const m = NODE_ID.exec(g.id);
    return (m && m[1] === want) || g.id === want || g.dataset.id === want;
  });
}

function splitEdge(dataId, ids) {
  const body = dataId.replace(/^L_/, "").replace(/_\d+$/, "");
  for (let i = body.indexOf("_"); i > 0; i = body.indexOf("_", i + 1)) {
    const a = body.slice(0, i), b = body.slice(i + 1);
    if (ids.has(a) && ids.has(b)) return [a, b];
  }
  return null;
}

export function flowchartKeys(svg) {
  const found = new Map();
  if (!svg) return found;
  const add = (key, el) => { if (!found.has(key)) found.set(key, []); found.get(key).push(el); };
  const ids = new Set(), prefix = svg.id ? svg.id + "-" : "";
  for (const g of svg.querySelectorAll("g.node")) {
    const m = NODE_ID.exec(g.id);
    if (m) { ids.add(m[1]); add("node:" + m[1], g); }
  }
  for (const g of svg.querySelectorAll("g.cluster")) {
    const id = prefix && g.id.startsWith(prefix) ? g.id.slice(prefix.length) : g.id;
    if (id) { ids.add(id); add("group:" + id, g); }
  }
  const labels = new Map();
  for (const l of svg.querySelectorAll("g.edgeLabel g.label[data-id]")) labels.set(l.dataset.id, l.closest("g.edgeLabel"));
  const seen = new Map();
  for (const path of svg.querySelectorAll("path[data-id]")) {
    if (!isEdgePath(path)) continue;
    const pair = splitEdge(path.dataset.id, ids);
    if (!pair) continue;
    const name = pair[0] + "->" + pair[1], n = seen.get(name) || 0;
    seen.set(name, n + 1);
    add("edge:" + name + "#" + n, path);
    const label = labels.get(path.dataset.id);
    if (label) add("edge:" + name + "#" + n, label);
  }
  return found;
}

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
