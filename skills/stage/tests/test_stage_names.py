"""The names the stage's controls give a screen reader and a voice command (stage.js, run under node)."""
from skills.stage.tests.stage_page import StagePage, needs_node

pytestmark = needs_node


def test_the_board_list_button_is_named_by_the_position_it_shows(tmp_path):
    # study finder-4: the aria-label said "All boards" and hid "Board 3 of 8", so the control was found by neither its words nor its role
    page = StagePage(tmp_path)
    for name in ("a", "b", "c"):
        page.show(name, {"type": "inline", "format": "table", "body": "| x |\n|---|\n| 1 |"}, title=name.upper())
    page.open()
    name = "[document.querySelector('.tabpos').textContent, document.querySelector('.tabnav .pos').getAttribute('aria-label')]"
    page.check(name)
    page.js("document.querySelector('.tabnav .prev').click();").check(name)
    assert page.run() == [["Board 3 of 3", "Board 3 of 3, all boards"], ["Board 2 of 3", "Board 2 of 3, all boards"]]
