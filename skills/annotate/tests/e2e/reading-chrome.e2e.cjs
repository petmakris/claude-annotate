#!/usr/bin/env node
/*
 * Playwright end-to-end for the reading chrome: what the reading surface
 * looks like at rest, and the sticky page ribbons. (The document map rail
 * this file once guarded was removed on request — see
 * test_smoke_reading_chrome.py's stays-removed guard. The collapsed composer
 * trigger it also guarded became a header icon button; that whole control now
 * lives in top-panels.e2e.cjs.)
 *
 * Everything here is measured on a rendered page — getComputedStyle() and
 * getBoundingClientRect() — because every bug this file guards passed a
 * source-string test while being visibly wrong on screen:
 *
 *   1. `openBtn.hidden = true` left the collapsed-composer trigger PAINTED:
 *      an author `display: flex` rule beats the UA's `[hidden]` rule, so the
 *      property said hidden and the pixels said otherwise.
 *   2. The sticky ribbons must track the document column at every viewport
 *      width — stale rail-offset math shoved them right of centre.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/reading-chrome.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "rc-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-rc", title: "rc", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}
function para(word) {
  return Array.from({ length: 7 },
    (_, i) => `Paragraph ${i + 1} about ${word}. ` + `${word} `.repeat(30)).join("\n\n");
}
function deck(mark) {
  return ["b-0", "b-1", "b-2", "b-3", "b-4"].map((id, i) => ({
    id, title: `Section ${i}`, markdown: para(mark === id ? "rewritten" : "original"),
  }));
}

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  let beat;
  const cleanup = () => {
    try { clearInterval(beat); } catch (_) {}
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "rc-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const responseDir = sess.response_dir, eventsDir = sess.events_dir, consumedDir = sess.consumed_dir;
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(responseDir, deck(null));

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-4"]', { timeout: 8000 });
    log("✓ blocks rendered");

    // ── The rail is gone and the reading column keeps its full width ───────
    // Measured against the column's OWN declared measure rather than a
    // hardcoded 1040: the width is a reader preference now, so pinning one
    // number here would test the default instead of the claim. The claim is
    // that nothing steals space from the reading column -- no rail, no shell,
    // and the prose fills the measure it was given.
    const layout = await page.evaluate(() => ({
      prose: document.querySelector("main.prose").getBoundingClientRect().width,
      contentMax: parseFloat(
        getComputedStyle(document.body).getPropertyValue("--content-max")),
      rail: !!document.getElementById("map-rail"),
      shell: !!document.querySelector(".reading-shell"),
    }));
    if (layout.rail || layout.shell) fail("the map rail / reading shell is back: " + JSON.stringify(layout));
    if (Math.round(layout.prose) !== Math.round(layout.contentMax))
      fail(`main.prose is ${Math.round(layout.prose)}px inside a ${layout.contentMax}px column — `
        + "something is taking space from the reading column");
    log(`✓ no rail, main.prose fills its ${Math.round(layout.contentMax)}px column`);

    // ── 1. The composer is closed until something opens it ─────────────────
    // The collapsed trigger row this section used to drive is gone: the
    // composer now opens from #composer-toggle in the page header, and all of
    // its open/close/focus/geometry behaviour is measured in
    // `top-panels.e2e.cjs`. What still belongs here is the one fact the
    // reading surface owns — nothing of the composer paints until asked.
    const composerOnLoad = await page.evaluate(() => ({
      display: getComputedStyle(document.querySelector(".general-composer")).display,
      legacyTrigger: !!document.getElementById("composer-open"),
    }));
    if (composerOnLoad.legacyTrigger) fail("the retired composer trigger row is back on the page");
    if (composerOnLoad.display !== "none") {
      fail("the composer renders expanded on load: display=" + composerOnLoad.display);
    }
    log("✓ composer closed on load, no legacy trigger row");

    // ── 2a. The busy ribbon tracks the document column ─────────────────────
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    await page.evaluate(() => window.scrollTo(0, 0));
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="keep"]').click();
    await page.locator("#round-submit").click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    const busy = await measureColumn(page, "#busy-banner");
    assertOnColumn(busy, "#busy-banner");
    log(`✓ busy ribbon ${JSON.stringify(busy.ribbon)} tracks document ${JSON.stringify(busy.prose)}`);

    // ── 2b. The change ribbon tracks it too, wide and narrow ───────────────
    const eventId = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"))[0].replace(/\.json$/, "");
    const next = deck(null);
    next[0].markdown = para("rewritten");
    writeBlocks(responseDir, next);
    fs.writeFileSync(path.join(consumedDir, eventId + ".ack"), "");
    await page.waitForSelector("#change-bar", { timeout: 10000 });

    const bar = await measureColumn(page, "#change-bar");
    assertOnColumn(bar, "#change-bar");
    log(`✓ change ribbon ${JSON.stringify(bar.ribbon)} tracks document ${JSON.stringify(bar.prose)}`);

    await page.setViewportSize({ width: 820, height: 900 });
    const narrow = await measureColumn(page, "#change-bar");
    assertOnColumn(narrow, "#change-bar @820px");
    log(`✓ 820px: ribbon ${Math.round(narrow.ribbon.left)}..${Math.round(narrow.ribbon.right)} `
        + `= document ${Math.round(narrow.prose.left)}..${Math.round(narrow.prose.right)}`);

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

async function measureColumn(page, sel) {
  return page.evaluate((s) => {
    const r = (el) => { const b = el.getBoundingClientRect();
      return { top: Math.round(b.top), left: Math.round(b.left), right: Math.round(b.right), bottom: Math.round(b.bottom) }; };
    return { ribbon: r(document.querySelector(s)), prose: r(document.querySelector("main.prose")) };
  }, sel);
}

function assertOnColumn(m, sel) {
  if (Math.abs(m.ribbon.left - m.prose.left) > 1
      || Math.abs(m.ribbon.right - m.prose.right) > 1) {
    fail(sel + " is not flush with the document column: "
         + JSON.stringify(m.ribbon) + " vs " + JSON.stringify(m.prose));
  }
}
