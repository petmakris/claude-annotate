#!/usr/bin/env node
/*
 * Playwright end-to-end for code anchors: the second column that paints real
 * source beside the prose.
 *
 * Every other test written for this feature (Tasks 7 and 8) is a
 * source-presence assertion — it greps script.js or style.css for a string.
 * That proves the text exists, not that the behaviour works. This file is
 * the only one that executes the browser, so it carries every claim no
 * source check can see:
 *
 *   - "side by side" is a fact about pixels (getBoundingClientRect), not a
 *     class name — and a zero-width column would pass that check while
 *     rendering nothing, so width is checked too;
 *   - a failing anchor must render ZERO lines, not whatever now sits at that
 *     line number — that would be a lie the reader cannot detect;
 *   - nothing inside a pane is a click target except widen and jump — a
 *     .cp-row that quietly opens a comment box would be a lie about what a
 *     click does;
 *   - export is free because inlining happens server-side, not fetched by
 *     the client after render;
 *   - a collapsed code-bearing card must not leak its two-column grid —
 *     the split rule's `:not(.collapsed)` guard exists for exactly this;
 *   - an anchorless block in a code-bearing document gets no `.code-col` at
 *     all and its prose keeps the card's full width — there is no longer a
 *     marker slot to check instead (Task 12 dropped it after measuring its
 *     layout cost on a real page: see the spec amendment);
 *   - the document-wide hasCode flag (driving --content-max) is a decision
 *     about the DOCUMENT, including on the poll-delta path where one
 *     block's first anchor has to update the flag for siblings rendered in
 *     the same tick (Task 8's fix to reconcile/setDocumentCodeFlag).
 *
 * A note on the export check (item 7), after a fix-round review finding:
 * the obvious way to prove "inlined server-side, not appended later" is to
 * defer renderCodePane's line-append by one tick (setTimeout(…, 0)) and
 * confirm the exported file's real button+download flow comes up empty.
 * It doesn't — measured directly (see the sabotage note by item 7 below),
 * clicking #export-btn and waiting for the download always takes 40ms+
 * (Playwright's CDP round trip alone accounts for most of it; export.js's
 * own font-embedding step adds the rest), which is an eternity next to a
 * same-tick 0ms deferral — so the deferred rows are already in the live DOM
 * by the time the real export ever fires, sabotaged or not. No amount of
 * reordering this file's calls changes that: it was verified with the
 * export check moved to the very first thing after the page loads, and
 * separately with window.fetch mocked to remove real network I/O from
 * export.js's font-embedding step entirely — neither made the real
 * button+download flow observe a still-pending render.
 *
 * So item 7 is two checks. The first is a MutationObserver installed via
 * page.addInitScript BEFORE the page's own scripts run, watching for the
 * moment b-0's card is inserted into the document and recording — as a
 * MicroTask, which the JS spec guarantees runs before ANY further
 * setTimeout callback, no matter how small its delay — whether that card's
 * pane already contained `.cp-row` elements at that exact instant. That is
 * not a wall-clock race: microtask-before-macrotask ordering is a language
 * guarantee, not a timing hope, so it deterministically catches a deferred
 * render that the real button click structurally cannot. The second is the
 * real #export-btn click + download, which still earns its keep for
 * everything ELSE it proves: the file it produces actually contains the
 * real source line, and the widen control (dead chrome with no JS in the
 * export) is stripped.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/code-anchors.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "ca-e2e-home-"));
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

// Installed before the page's own scripts run. Watches for b-0's card being
// inserted into the document and records — synchronously, in the
// MutationObserver callback, which the spec guarantees runs as a microtask
// before the next macrotask (i.e. before ANY setTimeout callback, including
// a 0ms one queued earlier in the same turn) — whether its pane already
// contained `.cp-row` elements at that exact instant. See the file header
// for why this, and not the real export button, is what actually has teeth
// against a same-tick deferred render.
function installSameTickProbe(page) {
  return page.addInitScript(() => {
    window.__cpSyncProbe = { fired: false, hadRows: null };
    const obs = new MutationObserver((records) => {
      if (window.__cpSyncProbe.fired) return;
      for (const rec of records) {
        for (const node of rec.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches && node.matches('section.block[data-block-id="b-0"]')) {
            const pane = node.querySelector(".codepane");
            if (pane) {
              window.__cpSyncProbe.fired = true;
              window.__cpSyncProbe.hadRows = !!pane.querySelector(".cp-row");
              obs.disconnect();
            }
          }
        }
      }
    });
    // document.documentElement does not exist yet at addInitScript time;
    // `document` itself always does, and subtree:true still catches
    // everything under the eventual <html>.
    obs.observe(document, { childList: true, subtree: true });
  });
}

// ── Workspace A fixture: real source, one good anchor, one stale anchor ────
const CALC_LINES = [
  '"""Calculator utilities used by the reporting pipeline."""',
  "",
  "",
  "def add(a, b):",
  "    return a + b",
  "",
  "",
  "def multiply(a, b):",
  "    return a * b",
  "",
  "",
  "def compute_total(items):",
  "    subtotal = 0",
  "    for item in items:",
  "        subtotal = add(subtotal, item.price)",
  "    tax = multiply(subtotal, 0.08)",
  "    return add(subtotal, tax)",
  "",
  "",
  "def format_currency(amount):",
  '    return f"${amount:,.2f}"',
];
const ANCHOR_SNIPPET = "subtotal = add(subtotal, item.price)";
const ANCHOR_LINE = CALC_LINES.indexOf(`        ${ANCHOR_SNIPPET}`) + 1;
if (ANCHOR_LINE < 1) throw new Error("fixture setup: anchor snippet not found in fixture source");

// ── Workspace B fixture: gains its first-ever anchor mid-poll ──────────────
const UTIL_LINES = ["def util():", "    return 42"];
const UTIL_SNIPPET = "return 42";
const UTIL_LINE = UTIL_LINES.indexOf(`    ${UTIL_SNIPPET}`) + 1;
if (UTIL_LINE < 1) throw new Error("fixture setup: util snippet not found in fixture source");

function blockRect(page, blockId, selector) {
  return page.evaluate(({ blockId, selector }) => {
    const section = document.querySelector(`section.block[data-block-id="${blockId}"]`);
    if (!section) return null;
    const el = section.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width };
  }, { blockId, selector });
}

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
    // ── Workspace A: a document that cites code ─────────────────────────────
    const projectA = fs.mkdtempSync(path.join(os.tmpdir(), "ca-e2e-proj-a-"));
    fs.mkdirSync(path.join(projectA, "lib"), { recursive: true });
    fs.writeFileSync(path.join(projectA, "lib", "calc.py"), CALC_LINES.join("\n") + "\n");
    const sessA = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: projectA })).body);
    beatA = keepAlive(sessA.state_dir);
    writeBlocks(sessA.response_dir, "resp-anchors-a", "Code anchors", [
      { id: "b-0", title: "The anchored block", markdown: "This cites the total calculation.",
        code: [{ file: "lib/calc.py", line: ANCHOR_LINE, snippet: ANCHOR_SNIPPET }] },
      { id: "b-1", title: "A stale anchor", markdown: "This citation has drifted.",
        code: [{ file: "lib/calc.py", line: 5, snippet: "THIS_TEXT_IS_NOT_IN_THE_FILE_92f1" }] },
      { id: "b-2", title: "A block with nothing to cite", markdown: "Plain prose, no anchors." },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await installSameTickProbe(page);
    await page.goto(sessA.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-2"]', { timeout: 8000 });
    log("✓ workspace A rendered: three blocks");

    // ── 7. Export carries the code (deterministic half) ─────────────────────
    // See the file header: this is the check with real teeth against a
    // same-tick deferred render, because it relies on microtask-before-
    // macrotask ordering rather than out-racing Playwright's own IPC.
    const probe = await page.evaluate(() => window.__cpSyncProbe);
    if (!probe.fired) fail("the same-tick probe never saw b-0's card get inserted");
    if (!probe.hadRows)
      fail("b-0's pane had no .cp-row at the instant its card entered the DOM — "
        + "the code was not rendered synchronously with the pane container");
    log("✓ the pane's code rows exist in the DOM in the same tick as the pane itself (deterministic, not raced)");

    // ── 7. Export carries the code (the real button, for everything else it
    //       proves: the file is real, and dead chrome is stripped) ─────────
    const outFile = path.join(projectA, "exported.html");
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      page.locator("#export-btn").click(),
    ]);
    await download.saveAs(outFile);
    const exportedHtml = fs.readFileSync(outFile, "utf8");
    // hljs wraps tokens in <span>s that split the raw line across tags, so
    // compare against the tag-stripped text — hljs preserves every character,
    // it only wraps substrings, so the stripped text reassembles exactly.
    const strippedText = exportedHtml.replace(/<[^>]+>/g, "");
    if (!strippedText.includes(ANCHOR_SNIPPET))
      fail("the exported file does not contain the real source line — code was not inlined server-side");
    if (/class="cp-widen"/.test(exportedHtml))
      fail("the exported file still carries a .cp-widen button — dead chrome with no JS behind it");
    log("✓ export carries the real source line and strips the widen control");

    // M3: the live page's document.body.dataset.hasCode drives --content-max
    // (1180px vs 1040px) via body[data-has-code="1"] in style.css. Each
    // code-bearing section keeps its own data-has-code attribute through the
    // clone, so its card still split 46/54 even without this — just into the
    // narrow column instead of the wide one.
    if (!/<body class="exported" data-has-code="1">/.test(exportedHtml))
      fail("the exported <body> does not carry data-has-code — the exported "
        + "document loses its widened --content-max while its sections still split");
    log("✓ export carries data-has-code so the wide column survives");

    // I1: the exported file has no owner, so a jetbrains:// link (which only
    // ever resolves on the author's machine) must not ride along either.
    if (/class="cp-jump"/.test(exportedHtml))
      fail("the exported file still carries a .cp-jump link — a dead, "
        + "author-machine-only href leaking a filesystem path");
    log("✓ export strips the IDE jump link");

    await sleep(300); // let the initial /raw render settle before measuring layout

    // ── 1. The split is real, not just classed ──────────────────────────────
    const contentRect = await blockRect(page, "b-0", ".block-content");
    const codeRect = await blockRect(page, "b-0", ".code-col");
    if (!contentRect || !codeRect) fail("b-0 is missing .block-content or .code-col");
    if (!(contentRect.width > 0)) fail(".block-content has zero width: " + JSON.stringify(contentRect));
    if (!(codeRect.width > 0)) fail(".code-col has zero width — a collapsed column would pass the overlap check while rendering nothing: " + JSON.stringify(codeRect));
    const vOverlap = contentRect.top < codeRect.bottom && codeRect.top < contentRect.bottom;
    const hOverlap = contentRect.left < codeRect.right && codeRect.left < contentRect.right;
    if (!vOverlap) fail("block-content and code-col do not overlap vertically: "
      + JSON.stringify(contentRect) + " vs " + JSON.stringify(codeRect));
    if (hOverlap) fail("block-content and code-col overlap horizontally — not side by side: "
      + JSON.stringify(contentRect) + " vs " + JSON.stringify(codeRect));
    log(`✓ split is real: content right=${Math.round(contentRect.right)} <= code left=${Math.round(codeRect.left)}, both columns have real width, rows overlap vertically`);

    // ── 2. The anchor line is the emphasised one ────────────────────────────
    const anchorInfo = await page.evaluate(() => {
      const section = document.querySelector('section.block[data-block-id="b-0"]');
      const rows = [...section.querySelectorAll(".code-col .cp-row.is-anchor")];
      return { count: rows.length, num: rows[0] && rows[0].querySelector(".cp-num").textContent };
    });
    if (anchorInfo.count !== 1) fail("expected exactly one .cp-row.is-anchor, found " + anchorInfo.count);
    if (anchorInfo.num !== String(ANCHOR_LINE)) fail(`anchor row shows line ${anchorInfo.num}, expected ${ANCHOR_LINE}`);
    log(`✓ exactly one anchor row, line number ${anchorInfo.num} matches the anchor`);

    // ── 3. Context lines are dimmed, not hidden ─────────────────────────────
    // The light theme (task 13) de-emphasises context rows by desaturating
    // them to a single muted grey instead of opacity — opacity blends ink
    // toward the paper, which drops a comment token to 2.17:1 on a light
    // ground. So this now asserts full opacity (not hidden) plus the
    // desaturated colour actually winning over any token colour a row's
    // syntax highlighting would otherwise have painted.
    const contextInfo = await page.evaluate(() => {
      const section = document.querySelector('section.block[data-block-id="b-0"]');
      const rows = [...section.querySelectorAll(".code-col .cp-row.is-context")];
      return rows.map((el) => {
        const tokens = [...el.querySelectorAll('[class^="hljs-"], [class*=" hljs-"]')];
        return {
          opacity: parseFloat(getComputedStyle(el).opacity),
          rowColor: getComputedStyle(el).color,
          tokenColors: tokens.map((t) => getComputedStyle(t).color),
        };
      });
    });
    if (!contextInfo.length) fail("no .cp-row.is-context found — the fixture's context window is empty");
    const DESATURATED = "rgb(95, 103, 115)"; // #5f6773
    for (const row of contextInfo) {
      if (row.opacity !== 1) fail("a context row has opacity " + row.opacity + ", expected 1 (desaturation replaces opacity now)");
      if (row.rowColor !== DESATURATED) fail("a context row has color " + row.rowColor + ", expected the desaturated " + DESATURATED);
      for (const tc of row.tokenColors) {
        if (tc !== DESATURATED) fail("a context row's token has color " + tc + " instead of the desaturated " + DESATURATED + " — a syntax colour is winning back through");
      }
    }
    log(`✓ ${contextInfo.length} context rows desaturated to ${DESATURATED} (opacity 1, not hidden, not dimmed via opacity)`);

    // ── 4. widen promotes ────────────────────────────────────────────────────
    const beforeWidth = (await blockRect(page, "b-0", ".code-col")).width;
    await page.locator('section.block[data-block-id="b-0"] .cp-widen').click();
    await page.waitForFunction(() => {
      const s = document.querySelector('section.block[data-block-id="b-0"]');
      return s && s.dataset.codeWide === "1";
    }, { timeout: 3000 });
    const afterWidth = (await blockRect(page, "b-0", ".code-col")).width;
    if (!(afterWidth > beforeWidth)) fail(`widen did not grow the pane: ${beforeWidth} -> ${afterWidth}`);
    log(`✓ widen promotes: code-col ${Math.round(beforeWidth)}px -> ${Math.round(afterWidth)}px, data-code-wide=1`);

    // ── 5. Promotion survives reload ────────────────────────────────────────
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-0"] .code-col .cp-row', { timeout: 8000 });
    const persisted = await page.evaluate(() => {
      const s = document.querySelector('section.block[data-block-id="b-0"]');
      const btn = s.querySelector(".cp-widen");
      return { wide: s.dataset.codeWide, label: btn && btn.textContent };
    });
    if (persisted.wide !== "1") fail("data-code-wide did not survive reload: " + persisted.wide);
    if (persisted.label !== "narrow") fail("widen button did not read 'narrow' after reload: " + persisted.label);
    log("✓ promotion survives reload: data-code-wide=1, button reads 'narrow'");

    // ── 8. A failing pane shows its reason and NO code ──────────────────────
    const stale = await page.evaluate(() => {
      const section = document.querySelector('section.block[data-block-id="b-1"]');
      const status = section.querySelector(".code-col .cp-status");
      const rows = section.querySelectorAll(".code-col .cp-row");
      const path = section.querySelector(".code-col .cp-path");
      return {
        status: status && status.dataset.status,
        message: status && status.textContent,
        rowCount: rows.length,
        header: path && path.textContent,
      };
    });
    if (stale.status !== "stale") fail("expected the b-1 pane status to be 'stale', got " + stale.status);
    if (!stale.message) fail("the stale pane carries no reason text");
    if (stale.rowCount !== 0) fail(`the stale pane rendered ${stale.rowCount} .cp-row elements — it must render none`);
    log(`✓ failing pane shows its reason ("${stale.message}") and renders zero code rows`);

    // ── Fix 2: a failing pane must not claim a line number, and must not
    //         repeat its filename ──────────────────────────────────────────
    // b-1's anchor is on "lib/calc.py". A failing pane's header used to read
    // "lib/calc.py:5" — asserting a location the body text was about to
    // disprove — and the message started with "lib/calc.py: " again, so the
    // filename appeared twice.
    if (stale.header !== "lib/calc.py")
      fail(`stale pane header is "${stale.header}", expected the bare file path `
        + `"lib/calc.py" with no :line suffix`);
    if (stale.message.startsWith("lib/calc.py"))
      fail(`stale pane status text starts with the filename ("${stale.message}") — `
        + "the header already shows it, it should not be repeated");
    log(`✓ stale pane header is the bare file path ("${stale.header}", no :line) and its `
      + `status text does not repeat the filename`);

    // ── 12. A collapsed code-bearing card does not leak its split grid ─────
    // The split rule (style.css) guards its two-column grid with
    // `:not(.collapsed)`. Nothing before this line ever folds a code-bearing
    // card, so nothing has proved that guard holds. Uses b-1, not b-0 — b-0
    // stays expanded because item 9 below still needs to click into it.
    await page.locator('section.block[data-block-id="b-1"] .card-chevron').click();
    await page.waitForFunction(() => {
      const s = document.querySelector('section.block[data-block-id="b-1"]');
      return s && s.classList.contains("collapsed");
    }, { timeout: 3000 });
    const foldedDisplay = await page.evaluate(() => {
      const s = document.querySelector('section.block[data-block-id="b-1"]');
      const body = s.querySelector(".card-body");
      return body && getComputedStyle(body).display;
    });
    if (foldedDisplay !== "none")
      fail(`a collapsed code-bearing card still shows its body: display=${foldedDisplay} — the split grid leaked through .collapsed`);
    log("✓ folding a code-bearing card hides its body — the split grid does not leak through .collapsed");

    // ── 9. Nothing inside the pane is a click target except widen/jump ─────
    const before9 = await page.evaluate(() => ({
      url: location.href,
      composers: document.querySelectorAll(".unit-composer, .comment-card").length,
    }));
    await page.locator('section.block[data-block-id="b-0"] .code-col .cp-row.is-context').first().click();
    await sleep(200);
    const after9 = await page.evaluate(() => ({
      url: location.href,
      composers: document.querySelectorAll(".unit-composer, .comment-card").length,
    }));
    if (after9.url !== before9.url) fail(`clicking a .cp-row navigated: ${before9.url} -> ${after9.url}`);
    if (after9.composers !== before9.composers) fail("clicking a .cp-row opened a comment composer/card");
    log("✓ clicking a .cp-row does nothing — no composer, no navigation");

    // ── 10. An anchorless block in a code-bearing document gets its full
    //         card width back — no marker, no second column ────────────────
    const b2CodeCols = await page.evaluate(() =>
      document.querySelectorAll('section.block[data-block-id="b-2"] .code-col').length);
    if (b2CodeCols !== 0) fail(`b-2 (no anchors, but the doc cites code elsewhere) has ${b2CodeCols} .code-col element(s) — should have none`);
    const b2ContentRect = await blockRect(page, "b-2", ".block-content");
    const b2CardWidth = await page.evaluate(() => {
      const section = document.querySelector('section.block[data-block-id="b-2"]');
      return section.getBoundingClientRect().width;
    });
    if (!b2ContentRect) fail("b-2 is missing .block-content");
    const b2Ratio = b2ContentRect.width / b2CardWidth;
    if (!(b2Ratio > 0.85))
      fail(`b-2's .block-content (${Math.round(b2ContentRect.width)}px) does not span the card `
        + `(${Math.round(b2CardWidth)}px, ratio ${b2Ratio.toFixed(2)}) — expected the full width `
        + `back now that the marker slot is gone`);
    log(`✓ b-2 (anchorless, in a code-bearing document) has no .code-col and its prose spans `
      + `the full card width (${Math.round(b2ContentRect.width)}px / ${Math.round(b2CardWidth)}px)`);

    // ── Workspace B: a document with NO anchors anywhere ────────────────────
    const projectB = fs.mkdtempSync(path.join(os.tmpdir(), "ca-e2e-proj-b-"));
    fs.writeFileSync(path.join(projectB, "util.py"), UTIL_LINES.join("\n") + "\n");
    const sessB = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: projectB })).body);
    beatB = keepAlive(sessB.state_dir);
    writeBlocks(sessB.response_dir, "resp-anchors-b", "No code cited anywhere", [
      { id: "b-0", title: "First observation", markdown: "Nothing here cites source." },
      { id: "b-1", title: "Second observation", markdown: "Neither does this." },
    ]);

    const pageB = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    pageB.on("pageerror", (e) => log("PAGE ERROR (workspace B): " + e.message));
    await pageB.goto(sessB.url, { waitUntil: "domcontentloaded" });
    await pageB.waitForSelector('section.block[data-block-id="b-1"]', { timeout: 8000 });

    // ── 6. An anchorless document is untouched ──────────────────────────────
    const untouched = await pageB.evaluate(() => ({
      hasCode: document.body.dataset.hasCode,
      codeCols: document.querySelectorAll(".code-col").length,
      contentMax: getComputedStyle(document.body).getPropertyValue("--content-max").trim(),
    }));
    if (untouched.hasCode === "1") fail("body.dataset.hasCode is '1' in a document with no anchors");
    if (untouched.codeCols !== 0) fail(`found ${untouched.codeCols} .code-col elements in an anchorless document`);
    if (untouched.contentMax !== "1040px") fail("--content-max is " + untouched.contentMax + ", expected 1040px");
    log("✓ anchorless document untouched: no hasCode flag, no .code-col, --content-max=1040px");

    // ── 11. The poll-delta path sets the document flag ──────────────────────
    // Both blocks change in the SAME rewrite: b-1 gains the document's first
    // anchor, and b-0 (still anchorless) is edited too so it is re-rendered
    // in the SAME reconcile tick. That is exactly the scenario Task 8's
    // setDocumentCodeFlag-in-reconcile fix targets — body[data-has-code="1"]
    // drives --content-max by a live CSS attribute selector, so a stale flag
    // would show up as the wrong width, not (any more) as a marker on b-0.
    // b-0 itself must come back from the rewrite with no .code-col of its
    // own — it stays anchorless even though its sibling and the document
    // flag both went code-bearing in the same tick.
    writeBlocks(sessB.response_dir, "resp-anchors-b", "No code cited anywhere", [
      { id: "b-0", title: "First observation", markdown: "Nothing here cites source. (revised)" },
      { id: "b-1", title: "Second observation", markdown: "Neither does this.",
        code: [{ file: "util.py", line: UTIL_LINE, snippet: UTIL_SNIPPET }] },
    ]);
    await pageB.waitForFunction(() => document.body.dataset.hasCode === "1", { timeout: 6000 });
    await pageB.waitForFunction(() => {
      const s = document.querySelector('section.block[data-block-id="b-1"]');
      return s && s.querySelectorAll(".code-col .cp-row").length > 0;
    }, { timeout: 6000 });
    const afterPoll = await pageB.evaluate(() => ({
      hasCode: document.body.dataset.hasCode,
      b1Rows: document.querySelector('section.block[data-block-id="b-1"]')
        .querySelectorAll(".code-col .cp-row").length,
      b0CodeCols: document.querySelectorAll('section.block[data-block-id="b-0"] .code-col').length,
    }));
    if (afterPoll.hasCode !== "1") fail("hasCode flag did not flip to '1' after the poll delta");
    if (!afterPoll.b1Rows) fail("b-1's new anchor never rendered any .cp-row after the poll");
    if (afterPoll.b0CodeCols !== 0)
      fail(`b-0 (still anchorless, but re-rendered in the same tick) has ${afterPoll.b0CodeCols} `
        + ".code-col element(s) — it should have none");
    log("✓ poll-delta path: hasCode flips to 1, the new pane renders, and a sibling block "
      + "re-rendered in the same tick stays anchorless (no .code-col) — all without a reload");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
