#!/usr/bin/env node
/*
 * Playwright end-to-end for the maximize control.
 *
 * The rule it guards, and why it needs a real browser. Maximize promotes a
 * picture block to viewport width. The obvious implementations both corrupt the
 * document and neither can be seen from the source:
 *
 *   - CLONING the card gives two live nodes carrying the same `data-block-id`,
 *     which every engaged-state and card-focus selector in script.js keys off.
 *   - MOVING the card into an overlay host is worse: script.js's render loop
 *     finds the block missing from main.prose and paints a replacement. Measured
 *     on the first build of this feature, the block was listed twice within
 *     50ms, and closing put the moved copy back beside the replacement.
 *
 * So the card is promoted IN PLACE with position:fixed and never leaves its
 * parent. Assertion 3 is the one that catches a regression to either design,
 * and it deliberately waits out a full poll cycle — the duplicate did not exist
 * synchronously.
 *
 *   1. Picture blocks get a maximize button; markdown blocks do not.
 *   2. Clicking it promotes the card to the viewport and widens the content box.
 *   3. The block is NOT duplicated or moved — through a live poll cycle.
 *   4. Esc, the bar's close button and the header toggle all restore, leaving
 *      block order byte-identical and no maximized node behind. (The scrim is
 *      background paint, not a close target: the card is inset by 16px, so a
 *      scrim click is a hairline frame nobody can hit deliberately.)
 *   5. "Fit width" makes the picture exactly fit its content box — no residual
 *      scroll, and no band of empty card below it.
 *   6. Fit round-trips: back to 1:1 is the authored width, and re-fitting does
 *      not compound the scale.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/maximize.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "mx-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-mx", title: "mx", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}

// Twelve actors, so the rendered SVG is far wider than the reading column and
// wider than the viewport too — which is what makes "Fit width" measurable.
const WIDE_SPEC = {
  title: "A trace wide enough to need the whole screen",
  actors: [
    { id: "br", label: "Browser", tone: "edge" },
    { id: "gw", label: "Kong gateway", tone: "edge" },
    { id: "ctl", label: "ProposalListController", tone: "internal" },
    { id: "task", label: "InternalProposalTaskService", tone: "internal" },
    { id: "batch", label: "EnrichedProposalBatchService", tone: "internal" },
    { id: "orders", label: "ProposedOrdersService", tone: "internal" },
    { id: "checkup", label: "PortfolioCheckupFactory", tone: "internal" },
    { id: "enrich", label: "EnrichedProposalService", tone: "internal" },
    { id: "integ", label: "Integration Layer", tone: "cheap" },
    { id: "morph", label: "Morpheus", tone: "service" },
    { id: "bps", label: "BPS", tone: "service" },
    { id: "rules", label: "Rule Engine", tone: "cheap" },
  ],
  legend: [{ tone: "service", label: "crosses the gateway — expensive" }],
  steps: [
    { id: "s1", from: "br", to: "gw", arrow: "request", tone: "edge", label: "PUT /completion" },
    { id: "s2", from: "gw", to: "ctl", arrow: "request", tone: "edge", label: "forward" },
    { id: "s3", from: "ctl", to: "enrich", arrow: "band", tone: "internal", label: "pre-processing" },
    { id: "s4", from: "ctl", to: "task", arrow: "request", label: "completeTask(taskId, parameters)" },
    { id: "s5", from: "task", to: "task", arrow: "self", label: "fastLifecycleData()" },
    { id: "s6", from: "orders", to: "morph", arrow: "request", tone: "service",
      label: "portfolioSimulationService.simulate(scenario, riskRequest, strategy)",
      sub: "Morpheus simulation #1", note: "581 ms · gateway 56 ms" },
    { id: "s7", from: "checkup", to: "bps", arrow: "request", tone: "service",
      label: "bpsQueryService.getUniversesByAssetIds(positionAssetIds)",
      note: "750 ms · gateway 8 ms" },
    { id: "s8", from: "gw", to: "br", arrow: "event", tone: "edge", label: "200 OK",
      note: "7,866 ms total" },
  ],
};

const NARROW_SPEC = {
  title: "A narrow one",
  actors: [{ id: "a", label: "UI" }, { id: "b", label: "API" }],
  steps: [{ id: "s1", from: "a", to: "b", arrow: "request", label: "call" }],
};

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  const cleanup = () => {
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "mx-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(sess.response_dir, [
      { id: "b-intro", title: "Intro", markdown: "Prose gets no maximize button." },
      { id: "b-wide", title: "Wide trace", kind: "sequence", spec: WIDE_SPEC },
      { id: "b-mid", title: "Between", markdown: "More prose between the pictures." },
      { id: "b-narrow", title: "Narrow trace", kind: "sequence", spec: NARROW_SPEC },
      { id: "b-outro", title: "Outro", markdown: "And prose at the end." },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-outro"]', { timeout: 8000 });
    await page.waitForSelector('section.block[data-block-id="b-wide"] .max-toggle', { timeout: 8000 });
    log("✓ blocks rendered");

    const order = () => page.evaluate(() =>
      [...document.querySelectorAll("main.prose section.block")].map(s => s.dataset.blockId));
    const baseline = await order();

    // ── 1. only picture blocks carry the control ────────────────────────────
    const buttons = await page.evaluate(() => {
      const out = {};
      document.querySelectorAll("section.block[data-kind]").forEach((s) => {
        out[s.dataset.blockId] = !!s.querySelector(".max-toggle");
      });
      return out;
    });
    for (const [id, has] of Object.entries(buttons)) {
      const wantsIt = id === "b-wide" || id === "b-narrow";
      if (has !== wantsIt) fail(`${id}: maximize button present=${has}, expected ${wantsIt}`);
    }
    // The control is not hover-gated: it is a view control, and one you cannot
    // see is one nobody uses.
    const vis = await page.locator('section.block[data-block-id="b-wide"] .max-toggle')
      .evaluate(el => ({ opacity: getComputedStyle(el).opacity, w: el.getBoundingClientRect().width }));
    if (Number(vis.opacity) < 1 || vis.w < 10) fail(`the button is not visible at rest: ${JSON.stringify(vis)}`);
    log("✓ pictures get a visible button, prose gets none");

    const toggle = page.locator('section.block[data-block-id="b-wide"] .max-toggle');
    const geom = () => page.evaluate(() => {
      const sec = document.querySelector('section.block[data-block-id="b-wide"]');
      const host = sec.querySelector(".block-content");
      const svg = host.querySelector("svg");
      const r = svg.getBoundingClientRect();
      return {
        maximized: sec.classList.contains("is-maximized"),
        hostW: host.clientWidth,
        svgW: Math.round(r.width),
        svgH: Math.round(r.height),
        boxH: Math.round(host.getBoundingClientRect().height),
        scrolls: host.scrollWidth > host.clientWidth + 1,
        position: getComputedStyle(sec).position,
      };
    });

    const before = await geom();
    if (before.maximized) fail("block started out maximized");

    // ── 2. it promotes and widens ───────────────────────────────────────────
    await toggle.click();
    await sleep(250);
    const opened = await geom();
    if (!opened.maximized) fail("clicking the button did not maximize the block");
    if (opened.position !== "fixed") fail(`maximized card is position:${opened.position}, expected fixed`);
    if (!(opened.hostW > before.hostW + 200))
      fail(`maximizing barely widened the content box: ${before.hostW} → ${opened.hostW}`);
    log(`✓ maximizes and widens the content box (${before.hostW} → ${opened.hostW}px)`);

    // ── 3. the block is neither duplicated nor moved ────────────────────────
    // Waits out a poll cycle on purpose: the duplicate a move-based build
    // produced did not exist synchronously.
    await sleep(3000);
    const dupCheck = await page.evaluate(() => {
      const ids = [...document.querySelectorAll("main.prose section.block")].map(s => s.dataset.blockId);
      const seen = {};
      ids.forEach(id => { seen[id] = (seen[id] || 0) + 1; });
      return {
        ids,
        dupes: Object.entries(seen).filter(([, n]) => n > 1),
        outsideProse: document.querySelectorAll(
          "section.block:not(main.prose section.block)").length,
        stillMaximized: !!document.querySelector(
          'main.prose section.block.is-maximized[data-block-id="b-wide"]'),
      };
    });
    if (dupCheck.dupes.length)
      fail(`block duplicated while maximized: ${JSON.stringify(dupCheck.dupes)}`);
    if (dupCheck.outsideProse)
      fail(`${dupCheck.outsideProse} block(s) left main.prose — the card must be promoted in place`);
    if (JSON.stringify(dupCheck.ids) !== JSON.stringify(baseline))
      fail(`block order changed while maximized: ${JSON.stringify(dupCheck.ids)}`);
    if (!dupCheck.stillMaximized)
      fail("the block stopped being maximized after a poll cycle");
    log("✓ still exactly one node, in place, after a live poll cycle");

    // ── 5. fit width is exact ───────────────────────────────────────────────
    if (!opened.scrolls)
      fail("the wide diagram already fits — this test cannot measure Fit width");
    const fitBtn = page.locator(".max-bar .max-btn", { hasText: /Fit width|Actual size/ });
    await fitBtn.click();
    await sleep(250);
    const fitted = await geom();
    if (fitted.scrolls)
      fail(`after Fit width the picture still scrolls: svg ${fitted.svgW} vs host ${fitted.hostW}`);
    if (Math.abs(fitted.svgW - fitted.hostW) > 2)
      fail(`Fit width is not exact: svg ${fitted.svgW} vs host ${fitted.hostW}`);
    if (Math.abs(fitted.boxH - fitted.svgH) > 2)
      fail(`a transform-scaled picture left a ${fitted.boxH - fitted.svgH}px band of empty card below it`);
    log(`✓ Fit width is exact (${fitted.svgW}px into ${fitted.hostW}px) and leaves no gap`);

    // ── 6. and it round-trips without compounding ───────────────────────────
    await fitBtn.click(); await sleep(200);
    const back = await geom();
    if (back.svgW !== opened.svgW)
      fail(`Actual size did not return to the authored width: ${back.svgW} vs ${opened.svgW}`);
    await fitBtn.click(); await sleep(200);
    const refit = await geom();
    if (Math.abs(refit.svgW - refit.hostW) > 2)
      fail(`re-fitting compounded the scale: svg ${refit.svgW} vs host ${refit.hostW}`);
    await fitBtn.click(); await sleep(200);
    log("✓ Fit round-trips to the authored width and does not compound");

    // ── 4. every close path restores cleanly ────────────────────────────────
    async function assertRestored(how) {
      await sleep(300);
      const st = await page.evaluate(() => ({
        ids: [...document.querySelectorAll("main.prose section.block")].map(s => s.dataset.blockId),
        anyMaximized: !!document.querySelector(".is-maximized"),
        chromeHidden: document.querySelector(".max-chrome").hidden,
        bodyOverflow: getComputedStyle(document.body).overflow,
        position: getComputedStyle(
          document.querySelector('section.block[data-block-id="b-wide"]')).position,
      }));
      if (st.anyMaximized) fail(`${how}: a block is still maximized`);
      if (!st.chromeHidden) fail(`${how}: the overlay chrome is still showing`);
      if (st.bodyOverflow === "hidden") fail(`${how}: the page is still scroll-locked`);
      if (st.position === "fixed") fail(`${how}: the card is still position:fixed`);
      if (JSON.stringify(st.ids) !== JSON.stringify(baseline))
        fail(`${how}: block order changed — ${JSON.stringify(st.ids)}`);
      log(`✓ ${how} restores the page exactly`);
    }

    await page.keyboard.press("Escape");
    await assertRestored("Esc");

    await toggle.click(); await sleep(250);
    await page.locator(".max-bar .max-close").click();
    await assertRestored("the close button");

    await toggle.click(); await sleep(250);
    await toggle.click();
    await assertRestored("the button again");

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
