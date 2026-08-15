#!/usr/bin/env node
/*
 * Playwright end-to-end for the DELETE button on the workspace index.
 *
 * Deleting a workspace is the only irreversible action the product has, and
 * until this file nothing drove it: test_delete_session.py covers the function,
 * test_write_gate.py covers the route, and test_index_page.py reads the page's
 * source as a string. The button itself — confirm dialog, fetch, row removal,
 * and whether the bytes actually leave the disk — was never exercised.
 *
 *   1. Cancelling the confirm deletes NOTHING. The dialog is the only thing
 *      standing between a stray click and a workspace, so it has to hold.
 *   2. Accepting it removes that row, and ONLY that row.
 *   3. The workspace is gone from disk — the row vanishing is not enough, the
 *      list is updated optimistically and would look identical either way.
 *   4. It stays gone across a reload, i.e. the registry was persisted rather
 *      than only mutated in memory.
 *   5. The untouched workspace still opens.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/sessions-delete.e2e.cjs
 * (requires the global `playwright` package + an installed chromium)
 */
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const readline = require("readline");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
function log(m) { process.stdout.write(m + "\n"); }
function fail(m) { throw new Error("ASSERTION FAILED: " + m); }
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function startServer() {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "sd-e2e-home-"));
  const proc = spawn("python3", ["-m", "skills.annotate.server"], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONPATH: REPO_ROOT, HOME: fakeHome,
           ANNOTATE_PUBLIC_HOST: "localhost", ANNOTATE_SHUTDOWN_SECONDS: "180",
           ANNOTATE_PORT: "0" },
  });
  return new Promise((resolve, reject) => {
    const rl = readline.createInterface({ input: proc.stdout });
    rl.on("line", (line) => {
      try { const i = JSON.parse(line); if (i.type === "server-started") resolve({ proc, info: i, fakeHome }); }
      catch (_) {}
    });
    proc.stderr.on("data", () => {});
    proc.on("exit", (c) => reject(new Error("server exited early: " + c)));
    setTimeout(() => reject(new Error("server start timeout")), 8000);
  });
}
function postJSON(port, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const req = http.request({ host: "127.0.0.1", port, path: urlPath, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": data.length } },
      (res) => { let b = ""; res.on("data", c => b += c); res.on("end", () => resolve({ status: res.statusCode, body: b })); });
    req.on("error", reject); req.write(data); req.end();
  });
}
function writeBlocks(dir, blocks) {
  const tmp = path.join(dir, "blocks.json.tmp");
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-sd", title: "sd", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  const cleanup = () => {
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    // Two workspaces, so "deleted the right one" is a real question.
    async function make(title) {
      const project = fs.mkdtempSync(path.join(os.tmpdir(), "sd-e2e-proj-"));
      const r = await postJSON(info.port, "/api/sessions", { cwd: project, title });
      if (r.status !== 200) throw new Error("create failed: " + r.body);
      const s = JSON.parse(r.body);
      writeBlocks(s.response_dir, [{ id: "b-0", title, markdown: "Body of " + title }]);
      return { ...s, dir: path.dirname(s.state_dir) };
    }
    const doomed = await make("Payroll notes");
    const keeper = await make("Keep me around");
    if (!fs.existsSync(doomed.dir) || !fs.existsSync(keeper.dir))
      throw new Error("fixture workspaces were not created on disk");
    log(`✓ two workspaces: ${doomed.slug}, ${keeper.slug}`);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    const indexUrl = `http://127.0.0.1:${info.port}/`;
    await page.goto(indexUrl, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`tr[data-slug="${doomed.slug}"]`, { timeout: 8000 });
    await page.waitForSelector(`tr[data-slug="${keeper.slug}"]`, { timeout: 8000 });
    log("✓ the index lists both");

    // ── 1. cancelling the confirm must delete nothing ───────────────────────
    let dialogText = "";
    const decline = (d) => { dialogText = d.message(); d.dismiss(); };
    page.on("dialog", decline);
    await page.locator(`.act-del[data-del="${doomed.slug}"]`).click();
    await sleep(600);
    if (!/permanent|cannot be undone/i.test(dialogText))
      fail(`the confirm does not say the action is irreversible: ${JSON.stringify(dialogText)}`);
    if (!fs.existsSync(doomed.dir)) fail("a CANCELLED confirm still deleted the workspace");
    if (!(await page.locator(`tr[data-slug="${doomed.slug}"]`).count()))
      fail("a cancelled delete removed the row anyway");
    log(`✓ cancelling deletes nothing; confirm reads ${JSON.stringify(dialogText.slice(0, 48))}…`);
    page.off("dialog", decline);

    // ── 2 & 3. accepting deletes exactly that one, on disk ──────────────────
    page.on("dialog", (d) => d.accept());
    await page.locator(`.act-del[data-del="${doomed.slug}"]`).click();
    await page.waitForSelector(`tr[data-slug="${doomed.slug}"]`, { state: "detached", timeout: 8000 });
    if (!(await page.locator(`tr[data-slug="${keeper.slug}"]`).count()))
      fail("deleting one workspace removed the other's row too");
    if (fs.existsSync(doomed.dir))
      fail("the row vanished but the workspace is still on disk — the list only looked updated");
    if (!fs.existsSync(keeper.dir)) fail("the WRONG workspace was deleted from disk");
    log("✓ accepting removed exactly one workspace, bytes and all");

    // ── 4. the SERVER agrees it is gone, not just this page ─────────────────
    // A reload re-fetches /api/sessions?scope=all, so a row that survived
    // client-side hiding would come back here. It does NOT prove the registry
    // was written to disk — that needs a server restart, and is asserted in
    // test_delete_session.py::test_delete_is_written_to_disk_not_just_memory.
    await page.goto(indexUrl, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`tr[data-slug="${keeper.slug}"]`, { timeout: 8000 });
    if (await page.locator(`tr[data-slug="${doomed.slug}"]`).count())
      fail("the deleted workspace came back on reload — the server still lists it");
    log("✓ the server no longer lists it either");

    // ── 5. the survivor still opens ─────────────────────────────────────────
    const opened = await page.goto(`http://127.0.0.1:${info.port}/s/${keeper.slug}/`,
                                   { waitUntil: "domcontentloaded" });
    if (!opened || opened.status() !== 200)
      fail("the surviving workspace no longer opens: " + (opened && opened.status()));
    log("✓ the untouched workspace still opens");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
