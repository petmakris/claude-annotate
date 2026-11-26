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


def test_each_mode_button_says_what_it_does_in_its_title_and_description_in_both_languages(tmp_path):
    html, states = served(tmp_path, [])
    pick = "[...document.querySelectorAll('#modesw button')].map((b) => [b.dataset.mode, b.title, b.getAttribute('aria-description')])"
    page = CallPage(html, states).check(pick)
    page.js("document.querySelector('#lang [data-lang=el]').click(); await settle();").check(pick)
    page.js("document.querySelector('#lang [data-lang=en]').click(); recorder = {}; paintAll();").check("[...document.querySelectorAll('#modesw button')].map((b) => [b.title, b.getAttribute('aria-description').slice(0, 20)])")
    out = page.run()
    live_en = "The microphone stays open: just speak and your turn is sent after a pause. Speaking over an answer interrupts it. The mic button mutes."
    assert out[0] == [["type", "Type your message in the field. The microphone stays off.", "Type your message in the field. The microphone stays off."],
                      ["talk", "Press the mic, speak, then press Done to send what you said.", "Press the mic, speak, then press Done to send what you said."],
                      ["live", live_en, live_en]]
    assert [row[1] for row in out[1]] == [
        "Πληκτρολογήστε το μήνυμά σας στο πεδίο. Το μικρόφωνο μένει κλειστό.",
        "Πατήστε το μικρόφωνο, μιλήστε και πατήστε Τέλος για να σταλεί ό,τι είπατε.",
        "Το μικρόφωνο μένει ανοιχτό: απλώς μιλήστε και η σειρά σας στέλνεται μετά από μια παύση. Αν μιλήσετε πάνω από μια απάντηση, τη διακόπτει. Το κουμπί του μικροφώνου το σιγάζει."]
    assert out[2] == [["Finish the recording first", "Type your message in"], ["Finish the recording first", "Press the mic, speak"], ["Finish the recording first", "The microphone stays"]]


def test_the_stage_status_line_says_what_following_means_in_both_languages():
    from call_page import STATIC
    import re
    text = (STATIC / "call-i18n.js").read_text()
    assert re.findall(r'"s\.fol\.following": "([^"]*)"', text) == ["The stage follows the voice", "Η σκηνή ακολουθεί τη φωνή"]


BOARDS = ("[[show table | Heat pump or gas boiler]]| a | b |\n|---|---|\n| 1 | 2 |[[/show]] A heat pump moves heat. It costs more to install. [[key: Install costs more]]")


@needs_node
def test_alt_b_and_the_skip_link_focus_the_chip_of_the_board_in_front_else_the_first_chip_and_the_sheet_lists_the_key(tmp_path):
    from test_call_shell import asked
    html, states = asked(tmp_path, answers=(BOARDS,), asks=["How does a heat pump work?"])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js(
        "const press = (key, o = {}, at = document.body) => at.dispatchEvent(new ShimEvent('keydown', {key, code: o.code || '', altKey: !!o.alt, bubbles: true}));"
        "await serve(1); document.body.focus();")
    focus = "[document.activeElement.className, document.activeElement.dataset.view || null]"
    page.js("press('b', {alt: true, code: 'KeyB'});").check(focus)                                    # no board in front: the first chip
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}, {name: 'key-points', answer: 1}]});"
            "fromStage({type: 'stage:shown', view: 'key-points'}); document.body.focus(); $('skipboard').click();").check(focus)   # the skip link: the chip in front
    page.js("document.body.focus(); press('b', {alt: true, code: 'KeyB'});").check(focus)
    page.check("[...document.querySelectorAll('#pKeys .krow')].map((r) => r.dataset.key + ' ' + r.querySelector('.kk').textContent.trim()).filter((x) => x.startsWith('board'))")
    page.check("[$('keyhint').textContent.includes('Alt'), $('keyhint').querySelector('[data-t=\"hint.board\"]').textContent]")
    out = page.run()
    assert out[0] == ["chip board", "heat-pump-or-gas-boiler"]
    assert out[1] == ["chip board front", "key-points"] and out[2] == out[1]
    assert out[3] == ["board Alt B"]
    assert out[4] == [True, "board"]
