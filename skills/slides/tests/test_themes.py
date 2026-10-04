"""inline.py: the framework and a theme become snapshots inside a deck."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
INLINE = SKILL / "framework" / "inline.py"
SKELETON = SKILL / "references" / "skeleton.html"


def run(*args, config_home, env=None):
    full = {**os.environ, "XDG_CONFIG_HOME": str(config_home), **(env or {})}
    full.pop("SLIDES_THEME", None) if not (env and "SLIDES_THEME" in env) else None
    return subprocess.run([sys.executable, str(INLINE), *map(str, args)],
                          capture_output=True, text=True, env=full)


@pytest.fixture
def deck(tmp_path):
    path = tmp_path / "2026.01.01-demo" / "2026.01.01-demo.html"
    path.parent.mkdir()
    shutil.copyfile(SKELETON, path)
    return path


def make_theme(root, name, css=":root{--accent:#123456}", logo=None, readme=None):
    theme = root / "slides" / "themes" / name
    theme.mkdir(parents=True)
    (theme / "theme.css").write_text(css)
    if logo:
        (theme / "logo.svg").write_text(logo)
    if readme:
        (theme / "README.md").write_text(readme)
    return theme


def test_the_default_theme_is_used_when_nothing_is_configured(deck, tmp_path):
    done = run(deck, config_home=tmp_path / "cfg")
    assert done.returncode == 0, done.stderr
    html = deck.read_text()
    assert "theme:css snapshot of 'default'" in html
    assert "--accent:#B85C2E" in html
    assert "framework:css snapshot v" in html and "framework:js snapshot v" in html


def test_the_default_theme_sets_every_token_the_framework_uses():
    framework = (SKILL / "framework" / "deck.css").read_text() + (SKILL / "framework" / "deck.js").read_text()
    used = set(re.findall(r"var\((--[\w-]+)", framework))
    theme = (SKILL / "themes" / "default" / "theme.css").read_text()
    defined = set(re.findall(r"(--[\w-]+)\s*:", theme))
    # set at run time by deck.js, not a theme token
    runtime = set(re.findall(r"setProperty\(['\"](--[\w-]+)", (SKILL / "framework" / "deck.js").read_text()))
    assert used - defined - runtime == set()


def test_the_framework_names_no_colour_the_theme_should_own():
    css = (SKILL / "framework" / "deck.css").read_text()
    assert ":root{" not in css.replace(" ", "")


def test_a_configured_theme_and_its_logo_are_inlined(deck, tmp_path):
    cfg = tmp_path / "cfg"
    make_theme(cfg, "brand", css=":root{--accent:#123456}", logo='<svg aria-label="Brand"></svg>')
    (cfg / "slides" / "config.json").write_text(json.dumps({"theme": "brand"}))
    done = run(deck, config_home=cfg)
    assert done.returncode == 0, done.stderr
    html = deck.read_text()
    assert "--accent:#123456" in html
    assert '<!-- theme:logo --><svg aria-label="Brand"></svg><!-- /theme:logo -->' in html


def test_the_command_line_beats_the_config(deck, tmp_path):
    cfg = tmp_path / "cfg"
    make_theme(cfg, "brand", css=":root{--accent:#111111}")
    make_theme(cfg, "other", css=":root{--accent:#222222}")
    (cfg / "slides" / "config.json").write_text(json.dumps({"theme": "brand"}))
    assert run(deck, "--theme", "other", config_home=cfg).returncode == 0
    assert "--accent:#222222" in deck.read_text()


def test_a_theme_can_be_a_path(deck, tmp_path):
    theme = make_theme(tmp_path / "elsewhere", "loose", css=":root{--accent:#333333}")
    assert run(deck, "--theme", theme, config_home=tmp_path / "cfg").returncode == 0
    assert "--accent:#333333" in deck.read_text()


def test_an_unknown_theme_is_refused_and_the_deck_left_alone(deck, tmp_path):
    before = deck.read_text()
    done = run(deck, "--theme", "nope", config_home=tmp_path / "cfg")
    assert done.returncode != 0
    assert "theme 'nope'" in (done.stderr + done.stdout)
    assert deck.read_text() == before


def test_re_inlining_replaces_rather_than_stacks(deck, tmp_path):
    cfg = tmp_path / "cfg"
    run(deck, config_home=cfg)
    run(deck, config_home=cfg)
    html = deck.read_text()
    assert html.count("<!-- theme:css -->") == 1
    assert html.count("<!-- framework:css -->") == 1


def test_a_deck_from_before_themes_gets_a_theme_block(deck, tmp_path):
    html = deck.read_text().replace("<!-- theme:css -->\n<!-- /theme:css -->\n", "")
    deck.write_text(html)
    assert run(deck, config_home=tmp_path / "cfg").returncode == 0
    out = deck.read_text()
    assert out.index("<!-- /framework:css -->") < out.index("<!-- theme:css -->")


def test_which_theme_says_why(tmp_path):
    done = run("--which-theme", config_home=tmp_path / "cfg")
    assert done.returncode == 0
    assert "default" in done.stdout and "no theme configured" in done.stdout
