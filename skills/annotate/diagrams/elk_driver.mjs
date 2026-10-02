// Reads one ELK graph as JSON on stdin, writes the laid-out graph as JSON on
// stdout. A driver, not a renderer: no styling, no fonts, no knowledge of what
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

new ELK()
  .layout(graph)
  .then((out) => {
    process.stdout.write(JSON.stringify(out));
  })
  .catch((e) => {
    process.stderr.write(String((e && e.message) || e));
    process.exit(1);
  });
