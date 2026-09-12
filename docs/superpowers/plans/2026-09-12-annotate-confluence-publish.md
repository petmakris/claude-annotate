# Annotate → Confluence Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an annotate document as a Confluence page in the PMP space, with diagrams as image attachments and code citations resolved against `origin/master`, and make that page regenerable later from a manifest attached to it.

**Architecture:** Python renders a *publish bundle* on disk — page body, PNGs, manifest, anchor report — and never talks to Confluence. The model performs the Confluence calls through MCP tools, following `references/publishing.md`. This mirrors annotate's existing split, where `push.py` renders and the skill orchestrates, and it keeps every deterministic part under test.

**Tech Stack:** Python 3.9+, standard library only. Headless Chromium via the globally installed `playwright` npm package, invoked as a subprocess. `git` for reading files at a ref. pytest for tests.

**Spec:** `docs/superpowers/specs/2026-09-12-annotate-confluence-publish-design.md`

## Global Constraints

- **Standard library only.** The plugin promises "Python 3.9 or newer (standard library only — nothing to pip install)" in its own error text (`references/code-anchors.md`). No new runtime dependency. This is why the markdown converter in Task 4 is written rather than imported.
- **Never emit storage format.** `<ac:…>` and `<ri:…>` markup is not part of Confluence's HTML format and renders as visible raw text rather than erroring. Every generated body is authored in the ADF-mapped HTML subset.
- **Never silently change the document.** A stale anchor, an ambiguous anchor, or a markdown construct the converter does not handle sets `"proceed": false` and stops the publish. Degrading a block quietly is forbidden.
- **`origin/master` only.** Anchors resolve against `origin/master`. Not the working tree, not the authoring branch.
- **Package location:** `skills/annotate/confluence/`. **Tests:** `skills/annotate/tests/test_confluence_*.py`.
- **Run tests with:** `python3 -m pytest skills -q` from the repo root. The suite passes at 737 tests before this plan starts; every task leaves it green.
- **Repo web URL for the first document:** `https://github.com/evooq/montblanc`. **Space:** PMP (key `PIMP`, id `2672492578`). **Cloud id:** `0cdfea0c-5f20-412f-bec3-236bc454b30b`.

---

### Task 1: The manifest

The file that makes a published page regenerable. It is attached to the Confluence page, so a refresh months later needs only this file and a checkout.

**Files:**
- Create: `skills/annotate/confluence/__init__.py`
- Create: `skills/annotate/confluence/manifest.py`
- Test: `skills/annotate/tests/test_confluence_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MANIFEST_VERSION: int` (= 1)
  - `MANIFEST_NAME: str` (= `"annotate-source.json"`)
  - `class ManifestError(ValueError)`
  - `build(*, response_id: str, title: str, glossary: list[dict], blocks: list[dict], repo: dict) -> dict`
  - `parse(raw: str) -> dict`
  - `anchors_of(manifest: dict) -> list[tuple[str, dict]]` — `(block_id, anchor)` pairs in document order

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_manifest.py
"""The manifest is the page's regeneration source, so its contract is a
round-trip: what a publish writes, a refresh months later must read back
unchanged. A lossy field here is a page that cannot be rebuilt."""
import json

import pytest

from skills.annotate.confluence import manifest as m


REPO = {
    "remote": "git@github.com:evooq/montblanc.git",
    "web": "https://github.com/evooq/montblanc",
    "ref": "origin/master",
    "commit": "f4a2e8eae046922b55baaf44529505aa022d9633",
    "resolved_at": "2026-09-12T11:40:00Z",
}
BLOCKS = [
    {"id": "section-1", "kind": "markdown", "title": "Two identities",
     "markdown": "prose",
     "code": [{"file": "a/B.java", "line": 21, "snippet": "@Transient"}]},
    {"id": "section-2", "kind": "sequence", "spec": {"steps": []},
     "svg": "<svg/>", "key": "<div/>"},
]


def _built():
    return m.build(response_id="resp-1", title="The pre-trade id chain",
                   glossary=[{"term": "proposalSyncId", "definition": "d"}],
                   blocks=BLOCKS, repo=REPO)


def test_round_trip_is_lossless():
    out = m.parse(json.dumps(_built()))
    assert out["blocks"] == BLOCKS
    assert out["repo"] == REPO
    assert out["title"] == "The pre-trade id chain"


def test_blocks_are_stored_verbatim_including_rendered_svg():
    # A refresh re-renders pictures from these bytes rather than re-running
    # the layout engine, so dropping `svg` would cost the diagrams.
    assert _built()["blocks"][1]["svg"] == "<svg/>"


def test_an_unknown_manifest_version_is_refused():
    raw = json.dumps({**_built(), "manifest_version": 99})
    with pytest.raises(m.ManifestError) as e:
        m.parse(raw)
    assert "99" in str(e.value)


def test_a_manifest_without_a_version_is_refused():
    raw = json.dumps({"title": "x", "blocks": [], "repo": REPO})
    with pytest.raises(m.ManifestError):
        m.parse(raw)


def test_anchors_are_listed_with_their_block():
    assert m.anchors_of(_built()) == [("section-1", BLOCKS[0]["code"][0])]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.confluence'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/__init__.py
"""Publishing an annotate document to Confluence.

Nothing in this package talks to Confluence. The Atlassian API is reachable
only through MCP tools, which the model calls and a subprocess cannot, so
these modules render a bundle on disk and `references/publishing.md` carries
the call sequence. That split is deliberate: it keeps every deterministic
part — anchor resolution, markdown conversion, image rendering — under test.
"""
```

```python
# skills/annotate/confluence/manifest.py
"""`annotate-source.json` — what makes a published page regenerable.

This file is attached to the Confluence page, which is the point: a refresh
needs the document and its anchors, and nothing guarantees the machine that
published it still exists. Confluence content properties would be the natural
home, but no available MCP tool exposes them, so an attachment is the storage.

Blocks are stored VERBATIM, rendered SVG included. A refresh re-renders the
pictures from those bytes instead of re-running the layout engine, so a change
to the renderer cannot silently redraw a published page.
"""
from __future__ import annotations

import json
from typing import Any

MANIFEST_VERSION = 1
MANIFEST_NAME = "annotate-source.json"


class ManifestError(ValueError):
    """A manifest this code cannot safely read."""


def build(*, response_id: str, title: str, glossary: list[dict[str, Any]],
          blocks: list[dict[str, Any]], repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "response_id": response_id,
        "title": title,
        "glossary": list(glossary),
        "repo": dict(repo),
        "blocks": list(blocks),
    }


def parse(raw: str) -> dict[str, Any]:
    """Read a manifest, refusing one this version cannot honour.

    A future manifest is refused rather than read on a best-effort basis: a
    field this code does not know about is a field it would silently drop from
    the page it regenerates.
    """
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ManifestError("not valid JSON: %s" % e) from None
    if not isinstance(out, dict):
        raise ManifestError("expected an object at the top level")
    version = out.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ManifestError(
            "manifest_version %r cannot be read by this version (expected %d)"
            % (version, MANIFEST_VERSION))
    for key in ("title", "blocks", "repo"):
        if key not in out:
            raise ManifestError("manifest is missing %r" % key)
    return out


def anchors_of(manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every anchor in the document, paired with the block that carries it."""
    pairs: list[tuple[str, dict[str, Any]]] = []
    for blk in manifest.get("blocks") or []:
        for a in (blk.get("code") or []):
            pairs.append((blk.get("id", ""), a))
    return pairs
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_manifest.py -q`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/__init__.py skills/annotate/confluence/manifest.py \
        skills/annotate/tests/test_confluence_manifest.py
git commit -m "Add the annotate-source manifest a published page regenerates from"
```

---

### Task 2: Resolving an anchor against bytes you already hold

`anchors.py` resolves against the filesystem. Publishing resolves against `git show origin/master:<path>`. The drift search must not be copied — it is the thing that keeps citations correct, and two copies will diverge.

**Files:**
- Modify: `skills/annotate/anchors.py` (add one public function after `resolve_anchor`)
- Test: `skills/annotate/tests/test_anchors.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `anchors.resolve_anchor_in(a: dict, lines: list[str]) -> dict` — the same payload shape `resolve_anchor` returns (`status` one of `refused`/`stale`/`moved`/`ok`, plus `lines`), for a caller that already has the file's lines.

- [ ] **Step 1: Write the failing test**

```python
# append to skills/annotate/tests/test_anchors.py
"""Resolving from lines the caller already holds.

Publishing reads source at a git ref, not from the working tree, so it needs
the drift matcher without the filesystem underneath it. One matcher, two byte
sources — a second copy of _locate would drift from this one."""


def test_resolve_anchor_in_finds_an_exact_line():
    lines = ["package x;", "", "@Transient", "private String id;"]
    a = {"file": "X.java", "line": 3, "snippet": "@Transient"}
    out = anchors.resolve_anchor_in(a, lines)
    assert out["status"] == "ok"
    assert out["actual_line"] == 3


def test_resolve_anchor_in_follows_a_line_that_moved():
    lines = ["package x;", "", "", "", "@Transient", "private String id;"]
    a = {"file": "X.java", "line": 3, "snippet": "@Transient"}
    out = anchors.resolve_anchor_in(a, lines)
    assert out["status"] == "moved"
    assert out["actual_line"] == 5


def test_resolve_anchor_in_reports_a_line_that_is_gone():
    a = {"file": "X.java", "line": 3, "snippet": "@Transient"}
    out = anchors.resolve_anchor_in(a, ["package x;", "", "class X {}"])
    assert out["status"] == "stale"


def test_resolve_anchor_in_still_validates_the_anchor():
    out = anchors.resolve_anchor_in({"file": "X.java", "line": 0}, ["a"])
    assert out["status"] == "refused"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q -k resolve_anchor_in`
Expected: FAIL — `AttributeError: module 'skills.annotate.anchors' has no attribute 'resolve_anchor_in'`

- [ ] **Step 3: Write the implementation**

Add immediately after `resolve_anchor` in `skills/annotate/anchors.py`:

```python
def resolve_anchor_in(a: dict, lines: list) -> dict:
    """Resolve an anchor against lines the caller already holds.

    Same validation and same drift search as `resolve_anchor`; only the byte
    source differs. Publishing reads source at a git ref (`git show
    origin/master:<path>`) rather than from the working tree, and copying
    `_locate` into that path would give citations two matchers that are free
    to disagree. There is no path check here because there is no path — the
    caller decided which bytes these are.
    """
    problem = anchor_problem(a)
    if problem:
        return _fail(a if isinstance(a, dict) else {}, "refused", problem)
    return _build(a, lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_anchors.py -q`
Expected: PASS, including the 4 new tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/anchors.py skills/annotate/tests/test_anchors.py
git commit -m "Let an anchor resolve against lines the caller already holds"
```

---

### Task 3: Anchors against origin/master, with permalinks

**Files:**
- Create: `skills/annotate/confluence/gitref.py`
- Create: `skills/annotate/confluence/resolve.py`
- Test: `skills/annotate/tests/test_confluence_resolve.py`

**Interfaces:**
- Consumes: `anchors.resolve_anchor_in`, `anchors.DRIFT_RADIUS`.
- Produces:
  - `gitref.GitError(RuntimeError)`
  - `gitref.commit_of(repo: str, ref: str) -> str` — full sha
  - `gitref.read_lines(repo: str, ref: str, path: str) -> list[str] | None` — `None` when the path does not exist at that ref
  - `gitref.web_url(remote: str) -> str` — `git@github.com:o/r.git` → `https://github.com/o/r`
  - `gitref.remote_of(repo: str) -> str`
  - `resolve.resolve_all(pairs, *, repo, ref, commit, web) -> list[dict]` where each dict is `{block_id, file, line, end_line, snippet, status, actual_line, lines, url, message}` and `status` ∈ `ok`/`moved`/`stale`/`ambiguous`/`missing`/`refused`
  - `resolve.blocking(results: list[dict]) -> list[dict]` — those with a status that must stop a publish

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_resolve.py
"""Citations resolved against origin/master, not the working tree.

Documentation describes the code its readers have. These tests build a real
git repository so the resolution path is the one that will run in anger —
`git show`, a detached ref, a file that does not exist at that ref."""
import subprocess

import pytest

from skills.annotate.confluence import gitref, resolve


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A repo whose master has: a line that moved, a line that was deleted,
    and a snippet that occurs twice."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "A.java").write_text(
        "package a;\n@Transient\nprivate String id;\ngone();\n")
    (r / "B.java").write_text("x();\n@Id\ny();\n@Id\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "first")
    # master moves the anchored line down by two and deletes gone()
    (r / "A.java").write_text(
        "package a;\n\n\n@Transient\nprivate String id;\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "second")
    _git(r, "remote", "add", "origin", "git@github.com:evooq/montblanc.git")
    return r


def _resolve(repo, pairs, ref="master"):
    commit = gitref.commit_of(str(repo), ref)
    return resolve.resolve_all(
        pairs, repo=str(repo), ref=ref, commit=commit,
        web=gitref.web_url(gitref.remote_of(str(repo))))


def test_a_moved_line_is_followed(repo):
    out = _resolve(repo, [("section-1", {
        "file": "A.java", "line": 2, "snippet": "@Transient"})])
    assert out[0]["status"] == "moved"
    assert out[0]["actual_line"] == 4


def test_a_deleted_line_is_stale(repo):
    out = _resolve(repo, [("section-1", {
        "file": "A.java", "line": 4, "snippet": "gone();"})])
    assert out[0]["status"] == "stale"


def test_a_snippet_matching_twice_is_ambiguous(repo):
    # Authored at line 3, which is y(); — so _locate would GUESS between the
    # two @Id lines and report the guess as a confident `moved`.
    out = _resolve(repo, [("section-1", {
        "file": "B.java", "line": 3, "snippet": "@Id"})])
    assert out[0]["status"] == "ambiguous"


def test_a_snippet_matching_twice_is_fine_when_the_authored_line_is_right(repo):
    out = _resolve(repo, [("section-1", {
        "file": "B.java", "line": 2, "snippet": "@Id"})])
    assert out[0]["status"] == "ok"


def test_a_file_absent_at_the_ref_is_missing(repo):
    out = _resolve(repo, [("section-1", {
        "file": "Nope.java", "line": 1, "snippet": "x"})])
    assert out[0]["status"] == "missing"


def test_the_permalink_pins_the_commit_not_the_ref(repo):
    commit = gitref.commit_of(str(repo), "master")
    out = _resolve(repo, [("section-1", {
        "file": "A.java", "line": 2, "end_line": 3, "snippet": "@Transient"})])
    assert out[0]["url"] == (
        "https://github.com/evooq/montblanc/blob/%s/A.java#L4-L5" % commit)


def test_stale_missing_and_ambiguous_block_a_publish(repo):
    results = _resolve(repo, [
        ("s1", {"file": "A.java", "line": 2, "snippet": "@Transient"}),
        ("s2", {"file": "A.java", "line": 4, "snippet": "gone();"}),
        ("s3", {"file": "B.java", "line": 3, "snippet": "@Id"}),
        ("s4", {"file": "Nope.java", "line": 1, "snippet": "x"}),
    ])
    assert [r["block_id"] for r in resolve.blocking(results)] == ["s2", "s3", "s4"]


def test_web_url_normalises_both_remote_forms():
    assert gitref.web_url("git@github.com:evooq/montblanc.git") == \
        "https://github.com/evooq/montblanc"
    assert gitref.web_url("https://github.com/evooq/montblanc.git") == \
        "https://github.com/evooq/montblanc"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_resolve.py -q`
Expected: FAIL — `ImportError: cannot import name 'gitref'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/gitref.py
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
    """The file's lines at `ref`, or None when it does not exist there."""
    r = _git(repo, "show", "%s:%s" % (ref, path))
    if r.returncode:
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
```

```python
# skills/annotate/confluence/resolve.py
"""Anchors resolved against a ref, with a permalink and an honesty check.

Two things separate this from the anchor resolution the live page does.

First, the byte source is `git show origin/master:<path>` — a published page
describes the code its readers have, not the branch it was written on.

Second, `ambiguous`. `anchors._locate` picks the match nearest the authored
line and reports it as `moved` with the same confidence as an exact hit. That
is right for a page the author is looking at while the file changes under
them; it is wrong for a page nobody re-reads for months, where a citation that
quietly slid onto the wrong line is worse than one that admits it is broken.
So when the snippet matches more than once in the drift window and the
authored line is not one of the matches, the guess is refused.
"""
from __future__ import annotations

from typing import Any

from skills.annotate import anchors
from skills.annotate.confluence import gitref

# Any of these stops a publish. `refused` is a malformed anchor, which is an
# authoring bug; the rest are citations that would mislead a reader.
BLOCKING = ("stale", "missing", "ambiguous", "refused")


def _matches_in_window(lines: list[str], snippet: str, authored: int) -> int:
    want = snippet.strip()
    lo = max(1, authored - anchors.DRIFT_RADIUS)
    hi = min(len(lines), authored + anchors.DRIFT_RADIUS)
    return sum(1 for n in range(lo, hi + 1) if lines[n - 1].strip() == want)


def _permalink(web: str, commit: str, path: str,
               start: int, end: int) -> str:
    span = "#L%d" % start if end <= start else "#L%d-L%d" % (start, end)
    return "%s/blob/%s/%s%s" % (web, commit, path, span)


def resolve_all(pairs: list[tuple[str, dict[str, Any]]], *, repo: str,
                ref: str, commit: str, web: str) -> list[dict[str, Any]]:
    """Resolve every (block_id, anchor) pair at `ref`."""
    out: list[dict[str, Any]] = []
    for block_id, a in pairs:
        row: dict[str, Any] = {
            "block_id": block_id,
            "file": a.get("file", ""),
            "line": a.get("line", 0),
            "end_line": a.get("end_line"),
            "snippet": a.get("snippet", ""),
        }
        lines = gitref.read_lines(repo, ref, str(a.get("file", "")))
        if lines is None:
            row.update(status="missing",
                       message="%s: not present at %s" % (a.get("file"), ref))
            out.append(row)
            continue

        resolved = anchors.resolve_anchor_in(a, lines)
        row.update({k: v for k, v in resolved.items() if k != "file"})

        if resolved["status"] == "moved":
            authored = a["line"]
            exact = (1 <= authored <= len(lines)
                     and lines[authored - 1].strip() == a["snippet"].strip())
            if not exact and _matches_in_window(
                    lines, a["snippet"], authored) > 1:
                row["status"] = "ambiguous"
                row["message"] = (
                    "%s: %r matches more than one line near line %d, so the "
                    "line this cites would be a guess"
                    % (a.get("file"), a["snippet"].strip(), authored))

        if row["status"] in ("ok", "moved"):
            start = resolved["actual_line"]
            end = start + ((a.get("end_line") or a["line"]) - a["line"])
            row["url"] = _permalink(web, commit, str(a["file"]), start, end)
        out.append(row)
    return out


def blocking(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The results that must stop a publish, in document order."""
    return [r for r in results if r.get("status") in BLOCKING]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_resolve.py -q`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/gitref.py skills/annotate/confluence/resolve.py \
        skills/annotate/tests/test_confluence_resolve.py
git commit -m "Resolve annotate code anchors against origin/master with permalinks"
```

---

### Task 4: Markdown to the ADF-mapped HTML subset

Written rather than imported, because the plugin promises no pip installs. The subset is bounded: annotate's markdown is model-authored against `references/pushing.md`. The hard rule is that anything the converter does not understand **raises** — a publish that silently drops a paragraph is the failure this whole design exists to avoid.

**Files:**
- Create: `skills/annotate/confluence/markdown_html.py`
- Test: `skills/annotate/tests/test_confluence_markdown.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class UnsupportedMarkdown(ValueError)`
  - `to_html(md: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_markdown.py
"""Markdown to Confluence's HTML format.

Two rules decide every case below. Confluence's format is an ADF-mapped HTML
subset, so anything outside it (`<ac:…>`, a bare `<div>`, a style attribute)
is not "degraded" — it renders as visible junk or is dropped. And a construct
this converter does not understand must RAISE, because a publish that quietly
loses a paragraph is worse than one that refuses to run."""
import pytest

from skills.annotate.confluence.markdown_html import (
    UnsupportedMarkdown, to_html)


def test_paragraphs():
    assert to_html("one\n\ntwo") == "<p>one</p><p>two</p>"


def test_inline_marks():
    assert to_html("**b** and *i* and `c`") == \
        "<p><strong>b</strong> and <em>i</em> and <code>c</code></p>"


def test_a_link():
    assert to_html("see [docs](https://x.test/a)") == \
        '<p>see <a href="https://x.test/a">docs</a></p>'


def test_inline_text_is_escaped():
    assert to_html("a < b & c") == "<p>a &lt; b &amp; c</p>"


def test_code_spans_are_escaped_too():
    assert to_html("`<T>`") == "<p><code>&lt;T&gt;</code></p>"


def test_bullet_list():
    assert to_html("- one\n- two") == "<ul><li><p>one</p></li><li><p>two</p></li></ul>"


def test_ordered_list_carries_its_start():
    assert to_html("3. c\n4. d") == \
        '<ol start="3"><li><p>c</p></li><li><p>d</p></li></ol>'


def test_fenced_code_keeps_its_language():
    assert to_html("```java\nint x = 1;\n```") == \
        '<pre><code class="language-java">int x = 1;</code></pre>'


def test_fenced_code_without_a_language():
    assert to_html("```\nplain\n```") == "<pre><code>plain</code></pre>"


def test_fenced_code_is_escaped_but_not_marked_up():
    assert to_html("```\n**not bold** <x>\n```") == \
        "<pre><code>**not bold** &lt;x&gt;</code></pre>"


def test_heading():
    assert to_html("### Deep") == "<h3>Deep</h3>"


def test_blockquote():
    assert to_html("> quoted") == "<blockquote><p>quoted</p></blockquote>"


def test_pipe_table_with_a_header():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert to_html(md) == (
        "<table><thead><tr><th><p>a</p></th><th><p>b</p></th></tr></thead>"
        "<tbody><tr><td><p>1</p></td><td><p>2</p></td></tr></tbody></table>")


def test_table_cells_carry_inline_marks():
    md = "| a |\n| --- |\n| `x` |"
    assert "<td><p><code>x</code></p></td>" in to_html(md)


def test_raw_html_is_refused_not_dropped():
    # pushing.md allows inline HTML in a markdown block, with inline styles and
    # custom classes. None of that survives ADF conversion, so it must stop the
    # publish rather than arrive as a differently-shaped page.
    with pytest.raises(UnsupportedMarkdown) as e:
        to_html('<table class="weigh-up"><tr><td>x</td></tr></table>')
    assert "HTML" in str(e.value)


def test_an_image_is_refused():
    # A markdown image points at a URL Confluence cannot resolve; pictures on a
    # published page are attachments, built by images.py.
    with pytest.raises(UnsupportedMarkdown):
        to_html("![alt](cat.png)")


def test_nothing_emits_storage_format():
    md = "# H\n\ntext\n\n| a |\n| --- |\n| 1 |\n\n```java\nx\n```"
    out = to_html(md)
    assert "<ac:" not in out and "<ri:" not in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_markdown.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.confluence.markdown_html'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/markdown_html.py
"""Markdown → Confluence's HTML format (the ADF-mapped subset).

Written, not imported. The plugin's own error text promises "standard library
only — nothing to pip install", and a publish path is not a good enough reason
to break that for everyone who installs annotate.

The subset is small on purpose. Annotate's markdown is model-authored against
`references/pushing.md`, so what actually appears is headings, paragraphs,
lists, pipe tables, fenced code, blockquotes, and four inline marks. Anything
else RAISES. That is the whole safety argument: a converter that guesses
produces a page subtly unlike the one the author approved, and nobody
re-reads a published page closely enough to catch it.
"""
from __future__ import annotations

import re
from html import escape

# Confluence's HTML format is not HTML — it is a fixed set of nodes that map to
# ADF. Raw HTML from a markdown block cannot be passed through: a <div> is
# dropped, a style attribute is dropped, and the reader sees a differently
# shaped page with no error anywhere.
_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(\s|>|/)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

_FENCE = re.compile(r"^\s*```(\S*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


class UnsupportedMarkdown(ValueError):
    """A construct this converter will not guess at."""


def _inline(text: str) -> str:
    """Inline marks, with code spans taken out of the line first.

    Code spans are extracted before anything else and put back last, so
    `**x**` inside backticks stays literal — the one ordering bug that makes a
    converter silently corrupt a code sample.
    """
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(escape(m.group(1)))
        return "\x00%d\x00" % (len(spans) - 1)

    out = _CODE_SPAN.sub(stash, text)
    out = escape(out)
    out = _LINK.sub(
        lambda m: '<a href="%s">%s</a>' % (escape(m.group(2)), m.group(1)), out)
    out = _BOLD.sub(lambda m: "<strong>%s</strong>" % m.group(1), out)
    out = _ITALIC.sub(lambda m: "<em>%s</em>" % m.group(1), out)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: "<code>%s</code>" % spans[int(m.group(1))], out)


def _cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _guard(md: str) -> None:
    fenced = False
    for line in md.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _IMAGE.search(line):
            raise UnsupportedMarkdown(
                "a markdown image cannot be published: pictures on a "
                "Confluence page are attachments — %s" % line.strip())
        if _HTML_TAG.search(line):
            raise UnsupportedMarkdown(
                "raw HTML in a markdown block has no Confluence equivalent "
                "and would be silently dropped — %s" % line.strip())


def to_html(md: str) -> str:
    """Convert one block's markdown. Raises on anything outside the subset."""
    _guard(md)
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            lang, body, i = fence.group(1), [], i + 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence
            cls = ' class="language-%s"' % escape(lang) if lang else ""
            out.append("<pre><code%s>%s</code></pre>"
                       % (cls, escape("\n".join(body))))
            continue

        if not line.strip():
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append("<h%d>%s</h%d>"
                       % (level, _inline(heading.group(2).strip()), level))
            i += 1
            continue

        if (line.lstrip().startswith("|") and i + 1 < len(lines)
                and _TABLE_DIVIDER.match(lines[i + 1])):
            head = _cells(line)
            i += 2
            body_rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                body_rows.append(_cells(lines[i]))
                i += 1
            thead = "".join("<th><p>%s</p></th>" % _inline(c) for c in head)
            tbody = "".join(
                "<tr>%s</tr>" % "".join("<td><p>%s</p></td>" % _inline(c)
                                        for c in row)
                for row in body_rows)
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody>"
                       "</table>" % (thead, tbody))
            continue

        if _BULLET.match(line):
            items = []
            while i < len(lines) and _BULLET.match(lines[i]):
                items.append(_BULLET.match(lines[i]).group(1))
                i += 1
            out.append("<ul>%s</ul>" % "".join(
                "<li><p>%s</p></li>" % _inline(t) for t in items))
            continue

        if _ORDERED.match(line):
            start = _ORDERED.match(line).group(1)
            items = []
            while i < len(lines) and _ORDERED.match(lines[i]):
                items.append(_ORDERED.match(lines[i]).group(2))
                i += 1
            out.append('<ol start="%s">%s</ol>' % (escape(start), "".join(
                "<li><p>%s</p></li>" % _inline(t) for t in items)))
            continue

        if _QUOTE.match(line):
            quoted = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>"
                       % _inline(" ".join(quoted).strip()))
            continue

        para = []
        while i < len(lines) and lines[i].strip() and not (
                _FENCE.match(lines[i]) or _HEADING.match(lines[i])
                or _BULLET.match(lines[i]) or _ORDERED.match(lines[i])
                or _QUOTE.match(lines[i])
                or lines[i].lstrip().startswith("|")):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
    return "".join(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_markdown.py -q`
Expected: PASS, 17 tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/markdown_html.py \
        skills/annotate/tests/test_confluence_markdown.py
git commit -m "Convert annotate markdown to Confluence's ADF-mapped HTML subset"
```

---

### Task 5: The page body

**Files:**
- Create: `skills/annotate/confluence/body.py`
- Test: `skills/annotate/tests/test_confluence_body.py`

**Interfaces:**
- Consumes: `markdown_html.to_html`, `sequence._numbered`, `resolve.resolve_all`'s row shape.
- Produces:
  - `media_token(block_id: str) -> tuple[str, str]` — the `(id, collection)` placeholder pair
  - `figure(block_id: str, alt: str, caption: str = "") -> str`
  - `sequence_key_table(spec: dict) -> str`
  - `render_block(blk: dict, anchors_for_block: list[dict]) -> str`
  - `render_page(*, title: str, glossary: list[dict], blocks: list[dict], anchor_rows: list[dict], repo: dict, slug: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_body.py
"""The document as a Confluence page body.

The invariant that matters most is negative: no output may contain storage
format. `<ac:structured-macro>` does not error on publish — it renders as raw
text in the middle of the page — so only a test keeps it out."""
from skills.annotate.confluence import body


SEQ_SPEC = {
    "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    "steps": [
        {"id": "s1", "from": "a", "to": "b", "label": "save", "tone": "edge",
         "sub": "with the id"},
        {"id": "s2", "kind": "band", "label": "later"},
        {"id": "s3", "from": "b", "to": "a", "label": "ack"},
    ],
}
ANCHOR_OK = {
    "block_id": "section-1", "file": "a/B.java", "line": 21, "end_line": 22,
    "status": "ok", "actual_line": 21,
    "url": "https://github.com/evooq/montblanc/blob/abc/a/B.java#L21-L22",
    "lines": [{"n": 20, "text": "class B {", "role": "context"},
              {"n": 21, "text": "  @Transient", "role": "anchor"},
              {"n": 22, "text": "  String id;", "role": "window"},
              {"n": 23, "text": "}", "role": "context"}],
}


def test_a_markdown_block_becomes_a_heading_and_prose():
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "Two identities",
         "markdown": "one"}, [])
    assert out == "<h2>Two identities</h2><p>one</p>"


def test_a_flowchart_becomes_a_figure_titled_from_its_spec():
    out = body.render_block(
        {"id": "section-4", "kind": "flowchart", "svg": "<svg/>",
         "spec": {"title": "Outbound ids"}}, [])
    assert "<h2>Outbound ids</h2>" in out
    assert 'data-type="media-single"' in out
    assert "__MEDIA_ID__section-4__" in out


def test_a_sequence_carries_its_key_as_a_real_table():
    out = body.render_block(
        {"id": "section-2", "kind": "sequence", "svg": "<svg/>",
         "spec": {**SEQ_SPEC, "title": "One save"}}, [])
    assert "<table>" in out
    # Numbered steps only: a band is a heading row, not a numbered one.
    assert "<td><p>1</p></td>" in out and "<td><p>2</p></td>" in out
    assert "<td><p>3</p></td>" not in out
    assert "save" in out and "with the id" in out


def test_an_anchor_renders_its_excerpt_and_links_the_commit():
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p"},
        [ANCHOR_OK])
    assert "<pre><code" in out
    assert "@Transient" in out
    assert ANCHOR_OK["url"] in out
    # Context lines frame the excerpt; the anchored window is what is cited.
    assert "class B {" in out


def test_an_unanswered_choice_is_marked_not_dropped():
    out = body.render_block(
        {"id": "section-5", "kind": "choice",
         "spec": {"question": "Which?", "options": [{"id": "a", "label": "A"}]}},
        [])
    assert 'data-type="panel-warning"' in out
    assert "Which?" in out


def test_a_mockup_says_what_is_missing_rather_than_vanishing():
    out = body.render_block({"id": "section-6", "kind": "mockup",
                             "spec": {"html": "<b>x</b>"}}, [])
    assert 'data-type="panel-note"' in out
    assert "mockup" in out.lower()


def test_the_page_opens_with_the_glossary_and_closes_with_provenance():
    out = body.render_page(
        title="The pre-trade id chain",
        glossary=[{"term": "proposalSyncId", "definition": "the bank's id"}],
        blocks=[{"id": "section-1", "kind": "markdown", "title": "T",
                 "markdown": "p"}],
        anchor_rows=[],
        repo={"ref": "origin/master", "commit": "abc123def456",
              "web": "https://github.com/evooq/montblanc",
              "resolved_at": "2026-09-12T11:40:00Z"},
        slug="the-pre-trade-id-chain")
    assert out.index("proposalSyncId") < out.index("<h2>T</h2>")
    assert 'data-type="panel-info"' in out
    assert "abc123d" in out           # short sha
    assert "origin/master" in out


def test_no_storage_format_anywhere():
    out = body.render_page(
        title="T", glossary=[{"term": "x", "definition": "y"}],
        blocks=[
            {"id": "section-1", "kind": "markdown", "title": "A",
             "markdown": "p\n\n| a |\n| --- |\n| 1 |"},
            {"id": "section-2", "kind": "sequence", "svg": "<svg/>",
             "spec": SEQ_SPEC},
            {"id": "section-4", "kind": "flowchart", "svg": "<svg/>",
             "spec": {"title": "F"}},
        ],
        anchor_rows=[ANCHOR_OK],
        repo={"ref": "origin/master", "commit": "abc123def456",
              "web": "https://github.com/evooq/montblanc",
              "resolved_at": "2026-09-12T11:40:00Z"},
        slug="s")
    assert "<ac:" not in out
    assert "<ri:" not in out
    assert "ac:structured-macro" not in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_body.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.confluence.body'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/body.py
"""The annotate document as a Confluence page body.

Confluence's HTML format maps to ADF, so the vocabulary is fixed: `<figure
data-type="media-single">` for a picture, `<div data-type="panel-*">` for a
callout, `<details>` for an expand, `<pre><code>` for source. Storage-format
markup (`<ac:…>`, `<ri:…>`) is NOT part of it and does not fail loudly — it
renders as raw text in the middle of the page. A test guards against it
because nothing else will.

Media ids only exist after a file is uploaded, and a file can only be uploaded
to a page that already exists. So pictures are written as placeholders here
and substituted by `finalize.py` once the uploads have happened.
"""
from __future__ import annotations

from html import escape
from typing import Any

from skills.annotate.confluence.markdown_html import to_html
from skills.annotate.diagrams.sequence import _numbered


def media_token(block_id: str) -> tuple[str, str]:
    return ("__MEDIA_ID__%s__" % block_id, "__MEDIA_COLLECTION__%s__" % block_id)


def figure(block_id: str, alt: str, caption: str = "") -> str:
    """A picture, as a media node pointing at an attachment not yet uploaded.

    `data-width` is a percentage on the <figure>, per the format guide; 80 is
    its stated default for diagrams and charts.
    """
    mid, coll = media_token(block_id)
    cap = "<figcaption>%s</figcaption>" % escape(caption) if caption else ""
    return ('<figure data-type="media-single" data-layout="center" '
            'data-width="80"><div data-type="media" data-media-type="file" '
            'data-id="%s" data-collection="%s" data-alt="%s"></div>%s</figure>'
            % (mid, coll, escape(alt), cap))


def sequence_key_table(spec: dict[str, Any]) -> str:
    """The numbered key as native text.

    `render_key()` already emits HTML rather than SVG because it is the half a
    reader selects text out of. On Confluence that pays off twice: the key
    stays searchable and reflows on a phone, while only the grid is a picture.
    Built from the spec rather than parsed out of that HTML — same source,
    same numbering helper, no HTML round-trip.
    """
    rows = []
    for step, num in _numbered(spec.get("steps") or []):
        if num is None:
            rows.append('<tr><td colspan="3"><p><strong>%s</strong></p>'
                        "</td></tr>" % escape(str(step.get("label", ""))))
            continue
        detail = str(step.get("sub") or "")
        note = str(step.get("note") or "")
        if note:
            detail = ("%s (%s)" % (detail, note)) if detail else note
        rows.append("<tr><td><p>%d</p></td><td><p>%s</p></td>"
                    "<td><p>%s</p></td></tr>"
                    % (num, escape(str(step.get("label", ""))), escape(detail)))
    if not rows:
        return ""
    return ("<table><thead><tr><th><p>#</p></th><th><p>Step</p></th>"
            "<th><p>Detail</p></th></tr></thead><tbody>%s</tbody></table>"
            % "".join(rows))


def _excerpt(row: dict[str, Any]) -> str:
    """One anchor: the cited source, then a link pinned to the commit."""
    text = "\n".join(l["text"] for l in row.get("lines") or [])
    start = row.get("actual_line", row.get("line"))
    label = "%s:%s" % (row.get("file"), start)
    if row.get("end_line") and row["end_line"] != row.get("line"):
        label += "-%s" % (start + row["end_line"] - row["line"])
    link = ('<p><a href="%s">%s</a></p>' % (escape(row["url"]), escape(label))
            if row.get("url") else "<p>%s</p>" % escape(label))
    return "<pre><code>%s</code></pre>%s" % (escape(text), link)


def _title_of(blk: dict[str, Any]) -> str:
    """The card's name, by the same priority the page uses (block-title.js):
    an authored title first, then the spec's own."""
    if blk.get("title"):
        return str(blk["title"])
    spec = blk.get("spec") or {}
    for key in ("title", "question"):
        if spec.get(key):
            return str(spec[key])
    return "Section"


def render_block(blk: dict[str, Any],
                 anchors_for_block: list[dict[str, Any]]) -> str:
    kind = blk.get("kind") or "markdown"
    out = ["<h2>%s</h2>" % escape(_title_of(blk))]

    if kind == "markdown":
        out.append(to_html(blk.get("markdown", "")))
    elif kind == "sequence":
        out.append(figure(blk["id"], _title_of(blk)))
        out.append(sequence_key_table(blk.get("spec") or {}))
    elif kind == "flowchart":
        out.append(figure(blk["id"], _title_of(blk)))
    elif kind == "choice":
        spec = blk.get("spec") or {}
        options = "".join("<li><p>%s</p></li>"
                          % escape(str(o.get("label", "")))
                          for o in (spec.get("options") or []))
        out.append('<div data-type="panel-warning"><p>This question was open '
                   "when the page was published: <strong>%s</strong></p>"
                   "<ul>%s</ul></div>"
                   % (escape(str(spec.get("question", ""))), options))
    elif kind == "mockup":
        out.append('<div data-type="panel-note"><p>This section is an '
                   "interactive mockup, which has no Confluence equivalent. "
                   "It is readable on the annotate page.</p></div>")

    for row in anchors_for_block:
        out.append(_excerpt(row))
    return "".join(out)


def _glossary(glossary: list[dict[str, Any]]) -> str:
    if not glossary:
        return ""
    rows = "".join("<tr><td><p><code>%s</code></p></td><td><p>%s</p></td></tr>"
                   % (escape(str(g.get("term", ""))),
                      escape(str(g.get("definition", ""))))
                   for g in glossary)
    return ("<table><thead><tr><th><p>Term</p></th>"
            "<th><p>Meaning</p></th></tr></thead><tbody>%s</tbody></table>"
            % rows)


def _provenance(repo: dict[str, Any], slug: str) -> str:
    """What the page is, and how old. A reader who does not know a page was
    generated cannot judge whether to trust its line numbers."""
    return ('<div data-type="panel-info"><p>Generated from the annotate '
            "session <code>%s</code>, resolved against <code>%s</code> at "
            "commit <a href=\"%s/commit/%s\">%s</a> on %s. Re-running the "
            "publish updates this page in place.</p></div>"
            % (escape(slug), escape(str(repo.get("ref", ""))),
               escape(str(repo.get("web", ""))),
               escape(str(repo.get("commit", ""))),
               escape(str(repo.get("commit", ""))[:7]),
               escape(str(repo.get("resolved_at", "")))))


def render_page(*, title: str, glossary: list[dict[str, Any]],
                blocks: list[dict[str, Any]], anchor_rows: list[dict[str, Any]],
                repo: dict[str, Any], slug: str) -> str:
    by_block: dict[str, list[dict[str, Any]]] = {}
    for row in anchor_rows:
        by_block.setdefault(row["block_id"], []).append(row)
    parts = [_glossary(glossary)]
    for blk in blocks:
        parts.append(render_block(blk, by_block.get(blk["id"], [])))
    parts.append(_provenance(repo, slug))
    return "".join(p for p in parts if p)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_body.py -q`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/body.py skills/annotate/tests/test_confluence_body.py
git commit -m "Render an annotate document as a Confluence page body"
```

---

### Task 6: Diagrams as PNGs

The stored SVG carries class names only — every colour, stroke and font lives in `core.css` and `diagram.css`. Lifted out of the page it renders as unstyled black shapes, so the stylesheet and the woff2 faces have to travel with it.

**Files:**
- Create: `skills/annotate/confluence/images.py`
- Test: `skills/annotate/tests/test_confluence_images.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ChromiumMissing(RuntimeError)`
  - `standalone_html(svg: str) -> str`
  - `render_png(svg: str, out_path: Path) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_images.py
"""A diagram lifted out of the page and made into a file.

The SVG the server stores is class names and geometry — no colours, no fonts.
Everything that makes it legible is in core.css (the palette and the type) and
diagram.css (the tone tokens). Both must travel with it, and so must the woff2
faces, or the picture on Confluence is black shapes in the wrong font."""
import base64
import shutil
import subprocess

import pytest

from skills.annotate.confluence import images

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" '
       'width="200" height="100" class="annotate-seq">'
       '<rect class="actor-box tone-edge" x="10" y="10" width="80" '
       'height="30"/><text class="actor-label" x="50" y="30">A</text></svg>')


def test_the_stylesheets_are_inlined_not_linked():
    out = images.standalone_html(SVG)
    assert "<link" not in out
    assert "--t-edge:" in out          # from diagram.css
    assert "--accent:" in out          # from core.css


def test_the_fonts_are_embedded_as_data_uris():
    out = images.standalone_html(SVG)
    assert "url('fonts/" not in out
    assert "data:font/woff2;base64," in out


def test_the_font_bytes_are_the_real_file():
    out = images.standalone_html(SVG)
    blob = out.split("data:font/woff2;base64,", 1)[1].split("'", 1)[0]
    assert base64.b64decode(blob)[:4] == b"wOF2"


def test_the_svg_itself_is_present_unmodified():
    assert SVG in images.standalone_html(SVG)


def test_the_page_is_painted_light_regardless_of_the_machine():
    # The renderer machine may be in dark mode; the published picture must not
    # depend on it.
    assert "color-scheme: light" in images.standalone_html(SVG)


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs node")
def test_a_png_comes_out_at_twice_the_viewbox(tmp_path):
    try:
        out = images.render_png(SVG, tmp_path / "section-2.png")
    except images.ChromiumMissing as e:
        pytest.skip(str(e))
    assert out.exists()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(out.read_bytes()[16:20], "big")
    height = int.from_bytes(out.read_bytes()[20:24], "big")
    assert (width, height) == (400, 200)


def test_a_missing_chromium_is_named_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "Cannot find module 'playwright'"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "playwright" in str(e.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_images.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.confluence.images'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/images.py
"""A stored SVG, rendered to a PNG that can be attached to a page.

The SVG annotate stores is deliberately style-free: `class="actor-box
tone-edge"`, and the colours live in the stylesheet. That is right for a page
that themes its diagrams, and fatal for one lifted out of it — so this module
rebuilds the missing half, inlining core.css (palette, type), diagram.css
(tone tokens) and the two woff2 faces as data URIs.

Chromium, not librsvg: diagram.css uses `color-mix()`, which librsvg does not
implement. `rsvg-convert` would not fail — it would draw the washes wrong and
say nothing.
"""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
FONTS = {
    "Monaspace Radon": STATIC / "fonts" / "MonaspaceRadon-Regular.woff2",
    "Bricolage Grotesque": STATIC / "fonts" / "BricolageGrotesque-Variable.woff2",
}
SCALE = 2


class ChromiumMissing(RuntimeError):
    """Headless Chromium is not usable on this machine."""


def _font_faces() -> str:
    out = []
    for family, path in FONTS.items():
        blob = base64.b64encode(path.read_bytes()).decode("ascii")
        out.append("@font-face{font-family:'%s';src:url('data:font/woff2;"
                   "base64,%s') format('woff2');font-display:block;}"
                   % (family, blob))
    return "".join(out)


def standalone_html(svg: str) -> str:
    """The SVG with everything it needs to look like it does on the page."""
    css = (STATIC / "core.css").read_text() + (STATIC / "diagram.css").read_text()
    # The stylesheets reference their fonts by relative URL; those files are
    # not beside this document, so the @font-face rules are replaced wholesale
    # by data-URI ones emitted above.
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>:root{color-scheme:light;}"
        "html,body{margin:0;padding:0;background:#fff;"
        "font-family:'Bricolage Grotesque',ui-sans-serif,system-ui,sans-serif;}"
        "%s\n%s</style><body>%s</body>" % (_font_faces(), css, svg))


_SCRIPT = """
const { chromium } = require('playwright');
(async () => {
  const [htmlPath, outPath, scale] = process.argv.slice(2);
  const fs = require('fs');
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: Number(scale) });
  await page.setContent(fs.readFileSync(htmlPath, 'utf8'),
                        { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const svg = await page.$('svg');
  await svg.screenshot({ path: outPath, omitBackground: false });
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def _node_script(script_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the renderer under node, with the global module path available.

    playwright is installed globally rather than in this repo — there is no
    package.json here and adding one for a single screenshot would be a
    heavier dependency than the picture is worth.
    """
    root = subprocess.run(["npm", "root", "-g"], capture_output=True,
                          text=True).stdout.strip()
    return subprocess.run(["node", str(script_path), *args],
                          capture_output=True, text=True,
                          env={**__import__("os").environ, "NODE_PATH": root})


def render_png(svg: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    html_path = work / (out_path.stem + ".html")
    script_path = work / "_shot.cjs"
    html_path.write_text(standalone_html(svg))
    script_path.write_text(_SCRIPT)
    try:
        res = _node_script(script_path, str(html_path), str(out_path),
                           str(SCALE))
    finally:
        for p in (html_path, script_path):
            p.unlink(missing_ok=True)
    if res.returncode:
        detail = (res.stderr or res.stdout).strip()
        if "playwright" in detail or "chromium" in detail.lower():
            raise ChromiumMissing(
                "headless Chromium is not available, and a page published "
                "without its diagrams is not the document the author "
                "approved.\n  npm install -g playwright && npx playwright "
                "install chromium\n%s" % detail)
        raise RuntimeError("rendering %s failed: %s" % (out_path.name, detail))
    return out_path
```

Note on `json` import: it is unused in the code above — drop the import when writing the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_images.py -q`
Expected: PASS (the PNG test runs if Chromium is installed, skips with a reason otherwise)

- [ ] **Step 5: Verify a real picture by eye**

```bash
python3 - <<'EOF'
import json, pathlib
from skills.annotate.confluence import images
d = pathlib.Path.home()/".claude/webcompanion/workspaces/annotate/260912-104014-9e4021501a26eefe/items"
b = json.load(open(d/"section-4.json")); b = b.get("body", b)
images.render_png(b["svg"], pathlib.Path("/tmp/section-4.png"))
print("wrote /tmp/section-4.png")
EOF
```

Open it. It must match the card at `http://localhost:3080/s/the-pre-trade-id-chain/` — same colours, same font, no black-on-white fallback. If the fonts are wrong, `document.fonts.ready` resolved too early; if the colours are flat, a stylesheet is missing.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/confluence/images.py skills/annotate/tests/test_confluence_images.py
git commit -m "Render a stored diagram SVG to a PNG with its stylesheet inlined"
```

---

### Task 7: The publish bundle

**Files:**
- Create: `skills/annotate/confluence/prepare.py`
- Test: `skills/annotate/tests/test_confluence_prepare.py`

**Interfaces:**
- Consumes: `manifest`, `gitref`, `resolve`, `body`, `images`.
- Produces:
  - `load_items(items_dir: Path) -> tuple[dict, list[dict]]` — `(doc, blocks in order)`
  - `prepare(*, items_dir: Path, repo: str, out_dir: Path, slug: str, ref: str = "origin/master", with_images: bool = True) -> dict` — the report
  - `main(argv=None) -> int` — CLI

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_prepare.py
"""Building the bundle a publish uploads.

The rule under test is refusal. A stale citation, or markdown this converter
does not understand, must produce no bundle at all — not a bundle with a gap
in it. Publishing a page that differs from what the author approved, without
saying so, is the failure mode this whole path exists to prevent."""
import json
import subprocess

import pytest

from skills.annotate.confluence import prepare


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "A.java").write_text("package a;\n@Transient\nString id;\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "first")
    _git(r, "remote", "add", "origin", "git@github.com:evooq/montblanc.git")
    return r


def _items(tmp_path, blocks, order=None):
    d = tmp_path / "items"
    d.mkdir()
    (d / "__doc__.json").write_text(json.dumps({"body": {
        "title": "T", "response_id": "r1", "glossary": [],
        "order": order or [b["id"] for b in blocks]}}))
    for b in blocks:
        (d / ("%s.json" % b["id"])).write_text(json.dumps({"body": b}))
    return d


def test_a_clean_document_produces_a_bundle(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T",
         "markdown": "prose",
         "code": [{"file": "A.java", "line": 2, "snippet": "@Transient"}]},
        {"id": "section-2", "kind": "flowchart", "svg": "<svg/>",
         "spec": {"title": "F"}},
    ])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is True
    assert (out / "body.template.html").exists()
    assert (out / "annotate-source.json").exists()
    assert "__MEDIA_ID__section-2__" in (out / "body.template.html").read_text()
    assert report["images"] == ["section-2.png"]


def test_a_stale_anchor_stops_the_publish_and_writes_no_body(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p",
         "code": [{"file": "A.java", "line": 2, "snippet": "deleted();"}]}])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is False
    assert report["blocking"][0]["status"] == "stale"
    assert not (out / "body.template.html").exists()


def test_markdown_it_cannot_convert_stops_the_publish(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T",
         "markdown": '<table class="weigh-up"><tr><td>x</td></tr></table>'}])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is False
    assert "section-1" in json.dumps(report["unconvertible"])
    assert not (out / "body.template.html").exists()


def test_blocks_come_out_in_document_order(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "One",
         "markdown": "a"},
        {"id": "section-2", "kind": "markdown", "title": "Two",
         "markdown": "b"},
    ], order=["section-2", "section-1"])
    out = tmp_path / "bundle"
    prepare.prepare(items_dir=items, repo=str(repo), out_dir=out, slug="s",
                    ref="master", with_images=False)
    html = (out / "body.template.html").read_text()
    assert html.index("Two") < html.index("One")


def test_the_manifest_records_the_commit_that_was_resolved(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p"}])
    out = tmp_path / "bundle"
    prepare.prepare(items_dir=items, repo=str(repo), out_dir=out, slug="s",
                    ref="master", with_images=False)
    got = json.loads((out / "annotate-source.json").read_text())
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "master"],
                          capture_output=True, text=True).stdout.strip()
    assert got["repo"]["commit"] == head
    assert got["repo"]["web"] == "https://github.com/evooq/montblanc"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_prepare.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.confluence.prepare'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/prepare.py
"""Build the bundle a publish uploads.

Nothing here touches Confluence. It writes four things into a directory:

    body.template.html    the page, with placeholders where pictures go
    annotate-source.json  the manifest a future refresh regenerates from
    images/<id>.png       one per diagram
    report.json           every anchor's status, and whether to proceed

`proceed: false` means the publish stops and NO body is written. That is the
point of the split: a page that is missing a citation, or that quietly dropped
a block the converter could not handle, is not the document the author
approved, and the only safe moment to notice is before anything is uploaded.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skills.annotate.confluence import body as body_mod
from skills.annotate.confluence import gitref, images, manifest, resolve
from skills.annotate.confluence.markdown_html import UnsupportedMarkdown

REPORT_NAME = "report.json"
BODY_TEMPLATE = "body.template.html"


def load_items(items_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The stored document: (__doc__ body, blocks in `order`).

    Read from disk rather than from the daemon's API — a refresh may run long
    after the session was last open, and a scheduled job has no daemon at all.
    """
    items_dir = Path(items_dir)
    doc = json.loads((items_dir / "__doc__.json").read_text())
    doc = doc.get("body", doc)
    blocks = []
    for bid in doc.get("order") or []:
        path = items_dir / ("%s.json" % bid)
        if not path.exists():
            continue
        raw = json.loads(path.read_text())
        blocks.append(raw.get("body", raw))
    return doc, blocks


def prepare(*, items_dir: Path, repo: str, out_dir: Path, slug: str,
            ref: str = "origin/master", with_images: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, blocks = load_items(Path(items_dir))

    commit = gitref.commit_of(repo, ref)
    web = gitref.web_url(gitref.remote_of(repo))
    repo_info = {
        "remote": gitref.remote_of(repo),
        "web": web,
        "ref": ref,
        "commit": commit,
        "resolved_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    }

    man = manifest.build(
        response_id=doc.get("response_id", ""), title=doc.get("title", ""),
        glossary=doc.get("glossary") or [], blocks=blocks, repo=repo_info)
    (out_dir / manifest.MANIFEST_NAME).write_text(json.dumps(man, indent=2))

    rows = resolve.resolve_all(manifest.anchors_of(man), repo=repo, ref=ref,
                               commit=commit, web=web)
    blocked = resolve.blocking(rows)

    # Convert every markdown block up front, so a construct the converter
    # cannot handle is reported alongside the anchor problems rather than
    # raising halfway through writing a page.
    unconvertible = []
    for blk in blocks:
        if (blk.get("kind") or "markdown") != "markdown":
            continue
        try:
            body_mod.render_block(blk, [])
        except UnsupportedMarkdown as e:
            unconvertible.append({"block_id": blk["id"], "problem": str(e)})

    report: dict[str, Any] = {
        "slug": slug,
        "title": doc.get("title", ""),
        "repo": repo_info,
        "anchors": rows,
        "blocking": blocked,
        "unconvertible": unconvertible,
        "images": ["%s.png" % b["id"] for b in blocks if b.get("svg")],
        "proceed": not blocked and not unconvertible,
    }
    (out_dir / REPORT_NAME).write_text(json.dumps(report, indent=2))
    if not report["proceed"]:
        return report

    (out_dir / BODY_TEMPLATE).write_text(body_mod.render_page(
        title=doc.get("title", ""), glossary=doc.get("glossary") or [],
        blocks=blocks, anchor_rows=rows, repo=repo_info, slug=slug))

    if with_images:
        img_dir = out_dir / "images"
        for blk in blocks:
            if blk.get("svg"):
                images.render_png(blk["svg"], img_dir / ("%s.png" % blk["id"]))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.prepare")
    ap.add_argument("--items", required=True, help="the session's items dir")
    ap.add_argument("--repo", required=True, help="checkout to resolve against")
    ap.add_argument("--out", required=True, help="bundle directory to write")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--ref", default="origin/master")
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args(argv)
    report = prepare(items_dir=Path(a.items), repo=a.repo, out_dir=Path(a.out),
                     slug=a.slug, ref=a.ref, with_images=not a.no_images)
    print(json.dumps({k: report[k] for k in
                      ("proceed", "blocking", "unconvertible", "images")},
                     indent=2))
    return 0 if report["proceed"] else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_prepare.py -q`
Expected: PASS, 5 tests

- [ ] **Step 5: Run it against the real document**

```bash
PYTHONPATH=. python3 -m skills.annotate.confluence.prepare \
  --items ~/.claude/webcompanion/workspaces/annotate/260912-104014-9e4021501a26eefe/items \
  --repo /Users/petros.makris/projects/wp/pmp-287/montblanc \
  --out /tmp/pretrade-bundle --slug the-pre-trade-id-chain --no-images
```

Expected: exit 2, `"proceed": false`, and `blocking` naming exactly one anchor — `section-8`, `CustomJpaProposalRepository.java`, snippet `@Query("""`, status `stale`. That is the known unmerged claim recorded in the spec, and seeing it here is the proof the refusal path works on real data.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/confluence/prepare.py skills/annotate/tests/test_confluence_prepare.py
git commit -m "Build the publish bundle, refusing a document with a stale citation"
```

---

### Task 8: Substituting media ids, and remembering the page

**Files:**
- Create: `skills/annotate/confluence/finalize.py`
- Create: `skills/annotate/confluence/state.py`
- Test: `skills/annotate/tests/test_confluence_finalize.py`

**Interfaces:**
- Consumes: `prepare.BODY_TEMPLATE`.
- Produces:
  - `finalize.UnfilledPlaceholder(ValueError)`
  - `finalize.finalize(bundle: Path, media: dict[str, dict]) -> Path` — writes `body.html`, returns its path
  - `finalize.main(argv=None) -> int`
  - `state.load(workspace: Path) -> dict`, `state.save(workspace: Path, **fields) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_finalize.py
"""Putting the uploaded ids into the body.

A media node whose id was never uploaded does not warn — it renders as a
broken node in the middle of the page. So the substitution refuses rather than
publishes a body with a placeholder still in it."""
import json

import pytest

from skills.annotate.confluence import finalize, state


def _bundle(tmp_path, html):
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "body.template.html").write_text(html)
    return b


def test_ids_and_collections_are_substituted(tmp_path):
    b = _bundle(tmp_path, 'x <div data-id="__MEDIA_ID__section-2__" '
                          'data-collection="__MEDIA_COLLECTION__section-2__"/>')
    out = finalize.finalize(b, {"section-2.png": {"id": "m-1",
                                                  "collection": "contentId-9"}})
    text = out.read_text()
    assert 'data-id="m-1"' in text
    assert 'data-collection="contentId-9"' in text
    assert out.name == "body.html"


def test_a_missing_id_refuses_and_names_the_picture(tmp_path):
    b = _bundle(tmp_path, '<div data-id="__MEDIA_ID__section-4__"/>')
    with pytest.raises(finalize.UnfilledPlaceholder) as e:
        finalize.finalize(b, {})
    assert "section-4" in str(e.value)


def test_an_extra_upload_is_not_an_error(tmp_path):
    # Re-uploading the manifest, or an image from a previous run, must not
    # block a body that does not reference it.
    b = _bundle(tmp_path, "<p>no pictures</p>")
    out = finalize.finalize(b, {"annotate-source.json": {"id": "m-9",
                                                         "collection": "c"}})
    assert out.read_text() == "<p>no pictures</p>"


def test_state_round_trips(tmp_path):
    state.save(tmp_path, page_id="123", space_id="2672492578",
               parent_id="99", last_commit="abc")
    got = state.load(tmp_path)
    assert got["page_id"] == "123"
    assert got["last_commit"] == "abc"


def test_state_is_empty_before_the_first_publish(tmp_path):
    assert state.load(tmp_path) == {}


def test_state_merges_rather_than_replaces(tmp_path):
    state.save(tmp_path, page_id="123", parent_id="99")
    state.save(tmp_path, last_commit="def")
    got = state.load(tmp_path)
    assert got["page_id"] == "123" and got["last_commit"] == "def"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_finalize.py -q`
Expected: FAIL — `ImportError: cannot import name 'finalize'`

- [ ] **Step 3: Write the implementation**

```python
# skills/annotate/confluence/finalize.py
"""Put the uploaded media ids into the page body.

A media id exists only after the file is uploaded, and the file can only be
uploaded to a page that already exists — so the body is written twice, and
this is the second pass. It refuses on an unfilled placeholder because the
failure it prevents is silent: Confluence renders a media node pointing at
nothing as a broken tile, with no error anywhere in the publish.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BODY_TEMPLATE = "body.template.html"
BODY_FINAL = "body.html"
_LEFTOVER = re.compile(r"__MEDIA_(?:ID|COLLECTION)__([A-Za-z0-9_-]+)__")


class UnfilledPlaceholder(ValueError):
    """A picture in the body was never uploaded."""


def finalize(bundle: Path, media: dict[str, dict]) -> Path:
    """Substitute `{filename: {id, collection}}` into the body template."""
    bundle = Path(bundle)
    text = (bundle / BODY_TEMPLATE).read_text()
    for filename, ids in media.items():
        block_id = Path(filename).stem
        text = text.replace("__MEDIA_ID__%s__" % block_id, str(ids["id"]))
        text = text.replace("__MEDIA_COLLECTION__%s__" % block_id,
                            str(ids["collection"]))
    left = sorted(set(_LEFTOVER.findall(text)))
    if left:
        raise UnfilledPlaceholder(
            "no upload was recorded for %s — publishing this body would put a "
            "broken picture on the page" % ", ".join(left))
    out = bundle / BODY_FINAL
    out.write_text(text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.confluence.finalize")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--media", required=True,
                    help='JSON: {"section-2.png": {"id": ..., "collection": ...}}')
    a = ap.parse_args(argv)
    try:
        out = finalize(Path(a.bundle), json.loads(a.media))
    except UnfilledPlaceholder as e:
        print("annotate publish: %s" % e, file=sys.stderr)
        return 2
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```python
# skills/annotate/confluence/state.py
"""Which Confluence page a session publishes to.

Kept in the workspace so a second publish updates the page the author already
shared rather than minting a second one beside it — the same reason
`push.py` resolves a slug to a live session before creating one.

This is a convenience, not the source of truth: the page carries its own
manifest, so a refresh works even when this file is gone.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._shared.web_companion.atomic import write_text_atomic

NAME = "confluence.json"


def _path(workspace: Path) -> Path:
    return Path(workspace) / NAME


def load(workspace: Path) -> dict[str, Any]:
    path = _path(workspace)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(workspace: Path, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into the record. Merging, not replacing: a publish that
    only moves the commit forward must not drop the page id."""
    out = {**load(workspace), **{k: v for k, v in fields.items()
                                 if v is not None}}
    write_text_atomic(_path(workspace), json.dumps(out, indent=2))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_finalize.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/confluence/finalize.py skills/annotate/confluence/state.py \
        skills/annotate/tests/test_confluence_finalize.py
git commit -m "Substitute uploaded media ids into the body, and record the page"
```

---

### Task 9: The skill wiring

The Confluence calls live here, because only the model can make them. `test_skill_structure.py` already enforces that every `references/**/*.md` is reachable from `SKILL.md`, so the reference and its link ship together or the suite fails.

**Files:**
- Create: `skills/annotate/references/publishing.md`
- Modify: `skills/annotate/SKILL.md` (phase-map row + `allowed-tools`)
- Test: `skills/annotate/tests/test_confluence_skill_wiring.py`

**Interfaces:**
- Consumes: `prepare`, `finalize`, `state` CLIs.
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

```python
# skills/annotate/tests/test_confluence_skill_wiring.py
"""Publishing is only reachable if the skill can actually make the calls.

annotate's allowed-tools is Bash/Read/Write. Every Confluence call in
references/publishing.md is an MCP tool, so without them in the frontmatter
the procedure documents something the skill is not permitted to do."""
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
PUBLISHING = SKILL_DIR / "references" / "publishing.md"


def test_the_reference_exists_and_skill_md_points_at_it():
    assert PUBLISHING.exists()
    assert "references/publishing.md" in SKILL_MD.read_text()


def test_the_command_is_named_in_the_phase_map():
    assert "/annotate publish" in SKILL_MD.read_text()


def test_allowed_tools_covers_every_confluence_call_the_reference_makes():
    frontmatter = SKILL_MD.read_text().split("---", 2)[1]
    used = set(re.findall(r"\b(createConfluencePage|updateConfluencePage|"
                          r"createConfluenceAttachment|listConfluenceAttachments|"
                          r"downloadConfluenceAttachment|getConfluenceSpaces)\b",
                          PUBLISHING.read_text()))
    assert used, "the reference names no Confluence calls"
    missing = [t for t in sorted(used) if t not in frontmatter]
    assert not missing, (
        "references/publishing.md calls %s, which annotate's allowed-tools "
        "does not permit" % ", ".join(missing))


def test_the_procedure_stops_on_a_refusal_before_touching_confluence():
    text = PUBLISHING.read_text()
    assert "proceed" in text
    # The order on the page is the order of operations; resolving must come
    # before the first write.
    assert text.index("prepare") < text.index("createConfluencePage")


def test_the_procedure_finalizes_before_updating_the_body():
    text = PUBLISHING.read_text()
    assert text.index("finalize") < text.index("updateConfluencePage")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_skill_wiring.py -q`
Expected: FAIL — `references/publishing.md` does not exist

- [ ] **Step 3: Write the reference**

Create `skills/annotate/references/publishing.md`:

````markdown
# Publishing a document to Confluence

Read this when the user types `/annotate publish`. It turns the session the
conversation is attached to into a Confluence page, and updates that same page
on every later publish.

## What this is not

It is not the Share export (`static/export.js`), which produces a standalone
HTML file from the live page. This builds a native Confluence page: the prose
is Confluence prose, the diagrams are attachments, and the citations link
GitHub at a pinned commit.

## The rule that shapes the procedure

**Documentation is built from `origin/master`.** A page describing an unmerged
branch documents code its readers do not have. If a citation does not resolve
on master, the publish stops and the user decides — it is never quietly
dropped, and never published as though it were current.

## Step 1 — build the bundle

```bash
cd "$PLUGIN_ROOT" && PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.annotate.confluence.prepare \
  --items "<workspace>/items" \
  --repo "<a checkout of the repo the session was authored against>" \
  --out "<bundle dir>" \
  --slug "<session slug>"
```

Exit 0 means the bundle is complete. **Exit 2 means stop.** Read
`<bundle dir>/report.json` and tell the user exactly what refused:

- `blocking` — citations that do not resolve on master. Each names the block,
  the file, the snippet, and why (`stale`, `missing`, `ambiguous`, `refused`).
- `unconvertible` — markdown blocks using raw HTML or an image, neither of
  which has a Confluence equivalent.

Do not work around either. The user's options are to reword the block, drop it,
or wait for the merge; all three are theirs to choose.

## Step 2 — find or create the page

Read `<workspace>/confluence.json`. If it has a `page_id`, this document has
been published before: skip to step 3.

Otherwise ask the user which page to nest under, once, then:

```
createConfluencePage(cloudId, spaceId: "<PMP space id>", title: <report.title>,
                     parentId: <the page they named>, status: "draft",
                     contentFormat: "html", body: "<p>Publishing…</p>")
```

Created as a **draft**: the first publish of a document is never live until its
author has read it. Record the result:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -c "
from pathlib import Path; from skills.annotate.confluence import state
state.save(Path('<workspace>'), page_id='<id>', space_id='<id>',
           parent_id='<id>')"
```

## Step 3 — upload the attachments

For every file in `<bundle dir>/images/` and for `annotate-source.json`:

```
createConfluenceAttachment(cloudId, contentId: <page id>,
                           localFilePath: "<bundle dir>/images/section-4.png")
```

It returns a curl command. Run it with Bash, and keep the media id and
collection from its response. If the response does not carry them, read them
back with `listConfluenceAttachments(cloudId, contentId)`.

`annotate-source.json` is not decoration: it is what lets this page be rebuilt
against a later master by someone who has never seen this machine.

## Step 4 — write the body

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -m skills.annotate.confluence.finalize \
  --bundle "<bundle dir>" \
  --media '{"section-4.png": {"id": "<media id>", "collection": "<collection>"}}'
```

It refuses if any picture is missing an id, because a media node pointing at
nothing renders as a broken tile with no error anywhere. Then:

```
updateConfluencePage(cloudId, pageId, title, contentFormat: "html",
                     body: <contents of bundle/body.html>)
```

Record the commit that was published:

```bash
PYTHONPATH="$PLUGIN_ROOT" python3 -c "
from pathlib import Path; from skills.annotate.confluence import state
state.save(Path('<workspace>'), last_commit='<report.repo.commit>')"
```

Give the user the page URL and say it is a draft, if it is.

## Refreshing a published page

`/annotate publish --refresh <page url or id>` rebuilds a page against today's
master. It needs no annotate workspace — only a checkout of the repo the
manifest names.

1. `listConfluenceAttachments(cloudId, contentId)` → find
   `annotate-source.json` → `downloadConfluenceAttachment` → run the curl it
   returns.
2. Write the manifest's `blocks` into an items directory shaped like a
   workspace's, then run step 1 above against it with the same `--repo`.
3. Continue from step 3. The page already exists, so nothing is created.
4. Report what changed: anchors that moved, anchors that went stale, and any
   block whose prose no longer matches the source beneath it. The last one is
   a judgement, not a diff — say what you saw and let the user decide. Never
   edit the prose to fit the code.
````

- [ ] **Step 4: Wire it into SKILL.md**

Add to the `allowed-tools` list in the frontmatter:

```yaml
  - mcp__claude_ai_Atlassian_Rovo__createConfluencePage
  - mcp__claude_ai_Atlassian_Rovo__updateConfluencePage
  - mcp__claude_ai_Atlassian_Rovo__getConfluenceSpaces
  - mcp__plugin_atlassian_atlassian__executeRead
  - mcp__plugin_atlassian_atlassian__executeWrite
```

Add this row to the phase-map table, after the `resume` row:

```markdown
| The user typed `/annotate publish` (or `/annotate publish --refresh <page>`) | **Publish** the document to Confluence | `references/publishing.md` |
```

Note for the implementer: `createConfluenceAttachment`, `listConfluenceAttachments` and `downloadConfluenceAttachment` are not primary tools — they are reached through `executeWrite` / `executeRead` with that operation `name`. Name them in `references/publishing.md` as above; the wiring test reads the reference for the operation names and the frontmatter for the tools that carry them.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest skills/annotate/tests/test_confluence_skill_wiring.py skills/annotate/tests/test_skill_structure.py -q`
Expected: PASS. `test_no_orphan_reference_files` in particular proves the new reference is reachable from `SKILL.md`.

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest skills -q`
Expected: PASS, 737 + the new tests

- [ ] **Step 7: Commit**

```bash
git add skills/annotate/references/publishing.md skills/annotate/SKILL.md \
        skills/annotate/tests/test_confluence_skill_wiring.py
git commit -m "Add /annotate publish, the Confluence procedure the model follows"
```

---

### Task 10: Publish the real document and look at it

Two defects in the sequence-key work were invisible to every source-level test and only showed up in a browser. A rendering target this code has never produced gets the same treatment before it is called done.

**Files:**
- Modify: none, unless the page reveals a defect.

**Interfaces:**
- Consumes: everything above.
- Produces: a draft Confluence page.

- [ ] **Step 1: Confirm the known refusal, then resolve it with the user**

```bash
PYTHONPATH=. python3 -m skills.annotate.confluence.prepare \
  --items ~/.claude/webcompanion/workspaces/annotate/260912-104014-9e4021501a26eefe/items \
  --repo /Users/petros.makris/projects/wp/pmp-287/montblanc \
  --out /tmp/pretrade-bundle --slug the-pre-trade-id-chain
```

It will refuse on `section-8` — the nightly-step correction, which cites
`findAllIdsByOrganizationIdAndStatusInAndPreTradeChecked`, added by PMP-272 and
not on master. Ask the user whether to hold that section, reword it, or wait
for the merge. **Do not resolve this without them**; it is a claim about what
the system does, and the answer changes what the page says.

- [ ] **Step 2: Publish the bundle as a draft**

Follow `references/publishing.md` steps 2–4 against space PMP
(`spaceId: "2672492578"`, cloudId `0cdfea0c-5f20-412f-bec3-236bc454b30b`),
under the parent page the user names.

- [ ] **Step 3: Read the published page in a browser**

Open it and check each of these, which are the things no unit test can see:

- Every diagram renders, in the right colours and the right font — not black
  shapes, not a fallback typeface.
- The sequence key is a real table beneath its picture, not an image of one.
- Tables from markdown have their header row.
- Code excerpts are syntax-shaped blocks, not paragraphs, and each link opens
  GitHub at the cited lines.
- The glossary is above the first section; the provenance panel is at the foot.
- No literal `<ac:`, `<ri:`, `__MEDIA_ID__`, or `&lt;p&gt;` anywhere on the page.

- [ ] **Step 4: Fix anything the page revealed, with a test first**

Any defect found here gets a failing test before its fix — a browser-only
defect that ships without one is a defect that comes back.

- [ ] **Step 5: Commit and report**

```bash
git add -A && git commit -m "Fix <what the published page revealed>"
```

Then tell the user the page URL, that it is a draft, and which section (if any)
was held back because it is not yet on master.

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task: manifest → 1;
`resolve.py` and its injectable byte source → 2, 3; markdown and body → 4, 5;
`images.py` → 6; `prepare.py`/`finalize.py` and the three-phase ordering → 7, 8;
"who talks to Confluence" and the command surface → 9; the real draft publish
the spec's Testing section demands → 10. The refresh flow is documented in the
Task 9 reference and reuses tasks 1–8 with no new code, which is what the spec
claims for it.

**Two things the spec leaves to the implementer, decided here.** First, the
markdown converter is written rather than imported (Python-Markdown is present
on this machine, but the plugin promises no pip installs, and that promise is
in its own user-facing error text). Second, a markdown block the converter
cannot handle blocks the publish exactly as a stale anchor does — the spec's
rule is "never silently change the document", and quietly degrading a block
would break it just as surely as a bad citation.

**Type consistency.** `resolve_all` returns rows keyed `block_id`/`status`/
`url`/`lines`/`actual_line`; `body.render_page` consumes exactly those, and
`prepare` passes them through unchanged. `media_token`/`figure` mint the
placeholders that `finalize` substitutes, and the leftover regex in `finalize`
matches the format `media_token` emits. `prepare.BODY_TEMPLATE` and
`finalize.BODY_TEMPLATE` are the same literal — Task 8 keeps its own copy
rather than importing `prepare`, so the bundle can be finalized without the
rendering dependencies loaded.
