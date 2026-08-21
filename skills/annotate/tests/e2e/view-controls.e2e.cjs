#!/usr/bin/env node
/*
 * Playwright end-to-end for the two page-wide view controls in the top bar:
 * the container-width cycler and the code-layout toggle.
 *
 * Both are pure view preferences — they change how the reader sees the
 * document, never what it says — which is why they stay live on the
 * read-only share link, and why the author's choice rides along into an
 * export instead of being reset to the default.
 *
 * The claims here cannot be made by reading source:
 *
 *   - `body[data-has-code="1"]` and `body[data-width="normal"]` are BOTH
 *     specificity (0,1,1). Which one paints is decided by source order
 *     alone. So "picking Normal on a document that cites code actually
 *     narrows it" is a fact about the computed value, and an innocent
 *     reordering of style.css breaks it silently. Item 3 measures it.
 *   - the layout toggle promoting every pane is a fact about each card's
 *     computed grid, not about a class name;
 *   - and the per-block promotions a reader made must SURVIVE a trip
 *     through the global wide mode and back, because the global mode is a
 *     body attribute rather than a rewrite of per-block state. Item 6
 *     round-trips it.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/view-controls.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "vc-e2e-home-"));
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
function writeBlocks(dir, responseId, title, blocks) {
  const tmp = path.join(dir, "blocks.json.tmp");
  fs.writeFileSync(tmp, JSON.stringify({ response_id: responseId, title, blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}
function keepAlive(stateDir) {
  const hb = path.join(stateDir, "watcher_heartbeat");
  const beat = () => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} };
  beat();
  return setInterval(beat, 500);
}

const CALC_LINES = [
  '"""Calculator utilities."""',
  "",
  "def add(a, b):",
  "    return a + b",
  "",
  "def multiply(a, b):",
  "    return a * b",
];
const SNIP_A = "return a + b";
const LINE_A = CALC_LINES.indexOf(`    ${SNIP_A}`) + 1;
const SNIP_B = "return a * b";
const LINE_B = CALC_LINES.indexOf(`    ${SNIP_B}`) + 1;
if (LINE_A < 1 || LINE_B < 1) throw new Error("fixture setup: snippets not found");

// The measurement every width claim rests on. --content-max is a custom
// property, so it is read off <body>'s computed style rather than from any
// element's width: an element could be narrower for unrelated reasons
// (a max-width elsewhere, a grid) and still leave the property correct.
const readWidth = (page) => page.evaluate(() => ({
  attr: document.body.dataset.width,
  contentMax: getComputedStyle(document.body).getPropertyValue("--content-max").trim(),
  proseWidth: Math.round(document.querySelector("main.prose").getBoundingClientRect().width),
}));

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  let beatA, beatB;
  const cleanup = () => {
    try { clearInterval(beatA); } catch (_) {}
    try { clearInterval(beatB); } catch (_) {}
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const projectA = fs.mkdtempSync(path.join(os.tmpdir(), "vc-e2e-proj-a-"));
    fs.mkdirSync(path.join(projectA, "lib"), { recursive: true });
    fs.writeFileSync(path.join(projectA, "lib", "calc.py"), CALC_LINES.join("\n") + "\n");
    const sessA = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: projectA })).body);
    beatA = keepAlive(sessA.state_dir);
    writeBlocks(sessA.response_dir, "resp-view-a", "View controls", [
      { id: "b-0", title: "First anchored block", markdown: "Cites add().",
        code: [{ file: "lib/calc.py", line: LINE_A, snippet: SNIP_A }] },
      { id: "b-1", title: "Second anchored block", markdown: "Cites multiply().",
        code: [{ file: "lib/calc.py", line: LINE_B, snippet: SNIP_B }] },
    ]);

    // A viewport wide enough that 1600px is reachable — otherwise "extra
    // wide" would be clamped by the window and the check would pass on a
    // width the control never actually produced.
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1800, height: 950 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sessA.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-1"] .cp-row', { timeout: 8000 });
    log("✓ workspace A rendered: two anchored blocks");

    // ── 1. Both controls are in the bar, and the default is unchanged ───────
    const initial = await page.evaluate(() => ({
      hasWidth: !!document.getElementById("width-toggle"),
      hasLayout: !!document.getElementById("codelayout-toggle"),
      layoutVisible: (() => {
        const el = document.getElementById("codelayout-toggle");
        return el ? getComputedStyle(el).display !== "none" : false;
      })(),
      width: document.body.dataset.width,
      layout: document.body.dataset.codeLayout,
      contentMax: getComputedStyle(document.body).getPropertyValue("--content-max").trim(),
    }));
    if (!initial.hasWidth) fail("no #width-toggle in the header");
    if (!initial.hasLayout) fail("no #codelayout-toggle in the header");
    if (!initial.layoutVisible) fail("#codelayout-toggle is hidden on a document that DOES cite code");
    // A document that cites code opens at the wide measure, exactly as it did
    // before these controls existed. The control names the state it is in; it
    // does not change it on arrival.
    if (initial.width !== "wide")
      fail(`a code-bearing document should open at 'wide', got '${initial.width}'`);
    if (initial.contentMax !== "1180px")
      fail(`default --content-max is ${initial.contentMax}, expected 1180px (unchanged behaviour)`);
    if (initial.layout !== "split")
      fail(`default code layout should be 'split', got '${initial.layout}'`);
    log(`✓ both controls present; document opens unchanged at ${initial.contentMax}, layout=${initial.layout}`);

    // ── 2. The width cycles, and each stop is the width it claims ───────────
    const seen = [];
    for (let i = 0; i < 3; i++) {
      await page.locator("#width-toggle").click();
      await page.waitForTimeout(80);
      seen.push(await readWidth(page));
    }
    const cycle = seen.map(s => `${s.attr}=${s.contentMax}`).join(" → ");
    const want = { normal: "1040px", wide: "1180px", extra: "1600px" };
    for (const s of seen) {
      if (want[s.attr] !== s.contentMax)
        fail(`--content-max for '${s.attr}' is ${s.contentMax}, expected ${want[s.attr]} (cycle: ${cycle})`);
    }
    if (new Set(seen.map(s => s.attr)).size !== 3)
      fail("three clicks did not visit three distinct widths: " + cycle);
    if (seen[2].attr !== "wide")
      fail(`three clicks from 'wide' should return to 'wide', ended at '${seen[2].attr}' (${cycle})`);
    log(`✓ width cycles through all three stops and back: ${cycle}`);

    // ── 3. Normal really narrows a code-bearing document ────────────────────
    // The trap this whole file exists for. `body[data-has-code="1"]` sets
    // 1180px and `body[data-width="normal"]` sets 1040px at the SAME
    // specificity (0,1,1) — source order is the only thing deciding which
    // wins. Reorder style.css and this silently stops working while every
    // source-level check still passes.
    while ((await readWidth(page)).attr !== "normal") {
      await page.locator("#width-toggle").click();
      await page.waitForTimeout(60);
    }
    const narrowed = await readWidth(page);
    if (narrowed.contentMax !== "1040px")
      fail(`'normal' on a code-bearing document computed ${narrowed.contentMax}, not 1040px — `
        + "body[data-has-code] is winning, which means the width rules sit ABOVE it in style.css");
    if (narrowed.proseWidth > 1040)
      fail(`main.prose is ${narrowed.proseWidth}px wide at 'normal' — the property is right but nothing uses it`);
    log(`✓ 'normal' overrides the code-document default: ${narrowed.contentMax}, prose ${narrowed.proseWidth}px`);

    // ── 4. Extra wide is genuinely wider, measured ──────────────────────────
    while ((await readWidth(page)).attr !== "extra") {
      await page.locator("#width-toggle").click();
      await page.waitForTimeout(60);
    }
    const extra = await readWidth(page);
    if (extra.proseWidth <= narrowed.proseWidth)
      fail(`'extra' rendered ${extra.proseWidth}px, no wider than 'normal' at ${narrowed.proseWidth}px`);
    log(`✓ 'extra' is really wider: ${extra.proseWidth}px vs ${narrowed.proseWidth}px at 'normal'`);

    // ── 5. The layout toggle promotes every pane ────────────────────────────
    const beforeToggle = await page.evaluate(() =>
      [...document.querySelectorAll('section.block.card[data-has-code="1"]')].map(s =>
        getComputedStyle(s.querySelector(".card-body")).gridTemplateColumns.split(" ").length));
    if (!beforeToggle.every(n => n === 2))
      fail("cards are not two-column before the toggle: " + JSON.stringify(beforeToggle));
    await page.locator("#codelayout-toggle").click();
    await page.waitForTimeout(120);
    const promoted = await page.evaluate(() => ({
      layout: document.body.dataset.codeLayout,
      pressed: document.getElementById("codelayout-toggle").getAttribute("aria-pressed"),
      columns: [...document.querySelectorAll('section.block.card[data-has-code="1"]')].map(s =>
        getComputedStyle(s.querySelector(".card-body")).gridTemplateColumns.split(" ").length),
      widenVisible: [...document.querySelectorAll(".cp-widen")]
        .filter(b => getComputedStyle(b).display !== "none").length,
    }));
    if (promoted.layout !== "wide") fail("the toggle did not set data-code-layout='wide'");
    if (promoted.pressed !== "true") fail("the toggle does not report aria-pressed='true' when engaged");
    if (!promoted.columns.every(n => n === 1))
      fail("not every card collapsed to one column in wide mode: " + JSON.stringify(promoted.columns));
    if (promoted.widenVisible !== 0)
      fail(`${promoted.widenVisible} per-pane widen button(s) still visible in wide mode — there is `
        + "nothing left for them to promote");
    log(`✓ wide mode: all ${promoted.columns.length} cards single-column, all widen buttons hidden`);

    // ── 6. A per-block promotion survives the round trip ────────────────────
    // The global mode is a body attribute, NOT a rewrite of each block's
    // stored state. If it were a rewrite, flipping to wide and back would
    // silently promote every block the reader had left alone.
    await page.locator("#codelayout-toggle").click();   // back to split
    await page.waitForTimeout(120);
    await page.locator('section.block[data-block-id="b-0"] .cp-widen').click();
    await page.waitForTimeout(120);
    const beforeRound = await page.evaluate(() => ({
      b0: document.querySelector('section.block[data-block-id="b-0"]').dataset.codeWide,
      b1: document.querySelector('section.block[data-block-id="b-1"]').dataset.codeWide,
    }));
    if (beforeRound.b0 !== "1" || beforeRound.b1 === "1")
      fail("setup for the round trip failed: " + JSON.stringify(beforeRound));
    await page.locator("#codelayout-toggle").click();   // wide
    await page.waitForTimeout(120);
    await page.locator("#codelayout-toggle").click();   // and back to split
    await page.waitForTimeout(120);
    const afterRound = await page.evaluate(() => ({
      layout: document.body.dataset.codeLayout,
      b0: document.querySelector('section.block[data-block-id="b-0"]').dataset.codeWide,
      b1: document.querySelector('section.block[data-block-id="b-1"]').dataset.codeWide,
    }));
    if (afterRound.layout !== "split") fail("did not return to split mode");
    if (afterRound.b0 !== "1")
      fail("b-0's own promotion was lost through the global wide mode: " + JSON.stringify(afterRound));
    if (afterRound.b1 === "1")
      fail("b-1 came back PROMOTED — the global mode overwrote per-block state instead of overriding it: "
        + JSON.stringify(afterRound));
    log("✓ per-block promotion survives a trip through wide mode; untouched blocks stay untouched");

    // ── 7. Both settings survive a reload ───────────────────────────────────
    while ((await readWidth(page)).attr !== "extra") {
      await page.locator("#width-toggle").click();
      await page.waitForTimeout(60);
    }
    await page.locator("#codelayout-toggle").click();
    await page.waitForTimeout(120);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-1"] .cp-row', { timeout: 8000 });
    await page.waitForTimeout(200);
    const persisted = await page.evaluate(() => ({
      width: document.body.dataset.width,
      layout: document.body.dataset.codeLayout,
      contentMax: getComputedStyle(document.body).getPropertyValue("--content-max").trim(),
      label: document.getElementById("width-toggle").textContent.trim(),
    }));
    if (persisted.width !== "extra" || persisted.contentMax !== "1600px")
      fail("the width did not survive reload: " + JSON.stringify(persisted));
    if (persisted.layout !== "wide")
      fail("the code layout did not survive reload: " + JSON.stringify(persisted));
    if (!/extra/i.test(persisted.label))
      fail(`the button label reads "${persisted.label}" after reload — it does not name the state it is in`);
    log(`✓ both settings survive reload (${persisted.contentMax}, ${persisted.layout}, button reads "${persisted.label}")`);

    // ── 8. The export carries the author's layout choice ────────────────────
    const outFile = path.join(projectA, "exported.html");
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      page.locator("#export-btn").click(),
    ]);
    await download.saveAs(outFile);
    const html = fs.readFileSync(outFile, "utf8");
    const bodyTag = (/<body[^>]*>/.exec(html) || [""])[0];
    if (!/data-width="extra"/.test(bodyTag))
      fail("the exported <body> lost data-width — the reader gets the default measure, not the "
        + "one the document was laid out in: " + bodyTag);
    if (!/data-code-layout="wide"/.test(bodyTag))
      fail("the exported <body> lost data-code-layout: " + bodyTag);
    if (/id="width-toggle"/.test(html) || /id="codelayout-toggle"/.test(html))
      fail("the exported file carries the controls themselves — dead chrome with no JS behind it");
    log("✓ export carries data-width and data-code-layout, and neither control itself");

    // ── 9. An anchorless document hides the layout toggle ───────────────────
    // It would be a button that provably does nothing: there is no pane to
    // move. The width control still applies — prose has a measure too.
    const projectB = fs.mkdtempSync(path.join(os.tmpdir(), "vc-e2e-proj-b-"));
    const sessB = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: projectB })).body);
    beatB = keepAlive(sessB.state_dir);
    writeBlocks(sessB.response_dir, "resp-view-b", "No code anywhere", [
      { id: "b-0", title: "Just prose", markdown: "Nothing here cites source." },
    ]);
    const pageB = await browser.newPage({ viewport: { width: 1800, height: 950 } });
    await pageB.goto(sessB.url, { waitUntil: "domcontentloaded" });
    await pageB.waitForSelector('section.block[data-block-id="b-0"]', { timeout: 8000 });
    await pageB.waitForTimeout(200);
    const anchorless = await pageB.evaluate(() => {
      const el = document.getElementById("codelayout-toggle");
      return {
        layoutShown: el ? getComputedStyle(el).display !== "none" : false,
        widthShown: getComputedStyle(document.getElementById("width-toggle")).display !== "none",
        width: document.body.dataset.width,
        contentMax: getComputedStyle(document.body).getPropertyValue("--content-max").trim(),
      };
    });
    if (anchorless.layoutShown)
      fail("the code-layout toggle is visible on a document with no panes to lay out");
    if (!anchorless.widthShown) fail("the width control vanished on an anchorless document");
    if (anchorless.width !== "normal" || anchorless.contentMax !== "1040px")
      fail("an anchorless document should open at the normal measure: " + JSON.stringify(anchorless));
    log("✓ anchorless document: layout toggle hidden, width control live, opens at 1040px");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
