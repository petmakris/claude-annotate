/* specimen.js — renders a pushed specimen document as the populated instance.
 *
 * The daemon carries the document under one anchor, `__specimen__` (root,
 * worktree, commit, note, types, instance), plus one anchor per field,
 * `<fqn>#<field>`, holding the row lib/document.py already computed (declared
 * type, nullability, value, isNull, provenance, shapeFrom).
 *
 * The page draws `instance` as a tree. A field whose value is an object
 * expands into that object's own fields underneath it, so a MarketValue is
 * two numbers the reader can see rather than a dash and a filename to go and
 * look up. Each item of a list is its own node, which is what lets a null on
 * the first of three items sit on the item that holds it — the old table drew
 * one row per (type, field) and could only say that both a null and a number
 * had been observed somewhere.
 *
 * What did NOT change is the anchor. Every field row still carries
 * `<fqn>#<field>`, so two items of one type share one comment thread and that
 * thread survives a re-push after the code moves. A per-instance anchor would
 * carry a list index the next push can invalidate.
 *
 * Values come from `instance`; shape comes from `types`. An object node lists
 * the fields its TYPE declares, not the keys the specimen happened to fill, so
 * a field the populator never reached is drawn as an unset dash next to its
 * declared type instead of being invisible.
 *
 * Types the instance never reaches are drawn underneath it, one block each,
 * in the four kinds `typegraph.classify` emits. All four are printed, never
 * dropped: a silently missing type is how this page would become confidently
 * wrong. Their field rows keep their anchors and take their values from the
 * row bodies `build_items` computed, which is the only place a behaviour
 * page's values can come from.
 *
 * A single bulk fetch (`items`) gets every anchor's body in one request.
 */
(function () {
  "use strict";

  var WC = window.WebCompanion;
  var root = document.querySelector("[data-wc-root]");

  var DOC = null;     // __specimen__ body
  var FIELDS = {};    // "<fqn>#<field>" -> row body
  var OPEN = {};      // node path -> false when the reader collapsed it

  // Two views of the same document. The tree shows structure; the table puts
  // every field occurrence on one flat line, which is the only way to read the
  // same field of three list items next to each other — in the tree they are
  // pages apart once each item is open. The view lives in the URL so a link
  // can point at either one.
  var HASH = String((window.location || {}).hash || "");
  var VIEW = HASH.indexOf("#table") === 0 ? "table" : "tree";

  // Which composite columns are open, keyed by the record type and the dotted
  // path inside it. `COLS_ALL` is the default every unvisited path falls back
  // to, which is what makes `#table/all` a state rather than a script that
  // clicks everything.
  var OPEN_COLS = {};
  var COLS_ALL = HASH === "#table/all";

  function esc(v) { return v === undefined || v === null ? "" : String(v); }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function anchorFor(fqn, field) { return fqn + "#" + field; }

  function simpleName(fqn) {
    var last = String(fqn || "").split(".").pop();
    return last.split("$").pop();
  }

  function typeEntry(fqn) { return (DOC.types || {})[fqn] || null; }

  /* ---- copyable type names ----------------------------------------------

     The page names a lot of classes, and the next thing done with a class name
     is usually to open it. So every type name is a pill that copies the name
     an IDE's class search wants: fully qualified, and with the nested-class
     `$` written as a dot. `$` is what the JVM and the extractor call it and
     what a class search finds nothing for. */

  function qualifiedName(fqn) { return String(fqn || "").replace(/\$/g, "."); }

  // Any type on this page answering to that simple name, whether or not a
  // shape was read for it — a leaf has no fields and is still worth opening.
  // Only trusted when exactly one answers: a large codebase can have five called `Category`.
  function fqnForName(simple) {
    var hit = null;
    var names = Object.keys(DOC.types || {});
    for (var i = 0; i < names.length; i++) {
      if (simpleName(names[i]) !== simple) continue;
      if (hit) return null;
      hit = names[i];
    }
    return hit;
  }

  function flash(button) {
    button.className = "specimen-pill specimen-pill-copied";
    setTimeout(function () { button.className = "specimen-pill"; }, 900);
  }

  // `navigator.clipboard` needs a secure context, which 127.0.0.1 is; the
  // textarea is for the case where it is refused anyway, so the click is never
  // a click that silently did nothing.
  function copyName(button, name) {
    function fallback() {
      var box = document.createElement("textarea");
      box.value = name;
      document.body.appendChild(box);
      box.select();
      try { document.execCommand("copy"); flash(button); }
      catch (e) { console.warn("specimen: could not copy " + name); }
      document.body.removeChild(box);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(name).then(function () { flash(button); }, fallback);
      return;
    }
    fallback();
  }

  // `label` is what the reader sees — often the simple name, since the page has
  // no room for the package on every row. `name` is what lands on the
  // clipboard, which is as much of it as the page can say for certain.
  function typePill(label, fqn, fallbackName) {
    var name = fqn ? qualifiedName(fqn) : (fallbackName || label);
    var button = el("button", "specimen-pill", label);
    button.type = "button";
    button.title = "copy " + name;
    button.setAttribute("data-copy", name);
    button.onclick = function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      copyName(button, name);
    };
    return button;
  }

  // A field's declared type, as a pill. `base` is the erased name, so a
  // `List<Chart>` copies `List` rather than a string no search accepts.
  function declaredPill(field) {
    if (!field.declared) return el("span", "specimen-declared", "");
    var pill = typePill(field.declared, field.base ? fqnForName(field.base) : null,
      field.base || field.declared);
    pill.className = "specimen-pill specimen-declared";
    return pill;
  }

  function isOpen(path) { return OPEN[path] !== false; }

  /* ------------------------------------------------------------- editor */
  // The page cannot open a file itself: file:// is refused from an http
  // origin. The daemon's /api/open runs the opener, and it only accepts an
  // absolute path already inside a session's workspace — which is what
  // types.json's `source` is. A failure shows the server's reason rather
  // than a guess.
  function openInEditor(button, file, line) {
    button.disabled = true;
    fetch("/api/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: file, line: line }),
    }).then(function (res) {
      if (!res.ok) {
        button.className = "specimen-open specimen-open-failed";
        return res.text().then(function (why) {
          console.warn("specimen: could not open " + file + ":" + line + " — " + why);
        });
      }
    }).catch(function () {
      button.className = "specimen-open specimen-open-failed";
      console.warn("specimen: webcompanion unreachable, could not open " + file);
    }).then(function () { button.disabled = false; });
  }

  function openButton(file, line, label) {
    if (!file) return null;
    var button = el("button", "specimen-open", "⌘");
    button.type = "button";
    button.title = "open " + label + " in the editor";
    button.onclick = function (ev) {
      // Without this the click reaches the runtime's delegated handler and
      // opens a comment composer on top of the jump the reader asked for.
      if (ev && ev.stopPropagation) ev.stopPropagation();
      openInEditor(button, file, line);
    };
    return button;
  }

  /* -------------------------------------------------------------- cells */
  // Three display states, and they are three different facts. A `null` badge
  // means the field's value is genuinely absent and is the reason this page
  // exists. An unset dash means nobody put a value there. A value is a value.
  function valueCell(node) {
    if (!node) return el("span", "specimen-value specimen-unset", "–");
    if (node.kind === "null") return el("span", "specimen-value specimen-null", "null");
    if (node.kind === "list") {
      var n = (node.items || []).length;
      return el("span", "specimen-value specimen-count", n + (n === 1 ? " item" : " items"));
    }
    if (node.kind === "object") {
      var named = typePill(simpleName(node.type), node.type);
      named.className = "specimen-pill specimen-value specimen-count";
      return named;
    }
    if (node.value === null || node.value === undefined || node.value === "") {
      return el("span", "specimen-value specimen-unset", "–");
    }
    return el("span", "specimen-value", esc(node.value));
  }

  // What a node holds, said in one line, so a reader skimming a long tree
  // learns that a MarketValue is an amount and a currency without opening it.
  // It summarises the keys the INSTANCE carries, not the ones the type
  // declares: a preview is about what is in there, and a field nobody filled
  // is not.
  var PREVIEW_FIELDS = 3;

  function previewValue(node) {
    if (!node) return "–";
    if (node.kind === "null") return "null";
    if (node.kind === "object") return "{…}";
    if (node.kind === "list") return "[" + (node.items || []).length + "]";
    return esc(node.value);
  }

  function previewOf(node) {
    if (!node || node.kind !== "object") return "";
    var names = Object.keys(node.fields || {});
    if (!names.length) return "{}";
    var shown = names.slice(0, PREVIEW_FIELDS).map(function (name) {
      return name + ": " + previewValue(node.fields[name]);
    });
    if (names.length > PREVIEW_FIELDS) shown.push("…");
    return "{" + shown.join(", ") + "}";
  }

  // A mark, not a word. `@Nullable` spelled out on every second row is what
  // turned the tree into a table; the fact it carries is one bit and the
  // hover title still spells it.
  var NULLABILITY_MARK = { nullable: "?", "non-null": "", unmarked: "·" };

  // The file name is what ellipsises when the reference runs out of room; the
  // line number never does, because the line is the part that says where to
  // look. The whole reference stays on the title either way.
  function shapeCell(row) {
    var cell = el("span", "specimen-shape-from");
    var text = esc(row.shapeFrom);
    var cut = text.lastIndexOf(":");
    cell.appendChild(el("span", "specimen-shape-file",
      cut === -1 ? text : text.slice(0, cut)));
    if (cut !== -1) cell.appendChild(el("span", "specimen-shape-line", text.slice(cut)));
    if (row.shapeFrom) cell.title = row.shapeFrom;
    return cell;
  }

  function nullabilityCell(field, row) {
    var span = el(
      "span",
      "specimen-nullability specimen-nullability-" + esc(field.nullability),
      NULLABILITY_MARK[field.nullability] !== undefined
        ? NULLABILITY_MARK[field.nullability] : "·"
    );
    span.title = row.nullabilityLabel || field.nullability;
    return span;
  }

  /* --------------------------------------------------------------- rows */
  // One row, whatever it holds. `owner` is the class that DECLARES the field,
  // which is what the anchor and the source line are about; `node` is the
  // value the instance put there, and may be missing entirely.
  function fieldRow(owner, field, node, lead) {
    var anchor = anchorFor(owner, field.name);
    var row = FIELDS[anchor] || {};
    var cls = "specimen-field-row";
    if (node && node.kind === "null") cls += " specimen-row-null";
    var div = el("div", cls);
    div.setAttribute("data-wc-anchor", anchor);
    claimClicks(div, lead);

    // Every row keeps the slot whether or not it can be opened, so a leaf's
    // name starts where the name of the node above it starts.
    div.appendChild(lead || el("span", "specimen-lead", ""));
    div.appendChild(el("span", "specimen-field", field.name));
    div.appendChild(nullabilityCell(field, row));
    div.appendChild(el("span", "specimen-sep", ":"));
    div.appendChild(valueCell(node));
    div.appendChild(el("span", "specimen-preview", previewOf(node)));
    div.appendChild(metaGroup(owner, field, node, row));
    return div;
  }

  // Everything that is about the DECLARATION rather than the value: the
  // declared type, where it was written, the provenance of what is in it, and
  // the jump. It sits at the end of the line and stays dim, so the line reads
  // as `name: value` and the reference detail is there when wanted.
  function metaGroup(owner, field, node, row) {
    var meta = el("span", "specimen-meta-group");
    if (field.declared) meta.appendChild(declaredPill(field));
    meta.appendChild(el("span", "specimen-provenance",
      node && node.kind === "scalar" ? esc(node.provenance) : ""));
    meta.appendChild(shapeCell(row));
    var entry = typeEntry(owner);
    var jump = entry && openButton(entry.source, field.line, row.shapeFrom || field.name);
    if (jump) meta.appendChild(jump);
    meta.appendChild(askButton(anchorFor(owner, field.name)));
    return meta;
  }

  // The anchor stays on the ROW, so the runtime inserts a composer after the
  // row instead of inside its meta group, where it would tear the line apart.
  // But the runtime opens that composer on any click that reaches the page
  // root, and on a tree a click means "open this", not "write about this".
  // So the row swallows its own clicks — expanding when there is something to
  // expand — and only the ✻ is let through to reach the root.
  function claimClicks(rowEl, lead) {
    rowEl.onclick = function (ev) {
      if (ev && ev.target && isAsk(ev.target)) return;
      if (ev && ev.stopPropagation) ev.stopPropagation();
      if (lead && lead.onclick) lead.onclick(ev);
    };
  }

  function isAsk(target) {
    return String((target && target.className) || "").split(/\s+/).indexOf("specimen-ask") !== -1;
  }

  function askButton(anchor) {
    var button = el("button", "specimen-ask", "✻");
    button.type = "button";
    button.title = "ask about " + anchor.split("#").pop();
    return button;
  }

  /* -------------------------------------------------------------- nodes */
  function toggle(path) {
    var button = el("button", "specimen-toggle", isOpen(path) ? "▾" : "▸");
    button.type = "button";
    button.onclick = function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      OPEN[path] = !isOpen(path);
      render();
    };
    return button;
  }

  function nodeShell(kind, path, headRow, type) {
    var container = el("div", "specimen-node" + (isOpen(path) ? "" : " specimen-closed"));
    container.setAttribute("data-node-kind", kind);
    if (type) container.setAttribute("data-node-type", type);
    container.appendChild(headRow);
    return container;
  }

  // An object node lists the fields its type DECLARES. Where the extractor
  // read no shape for the type (a leaf reached as a value), fall back to the
  // keys the instance carries so the values are not silently dropped.
  function fieldsOfType(fqn) {
    var entry = typeEntry(fqn);
    return (entry && entry.fields) || [];
  }

  // The fields a node's type declares. Where the extractor read no shape for
  // the type, fall back to the keys the instance carries so the values are not
  // silently dropped.
  function objectFields(node) {
    var fields = fieldsOfType(node.type);
    if (fields.length) return fields;
    return Object.keys(node.fields || {}).map(function (name) {
      return { name: name, declared: "", nullability: "unmarked", line: null };
    });
  }

  // The value a dotted path reaches inside one record. `undefined` means the
  // instance never got there, which is a different fact from a null.
  function valueAtParts(node, parts) {
    var at = node;
    for (var i = 0; i < parts.length; i++) {
      if (!at || at.kind !== "object") return undefined;
      at = (at.fields || {})[parts[i]];
    }
    return at;
  }

  function objectBody(node, path) {
    var body = el("div", "specimen-node-body");
    objectFields(node).forEach(function (field) {
      var child = (node.fields || {})[field.name];
      body.appendChild(valueNode(child, node.type, field, path + "/" + field.name));
    });
    return body;
  }

  // A field whose value is an object or a list becomes a node; anything else
  // is a plain row. Both carry the same anchor, so what a comment attaches to
  // does not depend on how deep the value turned out to be.
  function valueNode(node, owner, field, path) {
    var kind = node && node.kind;
    if (kind === "object") {
      var obj = nodeShell("object", path,
        fieldRow(owner, field, node, toggle(path)), node.type);
      if (isOpen(path)) obj.appendChild(objectBody(node, path));
      return obj;
    }
    if (kind === "list") {
      var list = nodeShell("list", path,
        fieldRow(owner, field, node, toggle(path)), node.element);
      if (isOpen(path)) list.appendChild(listBody(node, path));
      return list;
    }
    var row = fieldRow(owner, field, node);
    row.setAttribute("data-node-kind", "field");
    return row;
  }

  function itemNode(item, index, path) {
    var label = "[" + index + "]";
    var kindEarly = item && item.kind;
    var head = el("div", "specimen-field-row specimen-item-head");
    var itemLead = kindEarly === "object" || kindEarly === "list"
      ? toggle(path) : el("span", "specimen-lead", "");
    claimClicks(head, itemLead);
    head.appendChild(itemLead);
    head.appendChild(el("span", "specimen-field", label));
    head.appendChild(item && item.type
      ? (function () {
          var pill = typePill(simpleName(item.type), item.type);
          pill.className = "specimen-pill specimen-declared";
          return pill;
        })()
      : el("span", "specimen-declared", ""));
    var kind = item && item.kind;
    if (kind !== "object" && kind !== "list") {
      head.appendChild(el("span", "specimen-sep", ":"));
      head.appendChild(valueCell(item));
      head.setAttribute("data-node-kind", "field");
      return head;
    }
    head.appendChild(el("span", "specimen-preview", previewOf(item)));
    var entry = item.type && typeEntry(item.type);
    if (entry && entry.source) {
      var meta = el("span", "specimen-meta-group");
      var jump = openButton(entry.source, entry.line, simpleName(item.type));
      if (jump) meta.appendChild(jump);
      head.appendChild(meta);
    }
    var container = nodeShell(kind, path, head, item.type || item.element);
    if (isOpen(path)) {
      container.appendChild(kind === "object" ? objectBody(item, path) : listBody(item, path));
    }
    return container;
  }

  function listBody(node, path) {
    var body = el("div", "specimen-node-body");
    (node.items || []).forEach(function (item, i) {
      body.appendChild(itemNode(item, i, path + "/" + i));
    });
    return body;
  }

  // The root of the instance has no field declaring it, so it gets a head of
  // its own rather than borrowing fieldRow's.
  function rootNode(node) {
    var kind = node && node.kind;
    var path = "$";
    var head = el("div", "specimen-field-row specimen-root-head");
    var rootLead = toggle(path);
    claimClicks(head, rootLead);
    head.appendChild(rootLead);
    head.appendChild(el("span", "specimen-field", "instance"));
    var owned = kind === "list" ? node.element : (node && node.type);
    var shown = kind === "list"
      ? "List<" + simpleName(node.element) + ">"
      : simpleName(node && node.type);
    var rootPill = typePill(shown, owned);
    rootPill.className = "specimen-pill specimen-declared";
    head.appendChild(rootPill);
    head.appendChild(valueCell(node));
    var owner = kind === "list" ? node.element : (node && node.type);
    var entry = owner && typeEntry(owner);
    if (entry && entry.source) {
      var jump = openButton(entry.source, entry.line, simpleName(owner));
      if (jump) head.appendChild(jump);
    }
    var container = nodeShell(kind, path, head, kind === "list" ? node.element : node.type);
    if (isOpen(path)) {
      container.appendChild(kind === "list" ? listBody(node, path) : objectBody(node, path));
    }
    return container;
  }

  /* ------------------------------------------------------------- header */
  function renderHeader() {
    var head = el("header", "specimen-header");
    head.appendChild(el("h1", null, simpleName(DOC.root) + " specimen"));
    var meta = el("p", "specimen-meta");
    if (DOC.commit) meta.appendChild(el("span", null, "commit " + DOC.commit + " · "));
    if (DOC.root) {
      var rootPill = typePill(DOC.root, DOC.root);
      rootPill.className = "specimen-pill specimen-pill-fqn";
      meta.appendChild(rootPill);
    }
    if (DOC.worktree) meta.appendChild(el("span", null, " · " + DOC.worktree));
    head.appendChild(meta);
    if (DOC.note) head.appendChild(el("p", "specimen-note", DOC.note));
    // Where the `captured` identifiers actually came from. The NOTE above says
    // they came from a real deployment; this line says WHICH one and WHEN, so
    // the claim is checkable instead of merely asserted.
    var capture = DOC.capture || {};
    if (capture.deployment || capture.captured) {
      var said = [];
      if (capture.deployment) said.push(capture.deployment);
      if (capture.captured) said.push(capture.captured);
      head.appendChild(el("p", "specimen-capture",
        "Captured identifiers: " + said.join(" · ")));
    }
    head.appendChild(viewControls());
    return head;
  }

  function controlButton(label, active, onclick) {
    var button = el("button",
      "specimen-control" + (active ? " specimen-control-on" : ""), label);
    button.type = "button";
    button.onclick = onclick;
    return button;
  }

  // Leaves a link that opens the view the reader was in, columns and all.
  // Assigning the hash rather than pushing history keeps the back button
  // meaning "the page before this one", not "the tab I clicked a moment ago".
  function writeHash() {
    var want = VIEW !== "table" ? "" : (COLS_ALL ? "#table/all" : "#table");
    try { window.location.hash = want; } catch (e) { /* no-op */ }
  }

  function setView(view) {
    VIEW = view;
    writeHash();
    render();
  }

  function setAllColumns(open) {
    COLS_ALL = open;
    OPEN_COLS = {};
    writeHash();
    render();
  }

  function viewControls() {
    var bar = el("p", "specimen-controls");
    bar.appendChild(controlButton("tree", VIEW === "tree",
      function () { setView("tree"); }));
    bar.appendChild(controlButton("table", VIEW === "table",
      function () { setView("table"); }));
    if (VIEW === "tree") {
      bar.appendChild(controlButton("expand all", false,
        function () { OPEN = {}; render(); }));
      bar.appendChild(controlButton("collapse all", false,
        function () { closeEverything(); render(); }));
    } else {
      bar.appendChild(controlButton("open all columns", COLS_ALL,
        function () { setAllColumns(true); }));
      bar.appendChild(controlButton("close all columns", !COLS_ALL,
        function () { setAllColumns(false); }));
    }
    return bar;
  }

  // Collapse-all has to name the paths, because a path is only open by
  // default — there is no list of them until the tree has been walked.
  function closeEverything() {
    OPEN = {};
    (function walkValue(node, path) {
      if (!node) return;
      if (node.kind === "object") {
        OPEN[path] = false;
        Object.keys(node.fields || {}).forEach(function (name) {
          walkValue(node.fields[name], path + "/" + name);
        });
      } else if (node.kind === "list") {
        OPEN[path] = false;
        (node.items || []).forEach(function (item, i) {
          walkValue(item, path + "/" + i);
        });
      }
    })(DOC.instance, "$");
  }

  /* ------------------------------------------------------------- blocks */
  function renderTree() {
    var section = el("section", "specimen-type specimen-tree");
    section.appendChild(el("h2", null, "instance"));
    var node = DOC.instance;
    if (!node || (node.kind !== "object" && node.kind !== "list")) {
      section.appendChild(el("p", "specimen-reason",
        "This specimen carries no populated instance, so there is no tree to " +
        "draw. Every type it names is below."));
      return section;
    }
    section.appendChild(rootNode(node));
    return section;
  }

  /* -------------------------------------------------------------- table */
  // One table per type the instance holds, one ROW per instance of it, one
  // column per field that type declares. Three Contributor items are three
  // lines under each other, which is the whole reason to leave the tree: once
  // each item is expanded there, its fields are pages away from its siblings'.
  //
  // Grouping is by type rather than by nesting, so an object reached at two
  // different depths still lands in the same table as its siblings.
  function recordGroups() {
    var order = [];
    var byType = {};

    function record(node, path) {
      if (!node || node.kind !== "object" || !node.type) return;
      if (!byType[node.type]) { byType[node.type] = []; order.push(node.type); }
      byType[node.type].push({ path: path, node: node });
      objectFields(node).forEach(function (field) {
        walkValue((node.fields || {})[field.name],
          path ? path + "." + field.name : field.name);
      });
    }

    function walkValue(node, path) {
      if (!node) return;
      if (node.kind === "object") record(node, path);
      else if (node.kind === "list") {
        (node.items || []).forEach(function (item, i) {
          walkValue(item, path + "[" + i + "]");
        });
      }
    }

    var root = DOC.instance;
    if (root && root.kind === "list") {
      (root.items || []).forEach(function (item, i) { walkValue(item, "[" + i + "]"); });
    } else if (root && root.kind === "object") {
      // The root has no field naming it, so its own row is labelled below; its
      // children start their paths bare rather than under an `instance.` stem
      // that says nothing and costs every path its first ten characters.
      record(root, "");
    }
    return order.map(function (fqn) { return { type: fqn, rows: byType[fqn] }; });
  }

  /* ---- the column tree -------------------------------------------------

     A composite column opens into its own fields as real columns under a
     spanning header, and those can open again. So the header of a record table
     is a tree, not a row, and a value three levels down can still be read
     straight down the page — which is the only reason to be in the table
     rather than in the tree view.

     The nested type comes from the INSTANCE, not from the field's declared
     name: `types.json` records declared types as simple names, and a simple
     name does not identify a class (a large codebase can have five called `Category`). The
     first record that actually holds an object at that path names it. A path
     no record reaches cannot be opened, which is correct — there is nothing
     there to open into. */

  function colKey(fqn, path) { return fqn + "|" + path; }

  function isColOpen(fqn, path) {
    var key = colKey(fqn, path);
    return OPEN_COLS[key] === undefined ? COLS_ALL : OPEN_COLS[key];
  }

  function toggleCol(fqn, path) {
    OPEN_COLS[colKey(fqn, path)] = !isColOpen(fqn, path);
    render();
  }

  // A field's declared type is a SIMPLE name, and a simple name does not
  // identify a class — a large codebase can have five called `Category`. So a simple name is
  // only trusted when exactly one type on this page answers to it.
  function fqnForSimpleName(simple) {
    var hit = null;
    var types = DOC.types || {};
    var names = Object.keys(types);
    for (var i = 0; i < names.length; i++) {
      if (simpleName(names[i]) !== simple) continue;
      if (!(types[names[i]].fields || []).length) continue;
      if (hit) return null;
      hit = names[i];
    }
    return hit;
  }

  // The instance names the type exactly, so it wins. Where no record holds an
  // object at that path — every instance null, or the field never reached —
  // the declared name is the only thing left, and the column still opens: the
  // shape is what this page is for, and a column of unset dashes under the
  // right field names says more than a column that refuses to open.
  function nestedTypeFor(rows, parts, field) {
    for (var i = 0; i < rows.length; i++) {
      var value = valueAtParts(rows[i].node, parts);
      if (value && value.kind === "object" && value.type) return value.type;
    }
    return field.base ? fqnForSimpleName(field.base) : null;
  }

  function buildColumns(group) {
    function build(ownerFqn, field, parts) {
      var nested = nestedTypeFor(group.rows, parts, field);
      var expandable = !!(nested && fieldsOfType(nested).length);
      var open = expandable && isColOpen(group.type, parts.join("."));
      return {
        ownerFqn: ownerFqn,
        field: field,
        parts: parts,
        path: parts.join("."),
        nested: nested,
        expandable: expandable,
        open: open,
        children: open ? fieldsOfType(nested).map(function (child) {
          return build(nested, child, parts.concat(child.name));
        }) : []
      };
    }
    var rootFields = group.rows.length ? objectFields(group.rows[0].node) : [];
    return rootFields.map(function (field) {
      return build(group.type, field, [field.name]);
    });
  }

  // How many leaf columns a column owns, and how many header rows it needs.
  function colSpan(col) {
    if (!col.open) return 1;
    return col.children.reduce(function (n, child) { return n + colSpan(child); }, 0);
  }

  function colDepth(col) {
    if (!col.open) return 1;
    return 1 + col.children.reduce(function (d, child) {
      return Math.max(d, colDepth(child));
    }, 1);
  }

  function leafColumns(col) {
    if (!col.open) return [col];
    return col.children.reduce(function (all, child) {
      return all.concat(leafColumns(child));
    }, []);
  }

  /* ---- header ---------------------------------------------------------- */

  // The column IS the (type, field) pair, so the anchor and the controls live
  // in the header — one thread per column rather than one per cell. A thread
  // per cell would need a per-instance anchor, which the next push invalidates.
  // A group header is a field too, so it carries its own anchor.
  function headerCell(col, level, totalRows, tint) {
    var anchor = anchorFor(col.ownerFqn, col.field.name);
    var row = FIELDS[anchor] || {};
    var lead = col.expandable
      ? (function () {
          var button = el("button", "specimen-toggle", col.open ? "▾" : "▸");
          button.type = "button";
          button.onclick = function (ev) {
            if (ev && ev.stopPropagation) ev.stopPropagation();
            toggleCol(col.rootFqn, col.path);
          };
          return button;
        })()
      : null;

    var th = el("th", "specimen-th" + (col.open ? " specimen-grouphead" : "") + tint);
    th.setAttribute("data-wc-anchor", anchor);
    th.setAttribute("data-col-path", col.path);
    if (col.open) {
      th.setAttribute("colspan", colSpan(col));
    } else {
      // Header cells are emitted level by level, so a leaf on row 3 follows a
      // leaf on row 1 in the DOM while standing to its LEFT on the page. The
      // visual position is the one a body cell lines up against, so the page
      // states it rather than leaving it to be inferred from the nesting.
      th.setAttribute("data-col-index", col.index);
      if (totalRows - level > 1) th.setAttribute("rowspan", totalRows - level);
    }
    claimClicks(th, lead);

    if (lead) th.appendChild(lead);
    th.appendChild(el("span", "specimen-th-name", col.field.name));
    th.appendChild(nullabilityCell(col.field, row));
    if (!col.open) {
      var declared = declaredPill(col.field);
      declared.className = "specimen-pill specimen-th-declared";
      th.appendChild(declared);
    }

    var controls = el("span", "specimen-meta-group");
    var entry = typeEntry(col.ownerFqn);
    var jump = entry && openButton(entry.source, col.field.line,
      row.shapeFrom || col.field.name);
    if (jump) controls.appendChild(jump);
    controls.appendChild(askButton(anchor));
    th.appendChild(controls);
    return th;
  }

  // Cells are emitted level by level: a closed column reaches down with
  // rowspan, an open one spans across with colspan and puts its children on
  // the row below.
  function tintFor(tintLevel, edge) {
    var cls = tintLevel > 0 ? " specimen-in" + Math.min(tintLevel, 2) : "";
    // Two groups side by side read as one wide group without a line between
    // them, so the first cell of each open group draws one.
    return cls + (edge ? " specimen-edge" + Math.min(Math.max(tintLevel, 1), 2) : "");
  }

  function headerLevels(col, level, totalRows, levels, tintLevel, edge) {
    levels[level].push(headerCell(col, level, totalRows,
      tintFor(col.open ? tintLevel + 1 : tintLevel, edge)));
    if (!col.open) return;
    col.children.forEach(function (child, i) {
      headerLevels(child, level + 1, totalRows, levels, tintLevel + 1, i === 0);
    });
  }

  /* ---- body ------------------------------------------------------------ */

  function bodyCells(col, recordNode, tintLevel, edge) {
    var value = valueAtParts(recordNode, col.parts);
    var tint = tintFor(tintLevel, edge);

    if (!col.open) {
      var td = el("td", (value && value.kind === "null" ? "specimen-row-null" : "") + tint);
      td.setAttribute("data-col-path", col.path);
      td.appendChild(recordCell(value));
      return [td];
    }
    if (value && value.kind === "null") {
      // One cell across the whole group. A run of empty cells would read as a
      // run of empty FIELDS; this says the object itself is absent.
      var spanned = el("td", "specimen-group-null" + tintFor(tintLevel + 1, true), "null");
      spanned.setAttribute("colspan", colSpan(col));
      spanned.setAttribute("data-col-path", col.path);
      return [spanned];
    }
    if (!value) {
      // Never reached by the instance, which is not the same as null, so each
      // leaf column says so for itself.
      return leafColumns(col).map(function (leaf, i) {
        var cell = el("td", tintFor(tintLevel + 1, i === 0));
        cell.setAttribute("data-col-path", leaf.path);
        cell.appendChild(el("span", "specimen-cell specimen-unset", "–"));
        return cell;
      });
    }
    return col.children.reduce(function (all, child, i) {
      return all.concat(bodyCells(child, recordNode, tintLevel + 1, i === 0));
    }, []);
  }

  // What one cell shows. An object says what it holds rather than only naming
  // its class, because in a record table the nested object is itself a value
  // being compared down the column.
  function recordCell(node) {
    if (node && node.kind === "object") {
      return el("span", "specimen-cell specimen-count", previewOf(node));
    }
    var cell = valueCell(node);
    cell.className = "specimen-cell " + cell.className;
    return cell;
  }

  function recordTable(group) {
    var columns = buildColumns(group);
    columns.forEach(function (col) {
      (function stamp(c) {
        c.rootFqn = group.type;
        c.children.forEach(stamp);
      })(col);
    });

    columns.reduce(function (all, col) { return all.concat(leafColumns(col)); }, [])
      .forEach(function (leaf, i) { leaf.index = i; });

    var totalRows = columns.reduce(function (d, col) {
      return Math.max(d, colDepth(col));
    }, 1);

    var table = el("table", "specimen-record-table");
    table.setAttribute("data-record-type", group.type);

    var levels = [];
    for (var i = 0; i < totalRows; i++) levels.push([]);
    var corner = el("th", "specimen-th specimen-th-path", "");
    if (totalRows > 1) corner.setAttribute("rowspan", totalRows);
    levels[0].push(corner);
    columns.forEach(function (col) { headerLevels(col, 0, totalRows, levels, 0, false); });

    var thead = el("thead");
    levels.forEach(function (cells) {
      var tr = el("tr");
      cells.forEach(function (cell) { tr.appendChild(cell); });
      thead.appendChild(tr);
    });
    table.appendChild(thead);

    var tbody = el("tbody");
    group.rows.forEach(function (entry) {
      var tr = el("tr", "specimen-record-row");
      var label = el("td", "specimen-record-path", entry.path || "instance");
      label.title = entry.path || "instance";
      tr.appendChild(label);
      columns.forEach(function (col) {
        bodyCells(col, entry.node, 0, false).forEach(function (cell) {
          tr.appendChild(cell);
        });
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function renderTable() {
    var section = el("section", "specimen-type specimen-flat");
    section.appendChild(el("h2", null, "instance"));
    var groups = recordGroups();
    if (!groups.length) {
      section.appendChild(el("p", "specimen-reason",
        "This specimen carries no populated instance, so there is nothing to " +
        "lay out. Every type it names is below."));
      return section;
    }
    groups.forEach(function (group) {
      var block = el("div", "specimen-record-block");
      var caption = el("p", "specimen-record-caption");
      var captionPill = typePill(simpleName(group.type), group.type);
      captionPill.className = "specimen-pill specimen-record-type";
      caption.appendChild(captionPill);
      caption.appendChild(el("span", "specimen-record-count",
        group.rows.length + (group.rows.length === 1 ? " instance" : " instances")));
      caption.title = group.type;
      block.appendChild(caption);
      block.appendChild(recordTable(group));
      section.appendChild(block);
    });
    return section;
  }

  // A type the instance never reached. Its fields still have anchors, and its
  // values still exist in the row bodies, which is where a behaviour page's
  // values live — that page's instance is thin by nature.
  function fieldsBlock(fqn, entry) {
    var block = el("div", "specimen-node specimen-orphan-body");
    (entry.fields || []).forEach(function (field) {
      var row = FIELDS[anchorFor(fqn, field.name)] || {};
      block.appendChild(fieldRow(fqn, field, nodeFromRow(row)));
    });
    return block;
  }

  // The row body is a flattened observation, not a value node. Turning it back
  // into one keeps a single renderer for both halves of the page instead of
  // two that can disagree about what a null looks like.
  function nodeFromRow(row) {
    var values = row.values || [];
    if (!values.length) return null;
    if (values.length === 1) {
      return values[0].isNull
        ? { kind: "null" }
        : { kind: "scalar", value: values[0].value, provenance: values[0].provenance };
    }
    return {
      kind: "scalar",
      value: values.map(function (v) { return v.isNull ? "null" : v.value; }).join(" / "),
      provenance: values.map(function (v) { return v.provenance; })
        .filter(function (p, i, all) { return p && all.indexOf(p) === i; }).join(" / "),
    };
  }

  function orphanSection(fqn, entry) {
    var kindClass = {
      data: "specimen-data",
      behaviour: "specimen-behaviour",
      leaf: "specimen-leaf",
    }[entry.kind] || "specimen-unhandled";
    var section = el("section", "specimen-type " + kindClass);
    var heading = el("h2");
    var headingPill = typePill(fqn, fqn);
    headingPill.className = "specimen-pill specimen-pill-fqn";
    heading.appendChild(headingPill);
    section.appendChild(heading);

    if (entry.kind === "data") {
      section.appendChild(el("p", "specimen-badge", "data — not reached by this instance"));
      section.appendChild(el("p", "specimen-reason",
        "Read from source. Nothing in the instance above holds one, so its " +
        "fields have shapes but no values."));
      section.appendChild(fieldsBlock(fqn, entry));
      return section;
    }
    if (entry.kind === "behaviour") {
      section.appendChild(el("p", "specimen-badge", "behaviour — holds collaborators, not data"));
      section.appendChild(el(
        "p", "specimen-reason",
        "Read from source. Its fields are the services and repositories it works " +
        "through; the data types they carry are in the instance above or in " +
        "their own blocks here."
      ));
      section.appendChild(fieldsBlock(fqn, entry));
      return section;
    }
    if (entry.kind === "leaf") {
      section.appendChild(el("p", "specimen-badge", "leaf — no source in this worktree"));
      section.appendChild(el("p", "specimen-reason", entry.reason || ""));
      var accessors = entry.accessors_observed || [];
      if (accessors.length) {
        section.appendChild(el("p", "specimen-accessors-label", "accessors observed:"));
        var ul = el("ul", "specimen-accessors");
        accessors.forEach(function (a) { ul.appendChild(el("li", null, a)); });
        section.appendChild(ul);
      }
      return section;
    }
    section.appendChild(el("p", "specimen-badge", "unhandled"));
    // lib/emit.py refuses a payload whose unhandled entry has no reason, so
    // this fallback should be unreachable; it says so rather than showing a
    // badge standing over a blank.
    section.appendChild(el("p", "specimen-reason",
      entry.reason || "no reason recorded — this is a bug in lib/emit.py's provenance check"));
    return section;
  }

  // Which types the tree already drew. A type drawn twice would read as two
  // different things rather than one thing seen from two places.
  function typesInTree() {
    var seen = {};
    (function walkValue(node) {
      if (!node) return;
      if (node.kind === "object") {
        if (node.type) seen[node.type] = true;
        Object.keys(node.fields || {}).forEach(function (name) {
          walkValue(node.fields[name]);
        });
      } else if (node.kind === "list") {
        (node.items || []).forEach(walkValue);
      }
    })(DOC.instance);
    return seen;
  }

  function render() {
    root.textContent = "";
    if (!DOC) {
      root.appendChild(el("p", "specimen-idle", "Waiting for a specimen to be pushed."));
      return;
    }
    root.appendChild(renderHeader());
    root.appendChild(VIEW === "table" ? renderTable() : renderTree());

    var drawn = typesInTree();
    var types = DOC.types || {};
    Object.keys(types).sort().forEach(function (fqn) {
      if (drawn[fqn]) return;
      root.appendChild(orphanSection(fqn, types[fqn] || {}));
    });
  }

  // The daemon's bulk `items` endpoint wraps each anchor as {body, version}
  // (see webcompanion's items.snapshot) — the same shape items.py's
  // single-anchor GET uses, just one per key. Unwrap `.body`; a client that
  // forgot to would read `undefined` for every field and show a page full
  // of blank cells that look like nulls but are not, which is the one
  // failure mode this page cannot afford.
  //
  // If a future daemon ever handed back a raw, unwrapped body instead, the
  // same silent failure would recur one layer up: `.body` reads undefined
  // and the page quietly shows "waiting" or all-dash rows instead of erring.
  // Falling back to the entry itself keeps the page honest about what it
  // has, and one warning (not one per anchor) names the drift instead of
  // letting it pass as "nothing was pushed".
  var driftWarned = false;
  function unwrapBody(entry) {
    if (entry && entry.body !== undefined) return entry.body;
    if (!driftWarned) {
      driftWarned = true;
      console.warn("specimen: daemon returned an unwrapped item; assuming contract drift");
    }
    return entry;
  }

  function applyItems(bulk) {
    bulk = bulk || {};
    driftWarned = false;
    var specimenEntry = bulk.__specimen__;
    DOC = specimenEntry ? unwrapBody(specimenEntry) : null;
    FIELDS = {};
    Object.keys(bulk).forEach(function (anchor) {
      if (anchor === "__specimen__") return;
      var entry = bulk[anchor];
      FIELDS[anchor] = entry ? unwrapBody(entry) : {};
    });
    render();
  }

  function refetch() {
    return WC.api.fetchJSON("items").then(applyItems).catch(function () {
      /* a transient fetch failure is not worth a banner; the next delta retries */
    });
  }

  function boot() {
    return refetch().then(function () {
      WC.init({
        root: root,
        onDelta: function (d) {
          // The bulk fetch above already reflects the snapshot every
          // `initial` delta is echoing; only a real change needs a redraw.
          if (d.kind !== "item" || d.initial) return;
          refetch();
        },
      });
    });
  }

  boot().catch(function (e) {
    root.textContent = "";
    root.appendChild(el("p", "specimen-error", "Could not load this specimen: " + e));
  });
})();
