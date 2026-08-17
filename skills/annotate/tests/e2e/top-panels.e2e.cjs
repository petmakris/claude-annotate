#!/usr/bin/env node
/*
 * Playwright end-to-end for the two on-demand panels in the top bar.
 *
 * The whole point of the design is a distinction that NO source-string test
 * can see, because it is a fact about pixels:
 *
 *   - the composer opens as a BAND of the bar, so the document moves down;
 *   - the legend opens as a POPOVER over the document, so the document does
 *     not move at all.
 *
 * Both are "the panel opened" as far as the DOM is concerned. Only
 * getBoundingClientRect() on main.prose tells them apart, so that comparison
 * is the spine of this file. Everything else here — computed display, focus,
 * the lit state of a toggle, whether a button actually sits inside the header
 * — is measured for the same reason: this area has now produced three bugs
 * that passed a source check while being visibly wrong on screen.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/top-panels.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "tp-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-tp", title: "tp", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}
function para(word) {
  return Array.from({ length: 5 },
    (_, i) => `Paragraph ${i + 1} about ${word}. ` + `${word} `.repeat(24)).join("\n\n");
}
const deck = () => ["b-0", "b-1", "b-2"].map((id, i) => ({
  id, title: `Section ${i}`, markdown: para("original"),
}));

// The lit state is a 140ms CSS transition, so reading getComputedStyle in the
// same tick as the click returns the START colour: the rule has matched, the
// paint simply has not caught up. An earlier draft of this file asserted on
// that immediate read and failed against correct code — measured live, the
// button reported rgb(248,249,251) on click and rgb(0,113,227) 400ms later.
// Wait for the attribute, then let the transition finish, then read.
async function litColor(page, id) {
  await page.waitForFunction(
    (i) => document.getElementById(i).matches('[aria-expanded="true"]'),
    id, { timeout: 2000 });
  await page.waitForTimeout(250);
  return page.evaluate(
    (i) => getComputedStyle(document.getElementById(i)).backgroundColor, id);
}

// Everything the two panels' state is made of, read in one round trip.
function readState(page) {
  return page.evaluate(() => {
    const box = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
      return { top: Math.round(b.top), left: Math.round(b.left),
               right: Math.round(b.right), bottom: Math.round(b.bottom),
               height: Math.round(b.height) }; };
    const disp = (sel) => { const el = document.querySelector(sel);
      return el ? getComputedStyle(el).display : "MISSING"; };
    const bubble = document.getElementById("composer-toggle");
    const help = document.getElementById("legend-toggle");
    return {
      composer: disp(".general-composer"),
      legend: disp(".legend-pop"),
      statstripShown: disp(".statstrip") !== "none",
      bubbleExpanded: bubble && bubble.getAttribute("aria-expanded"),
      helpExpanded: help && help.getAttribute("aria-expanded"),
      bubbleBg: bubble && getComputedStyle(bubble).backgroundColor,
      focus: document.activeElement && (document.activeElement.id || document.activeElement.tagName),
      prose: box(document.querySelector("main.prose")),
      header: box(document.querySelector(".page-header")),
      statstrip: box(document.querySelector(".statstrip")),
      band: box(document.querySelector(".general-composer")),
      pop: box(document.querySelector(".legend-pop")),
      helpBtn: box(help),
      bubbleBtn: box(bubble),
    };
  });
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "tp-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(sess.response_dir, deck());

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-2"]', { timeout: 8000 });
    log("✓ blocks rendered");

    // ── 1. Closed on load, and the toggles really are in the header ────────
    const load = await readState(page);
    if (load.composer !== "none") fail("composer paints on load: display=" + load.composer);
    if (load.legend !== "none") fail("legend popover paints on load: display=" + load.legend);
    if (load.bubbleExpanded !== "false") fail("bubble aria-expanded=" + load.bubbleExpanded + " on load");
    if (load.helpExpanded !== "false") fail("help aria-expanded=" + load.helpExpanded + " on load");
    for (const [name, b] of [["bubble", load.bubbleBtn], ["help", load.helpBtn]]) {
      if (!b) fail(name + " toggle is not rendered at all");
      if (b.top < load.header.top || b.bottom > load.header.bottom) {
        fail(name + " toggle is not inside the page header: " + JSON.stringify(b)
             + " vs header " + JSON.stringify(load.header));
      }
    }
    log("✓ both panels closed on load; both toggles inside the header box");

    // ── 2. The old always-on controls are gone from the reading column ─────
    const legacy = await page.evaluate(() => ({
      trigger: !!document.getElementById("composer-open"),
      details: !!document.querySelector("details.legend"),
    }));
    if (legacy.trigger) fail("the old full-width composer trigger row is still on the page");
    if (legacy.details) fail("the old <details class=legend> is still in the reading column");
    log("✓ neither legacy control survives");

    // ── 3. Bubble opens the composer as a BAND: document moves down ────────
    await page.locator("#composer-toggle").click();
    const opened = await readState(page);
    if (opened.composer !== "flex") fail("composer did not open: display=" + opened.composer);
    if (opened.bubbleExpanded !== "true") fail("bubble not marked expanded: " + opened.bubbleExpanded);
    if (opened.focus !== "general-input") fail("focus went to " + opened.focus + ", not the textarea");
    // Lit state — the accent fill is the only cue tying the band to its button.
    const litBubble = await litColor(page, "composer-toggle");
    if (litBubble === load.bubbleBg) {
      fail("the bubble toggle looks identical open and closed: " + litBubble);
    }
    // A band, not an overlay: it must push the document down.
    if (!(opened.prose.top > load.prose.top)) {
      fail("the composer did not displace the document (top " + load.prose.top
           + " -> " + opened.prose.top + ") — it is overlaying, not banding");
    }
    log(`✓ composer opened as a band (document ${load.prose.top} -> ${opened.prose.top}px), toggle lit, focus in textarea`);

    // ── 4. The band is full-bleed and flush with the bar above it ──────────
    if (opened.band.left !== opened.header.left || opened.band.right !== opened.header.right) {
      fail("the composer band does not span the same width as the header: "
           + JSON.stringify(opened.band) + " vs " + JSON.stringify(opened.header));
    }
    // Flush against whatever band actually precedes it. The statstrip only
    // renders when a statusline snapshot exists — it does not in this fixture,
    // and `.statstrip[hidden]` collapses its box to all-zeros, so measuring
    // against it unconditionally reports a bogus 51px gap against correct code.
    const above = opened.statstripShown ? opened.statstrip : opened.header;
    const aboveName = opened.statstripShown ? "statstrip" : "header";
    const gap = opened.band.top - above.bottom;
    if (Math.abs(gap) > 1) {
      fail("there is a " + gap + "px gap between the " + aboveName + " and the "
           + "composer band — the bar reads as two objects again");
    }
    log(`✓ band spans the header's full width and sits flush under the ${aboveName}`);

    // ── 5. Esc closes it and hands focus back to the button ────────────────
    await page.keyboard.press("Escape");
    const escaped = await readState(page);
    if (escaped.composer !== "none") fail("Esc did not close the composer: " + escaped.composer);
    if (escaped.bubbleExpanded !== "false") fail("aria-expanded stuck at true after Esc");
    if (escaped.focus !== "composer-toggle") fail("focus stranded on " + escaped.focus + " after Esc");
    if (escaped.prose.top !== load.prose.top) {
      fail("the document did not return to " + load.prose.top + " after closing: " + escaped.prose.top);
    }
    log("✓ Esc closes the band, restores focus to the toggle, document returns");

    // ── 6. The button toggles — a second click closes what the first opened ─
    await page.locator("#composer-toggle").click();
    if ((await readState(page)).composer !== "flex") fail("second open failed");
    await page.locator("#composer-toggle").click();
    if ((await readState(page)).composer !== "none") fail("clicking the lit toggle did not close the composer");
    log("✓ the toggle toggles");

    // ── 7. `g` still opens the composer ────────────────────────────────────
    await page.keyboard.press("g");
    if ((await readState(page)).composer !== "flex") fail("the `g` shortcut no longer opens the composer");
    await page.keyboard.press("Escape");
    log("✓ `g` still opens the composer");

    // ── 8. Help opens a POPOVER: the document does NOT move ────────────────
    const beforeHelp = await readState(page);
    await page.locator("#legend-toggle").click();
    const help = await readState(page);
    if (help.legend === "none") fail("the legend popover did not open");
    if (help.helpExpanded !== "true") fail("help toggle not marked expanded");
    if (help.prose.top !== beforeHelp.prose.top) {
      fail("opening the legend moved the document (" + beforeHelp.prose.top + " -> "
           + help.prose.top + ") — the whole point of a popover is that it does not");
    }
    // Anchored to its button, not floating loose in the page.
    if (help.pop.top < help.helpBtn.bottom) {
      fail("the popover overlaps its own button: pop.top=" + help.pop.top
           + " btn.bottom=" + help.helpBtn.bottom);
    }
    if (Math.abs(help.pop.right - help.helpBtn.right) > 24) {
      fail("the popover is not anchored to the help button: pop.right=" + help.pop.right
           + " btn.right=" + help.helpBtn.right);
    }
    if (help.pop.left < 0 || help.pop.right > 1512) {
      fail("the popover runs off screen: " + JSON.stringify(help.pop));
    }
    log(`✓ legend opens as an anchored popover, document unmoved at ${help.prose.top}px`);

    // ── 9. Only one panel at a time ────────────────────────────────────────
    await page.locator("#composer-toggle").click();
    const swapped = await readState(page);
    if (swapped.composer !== "flex") fail("composer did not open over the legend");
    if (swapped.legend !== "none") fail("both panels are open at once");
    if (swapped.helpExpanded !== "false") fail("the help toggle is still lit with its panel closed");
    log("✓ opening one panel closes the other");

    // ── 10. Click-outside dismisses the popover ────────────────────────────
    await page.keyboard.press("Escape");
    await page.locator("#legend-toggle").click();
    if ((await readState(page)).legend === "none") fail("legend failed to reopen");
    await page.mouse.click(200, 700);
    const outside = await readState(page);
    if (outside.legend !== "none") fail("clicking the document left the legend open");
    if (outside.helpExpanded !== "false") fail("help toggle still lit after click-outside");
    log("✓ click-outside dismisses the popover");

    // ── 11. Esc closes the popover too ─────────────────────────────────────
    await page.locator("#legend-toggle").click();
    await page.keyboard.press("Escape");
    if ((await readState(page)).legend !== "none") fail("Esc did not close the legend popover");
    log("✓ Esc closes the popover");

    // ── 12. It stays on screen on a narrow window ──────────────────────────
    // The legend used to be a full-width block in the reading column, so it
    // could not overflow. A fixed-width panel anchored to a button near the
    // right edge can: at a narrow viewport its left edge walks off screen and
    // the first column of the table becomes unreachable, with nothing to
    // scroll because the overflow is the page's, not the panel's.
    await page.setViewportSize({ width: 760, height: 900 });
    await page.locator("#legend-toggle").click();
    const narrow = await readState(page);
    if (narrow.legend === "none") fail("the legend did not open at 760px");
    if (narrow.pop.left < 0) {
      fail("the popover hangs off the left edge at 760px: " + JSON.stringify(narrow.pop));
    }
    if (narrow.pop.right > 760) {
      fail("the popover hangs off the right edge at 760px: " + JSON.stringify(narrow.pop));
    }
    log(`✓ popover stays on screen at 760px (${narrow.pop.left}..${narrow.pop.right})`);
    await page.setViewportSize({ width: 1512, height: 900 });

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
