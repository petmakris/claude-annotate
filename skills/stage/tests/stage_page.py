"""The stage page's own JavaScript (stage.js, with scene.js, lanes.js and map.js) run under node on a small DOM
(skills/_shared/tests/dom_shim.mjs), embedded as a talk call embeds it: no browser, no daemon.

A test puts views up with show() as stage.show() would (its items go through a fake daemon), opens the page,
sends it the messages the call page sends, and reads back what the page did with check(). Everything runs
in one node process, in order, when run() is called; it returns the checks' values.

What it shows is logic: which frame a board is on, which rows and cards carry which classes, what the page
posts. Nothing is laid out, so nothing measured (overlap, contrast, scrolling) can be checked here."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.stage import model, stage

STATIC = Path(__file__).resolve().parents[1] / "static"
SHIM = Path(__file__).resolve().parents[2] / "_shared" / "tests" / "dom_shim.mjs"
ROW = {"sid": "abc", "slug": "abc", "kind": "stage", "url": "http://stage.test/s/abc/", "state": "live"}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

PRELUDE = """
import { readFileSync } from "node:fs";
import { install, settle, advance, message, scripts, document } from %(shim)s;
const { posted } = install({ width: %(width)d, embedded: %(embedded)s });
const store = %(store)s;
const clone = (x) => JSON.parse(JSON.stringify(x));
window.WebCompanion = {
  api: { BASE: "/s/abc/", fetchJSON: async (p) => (p === "items" ? clone(store) : clone(store[decodeURIComponent(p.slice(6))])) },
  init(o) { window.__delta = o.onDelta; },
};
scripts({
  "marked.min.js": () => new Function(readFileSync(%(marked)s, "utf8"))(),
  "purify.min.js": () => { window.DOMPurify = { sanitize: (s) => s }; },
});
let version = 100;
async function put(items) {
  for (const anchor of Object.keys(items).sort((a, b) => (a === "__layout__" ? -1 : b === "__layout__" ? 1 : 0))) {
    store[anchor] = { version: ++version, body: items[anchor] };
    window.__delta({ kind: "item", anchor, version });
  }
  await settle();
}
const out = [];
const pane = (name) => document.querySelector(`section.pane[data-view="${name}"]`);
const keys = (els) => [...els].map((e) => e.dataset.key);
const selected = (name) => document.querySelector(`button[role=tab][data-view="${name}"]`)?.getAttribute("aria-selected") === "true";
const frames = () => window.__stageTest.frames();
// a lanes board as a reader sees it: its frame, its step bar, the rows shown, the step being said, the title card
const lanes = (name) => { const p = pane(name); return { frame: frames()[name], step: p.querySelector(".vstep")?.textContent,
  on: [...p.querySelectorAll(".ln-row[data-on]")].map((r) => r.dataset.step),
  cur: [...p.querySelectorAll(".ln-row.ln-cur")].map((r) => r.dataset.step), card: p.querySelector(".k-card")?.textContent ?? null }; };
const follows = () => posted.filter((m) => m.type === "stage:follow").map((m) => m.on);
const errors = [];
const logError = console.error;
console.error = (...a) => { errors.push(a.map(String).join(" ")); logError(...a); };
await import(%(stage)s);
await settle();
"""


class StagePage:
    def __init__(self, tmp_path, width: int = 1300, embedded: bool = True):
        self.cwd = str(tmp_path)
        self.width, self.embedded = width, embedded
        self.items: dict = {}
        self.store: dict = {}
        self.steps: list = []
        self.opened = False

    # -- the daemon, as stage.show() reaches it ----------------------------------------------------
    def show(self, name, source, **kw):
        """stage.show(), its items kept here: in the snapshot the page opens on, or as a change once it is open."""
        put = {}
        fakes = {
            "list_sessions": lambda cwd, kind: [ROW],
            "all_sessions": lambda kind=None: [ROW],
            "create_or_attach": lambda *a, **k: ROW,
            "register_assets": lambda *a, **k: None,
            "register_mount": lambda sid, name, root, kind: {"name": name},
            "get_items": lambda sid, kind: {a: {"body": b, "version": 1} for a, b in self.items.items()},
            "put_items": lambda sid, items, kind, replace=False: put.update(items),
        }
        patches = [patch.object(stage.wc, n, f) for n, f in fakes.items()]
        patches.append(patch.object(stage, "start_watch", lambda cwd, sid: None))
        for p in patches:
            p.start()
        try:
            stage.show(self.cwd, name, source, **kw)
        finally:
            for p in patches:
                p.stop()
        self.items.update(put)
        if self.opened:
            self.steps.append("await put(%s);" % json.dumps(put))
        else:
            for anchor, body in put.items():
                self.store[anchor] = {"version": 1, "body": body}
        return self

    # -- the page ----------------------------------------------------------------------------------
    def open(self):
        self.opened = True
        return self

    def send(self, msg):
        """A message from the call page, then whatever the page does with it settles."""
        self.steps.append("message(%s); await settle();" % json.dumps(msg))
        return self

    def js(self, code):
        """Any statement run on the page, then it settles."""
        self.steps.append(code + "\nawait settle();")
        return self

    def check(self, expr):
        """`expr` as the page holds it now, in run()'s result."""
        self.steps.append("out.push(%s);" % expr)
        return self

    def run(self):
        assert self.opened, "open() the page before run()"
        prelude = PRELUDE % {
            "shim": json.dumps(SHIM.as_uri()), "width": self.width, "embedded": "true" if self.embedded else "false",
            "store": json.dumps(self.store), "marked": json.dumps(str(STATIC / "vendor" / "marked.min.js")),
            "stage": json.dumps((STATIC / "stage.js").as_uri()),
        }
        code = prelude + "\n".join(self.steps) + "\nprocess.stdout.write(JSON.stringify({out, posted, errors}));\nprocess.exit(0);\n"
        done = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[-4000:]
        got = json.loads(done.stdout)
        self.posted, self.errors = got["posted"], got["errors"]
        return got["out"]


def visual(tool, spec):
    return model.parse_source(f"{tool}:-", Path("."), json.dumps(spec))
