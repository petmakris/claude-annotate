"""Reading a repository at a ref, without touching the working tree.

Documentation is built from master. The author's checkout is on a feature
branch, is dirty, or is gone — none of which may change what a published page
cites. Everything here goes through `git show <ref>:<path>`, which reads the
committed object and cannot see uncommitted edits.
"""
from __future__ import annotations

import re
import subprocess


class GitError(RuntimeError):
    """git could not answer."""


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)


def commit_of(repo: str, ref: str) -> str:
    r = _git(repo, "rev-parse", ref)
    if r.returncode:
        raise GitError("cannot resolve %r in %s: %s"
                       % (ref, repo, r.stderr.strip()))
    return r.stdout.strip()


def remote_of(repo: str, name: str = "origin") -> str:
    r = _git(repo, "remote", "get-url", name)
    if r.returncode:
        raise GitError("no remote %r in %s" % (name, repo))
    return r.stdout.strip()


def read_lines(repo: str, ref: str, path: str) -> list[str] | None:
    """The file's lines at `ref`, or None when it does not exist there.

    `git show <ref>:<path>` fails identically whether `ref` itself does not
    resolve or `ref` resolves but `path` is not in it — and reporting the
    first case as "missing" tells a reader code was deleted from master when
    really a ref name was mistyped. So a failure here checks which one it
    was: only a `path` genuinely absent at a real ref returns None; a ref
    that does not resolve raises, same as `commit_of`.
    """
    r = _git(repo, "show", "%s:%s" % (ref, path))
    if r.returncode:
        verify = _git(repo, "rev-parse", "--verify", "%s^{commit}" % ref)
        if verify.returncode:
            raise GitError("cannot resolve %r in %s: %s"
                           % (ref, repo, verify.stderr.strip()))
        return None
    return r.stdout.split("\n")[:-1] if r.stdout.endswith("\n") \
        else r.stdout.split("\n")


_SSH = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?$")
_HTTPS = re.compile(r"^https?://([^/]+)/(.+?)(?:\.git)?$")


def web_url(remote: str) -> str:
    """A browsable base URL for a git remote.

    The published citation is a link a colleague clicks, so the ssh form the
    author pushes with has to become the https form a browser opens.
    """
    for pattern in (_SSH, _HTTPS):
        m = pattern.match(remote.strip())
        if m:
            return "https://%s/%s" % (m.group(1), m.group(2))
    raise GitError("cannot derive a web URL from remote %r" % remote)
