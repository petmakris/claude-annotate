"""Shared HTTP client for the webcompanion daemon.

Every skill that has migrated onto the daemon (starting with `dataflow`, see
`skills/dataflow/push.py`) uses this module instead of hand-rolling its own
`urllib` calls. `skills/annotate/push.py` predates this module and is
retrofitted onto it in a later phase of the same cutover program — see
docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md.

Stdlib only, deliberately: this plugin ships with no pip dependencies, and
`webcompanion` itself is only ever `pipx`-installed (an isolated venv the
plain `python3` these skills run under cannot import), so nothing here can
lean on `webcompanion.client.Client` even though it exists and is broader.

Contract reference: ~/projects/webcompanion/docs/contract.md (version 1).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONTRACT = 1
_CONFIG_PATH = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


class DaemonNotConfigured(Exception):
    """~/.claude/webcompanion/config.json does not exist."""


class DaemonUnreachable(Exception):
    """The config exists but the daemon did not answer (connection/timeout)."""


class ContractMismatch(Exception):
    """The daemon returned 426 — client and daemon disagree on the wire contract."""


def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        raise DaemonNotConfigured(
            "webcompanion is not configured on this machine "
            f"({_CONFIG_PATH} is missing).\n"
            "  pipx install webcompanion && webcompanion install-service")
    return json.loads(_CONFIG_PATH.read_text())


def _request(method: str, path: str, body: dict | list | None = None) -> dict | list:
    cfg = load_config()
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
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        if e.code == 426:
            raise ContractMismatch(detail) from None
        raise RuntimeError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise DaemonUnreachable(
            "cannot reach the webcompanion daemon on port %s (%s).\n"
            "  webcompanion status   # is the service running?\n"
            "  webcompanion doctor   # full check"
            % (cfg["port"], e.reason)) from None
    return json.loads(raw) if raw.strip() else {}


def _kind_qs(kind: str) -> str:
    return "?kind=" + urllib.parse.quote(kind)


def create_or_attach(kind: str, cwd: str, *, title: str | None = None,
                     slug: str | None = None, supersede: bool = False) -> dict:
    """Resolve `slug` to a live session if given and found; otherwise create one.

    Mirrors `annotate/push.py:push()`'s attach-before-create logic: a slug is
    unique only within a kind, so resolving it here (rather than trusting the
    slug string onward to the caller) avoids a later ambiguous-slug 409 at the
    worst possible moment (e.g. inside `webcompanion ack`).

    `supersede`, when creating, ends every other live session of this same
    `(kind, cwd)` pair (`server.py`'s `_supersede_siblings`) — it is scoped
    coarser than a single Claude conversation, so it is never sent on the
    attach-by-slug path, which does not create anything and would have no
    effect there anyway.
    """
    if slug:
        try:
            rows = _request("GET", "/api/sessions" + "?cwd=%s&kind=%s"
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
    return _request("POST", "/api/sessions", body)


def put_items(sid: str, items: dict, *, kind: str, replace: bool = False) -> dict:
    return _request("PATCH", f"/s/{sid}/items" + _kind_qs(kind),
                    {"items": items, "replace": replace})


def get_items(sid: str, *, kind: str) -> dict:
    return _request("GET", f"/s/{sid}/items" + _kind_qs(kind))


def register_assets(sid: str, static_root: str, entry: str, *, kind: str) -> None:
    _request("POST", f"/s/{sid}/api/assets" + _kind_qs(kind),
             {"static_root": static_root, "entry": entry})


def get_threads(sid: str, *, kind: str) -> dict:
    return _request("GET", f"/s/{sid}/threads" + _kind_qs(kind))


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
    return _request("POST", f"/s/{sid}/threads/{urllib.parse.quote(anchor, safe='')}"
                    + _kind_qs(kind), body)


def delete_thread(sid: str, anchor: str, *, kind: str) -> bool:
    res = _request("POST", f"/s/{sid}/api/threads/delete" + _kind_qs(kind), {"anchor": anchor})
    return bool(res.get("deleted"))


def submit_event(sid: str, anchor: str, text: str, *, kind: str,
                 images: list[str] | None = None) -> str:
    body: dict = {"anchor": anchor, "text": text}
    if images:
        body["images"] = images
    res = _request("POST", f"/s/{sid}/api/submit" + _kind_qs(kind), body)
    return res["event_id"]
