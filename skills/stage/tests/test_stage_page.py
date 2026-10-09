"""The stage page follows the voice: which board is in front, which frame of which answer's scene each board is
on, and what each frame lights. Run on the page's own JavaScript under node (stage_page.py), with no browser."""
from __future__ import annotations

from skills.stage import scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_scene import CALLS_SPEC, ENGINES as ENGINES_MODEL, LIVE_SPEC, TIMELINE

pytestmark = needs_node

TABLE = {"type": "inline", "format": "table", "body": "| area | what |\n|---|---|\n| kappa | lives here |"}
CODE5 = {"type": "inline", "format": "code", "path": "five.py", "start": 1, "highlight": None, "lang": "python",
         "lines": [f"step_{i} = {i}" for i in range(1, 6)]}
AREAS = """| Area | What lives there |
|---|---|
| `apps/` | Python and Swift apps |
| `bin/` | Dispatchers |"""


def _scene(model, tags, title):
    built, _ = scene.compile_scene(model, [[scene.parse_verb(t) for t in group] for group in tags], title)
    return built


def _saved_before_cur(built):
    """The scene as it was saved before frames named what is being said."""
    return {**built, "frames": [{"show": f["show"], "focus": f["focus"]} for f in built["frames"]]}


# -- each answer keeps its own scene on a board ---------------------------------------------------------

# "Release path", from call 9BH6YJ7jN5n3mTCVyQWotg (workspace 261006-163450), the private name changed and the
# build refs dropped. Answer 1 showed it whole and pointed at s7 as its last sentence was said; answer 2 showed
# it again and stepped it from empty, a step a sentence.
RELEASE = {"title": "Service check, real versions",
           "actors": [{"id": "c", "label": "Contract\nPR 288 → master", "tone": "service"},
                      {"id": "m", "label": "Platform", "tone": "internal"}, {"id": "k", "label": "Core banking", "tone": "edge"}],
           "phases": [{"id": "p1", "label": "Draft", "start_at": "s1"}, {"id": "p2", "label": "Release", "start_at": "s5"}],
           "steps": [{"id": "s0", "from": "m", "to": "k", "arrow": "band", "label": "Before: Platform on build 14, core banking on 2025-R3-1"},
                     {"id": "s1", "from": "c", "to": "c", "arrow": "self", "tone": "service", "label": "PR 288 opened, dev build published"},
                     {"id": "s2", "from": "c", "to": "m", "arrow": "request", "tone": "internal", "label": "draft pins build 139"},
                     {"id": "s3", "from": "c", "to": "c", "arrow": "self", "tone": "service", "label": "new push, dev build published"},
                     {"id": "s4", "from": "c", "to": "m", "arrow": "request", "tone": "internal", "label": "re-pins build 140"},
                     {"id": "s5", "from": "c", "to": "c", "arrow": "self", "tone": "good", "label": "merged, master publishes build 16"},
                     {"id": "s6", "from": "c", "to": "m", "arrow": "request", "tone": "good", "label": "pins build 16 and merges"},
                     {"id": "s7", "from": "c", "to": "k", "arrow": "request", "tone": "good", "label": "jumps from 2025-R3-1 to build 16"}]}
ALL8 = [f"s{i}" for i in range(8)]


def _release_scenes():
    model = scene.sequence_model(RELEASE)
    one = _scene(model, [["focus step s7"]], "Release path")
    two = _scene(model, [[f"+ step s{i}"] for i in range(8)], "Release path")
    return one, two


def test_replaying_an_earlier_answer_steps_the_scene_it_was_said_with(tmp_path):
    one, two = _release_scenes()
    page = StagePage(tmp_path, width=1400).show("rp", visual("sequence", RELEASE), title="Release path",
                                                extra={"scene": two, "scenes": {"1": one, "2": two}, "answer": 1}).open()
    # answer 1 played again, as call.js sends it: frame 0 until char 317, then frame 1
    page.send({"type": "stage:answer", "n": 1})
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 0}, "keys": 0, "answer": 1}).check("lanes('rp')")
    page.send({"type": "stage:frame", "view": "rp", "n": 1, "animate": True, "answer": 1}).check("lanes('rp')")
    # answer 2 played again: its own scene, from empty
    page.send({"type": "stage:answer", "n": 2})
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 1}, "keys": 0, "answer": 2}).check("lanes('rp')")
    # an answer that fronts the board with no steps of its own shows it whole
    page.send({"type": "stage:answer", "n": 3})
    page.send({"type": "stage:state", "front": "rp", "frames": {}, "keys": 0, "answer": 3}).check("lanes('rp')")
    assert page.run() == [
        {"frame": 0, "step": "1 step", "on": ALL8, "cur": [], "card": None},
        {"frame": 1, "step": "Step 1 of 1", "on": ALL8, "cur": ["s7"], "card": None},
        {"frame": 1, "step": "Step 1 of 8", "on": ["s0"], "cur": ["s0"], "card": None},
        {"frame": 9, "step": "All shown", "on": ALL8, "cur": [], "card": None}]


def test_a_later_answers_scene_never_takes_the_board_from_the_voice_on_it(tmp_path):
    one, two = _release_scenes()
    page = StagePage(tmp_path, width=1400).show("rp", visual("sequence", RELEASE), title="Release path",
                                                extra={"scene": two, "scenes": {"2": two}, "answer": 2}).open()
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 5}, "keys": 0, "answer": 2}).check("lanes('rp')")
    page.show("rp", visual("sequence", RELEASE), title="Release path", background=True,
              extra={"scene": one, "scenes": {"2": two, "3": one}, "answer": 2}).check("lanes('rp')")
    page.send({"type": "stage:frame", "view": "rp", "n": 6, "animate": True, "answer": 2}).check("lanes('rp')")
    on5 = {"frame": 5, "step": "Step 5 of 8", "on": ALL8[:5], "cur": ["s4"], "card": None}
    assert page.run() == [on5, on5, {"frame": 6, "step": "Step 6 of 8", "on": ALL8[:6], "cur": ["s5"], "card": None}]


def test_a_frame_another_answer_sent_before_a_board_came_is_not_applied_to_it(tmp_path):
    one, two = _release_scenes()
    page = StagePage(tmp_path, width=1400).show("first", TABLE, title="First").open()
    # answer 3 framed "rp", whose show failed; answer 4 shows a board of that name before its voice starts
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 7}, "keys": 0, "answer": 3})
    page.show("rp", visual("sequence", RELEASE), title="Release path", extra={"scene": two, "scenes": {"4": two}, "answer": 4})
    page.check("lanes('rp')")
    # a frame of its own answer sent early still waits for it
    page.send({"type": "stage:frame", "view": "rp2", "n": 2, "answer": 4})
    page.show("rp2", visual("sequence", RELEASE), title="Release path 2", extra={"scene": two, "scenes": {"4": two}, "answer": 4})
    page.check("lanes('rp2')")
    assert page.run() == [{"frame": 0, "step": "8 steps", "on": [], "cur": [], "card": "Release path"},
                          {"frame": 2, "step": "Step 2 of 8", "on": ALL8[:2], "cur": ["s1"], "card": None}]


THREE_PATHS = {"nodes": [{"id": "open", "role": "entry", "label": "Open a proposal"},
                         {"id": "batch", "role": "entry", "label": "Nightly batch"},
                         {"id": "share", "role": "entry", "label": "Share task"},
                         {"id": "catch", "role": "code", "label": "Catch every error"}, {"id": "guard", "role": "code", "label": "Broken guard first"},
                         {"id": "state", "role": "success", "label": "Return latest state"}, {"id": "err", "role": "error", "label": "Put in error"}],
               "edges": [{"from": "open", "to": "catch"}, {"from": "batch", "to": "guard"}, {"from": "guard", "to": "err"},
                         {"from": "share", "to": "state", "label": "if broken"}]}


def test_a_frame_past_the_rest_is_the_rest_and_never_stops_the_front(tmp_path):
    paths = _scene(scene.flowchart_spec_model(THREE_PATHS), [["+ open"], ["+ batch"], ["+ share"]], "Three paths changed")
    assert paths["rest"] == 4
    page = (StagePage(tmp_path, width=1400).show("map", visual("flowchart", THREE_PATHS), title="Three paths changed",
                                                 extra={"scene": paths})
            .show("other", TABLE, title="Other", background=True).open())
    page.send({"type": "stage:state", "front": "other", "frames": {"map": 6}, "keys": 0})
    page.check("[selected('other'), frames().map, pane('map').querySelector('.vstep').textContent, errors]")
    assert page.run() == [[True, 4, "All shown", []]]


def test_a_chip_works_as_a_tab_tap_and_never_jumps_the_board_the_voice_is_on(tmp_path):
    one, two = _release_scenes()
    page = (StagePage(tmp_path, width=1400).show("rp", visual("sequence", RELEASE), title="Release path",
                                                 extra={"scene": two, "scenes": {"2": two}, "answer": 2})
            .show("other", TABLE, title="Other", background=True).open())
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 3}, "keys": 0, "answer": 2}).check("lanes('rp')")
    # the chip of the board in front: it stays on the voice's frame, and the voice keeps it
    page.send({"type": "stage:front", "view": "rp", "manual": True}).check("[lanes('rp'), follows()]")
    page.send({"type": "stage:frame", "view": "rp", "n": 4, "animate": True, "answer": 2}).check("lanes('rp')")
    # the chip of another board opens it and takes the stage off the voice, which the call page is told
    page.send({"type": "stage:front", "view": "other", "manual": True}).check("[selected('other'), follows()]")
    page.send({"type": "stage:front", "view": "rp", "answer": 2}).check("selected('other')")
    on3 = {"frame": 3, "step": "Step 3 of 8", "on": ALL8[:3], "cur": ["s2"], "card": None}
    assert page.run() == [on3, [on3, []], {"frame": 4, "step": "Step 4 of 8", "on": ALL8[:4], "cur": ["s3"], "card": None},
                          [True, [False]], True]


def test_a_board_the_voice_fronts_before_it_arrives_comes_forward_when_it_does(tmp_path):
    one, two = _release_scenes()
    page = StagePage(tmp_path, width=1400).show("first", TABLE, title="First").open()
    page.send({"type": "stage:front", "view": "rp", "manual": False, "answer": 2})
    page.send({"type": "stage:frame", "view": "rp", "n": 2, "animate": True, "answer": 2})
    page.show("rp", visual("sequence", RELEASE), title="Release path", background=True,
              extra={"scene": two, "scenes": {"2": two}, "answer": 2})
    page.check("[selected('rp'), selected('first'), lanes('rp')]")
    # a board fronted early stays behind when the voice has fronted another since
    page.send({"type": "stage:front", "view": "late", "manual": False, "answer": 2})
    page.send({"type": "stage:front", "view": "first", "manual": False, "answer": 2})
    page.show("late", TABLE, title="Late", background=True).check("[selected('first'), selected('late')]")
    # a frame sent before its board arrives is applied when it does: one for an answer, to a board that
    # carries only its own scene; one for no answer, to a board that carries its answers' scenes
    page.send({"type": "stage:frame", "view": "own", "n": 3, "animate": True, "answer": 2})
    page.send({"type": "stage:frame", "view": "kept", "n": 4, "animate": True})
    page.show("own", visual("sequence", RELEASE), title="Own scene", background=True, extra={"scene": two})
    page.show("kept", visual("sequence", RELEASE), title="Kept scenes", background=True,
              extra={"scene": two, "scenes": {"2": two}, "answer": 2})
    page.send({"type": "stage:front", "view": "own", "manual": False, "answer": 2}).check("[frames().own, lanes('own').step]")
    page.send({"type": "stage:front", "view": "kept", "manual": False, "answer": None}).check("[frames().kept, lanes('kept').step]")
    assert page.run() == [[True, False, {"frame": 2, "step": "Step 2 of 8", "on": ALL8[:2], "cur": ["s1"], "card": None}],
                          [True, False], [3, "Step 3 of 8"], [4, "Step 4 of 8"]]


# a lanes board as the reader sees it fade: its frame, its step bar, and whether the board is dimmed
FADE = ("(n => ({frame: frames()[n], step: pane(n).querySelector('.vstep').textContent,"
        " dim: pane(n).querySelector('.visual').classList.contains('k-dim')}))")


def test_when_an_answer_ends_each_board_it_stepped_shows_whole_and_undimmed(tmp_path):
    # call 9BH6, answer 1: it ended on a focus of the last step, which left the rest of the board faded
    one, two = _release_scenes()
    page = (StagePage(tmp_path, width=1400).show("rp", visual("sequence", RELEASE), title="Release path",
                                                 extra={"scene": one, "scenes": {"1": one}, "answer": 1})
            .show("rp2", visual("sequence", RELEASE), title="Release path 2", background=True,
                  extra={"scene": one, "scenes": {"1": one}, "answer": 1}).open())
    page.send({"type": "stage:answer", "n": 1})
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 1, "rp2": 1}, "keys": 0, "answer": 1}).check(FADE + "('rp')")
    page.send({"type": "stage:rest", "views": ["rp", "rp2"], "answer": 1}).check(FADE + "('rp')")
    page.send({"type": "stage:front", "view": "rp2", "answer": 1}).check(FADE + "('rp2')")  # the board behind went whole too
    page.send({"type": "stage:front", "view": "rp", "answer": 1})
    # a rest for another answer, or for the board in front that the reader stepped, changes nothing
    page.send({"type": "stage:state", "front": "rp", "frames": {"rp": 1, "rp2": 1}, "keys": 0, "answer": 1})
    page.send({"type": "stage:rest", "views": ["rp", "rp2"], "answer": 3}).check("[frames().rp, frames().rp2]")
    page.send({"type": "stage:front", "view": "rp", "answer": 1})
    page.js("pane('rp').querySelector('.stepback').click();")
    page.send({"type": "stage:rest", "views": ["rp", "rp2"], "answer": 1}).check(FADE + "('rp')")
    page.check("frames().rp2")  # behind, it still goes whole
    whole = {"frame": 2, "step": "All shown", "dim": False}
    assert page.run() == [{"frame": 1, "step": "Step 1 of 1", "dim": True}, whole, whole, [1, 1],
                          {"frame": 0, "step": "1 step", "dim": False}, 2]


# -- the map: what each frame lights, and what draws in ------------------------------------------------

def _each_part_said(spec, title):
    model = scene.flowchart_spec_model(spec)
    return _scene(model, [[f"+ {k[5:]}"] for k in model.order], title)


CUR = "(n => [keys(pane(n).querySelectorAll('.m-node.m-cur')), keys(pane(n).querySelectorAll('.m-edge.m-cur'))])"
# the arrows drawing in on the map now, and the ones a dot runs along
DRAWING = ("(n => [keys([...pane(n).querySelectorAll('.m-edge')].filter((g) => g.querySelector('.m-line.m-draw'))),"
           " [...pane(n).querySelectorAll('.m-dot')].map((d) => d.parentElement.dataset.key)])")


def test_the_map_lights_the_part_being_said_and_the_arrow_out_of_it_even_on_a_scene_saved_before_frames_named_it(tmp_path):
    model = scene.flowchart_spec_model(THREE_PATHS)
    now = _scene(model, [["+ open", "focus open"], ["+ batch", "focus batch"],
                         ["+ share, catch, guard, state, err", "focus share"]], "Three paths changed")
    # as call ggkmNh saved it: the automatic steps ran a node ahead of the points
    then = _saved_before_cur(_scene(model, [["next 2", "focus open"], ["next 2", "focus batch"], ["next 3", "focus share"]],
                                    "Three paths changed"))
    page = (StagePage(tmp_path).show("now", visual("flowchart", THREE_PATHS), title="Three paths changed", extra={"scene": now})
            .show("then", visual("flowchart", THREE_PATHS), title="Three paths then", extra={"scene": then}).open())
    for view in ("now", "then"):
        page.send({"type": "stage:state", "front": view, "frames": {}})
        page.send({"type": "stage:frame", "view": view, "n": 0}).check(CUR + f"('{view}')")  # nothing is said before the first sentence
        page.send({"type": "stage:frame", "view": view, "n": 1, "animate": True}).check(CUR + f"('{view}')")
    # the arrow into nothing said is not lit; the one out of the card being said is
    page.send({"type": "stage:frame", "view": "now", "n": 3, "animate": True}).check(CUR + "('now')")
    assert page.run() == [[[], []], [["node:open"], []], [[], []], [["node:open"], []],
                          [["node:share"], ["edge:share->state#0"]]]


def test_every_arrow_arriving_draws_in_and_the_dot_runs_on_the_one_into_the_card_being_said(tmp_path):
    built = _scene(scene.flowchart_spec_model(LIVE_SPEC), [["+ listening"], ["+ hearing"], ["+ sending"], ["+ working"], ["+ speaking"]],
                   "Live mode's states")
    page = StagePage(tmp_path).show("live", visual("flowchart", LIVE_SPEC), title="Live mode's states", extra={"scene": built}).open()
    for n in range(5):
        page.send({"type": "stage:frame", "view": "live", "n": n, "animate": n > 0})
    page.send({"type": "stage:frame", "view": "live", "n": 5, "animate": True}).check(DRAWING + "('live')").check(CUR + "('live')")
    # three arrive with speaking; the dot runs along the one into it, not along "it ends", the last arrow declared
    assert page.run() == [[["edge:working->speaking#0", "edge:speaking->hearing#0", "edge:speaking->listening#0"],
                           ["edge:working->speaking#0"]], [["node:speaking"], ["edge:working->speaking#0"]]]


def test_an_arriving_arrow_draws_in_with_its_dot_on_a_step_forward_only(tmp_path):
    built = _each_part_said(LIVE_SPEC, "Live mode's states")
    page = StagePage(tmp_path).show("live", visual("flowchart", LIVE_SPEC), title="Live mode's states", extra={"scene": built}).open()
    for n in range(4):  # listening, hearing, sending: an arrow arrives into each of the last two
        page.send({"type": "stage:frame", "view": "live", "n": n, "animate": n > 0}).check(DRAWING + "('live')")
    page.js("pane('live').querySelector('.stepback').click();").check(DRAWING + "('live')")  # Back to hearing
    page.send({"type": "stage:follow", "on": True})
    page.send({"type": "stage:state", "front": "live", "frames": {"live": 3}}).check(DRAWING + "('live')")  # a seek to sending
    page.send({"type": "stage:frame", "view": "live", "n": 3, "animate": True}).check(DRAWING + "('live')")  # sending again
    page.js("pane('live').querySelector('.stepnext').click();").check(DRAWING + "('live')")  # on to working: its arrow arrives
    page.check("[frames().live, keys(pane('live').querySelectorAll('.m-edge.m-cur'))]")
    still = [[], []]
    assert page.run() == [
        still, still, [["edge:listening->hearing#0"], ["edge:listening->hearing#0"]],
        [["edge:hearing->sending#0", "edge:sending->listening#0"], ["edge:hearing->sending#0"]],
        still, still, still, [["edge:sending->working#0"], ["edge:sending->working#0"]], [4, ["edge:sending->working#0"]]]


def test_a_map_shows_no_title_over_its_ghosts_before_the_first_sentence(tmp_path):
    spec = scene.mermaid_spec("graph LR; P[Page] --> Q[Queue]; Q --> S[Session]")  # "Turn path", workspace 261006-154701
    built = _scene(scene.flowchart_spec_model(spec), [["next"], ["next"], ["next"]], "Turn path")
    assert built["start"] == "empty"
    page = StagePage(tmp_path).show("m", visual("flowchart", spec), title="Turn path", extra={"scene": built}).open()
    page.send({"type": "stage:frame", "view": "m", "n": 0})
    page.check("[keys(pane('m').querySelectorAll('.m-node.k-hidden')), pane('m').querySelectorAll('.k-card').length]")
    assert page.run() == [[["node:P", "node:Q", "node:S"], 0]]


def test_a_scene_key_the_drawing_lacks_lights_nothing_and_posts_nothing(tmp_path):
    spec = scene.mermaid_spec("graph LR; P[Page] --> Q[Queue]")
    built = _scene(scene.flowchart_spec_model(scene.mermaid_spec("graph LR; P[Page] --> Q[Queue] --> S[Session]")),
                   [["+ P"], ["+ S"]], "Turn path")
    page = StagePage(tmp_path).show("m", visual("flowchart", spec), title="Turn path", extra={"scene": built}).open()
    for n in (0, 1, 2):
        page.send({"type": "stage:frame", "view": "m", "n": n})
    page.check("keys(pane('m').querySelectorAll('.m-node:not(.k-hidden)'))")
    page.check("posted.map((m) => m.type).filter((t) => !['stage:ready', 'stage:views', 'stage:changed', 'stage:shown', 'stage:follow'].includes(t))")
    assert page.run() == [["node:P"], []]


# "Turn path" as saved in workspace 261006-154701, compiled before an arrow came in with its second end
TURN_PATH_SAVED = {"kind": "flowchart", "keys": ["node:P", "node:Q", "node:S", "edge:P->Q#0", "edge:Q->S#0"],
                   "frames": [{"show": [], "focus": []}, {"show": ["node:P"], "focus": []},
                              {"show": ["node:P", "node:Q"], "focus": []}, {"show": ["node:P", "node:Q", "node:S"], "focus": []},
                              {"show": ["node:P", "node:Q", "node:S", "edge:P->Q#0", "edge:Q->S#0"], "focus": []}],
                   "steps": 3, "rest": 4, "start": "empty", "title": "Turn path", "repairs": 0}


def test_a_saved_scene_from_before_arrows_came_with_their_ends_lights_each_arrow_with_its_second_end(tmp_path):
    spec = scene.mermaid_spec("graph LR; P[Page] --> Q[Queue]; Q --> S[Session]")
    page = StagePage(tmp_path).show("turn", visual("flowchart", spec), title="Turn path", extra={"scene": TURN_PATH_SAVED}).open()
    for n in range(5):
        page.send({"type": "stage:frame", "view": "turn", "n": n})
        page.check("keys(pane('turn').querySelectorAll('.m-edge:not(.k-hidden)'))")
    assert page.run() == [[], [], ["edge:P->Q#0"], ["edge:P->Q#0", "edge:Q->S#0"], ["edge:P->Q#0", "edge:Q->S#0"]]


def test_a_mermaid_link_keeps_its_look_on_the_map_dashed_or_with_a_head_at_both_ends_or_none(tmp_path):
    spec = scene.mermaid_spec("graph LR; A[Page] <--> B[Server]; B -.-> C[Queue]; C --- D[Store]; D ~~~ E[Log]")
    page = StagePage(tmp_path, embedded=False).show("m", visual("flowchart", spec), title="Links").open()
    page.check("[...pane('m').querySelectorAll('.m-edge')].map((g) => [g.dataset.key, g.classList.contains('m-dashed'),"
               " g.querySelectorAll('.m-tip').length, g.querySelectorAll('.m-tail').length])")
    # [arrow, dashed, heads, heads at its start]: ~~~ draws no arrow at all
    assert page.run() == [[["edge:A->B#0", False, 2, 1], ["edge:B->C#0", True, 1, 0], ["edge:C->D#0", False, 0, 0]]]


CYCLE = {"nodes": [{"id": "idle", "role": "entry", "label": "Idle"}, {"id": "busy", "label": "Busy"}, {"id": "done", "label": "Done"}],
         "edges": [{"from": "idle", "to": "busy"}, {"from": "busy", "to": "done"}, {"from": "done", "to": "idle", "label": "again"}]}
RETRY = {"nodes": [{"id": f"p{i}", "label": f"Phase {i}"} for i in range(8)],
         "edges": [{"from": f"p{i}", "to": f"p{i + 1}"} for i in range(7)] + [{"from": "p7", "to": "p0", "label": "retry"}]}
POLL = {"nodes": [{"id": "a", "role": "entry", "label": "Poll"}, {"id": "b", "role": "success", "label": "Done"}],
        "edges": [{"from": "a", "to": "a", "label": "not yet"}, {"from": "a", "to": "b", "label": "ready"}]}


def test_a_map_whose_entry_sits_in_its_one_loop_is_a_ring_and_a_pipeline_with_one_retry_is_not(tmp_path):
    # the browser suite measured these maps for overlaps; here, which way each is laid out and what its cards say
    page = StagePage(tmp_path, embedded=False)
    for name, spec in (("live", LIVE_SPEC), ("cycle", CYCLE), ("retry", RETRY), ("poll", POLL)):
        page.show(name, visual("flowchart", spec), title=name)
    page.open()
    for name in ("live", "cycle", "retry", "poll"):
        page.js(f"document.querySelector('button[role=tab][data-view=\"{name}\"]').click();")  # a tab tap draws it
        page.check(f"[pane('{name}').querySelector('.map').dataset.layout, pane('{name}').querySelector('.map').classList.contains('m-ring'),"
                   f" [...pane('{name}').querySelectorAll('.m-node > b')].map((b) => b.textContent)]")
    # unmeasured, a board is placed as 900px wide: the eight phases of the retry go top to bottom there
    assert page.run() == [
        ["ring", True, ["Listening", "Hearing you", "Sending", "Working", "Speaking"]],
        ["ring", True, ["Idle", "Busy", "Done"]],
        ["down", False, [f"Phase {i}" for i in range(8)]],
        ["across", False, ["Poll", "Done"]]]


# -- the lanes ---------------------------------------------------------------------------------------------

LANES_LIT = ("(n => ({cur: [...pane(n).querySelectorAll('.ln-row.ln-cur')].map((r) => r.dataset.step),"
             " mine: [...pane(n).querySelectorAll('.ln-row.ln-mine')].map((r) => r.dataset.step),"
             " on: [...pane(n).querySelectorAll('.ln-chip.ln-on')].map((c) => c.dataset.actor),"
             " off: [...pane(n).querySelectorAll('.ln-chip.ln-off')].map((c) => c.dataset.actor)}))")


def test_the_lanes_draw_the_step_pointed_at_as_the_one_said_and_an_actor_pointed_at_lights_its_chip_and_steps(tmp_path):
    m = scene.sequence_model(CALLS_SPEC)
    # as call WM4mN6 compiled it: each sentence brought a step in and pointed at the one before
    built = _scene(m, [["next"], ["next", "focus s1"], ["next", "focus s2"], ["focus actor fl"]], "Calls in both directions")
    page = StagePage(tmp_path).show("calls", visual("sequence", CALLS_SPEC), title="Calls in both directions",
                                    extra={"scene": built}).open()
    for n in (0, 1, 2):
        page.send({"type": "stage:frame", "view": "calls", "n": n, "animate": n > 0})
    page.check(LANES_LIT + "('calls')")
    page.send({"type": "stage:frame", "view": "calls", "n": 4}).check(LANES_LIT + "('calls')")
    # frame 2: the step pointed at is the one said, its two actors' chips lit; frame 4: the Flowable module's chip
    # and the steps it takes part in, and no step said
    assert page.run() == [{"cur": ["s1"], "mine": [], "on": ["app", "port"], "off": ["fl"]},
                          {"cur": [], "mine": ["s2", "s3"], "on": ["fl"], "off": ["app", "port"]}]


# -- tables and code: the part being said ------------------------------------------------------------------

TIMELINE_BODY = {"type": "inline", "format": "table", "body": "| When | Contract repo | Service |\n|---|---|---|\n"
                 "| before | | pins M14 |\n| 13 Jan | PR opened, builds D139 | draft pins D139 |\n"
                 "| 21 Jan | new push, builds D140 | draft re-pins D140 |\n| 26 Jan | PR merges, builds M16 | pins M16 and merges |\n"
                 "| 2 Feb | | core banking moves to M16 |"}
ENGINES5 = {"type": "inline", "format": "table", "body": "| | Azure | VoiceStudio |\n|---|---|---|\n"  # the demo's
            "| Speed | a second or two per answer | about as long to make as to play |\n| Cost | billed per character | free |\n"
            "| Runs on | Microsoft's servers | this Mac |\n| Needs | `TALK_AZURE_KEY_COMMAND` | the VoiceStudio app open |\n"
            "| Picked | when a key is found | when no key is found |"}
SAID_ROWS = "(n => keys(pane(n).querySelectorAll('tbody tr.g-cur')))"


def test_a_table_draws_no_row_as_being_said_before_one_is_pointed_at_and_a_range_of_rows_together(tmp_path):
    now = _scene(TIMELINE, [["focus rows 1-2"], ["focus row 3"]], "Timeline, simply")
    then = _saved_before_cur(_scene(TIMELINE, [[f"focus row {n}"] for n in range(1, 6)], "Timeline, simply"))
    engines = _scene(ENGINES_MODEL, [["next", 'focus cell "Speed" / "Azure"'], ["next"]], "Two speech engines")
    page = (StagePage(tmp_path).show("now", TIMELINE_BODY, title="Timeline, simply", extra={"scene": now})
            .show("then", TIMELINE_BODY, title="Timeline then", extra={"scene": then})
            .show("eng", ENGINES5, title="Two speech engines", extra={"scene": engines}).open())
    for view in ("now", "then"):
        page.send({"type": "stage:state", "front": view, "frames": {}})
        page.send({"type": "stage:frame", "view": view, "n": 0}).check(SAID_ROWS + f"('{view}')")  # not the last row
    page.send({"type": "stage:state", "front": "now", "frames": {"now": 1}}).check(SAID_ROWS + "('now')")
    page.send({"type": "stage:state", "front": "eng", "frames": {"eng": 1}})
    page.send({"type": "stage:frame", "view": "eng", "n": 2, "animate": True})
    # the Speed cell pointed at before is not left lit
    page.check(SAID_ROWS + "('eng')").check("keys(pane('eng').querySelectorAll('.k-focus'))")
    assert page.run() == [[], [], ["row#1", "row#2"], ["row#2"], []]


# Real boards, from the stage demo (call workspaces 261005-105449 and 261007-073115): this repository's own code.
OFFER = {"type": "inline", "format": "code", "path": "skills/talk/live_turns.py", "start": 30, "highlight": [31, 33], "lang": "py",
         "lines": [
             "    def offer(self, turn_id: str, lines: list[dict]) -> None:",
             "        \"\"\"A new turn. One still waiting to be collected is merged into it under the new id.\"\"\"",
             "        if self.pending_id:",
             "            self.offered_ids.discard(self.pending_id)",
             "        self.pending_id = turn_id",
             "        self.offered_ids.add(turn_id)",
             "        self.lines.extend(lines)",
             "        self.offered_at = self.clock()",
             "        self._changed.set()",
         ]}
CELLS = {"type": "inline", "format": "change", "path": "skills/stage/static/scene.js", "rev": "7e355e8", "added": 4, "removed": 1, "more": 0,
         "lang": "js", "hunks": [
             {"header": "@@ -16,5 +16,8 @@ function stampKeys(kind, box) {", "start_old": 16, "start_new": 16, "lines": [
                 {"op": " ", "old": 16, "new": 16, "text": "  if (kind === \"rows\") {"},
                 {"op": " ", "old": 17, "new": 17, "text": "    const rows = [...(box.querySelector(\"table\")?.querySelectorAll(\"tbody tr\") || [])];"},
                 {"op": "-", "old": 18, "new": None, "text": "    rows.forEach((tr, i) => { tr.dataset.key = \"row#\" + (i + 1); });"},
                 {"op": "+", "old": None, "new": 18, "text": "    rows.forEach((tr, i) => {"},
                 {"op": "+", "old": None, "new": 19, "text": "      tr.dataset.key = \"row#\" + (i + 1);"},
                 {"op": "+", "old": None, "new": 20, "text": "      [...tr.children].forEach((td, j) => { td.dataset.key = `cell#${i + 1}.${j + 1}`; });"},
                 {"op": "+", "old": None, "new": 21, "text": "    });"},
                 {"op": " ", "old": 19, "new": 22, "text": "    return rows.length > 0;"},
                 {"op": " ", "old": 20, "new": 23, "text": "  }"},
             ]}]}
LIT_LINES = "(n => keys(pane(n).querySelectorAll('.ln.k-focus')))"


def test_a_line_pointed_at_is_lit_outside_a_highlight_and_on_a_context_an_added_or_a_removed_line(tmp_path):
    offer = _scene(scene.lines_model(range(30, 39)), [["focus 36"], ["focus 32"]], "Offer merges waiting turns")
    cells = _scene(scene.change_model(CELLS["hunks"]), [["focus 17-18"], ["focus old 18"]], "Cells and the current one")
    page = (StagePage(tmp_path).show("o", OFFER, title="Offer merges waiting turns", extra={"scene": offer})
            .show("c", CELLS, title="Cells and the current one", extra={"scene": cells}, background=True).open())
    page.send({"type": "stage:frame", "view": "o", "n": 1, "animate": True}).check(LIT_LINES + "('o')")
    page.send({"type": "stage:frame", "view": "o", "n": 2, "animate": True}).check(LIT_LINES + "('o')")
    page.send({"type": "stage:state", "front": "c", "frames": {"c": 1}}).check(LIT_LINES + "('c')")
    page.send({"type": "stage:frame", "view": "c", "n": 2, "animate": True}).check(LIT_LINES + "('c')")
    # lines 17-18 of the change: a context line, the removed old line 18 inside them, and the added line 18
    assert page.run() == [["line:36"], ["line:32"], ["line:17", "old:18", "line:18"], ["old:18"]]


def test_only_a_scene_frame_lights_a_part_and_the_old_point_message_does_nothing(tmp_path):
    # stage:point had its own highlight (.spot, .dimmed) beside the frames' k-focus; nothing sent it, so it is gone
    page = (StagePage(tmp_path).show("c", CODE5, title="Five steps")
            .show("t", {"type": "inline", "format": "table", "body": AREAS}, title="Areas", background=True).open())
    page.send({"type": "stage:point", "view": "c", "target": {"type": "lines", "a": 2, "b": 3}})
    page.send({"type": "stage:point", "view": "t", "target": {"type": "row", "n": 2}})
    page.check("[selected('c'), selected('t'), document.querySelectorAll('.spot, .dimmed, .k-focus, .k-dim').length]")
    assert page.run() == [[True, False, 0]]

