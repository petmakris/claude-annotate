// Reads one ELK graph as JSON on stdin, writes the laid-out graph as JSON on
// stdout; or reads an array of graphs and writes an array of results. A driver, not a renderer: no styling, no fonts, no knowledge of what
// the boxes contain. Python measures the text and sends sizes; this returns
// coordinates and edge bend points and nothing else.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
// elk.bundled.js is a UMD build; under createRequire it may hand back either
// the class or a module namespace with it on `default`.
const mod = require("./vendor/elk.bundled.js");
const ELK = mod.default || mod;

let graph;
try {
  graph = JSON.parse(readFileSync(0, "utf8"));
} catch (e) {
  process.stderr.write("bad graph json: " + (e && e.message));
  process.exit(1);
}

const elk = new ELK();
const message = (e) => String((e && e.message) || e);

if (Array.isArray(graph)) {
  // A batch: parsing elk.bundled.js costs more than a diagram-sized layout,
  // so several graphs share one process. One graph failing must not cost the
  // others theirs, so each answers {"ok": out} or {"error": message}.
  (async () => {
    const results = [];
    for (const g of graph) {
      try {
        results.push({ ok: await elk.layout(g) });
      } catch (e) {
        results.push({ error: message(e) });
      }
    }
    process.stdout.write(JSON.stringify(results));
  })();
} else {
  elk
    .layout(graph)
    .then((out) => {
      process.stdout.write(JSON.stringify(out));
    })
    .catch((e) => {
      process.stderr.write(message(e));
      process.exit(1);
    });
}
