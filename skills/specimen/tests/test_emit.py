import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills.specimen.emit import ProvenanceError, provenance_errors, to_payload, write
from skills.specimen.fields import Field, parse_type_ref
from skills.specimen.typegraph import Node

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACT = [sys.executable, '-m', 'skills.specimen.extract_types']


def data_node():
    return Node(
        fqn='app.R', kind='data', source='/w/app/R.java', line=3,
        fields=[Field('proposed', parse_type_ref('RiskContribution'), 'nullable', 5)],
    )


def test_payload_records_the_entry_and_the_worktree():
    payload = to_payload('app.R', {'app.R': data_node()}, '/w', 'abc1234')
    assert payload['root'] == 'app.R'
    assert payload['worktree'] == '/w'
    assert payload['commit'] == 'abc1234'


def test_every_field_carries_a_source_and_a_line():
    payload = to_payload('app.R', {'app.R': data_node()}, '/w', 'abc1234')
    field = payload['types']['app.R']['fields'][0]
    assert field['line'] == 5
    assert field['nullability'] == 'nullable'
    assert payload['types']['app.R']['source'] == '/w/app/R.java'


def test_a_field_without_a_line_is_a_provenance_error():
    node = data_node()
    node.fields = [Field('x', parse_type_ref('int'), 'unmarked', 0)]
    payload = to_payload('app.R', {'app.R': node}, '/w', 'abc1234')
    errors = provenance_errors(payload)
    assert any('app.R.x' in e for e in errors)


def test_a_leaf_needs_no_line_but_states_its_reason():
    node = Node(fqn='com.ext.Category', kind='leaf', reason='no source in worktree',
                accessors_observed=('getId',))
    payload = to_payload('com.ext.Category', {'com.ext.Category': node}, '/w', 'abc1234')
    assert provenance_errors(payload) == []
    assert payload['types']['com.ext.Category']['accessors_observed'] == ['getId']


def test_write_refuses_to_produce_a_file_that_would_fail_the_check(tmp_path):
    node = data_node()
    node.fields = [Field('x', parse_type_ref('int'), 'unmarked', 0)]
    target = tmp_path / 'types.json'
    with pytest.raises(ProvenanceError):
        write(str(target), to_payload('app.R', {'app.R': node}, '/w', 'abc'))
    assert not target.exists(), 'a failing payload must leave no file behind'


def test_cli_reports_an_ambiguous_simple_name_instead_of_picking_one(tmp_path):
    for pkg in ('a.one', 'b.two'):
        path = tmp_path / (pkg.replace('.', '/') + '/Category.java')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'package {pkg};\npublic record Category(int x) {{}}\n')
    done = subprocess.run(
        [*EXTRACT, 'Category', '--worktree', str(tmp_path),
         '--out', str(tmp_path / 'types.json')],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert done.returncode == 2
    assert 'a.one.Category' in done.stdout + done.stderr
    assert 'b.two.Category' in done.stdout + done.stderr


def test_cli_refuses_a_dotted_name_absent_from_the_index(tmp_path):
    for pkg in ('a.one', 'b.two'):
        path = tmp_path / (pkg.replace('.', '/') + '/Category.java')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'package {pkg};\npublic record Category(int x) {{}}\n')
    done = subprocess.run(
        [*EXTRACT, 'com.totally.wrong.Category', '--worktree', str(tmp_path),
         '--out', str(tmp_path / 'types.json')],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert done.returncode == 2
    assert not (tmp_path / 'types.json').exists(), 'no file must be written for a wrong FQN'
