"""ELK-backed geometry for the flowchart renderer.

`flowchart_layout` stays as the fallback and as the source of node sizing;
this module hands ELK the sizes that module measured and turns what comes back
into the same `positions` shape the renderer already reads, plus edge routes it
did not have before.

The subprocess and JSON I/O are isolated here; everything above this module
stays pure.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from skills.annotate.atomic import write_text_atomic

from . import flavours, views
from .flowchart_layout import layout as _python_layout
from .flowchart_layout import node_lines, node_size

DRIVER = Path(__file__).with_name("elk_driver.mjs")
BUNDLE = Path(__file__).with_name("vendor") / "elk.bundled.js"

# ELK on a diagram-sized graph is ~130 ms. The ceiling is for a wedged node
# process, not for a slow layout.
LAYOUT_TIMEOUT_S = 20


class ElkUnavailable(RuntimeError):
    """Raised when node is missing, the driver fails, or ELK rejects the graph."""


# ── Layout cache ────────────────────────────────────────────────────────────
# Every push re-renders every block, and every drawing (each layout variant,
# each view) is one node process that parses the 1.6 MB ELK bundle before it
# lays anything out. A layout is a pure function of the graph sent and the
# engine that ran it, so it is cached on disk keyed by both: an unchanged
# diagram never respawns node. The cache is an optimisation only — any
# failure to read or write it falls through to running ELK.

# Entries are a few KB each; pruning keeps the newest CACHE_KEEP once the
# directory grows past CACHE_MAX_ENTRIES.
CACHE_MAX_ENTRIES = 1000
CACHE_KEEP = 800

# Layouts already seen by this process, by cache key, as the driver's JSON.
_memo: dict[str, str] = {}


def cache_dir() -> Path | None:
    """Where layouts are kept; None when caching to disk is switched off.

    `CLAUDE_ANNOTATE_ELK_CACHE` names the directory (empty disables the disk
    cache). Otherwise it lives under annotate's state directory, which the
    test suite already points at a throwaway place per test.
    """
    override = os.environ.get("CLAUDE_ANNOTATE_ELK_CACHE")
    if override is not None:
        return Path(override).expanduser() if override else None
    base = (os.environ.get("CLAUDE_ANNOTATE_STATE_DIR")
            or os.path.expanduser("~/.claude/annotate"))
    return Path(base) / "cache" / "elk"


@functools.lru_cache(maxsize=None)
def _engine_fingerprint() -> bytes:
    """The driver and the ELK build, so upgrading either invalidates."""
    h = hashlib.sha256()
    for p in (DRIVER, BUNDLE):
        h.update(p.read_bytes())
    return h.digest()


def _cache_key(payload: bytes) -> str:
    return hashlib.sha256(_engine_fingerprint() + payload).hexdigest()


def _cache_get(key: str) -> Any:
    """The cached layout, parsed afresh for each caller; None on a miss."""
    text = _memo.get(key)
    if text is None:
        d = cache_dir()
        if d is None:
            return None
        path = d / (key + ".json")
        try:
            text = path.read_text(encoding="utf-8")
            os.utime(path)  # pruning drops the least recently used
        except OSError:
            return None
    try:
        out = json.loads(text)
    except ValueError:
        return None  # a damaged entry is a miss; the rewrite replaces it
    _memo[key] = text
    return out


def _cache_put(key: str, text: str) -> None:
    _memo[key] = text
    d = cache_dir()
    if d is None:
        return
    try:
        write_text_atomic(d / (key + ".json"), text)
        _prune(d)
    except OSError:
        pass  # a cache that cannot be written is a cache miss next time


def _prune(d: Path) -> None:
    entries = list(d.glob("*.json"))
    if len(entries) <= CACHE_MAX_ENTRIES:
        return

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    entries.sort(key=mtime, reverse=True)
    for p in entries[CACHE_KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass


def _payload(graph: dict[str, Any]) -> bytes:
    try:
        return json.dumps(graph).encode("utf-8")
    except TypeError as e:
        raise ElkUnavailable(f"elk graph is not JSON-serializable: {e}") from e


def _spawn(payload: bytes, timeout: float) -> bytes:
    """Run the driver on `payload`; its stdout, or ElkUnavailable."""
    node = shutil.which("node")
    if not node:
        raise ElkUnavailable("node not found on PATH")
    try:
        proc = subprocess.run(
            [node, str(DRIVER)],
            input=payload,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ElkUnavailable(f"elk driver did not run: {e}") from e
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise ElkUnavailable(detail or "elk driver failed")
    return proc.stdout


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as e:
        raise ElkUnavailable(f"elk driver returned non-JSON: {e}") from e


def run_elk(graph: dict[str, Any]) -> dict[str, Any]:
    """Lay out one ELK graph. Raises ElkUnavailable on any failure."""
    payload = _payload(graph)
    key = _cache_key(payload)
    out = _cache_get(key)
    if out is None:
        text = _spawn(payload, LAYOUT_TIMEOUT_S).decode("utf-8", "replace")
        out = _parse(text)
        _cache_put(key, text)
    return out


def run_elk_many(graphs: list[dict[str, Any]]) -> list[Any]:
    """Lay out several graphs, spawning node at most once for all of them.

    Each result is the laid-out graph, or the ElkUnavailable that graph met;
    one bad graph does not cost the others their layouts.
    """
    results: list[Any] = [None] * len(graphs)
    misses: list[tuple[int, str, bytes]] = []
    for i, g in enumerate(graphs):
        try:
            payload = _payload(g)
        except ElkUnavailable as e:
            results[i] = e
            continue
        key = _cache_key(payload)
        out = _cache_get(key)
        if out is None:
            misses.append((i, key, payload))
        else:
            results[i] = out
    if not misses:
        return results
    batch = b"[" + b",".join(p for _, _, p in misses) + b"]"
    try:
        replies = _parse(_spawn(batch, LAYOUT_TIMEOUT_S + 2 * len(misses))
                         .decode("utf-8", "replace"))
        if not isinstance(replies, list) or len(replies) != len(misses):
            raise ElkUnavailable("elk driver answered a batch with the "
                                 "wrong number of results")
    except ElkUnavailable as e:
        for i, _, _ in misses:
            results[i] = e
        return results
    for (i, key, _), reply in zip(misses, replies):
        if isinstance(reply, dict) and "ok" in reply:
            _cache_put(key, json.dumps(reply["ok"]))
            results[i] = reply["ok"]
        else:
            error = reply.get("error") if isinstance(reply, dict) else None
            results[i] = ElkUnavailable(str(error or "elk driver failed"))
    return results


def warm(drawings: list[tuple[list[dict[str, Any]], list[dict[str, Any]], str]]
         ) -> None:
    """Lay out several (nodes, edges, variant) drawings in one node process.

    The renders that follow find them in the cache instead of each starting
    node. A prefetch only: whatever is wrong with a drawing is reported by
    the render that needs it, so nothing here raises.
    """
    graphs = []
    for nodes, edges, variant in drawings:
        try:
            graphs.append(_build_graph(nodes, edges, variant))
        except Exception:
            continue
    if graphs:
        run_elk_many(graphs)


# Room around the drawing. ELK lays out from (0, 0); annotate's canvas has
# always carried a margin, and edge labels are placed after layout and clamped
# to the canvas, so they need somewhere to sit.
MARGIN = 24.0


def _build_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                 variant: str) -> dict[str, Any]:
    pin = flavours.pins_entries(variant)
    # Bands are the authored role axis. ELK's own layering is derived from the
    # edges, so it carries whatever distortion the edge set has; a band does
    # not, which is what lets two views of one graph be compared side by side.
    band = views.bands({"nodes": nodes})
    children = []
    for n in nodes:
        w, h = node_size(n)
        child: dict[str, Any] = {"id": n["id"], "width": w, "height": h}
        if n["id"] in band:
            child["layoutOptions"] = {
                "elk.partitioning.partition": str(band[n["id"]])}
        elif pin and n.get("role") == "entry":
            # The single most valuable option in the set: without it a layered
            # algorithm puts each entry point wherever crossings are cheapest,
            # and five starts read as noise.
            child["layoutOptions"] = {
                "elk.layered.layering.layerConstraint": "FIRST"}
        children.append(child)
    root = dict(flavours.options(variant))
    if band:
        root["elk.partitioning.activate"] = "true"
    return {
        "id": "root",
        "layoutOptions": root,
        "children": children,
        # Labels are NOT sent. flowchart.py places them itself, better than ELK
        # would, and only the layered algorithm places them at all.
        "edges": [{"id": f"e{i}", "sources": [e["from"]], "targets": [e["to"]]}
                  for i, e in enumerate(edges)],
    }


def _positions_from(out: dict[str, Any],
                    nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = {n["id"]: n for n in nodes}
    placed = {}
    for c in out.get("children") or []:
        node = by_id.get(c["id"])
        if node is None:
            continue
        w, h = float(c["width"]), float(c["height"])
        placed[c["id"]] = {
            "cx": float(c["x"]) + w / 2 + MARGIN,
            "cy": float(c["y"]) + h / 2 + MARGIN,
            "w": w, "h": h,
            "role": node.get("role"),
            "node": node,
            "lines": node_lines(node),
            # ELK does not expose its layering, and the renderer only reads
            # `layer` on the fallback path where routes are absent.
            "layer": 0,
        }
    return placed


def _routes_from(out: dict[str, Any]) -> dict[int, list[tuple[float, float]]]:
    routes: dict[int, list[tuple[float, float]]] = {}
    for e in out.get("edges") or []:
        # Each edge is handled independently: a malformed section or point in
        # one edge's reply must not discard the node positions ELK already
        # computed for the whole graph, so the error is caught per-edge here
        # rather than bubbling up to layout()'s outer handler.
        try:
            idx = int(str(e["id"])[1:])
            pts: list[tuple[float, float]] = []
            for sec in e.get("sections") or []:
                pts.append((float(sec["startPoint"]["x"]) + MARGIN,
                            float(sec["startPoint"]["y"]) + MARGIN))
                for b in sec.get("bendPoints") or []:
                    pts.append((float(b["x"]) + MARGIN, float(b["y"]) + MARGIN))
                pts.append((float(sec["endPoint"]["x"]) + MARGIN,
                            float(sec["endPoint"]["y"]) + MARGIN))
        except (KeyError, ValueError, TypeError):
            continue
        if len(pts) >= 2:
            routes[idx] = pts
    return routes


def layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
           variant: str = flavours.DEFAULT):
    """Position every node, and route every edge when ELK could.

    Returns ``(positions, canvas_w, canvas_h, routes)``. On any failure — node
    missing, driver error, malformed reply — this falls back to the pure-Python
    layout and returns empty routes, so the renderer keeps working exactly as
    it did before ELK existed.
    """
    try:
        out = run_elk(_build_graph(nodes, edges, variant))
        if not isinstance(out, dict):
            raise ElkUnavailable("elk returned a non-object reply")
        positions = _positions_from(out, nodes)
        if len(positions) != len(nodes):
            raise ElkUnavailable("elk did not place every node")
        canvas_w = float(out["width"]) + 2 * MARGIN
        canvas_h = float(out["height"]) + 2 * MARGIN
        return positions, canvas_w, canvas_h, _routes_from(out)
    except (ElkUnavailable, KeyError, TypeError, ValueError):
        positions, canvas_w, canvas_h = _python_layout(nodes, edges)
        return positions, canvas_w, canvas_h, {}
