"""Round 4 fixes of stage.py and the code boards (bulldozer bd1125)."""
import io
import json

import pytest

from skills.stage import model, stage
from skills.stage.tests.test_stage import ROW, fake  # noqa: F401  (the fixture)


def test_a_slug_that_names_no_live_stage_is_exit_2_and_creates_nothing(fake, tmp_path, capsys):  # noqa: F811
    fake.rows = [dict(ROW, sid="s1", slug="stage-proj", cwd="/work/proj")]
    for cmd in (["show", "a", "https://a"], ["hide", "a"], ["link"]):
        assert stage.main([*cmd, "--cwd", str(tmp_path), "--slug", "nosuch"]) == 2
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "stage: no live stage named nosuch; live stages: stage-proj in /work/proj"
    assert fake.created == [] and len(err) == 3
    # without --slug a stage is still made when none is live
    fake.rows = []
    assert stage.main(["link", "--cwd", str(tmp_path)]) == 0
    assert len(fake.created) == 1


def test_hide_of_an_unknown_name_is_exit_2_with_the_names_that_exist(fake, tmp_path, capsys):  # noqa: F811
    stage.show(str(tmp_path), "alpha", {"type": "url", "url": "https://a"})
    stage.show(str(tmp_path), "beta", {"type": "url", "url": "https://b"})
    assert stage.main(["hide", "gamma", "--cwd", str(tmp_path)]) == 2
    assert capsys.readouterr().err == "stage: no view named gamma on this stage; views: alpha, beta\n"
    assert stage.main(["hide", "alpha", "--cwd", str(tmp_path)]) == 0
    assert fake.items["__layout__"]["order"] == ["beta"]


def test_a_binary_file_is_refused_by_the_stage_as_talk_refuses_it(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"abc\0def\n")
    with pytest.raises(model.SourceError, match="^bin.dat is a binary file$"):
        model.code_source(tmp_path, "bin.dat:1-1")


def test_lines_no_board_can_carry_are_refused_by_name_never_as_a_daemon_failure(fake, tmp_path, capsys):  # noqa: F811
    (tmp_path / "big.txt").write_text("x" * 5000 + "\nsmall\n")
    (tmp_path / "wide.txt").write_text(("y" * 3500 + "\n") * 60)
    with pytest.raises(model.SourceError, match="line 1 of big.txt is 5000 bytes: a board holds lines of at most 4000 bytes"):
        model.code_source(tmp_path, "big.txt:1-1")
    assert model.code_source(tmp_path, "big.txt:2-2")["lines"] == ["small"]
    with pytest.raises(model.SourceError, match="the lines asked of wide.txt are 210000 bytes: a board holds at most 200000"):
        model.code_source(tmp_path, "wide.txt:1-60")
    assert stage.main(["show", "b", "code:big.txt:1-1", "--cwd", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("stage: line 1 of big.txt is 5000 bytes")


def test_a_change_of_a_very_long_line_is_refused_by_name(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    (tmp_path / "f.txt").write_text("a\n")
    run("add", "f.txt")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    (tmp_path / "f.txt").write_text("a\n" + "z" * 4500 + "\n")
    with pytest.raises(model.SourceError, match="line 2 of f.txt is 4500 bytes"):
        model.change_source(tmp_path, "f.txt")


def test_stage_prints_a_sequence_refs_problems_on_stderr_and_still_shows_the_step(fake, tmp_path, capsys, monkeypatch):  # noqa: F811
    (tmp_path / "talk.py").write_text("".join(f"line {i}\n" for i in range(1, 11)))
    spec = {"actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "steps": [{"id": "s1", "from": "a", "to": "b", "arrow": "request", "label": "ok", "ref": "talk.py:2"},
                      {"id": "s2", "from": "a", "to": "b", "arrow": "request", "label": "far", "ref": "talk.py:99"},
                      {"id": "s3", "from": "a", "to": "b", "arrow": "request", "label": "gone", "ref": "gone.py:1"}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(spec)))
    assert stage.main(["show", "seq", "sequence:-", "--cwd", str(tmp_path)]) == 0
    assert capsys.readouterr().err == (
        "stage: sequence ref: step s2: ref talk.py:99 is past the end of talk.py, which has 10 lines; "
        "sequence ref: step s3: ref gone.py:1 names no file in the code folder\n")
    shown = fake.items["view:seq"]["source"]
    assert [s["id"] for s in shown["spec"]["steps"]] == ["s1", "s2", "s3"] and list(shown["refs"]) == ["s1"]
