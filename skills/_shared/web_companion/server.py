"""Shared HTTP server entrypoint.

Each skill calls server.run(skill_name=..., port_range=..., handlers=...,
static_dirs=...). The shared core owns: port binding, threaded HTTP shell,
idle watchdog, server.json write under ~/.claude/<skill>/server.json,
the /, /health, /static/*, /api/sessions, /s/<sid>/api/upload routes, and
session registry.  Everything else dispatches to the skill via
HandlersProtocol.
"""
from __future__ import annotations

import http.server
import ipaddress
import json
import os
import secrets
import socket
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from skills._shared.web_companion.handlers import HandlersProtocol
from skills._shared.web_companion.sessions import Registry, SID_RE
from skills._shared.web_companion import uploads as upload_module
from skills._shared.web_companion import static_serve
from skills._shared.web_companion import cleanup, paths
from skills._shared.web_companion.atomic import write_text_atomic

SHARED_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _is_terminal(dirs: dict) -> bool:
    """Return True if the session has a finished or cancelled marker."""
    state_dir = Path(dirs["state_dir"])
    return (state_dir / "finished").exists() or (state_dir / "cancelled").exists()


REAP_AFTER = 180  # seconds; a watcher silent longer than this is treated as dead


def _watcher_age(dirs: dict) -> int | None:
    """Seconds since the watcher last beat, or None if it never has.

    The heartbeat file holds an integer epoch second (written by watcher.sh
    every ~1s). Missing/empty/unparseable -> None, which callers treat as
    "live": a freshly-armed session has not written its first beat yet, so it
    must not be reaped.
    """
    hb_path = Path(dirs["state_dir"]) / "watcher_heartbeat"
    try:
        hb = int(hb_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return int(time.time()) - hb


LIVE_WINDOW = 10  # seconds; heartbeat fresher than this => "live"


def _read_hb(state_dir):
    p = Path(state_dir) / "watcher_heartbeat"
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def _session_meta(registry, dirs, sid):
    """Legacy meta source: state_dir/meta.json (NOT registry meta), preserved
    byte-for-byte from the pre-scope=all behavior so interactive_review is
    unaffected."""
    meta = {}
    mp = Path(dirs["state_dir"]) / "meta.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
        except json.JSONDecodeError:
            meta = {}
    return meta


def session_row(sid, dirs, meta, now, legacy=False, count_fn=None):
    if legacy:
        return {"sid": sid, "pr_ref": meta.get("pr_ref", ""),
                "title": meta.get("title", ""), "state_dir": str(dirs["state_dir"])}
    hb = _read_hb(dirs["state_dir"])
    if _is_terminal(dirs):
        status = "done"
    elif hb is not None and (now - hb) < LIVE_WINDOW:
        status = "live"
    else:
        status = "idle"
    return {
        "sid": sid, "slug": meta.get("slug", sid),
        "title": meta.get("title", ""), "project": meta.get("project", ""),
        "pr_ref": meta.get("pr_ref", ""),
        "last_active": hb or meta.get("created_at", 0),
        "comment_count": count_fn(dirs) if count_fn else 0,
        "status": status, "state_dir": str(dirs["state_dir"]),
    }


def list_rows(registry, cwd, scope, now, count_fn=None):
    if cwd:
        pairs = registry.find_by_cwd(cwd)
        out = []
        for sid, dirs in pairs:
            age = _watcher_age(dirs)
            if _is_terminal(dirs) or (age is not None and age > REAP_AFTER):
                continue
            out.append(session_row(sid, dirs, _session_meta(registry, dirs, sid), now, legacy=True))
        out.sort(key=lambda r: r["sid"], reverse=True)
        return out
    if scope != "all":
        return []          # handler renders the legacy 400 for this case
    # scope=all -> every registered session (live, idle, or done) within the
    # retention window. Unlike the legacy ?cwd= branch above, this must NOT
    # reap by watcher age: a watcher stops heartbeating the instant its
    # Claude session ends, leaving a STALE (but present) heartbeat file on
    # disk, so age-based reaping here would hide every idle-but-legitimate
    # workspace 180s after the session that created it exits — exactly the
    # set /annotate resume and the browser need to see. registry.list_all()
    # is already pruned to live on-disk dirs by rehydrate(), so the only
    # remaining gate is retention (same env/default the startup GC uses) —
    # and by default there is none: workspaces stay listed until deleted.
    retention_seconds = cleanup.retention_seconds_from_env()
    out = []
    for sid, dirs in registry.list_all():
        meta = registry.get_meta(sid)
        hb = _read_hb(dirs["state_dir"])
        last_active = hb or meta.get("created_at", 0)
        if now - last_active > retention_seconds:
            continue
        out.append(session_row(sid, dirs, meta, now, count_fn=count_fn))
    out.sort(key=lambda r: r["last_active"], reverse=True)
    return out


def delete_session(registry, key) -> bool:
    """Explicitly delete a workspace: its on-disk dir, then its registration.

    This is the ONLY sanctioned way a workspace disappears under the default
    (infinite) retention. `key` may be a slug or a sid. Returns False for an
    unknown key, and False without raising if the tree could not be removed.

    The registration is dropped ONLY once the tree is actually gone. That
    ordering is the whole point: `rmtree(ignore_errors=True)` swallows a
    permissions problem or a locked file, so unregistering unconditionally
    reported success, left the files on disk, and threw away the only handle
    that could reach them — the key stopped resolving, so "just delete it
    again" answered 404 forever, and `rehydrate` could not recover it either
    because the row was gone from sessions.json. Keeping the row instead
    leaves the workspace visible in the index and the retry genuinely works.
    """
    sid = registry.resolve(key)
    if sid is None:
        return False
    dirs = registry.lookup(sid)
    state_dir = (dirs or {}).get("state_dir")
    if state_dir:
        base = Path(state_dir).parent
        shutil.rmtree(base, ignore_errors=True)
        if base.exists():
            return False
    registry.unregister(sid)
    registry.persist()
    return True


def supersede_for_claude_session(registry, claude_session_id, exclude_sid=None):
    """Cancel every non-terminal session created by this Claude session.

    Lifecycle ownership lives here, not in SKILL.md prose: a skill whose
    handlers set `supersede_by_claude_session = True` gets prior sessions
    cancelled server-side on every create, so a model that forgets a cleanup
    step can no longer leak watchers. Returns the superseded sids.
    """
    if not claude_session_id:
        return []
    superseded = []
    for sid, dirs in registry.list_all():
        if sid == exclude_sid:
            continue
        if registry.get_meta(sid).get("claude_session_id") != claude_session_id:
            continue
        state_dir = Path(dirs.get("state_dir", ""))
        if not state_dir.is_dir() or _is_terminal(dirs):
            continue
        write_text_atomic(
            state_dir / "cancelled",
            json.dumps({"reason": "superseded", "at": int(time.time())}))
        registry.note_change(sid)
        superseded.append(sid)
    return superseded


def create_or_attach(registry, skill_name, payload, cwd, mkdirs, on_create=None,
                     supersede=False):
    """Return ({sid, slug, dirs, created}, created_bool).

    mkdirs(sid) -> dirs dict (response_dir/annotations_dir/state_dir/events_dir/
    consumed_dir), all created. Pure of HTTP; URL assembly is the caller's job.

    on_create(dirs), if given, runs on the CREATE path only — after dirs are
    made and `_cwd` is set, but BEFORE the session is registered/persisted.
    If it raises, the exception propagates, nothing is registered, and the
    just-made directory tree is removed again (an unregistered tree would be
    invisible to the GC sweep and leak forever). Never called on the attach
    path (attach must not re-run a skill's per-session init, e.g. re-fetching
    a PR diff).

    supersede=True: after a successful CREATE, cancel every other non-terminal
    session whose meta carries the same `claude_session_id` as this payload.
    """
    title = (payload.get("title") or "").strip()
    project = (payload.get("project") or Path(cwd).name).strip()
    explicit_slug = (payload.get("slug") or "").strip()
    claude_session_id = (payload.get("claude_session_id") or "").strip()
    want_attach = bool(payload.get("attach"))

    if want_attach:
        target_sid = None
        if explicit_slug:
            target_sid = registry.find_by_slug(explicit_slug)
        else:
            live = registry.find_by_cwd(cwd)
            live.sort(key=lambda kv: kv[0], reverse=True)
            target_sid = live[0][0] if live else None
        if target_sid is not None:
            dirs = registry.lookup(target_sid)
            if dirs and Path(dirs["state_dir"]).is_dir():
                meta = registry.get_meta(target_sid)
                return ({"sid": target_sid, "slug": meta.get("slug", target_sid),
                         "dirs": dirs, "created": False}, False)
            # dead sid (state_dir missing): free its slug before falling
            # through to create, so the intended slug is reused (no -2
            # bump) and no ghost registry entry lingers.
            registry.unregister(target_sid)
        # fall through to create (self-heal)

    sid = registry.make_sid()
    dirs = mkdirs(sid)
    dirs["_cwd"] = str(cwd)
    # The workspace no longer sits inside its project, so its path no longer
    # names the project. Record that inside the tree, or nothing on disk knows
    # which repo the anchors in this workspace resolve against.
    paths.write_marker(paths.base_of(dirs), sid, skill_name, cwd)
    if on_create is not None:
        try:
            on_create(dirs)
        except Exception:
            # The tree was made before init failed; it isn't registered, so
            # the registry-driven GC would never see it. Remove it now.
            base = Path(dirs["state_dir"]).parent
            shutil.rmtree(base, ignore_errors=True)
            raise
    # Slug allocation + registration happen atomically under one lock inside
    # register_with_slug — see its docstring for why the old two-step
    # (make_slug snapshot, then register) was a check-then-act race.
    meta = {"title": title, "project": project, "created_at": int(time.time())}
    if claude_session_id:
        meta["claude_session_id"] = claude_session_id
    slug = registry.register_with_slug(sid, dirs, meta, cwd, explicit_slug)
    registry.persist()
    if supersede:
        supersede_for_claude_session(registry, claude_session_id, exclude_sid=sid)
    return ({"sid": sid, "slug": slug, "dirs": dirs, "created": True}, True)


def code_fingerprint() -> str:
    """Stable hash of the skills tree this process runs from.

    Mirrors the computation in ensure_server.sh; the pair must agree so a
    healthy-but-outdated server (old install dir, or same dir with edited
    files) is detected and restarted instead of serving stale code forever.
    """
    import hashlib
    root = Path(__file__).resolve().parents[2]      # .../skills
    h = hashlib.sha1()
    paths = sorted(list(root.rglob("*.py")) + list(root.rglob("*.sh")))
    for p in paths:
        if "__pycache__" in p.parts or "tests" in p.parts:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root)}:{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()[:12]


def _resolve_public_host() -> str:
    if env := os.environ.get("WEBCOMPANION_PUBLIC_HOST"):
        return env
    try:
        out = subprocess.check_output(
            ["tailscale", "status", "--json"], timeout=1, text=True,
            stderr=subprocess.DEVNULL,
        )
        dns_name = json.loads(out).get("Self", {}).get("DNSName") or ""
        short = dns_name.split(".", 1)[0]
        if short:
            return short
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return "127.0.0.1"


def _resolve_bind_addr() -> str:
    """Loopback unless explicitly opened up.

    Sharing across devices (LAN, Tailscale) is an explicit opt-in:
    WEBCOMPANION_BIND=0.0.0.0 (or a specific interface IP). Opening the bind
    is safe for *reading* — see WRITE_TOKEN_HEADER for what guards writes —
    but it is still a deliberate act, so it stays off by default.
    """
    return os.environ.get("WEBCOMPANION_BIND", "127.0.0.1")


# Every request that changes something carries this header. Reads never need
# it. See _Handler._is_owner for the two ways to satisfy the gate.
WRITE_TOKEN_HEADER = "X-WebCompanion-Token"


def _resolve_write_token() -> str:
    """The capability that lets a non-loopback client write.

    Minted fresh per server start and published in ~/.claude/<skill>/server.json
    (mode 0600), so anything running as this user can read it and nothing else
    can. Overridable via WEBCOMPANION_TOKEN when a caller needs a stable value
    across restarts.
    """
    return os.environ.get("WEBCOMPANION_TOKEN") or secrets.token_urlsafe(32)


def _is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _port_holder(port: int) -> str:
    """Best-effort description of whatever already owns the port.

    "Port 3080 is taken" sends you hunting; "taken by node (pid 4821)" does
    not. Never let the diagnostic itself fail the startup path.
    """
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fcp"],
            timeout=2, text=True, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    pid = cmd = ""
    for line in out.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("c"):
            cmd = line[1:]
    if cmd and pid:
        return f" It is held by {cmd} (pid {pid})."
    return ""


def _port_in_use(port: int) -> bool:
    """Is something already listening here?

    bind() alone does not answer this. We set SO_REUSEADDR so a restart is not
    blocked by TIME_WAIT, and on BSD/macOS that also lets a bind to a SPECIFIC
    address succeed while another process holds the same port on the WILDCARD
    address. Two servers then listen on one port and requests are split between
    them at random — which is how the fixed-port guarantee failed the first
    time it was tested, and why an earlier idle-shutdown test hung.

    Connecting is the reliable question: if something answers, the port is
    taken no matter which address it bound.
    """
    for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(0.25)
        try:
            if s.connect_ex((addr, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            s.close()
    return False


def _bind_first_available_port(port_range: range, bind_addr: str) -> tuple[socket.socket, int]:
    """Bind the first free port, or fail loudly.

    A single-port range is the normal case: the whole value of a fixed port is
    that the URL you memorised keeps working, and silently drifting to the next
    one destroys exactly that. Worse, the address you then reach may be someone
    else's service. So when the range is exhausted we say what is in the way
    and stop, rather than landing somewhere unpredictable.
    """
    for port in port_range:
        if port and _port_in_use(port):
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind_addr, port))
            # Report what the socket actually got, not what we asked for. They
            # differ for port 0, which asks the OS to pick a free one — the
            # only sane way for a test to start a server while the real one
            # holds the fixed port.
            return s, s.getsockname()[1]
        except OSError:
            s.close()
            continue
    if len(port_range) == 1:
        port = port_range.start
        raise OSError(
            f"Port {port} is not available.{_port_holder(port)} "
            f"Free it, or set the port explicitly and restart.")
    raise OSError(
        f"No free port in range {port_range.start}-{port_range.stop - 1}."
        f"{_port_holder(port_range.start)}")


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run(skill_name: str, port_range: range, handlers: HandlersProtocol,
        static_dirs: list[Path], shutdown_after_seconds: int | None = None,
        prune_globs: tuple[str, ...] = ()) -> int:
    """Long-lived HTTP server entrypoint. Returns the process exit code."""

    if shutdown_after_seconds is None:
        shutdown_after_seconds = int(os.environ.get(
            f"{skill_name.upper()}_SHUTDOWN_SECONDS", 24 * 60 * 60))

    # The escape hatch for the rare clash, so a fixed port never becomes a
    # reason to edit source. Same {SKILL}_ convention as the timeout above.
    port_override = os.environ.get(f"{skill_name.upper()}_PORT")
    if port_override:
        try:
            fixed = int(port_override)
        except ValueError:
            raise SystemExit(
                f"{skill_name.upper()}_PORT must be a port number, got {port_override!r}")
        port_range = range(fixed, fixed + 1)

    # A Tailscale/public hostname in `url` is only truthful when the socket
    # actually listens beyond loopback; otherwise advertise loopback.
    public_host = (_resolve_public_host()
                   if _resolve_bind_addr() not in ("127.0.0.1", "localhost")
                   else "127.0.0.1")

    write_token = _resolve_write_token()

    state_root = paths.state_root(skill_name)
    workspace_base = paths.workspace_root(skill_name)

    # Workspaces used to be written inside the project directory they were
    # created from, so removing a throwaway git worktree destroyed them. They
    # now live under workspace_base; move any that predate that, BEFORE the
    # sweep, so sweep_state and rehydrate both see the settled paths.
    try:
        mig = cleanup.migrate_workspaces(state_root, workspace_base, skill_name)
        if mig["moved"] or mig["errors"]:
            sys.stdout.write(json.dumps({"type": "migrate", "skill": skill_name, **mig}) + "\n")
            sys.stdout.flush()
    except Exception:
        pass

    # Reconcile state before we rehydrate: prune registry rows whose dirs are
    # already gone, and — only when WEBCOMPANION_RETENTION_DAYS is set to a
    # positive number — expire dormant workspaces. By default nothing expires:
    # a workspace lives until explicitly deleted. Best-effort: a sweep failure
    # must never stop the server from starting.
    try:
        gc = cleanup.sweep_state(
            state_root, cleanup.retention_seconds_from_env(), time.time(),
            extra_globs=prune_globs)
        if any(gc.values()):
            sys.stdout.write(json.dumps({"type": "cleanup", "skill": skill_name, **gc}) + "\n")
            sys.stdout.flush()
    except Exception:
        pass

    registry = Registry(state_root=state_root)
    registry.rehydrate()
    if hasattr(handlers, "set_registry"):
        handlers.set_registry(registry)

    last_activity = [time.time()]
    last_activity_lock = threading.Lock()

    def touch():
        with last_activity_lock:
            last_activity[0] = time.time()

    def seconds_since_activity():
        with last_activity_lock:
            return time.time() - last_activity[0]

    banner = f"{skill_name}-server v1"
    # /health advertises a fingerprint of the code tree this process actually
    # runs, so ensure_server.sh can detect an old-code server surviving a
    # plugin update (its 24h idle clock resets on every request, so it would
    # otherwise pass the static-banner check forever) and restart it.
    code_fp = code_fingerprint()
    server_holder = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            # Log every HTTP request to the same server.log so we can
            # diagnose why a client's call appeared to go nowhere. Cheap,
            # and the only thing we lose is a tiny bit of log noise.
            try:
                line = f"{self.address_string()} - {format % args}"
                print(json.dumps({"type": "http", "line": line}), flush=True)
            except Exception:
                pass

        def _send_text(self, status: int, body: str):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status: int, body_obj: dict):
            data = json.dumps(body_obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _is_cross_site(self) -> bool:
            """Did this write come from a page on somebody else's site?

            _is_owner cannot answer that. Loopback is the owner by
            construction, and JavaScript on ANY website runs from loopback —
            so a page you merely visit could reach the local server as the
            owner. `Content-Type: text/plain` makes a POST a CORS "simple
            request", which the browser sends with no preflight to stop it,
            and the handlers json.loads the body without consulting
            Content-Type. That is a working delete-everything gadget for any
            site you open, so the origin of the request has to be checked.

            `Sec-Fetch-Site` is the reliable signal — the browser sets it and
            script cannot forge it. Non-browser callers (curl, and the Claude
            session driving this server) send neither header and are
            unaffected; requiring one would break them.

            The Origin fallback compares HOST ONLY, deliberately. The owner
            typically browses a TLS-terminating reverse proxy — `https://
            annotate` in front of a plain-http server — so the Origin's scheme
            and port do not match the server's own. Comparing whole origin
            strings would lock the owner out of their own page.
            """
            site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
            if site:
                # "same-origin"/"same-site" are ours; "none" is a typed URL or
                # a bookmark. Only "cross-site" is another site's page.
                return site == "cross-site"
            origin = (self.headers.get("Origin") or "").strip()
            if not origin or origin == "null":
                return False
            from urllib.parse import urlsplit
            try:
                origin_host = urlsplit(origin).hostname
            except ValueError:
                return True                      # unparseable: refuse
            if not origin_host:
                return True
            host_header = (self.headers.get("Host") or "").strip()
            try:
                # urlsplit needs a scheme to find a hostname in a bare
                # authority, and gives us IPv6-bracket handling for free.
                own_host = urlsplit(f"//{host_header}").hostname
            except ValueError:
                own_host = None
            return origin_host.lower() != (own_host or "").lower()

        def _is_owner(self) -> bool:
            """Two ways to be the owner, and no third.

            Loopback is the owner by construction — nobody else can reach it,
            so the Claude session driving this server and the browser on this
            machine both pass without configuration. Everyone else needs the
            capability token, which is handed out only through the owner URL.

            The token is compared with compare_digest so a wrong guess takes
            the same time as any other wrong guess.
            """
            if _is_loopback(self.client_address[0]):
                return True
            supplied = self.headers.get(WRITE_TOKEN_HEADER) or ""
            return bool(supplied) and secrets.compare_digest(supplied, write_token)

        def _content_length(self) -> int | None:
            """Parse Content-Length, rejecting missing/negative/non-integer.

            Returns the byte count, or None if the header is malformed. A
            negative length would make rfile.read(length) read to EOF
            (unbounded); a non-integer would raise inside int(). Callers
            treat None as a 400.
            """
            raw = self.headers.get("Content-Length", "0") or "0"
            try:
                n = int(raw)
            except ValueError:
                return None
            return n if n >= 0 else None

        def _read_body_text(self):
            """Read the request body as UTF-8 text.

            Returns (text, None) on success, or (None, error_message) when the
            Content-Length is missing/negative/non-integer or the body is not
            valid UTF-8 — both of which would otherwise raise and kill the
            worker thread with no response.
            """
            length = self._content_length()
            if length is None:
                return None, "invalid content-length"
            if length == 0:
                return "", None
            try:
                return self.rfile.read(length).decode("utf-8"), None
            except UnicodeDecodeError:
                return None, "body must be utf-8"

        def _match_session(self, prefix: str):
            if not self.path.startswith(prefix):
                return None
            tail = self.path[len(prefix):]
            if "/" not in tail:
                return None
            key, rest = tail.split("/", 1)
            if not SID_RE.match(key):
                return None
            sid = registry.resolve(key)          # slug OR sid -> canonical sid
            if sid is None:
                return None
            return sid, "/" + rest

        def _safe_500(self):
            """Best-effort 500 when a handler raised. If headers were already
            sent the send_response will itself raise — swallow that so we never
            mask the original error with a secondary one, but always avoid
            leaving the worker thread dead with no response written."""
            try:
                self._send_text(500, "internal server error")
            except Exception:
                pass

        def do_GET(self):
            try:
                self._dispatch_get()
            except Exception:
                self.log_message("unhandled GET error: %s", traceback.format_exc())
                self._safe_500()

        def do_POST(self):
            try:
                self._dispatch_post()
            except Exception:
                self.log_message("unhandled POST error: %s", traceback.format_exc())
                self._safe_500()

        def _dispatch_get(self):
            touch()
            if self.path == "/health":
                self._send_text(200, f"{banner} fp={code_fp}")
                return
            # Lets the page decide whether to render its controls at all,
            # instead of showing them and failing the click with a 403.
            #
            # Also carries the two host names, because only the server knows
            # them: the index page has to offer a loopback link for the owner
            # AND a shareable one, and it cannot derive the second from
            # window.location (the owner usually browses on localhost).
            if self.path == "/api/whoami":
                port = server_holder['server'].server_address[1]
                self._send_json(200, {
                    "writable": self._is_owner(),
                    "port": port,
                    "public_host": public_host,
                    "shareable": public_host not in ("127.0.0.1", "localhost"),
                })
                return
            # The index lists every workspace on this machine, across every
            # project. Someone handed a link to one review should reach that
            # review and nothing else, so the directory is owner-only even
            # though the individual pages it lists are not.
            if self.path == "/":
                if not self._is_owner():
                    self._send_text(403, "read-only: the workspace index is not shared")
                    return
                static_serve.serve(self, "sessions.html", static_dirs)
                return
            if self.path.startswith("/static/"):
                static_serve.serve(self, self.path[len("/static/"):], static_dirs)
                return
            matched = self._match_session("/s/")
            if matched is not None:
                sid, rest = matched
                dirs = registry.lookup(sid)
                if rest == "/":
                    handlers.serve_root(self, dirs)
                    return
                if rest == "/poll":
                    handlers.serve_poll(self, dirs)
                    return
                query = rest.lstrip("/")
                dirs_with_sid = {**dirs, "_sid": sid}
                handlers.serve_data(self, dirs_with_sid, query)
                return
            if self.path.startswith("/api/sessions"):
                # Same reasoning as "/" — this is the data behind the index.
                if not self._is_owner():
                    self._send_text(403, "read-only: the workspace index is not shared")
                    return
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                cwd = (qs.get("cwd") or [""])[0]
                scope = (qs.get("scope") or [""])[0]
                if not cwd and scope != "all":
                    self._send_text(400, "missing cwd")   # legacy contract intact
                    return
                rows = list_rows(
                    registry, cwd, scope, now=int(time.time()),
                    count_fn=handlers.comment_count)
                self._send_json(200, rows)
                return
            self._send_text(404, "not found")

        def _dispatch_post(self):
            touch()
            # Every write goes through here, so the gate lives here and not on
            # the seven individual routes — a route added later is guarded by
            # default rather than by whoever remembers. Reads are deliberately
            # ungated: a shared link is meant to be readable.
            if self._is_cross_site():
                self._send_text(403, "refused: cross-site write")
                return
            if not self._is_owner():
                self._send_text(403, "read-only: this link does not carry write access")
                return
            if self.path == "/api/sessions":
                self._handle_create_session()
                return
            if self.path == "/api/open":
                self._handle_open_in_editor(registry)
                return
            if self.path == "/api/sessions/delete":
                raw, err = self._read_body_text()
                if err is not None:
                    self._send_text(400, err)
                    return
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    self._send_text(400, "invalid json")
                    return
                key = payload.get("key")
                if not isinstance(key, str) or not key:
                    self._send_text(400, "missing key")
                    return
                if registry.resolve(key) is None:
                    self._send_text(404, "unknown session")
                    return
                if not delete_session(registry, key):
                    # Known key, tree still there: a permissions problem or a
                    # locked file. The workspace is deliberately still
                    # registered, so saying "unknown session" here would be a
                    # lie the user cannot act on.
                    self._send_text(500, "could not remove the workspace directory")
                    return
                self._send_json(200, {"deleted": key})
                return
            if self.path == "/api/cancel_for_claude_session":
                raw, err = self._read_body_text()
                if err is not None:
                    self._send_text(400, err)
                    return
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    self._send_text(400, "invalid json")
                    return
                csid = payload.get("claude_session_id")
                if not isinstance(csid, str) or not csid:
                    self._send_text(400, "missing claude_session_id")
                    return
                superseded = supersede_for_claude_session(registry, csid)
                self._send_json(200, {"cancelled": superseded})
                return
            matched = self._match_session("/s/")
            if matched is not None:
                sid, rest = matched
                dirs = registry.lookup(sid)
                if rest == "/api/submit":
                    self._handle_submit(sid, dirs)
                    return
                if rest == "/api/finish":
                    if _is_terminal(dirs):
                        self._send_text(409, "session closed")
                        return
                    (Path(dirs["state_dir"]) / "finished").write_text("")
                    self._send_text(200, "ok")
                    return
                if rest == "/api/cancel":
                    if _is_terminal(dirs):
                        self._send_text(409, "session closed")
                        return
                    (Path(dirs["state_dir"]) / "cancelled").write_text(
                        json.dumps({"reason": "user-cancelled", "at": int(time.time())})
                    )
                    self._send_text(200, "ok")
                    return
                if rest == "/api/upload":
                    if _is_terminal(dirs):
                        self._send_text(409, "session closed")
                        return
                    upload_module.handle(self, dirs)
                    return
                if rest == "/api/threads/delete":
                    if _is_terminal(dirs):
                        self._send_text(409, "session closed")
                        return
                    self._handle_thread_delete(sid, dirs)
                    return
            self._send_text(404, "not found")

        def _handle_open_in_editor(self, registry):
            """Open one of a session's own files in the user's editor.

            A page cannot ask the OS to open a file: `file://` is refused from an http
            origin, and a browser would render the file rather than hand it to an editor.
            The custom `jetbrains://` scheme was the way round that, and it carried the
            IDE's *project name* — which the page had to guess from a directory basename,
            guessed wrong whenever the two differed, and failed silently when it did.

            The server has no such problem: it is an ordinary local process, so it can
            simply run the opener. `idea --line N <file>` resolves the project itself from
            the file's own location, which is the whole guessing step deleted rather than
            fixed. Falls back to the platform default when the IDE launcher is absent —
            that loses the line number, never the file.

            POST-gated by `_dispatch_post` (owner-only, same-site), and the path must
            resolve INSIDE the session's own root — otherwise this is an
            open-any-file-on-the-host endpoint wearing a review tool's clothes.
            """
            raw, err = self._read_body_text()
            if err is not None:
                self._send_text(400, err)
                return
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send_text(400, "invalid json")
                return
            key = payload.get("key")
            rel = payload.get("file")
            if not isinstance(key, str) or not key or not isinstance(rel, str) or not rel:
                self._send_text(400, "missing key or file")
                return
            sid = registry.resolve(key)
            if sid is None:
                self._send_text(404, "unknown session")
                return
            root = (registry.lookup(sid) or {}).get("_cwd")
            if not root:
                self._send_text(409, "session has no workspace root")
                return
            try:
                root_real = Path(root).resolve()
                target = (root_real / rel).resolve()
            except OSError as e:
                self._send_text(400, f"path could not be resolved ({e})")
                return
            # Same rule anchors.py applies at render time: `..` and symlinks may not
            # walk out of the workspace. A rendered anchor already passed this check,
            # but the request arrives from the browser, so it is re-checked here rather
            # than assumed — the page is not the only thing that can POST.
            if not target.is_relative_to(root_real) or not target.is_file():
                self._send_text(400, "refused: not a file inside this workspace")
                return
            line = payload.get("line")
            line = line if isinstance(line, int) and line > 0 else None
            launcher = shutil.which("idea")
            if launcher and line:
                cmd = [launcher, "--line", str(line), str(target)]
            elif launcher:
                cmd = [launcher, str(target)]
            elif sys.platform == "darwin":
                cmd = ["open", str(target)]
            else:
                cmd = ["xdg-open", str(target)]
            try:
                # Detached and not waited on: opening an editor is fire-and-forget, and a
                # launcher that blocks must not hold the request open behind it.
                subprocess.Popen(cmd, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self._send_text(500, f"could not launch the editor ({e})")
                return
            self._send_json(200, {"opened": str(target), "line": line, "via": cmd[0]})

        def _handle_create_session(self):
            raw, err = self._read_body_text()
            if err is not None:
                self._send_text(400, err)
                return
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send_text(400, "invalid json")
                return
            cwd_str = payload.get("cwd")
            if not isinstance(cwd_str, str) or not cwd_str:
                self._send_text(400, "missing cwd")
                return
            cwd = Path(cwd_str)
            if not cwd.is_absolute() or not cwd.is_dir():
                self._send_text(400, "cwd must be an absolute existing directory")
                return
            def _mkdirs(sid):
                # Central home, not `cwd`: see paths.workspace_root. `cwd`
                # still reaches the session as `_cwd`, the project root.
                return paths.make_session_dirs(workspace_base, sid)

            extra_holder = {}

            def _on_create(dirs):
                extra_holder['extra'] = handlers.create_session_extra(payload, dirs) or {}

            try:
                result, _created = create_or_attach(
                    registry, skill_name, payload, cwd, _mkdirs, on_create=_on_create,
                    supersede=getattr(handlers, "supersede_by_claude_session", False))
            except Exception as e:
                self._send_text(500, f"session-init failed: {e}")
                return
            sid = result["sid"]; slug = result["slug"]; dirs = result["dirs"]
            extra = extra_holder.get('extra', {})
            port = server_holder['server'].server_address[1]
            self._send_json(200, {
                "sid": sid,
                "slug": slug,
                "created": _created,
                # The shareable, READ-ONLY link. Handing this to a colleague
                # lets them read and comment on nothing.
                "url": f"http://{public_host}:{port}/s/{slug}/",
                # Always-secure-context loopback URL. Browser features that need
                # a secure context (e.g. voice dictation) work here but not over
                # the public_host URL when it's plain-HTTP.
                "localhost_url": f"http://localhost:{port}/s/{slug}/",
                # The same page with write access, for the owner on another
                # device. The token rides in the URL fragment, which browsers
                # never put on the wire and never write to server logs; the
                # page moves it into sessionStorage and strips it from the
                # address bar on arrival. Do not paste this one into chat.
                "owner_url": f"http://{public_host}:{port}/s/{slug}/#k={write_token}",
                "response_dir": str(dirs["response_dir"]),
                "annotations_dir": str(dirs["annotations_dir"]),
                "state_dir": str(dirs["state_dir"]),
                "events_dir": str(dirs["events_dir"]),
                "consumed_dir": str(dirs["consumed_dir"]),
                **extra,
            })

        def _handle_submit(self, sid, dirs):
            raw, err = self._read_body_text()
            if err is not None:
                self._send_text(400, err)
                return
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                self._send_text(400, "invalid json")
                return
            if not isinstance(payload, dict):
                self._send_text(400, "payload must be an object")
                return
            handlers.handle_submit(self, dirs, payload)
            registry.note_change(sid)

        def _handle_thread_delete(self, sid, dirs):
            if not hasattr(handlers, "handle_thread_delete"):
                self._send_text(404, "delete not supported by this skill")
                return
            raw, err = self._read_body_text()
            if err is not None:
                self._send_text(400, err)
                return
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                self._send_text(400, "invalid json")
                return
            if not isinstance(payload, dict):
                self._send_text(400, "payload must be an object")
                return
            handlers.handle_thread_delete(self, dirs, payload)
            registry.note_change(sid)

    bind_addr = _resolve_bind_addr()
    sock, port = _bind_first_available_port(port_range, bind_addr)
    sock.listen()

    server = _ThreadedHTTPServer((bind_addr, port), _Handler, bind_and_activate=False)
    server.socket = sock
    server.server_address = (bind_addr, port)
    server_holder['server'] = server

    info = {"type": "server-started", "skill": skill_name, "port": port,
            "url": f"http://{public_host}:{port}",
            "write_token": write_token,
            "plugin_root": os.environ.get("PLUGIN_ROOT", "")}
    home_info_dir = Path(os.path.expanduser(f"~/.claude/{skill_name}"))
    home_info_dir.mkdir(parents=True, exist_ok=True)
    info_path = home_info_dir / "server.json"
    # Atomic, and 0600 for the whole life of the bytes: this file is a
    # credential (it carries write_token), so a world-readable moment would be
    # a real window on a shared machine — and a torn read is a real window too.
    # The IDE plugin re-reads this file on every failed discovery poll and
    # regex-matches "url"; a reader landing inside a plain write() got a
    # truncated file, missed the match, and silently fell back to a hardcoded
    # port. write_text_atomic writes through tempfile.mkstemp (created 0600)
    # and os.replace()s it into place, so readers see the old file or the new
    # one and never a half-written one.
    write_text_atomic(info_path, json.dumps(info))
    info_path.chmod(0o600)
    # stdout goes to the server log, which is not 0600 — publish everything
    # except the credential there.
    sys.stdout.write(json.dumps({k: v for k, v in info.items()
                                 if k != "write_token"}) + "\n")
    sys.stdout.flush()

    stop_event = threading.Event()

    def _watch_idle():
        while not stop_event.wait(1.0):
            if seconds_since_activity() >= shutdown_after_seconds:
                # HTTP silence alone isn't idleness: an armed watcher beats
                # via the filesystem, not via requests. Shutting down under
                # it strands server.json on a dead port with no way for the
                # IDE to restart us.
                if any((_watcher_age(dirs) or REAP_AFTER + 1) <= REAP_AFTER
                       for _sid, dirs in registry.items()
                       if not _is_terminal(dirs)):
                    touch()
                    continue
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

    threading.Thread(target=_watch_idle, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
    return 0
