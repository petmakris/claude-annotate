// /draw's page: the drawing pad, full screen, at a link that never changes.
// It shows nothing else. The lines are saved on the daemon as they are drawn
// (item "strokes"), so a reload or another device opens the same drawing.
// Update sends the drawing as it is now to the Claude session that last ran
// /draw, as one event with the PNG attached. The only words it ever shows are
// "Sent" for a moment and "nobody listening" when no session holds the link.
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
        await api.submit({ anchor: "drawing", text: JSON.stringify({ type: "update" }), images: [{ path: up.path }] });
        flash = "Sent";
      } catch (_) {
        flash = "not sent";
      }
      show(pad);
      setTimeout(() => { flash = null; show(pad); }, 2500);
    },
  });

  async function check() {
    status = (await listening()) ? "" : "nobody listening";
    show(pad);
  }
  check();
  setInterval(check, 10000);
}

main();
