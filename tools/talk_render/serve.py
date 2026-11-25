"""Run claude-annotate's own talk.py from a checkout with the silent engine, never Azure.

    uv run --with aiohttp python serve.py --repo <checkout> -- <talk.py arguments>

Imports <repo>'s talk.py, puts fake_speech in as the engine, and runs talk.main(). Used for the
server (`-- --serve --port N`) and for the launch (`-- --topic ... --port N --no-open ...`), so both
run the checkout's code and neither goes through launchd or touches the engine choice.
"""
import argparse
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--repo", required=True, type=Path)
ap.add_argument("rest", nargs=argparse.REMAINDER)
a = ap.parse_args()
repo = a.repo.resolve()
rest = [x for x in a.rest if x != "--"] if a.rest[:1] == ["--"] else a.rest
sys.path.insert(0, str(repo / "skills" / "talk"))
sys.path.insert(0, str(repo))
sys.path.insert(1, str(here))
import speech  # noqa: E402
import fake_speech  # noqa: E402

speech._engine = fake_speech
import talk  # noqa: E402

assert Path(talk.__file__).resolve().parent == (repo / "skills" / "talk"), talk.__file__
sys.argv = ["talk.py", *rest]
sys.exit(talk.main())
