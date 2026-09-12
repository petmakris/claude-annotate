"""Building the bundle a publish uploads.

The rule under test is refusal. A stale citation, or markdown this converter
does not understand, must produce no bundle at all — not a bundle with a gap
in it. Publishing a page that differs from what the author approved, without
saying so, is the failure mode this whole path exists to prevent."""
import json
import subprocess
from pathlib import Path

import pytest

from skills.annotate.confluence import constants, prepare


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


def test_a_flowchart_with_extra_views_refuses_the_publish(tmp_path, repo):
    # body.py publishes only the union drawing, so a block's extra views were
    # dropped with nothing said. Refusing is honest where dropping is not.
    items = _items(tmp_path, [
        {"id": "section-2", "kind": "flowchart", "svg": "<svg/>",
         "svgs": {"all": "<svg/>", "write": "<svg2/>"},
         "views": ["all", "write"], "spec": {"title": "F"}}])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is False
    assert report["unsupported_views"] == [
        {"block_id": "section-2", "views": ["write"]}]
    assert not (out / "body.template.html").exists()


def test_the_union_view_alone_is_not_an_extra_view(tmp_path, repo):
    items = _items(tmp_path, [
        {"id": "section-2", "kind": "flowchart", "svg": "<svg/>",
         "views": ["all"], "spec": {"title": "F"}}])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["unsupported_views"] == []
    assert report["proceed"] is True


def test_a_refused_rerun_clears_the_previous_run_s_body(tmp_path, repo):
    # out_dir was never cleared, so a successful run, an edit, and a re-run
    # into the same --out left "proceed": false beside the PREVIOUS body and
    # the NEW manifest. The "no bundle at all" guarantee held only for a
    # fresh directory.
    items = _items(tmp_path, [
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p",
         "code": [{"file": "A.java", "line": 2, "snippet": "@Transient"}]}])
    out = tmp_path / "bundle"
    first = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                            slug="s", ref="master", with_images=False)
    assert first["proceed"] is True
    (out / "body.html").write_text("<p>a previous finalize</p>")

    (items / "section-1.json").write_text(json.dumps({"body": {
        "id": "section-1", "kind": "markdown", "title": "T",
        "markdown": "p",
        "code": [{"file": "A.java", "line": 2, "snippet": "deleted();"}]}}))
    second = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert second["proceed"] is False
    assert not (out / "body.template.html").exists()
    assert not (out / "body.html").exists()


def test_a_diagram_block_with_no_stored_picture_refuses(tmp_path, repo):
    # prepare listed images by `svg`, body emitted a figure by `kind`. A
    # flowchart with no stored svg therefore got a placeholder no PNG would
    # ever fill, and the publish died in finalize -- after the page and its
    # attachments already existed.
    items = _items(tmp_path, [
        {"id": "section-2", "kind": "flowchart", "spec": {"title": "F"}}])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    assert report["proceed"] is False
    assert "section-2" in json.dumps(report["unconvertible"])
    assert not (out / "body.template.html").exists()


def test_every_placeholder_in_the_body_has_an_image_listed_for_it(tmp_path, repo):
    items = _items(tmp_path, [
        # a markdown block carrying a stray `svg` is not a picture
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p",
         "svg": "<svg/>"},
        {"id": "section-2", "kind": "sequence", "svg": "<svg/>",
         "spec": {"steps": []}},
        {"id": "section-3", "kind": "flowchart", "svg": "<svg/>",
         "spec": {"title": "F"}},
    ])
    out = tmp_path / "bundle"
    report = prepare.prepare(items_dir=items, repo=str(repo), out_dir=out,
                             slug="s", ref="master", with_images=False)
    html = (out / "body.template.html").read_text()
    assert sorted(set(constants.LEFTOVER.findall(html))) == \
        sorted({Path(n).stem for n in report["images"]})
