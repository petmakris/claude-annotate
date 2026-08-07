#!/usr/bin/env node
/*
 * Playwright end-to-end for the reading chrome: the collapsed general
 * composer, the sticky document map rail, and the sticky page ribbons.
 *
 * Everything here is measured on a rendered page — getComputedStyle() and
 * getBoundingClientRect() — because every bug this file guards passed a
 * source-string test while being visibly wrong on screen:
 *
 *   1. `openBtn.hidden = true` left the collapsed-composer trigger PAINTED:
 *      an author `display: flex` rule beats the UA's `[hidden]` rule, so the
 *      property said hidden and the pixels said otherwise.
 *   2. The rail's "this section changed" dot was gated on `dataset.diff`,
 *      which only the card's own "what changed" toggle ever sets — so the
 *      dot could only ever mark a section the reader had already found.
 *      Asserted here WITHOUT clicking any toggle: that is the actual claim.
 *   3. The rail and the sticky ribbons are both `top: 0`; a ribbon that
 *      spanned the whole reading shell painted over the rail's header and
 *      first rows whenever the page was scrolled.
 *   4. The rail never said which section you were reading.
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
// Tall enough that one section fills well over a third of the viewport, so
// the reading-line spy has something unambiguous to point at.
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
    await page.waitForSelector("#map-rail .map-item", { timeout: 8000 });
    log("✓ blocks rendered, rail built");

    // ── The reading column is the width it was before the rail existed ─────
    const widths = await page.evaluate(() => ({
      prose: document.querySelector("main.prose").getBoundingClientRect().width,
      shellKids: [...document.querySelector(".reading-shell").children].map(e => e.tagName + "." + e.className),
    }));
    if (Math.round(widths.prose) !== 1040) fail("main.prose width = " + widths.prose + ", expected 1040");
    if (widths.shellKids.length !== 2) fail("reading shell children = " + JSON.stringify(widths.shellKids));
    log("✓ main.prose 1040px, shell children " + JSON.stringify(widths.shellKids));

    // ── 1. The collapsed composer trigger actually disappears ──────────────
    const before = await page.evaluate(() => ({
      btn: getComputedStyle(document.getElementById("composer-open")).display,
      composer: getComputedStyle(document.querySelector(".general-composer")).display,
    }));
    if (before.btn === "none") fail("the trigger is hidden before anything opened the composer");
    if (before.composer !== "none") fail("the composer renders expanded on load: display=" + before.composer);
    await page.locator("#composer-open").click();
    const after = await page.evaluate(() => ({
      btn: getComputedStyle(document.getElementById("composer-open")).display,
      btnBox: document.getElementById("composer-open").getBoundingClientRect().height,
      composer: getComputedStyle(document.querySelector(".general-composer")).display,
      focus: document.activeElement && document.activeElement.id,
    }));
    // The PROPERTY was always true; only these two reads can see the bug.
    if (after.btn !== "none") fail("trigger still painted after opening: display=" + after.btn);
    if (after.btnBox !== 0) fail("trigger still occupies " + after.btnBox + "px of layout");
    if (after.composer !== "flex") fail("composer did not expand: display=" + after.composer);
    if (after.focus !== "general-input") fail("focus went to " + after.focus);
    log("✓ trigger display none / 0px box, composer flex, focus in #general-input");

    // ── 4. The rail says which section you are reading ─────────────────────
    await page.evaluate(() => {
      const s = document.querySelector('section.block[data-block-id="b-3"]');
      window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 50);
    });
    await page.waitForFunction(
      () => document.querySelector('#map-rail .map-item[aria-current="true"]')?.dataset.blockId === "b-3",
      null, { timeout: 4000 });
    const current = await page.evaluate(() => {
      const items = [...document.querySelectorAll('#map-rail .map-item[aria-current="true"]')];
      const it = items[0];
      return { n: items.length, id: it.dataset.blockId,
               weight: getComputedStyle(it).fontWeight,
               border: getComputedStyle(it).borderLeftColor };
    });
    if (current.n !== 1) fail(current.n + " sections claim to be the current one");
    log(`✓ reading b-3 → rail marks ${current.id} (font-weight ${current.weight}, border ${current.border})`);

    // ── 3a. The busy ribbon does not paint over the rail ───────────────────
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    await page.evaluate(() => window.scrollTo(0, 0));
    await b0.locator(".card-head").hover();
    await b0.locator('.hover-actions button[data-type="keep"]').click();
    await page.locator("#round-submit").click();
    await page.waitForSelector("#busy-banner", { timeout: 8000 });
    await page.evaluate(() => {
      const s = document.querySelector('section.block[data-block-id="b-2"]');
      window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY);
    });
    const busyOverlap = await measureOverlap(page, "#busy-banner");
    assertClear(busyOverlap, "#busy-banner");
    log(`✓ busy ribbon ${JSON.stringify(busyOverlap.ribbon)} clears rail ${JSON.stringify(busyOverlap.rail)}; `
        + `rail header hit-tests to ${busyOverlap.atRailHead}`);

    // ── 2. A completed round dots the rail, with nobody clicking a toggle ──
    const eventId = fs.readdirSync(eventsDir).filter(f => f.endsWith(".json"))[0].replace(/\.json$/, "");
    const next = deck(null);
    next[0].markdown = para("rewritten");   // b-0: the block the user marked
    next[1].markdown = para("swept");       // b-1: moved by the coherence sweep
    writeBlocks(responseDir, next);
    fs.writeFileSync(path.join(consumedDir, eventId + ".ack"), "");
    await page.waitForSelector("#change-bar", { timeout: 10000 });

    const dots = await page.evaluate(() => {
      const togglesClicked = [...document.querySelectorAll(".card-diff-toggle")]
        .filter(t => t.getAttribute("aria-pressed") === "true").length;
      const openPanes = [...document.querySelectorAll("section.block")]
        .filter(s => s.dataset.diff === "open").length;
      const rows = [...document.querySelectorAll("#map-rail .map-item")].map(it => ({
        id: it.dataset.blockId,
        dots: [...it.querySelectorAll(".map-dot")].map(d => ({
          cls: d.className,
          box: d.getBoundingClientRect().width,
          bg: getComputedStyle(d).backgroundColor,
        })),
      }));
      return { togglesClicked, openPanes, rows };
    });
    if (dots.togglesClicked || dots.openPanes) fail("a diff toggle was open before the dots were read");
    const dotFor = (id) => (dots.rows.find(r => r.id === id) || { dots: [] }).dots;
    const changed = dotFor("b-0").filter(d => d.cls.includes("d-changed"));
    const swept = dotFor("b-1").filter(d => d.cls.includes("d-swept"));
    const quiet = dotFor("b-4").filter(d => d.cls.includes("d-changed") || d.cls.includes("d-swept"));
    if (changed.length !== 1) fail("b-0 (you asked) has " + changed.length + " changed dots: " + JSON.stringify(dotFor("b-0")));
    if (swept.length !== 1) fail("b-1 (sweep) has " + swept.length + " swept dots: " + JSON.stringify(dotFor("b-1")));
    if (quiet.length !== 0) fail("b-4 never moved but carries " + JSON.stringify(quiet));
    if (!changed[0].box || !swept[0].box) fail("a dot renders at zero width");
    log(`✓ no toggle clicked; b-0 ${JSON.stringify(changed[0])} b-1 ${JSON.stringify(swept[0])} b-4 none`);

    // ── 3b. The change ribbon does not paint over the rail either ──────────
    await page.evaluate(() => {
      const s = document.querySelector('section.block[data-block-id="b-2"]');
      window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY);
    });
    const barOverlap = await measureOverlap(page, "#change-bar");
    assertClear(barOverlap, "#change-bar");
    log(`✓ change ribbon ${JSON.stringify(barOverlap.ribbon)} clears rail ${JSON.stringify(barOverlap.rail)}; `
        + `rail header hit-tests to ${barOverlap.atRailHead}`);
    if (Math.abs(barOverlap.ribbon.left - barOverlap.prose.left) > 1
        || Math.abs(barOverlap.ribbon.right - barOverlap.prose.right) > 1) {
      fail("change ribbon is not flush with the document column: "
           + JSON.stringify(barOverlap.ribbon) + " vs " + JSON.stringify(barOverlap.prose));
    }
    log("✓ ribbon spans exactly the document column");

    // ── 3c. …and the narrow layout, where there is no rail to clear ────────
    await page.setViewportSize({ width: 820, height: 900 });
    const narrow = await page.evaluate(() => ({
      rail: getComputedStyle(document.getElementById("map-rail")).display,
      bar: document.getElementById("change-bar").getBoundingClientRect(),
      prose: document.querySelector("main.prose").getBoundingClientRect(),
    }));
    if (narrow.rail !== "none") fail("rail still shown at 820px: " + narrow.rail);
    if (Math.abs(narrow.bar.left - narrow.prose.left) > 1 || Math.abs(narrow.bar.width - narrow.prose.width) > 1) {
      fail("ribbon does not track the document at 820px: "
           + JSON.stringify(narrow.bar) + " vs " + JSON.stringify(narrow.prose));
    }
    log(`✓ 820px: rail hidden, ribbon ${Math.round(narrow.bar.left)}..${Math.round(narrow.bar.right)} `
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

// Rects for a sticky ribbon and the sticky rail, plus what the browser
// itself says is on top at the rail's header — the only read that can tell
// "beside" from "painted over".
async function measureOverlap(page, sel) {
  return page.evaluate((s) => {
    const r = (el) => { const b = el.getBoundingClientRect();
      return { top: Math.round(b.top), left: Math.round(b.left), right: Math.round(b.right), bottom: Math.round(b.bottom) }; };
    const ribbon = document.querySelector(s);
    const rail = document.getElementById("map-rail");
    const head = rail.querySelector(".map-rail-head");
    const hb = head.getBoundingClientRect();
    const hit = document.elementFromPoint(hb.left + hb.width / 2, hb.top + hb.height / 2);
    return {
      ribbon: r(ribbon), rail: r(rail), prose: r(document.querySelector("main.prose")),
      head: r(head),
      atRailHead: hit ? hit.tagName + "." + (hit.className || "") : "nothing",
    };
  }, sel);
}

function assertClear(m, sel) {
  const vertical = m.ribbon.bottom > m.rail.top && m.ribbon.top < m.rail.bottom;
  if (!vertical) fail(sel + " and the rail do not even share a band — the scroll setup is wrong, "
                      + JSON.stringify(m));
  if (m.ribbon.left < m.rail.right) {
    fail(sel + " spans the rail's column (" + JSON.stringify(m.ribbon) + " vs " + JSON.stringify(m.rail) + ")");
  }
  // Geometry can agree and the paint still lose: ask the browser who is on
  // top where the rail's header sits.
  if (!/map-rail/.test(m.atRailHead)) {
    fail(sel + " (or something else) paints over the rail's header — elementFromPoint says " + m.atRailHead);
  }
}
