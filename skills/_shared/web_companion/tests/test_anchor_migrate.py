import json
from pathlib import Path

import pytest

from skills._shared.web_companion.anchor_migrate import locate, Kind

FIXTURE = Path(__file__).parent / "anchor_migration_fixtures.json"
CASES = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_fixture_cases(case):
    res = locate(case["lines"], case["recorded_line"], case["anchor_text"], case["k"])
    assert res.kind is Kind[case["expected_kind"]]
    assert res.line == case["expected_line"]


def test_empty_file_is_stale():
    res = locate([], 1, "anything", 25)
    assert res.kind is Kind.STALE
    assert res.line == -1
