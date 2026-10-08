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


def test_a_row_named_in_words_never_matches_a_column_header():
    table = scene.rows_model(["statement", "breach question", "examples"], ["Field", "Description"])
    assert scene.resolve(table, "row description", "T") == ([], '"row description" in "T" matches nothing; dropped')
    assert scene.resolve(table, "descriptio", "T") == ([], '"descriptio" in "T" matches nothing; dropped')
    assert scene.resolve(table, "row example", "T") == (["row#3"], '"row example" in "T" read as row#3')
    assert scene.resolve(table, "cell examples / Description", "T") == (["cell#3.2"], None)  # a header still names its column


WORKED = [["+ pws"], ["+ pws->wf"], ["+ wf->engine"], ["focus pws->wf"], ["focus none"],
          ["+ legacy, pws->legacy", "focus legacy"]]


def test_the_worked_example_compiles_to_frames_a0_to_a6_and_a_rest_frame():
    model = scene.flowchart_model(EXAMPLE)
    built, notes = scene.compile_scene(model, [verbs(*g) for g in WORKED], "advisory drops :workflows")
    assert notes == []
    frames = built["frames"]
    assert (built["steps"], built["rest"], built["start"], built["repairs"]) == (6, 7, "empty", 0)
    assert frames[0] == {"show": [], "focus": [], "cur": []}
    assert frames[1] == {"show": ["group:adv", "node:pws"], "focus": [], "cur": ["node:pws"]}
    assert frames[2]["show"] == ["group:adv", "node:pws", "node:wf", "edge:pws->wf#0"]
    assert frames[2]["cur"] == ["node:wf", "edge:pws->wf#0"]  # an arrow said with the end it brought in
    assert frames[3]["show"] == ["group:adv", "node:pws", "node:wf", "node:engine", "edge:pws->wf#0",
                                 "edge:wf->engine#0"]
    assert frames[4] == {"show": frames[3]["show"], "focus": ["edge:pws->wf#0"], "cur": ["edge:pws->wf#0"]}
    assert frames[5] == {"show": frames[3]["show"], "focus": [], "cur": []}
    assert frames[6] == {"show": model.keys, "focus": ["node:legacy"], "cur": ["node:legacy", "edge:pws->legacy#0"]}
    assert frames[7] == {"show": model.keys, "focus": [], "cur": []}


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


def test_a_board_whose_every_reveal_names_nothing_starts_whole_instead_of_blank():
    table = scene.rows_model(["Speed", "Cost", "Needs"], ["", "Azure", "VoiceStudio"])
    built, notes = scene.compile_scene(table, [verbs("+ row 7"), verbs("focus row 2")], "Engines")
    assert built["start"] == "full" and notes == ['"Engines" has 3 rows, not row 7; dropped']
    assert [len(f["show"]) for f in built["frames"]] == [12, 12, 12, 12]
    assert built["frames"][2]["focus"] == ["row#2"] and built["frames"][2]["cur"] == ["row#2"]
    # one reveal that does name a part: the board starts empty, and that part comes in with it
    built, _ = scene.compile_scene(table, [verbs("+ row 7"), verbs("+ row 2")], "Engines")
    assert built["start"] == "empty" and [f["show"][:1] for f in built["frames"]] == [[], [], ["row#2"], ["row#1"]]


def test_next_reveals_in_declaration_order_and_says_when_nothing_is_left():
    model = scene.flowchart_model("graph TD; P[Page]-->Q[Queue]")
    built, notes = scene.compile_scene(model, [verbs("next"), verbs("next 2"), verbs("next")], "F")
    assert [f["show"] for f in built["frames"][1:4]] == [["node:P"], model.keys, model.keys]
    assert notes == ['next in "F": everything is shown already']


def test_a_board_with_more_than_three_elements_and_no_verbs_is_stepped_per_sentence():
    model = scene.flowchart_model(EXAMPLE)
    plan, later = scene.auto_steps(model, ["One.", "Two.", "Three."])
    assert plan == {0: [["node:pws"]], 1: [["node:legacy"]], 2: [["node:wf", "node:engine"]]} and later == model.order
    # more sentences than parts, none naming one: the first is the board's introduction and brings nothing
    plan, _ = scene.auto_steps(model, [f"S{i}." for i in range(20)])
    assert plan == {1: [["node:pws"]], 2: [["node:legacy"]], 3: [["node:wf"]], 4: [["node:engine"]]}
    assert scene.auto_steps(scene.flowchart_model("graph TD; P-->Q"), ["a."] * 5) == ({}, [])
    assert scene.auto_steps(scene.lines_model(range(1, 30)), ["a."] * 5) == ({}, [])
    assert scene.auto_steps(model, []) == ({}, [])
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
    plan, _ = scene.auto_steps(model, ["One.", "Two.", "Three.", "Four."])
    assert [len(steps[0]) for _, steps in sorted(plan.items())] == [1, 1, 1, 2]
    groups = [[scene.Verb("+", keys=keys) for keys in steps] for _, steps in sorted(plan.items())]
    built, notes = scene.compile_scene(model, groups, "T")
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


# -- what each frame says is being said (cur) -------------------------------------------------------
# The boards below are real: the stage demo's (skills/talk/demo.md) and boards from saved calls, with
# the verbs their tags compiled to.

TIMELINE = scene.rows_model(["before", "13 Jan", "21 Jan", "26 Jan", "2 Feb"], ["When", "Contract repo", "Service"])
ENGINES = scene.rows_model(["Speed", "Cost", "Runs on", "Needs", "Picked"], ["", "Azure", "VoiceStudio"])
LIVE_SPEC = {"nodes": [{"id": "listening", "role": "entry", "label": "Listening"}, {"id": "hearing", "label": "Hearing you"},
                       {"id": "sending", "label": "Sending"}, {"id": "working", "label": "Working"},
                       {"id": "speaking", "role": "success", "label": "Speaking"}],
             "edges": [{"from": "listening", "to": "hearing", "label": "you speak"}, {"from": "hearing", "to": "sending", "label": "you pause"},
                       {"from": "sending", "to": "working", "label": "a turn went"}, {"from": "working", "to": "speaking", "label": "it is ready"},
                       {"from": "sending", "to": "listening", "label": "nothing said"}, {"from": "speaking", "to": "hearing", "label": "you cut in"},
                       {"from": "speaking", "to": "listening", "label": "it ends"}]}
CALLS_SPEC = {"actors": [{"id": "app", "label": "Application (advisory)"}, {"id": "port", "label": "Interfaces in advisory legacy"},
                         {"id": "fl", "label": "Flowable module (workflows)"}],
              "steps": [{"id": "s1", "from": "app", "to": "port", "arrow": "request", "label": "asks for tasks"},
                        {"id": "s2", "from": "port", "to": "fl", "arrow": "request", "label": "Spring injects the Flowable implementation"},
                        {"id": "s3", "from": "fl", "to": "port", "arrow": "event", "label": "BPMN step needs orders sent"},
                        {"id": "s4", "from": "port", "to": "app", "arrow": "event", "label": "Spring injects the app implementation"}]}


def _cur(built):
    return [f["cur"] for f in built["frames"]]


def test_frame_0_and_the_rest_frame_of_a_full_board_name_nothing_as_being_said():
    # "Timeline, simply" (saved call IzwEEFZT6): a table that starts full and is pointed at row by row
    built, _ = scene.compile_scene(TIMELINE, [verbs(f"focus row {n}") for n in range(1, 6)] + [verbs("focus none")],
                                   "Timeline, simply")
    assert built["start"] == "full"
    assert _cur(built) == [[], ["row#1"], ["row#2"], ["row#3"], ["row#4"], ["row#5"], [], []]
    # a frame that brings nothing and points at nothing names nothing either
    built, _ = scene.compile_scene(TIMELINE, [verbs("next 5"), verbs("next")], "T")
    assert _cur(built)[2] == []


def test_a_reveal_with_no_point_of_its_own_clears_the_focus_and_is_what_is_said():
    # the demo's "Two speech engines": a cell pointed at, then the rows that follow with [[next]]
    tags = [["next", 'focus cell "Speed" / "Azure"'], ['focus cell "Speed" / "VoiceStudio"'], ["next"], ["next"], ["next"],
            ["next", 'focus cell "Picked" / "Azure"']]
    built, notes = scene.compile_scene(ENGINES, [verbs(*g) for g in tags], "Two speech engines")
    assert notes == []
    assert [f["focus"] for f in built["frames"]] == [[], ["cell#1.2"], ["cell#1.3"], [], [], [], ["cell#5.2"], []]
    assert _cur(built) == [[], ["row#1"], ["row#1"], ["row#2"], ["row#3"], ["row#4"], ["row#5"], []]


def test_a_point_wins_over_a_reveal_in_its_own_frame():
    # "Calls in both directions" (saved call WM4mN6) as the old automatic steps compiled it: each sentence
    # brought the next step in and pointed at the one before
    m = scene.sequence_model(CALLS_SPEC)
    built, _ = scene.compile_scene(m, [[scene.Verb("next")]] + [[scene.Verb("next"), scene.Verb("focus", keys=[f"step:s{i}"])]
                                                               for i in range(1, 4)], "Calls in both directions")
    assert _cur(built) == [[], ["step:s1"], ["step:s1"], ["step:s2"], ["step:s3"], []]
    assert built["frames"][2]["focus"] == ["step:s1"]
    built, _ = scene.compile_scene(m, [verbs("focus actor port")], "Calls")
    assert _cur(built)[1] == ["actor:port"]  # an actor pointed at is what is said; the lanes light its chip


def test_the_arrow_said_is_the_one_that_arrived_into_the_part_being_said():
    # the demo's "Live mode's states": a node can bring an arrow in and an arrow back at once
    m = scene.flowchart_spec_model(LIVE_SPEC)
    tags = [["+ listening"], ["+ hearing"], ["+ sending"], ["+ working"], ["+ speaking"],
            ["+ sending->listening, speaking->hearing, speaking->listening"]]
    built, notes = scene.compile_scene(m, [verbs(*g) for g in tags], "Live mode's states")
    assert notes == []
    assert _cur(built) == [
        [], ["node:listening"], ["node:hearing", "edge:listening->hearing#0"],
        ["node:sending", "edge:hearing->sending#0"],  # not sending->listening, which arrived with it
        ["node:working", "edge:sending->working#0"],
        ["node:speaking", "edge:working->speaking#0"],  # not the two arrows back that arrived with it
        ["edge:sending->listening#0", "edge:speaking->hearing#0", "edge:speaking->listening#0"], []]


ONE_TURN_SPEC = {"actors": [{"id": "p", "label": "Call page"}, {"id": "t", "label": "Talk server"}, {"id": "a", "label": "Azure speech"},
                            {"id": "c", "label": "Claude session"}],
                 "steps": [{"id": "s1", "from": "p", "to": "t", "label": "sends what you said as a WAV"},
                           {"id": "s2", "from": "t", "to": "a", "label": "turns the recording into words"},
                           {"id": "s3", "from": "a", "to": "t", "label": "returns the words it heard"},
                           {"id": "s4", "from": "c", "to": "t", "label": "the doorbell collects the turn"},
                           {"id": "s5", "from": "c", "to": "c", "label": "reads the code and writes the answer"},
                           {"id": "s6", "from": "c", "to": "t", "label": "sends the answer and its boards"},
                           {"id": "s7", "from": "t", "to": "a", "label": "reads the whole answer aloud"},
                           {"id": "s8", "from": "t", "to": "p", "label": "the answer is ready on the next poll"}]}
# the sentences said over it in call NtQA_iUv88X6oZvdr_zCxw (entry 21), the demo as it was then
ONE_TURN_SAID = ["A sequence comes in a step at a time, here the path of one turn.",
                 "When you stop talking, the call page sends what you said to the talk server.",
                 "The server hands the recording to Azure.", "Azure sends back the words it heard.",
                 "Your Claude session collects the turn on its doorbell.", "It reads the code and writes the answer.",
                 "Then it sends the answer and its boards back.", "The server has Azure read the whole answer aloud.",
                 "And the page picks it up on its next poll.", "The slow part is always this one: Claude reading and writing.",
                 "Next is a map."]


def test_each_part_arrives_with_the_sentence_that_names_it_and_an_introduction_brings_nothing():
    m = scene.sequence_model(ONE_TURN_SPEC)
    plan, later = scene.auto_steps(m, ONE_TURN_SAID, {9: ["step:s5"]})
    # s2 and s8 are named by no sentence: they fill the sentences between the named steps around them
    assert plan == {1: [["step:s1"]], 2: [["step:s2"]], 3: [["step:s3"]], 4: [["step:s4"]], 5: [["step:s5"]],
                    6: [["step:s6"]], 7: [["step:s7"]], 8: [["step:s8"]]}
    assert later == ["step:s2", "step:s8"]
    assert scene.names_part(scene._words("Then it sends the answer and its boards back."),
                            scene.part_names(m)["step:s6"])


def test_a_point_is_the_reveal_for_its_sentence_and_parts_named_nowhere_ride_with_a_named_one():
    m = scene.sequence_model(CALLS_SPEC)
    said = ["The two engines still talk in both directions, and that is why the interfaces live in advisory.",
            "When the application wants a proposal's Flowable tasks, it calls the WorkflowsRepository interface.",
            "At runtime Spring hands it the Flowable implementation, AdvisoryWorkflowsRepository, which now sits inside the workflows module.",
            "The other way round, when a BPMN step must send orders, Flowable calls the SendOrdersDelegate interface.",
            "The application implements that one, in OrdersSyncService."]
    plan, later = scene.auto_steps(m, said, {1: ["step:s1"], 2: ["step:s2"], 3: ["step:s3"], 4: ["step:s4"]})
    assert plan == {1: [["step:s1"]], 2: [["step:s2"]], 3: [["step:s3"]], 4: [["step:s4"]]} and later == []
    # with fewer sentences: s1 fills the sentence before the named ones, and s4, named nowhere and with no
    # sentence left after them, comes in with them (before them, so they are what is said)
    plan, later = scene.auto_steps(m, said[:3], {2: ["step:s3"]})
    assert plan == {1: [["step:s1"]], 2: [["step:s4"], ["step:s2", "step:s3"]]} and later == ["step:s1", "step:s4"]


def test_rows_take_a_range_as_lines_do():
    assert scene.resolve(TIMELINE, "rows 2-4", "T") == (["row#2", "row#3", "row#4"], None)
    assert scene.resolve(TIMELINE, "rows 4-6", "T") == ([], '"T" has 5 rows, not rows 4-6; dropped')
    built, _ = scene.compile_scene(TIMELINE, [verbs("focus rows 1-2")], "T")
    assert built["frames"][1]["focus"][:2] == ["row#1", "row#2"] and _cur(built)[1] == ["row#1", "row#2"]


# the first hunk of "Cells and the current one", the stage demo's change board: one line removed for four
CELLS_HUNK = [{"lines": [{"op": " ", "old": 16, "new": 16}, {"op": " ", "old": 17, "new": 17}, {"op": "-", "old": 18, "new": None},
                         {"op": "+", "old": None, "new": 18}, {"op": "+", "old": None, "new": 19}, {"op": "+", "old": None, "new": 20},
                         {"op": "+", "old": None, "new": 21}, {"op": " ", "old": 19, "new": 22}]}]


def test_a_change_board_keys_its_removed_lines_and_a_range_takes_the_ones_inside_it():
    change = scene.change_model(CELLS_HUNK)
    assert change.keys == ["line:16", "line:17", "old:18", "line:18", "line:19", "line:20", "line:21", "line:22"]
    assert scene.resolve(change, "17-18", "C") == (["line:17", "old:18", "line:18"], None)
    assert scene.resolve(change, "lines 18-21", "C") == (["line:18", "line:19", "line:20", "line:21"], None)
    assert scene.resolve(change, "old line 18", "C") == (["old:18"], None)
    assert scene.resolve(change, "old 19", "C") == ([], '"old 19" is not a removed line of "C"; dropped')
    built, notes = scene.compile_scene(change, [verbs("focus old 18")], "C")
    assert (built["frames"][1]["focus"], built["frames"][1]["cur"], notes) == (["old:18"], ["old:18"], [])
