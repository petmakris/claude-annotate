"""Dataflow skill — thin handlers module over web_companion.

Renders one feature's path through a codebase as a diagram in the browser:
columns of nodes per slice, mappers hanging off the arrows between them, and
every node openable in the editor. The reader can ask a question on any node;
the answer lands back inside that node.

The server knows nothing about Java, Spring, DDD or layering. It renders
whatever `dataflow.json` Claude wrote, exactly as walkthrough renders
steps.json — the domain knowledge lives in SKILL.md. That is what keeps this
skill usable on a codebase nobody anticipated.
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from skills._shared.web_companion import server as wc_server
from skills._shared.web_companion import stream as stream_module
from skills._shared.web_companion import events as events_module
from skills._shared.web_companion import uploads as uploads_module
from skills._shared.web_companion import threads as threads_module
from skills._shared.web_companion.atomic import write_text_atomic
from skills._shared.web_companion.templates import html_escape
from skills.dataflow import flow as flow_module

SHARED_STATIC_DIR = wc_server.SHARED_STATIC_DIR
STATIC_DIR = Path(__file__).resolve().parent / "static"

# A fixed port, like annotate and deck: this page is opened by a human in a
# browser, and a URL that moves between runs is a URL nobody can bookmark.
PORT_RANGE = range(3100, 3101)
NEVER_ARMED_GRACE = 1800  # s — see walkthrough/server.py for why this is high
BANNER = "dataflow-server v1"

EMPTY_DOC = {"seed": "", "question": "", "generated_ts": 0, "model": [], "slices": []}


def _is_terminal(state_dir: Path) -> bool:
    return (state_dir / "finished").exists() or (state_dir / "cancelled").exists()


def _shell(title: str, body: str, *, script: bool = True) -> str:
    """The page shell. Deliberately minimal: everything else is fetched.

    The board is built client-side from dataflow.json rather than rendered
    here, because the same render has to run again when SSE reports the
    document changed. One renderer, not two that drift.
    """
    # markdown-it first: Claude writes replies as raw markdown, and a reply
    # rendered as plain text shows its own asterisks and pipe tables to the
    # reader. Both are `defer`, so load order is document order.
    js = ('<script src="/static/markdown-it.min.js" defer></script>'
          '<script src="/static/dataflow.js" defer></script>') if script else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html_escape(title)}</title>"
        '<link rel="stylesheet" href="/static/dataflow.css">'
        f"{js}</head><body>{body}</body></html>"
    )


WAITING_BODY = (
    '<div class="splash"><div><h1>Mapping the dataflow…</h1>'
    '<p>Claude is reading the code. This page refreshes itself when the '
    'diagram is ready.</p></div></div>'
    '<script>setTimeout(()=>location.reload(),2500)</script>'
)
CLOSED_BODY = (
    '<div class="splash"><div><h1>This dataflow is closed.</h1>'
    '<p>Run <code>/dataflow &lt;class or feature&gt;</code> again to open a new one.</p>'
    '</div></div>'
)


class Handlers:
    # One live dataflow per Claude session: a second /dataflow in the same
    # conversation replaces the first rather than leaving two armed watchers
    # racing to answer the same question. annotate keeps this off because its
    # workspaces are long-lived; this one is a per-question artifact.
    supersede_by_claude_session = True

    def __init__(self):
        self._registry = None

    def set_registry(self, registry) -> None:
        self._registry = registry

    # ---------------------------------------------------------------- pages
    def serve_root(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        if _is_terminal(state_dir):
            _send_html(h, 200, _shell("Closed", CLOSED_BODY, script=False))
            return
        doc = flow_module.load_flow(state_dir)
        if not doc:
            _send_html(h, 200, _shell("Dataflow", WAITING_BODY, script=False))
            return
        seed = str(doc.get("seed") or "dataflow")
        _send_html(h, 200, _shell(f"Dataflow — {seed}", '<div id="app"></div>'))

    # ----------------------------------------------------------------- data
    def serve_data(self, h: BaseHTTPRequestHandler, dirs: dict, query: str) -> None:
        state_dir = Path(dirs["state_dir"])
        if query == "stream":
            self._serve_stream(h, dirs)
            return
        if query == "dataflow.json":
            _send_json(h, 200, flow_module.load_flow(state_dir) or EMPTY_DOC)
            return
        if query == "threads.json":
            _send_json(h, 200, self.threads_bulk(dirs))
            return
        _send_text(h, 404, "not found")

    def threads_bulk(self, dirs: dict) -> dict:
        """{anchor: {latest_synthesis, version, updated_at, title, question}}.

        Threads with no claude-role message yet are omitted — the page owns the
        pending state for a question it has just submitted, and an empty thread
        would overwrite that with nothing.
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
            if not isinstance(anchor, str) or not flow_module.valid_anchor(anchor):
                continue
            messages = t.get("messages", [])
            claude_msgs = [m for m in messages if m.get("role") == "claude"]
            if not claude_msgs:
                continue
            user_msgs = [m for m in messages if m.get("role") == "user"]
            last = claude_msgs[-1]
            result[anchor] = {
                "latest_synthesis": last.get("text", ""),
                "version": t.get("version", 0),
                "updated_at": last.get("ts", 0),
                "title": t.get("title", ""),
                "question": user_msgs[-1].get("text", "") if user_msgs else "",
            }
        return result

    def _serve_stream(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        """SSE: flow-changed on top of the shared thread stream.

        The document can be regenerated mid-session — a follow-up question can
        widen the trace — so the page needs to know to refetch it. Rides the
        engine loop's `extra` hook rather than forking the loop.
        """
        state_dir = Path(dirs["state_dir"])
        last_ts = [None]  # None = not yet sent; forces the first tick to emit

        def emit_flow(emit) -> bool:
            ts = flow_module.generated_ts(state_dir)
            first = last_ts[0] is None
            if not first and ts == last_ts[0]:
                return True
            last_ts[0] = ts
            if first and not ts:
                # Nothing generated yet: the client's splash is already right.
                # A LATER drop to 0 does emit, so a client that had a diagram
                # learns it went away.
                return True
            doc = flow_module.load_flow(state_dir) or EMPTY_DOC
            return emit("flow-changed",
                        {"generated_ts": ts, "nodes": flow_module.count_nodes(doc)})

        stream_module.serve(
            h, dirs,
            registry=self._registry,
            threads_bulk=self.threads_bulk,
            is_terminal=_is_terminal,
            extra=emit_flow,
        )

    # ---------------------------------------------------------------- writes
    def handle_submit(self, h: BaseHTTPRequestHandler, dirs: dict, payload: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        if _is_terminal(state_dir):
            _send_text(h, 409, "session closed")
            return
        anchor = payload.get("anchor")
        ask_type = payload.get("type", "comment")
        text = payload.get("text", "")
        selected_text = payload.get("selected_text")
        images = payload.get("images", [])
        if not flow_module.valid_anchor(anchor):
            _send_text(h, 400, "bad anchor")
            return
        # The anchor must name a node that is actually in the document. A
        # question filed against a node that does not exist can never be
        # rendered back, so it would queue an event Claude answers into a void.
        doc = flow_module.load_flow(state_dir)
        if not doc or flow_module.anchor_node_id(anchor) not in flow_module.node_ids(doc):
            _send_text(h, 404, "unknown node")
            return
        if ask_type not in ("comment", "reject"):
            _send_text(h, 400, "bad type")
            return
        if not isinstance(text, str) or not text.strip():
            _send_text(h, 400, "bad text")
            return
        if images and not uploads_module.images_ok(images, state_dir):
            _send_text(h, 400, "bad images")
            return
        eid = events_module.append(Path(dirs["events_dir"]), {
            "anchor": anchor,
            "type": ask_type,
            "text": text,
            "selected_text": selected_text,
            "images": images,
        })
        threads_module.append_message(state_dir / "threads", anchor, {
            "role": "user",
            "ts": int(time.time()),
            "text": text,
            "selected_text": selected_text,
            "images": images,
            "source_event_id": f"user-{eid}",
        })
        _send_json(h, 202, {"event_id": eid, "status": "queued"})

    # -------------------------------------------------------------- lifecycle
    def serve_poll(self, h: BaseHTTPRequestHandler, dirs: dict) -> None:
        state_dir = Path(dirs["state_dir"])
        versions = threads_module.list_versions(state_dir / "threads")
        hb_path = state_dir / "watcher_heartbeat"
        armed = hb_path.exists()
        try:
            hb = int(hb_path.read_text().strip())
        except (FileNotFoundError, ValueError, OSError):
            hb = 0
        if hb:
            age = int(time.time()) - hb
        elif armed:
            # The file is there but unreadable this tick. A live watcher
            # rewrites it every ~1s, so one bad sample proves nothing — never
            # death. Report age unknown and let the next poll decide.
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
            "flow_generated_at": flow_module.generated_ts(state_dir),
            "watcher_seen_at": hb,
            "finished": _is_terminal(state_dir),
            "ended": ended_reason is not None,
            "ended_reason": ended_reason,
        })

    def create_session_extra(self, payload: dict, dirs: dict) -> dict | None:
        """Cheap: no external fetch. Seed dirs and record what was asked."""
        state_dir = Path(dirs["state_dir"])
        (state_dir / "threads").mkdir(exist_ok=True)
        seed = payload.get("seed")
        if not isinstance(seed, str) or not seed.strip():
            raise ValueError("payload missing 'seed' (the class or feature to trace)")
        question = payload.get("question") or seed
        if not isinstance(question, str) or not question.strip():
            raise ValueError("payload 'question', when present, must be non-empty")
        write_text_atomic(state_dir / "meta.json", json.dumps({
            "title": seed.strip(),
            "seed": seed.strip(),
            "question": question.strip(),
            "cwd": dirs.get("_cwd", ""),
            "created_at": int(time.time()),
        }, indent=2))
        return {"title": seed.strip(), "seed": seed.strip()}

    def comment_count(self, dirs: dict) -> int:
        """Number of per-node threads on this dataflow."""
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
        skill_name="dataflow",
        port_range=PORT_RANGE,
        handlers=Handlers(),
        static_dirs=[SHARED_STATIC_DIR, STATIC_DIR],
    )


if __name__ == "__main__":
    sys.exit(main())
