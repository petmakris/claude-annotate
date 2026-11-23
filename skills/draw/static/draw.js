// /draw's page: the drawing pad, full screen, at a link that never changes.
// It shows nothing else. The lines are saved on the daemon as they are drawn
// (item "strokes"), so a reload or another device opens the same drawing.
// Pictures (a photo from the camera or the library) wait as thumbnails beside
// Update (item "photos") and go with the next Update only.
// Full screen hides the browser's bars and, on Android, the status bar and the
// navigation buttons. The pad enters it after the first line is drawn, and a
// button beside Update enters and leaves it; leaving by the button stops the
// automatic entry until the page is opened again.
// Update sends the drawing as it is now to the Claude session that last ran
// /draw, as one event with the PNG first and the pictures after it. The only
// words it ever shows are "Sent" for a moment and "nobody listening" when no
// session holds the link.
const wc = window.WebCompanion;
const api = wc.api;
const LISTENING_S = 90; // a watcher heartbeat younger than this is someone listening

function load(tag, attrs) {
  return new Promise((resolve, reject) => {
    const el = document.createElement(tag);
    Object.assign(el, attrs, { onload: resolve, onerror: reject });
    document.head.appendChild(el);
  });
}

// Two decimals of a pixel are plenty, and they keep the saved item small.
function compact(strokes) {
  return strokes.map((s) => ({ ...s, points: s.points.map((p) => p.map((v) => Math.round(v * 100) / 100)) }));
}

let saveTimer = null;
let pending = null;
function save(strokes) {
  pending = strokes;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = JSON.stringify({ strokes: compact(pending), at: Date.now() });
    try {
      await api.fetchJSON("items/strokes", { method: "PUT", headers: { "Content-Type": "application/json" }, body });
    } catch (_) { /* the next change saves again */ }
  }, 600);
}

// ── pictures ──
// A tablet photo can be HEIC and larger than the daemon's 10 MB upload limit,
// so each one is drawn onto a canvas no larger than PHOTO_MAX px and sent as JPEG.
const PHOTO_MAX = 2000;
const THUMB = 96;
let photos = []; // [{path, thumb}]

async function decode(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

function scaled(img, max) {
  const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement("canvas");
  c.width = Math.round(img.naturalWidth * k);
  c.height = Math.round(img.naturalHeight * k);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c;
}

async function savePhotos() {
  const body = JSON.stringify({ photos, at: Date.now() });
  try {
    await api.fetchJSON("items/photos", { method: "PUT", headers: { "Content-Type": "application/json" }, body });
  } catch (_) { /* kept on screen; the next change saves again */ }
}

const PHOTO_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="15" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M21 17l-5-5-9 8"/></svg>';

function mountPhotos(pad) {
  const end = document.querySelector(".dp-end");
  if (!end) return () => {};
  const style = document.createElement("style");
  style.textContent = `
    .dw-thumbs { display: flex; gap: 6px; align-items: center; margin-right: 6px; }
    .dw-thumb { position: relative; width: 36px; height: 36px; border-radius: 6px; overflow: hidden;
      border: 1px solid var(--dp-line, #ccc); background: var(--dp-hover, #eee); }
    .dw-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .dw-thumb button { position: absolute; top: 0; right: 0; width: 18px; height: 18px; padding: 0; border: 0;
      border-radius: 0 0 0 6px; background: rgba(0,0,0,.6); color: #fff; font-size: 13px; line-height: 18px; cursor: pointer; }
    .dw-thumb.dw-busy { opacity: .5; }
    .dw-add { display: inline-flex; align-items: center; gap: 6px; }
    @media (max-width: 560px) { .dw-add .dw-word { display: none; } }
  `;
  document.head.appendChild(style);
  const thumbs = document.createElement("div");
  thumbs.className = "dw-thumbs";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "dp-text-btn dw-add";
  add.title = "Add pictures: they go with the next Update";
  add.setAttribute("aria-label", "Add pictures");
  add.innerHTML = `${PHOTO_ICON}<span class="dw-word">Pictures</span>`;
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.multiple = true;
  input.hidden = true;
  const status = end.querySelector(".dp-status");
  end.insertBefore(thumbs, status);
  end.insertBefore(add, status);
  end.appendChild(input);

  function render(busy = 0) {
    thumbs.innerHTML = "";
    photos.forEach((p, i) => {
      const t = document.createElement("div");
      t.className = "dw-thumb";
      t.innerHTML = `<img alt="Picture ${i + 1}"><button type="button" aria-label="Remove picture ${i + 1}" title="Remove">×</button>`;
      t.querySelector("img").src = p.thumb;
      t.querySelector("button").onclick = (ev) => { ev.stopPropagation(); photos.splice(i, 1); render(); savePhotos(); };
      thumbs.appendChild(t);
    });
    for (let i = 0; i < busy; i++) {
      const t = document.createElement("div");
      t.className = "dw-thumb dw-busy";
      thumbs.appendChild(t);
    }
  }

  add.addEventListener("click", (ev) => { ev.stopPropagation(); input.click(); });
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    let left = files.length;
    render(left);
    for (const f of files) {
      try {
        const img = await decode(f);
        const big = scaled(img, PHOTO_MAX);
        const blob = await new Promise((r) => big.toBlob(r, "image/jpeg", 0.85));
        const up = await api.pasteImage(blob);
        photos.push({ path: up.path, thumb: scaled(img, THUMB).toDataURL("image/jpeg", 0.7) });
      } catch (_) {
        flash = "picture not added";
        show(pad);
        setTimeout(() => { flash = null; show(pad); }, 2500);
      }
      render(--left);
    }
    savePhotos();
  });
  render();
  return () => { photos = []; render(); savePhotos(); };
}

// ── full screen ──
const FULL_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
const EXIT_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';

function mountFullscreen() {
  const end = document.querySelector(".dp-end");
  const el = document.documentElement;
  if (!end || !el.requestFullscreen) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dp-text-btn dw-add dw-full";
  end.insertBefore(btn, end.firstChild);
  let auto = true;
  const on = () => !!document.fullscreenElement;
  const enter = () => el.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  function render() {
    const full = on();
    btn.innerHTML = full ? `${EXIT_ICON}<span class="dw-word">Exit full screen</span>` : `${FULL_ICON}<span class="dw-word">Full screen</span>`;
    btn.title = full ? "Show the browser and Android's bars again" : "Hide the browser and Android's bars";
    btn.setAttribute("aria-label", full ? "Exit full screen" : "Full screen");
    btn.setAttribute("aria-pressed", String(full));
  }
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (on()) { auto = false; document.exitFullscreen().catch(() => {}); } else enter();
  });
  // After a line, not while it is drawn: entering resizes the page, which would cut the line.
  const stage = document.querySelector(".dp-stage");
  if (stage) stage.addEventListener("pointerup", () => { if (auto && !on()) enter(); });
  document.addEventListener("fullscreenchange", () => { render(); window.dispatchEvent(new Event("resize")); });
  render();
}

let status = "";
let flash = null;
function show(pad) { pad.setStatus(flash || status); }

async function listening() {
  try {
    const p = await api.fetchJSON("poll");
    const seen = p.watcher_seen_at || 0;
    const stopped = p.watcher_stopped_at || 0;
    return !p.finished && !p.cancelled && seen > stopped && Date.now() / 1000 - seen < LISTENING_S;
  } catch (_) {
    return false;
  }
}

async function main() {
  await Promise.all([
    load("link", { rel: "stylesheet", href: "assets/drawpad.css" }),
    load("script", { src: "assets/drawpad.js" }),
  ]);
  let strokes = [];
  try {
    const item = await api.fetchJSON("items/strokes");
    strokes = (item.body && item.body.strokes) || [];
  } catch (_) { /* a first visit has no drawing yet */ }
  try {
    const item = await api.fetchJSON("items/photos");
    photos = (item.body && item.body.photos) || [];
  } catch (_) { /* no pictures waiting */ }
  let clearPhotos = () => {};

  const pad = window.DrawPad.open({
    title: "Drawing",
    doneLabel: "Update",
    hint: "Draw with the pen. Update sends the drawing to Claude.",
    noCancel: true,
    stayOpen: true,
    strokes,
    onChange: save,
    async onDone(blob, kept) {
      save(kept);
      try {
        const up = await api.pasteImage(blob);
        const images = [{ path: up.path }, ...photos.map((p) => ({ path: p.path }))];
        await api.submit({ anchor: "drawing", text: JSON.stringify({ type: "update", pictures: photos.length }), images });
        clearPhotos();
        flash = "Sent";
      } catch (_) {
        flash = "not sent";
      }
      show(pad);
      setTimeout(() => { flash = null; show(pad); }, 2500);
    },
  });

  clearPhotos = mountPhotos(pad);
  mountFullscreen();

  async function check() {
    status = (await listening()) ? "" : "nobody listening";
    show(pad);
  }
  check();
  setInterval(check, 10000);
}

main();
