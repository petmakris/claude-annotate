"""world.py: a fully invented fleet world, and the real fleet page served on top of it.

    uv run --with playwright python tools/promo/fixtures/fleet/world.py <scratch dir> --port <p>
    uv run python tools/promo/fixtures/fleet/world.py <scratch dir> --stop        # stops what the run started

It builds two machines, `laptop` and `build-box`, inside <scratch dir>/world (nothing outside it is read or
written): each has its own FLEET_HOME and a synthetic home, a stub `claude` (`agents --json`, `mcp list`, and the
headless `-p` answer that "search by meaning" uses), and a fake `ssh` on PATH that runs fleet's CLI with the other
machine's FLEET_HOME, the way fleet's own tests do (fleet/tests/fleet_testkit.py). `laptop` is the hub and serves the
page; `build-box` answers over the fake ssh. The Tools tab reads each machine's synthetic home (tools.json
`scan_home`), never the real one. Then it starts `fleet ui` on 127.0.0.1:<p>, prints the login URL and the server
PID (and writes every PID it started to <scratch dir>/world/pids.json), and exits: the server and the sleeping
stand-ins for sessions keep running until `--stop`, or until the caller kills the PIDs.

Everything shown is invented: machines, folders, members, to-dos, sessions, skills, MCP servers and hooks.
The page never shows the word fleet reserves for the user's inbox: nothing is seeded for the For you tab
except what the page renders as "you" (see ask/notify below).
"""
import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
FLEET = os.path.join(REPO, "fleet")
TOKEN = "promo-token-0123456789abcdefghij"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"  # a long-lived interpreter: uv puts a throwaway one on PATH
INBOX = "pe" + "tros"  # the word fleet.py reserves for the user's inbox; built here so this file never spells it

STUB = r'''#!/usr/bin/env python3
import json, os, re, sys
a = sys.argv[1:]
fh = os.environ.get("FLEET_HOME", "")
m = "build-box" if "build-box" in fh else "laptop"
base = %(base)r
if a[:2] == ["agents", "--json"]:
    try:
        print(open(os.path.join(base, m, "agents.json")).read())
    except OSError:
        print("[]")
    sys.exit(0)
if a[:2] == ["mcp", "list"]:
    print("Checking MCP server health...\n")
    print("shop-db: shop-db-server - Connected")
    print("docs-search: https://docs.example.invalid/mcp - Connected")
    sys.exit(0)
if "-p" in a:
    prompt = sys.stdin.read()
    if "They are looking for" in prompt:
        want = prompt.split("They are looking for:", 1)[1].split("\n", 1)[0].lower()
        hits = []
        for line in prompt.split("Sessions:", 1)[-1].splitlines():
            mm = re.match(r"\[(\d+)\] \S+ \S*: (.*)", line)
            if mm and any(w in mm.group(2).lower() for w in ("retry", "idempotency")):
                why = "it is about retrying a failed charge at checkout"
                hits.append({"n": int(mm.group(1)), "why": why})
        print(json.dumps(hits))
    elif "Question:" in prompt:
        print("It added a retry with an idempotency key to the charge call.")
    else:
        print("A described session.")
    sys.exit(0)
sys.exit(0)
'''

FAKE_SSH = """#!%(py)s
import json, os, subprocess, sys
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "-o":
        i += 2
    elif args[i] == "--":
        i += 1
        break
    else:
        break
host, cmd = args[i], " ".join(args[i + 1:])
hosts = json.load(open(os.path.join(%(base)r, "hosts.json")))
if host not in hosts:
    sys.stderr.write("ssh: could not resolve hostname %%s\\n" %% host)
    sys.exit(255)
env = dict(os.environ, FLEET_HOME=hosts[host]["fleet_home"], FLEET_SESSIONS_DIR=hosts[host]["sessions"],
           HOME=hosts[host]["home"])
for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "FLEET_JOIN_NAME", "FLEET_AS"):
    env.pop(k, None)
sys.exit(subprocess.run(["sh", "-c", cmd], env=env).returncode)
"""


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text if isinstance(text, str) else json.dumps(text, indent=1))


def skill(path, name, desc, manual=False):
    put(path, "---\nname: %s\ndescription: >\n  %s\n%s---\n# %s\n"
        % (name, desc, "disable-model-invocation: true\n" if manual else "", name))


def stop(base):
    f = os.path.join(base, "world", "pids.json")
    try:
        pids = json.load(open(f))
    except (OSError, ValueError):
        print("no pids.json under", base)
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print("stopped", pid)
        except ProcessLookupError:
            print("already gone", pid)
    os.remove(f)


def machine_home(base, m):
    """The synthetic home of a machine: user skills, hooks, MCP servers, a plugin folder with launch profiles."""
    h = os.path.join(base, m, "home")
    kit = os.path.join(h, "kit")
    hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/guard.sh"}]}],
             "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/format.sh"}]}]}
    if m == "build-box":
        hooks["Stop"] = [{"hooks": [{"type": "command", "command": "~/.claude/hooks/notify-done.sh"}]}]
    put(os.path.join(h, ".claude", "settings.json"), {"enabledPlugins": {"kit-extras@kit-market": True}, "hooks": hooks})
    put(os.path.join(h, ".claude", "hooks", "guard.sh"), "echo guard\n")
    put(os.path.join(h, ".claude", "hooks", "format.sh"), "echo formatted\n" if m == "laptop" else "echo formatted by hand\n")
    put(os.path.join(h, ".claude", "hooks", "notify-done.sh"), "echo done\n")
    put(os.path.join(kit, "user-hooks", "guard.sh"), "echo guard\n")
    put(os.path.join(kit, "user-hooks", "format.sh"), "echo formatted\n")
    put(os.path.join(kit, "user-hooks", "notify-done.sh"), "echo done\n")
    skill(os.path.join(h, ".claude", "skills", "release-notes", "SKILL.md"), "release-notes",
          "Draft release notes from the merged pull requests of a week.")
    skill(os.path.join(h, ".claude", "skills", "commit-helper", "SKILL.md"), "commit-helper",
          "Write a one-line commit message from the staged diff.")
    put(os.path.join(h, ".claude.json"), {"mcpServers": {
        "shop-db": {"command": "shop-db-server", "args": ["--readonly"]},
        "docs-search": {"type": "http", "url": "https://docs.example.invalid/mcp"}}})
    put(os.path.join(kit, ".claude-plugin", "plugin.json"), {"name": "kit"})
    skill(os.path.join(kit, "skills", "checkout-review", "SKILL.md"), "checkout-review",
          "Review a change to the checkout flow against the payment rules.")
    skill(os.path.join(kit, "skills", "commit-helper", "SKILL.md"), "commit-helper",
          "Write a one-line commit message from the staged diff.")
    skill(os.path.join(kit, "skills", "invoice-check", "SKILL.md"), "invoice-check",
          "Check an invoice export against the billing schema.")
    put(os.path.join(kit, "hooks", "hooks.json"), {"description": "Kit hook bundle.", "hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/start.sh\""}]}]}})
    put(os.path.join(kit, "output-styles", "plain.md"), "---\nname: plain\ndescription: Short, plain answers.\n---\n")
    prof = os.path.join(kit, "claude", "profiles")
    put(os.path.join(prof, "shop.args"), "# the shop app\n--plugin-dir ~/kit\n"
        "--settings ~/kit/claude/profiles/shop.json\n")
    put(os.path.join(prof, "shop.json"), {"permissions": {"deny": ["Bash(rm:*)"]}})
    put(os.path.join(prof, "billing.args"), "# the billing app\n--plugin-dir ~/kit\n"
        "--settings ~/kit/claude/profiles/billing.json\n")
    put(os.path.join(prof, "billing.json"), {"permissions": {"deny": ["mcp__docs-search"]}})
    put(os.path.join(h, ".claude", "fleet-folders", "keep"), "")
    for d in ("work/shop-app", "work/acme-billing", "notes"):
        os.makedirs(os.path.join(h, d), exist_ok=True)
    put(os.path.join(h, "work", "shop-app", ".claude-launch"), "profile shop\n")
    put(os.path.join(h, "work", "acme-billing", ".claude-launch"), "profile billing\n")
    skill(os.path.join(h, "work", "shop-app", ".claude", "skills", "cart-rules", "SKILL.md"), "cart-rules",
          "The rules for the cart: limits, coupons and rounding.")
    return h


def build(base):
    w = os.path.join(base, "world")
    shutil.rmtree(w, ignore_errors=True)
    os.makedirs(w)
    machines = ("laptop", "build-box")
    homes = {m: machine_home(w, m) for m in machines}
    fhs = {m: os.path.join(w, m, "fleet") for m in machines}
    sess = {m: os.path.join(w, m, "sessions") for m in machines}
    for m in machines:
        os.makedirs(fhs[m], mode=0o700)
        os.makedirs(sess[m])
    os.makedirs(os.path.join(w, "bin"))
    put(os.path.join(w, "bin", "claude"), STUB % {"base": w})
    put(os.path.join(w, "bin", "ssh"), FAKE_SSH % {"py": "/usr/bin/env python3", "base": w})
    for n in ("claude", "ssh"):
        os.chmod(os.path.join(w, "bin", n), 0o755)
    put(os.path.join(w, "hosts.json"), {m: {"fleet_home": fhs[m], "sessions": sess[m], "home": homes[m]} for m in machines})

    env = dict(os.environ, HOME=homes["laptop"], FLEET_HOME=fhs["laptop"], FLEET_SESSIONS_DIR=sess["laptop"],
               FLEET_CLAUDE_BIN=os.path.join(w, "bin", "claude"), FLEET_NO_RECORD="1", FLEET_DESCRIBE_PAUSE="0",
               FLEET_SHARED_TOKEN_FILE=os.path.join(w, "no-shared-token"), FLEET_USER_SETTINGS=os.path.join(w, "settings.json"),
               FLEET_BACKUP_DIR=os.path.join(w, "backups"), FLEET_NO_RECORD_INDEX="1",
               PATH=os.path.join(w, "bin") + os.pathsep + os.environ["PATH"], GIT_CONFIG_NOSYSTEM="1")
    for k in ("FLEET_JOIN_NAME", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "FLEET_AS", "PROMO_DENY_EXTRA"):
        env.pop(k, None)

    for m in machines:
        other = [o for o in machines if o != m]
        conf = {"self": m, "hub": "laptop", "screen": "none"}
        for o in other:
            conf[o] = {"ssh": o, "fleet": os.path.join(FLEET, "fleet.py"), "python": PY}
        put(os.path.join(fhs[m], "machines.json"), conf)
        put(os.path.join(fhs[m], "tools.json"), {"scan_home": homes[m], "hook_sources": [os.path.join(homes[m], "kit", "user-hooks")]})
        put(os.path.join(fhs[m], "profiles.json"), {"roots": ["~/kit"], "default_dirs": ["~/kit"],
                                                      "locked": {}, "hidden": []})
        menv = dict(env, HOME=homes[m], FLEET_HOME=fhs[m], FLEET_SESSIONS_DIR=sess[m])
        subprocess.run([sys.executable, os.path.join(FLEET, "fleet.py"), "todo", "ls", "--json"], env=menv, check=True,
                       capture_output=True)
    put(os.path.join(fhs["laptop"], "ui.json"), {"token": TOKEN, "port": 0})
    os.chmod(os.path.join(fhs["laptop"], "ui.json"), 0o600)

    pids = []
    now = time.time()

    # live stand-ins: one real sleeping process per running session, listed by the stub's `agents --json`
    members = {  # machine: [(sid, name, cwd, activity)]
        "laptop": [("a1000000-0000-4000-8000-000000000001", "builder", "/work/shop-app", "busy"),
                   ("a1000000-0000-4000-8000-000000000002", "reviewer", "/work/acme-billing", "idle")],
        "build-box": [("b2000000-0000-4000-8000-000000000001", "docs-writer", "/work/acme-billing", "busy"),
                      ("b2000000-0000-4000-8000-000000000002", "tester", "/work/shop-app", "idle")]}
    for m in machines:
        agents = []
        for sid, name, cwd, act in members[m]:
            p = subprocess.Popen(["sleep", "86400"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            pids.append(p.pid)
            agents.append({"sessionId": sid, "pid": p.pid, "name": name, "kind": "background", "state": "working",
                           "status": act, "cwd": cwd})
        put(os.path.join(w, m, "agents.json"), agents)
        con = sqlite3.connect(os.path.join(fhs[m], "fleet.db"))
        for sid, name, cwd, act in members[m]:
            con.execute("INSERT INTO members(session_id, name, host, cwd, joined_at, left_at) VALUES (?,?,?,?,?,?)",
                        (sid, name, None, cwd, now - 3600, None))
        con.commit()
        con.close()
    json.dump(pids, open(os.path.join(w, "pids.json"), "w"))

    # laptop: the to-dos (one waits on another), a thread between members, an ask and a notification for the user
    con = sqlite3.connect(os.path.join(fhs["laptop"], "fleet.db"))
    con.executemany("INSERT INTO messages(thread, kind, sender, recipient, body, in_reply_to, created_at, answered_at, delivery) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", [
        ("t0aa1", "ask", "builder", "reviewer", "Which branch has the payment schema change?", None, now - 3000, now - 2900, "confirmed"),
        ("t0aa1", "answer", "reviewer", "builder", "payment-schema, rebased this morning.", 1, now - 2900, None, "confirmed"),
        ("t0bb2", "ask", "builder", INBOX, "Retry a charge up to three times, or five?", None, now - 240, None, None),
        ("t0cc3", "notify", "reviewer", INBOX, "The billing export tests are green again.", None, now - 90, None, None)])
    con.executemany("INSERT INTO todos(title, ref, notes, created_by, state, claimed_by, created_at) VALUES (?,?,?,?,?,?,?)", [
        ("Review the payment schema", "docs/payment-schema.md", "Check the new idempotency column.", "builder", "claimed", "reviewer", now - 900),
        ("Add retry to checkout", "shop-app/src/checkout.py", "Needs the reviewed schema first.", "builder", "open", None, now - 800),
        ("Draft the invoice export docs", "acme-billing/docs/export.md", None, "reviewer", "open", None, now - 700),
        ("Fix the cart rounding bug", None, None, "builder", "done", "builder", now - 9000)])
    ids = {r[1]: r[0] for r in con.execute("SELECT id, title FROM todos")}
    con.execute("UPDATE todos SET owner='builder', after=? WHERE title='Add retry to checkout'", (str(ids["Review the payment schema"]),))
    con.execute("UPDATE todos SET owner='docs-writer@build-box' WHERE title='Draft the invoice export docs'")
    con.commit()
    con.close()

    # the history (Profiles view takes its folders from it)
    for m in machines:
        con = sqlite3.connect(os.path.join(fhs[m], "fleet.db"))
        for i, (cwd, prompt) in enumerate([("work/shop-app", "Add retry to the charge call"),
                                           ("work/acme-billing", "Check the invoice export"),
                                           ("notes", "Tidy the release notes")]):
            d = os.path.join(homes[m], cwd)
            tp = os.path.join(w, m, "t%d.jsonl" % i)
            put(tp, json.dumps({"type": "user", "cwd": d, "message": {"role": "user", "content": prompt}}) + "\n")
            con.execute("INSERT INTO conversations(session_id, cwd, transcript_path, started_at, last_seen_at, first_prompt)"
                        " VALUES (?,?,?,?,?,?)", ("h-%s-%d" % (m, i), d, tp, now - 90000 + i, now - 80000 + i, prompt))
        con.commit()
        con.close()

    # the session index on the hub (laptop): rows of both machines
    sys.path.insert(0, FLEET)
    import fleet_index_store as store  # noqa: E402
    hub = store.connect(os.path.join(fhs["laptop"], "index", "hub.db"))
    seq = {m: 0 for m in machines}

    def index(m, sid, fields, ago, event="start"):
        seq[m] += 1
        r = store.apply_batch(hub, {"machine": m, "entries": [{
            "v": 1, "machine": m, "seq": seq[m], "as": m, "sid": sid, "epoch_seen": 1, "event": event,
            "at": now - ago, "fields": fields}]}, hub="laptop", machines=set(machines), now=now - ago)
        assert r["results"][0]["outcome"] == "applied", r

    def chat(m, sid, name, cwd, prompt, ago, ended=True, description=None, last=None):
        f = {"cwd": cwd, "first_prompt": prompt, "kind": "chat", "work": False}
        if name:
            f.update(name=name, name_source="custom")
        index(m, sid, f, ago)
        if last:
            index(m, sid, {"last_prompt": last, "work": False}, ago - 1, "prompt")
        if description:
            index(m, sid, {"description": description, "work": False}, ago - 2, "describe")
        if ended:
            index(m, sid, {"end_reason": "exit", "work": False}, ago - 3, "end")

    H = 3600
    # laptop
    chat("laptop", "a1000000-0000-4000-8000-000000000001", "builder", "/work/shop-app", "Build the checkout retry", 600,
         ended=False, description="Adding a retry with an idempotency key to the shop app's checkout charge.")
    chat("laptop", "a1000000-0000-4000-8000-000000000002", "reviewer", "/work/acme-billing", "Review the payment schema", 900,
         ended=False, description="Reviewing the billing app's payment schema change.")
    chat("laptop", "c3000000-0000-4000-8000-000000000001", "Cart empty state", "/work/shop-app", "Design the empty cart screen", 5 * H,
         description="Designed the empty cart screen and its copy for the shop app.")
    chat("laptop", "c3000000-0000-4000-8000-000000000002", "Checkout retry plan", "/work/shop-app",
         "Plan how checkout should retry a timed-out charge", 26 * H,
         description="Planned the checkout retry: three attempts with an idempotency key.")
    chat("laptop", "c3000000-0000-4000-8000-000000000003", "Tax rounding", "/work/acme-billing", "Why do invoice totals differ by a cent?", 30 * H,
         description="Found the invoice tax rounding bug in the billing app.")
    chat("laptop", "c3000000-0000-4000-8000-000000000004", None, "~/notes", "Tidy my release notes for the week", 50 * H,
         description="Tidied the weekly release notes.")
    # build-box
    chat("build-box", "b2000000-0000-4000-8000-000000000001", "docs-writer", "/work/acme-billing", "Write the invoice export docs", 400,
         ended=False, description="Writing the invoice export documentation for the billing app.")
    chat("build-box", "b2000000-0000-4000-8000-000000000002", "tester", "/work/shop-app", "Run the checkout tests", 1200,
         ended=False, description="Running the shop app's checkout tests.")
    chat("build-box", "d4000000-0000-4000-8000-000000000001", "Checkout retry tests", "/work/shop-app",
         "Write tests for the retry on a failed charge", 8 * H,
         description="Wrote the tests for the checkout charge retry, including the idempotency key.")
    chat("build-box", "d4000000-0000-4000-8000-000000000002", "Invoice PDF layout", "/work/acme-billing", "Fix the invoice PDF page break", 20 * H,
         description="Fixed the page break in the invoice PDF.")
    chat("build-box", "d4000000-0000-4000-8000-000000000003", "Nightly build", "/work/shop-app", "Why did the nightly build fail?", 40 * H,
         description="Traced the nightly build failure to a stale lockfile.")
    hub.close()
    for m in machines:
        put(os.path.join(fhs[m], "index", "journal.state.json"), {"next_seq": seq[m] + 1, "acked_seq": seq[m]})
    return w, env, fhs


def serve(base, port):
    w, env, fhs = build(base)
    put(os.path.join(fhs["laptop"], "ui.json"), {"token": TOKEN, "port": port})
    os.chmod(os.path.join(fhs["laptop"], "ui.json"), 0o600)
    log = open(os.path.join(w, "ui.log"), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(FLEET, "fleet.py"), "ui", "--port", str(port), "--host", "127.0.0.1"],
                           env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pids = json.load(open(os.path.join(w, "pids.json")))
    pids.append(srv.pid)
    json.dump(pids, open(os.path.join(w, "pids.json"), "w"))
    url = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/login?t=" + TOKEN, timeout=1)
            break
        except urllib.error.HTTPError:  # the login redirects to a page that wants the cookie: it answers, so it is up
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    else:
        print("the page did not start; see", os.path.join(w, "ui.log"))
        sys.exit(1)
    print("login url: %s/login?t=%s" % (url, TOKEN))
    print("server pid: %d" % srv.pid)
    print("all pids (stand-in sessions and server): %s" % " ".join(str(p) for p in pids))
    print("stop with: uv run python %s %s --stop" % (os.path.relpath(__file__), base))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scratch")
    ap.add_argument("--port", type=int)
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args()
    base = os.path.abspath(a.scratch)
    if a.stop:
        stop(base)
    elif a.port:
        serve(base, a.port)
    else:
        ap.error("--port or --stop")
