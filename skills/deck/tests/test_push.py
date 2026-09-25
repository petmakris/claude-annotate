from pathlib import Path
from unittest.mock import patch

from skills.deck import push


MINIMAL_DECK_HTML = """<!doctype html><html><body>
<div class="deck"><section class="slide"><div class="pro"><p>Point one</p></div></section></div>
</body></html>"""


def test_push_creates_session_copies_files_and_pushes_model(tmp_path):
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)

    with patch("skills.deck.push.wc.list_sessions", return_value=[]), \
         patch("skills.deck.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "deck",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.deck.push.wc.put_items") as mock_put, \
         patch("skills.deck.push.wc.register_assets") as mock_assets:
        res = push.push(deck_file, str(tmp_path), title="MyDeck")

    mock_create.assert_called_once_with("deck", str(tmp_path), title="MyDeck", slug=None)
    assert res["sid"] == "s1"

    # The pushed model item is real parse_deck() output, not a stub.
    put_call = mock_put.call_args
    assert put_call.args[0] == "s1"
    items = put_call.args[1]
    assert set(items.keys()) == {"__model__"}
    assert items["__model__"]["slides"][0]["elements"][0]["component"] == "pro"
    # Claude-relevant, not browser-relevant: the only place left to carry the
    # deck's absolute path now that there is no meta.json.
    assert items["__model__"]["deck"] == str(deck_file.resolve())
    assert "fingerprint" not in items["__model__"]  # superseded by the item's own version
    assert put_call.kwargs == {"kind": "deck", "replace": True}

    # The copy directory actually contains a fixed-name copy of the deck, plus
    # the plugin's own static files, and register_assets points at it.
    assets_call = mock_assets.call_args
    assert assets_call.args[0] == "s1"
    copy_dir = Path(assets_call.args[1])
    assert assets_call.args[2] == "entry.js"
    assert assets_call.kwargs == {"kind": "deck"}
    assert (copy_dir / "content.html").read_text() == MINIMAL_DECK_HTML
    assert (copy_dir / "entry.js").is_file()
    assert (copy_dir / "deck.js").is_file()
    assert (copy_dir / "deck.css").is_file()
    present = (copy_dir / "present.html").read_text()
    assert 'sandbox="allow-scripts' in present
    assert "allow-same-origin" not in present.split("<iframe", 1)[1].split(">", 1)[0]


def test_push_rejects_a_non_html_file(tmp_path):
    not_html = tmp_path / "deck.txt"
    not_html.write_text("nope")
    try:
        push.push(not_html, str(tmp_path))
        assert False, "expected a ValueError"
    except ValueError as e:
        assert "html" in str(e).lower()


def test_push_rejects_a_missing_file(tmp_path):
    try:
        push.push(tmp_path / "nope.html", str(tmp_path))
        assert False, "expected a ValueError"
    except ValueError as e:
        assert "not found" in str(e).lower() or "no such" in str(e).lower()


def test_push_re_copies_updated_content_on_a_second_push(tmp_path):
    """The whole change-notification design depends on this: an edited file's
    new bytes must actually land in the copy directory on the next push, not
    a stale copy from the first push."""
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)

    with patch("skills.deck.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "myslug", "kind": "deck",
                            "url": "http://127.0.0.1:3080/s/myslug/", "token": "tok"}), \
         patch("skills.deck.push.wc.put_items") as mock_put, \
         patch("skills.deck.push.wc.register_assets") as mock_assets:
        push.push(deck_file, str(tmp_path), slug="myslug")
        copy_dir = Path(mock_assets.call_args.args[1])

        deck_file.write_text(MINIMAL_DECK_HTML.replace("Point one", "Point one, edited"))
        push.push(deck_file, str(tmp_path), slug="myslug")

    assert "Point one, edited" in (copy_dir / "content.html").read_text()


def _sessions(deck_file):
    return [
        {"sid": "260923-100000-old", "slug": "my-deck", "state": "live"},
        {"sid": "260923-120000-new", "slug": "other", "state": "live"},
        {"sid": "260923-130000-gone", "slug": "x", "state": "finished"},
    ]


def _items_for(deck_file):
    def get_items(sid, kind):
        deck = str(deck_file.resolve()) if sid != "260923-120000-new" else "/elsewhere.html"
        return {"__model__": {"body": {"deck": deck}}}
    return get_items


def test_a_push_without_slug_reuses_the_session_already_showing_this_deck(tmp_path):
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)
    with patch("skills.deck.push.wc.list_sessions", return_value=_sessions(deck_file)), \
         patch("skills.deck.push.wc.get_items", side_effect=_items_for(deck_file)), \
         patch("skills.deck.push.wc.create_or_attach") as mock_create, \
         patch("skills.deck.push.wc.put_items") as mock_put, \
         patch("skills.deck.push.wc.register_assets"):
        res = push.push(deck_file, str(tmp_path))
    mock_create.assert_not_called()
    assert res["sid"] == "260923-100000-old"
    assert mock_put.call_args.args[0] == "260923-100000-old"


def test_slug_accepts_the_sid_from_the_url(tmp_path):
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)
    with patch("skills.deck.push.wc.list_sessions", return_value=_sessions(deck_file)), \
         patch("skills.deck.push.wc.create_or_attach") as mock_create, \
         patch("skills.deck.push.wc.put_items"), \
         patch("skills.deck.push.wc.register_assets"):
        res = push.push(deck_file, str(tmp_path), slug="260923-120000-new")
    mock_create.assert_not_called()
    assert res["sid"] == "260923-120000-new"


def test_watch_re_pushes_on_change_and_stops_when_the_session_ends(tmp_path):
    deck_file = tmp_path / "MyDeck.html"
    deck_file.write_text(MINIMAL_DECK_HTML)
    ticks = iter(range(1000))
    edits = {3: "edit one", 6: "edit two"}
    step = {"n": 0}

    def fake_sleep(_):
        step["n"] += 1
        if step["n"] in edits:
            deck_file.write_text(MINIMAL_DECK_HTML.replace("Point one", edits[step["n"]]))
            import os
            os.utime(deck_file, ns=(step["n"] * 10**9, step["n"] * 10**9))

    alive = {"n": 0}

    def fake_rows(cwd):
        alive["n"] += 1
        return [{"sid": "s1", "slug": "s1", "state": "live"}] if alive["n"] < 3 else []

    with patch("skills.deck.push.push") as mock_push, \
         patch("skills.deck.push._rows", side_effect=fake_rows):
        code = push.watch(deck_file, str(tmp_path), "s1", interval=0, alive_every=4,
                          sleep=fake_sleep, clock=lambda: next(ticks))
    assert code == 0
    assert mock_push.call_count == 2
    assert all(c.kwargs == {"slug": "s1"} for c in mock_push.call_args_list)
