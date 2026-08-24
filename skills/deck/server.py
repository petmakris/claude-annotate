"""Deck skill — thin handlers module over web_companion.

The deck .html is the document. This server READS it to compute addresses and
to serve it into the browser's iframe; it never writes it. Claude edits the
file with its own Edit tool and writes the ack, exactly as annotate does with
blocks.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from skills._shared.web_companion import server as wc_server
from skills._shared.web_companion import events as events_module
from skills._shared.web_companion.atomic import write_text_atomic
from skills.deck import model as model_module

SHARED_STATIC_DIR = Path(__file__).resolve().parent.parent / "_shared" / "web_companion" / "static"
STATIC_DIR = Path(__file__).resolve().parent / "static"

PORT_RANGE = range(3090, 3091)
BANNER = "deck-server v1"

# Static assets are mounted at /static/ by the shared server, not under the
# session path — a relative href here would resolve to /s/<sid>/core.css and
# fall through to serve_data as an unknown route.
PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — claude-deck</title>
<link rel="stylesheet" href="/static/core.css">
<link rel="stylesheet" href="/static/deck.css">
</head><body data-response-id="{sid}">
<div id="app"><div id="deckhead"></div><div id="deckbody"></div></div>
<script src="/static/core.js" defer></script>
<script src="/static/deck.js" defer></script>
</body></html>
"""


def deck_path(dirs: dict) -> Path:
    """The .html this workspace is attached to. Raises if the session is unseeded."""
    meta = json.loads((Path(dirs["state_dir"]) / "meta.json").read_text(encoding="utf-8"))
    return Path(meta["deck"])


def _fingerprint(p: Path) -> str:
    """Cheap change token: a hash of the bytes."""
    raw = p.read_bytes()
    return hashlib.sha1(raw).hexdigest()[:16]


class Handlers:
    # Deck workspaces are long-lived and re-opened, like annotate's — a new
    # session must not cancel the one you left open in another tab.
    supersede_by_claude_session = False

    # -- lifecycle -------------------------------------------------------
    def create_session_extra(self, payload: dict, dirs: dict) -> dict | None:
        raw = payload.get("deck")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("payload missing 'deck' (absolute path to the deck .html)")
        deck = Path(raw).expanduser()
        if not deck.is_file():
            raise ValueError(f"deck not found: {deck}")
        if deck.suffix.lower() != ".html":
            raise ValueError(f"deck must be an .html file: {deck}")
        write_text_atomic(Path(dirs["state_dir"]) / "meta.json", json.dumps({
            "deck": str(deck.resolve()),
            "title": deck.stem,
            "created_at": int(time.time()),
        }, indent=2))
        return {"deck": str(deck.resolve()), "title": deck.stem}

    # -- reads -----------------------------------------------------------
    def serve_root(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        try:
            title = deck_path(dirs).stem
        except (OSError, KeyError, json.JSONDecodeError):
            title = "deck"
        sid = Path(dirs["state_dir"]).parent.name
        _send_html(h, 200, PAGE.format(title=title, sid=sid))

    def serve_data(self, h: BaseHTTPRequestHandler, dirs: dict, query: str) -> None:
        if query == "deck":
            try:
                raw = deck_path(dirs).read_bytes()
            except OSError as exc:
                _send_text(h, 404, f"deck unreadable: {exc}")
                return
            # byte-for-byte. No parsing, no rewriting.
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(raw)))
            h.send_header("Cache-Control", "no-store")
            h.end_headers()
            h.wfile.write(raw)
            return

        if query == "model":
            deck = deck_path(dirs)
            parsed = model_module.parse_deck(deck.read_text(encoding="utf-8"))
            parsed["deck"] = str(deck)
            parsed["fingerprint"] = _fingerprint(deck)
            _send_json(h, 200, parsed)
            return

        if query == "poll":
            self.serve_poll(h, dirs)
            return

        _send_text(h, 404, f"unknown route: {query}")

    def serve_poll(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        events_dir = state_dir / "events"
        consumed_dir = state_dir / "consumed"
        queued = {p.stem for p in events_dir.glob("*.json")} if events_dir.is_dir() else set()
        acked = {p.stem for p in consumed_dir.glob("*.ack")} if consumed_dir.is_dir() else set()
        try:
            version = _fingerprint(deck_path(dirs))
        except (OSError, KeyError, json.JSONDecodeError):
            version = ""
        hb_file = state_dir / "watcher_heartbeat"
        hb = int(hb_file.read_text().strip()) if hb_file.is_file() else 0
        _send_json(h, 200, {
            # key name is dictated by core.js:110 — it reads .blocks/.threads only
            "blocks": {"deck": version},
            "consumed_events": sorted(acked),
            "busy": bool(queued - acked),
            "queued": len(queued - acked),
            "watcher_seen_at": hb,
            "finished": (state_dir / "finished").exists(),
        })

    # -- writes (events only; never the deck) ----------------------------
    def handle_submit(self, h: BaseHTTPRequestHandler, dirs: dict, payload: dict) -> None:
        comment = payload.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            _send_text(h, 400, "empty comment")
            return
        path = payload.get("path")
        if not isinstance(path, str) or not path:
            _send_text(h, 400, "missing path")
            return

        deck = deck_path(dirs)
        parsed = model_module.parse_deck(deck.read_text(encoding="utf-8"))
        known = {(e["slide"], e["path"])
                 for s in parsed["slides"] for e in s["elements"]}
        slide = payload.get("slide")
        if (slide, path) not in known:
            _send_text(h, 400, f"unknown element: slide {slide} {path}")
            return

        current = next(e for s in parsed["slides"] for e in s["elements"]
                       if e["slide"] == slide and e["path"] == path)
        event_id = events_module.append(Path(dirs["state_dir"]) / "events", {
            "type": "deck_comment",
            "deck": str(deck),
            "slide": slide,
            "path": path,
            "component": current["component"],
            "line_start": current["line_start"],
            "line_end": current["line_end"],
            "text": current["text"],
            "comment": comment.strip(),
        })
        _send_json(h, 202, {"event_id": event_id, "status": "queued"})

    def comment_count(self, dirs: dict) -> int:
        events_dir = Path(dirs["state_dir"]) / "events"
        if not events_dir.is_dir():
            return 0
        return sum(1 for p in events_dir.iterdir() if p.suffix == ".json")


def _send_text(h, status, body):
    data = body.encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/plain; charset=utf-8")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def _send_html(h, status, body):
    data = body.encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def _send_json(h, status, body_obj):
    data = json.dumps(body_obj).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def main() -> int:
    return wc_server.run(
        skill_name="deck",
        port_range=PORT_RANGE,
        handlers=Handlers(),
        # shared first — the skill CANNOT override core.css/core.js, hence
        # the distinct deck.css / deck.js filenames.
        static_dirs=[SHARED_STATIC_DIR, STATIC_DIR],
    )


if __name__ == "__main__":
    sys.exit(main())
