// annotate page code, part 7 of 9 (see script.js): the page lock and the
// watcher state the poll delta drives.

// ── Polling / block refresh ────────────────────────────────────────────────

function clearUpdatingOverlay(section) {
  section.classList.remove("is-updating");
  if (section._updatingTimerId) {
    clearInterval(section._updatingTimerId);
    section._updatingTimerId = null;
  }
  section.querySelector(".updating-overlay")?.remove();
}

// Clear the "updating" UI for every comment whose event Claude has acked.
// This is the real done-signal: it fires whether Claude answered by
// rewriting the commented block, a neighbour, a new block, or nothing —
// none of which the old "same-block version bump" check could detect.
function handleConsumedEvents(consumed) {
  if (!Array.isArray(consumed) || pendingEvents.size === 0) return;
  for (const eid of consumed) {
    const key = String(eid);
    const pend = pendingEvents.get(key);
    if (!pend) continue;
    pendingEvents.delete(key);
    if (pend.blockId) {
      const section = document.querySelector(`section.block[data-block-id="${cssEsc(pend.blockId)}"]`);
      if (section) clearUpdatingOverlay(section);
    } else if (pend.round) {
      for (const id of pend.blockIds || []) {
        const section = document.querySelector(`section.block[data-block-id="${cssEsc(id)}"]`);
        if (section) clearUpdatingOverlay(section);
      }
    } else if (pend.general) {
      const statusEl = document.getElementById("general-status");
      if (statusEl) statusEl.textContent = "responded";
    }
  }
}

// Ticking timer for the busy banner's .bb-timer, started when the banner
// is created and cleared when it's removed.
let busyTimer = null;

// Server-authoritative page lock. `data.busy` is true while any submitted
// event is unacked; reflect it as body.is-busy + a banner. Survives reload
// and is consistent across devices because it is recomputed each poll.
function setBusy(busy) {
  document.body.classList.toggle("is-busy", !!busy);
  let banner = document.getElementById("busy-banner");
  if (busy) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "busy-banner";
      banner.className = "busy-banner";
      banner.setAttribute("role", "status");
      banner.setAttribute("aria-live", "polite");
      const spin = document.createElement("span");
      spin.className = "busy-spinner";
      const label = document.createElement("span");
      label.className = "bb-label";
      label.textContent = "Claude is applying your round…";
      const timer = document.createElement("span");
      timer.className = "bb-timer";
      // No sub-label node. One was created here for a promised "3 of 5 marks
      // applied" progress line, but nothing could write it: the old
      // PostToolUse hook that once captioned it mapped tool names onto a
      // fixed allowlist ("Editing the response…", "Working…") and knew
      // nothing about mark counts. An empty span still consumed a flex gap.
      banner.append(spin, label, timer);
      banner.dataset.startedAt = String(Date.now());
      // Place the lock ribbon at the top of the content (just under the
      // header, above the composer) so it pins flush to the top of the
      // screen when the page scrolls — not buried below the composer.
      const header = document.querySelector(".page-header");
      if (header) header.insertAdjacentElement("afterend", banner);
      // Fallback for a shell with no header at all. It used to anchor on
      // .general-composer, which is now a band of the top bar — landing the
      // ribbon inside the chrome it is supposed to sit below. The document
      // itself is the only anchor that still means "top of the content".
      else proseEl?.parentNode?.insertBefore(banner, proseEl);
    }
    if (!busyTimer) {
      busyTimer = setInterval(() => {
        const b = document.getElementById("busy-banner");
        if (!b) return;
        const t = Math.floor((Date.now() - Number(b.dataset.startedAt || Date.now())) / 1000);
        const el = b.querySelector(".bb-timer");
        if (el) el.textContent = `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
      }, 1000);
    }
  } else if (banner) {
    if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
    banner.remove();
  }
}

// The statusline strip was here: a live mirror of the terminal's context
// %, model, rate limits and diff, polled from GET <base>/statusline.
//
// It worked because annotate's own server read a snapshot file off the disk
// on request. The daemon that replaced it is deliberately not allowed to
// read arbitrary paths, and that restraint is worth more than the widget —
// so compat.js answered the route with {ok:false} and the strip hid itself
// for good. This removes ~70 lines of renderer, its CSS and its markup,
// which had been kept alive only by a shim hard-wired to say "no".
//
// Reviving it means giving the daemon a real route with a real source of
// truth, not restoring this code.

// A heartbeat older than this means the watcher (and the Claude session
// that owns it) is dead, not slow — the watcher writes every ~1s, including
// while it blocks on an ack.
const WATCHER_DEAD_AFTER_S = 15;

// The session behind this page died mid-event (crash, closed terminal).
// Without this, the unacked event keeps busy=true forever and the page
// stays locked with a spinner that lies. Show the truth and unlock.
function setWatcherDead(dead) {
  let banner = document.getElementById("watcher-dead-banner");
  if (dead) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "watcher-dead-banner";
      banner.className = "watcher-dead-banner";
      banner.setAttribute("role", "alert");
      banner.setAttribute("aria-live", "assertive");
      const label = document.createElement("span");
      label.textContent =
        "Claude's session is gone. Your last submission is still queued — " +
        "it will be picked up when a Claude session reattaches to this page. " +
        "Run `/annotate resume` from a Claude session to continue. " +
        "Don't resubmit; it would apply the same round twice.";
      banner.append(label);
      const header = document.querySelector(".page-header");
      if (header) header.insertAdjacentElement("afterend", banner);
      else document.body.insertBefore(banner, document.body.firstChild);
    }
  } else if (banner) {
    banner.remove();
  }
}

// Advisory-only: more than one live Claude session (watcher) is heartbeating
// on this workspace at once — e.g. two terminals reopened the same slug.
// Purely informational, doesn't gate anything the way setBusy/setWatcherDead
// do. The pill lives in the header title and is created once, then just
// toggled — unlike the busy/watcher-dead banners it isn't inserted/removed
// per poll.
function setAttachedPill(count) {
  let pill = document.getElementById("attached-pill");
  if (!pill) {
    const title = document.querySelector(".header-title");
    if (!title) return; // header not rendered (yet); try again next poll
    pill = document.createElement("span");
    pill.id = "attached-pill";
    pill.className = "attached-pill";
    title.appendChild(pill);
  }
  const show = typeof count === "number" && count > 1;
  pill.textContent = show ? `${count} sessions attached` : "";
  pill.classList.toggle("show", show);
}
