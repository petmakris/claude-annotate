// A small DOM, enough to run the stage's and the call page's own JavaScript under node, with no browser.
//
// It parses and serialises HTML, matches the selectors those pages use (tags, ids, classes, attributes,
// :scope, :not, descendant and child), keeps classes, data attributes, inline style and events, and lays
// nothing out: every box measures 0. Time is virtual: setTimeout, setInterval and requestAnimationFrame
// run only when a test calls settle() or advance(ms), so a run is the same every time.
//
// What a test can check through it is logic: which elements carry which classes and attributes, what a
// page posts, which frame a board is on. Anything measured (overlap, contrast, scroll positions) needs a
// real browser and is not checked here.

const realImmediate = globalThis.setImmediate;
const SVG_NS = "http://www.w3.org/2000/svg";
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const RAW = new Set(["script", "style", "textarea", "title"]);
const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
const decode = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => (e[0] === "#"
  ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : +e.slice(1)) : ENT[e.toLowerCase()] ?? m));
const escText = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
const escAttr = (s) => s.replace(/[&"]/g, (c) => ({ "&": "&amp;", '"': "&quot;" })[c]);
const kebab = (p) => p.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
const camel = (p) => p.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

// ---- events ---------------------------------------------------------------------------------------

export class ShimEvent {
  constructor(type, init = {}) {
    Object.assign(this, { bubbles: false, cancelable: true }, init);
    this.type = type; this.defaultPrevented = false; this.target = init.target ?? null; this._stop = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
  stopImmediatePropagation() { this._stop = true; }
}

class Target {
  constructor() { this._ls = new Map(); }
  addEventListener(type, fn, opts) {
    if (!fn) return;
    const once = typeof opts === "object" && !!opts?.once;
    if (!this._ls.has(type)) this._ls.set(type, []);
    this._ls.get(type).push({ fn, once });
  }
  removeEventListener(type, fn) {
    const l = this._ls.get(type);
    if (l) this._ls.set(type, l.filter((x) => x.fn !== fn));
  }
  _fire(ev) {
    ev.currentTarget = this;
    for (const l of [...(this._ls.get(ev.type) || [])]) {
      if (l.once) this.removeEventListener(ev.type, l.fn);
      typeof l.fn === "function" ? l.fn.call(this, ev) : l.fn.handleEvent(ev);
    }
    const on = this["on" + ev.type];
    if (typeof on === "function") on.call(this, ev);
  }
  dispatchEvent(ev) {
    if (!ev.target) ev.target = this;
    for (let at = this; at && !ev._stop; at = ev.bubbles ? at._up() : null) at._fire(ev);
    return !ev.defaultPrevented;
  }
  _up() { return null; }
}

// ---- nodes ----------------------------------------------------------------------------------------

class Node extends Target {
  constructor(doc) { super(); this.ownerDocument = doc; this.parentNode = null; this.childNodes = []; }
  _up() { return this.parentNode || (this === this.ownerDocument ? win : null); }
  get parentElement() { return this.parentNode instanceof Element ? this.parentNode : null; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === this.ownerDocument; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get nextSibling() { const s = this.parentNode?.childNodes; return s ? s[s.indexOf(this) + 1] || null : null; }
  get previousSibling() { const s = this.parentNode?.childNodes; return s ? s[s.indexOf(this) - 1] || null : null; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(t) { this.replaceChildren(...(String(t ?? "") ? [new Text(this.ownerDocument, String(t))] : [])); }
  _adopt(nodes) {
    return nodes.flatMap((n) => {
      if (n instanceof Fragment) { const kids = [...n.childNodes]; for (const k of kids) k.remove(); return kids; }
      const node = n instanceof Node ? n : new Text(this.ownerDocument, String(n));
      node.remove();
      return [node];
    });
  }
  _insert(nodes, at) {
    const kids = this._adopt(nodes);
    if (at === undefined || at < 0) at = this.childNodes.length;
    this.childNodes.splice(at, 0, ...kids);
    for (const k of kids) k.parentNode = this;
  }
  append(...nodes) { this._insert(nodes); }
  prepend(...nodes) { this._insert(nodes, 0); }
  appendChild(n) { this._insert([n]); return n; }
  removeChild(n) { n.remove(); return n; }
  insertBefore(n, ref) { if (n === ref) return n; this._insert([n], ref ? this.childNodes.indexOf(ref) : undefined); if (ref && n.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(n), 1); this.childNodes.splice(this.childNodes.indexOf(ref), 0, n); } return n; }
  replaceChildren(...nodes) { for (const c of [...this.childNodes]) c.remove(); this._insert(nodes); }
  remove() {
    const p = this.parentNode; if (!p) return;
    p.childNodes.splice(p.childNodes.indexOf(this), 1); this.parentNode = null;
  }
  before(...nodes) { const p = this.parentNode; if (p) { const kids = p._adopt(nodes.filter((n) => n !== this)); p.childNodes.splice(p.childNodes.indexOf(this), 0, ...kids); for (const k of kids) k.parentNode = p; } }
  after(...nodes) { const p = this.parentNode; if (p) { const kids = p._adopt(nodes.filter((n) => n !== this)); p.childNodes.splice(p.childNodes.indexOf(this) + 1, 0, ...kids); for (const k of kids) k.parentNode = p; } }
  replaceWith(...nodes) { this.before(...nodes); this.remove(); }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  get childElementCount() { return this.children.length; }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { const c = this.children; return c[c.length - 1] || null; }
  get nextElementSibling() { const s = this.parentNode?.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  get previousElementSibling() { const s = this.parentNode?.children; return s ? s[s.indexOf(this) - 1] || null : null; }
  _all() { const out = []; const walk = (n) => { for (const c of n.children) { out.push(c); walk(c); } }; walk(this); return out; }
  querySelectorAll(sel) { const list = parseSelectors(sel); return this._all().filter((e) => matchList(e, list, this)); }
  querySelector(sel) { const list = parseSelectors(sel); return this._all().find((e) => matchList(e, list, this)) || null; }
  getElementsByTagName(t) { return this.querySelectorAll(t); }
  getElementsByClassName(c) { return this.querySelectorAll(c.trim().split(/\s+/).map((x) => "." + x).join("")); }
}

class Text extends Node {
  constructor(doc, data) { super(doc); this.data = data; this.nodeType = 3; }
  get textContent() { return this.data; }
  set textContent(t) { this.data = String(t); }
  get nodeValue() { return this.data; }
  cloneNode() { return new Text(this.ownerDocument, this.data); }
  get _html() { return this.parentNode && RAW.has(this.parentNode.localName) ? this.data : escText(this.data); }
}

class Fragment extends Node {}

class ClassList {
  constructor(el) { this.el = el; }
  _get() { return (this.el.getAttribute("class") || "").split(/\s+/).filter(Boolean); }
  _set(list) { this.el.setAttribute("class", [...new Set(list)].join(" ")); }
  add(...c) { this._set([...this._get(), ...c]); }
  remove(...c) { if (this.el.hasAttribute("class")) this._set(this._get().filter((x) => !c.includes(x))); }
  contains(c) { return this._get().includes(c); }
  toggle(c, force) { const on = force === undefined ? !this.contains(c) : !!force; if (on) this.add(c); else this.remove(c); return on; }
  replace(a, b) { if (!this.contains(a)) return false; this._set(this._get().map((x) => (x === a ? b : x))); return true; }
  get length() { return this._get().length; }
  get value() { return this._get().join(" "); }
  item(i) { return this._get()[i] ?? null; }
  [Symbol.iterator]() { return this._get()[Symbol.iterator](); }
}

// Inline style: named properties as the page sets them, custom properties through setProperty.
function makeStyle() {
  const props = new Map();
  const api = {
    setProperty(name, value) { props.set(name.startsWith("--") ? name : kebab(camel(name)), String(value)); },
    getPropertyValue(name) { return props.get(name.startsWith("--") ? name : kebab(camel(name))) ?? ""; },
    removeProperty(name) { const k = name.startsWith("--") ? name : kebab(camel(name)); const v = props.get(k) ?? ""; props.delete(k); return v; },
    get cssText() { return [...props].map(([k, v]) => `${k}: ${v};`).join(" "); },
    set cssText(t) { props.clear(); for (const part of String(t).split(";")) { const i = part.indexOf(":"); if (i > 0) props.set(part.slice(0, i).trim(), part.slice(i + 1).trim()); } },
    _props: props,
  };
  return new Proxy(api, {
    get(t, p) { if (p in t || typeof p === "symbol") return t[p]; return props.get(kebab(p)) ?? ""; },
    set(t, p, v) { if (p === "cssText") { t.cssText = v; return true; } if (v === "" || v == null) props.delete(kebab(p)); else props.set(kebab(p), String(v)); return true; },
  });
}

const RECT = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON() { return { ...this }; } });

export class Element extends Node {
  constructor(doc, name, ns = null) {
    super(doc);
    this.namespaceURI = ns;
    this.localName = ns === SVG_NS ? name : name.toLowerCase();
    this.tagName = ns === SVG_NS ? name : name.toUpperCase();
    this.nodeType = 1;
    this.attrs = new Map();
    this.classList = new ClassList(this);
    this.style = makeStyle();
    this.scrollTop = 0; this.scrollLeft = 0; this.clientWidth = 0; this.clientHeight = 0;
    this.dataset = new Proxy({}, {
      get: (_, p) => (typeof p === "string" ? this.getAttribute("data-" + kebab(p)) ?? undefined : undefined),
      set: (_, p, v) => { this.setAttribute("data-" + kebab(p), v); return true; },
      deleteProperty: (_, p) => { this.removeAttribute("data-" + kebab(p)); return true; },
      has: (_, p) => this.hasAttribute("data-" + kebab(p)),
      ownKeys: () => [...this.attrs.keys()].filter((k) => k.startsWith("data-")).map((k) => camel(k.slice(5))),
      getOwnPropertyDescriptor: (_, p) => (this.hasAttribute("data-" + kebab(p)) ? { value: this.getAttribute("data-" + kebab(p)), enumerable: true, configurable: true } : undefined),
    });
  }
  _name(n) { return this.namespaceURI === SVG_NS ? n : n.toLowerCase(); }
  getAttribute(n) { return this.attrs.has(this._name(n)) ? this.attrs.get(this._name(n)) : null; }
  setAttribute(n, v) { n = this._name(n); v = String(v); this.attrs.set(n, v); if (n === "style") this.style.cssText = v; }
  removeAttribute(n) { n = this._name(n); this.attrs.delete(n); if (n === "style") this.style.cssText = ""; }
  hasAttribute(n) { return this.attrs.has(this._name(n)); }
  toggleAttribute(n, force) { const on = force === undefined ? !this.hasAttribute(n) : !!force; if (on) { if (!this.hasAttribute(n)) this.setAttribute(n, ""); } else this.removeAttribute(n); return on; }
  get attributes() { return [...this.attrs].map(([name, value]) => ({ name, value })); }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get hidden() { return this.hasAttribute("hidden"); }
  set hidden(v) { this.toggleAttribute("hidden", !!v); }
  get disabled() { return this.hasAttribute("disabled"); }
  set disabled(v) { this.toggleAttribute("disabled", !!v); }
  get value() { return this._value ?? this.getAttribute("value") ?? (this.localName === "textarea" ? this.textContent : ""); }
  set value(v) { this._value = String(v); }
  get innerText() { return this.textContent; }
  set innerText(t) { this.textContent = t; }
  get innerHTML() { return this.childNodes.map(html).join(""); }
  set innerHTML(h) { this.replaceChildren(...parseHTML(String(h), this.ownerDocument, this.namespaceURI === SVG_NS || this.localName === "svg")); }
  get outerHTML() { return html(this); }
  insertAdjacentHTML(where, h) {
    const nodes = parseHTML(String(h), this.ownerDocument, this.namespaceURI === SVG_NS);
    if (where === "afterbegin") this.prepend(...nodes);
    else if (where === "beforeend") this.append(...nodes);
    else if (where === "beforebegin") this.before(...nodes);
    else this.after(...nodes);
  }
  cloneNode(deep = false) {
    const c = this.ownerDocument._make(this.localName, this.namespaceURI);
    for (const [k, v] of this.attrs) c.setAttribute(k, v);
    for (const [k, v] of this.style._props) c.style.setProperty(k, v);
    if (deep) c.append(...this.childNodes.map((n) => n.cloneNode(true)));
    return c;
  }
  matches(sel) { return matchList(this, parseSelectors(sel), this); }
  closest(sel) { const list = parseSelectors(sel); for (let e = this; e instanceof Element; e = e.parentNode) if (matchList(e, list, e)) return e; return null; }
  click() { if (this.disabled) return; this.dispatchEvent(new ShimEvent("click", { bubbles: true })); }
  focus() { this.ownerDocument.activeElement = this; }
  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body; }
  getBoundingClientRect() { return RECT(); }
  getClientRects() { return []; }
  getBBox() { return { x: 0, y: 0, width: 0, height: 0 }; }
  beginElement() {}
  select() {}
  scrollTo(a, b) { if (typeof a === "object") { if (a.top != null) this.scrollTop = a.top; if (a.left != null) this.scrollLeft = a.left; } else { this.scrollLeft = a; this.scrollTop = b; } }
  scrollIntoView() {}
  get offsetWidth() { return 0; }
  get offsetHeight() { return 0; }
  get offsetTop() { return 0; }
  get offsetLeft() { return 0; }
  get offsetParent() { return null; }
  get scrollHeight() { return 0; }
  get scrollWidth() { return 0; }
}
for (const p of ["id", "title", "href", "src", "type", "rel", "target", "name", "placeholder", "role", "lang", "alt"]) {
  Object.defineProperty(Element.prototype, p, {
    get() { return this.getAttribute(p) ?? ""; }, set(v) { this.setAttribute(p, v); }, configurable: true,
  });
}

// An <iframe>'s window: what is posted to it is kept, in order, as the page it holds would receive it.
class FrameElement extends Element {
  get contentWindow() { return this._win ||= { posted: [], postMessage(m) { this.posted.push(JSON.parse(JSON.stringify(m))); } }; }
  get contentDocument() { return null; }
}

// An <audio>: playing, pausing, seeking and ending are what a test does to it, and fire the events a browser would.
export class MediaElement extends Element {
  constructor(doc, name) { super(doc, name); this.paused = true; this.ended = false; this._t = 0; this.duration = NaN; this.playbackRate = 1; this.preservesPitch = true; this.volume = 1; }
  get currentTime() { return this._t; }
  set currentTime(t) { this._t = Number(t) || 0; this.ended = false; this.dispatchEvent(new ShimEvent("seeking")); setTimeout(() => this.dispatchEvent(new ShimEvent("seeked")), 0); }
  // with no source a browser refuses to play; one that played to its end starts again from the top
  play() {
    if (!this.getAttribute("src")) return Promise.reject(Object.assign(new Error("no supported source"), { name: "NotSupportedError" }));
    if (this.ended) this.currentTime = 0;
    if (this.paused) { this.paused = false; this.dispatchEvent(new ShimEvent("play")); }
    return Promise.resolve();
  }
  pause() { if (!this.paused) { this.paused = true; this.dispatchEvent(new ShimEvent("pause")); } }
  load() {}
  // the end of the answer: played to its last word
  end() { this._t = this.duration || this._t; if (!this.paused) { this.paused = true; this.dispatchEvent(new ShimEvent("pause")); } this.ended = true; this.dispatchEvent(new ShimEvent("ended")); }
}

class Document extends Node {
  constructor() {
    super(null);
    this.ownerDocument = this;
    this.nodeType = 9;
    this.documentElement = this._make("html");
    this.head = this._make("head"); this.body = this._make("body");
    this.documentElement.append(this.head, this.body);
    this.childNodes = [this.documentElement]; this.documentElement.parentNode = this;
    this.activeElement = this.body;
    this.title = ""; this.hidden = false; this.visibilityState = "visible";
    this.fullscreenElement = null; this.fullscreenEnabled = false;
  }
  _make(name, ns = null) {
    const n = ns === SVG_NS ? name : name.toLowerCase();
    if (n === "iframe") return new FrameElement(this, name);
    if (n === "audio" || n === "video") return new MediaElement(this, name);
    return new Element(this, name, ns);
  }
  createElement(name) { return this._make(name); }
  createElementNS(ns, name) { return this._make(name, ns); }
  createTextNode(t) { return new Text(this, String(t)); }
  createDocumentFragment() { return new Fragment(this); }
  getElementById(id) { return this._all().find((e) => e.getAttribute("id") === id) || null; }
  execCommand() { return false; }
}

// ---- HTML ------------------------------------------------------------------------------------------

function html(n) {
  if (n instanceof Text) return n._html;
  const attrs = [...n.attrs].map(([k, v]) => (v === "" && k !== "class" ? ` ${k}` : ` ${k}="${escAttr(v)}"`)).join("");
  if (VOID.has(n.localName) && n.namespaceURI !== SVG_NS) return `<${n.localName}${attrs}>`;
  return `<${n.localName}${attrs}>${n.childNodes.map(html).join("")}</${n.localName}>`;
}

const ATTR = /\s*([^\s=/>"']+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/y;
function parseHTML(src, doc, inSvg = false) {
  const top = new Fragment(doc), stack = [top];
  const svgDepth = [];
  let i = 0;
  const here = () => stack[stack.length - 1];
  const text = (t) => { if (t) here().append(new Text(doc, decode(t))); };
  while (i < src.length) {
    if (src.startsWith("<!--", i)) { const e = src.indexOf("-->", i + 4); i = e < 0 ? src.length : e + 3; continue; }
    if (src.startsWith("<!", i)) { const e = src.indexOf(">", i); i = e < 0 ? src.length : e + 1; continue; }
    if (src[i] === "<" && src[i + 1] === "/" && /[A-Za-z]/.test(src[i + 2] || "")) {
      const e = src.indexOf(">", i), name = src.slice(i + 2, e).trim().toLowerCase();
      const at = stack.map((n) => n.localName?.toLowerCase()).lastIndexOf(name);
      if (at > 0) stack.length = at;
      if (name === "svg") svgDepth.pop();
      i = e + 1; continue;
    }
    if (src[i] === "<" && /[A-Za-z]/.test(src[i + 1] || "")) {
      const m = /^<([A-Za-z][\w:-]*)/.exec(src.slice(i, i + 64));
      const name = m[1];
      let j = i + m[0].length;
      const attrs = [];
      for (;;) {
        ATTR.lastIndex = j;
        const a = ATTR.exec(src);
        if (!a || !a[0].trim()) break;
        attrs.push([a[1], decode(a[2] ?? a[3] ?? a[4] ?? "")]);
        j = ATTR.lastIndex;
      }
      while (j < src.length && /\s/.test(src[j])) j++;
      const selfClose = src[j] === "/";
      const end = src.indexOf(">", j);
      const svg = inSvg || svgDepth.length > 0 || name.toLowerCase() === "svg";
      const el = doc._make(svg ? name : name.toLowerCase(), svg ? SVG_NS : null);
      for (const [k, v] of attrs) el.setAttribute(k, v);
      here().append(el);
      i = end + 1;
      const lower = name.toLowerCase();
      if (selfClose || (!svg && VOID.has(lower))) continue;
      if (!svg && RAW.has(lower)) {
        const close = src.toLowerCase().indexOf(`</${lower}`, i);
        const body = src.slice(i, close < 0 ? src.length : close);
        if (body) el.append(new Text(doc, lower === "textarea" || lower === "title" ? decode(body) : body));
        i = close < 0 ? src.length : src.indexOf(">", close) + 1;
        continue;
      }
      if (lower === "svg") svgDepth.push(1);
      stack.push(el);
      continue;
    }
    const next = src.indexOf("<", i + 1);
    const stop = next < 0 ? src.length : next;
    text(src.slice(i, stop));
    i = stop;
  }
  return [...top.childNodes];
}

// ---- selectors -------------------------------------------------------------------------------------

const selCache = new Map();
function parseSelectors(sel) {
  if (selCache.has(sel)) return selCache.get(sel);
  const list = splitTop(sel, ",").map((s) => parseComplex(s.trim()));
  selCache.set(sel, list);
  return list;
}
// split on `ch` outside brackets, parentheses and quotes
function splitTop(s, ch) {
  const out = []; let depth = 0, q = null, cur = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q) { cur += c; if (c === "\\") { cur += s[++i] ?? ""; } else if (c === q) q = null; continue; }
    if (c === '"' || c === "'") { q = c; cur += c; continue; }
    if (c === "[" || c === "(") depth++;
    if (c === "]" || c === ")") depth--;
    if (c === ch && depth === 0) { out.push(cur); cur = ""; continue; }
    cur += c;
  }
  out.push(cur);
  return out;
}
// [{comb, compound}], left to right; comb is how this compound relates to the one before it
function parseComplex(s) {
  const parts = []; let comb = null, i = 0, cur = "";
  const flush = () => { if (cur.trim()) { parts.push({ comb, compound: parseCompound(cur.trim()) }); comb = " "; } cur = ""; };
  let depth = 0, q = null;
  for (; i < s.length; i++) {
    const c = s[i];
    if (q) { cur += c; if (c === "\\") cur += s[++i] ?? ""; else if (c === q) q = null; continue; }
    if (c === '"' || c === "'") { q = c; cur += c; continue; }
    if (c === "[" || c === "(") depth++;
    if (c === "]" || c === ")") depth--;
    if (depth === 0 && (c === ">" || c === "+" || c === "~")) { flush(); comb = c; continue; }
    if (depth === 0 && /\s/.test(c)) { if (cur.trim()) { flush(); } continue; }
    cur += c;
  }
  flush();
  if (parts.length) parts[0].comb = null;
  return parts;
}
const unescape = (s) => s.replace(/\\(.)/g, "$1");
function parseCompound(s) {
  const c = { tag: null, ids: [], classes: [], attrs: [], nots: [], scope: false };
  let i = 0;
  const ident = () => { let out = ""; while (i < s.length && /[\w\- -￿\\]/.test(s[i])) { if (s[i] === "\\") { out += s[i + 1]; i += 2; } else out += s[i++]; } return out; };
  if (s[i] === "*") i++;
  else if (/[A-Za-z]/.test(s[i])) c.tag = ident().toLowerCase();
  while (i < s.length) {
    const ch = s[i];
    if (ch === ".") { i++; c.classes.push(ident()); }
    else if (ch === "#") { i++; c.ids.push(ident()); }
    else if (ch === "[") {
      let j = i + 1, q = null, body = "";
      for (; j < s.length; j++) { const d = s[j]; if (q) { if (d === "\\") { body += d + s[++j]; continue; } if (d === q) q = null; body += d; continue; } if (d === '"' || d === "'") { q = d; body += d; continue; } if (d === "]") break; body += d; }
      i = j + 1;
      const m = /^\s*([^\s~|^$*=]+)\s*(?:([~|^$*]?=)\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([^\s\]]+)))?\s*$/.exec(body);
      c.attrs.push({ name: m[1], op: m[2] || null, val: m[2] ? unescape(m[3] ?? m[4] ?? m[5]) : null });
    } else if (ch === ":") {
      i++;
      const name = ident();
      if (s[i] === "(") {
        let depth = 1, j = i + 1;
        for (; j < s.length && depth; j++) { if (s[j] === "(") depth++; else if (s[j] === ")") depth--; }
        const arg = s.slice(i + 1, j - 1);
        i = j;
        if (name === "not") c.nots.push(parseSelectors(arg));
        else throw new Error("dom_shim: no :" + name + "()");
      } else if (name === "scope") c.scope = true;
      else throw new Error("dom_shim: no :" + name);
    } else throw new Error("dom_shim: cannot read selector " + JSON.stringify(s));
  }
  return c;
}
function matchCompound(e, c, scope) {
  if (!(e instanceof Element)) return false;
  if (c.scope && e !== scope) return false;
  if (c.tag && e.localName.toLowerCase() !== c.tag) return false;
  for (const id of c.ids) if (e.getAttribute("id") !== id) return false;
  if (c.classes.length) { const have = e.classList._get(); for (const k of c.classes) if (!have.includes(k)) return false; }
  for (const a of c.attrs) {
    const v = e.getAttribute(a.name);
    if (v === null) return false;
    if (a.op === "=" && v !== a.val) return false;
    if (a.op === "^=" && !v.startsWith(a.val)) return false;
    if (a.op === "$=" && !v.endsWith(a.val)) return false;
    if (a.op === "*=" && !v.includes(a.val)) return false;
    if (a.op === "~=" && !v.split(/\s+/).includes(a.val)) return false;
  }
  for (const n of c.nots) if (matchList(e, n, scope)) return false;
  return true;
}
function matchComplex(e, parts, k, scope) {
  if (!matchCompound(e, parts[k].compound, scope)) return false;
  if (k === 0) return true;
  const comb = parts[k].comb;
  if (comb === ">") return matchComplex(e.parentNode, parts, k - 1, scope);
  if (comb === " ") { for (let p = e.parentNode; p instanceof Element; p = p.parentNode) if (matchComplex(p, parts, k - 1, scope)) return true; return false; }
  if (comb === "+") return matchComplex(e.previousElementSibling, parts, k - 1, scope);
  if (comb === "~") { for (let p = e.previousElementSibling; p; p = p.previousElementSibling) if (matchComplex(p, parts, k - 1, scope)) return true; return false; }
  return false;
}
function matchList(e, list, scope) { return list.some((parts) => parts.length && matchComplex(e, parts, parts.length - 1, scope)); }

// ---- time --------------------------------------------------------------------------------------------

let clock = 0, nextId = 1;
const timers = new Map();   // id -> {at, fn, args, every}
let rafs = [];
const flushMicrotasks = async () => { for (let k = 0; k < 4; k++) await new Promise((r) => realImmediate(r)); };
function runTimer(id) {
  const t = timers.get(id);
  if (!t) return;
  if (t.every) t.at = clock + t.every; else timers.delete(id);
  try { t.fn(...t.args); } catch (e) { console.error(e); }
}
function due(limit) {
  let best = null;
  for (const [id, t] of timers) if (t.at <= limit && (!best || t.at < best[1].at || (t.at === best[1].at && id < best[0]))) best = [id, t];
  return best;
}
// Runs what is waiting now: promises, timers already due, and up to `frames` animation frames.
export async function settle(frames = 3) {
  for (let round = 0; round < 200; round++) {
    await flushMicrotasks();
    const d = due(clock);
    if (d) { runTimer(d[0]); continue; }
    if (rafs.length && frames > 0) {
      frames--;
      const batch = rafs; rafs = [];
      for (const [, fn] of batch) { try { fn(clock); } catch (e) { console.error(e); } }
      continue;
    }
    return;
  }
}
// Moves the clock on by `ms`, running every timer that falls due on the way, in order.
export async function advance(ms) {
  const end = clock + ms;
  for (;;) {
    await settle(1);
    const d = due(end);
    if (!d) break;
    clock = Math.max(clock, d[1].at);
    runTimer(d[0]);
  }
  clock = end;
  await settle(1);
}

// ---- the window ---------------------------------------------------------------------------------------

const win = new Target();
export const document = new Document();

// Installs the shim as the page's global window. `parent` (optional) stands for the page around an embedded
// one: what the page posts to it is kept in `posted`.
export function install({ width = 1300, embedded = false, url = "http://stage.test/s/abc/", media = {} } = {}) {
  const g = globalThis;
  for (const k of ["addEventListener", "removeEventListener", "dispatchEvent"]) g[k] = win[k].bind(win);
  win._ls = new Map();
  g.window = g; g.self = g; g.document = document;
  g.innerWidth = width; g.innerHeight = 850;
  document.documentElement.clientWidth = width;
  const loc = new URL(url);
  g.location = { href: loc.href, origin: loc.origin, pathname: loc.pathname, search: loc.search, hash: loc.hash, host: loc.host, assign() {}, reload() {} };
  const posted = [];
  g.parent = embedded ? { posted, postMessage(m) { posted.push(JSON.parse(JSON.stringify(m))); } } : g;
  g.top = g.parent;
  g.setTimeout = (fn, ms = 0, ...args) => { const id = nextId++; timers.set(id, { at: clock + Math.max(0, +ms || 0), fn, args, every: 0 }); return id; };
  g.setInterval = (fn, ms = 0, ...args) => { const id = nextId++; timers.set(id, { at: clock + Math.max(1, +ms || 0), fn, args, every: Math.max(1, +ms || 0) }); return id; };
  g.clearTimeout = g.clearInterval = (id) => { timers.delete(id); };
  g.requestAnimationFrame = (fn) => { const id = nextId++; rafs.push([id, fn]); return id; };
  g.cancelAnimationFrame = (id) => { rafs = rafs.filter(([i]) => i !== id); };
  delete g.requestIdleCallback;
  delete g.BroadcastChannel;
  const query = (q) => {
    if (q in media) return !!media[q];
    let m = /max-width:\s*(\d+)px/.exec(q); if (m) return width <= +m[1];
    m = /min-width:\s*(\d+)px/.exec(q); if (m) return width >= +m[1];
    return false;
  };
  g.matchMedia = (q) => ({ matches: query(q), media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
  const store = new Map();
  g.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k), clear: () => store.clear() };
  g.getComputedStyle = (el) => new Proxy({}, {
    get(_, p) {
      if (p === "getPropertyValue") return (n) => el.style.getPropertyValue(n);
      const v = el.style[p];
      if (v) return v;
      return { overflowY: "visible", overflowX: "visible", display: "block", opacity: "1" }[p] ?? "";
    },
  });
  g.CSS = { escape: (s) => String(s).replace(/([^\w-])/g, "\\$1") };
  g.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  g.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
  g.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  g.Event = ShimEvent;
  g.Audio = class { constructor(src) { const a = document._make("audio"); if (src) a.src = src; return a; } };
  g.MediaMetadata = class { constructor(o) { Object.assign(this, o); } };
  return { posted };
}

// A message to the page, as its parent window posts it (or `source`, another window).
export function message(data, source = globalThis.parent, origin = "http://stage.test") {
  win.dispatchEvent(new ShimEvent("message", { data: JSON.parse(JSON.stringify(data)), source, origin }));
}

// Puts a page's <body> markup in place, scripts left out.
export function setBody(markup) {
  const body = /<body[^>]*>([\s\S]*)<\/body>/i.exec(markup);
  document.body.innerHTML = (body ? body[1] : markup).replace(/<script\b[\s\S]*?<\/script>/gi, "");
}

// What a script the page appends to <head> does when it "loads": `scripts` maps the end of its src to a
// function run as it loads (setting the globals the real library would); any other script loads empty.
export function scripts(map) {
  const proto = Node.prototype, append = proto.append;
  proto.append = function (...nodes) {
    append.apply(this, nodes);
    for (const n of nodes) {
      if (n instanceof Element && n.localName === "script" && n.getAttribute("src") && !n._ran) {
        n._ran = true;
        const src = n.getAttribute("src"), key = Object.keys(map).find((k) => src.endsWith(k));
        setTimeout(() => { try { if (key) map[key](); n.onload?.(new ShimEvent("load")); } catch (e) { n.onerror?.(e); } }, 0);
      }
    }
  };
}
