"""The call page is one program in several scripts (CLAUDE.md): every file is loaded, in the order the core names, nothing is
declared twice, and the slots the feature batches build into exist in the markup."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "call.html").read_text()
SCRIPTS = re.findall(r'<script src="/static/(call[\w-]*\.js)"></script>', HTML)
SHEETS = re.findall(r'<link rel="stylesheet" href="/static/(call[\w-]*\.css)">', HTML)

SLOTS = ["turns", "thinking", "empty", "note", "player", "playpause", "seek", "time", "pill", "text", "sendtext", "talk", "send",
         "cancel", "wave", "jump", "stopcard", "gear", "pGear", "pKeys", "pCalls", "keysrow", "livemode", "barge", "endpause",
         "nextwait", "announcer", "favicon", "toast", "audio", "gearbody", "boardtext"]


def test_every_script_and_sheet_of_the_page_is_loaded_and_the_core_comes_first():
    assert SCRIPTS[0] == "call.js" and SCRIPTS[-1] == "call-boot.js"
    assert sorted(SCRIPTS) == sorted(p.name for p in STATIC.glob("call*.js"))
    assert SHEETS == ["call.css", "call-panel.css"]
    assert sorted(SHEETS) == sorted(p.name for p in STATIC.glob("call*.css"))


def test_no_function_or_top_level_name_is_declared_in_two_files():
    seen: dict[str, str] = {}
    for name in SCRIPTS:
        text = (STATIC / name).read_text()
        for m in re.finditer(r"^(?:async )?function (\w+)|^(?:const|let|var) (\w+)", text, flags=re.M):
            ident = m.group(1) or m.group(2)
            assert ident not in seen or seen[ident] == name, f"{ident} is declared in {seen[ident]} and in {name}"
            seen[ident] = name


def test_the_slots_the_batches_build_into_are_in_the_markup():
    missing = [s for s in SLOTS if not re.search(rf'\bid="{s}"', HTML)]
    assert missing == []


def test_the_hooks_each_file_owns_are_declared_where_the_core_calls_them():
    owners = {"paintAll": "call.js", "paintPill": "call.js",
              "paintConvo": "call-shell.js", "shellOnView": "call-shell.js",
              "paintWait": "call-wait.js", "waitOnView": "call-wait.js", "turnSent": "call-wait.js", "waitActive": "call-wait.js",
              "paintNote": "call-wait.js", "skipQueued": "call-wait.js",
              "callsOnView": "call-calls.js", "paintCallsButton": "call-calls.js",
              "paintAnnounce": "call-announce.js", "announce": "call-announce.js", "announceOnView": "call-announce.js",
              "paintSettings": "call-input.js", "paintMic": "call-input.js", "popChanged": "call-input.js", "setSpeed": "call-input.js"}
    for fn, file in owners.items():
        assert re.search(rf"^function {fn}\(", (STATIC / file).read_text(), flags=re.M), f"{fn} is not in {file}"


def test_the_markup_is_balanced_and_every_layer_is_inside_the_app():
    from html.parser import HTMLParser

    class Walk(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack, self.inside, self.problems = [], {}, []

        def handle_starttag(self, tag, attrs):
            if tag in ("div", "aside", "section", "header", "nav"):
                a = dict(attrs); self.stack.append((tag, a.get("id") or a.get("class") or ""))
            for k, v in attrs:
                if k == "id":
                    self.inside[v] = any(c == "app" for _, c in self.stack)

        def handle_endtag(self, tag):
            if tag in ("div", "aside", "section", "header", "nav"):
                if not self.stack or self.stack[-1][0] != tag:
                    self.problems.append(f"</{tag}> closes {self.stack[-1] if self.stack else None}")
                else:
                    self.stack.pop()
    w = Walk(); w.feed(HTML)
    assert w.problems == [] and w.stack == []
    for layer in ("pGear", "pCalls", "pKeys", "announcer", "audio", "toast", "gearbody"):
        assert w.inside[layer], layer
