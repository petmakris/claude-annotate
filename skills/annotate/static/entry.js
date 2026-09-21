// The renderer the webcompanion daemon loads for an annotate session.
//
// The daemon serves a bare shell page — a title, its own core.js, and one
// module tag pointing here — and knows nothing about annotation. So this file
// does what annotate's own server used to do at request time: paint the page
// frame, pull in the stylesheets and scripts, and only then let the page code
// run.
//
// Order is the whole job. Four things must happen in sequence, and every one
// of them used to be guaranteed by the order of tags in a server-printed
// <head>:
//
//   1. the shell markup exists, because script.js queries for it on load
//   2. compat.js has replaced window.WebCompanion, because script.js calls it
//   3. highlight.js and markdown-it exist, because script.js builds a
//      markdown-it instance with the highlight hook at module scope
//   4. script.js has run, because maximize.js mounts into what it builds
import { SHELL_HTML } from "./shell.js";

const CSS = ["core.css", "style.css", "diagram.css", "popover.css", "code-theme.css"];

// Same order the old server's <head> had, and for the same reasons: the
// highlighter and the markdown renderer before script.js builds its instance;
// diff.js before the first acked round can read it; maximize.js near the end,
// because it mounts into DOM script.js creates. fullscreen.js only needs the
// button shell.js already rendered, so its position after that is not load
// bearing — it sits last because nothing else depends on it.
const JS = [
  "popover.js",
  // Before script.js: it calls blockTitle at module scope the first time a
  // card is painted, and the rule lives here.
  "block-title.js",
  "highlight.min.js",
  "markdown-it.min.js",
  "diff.js",
  "script.js",
  // After script.js: it mounts relative to .page-header and reads
  // window.WebCompanion, which compat.js installs before this list runs.
  "progress.js",
  "export.js",
  "subunits.js",
  "highlighter.js",
  "fuse.min.js",
  "search.js",
  "voice.js",
  "maximize.js",
  "fullscreen.js",
];

function addStylesheet(href) {
  return new Promise((resolve) => {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    // Resolve either way: a missing stylesheet is a cosmetic failure, and
    // hanging the whole boot on it would turn it into a blank page.
    l.onload = l.onerror = () => resolve();
    document.head.appendChild(l);
  });
}

// Appended one at a time and awaited, not emitted as a batch of `defer` tags.
// `defer` preserves document order only for tags present at parse time; these
// are injected after parsing, where the guarantee does not hold and the order
// above is load-order roulette.
function addScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = false;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load " + src));
    document.body.appendChild(s);
  });
}

function fail(message) {
  document.body.innerHTML =
    '<main class="waiting"><p></p></main>';
  document.body.querySelector("p").textContent = message;
}

async function boot() {
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  // The document's own identity, which the old server interpolated into the
  // page it printed. Read it first: a page that paints its frame before it
  // knows whether there is anything to show flashes an empty header.
  let doc = {};
  try {
    const r = await fetch("items/__doc__", { cache: "no-store" });
    if (r.ok) doc = (await r.json()).body || {};
  } catch (_) {
    /* fall through to the waiting state below */
  }

  await Promise.all(CSS.map((f) => addStylesheet(asset(f))));

  if (!doc.order || !doc.order.length) {
    fail("Waiting for a response.");
    return;
  }

  document.body.innerHTML = SHELL_HTML;
  document.body.dataset.responseId = doc.response_id || "";
  const title = doc.title || "Response";
  document.title = title;
  document.getElementById("hdr-title").textContent = title;
  document.getElementById("hdr-respid").textContent = doc.response_id || "";

  // The repo root gates the "open this in my editor" control. Only an owner
  // gets it: the read-only share link is allowed to serve code excerpts, but
  // that decision never covered handing a stranger the server's own directory
  // layout — and the control it enables would be refused for them anyway.
  //
  // Deliberately NOT awaited. It used to be, and that put one optional
  // control's permission check across the critical path of the whole page:
  // every open document holds an SSE stream, a browser allows six
  // connections per origin, and a request that cannot get one waits without
  // ever failing. Boot stopped here — no compat.js, no script.js, so no
  // hover controls and no way to comment on anything — while the document
  // above it rendered perfectly and looked like it was simply ignoring the
  // pointer. Nothing below this line needs the answer, so nothing waits for
  // it; the control appears if and when it arrives.
  fetch("/api/whoami", { cache: "no-store" })
    .then((who) => (who.ok ? who.json() : null))
    .then((me) => {
      if (me && me.writable && doc.cwd) document.body.dataset.repoRoot = doc.cwd;
      if (me && me.writable) setupResumeControl();
    })
    .catch(() => { /* no control, which is the safe direction */ });

  // "How do I attach a Claude Code session to THIS page" had no answer on
  // the page itself -- the command depends on this session's own slug, which
  // nothing here already knew. /api/sessions?scope=all is the one endpoint
  // that carries slug alongside sid (see webcompanion's server.py `_row`),
  // so this finds our own row in it rather than adding a new endpoint for
  // one field. Owner-only: a read-only visitor could not run the command
  // anyway, and scope=all is itself owner-gated, so a non-owner's request
  // would just 403 -- gating on `writable` first (above) skips that call
  // entirely instead of letting it fail silently.
  //
  // Shared with the watcher badge below: both are "attach a session here"
  // controls and both need the same command, discovered once.
  let resumeCommand = null;

  // Single-quoted, POSIX-shell safe: wraps in '...' and escapes any embedded
  // '. A cwd or slug is never attacker input here (both come from this
  // daemon's own registry), but a project path with a space in it is
  // completely ordinary and would otherwise split the `cd` argument.
  function shq(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'";
  }

  // navigator.clipboard needs a secure context (https, or the loopback
  // "localhost" origin) -- opening this page over Tailscale is plain http on
  // a non-localhost hostname, exactly the case this feature exists for, so
  // the modern API is simply ABSENT there (not merely denied: `navigator.
  // clipboard` itself is undefined), and the write throws before it ever
  // reaches a permission prompt. execCommand predates that restriction and
  // still works on a plain-http origin in the browsers this page needs to
  // support -- confirmed against Chrome on Android, which is what the
  // tablet workflow this control exists for actually uses. Same tradeoff
  // script.js's file:line copy-on-click already documented and accepted for
  // itself; this one adds the fallback instead because a resume command you
  // cannot copy is a control that does nothing.
  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {
        // fall through to the legacy path below
      }
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.top = "0";
      ta.style.left = "0";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (_) {
      return false;
    }
  }

  async function copyResumeCommand(statusEl) {
    if (!resumeCommand) return false;
    const ok = await copyText(resumeCommand);
    if (statusEl) {
      statusEl.textContent = ok ? "Copied."
        : "Could not copy -- select and copy the text above.";
    }
    return ok;
  }

  async function setupResumeControl() {
    const sid = location.pathname.split("/").filter(Boolean)[1];
    if (!sid) return;
    try {
      const r = await fetch("/api/sessions?scope=all", { cache: "no-store" });
      if (!r.ok) return;
      const rows = await r.json();
      const row = rows.find((x) => x.sid === sid);
      if (!row || !row.slug) return;
      // The full one-liner, not just the slash command: pasted anywhere, it
      // opens the right directory, starts Claude Code, and submits the
      // resume command as the first turn -- `claude [prompt]` runs
      // interactively and treats a bare positional argument as exactly
      // that (`-p`/`--print` is the separate, non-interactive one-shot
      // mode; this deliberately is not that).
      const cwd = row.cwd || "";
      resumeCommand = cwd
        ? "cd " + shq(cwd) + " && claude " + shq("/annotate resume " + row.slug)
        : "claude " + shq("/annotate resume " + row.slug);
      const cwdEl = document.getElementById("resume-cwd");
      const cmdEl = document.getElementById("resume-cmd");
      const copyBtn = document.getElementById("resume-copy");
      const statusEl = document.getElementById("resume-status");
      if (cwdEl && cmdEl) {
        cwdEl.textContent = row.cwd || "the session's project";
        cmdEl.textContent = resumeCommand;
        if (copyBtn) copyBtn.addEventListener("click", () => copyResumeCommand(statusEl));
      }
      // The command just became available and the current paint (from whatever
      // checkWatcherHealth tick already ran) does not know that yet -- it is
      // what decides whether the resume row is shown at all.
      paintWatcherHealth(lastSeenAt);
    } catch (_) {
      /* no control, which is the safe direction */
    }
  }

  // Watcher health: the registry's "live" state only means "not finished or
  // cancelled" -- it says nothing about whether a Claude Code session is
  // actually watching for a comment here, and until now nothing on the page
  // did either. `/poll` already reports `watcher_seen_at` for every reader,
  // owner or not (see webcompanion's server.py `_poll`), so this needs no
  // new endpoint -- just something that reads it. Fire-and-forget and on its
  // own interval, independent of compat.js/script.js booting below, so a
  // slow or failed page boot never hides this signal.
  //
  // 180s matches the daemon's own staleness convention (the IntelliJ
  // plugin's `REAP_AFTER_MS`, and the same number webcompanion's registry
  // uses to decide a watcher is dead) -- this reads the same fact everyone
  // else already agrees on, not a new threshold invented for the badge.
  const WATCHER_STALE_MS = 180_000;
  const WATCHER_POLL_MS = 15_000;

  // The last value /poll reported, so setupResumeControl can re-paint when the
  // command arrives without waiting up to 15s for the next tick.
  let lastSeenAt = null;

  function paintWatcherHealth(seenAt) {
    lastSeenAt = seenAt;
    const btn = document.getElementById("menu-toggle");
    const block = document.getElementById("menu-status");
    const title = document.getElementById("menu-status-title");
    const sub = document.getElementById("menu-status-sub");
    const resumeEl = document.getElementById("menu-resume");
    if (!btn || !title || !sub) return;

    const live = seenAt != null && (Date.now() - seenAt * 1000) <= WATCHER_STALE_MS;
    const cls = live ? "watcher-live" : "watcher-stale";
    btn.classList.remove("watcher-live", "watcher-stale");
    btn.classList.add(cls);
    if (block) {
      block.classList.remove("watcher-live", "watcher-stale");
      block.classList.add(cls);
    }

    if (live) {
      title.textContent = "Watching";
      sub.textContent = "A live Claude Code session is watching this page and "
        + "will answer comments here.";
    } else if (seenAt == null) {
      title.textContent = "Unwatched";
      sub.textContent = "No Claude Code session has watched this page yet — "
        + "a comment will queue, but nothing will answer it.";
    } else {
      const mins = Math.round((Date.now() - seenAt * 1000) / 60000);
      title.textContent = "Unwatched";
      sub.textContent = "The session that answers comments here has been "
        + "silent for " + mins + " min.";
    }

    // Only when nothing is attached, and only once the command is known: an
    // attached session needs no instructions for attaching one, and a
    // read-only viewer could not run the command anyway.
    if (resumeEl) resumeEl.hidden = live || !resumeCommand;
    // The button says what it is for at a glance, in a tooltip, without
    // opening the menu — and says the same thing to a screen reader, which is
    // why aria-label is written here too rather than left static in the shell.
    // A static aria-label WINS the accessible-name computation over title, so
    // a button labelled "Menu" announced exactly that however the dot was
    // painted: the pill this replaced was the page's only worded
    // Watching/Unwatched signal, and its replacement is a colour. Its panel
    // sibling is aria-hidden, so without this the state is unreachable without
    // opening the menu, and a change is never announced at all.
    btn.title = live ? "Menu — a session is watching this page"
                     : "Menu — nothing is watching this page";
    btn.setAttribute("aria-label", btn.title);
  }

  async function checkWatcherHealth() {
    try {
      const r = await fetch("poll", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      // A finished/cancelled session never gets a watcher again -- showing
      // "unwatched" on it would read as a problem to fix rather than the
      // session simply being over.
      if (data.finished || data.cancelled) return;
      paintWatcherHealth(data.watcher_seen_at);
    } catch (_) {
      /* offline: leave whatever the badge last said, rather than flicker */
    }
  }

  checkWatcherHealth();
  setInterval(checkWatcherHealth, WATCHER_POLL_MS);

  await addScript(asset("compat.js"));
  for (const f of JS) {
    try {
      await addScript(asset(f));
    } catch (e) {
      console.error(e);
    }
  }
}

boot().catch((e) => {
  console.error(e);
  fail("This page failed to load: " + e.message);
});
