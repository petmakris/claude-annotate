"""Guards for repository-level structure that no single skill owns.

These assert the things that break silently: a skill probing for a
marketplace name that no longer exists, a plugin manifest that stops
matching the skills on disk, a vendoring artifact left behind.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def _marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


# Skills reach their own code through bin/claude-annotate, which Claude Code
# puts on PATH and which finds the plugin root itself. A skill doc that names a
# runner command or a path under the root that does not exist cannot run once
# installed, and nothing else would notice until a user hit it.
RUNNER = ROOT / "bin" / "claude-annotate"

# Fenced shell blocks and inline code spans: the places a command is written.
FENCE_RE = re.compile(r"^```(?:bash|sh)\n(.*?)^```", re.DOTALL | re.MULTILINE)
INLINE_RE = re.compile(r"`([^`\n]+)`")
HEREDOC_RE = re.compile(r"<<-?\s*'?(\w+)'?\n.*?^\1$", re.DOTALL | re.MULTILINE)
# In command position only — start of a line or span, after `$(`, or after a
# pipe or `&&` — so prose that merely names the marketplace is not a command.
RUNNER_CMD_RE = re.compile(
    r"(?:^|\$\(|[;&|]\s*)[ \t]*\"?claude-annotate\s+([A-Za-z0-9._-]+)"
    r"(?:\s+-m\s+([\w.]+))?", re.MULTILINE)
SHELL_COMMENT_RE = re.compile(r"^\s*#.*$", re.MULTILINE)
ROOT_PATH_RE = re.compile(r'\$\(claude-annotate root\)/([\w./-]+)')
ROOT_VAR_RE = re.compile(r'(\w+)="\$\(claude-annotate root\)/([\w./-]+)"')
# The python probe each SKILL.md used to paste before the runner existed.
PASTED_PROBE_RE = re.compile(r'NAME, MARKER = "|known_marketplaces\.json')
# annotate-doctor cannot use the runner — it diagnoses a missing python3, so
# its locator is plain sh and names its marker as a shell assignment.
SHELL_MARKER_RE = re.compile(r'^MARKER="([^"]+)"$', re.MULTILINE)


def _skill_docs() -> list[Path]:
    return sorted(ROOT.glob("skills/**/*.md"))


def _code_in(doc: Path) -> list[str]:
    text = doc.read_text(encoding="utf-8")
    fenced = [SHELL_COMMENT_RE.sub("", HEREDOC_RE.sub("", b))
              for b in FENCE_RE.findall(text)]
    return fenced + INLINE_RE.findall(FENCE_RE.sub("", text))


def _module_file(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def _runner_target(cmd: str) -> Path | None:
    """The file `claude-annotate <cmd>` would run, per the runner's own rules."""
    module = cmd.replace("-", "_")
    annotate = _module_file("skills.annotate." + module)
    if annotate.is_file():
        return annotate
    if "." in module and _module_file("skills." + module).is_file():
        return _module_file("skills." + module)
    return None


def _runner_references() -> list[tuple[str, str, str | None]]:
    return [
        (str(doc.relative_to(ROOT)), cmd, mod)
        for doc in _skill_docs()
        for code in _code_in(doc)
        for cmd, mod in RUNNER_CMD_RE.findall(code)
    ]


def test_the_runner_is_used_and_executable():
    assert RUNNER.is_file() and RUNNER.stat().st_mode & 0o111
    used = {doc for doc, _, _ in _runner_references()}
    for skill in ("annotate", "ask_diff", "walkthrough", "dataflow", "deck",
                  "slides", "specimen", "show-diff"):
        assert any(d.startswith(f"skills/{skill}/") for d in used), (
            f"no runner reference found under skills/{skill}/ — did the "
            "invocation format change?")


def test_every_runner_command_in_a_skill_doc_resolves():
    broken = []
    for doc, cmd, mod in _runner_references():
        if cmd == "root":
            continue
        if cmd == "python":
            if mod and not _module_file(mod).is_file():
                broken.append((doc, f"python -m {mod}"))
            continue
        if _runner_target(cmd) is None:
            broken.append((doc, cmd))
    assert not broken, f"claude-annotate commands that do not exist: {broken}"


def test_every_path_under_the_plugin_root_exists():
    missing = []
    for doc in _skill_docs():
        for code in _code_in(doc):
            for rel in ROOT_PATH_RE.findall(code):
                if not (ROOT / rel).exists():
                    missing.append((str(doc.relative_to(ROOT)), rel))
        text = doc.read_text(encoding="utf-8")
        for var, base in ROOT_VAR_RE.findall(text):
            if not (ROOT / base).exists():
                missing.append((str(doc.relative_to(ROOT)), base))
            for rel in re.findall(r"\$\{?" + var + r"\}?/([\w./-]*\w)", text):
                if not (ROOT / base / rel).exists():
                    missing.append((str(doc.relative_to(ROOT)), f"{base}/{rel}"))
    assert not missing, f"skill docs name files the plugin does not ship: {missing}"


def test_no_skill_doc_pastes_its_own_root_probe():
    pasted = [
        str(doc.relative_to(ROOT))
        for doc in _skill_docs()
        if PASTED_PROBE_RE.search(doc.read_text(encoding="utf-8"))
    ]
    assert not pasted, f"use bin/claude-annotate instead of a pasted probe: {pasted}"


def test_every_shell_marker_file_exists():
    # The sh locator accepts a candidate root only if MARKER exists inside it,
    # so a stale marker path makes the skill unfindable.
    found = [
        (str(doc.relative_to(ROOT)), marker)
        for doc in _skill_docs()
        for marker in SHELL_MARKER_RE.findall(doc.read_text(encoding="utf-8"))
    ]
    assert any(doc == "skills/annotate-doctor/SKILL.md" for doc, _ in found), \
        "annotate-doctor's MARKER= locator is no longer seen by this check"
    missing = [(doc, marker) for doc, marker in found if not (ROOT / marker).is_file()]
    assert not missing, f"shell markers do not exist: {missing}"


def test_marketplace_publishes_two_plugins_from_one_root():
    plugins = _marketplace()["plugins"]
    assert [p["name"] for p in plugins] == ["claude-annotate", "claude-ide-review"]
    for plugin in plugins:
        # One root, shared. The skills array is what separates the plugins;
        # a subdirectory source would force a second copy of _shared.
        assert plugin["source"] == "./", plugin["name"]
        assert plugin["strict"] is False, plugin["name"]
        assert plugin["skills"], plugin["name"]
        assert plugin["description"], plugin["name"]


# Skills deliberately claimed by BOTH plugins. The list is not a loophole —
# anything not named here is still a duplicate-claim bug.
#
# annotate-doctor: every guard block's failure message tells the user to run
# /annotate-doctor. Shipping it only with
# claude-annotate meant a claude-ide-review-only user was pointed at a command
# their install does not have. One diagnostic, both plugins.
SHARED_SKILLS = {"./skills/annotate-doctor"}


def test_plugin_skill_lists_cover_the_skills_tree():
    listed = [s for p in _marketplace()["plugins"] for s in p["skills"]]
    doubled = {s for s in listed if listed.count(s) > 1}
    unexpected = doubled - SHARED_SKILLS
    assert not unexpected, f"a skill is claimed twice: {sorted(unexpected)}"
    stale = SHARED_SKILLS - doubled
    assert not stale, (
        f"declared shared but claimed by one plugin only: {sorted(stale)} — "
        "either share it or drop it from SHARED_SKILLS"
    )
    # A skill directory is one with a SKILL.md; _shared and tests have none.
    on_disk = {
        f"./skills/{d.name}"
        for d in (ROOT / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    }
    assert set(listed) == on_disk


def test_no_root_plugin_json():
    # Two plugins cannot share one plugin.json; their metadata lives in the
    # marketplace entries instead.
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()


BANNER = "GENERATED FILE"


def test_no_vendoring_artifacts():
    shared = ROOT / "skills" / "_shared"
    assert not (shared / "VENDOR.txt").exists()
    assert not (shared / "VENDOR.sha256").exists()


def test_engine_is_not_marked_generated():
    # The engine is edited here now. A "DO NOT EDIT" banner would send the
    # next reader looking for an upstream that no longer exists.
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "skills" / "_shared").rglob("*")
        if p.suffix in {".py", ".sh"} and BANNER in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"still marked generated: {offenders}"


# progress_publish.py was deleted while hooks/hooks.json still exec'd it,
# which turned a silent no-op into a PostToolUse error on every tool call
# once the gate's own pending-round condition was met. Nothing checked the
# registration against the tree. This scans every hooks.json in the repo —
# not just the one that broke — so a hook added next month is covered too.
_HOOK_COMMAND_SCRIPT_RE = re.compile(
    r'"((?:\$\{CLAUDE_PLUGIN_ROOT\}|/)[^"]*\.(?:py|sh))"'
)


def _hooks_json_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("hooks.json") if ".superpowers" not in p.parts)


def test_every_hook_command_names_a_script_that_exists():
    missing = []
    for hooks_json in _hooks_json_files():
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        for entries in data.get("hooks", {}).values():
            for entry in entries:
                for h in entry.get("hooks", []):
                    command = h.get("command", "")
                    for script in _HOOK_COMMAND_SCRIPT_RE.findall(command):
                        resolved = script.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
                        if not Path(resolved).is_file():
                            missing.append(f"{hooks_json.relative_to(ROOT)}: {resolved}")
    assert not missing, f"hook command names a script that does not exist: {missing}"


def test_every_reference_file_is_linked_from_its_skill():
    # A reference nobody routes to is never read: it is the same as deleting
    # it, except that it still looks maintained. Linked means SKILL.md, or
    # another reference of the same skill, names it.
    orphans = []
    for skill_md in sorted(ROOT.glob("skills/*/SKILL.md")):
        refs = sorted((skill_md.parent / "references").rglob("*.md"))
        for ref in refs:
            others = [skill_md, *(r for r in refs if r != ref)]
            rel = ref.relative_to(skill_md.parent).as_posix()
            if not any(rel in o.read_text(encoding="utf-8")
                       or (ref.name in o.read_text(encoding="utf-8")
                           and o.parent == ref.parent)
                       for o in others):
                orphans.append(str(ref.relative_to(ROOT)))
    assert not orphans, f"reference files no SKILL.md or sibling links to: {orphans}"
