"""What a stage view's source is, and how its revision is measured. No I/O beyond the local disk."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from skills._shared.visuals import bars_svg, flowchart, graph_svg, map_svg, sequence, sequence_svg
from skills.stage import compare, scene

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_CODE_LINES = 60
MAX_LINE_BYTES = 4000  # a code or change board holds lines of at most this many bytes: past it a file is minified or generated
MAX_BOARD_BYTES = 200_000  # and the lines of one board at most this many, far under what the daemon takes in one item
MAX_CHANGE_LINES = 80  # a change card shows whole hunks while their lines fit in this many; one hunk longer is cut
GIT_TIMEOUT_S = 3
# Walked twice a second, so the revision never descends into these, and stops counting
# after MAX_FILES: a deck folder is small; a repository root is not.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".idea"}
MAX_FILES = 5000

_CODE_RE = re.compile(
    r"(?P<path>.+?):(?P<a>\d+)\s*-\s*(?P<b>\d+)"
    r"(?:\s+highlight\s+(?P<ha>\d+)(?:\s*-\s*(?P<hb>\d+))?)?\s*$")
_CHANGE_RE = re.compile(r"(?P<path>.+?)(?:\s+since\s+(?P<rev>\S+))?(?:\s+hunks?\s+(?P<ha>\d+)(?:\s*-\s*(?P<hb>\d+))?)?\s*$")
_REV_RE = re.compile(r"^[\w./~^-]{1,64}$")
_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")
_SESSION_RE = re.compile(r"^session:(?P<kind>[a-z][a-z0-9_-]{0,63})/(?P<slug>[^/\s]+)$")


# A browser shows these in a frame. Any other file in a frame is downloaded instead, so the stage
# reads it and shows it itself: Markdown as a document, the rest as text.
PAGE_SUFFIXES = {".html", ".htm", ".xhtml", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                 ".avif", ".bmp", ".ico", ".mp4", ".webm", ".mp3", ".wav", ".ogg"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}


def split_lines(text: str) -> list[str]:
    """A file's lines as an editor numbers them: split at a newline (and the CR of a CRLF) only. str.splitlines
    also splits at a form feed, a vertical tab, U+0085 and U+2028, which no editor counts as a line, so every
    line number after one would be off. A trailing newline ends the last line; it starts no empty one."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


def file_display(name: str) -> str:
    """How the stage shows a file: "page" in a frame, "markdown" rendered, or "text"."""
    suffix = Path(name).suffix.lower()
    if suffix in PAGE_SUFFIXES:
        return "page"
    return "markdown" if suffix in MARKDOWN_SUFFIXES else "text"


_PART_ID = re.compile(r"[A-Za-z0-9_-]+")
_VOID = frozenset("area base br col embed hr img input link meta source track wbr".split())
SCENE_MAX_CHARS = 100_000
PART_WORDS = 16  # a scene part is a label, a number or a node; the voice says the rest


class _Parts(HTMLParser):
    """A scene's parts: every element with data-part, in page order, with the part it sits in and its name."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[dict] = []
        self.stack: list[tuple[str, dict | None]] = []  # open elements, with the part each one starts
        self.heading: list[dict] = []  # the parts whose first heading is being read
        self.scripted = False  # a <script> or an on… handler: the scene runs in a sealed frame
        self.code = False  # inside a <script> or <style>, whose text names no part

    def open_parts(self) -> list[dict]:
        return [p for _, p in self.stack if p is not None]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name, value in attrs:
            if name.startswith("on"):
                self.scripted = True
            if re.match(r"\s*javascript:", value or "", re.IGNORECASE):
                raise SourceError("a javascript: link never runs in a scene; use a button with a handler")
        if tag in ("script", "style"):
            self.scripted = self.scripted or tag == "script"
            self.code = True
        part = None
        if "data-part" in a:
            ident = (a["data-part"] or "").strip()
            if not _PART_ID.fullmatch(ident):
                raise SourceError(f'part id "{ident}" must be letters, digits, - or _')
            if any(p["id"] == ident for p in self.parts):
                raise SourceError(f'part "{ident}" is marked twice')
            parent = self.open_parts()[-1]["id"] if self.open_parts() else None
            part = {"id": ident, "name": (a.get("data-name") or "").strip(), "parent": parent, "words": [], "head": "", "own": 0}
            self.parts.append(part)
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = [p for p in self.open_parts() + ([part] if part else []) if not p["head"]]
        if tag not in _VOID:
            self.stack.append((tag, part))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.code = False
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = []
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.code:
            return
        words = data.split()
        for p in self.open_parts():
            p["words"] += words
        inner = self.open_parts()
        if inner and not any(t in ("pre", "table") for t, _ in self.stack):
            inner[-1]["own"] += len(words)  # the words a part holds itself, outside code and tables
        for p in self.heading:
            p["head"] = (p["head"] + " " + data).strip()


def scene_source(html: str) -> dict:
    """A scene: HTML whose parts (elements marked data-part) the voice reveals one at a time. Each part's name
    is its data-name, else its first heading, else its first eight words; a part inside another names it as
    its parent. The stage sanitizes a scene with no script; one with a <script> or an on… handler is kept whole
    and marked `sandboxed`, and the stage runs it in a sealed frame that reaches nothing outside it."""
    if len(html) > SCENE_MAX_CHARS:
        raise SourceError(f"a scene holds at most {SCENE_MAX_CHARS} characters; split it into two")
    reader = _Parts()
    reader.feed(html)
    reader.close()
    if not reader.parts:
        raise SourceError("no parts: mark each part with data-part")
    parts = [{"id": p["id"], "parent": p["parent"],
              "name": p["name"] or " ".join(p["head"].split()) or " ".join(p["words"][:8])} for p in reader.parts]
    return {"type": "inline", "format": "scene", "html": html, "parts": parts,
            **({"sandboxed": True} if reader.scripted else {})}


def scene_warnings(html: str) -> list[str]:
    """What makes a scene read as a document rather than a slide: a part holding a sentence, or no slide.
    Never a reason to refuse it; talk prints each as a board: line for the next answer."""
    reader = _Parts()
    try:
        reader.feed(html)
        reader.close()
    except SourceError:
        return []
    out = []
    for p in reader.parts:
        if p["own"] > PART_WORDS:
            name = p["name"] or " ".join(p["head"].split()) or " ".join(p["words"][:8])
            out.append(f'part "{name}" holds {p["own"]} words: a part is a label of at most {PART_WORDS}, say the rest aloud')
    if not re.search(r"""class=["'][^"']*\bslide\b""", html):
        out.append('no <div class="slide">: write the claim as <h1 class="title"> inside it')
    return out


class SourceError(ValueError):
    """The source cannot be shown as asked; the message says why, for a person."""


def _inside(cwd: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    p = (p if p.is_absolute() else cwd / p).resolve()
    root = cwd.resolve()
    if p != root and root not in p.parents:
        raise SourceError(f"{raw} is outside the project {root}")
    return p


def _git_root(folder: Path) -> Path | None:
    """The top of the git work tree that holds `folder`, or None when it is in none."""
    try:
        done = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, errors="replace", timeout=GIT_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return Path(done.stdout.strip()).resolve() if done.returncode == 0 and done.stdout.strip() else None


def _git_ignores(root: Path, rel: str) -> bool:
    """True when git ignores `rel`, and also when git cannot say: only a clear "not ignored" (exit 1) lets it
    through. check-ignore takes no literal pathspecs, which is why GIT_LITERAL_PATHSPECS is not set here."""
    try:
        done = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--no-index", "--", rel],
                              capture_output=True, timeout=GIT_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True
    return done.returncode != 1


# What a file's own name gives away: secrets and keys that sit in a project beside its code. The stage is
# served to other machines, so a board never reads them, inside the project folder or out of it.
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".config", ".azure", ".terraform"}
SECRET_NAMES = re.compile(r"^(?:\.env(?:\..*)?|\.npmrc|\.netrc|\.pypirc|\.pgpass|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)"
                          r"(?:\.pub)?|.*\.(?:pem|key|p12|pfx|kdbx))$", re.IGNORECASE)
MAX_PATH_CHARS = 4096


def _nearest_dir(path: Path) -> Path | None:
    """The closest folder at or above `path` that exists."""
    for p in (path, *path.parents):
        if p.is_dir():
            return p
    return None


def _refuse_secret(raw: str, rel_parts: tuple[str, ...]) -> None:
    """A path through .git, a secrets folder, or a file named like a secret is refused, wherever it sits."""
    if ".git" in rel_parts:
        raise SourceError(f"{raw} is inside a .git folder")
    if any(p in SECRET_DIRS for p in rel_parts[:-1]) or (rel_parts and SECRET_NAMES.match(rel_parts[-1])):
        raise SourceError(f"{raw} looks like a secret or a credential (a .env file, a key, or a folder such as .ssh), "
                          "which the stage never shows")


def _refuse_ignored(raw: str, path: Path, fallback: Path | None = None) -> Path | None:
    """The git work tree that holds `path`, after refusing a file that tree ignores. None when it is in none."""
    folder = _nearest_dir(path if path.is_dir() else path.parent)
    root = _git_root(folder) if folder else None
    root = root or fallback
    if root is not None and (path == root or root in path.parents) and _git_ignores(root, path.relative_to(root).as_posix()):
        raise SourceError(f"{raw} is ignored by git, so the stage does not show it")
    return root


def locate(cwd: Path | None, raw: str) -> tuple[Path, Path, str]:
    """Where a code or change board reads its file: (repository or project root, file, the name the board shows).
    A relative path stays inside the project `cwd`. An absolute or ~ path may name a file in any git work tree,
    since a code or change board carries its lines with it. A file git ignores, a path through .git, a file named
    like a secret (.env, a key) or in a secrets folder (.ssh, .aws), and a hidden folder under the home folder are
    refused wherever the file sits, inside the project too, because the stage is served to other machines. A path
    that cannot be read as one (an unknown ~user, a NUL, a name too long) is a SourceError, never an exception."""
    if "\0" in raw or len(raw) > MAX_PATH_CHARS:
        raise SourceError("not a usable path: it holds a NUL or is far too long")
    try:
        return _locate(cwd, raw)
    except SourceError:
        raise
    except (RuntimeError, ValueError, OSError) as e:  # ~nosuchuser, a name past the filesystem's limit, a loop of links
        raise SourceError(f"not a usable path: {raw[:80]} ({type(e).__name__}: {e})") from None


def _locate(cwd: Path | None, raw: str) -> tuple[Path, Path, str]:
    given = Path(raw).expanduser()
    inside = None
    if not given.is_absolute():
        if cwd is None:
            raise SourceError(f"{raw} is relative and there is no project folder; give an absolute path")
        path = _inside(cwd, raw)
        inside = cwd.resolve()
    else:
        path = given.resolve()
        if cwd is not None and (path == cwd.resolve() or cwd.resolve() in path.parents):
            inside = cwd.resolve()
    if inside is not None:
        rel = path.relative_to(inside)
        _refuse_ignored(raw, path, fallback=_git_root(inside))
        _refuse_secret(raw, rel.parts)
        return inside, path, rel.as_posix()
    if ".git" in path.parts:
        raise SourceError(f"{raw} is inside a .git folder")
    home = Path.home().resolve()
    if home in path.parents and any(part.startswith(".") for part in path.relative_to(home).parts[:-1]):
        raise SourceError(f"{raw} is in a hidden folder of the home folder, which the stage never shows")
    folder = path if path.is_dir() else path.parent
    root = _git_root(folder) if folder.is_dir() else None
    if root is None or (path != root and root not in path.parents):
        raise SourceError(f"{raw} is outside the project and in no git repository")
    if _git_ignores(root, path.relative_to(root).as_posix()):
        raise SourceError(f"{raw} is ignored by git, so the stage does not show it")
    _refuse_secret(raw, path.relative_to(root).parts)
    return root, path, f"{root.name}/{path.relative_to(root).as_posix()}"


def check_binary(raw: bytes, rel: str) -> None:
    """Refuse a binary file (a NUL in its first 8 KB) by name: stage.py and talk refuse it the same way."""
    if b"\0" in raw[:8192]:
        raise SourceError(f"{rel} is a binary file")


def check_line_bytes(lines: list, rel: str, first: int = 1, numbers: list | None = None) -> None:
    """Refuse lines no board can carry: one longer than MAX_LINE_BYTES, or all of them past MAX_BOARD_BYTES.
    The daemon would otherwise answer 'item body too large', which reads as a daemon failure (exit 3)."""
    total = 0
    for n, text in zip(numbers or range(first, first + len(lines)), lines):
        size = len(str(text).encode("utf-8", "replace"))
        if size > MAX_LINE_BYTES:
            raise SourceError(f"line {n} of {rel} is {size} bytes: a board holds lines of at most {MAX_LINE_BYTES} "
                              "bytes (a minified or generated file); name a range without it")
        total += size
    if total > MAX_BOARD_BYTES:
        raise SourceError(f"the lines asked of {rel} are {total} bytes: a board holds at most {MAX_BOARD_BYTES}; "
                          "name a shorter range")


def code_source(cwd: Path, spec: str) -> dict:
    """A range of a file's lines as a code board. At most MAX_CODE_LINES are kept: a longer range is cut and the
    board carries `note`, a sentence for the author that says what was left out, for talk to print."""
    m = _CODE_RE.match(spec.strip())
    if not m:
        raise SourceError(f"expected <path>:<first>-<last>: {spec}")
    rel = m["path"].strip()
    _, path, shown = locate(cwd, rel)
    if not path.is_file():
        raise SourceError(f"no such file in the project: {rel}")
    a, b = int(m["a"]), int(m["b"])
    if a < 1 or b < a:
        raise SourceError(f"bad line range {a}-{b} in {rel}")
    raw = path.read_bytes()
    check_binary(raw, rel)
    lines = split_lines(raw.decode(errors="replace"))
    if a > len(lines):
        raise SourceError(f"{rel} has only {len(lines)} lines")
    asked = b
    b = min(b, len(lines))
    truncated = b - a + 1 > MAX_CODE_LINES
    if truncated:
        b = a + MAX_CODE_LINES - 1
    check_line_bytes(lines[a - 1:b], rel, a)
    notes = []
    if asked > len(lines) and not truncated:
        notes.append(f"code cut at line {len(lines)}, the end of {rel}")
    elif truncated:
        notes.append(f"code cut to lines {a}-{b} of {rel}: at most {MAX_CODE_LINES} lines; lines {b + 1}-{min(asked, len(lines))} "
                     "are not shown, so name a second range for them")
    highlight = None
    if m["ha"]:
        ha, hb = int(m["ha"]), int(m["hb"] or m["ha"])
        ha, hb = min(ha, hb), max(ha, hb)
        if hb < a or ha > b:
            raise SourceError(f"highlight {ha}-{hb} is outside lines {a}-{b} of {rel}")
        highlight = [max(ha, a), min(hb, b)]
    return {"type": "inline", "format": "code", "path": shown,
            "start": a, "lines": lines[a - 1:b], "highlight": highlight,
            "lang": path.suffix.lstrip(".") or "text", "truncated": truncated,
            **({"note": "; ".join(notes)} if notes else {})}


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


def parse_diff(text: str, pick: tuple[int, int] | None = None) -> tuple[list, int, int, int, int]:
    """A unified diff as (hunks, added, removed, more, total): every hunk is {n, header, start_old, start_new,
    lines:[{op, old, new, text}]}, `n` its place in the whole diff from 1. `pick` (first, last) keeps only those
    hunks. Otherwise whole hunks are kept, in order, while their lines fit in MAX_CHANGE_LINES; the first one is
    always kept, cut at the limit when it alone is longer. `more` counts the changed (+ and -) lines left out of
    what is shown, never a context line; `total` is how many hunks the diff has. added and removed count the
    whole diff."""
    raw, added, removed = [], 0, 0
    old = new = 0
    hunk = None
    for line in split_lines(text):
        m = _HUNK_RE.match(line)
        if m:
            old, new = int(m["old"]), int(m["new"])
            hunk = {"n": len(raw) + 1, "header": line, "start_old": old, "start_new": new, "lines": []}
            raw.append(hunk)
            continue
        if hunk is None or not line or line[0] not in "+- ":
            continue  # the file header, or "\\ No newline at end of file"
        op, body = line[0], line[1:]
        hunk["lines"].append({"op": op, "old": None if op == "+" else old, "new": None if op == "-" else new, "text": body})
        old += op != "+"
        new += op != "-"
        added += op == "+"
        removed += op == "-"
    raw = [h for h in raw if h["lines"]]
    for i, h in enumerate(raw, 1):
        h["n"] = i
    changed = lambda h: sum(r["op"] != " " for r in h["lines"])
    if pick is not None:
        kept = [h for h in raw if pick[0] <= h["n"] <= pick[1]]
    else:
        kept, used = [], 0
        for h in raw:
            if kept and used + len(h["lines"]) > MAX_CHANGE_LINES:
                break
            kept.append(h)
            used += len(h["lines"])
        if len(kept) == 1 and used > MAX_CHANGE_LINES:  # one hunk longer than the card: cut it, and say how much
            kept = [{**kept[0], "lines": kept[0]["lines"][:MAX_CHANGE_LINES]}]
    more = sum(changed(h) for h in raw if pick is None) - sum(changed(h) for h in kept) if pick is None else 0
    return kept, added, removed, more, len(raw)


def change_source(cwd: Path, spec: str) -> dict:
    """What changed in a file, read from git: the working tree against HEAD, or against `since <rev>`, in the git
    work tree that holds the file (a file in a repository nested inside the project is diffed in its own, not
    shown whole as new). `hunk N` or `hunks A-B` picks hunks of a long change. A file git does not track yet
    shows as all new. `hunks_total` is how many hunks the change has and `more` the changed lines of those left
    out; `note` says it in a sentence for the author when a long change is cut."""
    m = _CHANGE_RE.match(spec.strip())
    if not m or not m["path"].strip():
        raise SourceError(f"expected <path> [since <rev>] [hunk N]: {spec}")
    raw, rev = m["path"].strip(), m["rev"]
    if rev is not None and (not _REV_RE.match(rev) or rev.startswith("-")):
        raise SourceError(f"not a git revision: {rev}")
    pick = None
    if m["ha"]:
        pick = tuple(sorted((int(m["ha"]), int(m["hb"] or m["ha"]))))
        if pick[0] < 1:
            raise SourceError("hunks are counted from 1")
    root, path, shown = locate(cwd, raw)
    if path.is_dir():
        raise SourceError(f"{shown} is a folder; name one file")
    folder = _nearest_dir(path.parent)
    repo = (_git_root(folder) if folder else None) or root
    if repo != path and repo not in path.parents:
        repo = root
    rel = path.relative_to(repo).as_posix()
    try:
        _git(repo, "ls-files", "--error-unmatch", "--", rel)
        tracked = True
    except SourceError as err:
        if "not a git repository" in str(err):
            raise SourceError(f"{repo} is not a git repository") from None
        tracked = False
    common = ("--no-color", "--no-ext-diff", "--no-textconv", "-U2")
    if tracked or not path.exists():
        diff = _git(repo, "diff", *common, rev or "HEAD", "--", rel)
    else:
        diff = _git(repo, "diff", "--no-index", *common, "--", "/dev/null", rel, ok=(0, 1))
    if re.search(r"^Binary files .* differ$", diff, re.MULTILINE):
        raise SourceError(f"{rel} is a binary file, so its change cannot be shown")
    hunks, added, removed, more, total = parse_diff(diff, pick)
    shown_rows = [r for h in hunks for r in h["lines"]]
    check_line_bytes([r["text"] for r in shown_rows], rel, numbers=[r["new"] or r["old"] for r in shown_rows])
    if not hunks:
        if pick is not None and total:
            said = f"hunk {pick[0]}" if pick[0] == pick[1] else f"hunks {pick[0]}-{pick[1]}"
            raise SourceError(f"{rel} has only {total} hunk{'s' if total != 1 else ''}, not {said}")
        raise SourceError(f"no changes in {rel}")
    out = {"type": "inline", "format": "change", "path": shown, "rev": rev, "hunks": hunks,
           "added": added, "removed": removed, "more": more, "hunks_total": total,
           "lang": path.suffix.lstrip(".") or "text"}
    if pick is None and (more or total > len(hunks)):
        out["note"] = (f"change cut to the first {len(hunks)} of {total} hunks: {more} changed line{'s' if more != 1 else ''} "
                       f"of {shown} are not shown; add `hunk N` to the tag to show one")
    return out


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
        kind = {"mermaid": "diagram", "flow": "diagram", "grid": "table", "chart": "bars"}.get(kind, kind)
        if kind == "graph" and not (stdin_text or "").lstrip().startswith("{"):
            kind = "diagram"  # graph:- with Mermaid on stdin is the old name of diagram:-; with a JSON spec it is the graph board
        if kind in ("sequence", "flowchart", "map", "bars", "graph"):
            return visual_source(kind, stdin_text or "", root=cwd)
        if kind not in ("diagram", "table"):
            raise SourceError(f"unknown {raw}: stdin takes sequence:-, flowchart:-, map:-, bars:-, graph:-, diagram:- or table:-")
        body = (stdin_text or "").strip()
        if not body:
            raise SourceError(f"{raw} reads its body from stdin, and stdin was empty")
        if kind == "diagram":
            return mermaid_source(raw, body, cwd)
        return {"type": "inline", "format": kind, "body": body}
    if raw.startswith("code:"):
        return code_source(cwd, raw[len("code:"):])
    if raw.startswith("change:"):
        return change_source(cwd, raw[len("change:"):])
    if raw.startswith("screen:"):
        return screen_source(cwd, raw[len("screen:"):])
    target, _, fragment = raw.partition("#")
    path = _inside(cwd, target)
    if not path.parent.is_dir():
        raise SourceError(f"no such folder in the project: {path.parent}")
    return {"type": "file", "path": path.relative_to(cwd.resolve()).as_posix(), "fragment": fragment or None}


_TAGS = re.compile(r"<[^>]*>")


def plain_text(markup) -> str:
    """Inline HTML as the words it says: a part's title as a sentence names it."""
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(_TAGS.sub("", str(markup or "")))).strip()


def screen_source(cwd: Path, raw: str) -> dict:
    """A spotlight spec (skills/spotlight) as a screen board: its screens, each part keyed p1, p2, ... in order.
    An image stays in the spec's folder, which the stage serves (stage.py mounts it), so the view holds only
    the path, the image's size and its crop; every box is in the drawn screen's pixels, as the spotlight draws it."""
    from skills.spotlight import build as spotlight  # the spotlight's own checks, so the two never disagree
    rel = raw.strip()
    if not rel:
        raise SourceError("expected screen:<path to a spotlight.json in the project>")
    path = _inside(cwd, rel)
    if not path.is_file():
        raise SourceError(f"no such spotlight spec in the project: {rel}")
    try:
        spec = json.loads(path.read_text())
    except ValueError as e:
        raise SourceError(f"screen:{rel}: not JSON ({e})") from None
    if not isinstance(spec, dict):
        raise SourceError(f"screen:{rel}: the spec must be a JSON object")
    base = path.parent
    for s in spec.get("screens") or []:
        img = isinstance(s, dict) and s.get("image")
        if img:
            try:
                (base / img).resolve().relative_to(base.resolve())
            except ValueError:
                raise SourceError(f"screen:{rel}: image {img} is outside the spec's folder") from None
    try:
        norm = spotlight.normalize(spec, base, embed=False)
    except spotlight.SpecError as e:
        raise SourceError(f"screen:{rel}: {e}") from None
    n, screens = 0, []
    for s in norm["screens"]:
        steps = []
        for st in s["steps"]:
            n += 1
            steps.append({"id": f"p{n}", **{k: st[k] for k in ("title", "text", "facts", "examples", "boxes", "focus")
                                            if st.get(k)}})
        screens.append({**{k: s[k] for k in ("id", "label", "phase", "title", "source", "image", "w", "h", "full",
                                              "off", "html", "alt") if s.get(k) is not None}, "steps": steps})
    root = cwd.resolve()
    return {"type": "inline", "format": "screen", "spec": path.relative_to(root).as_posix(),
            "dir": base.relative_to(root).as_posix(),
            **{k: norm[k] for k in ("title", "tag", "link", "footer") if norm.get(k)}, "screens": screens}


def screen_parts(source: dict) -> list:
    """A screen board's parts in order, for its scene: each step's key id and its title as words."""
    return [{"id": st["id"], "name": plain_text(st.get("title"))} for s in source["screens"] for st in s["steps"]]


def screen_model(source: dict) -> scene.SceneModel:
    """A screen board's scene model: one part per step, named by its title, so a sentence that says a title
    brings that part, and `part p3` or `part "Press Create"` points at one."""
    return scene.parts_model(screen_parts(source))


def screen_scene(source: dict, title: str) -> dict:
    """The steps of a screen board shown on its own: the whole first screen, then one part lit per step."""
    m = screen_model(source)
    built, _ = scene.compile_scene(m, [[scene.Verb("focus", keys=[k])] for k in m.keys], title)
    return built


def mermaid_source(raw: str, body: str, root: Path | None = None) -> dict:
    """Mermaid, which the stage no longer draws, as the board it can: a graph, flowchart or state diagram as a
    flowchart (drawn as a map, as a talk call draws it) and a sequenceDiagram as a sequence (drawn as lanes).
    Any other kind is refused in one line that names the JSON kinds to write instead."""
    spec, tool = scene.mermaid_spec(body), "flowchart"
    if spec is None:
        tool = "sequence"
        try:
            spec = scene.mermaid_sequence_spec(body)
        except ValueError as e:
            raise SourceError(f"{raw}: this sequenceDiagram cannot be drawn as lanes: {e}; "
                              "write it as a JSON spec for sequence:-") from None
    if spec is None:
        word = re.match(r"[A-Za-z][\w-]*", body)
        what = f"Mermaid {word.group()}" if word else "this body"
        raise SourceError(f"{raw}: the stage does not draw {what}, only a Mermaid graph, state or sequence diagram; "
                          "write a JSON spec for flowchart:-, sequence:- or map:- instead")
    try:
        return visual_source(tool, json.dumps(spec), root=root)
    except SourceError as e:
        raise SourceError(f"{raw}: drawn as a {tool}, {str(e).split(': ', 1)[-1]}") from None


_PARTS = {"sequence": "actors, steps, phases, legend, groups", "flowchart": "nodes, edges, groups",
          "map": "boxes, zones, arrows, legend", "bars": "bars", "graph": "nodes, edges"}
_NUMBERS = {"n"}  # fields the tools read as numbers: a step's number in the walkthrough
_MAP_TEXT = {"id", "name", "label", "from", "to"}  # on a map every other field may be a number (col, row, b, r)
_TEXT_FIELDS = {"map": _MAP_TEXT, "bars": {"id", "label", "note", "unit"}}  # bars: `value` is a number, never text


def _plain(tool: str, spec: dict) -> dict:
    """The spec with every list checked to hold objects, and a number written where the tools expect
    text (`"id": 1`, `"label": 404`) turned into that text."""
    out = {}
    for name, value in spec.items():
        if name in _PARTS[tool].split(", ") and value is not None:
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise SourceError(f"{tool}:-: {name} must be a list of objects")
            text = (lambda k: k in _TEXT_FIELDS[tool]) if tool in _TEXT_FIELDS else (lambda k: k not in _NUMBERS)
            value = [{k: str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and text(k) else v
                      for k, v in x.items()} for x in value]
        out[name] = value
    return out


def _plain_sides(spec: dict) -> dict:
    """A compare spec with each side's lists read as `_plain` reads a sequence's."""
    cmp = spec["compare"]
    if not isinstance(cmp, dict):
        return spec
    return dict(spec, compare={k: _plain("sequence", v) if isinstance(v, dict) else v for k, v in cmp.items()})


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


# The boards drawn on the server, keyed for the stage's frames, and kept as `svg` beside their spec.
DRAWN = {"map": map_svg, "bars": bars_svg, "graph": graph_svg}


def visual_source(tool: str, text: str, root: Path | None = None) -> dict:
    """A sequence, flowchart or map spec (JSON), checked and kept as its spec. The stage draws a sequence as its
    lanes (lanes.js) and a flowchart as its map (map.js), so no drawing is stored with them. An architecture map
    is drawn here, by map_svg, keyed for the stage's frames, and kept as `svg` beside its spec: it is measured and
    routed in Python, so the page cannot draw it. Its words reach the SVG only as escaped text, and the stage
    still runs it through DOMPurify before it goes in.
    With `root`, a sequence also keeps the lines round each step's `ref` (see step_refs), for its popups."""
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
        if tool == "sequence" and "compare" in spec:
            spec = compare.compare_spec(_plain_sides(spec))  # each side checked as a sequence, then merged
        elif tool == "sequence":
            sequence_svg.validate(spec)  # the base rules, plus role, checks, n, outcome and the four tones
        elif tool in DRAWN:
            DRAWN[tool].validate(spec)
        else:
            # Loops are allowed, since a state machine has them, so annotate's checks (which want a DAG) are not used.
            check_flowchart(spec)
    except (sequence.ValidationError, flowchart.ValidationError, map_svg.ValidationError, bars_svg.ValidationError,
            graph_svg.ValidationError) as e:
        raise SourceError(f"{tool}:-: {e}") from None
    except Exception as e:
        raise SourceError(f"{tool}:-: the tool could not read this spec ({type(e).__name__}: {e})") from None
    source = {"type": "inline", "format": "visual", "tool": tool, "spec": spec}
    if tool in DRAWN:
        uid = "vz" + tool[0] + hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:8]
        try:
            source["svg"] = DRAWN[tool].render(spec, uid, keyed=True)
        except Exception as e:
            raise SourceError(f"{tool}:-: the {tool} board could not be drawn ({type(e).__name__}: {e})") from None
    if tool == "sequence" and root is not None:
        refs, problems = step_refs(spec, root)
        if refs:
            source["refs"] = refs
        if problems:  # the step is still shown; stage.py prints the note on stderr
            source["note"] = "; ".join(f"sequence ref: {p}" for p in problems)
    return source


REF_BEFORE, REF_AFTER = 2, 5   # a step's popup shows its line with this many before and after it


def step_refs(spec: dict, root: Path) -> tuple[dict, list[str]]:
    """The source lines round each step's `ref` (path:line, under root), keyed by step id, and a problem
    for each ref that names no line there. A step's popup on the stage shows them."""
    refs, problems = {}, []
    base = root.resolve()
    # a compare board's row holds each side's step: the after one's ref under the row's key, the before one's
    # under before:<key> when the row has an after step too
    found = []
    for s in spec.get("steps") or []:
        found.append((s["id"], s.get("ref")))
        if s.get("before") and s.get("after"):
            found.append((f"before:{s['id']}", s["before"].get("ref")))
    for sid, ref in found:
        if not ref:
            continue
        rel, _, line = ref.strip().rpartition(":")
        path = (base / rel).resolve()
        if not path.is_relative_to(base):
            problems.append(f"step {sid}: ref {ref} names no file in the code folder")
            continue
        try:
            locate(base, rel)  # the same refusals as a code board: .env, .git, a git-ignored file
        except SourceError as e:
            problems.append(f"step {sid}: ref {ref} is refused: {e}")
            continue
        if not path.is_file():
            problems.append(f"step {sid}: ref {ref} names no file in the code folder")
            continue
        lines = split_lines(path.read_text(errors="replace"))
        at = int(line)
        if at > len(lines):
            problems.append(f"step {sid}: ref {ref} is past the end of {rel}, which has {len(lines)} lines")
            continue
        a, b = max(1, at - REF_BEFORE), min(len(lines), at + REF_AFTER)
        refs[sid] = {"path": path.relative_to(base).as_posix(), "start": a, "at": at, "lines": lines[a - 1:b],
                         "lang": path.suffix.lstrip(".") or "text"}
    return refs, problems


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
