"""Startup garbage-collection for web_companion state.

Session state accumulated without bound: every push created a per-session
directory under ``<cwd>/.claude/<skill>/<sid>/`` plus a
``pending-<claude_session>.json`` registry under ``~/.claude/<skill>/``, and
nothing ever removed either — so both grew by one entry per session forever.

The shared HTTP server is the single owner of this state and re-launches after
each idle shutdown (see ``server.run``'s idle watchdog), which makes server
startup the natural, once-per-lifecycle GC point. ``sweep_state`` runs there,
before ``Registry.rehydrate``. By default the retention window is infinite —
workspaces live until explicitly deleted, and the sweep only reconciles
registry rows whose dirs are already gone; setting
``WEBCOMPANION_RETENTION_DAYS`` to a positive number opts back into deleting
anything dormant past that window.

The clock is injected (``now``) so the sweep is deterministic under test, and
every filesystem step is best-effort: an error on one entry is counted and
skipped, never raised, so a GC failure can't stop the server from starting.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from skills._shared.web_companion import paths
from skills._shared.web_companion.atomic import write_text_atomic

# Shape of server-minted sids (sessions.Registry.make_sid). The stray sweep
# only ever deletes directories matching this, so user files that happen to
# live next to session dirs are never candidates.
_SID_DIR_RE = re.compile(r"^\d{6}-\d{6}-[0-9a-f]{16}$")

# Files whose mtime signals recent activity for a session. The server never
# rewrites the <sid> base dir after creation, so its mtime alone would read
# "old" even for a session being actively viewed right now — the watcher
# heartbeat (rewritten ~every 1s while armed), the event/consumed queues, and
# the terminal markers are what actually track liveness.
_LIVENESS_CHILDREN = (
    "watcher_heartbeat",
    "events",
    "consumed",
    "finished",
    "cancelled",
)


def retention_seconds_from_env() -> float:
    """The retention window in seconds, from WEBCOMPANION_RETENTION_DAYS.

    Workspaces live until explicitly deleted: unset, zero, negative, or
    unparseable all disable expiry (``inf``) — the failure mode of a bad value
    must be "keep everything", never "delete everything". A positive integer
    opts back into the old N-day sweep.
    """
    raw = os.environ.get("WEBCOMPANION_RETENTION_DAYS", "")
    try:
        days = int(raw)
    except ValueError:
        return float("inf")
    return days * 86400 if days > 0 else float("inf")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _last_activity(base: Path, state_dir: Path) -> float | None:
    """Freshest mtime across a session's liveness signals, or None if none stat.

    Taking the max (not the base dir's own mtime) keeps a long-lived session
    that is still being polled from looking dormant just because its directory
    was created long ago.
    """
    candidates = [_mtime(base), _mtime(state_dir)]
    for name in _LIVENESS_CHILDREN:
        candidates.append(_mtime(state_dir / name))
    live = [m for m in candidates if m is not None]
    return max(live) if live else None


def sweep_state(
    state_root: Path,
    retention_seconds: float,
    now: float,
    extra_globs: tuple[str, ...] = (),
) -> dict[str, int]:
    """Delete dormant session dirs, stale pending files, and ancillary junk.

    - Session dirs are enumerated from ``sessions.json`` (the only on-disk index
      of the per-project ``<sid>`` directories). A session is removed when its
      last activity is older than ``retention_seconds``; entries whose dir is
      already gone are pruned from ``sessions.json`` too.
    - ``pending-*.json`` registries and any ``extra_globs`` matches are removed
      purely by their own mtime.

    Returns a summary of what was removed. Never raises.
    """
    state_root = Path(state_root)
    summary = {"sessions_removed": 0, "pending_removed": 0, "files_removed": 0, "errors": 0}
    if not state_root.is_dir():
        return summary

    _sweep_sessions(state_root, retention_seconds, now, summary)
    _sweep_by_mtime(state_root.glob("pending-*.json"), retention_seconds, now,
                    summary, "pending_removed")
    for pattern in extra_globs:
        _sweep_by_mtime(state_root.glob(pattern), retention_seconds, now,
                        summary, "files_removed")
    return summary


def _sweep_sessions(state_root: Path, retention_seconds: float, now: float,
                    summary: dict[str, int]) -> None:
    sessions_file = state_root / "sessions.json"
    try:
        snapshot = json.loads(sessions_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(snapshot, dict):
        return

    kept: dict = {}
    changed = False
    for sid, dirs in snapshot.items():
        state_dir_str = dirs.get("state_dir") if isinstance(dirs, dict) else None
        if not state_dir_str:
            kept[sid] = dirs  # unrecognizable entry — leave it untouched
            continue
        state_dir = Path(state_dir_str)
        base = state_dir.parent  # <cwd>/.claude/<skill>/<sid>
        if not base.exists():
            changed = True  # dir already gone: drop the dangling registry row
            continue
        activity = _last_activity(base, state_dir)
        if activity is not None and (now - activity) <= retention_seconds:
            kept[sid] = dirs  # still within the retention window
            continue
        if activity is None:
            kept[sid] = dirs  # couldn't stat anything — don't guess, keep it
            continue
        try:
            shutil.rmtree(base)
            summary["sessions_removed"] += 1
            changed = True
        except OSError:
            summary["errors"] += 1
            kept[sid] = dirs

    if changed:
        try:
            write_text_atomic(sessions_file, json.dumps(kept, indent=2))
        except OSError:
            summary["errors"] += 1

    _prune_meta(state_root, kept, summary)
    _sweep_strays(snapshot, kept, retention_seconds, now, summary)


def _prune_meta(state_root: Path, kept: dict, summary: dict[str, int]) -> None:
    """Drop sessions_meta.json rows for sids no longer in sessions.json.

    Stale rows kept their slugs reserved, so a recreated session with the
    same title got a needless -2 bump until the next persist() happened by.
    """
    meta_file = state_root / "sessions_meta.json"
    try:
        meta = json.loads(meta_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(meta, dict):
        return
    pruned = {sid: m for sid, m in meta.items() if sid in kept}
    if pruned != meta:
        try:
            write_text_atomic(meta_file, json.dumps(pruned, indent=2))
        except OSError:
            summary["errors"] += 1


def _sweep_strays(snapshot: dict, kept: dict, retention_seconds: float,
                  now: float, summary: dict[str, int]) -> None:
    """Remove dormant sid-shaped dirs that no registry row points at.

    A session dir becomes invisible to the registry-driven sweep when its
    create failed after mkdirs, or when rehydrate() dropped its row while
    the dir survived. Walk the parent dirs the registry DOES know about and
    reap unregistered siblings past retention.
    """
    parents = set()
    for dirs in snapshot.values():
        state_dir_str = dirs.get("state_dir") if isinstance(dirs, dict) else None
        if state_dir_str:
            # <cwd>/.claude/<skill>/<sid>/state -> <cwd>/.claude/<skill>
            parents.add(Path(state_dir_str).parent.parent)
    registered = set(snapshot)
    for parent in parents:
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in registered or not _SID_DIR_RE.match(child.name):
                continue
            if not child.is_dir():
                continue
            activity = _last_activity(child, child / "state")
            if activity is None or (now - activity) <= retention_seconds:
                continue
            try:
                shutil.rmtree(child)
                summary["sessions_removed"] += 1
            except OSError:
                summary["errors"] += 1


def _sweep_by_mtime(paths, retention_seconds: float, now: float,
                    summary: dict[str, int], counter: str) -> None:
    for p in paths:
        if not p.is_file():
            continue
        mtime = _mtime(p)
        if mtime is None or (now - mtime) <= retention_seconds:
            continue
        try:
            p.unlink()
            summary[counter] += 1
        except OSError:
            summary["errors"] += 1


def migrate_workspaces(state_root: Path, workspace_root: Path,
                       skill_name: str) -> dict[str, int]:
    """Move every registered workspace still living inside a project directory
    into `workspace_root`, and rewrite sessions.json to match.

    Workspaces used to be created under ``<cwd>/.claude/<skill>/<sid>/`` — see
    ``paths`` for why that was wrong. This runs at server startup, before
    ``sweep_state`` and ``Registry.rehydrate``, so by the time anything reads
    the registry every row already points at the central home.

    Per row:

    - already under `workspace_root` -> backfill its ``workspace.json`` marker
      if missing, and count it as ``already_home``;
    - directory gone -> left alone, so ``sweep_state`` prunes the row as usual;
    - destination already exists -> refused and counted as an error, never
      clobbered: two trees claiming one sid means something is wrong that a
      silent overwrite would destroy the evidence of;
    - otherwise -> moved, every path value under the old base re-rooted onto
      the new one, and a marker written from the row's ``_cwd``.

    ``_cwd`` is a parent of the old base, never under it, so the re-rooting
    leaves it untouched by construction — the project root must keep naming
    the project even after the content stops living there.

    Idempotent, and never raises: a migration failure must not stop the server
    from starting, and the un-migrated row keeps working where it is.
    """
    state_root, workspace_root = Path(state_root), Path(workspace_root)
    summary = {"moved": 0, "already_home": 0, "errors": 0}
    sessions_file = state_root / "sessions.json"
    try:
        snapshot = json.loads(sessions_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return summary
    if not isinstance(snapshot, dict):
        return summary

    updated: dict = {}
    changed = False
    for sid, dirs in snapshot.items():
        state_dir_str = dirs.get("state_dir") if isinstance(dirs, dict) else None
        if not state_dir_str:
            updated[sid] = dirs          # unrecognizable entry — leave it alone
            continue
        base = Path(state_dir_str).parent
        if base.parent == workspace_root:
            summary["already_home"] += 1
            if not (base / paths.MARKER_FILE).exists():
                paths.write_marker(base, sid, skill_name, dirs.get("_cwd", ""))
            updated[sid] = dirs
            continue
        if not base.is_dir():
            updated[sid] = dirs          # gone: sweep_state prunes it next
            continue
        dest = workspace_root / sid
        if dest.exists():
            summary["errors"] += 1
            updated[sid] = dirs
            continue
        try:
            workspace_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(base), str(dest))
        except (OSError, shutil.Error):
            summary["errors"] += 1
            updated[sid] = dirs
            continue
        updated[sid] = _reroot(dirs, base, dest)
        paths.write_marker(dest, sid, skill_name, dirs.get("_cwd", ""))
        _rmdir_if_empty(base.parent)     # the vacated <cwd>/.claude/<skill>
        summary["moved"] += 1
        changed = True

    if changed:
        try:
            write_text_atomic(sessions_file, json.dumps(updated, indent=2))
        except OSError:
            summary["errors"] += 1
    return summary


def _reroot(dirs: dict, old_base: Path, new_base: Path) -> dict:
    """Rewrite every path value under `old_base` onto `new_base`, verbatim for
    the rest. `_cwd` sits above `old_base`, so it passes through untouched."""
    out = {}
    for key, value in dirs.items():
        try:
            p = Path(value)
        except TypeError:
            out[key] = value
            continue
        if p == old_base or p.is_relative_to(old_base):
            out[key] = str(new_base / p.relative_to(old_base))
        else:
            out[key] = value
    return out


def _rmdir_if_empty(path: Path) -> None:
    """Remove a now-empty directory the migration emptied. rmdir refuses a
    non-empty directory, so a project that keeps other state there is safe."""
    try:
        path.rmdir()
    except OSError:
        pass
