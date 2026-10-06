"""talk and stage ship in a public plugin: no file may lean on one person's machines or tools."""
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
FORBIDDEN = re.compile(r"@devdomains|@secrets|petros-|evooq|wealth|montblanc", re.IGNORECASE)


def test_no_file_names_a_private_tool_machine_or_employer():
    hits = []
    for folder in ("talk", "stage"):
        for path in sorted((SKILLS / folder).rglob("*")):
            if not path.is_file() or "vendor" in path.parts or "__pycache__" in path.parts or path.name == "test_public.py":
                continue
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(SKILLS)}:{n}: {line.strip()[:100]}")
    assert not hits, "\n".join(hits)
