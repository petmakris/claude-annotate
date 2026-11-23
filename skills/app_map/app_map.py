"""/app-map: facts about a repository, a check of Claude's source.json, and the build of map.json.

    claude-annotate app_map.app_map facts <repo>
    claude-annotate app_map.app_map check <name> [--repo DIR]
    claude-annotate app_map.app_map build <name> [--repo DIR]

Files live in $APP_MAP_HOME/<name>/ (default ~/.config/claude-annotate/app-map/<name>/): source.json, written by
Claude and the user, and map.json, written here and read by the IntelliJ plugin, with top.svg and <part>.svg beside
it for tools/vz_check.py. `check` and `build` print one JSON report; a failure to start prints one line on stderr
and exits 2, a map that does not pass exits 1."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skills._shared.visuals import map_svg

from . import convert, facts, paths

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
FORMAT_VERSION = 1


class Fail(Exception):
    """Something that stops the command before any check: printed as one line, exit 2."""


def home() -> Path:
    env = os.environ.get("APP_MAP_HOME")
    return Path(env) if env else Path.home() / ".config" / "claude-annotate" / "app-map"


def folder(name: str) -> Path:
    if not ID.fullmatch(name or ""):
        raise Fail(f"{name!r} is not a map name: letters, digits, '.', '_' and '-', starting with a letter or digit")
    return home() / name


def load_source(name: str) -> dict:
    f = folder(name) / "source.json"
    if not f.is_file():
        raise Fail(f"no {f}: write the map's source.json first")
    try:
        src = json.loads(f.read_text())
    except ValueError as e:
        raise Fail(f"{f} is not valid JSON: {e}")
    if not isinstance(src, dict):
        raise Fail(f"{f} must hold a JSON object")
    return src


def find_repo(src: dict, flag: Optional[str]) -> Path:
    if flag:
        p = Path(flag).expanduser()
        if not p.is_dir():
            raise Fail(f"--repo {flag} is not a folder")
        return p
    for f in (src.get("match") or {}).get("folders") or []:
        if Path(f).expanduser().is_dir():
            return Path(f).expanduser()
    raise Fail("no repo: pass --repo DIR, or list an existing folder in source.json match.folders")


def extra_repos(src: dict) -> List[dict]:
    """The other repos a map spans: `repos` in source.json, each {name, remote, folders}."""
    return [r for r in src.get("repos") or [] if isinstance(r, dict)]


def repo_folder(r: dict) -> Optional[Path]:
    for f in r.get("folders") or []:
        if Path(f).expanduser().is_dir():
            return Path(f).expanduser()
    return None


def scoped(src: dict, repo: Optional[str]) -> dict:
    """The parts (and their detail maps) that belong to one repo: `repo` None is the map's own repo."""
    parts = [p for p in src.get("parts") or [] if p.get("repo") == repo]
    ids = {p.get("id") for p in parts}
    details = {k: d for k, d in (src.get("details") or {}).items() if k in ids}
    return {"parts": parts, "details": details}


def checkouts(src: dict, repo: Path) -> List[Tuple[Optional[str], Path]]:
    """Every checkout the map reads: its own repo first, then each extra repo that has a folder here."""
    out: List[Tuple[Optional[str], Path]] = [(None, repo)]
    for r in extra_repos(src):
        f = repo_folder(r)
        if f is not None:
            out.append((r.get("name"), f))
    return out


# ---------------------------------------------------------------- matching

def box_ids(spec: dict) -> List[str]:
    out: List[str] = []

    def walk(b: dict) -> None:
        out.append(b.get("id"))
        for c in b.get("children") or []:
            walk(c)

    for b in (spec or {}).get("boxes") or []:
        walk(b)
    return [i for i in out if isinstance(i, str)]


def part_of(parts: List[dict], path: str) -> Optional[str]:
    """The last part with a pattern that matches the file."""
    for p in reversed(parts):
        if any(paths.matches(pat, path) for pat in p.get("paths") or []):
            return p["id"]
    return None


def assign(files: List[str], src: dict) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    details = src.get("details") or {}
    out = {}
    for f in files:
        top = part_of(src.get("parts") or [], f)
        sub = part_of((details.get(top) or {}).get("parts") or [], f) if top in details else None
        out[f] = (top, sub)
    return out


# ---------------------------------------------------------------- check

def check_report(name: str, src: dict, repo: Path) -> dict:
    errors: List[str] = []
    parts = src.get("parts") or []
    details = src.get("details") or {}
    top_ids = [p.get("id") for p in parts]
    all_ids: List[str] = list(top_ids)
    for d in details.values():
        all_ids += [p.get("id") for p in (d.get("parts") or [])]
    dups = sorted({i for i in all_ids if all_ids.count(i) > 1})
    bad = [i for i in all_ids if not isinstance(i, str) or not ID.fullmatch(i)]
    if bad:
        errors.append(f"part ids must be letters, digits, '.', '_' and '-': {bad}")
    if dups:
        errors.append(f"part ids used more than once across the maps: {dups}")
    orphan_details = sorted(d for d in details if d not in top_ids)
    if orphan_details:
        errors.append(f"details for ids that are no top-level part: {orphan_details}")
    if "top" in details:
        errors.append("a detail cannot be called 'top'")
    teams = src.get("teams")
    if teams is not None and (not isinstance(teams, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in teams.items())):
        errors.append("teams maps a CODEOWNERS team to its short label, both text")

    map_errors: List[str] = []
    maps = [("top", src.get("map"), parts)] + [(k, d.get("map"), d.get("parts") or []) for k, d in details.items()]
    parts_without_box: List[str] = []
    boxes_without_part: List[str] = []
    for label, spec, ps in maps:
        try:
            map_svg.validate(spec)
        except map_svg.ValidationError as e:
            map_errors.append(f"{label}: {e}")
            continue
        boxes = box_ids(spec)
        parts_without_box += [p["id"] for p in ps if p.get("id") not in boxes]
        boxes_without_part += [b for b in boxes if b not in [p.get("id") for p in ps]]
    if parts_without_box:
        errors.append(f"parts with no box in their map: {parts_without_box}")
    errors += map_errors

    names = [r.get("name") for r in extra_repos(src)]
    bad_repos = [n for n in names if not isinstance(n, str) or not ID.fullmatch(n)]
    if bad_repos:
        errors.append(f"repos need a name of letters, digits, '.', '_' and '-': {bad_repos}")
    missing = [r.get("name") for r in extra_repos(src) if repo_folder(r) is None]
    if missing:
        errors.append(f"repos with no existing folder on this machine: {missing}")
    unknown = sorted({p.get("repo") for p in parts if p.get("repo") is not None and p.get("repo") not in names})
    if unknown:
        errors.append(f"parts name repos that are not in repos: {unknown}")

    files: List[str] = []
    placed: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for name_, path in checkouts(src, repo):
        fs = facts.tracked_files(path)
        prefix = "" if name_ is None else f"{name_}:"
        files += [prefix + f for f in fs]
        for f, where in assign(fs, scoped(src, name_)).items():
            placed[prefix + f] = where
    counts = {p["id"]: 0 for p in parts}
    sub_counts: Dict[str, Dict[str, int]] = {k: {p["id"]: 0 for p in d.get("parts") or []} for k, d in details.items()}
    unmapped: Dict[str, int] = {}
    n_unmapped = 0
    for f, (top, sub) in placed.items():
        if top is None:
            n_unmapped += 1
            d = "/".join(f.split("/")[:-1][:2]) or (f.split(":")[0] + ":." if ":" in f else ".")
            unmapped[d] = unmapped.get(d, 0) + 1
            continue
        counts[top] += 1
        if sub is not None:
            sub_counts[top][sub] += 1
    biggest = sorted(unmapped.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    empty = [i for i, n in counts.items() if n == 0]
    for k, c in sub_counts.items():
        empty += [i for i, n in c.items() if n == 0]
    return {
        "ok": not errors, "name": name, "repo": str(repo), "total": len(files),
        "unmapped": {"count": n_unmapped, "folders": [{"folder": d, "files": n} for d, n in biggest]},
        "parts": counts, "details": sub_counts, "empty_parts": empty,
        "boxes_without_part": boxes_without_part, "parts_without_box": parts_without_box,
        "duplicate_part_ids": dups, "details_without_part": orphan_details, "map_errors": map_errors,
        "errors": errors,
    }


# ---------------------------------------------------------------- build

def owner_counts(src: dict, repo: Path) -> Dict[str, List[dict]]:
    """Files per CODEOWNERS team for every part, each repo's parts counted with that repo's own CODEOWNERS."""
    ids = [p["id"] for p in src.get("parts") or []]
    for d in (src.get("details") or {}).values():
        ids += [p["id"] for p in d.get("parts") or []]
    tally: Dict[str, Dict[Optional[str], int]] = {i: {} for i in ids}
    for name_, path in checkouts(src, repo):
        rules = (facts.codeowners(path) or {}).get("rules") or []
        patterns = [r["pattern"] for r in rules]
        for f, (top, sub) in assign(facts.tracked_files(path), scoped(src, name_)).items():
            i = paths.last_match(patterns, f)
            team = (rules[i]["owners"][0] if rules[i]["owners"] else None) if i is not None else None
            for pid in (top, sub):
                if pid is not None:
                    tally[pid][team] = tally[pid].get(team, 0) + 1
    return {pid: [{"team": t, "files": n} for t, n in
                  sorted(c.items(), key=lambda kv: (-kv[1], kv[0] is None, kv[0] or ""))]
            for pid, c in tally.items()}


def head_commit(repo: Path) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, check=True, text=True)
        return r.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


PILL_ROW = "\u00a0"  # a blank line the build adds at the foot of each part's box: the plugin draws its team pills there


def with_pill_rows(spec: dict, part_ids: set) -> dict:
    """A copy of a map spec where every box that is a part ends with a blank line, so its team pills get their own row."""
    out = json.loads(json.dumps(spec))
    def walk(box):
        if box.get("id") in part_ids:
            box["lines"] = list(box.get("lines") or []) + [PILL_ROW]
        for ch in box.get("children") or []:
            walk(ch)
    for b in out.get("boxes") or []:
        walk(b)
    return out


def build(name: str, src: dict, repo: Path) -> dict:
    report = check_report(name, src, repo)
    if not report["ok"]:
        return report
    details = src.get("details") or {}
    top_parts = {p["id"] for p in src.get("parts") or []}
    drawings, svgs = {}, {"top": map_svg.render(with_pill_rows(src["map"], top_parts), "top", keyed=True)}
    for i, (pid, d) in enumerate(details.items()):
        svgs[pid] = map_svg.render(with_pill_rows(d["map"], {p["id"] for p in d.get("parts") or []}), f"d{i}", keyed=True)
    for key, svg in svgs.items():
        drawings[key] = convert.svg_to_drawing(svg)
    match = src.get("match") or {}
    remotes = list(match.get("remotes") or [])
    folders = list(match.get("folders") or [])
    for r in extra_repos(src):
        if r.get("remote") and r["remote"] not in remotes:
            remotes.append(r["remote"])
        folders += [f for f in r.get("folders") or [] if f not in folders]

    def part(p: dict) -> dict:
        out = {"id": p["id"], "paths": p.get("paths") or []}
        if p.get("repo") is not None:
            out["repo"] = p["repo"]
        return out

    out = {
        "version": FORMAT_VERSION,
        "name": src.get("name") or name,
        "match": {"remotes": remotes, "folders": folders},
        "repos": {r["name"]: r.get("remote") or "" for r in extra_repos(src)},
        "built": {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": head_commit(repo)},
        "parts": [part(p) for p in src.get("parts") or []],
        "details": {k: {"parts": [part(p) for p in d.get("parts") or []]} for k, d in details.items()},
        "owners": owner_counts(src, repo),
        "teams": dict(src.get("teams") or {}),
        "modules": [{"name": m["name"], "dir": m["dir"], "repo": n}
                    for n, path in checkouts(src, repo) for m in facts.gather(path)["modules"]],
        "drawings": drawings,
    }
    dest = folder(name)
    written = []
    for key, svg in svgs.items():
        write_atomic(dest / f"{key}.svg", svg)
        written.append(f"{key}.svg")
    write_atomic(dest / "map.json", json.dumps(out, indent=1))
    written.append("map.json")
    report["written"] = written
    return report


# ---------------------------------------------------------------- command line

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="app_map", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts")
    f.add_argument("repo")
    for c in ("check", "build"):
        s = sub.add_parser(c)
        s.add_argument("name")
        s.add_argument("--repo")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "facts":
            p = Path(a.repo).expanduser()
            if not p.is_dir():
                raise Fail(f"{a.repo} is not a folder")
            print(json.dumps(facts.gather(p), indent=1))
            return 0
        src = load_source(a.name)
        repo = find_repo(src, a.repo)
        report = check_report(a.name, src, repo) if a.cmd == "check" else build(a.name, src, repo)
        print(json.dumps(report, indent=1))
        return 0 if report["ok"] else 1
    except Fail as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
