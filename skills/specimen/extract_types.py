"""Read a class's shape out of a Java checkout and write types.json.

Usage:
    python3 -m skills.specimen.extract_types <ClassName|fully.qualified.Name>
                                             --worktree <path> --out <types.json>

A simple name that matches more than one class is refused with the list, never
resolved by picking one. a large codebase can have five classes called Category.

Exit codes: 0 ok, 2 ambiguous name or no match, 3 provenance check failed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from skills.specimen.emit import ProvenanceError, to_payload, write
from skills.specimen.imports import SourceIndex
from skills.specimen.typegraph import AccessorObserver, build


def head_commit(worktree: str) -> str:
    try:
        done = subprocess.run(['git', '-C', worktree, 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=20)
        return done.stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--worktree', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    if not os.path.isdir(args.worktree):
        print(f'no such worktree: {args.worktree}', file=sys.stderr)
        return 2

    index = SourceIndex.scan(args.worktree)

    if '.' in args.name:
        # Treat as fully-qualified name; do not fall through to simple-name lookup
        if index.has(args.name):
            entry = args.name
        else:
            print(f'no class named {args.name} in {args.worktree}', file=sys.stderr)
            return 2
    else:
        # Bare simple name; ambiguity is an error
        matches = index.by_simple_name(args.name)
        if not matches:
            print(f'no class named {args.name} in {args.worktree}', file=sys.stderr)
            return 2
        if len(matches) > 1:
            print(f'{args.name} is ambiguous; name one of these in full:', file=sys.stderr)
            for fqn in matches:
                print(f'  {fqn}', file=sys.stderr)
            return 2
        entry = matches[0]

    nodes = build(entry, index, AccessorObserver(index))
    payload = to_payload(entry, nodes, args.worktree, head_commit(args.worktree))
    try:
        write(args.out, payload)
    except ProvenanceError as problem:
        print(f'provenance check failed: {problem}', file=sys.stderr)
        return 3

    print(f'{entry} -> {args.out} ({len(nodes)} types)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
