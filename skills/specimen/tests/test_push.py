import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from skills.specimen import push as push_mod
from skills.specimen.document import build_items

REPO_ROOT = Path(__file__).resolve().parents[3]

TYPES = {
    'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
    'types': {'app.Result': {'kind': 'data', 'source': '/w/app/Result.java',
                             'line': 1, 'fields': []}},
}
SPECIMEN = {
    'root': 'app.Result',
    'instance': {'kind': 'object', 'type': 'app.Result', 'fields': {}},
}
SESSION = {'sid': 's1', 'slug': 'result-specimen', 'kind': 'specimen',
           'url': 'http://127.0.0.1:3080/s/s1/'}


def _patched():
    return (patch('skills.specimen.push.wc.create_or_attach', return_value=SESSION),
            patch('skills.specimen.push.wc.put_items'),
            patch('skills.specimen.push.wc.register_assets'))


def test_push_creates_a_superseding_session_then_items_then_assets():
    create, put, assets = _patched()
    with create as mock_create, put as mock_put, assets as mock_assets:
        res = push_mod.push(TYPES, SPECIMEN, '/repo')

    mock_create.assert_called_once_with('specimen', '/repo', title='Result Specimen',
                                        supersede=True)
    mock_put.assert_called_once_with('s1', build_items(TYPES, SPECIMEN, {}),
                                     kind='specimen', replace=True)
    mock_assets.assert_called_once_with('s1', str(push_mod.STATIC_DIR), 'entry.js',
                                        kind='specimen')
    assert res == SESSION


def test_a_nested_root_titles_the_page_by_its_simple_name():
    assert push_mod.default_title({'root': 'app.Outer$Inner'}) == 'Inner Specimen'


def test_the_renderer_it_registers_is_on_disk():
    assert (push_mod.STATIC_DIR / push_mod.ENTRY).is_file()
    assert (push_mod.STATIC_DIR / 'specimen.js').is_file()


def _inputs(tmp_path):
    types_path = tmp_path / 'types.json'
    specimen_path = tmp_path / 'specimen.json'
    types_path.write_text(json.dumps(TYPES))
    specimen_path.write_text(json.dumps(SPECIMEN))
    return ['--types', str(types_path), '--specimen', str(specimen_path),
            '--cwd', str(tmp_path)]


def test_main_prints_the_session_as_json(tmp_path, capsys):
    create, put, assets = _patched()
    with create, put, assets:
        code = push_mod.main(_inputs(tmp_path))
    assert code == 0
    assert json.loads(capsys.readouterr().out)['url'] == SESSION['url']


def test_main_reports_unreadable_input_on_one_line(tmp_path, capsys):
    code = push_mod.main(['--types', str(tmp_path / 'missing.json'),
                          '--specimen', str(tmp_path / 'missing.json'),
                          '--cwd', str(tmp_path)])
    assert code == 1
    assert capsys.readouterr().err.startswith('specimen push: ')


def test_main_reports_a_refused_push_on_one_line(tmp_path, capsys):
    with patch('skills.specimen.push.wc.create_or_attach',
               side_effect=RuntimeError('POST /api/sessions -> 400 bad')):
        code = push_mod.main(_inputs(tmp_path))
    assert code == 1
    assert 'POST /api/sessions -> 400 bad' in capsys.readouterr().err


# The daemon is up on this machine (and most machines this will run on), so
# the happy path is what actually gets exercised in practice; "no daemon" is
# the branch most likely to bit-rot silently. This drives the module itself
# as a subprocess with an empty HOME, so it proves the *command's* behaviour
# (exit code, no traceback on stderr) rather than only the function's.
def test_no_daemon_is_exit_1_with_no_traceback(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    result = subprocess.run(
        [sys.executable, '-m', 'skills.specimen.push', *_inputs(tmp_path)],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
        env={**os.environ, 'HOME': str(home)},
    )
    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert result.stderr.startswith('specimen push: ')
    assert 'webcompanion' in result.stderr.lower()
