"""Round 2 of the bulldozer run, the stage engine: a part is named by a word of its label that no other part holds,
a small table follows the voice by its rows, a column or row is read by its text, and a sequence step's ref popup
is refused what a code board refuses."""
import subprocess

import pytest

from skills.stage import model, scene


def _flow(*labels, edges=None):
    nodes = [{"id": f"n{i}", "role": "entry" if i == 0 else "success", "label": label} for i, label in enumerate(labels)]
    links = edges or [(f"n{i}", f"n{i + 1}") for i in range(len(labels) - 1)]
    return scene.flowchart_spec_model({"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in links]})


# -- a part is named by its own word, never by order -------------------------------------------------------------

CACHE = ("Request", "Cache hit", "Cache miss", "Database")
CACHE_EDGES = [("n0", "n1"), ("n0", "n2"), ("n2", "n3")]
CACHE_SAID = ["A request arrives.", "If the lookup hits, the answer comes straight back.", "If it misses, we ask the database."]


def test_a_paraphrase_names_the_hit_and_the_miss_each_by_its_own_word():
    model_ = _flow(*CACHE, edges=CACHE_EDGES)
    plan, by_order = scene.auto_steps(model_, CACHE_SAID)
    # "hits" is the hit and "misses" the miss: nothing is handed out by order, so the two never swap
    assert plan == {0: [["node:n0"]], 1: [["node:n1"]], 2: [["node:n2", "node:n3"]]} and by_order == []
    assert scene.unnamed_parts(model_, CACHE_SAID) == []


def test_a_part_no_sentence_names_is_not_lit_by_order_and_is_listed_with_the_sentence_the_order_would_have_used():
    model_ = _flow("Processor", "L1 cache", "L2 cache", "Memory")
    said = ["Start at the processor.", "The cache is tried.", "Then the memory."]
    plan, by_order = scene.auto_steps(model_, said)
    # "cache" is the word of both caches, so it names neither; they come in with the rest frame, never by order
    assert plan == {0: [["node:n0"]], 2: [["node:n3"]]} and by_order == ["node:n1", "node:n2"]
    assert scene.unnamed_parts(model_, said) == [
        {"key": "node:n1", "label": "l1 cache", "sentence": "The cache is tried."},
        {"key": "node:n2", "label": "l2 cache", "sentence": "The cache is tried."}]
    built, _ = scene.compile_scene(model_, [[scene.Verb("+", keys=k)] for steps in plan.values() for k in steps], "C")
    assert [f["cur"] for f in built["frames"][1:-1]] == [["node:n0"], ["node:n3"]]
    assert built["frames"][-1]["show"] == model_.keys


def test_l1_cache_and_l2_cache_stay_distinct():
    model_ = _flow("Processor", "L1 cache", "L2 cache", "Memory")
    said = ["Start at the processor.", "The L1 cache is tried first.", "Then the L2 cache.", "Last the memory."]
    plan, by_order = scene.auto_steps(model_, said)
    assert plan == {0: [["node:n0"]], 1: [["node:n1"]], 2: [["node:n2"]], 3: [["node:n3"]]} and by_order == []
    assert scene.said_parts(_flow("L1 cache", "L2 cache"), ["The L2 cache answers.", "The L1 cache first."]) == {
        0: ["node:n1"], 1: ["node:n0"]}


def test_a_word_two_parts_hold_names_neither_of_them():
    two = _flow("Alpha cache", "Beta cache")
    assert scene.said_parts(two, ["The cache is warm.", "Alpha is first."]) == {1: ["node:n0"]}


def test_a_greek_label_is_named_by_an_inflected_form_of_its_word():
    model_ = _flow("Σύνδεση", "Έλεγχος κωδικού", "Συνεδρία", "Αρχική σελίδα")
    said = ["Πρώτα η σύνδεση του χρήστη.", "Μετά γίνεται ο έλεγχος των κωδικών.", "Ανοίγει μια συνεδρία.",
            "Τέλος φαίνεται η αρχική σελίδα."]
    plan, by_order = scene.auto_steps(model_, said)
    assert plan == {0: [["node:n0"]], 1: [["node:n1"]], 2: [["node:n2"]], 3: [["node:n3"]]} and by_order == []
    assert scene.said_parts(_flow("Σύνδεση", "Αρχική σελίδα"), ["Η σύνδεσης γίνεται."]) == {0: ["node:n0"]}


# -- a small table follows the voice by its rows -------------------------------------------------------------------

PLANS = "| Plan | Cost (USD) | Notes |\n|---|---|---|\n| Free | 0 | basic |\n| Pro | 20 | priority support |"


def test_a_table_of_two_rows_lights_the_row_each_sentence_names():
    table = scene.body_model(PLANS)
    assert scene.auto_steps(table, ["a.", "b."]) == ({}, [])  # three rows or fewer are not stepped
    said = ["Free costs nothing.", "Pro adds priority support.", "The notes column says more.", "The plan is yours."]
    assert scene.said_parts(table, said) == {0: ["row#1"], 1: ["row#2"]}  # a column header names no row


def test_a_table_of_three_rows_lights_one_row_per_sentence_and_a_text_two_rows_share_lights_none():
    table = scene.body_model(PLANS + "\n| Team | 20 | shared seats |")
    assert scene.said_parts(table, ["Free costs nothing.", "Pro adds priority support.", "Team shares seats."]) == {
        0: ["row#1"], 1: ["row#2"], 2: ["row#3"]}
    twin = scene.body_model("| Plan | Cost |\n|---|---|\n| Free | 0 |\n| Pro | 20 |\n| Pro | 30 |")
    assert scene.said_parts(twin, ["Pro is cheap.", "Free comes first."]) == {1: ["row#1"]}


def test_a_table_of_four_rows_is_still_stepped_by_name():
    table = scene.body_model(PLANS + "\n| Team | 20 | shared seats |\n| Large | 50 | dedicated support |")
    plan, _ = scene.auto_steps(table, ["Free costs nothing.", "Pro adds priority support.", "Team shares seats.", "Large is dedicated."])
    assert plan == {0: [["row#1"]], 1: [["row#2"]], 2: [["row#3"]], 3: [["row#4"]]}


# -- a column or a row is read by its text, then without its parenthetical, then by a word or a prefix --------------

UNITS = scene.body_model("| Plan | Cost (USD) | Unit price |\n|---|---|---|\n| Free | 0 | 0 |\n| Azure Speech | 16 | 16 |\n| Azure Batch | 8 | 8 |")


def test_a_column_is_read_by_its_full_text_first():
    assert scene.resolve(UNITS, "column Cost (USD)", "T") == (["col#2"], None)


def test_a_column_is_read_without_its_trailing_parenthetical():
    assert scene.resolve(UNITS, "column Cost", "T") == (["col#2"], None)
    assert scene.resolve(UNITS, "cell Free / Cost", "T") == (["cell#1.2"], None)


def test_a_column_is_read_by_a_unique_word_or_prefix_with_a_note_and_never_on_ambiguity():
    assert scene.resolve(UNITS, "column price", "T") == (["col#3"], '"price" in "T" read as column "Unit price"')
    assert scene.resolve(UNITS, "column uni", "T") == (["col#3"], '"uni" in "T" read as column "Unit price"')
    assert scene.resolve(UNITS, "cell Free / pri", "T") == (["cell#1.3"], '"pri" in "T" read as column "Unit price"')
    both = scene.body_model("| Plan | Unit cost | Unit price |\n|---|---|---|\n| Free | 0 | 0 |")
    assert scene.resolve(both, "column unit", "T")[0] == []


def test_a_row_is_read_by_a_unique_word_of_its_name_and_never_by_a_word_two_rows_have():
    assert scene.resolve(UNITS, "row Speech", "T") == (["row#2"], '"row Speech" in "T" read as row#2')
    assert scene.resolve(UNITS, "row Azure", "T")[0] == []


# -- a sequence step's ref popup reads what a code board may read ----------------------------------------------------

def test_a_step_ref_to_a_secret_or_an_ignored_file_is_refused_like_a_code_board(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / ".env").write_text("TOKEN=secret\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.js").write_text("a = 1\n")
    (tmp_path / "ok.py").write_text("x = 1\n")
    step = lambda sid, ref: {"id": sid, "from": "a", "to": "b", "arrow": "request", "label": sid, "ref": ref}
    spec = {"actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "steps": [step("s1", ".env:1"), step("s2", "build/out.js:1"), step("s3", ".git/config:1"), step("s4", "ok.py:1")]}
    refs, problems = model.step_refs(spec, tmp_path)
    assert list(refs) == ["s4"]
    assert problems == ["step s1: ref .env:1 is refused: .env looks like a secret or a credential (a .env file, a key, or a folder such as .ssh), which the stage never shows",
                        "step s2: ref build/out.js:1 is refused: build/out.js is ignored by git, so the stage does not show it",
                        "step s3: ref .git/config:1 is refused: .git/config is inside a .git folder"]
