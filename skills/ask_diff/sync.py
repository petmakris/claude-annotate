"""Live-sync engine for ask_diff (daemon `kind` "interactive-review"): keeps
a PR review session's diff and comment-thread anchors from going stale after
a local push/rebase/squash on the reviewed branch.

Merged module, not a thin wrapper: this file owns both what the old
2026-09-01 design split into `notify_change.py` (find which live session(s)
belong to the branch that just changed) and `sync.py` (re-fetch the diff and
migrate every thread's anchor). There is no per-skill HTTP server left to put
a `/resync` endpoint on, so both jobs collapse into one CLI invoked directly
by a git hook -- `python3 -m skills.ask_diff.sync`, no arguments -- which is
also why `main()` resolves `$PWD` and the current branch itself rather than
taking them as flags.

Ordering guarantee in `resync()`: every thread's anchor migration (Step 4/5
below) runs to completion BEFORE the refreshed `__diff__`/`__meta__` are
pushed (Step 6). A thread is never left pointing at the old file's line
numbers against the new file's content, even for the instant between writes
-- matches the original design's own reasoning verbatim.

Anchor occupancy, and the one invariant every part of the migration logic
below exists to enforce: a thread is identified ONLY by its anchor string on
the daemon's side -- there is no separate thread id -- so writing one
thread's messages into an anchor another thread still occupies silently
interleaves two unrelated conversations into one thread file, irreversibly
and with no error. The invariant is therefore:

    a thread may only be migrated into an anchor once that anchor's
    occupant -- whatever that occupant ultimately turns out to be -- has
    genuinely vacated it.

"Ultimately turns out to be" is the hard part, and is what three earlier
cuts of this code each got wrong in a different way. A thread's final
resting anchor is NOT simply what `anchor_migrate.locate()` says: a thread
whose computed target is blocked doesn't move at all, so it keeps occupying
its own old anchor -- which can in turn block a THIRD thread that the naive
one-shot census had already cleared as safe. `resync()` therefore resolves
the whole session's threads to a FIXED POINT before touching the daemon at
all, in five phases:

Phase 1 (pure resolution): every thread's naive target -- its own anchor for
EXACT, for STALE, for a gone/unreadable file, and for a thread whose
resolution itself raised; the computed new anchor string for MOVED. No
mutation, so nothing below can depend on which thread the daemon happened to
return first. An earlier single-pass, seen-so-far "occupied" check was
order-dependent in exactly this way and false-positived deterministically
(not rarely) on the ordinary "someone inserted N lines near the top of the
file, and two comments happened to be N lines apart" commit.

Phase 2 (resumable self-migrations): `_migrate_thread` appends every message
to the new anchor and then deletes the old one, so either half hiccupping (a
daemon blip, not a bug) leaves ONE thread's content sitting at TWO anchors.
Reuniting those fragments is a repair, not a merge, and failing to recognise
them as fragments orphans a thread against its own copy forever, re-firing
the same bogus "collision" event on every future commit. Common origin is
decided by `source_event_id` OVERLAP in either direction (`my_ids &
their_ids`, not containment): ids are globally unique per submitted event, so
a single shared id already proves it -- and a directional containment check
gets this wrong half the time, since an interrupted APPEND LOOP leaves the
target with a SUBSET of the source's ids while an interrupted DELETE leaves
it with a SUPERSET.

The fragments do not have to be sitting on each other, which is why the
question is asked per TARGET rather than per thread. Asking only "is my own
duplicate the thread currently occupying my target" heals the interruption
on the very next hook firing and never again: the commit AFTER that moves
the anchored line once more, both copies carry the same `anchor_text` and so
re-locate to the same third line that neither of them occupies, and each
then looks like an ordinary mover converging on a contested position. So
phase 2 groups everything that would end up at a given target -- the movers
claiming it, plus its own current occupant if it has one -- by common
origin, and heals a group only when it is unambiguously the one thread that
belongs there: exactly one group among them has more than one member (two
would make the winner arbitrary, none is the ordinary contested target), any
current occupant is IN that group, and that occupant is not itself moving
away (merging into a spot its own occupant is about to delete is the very
interleaving this mechanism exists to prevent). The healed position is then
locked, so a claimant left OUT of the group collides with the reunited
thread and is orphaned instead of being quietly folded into the repair.
Everything in a healing group is removed from collision consideration: the
daemon's own dedup makes the union of their messages, applied in any order,
exactly what one uninterrupted migration would have produced.

Phase 3 (fixed-point collision resolution): `locked` starts as every anchor
permanently occupied by a thread that is not going anywhere -- EXACT, STALE,
unreadable-file, and phase-1-failed. Every remaining mover is then repeatedly
tested against it: a mover whose target is `locked`, or whose target is
claimed by another surviving mover too, cannot execute, so it is orphaned
(`reason="collision"`, `attempted_anchor` naming where it would have gone)
and -- this is the step whose absence caused the third bug -- its OWN anchor
joins `locked`, because a thread that doesn't move keeps occupying where it
already is. That newly locked anchor can block a mover the previous round
had cleared, so the loop repeats until a full round marks nothing new. The
shape that needs this is three threads deep, which is why two-thread
regression tests kept missing it: A moves 5->8, B moves 8->20, D sits EXACT
at 20. B is blocked by D and stays at 8 -- so A, whose target 8 looked
uncontested in a one-shot census, is walking straight into B.

Phase 4 (topological execution): the movers that survive phase 3 each have a
target claimed by nobody else and locked by nobody, so the "my target is
your source" graph over them is a disjoint union of simple paths and cycles
(no anchor can be more than one survivor's dependency). Order still matters:
`_migrate_thread` appends then deletes, so if thread A's target anchor is
thread B's CURRENT (not-yet-vacated) anchor, running A before B appends A's
messages into a spot B is about to delete out from under it -- destroying
A's content with no error, no orphan event, and `resync()` reporting
`ok=True`. A mover therefore runs only once its target has either never been
anyone's own anchor or has already been vacated by that thread's own
completed migration (a resumable self-migration from phase 2 vacates its
anchor too, and counts here). Two commented lines that swapped places form a
genuine 2-cycle -- no execution order can save both -- so a cycle's threads
are orphaned in place instead (`reason="cycle"`), never destructively
executed.

Phase 5 (I/O): orphan events, then the resumable self-migrations, then the
ordered clean movers. Every phase before this one is pure, so a daemon call
failing part-way through phase 5 can only ever affect the one thread that
raised -- there is no running "occupied" set for a failure to leave stale.

Role decision (Global Constraints flagged this as Task 2's to settle, since
Task 1's `push.py` never calls `append_thread` and so never wrote a role):
replayed messages preserve whatever role each message already carries
(`msg.get("role", DEFAULT_ROLE)`) -- the daemon's own `_append_to_thread`
handler always stores a role (`msg.setdefault("role", "agent")` server-side),
so this is a straight replay, not a rewrite. `DEFAULT_ROLE` documents this
skill's own reply-flow convention going forward, for whatever future code
(SKILL.md's Mode D, built in a later task) constructs a brand-new message:
`"agent"`, matching the daemon's own default and every other migrated skill
(dataflow, walkthrough, deck) -- NOT `"claude"`, the historical role name
`ask_diff/server.py`'s `threads_bulk()` filtered on before this migration.
`"claude"` was a pre-daemon accident, never a functional requirement; keeping
it would mean Task 3's Java-side thread-derivation needs a one-off filter no
other skill needs, for a name with no reader left that cares once the old
server.py is deleted. This is a real behavior change from the pre-daemon
skill, called out here since Task 3 depends on it.

Timestamp loss (Global Constraints, stated plainly here as required): the
shared client's `append_thread` has no `ts` parameter, so a replayed message
gets a new server-assigned timestamp, not its original one. Accepted,
small, cosmetic -- see the plan's Global Constraints for the full reasoning.

Anchor source for `anchor_migrate.locate()`: the working tree on disk
(`(Path(cwd) / path).read_text().splitlines()`), not the freshly-fetched
diff. `locate()` mirrors `AnchorResolver.resolve()`, which re-locates an
anchor against "the live document the IDE has open" -- a diff's hunks don't
carry the full file, only changed regions plus a little context, so it
cannot answer "what is line N today" for an arbitrary N. The working tree is
also what's actually current at hook-fire time: `post-commit`/`post-rewrite`/
`post-checkout` all fire only once the working tree already reflects the new
HEAD. This inherits the original design's own simplification of never
distinguishing an anchor's `L`/`R` side when picking which ref to read --
both sides are resolved against the one checked-out copy of the file, same
as the IDE panel's own live-editor read.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills._shared.web_companion import anchor_migrate
from skills.ask_diff import diff as diff_module
from skills.ask_diff.push import KIND, DIFF_ANCHOR, META_ANCHOR

# This skill's own reply-flow role convention -- see the module docstring's
# "Role decision" section. Used only as a safety-net default: every message
# the daemon has ever stored already carries a role, so `msg.get("role", ...)`
# falling through to this is not expected to happen in practice.
DEFAULT_ROLE = "agent"

_ANCHOR_RE = re.compile(r"^(.+):([LR]):(\d+)(?:-(\d+))?$")
_SEARCH_WINDOW = 25  # keep in lockstep with AnchorResolver.DEFAULT_K

_GIT_TIMEOUT = 30


def _parse_anchor(anchor: str) -> tuple[str, str, int, int] | None:
    """(path, side, start, end) for a locatable `path:side:line[-line]`
    anchor, or None for anything else (e.g. `__general__`)."""
    m = _ANCHOR_RE.match(anchor)
    if not m:
        return None
    path, side, start, end = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    return path, side, start, (int(end) if end else start)


def find_matching_sessions(cwd: str, head: str) -> list[str]:
    """Every live `interactive-review` session at `cwd` whose recorded head
    branch (from its own `__meta__` item) equals `head`.

    The daemon's session rows carry no head-branch field of their own
    (`_row()`'s shape is `{sid, slug, kind, cwd, title, url}`) -- that lives
    only in the `__meta__` item Task 1's `push.py` writes, so each candidate
    needs its own `get_items` round trip. A session with no `__meta__` item
    yet (never successfully pushed) is skipped, not an error -- same
    treatment as a candidate whose items fetch itself fails (an ended or
    otherwise unreadable session should not block resync for the others).
    Every match is returned; multiple matches all get resynced.
    """
    rows = wc.list_sessions(cwd, KIND)

    matches: list[str] = []
    for row in rows:
        sid = row.get("sid")
        if not sid:
            continue
        try:
            items = wc.get_items(sid, kind=KIND)
        except Exception:
            continue
        meta_item = items.get(META_ANCHOR)
        if not meta_item:
            continue
        if meta_item.get("body", {}).get("head") == head:
            matches.append(sid)
    return matches


def _source_event_ids(thread: dict) -> set[str]:
    """Every `source_event_id` this thread's messages carry (message ids with
    none set are excluded, not counted as a shared `None`). Used only to tell
    a genuine collision apart from a thread's own stuck duplicate -- see the
    module docstring's phase 2."""
    return {m.get("source_event_id") for m in thread.get("messages", [])
           if m.get("source_event_id") is not None}


def _emit_orphaned(sid: str, anchor: str, thread: dict, *,
                   reason: str = "stale", attempted_anchor: str | None = None) -> None:
    """`reason` distinguishes why this anchor could not be kept live:

    - `"stale"` (default): the reviewed line's content drifted too far for
      `anchor_migrate.locate()` to relocate it -- there is nowhere for this
      thread to go.
    - `"collision"`: `locate()` DID find a home for this thread, but that
      target anchor is not available -- a different thread occupies it and
      is not leaving (an EXACT one, one orphaned-for-audit in this same
      pass, or one itself blocked from moving and therefore staying put), or
      another thread is converging on the very same target. See the module
      docstring's phase 3. `attempted_anchor` names where this thread would
      have moved to, so the message can be honest about why.
    - `"cycle"`: this thread's target and at least one other thread's target
      form a cycle (e.g. two commented lines swapped places) -- no execution
      order can migrate either without first destroying the other's
      not-yet-relocated content, so both are orphaned in place instead.
      `attempted_anchor` names where this thread would have moved to.
    """
    payload = {
        "event_kind": "anchor_orphaned",
        "thread_title": thread.get("title", ""),
        "old_anchor_text": thread.get("anchor_text", ""),
        "reason": reason,
    }
    if attempted_anchor is not None:
        payload["attempted_anchor"] = attempted_anchor
    wc.submit_event(sid, anchor, json.dumps(payload), kind=KIND)


def _migrate_thread(sid: str, old_anchor: str, new_anchor: str, thread: dict,
                    anchor_text: str) -> None:
    """Replay every message from `old_anchor` onto `new_anchor`, in original
    order, then delete `old_anchor`. `source_event_id` travels with each
    message (idempotency: a repeat replay dedups server-side). `anchor_text`
    only rides on the first call (first-write-wins on the daemon's side,
    matching `set_anchor_text_if_absent`'s semantics); `title` rides on
    every call since it's thread-level and last-write-wins -- redundant, not
    incorrect, to send it every time.
    """
    title = thread.get("title") or None
    for i, msg in enumerate(thread.get("messages", [])):
        wc.append_thread(
            sid, new_anchor, msg.get("text", ""),
            kind=KIND,
            role=msg.get("role", DEFAULT_ROLE),
            source_event_id=msg.get("source_event_id"),
            title=title,
            anchor_text=anchor_text if i == 0 else None,
        )
    wc.delete_thread(sid, old_anchor, kind=KIND)


def resync(sid: str, cwd: str) -> dict:
    """Re-fetch the diff and migrate every thread's anchor against the real,
    current working tree.

    Returns a summary: `{"sid", "ok", "diff_fetch_failed", "error",
    "migrated": [<new anchors>], "orphaned": [<old anchors>],
    "failed_threads": [<anchors that raised mid-migration>],
    "collided": [<old anchors orphaned because their target is occupied by
    an unrelated thread that is not leaving it, or claimed by another
    thread converging on it too -- a subset of "orphaned">],
    "cycled": [<old anchors orphaned because their targets formed a cycle
    with each other, a subset of "orphaned">]}`. Any failure
    before migration starts (reading the session's own items, the diff
    fetch itself, reading its threads) leaves everything untouched and
    returns with `ok=False` -- a session with a stale-but-known-good
    snapshot is strictly better than one half-overwritten. `diff_fetch_failed`
    is set specifically when `fetch_pr_diff` itself is what failed (a `gh`/
    network problem, likely to clear up on the next hook firing), as
    distinct from a malformed or unreadable session.

    Per-thread failure isolation: one thread's `append_thread`/`delete_thread`/
    `submit_event` call raising (a daemon hiccup mid-migration) does not abort
    the rest of the loop -- every other thread in this session still gets
    attempted, and whichever anchors DID migrate or orphan successfully stay
    reflected in `migrated`/`orphaned` below. But if ANY thread failed, the
    final `put_items` refresh (Step 6) is skipped entirely and `ok` is
    `False` -- extending the same "a stale-but-known-good snapshot beats a
    half-overwritten one" reasoning the failed-diff-fetch path already uses:
    pushing a fresh diff while some thread's anchor never got migrated onto
    it would leave that thread visibly wrong against content it was never
    checked against, which is worse than the session just not refreshing on
    this hook firing (idempotency means the next firing retries the whole
    thing safely).
    """
    summary: dict = {
        "sid": sid, "ok": False, "diff_fetch_failed": False,
        "error": None, "migrated": [], "orphaned": [], "failed_threads": [],
        "collided": [], "cycled": [],
    }

    try:
        items = wc.get_items(sid, kind=KIND)
    except Exception as e:
        summary["error"] = f"could not read session items: {e}"
        return summary

    meta_item = items.get(META_ANCHOR, {}).get("body", {})
    pr_ref = meta_item.get("pr_ref")
    if not pr_ref:
        summary["error"] = "no pr_ref recorded in __meta__"
        return summary

    try:
        diff_text, gh_meta = diff_module.fetch_pr_diff(pr_ref, cwd)
    except Exception as e:
        summary["diff_fetch_failed"] = True
        summary["error"] = f"gh fetch failed: {e}"
        return summary

    try:
        threads = wc.get_threads(sid, kind=KIND)
    except Exception as e:
        summary["error"] = f"could not read threads: {e}"
        return summary

    file_lines_cache: dict[str, list[str] | None] = {}

    def lines_for(path: str) -> list[str] | None:
        """Cached full-file read, mirroring what the IDE reads from its live
        editor document. None means the file no longer exists at this path
        (renamed or deleted) -- treated the same as a STALE match."""
        if path not in file_lines_cache:
            try:
                file_lines_cache[path] = (Path(cwd) / path).read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                file_lines_cache[path] = None
        return file_lines_cache[path]

    migrated: list[str] = []
    orphaned: list[str] = []
    failed_threads: list[str] = []
    collided: list[str] = []
    cycled: list[str] = []

    # ---- Phase 1: resolve every thread's NAIVE target -- what `locate()`
    # alone says, with no cross-thread reasoning yet. No mutation here, so
    # nothing below can depend on which thread the daemon happened to return
    # first -- see the module docstring's "Anchor occupancy" note.
    # `raw_target[anchor]` is:
    #   - the SAME anchor, for EXACT (nothing to migrate) and for a thread
    #     that is going to be orphaned (STALE, or its file is gone/
    #     unreadable) -- orphaning leaves the thread sitting at its own
    #     anchor, untouched, so it still occupies that slot going forward.
    #   - a NEW anchor string, for MOVED.
    # `stale_anchors` records which anchors need a `reason="stale"` orphan
    # event in phase 5 (their target equals their own anchor for a different
    # reason than EXACT's "nothing changed").
    raw_target: dict[str, str] = {}
    stale_anchors: set[str] = set()

    for anchor, thread in threads.items():
        parsed = _parse_anchor(anchor)
        if parsed is None:
            continue  # not a locatable path:side:line anchor -- leave alone
        path, side, start, end = parsed
        anchor_text = thread.get("anchor_text") or ""

        try:
            lines = lines_for(path)
            if lines is None:
                raw_target[anchor] = anchor
                stale_anchors.add(anchor)
                continue

            res = anchor_migrate.locate(lines, start, anchor_text, k=_SEARCH_WINDOW)
            if res.kind is anchor_migrate.Kind.STALE:
                raw_target[anchor] = anchor
                stale_anchors.add(anchor)
                continue
            if res.line == start:
                raw_target[anchor] = anchor  # EXACT -- nothing to migrate
                continue

            new_end = end + (res.line - start)
            raw_target[anchor] = (f"{path}:{side}:{res.line}" if end == start
                                 else f"{path}:{side}:{res.line}-{new_end}")
        except Exception:
            # Resolving this thread's fate blew up (locate()/lines_for() are
            # pure/self-guarded, so this is an unexpected bug, not a daemon
            # hiccup) -- isolate it the same as any other per-thread failure:
            # recorded, gates the final put_items below. Still seeded at its
            # OWN anchor (never touched, so this is accurate, not merely a
            # placeholder) so it locks that slot in phase 3 below --
            # otherwise a thread whose fate we failed to resolve would vanish
            # from the occupancy census entirely, and something else could
            # migrate into its still-very-much-there anchor undetected.
            failed_threads.append(anchor)
            raw_target[anchor] = anchor

    # ---- Phase 2: pre-resolve resumable self-migrations, so phase 3 never
    # sees a thread's own scattered fragments as a collision between
    # different conversations. `_migrate_thread` appends every message to the
    # new anchor and then deletes the old one, so either half hiccupping
    # leaves ONE thread's content sitting at TWO anchors. Both copies carry
    # the same `anchor_text`, so from the next hook firing on they resolve
    # together, and reuniting them is a repair, not a merge.
    #
    # Who counts as one thread's fragments is decided by `source_event_id`
    # overlap: ids are globally unique per submitted event, so a single
    # shared id already proves common origin. The test is overlap in EITHER
    # direction (`my_ids & their_ids`), never containment in one -- an
    # interrupted delete leaves the target with a SUPERSET of the source's
    # ids, but an interrupted APPEND LOOP leaves it with a SUBSET (fewer
    # messages made it over before the failure), and a one-directional check
    # permanently misdiagnoses whichever half it isn't written for.
    #
    # The fragments do NOT have to be sitting on each other. Checking only
    # "is my own duplicate the thread currently occupying my target" catches
    # the interruption on the very next firing and never again: the commit
    # AFTER that moves the anchored line once more, both copies re-locate to
    # the same third line neither of them occupies, and each then looks like
    # an ordinary mover converging on a contested target. Both get orphaned,
    # the same two bogus "collision" events fire on every subsequent commit,
    # and the duplicate never reconciles. So the question is asked per
    # TARGET, over every thread that will end up there: the movers claiming
    # `tgt`, plus `tgt`'s own current occupant if it has one.
    #
    # A group heals only when it is unambiguously the one thread that
    # belongs at `tgt`:
    #   - exactly ONE common-origin group among them has more than one
    #     member. Two such groups converging on one position would make
    #     whichever we picked an arbitrary winner, and no group at all is the
    #     ordinary contested-target case -- both stay collisions.
    #   - if something already occupies `tgt`, it must be IN that group.
    #     Otherwise the group would be merging into a stranger's thread file.
    #   - that occupant must not itself be moving away. Merging into a spot
    #     its own occupant is about to delete is the very interleaving this
    #     mechanism exists to prevent; such a thread stays an ordinary mover,
    #     so phase 4's ordering makes it wait for the occupant to vacate
    #     first.
    # Claimants of `tgt` left OUT of the healing group are genuine
    # third-party collisions against the reunited thread and are orphaned
    # normally -- phase 3 sees them collide because `tgt` is locked below.
    def _common_origin_groups(anchors: list[str]) -> list[list[str]]:
        """Partition `anchors` into groups that transitively share at least
        one `source_event_id`. A thread carrying no ids at all can never be
        shown to share an origin with anything, so it stays a group of one."""
        groups: list[list[str]] = []
        group_ids: list[set[str]] = []
        for anchor in anchors:
            mine = _source_event_ids(threads[anchor])
            hits = [i for i, ids in enumerate(group_ids) if mine & ids]
            if not hits:
                groups.append([anchor])
                group_ids.append(set(mine))
                continue
            keep = hits[0]
            groups[keep].append(anchor)
            group_ids[keep] |= mine
            for i in reversed(hits[1:]):  # this anchor bridges several groups
                groups[keep].extend(groups[i])
                group_ids[keep] |= group_ids[i]
                del groups[i]
                del group_ids[i]
        return groups

    claimants: dict[str, list[str]] = {}
    for anchor, tgt in raw_target.items():
        if tgt != anchor:
            claimants.setdefault(tgt, []).append(anchor)

    resumable: dict[str, str] = {}
    heal_targets: set[str] = set()
    for tgt, tgt_claimants in claimants.items():
        occupied = tgt in threads
        if occupied and raw_target.get(tgt, tgt) != tgt:
            continue  # its occupant is leaving -- ordinary ordering, not a heal
        members = tgt_claimants + ([tgt] if occupied else [])
        groups = [g for g in _common_origin_groups(members) if len(g) > 1]
        if len(groups) != 1:
            continue
        if occupied and tgt not in groups[0]:
            continue
        heal_targets.add(tgt)
        for anchor in groups[0]:
            if anchor != tgt:
                resumable[anchor] = tgt

    # ---- Phase 3: resolve collisions to a FIXED POINT.
    #
    # `locked` is every anchor whose occupant is never going to leave it:
    # EXACT threads, threads being orphaned as stale, threads whose file is
    # gone, and threads whose phase-1 resolution raised. A mover cannot
    # execute into a locked anchor, and it cannot execute into an anchor
    # another surviving mover also claims.
    #
    # The part that must iterate: a mover blocked on either count doesn't
    # move at all, so it goes on occupying its OWN anchor -- which locks that
    # anchor, which can block a mover the previous round had cleared as safe.
    # Three threads is enough to need this (A moves 5->8, B moves 8->20, D
    # sits EXACT at 20: B is blocked by D, so A is blocked by B), and a
    # single census cannot see it, because at census time B still looked like
    # it was leaving 8. So the loop runs until a full round marks nothing new.
    #
    # `claims` is recomputed once per round and read from the snapshot for
    # every decision in that round, deliberately: deciding against a count
    # that shrinks as the round removes movers would let whichever of two
    # converging movers happens to be visited second look uncontested and
    # execute, making the daemon's iteration order pick an arbitrary winner
    # between two threads that both have an equal claim.
    locked: set[str] = {a for a in threads
                       if a not in resumable and raw_target.get(a, a) == a}
    # A position phase 2 is reuniting a thread's fragments into is occupied
    # by that thread from here on, exactly as if it had never been split --
    # so anything ELSE aiming at it collides, and is orphaned rather than
    # being quietly folded into the repair.
    locked |= heal_targets
    movers: dict[str, str] = {a: t for a, t in raw_target.items()
                             if t != a and a not in resumable}
    collision_targets: dict[str, str] = {}

    changed = True
    while changed:
        changed = False
        claims: dict[str, int] = {}
        for tgt in movers.values():
            claims[tgt] = claims.get(tgt, 0) + 1
        for anchor in list(movers):
            tgt = movers[anchor]
            if tgt not in locked and claims[tgt] < 2:
                continue
            del movers[anchor]
            collision_targets[anchor] = tgt
            locked.add(anchor)
            changed = True

    # ---- Phase 5a: orphan events, and the resumable self-migrations.
    # Every decision was already made above, so a mid-loop failure here can
    # only ever affect the one thread that raised. The surviving movers are
    # deferred to phase 5b below, since THEY need ordering relative to each
    # other.
    vacated: set[str] = set()

    for anchor in raw_target:
        thread = threads[anchor]
        try:
            if anchor in stale_anchors:
                _emit_orphaned(sid, anchor, thread)
                orphaned.append(anchor)
            elif anchor in collision_targets:
                # Writing this thread's messages into `tgt` would silently
                # interleave them into an unrelated conversation -- worse
                # than losing live-tracking on this one thread, since it
                # corrupts a second, otherwise-untouched thread's history
                # rather than just this thread's own. Orphan it at its OLD
                # anchor instead (audit trail preserved, nothing merged) and
                # say where it would have gone.
                _emit_orphaned(sid, anchor, thread, reason="collision",
                              attempted_anchor=collision_targets[anchor])
                orphaned.append(anchor)
                collided.append(anchor)
            elif anchor in resumable:
                tgt = resumable[anchor]
                _migrate_thread(sid, anchor, tgt, thread,
                                thread.get("anchor_text") or "")
                migrated.append(tgt)
                vacated.add(anchor)
        except Exception:
            # One thread's daemon call failing must not abort the rest of
            # this session's threads -- see the docstring's "Per-thread
            # failure isolation" note. Recorded, not swallowed silently: it
            # gates the final put_items below.
            failed_threads.append(anchor)

    # ---- Phase 5b: topologically order and execute the surviving movers.
    # Each one's target is claimed by exactly one anchor and locked by none
    # (phase 3 guarantees both), so the "my target is your source" dependency
    # graph over this set is a disjoint union of simple paths and cycles --
    # no anchor can be more than one survivor's direct dependency, and no
    # path can therefore feed INTO a cycle. `_migrate_thread` appends then
    # deletes, so running a mover before the thread occupying its target has
    # actually vacated it (not merely been "visited") would append into --
    # and then have that thread's own delete call throw away -- the first
    # mover's just-written content. This is the chained-shift bug this phase
    # exists to fix: comments at lines 5 and 8 with 3 lines inserted above
    # both resolve cleanly (5->8, 8->11) but must run in the order 8-then-5,
    # never 5-then-8. A resumable self-migration from phase 5a vacates its
    # own anchor too, so it counts as a dependency here on exactly the same
    # terms -- including when it FAILED, in which case it is missing from
    # `vacated` and whatever waits on it stays blocked rather than executing
    # into a spot that never actually emptied.
    movable_sources = set(movers) | set(resumable)
    remaining = dict(movers)

    progress = True
    while remaining and progress:
        progress = False
        for anchor in list(remaining.keys()):
            tgt = remaining[anchor]
            if tgt in movable_sources and tgt not in vacated:
                continue  # blocked -- `tgt` hasn't actually been vacated yet
            del remaining[anchor]
            progress = True
            try:
                _migrate_thread(sid, anchor, tgt, threads[anchor],
                                threads[anchor].get("anchor_text") or "")
                migrated.append(tgt)
                vacated.add(anchor)
            except Exception:
                # Leave `anchor` OUT of `vacated` -- anything still waiting
                # on it stays blocked for the rest of this pass rather than
                # executing into a spot that never actually emptied.
                failed_threads.append(anchor)

    # Anything left once no further progress is possible is either a genuine
    # cycle (two threads whose lines swapped, say -- a structural property
    # of the data that will recur identically on every future firing until
    # the files change again) or transitively stuck behind a failure already
    # recorded above (which already forces `ok=False` and a full retry of
    # this session on the next hook firing, per the docstring's "Per-thread
    # failure isolation" note). Only the former is worth telling the user
    # about; mislabeling the latter as a "cycle" would blame a thread that
    # never itself failed for another thread's daemon hiccup.
    if remaining and not failed_threads:
        for anchor, tgt in remaining.items():
            _emit_orphaned(sid, anchor, threads[anchor], reason="cycle",
                          attempted_anchor=tgt)
            orphaned.append(anchor)
            cycled.append(anchor)

    summary["migrated"] = migrated
    summary["orphaned"] = orphaned
    summary["failed_threads"] = failed_threads
    summary["collided"] = collided
    summary["cycled"] = cycled

    if failed_threads:
        summary["error"] = (
            f"{len(failed_threads)} thread(s) failed to migrate/orphan "
            f"({', '.join(failed_threads)}); refreshed diff/meta not pushed")
        return summary

    new_meta = {
        **meta_item,
        "head": gh_meta.get("headRefName", meta_item.get("head", "")),
        "base": gh_meta.get("baseRefName", meta_item.get("base", "")),
        "head_oid": gh_meta.get("headRefOid", ""),
        "fetched_at": int(time.time()),
    }
    wc.put_items(sid, {DIFF_ANCHOR: diff_text, META_ANCHOR: new_meta},
                kind=KIND, replace=True)

    summary["ok"] = True
    return summary


def main(argv=None) -> int:
    """Git-hook entry point: `python3 -m skills.ask_diff.sync`, no arguments.

    Resolves `$PWD` to a repo root and the current branch itself, finds every
    matching live session, and resyncs each. Wrapped in one broad
    `except Exception: return 0` deliberately -- a git hook must never block
    or fail the git command that fired it, so every failure mode here
    (daemon not running, `gh` unreachable, no matching session, a resync
    that itself failed) is swallowed silently. This is the documented
    exception to "never swallow exceptions broadly": a git hook's failure
    mode is categorically different from a server's, where a broad catch
    would hide a real bug from whoever's watching it run.

    The per-session `resync` call also gets its own try/except inside the
    loop, on top of that outer one: multiple matching sessions "all get
    resynced... cheap and safer than guessing which one is 'the' session"
    (the original design's own reasoning) only holds if one session's total
    failure can't stop the loop before it reaches the next one. The outer
    catch alone would let the first session's uncaught exception (anything
    outside `resync()`'s own per-thread isolation -- a bug, or a failure at
    one of the few points in `resync()` before that isolation begins) abort
    every session after it for this hook firing; this inner guard keeps that
    to just the one session, and the outer catch stays as the final backstop
    for everything else in this function (the two `git` calls,
    `find_matching_sessions` itself).
    """
    try:
        cwd = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True, timeout=_GIT_TIMEOUT,
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True, cwd=cwd, timeout=_GIT_TIMEOUT,
        ).strip()
        if not branch:
            return 0
        for sid in find_matching_sessions(cwd, branch):
            try:
                resync(sid, cwd)
            except Exception:
                continue
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
