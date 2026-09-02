"""Push a deck's current content to the webcompanion daemon.

Replaces the old flow — a per-skill server on a fixed port, reading the deck
file off disk on every request. There is no deck server any more: the
daemon owns the session, and this module is the only thing that knows how a
deck maps onto it.

The mapping:
    __model__    parse_deck()'s output, plus the deck's own absolute path —
                 what deck.js renders, and what Claude needs back out of a
                 comment event to know which file to edit. An earlier version
                 of this module dropped that path as "locally-meaningless" to
                 the browser, which was true but beside the point: SKILL.md's
                 event handler is the one thing that reads it, and there is no
                 other place for it to live once server.py's meta.json is
                 gone. Correction, not a re-add for its own sake.

The deck's raw HTML is not pushed as an item (items cap at 2MB; real decks
run to tens of megabytes) — it is copied, under a fixed name, into a
directory this module controls and registers as the session's asset root,
alongside this skill's own static JS/CSS. Re-copied on every push, including
after every edit, which is also this design's change-notification signal:
`__model__`'s version changes each push, and the browser reacts to that
item's `item-changed` delta to reload — see skills/deck/static/entry.js and
docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md's
`deck (Phase 2)` section for the full reasoning.

Usage:
    python3 -m skills.deck.push --deck <path> --cwd <repo root>
                                [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.deck import model as model_module

KIND = "deck"
MODEL_ANCHOR = "__model__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"
DECK_COPY_NAME = "content.html"
# Every plugin-owned static file that must be reachable from the copy
# directory alongside the deck itself. Kept as an explicit list, not a
# directory copy, so a stray file added to skills/deck/static/ later
# (a scratch file, an editor swapfile) is never silently shipped into a
# session's asset root.
#
# core.css/fonts/*: deck.css itself declares none of the custom properties
# it uses (--surface, --border, --text, --accent, etc.) — they only exist
# under core.css's :root, so deck's page renders with no borders/colors at
# all (a silently-invalid `var()`, not an error) without it. This is the
# same "canonical source, per-skill copy" pattern wc-threads.js/
# markdown-it.min.js already established in Phase 1: skills/deck/static/
# core.css is a checked-in copy of skills/_shared/web_companion/static/
# core.css with its two @font-face URLs relativized (fonts/... rather than
# /static/fonts/..., which no route under the daemon serves), matching the
# fix skills/annotate/static/core.css already made for the same reason.
PLUGIN_ASSETS = [
    "entry.js", "deck.js", "deck.css", "core.css",
    "fonts/MonaspaceRadon-Regular.woff2",
    "fonts/BricolageGrotesque-Variable.woff2",
]


def _resolve_deck(raw: str) -> Path:
    # Resolve BEFORE checking the suffix — see server.py's own comment on
    # this ordering, which this replicates: checking the supplied path's
    # suffix would let a symlink named `deck.html` pointing at a non-html
    # file through, and every read under a session's /s/<slug>/ is ungated
    # by design.
    deck = Path(raw).expanduser().resolve()
    if not deck.is_file():
        raise ValueError(f"deck not found: {deck}")
    if deck.suffix.lower() != ".html":
        raise ValueError(f"deck must be an .html file (resolved to {deck.name}): {deck}")
    return deck


def _copy_dir_for(sid: str) -> Path:
    d = Path(tempfile.gettempdir()) / "claude-deck-assets" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _refresh_copy_dir(copy_dir: Path, deck: Path) -> None:
    for name in PLUGIN_ASSETS:
        dest = copy_dir / name
        # PLUGIN_ASSETS now carries a nested path (fonts/*.woff2); shutil
        # .copyfile does not create the parent directory for us the way a
        # flat top-level name never needed one to.
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC_DIR / name, dest)
    shutil.copyfile(deck, copy_dir / DECK_COPY_NAME)


def push(deck_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    deck = _resolve_deck(str(deck_path))
    title = title or deck.stem

    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug)
    sid = res["sid"]

    copy_dir = _copy_dir_for(sid)
    _refresh_copy_dir(copy_dir, deck)

    model = model_module.parse_deck(deck.read_text(encoding="utf-8"))
    # Browser-irrelevant, Claude-relevant: deck.js never reads this key, but
    # SKILL.md's comment-event handler does, via the envelope deck.js's
    # submit() copies it into. See the module docstring's mapping note.
    model["deck"] = str(deck)
    wc.put_items(sid, {MODEL_ANCHOR: model}, kind=KIND, replace=True)

    # Re-sent on every push — the copy directory's content.html just changed,
    # and re-registering is idempotent (same reasoning as Phase 1's push.py).
    wc.register_assets(sid, str(copy_dir), ENTRY, kind=KIND)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.deck.push")
    ap.add_argument("--deck", required=True, help="path to the deck .html")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.deck), a.cwd, a.slug, a.title)
    except ValueError as e:
        print("deck push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("deck push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
