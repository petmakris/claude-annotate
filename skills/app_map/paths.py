"""The path matcher: GitHub CODEOWNERS rules, used for parts and for CODEOWNERS alike.

A path is repo-relative, with no leading slash, and names a file. Java has a copy (AppMapPaths); both run
every case of tests/match_cases.json, so they cannot drift.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import List, Optional


@lru_cache(maxsize=4096)
def _regex(pattern: str) -> "re.Pattern[str]":
    folder = pattern.endswith("/")
    anchored = pattern.startswith("/") or "/" in pattern[:-1]
    core = pattern.strip("/")
    last = core.rsplit("/", 1)[-1]
    below = core.endswith("/**")
    out = []
    i = 0
    while i < len(core):
        c = core[i]
        if core.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif core.startswith("/**", i) and i + 3 == len(core):
            out.append("/.*")
            i += 3
        elif core.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    if folder:
        tail = "/.+$"
    elif below or (last == "*" and not folder):
        tail = "$"
    else:
        tail = "(?:/.*)?$"
    head = "^" if anchored else "^(?:.*/)?"
    return re.compile(head + "".join(out) + tail, re.S)


def matches(pattern: str, path: str) -> bool:
    return _regex(pattern).match(path) is not None


def last_match(rules: List[str], path: str) -> Optional[int]:
    """The index of the last rule that matches, or None."""
    for i in range(len(rules) - 1, -1, -1):
        if matches(rules[i], path):
            return i
    return None
