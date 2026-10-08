# claude-annotate

Run the tests with:

    uv run -q --with-requirements requirements-test.txt python -m pytest skills -q

`requirements-test.txt` pins the test tooling for CI, the pre-push hook and this command alike: pytest, pytest-xdist and aiohttp. The suite runs about 2,080 tests in about 15 seconds, on 4 workers (`pytest.ini`). For one file, name it instead of `skills`. Add `-n 0` to run serially.

The suite has no browser tests and starts no daemon: no test drives Chromium, and none needs webcompanion running. Keep it that way. A few tests run the page's JavaScript under node and skip without it.

A green suite does not show that the tests guard the code. `/audit-tests` (`tools/audit_tests.py`) plants small bugs in the lines changed since its last run and reports each one no test fails on, plus flaky tests and tests that run exactly the same lines as another. When planting a bug by hand to watch a new test fail, set `PYTHONDONTWRITEBYTECODE=1`: a file restored within the same second at the same size otherwise runs the planted bug again from Python's cache (`~/.cache/pycache`).

`.githooks/pre-push` runs the suite as CI does, with an empty `HOME` so no daemon config of yours is reachable, after compiling and collecting it under Python 3.9, and blocks the push if anything fails. A fresh clone enables it with:

    git config core.hooksPath .githooks
