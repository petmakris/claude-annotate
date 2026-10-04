"""Rich choice options and choice queues, in a real browser.

Reuses the live-daemon harness in test_browser_review.py: its `document`
fixture creates a throwaway session served from this checkout, and `page`
opens it in Chromium. Skips without playwright or without a daemon."""
from __future__ import annotations

import json

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()

from skills.annotate.tests.test_browser_review import (  # noqa: E402,F401
    BLOCKS, REPO, _call, document, page)

JAVA = "public record Asset(\n    String id\n) {}"


def _rich(anchor, question, group=None):
    spec = {"question": question, "options": [
        {"id": "o1", "label": "Original", "markdown": f"```java\n{JAVA}\n```"},
        {"id": "o2", "label": "Now",
         "markdown": "Plain **text** and a [link](https://example.com/x)."},
        {"id": "o3", "label": "Mix", "description": "Name the fields"},
    ]}
    if group:
        spec["group"] = group
    return {"id": anchor, "kind": "choice", "spec": spec}


def _md(anchor, text):
    return {"id": anchor, "kind": "markdown", "markdown": text}


def _publish(page, document, blocks):
    base, sid = document["base"], document["sid"]
    for b in blocks:
        _call(base, "PUT", f"/s/{sid}/items/{b['id']}", b)
    _call(base, "PUT", f"/s/{sid}/items/__doc__",
          {"response_id": "resp-browser-suite", "title": "annotate browser suite",
           "order": BLOCKS + [b["id"] for b in blocks], "cwd": str(REPO),
           "glossary": []})
    page.reload()
    page.wait_for_selector(
        f'section.block[data-block-id="{blocks[-1]["id"]}"]', state="attached")
    # The blocks paint before entry.js has loaded the rest: search.js among
    # them. A test that types into the search box before then types into a
    # field nothing listens to. maximize.js loads after search.js.
    page.wait_for_function("() => !!window.AnnotateMaximize", timeout=T(15000))


def _opt(anchor, n):
    return f'section.block[data-block-id="{anchor}"] .choice-option >> nth={n}'


def test_a_rich_option_renders_its_code_highlighted(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    code = page.locator(
        'section.block[data-block-id="rich"] .choice-option >> nth=0'
    ).locator(".choice-option-body pre code.sk-fence.language-java")
    assert code.count() == 1
    assert "public record Asset(" in code.inner_text()
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.has-body').count() == 2
    assert page.js_errors == []


def test_selecting_text_in_an_option_does_not_pick_it(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => {
      const code = document.querySelector(
        'section.block[data-block-id="rich"] .choice-option-body code');
      const r = document.createRange(); r.selectNodeContents(code);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      code.click();
    }""")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 0
    selected_text = page.evaluate("() => getSelection().toString()")
    assert "public record Asset(" in selected_text, "the code cannot be selected"

    # The selection is still live: a label click must pick regardless.
    page.click(_opt("rich", 0) + " >> .choice-option-label")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 1


def test_a_link_in_an_option_does_not_pick_it(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => document.addEventListener('click', e => {
      if (e.target.closest('a[href]')) e.preventDefault(); }, true)""")
    page.click(_opt("rich", 1) + " >> .choice-option-body a")
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 0


def test_a_plain_choice_is_unchanged(page, document):
    plain = {"id": "plain", "kind": "choice", "spec": {"question": "Size?",
             "options": [{"id": "o1", "label": "S"}, {"id": "o2", "label": "L"}]}}
    _publish(page, document, [plain])
    assert page.locator('section.block[data-block-id="plain"] .choice-option-body').count() == 0
    assert page.locator('section.block[data-block-id="plain"] .has-body').count() == 0
    page.click(_opt("plain", 1))
    assert page.locator('section.block[data-block-id="plain"] .choice-option.selected').count() == 1


def _queue(page, document, n=3, group="Decisions", extra=()):
    blocks = [_rich(f"q{i}", f"Question {i}?", group) for i in range(1, n + 1)]
    _publish(page, document, blocks + list(extra))


def _goto(page, anchor):
    page.evaluate(f"() => window.AnnotateChoiceQueue.show('{anchor}')")
    page.wait_for_function(_q_shown(anchor))


def _visible(page, anchor):
    return page.locator(f'section.block[data-block-id="{anchor}"]').is_visible()


def test_grouped_choices_collapse_into_one_queue(page, document):
    loose = {"id": "loose", "kind": "choice", "spec": {"question": "Loose?",
             "options": [{"id": "o1", "label": "Y"}, {"id": "o2", "label": "N"}]}}
    _queue(page, document, extra=[loose])
    bar = page.locator('.cq-bar')
    assert bar.count() == 1
    assert "Decisions" in bar.inner_text()
    assert "File 1 of 3" in bar.inner_text()
    assert _visible(page, "q1") and not _visible(page, "q2") and not _visible(page, "q3")
    assert _visible(page, "loose")
    assert page.js_errors == []


def test_a_pick_records_on_the_member_and_moves_on(page, document):
    _queue(page, document)
    posts = []
    page.on("request", lambda r: posts.append(r.post_data or "") if r.method == "POST" else None)
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('[data-block-id=\"q2\"]')).display !== 'none'")
    assert "File 2 of 3 · 1 decided" in page.inner_text(".cq-bar")
    page.fill('section.block[data-block-id="q2"] .choice-note', "typing does not move")
    page.wait_for_timeout(300)
    assert _visible(page, "q2")

    page.click("#round-submit")
    page.wait_for_function("() => document.body.classList.contains('is-busy')", timeout=T(10000))
    sent = [p for p in posts if "selected_options" in p]
    env = json.loads(json.loads(sent[0])["text"])
    by_block = {r["block_id"]: r for r in env["reactions"]}
    assert by_block["q1"]["selected_options"] == ["o1"]
    assert by_block["q2"]["text"] == "typing does not move"


def test_the_last_pick_stays_put(page, document):
    _queue(page, document, n=2)
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.wait_for_function("() => document.querySelector('.cq-bar').innerText.includes('File 2 of 2')")
    page.click(_opt("q2", 1) + " >> .choice-option-label")
    page.wait_for_timeout(400)
    assert _visible(page, "q2")
    assert "2 decided" in page.inner_text(".cq-bar")


def test_j_and_k_walk_the_queue_then_leave_it(page, document):
    _queue(page, document, n=2, extra=[_md("after", "The block after the queue.")])
    page.evaluate("() => window.AnnotateKeyboard.focusBlock('q1')")
    page.keyboard.press("j")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q2'")
    assert _visible(page, "q2") and not _visible(page, "q1")
    page.keyboard.press("j")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'after'")
    page.keyboard.press("k")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q2'")
    page.keyboard.press("k")
    page.wait_for_function("() => window.AnnotateKeyboard.focusedId() === 'q1'")
    assert _visible(page, "q1")


def test_show_all_expands_and_survives_a_reload(page, document):
    _queue(page, document)
    page.check(".cq-bar .cq-all input")
    assert all(_visible(page, f"q{i}") for i in (1, 2, 3))
    page.reload()
    page.wait_for_selector(".cq-bar")
    assert all(_visible(page, f"q{i}") for i in (1, 2, 3))
    page.uncheck(".cq-bar .cq-all input")
    assert sum(_visible(page, f"q{i}") for i in (1, 2, 3)) == 1


def test_the_position_survives_a_reload(page, document):
    _queue(page, document)
    _goto(page, "q3")
    assert _visible(page, "q3")
    page.reload()
    page.wait_for_selector(".cq-bar")
    assert _visible(page, "q3") and not _visible(page, "q1")


def test_two_runs_of_one_group_are_two_queues(page, document):
    blocks = [_rich("a1", "A1?", "G"), _rich("a2", "A2?", "G"), _md("split", "between"),
              _rich("b1", "B1?", "G"), _rich("b2", "B2?", "G")]
    _publish(page, document, blocks)
    assert page.locator(".cq-bar").count() == 2
    page.locator(".cq-bar >> nth=1").locator(".cq-primary").click()
    assert _visible(page, "b2") and _visible(page, "a1")


def test_a_lone_grouped_choice_is_an_ordinary_choice(page, document):
    _publish(page, document, [_rich("solo", "Solo?", "G")])
    assert page.locator(".cq-bar").count() == 0
    assert _visible(page, "solo")


def test_a_rewrite_keeps_the_current_question(page, document):
    _queue(page, document)
    _goto(page, "q2")
    base, sid = document["base"], document["sid"]
    rewritten = _rich("q2", "Question 2, reworded?", "Decisions")
    _call(base, "PUT", f"/s/{sid}/items/q2", rewritten)
    page.wait_for_function(
        "() => document.querySelector('[data-block-id=\"q2\"] .card-title')"
        ".textContent.includes('reworded')", timeout=T(15000))
    assert _visible(page, "q2") and not _visible(page, "q1")


def test_the_queue_works_with_storage_blocked(page, document):
    # Only the queue's own keys throw, so the rest of the page boots normally
    # and the test is about the queue's try/catch, not the whole page's.
    page.add_init_script("""
      for (const m of ['getItem', 'setItem']) {
        const orig = Storage.prototype[m];
        Storage.prototype[m] = function (k, ...rest) {
          if (String(k).startsWith('annotate.queue:')) throw new Error('blocked');
          return orig.call(this, k, ...rest);
        };
      }
    """)
    _queue(page, document)
    assert page.locator(".cq-bar").count() == 1
    assert _visible(page, "q1")


def test_a_multi_select_member_waits_for_next(page, document):
    first = _rich("q1", "Question 1?", "Decisions")
    first["spec"]["multiSelect"] = True
    _publish(page, document, [first, _rich("q2", "Question 2?", "Decisions")])
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.click(_opt("q1", 1) + " >> .choice-option-label")
    page.wait_for_timeout(400)
    assert _visible(page, "q1") and not _visible(page, "q2")
    assert page.locator(
        'section.block[data-block-id="q1"] .choice-option.selected').count() == 2
    page.click(".cq-bar .cq-primary")
    assert _visible(page, "q2") and not _visible(page, "q1")


def test_a_search_shows_the_matching_member_then_collapses_back(page, document):
    _queue(page, document)
    page.fill("#block-search", "Question 3")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('[data-block-id=\"q3\"]')).display !== 'none'")
    assert page.locator(".cq-bar .cq-all input").is_disabled()
    page.fill("#block-search", "")
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-block-id^=\"q\"]')]"
        ".filter(s => getComputedStyle(s).display !== 'none').length === 1")


def test_an_export_has_every_member_and_no_bar(page, document):
    _queue(page, document)
    html = page.evaluate("() => window.AnnotateExport.buildProse()")
    assert "cq-bar" not in html
    assert "cq-hidden" not in html
    for i in (1, 2, 3):
        assert f'data-block-id="q{i}"' in html


def test_a_search_does_not_loop(page, document):
    _queue(page, document)
    page.evaluate("() => { window.__n = 0;"
                  " document.addEventListener('annotate:search', () => window.__n++); }")
    page.fill("#block-search", "Question")
    page.wait_for_timeout(1000)
    assert page.evaluate("() => window.__n") == 1


def _q_shown(anchor):
    return ("() => getComputedStyle(document.querySelector("
            f"'[data-block-id=\"{anchor}\"]')).display !== 'none'")


def test_arrow_keys_move_without_advancing(page, document):
    _queue(page, document, n=2)
    page.focus(_opt("q1", 0))
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(400)
    assert _visible(page, "q1") and not _visible(page, "q2")
    assert "selected" in page.locator(_opt("q1", 2)).get_attribute("class")


def test_a_keyboard_pick_keeps_focus_in_the_queue(page, document):
    _queue(page, document, n=2)
    page.focus(_opt("q1", 0))
    page.keyboard.press("Space")
    page.wait_for_function(_q_shown("q2"))
    assert page.evaluate("""() => {
      const a = document.activeElement;
      return !!a && a.matches('.choice-option')
        && !!a.closest('section.block[data-block-id="q2"]');
    }""")


def test_a_label_click_picks_after_selecting_code(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => {
      const code = document.querySelector(
        'section.block[data-block-id="rich"] .choice-option-body code');
      const r = document.createRange(); r.selectNodeContents(code);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    }""")
    page.click(_opt("rich", 0) + " >> .choice-option-label")
    assert "selected" in page.locator(_opt("rich", 0)).get_attribute("class")


def test_the_dock_jumps_to_a_hidden_question(page, document):
    _queue(page, document)
    page.click(_opt("q1", 0) + " >> .choice-option-label")
    page.wait_for_function(_q_shown("q2"))
    assert not _visible(page, "q1")
    page.click("#round-dock .rd-summary")
    page.click("#round-dock .rd-row >> nth=0 >> .rd-body")
    page.wait_for_function(_q_shown("q1"))
    assert _visible(page, "q1") and not _visible(page, "q2")


def test_bar_buttons_keep_focus(page, document):
    _queue(page, document)
    page.focus(".cq-bar .cq-primary")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    assert "File 3 of 3" in page.inner_text(".cq-bar")
    # Next is disabled on the last question, so focus falls back to a live
    # bar button rather than to <body>.
    assert page.evaluate(
        "() => document.activeElement.matches('.cq-bar button:not([disabled])')")


def test_enter_on_a_link_in_an_option_does_not_pick(page, document):
    _publish(page, document, [_rich("rich", "Which version?")])
    page.evaluate("""() => document.addEventListener('click', e => {
      if (e.target.closest('a[href]')) e.preventDefault(); }, true)""")
    page.focus(_opt("rich", 1) + " >> .choice-option-body a")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    assert page.locator(
        'section.block[data-block-id="rich"] .choice-option.selected').count() == 0


def test_skip_passes_over_decided_questions(page, document):
    _queue(page, document)
    _goto(page, "q2")
    page.click(_opt("q2", 0) + " >> .choice-option-label")
    page.wait_for_function(_q_shown("q3"))
    _goto(page, "q1")
    page.click('.cq-bar [data-ctl="skip"]')
    assert _visible(page, "q3"), "Skip stopped on the decided q2"
    assert "File 3 of 3" in page.inner_text(".cq-bar")


def test_the_bar_is_minimal(page, document):
    """A ring, where you are, and three moves: no dots, no second progress bar."""
    _queue(page, document)
    bar = page.locator(".cq-bar")
    assert bar.locator(".cq-dot, .cq-progress").count() == 0
    assert bar.locator(".cq-ring").count() == 1
    assert bar.locator('[data-ctl="prev"]').is_disabled()
    assert bar.locator('[data-ctl="skip"]').inner_text() == "Next undecided"
    _goto(page, "q3")
    assert page.locator('.cq-bar [data-ctl="next"]').is_disabled()
