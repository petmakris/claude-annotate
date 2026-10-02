import argparse
import re

from helpers import SKILL_DIR, talk


def cli(**values) -> argparse.Namespace:
    base = dict(mode="talk", wake=None, max_minutes=None, dormant_after=None, name="Nova", sounds_like="")
    base.update(values)
    return argparse.Namespace(**base)


def test_talk_defaults_to_waking_on_speech_after_45_quiet_seconds(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli()
    assert talk.apply_mode(args) is None
    assert (args.wake, args.dormant_after, args.max_minutes) == ("speech", 45, 60)


def test_a_meeting_wakes_on_its_name_and_runs_two_hours(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli(mode="meeting")
    assert talk.apply_mode(args) is None
    assert (args.wake, args.dormant_after, args.max_minutes) == ("name", 20, 120)


def test_explicit_flags_win_over_the_mode_defaults(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli(mode="meeting", max_minutes=30, wake="speech", dormant_after=10)
    talk.apply_mode(args)
    assert (args.wake, args.dormant_after, args.max_minutes) == ("speech", 10, 30)


def test_talk_without_local_listening_runs_as_before_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "local listening needs an Apple Silicon Mac")
    args = cli()
    assert talk.apply_mode(args) is None
    assert args.dormant_after == 0
    assert "Dormancy is off for this call: local listening needs an Apple Silicon Mac." in capsys.readouterr().out


def test_a_meeting_without_local_listening_refuses_to_start(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "parakeet-mlx is not installed")
    assert talk.apply_mode(cli(mode="meeting")) == "/meet needs local listening: parakeet-mlx is not installed"


def test_a_meeting_cannot_switch_dormancy_off(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    assert "--dormant-after" in talk.apply_mode(cli(mode="meeting", dormant_after=0))


def test_dormant_after_zero_never_checks_for_the_ear(monkeypatch):
    def boom():
        raise AssertionError("checked")
    monkeypatch.setattr(talk.ear_mod, "unavailable", boom)
    args = cli(dormant_after=0)
    assert talk.apply_mode(args) is None and args.dormant_after == 0


def test_the_doctor_reports_the_model_and_offers_the_warm_up(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    monkeypatch.setattr(talk.ear_mod, "model_cached", lambda: False)
    lines = talk.ear_doctor_lines()
    assert len(lines) == 1 and "not downloaded yet" in lines[0] and "ear.py\" --warm" in lines[0]
    monkeypatch.setattr(talk.ear_mod, "model_cached", lambda: True)
    assert talk.ear_doctor_lines()[0].startswith("[ok] local listening")
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "local listening needs an Apple Silicon Mac")
    assert talk.ear_doctor_lines() == ["[--] local listening (dormancy, /meet): local listening needs an Apple Silicon Mac"]


def test_the_script_installs_parakeet_only_on_apple_silicon():
    header = (SKILL_DIR / "talk.py").read_text().split("# ///", 2)[1]
    line = next(l for l in header.splitlines() if "parakeet-mlx" in l)
    assert re.search(r"sys_platform == 'darwin' and platform_machine == 'arm64'", line)
