#!/usr/bin/env node
/*
 * Playwright end-to-end for the fold chords: ⌘K ⌘0 collapses every card,
 * ⌘K ⌘J expands every card, the chord is inert while typing, and the state
 * survives a reload because it goes through the same localStorage keys the
 * per-card chevron writes.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/fold-shortcuts.e2e.cjs
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
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "fold-e2e-home-"));
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
  fs.writeFileSync(tmp, JSON.stringify({ response_id: "resp-fold", title: "fold", blocks }));
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
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "fold-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions", { cwd: project })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));
    writeBlocks(sess.response_dir, deck(null));

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1512, height: 900 } });
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-4"]', { timeout: 8000 });
    log("✓ blocks rendered");

    const collapsedCount = () => page.evaluate(
      () => document.querySelectorAll("section.block.card.collapsed").length);
    const cardCount = await page.evaluate(
      () => document.querySelectorAll("section.block.card").length);
    if (cardCount !== 5) fail("expected 5 cards, got " + cardCount);
    if ((await collapsedCount()) !== 0) fail("cards start collapsed");

    // ── 1. ⌘K arms the chord and shows the pill ────────────────────────────
    await page.keyboard.press("Meta+KeyK");
    const pillShown = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display !== "none");
    if (!pillShown) fail("the ⌘K pill did not appear while the chord is armed");
    log("✓ ⌘K arms, pill visible");

    // ── 2. ⌘0 folds every card, pill goes away ─────────────────────────────
    await page.keyboard.press("Meta+Digit0");
    if ((await collapsedCount()) !== 5) fail("⌘K ⌘0 collapsed " + (await collapsedCount()) + "/5 cards");
    const bodyGone = await page.evaluate(
      () => getComputedStyle(document.querySelector('section.block[data-block-id="b-0"] .card-body')).display);
    if (bodyGone !== "none") fail("collapsed card body still painted: display=" + bodyGone);
    const pillGone = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display === "none");
    if (!pillGone) fail("the pill stayed on screen after the chord resolved");
    log("✓ ⌘K ⌘0 folds all 5, pill dismissed");

    // ── 3. The fold went through the chevron's localStorage keys ───────────
    const stored = await page.evaluate(() => {
      const rid = document.body.dataset.responseId || "default";
      return ["b-0", "b-1", "b-2", "b-3", "b-4"].map(
        (id) => localStorage.getItem(`annotate.collapsed:${rid}:${id}`));
    });
    if (!stored.every((v) => v === "1")) fail("localStorage after fold-all: " + JSON.stringify(stored));
    log("✓ localStorage keys written");

    // ── 4. Fold state survives a reload ────────────────────────────────────
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-4"]', { timeout: 8000 });
    if ((await collapsedCount()) !== 5) fail("fold-all did not survive reload");
    log("✓ fold survives reload");

    // ── 5. ⌘K ⌘J unfolds every card ────────────────────────────────────────
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("Meta+KeyJ");
    if ((await collapsedCount()) !== 0) fail("⌘K ⌘J left " + (await collapsedCount()) + " cards folded");
    log("✓ ⌘K ⌘J unfolds all");

    // ── 6. A non-chord second key disarms without folding ──────────────────
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("KeyX");
    if ((await collapsedCount()) !== 0) fail("stray key after ⌘K folded something");
    const pillOff = await page.evaluate(
      () => getComputedStyle(document.querySelector(".chord-pill")).display === "none");
    if (!pillOff) fail("stray key after ⌘K left the pill armed");
    log("✓ stray second key disarms");

    // ── 7. Inert while typing in the composer ──────────────────────────────
    await page.locator("#composer-toggle").click();
    await page.waitForSelector("#general-input");
    await page.keyboard.press("Meta+KeyK");
    await page.keyboard.press("Meta+Digit0");
    if ((await collapsedCount()) !== 0) fail("the chord fired while typing in the composer");
    log("✓ chord inert while typing");

    // ── 8. The chevron is a 26px round button, not a 14px text glyph ───────
    const chev = await page.evaluate(() => {
      const el = document.querySelector('section.block[data-block-id="b-0"] .card-chevron');
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { w: Math.round(r.width), h: Math.round(r.height),
               radius: cs.borderRadius, border: cs.borderTopStyle };
    });
    if (chev.w !== 26 || chev.h !== 26) fail("chevron is " + chev.w + "×" + chev.h + ", expected 26×26");
    if (chev.radius !== "50%") fail("chevron border-radius = " + chev.radius);
    if (chev.border !== "dashed") fail("chevron border-style = " + chev.border + ", expected dashed");
    log("✓ chevron is a 26×26 round dashed button");

    log("ALL PASS");
  } finally {
    cleanup();
  }
})().catch((e) => { log(String(e && e.stack || e)); process.exit(1); });
