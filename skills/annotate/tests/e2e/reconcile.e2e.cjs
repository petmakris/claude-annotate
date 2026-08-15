#!/usr/bin/env node
/*
 * Playwright end-to-end regression for the annotate client reconciliation bug.
 *
 * Reproduces the exact reported scenario and asserts the fix:
 *   1. Page renders block b-0.
 *   2. User comments on b-0 and submits the round → the page goes busy.
 *   3. Claude responds by ADDING a new block (b-1) and leaving b-0 unchanged,
 *      then acks the event (writes consumed/<id>.ack).
 *   4. Assert (Defect A): the new block b-1 renders in the DOM.
 *   5. Assert (Defect B): the pending state clears — even though b-0's own
 *      version never bumped — because clearing is keyed on the consumed event.
 *
 * The pending indicator used to be a per-block "updating" spinner on b-0. A
 * round applies across many blocks at once, so it is now the page-level busy
 * banner (the per-block overlay survives only on the `choice` path). The
 * invariant under test is unchanged: an ack clears the wait, a version bump
 * is not required, and no block may be left stuck.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/reconcile.e2e.cjs
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

function log(msg) { process.stdout.write(msg + "\n"); }
function fail(msg) { throw new Error("ASSERTION FAILED: " + msg); }

function startServer() {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "annotate-e2e-home-"));
  const proc = spawn("python3",
    ["-m", "skills.annotate.server"],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: REPO_ROOT,
        HOME: fakeHome,
        ANNOTATE_PUBLIC_HOST: "localhost",
        ANNOTATE_SHUTDOWN_SECONDS: "120",
        // Port 0 = let the OS pick. Without this the suite binds the default
        // port and dies with "server exited early: 1" whenever the developer
        // has their own annotate server running — which is most of the time.
        ANNOTATE_PORT: "0",
      },
    });
  return new Promise((resolve, reject) => {
    const rl = readline.createInterface({ input: proc.stdout });
    rl.on("line", (line) => {
      try {
        const info = JSON.parse(line);
        if (info.type === "server-started") resolve({ proc, info, rl, fakeHome });
      } catch (_) { /* http log lines — ignore, but keep draining */ }
    });
    proc.stderr.on("data", () => {});
    proc.on("exit", (code) => reject(new Error("server exited early: " + code)));
    setTimeout(() => reject(new Error("server start timeout")), 8000);
  });
}

function postJSON(port, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const req = http.request(
      { host: "localhost", port, path: urlPath, method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": data.length } },
      (res) => {
        let buf = "";
        res.on("data", (c) => (buf += c));
        res.on("end", () => resolve({ status: res.statusCode, body: buf }));
      });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function writeBlocks(responseDir, blocks) {
  const doc = { response_id: "resp-e2e", title: "e2e", blocks };
  const tmp = path.join(responseDir, "blocks.json.tmp");
  fs.writeFileSync(tmp, JSON.stringify(doc));
  fs.renameSync(tmp, path.join(responseDir, "blocks.json"));
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "annotate-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir;
    const eventsDir = sess.events_dir;
    const consumedDir = sess.consumed_dir;

    // Initial doc: a single markdown block.
    writeBlocks(responseDir, [{ id: "b-0", markdown: "# Original\n\nThe only block." }]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });

    // 1. b-0 renders.
    await page.waitForSelector('section.block[data-block-id="b-0"]', { timeout: 8000 });
    log("✓ b-0 rendered");

    // 2. Comment on b-0 and submit.
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    // Hover the HEADER, not the section. The control strip lives in the
    // card header and reveals on .card-head hover; hovering the section
    // puts the pointer in the body, leaving the strip hidden and the
    // header intercepting the click.
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="comment"]').click();
    const ta = page.locator('.comment-card textarea').first();
    await ta.fill("Please add a second block explaining the details.");
    // A card's submit button pins the comment into the LOCAL round; nothing
    // reaches Claude until the round dock's Submit fires it. Two clicks,
    // not one — the batching model is the whole point of the dock.
    await page.locator('.card-submit-btn').first().click();   // "Add to round"
    await page.locator("#round-submit").click();

    // The page goes busy on the submitted round.
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    log("✓ page went busy after the round was submitted");

    // 3. Simulate Claude: add b-1, leave b-0 untouched, then ack the event.
    const eventId = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"))[0].replace(/\.json$/, "");
    writeBlocks(responseDir, [
      { id: "b-0", markdown: "# Original\n\nThe only block." },         // UNCHANGED
      { id: "b-1", markdown: "## Details\n\nThe freshly added block." }, // NEW
    ]);
    fs.writeFileSync(path.join(consumedDir, eventId + ".ack"), "");

    // 4. Defect A: the new block renders (poll is 1s; allow margin).
    await page.waitForSelector('section.block[data-block-id="b-1"]', { timeout: 8000 });
    const b1text = await page.locator('section.block[data-block-id="b-1"]').innerText();
    if (!b1text.includes("freshly added block")) fail("b-1 rendered but content missing");
    log("✓ Defect A fixed: newly-added block b-1 rendered with its content");

    // 5. Defect B: the wait clears on the ACK, though b-0's version never
    //    bumped. b-0 must also be left in no kind of stuck state.
    await page.waitForSelector("#busy-banner", { state: "detached", timeout: 10000 });
    const stuck = await page.locator(
      'section.block[data-block-id="b-0"].is-updating, ' +
      'section.block[data-block-id="b-0"] .updating-overlay').count();
    if (stuck) fail("b-0 was left in an updating state after the ack");
    const b0text = await page.locator('section.block[data-block-id="b-0"]').innerText();
    if (!b0text.includes("The only block")) fail("b-0 lost its content across the reconcile");
    log("✓ Defect B fixed: wait cleared via consumed event (no version bump), b-0 intact");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
