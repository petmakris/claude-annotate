"""T15: a table the stage cannot fit gets a `board:` line the session can act on, and the guide gives a user's table
the rows they named (run bd1125b, batch S)."""
from __future__ import annotations

from pathlib import Path

from skills.talk import talk

GUIDE = Path(talk.__file__).resolve().parent


def test_a_cell_word_longer_than_the_floor_the_stage_gives_a_column_is_named():
    body = "| Part | Where |\n|---|---|\n| config | /etc/nginx/conf.d/default.conf.template.backup |\n| log | ok |"
    _, notes = talk.check_table("Files", body)
    assert notes == ['table "Files" has a word of 46 characters ("/etc/nginx/conf.d/default.conf…") that cannot wrap: '
                     "the stage scrolls the table sideways, or on a phone shows each row as a card; use a shorter word"]


def test_words_up_to_the_floor_are_not_reported():
    body = "| Part | Where |\n|---|---|\n| " + "x" * talk.TABLE_WORD_MAX + " | ok |"
    assert talk.check_table("Files", body)[1] == []


def test_the_guide_gives_a_user_who_names_a_table_the_rows_and_columns_they_named():
    skill = (GUIDE / "SKILL.md").read_text()
    boards = (GUIDE / "references" / "boards.md").read_text()
    assert "**A user who asks for a table gets a table:** every row and column they named, up to 8 rows by 6 columns" in skill
    assert (talk.MAX_TABLE_ROWS, talk.MAX_TABLE_COLUMNS) == (8, 6)   # what the guide promises is what the server reads
    assert "the 4 by 4 limit" in boards and "A table the user asked for is drawn as asked" in boards
    assert "You cannot see how the stage draws a board" in skill and "never send the same board again" in skill
