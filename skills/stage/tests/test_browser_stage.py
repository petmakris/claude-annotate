"""A newly shown view comes to the front, and a saved file reloads its own frame and keeps
its slide without taking the front back, measured in a real browser.

Skips without playwright, without a running daemon, or when the daemon predates mounts.
Makes its own stage session in a temporary project and deletes it afterwards."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from unittest.mock import patch  # noqa: E402

from skills.stage import model, stage  # noqa: E402

CONFIG = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


def _daemon_has_mounts() -> bool:
    if not CONFIG.exists():
        return False
    port = json.loads(CONFIG.read_text())["port"]
    req = urllib.request.Request("http://127.0.0.1:%d/s/nope/api/mounts" % port, data=b"{}", method="POST")
    try:
        urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as e:
        return e.code != 404 or "no such session" in e.read().decode()
    except OSError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _daemon_has_mounts(), reason="needs a running webcompanion with mounts")


def test_a_new_view_comes_to_the_front_and_a_saved_file_reloads_only_its_frame(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    deck = proj / "deck.html"
    deck.write_text("<section id='slide-2'><h1 id='v'>one</h1></section><section id='slide-3'></section>")
    # No background watcher: this test drives tick() itself, and a real watcher would race it.
    no_watch = patch.object(stage, "start_watch", lambda cwd, sid: None)
    no_watch.start()
    res = stage.show(str(proj), "deck", model.parse_source("deck.html#slide-2", proj), title="Deck")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(res["url"])
            frame_el = page.wait_for_selector('section.pane[data-view="deck"] iframe.frame')
            frame = frame_el.content_frame()
            frame.wait_for_function("document.getElementById('v')?.textContent === 'one'")
            # A second view shown (not --background) while the page is open comes to the front,
            # even though the daemon lists __layout__ before the view it names.
            stage.show(str(proj), "notes", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"})
            notes_tab = page.locator('button[role=tab][data-view="notes"]')
            notes_tab.wait_for()
            page.wait_for_function(
                "document.querySelector('button[role=tab][data-view=\"notes\"]')"
                "?.getAttribute('aria-selected') === 'true'", timeout=5000)
            assert page.locator('button[role=tab][data-view="deck"]').get_attribute("aria-selected") == "false"
            # Back on the deck to move its slide, then onto the notes again.
            page.locator('button[role=tab][data-view="deck"]').click()
            # Regression probes: move off the source fragment and onto the notes tab, and
            # tag the iframe element itself, so a pane rebuild (which would lose all three)
            # is distinguishable from an in-place reload (which must keep all three).
            frame.evaluate("location.hash = 'slide-3'")
            frame_el.evaluate("e => e.dataset.probe = '1'")
            notes_tab.click()
            deck.write_text("<section id='slide-2'><h1 id='v'>two</h1></section><section id='slide-3'></section>")
            t = time.time() + 5
            os.utime(deck, (t, t))
            assert stage.tick(str(proj), res["sid"]) == ["deck"]
            reloaded = frame_el.content_frame()
            reloaded.wait_for_function("document.getElementById('v')?.textContent === 'two'", timeout=5000)
            assert frame_el.evaluate("e => e.dataset.probe") == "1"
            assert reloaded.evaluate("location.hash") == "#slide-3"
            assert notes_tab.get_attribute("aria-selected") == "true"
            assert page.locator("button[role=tab]").count() == 2
            browser.close()
    finally:
        no_watch.stop()
        port = json.loads(CONFIG.read_text())["port"]
        req = urllib.request.Request("http://127.0.0.1:%d/s/%s/?kind=stage&force=1" % (port, res["sid"]),
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=5)


def test_a_failed_first_load_says_so_instead_of_an_empty_stage(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    res = stage.show(str(proj), "notes", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"})
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.route(lambda url: url.split("?")[0].endswith("/items"),
                       lambda route: route.fulfill(status=500, body="boom"))
            page.goto(res["url"])
            line = page.locator(".panes .empty")
            line.filter(has_text="Could not load the stage").wait_for(timeout=5000)
            assert line.text_content() == "Could not load the stage: items: 500. Reload to retry."
            # Later changes are dropped, not queued behind a snapshot that never comes.
            stage.show(str(proj), "more", {"type": "url", "url": "https://example.com"})
            page.wait_for_timeout(1000)
            assert page.locator("button[role=tab]").count() == 0
            assert line.is_visible()
            browser.close()
    finally:
        port = json.loads(CONFIG.read_text())["port"]
        req = urllib.request.Request("http://127.0.0.1:%d/s/%s/?kind=stage&force=1" % (port, res["sid"]),
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=5)
