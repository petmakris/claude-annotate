"""Claude Voice's parsers against what phase 1 writes (contract section 12.4).

Production's Claude Voice reads the registry files (`readRecord`, `Registry.all`, `sessionRows` in lomem's
`apps/claudevoice/host/src/sessions.ts`), `@claude session tail --json` (`tailOf`) and take's last line (`parseTake`
in `session-cmd.ts`). Phase 1 must leave its `GET /sessions` byte-equal. So:

- In Python, always: a port of `readRecord` and `sessionRows` gives the same bytes for registry files env wrote and
  for the files the shim writes from the index after an import.
- Under node, when node and a lomem checkout are there: the same, through Voice's real TypeScript, copied read only
  into a temp folder with its few imports stubbed, plus Voice's own `Registry.patch` on a shim-written file, and
  `tailOf` and `parseTake` on the contract's fixtures. The pre-push hook runs with an empty HOME, so these skip there.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_index_import import IndexWorld, SID_A, SID_B, SID_C, record  # noqa: E402

LOMEM = os.environ.get("LOMEM_CHECKOUT") or os.path.join(os.path.expanduser("~"), "projects", "lomem")
VOICE_HOST = os.path.join(LOMEM, "apps", "claudevoice", "host", "src")
VOICE_SHARED = os.path.join(LOMEM, "packages", "claudevoice-shared", "src", "sessions.ts")
FIXTURES = os.path.join(HERE, "fixtures", "session_index")
NOW_MS = 1796000000000  # 2026-11-30, after every fixture's `updated`
SESSION_NOW_MINUTES = 30
SID_J = "eeeeeeee-5555-4555-8555-000000000005"


# ---------------------------------------------------------------- Voice's parsers, ported (sessions.ts)

SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$")


def _str(v):
    return v if isinstance(v, str) else ""


def py_read_record(o):
    """readRecord."""
    if not isinstance(o, dict) or not isinstance(o.get("sid"), str) or not SID_RE.match(o["sid"]):
        return None
    t = o.get("topic") if isinstance(o.get("topic"), dict) else None
    num = lambda v, d: v if isinstance(v, (int, float)) and not isinstance(v, bool) else d  # noqa: E731
    return {"version": num(o.get("version"), 1), "sid": o["sid"], "name": _str(o.get("name")),
            "machine": _str(o.get("machine")), "account": _str(o.get("account")), "cwd": _str(o.get("cwd")),
            "last_prompt": _str(o.get("last_prompt")), "last_answer": _str(o.get("last_answer")),
            "updated": _str(o.get("updated")), "live": o.get("live") is True, "owner": _str(o.get("owner")),
            "owner_since": _str(o.get("owner_since")), "epoch": num(o.get("epoch"), 0),
            "kind": "job" if o.get("kind") == "job" else "chat",
            "topic": {"host": _str(t.get("host")), "id": _str(t.get("id"))}
            if t and _str(t.get("host")) and _str(t.get("id")) else None}


def py_registry_all(d):
    """Registry.all: every `*.json` that parses and reads as a record."""
    out = []
    for n in os.listdir(d):
        if not n.endswith(".json"):
            continue
        sid = n[:-5]
        if not SID_RE.match(sid):
            continue
        try:
            with open(os.path.join(d, n)) as f:
                rec = py_read_record(json.load(f))
        except (OSError, ValueError):
            continue
        if rec is not None:
            out.append(rec)
    return out


def _ms(iso):
    import datetime
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000
    except (ValueError, AttributeError):
        return 0


def _where(owner):
    """whereOf in @claudevoice/shared."""
    if owner.startswith("phone"):
        return "phone"
    return owner if owner in ("mac", "lat") else "main"


def py_session_rows(records, now_ms):
    """sessionRows with no topics of the server's own, no query and no filter."""
    rows = []
    for r in records:
        row = {k: r[k] for k in ("sid", "name", "machine", "account", "cwd", "last_prompt", "last_answer", "updated",
                                 "live", "owner", "owner_since", "epoch", "kind", "topic")}
        row["where"] = _where(r["owner"])
        live = row["live"] or now_ms - _ms(row["updated"]) <= SESSION_NOW_MINUTES * 60000
        row["section"] = "now" if live else "earlier"
        rows.append(row)
    rows.sort(key=lambda x: -_ms(x["updated"]))
    return rows


def get_sessions_bytes(rows):
    """What `GET /sessions` sends: Fastify's JSON.stringify of `{sessions}`."""
    return json.dumps({"sessions": rows}, ensure_ascii=False, separators=(",", ":")).encode()


# ---------------------------------------------------------------- Voice's real code under node

def voice_available():
    return bool(shutil.which("node")) and os.path.isfile(os.path.join(VOICE_HOST, "sessions.ts")) \
        and os.path.isfile(os.path.join(VOICE_HOST, "session-cmd.ts")) and os.path.isfile(VOICE_SHARED)


needs_voice = pytest.mark.skipif(not voice_available(), reason="needs node and a lomem checkout with Claude Voice")

STUBS = {
    "laptop.ts": 'export const LAPTOP = "laptop";\n',
    "records.ts": "export function zonedIso(d: Date = new Date()): string { return d.toISOString(); }\n",
    "topics.ts": ("export class OwnerError extends Error { status: number; "
                  "constructor(status: number, message: string) { super(message); this.status = status; } }\n"
                  "export type Topic = any;\nexport type Topics = any;\n"),
}

DRIVER = r"""
import { Registry, sessionRows, tailOf } from "./sessions.ts";
import { parseTake } from "./session-cmd.ts";
const [cmd, a, b, c, d] = process.argv.slice(2);
let out: unknown;
if (cmd === "rows") out = { sessions: sessionRows({ records: new Registry(a).all(), topics: [], host: "prod", account: "me", nowMs: Number(b), q: "", where: "" }) };
else if (cmd === "patch") out = new Registry(a).patch(b, JSON.parse(c));
else if (cmd === "get") out = new Registry(a).get(b);
else if (cmd === "tail") out = tailOf(a, JSON.parse(b));
else if (cmd === "take") { try { out = parseTake(a, Number(b), c, d ?? ""); } catch (e) { out = { error: (e as Error).message, refused: (e as { refused?: boolean }).refused }; } }
process.stdout.write(JSON.stringify(out));
"""


def _rewrite(src):
    src = src.replace('from "@claudevoice/shared"', 'from "./shared.ts"')
    return re.sub(r'from "\./([a-z-]+)\.js"', r'from "./\1.ts"', src)


@pytest.fixture(scope="module")
def voice(tmp_path_factory):
    """Voice's sessions.ts and session-cmd.ts, read only, copied with their imports pointed at stubs."""
    d = str(tmp_path_factory.mktemp("voice"))
    for name in ("sessions.ts", "session-cmd.ts"):
        with open(os.path.join(VOICE_HOST, name)) as f:
            src = f.read()
        with open(os.path.join(d, name), "w") as f:
            f.write(_rewrite(src))
    shutil.copy(VOICE_SHARED, os.path.join(d, "shared.ts"))
    for name, src in STUBS.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(src)
    with open(os.path.join(d, "driver.ts"), "w") as f:
        f.write(DRIVER)
    with open(os.path.join(d, "package.json"), "w") as f:
        f.write('{"type": "module"}\n')

    def call(*args):
        r = subprocess.run(["node", "--experimental-transform-types", "--no-warnings", os.path.join(d, "driver.ts")]
                           + [str(a) for a in args], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, TZ="UTC"))
        assert r.returncode == 0, r.stderr
        return r.stdout
    return call


# ---------------------------------------------------------------- the world: env's files, imported, then the shim's

@pytest.fixture
def iw(tmp_path, monkeypatch):
    import time
    w = IndexWorld(str(tmp_path), monkeypatch)
    m = w["main"]
    m.put_record(record(SID_A, owner="main", epoch=1, live=True, updated="2026-11-20T10:00:00+00:00"))
    m.put_record(record(SID_B, owner="phone:prod", epoch=2, topic={"host": "prod", "id": "kitchen"},
                        name="kitchen plans", last_prompt="what about the oven", last_answer="The oven fits.",
                        updated="2026-11-21T08:30:00+00:00"))
    m.put_record(record(SID_C, owner="mac", epoch=3, machine="mac", cwd="/Users/me/projects/notes",
                        account="second", name="notes — tidy", updated="2026-11-19T07:00:00+00:00"))
    m.put_record(record(SID_J, owner="main", epoch=1, kind="job", name="osidx-4-importer",
                        updated="2026-11-22T23:59:59+00:00"))
    yield w
    monkeypatch.undo()
    time.tzset()


def import_and_rewrite(iw, monkeypatch, out_dir):
    """Imports the hub's registry, then lets the shim write every file anew into `out_dir` from the index."""
    import fleet_index_import
    import fleet_registry_shim as shim
    assert fleet_index_import.main(["import", "--machine", "main", "--backup-dir", os.path.join(iw.base, "bk")]) == 0
    os.makedirs(out_dir)
    monkeypatch.setenv("CLAUDE_SESSIONS_DIR", out_dir)
    os.unlink(shim.state_path())
    con = iw.con()
    try:
        shim.after_change(con, sorted(iw.rows()))
    finally:
        con.close()


EXPECTED_ROWS = [
    {"sid": SID_J, "name": "osidx-4-importer", "machine": "main", "account": "me", "cwd": "/home/me/projects/app",
     "last_prompt": "run the tests", "last_answer": "All green.", "updated": "2026-11-22T23:59:59+00:00",
     "live": False, "owner": "main", "owner_since": "2026-11-20T09:00:00+00:00", "epoch": 1, "kind": "job",
     "topic": None, "where": "main", "section": "earlier"},
    {"sid": SID_B, "name": "kitchen plans", "machine": "main", "account": "me", "cwd": "/home/me/projects/app",
     "last_prompt": "what about the oven", "last_answer": "The oven fits.", "updated": "2026-11-21T08:30:00+00:00",
     "live": False, "owner": "phone:prod", "owner_since": "2026-11-20T09:00:00+00:00", "epoch": 2, "kind": "chat",
     "topic": {"host": "prod", "id": "kitchen"}, "where": "phone", "section": "earlier"},
    {"sid": SID_A, "name": "fix the build", "machine": "main", "account": "me", "cwd": "/home/me/projects/app",
     "last_prompt": "run the tests", "last_answer": "All green.", "updated": "2026-11-20T10:00:00+00:00",
     "live": True, "owner": "main", "owner_since": "2026-11-20T09:00:00+00:00", "epoch": 1, "kind": "chat",
     "topic": None, "where": "main", "section": "now"},
    {"sid": SID_C, "name": "notes — tidy", "machine": "mac", "account": "second",
     "cwd": "/Users/me/projects/notes", "last_prompt": "run the tests", "last_answer": "All green.",
     "updated": "2026-11-19T07:00:00+00:00", "live": False, "owner": "mac",
     "owner_since": "2026-11-20T09:00:00+00:00", "epoch": 3, "kind": "chat", "topic": None, "where": "mac",
     "section": "earlier"},
]


# ---------------------------------------------------------------- always: the Python fixture comparison

def test_get_sessions_is_byte_equal_for_env_files_and_shim_files(iw, monkeypatch):
    before = get_sessions_bytes(py_session_rows(py_registry_all(iw.hub.registry), NOW_MS))
    assert json.loads(before) == {"sessions": EXPECTED_ROWS}
    out = os.path.join(iw.base, "shim-written")
    import_and_rewrite(iw, monkeypatch, out)
    assert sorted(os.listdir(out)) == sorted(n for n in os.listdir(iw.hub.registry))
    after = get_sessions_bytes(py_session_rows(py_registry_all(out), NOW_MS))
    assert after == before


def test_an_import_rewrites_no_registry_file(iw):
    import fleet_index_import
    files = {p: (open(p, "rb").read(), os.stat(p).st_mtime_ns)
             for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))}
    assert fleet_index_import.main(["import", "--backup-dir", os.path.join(iw.base, "bk")]) == 0
    assert {p: (open(p, "rb").read(), os.stat(p).st_mtime_ns)
            for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))} == files


# ---------------------------------------------------------------- under node: Voice's real code

@needs_voice
def test_voice_reads_shim_files_exactly_as_env_files(iw, monkeypatch, voice):
    before = voice("rows", iw.hub.registry, NOW_MS)
    assert json.loads(before) == {"sessions": EXPECTED_ROWS}
    # The Python port above is Voice's own logic: same bytes.
    assert before.encode() == get_sessions_bytes(py_session_rows(py_registry_all(iw.hub.registry), NOW_MS))
    out = os.path.join(iw.base, "shim-written")
    import_and_rewrite(iw, monkeypatch, out)
    assert voice("rows", out, NOW_MS) == before


@needs_voice
def test_voices_own_patch_survives_the_next_shim_write(iw, voice):
    import fleet_index_import
    import fleet_index_store
    import fleet_registry_shim as shim
    assert fleet_index_import.main(["import", "--backup-dir", os.path.join(iw.base, "bk")]) == 0
    patch = {"topic": {"host": "prod", "id": "kitchen"}, "live": True, "last_prompt": "and the fridge",
             "last_answer": "It fits too.", "updated": "2026-11-25T12:00:00+00:00"}
    assert voice("patch", iw.hub.registry, SID_B, json.dumps(patch)) == "true"
    con = iw.con()
    try:
        fleet_index_store.rename(con, SID_B, "kitchen and fridge")
        shim.after_change(con, [SID_B])
    finally:
        con.close()
    got = json.loads(voice("get", iw.hub.registry, SID_B))
    assert {k: got[k] for k in patch} == patch
    assert (got["name"], got["owner"], got["epoch"]) == ("kitchen and fridge", "phone:prod", 2)
    assert (iw.rows()[SID_B]["last_prompt"], iw.rows()[SID_B]["last_answer"]) == ("and the fridge", "It fits too.")


@needs_voice
def test_voices_tail_and_take_parsers_read_the_contracts_shapes(voice):
    with open(os.path.join(FIXTURES, "tail_reply", "valid", "two-turns.json")) as f:
        tail = json.load(f)
    assert json.loads(voice("tail", tail["sid"], json.dumps(tail))) == {
        "sid": tail["sid"],
        "turns": [{"prompt": "the build fails on the docs step, fix it",
                   "answer": "Fixed: the docs step had a stale path.", "at": "2026-11-25T21:00:05.120Z"}]}
    with open(os.path.join(FIXTURES, "env_take_reply", "valid", "ok.json")) as f:
        take = json.load(f)
    stdout = "moving...\n" + json.dumps(take) + "\n"
    assert json.loads(voice("take", take["sid"], 0, stdout, "")) == {
        "sid": take["sid"], "owner": take["owner"], "cwd": take["cwd"], "epoch": take["epoch"]}
    refused = json.loads(voice("take", take["sid"], 2, "", "session x is a work session: it never leaves its machine\n"))
    assert refused == {"error": "session x is a work session: it never leaves its machine", "refused": True}
