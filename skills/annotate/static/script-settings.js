// annotate page code, part 2 of 9 (see script.js): code anchor panes, the
// page-wide view controls and the settings panel.

// ── Code anchors ───────────────────────────────────────────────────────────
// A block's anchors, resolved by the server into real lines. The pane is a
// reading aid: it links into the IDE and nothing inside it is a click
// target. Comments come from the card header, the same rule the flowchart
// source pane adopted after a `ref` that only looked like a link kept
// opening a comment box for people reaching for a file.

// ── Page-wide view controls ───────────────────────────────────────────
// How wide the column is, stored per response, because a preference you
// must re-set on every reload is worse than not having one.
// Two stops: Normal, a 1600px column, and Wide, which has no cap and runs
// the full width of the window less the side gutters. Code panes always
// sit under the prose, so no stop has to make room for a second column.
const VIEW_WIDTHS = ["normal", "wide"];
const VIEW_LABELS = { normal: "Normal", wide: "Wide" };

function viewKey(name) {
  const rid = (document.body.dataset.responseId || "default");
  return `annotate.view:${rid}:${name}`;
}
function readStored(name) {
  try { return localStorage.getItem(viewKey(name)); } catch (_) { return null; }
}
// Every new session opens at Normal, code or not. This used to be derived
// from data-has-code, which made the opening measure depend on something
// the reader never chose. One default, chosen once; anything else is the
// reader's own click, and that is what `stored` is for.
const DEFAULT_WIDTH = "normal";
// `pagewidth`, not `width`: the stops have been renamed in place before,
// and the older key's values all name columns narrower than Normal now.
// AnnotateStorage retires that key rather than mapping it to the default.
const WIDTH_KEY = "pagewidth";
function effectiveWidth() {
  const stored = readStored(WIDTH_KEY);
  return VIEW_WIDTHS.indexOf(stored) >= 0 ? stored : DEFAULT_WIDTH;
}
// Pane themes. Daylight is the measured light palette the pane shipped
// with; the others redeclare its variables. An unknown stored value falls
// back rather than painting an undefined theme.
//
// Midnight is the default, not Daylight: the pane is a quotation from a
// file, and a dark ground is what separates it at a glance from the prose
// it sits under. The order of PANE_THEMES is the popover's order and says
// nothing about which one is default — hence the named constant.
const PANE_THEMES = ["daylight", "midnight", "contrast", "contrast-dark"];
const DEFAULT_PANE_THEME = "midnight";
function effectivePaneTheme() {
  const stored = readStored("panetheme");
  return PANE_THEMES.indexOf(stored) >= 0 ? stored : DEFAULT_PANE_THEME;
}

// ── Settings ───────────────────────────────────────────────────────────
// One spec drives the markup, the persistence and the painting, because
// these all used to live in the header as their own controls: a button that
// cycled the width, a toggle for the pane layout, a popover for the theme,
// another for the highlight colour. Four controls, none of them things a
// reader touches twice, in a bar that also carries search, the highlighter,
// the composer, the legend, Share and Done. They are one gear now, and the
// bar is down from twelve controls to nine.
//
// `scope` is the only interesting field. "doc" keeps the choice per
// response — a document that cites code wants a wider measure than a memo,
// and that is a property of the document, not of the reader. "global" keeps
// it for the reader across every document: nobody wants to choose their
// code font again on each one.
//
// `attr` is the dataset key, so `width` paints data-width and `codeFont`
// paints data-code-font. The stylesheet keys off those attributes and
// nothing else; see the view-controls and typography blocks in style.css.
const SETTINGS = [
  // First row, and "global": a reader who works in the dark does so in every
  // document, the same way they read in one typeface. Light is the default
  // because it is what shipped and what every existing reader already has.
  { key: "pagetheme", attr: "pageTheme", label: "Page", scope: "global",
    def: "light",
    options: [["light", "Light"], ["dark", "Dark"]] },
  { key: WIDTH_KEY, attr: "width", label: "Page width", scope: "doc",
    read: effectiveWidth,
    options: VIEW_WIDTHS.map((v) => [v, VIEW_LABELS[v]]) },
  { key: "panetheme", attr: "paneTheme", label: "Code theme", scope: "doc",
    read: effectivePaneTheme,
    // Each is a standard editor theme, used as it ships (code-paint.js).
    options: [["daylight", "Light (VS Code Light+)", "#ffffff", "#000000"],
              ["midnight", "Dark (GitHub Dark)", "#0d1117", "#e6edf3"],
              ["contrast", "High contrast light", "#ffffff", "#0e1116"],
              ["contrast-dark", "High contrast dark", "#0a0c10", "#f0f3f6"]] },
  { key: "codefont", attr: "codeFont", label: "Code font", scope: "global",
    def: "jetbrains",
    options: [["jetbrains", "JetBrains"], ["monaspace", "Monaspace"],
              ["system", "System"]] },
  { key: "textsize", attr: "textSize", label: "Reading size", scope: "global",
    def: "medium",
    options: [["small", "Small"], ["medium", "Medium"], ["large", "Large"]] },
  { key: "speechvoice", attr: "speechVoice", label: "Read-aloud voice", scope: "global",
    def: "ava",
    options: [["ava", "Ava (US)"], ["andrew", "Andrew (US)"], ["emma", "Emma (US)"],
              ["brian", "Brian (US)"], ["sonia", "Sonia (UK)"], ["ryan", "Ryan (UK)"]] },
  { key: "dictationlang", attr: "dictationLang", label: "Dictation language", scope: "global",
    def: "auto",
    options: [["auto", "Browser's"], ["en-US", "English (US)"], ["en-GB", "English (UK)"],
              ["el-GR", "Greek"], ["fr-FR", "French"]] },
];

// A global setting drops the response id from the key, which is the whole
// difference between "this document is wide" and "I read in this typeface".
function settingKey(s) {
  return s.scope === "global" ? `annotate.view:${s.key}` : viewKey(s.key);
}

function settingValue(s) {
  // The two settings that predate this panel keep their own readers, which
  // carry their defaults.
  if (s.read) return s.read();
  let stored = null;
  try { stored = localStorage.getItem(settingKey(s)); } catch (_) {}
  return s.options.some(([v]) => v === stored) ? stored : s.def;
}

function setSetting(s, value) {
  try { localStorage.setItem(settingKey(s), value); } catch (_) {}
  applyViewControls();
}

// Everything the panel shows, back to its default — including the code font
// and the reading size, which are the reader's and therefore shared with every
// other annotate document. That is a deliberate choice and the button's
// title says so, because nothing on screen otherwise reveals that this one
// click reaches outside the document you are looking at.
//
// Removing the keys rather than writing the defaults into them keeps one
// meaning for "unset": a stored value is a choice somebody made, and a
// default that changes later should reach a reader who never chose.
//
// What it does NOT touch, all of it deliberate: the highlight MARKS
// (annotate.read:*), which are reading work and belong to the eraser in the
// bar; the comment drafts; and the highlighter's own on/off, which is a
// control in the bar and not a row in this panel.
function resetSettings() {
  for (const s of SETTINGS) {
    try { localStorage.removeItem(settingKey(s)); } catch (_) {}
  }
  try { localStorage.removeItem(viewKey("highlightcolor")); } catch (_) {}
  applyViewControls();
  // The colour lives on <body> and the swatches' pressed state is painted
  // from it, so clearing the key changes nothing on screen without this.
  window.annotateHighlighter?.syncControls?.();
}

// Paints every setting onto <body> and syncs the panel to it. Idempotent,
// and safe to call on every render: it reads state, it never advances it.
function applyViewControls() {
  const groups = document.getElementById("settings-groups");
  for (const s of SETTINGS) {
    const value = settingValue(s);
    document.body.dataset[s.attr] = value;
    if (!groups) continue;
    groups.querySelectorAll(`[data-setting="${s.key}"] [data-value]`).forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.value === value ? "true" : "false");
    });
  }
}

function wireViewControls() {
  const groups = document.getElementById("settings-groups");
  if (groups && !groups.childElementCount) {
    for (const s of SETTINGS) {
      const group = document.createElement("div");
      group.className = "set-group";
      group.dataset.setting = s.key;
      const label = document.createElement("span");
      label.className = "set-label";
      label.textContent = s.label;
      const row = document.createElement("div");
      row.className = "set-row";
      for (const [value, text, chipBg, chipFg] of s.options) {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.value = value;
        b.setAttribute("aria-pressed", "false");
        // The code themes keep the chip the old popover gave them: "Midnight"
        // names the choice, and the chip shows the ground and ink it means.
        if (chipBg) {
          const chip = document.createElement("span");
          chip.className = "pt-chip";
          chip.style.background = chipBg;
          chip.style.color = chipFg;
          chip.textContent = "Aa";
          b.appendChild(chip);
        }
        const name = document.createElement("span");
        name.className = "pt-name";
        name.textContent = text;
        b.appendChild(name);
        b.addEventListener("click", () => setSetting(s, value));
        row.appendChild(b);
      }
      group.append(label, row);
      groups.appendChild(group);
    }
  }
  // The highlighter's own controls are hidden when the browser has no
  // Highlight API (see highlighter.js), and its colour row must go with
  // them — a palette for a feature that cannot run is worse than no palette.
  const hlBtn = document.getElementById("highlighter-toggle");
  const hlGroup = document.getElementById("set-group-highlight");
  if (hlBtn && hlGroup && hlBtn.hidden) hlGroup.hidden = true;
  const reset = document.getElementById("settings-reset");
  // Bound once: wireViewControls is called at parse time and the button is
  // server-rendered, but a second call must not stack a second listener and
  // reset twice.
  if (reset && !reset.dataset.wired) {
    reset.dataset.wired = "1";
    reset.addEventListener("click", resetSettings);
  }
  applyViewControls();
}

function renderCodePane(pane) {
  const wrap = document.createElement("div");
  wrap.className = "codepane";

  const head = document.createElement("div");
  head.className = "cp-head";
  const path = document.createElement("span");
  path.className = "cp-path";
  const shown = pane.actual_line || pane.line;
  // A pane whose status isn't "ok"/"moved" has no location to assert — the
  // body text is about to say the anchored line ISN'T there, so a header
  // reading "file:44" would claim the very thing the message disproves.
  // "moved" is the one non-"ok" status that keeps its line: actual_line is
  // real, it's just not where the block originally pointed.
  const resolved = pane.status === "ok" || pane.status === "moved";
  // The filename, not the path. A repo-relative path is routinely 90+
  // characters and the header is ~475px wide, so the full string was
  // ellipsised in the middle of the part that identifies it --
  // `app-worktrees/ABC-272/advisory/.../featuretoggle/Feat...` told the
  // reader the repo (which the prose already said) and hid the filename
  // (which it did not). Leading segment plus basename keeps both ends, and
  // the full path stays one hover away in the title.
  const segments = (pane.file || "").split("/").filter(Boolean);
  const base = segments.length ? segments[segments.length - 1] : (pane.file || "");
  const project = segments.length > 1 ? segments[0] : "";
  const located = (resolved && shown) ? `${base}:${shown}` : base;
  path.title = pane.file || "";

  // The project reads as a pill, tinted from its own name. A page citing four
  // repos otherwise gives every header the same colour, so telling them apart
  // means reading each one; a stable tint makes it a glance. Deterministic by
  // construction — the same name always lands on the same hue, across panes,
  // pages and reloads — so the colour is a property of the project rather
  // than of the order things happened to render in.
  if (project) {
    const pill = document.createElement("span");
    pill.className = "cp-proj";
    pill.textContent = project;
    pill.style.setProperty("--cp-pill-h", String(hueFromName(project)));
    path.appendChild(pill);
  }

  // file:line copies on click. It is the one string in the pane somebody
  // wants in another window -- a message, a commit, a terminal -- and the
  // FULL repo-relative path is what pastes usefully, even though the header
  // shows the short form. Reading the long path off the screen was never
  // possible anyway: it is why the label was shortened.
  const loc = document.createElement("button");
  loc.type = "button";
  loc.className = "cp-loc";
  loc.textContent = located;
  const toCopy = (resolved && shown) ? `${pane.file}:${shown}` : (pane.file || "");
  loc.title = `copy ${toCopy}`;
  loc.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    const was = loc.textContent;
    try {
      await navigator.clipboard.writeText(toCopy);
      loc.textContent = "copied";
    } catch (_) {
      // Clipboard access needs a secure context; the shared LAN link is
      // plain http, so this is a normal outcome there, not a defect. Say so
      // rather than looking like the click did nothing.
      loc.textContent = "copy unavailable";
    }
    loc.dataset.flash = "1";
    setTimeout(() => { loc.textContent = was; delete loc.dataset.flash; }, 1200);
  });
  path.appendChild(loc);

  const spacer = document.createElement("span");
  spacer.className = "cp-spacer";
  head.append(path, spacer);

  // Drift rides in the header band as a chip. It used to be a `.cp-status`
  // row under the note, and head + note + status stacked to 101px above the
  // first line of code — more chrome than content on a short pane. The chip
  // has to carry the AUTHORED line, because that is the one fact the header
  // does not: `path` shows where the line is NOW. The full message stays as
  // the title, so nothing is lost, and a pane with no code to show keeps the
  // whole sentence as a row (below) rather than shrinking to this.
  if (pane.status !== "ok") {
    const chip = document.createElement("span");
    chip.className = "cp-chip";
    chip.dataset.status = pane.status;
    chip.textContent = pane.status === "moved" && pane.line
      ? `moved · was ${pane.line}`
      : pane.status;
    if (pane.message) chip.title = pane.message;
    head.appendChild(chip);
  }

  if (pane.status === "ok" || pane.status === "moved") {
    // Opening is asked of the SERVER, not of the operating system. A page has no
    // way to hand a path to a native app -- `file://` is refused from an http
    // origin -- which is why this used to build a `jetbrains://` URI carrying the
    // IDE's project name, guessed from a directory basename. The guess was wrong
    // whenever a project's name differed from its folder's, and the failure was
    // silent. The server is a local process with no such limitation, so it runs
    // the opener itself and the project name stops existing as a concept here.
    const abs = document.body.dataset.repoRoot || "";
    if (abs) {
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "cp-jump";
      jump.replaceChildren(icon(ICON_OPEN));
      jump.title = "open in editor";
      jump.setAttribute("aria-label", jump.title);
      // A failure has to stay legible now that the button is an icon: it
      // cannot become its own error message any more. The reason goes into
      // the tooltip and a red state onto the button, so the click is never
      // silent -- which was the entire point of moving opening server-side.
      const failFor = (why) => {
        jump.dataset.failed = "1";
        jump.title = why;
        jump.setAttribute("aria-label", why);
        setTimeout(() => {
          delete jump.dataset.failed;
          jump.title = "open in editor";
          jump.setAttribute("aria-label", jump.title);
          jump.disabled = false;
        }, 4000);
      };
      jump.addEventListener("click", async () => {
        jump.disabled = true;
        // The reason is the server's, not a guess (wc-open.js).
        const res = await window.WcOpen.open({ key: workspaceKey(), file: pane.file, line: shown });
        if (!res.ok) {
          failFor(res.reason);
          return;
        }
        jump.disabled = false;
      });
      head.appendChild(jump);
    }
  }
  wrap.appendChild(head);

  // A pane that could not resolve shows its reason and NO code. Rendering
  // whatever now sits at that line number would be a lie the reader has no
  // way to detect.
  if (pane.status !== "ok" && pane.status !== "moved") {
    const status = document.createElement("div");
    status.className = "cp-status";
    status.dataset.status = pane.status;
    let msg = pane.message || "this anchor could not be resolved";
    // The header already shows the filename; strip it back off the message
    // if it leads with exactly "<file>: " so it isn't said twice. Only an
    // exact match is stripped — an unexpected message shape renders in
    // full rather than being mangled.
    const filePrefix = pane.file ? `${pane.file}: ` : null;
    if (filePrefix && msg.startsWith(filePrefix)) msg = msg.slice(filePrefix.length);
    status.textContent = msg;
    wrap.appendChild(status);
    return wrap;
  }

  const body = document.createElement("div");
  body.className = "cp-body";
  // Painted as one run and cut into rows, for the same reason as the explain
  // pane: a row coloured on its own loses the annotation or comment it
  // continues.
  const lines = pane.lines || [];
  const misses = codeMisses();
  const paintedRows = window.CodePaint
    ? CodePaint.rows(lines.map((l) => l.text), { file: pane.file }) : null;
  const cells = [];
  lines.forEach((l, i) => {
    const row = document.createElement("div");
    row.className = "cp-row";
    if (l.role === "anchor") row.classList.add("is-anchor");
    if (l.role === "context") row.classList.add("is-context");
    // A blank context line renders nothing at all; at a full row height it
    // reads as a hole in the pane rather than as the blank line it is.
    if (l.role === "context" && !String(l.text || "").trim()) row.classList.add("is-blank");
    const text = document.createElement("span");
    text.className = "cp-line";
    if (paintedRows) text.innerHTML = paintedRows[i];
    else text.textContent = l.text;
    cells.push(text);
    row.appendChild(text);
    body.appendChild(row);
  });
  wrap.appendChild(body);
  if (!paintedRows && codeMisses() > misses) {
    later(body, paintRowsLater(cells, lines.map((l) => l.text), { file: pane.file }));
  }

  if (pane.truncated) {
    const cut = document.createElement("div");
    cut.className = "cp-truncated";
    cut.textContent = `… ${pane.truncated} more lines`;
    wrap.appendChild(cut);
  }
  return wrap;
}
