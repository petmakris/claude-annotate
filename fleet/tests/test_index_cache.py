"""The cache: one file per session, written atomically, the truth from the hub kept, work rows masked when dumped."""
import os

from index_testkit import fixture, index_env, sid  # noqa: F401

import fleet_index_cache as cache  # noqa: E402


def test_write_read_and_the_owner_the_status_line_reads(index_env):
    fh = str(index_env / "fleet")
    row = fixture("cache_row", "valid", "chat.json")
    cache.write(fh, row, source="hub")
    got = cache.read(fh, row["sid"])
    assert (got["owner"], got["source"], got["v"]) == (row["owner"], "hub", 1)
    path = os.path.join(fh, "index", "cache", row["sid"] + ".json")
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert cache.read(fh, sid(99)) is None


def test_the_truth_of_a_journal_reply_moves_owner_and_epoch_and_keeps_the_words(index_env):
    fh = str(index_env / "fleet")
    cache.write(fh, {"sid": sid(1), "owner": "mac", "epoch": 1, "machine": "mac", "name": "notes",
                     "name_source": "custom", "last_prompt": "go"}, source="local")
    cache.write_truth(fh, {sid(1): {"owner": "lat", "epoch": 2, "conversation": sid(1), "head": sid(1), "work": False}})
    got = cache.read(fh, sid(1))
    assert (got["owner"], got["epoch"], got["name"], got["last_prompt"], got["source"]) == ("lat", 2, "notes", "go", "hub")
    cache.write_truth(fh, {sid(2): {"owner": "mac", "epoch": 3, "conversation": sid(2), "head": sid(5), "work": False}})
    assert (cache.read(fh, sid(2))["owner"], cache.read(fh, sid(2))["superseded_by"]) == ("mac", sid(5))


def test_a_dump_masks_work_rows(index_env):
    fh = str(index_env / "fleet")
    sc = fixture("scenarios", "work-masked.json")
    cache.write(fh, sc["local_cache"], source="local")
    [row] = cache.dump(fh)["rows"]
    for k in ("cwd", "first_prompt", "last_prompt", "last_answer"):
        assert row[k] is None
    assert (row["name"], row["work"]) == ("", True)
    assert cache.dump(fh)["acked_seq"] == 0
