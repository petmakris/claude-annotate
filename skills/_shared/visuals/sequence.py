"""Sequence-diagram spec validator, the rules every sequence spec must keep.

Pure functions, no I/O. `sequence_svg.py` runs `validate` before it draws a sequence, the stage
catches `ValidationError`, and Annotate's Confluence export numbers steps with `_numbered`. The
numbered grid this module used to draw is gone, but the `.annotate-seq` rules in visuals.css and
annotate's diagram.css stay, because pages already stored in the daemon hold SVG it drew.
"""
from __future__ import annotations

import re
from typing import Any

ARROW_TYPES = ("request", "event", "self", "band")

# Tone = what the author wants the reader to conclude from an edge, not the
# mechanism that carried it. `plain` is the default and needs no legend entry.
TONES = ("plain", "edge", "internal", "service", "cheap", "hot", "good", "dropped")

# A box round a run of steps, as in UML: `alt` and `par` split it into branches, `loop` and `opt` carry a
# condition. The stage and sequence_svg draw them.
GROUP_KINDS = ("alt", "par", "loop", "opt")
BRANCHED = ("alt", "par")
REF_RE = re.compile(r"[^\s:][^:]*:[1-9]\d*")  # path:line, the line a step's popup on the stage shows


class ValidationError(ValueError):
    """Raised when a sequence spec violates a structural rule."""


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    actors = spec.get("actors") or []
    steps = spec.get("steps") or []
    phases = spec.get("phases") or []
    legend = spec.get("legend") or []

    if len(actors) < 2:
        raise ValidationError("sequence requires at least 2 actors")
    if len(steps) < 1:
        raise ValidationError("sequence requires at least 1 step")

    actor_ids: set[str] = set()
    for a in actors:
        aid = a.get("id")
        if not aid or aid in actor_ids:
            raise ValidationError(f"actor id missing or duplicate: {aid!r}")
        if not a.get("label"):
            raise ValidationError(f"actor {aid!r}: label required")
        tone = a.get("tone", "plain")
        if tone not in TONES:
            raise ValidationError(f"actor {aid!r}: unknown tone {tone!r}")
        actor_ids.add(aid)

    seen_step_ids: set[str] = set()
    step_order: list[str] = []
    for s in steps:
        sid = s.get("id")
        if not sid:
            raise ValidationError("step id required")
        if sid in seen_step_ids:
            raise ValidationError(f"duplicate step id: {sid!r}")
        seen_step_ids.add(sid)
        step_order.append(sid)

        if s.get("from") not in actor_ids:
            raise ValidationError(f"step {sid}: unknown from actor {s.get('from')!r}")
        if s.get("to") not in actor_ids:
            raise ValidationError(f"step {sid}: unknown to actor {s.get('to')!r}")

        arrow = s.get("arrow")
        if arrow not in ARROW_TYPES:
            raise ValidationError(f"step {sid}: unknown arrow type {arrow!r}")
        if arrow == "self" and s.get("from") != s.get("to"):
            raise ValidationError(f"step {sid}: arrow=self requires from == to")
        if arrow == "request" and s.get("from") == s.get("to"):
            raise ValidationError(f"step {sid}: cross-actor arrow with from == to; use arrow=self")
        if arrow == "event" and s.get("from") == s.get("to"):
            raise ValidationError(f"step {sid}: cross-actor arrow with from == to; use arrow=self")

        tone = s.get("tone", "plain")
        if tone not in TONES:
            raise ValidationError(f"step {sid}: unknown tone {tone!r}")
        ref = s.get("ref")
        if ref is not None and not (isinstance(ref, str) and REF_RE.fullmatch(ref.strip())):
            raise ValidationError(f"step {sid}: ref {ref!r} is not path:line")

    _validate_replies(steps)
    _validate_groups(spec.get("groups") or [], steps)

    for item in legend:
        if item.get("tone") not in TONES:
            raise ValidationError(f"legend: unknown tone {item.get('tone')!r}")
        if not item.get("label"):
            raise ValidationError(f"legend {item.get('tone')!r}: label required")

    last_step_idx = -1
    for p in phases:
        if not p.get("label"):
            raise ValidationError(f"phase {p.get('id')!r}: label required")
        start = p.get("start_at")
        if start not in seen_step_ids:
            raise ValidationError(f"phase {p.get('id')!r}: start_at refers to unknown step {start!r}")
        idx = step_order.index(start)
        if idx <= last_step_idx:
            raise ValidationError(f"phase {p.get('id')!r}: phase order violates step order")
        last_step_idx = idx
        # a box never runs across the start of a phase
        before, at = steps[idx - 1] if idx else {}, steps[idx]
        if at.get("group") is not None and before.get("group") == at.get("group"):
            raise ValidationError(f"phase {p.get('id')!r}: starts inside group {at['group']!r}")


def _validate_replies(steps: list[dict]) -> None:
    """A reply (`reply_to`) is an event that answers an earlier request, going back the way it came."""
    seen: dict[str, dict] = {}
    answered: set[str] = set()
    for s in steps:
        rid = s.get("reply_to")
        if rid is not None:
            call = seen.get(rid)
            if call is None:
                raise ValidationError(f"step {s['id']}: reply_to {rid!r} is not an earlier step")
            if s.get("arrow") != "event" or call.get("arrow") != "request":
                raise ValidationError(f"step {s['id']}: reply_to joins an event to the request it answers")
            if (s["from"], s["to"]) != (call["to"], call["from"]):
                raise ValidationError(f"step {s['id']}: a reply goes back from {call['to']!r} to {call['from']!r}")
            if rid in answered:
                raise ValidationError(f"step {s['id']}: step {rid!r} is already answered")
            answered.add(rid)
        seen[s["id"]] = s


def _validate_groups(groups: list[dict], steps: list[dict]) -> None:
    """Each group holds one unbroken run of steps; a branched one's branches come in order, from the first."""
    kinds: dict[str, dict] = {}
    for g in groups:
        gid, kind = g.get("id"), g.get("kind")
        if not gid or gid in kinds:
            raise ValidationError(f"group id missing or duplicate: {gid!r}")
        if kind not in GROUP_KINDS:
            raise ValidationError(f"group {gid!r}: kind must be one of {', '.join(GROUP_KINDS)}")
        branches = g.get("branches")
        if kind in BRANCHED:
            if not isinstance(branches, list) or len(branches) < 2 or not all(isinstance(b, str) and b.strip() for b in branches):
                raise ValidationError(f"group {gid!r}: {kind} needs branches, a list of two or more conditions")
        elif not str(g.get("label") or "").strip():
            raise ValidationError(f"group {gid!r}: {kind} needs a label, its condition")
        kinds[gid] = g
    runs: dict[str, list[int]] = {}
    last = None
    for s in steps:
        gid = s.get("group")
        if gid is None:
            if s.get("branch") is not None:
                raise ValidationError(f"step {s['id']}: branch is set but the step is in no group")
            last = None
            continue
        g = kinds.get(gid)
        if g is None:
            raise ValidationError(f"step {s['id']}: unknown group {gid!r}")
        if gid in runs and last != gid:
            raise ValidationError(f"group {gid!r}: its steps must follow one another")
        branch = s.get("branch", 0)
        if g["kind"] in BRANCHED:
            if isinstance(branch, str) and branch.isdigit():
                branch = int(branch)
            if not isinstance(branch, int) or isinstance(branch, bool) or not 0 <= branch < len(g["branches"]):
                raise ValidationError(f"step {s['id']}: branch must be a number from 0 to {len(g['branches']) - 1}")
            done = runs.setdefault(gid, [])
            if (not done and branch != 0) or (done and branch not in (done[-1], done[-1] + 1)):
                raise ValidationError(f"step {s['id']}: the branches of {gid!r} come in order, from 0")
            done.append(branch)
        else:
            if s.get("branch") is not None:
                raise ValidationError(f"step {s['id']}: a {g['kind']} has no branches")
            runs.setdefault(gid, []).append(0)
        last = gid
    for gid, g in kinds.items():
        if gid not in runs:
            raise ValidationError(f"group {gid!r} holds no step")
        if g["kind"] in BRANCHED and runs[gid][-1] != len(g["branches"]) - 1:
            raise ValidationError(f"group {gid!r}: every branch needs a step")


def _numbered(steps: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int | None]]:
    """Pair each step with its number, or None for a band.

    A band narrates across the actors it spans rather than carrying a message,
    so it has no number. Every other step is numbered from 1.
    """
    out: list[tuple[dict[str, Any], int | None]] = []
    n = 0
    for step in steps:
        if step["arrow"] == "band":
            out.append((step, None))
            continue
        n += 1
        out.append((step, n))
    return out
