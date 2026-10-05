"""Shared HTTP client for the webcompanion daemon.

Every skill talks to the daemon through this module rather than hand-rolling
its own `urllib` calls: annotate (push, pull, progress, session), dataflow,
walkthrough, ask_diff and deck.

Stdlib only, deliberately: this plugin ships with no pip dependencies, and
`webcompanion` itself is only ever `pipx`-installed (an isolated venv the
plain `python3` these skills run under cannot import), so nothing here can
lean on `webcompanion.client.Client` even though it exists and is broader.

Every failure to talk to the daemon raises a `DaemonError`, so a caller has
one class to catch and `run_cli` one class to report. Nothing else escapes
`request()` except a bug.

Contract reference: ~/projects/webcompanion/docs/contract.md (version 1).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONTRACT = 1
_CONFIG_PATH = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))
TIMEOUT_S = 15

# What every CLI here exits with when the daemon (or its input) refused.
EXIT_FAILURE = 1


class DaemonError(Exception):
    """Any failure to get an answer out of the daemon."""


class DaemonNotConfigured(DaemonError):
    """~/.claude/webcompanion/config.json does not exist."""


class DaemonConfigInvalid(DaemonError):
    """config.json exists but is not JSON, or names no usable port."""


class DaemonUnreachable(DaemonError):
    """The config exists but the daemon did not answer (connection/timeout)."""


class ContractMismatch(DaemonError):
    """The daemon returned 426 — client and daemon disagree on the wire contract."""


class DaemonHTTPError(DaemonError):
    """The daemon answered with any other 4xx/5xx."""

    def __init__(self, method: str, path: str, status: int, detail: str):
        super().__init__("%s %s -> %d %s" % (method, path, status, detail))
        self.method, self.path, self.status, self.detail = method, path, status, detail


def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        raise DaemonNotConfigured(
            "webcompanion is not configured on this machine "
            f"({_CONFIG_PATH} is missing).\n"
            "  pipx install webcompanion && webcompanion install-service")
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        int(cfg["port"])
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise DaemonConfigInvalid(
            "%s is unreadable or names no port (%s).\n"
            "  webcompanion install-service   # rewrites it" % (_CONFIG_PATH, e)) from None
    return cfg


def request(method: str, path: str, body: dict | list | None = None, *,
            cfg: dict | None = None, allow_missing: bool = False,
            timeout: float = TIMEOUT_S):
    """One call to the daemon; the decoded JSON answer ({} when empty).

    `cfg` saves a re-read for a caller that already holds the config.
    `allow_missing` turns a 404 into None, for a READ where "not there yet"
    is the ordinary case. Never pass it on a write: there a 404 means the
    session id is wrong, and swallowing it makes a typo look like success.
    """
    cfg = load_config() if cfg is None else cfg
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404 and allow_missing:
            return None
        detail = e.read().decode(errors="replace").strip()
        if e.code == 426:
            raise ContractMismatch("contract mismatch: %s" % detail) from None
        raise DaemonHTTPError(method, path, e.code, detail) from None
    except (urllib.error.URLError, OSError) as e:
        raise DaemonUnreachable(
            "cannot reach the webcompanion daemon on port %s (%s).\n"
            "  webcompanion status   # is the service running?\n"
            "  webcompanion doctor   # full check"
            % (cfg["port"], getattr(e, "reason", e))) from None
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise DaemonHTTPError(method, path, 200, "answer is not JSON: %.200s" % raw) from None


def run_cli(prog: str, fn, *args, also: tuple = (), **kwargs):
    """Call `fn`, reporting a DaemonError (or one of `also`) as `prog: ...`.

    Returns `(result, 0)`, or `(None, EXIT_FAILURE)` after printing the
    error on stderr: one message, never a traceback, and the same exit code
    from every skill's CLI.
    """
    try:
        return fn(*args, **kwargs), 0
    except (DaemonError,) + tuple(also) as e:
        print("%s: %s" % (prog, e), file=sys.stderr)
        return None, EXIT_FAILURE


def _kind_qs(kind: str) -> str:
    return "?kind=" + urllib.parse.quote(kind)


def create_or_attach(kind: str, cwd: str, *, title: str | None = None,
                     slug: str | None = None, supersede: bool = False) -> dict:
    """Resolve `slug` to a live session if given and found; otherwise create one.

    Attach-before-create, the same order annotate's push uses: a slug is
    unique only within a kind, so resolving it here (rather than trusting the
    slug string onward to the caller) avoids a later ambiguous-slug 409 at the
    worst possible moment (e.g. inside `webcompanion ack`).

    `supersede`, when creating, ends every other live session of this same
    `(kind, cwd)` pair (the daemon's `_supersede_siblings`) — it is scoped
    coarser than a single Claude conversation, so it is never sent on the
    attach-by-slug path, which does not create anything and would have no
    effect there anyway.
    """
    if slug:
        try:
            rows = request("GET", "/api/sessions" + "?cwd=%s&kind=%s"
                           % (urllib.parse.quote(cwd), urllib.parse.quote(kind)))
        except (DaemonNotConfigured, DaemonUnreachable):
            rows = []
        for row in (rows if isinstance(rows, list) else rows.get("sessions", [])):
            if row.get("slug") == slug:
                return row
    body: dict = {"kind": kind, "cwd": cwd}
    if title:
        body["title"] = title
    if slug:
        body["slug"] = slug
    if supersede:
        body["supersede"] = True
    return request("POST", "/api/sessions", body)


def list_sessions(cwd: str, kind: str) -> list[dict]:
    """GET /api/sessions?cwd=&kind= -- every session in `kind` at `cwd`.

    A bare JSON array, `_row()`'s shape per entry (`{sid, slug, kind, cwd,
    title, url}`) -- not sorted, not filtered to live/non-terminal sessions.
    A caller that needs "the" session applies its own selection on top of
    this (e.g. `create_or_attach`'s own slug scan just above, which predates
    this function and keeps its own identical query rather than depending on
    it, to avoid a `list`-vs-empty-list `except` mismatch on the exact same
    call two functions rely on differently).
    """
    return request("GET", "/api/sessions" + "?cwd=%s&kind=%s"
                   % (urllib.parse.quote(cwd), urllib.parse.quote(kind)))


def all_sessions() -> list[dict]:
    """GET /api/sessions?scope=all -- every session of every kind, any cwd,
    in any state. For a lookup by slug, which is unique within a kind and so
    needs no cwd."""
    rows = request("GET", "/api/sessions?scope=all")
    return rows if isinstance(rows, list) else rows.get("sessions", [])


def put_items(sid: str, items: dict, *, kind: str, replace: bool = False,
              keep: list[str] | None = None) -> dict:
    """PATCH the item set. With `replace`, anchors not in `items` are deleted
    -- except those named in `keep`, which the daemon leaves exactly as
    stored, decided under its own write lock."""
    body: dict = {"items": items, "replace": replace}
    if keep is not None:
        body["keep"] = keep
    return request("PATCH", f"/s/{sid}/items" + _kind_qs(kind), body)


def get_items(sid: str, *, kind: str) -> dict:
    return request("GET", f"/s/{sid}/items" + _kind_qs(kind))


def get_item(sid: str, anchor: str, *, allow_missing: bool = False,
             timeout: float = TIMEOUT_S) -> dict | None:
    """One item's envelope (`{body, version, ...}`); None for a missing one
    when `allow_missing`."""
    return request("GET", f"/s/{sid}/items/{urllib.parse.quote(anchor, safe='')}",
                   allow_missing=allow_missing, timeout=timeout)


def put_item(sid: str, anchor: str, body, *, timeout: float = TIMEOUT_S) -> dict:
    return request("PUT", f"/s/{sid}/items/{urllib.parse.quote(anchor, safe='')}",
                   body, timeout=timeout)


def register_assets(sid: str, static_root: str, entry: str, *, kind: str) -> None:
    request("POST", f"/s/{sid}/api/assets" + _kind_qs(kind),
            {"static_root": static_root, "entry": entry})


def get_threads(sid: str, *, kind: str) -> dict:
    return request("GET", f"/s/{sid}/threads" + _kind_qs(kind))


def append_thread(sid: str, anchor: str, text: str, *, kind: str, role: str = "agent",
                  source_event_id: str | None = None, title: str | None = None,
                  anchor_text: str | None = None) -> dict:
    body: dict = {"text": text, "role": role}
    if source_event_id is not None:
        body["source_event_id"] = source_event_id
    if title is not None:
        body["title"] = title
    if anchor_text is not None:
        body["anchor_text"] = anchor_text
    return request("POST", f"/s/{sid}/threads/{urllib.parse.quote(anchor, safe='')}"
                   + _kind_qs(kind), body)


def delete_thread(sid: str, anchor: str, *, kind: str) -> bool:
    res = request("POST", f"/s/{sid}/api/threads/delete" + _kind_qs(kind), {"anchor": anchor})
    return bool(res.get("deleted"))


def submit_event(sid: str, anchor: str, text: str, *, kind: str,
                 images: list[str] | None = None) -> str:
    body: dict = {"anchor": anchor, "text": text}
    if images:
        body["images"] = images
    res = request("POST", f"/s/{sid}/api/submit" + _kind_qs(kind), body)
    return res["event_id"]
