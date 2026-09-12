"""A diagram lifted out of the page and made into a file.

The SVG the server stores is class names and geometry — no colours, no fonts.
Everything that makes it legible is in core.css (the palette and the type) and
diagram.css (the tone tokens). Both must travel with it, and so must the woff2
faces, or the picture on Confluence is black shapes in the wrong font."""
import base64
import shutil
import subprocess

import pytest

from skills.annotate.confluence import images

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" '
       'width="200" height="100" class="annotate-seq">'
       '<rect class="actor-box tone-edge" x="10" y="10" width="80" '
       'height="30"/><text class="actor-label" x="50" y="30">A</text></svg>')


def test_the_stylesheets_are_inlined_not_linked():
    out = images.standalone_html(SVG)
    assert "<link" not in out
    assert "--t-edge:" in out          # from diagram.css
    assert "--accent:" in out          # from core.css


def test_the_fonts_are_embedded_as_data_uris():
    out = images.standalone_html(SVG)
    assert "url('fonts/" not in out
    assert "data:font/woff2;base64," in out


def test_the_font_bytes_are_the_real_file():
    out = images.standalone_html(SVG)
    blob = out.split("data:font/woff2;base64,", 1)[1].split("'", 1)[0]
    assert base64.b64decode(blob)[:4] == b"wOF2"


def test_the_svg_itself_is_present_unmodified():
    assert SVG in images.standalone_html(SVG)


def test_the_page_is_painted_light_regardless_of_the_machine():
    # The renderer machine may be in dark mode; the published picture must not
    # depend on it.
    assert "color-scheme: light" in images.standalone_html(SVG)


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs node")
def test_a_png_comes_out_at_twice_the_viewbox(tmp_path):
    try:
        out = images.render_png(SVG, tmp_path / "section-2.png")
    except images.ChromiumMissing as e:
        pytest.skip(str(e))
    assert out.exists()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(out.read_bytes()[16:20], "big")
    height = int.from_bytes(out.read_bytes()[20:24], "big")
    assert (width, height) == (400, 200)


def test_a_missing_chromium_is_named_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "Cannot find module 'playwright'"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "playwright" in str(e.value)
