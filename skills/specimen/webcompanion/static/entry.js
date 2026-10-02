/* entry.js — specimen's registered asset entry point. */
(function () {
  "use strict";
  const base = new URL("./", import.meta.url);
  const asset = (name) => new URL(name, base).href;

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = asset("specimen.css");
  document.head.appendChild(link);

  const script = document.createElement("script");
  script.type = "module";
  script.src = asset("specimen.js");
  script.onerror = () => {
    const root = document.querySelector("[data-wc-root]") || document.body;
    root.textContent = "specimen.js failed to load";
  };
  document.body.appendChild(script);
})();
