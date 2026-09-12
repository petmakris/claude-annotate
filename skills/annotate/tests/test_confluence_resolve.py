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


def test_read_lines_raises_for_an_unresolvable_ref(repo):
    with pytest.raises(gitref.GitError):
        gitref.read_lines(str(repo), "not-a-real-ref", "A.java")


def test_read_lines_returns_none_for_an_absent_path_at_a_real_ref(repo):
    assert gitref.read_lines(str(repo), "master", "Nope.java") is None
