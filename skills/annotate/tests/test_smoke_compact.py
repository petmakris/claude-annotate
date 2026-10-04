"""Structural guards for the compact control.

Compact replaced the private fold. Its first guarantee is therefore a
negative one: the fold apparatus must be gone, not merely unreferenced.
A surviving `data-read` rule or an orphaned `toggleUnitRead` is how a
replaced feature comes back to life six months later.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
import re
from pathlib import Path
from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

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

# Every identifier the fold owned. None may survive in any form.
FOLD_JS_SYMBOLS = (
    "annotate.read.", "READ_KEY", "loadRead", "saveRead",
    "toggleUnitRead", "toggleBlockRead", "applyReadState", "applyBlockRead",
    "readKeyForUnit", "foldable", "READ_ICON", "READ_TITLE",
)
FOLD_CSS_SELECTORS = ('[data-read="1"]', ".unit-read", ".hover-read")


def test_the_private_fold_is_gone_from_the_javascript():
    for path in (SUBUNITS_JS, SCRIPT_JS):
        src = path.read_text()
        for dead in FOLD_JS_SYMBOLS:
            assert dead not in src, f"{path.name} still carries {dead!r}"


def test_the_private_fold_is_gone_from_the_css():
    css = STYLE_CSS.read_text()
    for dead in FOLD_CSS_SELECTORS:
        assert dead not in css, f"style.css still styles {dead!r}"


def test_the_round_store_survived_the_removal():
    """The fold had its own key space. Deleting it must not have taken the
    marks store with it."""
    src = SUBUNITS_JS.read_text()
    assert "annotate.round." in src, "the round storage key vanished"


def test_no_control_survives_a_read_only_link():
    """The fold used to be the one thing a guest could do, because it never
    reached the server. Compact is an edit, so nothing is left to exempt."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .sel-menu," in css, \
        "read-only no longer hides the selection menu"
    assert "body.read-only .sel-composer," in css, \
        "read-only no longer hides the span comment box"
    assert ":not(.hover-read)" not in css and ":not(.unit-read)" not in css, \
        "a read-only carve-out for the deleted fold survived"


def test_the_legend_does_not_advertise_a_private_control():
    src = SERVER_PY.read_text()
    assert ">Fold<" not in src, "the legend still lists the removed fold"
    assert "legend-private" not in src, \
        "the legend still marks a row as private to the browser"
    assert "Claude is never told" not in src, \
        "the legend still promises a control that sends nothing"


EYE_OFF = '<line x1="1" y1="1" x2="23" y2="23"/>'


def test_compact_is_in_the_wire_vocabulary():
    """CONTROL_SPECS is the list of kinds that reach Claude. Compact belongs
    in it — that is precisely the difference from the fold it replaced."""
    src = SUBUNITS_JS.read_text()
    start = src.index("const CONTROL_SPECS")
    end = src.index("];", start)
    spec = src[start:end]
    for kind in ('"delete"', '"comment"', '"compact"'):
        assert kind in spec, f"round vocabulary is missing {kind}"
    assert '"keep"' not in spec, "the retired keep control is back"


def test_both_scopes_offer_compact_with_the_same_glyph():
    subunits = SUBUNITS_JS.read_text()
    selection = SELECTION_JS.read_text()
    assert "COMPACT_ICON" in subunits, "subunits.js does not define the glyph"
    assert EYE_OFF in subunits, "the dock's compact glyph is not the eye-off icon"
    assert EYE_OFF in selection, "the menu glyph is not the eye-off icon"
    assert '["compact",' in selection, \
        "the selection menu does not carry a compact act"


def test_table_rows_can_be_compacted():
    """The fold excluded <tr> because a row cannot be height-clamped. Compact
    clamps nothing, so the exclusion must not have been carried over."""
    src = SUBUNITS_JS.read_text()
    assert 'tagName !== "TR"' not in src, \
        "the fold's table-row exclusion survived into compact"


def test_compact_has_its_own_pending_appearance():
    """Delete strikes through, keep tints green. Compact must not be
    mistakable for either — it is the only one that is lossy AND silent."""
    css = STYLE_CSS.read_text()
    assert 'section.block[data-block-mark="compact"]' in css, \
        "a pending block-scope compact does not light its control"
    assert "::highlight(annotate-compact)" in css, \
        "a pending span-scope compact has no highlight"


def test_the_legend_explains_compact_honestly():
    """The legend is the only place the lossiness is stated. If it claims
    nothing is lost, the control is mis-sold."""
    src = SERVER_PY.read_text()
    assert ">Compact<" in src, "the legend does not list compact"
    assert "<span>Compact</span>" in src, "the legend draws no compact row"
    assert EYE_OFF in src, "the legend glyph drifted from the button's"


def test_the_dead_private_legend_style_is_gone():
    css = STYLE_CSS.read_text()
    assert ".legend-private" not in css, \
        "styling survives for a legend row that no longer exists"


def _highlight_rule(css, name):
    """The body of the `::highlight(<name>)` rule that has no selector in
    front of it: the one that paints every mark of that kind."""
    i = css.index(f"\n::highlight({name})")
    return css[css.index("{", i):css.index("}", i) + 1]


def test_compact_reads_as_heavier_than_it_did():
    """Compact discards detail the user never chose to lose, so it must not
    look gentler than delete, which removes content they did choose to.

    Weight carries this: a violet wash and a heavy underline. A consequence
    line beside each mark was tried and removed: repeated on every mark it read
    as wallpaper instead of a warning. The warning belongs at submit time,
    where the round drawer lists each pending compact by name with a x."""
    rule = _highlight_rule(STYLE_CSS.read_text(), "annotate-compact")
    assert "#7c3aed" in rule and "background-color" in rule, \
        f"the compact mark lost its violet wash: {rule}"
    assert "underline 2px" in rule, f"the compact mark lost its weight: {rule}"


def test_compact_still_is_not_delete():
    """Heavier, but never struck through — strikethrough is delete's, and
    conflating them is the failure this styling exists to avoid."""
    css = STYLE_CSS.read_text()
    assert "line-through" not in _highlight_rule(css, "annotate-compact"), \
        "compact was made to look like delete"
    assert "line-through" in _highlight_rule(css, "annotate-delete"), \
        "delete is no longer struck through"


def test_there_is_no_keep_control():
    """"Leave as written" promised Claude would not rewrite a sentence, but
    Claude rewrites only what a round asks about, so it did nothing."""
    for f in (SUBUNITS_JS, SCRIPT_JS, SERVER_PY):
        assert "Leave as written" not in f.read_text()
    assert 'id: "keep"' not in SCRIPT_JS.read_text()


def test_no_static_file_hides_a_raw_nul_byte():
    """A literal 0x00 in a source file makes the WHOLE file invisible to
    every line-based tool — grep, ripgrep, most editors' search, diff
    viewers all silently report nothing for it. `file(1)` calls such a file
    `data`, not `text`. This bit script.js once (commit 81013cc, a NUL used
    as an unambiguous join delimiter); catch it structurally so it can't
    happen again without a test failing first."""
    for path in sorted(STATIC.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert b"\x00" not in data, \
            f"{path.name} contains a raw NUL byte — it will read as binary " \
            "to grep and most editors; use an escape sequence instead"


def test_there_is_no_disagree_checkbox():
    """The words of a comment already say whether the reader disagrees, and
    Claude weighs every comment on its merits, so a checkbox added nothing."""
    for f in (SUBUNITS_JS, SCRIPT_JS):
        src = f.read_text()
        assert "I disagree" not in src.replace('no separate "I disagree" flag', "")
        assert ".disagree" not in src and "disagree:" not in src
    assert "stance" not in STYLE_CSS.read_text()
