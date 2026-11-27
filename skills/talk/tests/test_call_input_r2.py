"""Round 2, input batch: the page's language before the first answer, the mode tips, the board key, the phone's chrome."""
import json

from call_page import CallPage, needs_node, served

SET_BROWSER = "Object.defineProperty(globalThis, 'navigator', {value: {language: %r}, configurable: true});"


def language(page, topic, entries, browser):
    """What the page's language is (pageLanguage and uiLang after applyLang) with this topic, these entries and this browser."""
    page.js(SET_BROWSER % browser + "language = 'auto'; CFG.topic = %s; view.entries = %s; applyLang();" % (json.dumps(topic), json.dumps(entries)))
    page.check("[pageLanguage(), uiLang, document.documentElement.lang, $('skipmsg').textContent]")


def you(text, **extra):
    return {"id": 0, "who": "you", "text": text, **extra}


@needs_node
def test_before_any_answer_the_page_follows_a_greek_topic_or_a_greek_question_and_a_greek_browser_is_never_overridden(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states)
    language(page, "Test topic", [], "en-US")                                         # 0: nothing Greek anywhere
    language(page, "Πώς δουλεύει το DNS;", [], "en-US")                               # 1: a Greek topic
    language(page, "Test topic", [you("Τι είναι ένας ανακατευθυντής;")], "en-US")      # 2: a Greek typed question
    language(page, "Setting up DNS", [you("What is a resolver?")], "el-GR")            # 3: English topic and question, Greek browser
    language(page, "2026 11", [you("12345 ?!")], "el-GR")                             # 4: no letters at all: nothing changes
    language(page, "Test topic", [you("Τι είναι ένας ανακατευθυντής;", withdrawn=True)], "en-US")   # 5: a withdrawn turn says nothing
    language(page, "Πώς δουλεύει το DNS;", [{"id": 1, "who": "claude", "text": "An answer in English."}], "en-US")   # 6: the latest answer wins over the topic
    out = page.run()
    assert out[0][:3] == ["en", "en", "en"] and out[0][3] == "Skip to the message"
    assert out[1][:3] == ["el", "el", "el"] and out[1][3] == "Μετάβαση στο μήνυμα"
    assert out[2][:3] == ["el", "el", "el"]
    assert out[3][:3] == ["el", "el", "el"]
    assert out[4][:3] == ["el", "el", "el"]
    assert out[5][:3] == ["en", "en", "en"]
    assert out[6][:3] == ["en", "en", "en"]


def test_the_stage_status_line_says_what_following_means_in_both_languages():
    from call_page import STATIC
    import re
    text = (STATIC / "call-i18n.js").read_text()
    assert re.findall(r'"s\.fol\.following": "([^"]*)"', text) == ["Following the voice", "Ακολουθεί τη φωνή"]
