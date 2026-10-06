"""The talk server as a launchd agent: its settings come from its plist, and a launch asks launchd
for it instead of starting one with the session's own environment."""
import plistlib
import subprocess
from pathlib import Path

import pytest

from helpers import talk

import talk_service

KEYED = {"HOME": "/Users/me", "PATH": "/usr/bin", "TALK_AZURE_KEY_COMMAND": "print-key azure-speech",
         "TALK_AZURE_REGION": "switzerlandwest", "TALK_SPEECH": "", "UNRELATED": "x"}


def test_the_plist_carries_the_speech_settings_and_runs_a_server_that_stays():
    spec = talk_service.build(Path("/p/skills/talk/talk.py"), 8766, "/bin/uv", KEYED, Path("/l/server.log"))
    assert spec["ProgramArguments"] == ["/bin/uv", "run", "-q", "--script", "/p/skills/talk/talk.py",
                                        "--serve", "--stay", "--port", "8766"]
    assert spec["EnvironmentVariables"] == {"HOME": "/Users/me", "PATH": "/usr/bin",
                                            "TALK_AZURE_KEY_COMMAND": "print-key azure-speech",
                                            "TALK_AZURE_REGION": "switzerlandwest"}
    assert spec["KeepAlive"] is True and spec["RunAtLoad"] is True
    plistlib.dumps(spec)  # it is a valid plist


def test_a_shell_without_the_key_command_cannot_install_a_server_that_would_speak_with_voicestudio():
    with pytest.raises(talk_service.ServiceError, match="TALK_AZURE_KEY_COMMAND is not set"):
        talk_service.service_env({"PATH": "/usr/bin"})
    assert talk_service.service_env({"PATH": "/usr/bin", "TALK_SPEECH": "voicestudio"})["TALK_SPEECH"] == "voicestudio"


def test_the_azure_key_itself_never_goes_into_the_plist():
    with pytest.raises(talk_service.ServiceError, match="write the key into its plist"):
        talk_service.service_env({"PATH": "/usr/bin", "AZURE_SPEECH_KEY": "secret"})
    env = talk_service.service_env({**KEYED, "AZURE_SPEECH_KEY": "secret"})
    assert "AZURE_SPEECH_KEY" not in env and "secret" not in env.values()


def test_install_writes_the_plist_and_loads_it(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(talk_service, "supported", lambda: True)
    monkeypatch.setattr(talk_service.shutil, "which", lambda name: "/bin/uv")
    monkeypatch.setattr(talk_service, "launchctl", lambda *a: ran.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    talk_service.install(Path("/p/talk.py"), 8766, tmp_path / "server.log", env=KEYED)
    written = plistlib.loads(talk_service.plist_path().read_bytes())
    assert written["EnvironmentVariables"]["TALK_AZURE_KEY_COMMAND"] == "print-key azure-speech"
    assert [a[0] for a in ran] == ["bootout", "bootstrap"] and ran[1][2] == str(talk_service.plist_path())
    assert talk_service.installed()


@pytest.fixture
def service(monkeypatch):
    """The service is installed; kickstart brings up a server with a new pid, as launchd would."""
    state = {"pid": 100, "kicks": []}
    info = {"port": 8766, "token": "t"}
    monkeypatch.setattr(talk_service, "installed", lambda: True)

    def kickstart(restart=False):
        state["kicks"].append(restart)
        state["pid"] += 1

    monkeypatch.setattr(talk_service, "kickstart", kickstart)
    monkeypatch.setattr(talk, "running_server", lambda port: info if state["kicks"] else None)
    monkeypatch.setattr(talk, "server_health", lambda i: {"pid": state["pid"], "code": talk.code_version(),
                                                         "open": 0, "handover": True, "service": True})
    return state


def test_with_the_service_installed_a_launch_asks_launchd_and_never_starts_a_server(service, monkeypatch):
    monkeypatch.setattr(talk, "port_held", lambda port: False)
    assert talk.start_server(8766) == {"port": 8766, "token": "t"}  # no_real_server fails any spawn
    assert service["kicks"] == [False]


def test_a_service_on_older_code_is_restarted_through_launchd(service, monkeypatch):
    service["kicks"].append(False)  # it is running already
    monkeypatch.setattr(talk, "server_health", lambda i: {"pid": service["pid"], "open": 0, "handover": True,
                                                         "service": True,
                                                         "code": "older" if service["kicks"] == [False] else talk.code_version()})
    talk.start_server(8766)
    assert service["kicks"] == [False, True]


def test_restart_goes_through_launchd_and_waits_for_the_new_server(service, capsys):
    service["kicks"].append(False)
    assert talk.restart_server(8766) == 0
    assert service["kicks"] == [False, True]
    assert "restarted on port 8766: pid 101" in capsys.readouterr().out


def test_a_doorbell_reviving_a_lost_server_asks_launchd_when_the_service_is_installed(monkeypatch):
    import talk_client
    kicks = []
    monkeypatch.setattr(talk_service, "installed", lambda: True)
    monkeypatch.setattr(talk_service, "kickstart", lambda restart=False: kicks.append(restart))
    monkeypatch.setattr(talk_client.subprocess, "Popen", lambda *a, **k: pytest.fail("the doorbell started a server itself"))
    talk_client.spawn_server(8766)
    assert kicks == [False]
