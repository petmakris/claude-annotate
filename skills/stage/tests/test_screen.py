"""A screen board: a spotlight spec (skills/spotlight) shown on the stage, one part lit at a time."""
import json
import struct
import zlib

import pytest

from skills.stage import model, scene
from skills.stage.tests.test_stage import fake  # noqa: F401  (the daemon, faked, for the show tests)
from skills.stage import stage


def png(w, h):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SPEC = {
    "tag": "Team · Tool", "title": "How to file a request", "footer": "Screens from a test site",
    "screens": [
        {"id": "form", "label": "The form", "image": "shots/form.png", "crop": [20, 10, 160, 80], "source": "The form",
         "steps": [{"title": "Every request starts from one form", "text": "What the reader sees first."},
                   {"box": [30, 20, 40, 10], "title": "Press <b>Send</b> when it is done", "text": "The button."}]},
        {"id": "list", "label": "The list", "html": "<ul><li class='mine'>Mine</li><li>Others</li></ul>",
         "steps": [{"focus": ".mine", "title": "Your own requests come first"}]},
    ],
}


def project(tmp_path, spec=SPEC):
    (tmp_path / "docs" / "shots").mkdir(parents=True)
    (tmp_path / "docs" / "shots" / "form.png").write_bytes(png(200, 100))
    (tmp_path / "docs" / "spotlight.json").write_text(json.dumps(spec))
    return tmp_path


def test_a_screen_source_keeps_its_images_in_their_folder_and_numbers_its_parts(tmp_path):
    src = model.parse_source("screen:docs/spotlight.json", project(tmp_path))
    assert (src["type"], src["format"], src["spec"], src["dir"]) == ("inline", "screen", "docs/spotlight.json", "docs")
    assert (src["title"], src["tag"], src["footer"]) == ("How to file a request", "Team · Tool", "Screens from a test site")
    form, lst = src["screens"]
    # the image stays a path; the crop is drawn by the page, so the box is moved into the cut
    assert (form["image"], form["w"], form["h"], form["full"], form["off"]) == ("shots/form.png", 160, 80, [200, 100], [20, 10])
    assert "src" not in form
    assert [st["id"] for st in form["steps"]] == ["p1", "p2"] and form["steps"][1]["boxes"] == [[10, 10, 40, 10]]
    assert lst["html"].startswith("<ul>") and lst["steps"] == [{"id": "p3", "title": "Your own requests come first", "focus": ".mine"}]
    assert len(json.dumps(src)) < 2000  # no image bytes in the view


@pytest.mark.parametrize("spec, where, want", [
    (None, "screen:docs/missing.json", "no such spotlight spec in the project: docs/missing.json"),
    (None, "screen:../outside.json", "outside"),
    (None, "screen:", "expected screen:<path to a spotlight.json in the project>"),
    ({"title": "T", "screens": [{"id": "a", "image": "../x.png", "steps": [{"title": "x"}]}]}, "screen:docs/spotlight.json",
     "image ../x.png is outside the spec's folder"),
    ({"title": "T", "screens": [{"id": "a", "image": "shots/form.png", "steps": [{"title": "x", "box": [190, 0, 20, 5]}]}]},
     "screen:docs/spotlight.json", "screen:docs/spotlight.json: a step 1: box [190, 0, 20, 5] leaves the 200x100 image"),
    ({"title": "T", "screens": [{"id": "a", "image": "shots/form.png", "crop": [150, 0, 100, 50], "steps": [{"title": "x"}]}]},
     "screen:docs/spotlight.json", "crop [150, 0, 100, 50] leaves the 200x100 image"),
])
def test_a_screen_source_is_refused_with_the_reason(tmp_path, spec, where, want):
    root = project(tmp_path, spec or SPEC)
    with pytest.raises(model.SourceError, match=__import__("re").escape(want)):
        model.parse_source(where, root)


def test_a_screen_that_is_not_json_is_refused(tmp_path):
    root = project(tmp_path)
    (root / "docs" / "spotlight.json").write_text("{nope")
    with pytest.raises(model.SourceError, match="screen:docs/spotlight.json: not JSON"):
        model.parse_source("screen:docs/spotlight.json", root)


def test_a_screens_parts_are_named_by_their_titles_as_plain_words(tmp_path):
    src = model.parse_source("screen:docs/spotlight.json", project(tmp_path))
    m = model.screen_model(src)
    assert m.kind == "parts" and m.keys == ["part:p1", "part:p2", "part:p3"]
    assert m.names["press send when it is done"] == "part:p2"  # the <b> is not a word a sentence says
    assert scene.resolve(m, "part p3", "T")[0] == ["part:p3"]
    assert scene.resolve(m, 'part "Press Send when it is done"', "T")[0] == ["part:p2"]


def test_a_screen_shown_on_its_own_steps_one_part_at_a_time(tmp_path):
    src = model.parse_source("screen:docs/spotlight.json", project(tmp_path))
    built = model.screen_scene(src, "How to file a request")
    assert (built["start"], built["steps"], built["rest"]) == ("full", 3, 4)
    assert [f["cur"] for f in built["frames"]] == [[], ["part:p1"], ["part:p2"], ["part:p3"], []]
    assert [f["focus"] for f in built["frames"]] == [[], ["part:p1"], ["part:p2"], ["part:p3"], []]


def test_showing_a_screen_mounts_its_folder_and_the_cli_gives_it_its_steps(fake, tmp_path, capsys):  # noqa: F811
    root = project(tmp_path)
    assert stage.main(["show", "how", "screen:docs/spotlight.json", "--cwd", str(root)]) == 0
    view = fake.items["view:how"]
    assert view["title"] == "How to file a request" and view["source"]["format"] == "screen"
    assert fake.mounts[view["source"]["mount"]] == str((root / "docs").resolve())
    assert [f["cur"] for f in view["scene"]["frames"]][1:-1] == [["part:p1"], ["part:p2"], ["part:p3"]]


def test_the_cli_refuses_a_bad_screen_with_exit_2(fake, tmp_path, capsys):  # noqa: F811
    assert stage.main(["show", "how", "screen:docs/nothing.json", "--cwd", str(tmp_path)]) == 2
    assert "no such spotlight spec" in capsys.readouterr().err
