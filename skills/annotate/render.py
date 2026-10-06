"""Block rendering for a webcompanion push.

The daemon stores items as opaque JSON and never inspects them, so
everything that used to happen per-request in annotate's own server —
compiling a flowchart's source, rasterising a sequence spec to
SVG — happens once here, at push time, and the rendered body is what gets
stored.

Code anchors are the deliberate exception: they are left unresolved in the
body, because the daemon resolves them fresh on every read (the repository
can change while a session is open) using this same plugin's anchor format.
"""
from __future__ import annotations

import html as _html
from typing import Callable

from skills._shared.visuals.sequence import render, render_key
from skills._shared.visuals.flowchart import render as render_flowchart
from skills._shared.visuals.flowchart import render_variants as render_flowchart_variants
from skills._shared.visuals import elk_layout, flavours
from skills._shared.visuals import views as views_mod
from skills.annotate.pflow import PflowError, compile_source as compile_pflow
from skills.annotate.explain import compile_spec as compile_explain


def html_escape(s: str) -> str:
    return _html.escape(s, quote=True)


def _error_pill(blk_id: str, css: str, label: str, error: Exception, *,
                sized: bool) -> str:
    """Compact inline error pill instead of a full-width red banner.

    One malformed block must never crash the whole /raw response and blank
    the page. The message lands in <title>.
    """
    size = 'width="360" height="36" ' if sized else ''
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 36" '
        f'{size}'
        f'class="{css} {css}-error" '
        f'data-block-id="{html_escape(blk_id)}" '
        f'role="img" aria-label="{label} failed to render">'
        f'<rect x="0" y="0" width="360" height="36" rx="6" '
        f'fill="#fde7e2" stroke="#e5b8af"/>'
        f'<text x="14" y="22" font-size="12" font-weight="600" '
        f'fill="#c1432f" font-family="ui-monospace, monospace">'
        f'⚠ diagram render failed</text>'
        f'<title>{html_escape(str(error))}</title>'
        f'</svg>'
    )


def _render_sequence(blk: dict, base: dict) -> None:
    spec = blk.get("spec") or {}
    key = ""
    try:
        svg = render(spec, block_id=blk["id"])
        # The grid is numbered badges and nothing else, so a grid without
        # its key is a picture of unexplained circles. Render both under
        # the one try: if either half fails, the reader gets the error pill
        # rather than half a diagram.
        key = render_key(spec, block_id=blk["id"])
    except Exception as e:
        # Catch *any* render failure (ValidationError, or a KeyError from a
        # spec that passed validation but is missing a field the renderer
        # reads).
        svg = _error_pill(blk["id"], "annotate-seq", "sequence diagram", e,
                          sized=True)
    base["spec"] = spec
    base["svg"] = svg
    # Additive, like flowchart's `svgs` below: a client that has not been
    # updated paints the grid alone and is no worse off than before.
    if key:
        base["key"] = key


def _compile_flowchart_source(blk: dict, spec: dict
                              ) -> tuple[dict, list[str], str | None]:
    """(spec, warnings, source_error) once any pflow `source` is compiled."""
    source = spec.get("source")
    if not source:
        return spec, [], None
    # Authored as pflow: nodes/edges are derived, so any that were stored
    # alongside the source are stale by definition and get replaced.
    try:
        compiled = compile_pflow(source, filename=blk["id"])
    except PflowError as e:
        return {**spec, "nodes": [], "edges": []}, [], str(e)
    warnings = compiled.pop("warnings", [])
    return {**spec, **compiled}, warnings, None


def _flowchart_views(blk: dict, spec: dict, svg: str, svgs: dict[str, str],
                     base: dict, warnings: list[str]) -> list[str]:
    """Add the per-view drawings to `base`; return the warnings so far.

    Views are a different axis from layout flavours: same renderer, a
    different edge set per drawing. They ride the same `svgs` map so the
    client needs one swap mechanism, keyed by name.
    """
    try:
        vnames = views_mod.declared(spec)
    except Exception as e:
        # The block still ships, without a view control; the author is
        # told why rather than finding the control silently missing.
        return [*warnings, "views ignored: %s: %s" % (type(e).__name__, e)]
    if not vnames:
        return warnings
    per_view = dict(svgs)
    per_view[views_mod.ALL_VIEW] = svg
    emitted = []
    for v in vnames:
        try:
            sub = views_mod.subspec(spec, v)
            if not sub.get("edges"):
                continue
            per_view[v] = render_flowchart(sub, f'{blk["id"]}-{v}')
            emitted.append(v)
        except Exception:
            # One unrenderable view must not cost the block its others.
            continue
    if emitted:
        base["svgs"] = per_view
        base["views"] = [views_mod.ALL_VIEW] + emitted
    return warnings


def _warm_flowchart_layouts(spec: dict) -> None:
    """Lay out every drawing the block is about to render in one node process.

    Each variant and each view is its own ELK layout; done one by one, each
    starts node afresh. The renders below then find theirs in the cache.
    """
    try:
        drawings = [(spec["nodes"], spec.get("edges") or [], name)
                    for name, _ in flavours.HOUSE_SET]
        for v in views_mod.declared(spec):
            sub = views_mod.subspec(spec, v)
            if sub.get("edges"):
                drawings.append((sub["nodes"], sub["edges"], flavours.DEFAULT))
    except Exception:
        # Only a prefetch: the renders below meet the same malformed spec
        # and report it where the reader sees it.
        return
    elk_layout.warm(drawings)


def _render_flowchart(blk: dict, base: dict) -> None:
    spec, warnings, source_error = _compile_flowchart_source(
        blk, blk.get("spec") or {})
    if not source_error:
        _warm_flowchart_layouts(spec)
    svgs: dict[str, str] = {}
    names: list[str] = []
    try:
        if source_error:
            raise ValueError(source_error)
        svgs, names = render_flowchart_variants(spec, block_id=blk["id"])
        svg = svgs[names[0]]
    except Exception as e:
        svgs, names = {}, []
        # Same containment as the sequence pill.
        svg = _error_pill(blk["id"], "annotate-flow", "flowchart", e,
                          sized=False)
    base["spec"] = spec
    base["svg"] = svg
    # Additive: an un-updated client reads `svg` and is none the wiser.
    # A block whose variants all failed ships the error pill and no control.
    if len(names) > 1:
        base["svgs"] = svgs
        base["flavours"] = names
    warnings = _flowchart_views(blk, spec, svg, svgs, base, warnings)
    if warnings:
        base["warnings"] = warnings


def _forward_spec(blk: dict, base: dict) -> None:
    # choice, and mockup: trusted Claude HTML rendered client-side in a
    # sandboxed iframe. The spec is forwarded verbatim; the HTML is never
    # parsed or rendered here.
    base["spec"] = blk.get("spec") or {}


def _render_explain(blk: dict, base: dict) -> None:
    # Spans are resolved to columns HERE, at push time, for the same
    # reason a flowchart's source is compiled here: it is the last moment
    # a mistake can still be reported to the author. A quote that is not
    # in the snippet becomes a visible error pill instead of an underline
    # painted confidently under the wrong tokens.
    spec = blk.get("spec") or {}
    base["spec"] = spec
    try:
        base["view"] = compile_explain(spec)
    except Exception as e:
        # Any failure, not just ExplainError: a spec that passes the
        # checks but trips a KeyError downstream must not blank the whole
        # /raw response. Same containment as the sequence pill.
        base["view"] = {"error": str(e)}


def _render_markdown(blk: dict, base: dict) -> None:
    base["markdown"] = blk.get("markdown", "")


# One renderer per block kind; each fills in the kind's own fields on `base`.
# markdown is the fallback, and only for markdown: blocks.load() refuses any
# other kind before a push reaches here, so it can never swallow one.
_RENDERERS: dict[str, Callable[[dict, dict], None]] = {
    "sequence": _render_sequence,
    "flowchart": _render_flowchart,
    "choice": _forward_spec,
    "mockup": _forward_spec,
    "explain": _render_explain,
}


def render_block(blk: dict) -> dict:
    """Return the stored body for one block.

    No `version`: the daemon derives that from the body's content hash and
    hands it back in the item envelope, so carrying one here would be a
    second, disagreeing source of truth.

    - markdown blocks → pass markdown through
    - sequence / flowchart → rendered svg + spec
    - choice / mockup → spec forwarded verbatim
    """
    kind = blk.get("kind") or "markdown"
    base = {"id": blk["id"], "kind": kind}
    if blk.get("title"):
        base["title"] = blk["title"]
    # Optional per-rewrite explanation (references/handling-events.md
    # § "Explaining a change"). The diff pane renders it above the marks, and
    # its `Lost:` line is the only place a user can ever learn what a compact
    # discarded — so it has to be on the wire. It was not, for the whole life
    # of the feature: the pane read blk.change_note and this allowlist never
    # put it there. blocks.json is model-authored, so guard the type.
    note = blk.get("change_note")
    if isinstance(note, str) and note.strip():
        base["change_note"] = note
    # The words the reader wrote in the editor (edit.js), as text anchors.
    # Claude keeps them verbatim, so they ride every push untouched; a list
    # of anchors or nothing, since blocks.json is model-authored.
    mine = blk.get("mine")
    if isinstance(mine, list) and mine and all(
            isinstance(a, dict) and isinstance(a.get("selected_text"), str) for a in mine):
        base["mine"] = mine
    _RENDERERS.get(kind, _render_markdown)(blk, base)

    # Code anchors travel UNRESOLVED. The daemon resolves them on every
    # read of the item, against the session's own cwd, so an anchor keeps
    # tracking the file as it changes under a page that stays open. Resolving
    # them here would freeze the excerpt at push time — which is exactly the
    # drift the snippet field exists to survive.
    code = blk.get("code")
    # `explain` joins `mockup` in refusing the side column: this kind's whole
    # premise is that the code and its explanation are one object, so a second
    # pane of the same file beside it would restate the split it deletes.
    if kind not in ("mockup", "explain") and isinstance(code, list) and code:
        base["code"] = code
    return base
