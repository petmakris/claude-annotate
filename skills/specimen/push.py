"""Push a specimen to the webcompanion daemon as a session of kind `specimen`.

Usage:
    python3 -m skills.specimen.push --types <types.json> --specimen <specimen.json>
                                    --cwd <repo root> [--title <title>]
                                    [--leaves <leaves.json>]

Prints the session (`sid`, `slug`, `url`, ...) as JSON and exits 0. Any failure —
an unreadable input, the daemon not installed or not answering, the push refused —
is one line on stderr and exit 1, the same as every other skill's push.

There is no fallback. If the daemon is absent the caller is told, and stops. A
silent downgrade to a plain HTML file would take away the only thing this page has
that a printout does not: you can ask it a question.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.specimen.document import build_items
from skills.specimen.leaves import load as load_leaves

KIND = 'specimen'
STATIC_DIR = Path(__file__).resolve().parent / 'static'
ENTRY = 'entry.js'


def default_title(types_payload: dict) -> str:
    simple = types_payload['root'].rsplit('.', 1)[-1].rsplit('$', 1)[-1]
    return f'{simple} Specimen'


def push(types_payload: dict, specimen: dict, cwd: str,
         title: str | None = None, leaves: dict | None = None) -> dict:
    """Create the session, store the page's items, register its renderer.

    Every push creates a fresh session and `supersede`s the others of this kind
    at `cwd`: a re-push of the same page replaces it. That also closes a page of
    a DIFFERENT class open in the same checkout — SKILL.md says when to ask
    first.
    """
    items = build_items(types_payload, specimen, leaves or {})
    res = wc.create_or_attach(KIND, cwd, title=title or default_title(types_payload),
                              supersede=True)
    sid = res['sid']
    wc.put_items(sid, items, kind=KIND, replace=True)
    # Re-sent on every push so a plugin that has moved on disk since the
    # session was created still resolves, as dataflow and walkthrough do.
    wc.register_assets(sid, str(STATIC_DIR), ENTRY, kind=KIND)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='skills.specimen.push')
    ap.add_argument('--types', required=True, help='extract_types output')
    ap.add_argument('--specimen', required=True, help='the populated instance')
    ap.add_argument('--cwd', required=True, help='repo root the session belongs to')
    ap.add_argument('--title')
    ap.add_argument('--leaves',
                    help='the capture the page names as the source of its '
                         'captured identifiers — normally the project '
                         'profile\'s leaves.json (default: none)')
    a = ap.parse_args(argv)
    try:
        types_payload = json.loads(Path(a.types).read_text(encoding='utf-8'))
        specimen = json.loads(Path(a.specimen).read_text(encoding='utf-8'))
        leaves = load_leaves(a.leaves) if a.leaves else {}
        res = push(types_payload, specimen, a.cwd, a.title, leaves)
    except (OSError, ValueError, KeyError) as e:
        print('specimen push: cannot read the inputs: %s' % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch,
            RuntimeError) as e:
        print('specimen push: %s' % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
