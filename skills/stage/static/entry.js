// Loaded by the daemon's shell page after /_wc/core.js.
const add = (attrs) => { const l = document.createElement("link"); Object.assign(l, attrs); document.head.append(l); };
// Geist ships beside these files (stage.css), and visuals.css draws the shared sequence and flowchart tools.
add({ rel: "stylesheet", href: new URL("visuals.css", import.meta.url).href });
add({ rel: "stylesheet", href: new URL("stage.css", import.meta.url).href });
await import("./stage.js");
