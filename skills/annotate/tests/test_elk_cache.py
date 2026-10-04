"""Layouts are cached by content, so an unchanged diagram never respawns node.

Every push re-renders every block. Without the cache each flowchart, and each
of its views, started a node process that parsed the ELK bundle before laying
anything out."""
import shutil
import subprocess

import pytest

from skills.annotate.diagrams import elk_layout
from skills.annotate.render import render_block
from skills.annotate.tests.test_views import orders_sync

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _graph(label="b"):
    return {
        "id": "root",
        "layoutOptions": {"elk.algorithm": "layered", "elk.direction": "DOWN"},
        "children": [{"id": "a", "width": 120.0, "height": 40.0},
                     {"id": label, "width": 120.0, "height": 40.0}],
        "edges": [{"id": "e0", "sources": ["a"], "targets": [label]}],
    }


@pytest.fixture
def spawns(tmp_path, monkeypatch):
    """A fresh process's view of a cache in tmp_path; counts node spawns."""
    monkeypatch.setenv("CLAUDE_ANNOTATE_ELK_CACHE", str(tmp_path / "elk"))
    monkeypatch.setattr(elk_layout, "_memo", {}, raising=False)
    calls = []
    real = subprocess.run

    def counting(cmd, *a, **k):
        calls.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(elk_layout.subprocess, "run", counting)
    return calls


def test_the_same_graph_is_laid_out_once(spawns):
    first = elk_layout.run_elk(_graph())
    second = elk_layout.run_elk(_graph())
    assert first == second
    assert len(spawns) == 1


def test_the_cache_outlives_the_process(spawns, monkeypatch):
    elk_layout.run_elk(_graph())
    monkeypatch.setattr(elk_layout, "_memo", {}, raising=False)  # a later push
    elk_layout.run_elk(_graph())
    assert len(spawns) == 1


def test_a_changed_graph_is_laid_out_again(spawns):
    elk_layout.run_elk(_graph("b"))
    elk_layout.run_elk(_graph("c"))
    assert len(spawns) == 2


def test_a_failure_is_not_cached(spawns):
    bad = {"id": "root", "children": [{"id": "a"}],
           "edges": [{"id": "e0", "sources": ["ghost"], "targets": ["a"]}]}
    for _ in range(2):
        with pytest.raises(elk_layout.ElkUnavailable):
            elk_layout.run_elk(bad)
    assert len(spawns) == 2


def test_a_damaged_entry_is_a_miss(spawns, tmp_path, monkeypatch):
    elk_layout.run_elk(_graph())
    for p in (tmp_path / "elk").glob("*.json"):
        p.write_text("{not json")
    monkeypatch.setattr(elk_layout, "_memo", {}, raising=False)
    assert elk_layout.run_elk(_graph())["children"]
    assert len(spawns) == 2


def test_the_cache_is_bounded(spawns, tmp_path, monkeypatch):
    monkeypatch.setattr(elk_layout, "CACHE_MAX_ENTRIES", 3)
    monkeypatch.setattr(elk_layout, "CACHE_KEEP", 2)
    elk_layout.run_elk_many([_graph(str(i)) for i in range(5)])
    assert 1 <= len(list((tmp_path / "elk").glob("*.json"))) <= 3


def test_a_batch_spawns_node_once_and_isolates_a_bad_graph(spawns):
    bad = {"id": "root", "children": [{"id": "a"}],
           "edges": [{"id": "e0", "sources": ["ghost"], "targets": ["a"]}]}
    out = elk_layout.run_elk_many([_graph("b"), bad, _graph("c")])
    assert len(spawns) == 1
    assert isinstance(out[1], elk_layout.ElkUnavailable)
    assert out[0] == elk_layout.run_elk(_graph("b"))
    assert {c["id"] for c in out[2]["children"]} == {"a", "c"}
    assert len(spawns) == 1, "the batch's layouts were not cached"


def test_a_flowchart_with_views_starts_node_once_and_then_never(spawns,
                                                                monkeypatch):
    blk = {"id": "f", "kind": "flowchart", "spec": orders_sync()}
    cold = render_block(blk)
    assert len(cold["views"]) > 2
    assert len(spawns) == 1
    monkeypatch.setattr(elk_layout, "_memo", {}, raising=False)  # the next push
    warm = render_block(blk)
    assert warm == cold
    assert len(spawns) == 1
