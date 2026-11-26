"""Claude Voice's parsers against the contract's shapes (contract section 12.4).

Claude Voice reads the session index, never a registry file. It still runs `@claude session tail --json` (`tailOf` in
lomem's `apps/claudevoice/host/src/sessions.ts`) and reads take's last line (`parseTake` in `session-cmd.ts`). Under
node, when node and a lomem checkout are there, Voice's real TypeScript is copied read only into a temp folder with
its few imports stubbed and run on the contract's fixtures. The pre-push hook runs with an empty HOME, so it skips
there. An import, which still reads the old registry files, rewrites none of them.
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

from test_index_import import IndexWorld, SID_A, SID_B, record  # noqa: E402

LOMEM = os.environ.get("LOMEM_CHECKOUT") or os.path.join(os.path.expanduser("~"), "projects", "lomem")
VOICE_HOST = os.path.join(LOMEM, "apps", "claudevoice", "host", "src")
VOICE_SHARED = os.path.join(LOMEM, "packages", "claudevoice-shared", "src", "sessions.ts")
FIXTURES = os.path.join(HERE, "fixtures", "session_index")


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
import { tailOf } from "./sessions.ts";
import { parseTake } from "./session-cmd.ts";
const [cmd, a, b, c, d] = process.argv.slice(2);
let out: unknown;
if (cmd === "tail") out = tailOf(a, JSON.parse(b));
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


# ---------------------------------------------------------------- an import reads the old files and writes none

@pytest.fixture
def iw(tmp_path, monkeypatch):
    w = IndexWorld(str(tmp_path), monkeypatch)
    m = w["main"]
    m.put_record(record(SID_A, owner="main", epoch=1, live=True, updated="2026-11-20T10:00:00+00:00"))
    m.put_record(record(SID_B, owner="phone:prod", epoch=2, topic={"host": "prod", "id": "kitchen"},
                        name="kitchen plans", updated="2026-11-21T08:30:00+00:00"))
    return w


def test_an_import_rewrites_no_registry_file(iw):
    import fleet_index_import
    files = {p: (open(p, "rb").read(), os.stat(p).st_mtime_ns)
             for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))}
    assert fleet_index_import.main(["import", "--backup-dir", os.path.join(iw.base, "bk")]) == 0
    assert {p: (open(p, "rb").read(), os.stat(p).st_mtime_ns)
            for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))} == files


# ---------------------------------------------------------------- under node: Voice's real code

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
