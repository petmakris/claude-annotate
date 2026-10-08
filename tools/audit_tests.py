#!/usr/bin/env python3
"""Do the tests keep up with the code? Two checks, run by /audit-tests.

    python3 tools/audit_tests.py changed [--base REV] [--max 30] [--seed N] [--out DIR]
    python3 tools/audit_tests.py redundant [PATH ...] [--out DIR]

`changed` plants one small bug at a time in the lines changed since REV (default: the commit in
.claude/skills/audit-tests/last-audit) and runs the tests of that skill against it. A bug no test
fails on ("survived") is a change that landed without a test that guards it.

`redundant` records which tests run which Python lines and lists the
tests whose lines another test in the same file runs exactly as well, and the tests that run no
product code at all. These are candidates to read, not to delete blind: two tests can run the same
lines with different inputs.

Both work in a throwaway git worktree of HEAD, so they audit the committed tree and never touch
the checkout they are started from. Bytecode caching is off: a bug restored within the same second
at the same file size would otherwise run again from Python's cache.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           check=True).stdout.strip())
MARKER = ROOT / ".claude" / "skills" / "audit-tests" / "last-audit"
PYTEST = ["uv", "run", "-q", "--with-requirements", "requirements-test.txt", "python", "-m", "pytest",
          "-q", "-p", "no:cacheprovider"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
ALSO_TESTED_BY = {"_shared": ["skills"]}


# ---- the worktree ----------------------------------------------------------------------------

@contextlib.contextmanager
def worktree():
    where = Path(tempfile.mkdtemp(prefix="audit-tests-")) / "tree"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(where), "HEAD"], cwd=ROOT, check=True)
    try:
        yield where
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(where)], cwd=ROOT, check=False)


def run_tests(tree: Path, dirs: list[str], first_failure: bool = True) -> tuple[str, list[str], str]:
    """('pass' | 'fail' | 'none', failed test ids, last line)."""
    cmd = PYTEST + dirs + ["-rf"] + (["-x"] if first_failure else [])
    r = subprocess.run(cmd, cwd=tree, env=ENV, capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    failed = sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)))
    last = (out.strip().splitlines() or [""])[-1]
    status = "none" if r.returncode == 5 else "pass" if r.returncode == 0 else "fail"
    return status, failed, last


# ---- what changed ----------------------------------------------------------------------------

def is_product(path: str) -> bool:
    p = Path(path)
    return (path.startswith("skills/") and p.suffix in (".py", ".js") and "tests" not in p.parts
            and not p.name.startswith("test_") and p.name != "conftest.py" and not p.name.endswith(".min.js")
            and "vendor" not in p.parts)


def changed_lines(base: str) -> dict[str, set[int]]:
    names = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AM", base, "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    out: dict[str, set[int]] = {}
    for name in filter(is_product, names):
        diff = subprocess.run(["git", "diff", "-U0", base, "HEAD", "--", name], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout
        lines = set()
        for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
            start, n = int(m[1]), int(m[2] if m[2] is not None else 1)
            lines.update(range(start, start + n))
        if lines:
            out[name] = lines
    return out


def at_head(path: str) -> str:
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def tests_for(path: str) -> list[str]:
    skill = Path(path).parts[1]
    dirs = [f"skills/{skill}/tests"] + ALSO_TESTED_BY.get(skill, [])
    return [d for d in dict.fromkeys(dirs) if (ROOT / d).is_dir() or d == "skills"]


# ---- Python mutants (from the AST) -----------------------------------------------------------

FLIP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
QUIET = ("say", "print", "print_exc", "warn", "debug", "info")


def python_mutants(path: str, src: str, wanted: set[int]) -> list[dict]:
    tree, out = ast.parse(src), []
    starts = [0]
    for line in src.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    lines = src.splitlines()

    def at(node, end=False):
        line, col = (node.end_lineno, node.end_col_offset) if end else (node.lineno, node.col_offset)
        return starts[line - 1] + len(lines[line - 1].encode()[:col].decode())

    def add(node, kind, a, b, new):
        if node.lineno in wanted and src[a:b] != new:
            out.append({"file": path, "line": node.lineno, "kind": kind, "a": a, "b": b, "old": src[a:b], "new": new})

    def callee(call):
        return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")

    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or any(f"{q}(" in lines[node.lineno - 1] for q in QUIET):
            continue
        if isinstance(node, ast.Compare) and type(node.ops[0]) in FLIP:
            m = ast.Compare(left=node.left, ops=[FLIP[type(node.ops[0])]()] + node.ops[1:], comparators=node.comparators)
            add(node, "flip comparison", at(node), at(node, True), "(" + ast.unparse(m) + ")")
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            a, b = at(node.test), at(node.test, True)
            add(node, "negate condition", a, b, f"(not ({src[a:b]}))")
        elif isinstance(node, ast.BoolOp):
            m = ast.BoolOp(op=ast.Or() if isinstance(node.op, ast.And) else ast.And(), values=node.values)
            add(node, "and/or", at(node), at(node, True), "(" + ast.unparse(m) + ")")
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            add(node, "flip boolean", at(node), at(node, True), str(not node.value))
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value not in (0, 1):
            add(node, "constant + 1", at(node), at(node, True), repr(node.value + 1))
        elif isinstance(node, ast.Expr):
            v = node.value.value if isinstance(node.value, ast.Await) else node.value
            if isinstance(v, ast.Call) and callee(v) not in QUIET:
                add(node, "delete call", at(node), at(node, True), "pass")
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            add(node, "return None", at(node), at(node, True), "return None")
    return [m for m in out if compiles(src[:m["a"]] + m["new"] + src[m["b"]:], path)]


def compiles(src: str, path: str) -> bool:
    try:
        compile(src, path, "exec")
        return True
    except SyntaxError:
        return False


# ---- JavaScript mutants (line by line, on a copy with strings and comments blanked) --------

def mask(line: str) -> str:
    out, i, q = [], 0, None
    while i < len(line):
        c = line[i]
        if q:
            if c == "\\":
                out.append("__"); i += 2; continue
            out.append(q if c == q else "_")
            if c == q:
                q = None
        elif c in "\"'`":
            q = c; out.append(c)
        elif line.startswith("//", i):
            out.append("_" * (len(line) - i)); break
        elif c == "/" and re.search(r"[(,=!&|?:;{]\s*$", line[:i]) and not line.startswith("/*", i):
            j = line.find("/", i + 1)  # a regex literal
            while j > 0 and line[j - 1] == "\\":
                j = line.find("/", j + 1)
            if j < 0:
                out.append(c); i += 1; continue
            out.append("_" * (j - i + 1)); i = j + 1; continue
        else:
            out.append(c)
        i += 1
    return "".join(out)[:len(line)]


SWAPS = [(r"(?<![=!<>])===(?!=)", "!==", "=== to !=="), (r"!==", "===", "!== to ==="),
         (r"(?<![=<>!])<=", "<", "<= to <"), (r"(?<![=<>!])<(?![=<])", "<=", "< to <="),
         (r"(?<![=<>!])>=", ">", ">= to >"), (r"(?<![=>\-<!])>(?![=>])", ">=", "> to >="),
         (r"&&", "||", "&& to ||"), (r"\|\|", "&&", "|| to &&"),
         (r"\btrue\b", "false", "true to false"), (r"\bfalse\b", "true", "false to true")]


def js_mutants(path: str, src: str, wanted: set[int]) -> list[dict]:
    lines, out = src.split("\n"), []
    module = bool(re.search(r"^(import|export)\b", src, re.M))
    for no in sorted(wanted):
        if no > len(lines):
            continue
        raw = lines[no - 1]
        m = mask(raw)
        if not raw.strip() or raw.strip().startswith(("//", "/*", "*")) or "style.setProperty" in raw:
            continue
        found = []
        for pat, rep, kind in SWAPS:
            for hit in re.finditer(pat, m):
                if kind.startswith(">") and m[hit.start() - 1:hit.start()] == "=":
                    continue  # an arrow =>
                found.append((kind, raw[:hit.start()] + rep + raw[hit.end():]))
        for hit in re.finditer(r"\bif \(", m):
            depth, j = 0, hit.end() - 1
            for j in range(hit.end() - 1, len(m)):
                depth += m[j] == "("; depth -= m[j] == ")"
                if depth == 0:
                    break
            if depth == 0:
                found.append(("negate condition", raw[:hit.end()] + "!(" + raw[hit.end():j] + ")" + raw[j:]))
        if re.fullmatch(r"\s*[\w.$]+(\([^;]*\))+;\s*", m) and not re.match(r"\s*(const|let|var|return)\b", m):
            found.append(("delete call", re.match(r"\s*", raw).group() + "/* deleted */"))
        for hit in re.finditer(r"\breturn ([^;]+);", m):
            found.append(("return nothing", raw[:hit.start()] + "return;" + raw[hit.end():]))
        for kind, new in found:
            out.append({"file": path, "line": no, "kind": kind, "old": raw, "new": new, "module": module})
    return out


def js_parses(src: str, module: bool) -> bool:
    cmd = ["node", "--input-type=module", "--check"] if module else ["node", "--check", "-"]
    return subprocess.run(cmd, input=src, text=True, capture_output=True).returncode == 0


def mutated(src: str, m: dict) -> str:
    if "a" in m:
        return src[:m["a"]] + m["new"] + src[m["b"]:]
    lines = src.split("\n")
    lines[m["line"] - 1] = m["new"]
    return "\n".join(lines)


# ---- changed ---------------------------------------------------------------------------------

def sample(found: dict[str, list[dict]], most: int, seed: int) -> list[dict]:
    """Round-robin over the files, one bug per line, so a big file does not take every slot."""
    rng = random.Random(seed)
    pools = {f: rng.sample(ms, len(ms)) for f, ms in found.items() if ms}
    picked, used = [], set()
    while len(picked) < most and any(pools.values()):
        for f in list(pools):
            while pools[f]:
                m = pools[f].pop()
                if (m["file"], m["line"]) in used:
                    continue
                if "module" in m and not js_parses(mutated(at_head(f), m), m["module"]):
                    continue
                used.add((m["file"], m["line"])); picked.append(m)
                break
            if len(picked) >= most:
                break
    return sorted(picked, key=lambda m: (m["file"], m["line"]))


def changed(args) -> int:
    base = args.base or (MARKER.read_text().strip() if MARKER.is_file() else "HEAD~20")
    base_sha = subprocess.run(["git", "rev-parse", "--short", base], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    lines = changed_lines(base)
    found = {}
    for path, wanted in lines.items():
        src = at_head(path)
        found[path] = (python_mutants if path.endswith(".py") else js_mutants)(path, src, wanted)
    picked = sample(found, args.max, args.seed)
    out = Path(args.out or tempfile.mkdtemp(prefix="audit-tests-out-"))
    out.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"base {base_sha}, HEAD {head}: {sum(len(v) for v in lines.values())} changed product lines in "
          f"{len(lines)} files, {sum(len(v) for v in found.values())} possible bugs, {len(picked)} sampled", flush=True)
    if not picked:
        (out / "changed.json").write_text(json.dumps({"base": base_sha, "head": head, "results": []}, indent=1))
        print(f"nothing to plant. results: {out / 'changed.json'}")
        return 0
    results = []
    with worktree() as tree:
        # Every set of tests a bug may meet must pass untouched first, or a failure would prove nothing.
        for dirs in sorted({tuple(tests_for(m["file"])) for m in picked}):
            status, failed, last = run_tests(tree, list(dirs), first_failure=False)
            print(f"baseline {' '.join(dirs)}: {last}", flush=True)
            if status == "fail":
                print(f"the tests fail before any bug is planted: {failed[:5]}. Fix them first.", file=sys.stderr)
                return 2
        for i, m in enumerate(picked, 1):
            f = tree / m["file"]
            orig = f.read_text()
            f.write_text(mutated(orig, m))
            t0, verdict, by = time.time(), "survived", []
            try:
                status, failed, last = run_tests(tree, tests_for(m["file"]))
                if status == "fail":
                    verdict, by = "killed", failed[:3] or [last]
            finally:
                f.write_text(orig)
            row = {"id": i, **{k: m[k] for k in ("file", "line", "kind", "old", "new")}, "status": verdict,
                   "by": by, "secs": round(time.time() - t0)}
            results.append(row)
            print(f"{i:>3} {verdict:8} {row['secs']:>4}s {m['file']}:{m['line']} {m['kind']}"
                  + (f"  <- {by[0]}" if by else ""), flush=True)
    (out / "changed.json").write_text(json.dumps({"base": base_sha, "head": head, "results": results}, indent=1))
    survived = [r for r in results if r["status"] == "survived"]
    print(f"\n{len(results) - len(survived)} of {len(results)} planted bugs killed. results: {out / 'changed.json'}")
    for r in survived:
        print(f"\nsurvived #{r['id']} {r['file']}:{r['line']} ({r['kind']})\n  - {r['old'].strip()}\n  + {r['new'].strip()}")
    return 0


# ---- redundant -------------------------------------------------------------------------------

def redundant(args) -> int:
    out = Path(args.out or tempfile.mkdtemp(prefix="audit-tests-out-"))
    out.mkdir(parents=True, exist_ok=True)
    paths = args.paths or ["skills"]
    with worktree() as tree:
        env = {**ENV, "COVERAGE_FILE": str(out / ".coverage")}
        cmd = ["uv", "run", "-q", "--with-requirements", "requirements-test.txt", "--with", "pytest-cov",
               "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths,
               "--cov=skills", "--cov-context=test", "--cov-report="]
        r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=3600)
        print((r.stdout.strip().splitlines() or [""])[-1], flush=True)
        if r.returncode not in (0,):
            print(r.stdout[-3000:], file=sys.stderr)
            return 2
        analyse = ["uv", "run", "-q", "--with", "coverage", "python", str(Path(__file__).resolve()), "_analyse",
                   str(out / ".coverage"), str(tree), str(out / "redundant.json")]
        return subprocess.run(analyse, cwd=tree, env=env).returncode


def _analyse(cov_file: str, tree: str, dest: str) -> int:
    import coverage  # only here: run under `uv run --with coverage`

    data = coverage.CoverageData(basename=cov_file)
    data.read()
    tree_root = str(Path(tree).resolve())
    runs: dict[str, set] = {}
    for measured in data.measured_files():
        rel = os.path.relpath(measured, tree_root)
        if not is_product(rel):
            continue
        for line, contexts in (data.contexts_by_lineno(measured) or {}).items():
            for ctx in contexts:
                if ctx.endswith("|run"):
                    runs.setdefault(ctx[:-4], set()).add((rel, line))
    for ctx in data.measured_contexts():
        if ctx.endswith("|run"):
            runs.setdefault(ctx[:-4], set())
    by_file: dict[str, dict[str, frozenset]] = {}
    for test, lines in runs.items():
        by_file.setdefault(test.split("::")[0], {})[test] = frozenset(lines)
    same, idle = [], []
    for f, tests in sorted(by_file.items()):
        groups: dict[frozenset, list[str]] = {}
        for test, lines in tests.items():
            if lines:
                groups.setdefault(lines, []).append(test)
            else:
                idle.append(test)
        same += [{"file": f, "tests": sorted(t), "lines": len(k)} for k, t in groups.items() if len(t) > 1]
    report = {"tests": len(runs), "same_lines": same, "no_product_code": sorted(idle)}
    Path(dest).write_text(json.dumps(report, indent=1))
    print(f"{len(runs)} tests measured. {len(same)} groups of tests in one file that run exactly the same lines "
          f"({sum(len(g['tests']) for g in same)} tests); {len(idle)} tests run no product code. results: {dest}")
    for g in same:
        print(f"\nsame {g['lines']} lines: " + "\n  ".join([""] + [t.split("::", 1)[1] for t in g["tests"]]).rstrip()
              + f"\n  ({g['file']})")
    if idle:
        print("\nno product code:\n  " + "\n  ".join(idle))
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "_analyse":
        return _analyse(*sys.argv[2:5])
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("changed", help="plant bugs in the lines changed since a commit")
    c.add_argument("--base", help="the commit to diff from (default: the last audit, else HEAD~20)")
    c.add_argument("--max", type=int, default=30, help="how many bugs to plant (default 30)")
    c.add_argument("--seed", type=int, default=20261007)
    c.add_argument("--out", help="where to write changed.json (default: a new temporary folder)")
    r = sub.add_parser("redundant", help="tests that run exactly the same lines as another, or none")
    r.add_argument("paths", nargs="*", help="test folders (default: skills)")
    r.add_argument("--out", help="where to write redundant.json (default: a new temporary folder)")
    args = parser.parse_args()
    return changed(args) if args.cmd == "changed" else redundant(args)


if __name__ == "__main__":
    sys.exit(main())
