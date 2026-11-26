"""The session index's service routes, served by `fleet ui` on the hub (fleet.py routes them here).

They are for servers, never for a page: a loopback bind, a loopback Host (or one listed in `hosts` of ui.json),
`Authorization: Bearer <token>` (never the cookie, so no page can be tricked into them) and a JSON body for a POST.
`POST /api/session/journal` writes as the hub machine: its entry goes through the hub machine's own journal, so a
Claude Voice server on the hub journals as `phone:prod` or `phone:dev:<sandbox>`. Contract:
`fleet/docs/session-index.md`, section 15. Stdlib only, no fleet imports.
"""
import hmac
import json
import os

import fleet_index_cli as cli
import fleet_index_journal as journal
import fleet_index_store as store

SERVICE_POSTS = ("/api/session/take", "/api/session/journal", "/api/session/chain", "/api/session/end-host")
SERVICE_GETS = ("/api/session/owner",)
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _header(headers, name):
    if headers is None:
        return ""
    for k in headers.keys():
        if k.lower() == name.lower():
            return headers[k] or ""
    return ""


def _host_name(value):
    v = (value or "").strip().lower()
    if v.startswith("["):
        return v[1:v.index("]")] if "]" in v else v
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def _hosts():
    try:
        with open(os.path.join(cli._home(), "ui.json")) as f:
            extra = json.load(f).get("hosts") or []
    except (OSError, ValueError, AttributeError):
        extra = []
    return set(LOOPBACK) | {h.lower() for h in extra if isinstance(h, str)}


def service_refusal(bound, headers, token):
    """Why a service request is refused, or None."""
    if _host_name(bound) not in LOOPBACK:
        return "the session routes answer only on a loopback bind"
    if _host_name(_header(headers, "Host")) not in _hosts():
        return "the Host is not a loopback name or one of ui.json's hosts"
    auth = _header(headers, "Authorization")
    if not token or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].strip(), token):
        return "the session routes need Authorization: Bearer with the token (fleet ui token)"
    return None


def _status(reply):
    if reply.get("ok") is not False:
        return 200
    return {"bad-request": 400, "no-session": 404, "hub-down": 503}.get(reply.get("code"), 409)


def handle(method, path, query, body, headers, bound, token):
    """(status, dict) for one service request."""
    if path not in SERVICE_POSTS + SERVICE_GETS:
        return 404, {"ok": False, "code": "bad-request", "error": "no such route"}
    why = service_refusal(bound, headers, token)
    if why:
        return 401 if "Authorization" in why else 403, {"ok": False, "code": "refused", "error": why}
    if not cli.is_hub():
        return 503, {"ok": False, "code": "hub-down", "error": "this machine is not the hub (%s is)" % cli.hub_name()}
    if path in SERVICE_GETS:
        if method != "GET":
            return 405, {"ok": False, "code": "bad-request", "error": "GET only"}
        sid = (query or {}).get("sid")
        sid = sid[0] if isinstance(sid, list) else sid
        reply = cli.hub_op("owner", {"sid": sid})
        reply.pop("_truth", None)
        return _status(reply), reply
    if method != "POST":
        return 405, {"ok": False, "code": "bad-request", "error": "POST only"}
    if not _header(headers, "Content-Type").lower().startswith("application/json"):
        return 415, {"ok": False, "code": "bad-request", "error": "the body must be JSON (Content-Type: application/json)"}
    try:
        data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else (body or ""))
    except (ValueError, UnicodeDecodeError):
        return 400, {"ok": False, "code": "bad-request", "error": "the body is not JSON"}
    if not isinstance(data, dict):
        return 400, {"ok": False, "code": "bad-request", "error": "the body is not a JSON object"}
    if path == "/api/session/take":
        reply = cli.hub_op("take", data)
    elif path == "/api/session/chain":
        reply = cli.hub_op("chain", data)
    elif path == "/api/session/end-host":
        reply = cli.hub_op("end-host", data)
    else:
        reply = _journal(data)
    return _status(reply), reply


def _journal(data):
    sid, event, fields = data.get("sid"), data.get("event"), data.get("fields") or {}
    writer = data.get("as") or cli.self_name()
    if not isinstance(sid, str) or not store.SID_RE.match(sid) or event not in store.EVENTS:
        return {"ok": False, "code": "bad-request", "error": "a journal post is {sid, event, fields, as}"}
    if not isinstance(writer, str) or not store.OWNER_RE.match(writer) or not (
            writer.startswith("phone:") or writer == cli.self_name()):
        return {"ok": False, "code": "bad-request", "error": "a journal post writes as the hub or a Claude Voice server"}
    why = store.fields_problem(fields)
    if why:
        return {"ok": False, "code": "bad-request", "error": why}
    entry = journal.append(cli._home(), cli.self_name(), sid, event, fields, as_owner=writer)
    reply = cli.flush_now()
    result = None
    for r in (reply or {}).get("results") or []:
        if r.get("seq") == entry["seq"]:
            result = r
    return {"ok": True, "seq": entry["seq"], "result": result, "row": ((reply or {}).get("rows") or {}).get(sid)}
