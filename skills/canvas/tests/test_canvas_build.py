"""The manifest check, the build and the template (skills/canvas/canvas.py, tools/canvas.py)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skills.canvas import canvas

PIL = pytest.importorskip("PIL.Image")
TOOL = Path(__file__).resolve().parents[3] / "tools" / "canvas.py"
REAL_ENSURE = canvas.ensure_session


def png(path: Path, w: int, h: int, colour=(200, 220, 240)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    PIL.new("RGB", (w, h), colour).save(path)


def journey(tmp: Path) -> Path:
    """Two boards: a desktop and a 2x full-page phone shot, then one desktop-only board."""
    png(tmp / "01-a.png", 1600, 1000)
    png(tmp / "01-a.phone.png", 780, 3808)
    png(tmp / "02-b.png", 1600, 1748)
    m = {
        "title": "Mealy journey", "id": "mealy", "subtitle": "petros-journey",
        "session": {"kind": "journey", "slug": "mealy", "cwd": "/home/x/mealy", "reruns": True},
        "comments": {"canvas": "mealy", "name": "Mealy", "scopes": {"app": "This app", "both": "Both apps"}},
        "groups": [{"name": "Account", "id": "account", "status": "passed", "boards": [
            {"number": 1, "title": "Sign in </script><b>", "caption": "Reached: start",
             "shots": [{"label": "Desktop", "file": "01-a.png", "viewport": {"width": 1600, "height": 1000}},
                       {"label": "Phone", "file": "01-a.phone.png", "width": 390, "height": 1904,
                        "viewport": {"width": 390, "height": 844}}]},
            {"number": 2, "title": "Settings", "shots": [{"label": "Desktop", "file": "02-b.png", "viewport": {"width": 1600, "height": 1000}}]}]}],
    }
    (tmp / "canvas.json").write_text(json.dumps(m))
    return tmp / "canvas.json"


@pytest.fixture(autouse=True)
def no_daemon(monkeypatch):
    """No test reaches webcompanion: the session a build would find or make is a stand-in."""
    made = []

    def fake(se, out):
        made.append((se, out))
        (out / canvas.BOOT).write_text(canvas.BOOT_JS)
        return {"sid": "s-1", "slug": se["slug"], "kind": se["kind"], "url": "https://wc.example/s/s-1/"}

    monkeypatch.setattr(canvas, "ensure_session", fake)
    monkeypatch.setenv("CANVAS_NO_SESSION", "1")
    return made


def page_data(page: Path) -> dict:
    html = page.read_text()
    blob = html.split('<script type="application/json" id="canvas-data">', 1)[1].split("</script>", 1)[0]
    return json.loads(blob)


def test_a_good_manifest_has_no_problems(tmp_path):
    m = json.loads(journey(tmp_path).read_text())
    assert canvas.check(m, tmp_path) == []


@pytest.mark.parametrize("change, problem", [
    (lambda m: m.pop("title"), "title:"),
    (lambda m: m.update(groups=[]), "groups:"),
    (lambda m: m["groups"][0]["boards"][1].update(number=1), "1 is also groups[0].boards[0]"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(file="../x.png"), "inside its folder"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(file="nope.png"), "nope.png does not exist"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][1].update(label="Desktop"), "Desktop twice on one board"),
    (lambda m: m["comments"].update(canvas="Mealy App"), "comments.canvas"),
    (lambda m: m["session"].update(kind="Journey!"), "session.kind"),
    (lambda m: m["session"].update(cwd="relative"), "session.cwd"),
    (lambda m: m["groups"][0].update(id="Account Feature"), "groups[0].id"),
    (lambda m: m["groups"][0]["boards"][0].update(status="broken"), "status"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(viewport={"width": 0}), "viewport"),
    (lambda m: m["groups"][0]["boards"][0].update(change="moved"), "change: one of changed, unchanged, new"),
    (lambda m: m["groups"][0]["boards"][0].update(change_note=3), "change_note: must be a string"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(previous="previous/gone.png"), "previous: previous/gone.png does not exist"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(previous="../x.png"), "previous: a path relative"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(change="same"), "shots[0].change"),
    (lambda m: m["groups"][0]["boards"][0]["shots"][0].update(diff={"x": 1, "y": 2}), "diff"),
    (lambda m: m.update(changes={"since": "today", "removed": [{"number": 3}]}), "changes.removed"),
    (lambda m: m["groups"][0]["boards"][0].update(id="../x y"), "boards[0].id: letters"),
    (lambda m: [b.update(id="account/01-a") for b in m["groups"][0]["boards"]], "account/01-a is also groups[0].boards[0]"),
])
def test_check_names_what_is_wrong(tmp_path, change, problem):
    m = json.loads(journey(tmp_path).read_text())
    change(m)
    errs = canvas.check(m, tmp_path)
    assert any(problem in e for e in errs), errs


def test_build_writes_one_page_with_its_data_and_thumbnails_of_the_drawn_part(tmp_path):
    page = canvas.build(journey(tmp_path), tmp_path)
    html = page.read_text()
    assert "/*CANVAS:" not in html
    d = page_data(page)
    # The desktop shot is drawn 480 wide, so 300 tall; the phone at the same height.
    assert d["height"] == 300 and d["labels"] == ["Desktop", "Phone"] and d["captionH"] == canvas.CAPTION_H
    desk, phone = d["groups"][0]["boards"][0]["shots"]
    assert desk["thumbs"] == ["thumbs/01-a.1.webp", "thumbs/01-a.2.webp"] and not desk["cropped"]
    sizes = [PIL.open(tmp_path / t).size for t in desk["thumbs"]]
    assert sizes == [(480, 300), (960, 600)]
    # The phone's first screen (390 × 844 of its 390 × 1904 page), 2x in its PNG; its key is its label.
    assert phone["key"] == "phone" and phone["cropped"] and (phone["width"], phone["height"]) == (390, 1904)
    frame_w = 300 * 390 / 844
    for tier, t in zip((1, 2), phone["thumbs"]):
        w = round(frame_w * tier)
        assert PIL.open(tmp_path / t).size == (w, round(1688 * w / 780))
    # A full-page desktop shot is cropped to its window too.
    assert d["groups"][0]["boards"][1]["shots"][0]["cropped"]


def test_no_text_in_the_data_can_end_its_script(tmp_path):
    page = canvas.build(journey(tmp_path), tmp_path)
    assert "Sign in </script>" not in page.read_text()
    assert page_data(page)["groups"][0]["boards"][0]["title"] == "Sign in </script><b>"


def test_build_into_another_folder_copies_the_images(tmp_path):
    out = tmp_path / "out"
    canvas.build(journey(tmp_path / "src"), out)
    assert (out / "01-a.png").is_file() and (out / "01-a.phone.png").is_file() and (out / "thumbs" / "02-b.2.webp").is_file()
    assert not (out / "canvas.json").exists()


def test_a_rebuild_keeps_thumbnails_newer_than_their_image(tmp_path):
    canvas.build(journey(tmp_path), tmp_path)
    t = tmp_path / "thumbs" / "01-a.1.webp"
    before = t.stat().st_mtime_ns
    canvas.build(tmp_path / "canvas.json", tmp_path)
    assert t.stat().st_mtime_ns == before


def test_the_page_runs_the_tested_scripts_and_names_its_shots_the_way_comments_need():
    page = canvas.template()
    static = Path(canvas.__file__).parent / "static"
    for f in ("canvas-math.js", "canvas-store.js", "canvas-page.js", "canvas-session.js", "canvas-comments.js"):
        assert (static / f).read_text() in page
    assert page.count(canvas.DATA_MARK) == 1
    assert "loading=" not in page


def test_the_page_stays_at_the_link_it_was_opened_at():
    # A session's canvas is opened only at its session's link; no copy elsewhere is sent there.
    assert "location.replace" not in canvas.template()


def test_the_cli_checks_and_builds(tmp_path):
    man = journey(tmp_path)
    ok = subprocess.run([sys.executable, str(TOOL), "check", str(man)], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.strip() == "ok"
    bad = json.loads(man.read_text())
    bad["groups"][0]["boards"][0]["shots"][0]["file"] = "missing.png"
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    no = subprocess.run([sys.executable, str(TOOL), "check", str(tmp_path / "bad.json")], capture_output=True, text=True)
    assert no.returncode == 1 and "missing.png does not exist" in no.stderr
    out = subprocess.run([sys.executable, str(TOOL), "build", str(man), "--out", str(tmp_path / "o")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "o" / "index.html").is_file()


def with_changes(tmp: Path) -> Path:
    """The journey, compared with an earlier capture: board 1's desktop shot changed, board 2 is new."""
    man = journey(tmp)
    png(tmp / "previous" / "01-a.png", 1600, 1000, (10, 10, 10))
    png(tmp / "previous" / "01-a.phone.png", 780, 3808)
    m = json.loads(man.read_text())
    m["changes"] = {"since": "29 Oct 2026, 08:00", "removed": [{"number": 3, "title": "Gone", "group": "Account"}]}
    b1, b2 = m["groups"][0]["boards"]
    b1.update(change="changed", change_label="renamed", change_note="Was “Log in”.")
    b1["shots"][0].update(change="changed", previous="previous/01-a.png", diff={"x": 10, "y": 20, "width": 300, "height": 40})
    b1["shots"][1].update(change="unchanged", previous="previous/01-a.phone.png")
    b2["change"] = "new"
    man.write_text(json.dumps(m))
    return man


def test_a_manifest_with_changes_has_no_problems(tmp_path):
    man = with_changes(tmp_path)
    assert canvas.check(json.loads(man.read_text()), tmp_path) == []


def test_the_changes_reach_the_page_and_the_earlier_images_get_no_thumbnails(tmp_path):
    out = tmp_path / "out"
    page = canvas.build(with_changes(tmp_path / "src"), out)
    d = page_data(page)
    assert d["changes"] == {"since": "29 Oct 2026, 08:00", "removed": [{"number": 3, "title": "Gone", "group": "Account"}]}
    b1, b2 = d["groups"][0]["boards"]
    assert (b1["change"], b1["changeLabel"], b1["changeNote"], b2["change"]) == ("changed", "renamed", "Was “Log in”.", "new")
    desk, phone = b1["shots"]
    assert desk["previous"] == "previous/01-a.png" and desk["change"] == "changed"
    assert desk["diff"] == {"x": 10, "y": 20, "width": 300, "height": 40}
    assert phone["change"] == "unchanged" and "diff" not in phone
    assert "previous" not in b2["shots"][0] and "change" not in b2["shots"][0]
    # Copied beside the new images, so the viewer can open them; no thumbnail of them.
    assert PIL.open(out / "previous" / "01-a.png").getpixel((0, 0)) == (10, 10, 10)
    assert sorted(p.name for p in (out / "thumbs").iterdir()) == sorted(
        f"{s}.{t}.webp" for s in ("01-a", "01-a.phone", "02-b") for t in (1, 2))


def test_a_canvas_without_changes_carries_no_change_data(tmp_path):
    d = page_data(canvas.build(journey(tmp_path), tmp_path))
    assert "changes" not in d
    assert not any(k in b for b in d["groups"][0]["boards"] for k in ("change", "changeLabel", "changeNote"))


def test_boards_with_ids_may_repeat_numbers_and_carry_their_id_to_the_page(tmp_path):
    """A canvas whose groups each number from 1 (lomem's feature journeys) names each board by its id."""
    man = journey(tmp_path)
    m = json.loads(man.read_text())
    second = json.loads(json.dumps(m["groups"][0]))
    second["name"] = "Settings"
    m["groups"].append(second)
    for g in m["groups"]:
        for b in g["boards"]:
            b["id"] = f"{g['name'].lower()}/{b['number']:02d}"
    assert canvas.check(m, tmp_path) == []
    man.write_text(json.dumps(m))
    d = page_data(canvas.build(man, tmp_path))
    assert [(b["number"], b["id"]) for g in d["groups"] for b in g["boards"]] == [
        (1, "account/01"), (2, "account/02"), (1, "settings/01"), (2, "settings/02")]
    # Without ids the numbers still have to be unique.
    for g in m["groups"]:
        for b in g["boards"]:
            del b["id"]
    assert any("1 is also" in e for e in canvas.check(m, tmp_path))


def test_a_session_canvas_carries_its_session_group_ids_and_build_time_to_the_page(tmp_path, no_daemon):
    page = canvas.build(journey(tmp_path), tmp_path / "out")
    d = page_data(page)
    assert d["session"] == {"sid": "s-1", "slug": "mealy", "kind": "journey", "url": "https://wc.example/s/s-1/", "reruns": True}
    assert d["groups"][0]["id"] == "account"
    assert d["comments"]["canvas"] == "mealy"
    assert d["built"].endswith("Z")
    assert no_daemon[0][0]["cwd"] == "/home/x/mealy" and no_daemon[0][1] == tmp_path / "out"
    assert (tmp_path / "out" / "wc-boot.js").read_text() == canvas.BOOT_JS


def test_without_its_session_a_canvas_builds_with_no_comments_and_says_why(tmp_path, monkeypatch):
    def down(se, out):
        raise canvas.SessionUnavailable("cannot reach the webcompanion daemon")

    monkeypatch.setattr(canvas, "ensure_session", down)
    d = page_data(canvas.build(journey(tmp_path), tmp_path / "out"))
    assert "comments" not in d and "session" not in d
    assert "Built without its webcompanion session (cannot reach the webcompanion daemon)" in d["banner"]


def test_the_real_ensure_session_stops_at_once_when_told_there_is_no_daemon(tmp_path):
    with pytest.raises(canvas.SessionUnavailable):
        REAL_ENSURE({"kind": "journey", "slug": "mealy", "cwd": "/x"}, tmp_path)


def test_comments_without_a_session_are_left_out_so_an_old_manifest_still_builds(tmp_path):
    p = journey(tmp_path)
    m = json.loads(p.read_text())
    m.pop("session")
    m["comments"]["url"] = "https://journey-comments.main.okimotus.com"
    p.write_text(json.dumps(m))
    assert canvas.check(m, tmp_path) == []
    d = page_data(canvas.build(p, tmp_path / "out"))
    assert "comments" not in d and "session" not in d and "banner" not in d
