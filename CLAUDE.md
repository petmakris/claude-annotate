# claude-annotate

Run the tests with:

    uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q

`pytest.ini` runs them in parallel (`-n auto`), about 40 seconds for the whole suite. For one file, name it instead of `skills`. Add `-n 0` to run serially.

`.githooks/pre-push` runs the suite as CI does, with an empty `HOME` so no webcompanion daemon is reachable, and blocks the push if it fails. A test that only passes against the local daemon breaks CI on main, so this catches it first. A fresh clone enables it with:

    git config core.hooksPath .githooks
