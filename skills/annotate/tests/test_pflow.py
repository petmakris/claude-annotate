"""pflow compiler tests — the restricted-Python subset and its refusals."""
import pytest

from skills.annotate.pflow import PflowError, compile_source


def _spec(body: str, head: str = "def f(request):\n"):
    return compile_source('"""t."""\n\n\n' + head + body)


def _ids(spec):
    return [n["id"] for n in spec["nodes"]]


def _roles(spec):
    return {n["id"]: n["role"] for n in spec["nodes"]}


def _edges(spec):
    return {(e["from"], e["to"], e.get("label")) for e in spec["edges"]}


# ---------------------------------------------------------------- happy path

def test_title_comes_from_the_module_docstring():
    assert compile_source('"""How it works."""\n\n\ndef f(r):\n    go()\n')["title"] == "How it works."


def test_statement_kinds_map_to_roles():
    spec = _spec("    x = call_it()\n    plain()\n    if q():  # ? ok?\n        return Win()\n    raise Lose()\n")
    roles = _roles(spec)
    assert roles["f"] == "entry"
    assert roles["call-it"] == "code"
    assert roles["plain"] == "call"
    assert roles["ok"] == "decision"
    assert roles["win"] == "success"
    assert roles["lose"] == "error"


def test_a_terminating_branch_leaves_the_fallthrough_to_the_next_statement():
    spec = _spec("    if a():  # ? a?\n        return Yes()\n    after()\n")
    assert ("a", "yes", "yes") in _edges(spec)
    assert ("a", "after", "no") in _edges(spec)


def test_a_non_terminating_branch_converges_on_the_next_statement():
    spec = _spec("    if a():  # ? a?\n        side()\n    after()\n")
    e = _edges(spec)
    assert ("a", "side", "yes") in e
    assert ("a", "after", "no") in e
    assert ("side", "after", None) in e          # the branch rejoins


def test_elif_chains_into_a_second_decision():
    spec = _spec("    if a():  # ? a?\n        return A()\n"
                 "    elif b():  # ? b?\n        return B()\n"
                 "    return C()\n")
    e = _edges(spec)
    assert ("a", "b", "no") in e
    assert ("b", "b-2", "yes") in e or ("b", "b", "yes") in e
    assert any(src == "b" and lbl == "no" for src, _, lbl in e)


def test_else_branch_is_labelled_no():
    spec = _spec("    if a():  # ? a?\n        return A()\n    else:\n        return B()\n")
    assert ("a", "b", "no") in _edges(spec)


def test_nested_ifs_nest():
    spec = _spec("    if a():  # ? a?\n        if b():  # ? b?\n            return AB()\n"
                 "        return A()\n    return Z()\n")
    assert ("a", "b", "yes") in _edges(spec)
    assert ("b", "ab", "yes") in _edges(spec)


def test_tags_become_node_fields():
    spec = _spec("    hit()  # cache: e2e corpus\n"
                 "    guard()  # gate: needs --yes\n"
                 "    plain()  # note: just so\n"
                 "    seen()  # ref: Thing:42\n")
    by_id = {n["id"]: n for n in spec["nodes"]}
    assert by_id["hit"]["sub"] == "cache: e2e corpus"
    assert by_id["guard"]["sub"] == "gate: needs --yes"
    assert by_id["plain"]["sub"] == "just so"
    assert by_id["seen"]["ref"] == "Thing:42"


def test_entry_tag_labels_the_def():
    spec = _spec("    go()\n", head="def f(request):  # ! request R\n")
    assert spec["nodes"][0]["label"] == "request R"


def test_every_node_carries_the_line_that_produced_it():
    spec = _spec("    a()\n    b()\n")
    lines = {n["id"]: n["line"] for n in spec["nodes"]}
    assert lines["a"] == 5 and lines["b"] == 6


# ------------------------------------------------------------ explicit ids

def test_a_derived_id_keeps_whole_words_and_stays_short():
    spec = _spec("    if a():  # ? some very long question here?\n        return Y()\n")
    assert _ids(spec)[1] == "some-very-long"           # not "some-very-long-ques"


def test_colliding_derived_ids_get_a_suffix():
    spec = _spec("    go()\n    go()\n")
    assert _ids(spec)[1:] == ["go", "go-2"]


def test_id_tag_pins_the_node_id_across_a_reword():
    a = _spec('    if a():  # ? shared env, unconfirmed\n        return Y()  # id: yes\n')
    b = _spec('    if a():  # ? environment is shared and unconfirmed\n        return Y()  # id: yes\n')
    assert "yes" in _ids(a) and "yes" in _ids(b)


def test_duplicate_explicit_ids_are_refused():
    with pytest.raises(PflowError, match="duplicate"):
        _spec("    a()  # id: same\n    b()  # id: same\n")


# ---------------------------------------------------------------- refusals

@pytest.mark.parametrize("body, needle", [
    ("    for x in xs:\n        go()\n",        "for"),
    ("    while go():\n        step()\n",       "while"),
    ("    with open(p) as fh:\n        go()\n", "with"),
    ("    try:\n        go()\n    except E:\n        pass\n", "try"),
    ("    def inner():\n        pass\n",        "nested"),
    ("    class C:\n        pass\n",            "class"),
])
def test_unsupported_statements_are_refused_not_dropped(body, needle):
    with pytest.raises(PflowError, match=needle):
        _spec(body)


def test_a_loop_refusal_explains_the_dag_constraint():
    with pytest.raises(PflowError, match="DAG"):
        _spec("    for x in xs:\n        go()\n")


def test_an_assignment_that_is_not_a_call_is_refused():
    with pytest.raises(PflowError, match="call"):
        _spec("    x = 3\n")


def test_a_bare_expression_that_is_not_a_call_is_refused():
    with pytest.raises(PflowError, match="call"):
        _spec("    x\n")


def test_unreachable_statements_are_refused():
    with pytest.raises(PflowError, match="unreachable"):
        _spec("    return Done()\n    after()\n")


def test_refusals_carry_the_line_number():
    with pytest.raises(PflowError) as exc:
        _spec("    a()\n    for x in xs:\n        go()\n")
    assert exc.value.line == 6
    assert ":6:" in str(exc.value)


def test_a_source_with_no_function_is_refused():
    with pytest.raises(PflowError, match="def"):
        compile_source('"""t."""\n\nx = 1\n')


def test_a_syntax_error_is_reported_as_a_pflow_error_with_its_line():
    with pytest.raises(PflowError) as exc:
        compile_source('"""t."""\n\n\ndef f(r):\n    if (:\n')
    assert exc.value.line == 5


# ----------------------------------------------------------------- budget

def test_node_budget_is_reported_but_does_not_fail():
    body = "".join("    step_%d()\n" % i for i in range(20))
    spec = _spec(body)
    assert len(spec["nodes"]) == 21
    assert spec["warnings"]
    assert "15" in spec["warnings"][0]


def test_a_small_flow_has_no_warnings():
    assert _spec("    a()\n    b()\n")["warnings"] == []
