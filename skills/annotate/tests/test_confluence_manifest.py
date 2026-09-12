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
