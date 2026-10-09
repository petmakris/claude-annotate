"""The call page's own JavaScript (call.js) run under node on a small DOM (skills/_shared/tests/dom_shim.mjs):
no browser, no microphone, no stage page.

A call is served as the other tests serve it (a fake speech engine, each answer `seconds` long with its words
spread evenly), and what the page polls is that call's /api/state as it stood before any answer and after
each one. The page is the call's own HTML; its stage is an empty frame that says it is ready, and what the
page posts to it is kept. The audio element plays when the test says it does: play_to(t) moves it on as a
browser would, frame by frame, and end() plays it out. Timers run on a virtual clock (advance(ms)).

A test writes statements against the page (js) and reads values back (check); run() runs them all in one
node process and returns the checks' values."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import AUTH, CALL, run as run_async, running_app

STATIC = Path(__file__).resolve().parents[1] / "static"
SHIM = Path(__file__).resolve().parents[2] / "_shared" / "tests" / "dom_shim.mjs"
STAGE = "http://stage.test/s/abc/"
PAGE = f"http://127.0.0.1:8000/c/{CALL}"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


async def _settle(call):
    import asyncio
    for _ in range(100):
        if all(e.get("speech") in (None, "ready", "failed") for e in call.entries):
            return
        await asyncio.sleep(0.02)


def served(tmp_path, answers, seconds=4.0):
    """The call page's HTML and its /api/state before any answer and after each of `answers`."""
    async def go():
        async with running_app(tmp_path, stage_url=STAGE) as (client, call, fake):
            fake.seconds = seconds
            states = [await (await client.get("/api/state", headers=AUTH)).json()]
            for text in answers:
                await call.answer(text)
                await _settle(call)
                states.append(await (await client.get("/api/state", headers=AUTH)).json())
            return await (await client.get(f"/c/{CALL}")).text(), states
    return run_async(go())


PRELUDE = """
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { install, settle, advance, message, setBody, document, ShimEvent } from %(shim)s;
install({ width: 1300, url: %(url)s });
const HTML = %(html)s, STATES = %(states)s;
let served = STATES[%(start)d];
const respond = (body) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)), text: async () => JSON.stringify(body) });
globalThis.fetch = async (path) => {
  if (String(path).startsWith("/api/state")) {
    const v = new URL(path, location.href).searchParams.get("v");
    return respond(v === served.v ? { v, same: true } : served);
  }
  return respond({});
};
%(storage)s
document.documentElement.dataset.theme = "light";
setBody(HTML);
window.CFG = JSON.parse(%(cfg)s);
vm.runInThisContext(readFileSync(%(call)s, "utf8"), { filename: "call.js" });
const $ = (id) => document.getElementById(id);
const audio = $("audio");
audio.duration = %(seconds)s;
const stageWin = $("stage").contentWindow;
const toStage = () => stageWin.posted;
const fromStage = (m) => message(m, stageWin, "http://stage.test");
// the server moves on to state i: the page sees it on its next poll
async function serve(i) { served = STATES[i]; await advance(900); }
// the voice plays on to t seconds, a frame at a time
async function playTo(t) {
  for (let x = audio.currentTime; x < t; x += 0.05) { audio._t = x; await settle(1); }
  audio._t = t; await settle(1);
}
async function end() { await playTo(audio.duration); audio.end(); await settle(); }
const key = (k, target = document.body) => target.dispatchEvent(new ShimEvent("keydown", { key: k, bubbles: true }));
const out = [];
await advance(100);
fromStage({ type: "stage:ready" });
await settle();
"""


class CallPage:
    def __init__(self, html: str, states: list, *, start: int = 0, seconds: float = 4.0, autoplay: bool = True):
        self.html, self.states, self.start, self.seconds, self.autoplay = html, states, start, seconds, autoplay
        self.steps: list = []

    def js(self, code):
        self.steps.append(code + "\nawait settle();")
        return self

    def check(self, expr):
        self.steps.append("out.push(%s);" % expr)
        return self

    def run(self):
        cfg = re.search(r"window\.CFG = (.*?);</script>", self.html).group(1).replace("<\\/", "</")
        prelude = PRELUDE % {
            "shim": json.dumps(SHIM.as_uri()), "url": json.dumps(PAGE), "html": json.dumps(self.html),
            "states": json.dumps(self.states), "start": self.start, "cfg": json.dumps(cfg),
            "call": json.dumps(str(STATIC / "call.js")), "seconds": self.seconds,
            "storage": "" if self.autoplay else 'localStorage.setItem("talk.autoplay", "false");',
        }
        code = prelude + "\n".join(self.steps) + "\nprocess.stdout.write(JSON.stringify(out));\nprocess.exit(0);\n"
        done = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[-4000:]
        return json.loads(done.stdout)
