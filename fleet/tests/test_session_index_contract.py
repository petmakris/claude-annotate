"""The session index contract (fleet/docs/session-index.md): every fixture fits the schema, or fails it for the
reason it names, and the schema and the document agree on the row's fields.

Fixtures live in fixtures/session_index/: `<definition>/valid/*.json` must fit `$defs/<definition>`,
`<definition>/invalid/*.json` hold `{why, expect, doc}` and `doc` must fail with an error that contains `expect`,
and `scenarios/*.json` name each of their parts' definitions in `parts`.
"""
import glob
import json
import os
import re

import pytest

import schema_check

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
SCHEMA_PATH = os.path.join(FLEET, "docs", "session-index.schema.json")
DOC_PATH = os.path.join(FLEET, "docs", "session-index.md")
FIXTURES = os.path.join(HERE, "fixtures", "session_index")
# Building blocks, checked through the documents that hold them.
PARTS = {"sid", "machine", "owner", "env", "time", "topic", "name_source", "kind", "where", "observed",
         "journal_fields"}


def load(path):
    with open(path) as f:
        return json.load(f)


SCHEMA = load(SCHEMA_PATH)


def fixture_files(kind):
    return sorted(glob.glob(os.path.join(FIXTURES, "*", kind, "*.json")))


def definition_of(path):
    return os.path.basename(os.path.dirname(os.path.dirname(path)))


def rel(path):
    return os.path.relpath(path, FIXTURES)


def test_the_schema_uses_only_keywords_the_checker_knows():
    assert schema_check.unknown_keywords(SCHEMA) == []


def test_every_reference_in_the_schema_resolves():
    refs = re.findall(r'"\$ref": "#/\$defs/([a-z_]+)"', json.dumps(SCHEMA))
    assert refs and sorted(set(refs) - set(SCHEMA["$defs"])) == []


@pytest.mark.parametrize("path", fixture_files("valid"), ids=rel)
def test_a_valid_fixture_fits_its_definition(path):
    assert schema_check.errors(SCHEMA, load(path), definition_of(path)) == []


@pytest.mark.parametrize("path", fixture_files("invalid"), ids=rel)
def test_an_invalid_fixture_fails_for_the_reason_it_names(path):
    fx = load(path)
    assert set(fx) == {"why", "expect", "doc"}
    errs = schema_check.errors(SCHEMA, fx["doc"], definition_of(path))
    assert errs, "%s fits, but should fail: %s" % (rel(path), fx["why"])
    assert any(fx["expect"] in e for e in errs), errs


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(FIXTURES, "scenarios", "*.json"))), ids=rel)
def test_every_part_of_a_scenario_fits_its_definition(path):
    sc = load(path)
    assert sc["parts"] and "expected" in sc and "about" in sc
    assert set(sc) == set(sc["parts"]) | {"parts", "expected", "about"}
    for part, defn in sc["parts"].items():
        assert schema_check.errors(SCHEMA, sc[part], defn) == [], part


def test_every_document_definition_has_a_valid_fixture_and_every_folder_a_definition():
    folders = {os.path.basename(p) for p in glob.glob(os.path.join(FIXTURES, "*")) if os.path.isdir(p)} - {"scenarios"}
    assert sorted(folders - set(SCHEMA["$defs"])) == []
    have = {definition_of(p) for p in fixture_files("valid")}
    assert sorted(set(SCHEMA["$defs"]) - PARTS - have) == []


def test_the_scenarios_the_contract_names_exist():
    for name in ("replayed-stale-entry", "take-chain", "voice-handover-chain", "dev-take-prod", "work-masked"):
        assert os.path.isfile(os.path.join(FIXTURES, "scenarios", name + ".json")), name


def test_a_replayed_stale_entry_leaves_the_row_as_it_was():
    sc = load(os.path.join(FIXTURES, "scenarios", "replayed-stale-entry.json"))
    assert sc["batch"]["entries"][0]["epoch_seen"] < sc["row_before"]["epoch"]
    assert sc["reply"]["results"][0]["outcome"] == "stale-epoch"
    assert sc["row_after"] == sc["row_before"]


def test_the_take_chain_counts_epochs_one_two_three():
    sc = load(os.path.join(FIXTURES, "scenarios", "take-chain.json"))
    assert [sc[r]["epoch"] for r in ("row_1", "row_2", "row_3")] == [1, 2, 3]
    assert [sc[r]["owner"] for r in ("row_1", "row_2", "row_3")] == ["laptop", "phone:prod", "spare"]
    assert sc["stale_take"]["expect_epoch"] == 2 and sc["stale_reply"]["code"] == "stale-epoch"


def test_a_handover_is_one_conversation_with_one_head():
    sc = load(os.path.join(FIXTURES, "scenarios", "voice-handover-chain.json"))
    old, new = sc["old_after"], sc["new_after"]
    assert old["superseded_by"] == new["sid"] and old["end_reason"] == "handover"
    assert new["continues"] == old["sid"] and new["conversation"] == old["conversation"] == old["sid"]
    assert sc["listed_head"]["chain"] == [old["sid"], new["sid"]] and sc["listed_head"]["head"] is True
    assert sc["take_old_reply"]["code"] == "superseded"


def test_no_work_byte_leaves_its_machine_in_the_work_scenario():
    sc = load(os.path.join(FIXTURES, "scenarios", "work-masked.json"))
    local = json.dumps(sc["local_cache"], ensure_ascii=False)
    for secret in sc["expected"]["never_leaves"]:
        assert secret in local, secret
        for part in ("entry", "hub_row", "listed"):
            assert secret not in json.dumps(sc[part], ensure_ascii=False), (part, secret)


def test_the_documents_row_table_lists_exactly_the_schemas_row_fields():
    with open(DOC_PATH) as f:
        doc = f.read()
    table = doc.split("### 2.1 Durable fields", 1)[1].split("###", 1)[0]
    fields = re.findall(r"^\| `([a-z_]+)` \|", table, re.M)
    assert fields == list(SCHEMA["$defs"]["row"]["properties"])


def test_the_documents_name_ranks_match_the_schema():
    with open(DOC_PATH) as f:
        doc = f.read()
    table = doc.split("### 2.3 Names", 1)[1].split("###", 1)[0]
    ranks = re.findall(r"^\| \d \| `([a-z]+)` \|", table, re.M)
    assert [""] + ranks == SCHEMA["$defs"]["name_source"]["enum"]


def test_the_hub_down_line_is_the_one_the_rulings_name():
    take_down = load(os.path.join(FIXTURES, "take_reply", "valid", "hub-down.json"))
    with open(DOC_PATH) as f:
        doc = f.read()
    assert take_down["error"] == "ownership cannot change while the hub is down"
    assert "\n    ownership cannot change while the hub is down\n" in doc


def test_the_contract_names_no_real_machine():
    """The repo is public: examples use hub, laptop and spare, never a machine of the user's."""
    machines = set()
    for path in [DOC_PATH, SCHEMA_PATH] + glob.glob(os.path.join(FIXTURES, "**", "*.json"), recursive=True):
        with open(path) as f:
            machines |= set(re.findall(r'"(?:machine|owner|hub|previous_owner|to|by)": "([a-z0-9-]+)"', f.read()))
    assert machines <= {"hub", "laptop", "spare"}, machines
