"""Structural guards for span and block marks + batched review rounds.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
SELECTION_JS = STATIC / "selection.js"
# The page shell and its asset list used to be printed by server.py; they now
# live in the renderer the daemon loads — shell.js for the markup, entry.js for
# which stylesheets and scripts are pulled in and in what order. These tests
# assert against the page's source either way, so they read both.
class _PageSource:
    """The page's markup and its asset list, as a single string to assert on.

    shell.js holds the markup as a JSON-encoded JS string literal, so reading
    the file raw would hand these tests `id=\\"block-search\\"` and every
    markup assertion would fail on the escaping rather than on the thing it
    is checking. The literal is decoded back to real HTML here, and entry.js
    (which lists the stylesheets and scripts, in load order) is appended.
    """

    def __init__(self, repo):
        static = repo / "skills" / "annotate" / "static"
        self._shell = static / "shell.js"
        self._entry = static / "entry.js"

    def read_text(self, *a, **k):
        # Decoded by one shared helper: the encoding of SHELL_HTML is shell.js's
        # business, and it has already changed once.
        from .shell_source import shell_html
        return shell_html(self._shell) + "\n" + self._entry.read_text(*a, **k)


SERVER_PY = _PageSource(REPO)


def _code(src):
    """`src` with its `//` comments blanked, so a literal that survives only in
    a comment explaining it can no longer satisfy an assertion."""
    return "\n".join(line.split("//", 1)[0] if line.lstrip().startswith("//")
                     else line for line in src.splitlines())


def _body(src, signature):
    """The brace-balanced body of the first function whose text starts with
    `signature`, comments removed. Scoping an assertion to one function is
    what makes it fail when that function stops doing the thing."""
    start = src.index(signature)
    open_at = src.index("{", start)
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return _code(src[open_at:i + 1])
    raise AssertionError(f"unbalanced body for {signature!r}")


def test_subunits_js_exists_with_public_api():
    src = SUBUNITS_JS.read_text()
    for needle in ("window.AnnotateSubunits", "onPoll", "localStorage"):
        assert needle in src, f"subunits.js missing {needle!r}"
    exported = _code(src.split("window.AnnotateSubunits = {", 1)[1].split("};", 1)[0])
    for name in ("setSpanMark", "spanMarkAt", "paintSpans"):
        assert re.search(rf"\b{name}\b", exported), f"AnnotateSubunits does not export {name}"
    assert not re.search(r"\bdecorate\b", exported), "the sentence strip's decorate is back"


def test_the_round_goes_out_as_one_round_event():
    """Read from submitRound itself: `"round"` also appears in the file's
    header comment, so a file-wide search passed with submitRound sending a
    plain comment instead."""
    body = _body(SUBUNITS_JS.read_text(), "function submitRound()")
    assert 'type: "round"' in body, "submitRound no longer sends a round"
    assert "reactions" in body


def test_subunits_anchors_authored_annotate_ids_by_id():
    """Words selected inside an authored data-annotate-id region carry the id
    as step_id, so the reaction survives a rewrite of those words."""
    src = (STATIC / "anchors.js").read_text()
    assert 'closest("[data-annotate-id]")' in src
    assert "a.step_id = authored.dataset.annotateId" in src


def test_subunits_prunes_orphan_marks_before_submit_and_render():
    """A block/unit Claude has already removed must never reach the wire —
    server.py's _handle_round 422s the WHOLE round on the first unknown
    block_id, so an unpruned orphan would wedge Submit forever."""
    src = SUBUNITS_JS.read_text()
    for needle in ("pruneMarks", "booted", "main.prose section.block"):
        assert needle in src, f"subunits.js missing prune guard {needle!r}"
    # pruneMarks must run at the top of both call sites the reviewer named.
    assert "function renderDock() {\n    pruneMarks();" in src
    assert "function submitRound() {\n    pruneMarks();" in src


def test_a_dead_watcher_keeps_the_round_locked():
    """A dead watcher does NOT clear the round. Its event is still queued and a
    fresh watcher re-emits it, so re-arming Submit would apply it twice. The
    dock only changes what it says. (This test was once named for the
    opposite, and asserted only that two identifiers existed.)"""
    body = _body(SUBUNITS_JS.read_text(), "function onPoll(")
    assert "sessionDead" in body and "watcher_age_s" in body, \
        "onPoll no longer notices a dead watcher"
    assert "pendingRound = null" not in body, \
        "a dead watcher re-arms Submit for a round that is still queued"


def test_subunits_surfaces_submit_failure():
    assert "roundError" in SUBUNITS_JS.read_text()


def test_server_page_includes_subunits_script():
    assert "subunits.js" in SERVER_PY.read_text()


def test_one_vocabulary_at_both_scopes():
    """The selection menu and the round's dock must speak the same three
    controls. The original confusion was two overlapping strips with
    different verbs (comment/reject/dismiss vs agree/dismiss/comment), so
    a drift back to different verb sets is the regression to catch."""
    subunits = SUBUNITS_JS.read_text()
    selection = SELECTION_JS.read_text()
    for kind in ("delete", "comment", "compact"):
        assert f'"{kind}"' in subunits, f"subunits.js lost the {kind!r} control"
        assert f'["{kind}",' in selection, f"selection.js lost the {kind!r} act"
    for gone in ("agree", "reject"):
        assert f'"{gone}"' not in subunits, \
            f"subunits.js still uses the retired {gone!r} vocabulary"
        assert f'"{gone}"' not in selection, \
            f"selection.js uses the retired {gone!r} vocabulary"


def test_pending_round_has_a_reachable_clear_path():
    """`clearRound()` must be reachable from something that actually happens.

    The round clears once compat.js's page lock no longer holds its event id,
    which covers an ack in this tab, in another tab, or while no tab was open.
    The behaviour is pinned by the browser suite; this keeps the two halves
    (the lock and the dock) from drifting apart without anyone noticing."""
    body = _body(SUBUNITS_JS.read_text(), "function onPoll(")
    assert "isHeld" in body and "clearRound()" in body, \
        "onPoll no longer clears a round the page lock has let go of"
    compat = (STATIC / "compat.js").read_text()
    assert "isHeld:" in compat, "compat.js no longer exposes isHeld"


def test_the_page_unlocks_on_the_ack_not_only_on_a_content_change():
    """A round of pure `keep` marks is answered without rewriting anything, so
    the ack is the only thing that moves. The ack branch must release the
    event, and it must run before the anchor check: an ack carries no anchor,
    and the check used to drop every one of them."""
    body = _body((STATIC / "compat.js").read_text(), "function toOldShape(")
    ack = body.index('"event-acked"')
    assert "release(" in body[ack:ack + 200], "the ack branch does not unlock"
    assert ack < body.index("if (!ev.anchor) return;"), \
        "acks are dropped by the anchor check before they are handled"


def test_a_block_write_unlocks_only_a_daemon_without_acks():
    """Claude writes blocks while it works; the first write is not the answer.
    Unlocking on it is kept only for a daemon too old to report acks."""
    body = _body((STATIC / "compat.js").read_text(), "function toOldShape(")
    assert 'ev.kind === "item" && isBusy() && acksReported === false' in body


def test_a_crossing_selection_is_marked_not_refused():
    sel = (STATIC / "selection.js").read_text()
    assert "Select within one section" not in sel
    assert "Select within one part" not in sel
    assert "anchorsAcross(range)" in sel


def test_a_round_names_every_block_a_mark_covers():
    sub = (STATIC / "subunits.js").read_text()
    i = sub.index("function submitRound(")
    body = sub[i:sub.index("\n  }\n", i)]
    assert "r.spans = m.spans" in body
    assert "r.spans.map((s) => s.block_id)" in body
