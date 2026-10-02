"""Push an annotate document to the webcompanion daemon.

Replaces the old flow — start a per-skill server, create a workspace, write
blocks.json into a directory the server happens to watch. There is no
annotate server any more: the daemon owns storage, comment threads and the
event queue, and this module is the only thing that knows how an annotate
document maps onto it.

The mapping, which is the whole contract between this file and the page's
compat.js:

    __doc__          {response_id, title, glossary, order: [block ids],
                      pushed: {block id: sha256 of the markdown this push wrote}}
    <block id>       one rendered block body (see render.render_block)
    __prev__         the previous __doc__ + blocks, for the "what changed" pane

Usage:
    python3 -m skills.annotate.push --blocks <blocks.json> --cwd <repo root>
                                    [--slug <slug>] [--title <title>]
                                    [--eval | --json]

Without --slug a new session is created. With it, the push lands on that
existing session or fails; it never quietly creates a second page beside the
one the reader has open.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import os
import re
import socket
import sys
import time
import urllib.error
from html.parser import HTMLParser
import urllib.request
from pathlib import Path

from skills.annotate import blocks as blocks_model
from skills.annotate import session as session_mod
from skills.annotate.confluence.markdown_html import UnsupportedMarkdown, to_html
from skills.annotate.render import render_block
from .progress import ANCHOR as PROGRESS_ANCHOR

CONTRACT = 1
KIND = "annotate"
DOC_ANCHOR = "__doc__"
PREV_ANCHOR = "__prev__"
# The sections the reader has open in the editor (edit.js), as
# {block_id: {opened_at, heartbeat_at, tab}} in epoch seconds.
HOLDS_ANCHOR = "__holds__"
# A hold whose heartbeat is older than this is a tab that died without
# releasing it, and everyone ignores it.
HELD_STALE_S = 1800
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"


class DaemonError(RuntimeError):
    pass


class PushError(RuntimeError):
    """The push was refused before anything was sent."""


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _config() -> dict:
    path = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))
    if not path.exists():
        raise DaemonError(
            "webcompanion is not configured on this machine "
            "(~/.claude/webcompanion/config.json is missing).\n"
            "  pipx install webcompanion && webcompanion install-service")
    return json.loads(path.read_text())


def _request(cfg: dict, method: str, path: str, body=None) -> dict:
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        if e.code == 426:
            raise DaemonError("contract mismatch: %s" % detail) from None
        raise DaemonError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise DaemonError(
            "cannot reach the webcompanion daemon on port %s (%s).\n"
            "  webcompanion status   # is the service running?\n"
            "  webcompanion doctor   # full check"
            % (cfg["port"], e.reason)) from None
    return json.loads(raw) if raw.strip() else {}


def items_for(doc: blocks_model.BlocksDoc, cwd: str) -> dict:
    """The full item set for a document — the exact body of a `replace` push."""
    items = {
        DOC_ANCHOR: {
            "response_id": doc.response_id,
            "title": doc.title,
            "glossary": list(doc.glossary),
            "order": [b["id"] for b in doc.blocks],
            # The repo root, so the page can offer "open this in my editor"
            # for a code anchor. The page shows the control to an owner only.
            "cwd": cwd,
        }
    }
    for blk in doc.blocks:
        items[blk["id"]] = render_block(blk)
    return items


def _existing_items(cfg: dict, sid: str) -> dict:
    try:
        snap = _request(cfg, "GET", "/s/%s/items?kind=%s" % (sid, KIND))
    except DaemonError:
        return {}
    return {a: v.get("body") for a, v in snap.items() if isinstance(v, dict)}


def _item_versions(cfg: dict, sid: str) -> dict:
    """{anchor: version} as stored now. Read after the bodies, so a save
    between the two reads makes the version newer than the body, never
    older: a `base` from before that save then no longer matches."""
    try:
        snap = _request(cfg, "GET", "/s/%s/items?kind=%s" % (sid, KIND))
    except DaemonError:
        return {}
    return {a: v.get("version") for a, v in snap.items() if isinstance(v, dict)}


def held_blocks(prev: dict, now: int) -> set:
    """The block ids a reader holds open, from the stored item bodies."""
    holds = prev.get(HOLDS_ANCHOR)
    if not isinstance(holds, dict):
        return set()
    out = set()
    for bid, h in holds.items():
        if not isinstance(bid, str) or bid.startswith("__"):
            continue        # never a section: __doc__, __holds__ itself
        try:
            if now - int(h.get("heartbeat_at", 0)) <= HELD_STALE_S:
                out.add(bid)
        except (TypeError, ValueError, AttributeError):
            continue
    return out


# ── the reader's words (`mine`) ─────────────────────────────────────────────
# edit.js stores `mine` as text anchors over the RENDERED prose of a section
# (AnnotateAnchors.textOf of markdown-it's output). Claude's working
# blocks.json never has them, so a push carries the stored ones forward; but
# only an anchor whose words AND full stored context still read the same in
# the new text. One that does not is dropped rather than left to land on
# Claude's rewritten copy of the same words.

# Where markdown-it puts a newline between elements, so where the page's text
# has whitespace. Inline marks (<strong>, <code>, <a>) add none.
_BLOCK_TAGS = {"p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
               "blockquote", "table", "thead", "tbody", "tr", "th", "td", "hr", "br"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_data(self, data):
        self.out.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.out.append("\n")


_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?\s*/?\s*>")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")


def rendered_text(md: str) -> str:
    """A section's markdown as the page reads it, near enough to compare
    whitespace-insensitively.

    There is no markdown-it in Python, so this is the plugin's own converter
    (confluence/markdown_html.py, the subset annotate's markdown is written
    in) with its tags stripped. Where that converter refuses (raw HTML, an
    image) the markup is set aside and the words converted.

    Known approximations: backslash escapes and entities (`&amp;`) are
    undone everywhere, code spans included; markers markdown-it reads that
    this subset does not (`_x_` emphasis, autolinks, a setext underline)
    stay in the text. Each mostly costs an anchor its carry-forward (the
    green rule disappears) rather than placing one wrongly."""
    try:
        html = to_html(md)
    except UnsupportedMarkdown:
        # Raw HTML and images are what it refuses most: their words (an
        # image's alt text) are kept, their markup set aside, and the rest
        # converted as usual.
        bare = _IMAGE.sub(r"\1", _TAG.sub("", md))
        try:
            html = to_html(bare)
        except UnsupportedMarkdown:
            html = bare
    p = _Text()
    p.feed(html)
    p.close()
    return html_mod.unescape(_ESCAPED.sub(r"\1", "".join(p.out)))


# The page keeps this much context either side of an anchor (anchors.js),
# counted in UTF-16 units as JavaScript counts. Shorter means the block's
# edge cut it.
CONTEXT = 32


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _anchor_pattern(a: dict):
    """A regex for the anchor's words with their full stored context.

    Whitespace-insensitive (any run matches any run, since the page's text
    and this render disagree on newlines between blocks) but never
    whitespace-blind: words separated in the anchor must be separated in the
    text, so "the rapist" does not match "therapist". A context shorter than
    CONTEXT was cut by the block's edge, so the match must reach that edge:
    words that opened the section must still open it."""
    pre, sel, suf = str(a.get("prefix") or ""), a["selected_text"], str(a.get("suffix") or "")
    if not sel.split():
        return None
    body = r"\s+".join(re.escape(t) for t in (pre + sel + suf).split())
    start = r"\A\s*" if _u16(pre) < CONTEXT else ""
    end = r"\s*\Z" if _u16(suf) < CONTEXT else ""
    return re.compile(start + body + end)


def _surviving(mine, md: str) -> list:
    if not isinstance(mine, list):
        return []
    text = rendered_text(md)
    out = []
    for a in mine:
        if not (isinstance(a, dict) and isinstance(a.get("selected_text"), str)):
            continue
        pat = _anchor_pattern(a)
        if pat and pat.search(text):
            out.append(a)
    return out


def _keep_mine(items: dict, prev: dict, skip: set) -> None:
    """Carry or filter `mine` on every markdown block of the push, naming on
    stderr every passage of the reader's that the push dropped."""
    for bid, body in items.items():
        if bid.startswith("__") or bid in skip or not isinstance(body, dict):
            continue
        if body.get("kind", "markdown") != "markdown":
            body.pop("mine", None)
            continue
        old = prev.get(bid) if isinstance(prev.get(bid), dict) else {}
        mine = body["mine"] if "mine" in body else old.get("mine")
        kept = _surviving(mine, body.get("markdown", ""))
        for a in mine if isinstance(mine, list) else []:
            if a not in kept and isinstance(a, dict) and isinstance(a.get("selected_text"), str):
                print('your change dropped the reader\'s words in %s: "%s"'
                      % (bid, a["selected_text"]), file=sys.stderr)
        if kept:
            body["mine"] = kept
        else:
            body.pop("mine", None)


def md_hash(md) -> str:
    """The hash `pushed` and `base` compare: sha256 of the markdown's UTF-8."""
    return hashlib.sha256(str(md).encode("utf-8")).hexdigest()


def edited_since_push(items: dict, prev: dict, bases: dict, versions: dict,
                      skip: set) -> set:
    """The sections the reader saved an edit to since Claude's last push,
    which this push would overwrite with text not built on it, or delete.

    Each push records in __doc__ the hash of the markdown it wrote (`pushed`).
    A stored section whose markdown no longer has that hash was edited by the
    reader. Claude's copy replaces it only when it is that same text, or when
    Claude built on exactly the stored item: `base`, which pull writes, is
    the item's version, and every save bumps it, so a base is spent by the
    reader's next save even when that save restores the pulled words. A
    section Claude left out is kept whenever the reader edited it. A section
    with no recorded push is not guarded: a first push, or a session pushed
    before `pushed` existed."""
    doc = prev.get(DOC_ANCHOR)
    pushed = doc.get("pushed") if isinstance(doc, dict) else None
    if not isinstance(pushed, dict):
        return set()
    out = set()
    for bid, old in prev.items():
        if bid.startswith("__") or bid in skip or bid not in pushed:
            continue
        if not (isinstance(old, dict) and isinstance(old.get("markdown"), str)):
            continue
        if md_hash(old["markdown"]) == pushed[bid]:
            continue                      # not edited since Claude wrote it
        body = items.get(bid)
        if not isinstance(body, dict):
            out.add(bid)                  # Claude left it out
            continue
        base = bases.get(bid)
        built_on = base is not None and versions.get(bid) is not None and base == versions[bid]
        if body.get("markdown") != old["markdown"] and not built_on:
            out.add(bid)
    return out


def resolve_slug(cfg: dict, slug: str) -> dict:
    """The session row for an annotate slug, from ANY cwd.

    This used to filter by `--cwd`, so a push from any directory other than the
    one the session was created in (a resume from elsewhere, a `cd` earlier in
    the turn) found nothing, fell through to creating a new session, and the
    reader's page never changed. The slug alone names the session: slugs are
    unique within a kind."""
    rows = _request(cfg, "GET", "/api/sessions?scope=all")
    for row in (rows if isinstance(rows, list) else rows.get("sessions", [])):
        if row.get("kind") == KIND and row.get("slug") == slug:
            return row
    raise PushError(
        "no annotate session has the slug %r. Check it against "
        "`claude-annotate session show`; to start a new page "
        "instead, push without --slug." % slug)


def share_host(cfg: dict) -> str | None:
    """A host another machine can reach the daemon at, or None.

    The daemon only knows the address a request arrived on, so from here that
    is always loopback, which no colleague or phone can open. When it listens
    beyond loopback, this machine's own name is the address that works."""
    if str(cfg.get("bind", "127.0.0.1")) in LOOPBACK:
        return None
    return socket.gethostname() or None


def push(blocks_path: Path, cwd: str, slug: str | None = None,
         title: str | None = None) -> dict:
    # Everything that can be refused is refused before the daemon is touched:
    # the push replaces the stored page wholesale, so a bad input that got as
    # far as the PATCH would empty the page the reader has open.
    if slug is not None and not slug.strip():
        raise PushError("--slug is empty. Pass the literal slug of the page "
                        "(it is printed by the first push and recorded by "
                        "`claude-annotate session show`), or omit "
                        "--slug to create a new page.")
    doc = blocks_model.load(blocks_path)
    if not doc.blocks:
        raise PushError(
            "%s has no blocks. Pushing it would replace the page with an "
            "empty one, so nothing was sent." % blocks_path)
    cfg = _config()
    title = title or doc.title or "Response"

    created = False
    if slug:
        sid = resolve_slug(cfg, slug)["sid"]
    else:
        res = _request(cfg, "POST", "/api/sessions",
                       {"kind": KIND, "cwd": cwd, "title": title})
        sid, slug, created = res["sid"], res["slug"], True

    items = items_for(doc, cwd)

    # The pre-round snapshot the diff pane reads. Written from what is
    # currently stored, BEFORE the replace lands — the old server kept this
    # by copying blocks.json on every mutating event, and losing it would
    # silently kill the "what changed since you commented" marks.
    prev = _existing_items(cfg, sid)
    trail = prev.pop(PROGRESS_ANCHOR, None)
    prev.pop(PREV_ANCHOR, None)

    # The one choke point every Claude section write goes through: a section
    # the reader has open in the editor is theirs. Their stored version stands
    # (a section Claude dropped stays too, where it was), the hold itself
    # survives the replace, and Claude is told to fold its change into the
    # next round. `prev` holds item bodies (_existing_items unwraps them).
    holds = prev.pop(HOLDS_ANCHOR, None)
    held = held_blocks({HOLDS_ANCHOR: holds}, int(time.time())) & set(prev)
    order = items[DOC_ANCHOR]["order"]
    old_order = (prev[DOC_ANCHOR].get("order") or []) if isinstance(prev.get(DOC_ANCHOR), dict) else []

    def keep_theirs(bid):
        """The stored section stands, where it was if Claude dropped it."""
        items[bid] = prev[bid]
        if bid not in order:
            at = len(order)
            if bid in old_order:
                # After the nearest earlier section still on the page.
                at = 0
                for o in reversed(old_order[:old_order.index(bid)]):
                    if o in order:
                        at = order.index(o) + 1
                        break
            order.insert(at, bid)

    for bid in sorted(held):
        keep_theirs(bid)
    if holds is not None:
        items[HOLDS_ANCHOR] = holds

    # A section the reader saved since Claude's last push, which Claude's
    # working copy predates or left out: kept like a held one, `mine` and
    # all. `base` (the item version pull read) is how a push built on the
    # stored version says so; it is never stored (render_block's allowlist
    # already leaves it out).
    bases = {b["id"]: b["base"] for b in doc.blocks
             if isinstance(b.get("base"), int) and not isinstance(b.get("base"), bool)}
    versions = _item_versions(cfg, sid) if bases else {}
    edited = edited_since_push(items, prev, bases, versions, held)
    for bid in sorted(edited, key=lambda b: old_order.index(b) if b in old_order else len(old_order)):
        keep_theirs(bid)
    kept_theirs = held | edited

    # What this push wrote, per markdown section. A section kept as the
    # reader's carries Claude's last recorded hash forward, so the next stale
    # push is refused too; keeping their text is not Claude writing it.
    old_doc = prev.get(DOC_ANCHOR) if isinstance(prev.get(DOC_ANCHOR), dict) else {}
    old_pushed = old_doc.get("pushed") if isinstance(old_doc.get("pushed"), dict) else {}
    pushed = {}
    for bid, body in items.items():
        if bid.startswith("__") or not isinstance(body, dict):
            continue
        if bid in kept_theirs:
            if bid in old_pushed:
                pushed[bid] = old_pushed[bid]
            elif isinstance(body.get("markdown"), str):
                pushed[bid] = md_hash(body["markdown"])
        elif isinstance(body.get("markdown"), str):
            pushed[bid] = md_hash(body["markdown"])
    items[DOC_ANCHOR]["pushed"] = pushed

    _keep_mine(items, prev, kept_theirs)
    if held:
        print("held by the reader: %s — kept their version; "
              "fold your change into the next round" % ", ".join(sorted(held)),
              file=sys.stderr)
    if edited:
        print("edited by the reader since your last push: %s — kept their version; "
              "pull first, then fold your change in" % ", ".join(sorted(edited)),
              file=sys.stderr)
    if prev:
        items[PREV_ANCHOR] = prev
    # The narration trail survives the replace for the same reason __prev__
    # does, and a sharper one: this push IS the answer landing, which is
    # exactly when the reader looks at how it was reached.
    if trail is not None:
        items[PROGRESS_ANCHOR] = trail

    # `keep`: the daemon leaves these alone, decided under its write lock, so
    # a save or a release the page makes between the read above and this
    # PATCH is not reverted by the copies sent here. The copies still go: a
    # daemon that predates `keep` ignores it, and then at least writes the
    # reader's version back rather than deleting the section.
    # __holds__ always: a tab may create it after the read.
    keep = sorted(kept_theirs | {HOLDS_ANCHOR})
    _request(cfg, "PATCH", "/s/%s/items?kind=%s" % (sid, KIND),
             {"items": items, "replace": True, "keep": keep})

    # Register the page. Idempotent, and re-sent on every push so a plugin
    # that has moved on disk since the session was created still resolves.
    _request(cfg, "POST", "/s/%s/api/assets?kind=%s" % (sid, KIND),
             {"static_root": str(STATIC_DIR), "entry": ENTRY})

    port = int(cfg["port"])
    host = share_host(cfg)
    share = "http://%s:%d/s/%s/" % (host, port, slug) if host else None
    result = {
        "sid": sid,
        "slug": slug,
        "created": created,
        "kind": KIND,
        "localhost_url": "http://localhost:%d/s/%s/" % (port, slug),
        # Read-only for anyone else; None when the daemon only listens on
        # loopback, because then no other machine can open any URL at all.
        "url": share,
        # Carries the write token. Never announce it unasked.
        "owner_url": share + "#k=" + cfg.get("token", "") if share else None,
        "blocks": len(doc.blocks),
    }
    # The marker is what the next Bash call (or the next turn, or a compacted
    # context) reads the sid, slug and working file back from. Losing it costs
    # a lookup, not the push, so a failure to write it is only reported.
    try:
        session_mod.record({"sid": sid, "slug": slug, "cwd": cwd, "title": title,
                            "blocks": str(Path(blocks_path).resolve())})
    except OSError as e:
        print("annotate push: pushed, but could not record the session in the "
              "conversation marker (%s)" % e, file=sys.stderr)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.push")
    ap.add_argument("--blocks", required=True, help="path to blocks.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--eval", action="store_true",
                     help="print WC_SID=, WC_SLUG=, WC_URL= and, when the daemon "
                          "is reachable from other machines, WC_SHARE_URL=")
    out.add_argument("--json", action="store_true",
                     help="print the full result as JSON (the default)")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.blocks), a.cwd, a.slug, a.title)
    except (DaemonError, PushError, ValueError) as e:
        # ValueError covers every refusal blocks.load raises: a missing or
        # unparseable file, an unknown kind, content under the wrong key.
        print("annotate push: %s" % e, file=sys.stderr)
        print("annotate push: nothing was changed on the page.", file=sys.stderr)
        return 1
    if a.eval:
        print("WC_SID=%s" % res["sid"])
        print("WC_SLUG=%s" % res["slug"])
        print("WC_URL=%s" % res["localhost_url"])
        if res["url"]:
            print("WC_SHARE_URL=%s" % res["url"])
    else:
        print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
