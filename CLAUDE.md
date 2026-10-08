# claude-annotate

Run the tests with:

    uv run -q --with-requirements requirements-test.txt python -m pytest skills -q

`requirements-test.txt` pins the test tooling for CI, the pre-push hook and this command alike: pytest, pytest-xdist, playwright and the webcompanion daemon. Once per machine (and after a playwright bump), install its browser:

    uv run -q --with-requirements requirements-test.txt python -m playwright install chromium

While developing, run the fast loop first: every test that does not drive a browser, about 2,080 of them in about 15 seconds, plus the browser file for what you changed:

    uv run -q --with-requirements requirements-test.txt python -m pytest skills -q -m "not browser"

The whole suite still runs before every push (below). Nearly all of its time is the browser tests.

`pytest.ini` runs them in parallel on 4 workers (`-n 4`), not `-n auto`: each worker drives its own Chromium, and one Chromium per core on a many-core laptop once coincided with a hard system freeze. Do not raise it on a laptop, and do not run the suite alongside other heavy jobs (local speech models, other browser suites). For one file, name it instead of `skills`. Add `-n 0` to run serially.

The browser and push suites never touch the daemon you are running. Each xdist worker starts its own webcompanion from the pinned package, under a throwaway HOME on a free port, and one Chromium that every test takes a fresh context from (`skills/tests/harness.py`, `skills/conftest.py`). Without playwright or webcompanion those suites skip; `CLAUDE_ANNOTATE_STRICT_TESTS=1` makes that a failure, and CI and the pre-push hook set it. On a slow machine, `PYTEST_TIMEOUT_SCALE=2` doubles every explicit browser wait.

A green suite does not show that the tests guard the code. `/audit-tests` (`tools/audit_tests.py`) plants small bugs in the lines changed since its last run and reports each one no test fails on, plus flaky tests and tests that run exactly the same lines as another. When planting a bug by hand to watch a new test fail, set `PYTHONDONTWRITEBYTECODE=1`: a file restored within the same second at the same size otherwise runs the planted bug again from Python's cache (`~/.cache/pycache`).

`.githooks/pre-push` runs the suite as CI does, strict and with an empty `HOME` so no daemon config of yours is reachable, after compiling and collecting it under Python 3.9, and blocks the push if anything fails. A fresh clone enables it with:

    git config core.hooksPath .githooks
