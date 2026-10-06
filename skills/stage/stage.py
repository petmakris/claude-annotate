"""The stage: named live views on one webcompanion page per project.

    python3 stage.py show <name> <source> [--title T] [--background] [--cwd DIR] [--slug S]
    python3 stage.py hide <name> [--cwd DIR] [--slug S]
    python3 stage.py link [--cwd DIR] [--slug S]
    python3 stage.py watch --sid SID [--cwd DIR]

<source>: a project file (path[#fragment]), http(s)://..., session:<kind>/<slug>,
code:<path>:<a>-<b>[ highlight x[-y]], change:<path>[ since <rev>] (what changed, read from git),
or diagram:- / table:- with the body on stdin.
Prints the stage URL. Exit 2: the name or source was refused. Exit 3: no daemon, or the
daemon refused a request.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from skills._shared import webcompanion_client as wc  # noqa: E402
from skills.stage import model  # noqa: E402

KIND = "stage"
LAYOUT = "__layout__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"
DAEMON_ERRORS = (wc.DaemonError,)
VIEW_EXTRAS = ("answer", "kind", "caption", "pinned", "scene")  # what a caller may add to a view's body
PRIVATE_SLUG_PREFIX = "talk-"
PAGE_TYPES = ("file", "url", "session")


class ViewTaken(ValueError):
    """The view name is already on the stage, put there by another writer."""


def _live_rows(cwd: str, kind: str = KIND) -> list:
    rows = wc.list_sessions(cwd, kind)
    rows = rows if isinstance(rows, list) else rows.get("sessions", [])
    return [r for r in rows if r.get("state", "live") == "live"]


def ensure_stage(cwd: str, *, slug: str | None = None, title: str | None = None) -> dict:
    """The newest live stage for `cwd` that no talk call owns (or the one named `slug`, a slug or a
    sid), created if there is none. A named stage that was ended, lives in another folder, or that the
    daemon would store under another slug raises wc.SlugMismatch."""
    rows = [r for r in _live_rows(cwd) if r.get("kind", KIND) == KIND]
    if slug:
        want = wc.slugify(slug)
        row = next((r for r in rows if r.get("sid") == slug or r.get("slug") == want), None)
    else:
        rows = [r for r in rows if not str(r.get("slug", "")).startswith(PRIVATE_SLUG_PREFIX)]
        # Newest first: a sid starts with its creation time.
        row = max(rows, key=lambda r: r.get("sid", ""), default=None)
    if row is None:
        row = wc.create_or_attach(KIND, cwd, title=title or "Stage · %s" % Path(cwd).name, slug=slug)
    # Re-registered every time: the plugin's install path moves on every update.
    wc.register_assets(row["sid"], str(STATIC_DIR), ENTRY, kind=KIND)
    return row


def _layout(items: dict) -> dict:
    body = (items.get(LAYOUT) or {}).get("body") or {}
    order = [n for n in body.get("order", []) if isinstance(n, str)]
    return {"order": order, "front": body.get("front")}


def _complete_source(cwd: str, sid: str, source: dict) -> tuple:
    """Fills in what the page needs (mount, sid) and returns (source, rev)."""
    source = dict(source)
    if source["type"] == "file":
        path = Path(cwd).resolve() / source["path"]
        folder = path.parent
        mount = model.mount_name(folder, Path(cwd))
        wc.register_mount(sid, mount, str(folder), kind=KIND)
        source.update(mount=mount, file=path.name, missing=not path.is_file(),
                      display=model.file_display(path.name))
        return source, model.dir_rev(folder)
    if source["type"] == "session":
        source["sid"] = _session_sid(cwd, source["kind"], source["slug"])
    return source, 0


def _session_sid(cwd: str, kind: str, key: str) -> str:
    """The sid of the live `kind` session named `key` (a slug or a sid): in `cwd` first, else in any
    folder when exactly one matches."""
    match = next((r for r in _live_rows(cwd, kind) if key in (r.get("slug"), r.get("sid"))), None)
    if match is not None:
        return match["sid"]
    try:
        rows = [r for r in wc.all_sessions(kind) if r.get("state", "live") == "live"]
    except wc.DaemonHTTPError:
        rows = []
    found = [r for r in rows if key in (r.get("slug"), r.get("sid"))]
    if len(found) == 1:
        return found[0]["sid"]
    if found:
        raise model.SourceError("%d live %s sessions are named %s: %s; pass its sid" % (
            len(found), kind, key, ", ".join("%s in %s" % (r["sid"], r.get("cwd")) for r in found)))
    near = ", ".join("%s in %s" % (r.get("slug"), r.get("cwd")) for r in rows[:8])
    raise model.SourceError("no live %s session named %s in %s%s" % (
        kind, key, cwd, "; live ones: " + near if near else ""))


def show(cwd: str, name: str, source: dict, *, title: str | None = None,
         background: bool = False, slug: str | None = None, extra: dict | None = None,
         owner: str | None = None) -> dict:
    """Put a view on the stage. `extra` adds metadata to the view's body (answer, kind, caption,
    pinned, scene); any other key is ignored. `owner` names the writer: a view put there by another writer
    is never replaced, it raises ViewTaken. On a talk call's stage a page (a file, an address or a
    session) opens behind what is in front and never takes the front: the result says so with `behind`."""
    if not model.NAME_RE.match(name):
        raise ValueError("view name must match %s: %r" % (model.NAME_RE.pattern, name))
    row = ensure_stage(cwd, slug=slug)
    sid = row["sid"]
    source, rev = _complete_source(cwd, sid, source)
    items = wc.get_items(sid, kind=KIND)
    old = (items.get("view:" + name) or {}).get("body") or {}
    if old and old.get("owner") != owner:
        raise ViewTaken("view %s is on stage %s already, put there by %s; pick another name"
                        % (name, row.get("slug") or sid, old.get("owner") or "hand (stage.py)"))
    view = {"name": name, "title": title or old.get("title") or name, "source": source, "rev": rev}
    view.update({k: v for k, v in (extra or {}).items() if k in VIEW_EXTRAS})
    if owner:
        view["owner"] = owner
    layout = _layout(items)
    if name not in layout["order"]:
        layout["order"].append(name)
    behind = source["type"] in PAGE_TYPES and str(row.get("slug", "")).startswith(PRIVATE_SLUG_PREFIX)
    if not behind and (not background or layout["front"] not in layout["order"]):
        layout["front"] = name
    wc.put_items(sid, {"view:" + name: view, LAYOUT: layout}, kind=KIND)
    if source["type"] == "file":
        start_watch(cwd, sid)
    return {"sid": sid, "url": row["url"], "view": view, "behind": behind}


def hide(cwd: str, name: str, *, slug: str | None = None) -> None:
    sid = ensure_stage(cwd, slug=slug)["sid"]
    layout = _layout(wc.get_items(sid, kind=KIND))
    wc.delete_item(sid, "view:" + name, kind=KIND)
    layout["order"] = [n for n in layout["order"] if n != name]
    if layout["front"] == name:
        layout["front"] = layout["order"][-1] if layout["order"] else None
    wc.put_items(sid, {LAYOUT: layout}, kind=KIND)


def link(cwd: str, *, slug: str | None = None) -> str:
    return ensure_stage(cwd, slug=slug)["url"]


def daemon_status() -> str | None:
    try:
        wc.list_sessions("/", KIND)
    except DAEMON_ERRORS as e:
        return str(e)
    return None


def _pid_file(sid: str) -> Path:
    d = Path(tempfile.gettempdir()) / "claude-stage"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%s.pid" % sid)


def watch_running(sid: str) -> bool:
    try:
        pid = int(_pid_file(sid).read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def start_watch(cwd: str, sid: str) -> None:
    """One detached `watch` per stage; a second call while it runs does nothing."""
    if watch_running(sid):
        return
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watch", "--sid", sid, "--cwd", cwd],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def tick(cwd: str, sid: str) -> list:
    """Re-measure every file view; write the ones whose folder or presence changed."""
    changed = {}
    for anchor, item in wc.get_items(sid, kind=KIND).items():
        view = (item or {}).get("body") or {}
        source = view.get("source") or {}
        if not anchor.startswith("view:") or source.get("type") != "file":
            continue
        path = Path(cwd).resolve() / source["path"]
        rev, missing = model.dir_rev(path.parent), not path.is_file()
        if rev != view.get("rev") or missing != source.get("missing"):
            changed[anchor] = dict(view, rev=rev, source=dict(source, missing=missing))
    if changed:
        wc.put_items(sid, changed, kind=KIND)
    return [a[len("view:"):] for a in changed]


def watch(cwd: str, sid: str, *, interval: float = 0.5, alive_every: float = 30.0,
          sleep=time.sleep, clock=time.monotonic) -> int:
    """Tick until the stage session stops being live. Rides out a daemon restart."""
    pid_file = _pid_file(sid)
    pid_file.write_text(str(os.getpid()))
    checked = clock()
    try:
        while True:
            sleep(interval)
            if clock() - checked >= alive_every:
                checked = clock()
                try:
                    if not any(r.get("sid") == sid for r in _live_rows(cwd)):
                        return 0
                except DAEMON_ERRORS:
                    continue
            try:
                tick(cwd, sid)
            except DAEMON_ERRORS + (RuntimeError,):
                continue
    finally:
        try:
            if pid_file.read_text().strip() == str(os.getpid()):
                pid_file.unlink()
        except OSError:
            pass


def repo_root(start: Path) -> str:
    """The git checkout root holding `start`, or `start` itself outside one. talk.py uses it too."""
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return str(start.resolve())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stage.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("show", "hide", "link", "watch"):
        p = sub.add_parser(cmd)
        p.add_argument("--cwd", help="the project folder (default: this git checkout's root)")
        p.add_argument("--slug", help="a specific stage (slug or sid)")
        if cmd in ("show", "hide"):
            p.add_argument("name")
        if cmd == "show":
            p.add_argument("source")
            p.add_argument("--title")
            p.add_argument("--background", action="store_true")
        if cmd == "watch":
            p.add_argument("--sid", required=True)
    args = ap.parse_args(argv)
    cwd = str(Path(args.cwd).expanduser().resolve()) if args.cwd else repo_root(Path.cwd())
    try:
        if args.cmd == "show":
            stdin = sys.stdin.read() if args.source in ("diagram:-", "table:-") else None
            source = model.parse_source(args.source, Path(cwd), stdin)
            res = show(cwd, args.name, source, title=args.title, background=args.background, slug=args.slug)
            print(res["url"])
            if res["behind"]:
                print("stage: a call is on, so this page opened as a background tab; say so, and the user "
                      "taps its tab to look", file=sys.stderr)
        elif args.cmd == "hide":
            hide(cwd, args.name, slug=args.slug)
        elif args.cmd == "link":
            print(link(cwd, slug=args.slug))
        else:
            return watch(cwd, args.sid)
    except json.JSONDecodeError as e:  # a ValueError too, but the daemon's side, not the caller's
        print("stage: unreadable webcompanion config or reply: %s" % e, file=sys.stderr)
        return 3
    except ValueError as e:  # model.SourceError is a ValueError
        print("stage: %s" % e, file=sys.stderr)
        return 2
    except DAEMON_ERRORS + (RuntimeError,) as e:  # RuntimeError: the daemon refused a request
        print("stage: %s" % e, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
