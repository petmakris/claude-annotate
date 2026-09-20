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
      const toggle = document.getElementById("resume-toggle");
      const cwdEl = document.getElementById("resume-cwd");
      const cmdEl = document.getElementById("resume-cmd");
      const copyBtn = document.getElementById("resume-copy");
      const statusEl = document.getElementById("resume-status");
      if (toggle && cwdEl && cmdEl) {
        cwdEl.textContent = row.cwd || "the session's project";
        cmdEl.textContent = resumeCommand;
        toggle.hidden = false;
        if (copyBtn) copyBtn.addEventListener("click", () => copyResumeCommand(statusEl));
      }
      // The badge is the thing that actually told you something's wrong --
      // clicking the popover's button separately is one more step than
      // clicking the thing you're already looking at. Re-paint immediately:
      // resumeCommand just became available and the current paint (from
      // whatever checkWatcherHealth tick already ran) does not know that yet.
      makeWatcherBadgeClickable();
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

  // Click-to-copy on the badge itself, not just the popover button: the
  // badge is what told you something needs fixing, so it should be the
  // thing you act on. Only wired up once resumeCommand is known (owner +
  // slug resolved) -- clicking it before then would either do nothing or
  // copy a stale value, and a read-only viewer could not use the command
  // anyway. Attached once, not on every repaint, so a click mid-animation
  // never double-fires.
  let watcherBadgeClickable = false;
  function makeWatcherBadgeClickable() {
    if (watcherBadgeClickable || !resumeCommand) return;
    const badge = document.getElementById("watcher-badge");
    if (!badge) return;
    watcherBadgeClickable = true;
    badge.classList.add("watcher-badge--clickable");
    badge.setAttribute("role", "button");
    badge.setAttribute("tabindex", "0");
    const activate = async () => {
      const original = badge.textContent;
      // Feedback on BOTH outcomes -- a click that silently does nothing on
      // failure is indistinguishable from a click that was never wired up
      // at all, which is exactly the bug this replaces (see script.js's
      // file:line copy-on-click, which learned the same lesson first).
      const copied = await copyResumeCommand(null);
      const flash = copied ? "Copied!" : "Copy unavailable";
      badge.textContent = flash;
      setTimeout(() => { if (badge.textContent === flash) badge.textContent = original; }, 1200);
    };
    badge.addEventListener("click", activate);
    badge.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
    });
  }

  function paintWatcherHealth(seenAt) {
    const badge = document.getElementById("watcher-badge");
    if (!badge) return;
    const clickableCls = watcherBadgeClickable ? " watcher-badge--clickable" : "";
    const copyHint = resumeCommand
      ? " Click to copy “" + resumeCommand + "”."
      : "";
    if (seenAt == null) {
      badge.hidden = false;
      badge.className = "watcher-badge watcher-stale" + clickableCls;
      badge.textContent = "Unwatched";
      badge.title = "No Claude Code session has watched this page yet -- "
        + "a comment will queue, but nothing will answer it." + copyHint;
      return;
    }
    const ageMs = Date.now() - seenAt * 1000;
    if (ageMs > WATCHER_STALE_MS) {
      badge.hidden = false;
      badge.className = "watcher-badge watcher-stale" + clickableCls;
      badge.textContent = "Unwatched";
      badge.title = "The session that answers comments here has been silent "
        + "for " + Math.round(ageMs / 60000) + " min." + copyHint;
    } else {
      badge.hidden = false;
      badge.className = "watcher-badge watcher-live" + clickableCls;
      badge.textContent = "Watching";
      badge.title = "A live Claude Code session is watching this page and "
        + "will answer comments." + copyHint;
    }
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
