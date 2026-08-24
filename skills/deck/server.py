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

# Everything that reading a deck (or its meta.json) can go wrong with. A
# Latin-1 deck raises UnicodeDecodeError, a truncated meta.json raises
# JSONDecodeError, and neither is an OSError — both used to 500 the page.
DECK_ERRORS = (OSError, KeyError, ValueError, json.JSONDecodeError)

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
        # Resolve BEFORE checking the suffix. What gets stored and served is
        # the resolved path, so checking the supplied one lets `deck.html`
        # pointing at `id_rsa` through — and every GET under /s/<slug>/ is
        # ungated by design, so a shared link would then serve that file.
        deck = Path(raw).expanduser().resolve()
        if not deck.is_file():
            raise ValueError(f"deck not found: {deck}")
        if deck.suffix.lower() != ".html":
            raise ValueError(
                f"deck must be an .html file (resolved to {deck.name}): {deck}")
        write_text_atomic(Path(dirs["state_dir"]) / "meta.json", json.dumps({
            "deck": str(deck),
            "title": deck.stem,
            "created_at": int(time.time()),
        }, indent=2))
        return {"deck": str(deck), "title": deck.stem}

    # -- reads -----------------------------------------------------------
    def serve_root(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        try:
            title = deck_path(dirs).stem
        except DECK_ERRORS:
            title = "deck"
        sid = Path(dirs["state_dir"]).parent.name
        _send_html(h, 200, PAGE.format(title=title, sid=sid))

    def serve_data(self, h: BaseHTTPRequestHandler, dirs: dict, query: str) -> None:
        if query == "deck":
            try:
                raw = deck_path(dirs).read_bytes()
            except DECK_ERRORS as exc:
                _send_text(h, 404, f"deck unreadable: {exc}")
                return
            # One page mounts one frame per slide, all pointing here, and a
            # deck with embedded images runs to tens of megabytes. Without a
            # validator each frame refetches the whole file — 25 slides of a
            # 15MB deck moved 386MB on every repaint. no-cache means
            # "revalidate every time", not "do not cache", so a changed file
            # is still picked up on the very next request.
            etag = '"%s"' % hashlib.sha1(raw).hexdigest()
            if _matches_etag(h.headers.get("If-None-Match"), etag):
                h.send_response(304)
                h.send_header("ETag", etag)
                h.send_header("Cache-Control", "no-cache")
                h.end_headers()
                return
            # byte-for-byte. No parsing, no rewriting.
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(raw)))
            h.send_header("ETag", etag)
            h.send_header("Cache-Control", "no-cache")
            h.end_headers()
            h.wfile.write(raw)
            return

        if query == "model":
            try:
                deck = deck_path(dirs)
                raw = deck.read_text(encoding="utf-8")
            except DECK_ERRORS as exc:
                # The file can vanish, be renamed, or turn out not to be UTF-8
                # under a long-lived workspace. Say so instead of raising into
                # the shared server, which would answer an opaque 500.
                _send_text(h, 404, f"deck unreadable: {exc}")
                return
            parsed = model_module.parse_deck(raw)
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
        except DECK_ERRORS:
            version = ""
        # watcher.sh writes this with `date +%s > file`, a truncate then a
        # write. A poll landing inside that window reads "" and int() raises.
        hb = 0
        try:
            hb = int((state_dir / "watcher_heartbeat").read_text().strip())
        except (OSError, ValueError):
            pass
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

        try:
            deck = deck_path(dirs)
            parsed = model_module.parse_deck(deck.read_text(encoding="utf-8"))
        except DECK_ERRORS as exc:
            _send_text(h, 404, f"deck unreadable: {exc}")
            return
        # A path is not unique: real decks carry several blocks with the same
        # class on one slide. (path, ord) is the address; matching on path
        # alone would land every comment on the first one.
        ordinal = payload.get("ord", 0)
        if not isinstance(ordinal, int) or ordinal < 0:
            _send_text(h, 400, "ord must be a non-negative integer")
            return
        slide = payload.get("slide")
        current = next(
            (e for s in parsed["slides"] for e in s["elements"]
             if e["slide"] == slide and e["path"] == path and e["ord"] == ordinal),
            None)
        if current is None:
            _send_text(h, 400, f"unknown element: slide {slide} {path} #{ordinal}")
            return
        event_id = events_module.append(Path(dirs["state_dir"]) / "events", {
            "type": "deck_comment",
            "deck": str(deck),
            "slide": slide,
            "path": path,
            "ord": ordinal,
            "component": current["component"],
            "line_start": current["line_start"],
            "line_end": current["line_end"],
            "text": current["text"],
            "comment": comment.strip(),
        })
        _send_json(h, 202, {"event_id": event_id, "status": "queued"})

    def comment_count(self, dirs: dict) -> int:
        """Distinct comments, queued and already handled.

        The watcher MOVES a handled event out of events/ into consumed/, so
        counting events/ alone reports 0 for a workspace that has taken
        twenty comments. Dedup by stem: an event that is both queued and
        acked (a brief race) must not count twice.
        """
        state_dir = Path(dirs["state_dir"])
        ids: set[str] = set()
        events_dir = state_dir / "events"
        if events_dir.is_dir():
            ids |= {p.stem for p in events_dir.glob("*.json")}
        consumed_dir = state_dir / "consumed"
        if consumed_dir.is_dir():
            ids |= {p.stem for p in consumed_dir.glob("*.ack")}
        return len(ids)


def _matches_etag(header: str | None, etag: str) -> bool:
    """True if the client already holds this version.

    Browsers revalidate with a weak validator (`W/"..."`) and may send several
    comma-separated tags. An exact string compare misses both and answers 200
    with the whole file — the bandwidth the ETag exists to save.
    """
    if not header:
        return False
    if header.strip() == "*":
        return True
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
    return False


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
