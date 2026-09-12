"""A diagram lifted out of the page and made into a file.

The SVG the server stores is class names and geometry — no colours, no fonts.
Everything that makes it legible is in core.css (the palette and the type) and
diagram.css (the tone tokens). Both must travel with it, and so must the woff2
faces, or the picture on Confluence is black shapes in the wrong font."""
import base64
import shutil
import struct
import subprocess
import zlib

import pytest

from skills.annotate.confluence import images

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" '
       'width="200" height="100" class="annotate-seq">'
       '<rect class="actor-box tone-edge" x="10" y="10" width="80" '
       'height="30"/><text class="actor-label" x="50" y="30">A</text></svg>')


def _top_left_pixel(png_path):
    """Decode the first (top-left) pixel of an 8-bit, non-interlaced PNG.

    A minimal, stdlib-only PNG reader: it decompresses the IDAT stream and
    un-filters only row 0 (whose "previous row" is defined as all zeros, so
    every PNG filter type reduces to depending only on already-reconstructed
    bytes within that same row — no need to walk the rest of the image)."""
    data = png_path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    length = struct.unpack(">I", data[8:12])[0]
    assert data[12:16] == b"IHDR"
    width, height, bitdepth, color_type = struct.unpack(">IIBB", data[16:26])
    assert bitdepth == 8, "decoder only handles 8-bit PNGs"
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]

    idat = bytearray()
    i = 8
    while i < len(data):
        clen = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        chunk = data[i + 8:i + 8 + clen]
        if ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        i += 8 + clen + 4

    raw = zlib.decompress(bytes(idat))
    filter_type = raw[0]
    row = bytearray(raw[1:1 + width * channels])
    if filter_type in (1, 4):  # Sub, Paeth (both reduce to "+= left" on row 0)
        for x in range(channels, len(row)):
            row[x] = (row[x] + row[x - channels]) % 256
    elif filter_type == 3:  # Average (right half of the sum is 0 on row 0)
        for x in range(channels, len(row)):
            row[x] = (row[x] + row[x - channels] // 2) % 256
    elif filter_type not in (0, 2):  # None, Up are no-ops on row 0
        raise ValueError("unexpected PNG filter type %d" % filter_type)
    return tuple(row[:3])


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


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs node")
def test_the_background_is_the_cards_surface_not_the_page_ground(tmp_path):
    # svg.annotate-flow paints no background of its own on the live page —
    # what shows through is its card (section.block), --surface #f8f9fb, not
    # the page body's --bg #e4e7ed. A pixel with no shape drawn over it (the
    # SVG's top-left corner, well clear of the actor box at x=10,y=10) must
    # decode to the card colour.
    try:
        out = images.render_png(SVG, tmp_path / "bg.png")
    except images.ChromiumMissing as e:
        pytest.skip(str(e))
    assert _top_left_pixel(out) == (248, 249, 251)


def test_a_missing_chromium_is_named_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "Cannot find module 'playwright'"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "playwright" in str(e.value)
