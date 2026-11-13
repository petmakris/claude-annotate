"""bin/decks: finding the decks folder and setting one up."""
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
DECKS = SKILL / "bin" / "decks"


def run(*args, config_home, env=None):
    full = {k: v for k, v in os.environ.items() if k not in ("SLIDES_DECKS_DIR", "MB_DECKS_DIR")}
    full.update({"XDG_CONFIG_HOME": str(config_home), **(env or {})})
    return subprocess.run([sys.executable, str(DECKS), *map(str, args)],
                          capture_output=True, text=True, env=full)


def test_nothing_set_means_exit_3_and_a_hint(tmp_path):
    done = run("where", config_home=tmp_path)
    assert done.returncode == 3
    assert "decks init" in done.stderr


def test_init_creates_the_folder_and_records_it(tmp_path):
    target = tmp_path / "talks"
    done = run("init", target, "--use", config_home=tmp_path / "cfg")
    assert done.returncode == 0, done.stderr
    for name in ("README.md", "PRESENTATION-STYLE.md", "export-pdf.py", ".gitignore"):
        assert (target / name).is_file(), name
    config = json.loads((tmp_path / "cfg" / "slides" / "config.json").read_text())
    assert config["decks_dir"] == str(target.resolve())
    where = run("where", config_home=tmp_path / "cfg")
    assert where.returncode == 0 and str(target.resolve()) in where.stdout


def test_init_never_overwrites_a_file_the_user_has(tmp_path):
    target = tmp_path / "talks"
    target.mkdir()
    (target / "PRESENTATION-STYLE.md").write_text("mine")
    run("init", target, config_home=tmp_path / "cfg")
    assert (target / "PRESENTATION-STYLE.md").read_text() == "mine"


def test_the_environment_beats_the_config(tmp_path):
    cfg = tmp_path / "cfg" / "slides"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"decks_dir": "/from/config"}))
    done = run("where", config_home=tmp_path / "cfg", env={"SLIDES_DECKS_DIR": "/from/env"})
    assert "/from/env" in done.stdout and "$SLIDES_DECKS_DIR" in done.stdout


def test_a_folder_without_the_exporter_is_flagged(tmp_path):
    done = run("where", config_home=tmp_path, env={"SLIDES_DECKS_DIR": str(tmp_path)})
    assert "not set up" in done.stdout


def test_the_shipped_exporter_compiles():
    compile((SKILL / "templates" / "export-pdf.py").read_text(), "export-pdf.py", "exec")
