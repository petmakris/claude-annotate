"""What a stage view's source is, and how its revision is measured. No I/O beyond the local disk."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from skills._shared.visuals import flowchart, sequence

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_CODE_LINES = 60
MAX_CHANGE_LINES = 80  # a change card shows at most this many diff lines, over all its hunks
GIT_TIMEOUT_S = 3
# Walked twice a second, so the revision never descends into these, and stops counting
# after MAX_FILES: a deck folder is small; a repository root is not.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".idea"}
MAX_FILES = 5000

_CODE_RE = re.compile(
    r"(?P<path>.+?):(?P<a>\d+)\s*-\s*(?P<b>\d+)"
    r"(?:\s+highlight\s+(?P<ha>\d+)(?:\s*-\s*(?P<hb>\d+))?)?\s*$")
_CHANGE_RE = re.compile(r"(?P<path>.+?)(?:\s+since\s+(?P<rev>\S+))?\s*$")
_REV_RE = re.compile(r"^[\w./~^-]{1,64}$")
_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")
_SESSION_RE = re.compile(r"^session:(?P<kind>[a-z][a-z0-9_-]{0,63})/(?P<slug>[^/\s]+)$")


# A browser shows these in a frame. Any other file in a frame is downloaded instead, so the stage
# reads it and shows it itself: Markdown as a document, the rest as text.
PAGE_SUFFIXES = {".html", ".htm", ".xhtml", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                 ".avif", ".bmp", ".ico", ".mp4", ".webm", ".mp3", ".wav", ".ogg"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}


def file_display(name: str) -> str:
    """How the stage shows a file: "page" in a frame, "markdown" rendered, or "text"."""
    suffix = Path(name).suffix.lower()
    if suffix in PAGE_SUFFIXES:
        return "page"
    return "markdown" if suffix in MARKDOWN_SUFFIXES else "text"


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
    b = min(b, len(lines))
    highlight = None
    if m["ha"]:
        ha, hb = int(m["ha"]), int(m["hb"] or m["ha"])
        ha, hb = min(ha, hb), max(ha, hb)
        if hb < a or ha > b:
            raise SourceError(f"highlight {ha}-{hb} is outside lines {a}-{b} of {rel}")
        highlight = [max(ha, a), min(hb, b)]
    return {"type": "inline", "format": "code", "path": path.relative_to(cwd.resolve()).as_posix(),
            "start": a, "lines": lines[a - 1:b], "highlight": highlight,
            "lang": path.suffix.lstrip(".") or "text", "truncated": truncated}


def _git(cwd: Path, *args: str, ok: tuple = (0,)) -> str:
    """A read-only git command in `cwd`: its output, or a SourceError that says what went wrong.
    Pathspecs are literal, so a file name is never read as git pathspec magic."""
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1", "GIT_PAGER": "cat", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              errors="replace", timeout=GIT_TIMEOUT_S, env=env)
    except FileNotFoundError:
        raise SourceError("git is not installed") from None
    except subprocess.TimeoutExpired:
        raise SourceError(f"git took longer than {GIT_TIMEOUT_S} s") from None
    if done.returncode not in ok:
        first = (done.stderr.strip().splitlines() or ["git failed"])[0]
        raise SourceError(first.removeprefix("fatal: ").removeprefix("error: "))
    return done.stdout


def parse_diff(text: str) -> tuple[list, int, int, int]:
    """A unified diff as (hunks, added, removed, more): every hunk is {header, start_old, start_new,
    lines:[{op, old, new, text}]}; at most MAX_CHANGE_LINES lines are kept over all hunks, and
    `more` counts the ones left out. added and removed count the whole diff."""
    hunks, added, removed, shown, more = [], 0, 0, 0, 0
    old = new = 0
    hunk = None
    for line in text.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            old, new = int(m["old"]), int(m["new"])
            hunk = {"header": line, "start_old": old, "start_new": new, "lines": []}
            if shown < MAX_CHANGE_LINES:
                hunks.append(hunk)
            continue
        if hunk is None or not line or line[0] not in "+- ":
            continue  # the file header, or "\\ No newline at end of file"
        op, body = line[0], line[1:]
        row = {"op": op, "old": None if op == "+" else old, "new": None if op == "-" else new, "text": body}
        old += op != "+"
        new += op != "-"
        added += op == "+"
        removed += op == "-"
        if shown < MAX_CHANGE_LINES:
            hunk["lines"].append(row)
            shown += 1
        else:
            more += 1
    return [h for h in hunks if h["lines"]], added, removed, more


def change_source(cwd: Path, spec: str) -> dict:
    """What changed in a file, read from git: the working tree against HEAD, or against `since <rev>`.
    A file git does not track yet shows as all new."""
    m = _CHANGE_RE.match(spec.strip())
    if not m or not m["path"].strip():
        raise SourceError(f"expected <path> [since <rev>]: {spec}")
    raw, rev = m["path"].strip(), m["rev"]
    if rev is not None and (not _REV_RE.match(rev) or rev.startswith("-")):
        raise SourceError(f"not a git revision: {rev}")
    path = _inside(cwd, raw)
    root = cwd.resolve()
    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        raise SourceError(f"{rel} is a folder; name one file")
    try:
        _git(root, "ls-files", "--error-unmatch", "--", rel)
        tracked = True
    except SourceError as err:
        if "not a git repository" in str(err):
            raise SourceError(f"{root} is not a git repository") from None
        tracked = False
    common = ("--no-color", "--no-ext-diff", "--no-textconv", "-U2")
    if tracked or not path.exists():
        diff = _git(root, "diff", *common, rev or "HEAD", "--", rel)
    else:
        diff = _git(root, "diff", "--no-index", *common, "--", "/dev/null", rel, ok=(0, 1))
    if re.search(r"^Binary files .* differ$", diff, re.MULTILINE):
        raise SourceError(f"{rel} is a binary file, so its change cannot be shown")
    hunks, added, removed, more = parse_diff(diff)
    if not hunks:
        raise SourceError(f"no changes in {rel}")
    return {"type": "inline", "format": "change", "path": rel, "rev": rev, "hunks": hunks,
            "added": added, "removed": removed, "more": more, "lang": path.suffix.lstrip(".") or "text"}


def parse_source(raw: str, cwd: Path, stdin_text: str | None = None) -> dict:
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return {"type": "url", "url": raw}
    if raw.startswith("session:"):
        m = _SESSION_RE.match(raw)
        if not m:
            raise SourceError(f"expected session:<kind>/<slug>: {raw}")
        return {"type": "session", "kind": m["kind"], "slug": m["slug"]}
    if raw.endswith(":-") and re.fullmatch(r"[A-Za-z]\w*:-", raw):
        kind = raw[:-2].lower()
        kind = {"mermaid": "diagram", "graph": "diagram", "flow": "diagram", "grid": "table"}.get(kind, kind)
        if kind in ("sequence", "flowchart"):
            return visual_source(kind, stdin_text or "")
        if kind not in ("diagram", "table"):
            raise SourceError(f"unknown {raw}: stdin takes sequence:-, flowchart:-, diagram:- or table:-")
        body = (stdin_text or "").strip()
        if not body:
            raise SourceError(f"{kind}:- reads its body from stdin, and stdin was empty")
        return {"type": "inline", "format": kind, "body": body}
    if raw.startswith("code:"):
        return code_source(cwd, raw[len("code:"):])
    if raw.startswith("change:"):
        return change_source(cwd, raw[len("change:"):])
    target, _, fragment = raw.partition("#")
    path = _inside(cwd, target)
    if not path.parent.is_dir():
        raise SourceError(f"no such folder in the project: {path.parent}")
    return {"type": "file", "path": path.relative_to(cwd.resolve()).as_posix(), "fragment": fragment or None}


_PARTS = {"sequence": "actors, steps, phases, legend", "flowchart": "nodes, edges, groups"}


def _plain(tool: str, spec: dict) -> dict:
    """The spec with every list checked to hold objects, and a number written where the tools expect
    text (`"id": 1`, `"label": 404`) turned into that text."""
    out = {}
    for name, value in spec.items():
        if name in _PARTS[tool].split(", ") and value is not None:
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise SourceError(f"{tool}:-: {name} must be a list of objects")
            value = [{k: str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                      for k, v in x.items()} for x in value]
        out[name] = value
    return out


def check_flowchart(spec: dict) -> None:
    """A flowchart the map can draw: nodes with unique ids, edges between them. Loops are fine."""
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise flowchart.ValidationError("a flowchart needs a non-empty nodes list")
    ids = [n.get("id") for n in nodes if isinstance(n, dict)]
    if len(ids) != len(nodes) or not all(isinstance(i, str) and i for i in ids):
        raise flowchart.ValidationError("every node needs an id")
    dup = next((i for i in ids if ids.count(i) > 1), None)
    if dup:
        raise flowchart.ValidationError(f"node id {dup!r} is used twice")
    for e in spec.get("edges") or []:
        if not isinstance(e, dict) or e.get("from") not in ids or e.get("to") not in ids:
            raise flowchart.ValidationError(f"edge {e!r} names a node the spec does not have")
    for g in spec.get("groups") or []:  # a Mermaid subgraph: no box on the map, a name for its nodes
        if not isinstance(g.get("id"), str) or not g["id"] or not isinstance(g.get("nodes"), list) \
                or not all(i in ids for i in g["nodes"]):
            raise flowchart.ValidationError(f"group {g!r} needs an id and a list of the spec's node ids")


def visual_source(tool: str, text: str) -> dict:
    """A sequence or flowchart spec (JSON), drawn by the shared tools in the stage's face and keyed for
    frames: the grid as `html`, a sequence's numbered key as `key`."""
    try:
        spec = json.loads(text)
    except ValueError as e:
        raise SourceError(f"{tool}:-: not JSON ({e.msg}, line {e.lineno})") from None
    if not isinstance(spec, dict):
        raise SourceError(f"{tool}:-: the spec must be a JSON object")
    if "spec" in spec or "source" in spec:
        raise SourceError(f"{tool}:-: give the spec object itself ({_PARTS[tool]}), not annotate's "
                          "block wrapper or its `source` form")
    spec = _plain(tool, spec)
    try:
        if tool == "sequence":
            html = sequence.render(spec, "v", keyed=True, face="stage")
            key = sequence.render_key(spec, "v", keyed=True, face="stage")
        else:
            # The stage draws a flowchart as its map (map.js) and checks it here: loops are allowed, since a
            # state machine has them, so annotate's renderer (which wants a DAG) is not used.
            check_flowchart(spec)
            html, key = "", ""
    except (sequence.ValidationError, flowchart.ValidationError) as e:
        raise SourceError(f"{tool}:-: {e}") from None
    except Exception as e:
        raise SourceError(f"{tool}:-: the tool could not draw this spec ({type(e).__name__}: {e})") from None
    return {"type": "inline", "format": "visual", "tool": tool, "spec": spec, "html": html, "key": key}


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
