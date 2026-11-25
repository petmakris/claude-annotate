"""A small JSON Schema checker for fleet/docs/session-index.schema.json, stdlib only.

It knows the keywords that schema uses and no others (`KNOWN`), so the contract test can refuse a schema that a
standard validator would read differently. `errors(schema, doc, name)` gives the problems of `doc` against the
definition `name` (`$defs/<name>`), each as `path: what`; an empty list means the document fits.
"""
import re

KNOWN = frozenset((
    "$schema", "title", "description", "$defs", "$ref", "type", "enum", "const", "pattern", "minLength",
    "maxLength", "minimum", "maximum", "properties", "required", "additionalProperties", "minProperties", "items",
    "minItems", "maxItems", "anyOf", "oneOf", "allOf", "not", "if", "then", "else"))

TYPES = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def unknown_keywords(node, path="#"):
    """Every keyword of the schema this checker does not know, as `path: keyword`."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if path.endswith("/properties") or path.endswith("/$defs"):
                out += unknown_keywords(v, "%s/%s" % (path, k))  # a property or definition name, not a keyword
                continue
            if k not in KNOWN:
                out.append("%s: %s" % (path, k))
            if k in ("enum", "const", "required"):
                continue
            out += unknown_keywords(v, "%s/%s" % (path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += unknown_keywords(v, "%s/%d" % (path, i))
    return out


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError("only local references are supported: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(root, s, v, path, out):
    if s is True or s == {}:
        return
    if s is False:
        out.append("%s: not allowed" % path)
        return
    if "$ref" in s:
        _check(root, _resolve(root, s["$ref"]), v, path, out)
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(TYPES[t](v) for t in types):
            out.append("%s: %r is not %s" % (path, v, " or ".join(types)))
            return
    if "enum" in s and not any(v == e and type(v) is type(e) for e in s["enum"]):
        out.append("%s: %r is not one of %r" % (path, v, s["enum"]))
    if "const" in s and not (v == s["const"] and type(v) is type(s["const"])):
        out.append("%s: %r is not %r" % (path, v, s["const"]))
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append("%s: %r does not match %s" % (path, v, s["pattern"]))
        if "minLength" in s and len(v) < s["minLength"]:
            out.append("%s: shorter than %d" % (path, s["minLength"]))
        if "maxLength" in s and len(v) > s["maxLength"]:
            out.append("%s: longer than %d" % (path, s["maxLength"]))
    if TYPES["number"](v):
        if "minimum" in s and v < s["minimum"]:
            out.append("%s: %r is below %r" % (path, v, s["minimum"]))
        if "maximum" in s and v > s["maximum"]:
            out.append("%s: %r is above %r" % (path, v, s["maximum"]))
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", ()):
            if k not in v:
                out.append("%s: %s is missing" % (path, k))
        if "minProperties" in s and len(v) < s["minProperties"]:
            out.append("%s: fewer than %d keys" % (path, s["minProperties"]))
        for k, val in v.items():
            if k in props:
                _check(root, props[k], val, "%s.%s" % (path, k), out)
            elif "additionalProperties" in s:
                _check(root, s["additionalProperties"], val, "%s.%s" % (path, k), out)
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            out.append("%s: fewer than %d items" % (path, s["minItems"]))
        if "maxItems" in s and len(v) > s["maxItems"]:
            out.append("%s: more than %d items" % (path, s["maxItems"]))
        if "items" in s:
            for i, item in enumerate(v):
                _check(root, s["items"], item, "%s[%d]" % (path, i), out)
    for sub in s.get("allOf", ()):
        _check(root, sub, v, path, out)
    if "anyOf" in s and not any(not _errs(root, sub, v, path) for sub in s["anyOf"]):
        out.append("%s: fits none of anyOf" % path)
    if "oneOf" in s:
        fits = sum(1 for sub in s["oneOf"] if not _errs(root, sub, v, path))
        if fits != 1:
            best = min((_errs(root, sub, v, path) for sub in s["oneOf"]), key=len)
            out.append("%s: fits %d of oneOf, not 1%s" % (path, fits, (" (" + best[0] + ")") if best else ""))
    if "not" in s and not _errs(root, s["not"], v, path):
        out.append("%s: fits a shape it must not" % path)
    if "if" in s:
        branch = s.get("then") if not _errs(root, s["if"], v, path) else s.get("else")
        if branch is not None:
            _check(root, branch, v, path, out)


def _errs(root, s, v, path):
    out = []
    _check(root, s, v, path, out)
    return out


def errors(schema, doc, name):
    """The problems of `doc` against `$defs/<name>` of `schema`."""
    return _errs(schema, schema["$defs"][name], doc, name)
