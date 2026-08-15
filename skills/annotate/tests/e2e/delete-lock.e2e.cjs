#!/usr/bin/env node
/*
 * Playwright e2e for the DELETE control and the page lock it eventually
 * raises. Formerly dismiss.e2e.cjs, when × on a block fired an event the
 * instant it was clicked. It does not any more, and that reversal is the
 * thing most worth pinning down here.
 *
 * Seeds 3 markdown blocks, then:
 *  - marks block 2 "delete" from its card header, and asserts NOTHING left the
 *    browser: no event on disk, no busy state. Every mark is local until the
 *    round dock's Submit — that is the whole timing model.
 *  - asserts the mark is visible and reversible (the block is struck through,
 *    still on the page, not removed)
 *  - submits the round, and only NOW asserts the page goes busy: .busy-banner,
 *    body.is-busy, and /poll reporting busy:true
 *  - asserts the block controls stay LIVE while busy. This is deliberate and
 *    was once the opposite: freezing the whole vocabulary took away work the
 *    user could still do on the sections Claude is not touching. Marks made
 *    now queue for the next round.
 *  - simulates Claude: remove block 2 from blocks.json + write the .ack
 *  - asserts the banner clears, body loses is-busy, and block 2 is gone
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/delete-lock.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "annotate-delete-home-"));
  const proc = spawn("python3", ["-m", "skills.annotate.server"], {
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
      } catch (_) { /* http log lines */ }
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

function getJSON(port, urlPath) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: "localhost", port, path: urlPath, method: "GET" },
      (res) => {
        let buf = "";
        res.on("data", (c) => (buf += c));
        res.on("end", () => resolve({ status: res.statusCode, body: buf }));
      });
    req.on("error", reject);
    req.end();
  });
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "annotate-delete-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir;
    const eventsDir = sess.events_dir;
    const consumedDir = sess.consumed_dir;

    // Write 3 blocks via atomic rename (same pattern as other e2e helpers).
    const doc = {
      response_id: "r-delete",
      title: "Delete test",
      blocks: [
        { id: "section-1", title: "Alpha", markdown: "First." },
        { id: "section-2", title: "Beta",  markdown: "Second." },
        { id: "section-3", title: "Gamma", markdown: "Third." },
      ],
    };
    const tmp = path.join(responseDir, "blocks.json.tmp");
    fs.writeFileSync(tmp, JSON.stringify(doc));
    fs.renameSync(tmp, path.join(responseDir, "blocks.json"));

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="section-2"]', { timeout: 8000 });
    log("✓ blocks rendered");

    const b2 = page.locator('section.block[data-block-id="section-2"]');

    // Mark block 2 "delete" from its card header. The strip reveals on
    // .card-head hover — hovering the section puts the pointer in the body.
    await b2.locator(".card-head").hover();
    await b2.locator('.hover-actions button[data-type="delete"]').click();

    // NOTHING may have left the browser yet.
    await new Promise((r) => setTimeout(r, 600));
    const earlyEvents = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"));
    if (earlyEvents.length) fail("a mark reached Claude before the round was submitted: " + earlyEvents);
    if (await page.evaluate(() => document.body.classList.contains("is-busy")))
      fail("the page went busy on a mark, before any submission");
    log("✓ the mark is local: no event on disk, page not busy");

    // It is visible and reversible: struck through, still on the page.
    if (await page.locator('section.block[data-block-id="section-2"][data-block-mark="delete"]').count() !== 1)
      fail("the pending delete is not shown on the block");
    if (await b2.count() !== 1) fail("the block was removed locally instead of marked");
    log("✓ the pending delete is shown on the block, which is still there");

    // Submit the round — NOW it reaches Claude.
    await page.locator("#round-submit").click();

    // Assert page entered BUSY state.
    await page.waitForSelector(".busy-banner", { timeout: 8000 });
    const isBusy = await page.evaluate(() => document.body.classList.contains("is-busy"));
    if (!isBusy) fail("body does not have is-busy class after the round was submitted");
    log("✓ busy-banner visible and body.is-busy set");

    // Assert /poll reports busy:true.
    const pollResp = await getJSON(info.port, "/s/" + sess.sid + "/poll");
    const pollData = JSON.parse(pollResp.body);
    if (!pollData.busy) fail("/poll did not report busy:true after submit; got: " + pollResp.body);
    log("✓ /poll reports busy:true");

    // Marking stays LIVE while a round is in flight — deliberate, and the
    // reverse of what this test used to assert. See the note in style.css
    // above the (absent) `body.is-busy .unit-strip` rule.
    //
    // Asserted by USE, not by computed style. `.card-head:hover
    // .hover-actions` sets `pointer-events: auto` at higher specificity than
    // any `body.is-busy` rule could, so reading the property while hovering
    // reports "auto" no matter what — a freeze added on the BUTTONS would
    // sail straight past it. Actually marking a block is the only check that
    // cannot be fooled.
    const b1 = page.locator('section.block[data-block-id="section-1"]');
    await b1.locator(".card-head").hover();
    try {
      await b1.locator('.hover-actions button[data-type="keep"]').click({ timeout: 4000 });
    } catch (_) {
      fail("block controls are frozen while busy — marks for the NEXT round are unreachable");
    }
    if (await page.locator('section.block[data-block-id="section-1"][data-block-mark="keep"]').count() !== 1)
      fail("a mark made during an in-flight round did not register");
    log("✓ a block can still be marked while a round is in flight");

    // Simulate Claude: find the queued event, rewrite blocks.json without section-2, write .ack.
    const eventFiles = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"));
    if (eventFiles.length === 0) fail("no event files found in events_dir after the round was submitted");
    const eventId = eventFiles[0].replace(/\.json$/, "");

    const updatedDoc = {
      response_id: "r-delete",
      title: "Delete test",
      blocks: [
        { id: "section-1", title: "Alpha", markdown: "First." },
        { id: "section-3", title: "Gamma", markdown: "Third." },
      ],
    };
    const tmp2 = path.join(responseDir, "blocks.json.tmp");
    fs.writeFileSync(tmp2, JSON.stringify(updatedDoc));
    fs.renameSync(tmp2, path.join(responseDir, "blocks.json"));
    fs.writeFileSync(path.join(consumedDir, eventId + ".ack"), "");

    // Assert banner clears, body loses is-busy, and section-2 is gone.
    await page.waitForSelector(".busy-banner", { state: "detached", timeout: 8000 });
    await page.waitForSelector('section.block[data-block-id="section-2"]', { state: "detached", timeout: 8000 });
    const isStillBusy = await page.evaluate(() => document.body.classList.contains("is-busy"));
    if (isStillBusy) fail("body.is-busy not cleared after ack");
    log("✓ busy-banner gone, body.is-busy cleared, section-2 removed from DOM");

    log("\nDELETE-LOCK E2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nDELETE-LOCK E2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
