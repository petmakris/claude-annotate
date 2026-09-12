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
