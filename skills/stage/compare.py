"""A sequence spec that compares two flows: `{"compare": {"before": {actors, steps}, "after": {actors, steps}}}`.

`compare_spec` validates each side as a sequence of its own and lines the two up row by row, as a split diff
lines up two files: the stage draws the two flows side by side, and a step on one side only faces a gap on
the other. A before step and an after step are a pair when they have the same id, or else the same `label`
and `arrow` between other actors. A pair is

- `same`     when only a replaced actor tells them apart (an actor on one side only, standing where an actor
             on the other side only stood) or nothing does;
- `changed`  the same, but with other words: one row, with the words that differ marked on each side;
- `moved`    between other actors that are on both sides, or out of order: two rows, each facing a gap.

A step with no pair is `added` (a gap on the left) or `removed` (a gap on the right). The rows of the pairs
that keep both sides' order (the longest such run) hold the two flows level, and between two of them come the
before-only rows, then the after-only rows, so each side keeps its own order.

The spec it returns keeps one step per row in `steps`, keyed as the scene engine knows them: the after step's
id, or the before step's when the row has none (`was~<id>` for the before row of a moved step with one id on
both sides). A row carries its `change`, its `before` and `after` steps (each as its side wrote it, with `row`,
the row's key, and `marks` when its words changed) and, for a moved step's after row, `replaces`. `compare`
holds each side's `label` and `actors`, each tagged `same`, `added` or `removed`; `actors` is every actor of
either side, so each is a key. No I/O.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from skills._shared.visuals import sequence_svg
from skills._shared.visuals.sequence import ValidationError

SIDES = ("before", "after")
SIDE_KEYS = {"label", "actors", "steps"}
OWN = {"actors", "steps", "phases", "groups", "outcome", "captions"}


def _side(spec: dict, name: str) -> dict:
    side = spec.get(name)
    if not isinstance(side, dict):
        raise ValidationError(f"compare.{name} must be an object with actors and steps")
    extra = sorted(set(side) - SIDE_KEYS)
    if extra:
        raise ValidationError(f"compare.{name}: {', '.join(extra)} not supported; a side holds its label, actors and steps")
    if side.get("label") is not None and not isinstance(side["label"], str):
        raise ValidationError(f"compare.{name}: label must be text")
    try:
        sequence_svg.validate({"actors": side.get("actors"), "steps": side.get("steps"),
                               "legend": spec.get("legend")})
    except ValidationError as e:
        raise ValidationError(f"compare.{name}: {e}") from None
    return side


def _merge_order(after_keys: list[str], before_keys: list[tuple[str, bool]],
                 beside: dict[str, str] | None = None) -> list[str]:
    """`after_keys` in order, with each before-only key (marked True) inserted just before the key it is replaced
    by (`beside`: before key -> after key), so an old row and its new one sit together; a key with no replacement
    goes just after the key that precedes it in the before list (at the front when it has none)."""
    beside = beside or {}
    order = list(after_keys)
    prev: str | None = None
    for key, extra in before_keys:
        if extra:
            mate = beside.get(key)
            if mate in order:
                order.insert(order.index(mate), key)
            else:
                order.insert(0 if prev is None else order.index(prev) + 1, key)
        prev = key
    return order


WORD = re.compile(r"\w+|\s+|[^\w\s]")
IGNORED = {"id", "n", "from", "to", "reply_to", "ref"}   # what a step's words are not: its place and its source


def _marks(old: str, new: str) -> tuple[list, list]:
    """Each text as runs of [words, differs], the words of one the other does not have marked."""
    a, b = WORD.findall(old), WORD.findall(new)
    fa, fb = [False] * len(a), [False] * len(b)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            fa[i1:i2] = [True] * (i2 - i1)
            fb[j1:j2] = [True] * (j2 - j1)

    def runs(toks: list[str], flags: list[bool]) -> list:
        for k in range(1, len(toks) - 1):  # a space between two marked words is marked with them
            if toks[k].isspace() and flags[k - 1] and flags[k + 1]:
                flags[k] = True
        out: list = []
        for t, f in zip(toks, flags):
            if out and out[-1][1] == f:
                out[-1][0] += t
            else:
                out.append([t, f])
        return out
    return runs(a, fa), runs(b, fb)


def _lis(seq: list[int]) -> set[int]:
    """The positions in `seq` of a longest strictly increasing run."""
    best: list[int] = []   # best[k]: the position ending the best run of length k + 1
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        lo, hi = 0, len(best)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[best[mid]] < v:
                lo = mid + 1
            else:
                hi = mid
        prev[i] = best[lo - 1] if lo else -1
        if lo == len(best):
            best.append(i)
        else:
            best[lo] = i
    out, i = set(), best[-1] if best else -1
    while i != -1:
        out.add(i)
        i = prev[i]
    return out


def compare_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """The lined-up spec for a compare spec; ValidationError when it is malformed."""
    cmp = spec.get("compare")
    if not isinstance(cmp, dict) or not all(k in cmp for k in SIDES):
        raise ValidationError('compare needs "before" and "after", each with actors and steps')
    extra = sorted(set(cmp) - set(SIDES))
    if extra:
        raise ValidationError(f"compare: {', '.join(extra)} not supported; it holds before and after")
    clash = sorted(OWN & set(spec))
    if clash:
        raise ValidationError(f"compare does not take {', '.join(clash)} beside it: actors and steps go inside "
                              "before and after, and phases, groups, outcome and captions are not supported with it")
    before, after = _side(cmp, "before"), _side(cmp, "after")
    b_ids = {a["id"] for a in before["actors"]}
    a_ids = {a["id"] for a in after["actors"]}

    def side_actors(side: dict, other: set) -> list[dict]:
        return [dict(a, change="same" if a["id"] in other else "removed" if side is before else "added") for a in side["actors"]]

    # -- pairs: by id, then the unmatched ones by their words ----------------------------------------------
    bs, as_ = before["steps"], after["steps"]
    a_at = {s["id"]: j for j, s in enumerate(as_)}
    pair: dict[int, int] = {}   # before position -> after position
    for i, b in enumerate(bs):
        if b["id"] in a_at:
            pair[i] = a_at[b["id"]]
    b_known = {b["id"] for b in bs}
    for i, b in enumerate(bs):
        if i in pair:
            continue
        hit = next((j for j, a in enumerate(as_) if a["id"] not in b_known and j not in pair.values()
                    and a.get("label") == b.get("label") and a.get("arrow") == b.get("arrow")), None)
        if hit is not None:
            pair[i] = hit

    def end_ok(x: str, y: str) -> bool:   # the same actor, or one replaced by another
        return x == y or (x not in a_ids and y not in b_ids)

    def words(s: dict) -> dict:
        return {k: v for k, v in s.items() if k not in IGNORED}

    kind: dict[int, str] = {}
    for i, j in pair.items():
        b, a = bs[i], as_[j]
        if not (end_ok(b["from"], a["from"]) and end_ok(b["to"], a["to"])):
            kind[i] = "moved"
        else:
            kind[i] = "same" if words(b) == words(a) else "changed"
    level = [i for i in sorted(pair) if kind[i] != "moved"]
    keep = _lis([pair[i] for i in level])
    anchors = [i for k, i in enumerate(level) if k in keep]
    for i in level:
        if i not in anchors:
            kind[i] = "moved"

    # -- the rows ---------------------------------------------------------------------------------------
    b_row: dict[int, str] = {}
    a_row: dict[int, str] = {}
    for i, b in enumerate(bs):
        if i in pair and kind[i] != "moved":
            b_row[i] = as_[pair[i]]["id"]
        elif i in pair and as_[pair[i]]["id"] == b["id"]:
            b_row[i] = f"was~{b['id']}"
        else:
            b_row[i] = b["id"]
    for j, a in enumerate(as_):
        a_row[j] = a["id"]
    def row(key: str, change: str, bi: int | None, aj: int | None) -> dict:
        b = dict(bs[bi], row=b_row[bi]) if bi is not None else None
        a = dict(as_[aj], row=a_row[aj]) if aj is not None else None
        if change == "changed":
            for f in ("label", "sub"):
                old, new = str(b.get(f) or ""), str(a.get(f) or "")
                if old != new:
                    mb, ma = _marks(old, new)
                    b.setdefault("marks", {})[f] = mb
                    a.setdefault("marks", {})[f] = ma
        top = dict(a if a is not None else b)
        top.pop("row", None)
        top.pop("marks", None)
        top.pop("reply_to", None)
        top.update(id=key, change=change)
        if b is not None:
            top["before"] = b
        if a is not None:
            top["after"] = a
        return top

    out_rows: list[dict] = []
    inv = {j: i for i, j in pair.items()}
    bi = aj = 0

    def flush(b_to: int, a_to: int) -> None:
        nonlocal bi, aj
        for i in range(bi, b_to):
            out_rows.append(row(b_row[i], "moved" if i in pair else "removed", i, None))
        for j in range(aj, a_to):
            r = row(a_row[j], "moved" if j in inv else "added", None, j)
            if j in inv:
                r["replaces"] = b_row[inv[j]]
            out_rows.append(r)

    for i in anchors:
        j = pair[i]
        flush(i, j)
        out_rows.append(row(as_[j]["id"], kind[i], i, j))
        bi, aj = i + 1, j + 1
    flush(len(bs), len(as_))

    a_order = _merge_order([a["id"] for a in after["actors"]],
                           [(a["id"], a["id"] not in a_ids) for a in before["actors"]])
    every = {a["id"]: a for a in before["actors"]} | {a["id"]: a for a in after["actors"]}
    actors = [dict(every[x], change="same" if x in a_ids and x in b_ids else "added" if x in a_ids else "removed")
              for x in a_order]
    out = {k: v for k, v in spec.items() if k != "compare"}
    out.update(actors=actors, steps=out_rows, compare={
        "before": {"label": before.get("label") or "Before", "actors": side_actors(before, a_ids)},
        "after": {"label": after.get("label") or "After", "actors": side_actors(after, b_ids)}})
    return out
