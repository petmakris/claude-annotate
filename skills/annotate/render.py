"""Block rendering for a webcompanion push.

The daemon stores items as opaque JSON and never inspects them, so
everything that used to happen per-request in annotate's own server —
compiling a flowchart's source, rasterising a sequence or mermaid spec to
SVG — happens once here, at push time, and the rendered body is what gets
stored.

Code anchors are the deliberate exception: they are left unresolved in the
body, because the daemon resolves them fresh on every read (the repository
can change while a session is open) using this same plugin's anchor format.
"""
from __future__ import annotations

from skills._shared.web_companion.templates import html_escape
from skills.annotate.diagrams.sequence import render
from skills.annotate.diagrams.mermaid import render as render_mermaid
from skills.annotate.diagrams.flowchart import render as render_flowchart
from skills.annotate.pflow import PflowError, compile_source as compile_pflow


def render_block(blk: dict) -> dict:
    """Return the stored body for one block.

    No `version`: the daemon derives that from the body's content hash and
    hands it back in the item envelope, so carrying one here would be a
    second, disagreeing source of truth.

    - markdown blocks → pass markdown through
    - sequence / flowchart / diagram → rendered svg + spec
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
    if kind == "sequence":
        spec = blk.get("spec") or {}
        try:
            svg = render(spec, block_id=blk["id"])
        except Exception as e:
            # Compact inline error pill instead of a full-width red banner.
            # Catch *any* render failure (ValidationError, or a KeyError from a
            # spec that passed validation but is missing a field the renderer
            # reads) so one malformed block can never crash the whole /raw
            # response and blank the page. The message lands in <title>.
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 36" '
                f'width="360" height="36" '
                f'class="annotate-seq annotate-seq-error" '
                f'data-block-id="{html_escape(blk["id"])}" '
                f'role="img" aria-label="sequence diagram failed to render">'
                f'<rect x="0" y="0" width="360" height="36" rx="6" '
                f'fill="#fde7e2" stroke="#e5b8af"/>'
                f'<text x="14" y="22" font-size="12" font-weight="600" '
                f'fill="#c1432f" font-family="ui-monospace, monospace">'
                f'⚠ diagram render failed</text>'
                f'<title>{html_escape(str(e))}</title>'
                f'</svg>'
            )
        base["spec"] = spec
        base["svg"] = svg
    elif kind == "flowchart":
        spec = blk.get("spec") or {}
        warnings: list[str] = []
        source = spec.get("source")
        if source:
            # Authored as pflow: nodes/edges are derived, so any that were stored
            # alongside the source are stale by definition and get replaced.
            try:
                compiled = compile_pflow(source, filename=blk["id"])
                warnings = compiled.pop("warnings", [])
                spec = {**spec, **compiled}
            except PflowError as e:
                spec = {**spec, "nodes": [], "edges": []}
                source_error = str(e)
            else:
                source_error = None
        else:
            source_error = None
        try:
            if source_error:
                raise ValueError(source_error)
            svg = render_flowchart(spec, block_id=blk["id"])
        except Exception as e:
            # Compact inline error pill — one malformed block must never
            # crash /raw and blank the page (same pattern as sequence/diagram).
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 36" '
                f'class="annotate-flow annotate-flow-error" '
                f'data-block-id="{html_escape(blk["id"])}" '
                f'role="img" aria-label="flowchart failed to render">'
                f'<rect x="0" y="0" width="360" height="36" rx="6" '
                f'fill="#fde7e2" stroke="#e5b8af"/>'
                f'<text x="14" y="22" font-size="12" font-weight="600" '
                f'fill="#c1432f" font-family="ui-monospace, monospace">'
                f'⚠ diagram render failed</text>'
                f'<title>{html_escape(str(e))}</title>'
                f'</svg>'
            )
        base["spec"] = spec
        base["svg"] = svg
        if warnings:
            base["warnings"] = warnings
    elif kind == "diagram":
        spec = blk.get("spec") or {}
        try:
            svg = render_mermaid(spec, block_id=blk["id"])
        except Exception as e:
            # Same compact error pill as the sequence branch: one malformed
            # block must never crash /raw and blank the page.
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 36" '
                f'class="annotate-diagram annotate-diagram-error" '
                f'data-block-id="{html_escape(blk["id"])}" '
                f'role="img" aria-label="mermaid diagram failed to render">'
                f'<rect x="0" y="0" width="360" height="36" rx="6" '
                f'fill="#fde7e2" stroke="#e5b8af"/>'
                f'<text x="14" y="22" font-size="12" font-weight="600" '
                f'fill="#c1432f" font-family="ui-monospace, monospace">'
                f'⚠ diagram render failed</text>'
                f'<title>{html_escape(str(e))}</title>'
                f'</svg>'
            )
        base["spec"] = spec
        base["svg"] = svg
    elif kind == "choice":
        base["spec"] = blk.get("spec") or {}
    elif kind == "mockup":
        # Trusted Claude HTML rendered client-side in a sandboxed iframe.
        # Server forwards the spec verbatim; it never parses or renders the HTML.
        base["spec"] = blk.get("spec") or {}
    else:
        base["markdown"] = blk.get("markdown", "")

    # Code anchors travel UNRESOLVED. The daemon resolves them on every
    # read of the item, against the session's own cwd, so an anchor keeps
    # tracking the file as it changes under a page that stays open. Resolving
    # them here would freeze the excerpt at push time — which is exactly the
    # drift the snippet field exists to survive.
    code = blk.get("code")
    if kind != "mockup" and isinstance(code, list) and code:
        base["code"] = code
    return base
