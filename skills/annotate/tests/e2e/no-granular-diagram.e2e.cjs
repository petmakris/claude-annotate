#!/usr/bin/env node
/*
 * Playwright end-to-end for ONE rule: a picture and a table are commented as a
 * whole, from the card header — never per node, per row, or per source line.
 *
 * Why the rule exists. A flowchart node's `ref` line is painted accent-coloured
 * and underlined whether or not the spec gave it an `href` (see
 * `.annotate-flow .flow-ref` in diagram.css). So a node that carries a file
 * reference with no href LOOKS like a jump-to-source link and behaves like a
 * comment target: the click misses the (absent) anchor and lands on the node
 * click handler, which opens the comment composer. The user reaches for a file
 * and gets an editor. The same accident had no equivalent on tables — there a
 * row simply was its own unit — but the fix is the same shape: the granular
 * scope goes away and the header keeps the whole-block one.
 *
 * Everything here is asserted against a rendered page driven through the real
 * UI. The suite's source-string smoke tests cannot see any of it: they pass
 * happily while a click still opens an editor.
 *
 *   1. Clicking a flowchart node's shape opens no comment editor.
 *   2. Clicking a node's `ref` line — the underlined pseudo-link that started
 *      this — opens no comment editor either.
 *   3. Clicking a pflow source line opens no comment editor.
 *   4. Clicking a sequence step row opens no comment editor.
 *   5. A table row is not a sub-unit and carries no unit strip.
 *   6. Paragraphs and list items ARE still sub-units — the granular scope is
 *      withdrawn from pictures and tables, not from prose.
 *   7. The card header still opens a WHOLE-BLOCK comment on a picture (no
 *      step chip on the card) — that is the one remaining way in.
 *   8. A real in-page anchor inside a flowchart still navigates instead of
 *      opening an editor.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/no-granular-diagram.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "ng-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-ng", title: "ng", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}

// A flowchart shaped like the one that reported the bug: refs that read as
// file links, one of them WITHOUT an href (node "c"), one WITH an in-page one
// (node "b").
const FLOW_SPEC = {
  title: "One executeTasks call, start to finish",
  nodes: [
    { id: "a", role: "entry", label: "Advisor presses a task",
      sub: "Save, Share, Accept, Discard…" },
    { id: "b", role: "code", ref: "InternalProposalTaskService:131",
      method: "executeTasks(task, proposal, …)", href: "#b-md" },
    { id: "c", role: "code", ref: "LifecycleActionsExecutor:105",
      method: "generatedInitialExecutionData(...)",
      sub: "proposal, flags, user, start timestamp" },
    { id: "d", role: "decision", label: "any action throws?" },
    { id: "e", role: "error", label: "Nothing is committed" },
    { id: "f", role: "success", label: "Status transition" },
  ],
  edges: [
    { from: "a", to: "b" }, { from: "b", to: "c" }, { from: "c", to: "d" },
    { from: "d", to: "e", label: "yes" }, { from: "d", to: "f", label: "no" },
  ],
};

// Same source the pflow e2e uses, so the pane renders with live lines.
const PFLOW_SOURCE = [
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

const SEQ_SPEC = {
  actors: [{ id: "ui", label: "Advisor UI" }, { id: "svc", label: "Task service" }],
  steps: [
    { id: "s1", from: "ui", to: "svc", arrow: "request", label: "executeTasks" },
    { id: "s2", from: "svc", to: "ui", arrow: "event", label: "status transition" },
  ],
};

const TABLE_MD = [
  "A paragraph that stays a sub-unit, because prose is not a picture.",
  "",
  "| Bank | Sends proposals |",
  "| --- | --- |",
  "| JPM | yes |",
  "| UBS | no |",
  "",
  "- and a bullet, also still a sub-unit",
].join("\n");

// Filler so the document is taller than the viewport and an in-page anchor
// has somewhere to scroll to.
const FILLER = Array.from({ length: 10 }, (_, i) => ({
  id: `b-fill-${i}`,
  title: `Filler ${i}`,
  markdown: `Paragraph ${i}. `.repeat(30),
}));

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  const cleanup = () => {
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "ng-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir;
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(responseDir, [
      { id: "b-flow", title: "One executeTasks call, start to finish",
        kind: "flowchart", spec: FLOW_SPEC },
      { id: "b-pflow", title: "Authored as pflow", kind: "flowchart",
        spec: { source: PFLOW_SOURCE } },
      { id: "b-seq", title: "The failure, step by step", kind: "sequence", spec: SEQ_SPEC },
      ...FILLER,
      { id: "b-md", title: "Which bank gets what", markdown: TABLE_MD },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-md"]', { timeout: 8000 });
    log("✓ blocks rendered");

    const cards = () => page.locator(".comment-card").count();
    // Every "no editor" assertion below runs through this, so a failure names
    // the gesture that opened one instead of a bare count.
    async function clickOpensNoEditor(what, locator) {
      const before = await cards();
      if (before) fail(`an editor was already open before ${what}`);
      await locator.click({ force: true });
      await sleep(300);
      const after = await cards();
      if (after) {
        // Leave the page clean for the next assertion so one failure does not
        // cascade into "single-flight refused" noise on every later click.
        await page.locator(".comment-card .card-close").first().click();
        fail(`${what} opened a comment editor`);
      }
      log(`✓ ${what} opened nothing`);
    }

    const flow = page.locator('section.block[data-block-id="b-flow"]');
    await flow.locator('g.node[data-node-id="c"] .node-shape').waitFor({ timeout: 8000 });

    // ── 1. the node body ────────────────────────────────────────────────────
    await clickOpensNoEditor("clicking a flowchart node shape",
      flow.locator('g.node[data-node-id="c"] .node-shape'));

    // ── 2. the underlined ref that started this ─────────────────────────────
    const bareRef = flow.locator('g.node[data-node-id="c"] text.flow-ref');
    if (!(await bareRef.count())) fail("node c has no .flow-ref line to click");
    if (await flow.locator('g.node[data-node-id="c"] a').count())
      fail("node c was supposed to have NO href — the fixture is wrong");
    await clickOpensNoEditor("clicking an href-less ref line", bareRef);

    // ── 3. the pflow source pane ────────────────────────────────────────────
    const pflow = page.locator('section.block[data-block-id="b-pflow"]');
    const liveRow = pflow.locator(".pflow-row.is-live").first();
    if (!(await pflow.locator(".pflow-row.is-live").count()))
      fail("the pflow pane rendered no live rows — the fixture is wrong");
    await clickOpensNoEditor("clicking a pflow source line", liveRow);

    // ── 4. a sequence step row ──────────────────────────────────────────────
    const seq = page.locator('section.block[data-block-id="b-seq"]');
    const stepRow = seq.locator("g.step-row").first();
    if (!(await seq.locator("g.step-row").count()))
      fail("the sequence diagram rendered no step rows — the fixture is wrong");
    await clickOpensNoEditor("clicking a sequence step row", stepRow);

    // ── 5. table rows are not units ─────────────────────────────────────────
    const md = page.locator('section.block[data-block-id="b-md"]');
    const rowUnits = await md.locator("table tbody tr.sub-unit").count();
    if (rowUnits) fail(`${rowUnits} table row(s) are still sub-units`);
    const rowStrips = await md.locator("table tbody tr .unit-strip").count();
    if (rowStrips) fail(`${rowStrips} table row(s) still carry a unit strip`);
    log("✓ table rows are neither sub-units nor strip carriers");

    // ── 6. prose keeps its granular scope ───────────────────────────────────
    const paraUnits = await md.locator("p.sub-unit").count();
    const liUnits = await md.locator("li.sub-unit").count();
    if (!paraUnits) fail("paragraphs stopped being sub-units — too much was removed");
    if (!liUnits) fail("list items stopped being sub-units — too much was removed");
    log(`✓ prose still granular: ${paraUnits} paragraph(s), ${liUnits} bullet(s)`);

    // ── 7. the header is the way in, and it is whole-block ──────────────────
    await flow.locator(".card-head").hover();
    await flow.locator('.hover-actions button[data-type="comment"]').click();
    await page.waitForSelector(".comment-card textarea", { timeout: 5000 });
    if (await page.locator(".comment-card .card-step-chip").count())
      fail("the header comment came out scoped to a step, not the whole block");
    log("✓ header comment on a picture is whole-block");
    await page.locator(".comment-card .card-close").click();
    await page.waitForSelector(".comment-card", { state: "detached", timeout: 5000 });

    // ── 8. a real in-page anchor still navigates ────────────────────────────
    const anchor = flow.locator('g.node[data-node-id="b"] a');
    if (!(await anchor.count())) fail("node b lost its href — the fixture is wrong");
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(200);
    await anchor.click({ force: true });
    await sleep(1200);
    if (await cards()) fail("following an in-page anchor also opened an editor");
    const scrolled = await page.evaluate(() => window.scrollY);
    if (scrolled <= 0) fail("the in-page anchor no longer scrolls to its target");
    log(`✓ in-page anchor still navigates (scrollY=${Math.round(scrolled)})`);

    // ── 9. a ref that is not a link must not be painted as one ──────────────
    // The other half of the same root cause. Withdrawing the node click stops
    // the wrong thing happening; this stops the wrong thing being PROMISED.
    // An accent-coloured underlined ref that goes nowhere is still a lie, and
    // the reader still reaches for it.
    const refStyle = (nodeId) => flow
      .locator(`g.node[data-node-id="${nodeId}"] text.flow-ref`)
      .evaluate((el) => {
        const cs = getComputedStyle(el);
        return { deco: cs.textDecorationLine, fill: cs.fill };
      });
    const linked = await refStyle("b");     // has href="#b-md"
    const bare = await refStyle("c");       // has no href at all
    if (!/underline/.test(linked.deco))
      fail(`a ref that IS a link lost its underline: ${JSON.stringify(linked)}`);
    if (/underline/.test(bare.deco))
      fail(`a ref with no href is still underlined: ${JSON.stringify(bare)}`);
    if (bare.fill === linked.fill)
      fail(`a ref with no href still paints as accent: ${JSON.stringify(bare)}`);
    log(`✓ only a real link is painted as one (linked=${linked.fill}, bare=${bare.fill})`);

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
