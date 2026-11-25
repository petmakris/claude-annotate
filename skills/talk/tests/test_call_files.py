"""The call page is one program in several scripts (CLAUDE.md): every file is loaded, in the order the core names, nothing is
declared twice, and the slots the feature batches build into exist in the markup."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "call.html").read_text()
SCRIPTS = re.findall(r'<script src="/static/(call[\w-]*\.js)"></script>', HTML)
SHEETS = re.findall(r'<link rel="stylesheet" href="/static/(call[\w-]*\.css)">', HTML)

SLOTS = ["statestrip", "welcome", "nowcard", "nowhead", "nowstate", "nownum", "nowclock", "waitcard", "nowbody", "nowq", "nowtext",
         "nowchips", "nowtransport", "nowfollow", "queuerow", "earlier", "tlhead", "tlcount", "tlsearch", "tlexpand", "tllist",
         "searchbtn", "sendnote", "modebar", "modesw", "yourturn", "keyhint", "pKeys", "nextwait", "announcer", "favicon"]


def test_every_script_and_sheet_of_the_page_is_loaded_and_the_core_comes_first():
    assert SCRIPTS[0] == "call.js" and SCRIPTS[-1] == "call-boot.js"
    assert sorted(SCRIPTS) == sorted(p.name for p in STATIC.glob("call*.js"))
    assert SHEETS[0] == "call.css" and sorted(SHEETS) == sorted(p.name for p in STATIC.glob("call*.css"))


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
    owners = {"paintNowCard": "call-shell.js", "paintEarlier": "call-shell.js", "shellOnView": "call-shell.js",
              "paintWait": "call-wait.js", "waitOnView": "call-wait.js", "turnSent": "call-wait.js", "waitActive": "call-wait.js",
              "callsOnView": "call-calls.js", "paintCallsButton": "call-calls.js",
              "paintInputMode": "call-input.js", "paintMic": "call-input.js",
              "returnOnView": "call-return.js", "paintWelcome": "call-return.js", "paintStateStrip": "call-return.js",
              "paintAnnounce": "call-return.js", "announce": "call-return.js", "returnMarkEarlier": "call-return.js",
              "popChanged": "call-input.js", "setSpeed": "call-input.js"}
    for fn, file in owners.items():
        assert re.search(rf"^function {fn}\(", (STATIC / file).read_text(), flags=re.M), f"{fn} is not in {file}"
