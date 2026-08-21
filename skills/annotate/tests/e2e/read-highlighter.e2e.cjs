#!/usr/bin/env node
/*
 * Playwright end-to-end for the reading highlighter: drag-select prose while
 * it is on and the stretch keeps a marker-yellow background, so the page
 * shows a trail of what has already been read.
 *
 * Everything here is a fact about a live selection and a live paint, which no
 * source check can reach:
 *
 *   - the paint uses the CSS Custom Highlight API, so there are NO wrapper
 *     elements to assert on. The only way to know a stretch is highlighted is
 *     to read the range back out of CSS.highlights and compare its text;
 *   - the selection must SURVIVE being recorded. script.js:189 quotes the
 *     live selection into a comment when a hover-action button is clicked,
 *     and a highlighter that collapsed the selection would silently break
 *     that flow while looking perfectly fine;
 *   - and the offsets are the whole game. Prose text nodes are interleaved
 *     with UI text nodes -- `.unit-strip` puts 🗑✓💬 INSIDE the paragraph --
 *     so a walker that counts those shifts every offset after them. Item 7
 *     highlights text in a SECOND paragraph, i.e. after a strip, and reloads:
 *     that is the only arrangement where a miscounting walker is visible.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/read-highlighter.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "hl-e2e-home-"));
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

const CALC = ['"""Calc."""', "", "def add(a, b):", "    return a + b"];
const SNIP = "return a + b";
const LINE = CALC.indexOf("    " + SNIP) + 1;

// The phrase every assertion is written against lives in the SECOND paragraph
// of b-0, i.e. after the first paragraph's hover strip. See the file header.
const PARA_ONE = "The first paragraph exists only so that a hover strip sits between it and the words this test actually highlights.";
const PARA_TWO = "Marbled quartz hums beneath the aqueduct while eleven jackdaws vex the sleeping foreman.";
const PHRASE = "eleven jackdaws vex the sleeping foreman";
const OVERLAP = "jackdaws vex the sleeping foreman.";
if (!PARA_TWO.includes(PHRASE) || !PARA_TWO.includes(OVERLAP)) throw new Error("fixture setup: phrases not in paragraph two");

// Select `needle` inside the given block's prose and release the mouse, which
// is the gesture the highlighter listens for. Returns what the browser
// reports as selected, so a test can prove the selection SURVIVED.
function selectPhrase(page, blockId, needle) {
  return page.evaluate(({ blockId, needle }) => {
    const root = document.querySelector(
      `section.block[data-block-id="${blockId}"] .block-content`);
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walk.nextNode())) {
      const i = node.textContent.indexOf(needle);
      if (i < 0) continue;
      const r = document.createRange();
      r.setStart(node, i);
      r.setEnd(node, i + needle.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      root.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return sel.toString();
    }
    return null;
  }, { blockId, needle });
}
// Everything the highlighter has painted, as text, straight out of the
// registry -- there are no elements to query.
function painted(page) {
  return page.evaluate(() => {
    const hl = CSS.highlights.get("annotate-read");
    if (!hl) return [];
    return [...hl].map((r) => r.toString());
  });
}


// The colour claim can only be settled in pixels: ::highlight() is painted by
// the engine, not by any element, so there is no computed style to read and no
// node to inspect. This screenshots the highlighted words, hands the PNG back
// INTO the page as a data URL, draws it on a canvas and reads the pixels --
// then returns the most common one, which is the background rather than a
// glyph. A CSSOM check would only prove a rule was written, not that it won.
async function sampleHighlightColour(page, phrase) {
  const box = await page.evaluate((needle) => {
    const hl = CSS.highlights.get("annotate-read");
    for (const r of hl) {
      if (r.toString() !== needle) continue;
      const b = r.getBoundingClientRect();
      return { x: b.x, y: b.y, width: b.width, height: b.height };
    }
    return null;
  }, phrase);
  if (!box) return null;
  const clip = { x: Math.round(box.x), y: Math.round(box.y),
                 width: Math.max(2, Math.round(box.width)), height: Math.max(2, Math.round(box.height)) };
  const png = await page.screenshot({ clip });
  return page.evaluate((b64) => new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      const tally = new Map();
      for (let i = 0; i < d.length; i += 4) {
        const k = `${d[i]},${d[i + 1]},${d[i + 2]}`;
        tally.set(k, (tally.get(k) || 0) + 1);
      }
      let best = null, n = -1;
      for (const [k, v] of tally) if (v > n) { n = v; best = k; }
      resolve(best);
    };
    img.src = "data:image/png;base64," + b64;
  }), png.toString("base64"));
}
const rgbOf = (hex) => {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(",");
};

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser, beat;
  const cleanup = () => {
    try { clearInterval(beat); } catch (_) {}
    try { browser && browser.close(); } catch (_) {}
    try { proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "hl-e2e-proj-"));
    fs.mkdirSync(path.join(project, "lib"), { recursive: true });
    fs.writeFileSync(path.join(project, "lib", "calc.py"), CALC.join("\n") + "\n");
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    beat = keepAlive(sess.state_dir);
    writeBlocks(sess.response_dir, "resp-hl", "Reading highlighter", [
      { id: "b-0", title: "Two paragraphs", markdown: PARA_ONE + "\n\n" + PARA_TWO },
      { id: "b-1", title: "A block citing code", markdown: "This one has a pane.",
        code: [{ file: "lib/calc.py", line: LINE, snippet: SNIP }] },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 950 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-1"] .cp-row', { timeout: 8000 });
    await page.waitForTimeout(250);
    log("✓ rendered: a two-paragraph block and a code-bearing block");

    // ── 1. Off by default, and OFF MEANS NOT RECORDING ──────────────────────
    // A highlighter that records while "off" and merely declines to paint
    // would ambush the reader with a trail the moment they switched it on.
    const off = await page.evaluate(() => ({
      attr: document.body.dataset.highlighter,
      pressed: document.getElementById("highlighter-toggle").getAttribute("aria-pressed"),
      clearShown: (() => { const c = getComputedStyle(document.getElementById("highlighter-clear"));
        return c.display !== "none" && c.visibility === "visible"; })(),
      toggleX: document.getElementById("highlighter-toggle").getBoundingClientRect().x,
    }));
    if (off.attr === "on") fail("the highlighter is on by default");
    if (off.pressed !== "false") fail("the toggle reports aria-pressed=" + off.pressed + " while off");
    if (off.clearShown) fail("the clear button is visible while the highlighter is off");
    await selectPhrase(page, "b-0", PHRASE);
    if ((await painted(page)).length)
      fail("a selection made while the highlighter was OFF was still recorded");
    log("✓ off by default: no clear button, and a selection records nothing");

    // ── 2. Turning it on ────────────────────────────────────────────────────
    await page.locator("#highlighter-toggle").click();
    await page.waitForTimeout(120);
    const on = await page.evaluate(() => ({
      attr: document.body.dataset.highlighter,
      pressed: document.getElementById("highlighter-toggle").getAttribute("aria-pressed"),
      clearShown: (() => { const c = getComputedStyle(document.getElementById("highlighter-clear"));
        return c.display !== "none" && c.visibility === "visible"; })(),
      toggleX: document.getElementById("highlighter-toggle").getBoundingClientRect().x,
    }));
    if (on.attr !== "on" || on.pressed !== "true") fail("the toggle did not engage: " + JSON.stringify(on));
    if (!on.clearShown) fail("the clear button did not appear with the highlighter on");
    // Revealing the eraser must not move the bar. .header-actions is
    // right-aligned, so a button that takes up space only when visible pushes
    // its neighbours sideways -- measured at 26px, which is exactly enough to
    // slide the eraser under a pointer still resting where it clicked the
    // toggle. The next click would then hit clear-all and wipe the page.
    if (Math.abs(on.toggleX - off.toggleX) > 0.5)
      fail(`the toggle moved ${Math.round(Math.abs(on.toggleX - off.toggleX))}px when the eraser `
        + "appeared — the eraser can land under a stationary cursor, one click from wiping the page");
    log("✓ on: aria-pressed=true, eraser appears, and the bar does not shift");

    // ── 3. A selection paints, and SURVIVES being recorded ──────────────────
    const stillSelected = await selectPhrase(page, "b-0", PHRASE);
    await page.waitForTimeout(120);
    let marks = await painted(page);
    if (marks.length !== 1) fail(`expected one painted range, got ${marks.length}: ${JSON.stringify(marks)}`);
    if (marks[0] !== PHRASE) fail(`painted "${marks[0]}", expected "${PHRASE}"`);
    const liveSel = await page.evaluate(() => window.getSelection().toString());
    if (liveSel !== PHRASE)
      fail(`the selection was consumed (now "${liveSel}") — clicking 💬 would no longer quote it`);
    if (stillSelected !== PHRASE) fail("the selection did not survive the mouseup");
    log(`✓ painted "${PHRASE}" and left the selection intact for the comment flow`);

    // ── 4. An overlapping drag merges instead of stacking ───────────────────
    await selectPhrase(page, "b-0", OVERLAP);
    await page.waitForTimeout(120);
    marks = await painted(page);
    if (marks.length !== 1)
      fail(`an overlapping drag produced ${marks.length} ranges — they stacked instead of merging: `
        + JSON.stringify(marks));
    if (!marks[0].includes(PHRASE) || !marks[0].includes(OVERLAP))
      fail(`the merged range "${marks[0]}" does not cover both drags`);
    log(`✓ overlapping drags merge into one range: "${marks[0]}"`);

    // ── 5. Re-selecting a fully-highlighted stretch erases it ───────────────
    // The same gesture does both, so a mis-drag is fixable without a wipe.
    await selectPhrase(page, "b-0", PHRASE);
    await page.waitForTimeout(120);
    marks = await painted(page);
    const stillHasPhrase = marks.some((m) => m.includes(PHRASE));
    if (stillHasPhrase)
      fail("re-selecting an already-highlighted stretch did not erase it: " + JSON.stringify(marks));
    log("✓ re-selecting an already-highlighted stretch erases it");

    // ── 6. A code pane is not highlightable ─────────────────────────────────
    const beforeCode = (await painted(page)).length;
    await page.evaluate(() => {
      const line = document.querySelector('section.block[data-block-id="b-1"] .cp-line');
      const r = document.createRange();
      r.selectNodeContents(line);
      const sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(r);
      line.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
    await page.waitForTimeout(120);
    if ((await painted(page)).length !== beforeCode)
      fail("a selection inside a code pane was recorded — panes keep their own palette");
    log("✓ a selection inside a code pane records nothing");

    // ── 7. Offsets survive a reload, measured AFTER a hover strip ───────────
    // The case the whole storage design turns on. `.unit-strip` puts button
    // text inside paragraph one; if the offset walker counts it, every offset
    // in paragraph two shifts and the highlight reloads onto the wrong words.
    await page.locator("#highlighter-clear").click();
    await page.waitForTimeout(120);
    await selectPhrase(page, "b-0", PHRASE);
    await page.waitForTimeout(150);
    if ((await painted(page)).join("|") !== PHRASE) fail("setup for the reload case failed");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-1"] .cp-row', { timeout: 8000 });
    await page.waitForTimeout(350);
    const restored = await painted(page);
    if (restored.length !== 1)
      fail(`after reload ${restored.length} ranges were restored, expected 1: ${JSON.stringify(restored)}`);
    if (restored[0] !== PHRASE)
      fail(`the highlight reloaded onto the WRONG WORDS: "${restored[0]}" instead of "${PHRASE}" — `
        + "the offset walker is counting text it should skip (the hover strip lives inside "
        + "paragraph one, before these words)");
    const stateAfterReload = await page.evaluate(() => document.body.dataset.highlighter);
    if (stateAfterReload !== "on") fail("the highlighter itself did not stay on across reload");
    log(`✓ the highlight reloads onto exactly the same words, past a hover strip`);

    // ── 7b. UI text APPEARING later must not shift a stored highlight ──────
    // The reload above is necessary but not sufficient, and proving that took
    // a sabotage run: storing and restoring use the same walker, so if the
    // walker miscounts UI text it miscounts it identically on both sides and
    // the error cancels. The failure only becomes visible when the UI text is
    // not the same at both moments -- which is exactly what happens in real
    // use, because `.unit-chip` (a pinned comment) and `.unit-composer` (an
    // open comment box) appear inside a paragraph AFTER a reader has already
    // highlighted things. So: add UI text ahead of the highlighted words and
    // repaint. If the walker counts it, every offset after it shifts.
    const shifted = await page.evaluate(() => {
      const first = document.querySelector(
        'section.block[data-block-id="b-0"] .block-content p');
      const chip = document.createElement("span");
      chip.className = "unit-chip";
      chip.textContent = "a pinned comment that appeared after the highlight was made";
      first.insertBefore(chip, first.firstChild);
      window.annotateHighlighter.repaint();
      const hl = CSS.highlights.get("annotate-read");
      return [...hl].map((r) => r.toString());
    });
    if (shifted.join("|") !== PHRASE)
      fail(`UI text appearing before the highlighted words moved the highlight to `
        + `${JSON.stringify(shifted)} — the offset walker is counting chrome as prose`);
    log("✓ UI text appearing later does not shift a stored highlight");

    // ── 8. Clear-all ────────────────────────────────────────────────────────
    await page.locator("#highlighter-clear").click();
    await page.waitForTimeout(150);
    if ((await painted(page)).length) fail("clear-all left highlights behind");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(350);
    if ((await painted(page)).length) fail("cleared highlights came back after a reload");
    log("✓ clear-all empties the page, and stays empty across a reload");

    // ── 9. Turning it off stops recording, and unpaints ─────────────────────
    await selectPhrase(page, "b-0", PHRASE);
    await page.waitForTimeout(120);
    if (!(await painted(page)).length) fail("setup for the off case failed");
    await page.locator("#highlighter-toggle").click();
    await page.waitForTimeout(150);
    if ((await painted(page)).length)
      fail("switching the highlighter off left the marks painted");
    await selectPhrase(page, "b-0", OVERLAP);
    await page.waitForTimeout(120);
    if ((await painted(page)).length) fail("a selection was recorded after the highlighter was switched off");
    await page.locator("#highlighter-toggle").click();
    await page.waitForTimeout(150);
    const back = await painted(page);
    if (back.join("|") !== PHRASE)
      fail(`switching back on should restore exactly what was there (${PHRASE}), got ${JSON.stringify(back)}`);
    log("✓ off unpaints and stops recording; on restores exactly what was there");

    // ── 10. Clicking a control does not rub out the highlight ──────────────
    // A drag leaves the stretch selected -- that is the point, so the comment
    // flow can quote it. The very next click therefore arrives with a live
    // selection over already-highlighted text, and a highlighter that treats
    // every mouseup as a reading gesture takes the ERASE branch and destroys
    // the mark that was just made. This is what item 9 caught in practice.
    await page.locator("#highlighter-clear").click();
    await page.waitForTimeout(120);
    await selectPhrase(page, "b-0", PHRASE);
    await page.waitForTimeout(120);
    if ((await painted(page)).join("|") !== PHRASE) fail("setup for the control-click case failed");
    // Click a top-bar control that is NOT the highlighter, so nothing about
    // the outcome depends on the toggle's own handler.
    await page.locator("#width-toggle").click();
    await page.waitForTimeout(150);
    const afterControlClick = await painted(page);
    if (afterControlClick.join("|") !== PHRASE)
      fail(`clicking a top-bar control while the text was still selected changed the highlights `
        + `to ${JSON.stringify(afterControlClick)} — a control click is being treated as a `
        + "reading gesture, and on already-read text that erases");
    log("✓ clicking a control with text still selected leaves the highlight alone");

    // ── 11. The blue sentence-hover wash is gone ───────────────────────────
    // It read as a second kind of highlight sitting next to the real one, in
    // the same family as the selection colour. The hover AFFORDANCE is not
    // the wash — it is the control strip appearing — so that rule stays and
    // is checked here, or removing the wash would quietly remove the cue too.
    const hover = await page.evaluate(() => {
      const unit = document.querySelector('section.block[data-block-id="b-0"] .sub-unit');
      const rules = [];
      for (const sheet of document.styleSheets) {
        let list; try { list = sheet.cssRules; } catch (_) { continue; }
        for (const r of list) if (r.selectorText === ".sub-unit:hover") rules.push(r.cssText);
      }
      return { washRules: rules, hasStrip: !!unit.querySelector(".unit-strip") };
    });
    const washesBackground = hover.washRules.filter((t) => /background/.test(t));
    if (washesBackground.length)
      fail("a .sub-unit:hover background rule is still present: " + JSON.stringify(washesBackground));
    if (!hover.hasStrip) fail("fixture drift: the sentence has no control strip");
    const stripOnHover = await page.evaluate(() => {
      const unit = document.querySelector('section.block[data-block-id="b-0"] .sub-unit');
      const rules = [];
      for (const sheet of document.styleSheets) {
        let list; try { list = sheet.cssRules; } catch (_) { continue; }
        for (const r of list) if (r.selectorText === ".sub-unit:hover .unit-strip") rules.push(r.cssText);
      }
      return rules.length;
    });
    if (!stripOnHover)
      fail("removing the wash also removed `.sub-unit:hover .unit-strip` — hovering a sentence "
        + "no longer reveals its controls at all");
    log("✓ the blue sentence-hover wash is gone, and the strip still reveals on hover");

    // ── 12. The colour picker actually repaints, measured in pixels ─────────
    await page.locator("#highlighter-clear").click();
    await page.waitForTimeout(120);
    await selectPhrase(page, "b-0", PHRASE);
    await page.evaluate(() => window.getSelection().removeAllRanges());
    await page.waitForTimeout(150);
    const asYellow = await sampleHighlightColour(page, PHRASE);
    if (asYellow !== rgbOf("#fcd34d"))
      fail(`the default highlight paints ${asYellow}, expected ${rgbOf("#fcd34d")} (#fcd34d)`);

    await page.locator("#highlighter-palette").click();
    await page.waitForTimeout(150);
    const paletteOpen = await page.evaluate(() => {
      const pop = document.getElementById("palette-pop");
      return { hidden: pop.hidden, swatches: pop.querySelectorAll("[data-color]").length };
    });
    if (paletteOpen.hidden) fail("clicking the swatch did not open the palette");
    if (paletteOpen.swatches < 2) fail("the palette offers " + paletteOpen.swatches + " colours");
    await page.locator('#palette-pop [data-color="pink"]').click();
    await page.evaluate(() => window.getSelection().removeAllRanges());
    await page.waitForTimeout(200);
    if ((await page.evaluate(() => document.body.dataset.highlightColor)) !== "pink")
      fail("picking pink did not set data-highlight-color");
    const asPink = await sampleHighlightColour(page, PHRASE);
    if (asPink !== rgbOf("#f9a8d4"))
      fail(`after picking pink the highlight still paints ${asPink}, expected ${rgbOf("#f9a8d4")} — `
        + "the page-wide colour is not reaching the existing marks");
    log(`✓ the colour picker repaints every mark: measured ${asYellow} → ${asPink} in real pixels`);

    // ── 13. The colour survives a reload ───────────────────────────────────
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(400);
    if ((await page.evaluate(() => document.body.dataset.highlightColor)) !== "pink")
      fail("the chosen highlight colour did not survive a reload");
    const stillPink = await sampleHighlightColour(page, PHRASE);
    if (stillPink !== rgbOf("#f9a8d4"))
      fail(`after reload the highlight paints ${stillPink}, expected pink`);
    log("✓ the chosen colour survives a reload, still measured in pixels");

    // ── 14. The selection goes neutral while the highlighter is on ─────────
    // A blue selection over a marker colour composites into something that
    // reads as a THIRD colour (blue over yellow measured as olive-green). A
    // neutral grey darkens whatever is underneath instead of inventing a hue.
    const selRules = await page.evaluate(() => {
      const out = [];
      for (const sheet of document.styleSheets) {
        let list; try { list = sheet.cssRules; } catch (_) { continue; }
        for (const r of list) {
          if (r.selectorText && /::selection/.test(r.selectorText)
              && /data-highlighter/.test(r.selectorText)) out.push(r.cssText);
        }
      }
      return out;
    });
    if (!selRules.length)
      fail("no ::selection rule scoped to the highlighter being on — a live selection will still "
        + "tint a mark into a colour that is not in the palette");
    if (selRules.some((t) => /\b0,\s*113,\s*227\b/.test(t) || /#0071e3/i.test(t)))
      fail("the highlighter-on selection colour is still the accent blue: " + JSON.stringify(selRules));
    log("✓ the selection goes neutral while the highlighter is on");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
