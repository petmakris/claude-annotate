#!/usr/bin/env node
/*
 * Playwright end-to-end for the pflow source pane on a flowchart block.
 *
 * The point of the pane is that a comment on a picture becomes an edit to a
 * line, so the things worth proving in a real browser are the ones that only
 * exist once both views are on the page together:
 *
 *   1. A flowchart authored as `spec.source` renders the chart AND the source,
 *      with one gutter number per line.
 *   2. Only lines that produced a node are live; the blank lines are inert.
 *   3. Clicking a source line opens a comment scoped to that line's node id —
 *      the same annotation clicking the node produces.
 *   4. Hovering either view lights both, because the id is on both.
 *   5. An in-place block update repaints chart and pane together. (Before this
 *      feature, updating a flowchart in place rendered its absent markdown and
 *      blanked the chart.)
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/pflow.e2e.cjs
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

const SOURCE = [
  '"""How a request becomes evidence."""',
  "",
  "",
  "def atlas(request):  # ! request R",
  "    scenarios = catalog()  # cache: e2e corpus",
  "    if covered(scenarios):  # ? one scenario covers all?",
  "        return PathB()",
  "    raise Decline()  # gate: honesty is enforced here",
  "",
].join("\n");

const SOURCE_V2 = SOURCE.replace("raise Decline()", "raise Refuse()");

function startServer() {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "pf-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-pf", title: "pf", blocks }));
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "pf-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(sess.response_dir, [
      { id: "b-0", kind: "flowchart", spec: { source: SOURCE } },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    const block = page.locator('section.block[data-block-id="b-0"]');
    await block.locator("svg.annotate-flow").waitFor({ timeout: 8000 });
    await block.locator(".pflow").waitFor({ timeout: 8000 });
    log("✓ chart and source pane both rendered");

    // 1. one gutter number per source line
    const lineCount = SOURCE.replace(/\n+$/, "").split("\n").length;
    const rows = await block.locator(".pflow-row").count();
    if (rows !== lineCount) fail(`${rows} rows != ${lineCount} source lines`);
    const nums = await block.locator(".pflow-num").allTextContents();
    if (nums.join(",") !== [...Array(lineCount)].map((_, i) => i + 1).join(","))
      fail("gutter numbers are not 1..N: " + nums.join(","));
    log(`✓ ${lineCount} rows, numbered 1..${lineCount}`);

    // the number and its code share a row, so they cannot drift apart
    const defRow = block.locator('.pflow-row[data-node-id="request-r"]');
    if ((await defRow.locator(".pflow-num").textContent()).trim() !== "4")
      fail("the def row is not numbered 4");
    if (!(await defRow.locator(".pflow-line").textContent()).includes("def atlas"))
      fail("row 4 does not hold the def");
    log("✓ row 4 holds both the number 4 and the def line");

    // 2. only the lines that produced a node are live
    const live = await block.locator(".pflow-row.is-live").count();
    const nodes = await block.locator("svg.annotate-flow g.node[data-node-id]").count();
    if (live !== nodes) fail(`${live} live lines but ${nodes} nodes`);
    if (live !== 5) fail(`expected 5 live lines (def/catalog/if/return/raise), got ${live}`);
    log(`✓ ${live} live lines, one per node; the rest inert`);

    // 3. the tags got their own colour, so the side-channel reads as one
    if (await block.locator(".pflow-tag").count() < 4) fail("pflow tags were not re-marked");
    log("✓ cache/gate/entry/decision tags marked");

    // 4. hovering a source line lights the matching node, and vice versa
    const declineLine = block.locator('.pflow-row[data-node-id="decline"]');
    await declineLine.hover();
    if (await block.locator('g.node[data-node-id="decline"].is-node-active').count() !== 1) {
      fail("hovering the source line did not light the node");
    }
    await block.locator('g.node[data-node-id="catalog"]').hover();
    if (await block.locator('.pflow-row[data-node-id="catalog"].is-node-active').count() !== 1) {
      fail("hovering the node did not light the source line");
    }
    if (await block.locator('.is-node-active').count() !== 2) {
      fail("the previous highlight was not cleared");
    }
    log("✓ hover links the two views both ways");

    // 5. clicking a source line opens a comment scoped to that line's node
    await declineLine.click();
    await page.waitForSelector(".comment-card textarea", { timeout: 5000 });
    const scoped = await page.evaluate(() =>
      [...document.querySelectorAll(".card-step-chip")].map((e) => e.textContent.trim()));
    if (!scoped.includes("decline")) fail("comment not scoped to the node: " + JSON.stringify(scoped));
    log("✓ a click on a line comments on that line's step");

    // 6. the whole loop: that comment goes back, Claude edits the line it named,
    //    and the block repaints. This is the feature in one move.
    await page.fill(".comment-card textarea", "call it Refuse, not Decline");
    await page.click(".comment-card .card-submit-btn");      // "Add to round"
    await page.click("#round-submit");
    await page.waitForSelector(".busy-banner", { timeout: 8000 });
    log("✓ the line comment submitted a round");

    const eventFiles = fs.readdirSync(sess.events_dir).filter((f) => f.endsWith(".json"));
    if (!eventFiles.length) fail("no event written for the line comment");
    const eventId = eventFiles[0].replace(/\.json$/, "");
    const event = JSON.parse(fs.readFileSync(path.join(sess.events_dir, eventFiles[0]), "utf8"));
    const carried = JSON.stringify(event).includes('"decline"');
    if (!carried) fail("the event did not carry the node id: " + JSON.stringify(event).slice(0, 300));
    log("✓ the event carries the step id Claude needs to find the line");

    writeBlocks(sess.response_dir, [
      { id: "b-0", kind: "flowchart", spec: { source: SOURCE_V2 } },
    ]);
    fs.writeFileSync(path.join(sess.consumed_dir, eventId + ".ack"), "");

    await page.waitForFunction(() => {
      const b = document.querySelector('section.block[data-block-id="b-0"]');
      return b && b.querySelector('.pflow-row[data-node-id="refuse"]');
    }, { timeout: 15000 });
    const stillThere = await block.locator("svg.annotate-flow g.node").count();
    if (stillThere < 5) fail("the chart did not survive the in-place update");
    if (await block.locator(".pflow").count() !== 1) fail("the source pane did not survive the update");
    if (await block.locator('g.node[data-node-id="refuse"]').count() !== 1) {
      fail("the chart was not recompiled from the edited source");
    }
    log("✓ the rewrite repaints chart and pane together, recompiled from the new source");

    clearInterval(beat);
    log("\nALL PFLOW E2E ASSERTIONS PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\n" + err.message);
    cleanup();
    process.exit(1);
  }
})();
