"""What a stage view's source is, and how its revision is measured. No I/O beyond the local disk."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_CODE_LINES = 60
# Walked twice a second, so the revision never descends into these, and stops counting
# after MAX_FILES: a deck folder is small; a repository root is not.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".idea"}
MAX_FILES = 5000

_CODE_RE = re.compile(
    r"(?P<path>.+?):(?P<a>\d+)\s*-\s*(?P<b>\d+)"
    r"(?:\s+highlight\s+(?P<ha>\d+)(?:\s*-\s*(?P<hb>\d+))?)?\s*$")
_SESSION_RE = re.compile(r"^session:(?P<kind>[a-z][a-z0-9_-]{0,63})/(?P<slug>[^/\s]+)$")


class SourceError(ValueError):
    """The source cannot be shown as asked; the message says why, for a person."""


def _inside(cwd: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    p = (p if p.is_absolute() else cwd / p).resolve()
    root = cwd.resolve()
    if p != root and root not in p.parents:
        raise SourceError(f"{raw} is outside the project {root}")
    return p


def code_source(cwd: Path, spec: str) -> dict:
    m = _CODE_RE.match(spec.strip())
    if not m:
        raise SourceError(f"expected <path>:<first>-<last>: {spec}")
    rel = m["path"].strip()
    path = _inside(cwd, rel)
    if not path.is_file():
        raise SourceError(f"no such file in the project: {rel}")
    a, b = int(m["a"]), int(m["b"])
    if a < 1 or b < a:
        raise SourceError(f"bad line range {a}-{b} in {rel}")
    lines = path.read_text(errors="replace").splitlines()
    if a > len(lines):
        raise SourceError(f"{rel} has only {len(lines)} lines")
    truncated = b - a + 1 > MAX_CODE_LINES
    if truncated:
        b = a + MAX_CODE_LINES - 1
    ha = int(m["ha"]) if m["ha"] else None
    hb = int(m["hb"]) if m["hb"] else ha
    return {"type": "inline", "format": "code", "path": path.relative_to(cwd.resolve()).as_posix(),
            "start": a, "lines": lines[a - 1:b], "highlight": [ha, hb] if ha else None,
            "lang": path.suffix.lstrip(".") or "text", "truncated": truncated}


def parse_source(raw: str, cwd: Path, stdin_text: str | None = None) -> dict:
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return {"type": "url", "url": raw}
    if raw.startswith("session:"):
        m = _SESSION_RE.match(raw)
        if not m:
            raise SourceError(f"expected session:<kind>/<slug>: {raw}")
        return {"type": "session", "kind": m["kind"], "slug": m["slug"]}
    if raw in ("diagram:-", "table:-"):
        body = (stdin_text or "").strip()
        if not body:
            raise SourceError(f"{raw} reads its body from stdin, and stdin was empty")
        return {"type": "inline", "format": raw.split(":")[0], "body": body}
    if raw.startswith("code:"):
        return code_source(cwd, raw[len("code:"):])
    target, _, fragment = raw.partition("#")
    path = _inside(cwd, target)
    if not path.parent.is_dir():
        raise SourceError(f"no such folder in the project: {path.parent}")
    return {"type": "file", "path": path.relative_to(cwd.resolve()).as_posix(), "fragment": fragment or None}


def mount_name(directory: Path, cwd: Path) -> str:
    rel = directory.resolve().relative_to(cwd.resolve()).as_posix()
    stem = "root" if rel == "." else (re.sub(r"[^a-z0-9_-]+", "-", rel.lower()).strip("-_") or "dir")
    return "%s-%s" % (stem[:50], hashlib.sha1(rel.encode()).hexdigest()[:6])


def dir_rev(directory: Path) -> int:
    """The newest mtime (ns) of the folder, its subfolders and its files. A deleted or
    renamed-over file moves its folder's mtime, so an atomic save is seen too."""
    newest, seen = 0, 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        try:
            newest = max(newest, os.stat(root).st_mtime_ns)
        except OSError:
            continue
        for f in files:
            try:
                newest = max(newest, os.stat(os.path.join(root, f)).st_mtime_ns)
            except OSError:
                continue
            seen += 1
            if seen >= MAX_FILES:
                return newest
    return newest
