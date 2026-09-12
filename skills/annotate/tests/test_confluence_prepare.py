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
    assert report["missing_blocks"] == []


def test_a_missing_block_stops_the_publish_and_writes_no_body(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p"}],
        order=["section-1", "section-2"])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is False
    assert report["missing_blocks"] == ["section-2"]
    assert not (out / "body.template.html").exists()


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
