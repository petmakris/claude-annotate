from skills.stage import scene

EXAMPLE = """flowchart LR
  subgraph adv[":advisory"]
    pws[ProposalWorkflowServiceImpl]
    legacy[web.workflows.legacy]
  end
  wf[":workflows"]
  engine[(Flowable engine)]
  pws -->|imports 3 types| wf
  wf --> engine
  pws --> legacy"""


def test_a_flowchart_names_its_groups_nodes_and_edges_in_declaration_order():
    m = scene.flowchart_model(EXAMPLE)
    assert m.keys == ["group:adv", "node:pws", "node:legacy", "node:wf", "node:engine",
                      "edge:pws->wf#0", "edge:wf->engine#0", "edge:pws->legacy#0"]
    assert m.order == m.keys[1:5]
    assert m.up["edge:pws->wf#0"] == ["node:pws", "node:wf"] and m.up["node:pws"] == ["group:adv"]
    assert m.down == {"group:adv": ["node:pws", "node:legacy"]}
    assert m.names["flowable engine"] == "node:engine" and m.names[":advisory"] == "group:adv"


def test_chains_ampersands_repeated_edges_and_text_links_are_all_edges():
    m = scene.flowchart_model("graph TD\n  A[Start] --> B & C\n  B --> D --> E\n  A --> B\n"
                              "  A -- text --> B\n  A -.-> B\n  X:::cls --> Y")
    assert [k for k in m.keys if k.startswith("edge:")] == [
        "edge:A->B#0", "edge:A->C#0", "edge:B->D#0", "edge:D->E#0", "edge:A->B#1", "edge:A->B#2", "edge:A->B#3",
        "edge:X->Y#0"]


def test_labels_with_brackets_shapes_and_nested_groups_are_read():
    m = scene.flowchart_model('graph TD\nA["f(x)"] --> B[(Store)]\nB --> C{Decide?}\nC -- Yes --> D>flag]\n'
                              "subgraph outer [Outer]\n  subgraph inner_one [Inner]\n    F\n  end\n  G\nend\nF --> outer")
    assert m.names["f(x)"] == "node:A" and m.names["store"] == "node:B"
    assert m.up["group:inner_one"] == ["group:outer"] and m.up["node:F"] == ["group:inner_one"]
    assert m.down["group:outer"] == ["node:G", "group:inner_one", "node:F"]
    assert m.up["edge:F->outer#0"] == ["node:F", "group:outer"]


def test_ids_with_dashes_dots_and_greek_letters_and_every_link_style_are_read():
    m = scene.flowchart_model("flowchart TD\n  a-b[Dash id] --> c_d\n  c_d --> e.f\n  A1 --o B1\n  B1 --x C1\n"
                              "  C1 <--> D1\n  D1 ~~~ E1\n  style B1 fill:#f9f\n  class A1 hot")
    assert [k for k in m.keys if k.startswith("edge:")] == [
        "edge:a-b->c_d#0", "edge:c_d->e.f#0", "edge:A1->B1#0", "edge:B1->C1#0", "edge:C1->D1#0", "edge:D1->E1#0"]
    greek = scene.flowchart_model("graph LR\n  αρχή[Αρχή] --> τέλος[Τέλος]")
    assert greek.keys == ["node:αρχή", "node:τέλος", "edge:αρχή->τέλος#0"] and greek.names["αρχη"] == "node:αρχή"


def test_only_a_graph_or_flowchart_has_a_model():
    assert scene.flowchart_model("sequenceDiagram\nAlice->>Bob: hi") is None
    assert scene.flowchart_model("graph TD; P[Page]-->Q[Queue]").keys == ["node:P", "node:Q", "edge:P->Q#0"]


def test_code_lines_are_always_shown_and_table_rows_can_be_hidden():
    lines = scene.lines_model(range(40, 43))
    assert lines.keys == ["line:40", "line:41", "line:42"] and not lines.can_hide and lines.order == []
    rows = scene.rows_model(["Azure", "Straße", "azure"])
    assert rows.keys == ["row#1", "row#2", "row#3"] and rows.can_hide and rows.order == rows.keys
    assert rows.names == {"azure": "row#1", "straße": "row#2"}


def verbs(*tags):
    return [scene.parse_verb(t) for t in tags]


def test_verbs_read_their_scene_title_and_targets():
    v = scene.parse_verb
    assert (v("+ pws").name, v("+ pws").title, v("+ pws").targets) == ("+", "", ["pws"])
    assert v("+ legacy, pws->legacy").targets == ["legacy", "pws->legacy"]
    assert (v("+ deps: port").title, v("+ deps: port").targets) == ("deps", ["port"])
    assert (v("focus Request path: page: node Queue").title, v("focus Request path: page: node Queue").targets) == (
        "Request path: page", ["node Queue"])
    assert v("FOCUS none").targets == ["none"] and v("focus 42-45").targets == ["42-45"]
    assert (v("next").count, v("next 2").count, v("next step").count) == (1, 2, 1)
    assert v("all").name == "all" and v("strike pws->wf").name == "strike" and v("- k").name == "-"
    for other in ("point: x", "note: x", "key: y", "show table | T", "/show", "nextstep"):
        assert v(other) is None, other


def test_a_target_that_names_nothing_exactly_is_repaired_and_said():
    m = scene.flowchart_model(EXAMPLE)
    assert scene.resolve(m, "pws", "T") == (["node:pws"], None)
    assert scene.resolve(m, "node wf", "T") == (["node:wf"], None)
    assert scene.resolve(m, "ProposalWorkflowServiceImp", "T") == (
        ["node:pws"], '"ProposalWorkflowServiceImp" in "T" read as node:pws')
    assert scene.resolve(m, ":advisory", "T") == (["group:adv"], None)
    assert scene.resolve(m, '"Flowable engine"', "T") == (["node:engine"], None)
    assert scene.resolve(m, ":advisor", "T") == (["group:adv"], '":advisor" in "T" read as group:adv')
    assert scene.resolve(m, "wf->pws", "T") == (
        ["edge:pws->wf#0"], '"wf->pws" in "T" read as pws->wf: that edge only goes the other way')
    assert scene.resolve(m, "nope", "T") == ([], '"nope" in "T" matches nothing; dropped')
    dotted = scene.flowchart_model("graph TD\n  c_d --> e.f")
    assert scene.resolve(dotted, "c_d->e.f", "T") == (["edge:c_d->e.f#0"], None)
    lines = scene.lines_model(range(10, 15))
    assert scene.resolve(lines, "lines 12-13", "C") == (["line:12", "line:13"], None)
    assert scene.resolve(lines, "13-11", "C") == (["line:11", "line:12", "line:13"], None)
    assert scene.resolve(lines, "40", "C") == ([], '"40" is outside the lines of "C"; dropped')
    rows = scene.rows_model(["Azure", "Straße"])
    assert scene.resolve(rows, "row 2", "P") == (["row#2"], None)
    assert scene.resolve(rows, 'row "Azur"', "P") == (["row#1"], '"row "Azur"" in "P" read as row#1')
    assert scene.resolve(rows, 'row "STRASSE"', "P") == ([], '"row "STRASSE"" in "P" matches nothing; dropped')
    assert scene.resolve(rows, "row azure", "P") == (["row#1"], None)
    assert scene.resolve(rows, "row 3", "P") == ([], '"P" has 2 rows, not row 3; dropped')


WORKED = [["+ pws"], ["+ pws->wf"], ["+ wf->engine"], ["focus pws->wf"], ["focus none"],
          ["+ legacy, pws->legacy", "focus legacy"]]


def test_the_worked_example_compiles_to_frames_a0_to_a6_and_a_rest_frame():
    model = scene.flowchart_model(EXAMPLE)
    built, notes = scene.compile_scene(model, [verbs(*g) for g in WORKED], "advisory drops :workflows")
    assert notes == []
    frames = built["frames"]
    assert (built["steps"], built["rest"], built["start"], built["repairs"]) == (6, 7, "empty", 0)
    assert frames[0] == {"show": [], "focus": []}
    assert frames[1] == {"show": ["group:adv", "node:pws"], "focus": []}
    assert frames[2]["show"] == ["group:adv", "node:pws", "node:wf", "edge:pws->wf#0"]
    assert frames[3]["show"] == ["group:adv", "node:pws", "node:wf", "node:engine", "edge:pws->wf#0",
                                 "edge:wf->engine#0"]
    assert frames[4] == {"show": frames[3]["show"], "focus": ["edge:pws->wf#0"]}
    assert frames[5] == {"show": frames[3]["show"], "focus": []}
    assert frames[6] == {"show": model.keys, "focus": ["node:legacy"]}
    assert frames[7] == {"show": model.keys, "focus": []}


def test_a_scene_that_only_focuses_starts_with_everything_shown():
    model = scene.lines_model(range(1, 6))
    built, notes = scene.compile_scene(model, [verbs("focus 2-3"), verbs("focus none")], "C")
    assert built["start"] == "full" and notes == []
    assert [f["focus"] for f in built["frames"]] == [[], ["line:2", "line:3"], [], []]
    assert all(f["show"] == model.keys for f in built["frames"])
    table = scene.rows_model(["a", "b", "c", "d"])
    built, _ = scene.compile_scene(table, [verbs("focus row 2")], "T")
    assert built["frames"][0]["show"] == table.keys and built["frames"][1]["focus"] == ["row#2"]


def test_a_group_brings_its_children_and_a_focused_group_lights_them():
    model = scene.flowchart_model(EXAMPLE)
    built, _ = scene.compile_scene(model, [verbs("+ adv"), verbs("focus adv"), verbs("all")], "T")
    assert built["frames"][1]["show"] == ["group:adv", "node:pws", "node:legacy", "edge:pws->legacy#0"]
    assert built["frames"][2]["focus"] == ["group:adv", "node:pws", "node:legacy"]
    assert built["frames"][3]["show"] == model.keys


def test_repairs_are_counted_and_what_is_never_revealed_comes_in_with_the_rest_frame():
    model = scene.flowchart_model(EXAMPLE)
    built, notes = scene.compile_scene(model, [verbs("+ pwss"), verbs("+ ghost")], "T")
    assert built["repairs"] == 2
    assert notes == ['"pwss" in "T" read as node:pws', '"ghost" in "T" matches nothing; dropped',
                     '3 of 4 elements of "T" are never revealed; they come in with the rest frame']
    assert built["frames"][-1]["show"] == model.keys


def test_next_reveals_in_declaration_order_and_says_when_nothing_is_left():
    model = scene.flowchart_model("graph TD; P[Page]-->Q[Queue]")
    built, notes = scene.compile_scene(model, [verbs("next"), verbs("next 2"), verbs("next")], "F")
    assert [f["show"] for f in built["frames"][1:4]] == [["node:P"], model.keys, model.keys]
    assert notes == ['next in "F": everything is shown already']


def test_a_board_with_more_than_three_elements_and_no_verbs_is_stepped_per_sentence():
    model = scene.flowchart_model(EXAMPLE)
    assert [[v.count for v in g] for g in scene.auto_steps(model, 3)] == [[1], [1], [2]]
    assert len(scene.auto_steps(model, 20)) == 4
    assert scene.auto_steps(scene.flowchart_model("graph TD; P-->Q"), 5) == []
    assert scene.auto_steps(scene.lines_model(range(1, 30)), 5) == []
    assert scene.auto_steps(model, 0) == []
    assert scene.compile_scene(model, [], "T") == (None, [])


SEQ_SPEC = {"actors": [{"id": "c", "label": "Contract"}, {"id": "m", "label": "Ledger"}],
            "steps": [{"id": "s1", "from": "c", "to": "c", "arrow": "self", "label": "dev build published"},
                      {"id": "s2", "from": "c", "to": "m", "arrow": "request", "label": "draft pins build 139"}]}
FLOW_SPEC = {"nodes": [{"id": "a", "role": "entry", "label": "Turn arrives"}, {"id": "b", "role": "decision", "label": "Floor free?"},
                       {"id": "c", "role": "success", "label": "Played"}],
             "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}, {"from": "b", "to": "c"}]}


def _shown(frame):
    return set(frame["show"])


def test_an_arrow_shows_once_both_its_ends_do_even_when_only_the_boxes_were_named():
    m = scene.flowchart_model("graph LR; P[Page] --> Q[Queue]; Q --> S[Session]")
    built, _ = scene.compile_scene(m, [[scene.Verb("+", targets=["P"])], [scene.Verb("+", targets=["Q"])],
                                       [scene.Verb("+", targets=["S"])]], "Turn path")
    assert "edge:P->Q#0" not in _shown(built["frames"][1])
    assert "edge:P->Q#0" in _shown(built["frames"][2]) and "edge:Q->S#0" not in _shown(built["frames"][2])
    assert {"edge:P->Q#0", "edge:Q->S#0"} <= _shown(built["frames"][3])


def test_a_sequence_spec_reveals_its_steps_in_order_and_each_brings_its_actors():
    m = scene.sequence_model(SEQ_SPEC)
    assert m.kind == "sequence" and m.can_hide
    assert m.keys == ["actor:c", "actor:m", "step:s1", "step:s2"] and m.order == ["step:s1", "step:s2"]
    assert m.up["step:s2"] == ["actor:c", "actor:m"]
    built, notes = scene.compile_scene(m, [[scene.Verb("next")], [scene.Verb("next")]], "Pins")
    assert _shown(built["frames"][1]) == {"actor:c", "step:s1"}
    assert _shown(built["frames"][2]) == set(m.keys) and notes == []


def test_a_flowchart_spec_steps_through_its_nodes_and_its_arrows_follow():
    m = scene.flowchart_spec_model(FLOW_SPEC)
    assert m.keys == ["node:a", "node:b", "node:c", "edge:a->b#0", "edge:b->c#0", "edge:b->c#1"]
    assert m.order == ["node:a", "node:b", "node:c"]
    assert m.edges[("b", "c")] == ["edge:b->c#0", "edge:b->c#1"]
    built, _ = scene.compile_scene(m, [[scene.Verb("next", count=2)], [scene.Verb("next")]], "Floor")
    assert _shown(built["frames"][1]) == {"node:a", "node:b", "edge:a->b#0"}
    assert {"edge:b->c#0", "edge:b->c#1"} <= _shown(built["frames"][2])


def test_steps_actors_and_nodes_are_found_by_id_by_word_or_by_label():
    seq = scene.sequence_model(SEQ_SPEC)
    for raw, want in (("s2", ["step:s2"]), ("step s2", ["step:s2"]), ("actor m", ["actor:m"]),
                      ("Ledger", ["actor:m"]), ("draft pins build 139", ["step:s2"])):
        assert scene.resolve(seq, raw, "Pins")[0] == want, raw
    flow = scene.flowchart_spec_model(FLOW_SPEC)
    assert scene.resolve(flow, "b->c", "Floor")[0] == ["edge:b->c#0", "edge:b->c#1"]
    assert scene.resolve(flow, "Floor free?", "Floor")[0] == ["node:b"]


def test_auto_steps_spread_evenly_and_never_end_on_an_empty_sentence():
    model = scene.flowchart_model("graph TD; A-->B; B-->C; C-->D; D-->E")
    assert [g[0].count for g in scene.auto_steps(model, 4)] == [1, 1, 1, 2]
    built, notes = scene.compile_scene(model, scene.auto_steps(model, 4), "T")
    assert notes == [] and built["frames"][4]["show"] == model.keys


def test_next_and_all_name_their_board_by_title():
    assert (scene.parse_verb("next Turn path").title, scene.parse_verb("next Turn path").count) == ("Turn path", 1)
    assert (scene.parse_verb("next Turn path: 2").title, scene.parse_verb("next Turn path: 2").count) == ("Turn path", 2)
    assert (scene.parse_verb("next 3").title, scene.parse_verb("next 3").count) == ("", 3)
    assert scene.parse_verb("all: Turn path").title == "Turn path"


def test_an_edge_between_ids_with_spaces_is_the_edge():
    model = scene.flowchart_spec_model({"nodes": [{"id": "Order service"}, {"id": "db"}],
                                        "edges": [{"from": "Order service", "to": "db"}]})
    assert scene.resolve(model, "Order service->db", "T") == (["edge:Order service->db#0"], None)


def test_mermaid_graphs_and_state_diagrams_become_map_specs():
    from skills.stage import scene as sc
    states = sc.mermaid_spec("stateDiagram-v2\n  [*] --> Idle\n  Idle --> Busy: work\n  Busy --> Idle: done\n  Busy --> [*]")
    assert [(n["id"], n["role"]) for n in states["nodes"]] == [("Idle", "entry"), ("Busy", "success")]
    assert states["edges"] == [{"from": "Idle", "to": "Busy", "label": "work"}, {"from": "Busy", "to": "Idle", "label": "done"}]
    graph = sc.mermaid_spec("graph LR; P[Page] -->|words| Q{Queue?} -- yes --> R(Run)")
    assert [(n["id"], n["label"], n["role"]) for n in graph["nodes"]] == [("P", "Page", "entry"), ("Q", "Queue?", "decision"), ("R", "Run", "code")]
    assert [e.get("label") for e in graph["edges"]] == ["words", "yes"]
    assert sc.mermaid_spec("sequenceDiagram\n  A->>B: hi") is None
