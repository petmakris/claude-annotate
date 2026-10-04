#!/usr/bin/env python3
"""Paste the framework and a theme into a deck as snapshots the deck owns.

    python3 inline.py DECK.html                  # fill or refresh every block
    python3 inline.py DECK.html --theme NAME     # use this theme instead of the configured one
    python3 inline.py DECK.html --theme PATH     # a theme directory anywhere on disk
    python3 inline.py DECK.html --check          # exit 1 if the deck has no framework markers
    python3 inline.py --which-theme              # print the theme that would be used, and why

The deck carries these marker pairs (the skeleton has all of them):

    <!-- framework:css -->...<!-- /framework:css -->   framework/deck.css
    <!-- theme:css -->...<!-- /theme:css -->           <theme>/theme.css
    <!-- theme:logo -->...<!-- /theme:logo -->         <theme>/logo.svg, if the theme has one
    <!-- framework:js -->...<!-- /framework:js -->     framework/deck.js

Whatever sits between a pair is replaced, with a one-line comment recording the
version, theme and date. A deck made before themes existed has no theme:css pair;
one is inserted right after /framework:css. Run this once when a deck is created,
and again only when you deliberately want that deck to adopt the current framework
or a different theme.

A theme is a directory holding `theme.css` (required: the tokens and any per-theme
rules), and optionally `logo.svg` (drawn top right on the cover) and `README.md`
(notes on the theme's own components). Which theme is used, first match wins:

    1. --theme on the command line
    2. $SLIDES_THEME
    3. "theme" in ~/.config/slides/config.json   ($XDG_CONFIG_HOME is honoured)
    4. default, shipped beside this file in ../themes/default

A theme name is looked up in ~/.config/slides/themes/<name>/ first, then in the
themes this skill ships.
"""
from __future__ import annotations

import datetime
import os
import pathlib
import re
import sys

from slides_config import config_dir, config_path, load_config

HERE = pathlib.Path(__file__).resolve().parent
SHIPPED = HERE.parent / "themes"


def find_theme(requested: str | None) -> tuple[pathlib.Path, str]:
    """The theme directory to use, and a few words on why it was chosen."""
    if requested:
        name, why = requested, "--theme"
    elif os.environ.get("SLIDES_THEME"):
        name, why = os.environ["SLIDES_THEME"], "$SLIDES_THEME"
    elif load_config().get("theme"):
        name, why = str(load_config()["theme"]), str(config_path())
    else:
        name, why = "default", "no theme configured"

    as_path = pathlib.Path(os.path.expanduser(name))
    candidates = [as_path] if ("/" in name or name.startswith(".")) else [
        config_dir() / "themes" / name, SHIPPED / name]
    for directory in candidates:
        if (directory / "theme.css").is_file():
            return directory, why
    looked = ", ".join(str(c) for c in candidates)
    raise SystemExit(f"theme {name!r} (from {why}) not found: no theme.css in {looked}")


def framework_block(kind: str, version: str) -> str:
    src = (HERE / ("deck.css" if kind == "css" else "deck.js")).read_text()
    tag = "style" if kind == "css" else "script"
    today = datetime.date.today().isoformat()
    note = (f"<!-- framework:{kind} snapshot v{version} ({today}). This deck owns this copy: "
            f"edit it here for this deck only. -->")
    return f"<!-- framework:{kind} -->\n{note}\n<{tag}>\n{src.rstrip()}\n</{tag}>\n<!-- /framework:{kind} -->"


def theme_block(theme: pathlib.Path) -> str:
    today = datetime.date.today().isoformat()
    note = (f"<!-- theme:css snapshot of '{theme.name}' ({today}). This deck owns this copy; "
            f"change the look here or pick another theme with inline.py --theme. -->")
    css = (theme / "theme.css").read_text().rstrip()
    return f"<!-- theme:css -->\n{note}\n<style>\n{css}\n</style>\n<!-- /theme:css -->"


def logo_block(theme: pathlib.Path) -> str:
    logo = theme / "logo.svg"
    body = logo.read_text().strip() if logo.is_file() else ""
    return f"<!-- theme:logo -->{body}<!-- /theme:logo -->"


def pattern(name: str) -> re.Pattern:
    return re.compile(rf"<!-- {name} -->.*?<!-- /{name} -->", re.S)


def main(argv: list[str]) -> int:
    args = argv[1:]
    requested = None
    if "--theme" in args:
        i = args.index("--theme")
        if i + 1 >= len(args):
            print("--theme needs a name or a path", file=sys.stderr)
            return 2
        requested = args[i + 1]
        del args[i:i + 2]
    if "--which-theme" in args:
        theme, why = find_theme(requested)
        print(f"{theme}  ({why})")
        return 0
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if not args:
        print(__doc__)
        return 2

    deck = pathlib.Path(args[0])
    html = deck.read_text()
    version = (HERE / "VERSION").read_text().strip()
    for kind in ("css", "js"):
        if not pattern(f"framework:{kind}").search(html):
            print(f"{deck}: no framework:{kind} markers", file=sys.stderr)
            return 1
    if check:
        return 0

    theme, why = find_theme(requested)
    for kind in ("css", "js"):
        html = pattern(f"framework:{kind}").sub(lambda _m, k=kind: framework_block(k, version), html, count=1)
    if not pattern("theme:css").search(html):
        html = html.replace("<!-- /framework:css -->", "<!-- /framework:css -->\n<!-- theme:css --><!-- /theme:css -->", 1)
    html = pattern("theme:css").sub(lambda _m: theme_block(theme), html, count=1)
    html = pattern("theme:logo").sub(lambda _m: logo_block(theme), html)
    deck.write_text(html)
    print(f"{deck}: framework v{version} inlined, theme '{theme.name}' ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
