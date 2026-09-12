"""The document as a Confluence page body.

The invariant that matters most is negative: no output may contain storage
format. `<ac:structured-macro>` does not error on publish — it renders as raw
text in the middle of the page — so only a test keeps it out."""
from skills.annotate.confluence import body


SEQ_SPEC = {
    "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    "steps": [
        {"id": "s1", "from": "a", "to": "b", "arrow": "request", "label": "save",
         "tone": "edge", "sub": "with the id"},
        {"id": "s2", "from": "a", "to": "a", "arrow": "band", "label": "later"},
        {"id": "s3", "from": "b", "to": "a", "arrow": "event", "label": "ack"},
    ],
}
ANCHOR_OK = {
    "block_id": "section-1", "file": "a/B.java", "line": 21, "end_line": 22,
    "status": "ok", "actual_line": 21,
    "url": "https://github.com/evooq/montblanc/blob/abc/a/B.java#L21-L22",
    "lines": [{"n": 20, "text": "class B {", "role": "context"},
              {"n": 21, "text": "  @Transient", "role": "anchor"},
              {"n": 22, "text": "  String id;", "role": "window"},
              {"n": 23, "text": "}", "role": "context"}],
}


def test_a_markdown_block_becomes_a_heading_and_prose():
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "Two identities",
         "markdown": "one"}, [])
    assert out == "<h2>Two identities</h2><p>one</p>"


def test_a_flowchart_becomes_a_figure_titled_from_its_spec():
    out = body.render_block(
        {"id": "section-4", "kind": "flowchart", "svg": "<svg/>",
         "spec": {"title": "Outbound ids"}}, [])
    assert "<h2>Outbound ids</h2>" in out
    assert 'data-type="media-single"' in out
    assert "__MEDIA_ID__section-4__" in out


def test_a_sequence_carries_its_key_as_a_real_table():
    out = body.render_block(
        {"id": "section-2", "kind": "sequence", "svg": "<svg/>",
         "spec": {**SEQ_SPEC, "title": "One save"}}, [])
    assert "<table>" in out
    # Numbered steps only: a band is a heading row, not a numbered one.
    assert "<td><p>1</p></td>" in out and "<td><p>2</p></td>" in out
    assert "<td><p>3</p></td>" not in out
    assert "save" in out and "with the id" in out


def test_an_anchor_renders_its_excerpt_and_links_the_commit():
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p"},
        [ANCHOR_OK])
    assert "<pre data-hide-line-numbers=" in out
    assert "@Transient" in out
    assert ANCHOR_OK["url"] in out
    # Context lines frame the excerpt; the anchored window is what is cited.
    assert "class B {" in out


def test_an_unanswered_choice_is_marked_not_dropped():
    out = body.render_block(
        {"id": "section-5", "kind": "choice",
         "spec": {"question": "Which?", "options": [{"id": "a", "label": "A"}]}},
        [])
    assert 'data-type="panel-warning"' in out
    assert "Which?" in out


def test_a_mockup_says_what_is_missing_rather_than_vanishing():
    out = body.render_block({"id": "section-6", "kind": "mockup",
                             "spec": {"html": "<b>x</b>"}}, [])
    assert 'data-type="panel-note"' in out
    assert "mockup" in out.lower()


def test_the_page_opens_with_the_glossary_and_closes_with_provenance():
    out = body.render_page(
        glossary=[{"term": "proposalSyncId", "definition": "the bank's id"}],
        blocks=[{"id": "section-1", "kind": "markdown", "title": "T",
                 "markdown": "p"}],
        anchor_rows=[],
        repo={"ref": "origin/master", "commit": "abc123def456",
              "web": "https://github.com/evooq/montblanc",
              "resolved_at": "2026-09-12T11:40:00Z"},
        slug="the-pre-trade-id-chain")
    assert out.index("proposalSyncId") < out.index("<h2>T</h2>")
    assert 'data-type="panel-info"' in out
    assert "abc123d" in out           # short sha
    assert "origin/master" in out


def test_no_storage_format_anywhere():
    out = body.render_page(
        glossary=[{"term": "x", "definition": "y"}],
        blocks=[
            {"id": "section-1", "kind": "markdown", "title": "A",
             "markdown": "p\n\n| a |\n| --- |\n| 1 |"},
            {"id": "section-2", "kind": "sequence", "svg": "<svg/>",
             "spec": SEQ_SPEC},
            {"id": "section-4", "kind": "flowchart", "svg": "<svg/>",
             "spec": {"title": "F"}},
            {"id": "section-5", "kind": "choice",
             "spec": {"question": "Which?",
                      "options": [{"id": "a", "label": "A"}]}},
            {"id": "section-6", "kind": "mockup", "spec": {"html": "<b>x</b>"}},
        ],
        anchor_rows=[ANCHOR_OK],
        repo={"ref": "origin/master", "commit": "abc123def456",
              "web": "https://github.com/evooq/montblanc",
              "resolved_at": "2026-09-12T11:40:00Z"},
        slug="s")
    assert "<ac:" not in out
    assert "<ri:" not in out
    assert "ac:structured-macro" not in out


def test_model_authored_text_is_escaped_everywhere():
    """Escaping is the invariant that decides whether a published page is
    valid ADF or a publish failure. Every field a model can author — a
    block title, a sequence step's label/sub, a glossary term/definition, a
    choice question — must arrive escaped, not just the fields the earlier
    happy-path tests happened to leave clean."""
    # Block title reaches the <h2> escaped.
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "A & B < C",
         "markdown": "p"}, [])
    assert "<h2>A &amp; B &lt; C</h2>" in out
    assert "A & B < C" not in out

    # Sequence step label and sub reach the key table escaped.
    spec = {
        "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "steps": [
            {"id": "s1", "from": "a", "to": "b", "arrow": "request",
             "label": 'Save & "now"', "sub": 'x & y "z"'},
        ],
    }
    out = body.render_block(
        {"id": "section-2", "kind": "sequence", "svg": "<svg/>", "spec": spec},
        [])
    assert "&amp;" in out and "&quot;" in out
    assert 'Save & "now"' not in out
    assert 'x & y "z"' not in out

    # Glossary term and definition reach the table escaped.
    out = body.render_page(
        glossary=[{"term": "A < B", "definition": "x < y"}],
        blocks=[], anchor_rows=[],
        repo={"ref": "r", "commit": "c", "web": "w", "resolved_at": "t"},
        slug="s")
    assert "A &lt; B" in out and "x &lt; y" in out
    assert "A < B" not in out and "x < y" not in out

    # Choice question reaches the warning panel escaped.
    out = body.render_block(
        {"id": "section-5", "kind": "choice",
         "spec": {"question": "Which & why?",
                  "options": [{"id": "a", "label": "A"}]}},
        [])
    assert "Which &amp; why?" in out
    assert "Which & why?" not in out


def test_markdown_html_is_not_double_escaped():
    # to_html already escapes/produces real markup; body.py must not
    # re-escape its output on top.
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "T",
         "markdown": "**bold**"}, [])
    assert "<strong>bold</strong>" in out
    assert "&lt;strong&gt;" not in out


def test_the_caption_distinguishes_the_cited_lines_from_the_span_on_screen():
    # The caption says `a/B.java:21-22` while the <pre> shows lines 20-23,
    # because `_build` frames every anchor with context lines. That gap has to
    # be stated somewhere or the caption is a claim about four lines that only
    # two of them support.
    #
    # It used to be stated with a numbered gutter and a bar on the cited rows.
    # That was wrong for Confluence, which numbers the block itself: every line
    # arrived with two numbers side by side, and the gutter — not being source
    # — defeated the syntax highlighter. The caption carries it instead, and
    # the code is left verbatim so it can be highlighted and copied.
    out = body.render_block(
        {"id": "section-1", "kind": "markdown", "title": "T", "markdown": "p"},
        [ANCHOR_OK])
    assert "a/B.java:21-22" in out
    assert "20-23" in out
    assert "  @Transient" in out
    assert "21 |" not in out


def test_a_figure_declares_its_width_as_a_percentage():
    """Confluence reads a bare `data-width` on a media-single as PIXELS.

    The format guide calls the attribute a percentage, and the first real
    publish came back stored as `data-width="80" data-width-type="pixel"` —
    which renders a 2292px diagram as an 80px thumbnail. The unit has to be
    stated, not assumed. Only a real publish showed this; the guide alone
    would never have.
    """
    out = body.figure("section-4", "F")
    assert 'data-width-type="percentage"' in out
    assert 'data-width-type="pixel"' not in out


JAVA_ANCHOR = {
    "block_id": "section-1", "file": "src/main/java/a/B.java", "line": 21,
    "end_line": 22, "status": "ok", "actual_line": 21,
    "url": "https://github.com/evooq/montblanc/blob/abc/src/main/java/a/B.java#L21-L22",
    "lines": [{"n": 20, "text": "class B {", "role": "context"},
              {"n": 21, "text": "  @Transient", "role": "anchor"},
              {"n": 22, "text": "  String id;", "role": "window"},
              {"n": 23, "text": "}", "role": "context"}],
}


def test_an_excerpt_declares_its_language_so_confluence_highlights_it():
    """Confluence highlights a code block from `class="language-*"`. Without
    it the block renders as undifferentiated grey text, which is what the
    first published page did."""
    out = body._excerpt(JAVA_ANCHOR)
    assert '<code class="language-java">' in out


def test_an_excerpt_does_not_print_its_own_line_numbers():
    """Confluence numbers a code block itself, from 1. Printing the file's
    real numbers inside the text too gives every line two different numbers
    side by side — `9  27 |` — and breaks syntax highlighting, because the
    gutter is not source."""
    out = body._excerpt(JAVA_ANCHOR)
    body_text = out.split("<code", 1)[1].split("</code>", 1)[0]
    assert "21 |" not in body_text
    assert "  @Transient" in body_text


def test_an_excerpt_hides_confluence_numbering_because_it_would_start_at_one():
    """A window over lines 20-23 numbered 1-4 invites the reader to believe
    the file starts there. The caption carries the real range instead."""
    assert 'data-hide-line-numbers="true"' in body._excerpt(JAVA_ANCHOR)


def test_a_caption_says_which_lines_are_cited_and_which_are_shown():
    out = body._excerpt(JAVA_ANCHOR)
    assert "B.java:21-22" in out
    assert "20-23" in out


def test_an_unknown_extension_gets_no_language_class():
    anchor = {**JAVA_ANCHOR, "file": "notes.weirdext",
              "lines": [{"n": 1, "text": "x", "role": "anchor"}]}
    out = body._excerpt(anchor)
    assert "<code>" in out and "language-" not in out


def test_a_diagram_is_laid_out_wide_enough_to_read():
    """At the default centred width a 2292px diagram renders about 544px
    across — legible only after clicking it. A diagram is the thing the
    reader came for, so it gets the wide container."""
    out = body.figure("section-4", "F")
    assert 'data-layout="wide"' in out
    assert 'data-width="100"' in out
    assert 'data-width-type="percentage"' in out


def test_a_landscape_diagram_goes_full_width():
    """`wide` resolved to 680px on the real page — no wider than ordinary
    prose, and unreadable for a 2292px sequence grid. A landscape diagram
    takes the full page width instead."""
    out = body.figure("section-4", "F", size=(2292, 1132))
    assert 'data-layout="full-width"' in out


def test_a_portrait_diagram_stays_in_the_wide_container():
    """Full width on a tall narrow diagram upscales it past its own
    resolution and makes the reader scroll past a soft, enormous picture."""
    out = body.figure("section-6", "F", size=(1090, 1576))
    assert 'data-layout="wide"' in out
    assert 'data-layout="full-width"' not in out


def test_a_diagram_of_unknown_size_stays_wide():
    """No dimensions means no judgement to make; the safe container wins."""
    assert 'data-layout="wide"' in body.figure("section-4", "F")


def test_picture_sizes_reach_the_page_renderer():
    out = body.render_page(
        glossary=[],
        blocks=[{"id": "section-4", "kind": "flowchart", "svg": "<svg/>",
                 "spec": {"title": "F"}}],
        anchor_rows=[],
        repo={"ref": "origin/master", "commit": "abc123def456",
              "web": "https://github.com/evooq/montblanc",
              "resolved_at": "2026-09-12T11:40:00Z"},
        slug="s", sizes={"section-4": (2292, 1132)})
    assert 'data-layout="full-width"' in out


def test_the_shape_comes_from_the_svg_when_no_size_is_supplied():
    """Deriving it from the stored SVG rather than the rendered PNG keeps the
    body byte-identical whether or not images were rendered this run — which
    is what the manifest round-trip depends on."""
    wide_svg = '<svg width="2292" height="1132" viewBox="0 0 2292 1132"></svg>'
    tall_svg = '<svg width="1090" height="1576" viewBox="0 0 1090 1576"></svg>'
    landscape = body.render_block(
        {"id": "section-4", "kind": "flowchart", "svg": wide_svg,
         "spec": {"title": "F"}}, [])
    portrait = body.render_block(
        {"id": "section-6", "kind": "flowchart", "svg": tall_svg,
         "spec": {"title": "F"}}, [])
    assert 'data-layout="full-width"' in landscape
    assert 'data-layout="wide"' in portrait


def test_an_svg_without_dimensions_falls_back_to_wide():
    out = body.render_block(
        {"id": "section-4", "kind": "flowchart", "svg": "<svg></svg>",
         "spec": {"title": "F"}}, [])
    assert 'data-layout="wide"' in out
