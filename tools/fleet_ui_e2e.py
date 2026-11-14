"""End-to-end UI test of the fleet page, in Playwright's headless Chromium, against a scratch world.

Nothing here touches the real fleet store, the real env repository or the real ~/.claude: the server runs with
HOME and FLEET_HOME inside a scratch folder, a stub `claude`, and profiles kept in a scratch git repository with a
bare remote. Every check is printed as PASS or FAIL; the exit code is the number of failures.

    uv run --with playwright python tools/fleet_ui_e2e.py fleet

It needs Playwright's Chromium (`uv run --with playwright python -m playwright install chromium-headless-shell`).
It is not part of the pytest suite, which starts no browser. The scratch world and the screenshots go to a new
temp folder, printed at the end. FLEET_E2E_PORT picks the port (default 8901).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

from playwright.sync_api import sync_playwright, expect

FLEET = os.path.abspath(sys.argv[1])
OUT = tempfile.mkdtemp(prefix="fleet-e2e-")
BASE = os.path.join(OUT, "world")
HOME = os.path.join(BASE, "home")
FH = os.path.join(HOME, ".claude", "fleet")
PORT = int(os.environ.get("FLEET_E2E_PORT", "8901"))
TOKEN = "e2e-token-0123456789abcdefghij"
URL = "http://127.0.0.1:%d" % PORT
ENV_REPO = os.path.join(HOME, "projects", "env-repo")
PDIR = os.path.join(ENV_REPO, "claude", "profiles")
REMOTE = os.path.join(BASE, "remote.git")
FAILFLAG = os.path.join(BASE, "mcp-fail")
SHOTS = os.path.join(OUT, "shots")

STUB = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
open(os.path.join(%(base)r, "claude-calls.log"), "a").write(" ".join(a) + "\n")
if a[:2] == ["mcp", "list"]:
    if os.path.exists(%(flag)r):
        sys.stderr.write("cannot reach the servers\n"); sys.exit(1)
    print("Checking MCP server health...\n")
    print("github: npx -y github-server - ✓ Connected")
    print("claude.ai Mail Box: https://mail.example/mcp - ✓ Connected")
    print("notes: notes-server - ✓ Connected")
    sys.exit(0)
if a[:2] == ["agents", "--json"]:
    pid = int(open(os.path.join(%(base)r, "alive.pid")).read())  # a real sleeping process stands in for the session
    print(json.dumps([{"sessionId": "s-builder", "pid": pid, "name": "builder", "kind": "background", "state": "idle"}]))
    sys.exit(0)
if "-p" in a:
    prompt = sys.stdin.read()
    if "They are looking for" in prompt:
        print('[{"n": 1, "why": "it planned the export job"}]')
    elif "Question:" in prompt:
        print("STUB ANSWER: the session wrote an export plan.")
    else:
        print("A described session.")
    sys.exit(0)
sys.exit(0)
'''

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print("PASS  " + name, flush=True)
    except Exception as e:  # noqa: BLE001
        msg = " / ".join((str(e).strip().splitlines() or [repr(e)])[:12])[:1500]
        results.append((name, False, msg))
        print("FAIL  " + name + "\n      " + msg, flush=True)
        if os.environ.get("E2E_TRACE"):
            traceback.print_exc()


def git(cwd, *a):
    return subprocess.run(["git", "-C", cwd] + list(a), check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# ---------------------------------------------------------------- the scratch world

shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(FH, mode=0o700)
ENV = dict(os.environ, HOME=HOME, FLEET_HOME=FH, FLEET_SESSIONS_DIR=os.path.join(BASE, "sessions"),
           FLEET_CLAUDE_BIN=os.path.join(BASE, "bin", "claude"), FLEET_NO_RECORD="1",
           GIT_AUTHOR_NAME="E2E", GIT_AUTHOR_EMAIL="e2e@example.invalid", GIT_COMMITTER_NAME="E2E",
           GIT_COMMITTER_EMAIL="e2e@example.invalid", GIT_CONFIG_NOSYSTEM="1")
for k in ("FLEET_JOIN_NAME", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "FLEET_AS"):
    ENV.pop(k, None)
os.makedirs(os.path.join(BASE, "sessions"))
write(ENV["FLEET_CLAUDE_BIN"], STUB % {"base": BASE, "flag": FAILFLAG})
os.chmod(ENV["FLEET_CLAUDE_BIN"], 0o755)

write(os.path.join(PDIR, "work.args"), "# work\n--plugin-dir ~/projects/skills\n--plugin-dir ~/projects/kit\n"
      "--settings ~/projects/env-repo/claude/profiles/work.json\n")
write(os.path.join(PDIR, "work.json"), json.dumps({"permissions": {"deny": ["mcp__notes", "Bash(rm:*)"]}}, indent=2) + "\n")
write(os.path.join(PDIR, "bare.args"), "--plugin-dir ~/projects/skills\n--settings ~/projects/env-repo/claude/profiles/bare.json\n")
write(os.path.join(PDIR, "bare.json"), "{}\n")
subprocess.run(["git", "init", "-q", "-b", "main", ENV_REPO], check=True, env=ENV)
git(ENV_REPO, "add", "-A")
git(ENV_REPO, "commit", "-q", "-m", "init")
subprocess.run(["git", "init", "-q", "--bare", REMOTE], check=True, env=ENV)
git(ENV_REPO, "remote", "add", "origin", REMOTE)
git(ENV_REPO, "push", "-q", "-u", "origin", "main")

APP = os.path.join(HOME, "projects", "app")
LIB = os.path.join(HOME, "projects", "group", "lib")
CUSTOM = os.path.join(HOME, "projects", "custom")
for d in (APP, LIB, CUSTOM, os.path.join(HOME, "projects", "skills"), os.path.join(HOME, "projects", "kit")):
    os.makedirs(d, exist_ok=True)
write(os.path.join(HOME, "projects", "group", ".claude-launch"),
      "# Tools this tree gets: see ~/projects/env-repo/claude/profiles/bare.args\nprofile bare\n")
write(os.path.join(CUSTOM, ".claude-launch"), "--plugin-dir ~/projects/kit\n")
write(os.path.join(HOME, ".claude", "settings.json"), json.dumps({"enabledPlugins": {"alpha@mk": True, "beta@mk": True}}))
write(os.path.join(FH, "profiles.json"), json.dumps({
    "roots": ["~/projects/env-repo"], "default_dirs": ["~/projects/skills", "~/projects/kit"],
    "locked": {"~/projects/skills": "your skills"}, "hidden": []}))
write(os.path.join(FH, "ui.json"), json.dumps({"token": TOKEN, "port": PORT}))
os.chmod(os.path.join(FH, "ui.json"), 0o600)

# the store, made by the CLI, then seeded with a member, a thread, an ask for the user, to-dos and history
subprocess.run([sys.executable, os.path.join(FLEET, "fleet.py"), "todo", "ls", "--json"], env=ENV, check=True, capture_output=True)
con = sqlite3.connect(os.path.join(FH, "fleet.db"))
now = time.time()
con.executemany("INSERT INTO members(session_id, name, host, cwd, joined_at, left_at) VALUES (?,?,?,?,?,?)", [
    ("s-builder", "builder", None, APP, now - 600, None),
    ("s-old", "reviewer", None, LIB, now - 7200, now - 3600)])
con.executemany("INSERT INTO messages(thread, kind, sender, recipient, body, in_reply_to, created_at, answered_at, delivery) "
                "VALUES (?,?,?,?,?,?,?,?,?)", [
    ("t0aa1", "ask", "builder", "reviewer", "Which branch has the export fix?", None, now - 3000, now - 2900, "confirmed"),
    ("t0aa1", "answer", "reviewer", "builder", "feature/export, rebased this morning.", 1, now - 2900, None, "confirmed"),
    ("t0bb2", "ask", "builder", "petros", "May I delete the old export table?", None, now - 120, None, None),
    ("t0cc3", "notify", "builder", "petros", "The nightly build is green again.", None, now - 60, None, None)])
con.executemany("INSERT INTO todos(title, ref, notes, created_by, state, claimed_by, created_at) VALUES (?,?,?,?,?,?,?)", [
    ("Write the export job", "docs/export.md", "after the schema lands", "builder", "open", None, now - 500),
    ("Review the schema", None, None, "builder", "claimed", "reviewer", now - 400),
    ("Old cleanup", None, None, "builder", "done", "builder", now - 9000)])
for i, (sid, cwd, name, prompt) in enumerate([
        ("aaaa1111-0000-0000-0000-000000000001", APP, "Export plan", "Plan the billing export"),
        ("aaaa1111-0000-0000-0000-000000000002", APP, None, "Fix the flaky test"),
        ("aaaa1111-0000-0000-0000-000000000003", LIB, "Lib refactor", "Split the parser"),
        ("aaaa1111-0000-0000-0000-000000000004", CUSTOM, "Custom thing", "Try the custom launcher"),
        ("aaaa1111-0000-0000-0000-000000000005", APP, "Throwaway", "A session to delete")]):
    tp = os.path.join(BASE, "t%d.jsonl" % i)
    write(tp, json.dumps({"type": "user", "cwd": cwd, "message": {"role": "user", "content": prompt}}) + "\n")
    con.execute("INSERT INTO conversations(session_id, cwd, transcript_path, started_at, last_seen_at, manual_name, first_prompt, description) "
                "VALUES (?,?,?,?,?,?,?,?)", (sid, cwd, tp, now - 5000 + i, now - 1000 + i, name, prompt,
                                              "Planned the billing export job." if i == 0 else None))
con.commit()
con.close()

sleeper = subprocess.Popen(["sleep", "3600"])
write(os.path.join(BASE, "alive.pid"), str(sleeper.pid))
server = subprocess.Popen([sys.executable, os.path.join(FLEET, "fleet.py"), "ui", "--port", str(PORT), "--host", "127.0.0.1"],
                          env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(50):
    try:
        urllib.request.urlopen(URL + "/login?t=" + TOKEN, timeout=1)
        break
    except Exception:  # noqa: BLE001
        time.sleep(0.2)


def db():
    c = sqlite3.connect(os.path.join(FH, "fleet.db"))
    c.row_factory = sqlite3.Row
    return c


def launch_file(d):
    p = os.path.join(d, ".claude-launch")
    return open(p).read() if os.path.exists(p) else None


# ---------------------------------------------------------------- the browser

os.makedirs(SHOTS, exist_ok=True)
console_errors = []
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.set_default_timeout(8000)
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        dialogs = []
        confirm_answer = {"accept": False}  # what the next confirm() is answered (never page.evaluate inside a dialog)

        def on_dialog(d):
            dialogs.append(d.message)
            d.accept() if confirm_answer["accept"] else d.dismiss()
        page.on("dialog", on_dialog)
        page.goto(URL + "/login?t=" + TOKEN)

        def view(name):
            page.click('#tabs button[data-view="%s"]' % name)
            expect(page.locator("#view-" + name)).to_be_visible()

        # ---- shell
        def shell():
            expect(page.locator("#tabs button")).to_have_count(4)
            expect(page.locator("#stamp")).to_contain_text("Live")
            expect(page.locator('#tabs button[data-view="foryou"] .badge')).to_have_text("2")
            assert page.title() == "(2) Fleet", page.title()
        check("App bar: four tabs, live status, the For you badge counts the open ask", shell)

        # ---- Fleet view
        view("fleet")

        def members():
            rows = page.locator(".ml-row")
            expect(rows).to_have_count(2)
            expect(rows.nth(0)).to_contain_text("builder")
            expect(rows.nth(0).locator(".pill")).to_have_text("alive")
            expect(rows.nth(1).locator(".pill")).to_have_text("left")
            expect(rows.nth(0).locator(".ml-folder")).to_have_text("~/projects/app")
            expect(page.locator("#n-members")).to_contain_text("1 alive")
        check("Members: alive first, status pills, home folder shown as ~", members)

        def compose():
            row = page.locator(".ml-row").nth(0)
            row.get_by_role("button", name="Tell").click()
            box = page.locator(".compose textarea")
            expect(box).to_be_focused()
            box.fill("draft that must survive a refresh")
            page.wait_for_timeout(6000)  # one poll passes
            expect(page.locator(".compose textarea")).to_have_value("draft that must survive a refresh")
            page.get_by_role("button", name="Cancel").click()
            expect(page.locator(".compose")).to_have_count(0)
        check("Members: Tell opens a box under the row, a poll keeps the draft, Cancel closes it", compose)

        def stop_confirm():
            b = page.locator(".ml-row").nth(0).get_by_role("button", name="Stop")
            b.click()
            expect(page.locator(".ml-row").nth(0).get_by_role("button", name="Confirm stop")).to_be_visible()
            page.wait_for_timeout(4300)
            expect(page.locator(".ml-row").nth(0).get_by_role("button", name="Stop")).to_be_visible()
        check("Members: Stop asks for a second press and resets after 4 s without acting", stop_confirm)

        def todos():
            expect(page.locator(".td-row.open")).to_have_count(1)
            expect(page.locator(".td-row.claimed")).to_contain_text("reviewer")
            page.fill("#todo-title", "E2E to-do from the page")
            page.fill("#todo-ref", "notes/e2e.md")
            page.click("#todo-form button[type=submit]")
            expect(page.locator("#todo-msg")).to_contain_text("Added to-do")
            expect(page.locator(".td-row.open")).to_have_count(2)
            r = db().execute("SELECT * FROM todos WHERE title='E2E to-do from the page'").fetchone()
            assert r and r["created_by"] == "petros" and r["ref"] == "notes/e2e.md", dict(r) if r else None
            expect(page.locator("#todo-title")).to_have_value("")
        check("Backlog: grouped by state; Add to-do stores it as the user and lists it", todos)

        def toast_fades():
            expect(page.locator("#todo-msg")).to_be_hidden(timeout=8000)
        check("Notices: a success notice fades by itself", toast_fades)

        def tell_send():
            row = page.locator(".ml-row").nth(0)
            row.get_by_role("button", name="Tell").click()
            page.locator(".compose textarea").fill("E2E: please run the tests")
            page.get_by_role("button", name="Send instruction").click()
            expect(page.locator("#m-msg")).to_contain_text("Not delivered to builder", timeout=20000)
            expect(page.locator("#m-msg")).to_have_class("h-msg toast bad on")
            r = db().execute("SELECT recipient, body, delivery FROM messages WHERE body LIKE 'E2E: please%'").fetchone()
            assert r and r["recipient"] == "builder", dict(r) if r else None
            print("      (delivery to a member with no socket: %s; page said: %s)" % (r["delivery"], page.inner_text("#m-msg")[:160]))
        check("Members: Send instruction stores the tell as the user and the page reports the outcome", tell_send)

        def respawn():
            row = page.locator(".ml-row.left")
            row.get_by_role("button", name="Respawn").click()
            row.get_by_role("button", name="Confirm respawn").click()
            expect(page.locator("#m-msg")).to_contain_text("reviewer", timeout=40000)
            calls = open(os.path.join(BASE, "claude-calls.log")).read()
            assert "respawn" in calls or "--resume" in calls, calls[-300:]
            print("      (page said: %s)" % page.inner_text("#m-msg")[:160])
        check("Members: Respawn needs a second press, runs claude, and reports what happened", respawn)

        def backlog_notes():
            row = page.locator(".td-row", has_text="Write the export job")
            notes = row.locator(".td-notes")
            expect(notes.locator("summary")).to_have_text("Notes")
            assert not notes.evaluate("d => d.open"), "notes start closed"
            notes.locator("summary").click()
            assert notes.evaluate("d => d.open"), "a click opens the notes"
            expect(page.locator("#threads")).to_have_count(0)
        check("Backlog: a to-do shows its title, its notes behind a Notes toggle; no threads panel", backlog_notes)

        # ---- For you
        view("foryou")

        def dismiss():
            item = page.locator(".fy-item", has_text="nightly build")
            item.get_by_role("button", name="Dismiss").click()
            expect(page.locator("#fy-msg")).to_contain_text("Dismissed")
            expect(page.locator(".fy-item:not(.done)", has_text="nightly build")).to_have_count(0)
            r = db().execute("SELECT answered_at FROM messages WHERE thread='t0cc3'").fetchone()
            assert r["answered_at"], "notice not cleared"
        check("For you: Dismiss clears a notice", dismiss)

        def foryou():
            item = page.locator(".fy-item", has_text="May I delete")
            expect(item).to_contain_text("May I delete the old export table?")
            item.locator("textarea").fill("Yes, after the backup.")
            item.get_by_role("button", name="Answer").click()
            expect(page.locator("#fy-msg")).to_contain_text("Answered")
            expect(page.locator(".empty-box")).to_contain_text("Nothing is waiting")
            r = db().execute("SELECT answered_at FROM messages WHERE thread='t0bb2' AND kind='ask'").fetchone()
            assert r["answered_at"], "ask not marked answered"
            reply = db().execute("SELECT body FROM messages WHERE thread='t0bb2' AND kind='answer'").fetchone()
            assert reply and reply["body"] == "Yes, after the backup.", reply
            expect(page.locator('#tabs button[data-view="foryou"] .badge')).to_have_count(0)
        check("For you: answering stores the reply, clears the item and the badge", foryou)

        # ---- History
        view("history")

        def htree():
            expect(page.locator(".hs-row")).to_have_count(5)
            page.locator("#h-tree .t-row", has_text="app").first.click()
            expect(page.locator(".hs-row")).to_have_count(3)
            expect(page.locator("#h-crumb")).to_contain_text("projects/app")
            page.locator("#h-tree .t-all").click()
            expect(page.locator(".hs-row")).to_have_count(5)
        check("History: the tree filters sessions by folder and All sessions resets", htree)

        def hfilter():
            page.fill("#h-q", "lib refactor")
            expect(page.locator(".hs-row")).to_have_count(1)
            page.fill("#h-q", "")
            expect(page.locator(".hs-row")).to_have_count(5)
        check("History: the filter box narrows the list as you type", hfilter)

        def hrename():
            row = page.locator(".hs-row", has_text="Fix the flaky test")
            row.get_by_role("button", name="Rename").click()
            inp = page.get_by_label("New name")
            expect(inp).to_be_focused()
            inp.fill("Flaky test hunt")
            inp.press("Enter")
            expect(page.locator(".hs-row", has_text="Flaky test hunt")).to_have_count(1)
            r = db().execute("SELECT manual_name FROM conversations WHERE session_id LIKE '%0002'").fetchone()
            assert r["manual_name"] == "Flaky test hunt", r["manual_name"]
        check("History: Rename edits in place, Enter saves it to the store", hrename)

        def hask():
            page.locator(".hs-row", has_text="Export plan").locator(".link").click()
            expect(page.locator(".detail")).to_contain_text("Planned the billing export job.")
            page.locator(".detail input").fill("What did it plan?")
            page.locator(".detail").get_by_role("button", name="Ask").click()
            expect(page.locator(".h-answer")).to_contain_text("STUB ANSWER", timeout=20000)
        check("History: a row opens its details and Ask answers from the transcript", hask)

        def hsearch():
            page.fill("#h-q", "the export")
            page.click("#h-meaning")
            expect(page.locator(".h-found")).to_contain_text("Matches by meaning", timeout=20000)
            expect(page.locator(".hs-row")).to_have_count(1)
            expect(page.locator("#h-clear")).to_be_visible()
            page.click("#h-clear")
            expect(page.locator(".hs-row")).to_have_count(5)
        check("History: Search by meaning lists the hits with why, Clear returns to all", hsearch)

        def hdelete():
            row = page.locator(".hs-row", has_text="Throwaway")
            row.get_by_role("button", name="Delete").click()
            row.get_by_role("button", name="Confirm delete").click()
            expect(page.locator(".hs-row")).to_have_count(4)
            assert db().execute("SELECT COUNT(*) FROM conversations WHERE manual_name='Throwaway'").fetchone()[0] == 0
            assert os.path.exists(os.path.join(BASE, "t4.jsonl")), "the transcript must stay"
        check("History: Delete needs a second press, removes the row, keeps the transcript", hdelete)

        # ---- Profiles
        view("profiles")
        page.wait_for_selector(".tl-row")
        tree = lambda name: page.locator("#p-tree .t-row", has_text=name).first  # noqa: E731

        def ptree():
            expect(tree("group").locator(".chip")).to_have_text("bare")
            expect(tree("lib").locator(".chip.ghost")).to_have_text("bare")
            expect(tree("app").locator(".chip")).to_have_count(0)
            expect(page.locator(".pl-row")).to_have_count(2)
        check("Profiles: tree chips show set-here (solid) and inherited (dashed); every profile listed", ptree)

        def pset_keyboard():
            tree("app").click()
            expect(page.locator(".src-line")).to_contain_text("launcher's defaults")
            btn = page.locator(".src-set .dd-btn")
            btn.focus()
            btn.press("ArrowDown")
            expect(page.locator(".src-set .dd-menu")).to_be_visible()
            page.keyboard.press("ArrowDown")  # inherit -> bare
            page.keyboard.press("ArrowDown")  # bare -> work
            page.keyboard.press("Enter")
            expect(page.locator("#p-msg")).to_contain_text("now uses work")
            assert launch_file(APP) == "# Tools this tree gets: see ~/projects/env-repo/claude/profiles/work.args\nprofile work\n", launch_file(APP)
            expect(page.locator(".src-line")).to_contain_text("set in this folder")
            expect(tree("app").locator(".chip")).to_have_text("work")
        check("Profiles: the custom select works by keyboard and writes the standard .claude-launch", pset_keyboard)

        def pdd_close():
            page.locator(".src-set .dd-btn").click()
            expect(page.locator(".src-set .dd-menu")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator(".src-set .dd-menu")).to_be_hidden()
            expect(page.locator(".src-set .dd-btn")).to_be_focused()
            page.locator(".src-set .dd-btn").click()
            page.mouse.click(5, 500)
            expect(page.locator(".src-set .dd-menu")).to_be_hidden()
        check("Profiles: the select closes on Escape (focus returns) and on a click outside", pdd_close)

        def pinherit():
            page.locator(".src-set .dd-btn").click()
            page.locator(".src-set .dd-menu li", has_text="inherit").click()
            expect(page.locator("#p-msg")).to_contain_text("now inherits")
            assert launch_file(APP) is None
        check("Profiles: choosing inherit by mouse removes the folder's file", pinherit)

        def pcustom():
            tree("custom").click()
            expect(page.locator(".src-line")).to_contain_text("hand-written")
            expect(page.locator(".p-pre")).to_contain_text("--plugin-dir ~/projects/kit")
            expect(page.locator(".src-set")).to_have_count(0)
        check("Profiles: a hand-written file is shown and cannot be changed from the page", pcustom)

        def plocked():
            page.locator("#p-tree .t-all").click()
            page.locator(".pl-row", has_text="work").locator("button").click()
            sw = page.get_by_role("switch", name="your skills")
            expect(sw).to_be_disabled()
            expect(sw).to_have_attribute("aria-checked", "true")
        check("Profiles: a locked plugin folder is on and cannot be switched", plocked)

        def pdirty_revert():
            page.get_by_role("switch", name="github").click()
            page.get_by_role("switch", name="beta").click()
            expect(page.locator(".savebar")).to_contain_text("2 unsaved changes to work")
            expect(page.locator(".tl-row.changed")).to_have_count(2)
            page.get_by_role("button", name="Revert").click()
            expect(page.locator(".savebar")).to_contain_text("No unsaved changes")
            expect(page.get_by_role("button", name="Save and push")).to_be_disabled()
        check("Profiles: switches count unsaved changes, mark changed rows, Revert clears them", pdirty_revert)

        def pguard():
            page.get_by_role("switch", name="github").click()
            confirm_answer["accept"] = False
            tree("lib").click()
            assert dialogs and "Discard unsaved changes to work" in dialogs[-1], dialogs
            expect(page.locator(".savebar")).to_contain_text("1 unsaved change")
            confirm_answer["accept"] = True
            tree("lib").click()
            expect(page.locator(".src-line")).to_contain_text("inherited from")
            page.locator("#p-tree .t-all").click()
            page.locator(".pl-row", has_text="work").locator("button").click()
            expect(page.locator(".savebar")).to_contain_text("No unsaved changes")
        check("Profiles: leaving unsaved switches asks; Cancel stays, OK discards", pguard)

        def psave():
            page.get_by_role("switch", name="github").click()   # mcp: deny it
            page.get_by_role("switch", name="notes").click()    # mcp: allow it again
            page.get_by_role("switch", name="kit").click()      # plugin dir: drop it
            page.get_by_role("switch", name="alpha").click()    # marketplace plugin: disable it
            page.get_by_role("button", name="Save and push").click()
            expect(page.locator("#p-msg")).to_contain_text("Saved and pushed", timeout=20000)
            msg = git(ENV_REPO, "log", "-1", "--format=%s")
            assert msg == "profiles: work — kit off, github off, notes on, alpha off", msg
            assert git(REMOTE, "log", "-1", "--format=%s", "main") == msg
            assert git(ENV_REPO, "show", "--name-only", "--format=", "HEAD").split() == ["claude/profiles/work.args", "claude/profiles/work.json"]
            js = json.load(open(os.path.join(PDIR, "work.json")))
            assert js["permissions"]["deny"] == ["Bash(rm:*)", "mcp__github"], js
            assert js["enabledPlugins"] == {"alpha@mk": False}, js
            assert "--plugin-dir ~/projects/kit" not in open(os.path.join(PDIR, "work.args")).read()
            expect(page.locator(".savebar")).to_contain_text("No unsaved changes")
            expect(page.get_by_role("switch", name="github")).to_have_attribute("aria-checked", "false")
        check("Profiles: Save and push rewrites both files, commits only them and pushes", psave)

        def pmcp_down():
            open(FAILFLAG, "w").close()
            page.get_by_role("button", name="Refresh tools").click()
            expect(page.locator("#p-main .h-msg.bad")).to_contain_text("MCP servers unavailable")
            expect(page.get_by_role("switch", name="github")).to_have_count(0)
            page.get_by_role("switch", name="beta").click()
            page.get_by_role("button", name="Save and push").click()
            expect(page.locator("#p-msg")).to_contain_text("MCP server list unavailable")
            os.unlink(FAILFLAG)
            page.get_by_role("button", name="Revert").click()
            page.get_by_role("button", name="Refresh tools").click()
            expect(page.get_by_role("switch", name="github")).to_have_count(1)
            expect(page.locator("#p-msg")).to_be_hidden()
        check("Profiles: with the MCP list down the page says so and a save is refused", pmcp_down)

        def keyboard():
            page.locator('#tabs button[data-view="fleet"]').focus()
            page.keyboard.press("Tab")
            expect(page.locator('#tabs button[data-view="foryou"]')).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.locator("#view-foryou")).to_be_visible()
            view("profiles")
            row = page.locator("#p-tree .t-row", has_text="lib").first
            row.focus()
            page.keyboard.press("Enter")
            expect(page.locator(".src-line")).to_contain_text("inherited from")
            sw = page.get_by_role("switch", name="beta")
            sw.focus()
            page.keyboard.press("Space")
            expect(page.get_by_role("switch", name="beta")).to_have_attribute("aria-checked", "false")
            expect(page.get_by_role("switch", name="beta")).to_be_focused()
            page.get_by_role("button", name="Revert").click()
        check("Keyboard: Tab and Enter switch views, pick a folder, and Space flips a switch (focus kept)", keyboard)

        def contrast():
            def lum(c):
                import re as _re
                r, g, b = [int(x) / 255 for x in _re.findall(r"[\d.]+", c)[:3]]
                f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
                return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
            def ratio(a, b):
                la, lb = sorted((lum(a), lum(b)), reverse=True)
                return (la + 0.05) / (lb + 0.05)
            bad = []
            for theme in ("light", "dark"):
                page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                cols = page.evaluate("""() => { const p = document.createElement('p'); document.querySelector('.card').append(p);
                  const get = v => { p.style.color = 'var(' + v + ')'; return getComputedStyle(p).color; };
                  const out = { text: get('--text'), dim: get('--dim'), accent: get('--accent'), card: getComputedStyle(document.querySelector('.card')).backgroundColor };
                  p.remove(); return out; }""")
                for name, need in (("text", 7), ("dim", 4.5), ("accent", 3)):
                    r = ratio(cols[name], cols["card"])
                    if r < need:
                        bad.append("%s %s %.2f < %s" % (theme, name, r, need))
            page.evaluate("document.documentElement.dataset.theme = 'light'")
            assert not bad, bad
        check("Contrast on cards, both themes: text 7:1, dim 4.5:1, accent 3:1", contrast)

        def theme():
            page.click("#theme")
            assert page.evaluate("document.documentElement.dataset.theme") in ("dark", "light")
            bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            page.screenshot(path=os.path.join(SHOTS, "profiles-theme.png"))
            page.click("#theme")
            assert page.evaluate("getComputedStyle(document.body).backgroundColor") != bg
        check("Theme: the button switches theme and the page repaints", theme)

        def phone():
            page.set_viewport_size({"width": 390, "height": 844})
            wide = []
            for v in ("fleet", "foryou", "history", "profiles"):
                view(v)
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(SHOTS, "phone-%s.png" % v), full_page=True)
                over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if over > 0:
                    wide.append("%s +%dpx" % (v, over))
            page.set_viewport_size({"width": 1400, "height": 1000})
            assert not wide, "horizontal scroll at 390 px: " + ", ".join(wide)
        check("Phone width (390 px): no view scrolls sideways", phone)

        for v in ("fleet", "foryou", "history", "profiles"):
            view(v)
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(SHOTS, "desktop-%s.png" % v), full_page=True)

        def no_errors():
            real = [e for e in console_errors if "favicon" not in e and "status of 4" not in e and "status of 503" not in e]  # 4xx and the 503 are the refusals the checks provoke
            assert not real, real[:3]
        check("No script errors in the console across the whole run", no_errors)
        browser.close()
finally:
    sleeper.terminate()
    server.terminate()
    out = server.communicate(timeout=5)[0]
    if out:
        print("server said:", out.decode()[-1500:])

failed = [r for r in results if not r[1]]
print("\n%d checks, %d passed, %d failed; screenshots in %s" % (len(results), len(results) - len(failed), len(failed), SHOTS))
sys.exit(len(failed))
