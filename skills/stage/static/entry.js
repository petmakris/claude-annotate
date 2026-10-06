// Loaded by the daemon's shell page after /_wc/core.js.
const add = (attrs) => { const l = document.createElement("link"); Object.assign(l, attrs); document.head.append(l); };
// The same fonts as the talk page, so the two read as one page.
add({ rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "" });
add({ rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" });
add({ rel: "stylesheet", href: new URL("stage.css", import.meta.url).href });
await import("./stage.js");
