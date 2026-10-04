"""Guards on the round contract Claude executes.

Everything else in this feature is a control that queues an intent. This file
guards the half that acts on it. Two failure modes are worth a test each: the
contract describing compact as if it were delete, and the sweep drifting to
after the ack — which is when the user sees the page, so a sweep after it is
a sweep the user watches happen.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "skills" / "annotate" / "references" / "handling-events.md"


def test_compact_is_in_the_kind_table():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "`compact`" in doc, "the contract does not mention compact"


def test_compact_is_distinguished_from_delete():
    """The single most important line in the contract. If compact reads as a
    synonym for delete, Claude stops acting on content the user only wanted
    off the page."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still binds" in doc, \
        "the contract does not say a compacted idea still binds the plan"
    assert "out of scope" in doc, \
        "the contract lost the phrase that makes delete's meaning explicit"


def test_keep_is_not_a_kind():
    """The page no longer offers "Leave as written", so the contract must not
    teach Claude to expect it."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "| `keep` |" not in doc
    assert '`"keep"`' not in doc


def test_nothing_is_stored_off_page():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "no hidden store" in doc.lower() or "not retained" in doc.lower(), \
        "the contract does not forbid retaining compacted content"


def test_the_sweep_runs_before_the_ack():
    """Order is the whole point: the ack unlocks the page. Anchored on the
    `## The coherence sweep` heading itself, not the first occurrence of the
    phrase anywhere in the doc — the Mode D universal-rule paragraph also
    says "coherence sweep" and sits thousands of characters away from this
    section, so anchoring on the phrase alone can miss the section entirely."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "## The coherence sweep" in doc, "the contract has no coherence sweep section"
    sweep = doc.index("## The coherence sweep")
    section = doc[sweep:sweep + 2500].lower()
    assert "before" in section and "ack" in section, \
        "the sweep does not state its position relative to the ack"


def test_reject_is_named_alongside_dismiss_in_the_universal_rule():
    """`reject` is a live legacy path — server.py accepts it alongside
    `dismiss` — not a hypothetical. Both places that illustrate the
    universal pre-ack rule's coverage must name it, or a reader can mistake
    the illustrative list for a closed set that excludes it."""
    doc = CONTRACT.read_text(encoding="utf-8")
    mode_d = doc.index("## Mode D")
    model_para = doc.index("## The model in one paragraph")
    universal_rule = doc[mode_d:model_para].lower()
    assert "reject" in universal_rule, \
        "the Mode D universal-rule paragraph does not name reject"

    sweep_heading = doc.index("## The coherence sweep")
    block_contract = doc.index("## Block-rewrite contract")
    sweep_section = doc[sweep_heading:block_contract].lower()
    assert "reject" in sweep_section, \
        "the coherence sweep section opening does not name reject"


def test_reject_edge_case_points_at_the_sweep():
    """The reject bullet in the block-rewrite contract mutates blocks.json
    via a non-null block_id and then acks — the same pre-ack condition as
    every other path — so it must point at the sweep the way the choice and
    general-comment paths do, rather than silently skipping it."""
    doc = CONTRACT.read_text(encoding="utf-8")
    reject_bullet = doc.index("The `type` is `reject`")
    next_bullet = doc.index("The user's `selected_text` no longer exists")
    section = doc[reject_bullet:next_bullet].lower()
    assert "coherence sweep" in section, \
        "the reject edge case does not point at the coherence sweep"


def test_the_sweep_is_bounded():
    """An unbounded 'make it all coherent' pass churns the whole document
    every round and inflates versions on blocks the user never touched."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "still reads true" in doc, \
        "the contract does not forbid rewriting blocks that are still true"


def test_the_sweep_is_a_universal_pre_ack_rule():
    """The sweep must not read as round-only. It was written under the round
    subsection and a review found several other paths mutate blocks.json and
    ack with no sweep. The rule has to be stated once, generally, so every
    path inherits it instead of drifting out of sync with a per-path bullet."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "universal" in doc.lower(), \
        "the contract does not state the sweep as a universal rule"
    assert "not a step scoped to" in doc or "not a round-only step" in doc.lower(), \
        "the contract does not disclaim the sweep as round-only"


def test_the_choice_path_references_the_sweep():
    """Resolving a choice both converts the block and appends follow-ups —
    the highest-risk path of all, since nothing else checks the two against
    the rest of the document. Bounded to the choice subsection's own heading
    through the next subsection's heading, so this can't pass on a sweep
    mention that lives in a neighbouring section."""
    doc = CONTRACT.read_text(encoding="utf-8")
    choice = doc.index('### `WEBCOMPANION_EVENT` with `type: "choice"`')
    dismiss = doc.index('### `WEBCOMPANION_EVENT` with `type: "dismiss"`')
    section = doc[choice:dismiss].lower()
    assert "coherence sweep" in section, \
        "the choice path does not reference the coherence sweep"


def test_the_general_comment_path_references_the_sweep():
    """A cross-document directive ('make this shorter') can orphan a
    reference or glossary term elsewhere with nothing checking. Anchored on
    the block-rewrite contract's null-block_id subsection specifically, not
    just any mention of the phrase 'general comment' in the document."""
    doc = CONTRACT.read_text(encoding="utf-8")
    general = doc.index("`block_id` is absent or `null` (a general comment")
    section = doc[general:general + 800].lower()
    assert "coherence sweep" in section, \
        "the general-comment path does not reference the coherence sweep"


def test_dismiss_is_covered_by_the_same_rule():
    """Dismiss is legacy but still mutates blocks.json and writes the ack —
    it does not get a special case. Bounded to the dismiss subsection's own
    heading through the next subsection's heading (round), so this can't
    pass on the round subsection's own sweep step instead."""
    doc = CONTRACT.read_text(encoding="utf-8")
    dismiss = doc.index('### `WEBCOMPANION_EVENT` with `type: "dismiss"`')
    round_ = doc.index('### `WEBCOMPANION_EVENT` with `type: "round"`')
    section = doc[dismiss:round_].lower()
    assert "coherence sweep" in section, \
        "the dismiss path does not reference the coherence sweep"


def test_the_contract_describes_the_change_note():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "change_note" in doc, "the contract does not mention change_note"


def test_a_compact_must_name_what_it_lost():
    """Compact is lossy and irreversible after submit. The change note is the
    only place the user could ever learn what it actually discarded."""
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "Lost:" in doc, \
        "the contract does not require a compact to name the dropped detail"


def test_the_change_note_is_optional():
    """A feature that breaks when Claude forgets a field is a broken feature.

    Scoped to the change_note section itself and to the specific claim, not
    a bare word search: "optional" already occurs elsewhere in the document
    (e.g. the coherence sweep is "not optional"), so an unscoped check for
    the substring alone stays green even if this whole section is deleted."""
    doc = CONTRACT.read_text(encoding="utf-8")
    start = doc.index("## Explaining a change: `change_note`")
    end = doc.index("## Block-rewrite contract")
    # Collapse whitespace: this document hand-wraps prose across source
    # lines within a paragraph (markdown treats a single newline as a
    # space), so a literal multi-word needle must not be sensitive to
    # exactly where the source happens to wrap.
    section = " ".join(doc[start:end].split())
    assert "`change_note` is **optional**" in section, \
        "the change_note section does not say change_note itself is optional"
    assert "diff renders with or without it" in section, \
        "the change_note section does not say the diff renders without it"


def test_the_sweep_covers_spec_blocks_not_just_prose():
    """A stale `choice` is the most visible staleness a page can carry.

    The sweep was written as "references that no longer resolve" plus "claims
    the change made false", and both read as being about prose. A choice
    block's staleness lives in `spec`, so a sweep that re-reads only markdown
    walks straight past a card still offering work that is finished — and it
    is invisible to a search for the block that changed, because nothing in it
    mentions that block. Observed in the wild: a user answered a choice in a
    comment, Claude did the work, and the card kept asking the question.
    """
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "Fix exactly three things" in doc, \
        "the sweep no longer enumerates three things — did spec blocks get dropped?"
    sweep = doc[doc.index("Fix exactly three things"):]
    sweep = sweep[:sweep.index("Change nothing else")]
    assert "spec" in sweep.lower(), \
        "the sweep does not mention spec blocks"
    assert "choice" in sweep.lower(), \
        "the sweep does not name a stale choice as the case to catch"


def test_a_comment_that_answers_a_choice_resolves_it():
    """Deciding in prose is deciding.

    A reader who types "let's do the second one" into a comment box has
    answered the question; only the transport differs from clicking the card.
    Without this rule the `comment` path folds the answer into prose, the work
    gets done, and the choice block is left re-asking something the reader
    considers closed.
    """
    doc = CONTRACT.read_text(encoding="utf-8")
    marker = "If the comment answers an open `choice` block"
    assert marker in doc, \
        "the comment path does not say a prose answer resolves the choice"
    section = doc[doc.index(marker):]
    section = section[:section.index("\n5. For each remaining touched block")]
    assert "resolve it in this same pass" in section, \
        "the rule does not require resolving in the same pass"



# --- the whole document's numbering, not just the event paths ----------
#
# The narration step was inserted into the four `WEBCOMPANION_EVENT` paths,
# but the renumber ran over the whole file, so nine lists that never received
# an inserted step were pushed up to start at `2.` with no step 1. Nothing
# caught it because every narration test slices the event sections out first
# — and those four were the only lists that were actually correct.


def _ordered_lists(doc):
    """Every ordered list in the document, as (first line number, numbers).

    A list is a maximal run of `N. ` markers at one indent whose numbers run
    consecutively, outside fenced code and never spanning a heading. Splitting
    on a break in the sequence is what lets a list survive the paragraphs the
    round path interleaves between its steps; the invariant left to assert is
    that each run opens at 1.
    """
    runs, cur, fenced = [], None, False
    for lineno, line in enumerate(doc.splitlines(), 1):
        if re.match(r"^\s*```", line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if re.match(r"^\s*#{1,6} ", line):
            cur = None
            continue
        m = re.match(r"^(\s*)(\d+)\. ", line)
        if not m:
            continue
        indent, n = len(m.group(1)), int(m.group(2))
        if cur is not None and cur[0] == indent and n == cur[2][-1] + 1:
            cur[2].append(n)
        else:
            cur = (indent, lineno, [n])
            runs.append(cur)
    return [(lineno, nums) for _, lineno, nums in runs]


def test_every_ordered_list_starts_at_one():
    doc = CONTRACT.read_text(encoding="utf-8")
    lists = _ordered_lists(doc)
    assert len(lists) >= 10, \
        "the list scanner stopped finding this document's lists — retarget it"
    broken = [f"line {lineno}: starts at {nums[0]} (runs {nums[0]}-{nums[-1]})"
              for lineno, nums in lists if nums[0] != 1]
    assert broken == [], \
        ("these lists have no step 1 — Claude reads this file on every event "
         "and follows the numbers: " + "; ".join(broken))


PUSHING = REPO / "skills" / "annotate" / "references" / "pushing.md"


def test_a_partial_sentence_delete_is_cut_and_repaired():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "part of a sentence" in doc
    assert "grammatical" in doc


def test_a_partial_compact_folds_into_the_same_sentence_first():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "same sentence" in doc


def test_a_comment_is_about_exactly_the_quoted_words():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "exactly the quoted words" in doc


def test_scope_is_no_longer_described_by_hovering():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "hovered the card header" not in doc
    assert "selected its title" in doc
    assert "exactly the words the reader selected" in doc
    # "sub-unit" should not describe feedback controls; only genuine technical uses remain
    bad_sub_unit_uses = [
        'sub-unit\'s plain text',
        'that sub-unit',
        'sub-unit from the block',
    ]
    for phrase in bad_sub_unit_uses:
        assert phrase not in doc, \
            f"old sub-unit control language remains: {phrase}"


def test_every_abbreviation_a_listener_may_not_know_gets_a_glossary_entry():
    doc = PUSHING.read_text(encoding="utf-8")
    assert "read-aloud" in doc and "dictation" in doc
    assert "abbreviation" in doc


def _doc():
    """The contract with line wraps collapsed, so a phrase is found wherever
    the file happens to wrap it."""
    return " ".join(CONTRACT.read_text(encoding="utf-8").split())


def _bullet(lead):
    """One bullet of "The reader's own words", from its bold lead to the next."""
    sec = _doc().split("## The reader's own words")[1].split("## Narrating")[0]
    for part in sec.split("- **")[1:]:
        if part.startswith(lead):
            return part
    raise AssertionError("no bullet leads with %r" % lead)


def test_the_edit_kind_carries_before_and_after():
    doc = _doc()
    assert '`"edit"`' in doc
    assert "`before`" in doc and "`after`" in doc


def test_an_edit_is_already_applied():
    b = _bullet("An `edit` reaction is already applied")
    assert "update the working `blocks.json` to `after` verbatim" in b
    assert "Do not write the block back only because of the edit" in b


def test_pull_comes_first_when_a_round_carries_an_edit_or_a_hold():
    b = _bullet("Pull first")
    assert "any `edit` reaction" in b and "held section" in b
    assert "claude-annotate pull --sid <sid> --out <blocks>" in b
    assert "before touching any block" in b
    assert "copy `after` into that one block by hand instead of pulling" in b


def test_a_stale_push_over_a_saved_edit_is_named_and_pull_writes_base():
    b = _bullet("Pull first")
    assert ("edited by the reader since your last push: <ids> — kept their version; "
            "pull first, then fold your change in") in b
    assert "`base`" in b
    assert "stored version" in b and "hash" not in b
    assert "leave out" in b
    assert "your change dropped the reader's words in" in _bullet("`mine` passages are final")


def test_mine_is_kept_character_for_character():
    b = _bullet("`mine` passages are final")
    assert "character for character" in b
    assert "unless a reaction on those exact words asks" in b
    assert "32 characters" in b and "adjacent" in b
    assert "immediate context" not in b


def test_the_edit_is_information_and_never_reverted():
    b = _bullet("Read the edit as information")
    assert "Never revert the reader's text" in b


def test_a_held_section_is_folded_into_the_next_round():
    b = _bullet("A held section")
    assert "held by the reader" in b
    assert "folded into the next round" in b
    assert "write down" in b and "in your reply" in b
    assert "after the round's last push" in b


# --- Markdown first (rich-editing spec 3.6) -------------------------------

PUSHING = REPO / "skills" / "annotate" / "references" / "pushing.md"
SKILL = REPO / "skills" / "annotate" / "SKILL.md"


def _paragraph(doc, needle):
    """The paragraph, or the single numbered/bulleted item, holding needle."""
    for para in re.split(r"\n\s*\n|\n(?=(?:\d+\.|-) )", doc):
        if needle in para:
            return para
    raise AssertionError(f"no paragraph contains {needle!r}")


def test_pushing_says_text_sections_are_markdown():
    para = _paragraph(PUSHING.read_text(encoding="utf-8"),
                      "Write text sections in markdown")
    for word in ("headings", "lists", "tables", "bold", "code", "links"):
        assert word in para


def test_pushing_no_longer_asks_for_data_annotate_id_on_prose():
    doc = PUSHING.read_text(encoding="utf-8")
    assert "Mark commentable sub-units with `data-annotate-id`" not in doc
    para = _paragraph(doc, "selection menu")
    assert "any words" in para and "no markup" in para


def test_pushing_names_the_three_html_exceptions():
    para = _paragraph(PUSHING.read_text(encoding="utf-8"),
                      "HTML only where markdown cannot say it")
    assert "merged table cells" in para
    assert "callout" in para
    assert '`kind: "mockup"`' in para


def test_compact_triage_and_digest_are_markdown_lists():
    doc = PUSHING.read_text(encoding="utf-8")
    triage = _paragraph(doc, "**Triage block**")
    digest = _paragraph(doc, "**Digest block**")
    assert "data-annotate-id" not in triage
    assert "data-annotate-id" not in digest
    assert "markdown list" in triage


def test_skill_menu_no_longer_offers_inline_html_for_markdown():
    doc = SKILL.read_text(encoding="utf-8")
    line = next(l for l in doc.splitlines() if l.startswith("| `markdown` (default)"))
    assert "Inline HTML" not in line


def test_rewriting_keeps_the_sections_format():
    para = _paragraph(CONTRACT.read_text(encoding="utf-8"),
                      "An HTML section stays HTML unless the reader asks otherwise.")
    assert "keep its format" in para


def test_step_id_still_arrives_for_data_annotate_id_sections():
    para = _paragraph(CONTRACT.read_text(encoding="utf-8"),
                      "`step_id` still arrives for a section that carries")
    assert "`data-annotate-id`" in para
