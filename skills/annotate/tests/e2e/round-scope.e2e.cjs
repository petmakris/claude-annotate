#!/usr/bin/env node
/*
 * Playwright end-to-end for the round's SCOPE — which events the change bar
 * belongs to, and which baseline it diffs against.
 *
 * The suite is full of source-string smoke tests that pass while the page is
 * visibly wrong, so every assertion here is made against a rendered page
 * driven through the real UI, never against a declaration.
 *
 *   1. M4 — a block-scope mark's drawer row says "whole section", not the
 *      block title printed twice.
 *   2. M3 — an open comment editor greys Submit out; the BUTTON has to say
 *      why, because a disabled button never shows its tooltip.
 *   3. S1 — the busy banner has no empty .bb-sub node eating a flex gap.
 *   4. M2 — a general comment sent WHILE a round is in flight must not move
 *      blocks.prev.json. If it does, "before" equals "now" for every block
 *      Claude already rewrote and the "what changed" toggle opens nothing.
 *   5. M1 — a general comment sent on its own is not a round. No change bar
 *      may appear for it, and no card may claim "you asked".
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/round-scope.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "rs-e2e-home-"));
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
    const req = http.request({ host: "localhost", port, path: urlPath, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": data.length } },
      (res) => { let b = ""; res.on("data", c => b += c); res.on("end", () => resolve({ status: res.statusCode, body: b })); });
    req.on("error", reject); req.write(data); req.end();
  });
}
function writeBlocks(dir, blocks) {
  const tmp = path.join(dir, "blocks.json.tmp");
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-rs", title: "rs", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}
// Every event id currently on disk without a matching ack — what the server
// calls "busy", and what "Claude has finished" has to clear.
function unacked(eventsDir, consumedDir) {
  const acked = new Set(fs.readdirSync(consumedDir).map(f => f.replace(/\.ack$/, "")));
  return fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"))
    .map(f => f.replace(/\.json$/, "")).filter(id => !acked.has(id));
}
function ackAll(eventsDir, consumedDir) {
  const ids = unacked(eventsDir, consumedDir);
  for (const id of ids) fs.writeFileSync(path.join(consumedDir, id + ".ack"), "");
  return ids;
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "rs-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir, eventsDir = sess.events_dir, consumedDir = sess.consumed_dir;
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    const ORIGINAL_B0 = "The retry path backs off exponentially before it gives up.";
    writeBlocks(responseDir, [
      { id: "b-0", title: "The retry path", markdown: ORIGINAL_B0 },
      { id: "b-1", title: "The queue", markdown: "A second paragraph that nobody marked at all." },
      { id: "b-2", title: "The cache", markdown: "A third paragraph that will not move." },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-2"]', { timeout: 8000 });
    log("✓ blocks rendered");

    // ── 1. M4: a block-scope row does not print its title twice ─────────────
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="keep"]').click();
    await page.waitForSelector("#round-dock", { timeout: 5000 });
    await page.locator("#round-dock .rd-caret").click();
    await page.waitForSelector("#round-dock .rd-row", { state: "visible", timeout: 5000 });
    const where = (await page.locator("#round-dock .rd-row .rd-where").innerText()).trim();
    const what = (await page.locator("#round-dock .rd-row .rd-text").innerText()).trim();
    if (where === what) fail(`drawer row prints its title twice: ${JSON.stringify(where)}`);
    if (what !== "whole section") fail(`block-scope row reads ${JSON.stringify(what)}`);
    log(`✓ M4 drawer row: where=${JSON.stringify(where)} what=${JSON.stringify(what)}`);

    // ── 2. M3: the dock says WHY it is dead ─────────────────────────────────
    const b1 = page.locator('section.block[data-block-id="b-1"]');
    await b1.locator(".card-head").hover();
    await b1.locator('.hover-actions button[data-type="comment"]').click();
    await page.waitForSelector(".comment-card textarea", { timeout: 5000 });
    const submit = page.locator("#round-submit");
    if (!(await submit.isDisabled())) fail("Submit is live with an editor open");
    const deadLabel = (await submit.innerText()).trim();
    if (!/finish or discard/i.test(deadLabel))
      fail(`disabled Submit reads ${JSON.stringify(deadLabel)} — nothing on screen says why`);
    log(`✓ M3 disabled Submit reads ${JSON.stringify(deadLabel)}`);
    await page.locator(".comment-card .card-close").click();
    await page.waitForSelector(".comment-card", { state: "detached", timeout: 5000 });
    if (await submit.isDisabled()) fail("Submit stayed dead after the editor was discarded");

    // ── 3. Submit the round; S1 checks the banner it raises ─────────────────
    await submit.click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    const subNodes = await page.locator("#busy-banner .bb-sub").count();
    if (subNodes) fail(`busy banner still carries ${subNodes} empty .bb-sub node(s)`);
    // Past the first tick of the 1s timer, so .bb-timer is legitimately full.
    await sleep(1400);
    const bannerKids = await page.locator("#busy-banner > *").evaluateAll(
      els => els.map(e => [e.className, (e.textContent || "").trim() === ""]));
    const emptyKids = bannerKids.filter(([, empty]) => empty).map(([c]) => c);
    if (emptyKids.some(c => !/spinner/.test(c)))
      fail("busy banner has an empty non-spinner child: " + JSON.stringify(emptyKids));
    log("✓ S1 busy banner children: " + JSON.stringify(bannerKids.map(k => k[0])));

    // ── 4. M2: a general comment mid-round must not move the baseline ───────
    // Claude starts applying, rewriting the block the user marked.
    const REWRITTEN_B0 = "The retry path gives up after three attempts, with no backoff.";
    writeBlocks(responseDir, [
      { id: "b-0", title: "The retry path", markdown: REWRITTEN_B0 },
      { id: "b-1", title: "The queue", markdown: "A second paragraph that nobody marked at all." },
      { id: "b-2", title: "The cache", markdown: "A third paragraph that will not move." },
    ]);
    await sleep(1500);   // let the page reconcile the mid-round rewrite
    // The user, still reading, sends a general comment through the real
    // composer — deliberately usable while busy.
    await page.locator("#composer-toggle").click();
    await page.locator("#general-input").fill("while you're in there, check the cache");
    await page.locator("#general-send").click();
    await sleep(1200);
    if (unacked(eventsDir, consumedDir).length < 2)
      fail("the general comment did not queue alongside the round");
    // Claude finishes: sweeps b-1 too, then acks both events.
    writeBlocks(responseDir, [
      { id: "b-0", title: "The retry path", markdown: REWRITTEN_B0 },
      { id: "b-1", title: "The queue", markdown: "A second paragraph that nobody marked whatsoever." },
      { id: "b-2", title: "The cache", markdown: "A third paragraph that will not move." },
    ]);
    log("  acked: " + JSON.stringify(ackAll(eventsDir, consumedDir)));

    await page.waitForSelector("#change-bar", { timeout: 10000 });
    await page.waitForSelector('section.block[data-block-id="b-0"] .card-diff-toggle', { timeout: 8000 });
    // The toggle is painted unconditionally; the pane is what the baseline
    // decides. A toggle with no pane is the bug.
    const paneCount = await page.locator('section.block[data-block-id="b-0"] .diff-pane').count();
    if (!paneCount) fail('"what changed" is offered on b-0 but opens nothing — the baseline moved');
    await page.locator('section.block[data-block-id="b-0"] .card-diff-toggle').click();
    const del = (await page.locator('section.block[data-block-id="b-0"] .diff-pane del').allInnerTexts()).join("").trim();
    const ins = (await page.locator('section.block[data-block-id="b-0"] .diff-pane ins').allInnerTexts()).join("").trim();
    if (!del || !ins) fail(`b-0 diff pane is empty: del=${JSON.stringify(del)} ins=${JSON.stringify(ins)}`);
    // "exponentially" exists ONLY in the pre-round text. If the baseline had
    // moved to the mid-round document it could not appear as a deletion.
    if (!/exponentially/.test(del)) fail(`b-0 diffed against the wrong baseline: del=${JSON.stringify(del)}`);
    log(`✓ M2 b-0 pane diffs against the PRE-round text: del=${JSON.stringify(del.slice(0, 40))}…`);

    // ── 5. M1: a general comment on its own is not a round ──────────────────
    await page.waitForSelector("#busy-banner", { state: "detached", timeout: 8000 });
    await page.locator("#general-input").fill("one more thought, unrelated");
    await page.locator("#general-send").click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    // Claude answers by rewriting two blocks — one of them b-0, which the
    // LAST round did mark. That is the block the stale set mislabels.
    writeBlocks(responseDir, [
      { id: "b-0", title: "The retry path", markdown: "The retry path is documented in the runbook." },
      { id: "b-1", title: "The queue", markdown: "A second paragraph that nobody marked whatsoever." },
      { id: "b-2", title: "The cache", markdown: "A third paragraph that moved for the general comment." },
    ]);
    log("  acked: " + JSON.stringify(ackAll(eventsDir, consumedDir)));
    await page.waitForSelector("#busy-banner", { state: "detached", timeout: 10000 });
    await sleep(2500);   // two full poll cycles past the ack
    const strayBar = await page.locator("#change-bar").count();
    const strayChips = await page.locator(".attr-chip").allInnerTexts();
    const strayPanes = await page.locator(".diff-pane").count();
    log(`  after a plain general comment: bar=${strayBar} chips=${JSON.stringify(strayChips)} panes=${strayPanes}`);
    if (strayBar) fail("a change bar appeared for a round the user never fired");
    if (strayChips.length) fail("attribution chips for a non-round: " + JSON.stringify(strayChips));
    if (strayPanes) fail(`${strayPanes} diff pane(s) survived a non-round exchange`);
    log("✓ M1 general comment produced no bar, no chips, no panes");

    // And the submitted set really is gone, not merely unread.
    const stillHeld = await page.evaluate(() => window.AnnotateSubunits.submittedBlockIds());
    if (stillHeld.length) fail("submittedBlockIds still holds " + JSON.stringify(stillHeld));
    log("✓ M1 submittedBlockIds cleared once the bar consumed it");

    clearInterval(beat);
    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
