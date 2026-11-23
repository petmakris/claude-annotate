"""Facts about a repository, for Claude to design its map from: build modules and the dependencies between
them, file counts, and the CODEOWNERS rules. Read only; stdlib only."""
from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

CODEOWNERS_PLACES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
SOURCE_ROOT = re.compile(r"(?:^|/)src/[^/]+/(?:java|kotlin|scala|groovy)/(.*)$")


def tracked_files(repo: Path) -> List[str]:
    """What `git ls-files` lists (untracked and ignored files never count); a folder with no git is walked."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True)
        return sorted(f for f in r.stdout.decode("utf-8", "replace").split("\0") if f and (repo / f).exists())
    except (OSError, subprocess.CalledProcessError):
        out = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d != ".git"]
            out += [os.path.relpath(os.path.join(root, f), repo) for f in files]
        return sorted(out)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- gradle

def _gradle_settings(repo: Path) -> Optional[str]:
    for n in ("settings.gradle", "settings.gradle.kts"):
        if (repo / n).is_file():
            return _read(repo / n)
    return None


def _gradle_modules(text: str) -> List[str]:
    names: List[str] = []
    for m in re.finditer(r"^\s*include\b\s*\(?([^\n]*(?:,\s*\n[^\n]*)*)", text, re.M):
        for q in re.findall(r"""["']:?([^"']+)["']""", m.group(1)):
            if q not in names:
                names.append(q)
    return names


def _norm(s: str) -> str:
    return re.sub(r"[-_:.]", "", s).lower()


def _is_test(config: str) -> bool:
    return config.startswith("test") or "Test" in config or "testFixtures" in config


def _gradle_edges(repo: Path, mods: Dict[str, str]) -> List[dict]:
    by_norm = {_norm(n): n for n in mods}
    edges: List[dict] = []
    seen = set()
    for user, d in mods.items():
        for bn in ("build.gradle", "build.gradle.kts"):
            f = repo / d / bn
            if not f.is_file():
                continue
            text = _read(f)
            found = [(m.group(1), m.group(2)) for m in re.finditer(
                r"""(\w+)\s*\(?\s*project\(\s*(?:path\s*[:=]\s*)?["']:?([^"']+)["']""", text)]
            found += [(m.group(1), m.group(2)) for m in re.finditer(
                r"(\w+)\s*\(?\s*projects\.([A-Za-z0-9_.]+)", text)]
            for config, ref in found:
                prov = mods.get(ref) and ref or by_norm.get(_norm(ref))
                if prov is None or prov == user:
                    continue
                k = (prov, user, config)
                if k not in seen:
                    seen.add(k)
                    edges.append({"from": prov, "to": user, "config": config, "test": _is_test(config)})
    return edges


# ---------------------------------------------------------------- maven

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el, name: str) -> str:
    c = _child(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None else ""


def _pom(path: Path):
    try:
        return ET.fromstring(_read(path))
    except ET.ParseError:
        return None


def _maven_modules(repo: Path):
    """[(artifactId, dir, groupId, pom)] for every module reachable from the root pom."""
    root = _pom(repo / "pom.xml")
    if root is None:
        return []
    out = []

    def walk(rel: str, pom, inherited_group: str):
        group = _text(pom, "groupId") or _text(_child(pom, "parent"), "groupId") or inherited_group
        out.append((_text(pom, "artifactId") or (rel or repo.name), rel, group, pom))
        mods = _child(pom, "modules")
        for m in (list(mods) if mods is not None else []):
            sub = (rel + "/" if rel else "") + (m.text or "").strip()
            p = _pom(repo / sub / "pom.xml")
            if p is not None:
                walk(sub, p, group)

    walk("", root, "")
    return [m for m in out if m[1] != "" or _text(m[3], "packaging") != "pom"] or out


def _maven_edges(mods) -> List[dict]:
    by_ga = {(g, a): a for a, _d, g, _p in mods}
    edges, seen = [], set()
    for art, _d, _g, pom in mods:
        deps = _child(pom, "dependencies")
        for dep in (list(deps) if deps is not None else []):
            ga = (_text(dep, "groupId"), _text(dep, "artifactId"))
            prov = by_ga.get(ga)
            if prov is None or prov == art:
                continue
            scope = _text(dep, "scope") or "compile"
            k = (prov, art, scope)
            if k not in seen:
                seen.add(k)
                edges.append({"from": prov, "to": art, "config": scope, "test": scope == "test"})
    return edges


# ---------------------------------------------------------------- counting

def _packages(files: List[str], moddir: str) -> Dict[str, int]:
    """Source folders of a module, cut under the prefix every one of them shares, plus one more folder."""
    dirs = []
    for f in files:
        rel = f[len(moddir) + 1:] if moddir else f
        m = SOURCE_ROOT.search(rel)
        if m and "/" in m.group(1):
            dirs.append(m.group(1).rsplit("/", 1)[0].split("/"))
    if not dirs:
        return {}
    prefix = list(dirs[0])
    for d in dirs[1:]:
        n = 0
        while n < min(len(prefix), len(d)) and prefix[n] == d[n]:
            n += 1
        prefix = prefix[:n]
    counts: Dict[str, int] = {}
    for d in dirs:
        key = "/".join(d[:len(prefix) + 1])
        counts[key] = counts.get(key, 0) + 1
    return counts


def _count(files: List[str], dirs: Dict[str, str]) -> List[dict]:
    """Each file belongs to the module with the longest dir that holds it."""
    owned: Dict[str, List[str]] = {n: [] for n in dirs}
    order = sorted(dirs.items(), key=lambda kv: -len(kv[1]))
    for f in files:
        for n, d in order:
            if d == "" or f.startswith(d + "/"):
                owned[n].append(f)
                break
    return [{"name": n, "dir": dirs[n], "files": len(owned[n]), "packages": _packages(owned[n], dirs[n])}
            for n in dirs]


# ---------------------------------------------------------------- codeowners

def codeowners(repo: Path) -> Optional[dict]:
    for rel in CODEOWNERS_PLACES:
        if (repo / rel).is_file():
            break
    else:
        return None
    rules, teams, skipped = [], set(), 0
    for line in _read(repo / rel).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") or line.startswith("^["):
            skipped += 1
            continue
        parts = re.split(r"\s+#", line)[0].split()
        rules.append({"pattern": parts[0], "owners": parts[1:]})
        teams.update(parts[1:])
    return {"file": rel, "rules": rules, "teams": sorted(teams), "skipped_sections": skipped}


# ---------------------------------------------------------------- gather

def gather(repo: Path) -> dict:
    repo = Path(repo)
    files = tracked_files(repo)
    build, edges = "folders", []
    settings = _gradle_settings(repo)
    if settings is not None and _gradle_modules(settings):
        build = "gradle"
        dirs = {n: n.replace(":", "/") for n in _gradle_modules(settings)}
        edges = _gradle_edges(repo, dirs)
    else:
        mv = _maven_modules(repo) if (repo / "pom.xml").is_file() else []
        mv = [m for m in mv if m[1]]
        if mv:
            build = "maven"
            dirs = {a: d for a, d, _g, _p in mv}
            edges = _maven_edges(mv)
        else:
            tops = sorted({f.split("/")[0] for f in files if "/" in f})
            dirs = {t: t for t in tops}
    return {"build": build, "modules": _count(files, dirs), "edges": edges, "codeowners": codeowners(repo)}
