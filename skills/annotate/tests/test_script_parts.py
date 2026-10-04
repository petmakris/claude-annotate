"""The page code's parts share one global scope; nothing else may claim its names.

script.js was one IIFE, so its ~140 top-level names were private. Split along
its section markers into nine classic scripts (see script.js's header), those
names are globals now: that is how one part reaches what another declared.
What that costs is a namespace, and these tests keep it clean:

- a name declared twice across the parts is a `const` redeclaration (the
  second part fails to load at all) or a function silently replaced;
- a name another classic script on the page declares at its top level is the
  same collision from the other side;
- a name the browser already defines on `window` (`close`, `name`, `status`,
  `top`, ...) is shadowed, or for some of them refused outright.

Each part must also parse on its own: they load as separate scripts.
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from skills.annotate.tests.page_source import STATIC, script_parts, style_parts

TOP = re.compile(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|^(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)


def _declared(text: str) -> list[str]:
    return [a or b for a, b in TOP.findall(text)]


def _parts():
    return {name: (STATIC / name).read_text() for name in script_parts()}


def test_the_page_code_is_its_parts():
    parts = script_parts()
    assert parts[0] == "script.js" and len(parts) == 9, parts
    names = [n for text in _parts().values() for n in _declared(text)]
    assert len(names) > 100, f"only {len(names)} top-level names: is the page code back in one IIFE?"


def test_no_name_is_declared_twice_across_the_parts():
    seen = {}
    twice = []
    for part, text in _parts().items():
        for n in _declared(text):
            if n in seen:
                twice.append(f"{n}: {seen[n]} and {part}")
            seen[n] = part
    assert not twice, "declared more than once:\n  " + "\n  ".join(twice)


def test_no_other_page_script_declares_a_part_name():
    mine = {n for text in _parts().values() for n in _declared(text)}
    parts = set(script_parts())
    clashes = []
    for js in sorted(STATIC.glob("*.js")):
        if js.name in parts or js.name.endswith(".min.js") or js.name in ("entry.js", "shell.js", "wc-boot.js"):
            continue
        for n in _declared(js.read_text()):
            if n in mine:
                clashes.append(f"{js.name}: {n}")
    assert not clashes, "top-level names that collide with the page code:\n  " + "\n  ".join(clashes)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_each_part_parses_on_its_own():
    for name in script_parts():
        proc = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"{name}: {proc.stderr}"


def test_no_part_name_shadows_a_browser_global(browser):
    mine = sorted({n for text in _parts().values() for n in _declared(text)})
    page = browser.new_page()
    page.set_content("<!doctype html><title>x</title>")
    taken = page.evaluate("""(names) => names.filter((n) => n in window)""", mine)
    assert not taken, f"names the browser already defines on window: {taken}"


def test_every_part_on_disk_is_loaded():
    """A part entry.js does not list never runs, and nothing on the page says so."""
    on_disk = sorted(p.name for p in STATIC.glob("script*.js"))
    assert on_disk == sorted(script_parts()), f"on disk {on_disk}, loaded {script_parts()}"


def test_every_stylesheet_part_on_disk_is_linked():
    on_disk = sorted(p.name for p in STATIC.glob("style*.css"))
    assert on_disk == sorted(style_parts()), f"on disk {on_disk}, linked {style_parts()}"
