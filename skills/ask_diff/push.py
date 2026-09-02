"""Push a PR's diff and metadata to the webcompanion daemon.

Replaces the old flow -- a per-skill server that snapshotted the diff into
`diff.patch`/`meta.json` on disk at session-create time
(`ask_diff/server.py`'s `create_session_extra`). There is no ask_diff server
any more: the daemon owns storage, comment threads and the event queue, and
this module is the only thing that knows how a PR review maps onto it.

The mapping:

    __diff__    raw unified diff text, exactly as `diff.fetch_pr_diff` returns it
    __meta__    pr_ref, title, head, base, author, url, head_oid, fetched_at
                -- the same field set the old meta.json carried

The daemon `kind` for this skill is the literal string "interactive-review",
not "ask_diff" -- the rename that gave this skill its module path and its
`/ask-diff` command name deliberately left the wire identifier alone, since
changing it needs the separately-installed webcompanion daemon and the
shipped plugin .zip released together, unlike the command name. See
`skills/ask_diff/SKILL.md`'s header note and this phase's plan's Global
Constraints.

Supersede scope: `create_or_attach(..., supersede=True)` cancels every other
live `(kind, cwd)` session, same mechanism `skills/walkthrough/push.py` uses.
The pre-daemon server instead superseded by Claude conversation
(`supersede_by_claude_session = True`, regardless of cwd) specifically to
prevent forgotten-cleanup watcher leaks. The shared client's `create_or_attach`
has no claude-session-scoped supersede at all -- the daemon's session rows
(`server.py`'s `_row()`) carry no `claude_session_id` field and nothing echoes
`create_or_attach`'s request body back for later lookup, so cross-cwd
tracking by Claude session is not possible today without a daemon change,
which is out of scope for this branch. `(kind, cwd)`-scoped `supersede=True`
is therefore the only available mechanism, not a preference among options --
confirmed against the daemon's real source during this phase's plan review
(see the plan's Task 1 Step 1 and Global Constraints). This reopens the
watcher-leak risk the original per-Claude-session supersede was built to
prevent: two PR reviews opened concurrently in different repos from the same
Claude conversation no longer auto-cancel each other. See this phase's Known
Limitations section and the program's separate session-leak initiative.

`claude_session_id` stays a required parameter/CLI flag for interface
symmetry with the old server's payload shape (and so `SKILL.md`'s
`--claude-session-id` invocation needs no special-casing) but is accepted
and otherwise unused here -- there is nowhere on the daemon's side to put it
today, per the ruling above.

Usage:
    python3 -m skills.ask_diff.push --pr <ref> --cwd <repo root>
                                    --claude-session-id <id> [--slug <slug>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from skills._shared import webcompanion_client as wc
from skills.ask_diff import diff as diff_module

KIND = "interactive-review"
DIFF_ANCHOR = "__diff__"
META_ANCHOR = "__meta__"

WARN_DIFF_BYTES = 1 * 1024 * 1024   # soft warning surfaced to the caller
MAX_DIFF_BYTES = 5 * 1024 * 1024    # hard reject -- review a narrower PR


def push(pr_ref: str, cwd: str, claude_session_id: str, *,
        slug: str | None = None) -> dict:
    try:
        diff_text, meta = diff_module.fetch_pr_diff(pr_ref, cwd)
    except Exception as e:
        raise ValueError(f"gh pr fetch failed: {e}") from e

    diff_bytes = len(diff_text.encode("utf-8"))
    if diff_bytes > MAX_DIFF_BYTES:
        raise ValueError(
            f"diff is {diff_bytes // 1024} KB, over the "
            f"{MAX_DIFF_BYTES // (1024 * 1024)} MB limit -- review a narrower "
            "PR, a single commit, or a branch with fewer changes"
        )

    title = meta.get("title", pr_ref)

    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug, supersede=True)
    sid = res["sid"]

    meta_item = {
        "pr_ref": pr_ref,
        "title": title,
        "head": meta.get("headRefName", ""),
        "base": meta.get("baseRefName", ""),
        "author": (meta.get("author") or {}).get("login", ""),
        "url": meta.get("url", ""),
        "head_oid": meta.get("headRefOid", ""),
        "fetched_at": int(time.time()),
    }
    wc.put_items(sid, {DIFF_ANCHOR: diff_text, META_ANCHOR: meta_item},
                kind=KIND, replace=True)

    if diff_bytes > WARN_DIFF_BYTES:
        res["warning"] = (
            f"large diff ({diff_bytes // 1024} KB) -- annotations may be "
            "slow; consider a narrower PR or branch"
        )
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.ask_diff.push")
    ap.add_argument("--pr", required=True, help="PR number, URL, or branch ref")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--claude-session-id", required=True, dest="claude_session_id")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    a = ap.parse_args(argv)
    try:
        res = push(a.pr, a.cwd, a.claude_session_id, slug=a.slug)
    except ValueError as e:
        print("ask_diff push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("ask_diff push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
