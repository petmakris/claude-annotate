// A screen board: an explainer (skills/explainer) on the stage. One screen at a time, everything on it dimmed
// except the part being said, which is ringed; beside it that part's count, title and text, joined to it by a
// dashed line. The scene engine decides what is said: every part has a keyed marker (part:p1, part:p2, ...) that
// applyFrame shows and lights, and paintScreen reads the frame's `cur` (else its focus) to pick the part, so the
// page draws what the frame names and guesses nothing. Nothing lit (frame 0, the rest frame, no scene): the screen
// shown last, undimmed, with the board's title. The spotlight itself is spotlight.js, shared with the explainer.
import "./spotlight.js";

const PART = /^part:(p\d+)$/;

// Inline HTML the explainer's author wrote (a title with <code>, a link): made safe when DOMPurify is in, else
// shown as its words.
function safe(html) {
  const s = String(html ?? "");
  if (window.DOMPurify) {
    return window.DOMPurify.sanitize(s, { FORBID_TAGS: ["form", "meta", "iframe", "style", "base", "script", "link", "object", "embed", "img"] });
  }
  const d = document.createElement("div"); d.textContent = s.replace(/<[^>]*>/g, "");
  return d.innerHTML;
}

function partsOf(src) {
  const out = [];
  src.screens.forEach((s, si) => s.steps.forEach((st) => out.push({ s, si, st, n: out.length + 1 })));
  return out;
}

// Builds the board. `imageUrl(path)` is where the stage serves a file of the spec's folder.
export function renderScreen(box, src, { imageUrl, embedded }) {
  box.className = "visual screenb" + (embedded ? " sb-call" : "");
  const parts = partsOf(src);
  box.innerHTML = `<div class="sb-stage"><div class="sb-frame"><div class="sb-pic"></div><svg class="sb-shade" aria-hidden="true"></svg></div>
    <p class="sb-src"></p></div><div class="sb-text" aria-live="polite"></div>
    <svg class="sb-link" aria-hidden="true"><path d=""/><circle r="0"/></svg><div class="sb-keys" aria-hidden="true"></div>`;
  const keys = box.querySelector(".sb-keys");
  for (const p of parts) {
    const i = document.createElement("i"); i.dataset.key = "part:" + p.st.id; keys.append(i);
  }
  box._sb = { src, parts, imageUrl, screen: -1, part: null };
  showPart(box, null);
  if (typeof ResizeObserver === "function") new ResizeObserver(() => place(box)).observe(box);
  return box;
}

// The part frame n of `scene` says (its `cur`), else the part it points at, else none.
export function paintScreen(box, scene, n, beingSaid) {
  const sb = box._sb;
  if (!sb) return;
  let id = null;
  if (scene && Array.isArray(scene.frames) && scene.frames.length) {
    const frame = scene.frames[Math.max(0, Math.min(n, scene.frames.length - 1))];
    const pick = (keys) => [...(keys || [])].reverse().map((k) => PART.exec(k)).find(Boolean);
    const m = pick(beingSaid(scene, n)) || pick(frame.focus);
    id = m ? m[1] : null;
  }
  showPart(box, id);
}

function showPart(box, id) {
  const sb = box._sb;
  const p = id ? sb.parts.find((q) => q.st.id === id) || null : null;
  const si = p ? p.si : Math.max(sb.screen, 0);
  if (si !== sb.screen) drawScreen(box, si);
  sb.part = p;
  const text = box.querySelector(".sb-text");
  const s = sb.src.screens[si], many = sb.src.screens.length > 1;
  let html = "";
  if (p) {
    html += `<div class="sb-meta"><span class="sb-count">${p.n} / ${sb.parts.length}</span>` +
      (many && s.label ? `<span class="sb-chip${s.phase ? " " + s.phase : ""}">${safe(s.phase === "design" ? "Design · " + s.label : s.label)}</span>` : "") + "</div>";
    if (s.title) html += `<p class="sb-claim">${safe(s.title)}</p>`;
    html += `<h2>${safe(p.st.title)}</h2>`;
    for (const t of [].concat(p.st.text || [])) html += `<p>${safe(t)}</p>`;
    if (p.st.facts?.length) html += `<div class="sb-facts">${p.st.facts.map((f) => `<div><b>${safe(f.big)}</b><span>${safe(f.small)}</span></div>`).join("")}</div>`;
    if (p.st.examples?.length) {
      html += `<ul class="sb-examples">${p.st.examples.map((x) => `<li><span class="sb-draw">${safe(x.draw)}</span><span class="sb-means">${safe(x.means)}` +
        `<small class="${x.seen ? "" : "none"}">${x.seen ? "Seen on " + safe(x.seen) : "Not seen yet"}</small></span></li>`).join("")}</ul>`;
    }
  } else {
    html += `<div class="sb-meta"><span class="sb-count">${sb.parts.length} ${sb.parts.length === 1 ? "part" : "parts"}</span>` +
      (sb.src.tag ? `<span class="sb-chip">${safe(sb.src.tag)}</span>` : "") + "</div>";
    html += `<h2>${safe(sb.src.title || "")}</h2>`;
    const first = sb.parts[0];
    if (first && !(first.st.boxes || []).length && !first.st.focus) {
      for (const t of [].concat(first.st.text || [])) html += `<p>${safe(t)}</p>`;
    }
  }
  text.innerHTML = html;
  for (const a of text.querySelectorAll("a[href]")) { a.target = "_blank"; a.rel = "noopener"; }
  box.dataset.part = p ? p.st.id : "";
  place(box);
}

function drawScreen(box, si) {
  const sb = box._sb, s = sb.src.screens[si];
  sb.screen = si;
  const pic = box.querySelector(".sb-pic");
  pic.replaceChildren();
  if (s.image) {
    const crop = document.createElement("div"); crop.className = "sb-crop";
    crop.style.aspectRatio = `${s.w} / ${s.h}`;
    const img = document.createElement("img");
    const [fw] = s.full || [s.w, s.h], [ox, oy] = s.off || [0, 0];
    img.alt = s.alt || s.label || "";
    img.src = sb.imageUrl(s.image);
    img.style.width = (fw / s.w) * 100 + "%";
    img.style.left = (-ox / s.w) * 100 + "%";
    img.style.top = (-oy / s.h) * 100 + "%";
    img.addEventListener("load", () => place(box));
    crop.append(img);
    pic.append(crop);
  } else {
    const h = document.createElement("div"); h.className = "sb-html"; h.innerHTML = safe(s.html || "");
    pic.append(h);
  }
  const cap = box.querySelector(".sb-src");
  cap.innerHTML = [s.source, sb.src.footer].filter(Boolean).map(safe).join(" · ");
  cap.hidden = !cap.textContent;
}

// Fits the screen into its half of the board, then draws the shade, the rings and the line for the part lit.
function place(box) {
  const sb = box._sb;
  if (!sb || !box.isConnected) return;
  const s = sb.src.screens[sb.screen], frame = box.querySelector(".sb-frame");
  const crop = frame.querySelector(".sb-crop"), link = box.querySelector(".sb-link");
  const stacked = getComputedStyle(link).display === "none";  // narrow: the text goes under the screen
  if (crop) {
    const stage = box.querySelector(".sb-stage"), cap = box.querySelector(".sb-src");
    const room = stacked ? Infinity : stage.clientHeight - (cap.hidden ? 0 : cap.offsetHeight + 8);
    const w = Math.max(80, Math.min(stage.clientWidth, room > 80 ? room * s.w / s.h : stage.clientWidth));
    crop.style.width = w + "px";
  }
  const S = window.Spotlight, st = sb.part?.st;
  const rects = !st ? [] : crop ? S.boxRects(crop, s.w, s.h, st.boxes) : S.focusRects(frame, st.focus);
  S.shade(box.querySelector(".sb-shade"), frame.clientWidth, frame.clientHeight, rects);
  const path = link.querySelector("path"), dot = link.querySelector("circle");
  if (stacked) { path.setAttribute("d", ""); dot.setAttribute("r", 0); return; }
  S.link(box, frame, rects, box.querySelector(".sb-text h2"), path, dot);
}
