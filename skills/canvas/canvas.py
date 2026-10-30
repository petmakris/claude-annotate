"""The canvas viewer: a set of screenshots as one Figma-like page that pans and zooms.

A manifest (JSON) names the groups, their boards and each board's shots; `build` writes a folder
with one self-contained index.html, the images, and thumbnails made here. `check` validates a
manifest. `template` writes the page with no data in it, for a project that cannot reach this
repo to vendor and fill in itself. See skills/canvas/SKILL.md.

Manifest:

    {
      "title": "Mealy journey", "subtitle": "…", "id": "mealy",
      "status": {"kind": "passed", "label": "Passed"},          optional chip by the title
      "meta": ["Run 29 Oct 2026, 18:10", "12 min"],              optional lines under it
      "banner": "The run failed in …",                            optional alert
      "session": {"kind": "journey", "slug": "mealy", "cwd": "/path/to/the/app's/checkout",
                  "title": "Mealy journey", "reruns": true},              optional, see below
      "comments": {"canvas": "mealy", "name": "Mealy",
                   "scopes": {"app": "This app", "both": "Both apps"}},   only with a session
      "board_width": 480,                                         the first shot's drawn width
      "groups": [
        {"name": "Account", "id": "account", "status": "passed", "note": "2 min", "empty": "Not run.",
         "boards": [
           {"number": 1, "title": "Sign in", "caption": "How it is reached …",
            "id": "account/01-sign-in",                           optional, see below
            "status": "failure", "error": "…",                    a failure board, optional
            "shots": [
              {"label": "Desktop", "file": "01-sign-in.png", "width": 1600, "height": 1000,
               "viewport": {"width": 1600, "height": 1000}},
              {"label": "Phone", "file": "01-sign-in.phone.png", "width": 390, "height": 844,
               "viewport": {"width": 390, "height": 844}}]}]}]
    }

A board's `number` is shown beside its title. Without ids it must be unique on the canvas: #board-<n>
(or #<n>) links and comments go by it. A board's `id` (letters, digits and - _ . /, up to 160) is its lasting
name instead, unique on the canvas: #board-<id> links and comments go by it, so a canvas whose
groups each number their boards from 1 can give every board an id and repeat numbers.

A canvas with a `session` lives in a webcompanion session (contract in ~/projects/webcompanion/
docs/contract.md): `build` finds the live session of that kind and slug, or reopens or creates it
(in `cwd`), registers the built folder as its page (`wc-boot.js`, which opens `assets/index.html`),
and puts its sid and link in the page. The page then keeps its comments in the session's threads
(one thread per board, each message one op of canvas-store.js); its link is the session's page,
so build it outside ~/Outbox. With `reruns`, every group whose
`id` is set gets a Re-run button and the toolbar Re-run all and Send to Claude: each is an event
on the session for the Claude session that owns it (claude-annotate's /journey), and the group shows
the run's state from the session's `run/<group id>` item. Without the daemon the canvas builds
without its session and says so.

A shot's file is relative to the manifest. Its width and height are its size in CSS pixels (a 2x
PNG of a 390 px window is 390 wide); left out, they are the image's own. With a viewport the shot
is drawn as its first screen, the rest of a full-page shot in the viewer a click opens.

What changed since an earlier capture, all optional (the project compares; the page only shows):

      "changes": {"since": "29 Oct 2026, 08:00",                 the earlier capture, for the count
                  "removed": [{"number": 64, "title": "…", "group": "Coach"}]},
      board:  "change": "changed" | "unchanged" | "new",          a mark on the board
              "change_label": "renamed",                           the mark's word, else the change
              "change_note": "Was “Sunday morning”.",              shown in the viewer
      shot:   "change": "changed" | "unchanged" | "new",          which of a board's shots moved
              "previous": "previous/01-sign-in.png",               the earlier image, before and after
              "diff": {"x": 120, "y": 40, "width": 300, "height": 18}   where it differs, CSS pixels

A canvas with `changes` gets a Changed only button and a count; a board with no `change` counts
as unchanged. A shot's `previous` is relative to the manifest, as its file is; it gets no
thumbnail (the canvas draws only the new image).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

STATIC = Path(__file__).resolve().parent / "static"
DATA_MARK = "/*CANVAS:DATA*/"
# Read in this order into the page's one script: maths, store, chrome, page, session, comments.
SCRIPTS = ["canvas-math.js", "canvas-store.js", "canvas-chrome.js"]
CLOSURE = ["canvas-page.js", "canvas-session.js", "canvas-comments.js"]
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
BOARD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/._-]{0,159}$")
SHOT_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")
KIND = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
# The page a canvas session's shell opens (registered as the session's renderer entry).
BOOT = "wc-boot.js"
BOOT_JS = "// The session's shell page opens the canvas itself (skills/canvas/canvas.py).\nlocation.replace('assets/index.html' + location.hash);\n"
# Azure's browser speech SDK, for spoken comments (vendored by the annotate skill).
SPEECH_SDK = Path(__file__).resolve().parents[1] / "annotate" / "static" / "vendor" / "speech-sdk.min.js"
CHANGES = ("changed", "unchanged", "new")
# Captions are drawn under their board, in this much of the surface (canvas-math.js).
CAPTION_H = 128
TALL = 2.4


def template() -> str:
    """The page with every script and style in it and DATA_MARK where the data goes."""
    css = (STATIC / "canvas.css").read_text() + "\n" + (STATIC / "canvas-comments.css").read_text()
    js = "\n".join((STATIC / f).read_text() for f in SCRIPTS)
    js += "\n(function () {\n" + "\n".join((STATIC / f).read_text() for f in CLOSURE) + "\n})();\n"
    page = (STATIC / "template.html").read_text()
    return page.replace("/*CANVAS:CSS*/", css).replace("/*CANVAS:JS*/", js)


def fill(page: str, data: dict) -> str:
    """The template with the canvas data in it. `<` is escaped so no text can end the script."""
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return page.replace(DATA_MARK, blob, 1)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "canvas"


def _file_problem(f: Any, base: Path | None) -> str | None:
    if not isinstance(f, str) or not f or f.startswith("/") or ".." in Path(f).parts:
        return "a path relative to the manifest, inside its folder."
    if base is not None and not (base / f).is_file():
        return f"{f} does not exist."
    return None


def check(m: Any, base: Path | None = None) -> list[str]:
    """What is wrong with a manifest, one line each; empty when it builds. `base` checks the files."""
    errs: list[str] = []
    if not isinstance(m, dict):
        return ["The manifest must be a JSON object."]
    if not isinstance(m.get("title"), str) or not m["title"].strip():
        errs.append("title: a non-empty string is required.")
    if "id" in m and not (isinstance(m["id"], str) and SLUG.match(m["id"])):
        errs.append("id: lower-case letters, digits and -, up to 40.")
    se = m.get("session")
    if se is not None:
        if not isinstance(se, dict) or not (isinstance(se.get("kind"), str) and KIND.match(se["kind"])):
            errs.append("session.kind: a webcompanion kind (a-z, 0-9, - and _).")
        elif not (isinstance(se.get("slug"), str) and SLUG.match(se["slug"])):
            errs.append("session.slug: lower-case letters, digits and -, up to 40.")
        elif not (isinstance(se.get("cwd"), str) and se["cwd"].startswith("/")):
            errs.append("session.cwd: the absolute folder the session belongs to.")
    c = m.get("comments")
    if c is not None:
        if not isinstance(c, dict):
            errs.append('comments: {"canvas", "name", "scopes"}.')
        elif not (isinstance(c.get("canvas"), str) and SLUG.match(c["canvas"])):
            errs.append("comments.canvas: lower-case letters, digits and -, up to 40.")
        sc = c.get("scopes") if isinstance(c, dict) else None
        if sc is not None and not (isinstance(sc, dict) and isinstance(sc.get("app"), str) and isinstance(sc.get("both"), str)):
            errs.append('comments.scopes: {"app": label, "both": label}.')
    ch = m.get("changes")
    if ch is not None:
        if not isinstance(ch, dict) or not isinstance(ch.get("since", ""), str):
            errs.append('changes: {"since": text, "removed": [...]}.')
        else:
            removed = ch.get("removed", [])
            if not isinstance(removed, list) or not all(isinstance(r, dict) and isinstance(r.get("title"), str) for r in removed):
                errs.append('changes.removed: a list of {"number", "title", "group"}.')
    if "board_width" in m and not (isinstance(m["board_width"], (int, float)) and 40 <= m["board_width"] <= 4000):
        errs.append("board_width: a number of pixels from 40 to 4000.")
    groups = m.get("groups")
    if not isinstance(groups, list) or not groups:
        errs.append("groups: a non-empty list is required.")
        return errs
    seen: dict[str, str] = {}
    for gi, g in enumerate(groups):
        at = f"groups[{gi}]"
        if not isinstance(g, dict):
            errs.append(f"{at}: must be an object.")
            continue
        if not isinstance(g.get("name"), str) or not g["name"].strip():
            errs.append(f"{at}.name: a non-empty string is required.")
        if "id" in g and not (isinstance(g["id"], str) and SLUG.match(g["id"])):
            errs.append(f"{at}.id: lower-case letters, digits and -, up to 40.")
        boards = g.get("boards", [])
        if not isinstance(boards, list):
            errs.append(f"{at}.boards: must be a list.")
            continue
        for bi, b in enumerate(boards):
            bat = f"{at}.boards[{bi}]"
            if not isinstance(b, dict):
                errs.append(f"{bat}: must be an object.")
                continue
            n = b.get("number")
            bid = b.get("id")
            if bid is not None:
                if not (isinstance(bid, str) and BOARD_ID.match(bid)):
                    errs.append(f"{bat}.id: letters, digits and - _ . /, up to 160.")
                elif "id:" + bid in seen:
                    errs.append(f"{bat}.id: {bid} is also {seen['id:' + bid]}; #board-{bid} links and comments need it once.")
                else:
                    seen["id:" + bid] = bat
            if not (isinstance(n, int) and not isinstance(n, bool) and n >= 0):
                errs.append(f"{bat}.number: a whole number from 0 is required.")
            elif b.get("status") != "failure" and bid is None:
                if str(n) in seen:
                    errs.append(f"{bat}.number: {n} is also {seen[str(n)]}; #board-{n} links and comments need it once.")
                seen[str(n)] = bat
            if not isinstance(b.get("title"), str):
                errs.append(f"{bat}.title: a string is required.")
            for k in ("caption", "error"):
                if k in b and not isinstance(b[k], str):
                    errs.append(f"{bat}.{k}: must be a string.")
            if "status" in b and b["status"] not in ("failure",):
                errs.append(f'{bat}.status: only "failure" is known.')
            if "change" in b and b["change"] not in CHANGES:
                errs.append(f"{bat}.change: one of {', '.join(CHANGES)}.")
            for k in ("change_label", "change_note"):
                if k in b and not isinstance(b[k], str):
                    errs.append(f"{bat}.{k}: must be a string.")
            shots = b.get("shots")
            if not isinstance(shots, list) or not shots:
                errs.append(f"{bat}.shots: a non-empty list is required.")
                continue
            keys = set()
            for si, s in enumerate(shots):
                sat = f"{bat}.shots[{si}]"
                if not isinstance(s, dict):
                    errs.append(f"{sat}: must be an object.")
                    continue
                label = s.get("label", "Shot")
                if not isinstance(label, str) or not SHOT_SLUG.match(slug(label)):
                    errs.append(f"{sat}.label: a short name such as Desktop or Phone.")
                elif slug(label) in keys:
                    errs.append(f"{sat}.label: {label} twice on one board.")
                else:
                    keys.add(slug(label))
                why = _file_problem(s.get("file"), base)
                if why:
                    errs.append(f"{sat}.file: {why}")
                if "previous" in s:
                    why = _file_problem(s["previous"], base)
                    if why:
                        errs.append(f"{sat}.previous: {why}")
                if "change" in s and s["change"] not in CHANGES:
                    errs.append(f"{sat}.change: one of {', '.join(CHANGES)}.")
                d = s.get("diff")
                if d is not None and not (isinstance(d, dict) and all(isinstance(d.get(k), (int, float)) and d[k] >= 0 for k in ("x", "y", "width", "height"))):
                    errs.append(f'{sat}.diff: {{"x", "y", "width", "height"}} in CSS pixels.')
                for k in ("width", "height"):
                    if k in s and not (isinstance(s[k], (int, float)) and s[k] > 0):
                        errs.append(f"{sat}.{k}: a positive number of pixels.")
                vp = s.get("viewport")
                if vp is not None and not (isinstance(vp, dict) and all(isinstance(vp.get(k), (int, float)) and vp[k] > 0 for k in ("width", "height"))):
                    errs.append(f'{sat}.viewport: {{"width": px, "height": px}}.')
    return errs


def frame_aspect(s: dict) -> float:
    """Height over width of a shot's frame on the canvas (canvas-math.js frameOf)."""
    vp = s.get("viewport")
    if vp:
        return vp["height"] / vp["width"]
    return min(s["height"], s["width"] * TALL) / s["width"]


def _image():
    try:
        from PIL import Image  # noqa: WPS433
    except ImportError as e:  # pragma: no cover - the message is the point
        raise SystemExit("canvas build needs Pillow: run it as `uv run --with pillow tools/canvas.py build …`.") from e
    return Image


def make_thumbs(src: Path, out: Path, stem: str, aspect: float, frame_w: float) -> tuple[list[str], int, int, bool]:
    """WebP thumbnails of the frame's part of the image, at the drawn width and twice it.

    Returns their paths relative to `out`, the first one's size and whether the frame crops the image.
    An existing thumbnail newer than its source is kept.
    """
    Image = _image()
    with Image.open(src) as im:
        im.load()
        w, h = im.size
        crop_h = min(h, max(1, round(w * aspect)))
        cropped = h > crop_h * 1.01
        part = im.crop((0, 0, w, crop_h)) if crop_h < h else im
        if part.mode not in ("RGB", "RGBA"):
            part = part.convert("RGBA" if "A" in part.getbands() else "RGB")
        paths, size = [], (0, 0)
        for tier in (1, 2):
            tw = max(1, min(w, round(frame_w * tier)))
            th = max(1, round(crop_h * tw / w))
            rel = f"thumbs/{stem}.{tier}.webp"
            dest = out / rel
            if not (dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime):
                dest.parent.mkdir(parents=True, exist_ok=True)
                part.resize((tw, th), Image.LANCZOS).save(dest, "WEBP", quality=80, method=4)
            paths.append(rel)
            if tier == 1:
                size = (tw, th)
        return paths, size[0], size[1], cropped


def data_for(m: dict, base: Path, out: Path, thumbs: Callable = make_thumbs) -> dict:
    """The page's data for a manifest: sizes filled in, thumbnails made, images copied into `out`."""
    Image = None
    groups = m["groups"]
    for g in groups:
        for b in g.get("boards", []):
            for s in b["shots"]:
                if "width" not in s or "height" not in s:
                    Image = Image or _image()
                    with Image.open(base / s["file"]) as im:
                        s.setdefault("width", im.size[0])
                        s.setdefault("height", im.size[1])
    first = next((s for g in groups for b in g.get("boards", []) for s in b["shots"][:1]), None)
    if first is None:
        height = 300.0
    else:
        aspect = frame_aspect(first)
        width = m.get("board_width") or (480 if aspect <= 1 else 300)
        height = width * aspect
    labels: list[str] = []
    out_groups = []
    captions = False
    for g in groups:
        boards = []
        for b in g.get("boards", []):
            shots = []
            for s in b["shots"]:
                label = s.get("label", "Shot")
                if label not in labels:
                    labels.append(label)
                key = slug(label)
                aspect = frame_aspect(s)
                frame_w = height / aspect
                if out.resolve() != base.resolve():
                    for f in (s["file"], s.get("previous")):
                        if f:
                            dest = out / f
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(base / f, dest)
                stem = re.sub(r"[^A-Za-z0-9._-]+", "-", str(Path(s["file"]).with_suffix("")))
                paths, tw, th, cropped = thumbs(base / s["file"], out, stem, aspect, frame_w)
                shot = {"label": label, "key": key, "file": s["file"], "width": s["width"], "height": s["height"],
                        "thumbs": paths, "thumbW": tw, "thumbH": th, "cropped": cropped}
                if s.get("viewport"):
                    shot["viewport"] = {"width": s["viewport"]["width"], "height": s["viewport"]["height"]}
                for k in ("previous", "change", "diff"):
                    if s.get(k):
                        shot[k] = s[k]
                shots.append(shot)
            board = {"number": b["number"], "title": b.get("title", ""), "shots": shots}
            if b.get("id"):
                board["id"] = b["id"]
            for k, dk in (("caption", "caption"), ("status", "status"), ("error", "error"), ("change", "change"),
                          ("change_label", "changeLabel"), ("change_note", "changeNote")):
                if b.get(k):
                    board[dk] = b[k]
            captions = captions or bool(b.get("caption") or b.get("error"))
            boards.append(board)
        grp = {"name": g["name"], "boards": boards}
        for k, dk in (("id", "id"), ("status", "status"), ("status_label", "statusLabel"), ("note", "note"), ("empty", "empty")):
            if g.get(k):
                grp[dk] = g[k]
        out_groups.append(grp)
    data = {"title": m["title"], "id": m.get("id") or slug(m["title"]), "height": round(height, 2),
            "captionH": CAPTION_H if captions else 0, "labels": labels, "groups": out_groups}
    for k in ("subtitle", "status", "meta", "banner", "comments", "changes"):
        if m.get(k):
            data[k] = m[k]
    data["built"] = _now_iso()
    return data


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SessionUnavailable(Exception):
    """The canvas names a session and the webcompanion daemon could not give one."""


def ensure_session(se: dict, out: Path) -> dict:
    """The live webcompanion session of `se`'s kind and slug, reopened or made if need be, with
    `out` registered as its page. Returns {sid, slug, kind, url}: url is the session's page on its
    devdomains name (https://webcompanion.<machine>…/s/<sid>/) when it has one."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _shared import webcompanion_client as wc  # noqa: WPS433

    kind, slug = se["kind"], se["slug"]
    if os.environ.get("CANVAS_NO_SESSION"):
        raise SessionUnavailable("CANVAS_NO_SESSION is set")
    try:
        rows = wc.all_sessions(kind)
        mine = [r for r in rows if r.get("slug") == slug]
        row = next((r for r in mine if r.get("state", "live") == "live"), None)
        if row is None and mine:
            wc.request("POST", f"/s/{mine[0]['sid']}/api/unfinish")
            row = mine[0]
        if row is None:
            row = wc.request("POST", "/api/sessions", {"kind": kind, "cwd": se["cwd"], "slug": slug,
                                                       "title": se.get("title") or slug})
            if row.get("slug") != slug:
                raise SessionUnavailable(f"asked for {kind} session {slug} and got {row.get('slug')}")
        (out / BOOT).write_text(BOOT_JS)
        wc.register_assets(row["sid"], str(out.resolve()), BOOT, kind=kind)
    except wc.DaemonError as e:
        raise SessionUnavailable(str(e)) from None
    return {"sid": row["sid"], "slug": slug, "kind": kind, "url": public_url(row["sid"])}


def public_url(sid: str) -> str:
    """The session page's link from every machine: webcompanion's devdomains name, else loopback."""
    import shutil
    import subprocess
    base = os.environ.get("WEBCOMPANION_PUBLIC_URL", "")
    if not base:
        tool = shutil.which("@devdomains") or str(Path.home() / "projects" / "env" / "bin" / "@devdomains")
        try:
            base = subprocess.run([tool, "url", "webcompanion"], capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            base = ""
    if not base.startswith("http"):
        base = "http://127.0.0.1:3080"
    return f"{base.rstrip('/')}/s/{sid}/"


def build(manifest: Path, out: Path) -> Path:
    """Write out/index.html (and the images and thumbnails it needs). Returns the page's path."""
    m = json.loads(manifest.read_text())
    base = manifest.resolve().parent
    errs = check(m, base)
    if errs:
        raise ValueError("\n".join(errs))
    out.mkdir(parents=True, exist_ok=True)
    data = data_for(m, base, out)
    se = m.get("session")
    if not se:
        # Comments live only in a canvas's session. A manifest from before sessions (its comments
        # named the journey-comments service, `comments.url`) builds without them.
        data.pop("comments", None)
    if se:
        try:
            data["session"] = {**ensure_session(se, out), "reruns": bool(se.get("reruns"))}
        except SessionUnavailable as e:
            data.pop("comments", None)
            data["banner"] = ((data.get("banner") or "") + " " +
                              f"Built without its webcompanion session ({e}), so it takes no comments.").strip()
        else:
            if data.get("comments") and SPEECH_SDK.is_file():
                (out / "vendor").mkdir(exist_ok=True)
                shutil.copy2(SPEECH_SDK, out / "vendor" / "speech-sdk.min.js")
    page = out / "index.html"
    tmp = page.with_name(f".index.{os.getpid()}.html")
    tmp.write_text(fill(template(), data))
    tmp.replace(page)
    return page
