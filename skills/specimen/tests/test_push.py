import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import push as push_mod


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        class R:
            returncode = 0
            stdout = ('WC_SID=sid-1\nWC_URL=http://127.0.0.1:3080/s/sid-1\n'
                      'WC_SLUG=result-specimen\n')
            stderr = ''
        return R()


def test_missing_daemon_is_reported_never_worked_around(monkeypatch):
    monkeypatch.setattr(push_mod.shutil, 'which', lambda _: None)
    assert push_mod.binary() is None
    with pytest.raises(push_mod.DaemonMissing):
        push_mod.push('/tmp/items.json', '/repo', 'T', '/static')


def test_push_then_assets_in_that_order(monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(push_mod.shutil, 'which', lambda _: '/usr/bin/webcompanion')
    monkeypatch.setattr(push_mod.subprocess, 'run', fake)
    items = tmp_path / 'items.json'
    items.write_text(json.dumps({'items': {}}))

    got = push_mod.push(str(items), '/repo', 'Result Specimen', str(tmp_path))

    assert got['sid'] == 'sid-1'
    assert got['url'].endswith('/s/sid-1')
    assert fake.calls[0][1] == 'push'
    assert fake.calls[1][1] == 'assets'
    assert '--sid' in fake.calls[1] and 'sid-1' in fake.calls[1]


def test_push_declares_the_specimen_kind_and_eval_output(monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(push_mod.shutil, 'which', lambda _: '/usr/bin/webcompanion')
    monkeypatch.setattr(push_mod.subprocess, 'run', fake)
    items = tmp_path / 'items.json'
    items.write_text(json.dumps({'items': {}}))

    push_mod.push(str(items), '/repo', 'T', str(tmp_path))

    argv = fake.calls[0]
    assert argv[argv.index('--kind') + 1] == 'specimen'
    assert '--eval' in argv


def test_entry_defaults_to_entry_js(monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(push_mod.shutil, 'which', lambda _: '/usr/bin/webcompanion')
    monkeypatch.setattr(push_mod.subprocess, 'run', fake)
    items = tmp_path / 'items.json'
    items.write_text(json.dumps({'items': {}}))

    push_mod.push(str(items), '/repo', 'T', str(tmp_path))

    argv = fake.calls[1]
    assert argv[argv.index('--entry') + 1] == 'entry.js'


# --- CLI-level coverage of the "no daemon" branch --------------------------
#
# The daemon is up on this machine (and most machines this will run on), so
# the happy path is what actually gets exercised in practice; DaemonMissing ->
# exit 4 is the branch most likely to bit-rot silently. This drives
# bin/push-specimen itself as a subprocess with PATH emptied, so it proves
# the *script's* behaviour (exit code, no traceback on stderr) rather than
# only the library function's exception.

import os
import subprocess as _subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN = REPO_ROOT / 'bin' / 'push-specimen'


def test_bin_push_specimen_exits_4_with_no_traceback_when_daemon_absent(tmp_path):
    types_path = tmp_path / 'types.json'
    specimen_path = tmp_path / 'specimen.json'
    types_path.write_text(json.dumps({
        'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
        'types': {'app.Result': {'kind': 'data', 'source': '/w/app/Result.java',
                                  'line': 1, 'fields': []}},
    }))
    specimen_path.write_text(json.dumps({
        'root': 'app.Result',
        'instance': {'kind': 'object', 'type': 'app.Result', 'fields': {}},
    }))

    env = dict(os.environ)
    env['PATH'] = str(tmp_path)  # a directory with no `webcompanion` in it

    result = _subprocess.run(
        [sys.executable, str(BIN), '--types', str(types_path),
         '--specimen', str(specimen_path), '--cwd', str(tmp_path)],
        capture_output=True, text=True, env=env, timeout=30,
    )

    assert result.returncode == 4
    assert 'Traceback' not in result.stderr
    assert 'webcompanion' in result.stderr.lower()
