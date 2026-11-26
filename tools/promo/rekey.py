# /// script
# requires-python = ">=3.9"
# ///
"""rekey.py: swap names, paths and ids in a captured file, and nothing else.

A real run on made-up data can still print a scratch path or a host name.
rekey.py replaces only the strings a mapping file names, longest first, and
then checks that none of the old strings is left. Counts, times and exit codes
are never touched: a mapping that would change a digit-only string is refused.

    uv run tools/promo/rekey.py map.txt in.cast [out.cast]     # out defaults to in (in place)
    uv run tools/promo/rekey.py --check map.txt file...         # exit 1 when an old string is left

map.txt holds one swap per line, `old => new`; blank lines and `#` lines are
skipped. `{SCRATCH}` and `{HOME}` in an old string stand for the current
folder's `.scratch` path and $HOME, so a mapping file stays the same on every
machine:

    {SCRATCH}/work/acme-billing => /work/acme-billing
    {HOME} => /home/dana
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def load_map(path) -> list[tuple[str, str]]:
    subs = {"{SCRATCH}": str(Path(".scratch").resolve()), "{HOME}": os.path.expanduser("~")}
    pairs = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" not in line:
            sys.exit(f"rekey.py: {path}:{n}: no '=>' in the line")
        old, new = (s.strip() for s in line.split("=>", 1))
        for k, v in subs.items():
            old = old.replace(k, v)
        if not old:
            sys.exit(f"rekey.py: {path}:{n}: empty old string")
        if re.fullmatch(r"[\d.:,\s]+", old):
            sys.exit(f"rekey.py: {path}:{n}: '{old}' is only digits; numbers stay as the run printed them")
        pairs.append((old, new))
    # Longest first, so a path is swapped before a word inside it.
    return sorted(pairs, key=lambda p: -len(p[0]))


def rekey_text(text: str, pairs) -> str:
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def leftovers(text: str, pairs) -> list[str]:
    return [old for old, new in pairs if old in text and old not in new]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="only report old strings still present")
    ap.add_argument("map")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    pairs = load_map(a.map)
    if a.check:
        bad = 0
        for f in a.files:
            for old in leftovers(Path(f).read_text(errors="replace"), pairs):
                print(f"{f}: still holds {old!r}")
                bad += 1
        sys.exit(1 if bad else 0)
    if len(a.files) > 2:
        ap.error("give one input and at most one output")
    src = Path(a.files[0])
    dst = Path(a.files[1]) if len(a.files) == 2 else src
    out = rekey_text(src.read_text(), pairs)
    left = leftovers(out, pairs)
    if left:
        sys.exit(f"rekey.py: still holds {left!r} after the swap")
    dst.write_text(out)
    print(f"rekey.py: {len(pairs)} swaps applied to {dst}")


if __name__ == "__main__":
    main()
