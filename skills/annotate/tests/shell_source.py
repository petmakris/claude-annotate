"""The page shell's markup, as HTML, for tests to assert against.

shell.js exports SHELL_HTML as a JavaScript string literal, so a raw read of
the file hands a test the literal's *source* — escapes, quotes, continuations
and all — and every markup assertion then fails on the encoding rather than on
the thing it is checking. Eleven test modules each carried their own copy of a
regex to undo that, which meant the encoding was hardcoded in eleven places.

It changed once (a one-line JSON string became a line-continued template
literal, so the markup could be read and merged) and that is eleven edits for
one change. Hence one decoder, here.
"""
import re
from pathlib import Path

SHELL_JS = Path(__file__).resolve().parents[1] / "static" / "shell.js"


def shell_html(path: Path = SHELL_JS) -> str:
    """SHELL_HTML's VALUE — the markup the page actually mounts."""
    src = path.read_text()

    # Template literal, line-continued: every source line ends with a
    # backslash, so removing "\<newline>" reconstructs the exact string.
    m = re.search(r"export const SHELL_HTML = `(.*?)`;", src, re.S)
    if m:
        return re.sub(r"\\\n", "", m.group(1))

    # The older JSON-string form. Kept so this helper can read a shell.js from
    # before the change — a bisect, a stash, an older worktree — rather than
    # returning something that looks like markup and is not.
    m = re.search(r'export const SHELL_HTML = ("(?:[^"\\]|\\.)*");', src, re.S)
    if m:
        import json
        return json.loads(m.group(1))

    raise AssertionError(
        f"{path} exports SHELL_HTML in a form this helper does not know how to "
        f"read. Teach it here rather than in the test that hit it.")
