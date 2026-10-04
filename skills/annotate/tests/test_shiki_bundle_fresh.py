"""The committed highlighter was built from the committed build script.

shiki.min.js's first line carries the hash tools/shiki/build.mjs computed;
this recomputes it the same way (sha256 over build.mjs, package.json and
package-lock.json, in that order), so an edit to the language list, the
themes or a version pin without a rebuild fails here. Needs no node.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "tools" / "shiki"
STATIC = REPO / "skills" / "annotate" / "static"
BUNDLE = STATIC / "shiki.min.js"
LANGS = STATIC / "shiki-langs"
STALE = "the highlighter is stale: cd tools/shiki && npm ci && npm run build"


def _source_hash() -> str:
    h = hashlib.sha256()
    for name in ("build.mjs", "package.json", "package-lock.json"):
        h.update((TOOL / name).read_bytes())
    return h.hexdigest()


def test_the_bundle_matches_its_build_script():
    first = BUNDLE.read_bytes().split(b"\n", 1)[0].decode()
    m = re.fullmatch(r"/\* annotate-shiki ([0-9a-f]{64}) \*/", first)
    assert m and m.group(1) == _source_hash(), STALE


def test_every_grammar_the_index_names_was_built():
    """The bundle's index maps each language name to a module in shiki-langs/;
    a module it names and the build did not write is a language that fails
    the first time a page asks for it."""
    src = BUNDLE.read_text()
    m = re.search(r"\{(\"?java\"?:\"java\",[^}]*)\}", src)
    assert m, "no language index in shiki.min.js"
    modules = set(re.findall(r':"([\w-]+)"', m.group(1)))
    assert len(modules) >= 40, f"the index names only {len(modules)} grammars"
    missing = sorted(mod for mod in modules if not (LANGS / f"{mod}.js").is_file())
    assert not missing, f"{STALE} (missing: {', '.join(missing)})"


def test_every_chunk_a_grammar_imports_was_built():
    missing = set()
    for js in LANGS.glob("*.js"):
        for dep in re.findall(r'from"\./([\w-]+\.js)"|import"\./([\w-]+\.js)"', js.read_text()):
            for name in dep:
                if name and not (LANGS / name).is_file():
                    missing.add(name)
    assert not missing, f"{STALE} (missing: {', '.join(sorted(missing))})"


def test_the_grammars_are_not_back_inside_the_bundle():
    """They load on demand. Inlined, the page parsed 3.2 MB of grammars
    before it showed any code."""
    size = BUNDLE.stat().st_size
    assert size < 1_200_000, f"shiki.min.js is {size} bytes: grammars have been bundled back in"
