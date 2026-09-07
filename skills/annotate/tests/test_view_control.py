"""The view switcher: per-view SVGs on the wire and one control in the client."""
import pathlib

import pytest

from skills.annotate import render as render_mod
from skills.annotate.diagrams import views
from skills.annotate.diagrams.flowchart import ValidationError, validate
from skills.annotate.tests.test_views import orders_sync

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "static" / "script.js"


def _block(spec):
    return render_mod.render_block(
        {"id": "b1", "kind": "flowchart", "spec": spec})


def test_block_ships_one_svg_per_view_plus_the_union():
    blk = _block(orders_sync())
    assert blk["views"] == [views.ALL_VIEW, "write", "read", "persist"]
    for name in blk["views"]:
        assert blk["svgs"][name].startswith("<svg")
    # the union stays the default the un-updated client paints
    assert blk["svg"] == blk["svgs"][views.ALL_VIEW]


def test_each_view_svg_is_distinct_from_the_union():
    blk = _block(orders_sync())
    union = blk["svgs"][views.ALL_VIEW]
    for name in ("write", "read", "persist"):
        assert blk["svgs"][name] != union


def test_a_spec_without_views_ships_no_view_control():
    blk = _block(orders_sync(tagged=False, banded=False))
    assert "views" not in blk
    assert blk["svg"].startswith("<svg")


def test_a_view_name_colliding_with_a_layout_flavour_is_rejected():
    spec = orders_sync()
    spec["edges"][0]["views"] = ["layered"]
    with pytest.raises(ValidationError, match="collides"):
        validate(spec)


def test_client_prefers_views_over_flavours_and_keys_them_apart():
    js = SCRIPT.read_text()
    assert 'const VIEW_KEY = "annotate.view.";' in js
    assert "const isViews = viewNames.length > 1;" in js
    assert 'const names = isViews ? viewNames : blk.flavours || [];' in js
    # separate storage prefixes, so a flavour choice cannot select a view
    assert "writeChoice(key, blk.id, name)" in js
    assert "readChoice(key, blk.id)" in js
