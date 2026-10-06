from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from skills.stage import model


def _bump(path: Path) -> None:
    # Filesystems with coarse mtimes: move the clock forward explicitly.
    t = time.time() + 5
    os.utime(path, (t, t))


def test_a_url_is_a_url(tmp_path):
    assert model.parse_source("https://example.com/x", tmp_path) == {"type": "url", "url": "https://example.com/x"}


def test_a_session_names_kind_and_slug(tmp_path):
    assert model.parse_source("session:deck/my-deck", tmp_path) == {
        "type": "session", "kind": "deck", "slug": "my-deck"}


def test_a_bad_session_is_refused(tmp_path):
    with pytest.raises(model.SourceError):
        model.parse_source("session:deck", tmp_path)


def test_diagram_and_table_read_stdin(tmp_path):
    assert model.parse_source("diagram:-", tmp_path, "graph TD; A-->B\n") == {
        "type": "inline", "format": "diagram", "body": "graph TD; A-->B"}
    assert model.parse_source("table:-", tmp_path, "| a |\n|---|\n| 1 |")["format"] == "table"
    with pytest.raises(model.SourceError):
        model.parse_source("diagram:-", tmp_path, "  ")


def test_a_file_keeps_its_fragment_and_may_not_exist_yet(tmp_path):
    (tmp_path / "deck").mkdir()
    assert model.parse_source("deck/index.html#slide-3", tmp_path) == {
        "type": "file", "path": "deck/index.html", "fragment": "slide-3"}
    assert model.parse_source(str(tmp_path / "deck" / "new.html"), tmp_path) == {
        "type": "file", "path": "deck/new.html", "fragment": None}


def test_a_file_outside_the_project_is_refused(tmp_path):
    with pytest.raises(model.SourceError, match="outside"):
        model.parse_source("../elsewhere.html", tmp_path)


def test_a_file_in_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(model.SourceError, match="no such folder"):
        model.parse_source("nope/index.html", tmp_path)


def test_code_reads_the_range_and_highlight(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
    src = model.parse_source("code:a.py:2-3 highlight 3", tmp_path)
    assert src == {"type": "inline", "format": "code", "path": "a.py", "start": 2,
                   "lines": ["y = 2", "z = 3"], "highlight": [3, 3], "lang": "py", "truncated": False}


def test_code_is_cut_at_sixty_lines(tmp_path):
    (tmp_path / "long.txt").write_text("\n".join(str(i) for i in range(100)))
    src = model.code_source(tmp_path, "long.txt:1-100")
    assert len(src["lines"]) == 60 and src["truncated"] is True


def test_code_errors_are_source_errors(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    for spec in ("a.py", "missing.py:1-2", "a.py:3-1", "a.py:5-6", "../x.py:1-2"):
        with pytest.raises(model.SourceError):
            model.code_source(tmp_path, spec)


def test_mount_name_is_stable_valid_and_distinct(tmp_path):
    (tmp_path / "Decks" / "Q3 Review").mkdir(parents=True)
    (tmp_path / "decks" / "q3-review").mkdir(parents=True)
    a = model.mount_name(tmp_path / "Decks" / "Q3 Review", tmp_path)
    b = model.mount_name(tmp_path / "decks" / "q3-review", tmp_path)
    assert model.NAME_RE.match(a) and model.NAME_RE.match(b)
    assert a != b
    assert a == model.mount_name(tmp_path / "Decks" / "Q3 Review", tmp_path)
    assert model.mount_name(tmp_path, tmp_path).startswith("root-")


def test_dir_rev_changes_when_a_file_changes(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("one")
    before = model.dir_rev(tmp_path)
    f.write_text("two")
    _bump(f)
    assert model.dir_rev(tmp_path) != before


def test_dir_rev_changes_on_atomic_replace(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("one")
    before = model.dir_rev(tmp_path)
    tmp = tmp_path / ".index.html.swp"
    tmp.write_text("two")
    os.replace(tmp, f)
    _bump(tmp_path)
    assert model.dir_rev(tmp_path) != before


def test_dir_rev_sees_a_nested_asset(tmp_path):
    (tmp_path / "assets").mkdir()
    logo = tmp_path / "assets" / "logo.svg"
    logo.write_text("<svg/>")
    before = model.dir_rev(tmp_path)
    logo.write_text("<svg></svg>")
    _bump(logo)
    assert model.dir_rev(tmp_path) != before


def test_dir_rev_ignores_git_and_node_modules(tmp_path):
    (tmp_path / "index.html").write_text("x")
    for d in (".git", "node_modules"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "f").write_text("x")
    before = model.dir_rev(tmp_path)
    for d in (".git", "node_modules"):
        _bump(tmp_path / d / "f")
    assert model.dir_rev(tmp_path) == before


def test_dir_rev_of_a_missing_directory_is_zero(tmp_path):
    assert model.dir_rev(tmp_path / "gone") == 0


# -- what changed, read from git --------------------------------------------------


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"})


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("".join(f"value_{i} = {i}\n" for i in range(1, 21)))
    (tmp_path / "same.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def test_a_change_is_read_from_git_with_line_numbers(repo):
    lines = (repo / "a.py").read_text().splitlines()
    lines[4] = "value_5 = 50"         # edit two lines
    lines[14] = "value_15 = 150"
    lines.insert(10, "added = True")  # and add one
    (repo / "a.py").write_text("\n".join(lines) + "\n")
    src = model.parse_source("change:a.py", repo)
    assert src["type"] == "inline" and src["format"] == "change" and src["path"] == "a.py"
    assert src["rev"] is None and src["lang"] == "py" and src["more"] == 0
    assert src["added"] == 3 and src["removed"] == 2
    rows = [r for h in src["hunks"] for r in h["lines"]]
    assert {"op": "-", "old": 5, "new": None, "text": "value_5 = 5"} in rows
    assert {"op": "+", "old": None, "new": 5, "text": "value_5 = 50"} in rows
    assert {"op": "+", "old": None, "new": 11, "text": "added = True"} in rows
    assert {"op": "+", "old": None, "new": 16, "text": "value_15 = 150"} in rows
    first = src["hunks"][0]
    assert first["header"].startswith("@@ -3,") and first["start_new"] == 3 and first["start_old"] == 3
    assert model.change_source(repo, "a.py since HEAD~0")["added"] == 3


def test_an_untracked_file_is_all_new(repo):
    (repo / "new.py").write_text("a = 1\nb = 2\n")
    src = model.change_source(repo, "new.py")
    rows = src["hunks"][0]["lines"]
    assert [r["op"] for r in rows] == ["+", "+"] and [r["new"] for r in rows] == [1, 2]
    assert src["added"] == 2 and src["removed"] == 0


def test_a_change_that_cannot_be_shown_says_why(repo, tmp_path_factory):
    with pytest.raises(model.SourceError, match="no changes in same.py"):
        model.change_source(repo, "same.py")
    with pytest.raises(model.SourceError, match="not a git revision"):
        model.change_source(repo, "a.py since ;rm")
    with pytest.raises(model.SourceError, match="not a git revision"):
        model.change_source(repo, "a.py since --output=x")
    with pytest.raises(model.SourceError, match="outside the project"):
        model.change_source(repo, "../elsewhere.py")
    (repo / "b.bin").write_bytes(b"\0\1\2")
    with pytest.raises(model.SourceError, match="binary"):
        model.change_source(repo, "b.bin")
    plain = tmp_path_factory.mktemp("plain")
    (plain / "x.py").write_text("x\n")
    with pytest.raises(model.SourceError, match="not a git repository"):
        model.change_source(plain, "x.py")


def test_a_long_change_shows_80_lines_and_counts_the_rest(repo):
    (repo / "a.py").write_text("".join(f"other_{i} = {i}\n" for i in range(1, 181)))
    src = model.change_source(repo, "a.py")
    shown = sum(len(h["lines"]) for h in src["hunks"])
    assert shown == 80 and src["added"] == 180 and src["removed"] == 20
    assert src["more"] == 200 - 80


def test_a_highlight_is_ordered_clamped_and_refused_outside_the_range(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"x{i}" for i in range(1, 11)) + "\n")
    assert model.parse_source("code:a.py:5-8 highlight 7-3", tmp_path)["highlight"] == [5, 7]
    assert model.parse_source("code:a.py:5-200 highlight 9-40", tmp_path)["highlight"] == [9, 10]
    with pytest.raises(model.SourceError, match="outside lines 5-8"):
        model.parse_source("code:a.py:5-8 highlight 1-2", tmp_path)
