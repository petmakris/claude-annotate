"""Interactive-review skill — thin handlers module over web_companion.

Per-line PR review runs in IntelliJ via the IDE plugin.
This server is headless: it snapshots the PR diff, holds per-anchor threads,
streams thread changes over SSE, and enqueues /api/submit comments as events
for Claude. Claude wakes via watcher, reads context, appends a claude-role
message to the thread, acks. There is no browser review UI.
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from skills._shared.web_companion import server as wc_server
from skills._shared.web_companion import stream as stream_module
from skills._shared.web_companion.atomic import write_text_atomic
from skills._shared.web_companion import events as events_module
from skills._shared.web_companion import uploads as uploads_module
from skills.interactive_review import diff as diff_module
from skills._shared.web_companion import threads as threads_module

# The engine owns its own layout; ask it where its static files are rather
# than rebuilding the path by hand. Four skills hard-coding
# `../_shared/web_companion/static` meant moving that folder broke all four
# silently — the expression still resolves, it just resolves to nothing.
SHARED_STATIC_DIR = wc_server.SHARED_STATIC_DIR

PORT_RANGE = range(54620, 54641)
NEVER_ARMED_GRACE = 1800  # s; a session that never wrote a heartbeat is dead
# past this. Measured from the state dir's mtime, i.e. roughly session-create
# time, and it must comfortably exceed the longest gap a caller can put between
# creating the session and arming the watcher — because once it expires the
# server reports ended_reason "dead" on EVERY poll, which the IDE latches
# read-only for good. At the old 300s, a caller that seeded a batch of threads
# before arming froze its own live session. The cost of erring high is only
# that a session whose Claude died before arming lingers in the panel.
BANNER = "interactive-review-server v1"

WARN_DIFF_BYTES = 1 * 1024 * 1024   # soft warning surfaced to the user
MAX_DIFF_BYTES = 5 * 1024 * 1024    # hard reject — review a narrower PR

IDE_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Interactive Review</title>
<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center}main{max-width:32rem;text-align:center;padding:2rem;line-height:1.5}h1{font-size:1.15rem;font-weight:600}b{color:#fff}</style></head>
<body><main><h1>🔍 Interactive review runs in IntelliJ</h1>
<p>This review has no browser page. Open the project in <b>IntelliJ&nbsp;IDEA</b> — the plugin shows per-line annotations on the diff.</p></main></body></html>
"""

CLOSED_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Closed</title>
<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0d1117;color:#8b949e;display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center}</style></head>
<body><main><p>This review session is closed.</p></main></body></html>
"""


def _is_terminal(state_dir: Path) -> bool:
    return (state_dir / "finished").exists() or (state_dir / "cancelled").exists()


class Handlers:
    # Lifecycle is owned server-side: each create cancels this Claude
    # session's prior sessions, so a forgotten SKILL.md cleanup step can't
    # leak watchers (annotate keeps this off — its workspaces are long-lived
    # and multi-push by design).
    supersede_by_claude_session = True

    def __init__(self):
        self._registry = None

    def set_registry(self, registry) -> None:
        self._registry = registry

    def serve_root(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        if _is_terminal(state_dir):
            _send_html(h, 200, CLOSED_PAGE)
            return
        _send_html(h, 200, IDE_PAGE)

    def threads_bulk(self, dirs: dict) -> dict:
        """Return {anchor: {latest_synthesis, version, updated_at}} for all threads.

        latest_synthesis is the text of the most-recent message with role='claude'.
        Threads without a claude message yet are omitted.
        """
        threads_dir = Path(dirs["state_dir"]) / "threads"
        result: dict = {}
        if not threads_dir.is_dir():
            return result
        for p in threads_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                t = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            anchor = t.get("anchor")
            if not isinstance(anchor, str):
                continue
            claude_msgs = [m for m in t.get("messages", []) if m.get("role") == "claude"]
            if not claude_msgs:
                continue
            last = claude_msgs[-1]
            user_msgs = [m for m in t.get("messages", []) if m.get("role") == "user"]
            result[anchor] = {
                "latest_synthesis": last.get("text", ""),
                "version": t.get("version", 0),
                "updated_at": last.get("ts", 0),
                "anchor_text": t.get("anchor_text", ""),
                "title": t.get("title", ""),
                # The LAST question, not the first: this field is shown next to
                # `latest_synthesis`, which is the last Claude reply, so it has
                # to be the question that reply answers. Walkthrough's copy of
                # this function already did it this way; on any thread with a
                # follow-up the two skills displayed different questions for
                # identically-shaped data.
                "question": user_msgs[-1].get("text", "") if user_msgs else "",
            }
        return result

    def serve_data(self, h: BaseHTTPRequestHandler, dirs: dict, query: str) -> None:
        state_dir = Path(dirs["state_dir"])
        if query == "stream":
            self._serve_stream(h, dirs)
            return
        if query == "threads.json":
            _send_json(h, 200, self.threads_bulk(dirs))
            return
        _send_text(h, 404, "not found")

    def _serve_stream(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        """SSE: thread-changed / thread-deleted / session-ended / heartbeat."""
        stream_module.serve(
            h, dirs,
            registry=self._registry,
            threads_bulk=self.threads_bulk,
            is_terminal=_is_terminal,
        )

    def handle_thread_delete(self, h: BaseHTTPRequestHandler, dirs: dict, payload: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        if _is_terminal(state_dir):
            _send_text(h, 409, "session closed")
            return
        anchor = payload.get("anchor")
        if not isinstance(anchor, str) or not threads_module.valid_anchor(anchor):
            _send_text(h, 400, "bad anchor")
            return
        threads_module.delete(state_dir / "threads", anchor)
        _send_json(h, 200, {"anchor": anchor, "status": "deleted"})

    def handle_submit(self, h: BaseHTTPRequestHandler, dirs: dict, payload: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        if _is_terminal(state_dir):
            _send_text(h, 409, "session closed")
            return
        anchor = payload.get("anchor")
        comment_type = payload.get("type", "comment")
        text = payload.get("text", "")
        selected_text = payload.get("selected_text")
        images = payload.get("images", [])
        if not isinstance(anchor, str) or not threads_module.valid_anchor(anchor):
            _send_text(h, 400, "bad anchor")
            return
        if comment_type not in ("comment", "reject"):
            _send_text(h, 400, "bad type")
            return
        if not isinstance(text, str):
            _send_text(h, 400, "bad text")
            return
        if images and not uploads_module.images_ok(images, state_dir):
            _send_text(h, 400, "bad images")
            return
        evt = {
            "anchor": anchor,
            "type": comment_type,
            "text": text,
            "selected_text": selected_text,
            "images": images,
        }
        eid = events_module.append(Path(dirs["events_dir"]), evt)
        threads_dir = state_dir / "threads"
        threads_module.append_message(threads_dir, anchor, {
            "role": "user",
            "ts": int(time.time()),
            "text": text,
            "selected_text": selected_text,
            "images": images,
            "source_event_id": f"user-{eid}",
        })
        anchor_text = payload.get("anchor_text")
        if isinstance(anchor_text, str):
            threads_module.set_anchor_text_if_absent(threads_dir, anchor, anchor_text)
        _send_json(h, 202, {"event_id": eid, "status": "queued"})

    def serve_poll(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        threads_dir = state_dir / "threads"
        versions = threads_module.list_versions(threads_dir)
        hb_path = state_dir / "watcher_heartbeat"
        armed = hb_path.exists()
        try:
            hb = int(hb_path.read_text().strip())
        except (FileNotFoundError, ValueError, OSError):
            # The file is missing (never armed) OR it exists and this read
            # caught it mid-rewrite / failed transiently. Those are opposite
            # facts and must not collapse into the same answer — see `armed`.
            hb = 0
        # Liveness: a session is ENDED if explicitly cancelled/finished, or if
        # its watcher has been silent past REAP_AFTER. When no beat was ever
        # written, fall back to the session's creation age (state_dir mtime):
        # a session whose Claude crashed before arming the watcher must not
        # look live forever.
        if hb:
            age = int(time.time()) - hb
        elif armed:
            # A heartbeat file exists but this read couldn't parse it. A live
            # watcher rewrites it every ~1s, so an unreadable sample is
            # evidence of nothing — never of death. Report age unknown and let
            # the next poll (~1s later) decide. Collapsing this into the
            # never-armed branch below declared live sessions dead, and the
            # IDE's ENDED latch made that permanent.
            age = None
        else:
            try:
                created = int(state_dir.stat().st_mtime)
            except OSError:
                created = int(time.time())
            grace_age = int(time.time()) - created
            age = grace_age if grace_age > NEVER_ARMED_GRACE else None
        cancelled = (state_dir / "cancelled").exists()
        finished = (state_dir / "finished").exists()
        dead = age is not None and age > wc_server.REAP_AFTER
        ended_reason = (
            "cancelled" if cancelled
            else "finished" if finished
            else "dead" if dead
            else None
        )
        _send_json(h, 200, {
            "threads": versions,
            "watcher_seen_at": hb,
            "finished": _is_terminal(state_dir),
            "ended": ended_reason is not None,
            "ended_reason": ended_reason,
        })

    def create_session_extra(self, payload: dict, dirs: dict) -> dict | None:
        state_dir = Path(dirs["state_dir"])
        (state_dir / "threads").mkdir(exist_ok=True)
        pr_ref = payload.get("pr")
        if not isinstance(pr_ref, str) or not pr_ref:
            raise ValueError("payload missing 'pr' (PR number, URL, or branch)")
        try:
            diff_text, meta = diff_module.fetch_pr_diff(pr_ref, dirs.get("_cwd"))
        except Exception as e:
            raise ValueError(f"gh pr fetch failed: {e}") from e
        diff_bytes = len(diff_text.encode("utf-8"))
        if diff_bytes > MAX_DIFF_BYTES:
            raise ValueError(
                f"diff is {diff_bytes // 1024} KB, over the {MAX_DIFF_BYTES // (1024 * 1024)} MB limit — "
                "review a narrower PR, a single commit, or a branch with fewer changes"
            )
        write_text_atomic(state_dir / "diff.patch", diff_text)
        write_text_atomic(state_dir / "meta.json", json.dumps({
            "pr_ref": pr_ref,
            "title": meta.get("title", pr_ref),
            "head": meta.get("headRefName", ""),
            "base": meta.get("baseRefName", ""),
            "author": (meta.get("author") or {}).get("login", ""),
            "url": meta.get("url", ""),
            "head_oid": meta.get("headRefOid", ""),
            "fetched_at": int(time.time()),
        }, indent=2))
        result = {"pr_ref": pr_ref, "title": meta.get("title", pr_ref)}
        if diff_bytes > WARN_DIFF_BYTES:
            result["warning"] = (
                f"large diff ({diff_bytes // 1024} KB) — annotations may be slow; "
                "consider a narrower PR or branch"
            )
        return result

    def comment_count(self, dirs: dict) -> int:
        """Number of per-anchor threads for this review session."""
        threads_dir = Path(dirs["state_dir"]) / "threads"
        if not threads_dir.is_dir():
            return 0
        return sum(1 for p in threads_dir.iterdir() if p.suffix == ".json")


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
        skill_name="interactive-review",
        port_range=PORT_RANGE,
        handlers=Handlers(),
        static_dirs=[SHARED_STATIC_DIR],
    )


if __name__ == "__main__":
    sys.exit(main())
