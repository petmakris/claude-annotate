#!/usr/bin/env node
/*
 * Playwright end-to-end for the change summary bar and per-block diff.
 *
 * Attribution is DERIVED, not reported: a block whose version bumped that the
 * client never submitted was moved by the coherence sweep. This walks the real
 * path that produces it — mark one block, submit, let "Claude" rewrite the
 * marked block AND an unmarked one, ack — and asserts the page says so.
 *
 *   1. Mark b-0 only and submit a round.
 *   2. Rewrite b-0 (asked) and b-1 (swept), leave b-2 alone, then ack.
 *   3. The bar reads "2 sections changed - 1 you marked, 1 by the coherence
 *      sweep"; b-0 carries "you asked", b-1 "sweep", b-2 nothing.
 *   4. The diff pane opens on toggle, names the version it changed from, and
 *      says outright when the user did not mark the section.
 *   5. The next round wipes bar, chips and panes, so no card carries
 *      attribution from two rounds ago.
 *   6. Block markdown that looks like HTML lands in the diff as text: no node
 *      is materialised and no handler fires.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/change-bar.e2e.cjs
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

function startServer() {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "cb-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-cb", title: "cb", blocks }));
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "cb-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir, eventsDir = sess.events_dir, consumedDir = sess.consumed_dir;
    // Keep the watcher alive or the client declares the session dead.
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(responseDir, [
      { id: "b-0", markdown: "The quick brown fox jumps over the lazy dog." },
      { id: "b-1", markdown: "A second paragraph that nobody marked at all." },
      { id: "b-2", markdown: "A third paragraph that will not move." },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-2"]', { timeout: 8000 });
    log("✓ blocks rendered");

    // Mark b-0 only, then submit the round.
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="keep"]').click();
    await page.locator("#round-submit").click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    log("✓ round submitted, page busy");

    const submitted = await page.evaluate(() => window.AnnotateSubunits.submittedBlockIds());
    if (JSON.stringify(submitted) !== '["b-0"]') fail("submittedBlockIds = " + JSON.stringify(submitted));
    if (!fs.existsSync(path.join(responseDir, "blocks.prev.json"))) fail("no blocks.prev.json snapshot");
    log("✓ submittedBlockIds=" + JSON.stringify(submitted) + ", snapshot written");

    // Claude: rewrites the marked b-0 AND sweeps the unmarked b-1. b-2 untouched.
    const eventId = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"))[0].replace(/\.json$/, "");
    writeBlocks(responseDir, [
      { id: "b-0", markdown: "The quick red fox leaps over the lazy dog." },
      { id: "b-1", markdown: "A second paragraph that nobody marked whatsoever." },
      { id: "b-2", markdown: "A third paragraph that will not move." },
    ]);
    fs.writeFileSync(path.join(consumedDir, eventId + ".ack"), "");

    await page.waitForSelector("#change-bar", { timeout: 10000 });
    const barText = (await page.locator("#change-bar").innerText()).replace(/\s+/g, " ");
    log("  bar: " + JSON.stringify(barText));
    for (const needle of ["2 sections changed", "1 you marked", "1 by the coherence sweep"]) {
      if (!barText.includes(needle)) fail("bar missing " + JSON.stringify(needle));
    }
    log("✓ change bar splits asked from swept");

    const youChip = await page.locator('section.block[data-block-id="b-0"] .attr-chip').innerText();
    const sweepChip = await page.locator('section.block[data-block-id="b-1"] .attr-chip').innerText();
    const untouched = await page.locator('section.block[data-block-id="b-2"] .attr-chip').count();
    if (youChip.trim() !== "you asked") fail("b-0 chip = " + youChip);
    if (sweepChip.trim() !== "sweep") fail("b-1 chip = " + sweepChip);
    if (untouched !== 0) fail("b-2 got a chip but never moved");
    log("✓ chips: b-0=you asked, b-1=sweep, b-2=none");

    // Diff pane is hidden until the toggle is pressed.
    const paneVisibleBefore = await page.locator('section.block[data-block-id="b-1"] .diff-pane').isVisible();
    if (paneVisibleBefore) fail("diff pane visible before toggle");
    await page.locator('section.block[data-block-id="b-1"] .card-diff-toggle').click();
    await page.waitForSelector('section.block[data-block-id="b-1"] .diff-pane', { state: "visible", timeout: 3000 });
    const h = await page.locator('section.block[data-block-id="b-1"] .diff-h').innerText();
    if (!/changed from v1/i.test(h) || !/did not mark/i.test(h)) fail("sweep diff heading = " + h);
    // The pane holds BOTH views and shows one, so every query below is scoped
    // to the visible tree. Querying the pane as a whole double-counts.
    const b1pane = page.locator('section.block[data-block-id="b-1"] .diff-pane');
    if (await b1pane.getAttribute("data-view") !== "reader") fail("reader is not the default view");

    // Reader: the new wording reads as prose, the removed wording is folded
    // into a chip rather than braided into the sentence.
    const readerText = (await b1pane.locator(".d-reader").innerText()).trim();
    if (!/whatsoever\./.test(readerText)) fail("reader view omits the new wording: " + readerText);
    if (/at all\./.test(readerText)) fail("reader view shows the old wording inline: " + readerText);
    const rIns = (await b1pane.locator(".d-reader ins").allInnerTexts()).join("").trim();
    if (!/whatsoever\./.test(rIns)) fail("reader marked the wrong span as added: " + rIns);
    const chip = b1pane.locator(".d-reader .d-cut");
    if (await chip.count() !== 1) fail("expected one cut chip, got " + await chip.count());
    if (!/at all\./.test(await chip.getAttribute("data-cut"))) fail("the cut chip does not carry what was cut");

    // Clicking the chip opens the cut text in place — nothing is unreachable,
    // it is one click away.
    await chip.click();
    const opened = (await b1pane.locator(".d-reader .d-cut-open").allInnerTexts()).join("").trim();
    if (!/at all\./.test(opened)) fail("clicking the chip did not reveal the cut text: " + opened);
    log("✓ reader view: additions tinted, deletion folded into a chip that opens");

    // Diff: both sides on show, in one row.
    await b1pane.locator('.diff-view-btn[data-view="diff"]').click();
    if (await b1pane.getAttribute("data-view") !== "diff") fail("the view switch did not change the view");
    if (await b1pane.locator(".d-reader").isVisible()) fail("reader tree still visible in diff view");
    const uDel = (await b1pane.locator(".d-uni del").allInnerTexts()).join("").trim();
    const uIns = (await b1pane.locator(".d-uni ins").allInnerTexts()).join("").trim();
    if (!/at all\./.test(uDel) || !/whatsoever\./.test(uIns)) fail("diff runs del=" + uDel + " ins=" + uIns);
    log("✓ diff view: del=" + JSON.stringify(uDel) + " ins=" + JSON.stringify(uIns));

    // The choice is a document-wide preference, not a per-card accident: a
    // reader who switched once should not switch again on the next card.
    const b0pane = page.locator('section.block[data-block-id="b-0"] .diff-pane');
    if (await b0pane.getAttribute("data-view") !== "diff") fail("the view choice did not carry to other panes");
    log("✓ the view choice applies to every pane at once");
    await b1pane.locator('.diff-view-btn[data-view="reader"]').click();

    // The toggle is a toggle: a second click closes the pane again.
    const t1 = page.locator('section.block[data-block-id="b-1"] .card-diff-toggle');
    if (await t1.getAttribute("aria-pressed") !== "true") fail("toggle not pressed while open");
    await t1.click();
    await page.waitForSelector('section.block[data-block-id="b-1"] .diff-pane', { state: "hidden", timeout: 3000 });
    if (await t1.getAttribute("aria-pressed") !== "false") fail("toggle still pressed after closing");
    log("✓ second click closes the pane and releases the toggle");

    // The block the user DID mark is not labelled as swept.
    await page.locator('section.block[data-block-id="b-0"] .card-diff-toggle').click();
    const b0h = await page.locator('section.block[data-block-id="b-0"] .diff-h').innerText();
    if (/did not mark/i.test(b0h)) fail("b-0 heading claims it was unmarked");
    log("✓ b-0 heading: " + JSON.stringify(b0h));

    // A second round wipes the previous verdict.
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="keep"]').click();
    await page.locator("#round-submit").click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    await page.waitForSelector("#change-bar", { state: "detached", timeout: 5000 });
    const staleChips = await page.locator(".attr-chip").count();
    const stalePanes = await page.locator(".diff-pane").count();
    if (staleChips || stalePanes) fail(`stale attribution survived: ${staleChips} chips, ${stalePanes} panes`);
    log("✓ next round clears the bar, chips and panes");

    // XSS guard: markdown that looks like HTML must land in the pane as text,
    // not as nodes. Sweep b-2 into markup with an inline event handler.
    const acked = new Set(fs.readdirSync(consumedDir).map(f => f.replace(/\.ack$/, "")));
    const eid2 = fs.readdirSync(eventsDir).map(f => f.replace(/\.json$/, "")).filter(id => !acked.has(id))[0];
    if (!eid2) fail("no unacked event for round 2");
    writeBlocks(responseDir, [
      { id: "b-0", markdown: "The quick red fox leaps over the lazy dog." },
      { id: "b-1", markdown: "A second paragraph that nobody marked whatsoever." },
      { id: "b-2", markdown: 'A third paragraph <img src=x onerror="window.__pwned=1"> moved.',
        change_note: "Why: you asked what moved here.\nLost: the original phrasing." },
    ]);
    fs.writeFileSync(path.join(consumedDir, eid2 + ".ack"), "");
    await page.waitForSelector('section.block[data-block-id="b-2"] .card-diff-toggle', { timeout: 10000 });
    await page.locator('section.block[data-block-id="b-2"] .card-diff-toggle').click();
    const b2pane = page.locator('section.block[data-block-id="b-2"] .diff-pane');
    // The note explains the marks, so it sits ABOVE them. Below the diff it is
    // the last thing you reach, and on a compact the Lost: line is the only
    // record of what was discarded.
    const notePos = await b2pane.evaluate((el) => {
      const why = el.querySelector(".diff-why");
      const body = el.querySelector(".d-reader, .d-uni");
      if (!why) return "missing";
      if (!body) return "no-body";
      return (why.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING) ? "above" : "below";
    });
    if (notePos !== "above") fail("change note is " + notePos + ", must be above the diff");
    const lost = await b2pane.locator(".diff-lost").count();
    if (lost !== 1) fail("the Lost: line has no distinguishing class");
    log("✓ change note sits above the diff, Lost: line marked");
    const paneHTML = await b2pane.innerHTML();
    if (/<img/i.test(paneHTML)) fail("diff pane materialised an <img> node from block text");
    const pwned = await page.evaluate(() => window.__pwned);
    if (pwned) fail("onerror fired from diff pane");
    log("✓ diff pane renders markup as text, no injected nodes");

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
