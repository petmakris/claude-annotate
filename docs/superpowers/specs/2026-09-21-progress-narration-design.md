# Telling the reader what Claude is doing

**Date:** 2026-09-21
**Status:** approved design, ready for an implementation plan

## The problem

A reader comments on a block, Claude goes away for five minutes, and the page
says nothing. Not "nothing useful" — nothing. The reader cannot tell working
from stalled, and the only honest way to find out is to go and look at the
terminal, which defeats the point of the page.

This is not a missing feature. It is a regression with a precise cause.

`skills/annotate/static/script.js:3043` defines `applyProgress(progress)`, which
captions the busy ribbon and each block's "updating" overlay with a live label.
`script.js:3611` calls it on every delta: `applyProgress(data.progress)`.

`data` is synthesised by `skills/annotate/static/compat.js:211`:

```js
handler({ finished: false, busy: busyLocal, consumed: [], blocks, threads }, before);
```

There is no `progress` key. There never is one. `applyProgress` has been
receiving `undefined` and returning immediately since the daemon cutover.

The thing that used to produce those labels, `skills/annotate/hooks/progress_publish.py`,
says so itself in its first line: **"DORMANT since annotate moved onto the
webcompanion daemon."** Nothing registers it — there is no `hooks.json` in that
directory at all — and the registry it reads, `~/.claude/annotate/pending-*.json`,
is not written by the daemon push.

So the reader gets a spinner, the words "Claude is applying your round…", and a
timer counting upward. Proof that *something* is happening, and no information
about what, for as long as it takes.

## What is NOT broken, and was nearly misdiagnosed

`data.busy` is real. `compat.js:184-211` reconstructs the page lock client-side —
locked on submit, unlocked on the daemon's `event-acked` frame — precisely
because the daemon's `/poll` does not report it. The ribbon appears, the timer
ticks, the page locks. Only the *caption* is dead.

This matters for scope: nothing here needs to rebuild the lock, the ribbon's
placement, or the timer. They work. The work is a channel that carries what
Claude is doing, and a panel that shows it.

## What already exists, and is reused rather than reinvented

| Thing | Where | Why it matters here |
|---|---|---|
| Per-item SSE delivery | the daemon's `/stream`, shimmed by `compat.js:192` (`toOldShape`) | Progress needs no new transport. An item write already reaches the page as a delta frame within milliseconds. |
| Single-item write route | `PUT /s/<sid>/items/<anchor>`, exercised by `tests/test_browser_review.py:86` | A progress write is one ordinary item write. No daemon change, no new route, works against the installed v1.0.0. |
| The `__`-prefix rule | `compat.js:51` and `:206` | **Corrected during planning:** an anchor absent from `order` still renders (`compat.js:48-52` deliberately appends unordered items so a stored block cannot go invisible). The real guarantee is the prefix — `compat.js:51` skips `__`-prefixed ids when building the block list, and `:206` excludes them from the version map handed to `script.js`. `__progress__` is invisible to the document because of its name, which is a stronger and already-enforced rule. |
| Reserved double-underscore anchors | `__doc__`, `__prev__` (`push.py:36`, `:14`) | The convention for "an item that is not a block" already exists and is already understood by the code that reads items. |
| Preserving an item across a replace | `push.py:148-151` re-inserts `__prev__` after reading existing items | The exact mechanism `__progress__` needs, already written and already tested. |
| The busy ribbon's geometry | `.busy-banner` (`style.css:1038`) — sticky, `top: 0`, under the header, `max-width: var(--content-max)` | The panel is this object with a body. Its position was already argued out; that argument is not reopened. |
| `body.read-only` | `core.css:783` and friends | The established way the page hides what a guest must not see. |

## Decisions taken

1. **Narration, not tool labels.** The dormant hook published a coarse label
   keyed on tool name from a fixed allowlist — "Reading files…", "Working…".
   That is cheap and safe and does not solve the problem: five minutes of
   "Reading files…" tells a reader as little as five minutes of nothing. Claude
   writes what it is actually doing, in its own words. The cost is tokens and a
   trust boundary that is now judgement rather than an allowlist; decision 7
   handles the second.

2. **Progress rides the items channel.** Claude writes an item at anchor
   `__progress__`. Nothing in the daemon changes. The alternative — a
   first-class progress route, SSE frame kind, and poll field in `webcompanion` —
   is the better long-term shape and every migrated skill would get it, but it
   is a second repository, a release, a `pipx` reinstall, and version-skew
   handling in annotate, in exchange for carrying strings that the item channel
   already carries. The door stays open: if deck, dataflow or walkthrough want
   the same thing, promote it then, knowing what good narration looks like.

3. **Written with `PUT`, never `PATCH … replace: true`.** `push.py:153` replaces
   the whole item set on every push. A progress write must not go near that
   path. Conversely, **`push.py` must preserve `__progress__` across its
   replace**, the same way it already preserves `__prev__` — otherwise the
   re-push that delivers Claude's answer deletes the record of how it got there,
   in the same instant the reader would want to look at it.

4. **`compat.js:210` must exempt the progress anchor.** Today:

   ```js
   if (ev.kind === "item" && busyLocal) setBusyLocal(false);
   ```

   Any item change clears the lock. That rule exists as a fallback for a daemon
   too old to send `event-acked`, and it is correct for document items. For
   `__progress__` it is exactly wrong: Claude's first narration line would
   unlock the page and dismiss the ribbon the narration is meant to caption.
   This is the one edit to existing behaviour the design requires.

5. **The panel is quiet, but still reads as a lock.** The accent-blue ribbon is
   currently the only thing that says "you cannot submit another round". The
   narration panel is a plain surface — information, not an alarm — with a thin
   accent left edge retained so the lock is still legible. Chosen from rendered
   mockups in the product's own stylesheets, not from description.

6. **Open by default while working, collapsed to a summary when done.** The
   complaint is silence; a panel that requires a click to reveal that anything
   is happening does not answer it. When `state` flips to `done` it becomes one
   line — "Claude worked for 4 min 20 s across 9 steps" — that expands.

7. **Hidden entirely from a read-only viewer — client-side, and that is the
   whole of it.** Narration names file paths, repository structure and what
   Claude looked at. The daemon binds `0.0.0.0` and this machine has Tailscale
   sharing configured, so these pages do get shared. The document is what the
   author chose to share; the trail of how it was produced is not, so
   `body.read-only` hides the panel completely — not greyed, not collapsed:
   absent, and `progress.js` refuses to render it at all unless
   `/api/whoami` said `writable`.

   **This is a presentation choice, not a confidentiality boundary.** Measured
   against this machine's daemon from its LAN address with no owner token:
   `/api/whoami` returns `{"writable": false}`, and `GET /s/<sid>/items` still
   returns `200` with every item in it, `__`-prefixed anchors included —
   `__progress__` body, steps and all. `compat.js` fetches that route on every
   page load, guest included, so the trail **is delivered to a guest's browser**
   and can be read with one `curl` by anyone holding the share link. Nothing
   here withholds the data; the panel simply is not drawn.

   Gating `__`-prefixed anchors server-side would be a change to
   `webcompanion`, which decision 2 puts out of scope for this branch. Until
   someone makes that change, the containment is decision 1's rule in
   `handling-events.md` — narration must not carry output, secrets or tokens —
   and that rule is load-bearing rather than belt-and-braces.

8. **The feed pins to its newest line.** Observed in the mockup: with a
   `max-height` and no scroll management, the one line the reader most wants —
   the current one — is the line clipped off the bottom.

9. **Narration is mandatory at named points, not encouraged.** See the contract
   below. The failure being fixed is silence, and an instruction to "narrate as
   you go" reproduces it under pressure.

## The narration contract

`skills/annotate/references/handling-events.md` describes each event type as a
numbered list of steps. Narration becomes numbered steps in those lists — the
same standing as acknowledging the event or re-pushing the document, not an
aside in prose.

The points, in order of when they occur:

| When | Example line |
|---|---|
| On receiving the event, before anything else | `Read your comment on section-3` |
| **Before** each step it takes | `Looking for where the currency conversion actually happens` |

A *step* is a distinct piece of work — a search, a pass of reading, a command
run, a rewrite — not an individual tool invocation. Three greps answering one
question are one step and get one line. This matters: narrating per tool call
would turn the panel into a log nobody reads, and would make the write volume
in the Risks section real.
| When a finding changes direction | `Found it: the importer normalises, the API does not` |
| Before writing the answer | `Rewriting the block with what I found` |
| On completion | the summary, written as `state: "done"` |

**Before, not after.** A line written after a ninety-second search arrives
ninety seconds too late — the silence it was supposed to fill has already
happened. This is the same rule that fixed the equivalent problem in multi-agent
runs, and it is the whole reason the contract is worth writing down.

Claude writes a line with:

```
python3 -m skills.annotate.progress --sid "$WC_SID" --text "Reading how anchors resolve"
```

and closes the round with `--done`. The module is stdlib-only and speaks to the
daemon through the same `_request` helper shape `push.py:56` uses, carrying the
contract header and the write token.

## Components

**`skills/annotate/progress.py`** (new) — `note(sid, text)` appends a step;
`finish(sid)` flips `state` and stamps the total. Reads the current item,
appends, writes back with `PUT`. One clear job, no knowledge of blocks.

**`skills/annotate/static/progress.js`** (new) — reads the `__progress__` item
out of the delta stream, renders the panel, pins to the newest line, collapses
on `done`, and renders nothing at all under `body.read-only`. Mounted like the
other page modules, from `entry.js`'s `JS` list.

**The item body:**

```json
{
  "id": "__progress__",
  "kind": "progress",
  "state": "working",
  "started_at": 1789999999,
  "event_id": "evt-…",
  "steps": [{"t": 1789999999, "text": "Read your comment on section-3"}]
}
```

`event_id` is carried so a stale panel from a previous round is recognisable
rather than silently shown against new work.

**How the page learns a line arrived.** `compat.js:207` strips `__`-prefixed
anchors out of the version map before `script.js` sees it, so `script.js` never
hears about a progress write — which is correct, and means the panel needs its
own signal. `compat.js` gains a `annotate:progress` DOM event, mirroring the
`annotate:busy` event it already dispatches at `:189` and that `subunits.js:836`
already consumes. `progress.js` listens for it and re-reads the item through
`window.WebCompanion.fetchJSON("raw?block=__progress__")`, a route `compat.js`
already serves.

## Deletions

| Gone | Where | Why |
|---|---|---|
| `applyProgress` and its call | `script.js:3043`, `:3611` | Superseded. It captioned a single label from a map keyed by event id; the panel replaces it. |
| `hooks/progress_publish.py` | the whole file | Dormant since the cutover, and the feature it advertises is being rebuilt differently. A file that documents a working feature nobody can reach is worse than no file. |

The per-block `.updating-label` (`script.js:3051`, built at `:2133`) stays. It is fed by the same
`applyProgress` today and will be fed by `progress.js` instead: a block being
rewritten should still say so on the block.

## Tests

Source-level, matching the repo's existing smoke style:

1. `__progress__` is never added to `__doc__.order` — asserted against
   `items_for`, so the invisibility is a property of the builder and not of a
   filter.
2. `push.py` preserves an existing `__progress__` across its `replace: true`
   PATCH, exactly as it preserves `__prev__`.
3. `compat.js`'s unlock rule names the progress anchor as an exemption.
4. `progress.js` is in `entry.js`'s `JS` list.
5. The dormant hook is gone and nothing references it.

Browser, against a live daemon — the level that matters, because three CSS
defects in this page's history passed every source-level test and were caught
only by computed styles and rects:

6. Writing progress items through the daemon API makes lines appear in the
   panel, in order, without a reload.
7. The newest line is visible — measured, not assumed — after enough lines to
   overflow the panel's `max-height`.
8. `state: "done"` collapses the panel to one line, which expands.
9. A page with `body.read-only` renders no panel at all.
10. A progress write does **not** clear the busy lock (decision 4), and does not
    render a block or disturb the document's block count (decision 2).

## Risks

- **Narration only happens if Claude narrates.** This is the whole design's
  weak point. If the contract is skipped, the reader gets a panel that promises
  detail and delivers a single stale line — arguably worse than today's honest
  spinner. Mitigation is that the steps are numbered items in the event flow,
  and that the panel shows its own elapsed timer and step count, so a stalled
  narration is visibly stalled rather than ambiguous.
- **An item write that the renderer does not expect.** `script.js` diffs item
  versions and re-renders what moved. `__progress__` is not in `order`, but
  whether the render path ignores an unknown moved anchor cleanly, or logs and
  limps, is not established by reading — test 10 exists to settle it in a
  browser.
- **Write volume.** One HTTP round trip per narration line. At the contract's
  cadence that is single-digit writes per round; it is not a concern, but a
  future "narrate every tool call" would make it one.
- **The trust boundary moved.** The old hook could not leak anything because it
  could only emit allowlisted strings. Narration is Claude's prose and can name
  paths. Decision 7 turns out **not** to be the containment it was drafted as:
  the hide is client-side, and the daemon hands `__progress__` to any holder of
  the link. The actual containment is the contract rule that narration carries
  no output, secrets or tokens — a judgement call where there used to be an
  allowlist, and now the only thing standing between the trail and a guest.
