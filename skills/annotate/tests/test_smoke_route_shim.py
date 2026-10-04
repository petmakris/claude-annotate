"""Every route the page asks for must be answered by something.

annotate's page code was written against annotate's own server. That server is
gone; the daemon serves a different, smaller surface. `compat.js` bridges the
two by patching `window.fetch` and synthesising the old routes in the browser —
`raw` from `__doc__` plus one GET per block, `prev` from the `__prev__` item
`push.py` writes.

Two consequences, and this file exists for both.

The first is a real failure mode, named in compat.js's own comment: patching
individual call sites "would work until the next one is written". Patching
fetch covers today's callers and tomorrow's, but only for the route NAMES in
its table. A call site that asks for something not in that table reaches the
daemon, 404s, and — because every one of these callers is wrapped in a
try/catch that hides the feature rather than reporting it — fails in complete
silence. Nothing checked that the table still covers what the page asks for.

The second is that these routes 404 over HTTP BY DESIGN, and everything
outside the browser sees that: curl, a shell test, a reader with a terminal.
That is exactly how they were once misread as three silently-broken features
and reported as a live bug. The routes were fine; the test was wrong. So this
file also serves as the written answer to "why does /prev 404?".
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

# Session-relative routes the DAEMON itself serves, from webcompanion's
# server.py route table (_SID_*_RE). Listed by hand on purpose: this is a
# contract with another repo, and a route appearing here should be a decision
# somebody made, not something a regex inferred from whatever is installed.
DAEMON_ROUTES = {
    "poll", "stream", "items", "threads", "assets",
    "api/finish", "api/cancel", "api/unfinish", "api/submit",
    "api/upload", "api/assets", "api/threads/delete",
}


def _client_js():
    for f in sorted(STATIC.glob("*.js")):
        if "min.js" in f.name or f.name == "compat.js":
            continue
        yield f


def _asked_routes():
    """Every session-relative route name the page fetches.

    Root-absolute paths (/api/whoami, /api/open) are deliberately excluded:
    those are the daemon's own top-level routes, not session-relative ones,
    and they never pass through the shim.
    """
    asked = {}
    for f in _client_js():
        src = f.read_text()
        for pattern in (r'BASE \+ "([a-z_][a-z_/]*)"',
                        r'fetchJSON\("([a-z_][a-z_/]*)"',
                        r'(?<!\.)\bfetch\("([a-z_][a-z_/]*)"'):
            for m in re.finditer(pattern, src):
                asked.setdefault(m.group(1).split("?")[0], set()).add(f.name)
    return asked


def _shimmed_routes():
    src = (STATIC / "compat.js").read_text()
    table = re.search(r"const routes = \{(.*?)\};", src, re.S)
    assert table, "compat.js no longer has a `routes` table to read"
    return set(re.findall(r"^\s*([a-z]+):", table.group(1), re.M))


class TestEveryRouteIsAnswered(unittest.TestCase):
    def test_nothing_the_page_asks_for_falls_through_to_a_404(self):
        shimmed = _shimmed_routes()
        for route, files in sorted(_asked_routes().items()):
            base = route.split("/")[0]
            answered = (route in shimmed or base in shimmed
                        or route in DAEMON_ROUTES or base in DAEMON_ROUTES)
            self.assertTrue(answered,
                            f"{route!r} (asked for in {', '.join(sorted(files))}) is "
                            f"answered by neither compat.js's shim nor the daemon. "
                            f"It will 404 into a try/catch and the feature it "
                            f"belongs to will disappear without a word.")

    def test_the_shim_still_patches_fetch_and_not_just_the_api_object(self):
        # api.fetchJSON alone is not enough: script.js reaches for
        # `fetch(BASE + "raw")` directly, and did so before compat.js existed.
        src = (STATIC / "compat.js").read_text()
        self.assertIn("window.fetch = async function", src,
                      "the shim no longer intercepts direct fetch() calls, so "
                      "any call site not going through api.fetchJSON now 404s")
        self.assertIn("realFetch", src, "the shim no longer chains to the real fetch")

    def test_the_shim_carries_the_routes_it_is_the_only_answer_for(self):
        shimmed = _shimmed_routes()
        for route in ("raw", "prev"):
            self.assertIn(route, shimmed,
                          f"{route!r} has no server-side route on the daemon — "
                          f"dropping it from the shim deletes the feature")

    def test_a_shimmed_route_is_not_also_a_daemon_route(self):
        # Overlap would mean two answers to one question, and whichever won
        # would be an accident of load order.
        self.assertFalse(_shimmed_routes() & DAEMON_ROUTES,
                         "a route is both synthesised and served")
