"""Print answer N (0-based) of skills/talk/demo.md from a checkout: demo_answer.py <repo> <n>, or --list."""
import re, sys
from pathlib import Path
repo, n = Path(sys.argv[1]), sys.argv[2]
raw = (repo / "skills/talk/demo.md").read_text()
raw = re.sub(r"\A<!--.*?-->\s*", "", raw, flags=re.S)
parts = [p.strip() for p in re.split(r"(?m)^---\s*$", raw) if p.strip()]
if n == "--list":
    for i, p in enumerate(parts):
        m = re.search(r"\[\[show (\w+)", p)
        print(i, m.group(1) if m else "-", len(p.split()), "words")
else:
    print(parts[int(n)])
