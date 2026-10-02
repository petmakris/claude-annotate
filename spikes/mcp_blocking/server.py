"""Minimal streamable-HTTP MCP server to measure how long Claude Code will wait
on a single tool call. Stdlib only.

Three tools, so three failure modes stay separable:
  wait_json(seconds)      - block, then answer as one application/json response
  wait_sse(seconds)       - answer as text/event-stream, keepalive every 5s
  wait_for_event(timeout) - block until POST /fire, then answer (the real shape)

Run:  python3 server.py 8899
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTOCOL_FALLBACK = "2025-06-18"
SESSION_ID = "spike-session-1"

# Set by POST /fire, consumed by wait_for_event.
_fired = threading.Event()
_fired_payload = {}

LOG = []


def log(msg):
    line = "%8.2f  %s" % (time.time() - START, msg)
    LOG.append(line)
    print(line, flush=True)


TOOLS = [
    {
        "name": "wait_json",
        "description": "Block for N seconds, then return. Plain JSON response.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "wait_sse",
        "description": "Block for N seconds, keeping the connection alive with SSE pings, then return.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "wait_progress",
        "description": "Block for N seconds, sending MCP progress notifications every 5s, then return.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "wait_for_event",
        "description": "Block until an external event arrives or timeout seconds pass. Returns the event payload.",
        "inputSchema": {
            "type": "object",
            "properties": {"timeout": {"type": "number"}},
            "required": ["timeout"],
        },
    },
]


def text_result(req_id, text):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": False},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # -- helpers ---------------------------------------------------------
    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Mcp-Session-Id", SESSION_ID)
        self.end_headers()
        self.wfile.write(body)

    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Mcp-Session-Id", SESSION_ID)
        self.end_headers()

    def _sse_ping(self):
        self.wfile.write(b": keepalive\n\n")
        self.wfile.flush()

    def _sse_message(self, obj):
        self.wfile.write(b"event: message\ndata: " + json.dumps(obj).encode() + b"\n\n")
        self.wfile.flush()

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        if self.path.startswith("/fire"):
            return self._fire()
        # Claude Code may open a GET /mcp SSE stream for server->client messages.
        if self.path.startswith("/mcp"):
            log("GET /mcp (server->client stream opened)")
            self._start_sse()
            try:
                while True:
                    time.sleep(5)
                    self._sse_ping()
            except Exception:
                log("GET /mcp stream closed")
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        log("DELETE %s (session end)" % self.path)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _fire(self):
        global _fired_payload
        _fired_payload = {"comment": "the user clicked block 3", "at": time.time()}
        _fired.set()
        log("POST /fire -> released wait_for_event")
        body = b'{"fired": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/fire"):
            return self._fire()
        msg = self._read_body()
        method = msg.get("method")
        req_id = msg.get("id")
        log("--> %s (id=%s)" % (method, req_id))

        if req_id is None:  # a notification
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            pv = msg.get("params", {}).get("protocolVersion", PROTOCOL_FALLBACK)
            log("    client protocolVersion=%s" % pv)
            return self._send_json({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": pv,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "annotate-spike", "version": "0.0.1"},
                },
            })

        if method == "tools/list":
            return self._send_json({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})

        if method == "ping":
            return self._send_json({"jsonrpc": "2.0", "id": req_id, "result": {}})

        if method == "tools/call":
            return self._call(msg, req_id)

        return self._send_json({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": "method not found: %s" % method},
        })

    def _call(self, msg, req_id):
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        t0 = time.time()
        log("    _meta=%s" % json.dumps(params.get("_meta")))

        if name == "wait_json":
            secs = float(args.get("seconds", 5))
            log("    wait_json: blocking %.0fs, no keepalive" % secs)
            try:
                time.sleep(secs)
                self._send_json(text_result(req_id, "wait_json returned after %.1fs" % (time.time() - t0)))
                log("    wait_json: WROTE RESPONSE after %.1fs" % (time.time() - t0))
            except Exception as e:
                log("    wait_json: CLIENT GONE after %.1fs (%s)" % (time.time() - t0, e))
            return

        if name == "wait_sse":
            secs = float(args.get("seconds", 5))
            log("    wait_sse: blocking %.0fs with 5s pings" % secs)
            self._start_sse()
            try:
                waited = 0.0
                while waited < secs:
                    time.sleep(min(5.0, secs - waited))
                    waited = time.time() - t0
                    if waited < secs:
                        self._sse_ping()
                        log("    wait_sse: ping at %.0fs" % waited)
                self._sse_message(text_result(req_id, "wait_sse returned after %.1fs" % waited))
                log("    wait_sse: WROTE RESPONSE after %.1fs" % waited)
            except Exception as e:
                log("    wait_sse: CLIENT GONE after %.1fs (%s)" % (time.time() - t0, e))
            return

        if name == "wait_progress":
            secs = float(args.get("seconds", 5))
            token = (params.get("_meta") or {}).get("progressToken")
            log("    wait_progress: blocking %.0fs, progressToken=%r" % (secs, token))
            self._start_sse()
            try:
                waited = 0.0
                n = 0
                while waited < secs:
                    time.sleep(min(5.0, secs - waited))
                    waited = time.time() - t0
                    if waited < secs:
                        n += 1
                        if token is not None:
                            self._sse_message({
                                "jsonrpc": "2.0",
                                "method": "notifications/progress",
                                "params": {
                                    "progressToken": token,
                                    "progress": n,
                                    "total": int(secs // 5),
                                    "message": "waiting for a comment (%.0fs)" % waited,
                                },
                            })
                        else:
                            self._sse_ping()
                        log("    wait_progress: progress %d at %.0fs" % (n, waited))
                self._sse_message(text_result(req_id, "wait_progress returned after %.1fs" % waited))
                log("    wait_progress: WROTE RESPONSE after %.1fs" % waited)
            except Exception as e:
                log("    wait_progress: CLIENT GONE after %.1fs (%s)" % (time.time() - t0, e))
            return

        if name == "wait_for_event":
            timeout = float(args.get("timeout", 60))
            log("    wait_for_event: waiting up to %.0fs for POST /fire" % timeout)
            self._start_sse()
            try:
                while time.time() - t0 < timeout:
                    if _fired.wait(timeout=5):
                        payload = json.dumps(_fired_payload)
                        _fired.clear()
                        self._sse_message(text_result(req_id, "EVENT " + payload))
                        log("    wait_for_event: DELIVERED EVENT after %.1fs" % (time.time() - t0))
                        return
                    self._sse_ping()
                    log("    wait_for_event: ping at %.0fs" % (time.time() - t0))
                self._sse_message(text_result(req_id, "TIMEOUT after %.1fs, no event" % (time.time() - t0)))
                log("    wait_for_event: timed out cleanly")
            except Exception as e:
                log("    wait_for_event: CLIENT GONE after %.1fs (%s)" % (time.time() - t0, e))
            return

        self._send_json({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32602, "message": "unknown tool: %s" % name},
        })


START = time.time()
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log("listening on http://127.0.0.1:%d/mcp" % port)
    srv.serve_forever()
