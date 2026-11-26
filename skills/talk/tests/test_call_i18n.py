"""The call page's words in English and Greek (call-i18n.js): both tables hold the same keys, every key a file asks for is in them,
no routed file writes its words where they are shown, and the page's language follows the "Speech language" choice."""
import re
from pathlib import Path

from call_page import CallPage, needs_node, served

STATIC = Path(__file__).resolve().parents[1] / "static"
I18N = (STATIC / "call-i18n.js").read_text()
HTML = (STATIC / "call.html").read_text()
# The files whose words go through t() (tr() where a function keeps a local named t).
ROUTED = ["call-input.js", "call-return.js", "call-calls.js", "call-live.js", "call-wait.js", "call-shell.js", "call-stage.js", "call-player.js"]


def table(lang):
    body = re.search(r"\n  %s: \{\n(.*?)\n  \},?\n" % lang, I18N, re.S).group(1)
    return dict(re.findall(r'"([\w.]+)": "((?:[^"\\]|\\.)*)"', body))


def used_keys():
    keys = set()
    for name in ROUTED:
        text = (STATIC / name).read_text()
        keys |= set(re.findall(r'\btr?\("([\w.]+)"', text))
        for m in re.finditer(r'\btr?\(([^(),]*?\?[^(),]*?)[,)]', text):          # t(cond ? "a" : "b")
            keys |= set(re.findall(r'"([a-z][\w.]*\.[\w.]+)"', m.group(1)))
        keys |= {k + suffix for k in re.findall(r'\b(?:tn|trn)\("([\w.]+)"', text) for suffix in (".one", ".other")}
    keys |= set(re.findall(r'data-t(?:-\w+)?="([\w.]+)"', HTML))
    return keys


def test_both_tables_hold_the_same_keys_and_the_same_placeholders():
    en, el = table("en"), table("el")
    assert len(en) > 200
    assert sorted(set(en) ^ set(el)) == []
    for key in en:
        assert sorted(re.findall(r"\{(\w+)\}", en[key])) == sorted(re.findall(r"\{(\w+)\}", el[key])), key
    assert [k for k, v in el.items() if not v.strip()] == []


def test_every_key_the_page_asks_for_is_in_the_table_and_the_html_names_only_known_keys():
    en = table("en")
    assert sorted(k for k in used_keys() if k not in en) == []
    assert sorted(set(re.findall(r'data-t(?:-\w+)?="([\w.]+)"', HTML)) - set(en)) == []


def test_the_keys_the_table_builds_from_data_exist():
    en = table("en")
    for key in ("g.listen", "g.move", "g.talk", "k.play", "k.sentence", "k.speed", "k.message", "k.player", "k.voice", "k.keys", "k.close",
                "k.send", "k.newline", "k.talk", "mode.type", "mode.talk", "mode.live", "barge.talk", "barge.keyword", "lang.auto"):
        assert key in en, key


ALLOWED = {  # literals in the routed files that are not words of the page: keys on the keyboard, protocol, class names, a name
    "Azure", "Content-Type", "Space", "Alt", "Esc", "Enter", "Shift", "Tab", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "English",
    "ib kclose", "BroadcastChannel", "btn callsall", "btn callsnext", "Claude", "AbortError", "NotAllowedError", "NotSupportedError", "chip board", "ib nowcopy", "Escape", "Talk · ", "Add to your question",
}


def literals(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"const LOCAL_COMMANDS = \{.*?\};", "", text, flags=re.S)          # the words a command is matched by, not shown
    for line in text.split("\n"):
        code = re.sub(r"(^|\s)//.*$", "", line)
        for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`', code):
            yield next(g for g in m.groups() if g is not None)


def test_no_routed_file_writes_its_words_where_they_are_shown():
    wordy = re.compile(r"(^|\s)[A-Za-z]{2,}\s+[A-Za-z]{2,}|^[A-Z][a-z]{2,}")
    for name in ROUTED:
        bare = [lit for lit in literals((STATIC / name).read_text()) if re.search(r"[A-Za-z]{3,}", lit) and wordy.search(lit) and lit not in ALLOWED]
        assert bare == [], f"{name} has words that bypass t(): {bare}"


def test_the_html_carries_a_key_for_every_word_it_shows():
    body = re.sub(r"<script.*?</script>|<!--.*?-->|<style.*?</style>|<svg.*?</svg>", "", HTML, flags=re.S)
    missing = []
    for m in re.finditer(r"<(\w+)([^>]*)>([^<]+)</\1>", body):
        tag, attrs, text = m.groups()
        if re.search(r"[A-Za-z]{3,}", text) and "data-t=" not in attrs and tag not in ("title", "kbd", "b") or (tag == "b" and "data-t=" not in attrs and re.search(r"[A-Za-z]{3,}", text)):
            if not attrs.strip().startswith("class=\"spin\"") and text.strip() not in ("Talk", "Nothing has been said yet."):   # the empty line is call-shell.js's (routed with that file)
                missing.append(text.strip())
    # the page's <title> is the brand until the call names it; id="endlbl", the segments and the keys all name keys
    assert missing == [], missing
    for attr, key in (("aria-label", "data-t-aria"), ("data-tip", "data-t-tip"), ("placeholder", "data-t-ph")):
        for m in re.finditer(r"<\w+([^>]*)>", body):
            attrs = m.group(1)
            if re.search(rf'\b{attr}="[A-Za-z][^"]*"', attrs) and "data-speedchip" not in attrs:   # the speed chip says its speed in paintSettings
                assert key + "=" in attrs, f"{attr} without {key}: {attrs.strip()[:80]}"


@needs_node
def test_the_language_choice_sets_html_lang_and_the_words_and_detect_follows_the_latest_answer(tmp_path):
    html, states = served(tmp_path, ["An answer in English."])
    words = "[document.documentElement.lang, uiLang, $('skipmsg').textContent, $('tlsearch').placeholder, $('statestrip').hidden ? '' : $('sstext').textContent]"
    page = CallPage(html, states, start=1).check(words)
    page.js("document.querySelector('#lang [data-lang=el]').click(); await settle();").check(words)
    page.js("document.querySelector('#lang [data-lang=en]').click(); await settle();").check(words)
    # Detect: the latest answer's language decides
    page.js("document.querySelector('#lang [data-lang=auto]').click(); await settle();").check("[document.documentElement.lang, uiLang]")
    page.js("STATES[1].entries.find((e) => e.who === 'claude').text = 'Μια απάντηση στα ελληνικά.'; STATES[1].v = 'gr'; await serve(1);").check("[document.documentElement.lang, uiLang, $('sstext').textContent]")
    out = page.run()
    assert out[0] == ["en", "en", "Skip to the message", "Search answers", "Waiting for you"]
    assert out[1] == ["el", "el", "Μετάβαση στο μήνυμα", "Αναζήτηση απαντήσεων", "Σας περιμένει"]
    assert out[2] == out[0]
    assert out[3] == ["en", "en"]
    assert out[4][:2] == ["el", "el"]


@needs_node
def test_a_stored_greek_choice_opens_the_page_in_greek_and_a_launch_language_wins(tmp_path):
    html, states = served(tmp_path, [])
    state = "[document.documentElement.lang, $('keyhint').textContent.includes('πρόταση'), document.querySelector('#pKeys .khead h3').textContent, document.querySelector('#lang [data-lang=auto]').textContent]"
    assert CallPage(html, states, stored={"language": "el"}).check(state).run() == [["el", True, "Συντομεύσεις πληκτρολογίου", "Ανίχνευση"]]
    assert CallPage(html, states).check(state).run() == [["en", False, "Keyboard shortcuts", "Detect"]]


def test_a_routed_file_never_shadows_the_function_it_asks_for_its_words():
    """A local named t made t("c.here") throw inside a function. Per top-level statement: one that asks t() declares no local t, and no file declares its own tr or trn (call-wait.js, call-shell.js, call-stage.js and call-player.js ask tr())."""
    local = re.compile(r"\b(?:const|let|var)\s+t\b|[^\w.]t\s*=>|\(t\s*[,)][^=;{]*?\)\s*=>|function\s*\w*\s*\([^)]*\bt\b[^)]*\)|\{\s*t\s*[,}]|,\s*t\s*\]")
    for name in ROUTED:
        text = re.sub(r"//.*$", "", (STATIC / name).read_text(), flags=re.M)
        assert not re.search(r"\b(?:const|let|var)\s+(?:tr|trn)\b|\b(?:tr|trn)\s*=>", text), name
        chunks = re.split(r"\n(?=[^\s}/])", text)
        for chunk in chunks:
            if re.search(r'(?<![\w.])t\("', chunk):
                assert [m.group(0) for m in local.finditer(chunk)] == [], f"{name}: {chunk[:60]!r} asks t() and declares a local t"
