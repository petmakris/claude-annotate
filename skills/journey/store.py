"""The journey canvas's comments, read the way the page reads them.

A journey canvas keeps its comments in its webcompanion session as an op log:
each create, edit, resolve, reply and delete is one message, in the thread of
the board it is about, carrying the op (skills/canvas/static/canvas-store.js).
`fold` is that file's `fold` in Python, so the journey tool sees exactly the
comments the page shows; tests/test_store.py runs both on the same cases.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

MAX_TEXT = 10000
ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BOARD_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/._-]{0,159}$")
APP_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SHOT_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")
AUDIO_OK = re.compile(r"^[A-Za-z0-9_.-]{1,120}\.wav$")


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def parse_time(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))


def _board_ok(b) -> bool:
    if isinstance(b, bool):
        return False
    if isinstance(b, int):
        return b >= 0
    return isinstance(b, str) and bool(BOARD_ID_OK.match(b))


def _frac(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1


def apply_op(store: dict, op, now: str) -> tuple[dict, str | None]:
    """The store after `op`, or the same store and why not (canvas-store.js applyOp)."""
    o = op
    if not isinstance(o, dict):
        return store, "An op must be an object."
    t = parse_time(o.get("at"))
    at = iso(t) if t else now
    comments = store["comments"]
    i = next((k for k, c in enumerate(comments) if isinstance(o.get("id"), str) and c["id"] == o["id"]), -1)
    kind = o.get("kind")
    holder = o.get("comment") if kind == "create" else o.get("reply") if kind == "reply" else o
    holder = holder if isinstance(holder, dict) else {}
    audio = None
    if "audio" in holder and holder["audio"] is not None:
        raw = holder["audio"]
        if not isinstance(raw, list) or len(raw) > 20:
            return store, "audio must be a list of file names."
        if not all(isinstance(a, str) and AUDIO_OK.match(a) for a in raw):
            return store, "audio must be a list of .wav file names."
        audio = list(raw)
    text = None
    if "text" in holder and holder["text"] is not None:
        raw = holder["text"]
        if not isinstance(raw, str) or not raw.strip():
            return store, "The text is empty."
        if len(raw) > MAX_TEXT:
            return store, f"The text is longer than {MAX_TEXT} characters."
        text = raw.strip()

    if kind == "create":
        c = o.get("comment")
        if not isinstance(c, dict):
            return store, "create needs a comment."
        if not (isinstance(c.get("id"), str) and ID_OK.match(c["id"])):
            return store, "The comment id is not valid."
        if any(x["id"] == c["id"] for x in comments):
            return store, None
        if not (isinstance(c.get("app"), str) and APP_OK.match(c["app"])):
            return store, "app must be a canvas id (a-z, 0-9 and -)."
        if not (isinstance(c.get("shot"), str) and SHOT_OK.match(c["shot"])):
            return store, "shot must be a shot label (a-z, 0-9 and -)."
        if not _board_ok(c.get("board")):
            return store, "board must be a board number or id."
        if not (_frac(c.get("fx")) and _frac(c.get("fy"))):
            return store, "The point must be fractions of the shot, from 0 to 1."
        if text is None:
            return store, "The text is empty."
        if c.get("scope") is not None and c["scope"] not in ("app", "both"):
            return store, "scope must be app or both."
        number = 1
        for x in comments:
            if x["app"] == c["app"] and x["number"] >= number:
                number = x["number"] + 1
        n = c.get("number")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 1:
            number = n
        made = {
            "id": c["id"], "number": number, "app": c["app"], "board": c["board"],
            "boardTitle": str(c.get("boardTitle") or "")[:300], "chapter": str(c.get("chapter") or "")[:300],
            "shot": c["shot"], "fx": c["fx"], "fy": c["fy"], "text": text,
            "scope": "both" if c.get("scope") == "both" else "app",
            "status": "open", "createdAt": at, "askedAt": at, "replies": [],
        }
        if audio:
            made["audio"] = audio
        return {"version": 1, "comments": comments + [made]}, None

    if kind == "delete":
        if i < 0:
            return store, None
        return {"version": 1, "comments": comments[:i] + comments[i + 1:]}, None
    if kind not in ("update", "move", "reply", "editReply", "deleteReply"):
        return store, f"Unknown op {_js(kind)}."
    if i < 0:
        if kind == "deleteReply":
            return store, None
        return store, f"No comment {_js(o.get('id'))}."
    was = comments[i]
    nxt = dict(was)
    nxt["replies"] = list(was["replies"])

    if kind == "update":
        if o.get("scope") is not None and o["scope"] not in ("app", "both"):
            return store, "scope must be app or both."
        if o.get("status") is not None and o["status"] not in ("open", "resolved"):
            return store, "status must be open or resolved."
        if o.get("sentAt") is not None:
            st = parse_time(o["sentAt"])
            if st is None:
                return store, "sentAt must be a time."
            nxt["sentAt"] = iso(st)
            if text is None and o.get("scope") is None and o.get("status") is None and audio is None:
                out = list(comments)
                out[i] = nxt
                return {"version": 1, "comments": out}, None
        if text is not None:
            nxt["text"] = text
            nxt["askedAt"] = at
        if o.get("scope") is not None:
            nxt["scope"] = o["scope"]
        if audio is not None:
            merged = list(was.get("audio") or [])
            merged += [a for a in audio if a not in merged]
            if merged:
                nxt["audio"] = merged
        if o.get("status") is not None and o["status"] != was["status"]:
            nxt["status"] = o["status"]
            if o["status"] == "resolved":
                nxt["resolvedAt"] = at
            else:
                nxt.pop("resolvedAt", None)
        nxt["updatedAt"] = at
    elif kind == "move":
        if not _board_ok(o.get("board")):
            return store, "board must be a board number or id."
        nxt["board"] = o["board"]
        if o.get("boardTitle") is not None:
            nxt["boardTitle"] = str(o["boardTitle"])[:300]
        if o.get("chapter") is not None:
            nxt["chapter"] = str(o["chapter"])[:300]
    elif kind == "reply":
        r = o.get("reply")
        if not (isinstance(r, dict) and isinstance(r.get("id"), str) and ID_OK.match(r["id"])):
            return store, "The reply id is not valid."
        if any(x["id"] == r["id"] for x in was["replies"]):
            return store, None
        if text is None:
            return store, "The text is empty."
        reply = {"id": r["id"], "text": text, "createdAt": at}
        if r.get("by") == "claude":
            reply["by"] = "claude"
            nxt["answeredAt"] = at
        else:
            nxt["askedAt"] = at
        if audio:
            reply["audio"] = audio
        nxt["replies"].append(reply)
    else:
        j = next((k for k, x in enumerate(was["replies"]) if x["id"] == o.get("replyId")), -1)
        if kind == "deleteReply":
            if j < 0:
                return store, None
            nxt["replies"].pop(j)
        else:
            if j < 0:
                return store, f"No reply {_js(o.get('replyId'))}."
            if text is None:
                return store, "The text is empty."
            edited = dict(was["replies"][j])
            edited["text"] = text
            edited["updatedAt"] = at
            if audio:
                edited["audio"] = list(was["replies"][j].get("audio") or []) + audio
            nxt["replies"][j] = edited
    out = list(comments)
    out[i] = nxt
    return {"version": 1, "comments": out}, None


def _js(v) -> str:
    import json
    return json.dumps(v)


def ops_of(threads: dict) -> list[dict]:
    """Every op in a threads snapshot, in the order made (canvas-store.js opsOf)."""
    rows = []
    n = 0
    for anchor in sorted(threads or {}):
        for m in (threads[anchor] or {}).get("messages") or []:
            if not isinstance(m, dict) or not isinstance(m.get("op"), dict):
                continue
            t = parse_time(m["op"].get("at"))
            ms = t.timestamp() * 1000 if t else (m.get("ts") or 0) * 1000
            rows.append((ms, m.get("ts") or 0, n, m["op"]))
            n += 1
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [copy.deepcopy(r[3]) for r in rows]


def fold(threads: dict, now: str | None = None) -> tuple[dict, list[dict]]:
    """The store the threads' ops make, and the ops refused with why."""
    s = {"version": 1, "comments": []}
    refused = []
    for op in ops_of(threads):
        s, err = apply_op(s, op, now or now_iso())
        if err:
            refused.append({"op": op, "error": err})
    return s, refused


def waiting(c: dict) -> bool:
    """Open, and Petros wrote on it after Claude last answered."""
    return c["status"] == "open" and (not c.get("answeredAt") or c.get("askedAt", "") > c["answeredAt"])
