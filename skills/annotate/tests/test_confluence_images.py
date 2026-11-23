"""A diagram lifted out of the page and made into a file.

The SVG the server stores is class names and geometry — no colours, no fonts.
Everything that makes it legible is in core.css (the palette and the type) and
diagram.css (the tone tokens). Both must travel with it, and so must the woff2
faces, or the picture on Confluence is black shapes in the wrong font."""
import base64
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


def test_a_missing_chromium_is_named_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "Cannot find module 'playwright'"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "playwright" in str(e.value)


def test_a_missing_node_module_is_not_blamed_on_chromium(tmp_path, monkeypatch):
    """The two PNG tests skip with this message on a machine that has Chromium
    but not the Node `playwright` package, and the message sent people to
    install a browser they already had."""
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "Error: Cannot find module 'playwright'"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    msg = str(e.value)
    assert "Node `playwright` module is not installed" in msg
    assert "npm install -g playwright" in msg
    assert "headless Chromium is not available" not in msg


def test_a_missing_browser_is_still_named_as_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_node_script",
                        lambda *a, **k: subprocess.CompletedProcess(
                            [], 1, "", "browserType.launch: Executable doesn't exist"
                                       " at /x/chromium-1/chrome"))
    with pytest.raises(images.ChromiumMissing) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "npx playwright install chromium" in str(e.value)
    assert "module is not installed" not in str(e.value)


def test_a_stalled_renderer_is_a_failure_not_a_hang(tmp_path, monkeypatch):
    """Headless Chromium can wedge; publishing must stop with an error that
    says so instead of waiting forever."""
    timeouts = []

    def stalled(cmd, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        if cmd[:2] == ["npm", "root"]:
            return subprocess.CompletedProcess(cmd, 0, "/g/node_modules\n", "")
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(images, "_npm_root_cache", None)
    monkeypatch.setattr(images.subprocess, "run", stalled)
    with pytest.raises(RuntimeError) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert not isinstance(e.value, images.ChromiumMissing)
    assert "did not finish" in str(e.value)
    assert None not in timeouts


def test_a_stalled_npm_is_a_failure_not_a_hang(tmp_path, monkeypatch):
    def stalled(cmd, **kwargs):
        assert kwargs.get("timeout") is not None
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(images, "_npm_root_cache", None)
    monkeypatch.setattr(images.subprocess, "run", stalled)
    with pytest.raises(RuntimeError) as e:
        images.render_png(SVG, tmp_path / "x.png")
    assert "npm root -g" in str(e.value)


def test_npm_root_is_asked_once_per_process(tmp_path, monkeypatch):
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "npm":
            return subprocess.CompletedProcess(cmd, 0, "/g/node_modules\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(images, "_npm_root_cache", None)
    monkeypatch.setattr(images.subprocess, "run", fake)
    images.render_png(SVG, tmp_path / "a.png")
    images.render_png(SVG, tmp_path / "b.png")
    assert calls.count("npm") == 1


def test_several_diagrams_share_one_chromium(tmp_path, monkeypatch):
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "npm":
            return subprocess.CompletedProcess(cmd, 0, "/g/node_modules\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(images, "_npm_root_cache", None)
    monkeypatch.setattr(images.subprocess, "run", fake)
    images.render_pngs([(SVG, tmp_path / "a.png"), (SVG, tmp_path / "b.png"),
                        (SVG, tmp_path / "c.png")])
    assert calls.count("node") == 1
