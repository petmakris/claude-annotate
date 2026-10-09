# claude-annotate

Run the tests with:

    uv run -q --with-requirements requirements-test.txt python -m pytest skills -q

`requirements-test.txt` pins the test tooling for CI, the pre-push hook and this command alike: pytest, pytest-xdist and aiohttp. The suite runs about 2,080 tests in about 15 seconds, on 4 workers (`pytest.ini`). For one file, name it instead of `skills`. Add `-n 0` to run serially.

The suite has no browser tests and starts no daemon: no test drives Chromium, and none needs webcompanion running. Keep it that way. A few tests run the page's JavaScript under node and skip without it. `skills/stage/tests/stage_page.py` and `skills/talk/tests/call_page.py` run the real `stage.js` and `call.js` under node on a small DOM (`skills/_shared/tests/dom_shim.mjs`), for page logic only: every box measures 0, so nothing about layout can be checked there.

A green suite does not show that the tests guard the code. `/audit-tests` (`tools/audit_tests.py`) plants small bugs in the lines changed since its last run and reports each one no test fails on, plus flaky tests and tests that run exactly the same lines as another. When planting a bug by hand to watch a new test fail, set `PYTHONDONTWRITEBYTECODE=1`: a file restored within the same second at the same size otherwise runs the planted bug again from Python's cache (`~/.cache/pycache`).

`.githooks/pre-push` runs the suite as CI does, with an empty `HOME` so no daemon config of yours is reachable, after compiling and collecting it under Python 3.9, and blocks the push if anything fails. A fresh clone enables it with:

    git config core.hooksPath .githooks

The stage's rules (`skills/stage/SKILL.md`, "What the stage keeps true") are checked on compiled frames by `stage_rule_breaks` in `skills/talk/tests/helpers.py`: call it on any reply a new test compiles. The scene compiler names what is being said in every frame (`cur`); the page draws that and never works it out itself. A saved scene from before `cur` is the one exception: `settled()` in `skills/stage/static/scene.js` gives its frames today's arrow rule as the view arrives, and `beingSaid()` guesses its part being said.

A board keeps one scene per answer that stepped it (`scenes`, keyed by the answer number as a string; `scene` is the one of the answer that last put the board up, absent when that answer had none). In `stage.js` read a view's scene through `sceneOf(v)` or `painted(v)`, never `v.body.scene`, so a replayed answer steps its own frames. Talk numbers an answer by the Claude entries before it, so a test that splits two replies must `call.add("claude", ...)` between them, or both get the same number.

The stage demo's change board (`skills/talk/demo.md`, "Cells and the current one") points at line numbers of `skills/stage/static/scene.js` against an old revision. An edit to that file above those lines moves them: re-point the demo in the same change (`test_the_demos_change_board_points_at_the_lines_it_talks_about` in `skills/talk/tests/test_demo.py` fails until you do, and `/audit-demo` checks the rest).

On the call page every play the reader starts (Play, Space, a tapped word, the conversation's ▶, a spoken "go on", the media keys) goes through `toVoice()` in `skills/talk/static/call.js`, which turns following back on and resends the whole picture. A new way to start playback must call it too; an automatic play (a new answer, a held answer picking up after the user spoke) must not.

The map (`skills/stage/static/map.js`) places its parts once per board size, with room round each for the larger card it becomes when said, and picks its layout (`data-layout`: `ring`, `across`, `down`) by what fits. When the card being said changes, only the arrows and labels are redrawn.

The lanes (`skills/stage/static/lanes.js`) measure their chips and notes to place them. A line folded with an ellipsis is measured by what shows inside its box: a text range alone reports the clipped words too.
