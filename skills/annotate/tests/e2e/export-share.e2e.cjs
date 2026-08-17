#!/usr/bin/env node
/*
 * Playwright end-to-end for the Share button: one click produces a standalone
 * HTML file of the document as rendered.
 *
 * The whole promise is "this file works somewhere I am not", so every
 * assertion here is made against the PRODUCED FILE, opened in a fresh browser
 * page with the server killed. A test that checked the exported markup while
 * the server was still up would pass on a file that is useless the moment it
 * leaves this machine.
 *
 *   1. The file opens with no server, and carries the prose.
 *   2. Diagrams survive — the SVGs are inline, not <img src>.
 *   3. Fonts are data: URIs; the page requests NOTHING over the network.
 *   4. Interactive chrome is gone: no controls, no round dock, no composer.
 *   5. No comment text appears anywhere in the file. Not hidden — ABSENT.
 *      `body.read-only` merely hides comment cards with CSS, so an export
 *      built on that mode would ship every private note to whoever you send
 *      the file to. This is the assertion the feature exists to satisfy.
 *   6. Collapsed blocks come out expanded — the reader does not inherit the
 *      author's fold state.
 *
 * Run:
 *   NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/export-share.e2e.cjs
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

// Unique enough that finding it in the file can only mean the comment leaked.
const SECRET = "SALARY-BAND-DISCUSSION-b7f3e1";

function startServer() {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), "ex-e2e-home-"));
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
    const req = http.request({ host: "127.0.0.1", port, path: urlPath, method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": data.length } },
      (res) => { let b = ""; res.on("data", c => b += c); res.on("end", () => resolve({ status: res.statusCode, body: b })); });
    req.on("error", reject); req.write(data); req.end();
  });
}
function writeBlocks(dir, blocks) {
  const tmp = path.join(dir, "blocks.json.tmp");
  fs.writeFileSync(tmp, JSON.stringify(
    { response_id: "resp-export", title: "Q3 architecture review", blocks }));
  fs.renameSync(tmp, path.join(dir, "blocks.json"));
}

const FLOW_SPEC = {
  title: "How a save is validated",
  nodes: [
    { id: "a", role: "entry", label: "Advisor presses Save" },
    { id: "b", role: "code", ref: "OrderService:154", method: "validate(order)" },
    { id: "c", role: "decision", label: "toggle on?" },
    { id: "d", role: "success", label: "allow" },
  ],
  edges: [{ from: "a", to: "b" }, { from: "b", to: "c" },
          { from: "c", to: "d", label: "off" }],
};
const SEQ_SPEC = {
  actors: [{ id: "ui", label: "Advisor UI" }, { id: "svc", label: "Task service" }],
  steps: [{ id: "s1", from: "ui", to: "svc", arrow: "request", label: "executeTasks" }],
};
const PROSE = [
  "The retry path backs off exponentially before it gives up.",
  "",
  "| Bank | Sends |",
  "| --- | --- |",
  "| JPM | yes |",
  "",
  "```python",
  "def retry(n):",
  "    return n * 2",
  "```",
  "",
  "- a bullet that must survive",
].join("\n");

(async () => {
  const { proc, info, fakeHome } = await startServer();
  let browser;
  let serverDead = false;
  const cleanup = () => {
    try { browser && browser.close(); } catch (_) {}
    try { if (!serverDead) proc.kill(); } catch (_) {}
    try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) {}
  };
  try {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), "ex-e2e-proj-"));
    const sess = JSON.parse((await postJSON(info.port, "/api/sessions",
      { cwd: project, title: "Q3 architecture review" })).body);
    const hb = path.join(sess.state_dir, "watcher_heartbeat");
    const beat = setInterval(() => { try { fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000))); } catch (_) {} }, 500);
    fs.writeFileSync(hb, String(Math.floor(Date.now() / 1000)));

    writeBlocks(sess.response_dir, [
      { id: "b-0", title: "The retry path", markdown: PROSE },
      { id: "b-1", title: "How a save is validated", kind: "flowchart", spec: FLOW_SPEC },
      { id: "b-2", title: "The call sequence", kind: "sequence", spec: SEQ_SPEC },
      { id: "b-3", title: "A folded aside", markdown: "Folded prose that must still be exported." },
    ]);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", (e) => log("PAGE ERROR: " + e.message));
    await page.goto(sess.url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('section.block[data-block-id="b-3"]', { timeout: 8000 });
    log("✓ document rendered");

    // Seed a private comment. This is the thing that must not travel.
    //
    // A UNIT comment specifically: pinning one renders its full text as a
    // .unit-chip span INSIDE main.prose, which is the subtree the export
    // clones. A block-scope comment would only reach the round dock, which
    // sits outside main.prose and is dropped for free — a leak test built on
    // that would pass without the export doing any work.
    const b0 = page.locator('section.block[data-block-id="b-0"]');
    const para = b0.locator("p.sub-unit").first();
    await para.hover();
    await para.locator('.unit-strip button[data-kind="comment"]').click();
    await page.waitForSelector(".unit-composer input", { timeout: 5000 });
    await page.fill(".unit-composer input", SECRET);
    await page.locator(".unit-composer button", { hasText: "Pin" }).click();
    await sleep(400);
    const chip = await page.locator(".unit-chip-text").first().innerText();
    if (!chip.includes(SECRET))
      fail("the comment never reached a chip in main.prose — the leak test would be vacuous");
    const proseHtml = await page.locator("main.prose").innerHTML();
    if (!proseHtml.includes(SECRET))
      fail("the comment is not in the cloned subtree — the leak test would be vacuous");
    log("✓ a private comment sits inside main.prose, exactly where an export would copy it");

    // Fold a block, so the export has a fold state to ignore.
    await page.locator('section.block[data-block-id="b-3"] .card-chevron').click();
    await sleep(200);
    if (!(await page.locator('section.block[data-block-id="b-3"].collapsed').count()))
      fail("could not fold b-3 — the un-collapse assertion would be vacuous");
    log("✓ one block folded");

    // ── The click ───────────────────────────────────────────────────────────
    const outFile = path.join(project, "shared.html");
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      page.locator("#export-btn").click(),
    ]);
    const suggested = download.suggestedFilename();
    await download.saveAs(outFile);
    log(`✓ one click produced ${suggested}`);
    if (!/\.html$/.test(suggested)) fail("the download is not named as HTML: " + suggested);

    const html = fs.readFileSync(outFile, "utf8");
    log(`  file is ${(html.length / 1024).toFixed(0)} KB`);

    // ── 5. the leak test, against the file's SOURCE ─────────────────────────
    if (html.includes(SECRET))
      fail("the private comment travelled inside the shared file");
    log("✓ no comment text anywhere in the file");

    // ── 3a. every font is embedded ──────────────────────────────────────────
    if (/url\(['"]?\/static\//.test(html))
      fail("the file still points at /static/ on the origin server");
    if (!html.includes("data:font/woff2;base64,"))
      fail("fonts were not embedded as data: URIs");
    // Each font must be embedded ONCE. The Bricolage @font-face names the same
    // file twice — `format('woff2-variations')` then `format('woff2')` — so a
    // naive replace-every-occurrence inlines 408KB of font twice and adds half
    // a megabyte to every file the user sends.
    const payloads = html.match(/data:font\/woff2;base64,[A-Za-z0-9+/=]+/g) || [];
    const unique = new Set(payloads);
    if (payloads.length !== unique.size)
      fail(`a font is embedded ${payloads.length} times but only ${unique.size} are distinct`);
    const kb = html.length / 1024;
    if (kb > 1100) fail(`the shared file is ${kb.toFixed(0)} KB — something is embedded twice`);
    log(`✓ ${unique.size} fonts embedded exactly once, no /static/ references`);

    // ── Exporting mid-search must not silently drop blocks ──────────────────
    // A search hides every non-matching section with a class. If the export
    // just copied the DOM, the file would quietly contain only what happened
    // to match — the worst kind of bug, because the author sees a full page
    // and the reader gets a truncated one.
    await page.fill("#block-search", "exponentially");
    await sleep(600);
    if (!(await page.locator('section.block[data-block-id="b-1"].search-hidden').count()))
      fail("the search did not filter anything — this assertion would be vacuous");
    const outFiltered = path.join(project, "filtered.html");
    const [dl2] = await Promise.all([
      page.waitForEvent("download", { timeout: 20000 }),
      page.locator("#export-btn").click(),
    ]);
    await dl2.saveAs(outFiltered);
    const filtered = fs.readFileSync(outFiltered, "utf8");
    for (const needle of ["How a save is validated", "The call sequence",
                          "A folded aside", "backs off exponentially"]) {
      if (!filtered.includes(needle))
        fail(`exporting during a search dropped: ${needle}`);
    }
    // Scoped to the MARKUP, not the whole file: the inlined stylesheet
    // legitimately defines `.search-hidden` and `mark.search-hit` as
    // selectors, so a naive whole-file search matches the CSS and fails on
    // a perfectly good export.
    const markup = filtered.slice(filtered.lastIndexOf("</style>"));
    if (markup.includes("search-hidden"))
      fail("the export carried the search's hidden-block class into the markup");
    if (markup.includes("search-hit"))
      fail("the export baked the search highlight marks into the markup");
    log("✓ exporting mid-search still contains every block, unhighlighted");
    await page.fill("#block-search", "");
    await sleep(300);

    // ── Kill the server. Everything below runs with nothing to fall back on ──
    clearInterval(beat);
    proc.kill();
    serverDead = true;
    await sleep(700);

    const viewer = await browser.newPage();
    const attempted = [];
    viewer.on("request", (r) => {
      const u = r.url();
      if (/^https?:/i.test(u)) attempted.push(u);
    });
    viewer.on("pageerror", (e) => log("EXPORTED PAGE ERROR: " + e.message));
    await viewer.goto("file://" + outFile, { waitUntil: "load" });
    await sleep(600);

    // ── 1. the prose ────────────────────────────────────────────────────────
    const text = await viewer.locator("body").innerText();
    for (const needle of ["backs off exponentially", "a bullet that must survive",
                          "Q3 architecture review"]) {
      if (!text.includes(needle)) fail(`the exported file is missing: ${needle}`);
    }
    if (!(await viewer.locator("table").count())) fail("the table did not survive");
    if (!(await viewer.locator("pre code").count())) fail("the code block did not survive");
    log("✓ opens with no server, and the prose/table/code are all there");

    // ── 6. the folded block came out expanded ───────────────────────────────
    if (!text.includes("Folded prose that must still be exported"))
      fail("a block folded by the author was exported folded (or dropped)");
    log("✓ the author's fold state was not inherited");

    // ── 2. diagrams ─────────────────────────────────────────────────────────
    const flowNodes = await viewer.locator("svg.annotate-flow g.node").count();
    const seqRows = await viewer.locator("svg.annotate-seq g.step-row").count();
    if (flowNodes < 4) fail(`the flowchart lost its nodes: ${flowNodes}`);
    if (!seqRows) fail("the sequence diagram did not survive");
    if (!text.includes("OrderService:154")) fail("a flowchart code ref was lost");
    log(`✓ diagrams inline and intact (${flowNodes} flow nodes, ${seqRows} step rows)`);

    // ── 3b. nothing was fetched ─────────────────────────────────────────────
    if (attempted.length)
      fail("the exported file reached out to the network: " + JSON.stringify(attempted.slice(0, 4)));
    log("✓ zero network requests");

    // ── 4. no interactive chrome ────────────────────────────────────────────
    for (const sel of [".hover-actions", ".unit-strip", ".comment-card", "#round-dock",
                       ".general-composer", ".card-chevron",
                       // The two header panel toggles and the panel one of them
                       // opens: live chrome that would arrive in a shared file
                       // as buttons wired to nothing.
                       "#composer-toggle", "#legend-toggle", ".legend-pop",
                       ".unit-composer", "#block-search", "#export-btn"]) {
      const n = await viewer.locator(sel).count();
      if (n) fail(`the export still carries ${n} × ${sel}`);
    }
    log("✓ no controls, dock, composer or search in the shared file");

    log("\nE2E PASSED");
    cleanup();
    process.exit(0);
  } catch (err) {
    log("\nE2E FAILED: " + (err && err.stack ? err.stack : err));
    cleanup();
    process.exit(1);
  }
})();
