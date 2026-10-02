// Loaded by the daemon's shell page after /_wc/core.js.
const css = document.createElement("link");
css.rel = "stylesheet";
css.href = new URL("stage.css", import.meta.url).href;
document.head.append(css);
await import("./stage.js");
