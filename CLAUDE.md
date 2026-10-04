# claude-annotate

Run the tests with:

    uv run -q --with-requirements requirements-test.txt python -m pytest skills -q

`requirements-test.txt` pins the test tooling for CI, the pre-push hook and this command alike: pytest, pytest-xdist, playwright and the webcompanion daemon. Once per machine (and after a playwright bump), install its browser:

    uv run -q --with-requirements requirements-test.txt python -m playwright install chromium

`pytest.ini` runs them in parallel (`-n auto`): the whole suite, about 2,460 tests with the browser suites, takes about 55 seconds on a busy machine (load average 30-40). For one file, name it instead of `skills`. Add `-n 0` to run serially.

The browser and push suites never touch the daemon you are running. Each xdist worker starts its own webcompanion from the pinned package, under a throwaway HOME on a free port, and one Chromium that every test takes a fresh context from (`skills/tests/harness.py`, `skills/conftest.py`). Without playwright or webcompanion those suites skip; `CLAUDE_ANNOTATE_STRICT_TESTS=1` makes that a failure, and CI and the pre-push hook set it. On a slow machine, `PYTEST_TIMEOUT_SCALE=2` doubles every explicit browser wait.

`.githooks/pre-push` runs the suite as CI does, strict and with an empty `HOME` so no daemon config of yours is reachable, after compiling and collecting it under Python 3.9, and blocks the push if anything fails. A fresh clone enables it with:

    git config core.hooksPath .githooks
