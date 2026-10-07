"""Fixtures shared by every skill's tests. See skills/tests/harness.py."""
from __future__ import annotations

import shutil

import pytest

from skills.tests import harness


@pytest.fixture(scope="session")
def wc_daemon():
    """A private webcompanion daemon for this xdist worker, started on first
    use and stopped when the worker ends."""
    d = harness.start_daemon()
    try:
        yield d
    finally:
        d.stop()
        shutil.rmtree(d.home, ignore_errors=True)


@pytest.fixture
def wc_config(wc_daemon, monkeypatch):
    """The private daemon, with HOME and every config path pointed at it, so
    push.py, progress.py and their CLIs find it as they would the real one."""
    harness.point_clients_at(wc_daemon, monkeypatch)
    return wc_daemon


@pytest.fixture(scope="session")
def pw():
    """The worker's Playwright driver. Only one sync Playwright may run per
    thread, so every browser test takes it from here rather than its own
    `with sync_playwright()`."""
    harness.require_playwright()
    from playwright.sync_api import sync_playwright
    # The driver finds its browsers under HOME. A test that asked for
    # `wc_config` first has HOME pointed at the daemon's throwaway one, so
    # the driver starts under the HOME this run began with.
    with harness.original_home():
        driver = sync_playwright().start()
    try:
        yield driver
    finally:
        driver.stop()


@pytest.fixture(scope="session")
def browser_session(pw):
    """One Chromium per xdist worker. Module-scoped fixtures take their page
    from this; a test takes `browser` below."""
    b = pw.chromium.launch()
    try:
        yield b
    finally:
        b.close()


@pytest.fixture
def browser(browser_session):
    """The worker's Chromium, for one test. Each `new_page()` /
    `new_context()` is a fresh context — storage, cookies and cache isolated
    the way a fresh launch isolated them — and whatever contexts the test
    opened are closed after it, as closing its own browser used to do, so a
    tab a test forgot cannot keep heartbeating into the next one."""
    before = set(browser_session.contexts)
    try:
        yield browser_session
    finally:
        for ctx in browser_session.contexts:
            if ctx not in before:
                ctx.close()


LIVE_QUEUES = 2  # the live-microphone tests run in this many queues, each one test at a time


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Spread the "live-mic" group over LIVE_QUEUES groups, in turn, so the longest serial chain of the
    suite is split. One live microphone per queue: more side by side starve a busy machine."""
    n = 0
    drives = {}
    for item in items:
        path = str(item.fspath)
        if path not in drives:
            try:
                drives[path] = "playwright" in open(path, encoding="utf-8").read()
            except OSError:
                drives[path] = False
        if drives[path] or {"pw", "browser", "browser_session", "wc_daemon"} & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.browser)  # `-m "not browser"`: the fast loop, seconds instead of minutes
        mark = item.get_closest_marker("xdist_group")
        if mark and (mark.args[:1] or [mark.kwargs.get("name")])[0] == "live-mic":
            item.add_marker(pytest.mark.xdist_group(f"live-mic-{n % LIVE_QUEUES}"), append=False)
            n += 1
