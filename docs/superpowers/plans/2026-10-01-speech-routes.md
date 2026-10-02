# webcompanion speech routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the webcompanion daemon three owner-only routes. One reports whether speech is set up, one hands the page a short-lived Azure Speech token, and one writes a spoken explanation script for a selection by running `claude -p`.

**Architecture:** A new stdlib-only module, `src/webcompanion/speech.py`, holds all the logic: config parsing, token minting, the script prompt, the `claude` call, piece cleaning and the on-disk cache. `server.py` gains three thin route handlers that call it. Speech config is read from `~/.claude/webcompanion/speech.env` on every request, so editing that file needs no restart.

**Tech Stack:** Python ≥ 3.9 standard library only (`urllib.request`, `subprocess`, `hashlib`), pytest, the daemon's existing `call` / `daemon` fixtures.

**Spec:** `docs/superpowers/specs/2026-10-01-selection-menu-and-speech-design.md` (in the claude-annotate repo), §2 "Why the engine is shaped this way", §4.4 and §5.

**Repo:** all code changes are in `~/projects/webcompanion`. This plan file lives in claude-annotate with the spec.

## Global Constraints

- `pyproject.toml` `dependencies` stays `[]`. No import outside the standard library in `src/`.
- Python floor 3.9: no `match`, no `X | Y` at runtime outside annotations (files use `from __future__ import annotations`).
- All three routes require the owner (`self._require_owner()`), as every write route does.
- The key from `speech.env` never appears in any response body, error message, or log line.
- Config file: `~/.claude/webcompanion/speech.env` with `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, optional `CLAUDE_BIN`. Always resolved as `daemon.state_root / "speech.env"`, so tests stay in their temp state root.
- Token route returns `{"token", "region", "expires_in": 540}`.
- Script route body `{selection, context, glossary, page_title}` returns `{"pieces": [{"say", "src"}], "cached": bool}`.
- Selection limit: 4,000 characters (`413` above it).
- Script timeout: 45 s (`504`).
- Cache: `~/.claude/webcompanion/speech-cache/<sha256>.json`. Entries older than 30 days are deleted on each write.
- `claude` invocation, exactly: `claude -p --model opus --tools "" --no-session-persistence --setting-sources "" --strict-mcp-config --output-format json --json-schema <schema> --system-prompt <prompt>`, with the user prompt passed on stdin, not as an argv element. `--strict-mcp-config` (with no `--mcp-config`) loads zero MCP servers; without it the owner's claude.ai connectors add about 78K input tokens per call. Measured on 2026-10-01: 4.9 s under launchd's minimal `PATH`, with the parsed object under the envelope's `structured_output` key.
- `claude` lookup order: `CLAUDE_BIN` from `speech.env` → `~/.local/bin/claude` → `shutil.which("claude")`. launchd's `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`) does not contain `~/.local/bin`.
- Commit messages are one line, with no body and no trailers.
- Test command for this repo: `cd ~/projects/webcompanion && uv run -q --with pytest --with playwright --with-editable . python -m pytest tests -q -p no:cacheprovider`. Baseline on 2026-10-01: 442 passed.

## Review Focus

1. **Opus guesses when context is thin.** In a probe with no glossary, it invented "routes" and speculated about what "EDR" means. The system prompt must forbid guessing and require spelling an undefined abbreviation as letters. Task 3 pins that the prompt says so. The live check in Task 5 confirms the behaviour on real text.
2. **A piece whose `src` is not in the selection.** The model paraphrases. Keep the `say` and blank the `src`, never drop the piece. Pinned in Task 3.
3. **`claude` not logged in, or not found under launchd.** Must come back as a readable `503` or `502` naming the cause, not a `500` or a hang. Pinned in Task 3.
4. **The key leaking.** A malformed `speech.env`, an Azure error and the status route must never echo the key. Pinned in Task 4.
5. **A malformed body.** `selection` missing, a number, or only whitespace; `glossary` not a list; glossary entries without `term`. Each must give a `400` with a message, not a traceback. Pinned in Task 3.

---

### Task 1: `speech.py`, config and status

**Files:**
- Create: `src/webcompanion/speech.py`
- Test: `tests/test_speech.py`

**Interfaces:**
- Produces:
  - `ENV_FILE = "speech.env"`
  - `CACHE_DIR = "speech-cache"`
  - `class SpeechError(Exception)` with `.status: int` and `.message: str`
  - `@dataclass(frozen=True) class SpeechConfig(key: str | None, region: str | None, claude_bin: str | None)`
  - `read_env_file(path: Path) -> dict[str, str]`
  - `load(state_root: Path) -> SpeechConfig`
  - `resolve_claude(cfg: SpeechConfig) -> str | None`
  - `status(cfg: SpeechConfig) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_speech.py
from __future__ import annotations

import os
import stat

import pytest

from webcompanion import speech


def _exe(path, body="#!/bin/sh\nexit 0\n"):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_the_env_file_reads_plain_quoted_and_exported_lines(tmp_path):
    p = tmp_path / "speech.env"
    p.write_text('# a comment\n\nAZURE_SPEECH_KEY="abc"\n'
                 "export AZURE_SPEECH_REGION='westeurope'\nCLAUDE_BIN=/x/claude\nnot a line\n")
    assert speech.read_env_file(p) == {
        "AZURE_SPEECH_KEY": "abc", "AZURE_SPEECH_REGION": "westeurope",
        "CLAUDE_BIN": "/x/claude"}


def test_a_missing_env_file_is_an_empty_config(tmp_path):
    cfg = speech.load(tmp_path)
    assert cfg == speech.SpeechConfig(key=None, region=None, claude_bin=None)


def test_claude_is_found_from_claude_bin_first(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _: None)
    exe = _exe(tmp_path / "my-claude")
    cfg = speech.SpeechConfig(key=None, region=None, claude_bin=str(exe))
    assert speech.resolve_claude(cfg) == str(exe)


def test_claude_falls_back_to_local_bin(tmp_path, monkeypatch):
    # HOME is redirected to tmp_path/_home by conftest.
    monkeypatch.setattr(speech.shutil, "which", lambda _: None)
    local = tmp_path / "_home" / ".local" / "bin"
    local.mkdir(parents=True)
    exe = _exe(local / "claude")
    assert speech.resolve_claude(speech.SpeechConfig(None, None, None)) == str(exe)


def test_a_claude_bin_that_is_not_executable_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _: None)
    f = tmp_path / "claude"
    f.write_text("not executable")
    assert speech.resolve_claude(speech.SpeechConfig(None, None, str(f))) is None


def test_status_names_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _: None)
    s = speech.status(speech.SpeechConfig(None, None, None))
    assert s["configured"] is False and s["claude"] is False
    assert "AZURE_SPEECH_KEY" in s["reason"]

    exe = _exe(tmp_path / "claude")
    s = speech.status(speech.SpeechConfig("k", "westeurope", str(exe)))
    assert s == {"configured": True, "claude": True, "region": "westeurope"}


def test_status_never_contains_the_key():
    s = speech.status(speech.SpeechConfig("SECRET-KEY-123", "westeurope", None))
    assert "SECRET-KEY-123" not in repr(s)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_speech.py -q -p no:cacheprovider`
Expected: collection error, `ImportError: cannot import name 'speech' from 'webcompanion'`.

- [ ] **Step 3: Write the module's first half**

```python
# src/webcompanion/speech.py
"""Speech for every skill's page: Azure tokens and spoken explanation scripts.

The page never holds a key. Through the /api/speech routes it asks this
module for a ten-minute Azure token, which the browser's Speech SDK uses
directly, and for a script that explains a selection in speakable pieces.

Stdlib only, like the rest of the daemon (pyproject.toml asserts
`dependencies = []`). Azure's Python SDK is a native package, which is why
synthesis and recognition run in the browser and only the token is made
here. The script is written by `claude -p` on the user's own subscription,
so no second model key exists anywhere.

Config lives in `<state_root>/speech.env` and is re-read on every request,
so editing it needs no restart. The key it holds must never reach a
response, an error message or a log line.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from webcompanion.atomic import write_text_atomic

ENV_FILE = "speech.env"
CACHE_DIR = "speech-cache"


class SpeechError(Exception):
    """A failure the route reports as `status` with `message` as its body."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class SpeechConfig:
    key: str | None
    region: str | None
    claude_bin: str | None


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines. `#` comments, blank lines, an `export ` prefix and
    one pair of surrounding quotes are allowed; anything else is skipped."""
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def load(state_root: Path) -> SpeechConfig:
    env = read_env_file(Path(state_root) / ENV_FILE)
    return SpeechConfig(key=env.get("AZURE_SPEECH_KEY") or None,
                        region=env.get("AZURE_SPEECH_REGION") or None,
                        claude_bin=env.get("CLAUDE_BIN") or None)


def resolve_claude(cfg: SpeechConfig) -> str | None:
    """CLAUDE_BIN, then ~/.local/bin/claude, then PATH. launchd's PATH does
    not include ~/.local/bin, which is where the installer puts claude."""
    for c in (cfg.claude_bin,
              str(Path.home() / ".local" / "bin" / "claude"),
              shutil.which("claude")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def status(cfg: SpeechConfig) -> dict:
    configured = bool(cfg.key and cfg.region)
    claude = resolve_claude(cfg) is not None
    out: dict = {"configured": configured, "claude": claude}
    if cfg.region:
        out["region"] = cfg.region
    if not configured:
        out["reason"] = ("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are not both "
                         "set in ~/.claude/webcompanion/speech.env")
    elif not claude:
        out["reason"] = ("claude was not found; set CLAUDE_BIN in "
                         "~/.claude/webcompanion/speech.env")
    return out
```

- [ ] **Step 4: Run the tests and see them pass**

Run: the command from Step 2.
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/webcompanion && git add src/webcompanion/speech.py tests/test_speech.py && git commit -m "feat(speech): read speech.env and find claude, stdlib only"
```

---

### Task 2: Azure token minting

**Files:**
- Modify: `src/webcompanion/speech.py` (append)
- Test: `tests/test_speech.py` (append)

**Interfaces:**
- Consumes: `SpeechConfig`, `SpeechError` from Task 1.
- Produces:
  - `STS_URL = "https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"`
  - `TOKEN_TTL_REPORTED = 540`
  - `mint_token(cfg: SpeechConfig) -> dict`, which returns `{"token": str, "region": str, "expires_in": 540}` or raises `SpeechError(503 | 502, ...)`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_speech.py
import http.server
import threading


class _FakeSTS:
    """A local stand-in for Azure's issueToken endpoint."""

    def __init__(self, status=200, body=b"tok-123"):
        seen = self.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen.append({"path": self.path,
                             "key": self.headers.get("Ocp-Apim-Subscription-Key")})
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/" + "{region}/sts"

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def sts(monkeypatch):
    made = []

    def make(**kw):
        f = _FakeSTS(**kw)
        made.append(f)
        monkeypatch.setattr(speech, "STS_URL", f.url)
        return f
    yield make
    for f in made:
        f.close()


def test_a_token_is_minted_with_the_key_in_the_header(sts):
    fake = sts()
    out = speech.mint_token(speech.SpeechConfig("KEY-1", "westeurope", None))
    assert out == {"token": "tok-123", "region": "westeurope", "expires_in": 540}
    assert fake.seen == [{"path": "/westeurope/sts", "key": "KEY-1"}]


def test_no_key_is_a_503_before_any_request(sts):
    fake = sts()
    with pytest.raises(speech.SpeechError) as e:
        speech.mint_token(speech.SpeechConfig(None, "westeurope", None))
    assert e.value.status == 503
    assert fake.seen == []


def test_an_azure_refusal_is_a_502_naming_the_status_and_not_the_key(sts):
    sts(status=401, body=b"Access denied due to invalid subscription key")
    with pytest.raises(speech.SpeechError) as e:
        speech.mint_token(speech.SpeechConfig("SECRET-KEY-123", "westeurope", None))
    assert e.value.status == 502
    assert "HTTP 401" in e.value.message
    assert "SECRET-KEY-123" not in e.value.message


def test_an_unreachable_azure_is_a_502(monkeypatch):
    monkeypatch.setattr(speech, "STS_URL", "http://127.0.0.1:9/{region}")
    with pytest.raises(speech.SpeechError) as e:
        speech.mint_token(speech.SpeechConfig("k", "westeurope", None))
    assert e.value.status == 502
    assert "did not answer" in e.value.message
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_speech.py -q -p no:cacheprovider -k "token or azure or key_is"`
Expected: FAIL with `AttributeError: module 'webcompanion.speech' has no attribute 'STS_URL'`.

- [ ] **Step 3: Implement**

```python
# append to src/webcompanion/speech.py
STS_URL = "https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
# Azure's tokens live ten minutes. Reporting nine makes the page refresh a
# minute early instead of finding out from a failed synthesis.
TOKEN_TTL_REPORTED = 540


def mint_token(cfg: SpeechConfig) -> dict:
    if not (cfg.key and cfg.region):
        raise SpeechError(503, "speech is not configured: set AZURE_SPEECH_KEY and "
                               "AZURE_SPEECH_REGION in ~/.claude/webcompanion/speech.env")
    req = urllib.request.Request(STS_URL.format(region=cfg.region), data=b"",
                                 method="POST")
    req.add_header("Ocp-Apim-Subscription-Key", cfg.key)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            token = r.read().decode("ascii", "replace").strip()
    except urllib.error.HTTPError as e:
        raise SpeechError(502, f"Azure refused the token request (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError) as e:
        raise SpeechError(502, f"Azure did not answer ({e.__class__.__name__})") from None
    if not token:
        raise SpeechError(502, "Azure returned an empty token")
    return {"token": token, "region": cfg.region, "expires_in": TOKEN_TTL_REPORTED}
```

- [ ] **Step 4: Run the whole file**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_speech.py -q -p no:cacheprovider`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/webcompanion && git add src/webcompanion/speech.py tests/test_speech.py && git commit -m "feat(speech): mint ten-minute Azure tokens without exposing the key"
```

---

### Task 3: The explanation script

**Files:**
- Modify: `src/webcompanion/speech.py` (append)
- Test: `tests/test_speech.py` (append)

**Interfaces:**
- Consumes: `SpeechConfig`, `SpeechError`, `resolve_claude` (Task 1).
- Produces:
  - `MAX_SELECTION = 4000`, `SCRIPT_TIMEOUT_S = 45`, `PROMPT_VERSION = 1`
  - `SCRIPT_SCHEMA: dict`, `SYSTEM_PROMPT: str`
  - `build_prompt(selection: str, context: str, glossary: list, page_title: str) -> str`
  - `cache_key(selection, context, glossary, page_title) -> str` (sha256 hex)
  - `write_script(cfg, cache_dir: Path, selection, context="", glossary=None, page_title="") -> dict`, which returns `{"pieces": [{"say": str, "src": str}], "cached": bool}` or raises `SpeechError` (400, 413, 502, 503, 504)

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_speech.py
import json as _json

ENVELOPE = {"type": "result", "subtype": "success", "is_error": False,
            "result": "...",
            "structured_output": {"pieces": [
                {"src": "The spec (use case 06a/07a)", "say": "The spec, in use cases zero-six-A and zero-seven-A,"},
                {"src": "a paraphrase not in the text", "say": "says Europe and Switzerland."},
                {"src": "", "say": "   "}]}}
SELECTION = "The spec (use case 06a/07a) says Europe & CH First/Premium."


def _fake_claude(tmp_path, envelope=ENVELOPE, exit_code=0, sleep=0):
    """A stand-in for `claude -p`. It records its argv and how often it ran,
    and prints a fixed envelope."""
    out = tmp_path / "fake.out"
    out.write_text(_json.dumps(envelope) if isinstance(envelope, dict) else envelope)
    exe = tmp_path / "fake-claude"
    _exe(exe, "#!/bin/sh\n"
              f'echo run >> "{tmp_path}/fake.count"\n'
              f'printf "%s\\n" "$@" > "{tmp_path}/fake.argv"\n'
              f"sleep {sleep}\n"
              f'cat "{out}"\n'
              f"exit {exit_code}\n")
    return speech.SpeechConfig("k", "westeurope", str(exe))


def _runs(tmp_path):
    p = tmp_path / "fake.count"
    return len(p.read_text().splitlines()) if p.exists() else 0


def test_pieces_come_back_with_unmatched_src_blanked_and_empty_say_dropped(tmp_path):
    cfg = _fake_claude(tmp_path)
    out = speech.write_script(cfg, tmp_path / "cache", SELECTION, "ctx", [], "ABC-310")
    assert out == {"cached": False, "pieces": [
        {"say": "The spec, in use cases zero-six-A and zero-seven-A,",
         "src": "The spec (use case 06a/07a)"},
        {"say": "says Europe and Switzerland.", "src": ""}]}


def test_claude_is_called_headless_with_opus_no_tools_and_the_schema(tmp_path):
    cfg = _fake_claude(tmp_path)
    speech.write_script(cfg, tmp_path / "cache", SELECTION)
    argv = (tmp_path / "fake.argv").read_text().split("\n")
    for flag in ("-p", "--no-session-persistence", "--output-format", "--json-schema",
                 "--system-prompt"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert _json.loads(argv[argv.index("--json-schema") + 1]) == speech.SCRIPT_SCHEMA


def test_a_second_identical_request_is_served_from_the_cache(tmp_path):
    cfg = _fake_claude(tmp_path)
    a = speech.write_script(cfg, tmp_path / "cache", SELECTION, "ctx", [{"term": "EDR"}], "T")
    b = speech.write_script(cfg, tmp_path / "cache", SELECTION, "ctx", [{"term": "EDR"}], "T")
    assert b == {**a, "cached": True}
    assert _runs(tmp_path) == 1
    speech.write_script(cfg, tmp_path / "cache", SELECTION, "other ctx", [{"term": "EDR"}], "T")
    assert _runs(tmp_path) == 2


def test_old_cache_entries_are_swept_on_write(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    old = cache / ("0" * 64 + ".json")
    old.write_text("{}")
    os.utime(old, (1, 1))
    speech.write_script(_fake_claude(tmp_path), cache, SELECTION)
    assert not old.exists()


@pytest.mark.parametrize("selection", [None, 42, "", "   \n "])
def test_a_missing_or_blank_selection_is_a_400(tmp_path, selection):
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(_fake_claude(tmp_path), tmp_path / "c", selection)
    assert e.value.status == 400
    assert _runs(tmp_path) == 0


def test_a_selection_over_the_limit_is_a_413(tmp_path):
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(_fake_claude(tmp_path), tmp_path / "c", "x" * 4001)
    assert e.value.status == 413


def test_a_glossary_that_is_not_a_list_is_a_400(tmp_path):
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(_fake_claude(tmp_path), tmp_path / "c", SELECTION, "", "EDR")
    assert e.value.status == 400


def test_glossary_entries_without_a_term_are_ignored_not_fatal(tmp_path):
    out = speech.write_script(_fake_claude(tmp_path), tmp_path / "c", SELECTION, "",
                              [{"definition": "no term"}, "junk", {"term": "EDR", "definition": "x"}])
    assert out["pieces"]


def test_claude_not_found_is_a_503(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _: None)
    cfg = speech.SpeechConfig("k", "r", str(tmp_path / "nope"))
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(cfg, tmp_path / "c", SELECTION)
    assert e.value.status == 503
    assert "claude was not found" in e.value.message


def test_claude_not_logged_in_is_a_502_with_its_own_words(tmp_path):
    cfg = _fake_claude(tmp_path, envelope={"type": "result", "is_error": True,
                                           "result": "Not logged in · Please run /login"},
                       exit_code=1)
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(cfg, tmp_path / "c", SELECTION)
    assert e.value.status == 502
    assert "Not logged in" in e.value.message


def test_output_that_is_not_json_is_a_502(tmp_path):
    cfg = _fake_claude(tmp_path, envelope="segfault\n", exit_code=139)
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(cfg, tmp_path / "c", SELECTION)
    assert e.value.status == 502


def test_a_slow_claude_is_a_504(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, "SCRIPT_TIMEOUT_S", 1)
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(_fake_claude(tmp_path, sleep=3), tmp_path / "c", SELECTION)
    assert e.value.status == 504


def test_no_usable_piece_is_a_502(tmp_path):
    env = {**ENVELOPE, "structured_output": {"pieces": [{"src": "", "say": ""}]}}
    with pytest.raises(speech.SpeechError) as e:
        speech.write_script(_fake_claude(tmp_path, envelope=env), tmp_path / "c", SELECTION)
    assert e.value.status == 502


def test_the_prompt_forbids_guessing_and_spells_undefined_abbreviations():
    p = speech.SYSTEM_PROMPT.lower()
    assert "never guess" in p
    assert "letter by letter" in p
    assert "exact" in p and "substring" in p


def test_the_user_prompt_carries_glossary_context_and_title():
    p = speech.build_prompt(SELECTION, "the paragraph",
                            [{"term": "EDR", "definition": "External Data Reference", "role": "confirms segments"}],
                            "ABC-310 ticket draft")
    assert "ABC-310 ticket draft" in p and "the paragraph" in p
    assert "EDR: External Data Reference" in p
    assert p.rstrip().endswith(SELECTION)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_speech.py -q -p no:cacheprovider`
Expected: the 11 earlier tests pass. The new ones fail with `AttributeError: module 'webcompanion.speech' has no attribute 'write_script'` (or `SYSTEM_PROMPT` / `build_prompt`).

- [ ] **Step 3: Implement**

```python
# append to src/webcompanion/speech.py
MAX_SELECTION = 4000
MAX_CONTEXT = 4000
MAX_GLOSSARY = 200
SCRIPT_TIMEOUT_S = 45
CACHE_MAX_AGE_S = 30 * 86400
# Part of every cache key: changing the prompt or the schema must not serve
# scripts written under the old one. Bump it whenever either changes.
PROMPT_VERSION = 1

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {"pieces": {"type": "array", "items": {
        "type": "object",
        "properties": {"say": {"type": "string"}, "src": {"type": "string"}},
        "required": ["say", "src"], "additionalProperties": False}}},
    "required": ["pieces"], "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You turn a passage a reader selected into a short spoken explanation. A
text-to-speech voice will read your words aloud while the reader looks at the
page.

Rules:
- Explain what the passage means and why it matters. Do not recite it.
- Use only what the selection, the surrounding context and the glossary say.
  Never guess what a term, acronym, name or code means. If nothing given to
  you defines an abbreviation, say it letter by letter (EDR becomes "E-D-R")
  and do not explain it.
- Expand an abbreviation the glossary or the context defines, the first time
  it is spoken.
- Say codes, numbers and symbols the way a person would: "06a/07a" becomes
  "zero-six-A and zero-seven-A", "21 Aug" becomes "August twenty-first", "&"
  becomes "and".
- Leave out citations that are not content, such as "transcript lines 29-34".
- Split the explanation into pieces of one or two sentences, in the order of
  the selection. Each piece's "src" is the exact substring of the selection
  that the piece explains, copied character for character.
- Plain spoken English. No markdown, lists, parentheses or emoji.
"""


def _glossary_lines(glossary: list) -> list[str]:
    lines = []
    for g in glossary:
        if not isinstance(g, dict) or not isinstance(g.get("term"), str) or not g["term"]:
            continue
        rest = " ".join(str(g.get(k) or "").strip() for k in ("definition", "role")).strip()
        lines.append(f"- {g['term']}: {rest}".rstrip(": ").rstrip())
    return lines


def build_prompt(selection: str, context: str, glossary: list, page_title: str) -> str:
    gl = "\n".join(_glossary_lines(glossary)) or "(none)"
    return (f"Page title: {page_title or '(none)'}\n\n"
            f"Glossary:\n{gl}\n\n"
            f"Surrounding context:\n{context or '(none)'}\n\n"
            f"Selection to explain:\n{selection}\n")


def cache_key(selection: str, context: str, glossary: list, page_title: str) -> str:
    raw = json.dumps([PROMPT_VERSION, selection, context, glossary, page_title],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean_pieces(raw, selection: str) -> list[dict]:
    """Keep every piece with something to say. A `src` that is not an exact
    substring of the selection is blanked rather than dropped: the model
    paraphrases, and losing a sentence of the explanation is worse than that
    sentence not lighting the page."""
    out = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        say, src = p.get("say"), p.get("src")
        if not isinstance(say, str) or not say.strip():
            continue
        ok = isinstance(src, str) and src != "" and src in selection
        out.append({"say": say.strip(), "src": src if ok else ""})
    return out


def _sweep_cache(cache_dir: Path) -> None:
    cutoff = time.time() - CACHE_MAX_AGE_S
    for f in cache_dir.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def write_script(cfg: SpeechConfig, cache_dir: Path, selection, context="",
                 glossary=None, page_title="") -> dict:
    if not isinstance(selection, str) or not selection.strip():
        raise SpeechError(400, "selection is required")
    if len(selection) > MAX_SELECTION:
        raise SpeechError(413, f"selection is over {MAX_SELECTION} characters")
    if glossary is None:
        glossary = []
    if not isinstance(glossary, list):
        raise SpeechError(400, "glossary must be a list")
    context = context[:MAX_CONTEXT] if isinstance(context, str) else ""
    page_title = page_title if isinstance(page_title, str) else ""
    glossary = glossary[:MAX_GLOSSARY]

    cache_dir = Path(cache_dir)
    hit = cache_dir / f"{cache_key(selection, context, glossary, page_title)}.json"
    try:
        cached = json.loads(hit.read_text())["pieces"]
        if isinstance(cached, list) and cached:
            return {"pieces": cached, "cached": True}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    claude = resolve_claude(cfg)
    if claude is None:
        raise SpeechError(503, "claude was not found; set CLAUDE_BIN in "
                               "~/.claude/webcompanion/speech.env")
    argv = [claude, "-p", "--model", "opus", "--tools", "",
            "--no-session-persistence", "--setting-sources", "",
            "--output-format", "json", "--json-schema", json.dumps(SCRIPT_SCHEMA),
            "--system-prompt", SYSTEM_PROMPT,
            build_prompt(selection, context, glossary, page_title)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=SCRIPT_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise SpeechError(504, f"writing the explanation took longer than "
                               f"{SCRIPT_TIMEOUT_S} s") from None
    except OSError as e:
        raise SpeechError(503, f"could not run claude ({e.__class__.__name__})") from None

    try:
        envelope = json.loads(proc.stdout)
    except ValueError:
        envelope = None
    if proc.returncode != 0 or not isinstance(envelope, dict) or envelope.get("is_error"):
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            detail = envelope["result"]
        else:
            detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise SpeechError(502, f"claude could not write the explanation: {detail[:200]}")

    structured = envelope.get("structured_output")
    pieces = _clean_pieces(structured.get("pieces") if isinstance(structured, dict) else None,
                           selection)
    if not pieces:
        raise SpeechError(502, "claude returned no explanation")
    cache_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(hit, json.dumps({"pieces": pieces}, ensure_ascii=False))
    _sweep_cache(cache_dir)
    return {"pieces": pieces, "cached": False}
```

- [ ] **Step 4: Run the whole file**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_speech.py -q -p no:cacheprovider`
Expected: `29 passed`. The parametrised 400 test counts as 4.

- [ ] **Step 5: Commit**

```bash
cd ~/projects/webcompanion && git add src/webcompanion/speech.py tests/test_speech.py && git commit -m "feat(speech): write spoken explanation scripts through claude -p, cached by content"
```

---

### Task 4: The routes, and the contract doc

**Files:**
- Modify: `src/webcompanion/server.py` (import, three handlers, three dispatch lines)
- Modify: `docs/contract.md` (quick-reference block and route table)
- Test: `tests/test_server_speech.py` (new)

**Interfaces:**
- Consumes: `speech.load`, `speech.status`, `speech.mint_token`, `speech.write_script`, `speech.SpeechError`, `speech.CACHE_DIR`.
- Produces: `GET /api/speech/status`, `POST /api/speech/token`, `POST /api/speech/script`.

- [ ] **Step 1: Write the failing route tests**

```python
# tests/test_server_speech.py
from __future__ import annotations

import json
import stat

import pytest

from webcompanion import paths, speech

CROSS_SITE = {"Sec-Fetch-Site": "cross-site"}
KEY = "SECRET-KEY-123"


@pytest.fixture
def configured(tmp_path):
    exe = tmp_path / "fake-claude"
    out = tmp_path / "fake.out"
    out.write_text(json.dumps({"type": "result", "is_error": False, "structured_output": {
        "pieces": [{"say": "It says hello.", "src": "hello"}]}}))
    exe.write_text(f'#!/bin/sh\ncat "{out}"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    root = paths.state_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "speech.env").write_text(
        f"AZURE_SPEECH_KEY={KEY}\nAZURE_SPEECH_REGION=westeurope\nCLAUDE_BIN={exe}\n")
    return root


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/speech/status"), ("POST", "/api/speech/token"),
    ("POST", "/api/speech/script")])
def test_every_speech_route_refuses_a_non_owner(call, configured, method, path):
    status, _ = call(method, path, {"selection": "hello"} if method == "POST" else None,
                     headers=CROSS_SITE)
    assert status == 403


def test_status_reports_configured_without_the_key(call, configured):
    status, body = call("GET", "/api/speech/status")
    assert status == 200
    assert body == {"configured": True, "claude": True, "region": "westeurope"}
    assert KEY not in json.dumps(body)


def test_status_when_nothing_is_set_up(call):
    status, body = call("GET", "/api/speech/status")
    assert status == 200
    assert body["configured"] is False


def test_script_route_returns_pieces(call, configured):
    status, body = call("POST", "/api/speech/script",
                        {"selection": "hello world", "context": "", "glossary": [],
                         "page_title": "T"})
    assert status == 200
    assert body == {"pieces": [{"say": "It says hello.", "src": "hello"}], "cached": False}
    assert (configured / speech.CACHE_DIR).is_dir()


def test_script_route_maps_errors_to_status_and_message(call, configured):
    status, body = call("POST", "/api/speech/script", {"selection": "x" * 4001})
    assert status == 413
    assert "4000" in body
    status, body = call("POST", "/api/speech/script", {})
    assert status == 400


def test_token_route_reports_azure_failure_without_the_key(call, configured, monkeypatch):
    monkeypatch.setattr(speech, "STS_URL", "http://127.0.0.1:9/{region}")
    status, body = call("POST", "/api/speech/token")
    assert status == 502
    assert KEY not in body


def test_editing_speech_env_needs_no_restart(call, configured):
    assert call("GET", "/api/speech/status")[1]["configured"] is True
    (configured / "speech.env").write_text("AZURE_SPEECH_REGION=westeurope\n")
    assert call("GET", "/api/speech/status")[1]["configured"] is False
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_server_speech.py -q -p no:cacheprovider`
Expected: every test fails on `status == 404` (route not found). The `403` tests fail because they get `404`.

- [ ] **Step 3: Wire the routes**

In `src/webcompanion/server.py`, add `speech` to the existing `from webcompanion import ...` line (or add `from webcompanion import speech` beside the other module imports).

In `do_GET`, directly after `if path == "/api/whoami": return self._whoami()`:

```python
            if path == "/api/speech/status":
                return self._speech_status()
```

In `do_POST`, directly after `if path == "/api/open": return self._open_in_editor()`:

```python
            if path == "/api/speech/token":
                return self._speech_token()
            if path == "/api/speech/script":
                return self._speech_script()
```

Add these handlers just above `def _open_in_editor(self) -> None:`:

```python
        # ── speech ──────────────────────────────────────────────────────
        # Owner only, all three: each spends the owner's Azure money or
        # Claude subscription. speech.env is re-read per request, so editing
        # it needs no restart. Error bodies come from speech.SpeechError,
        # whose messages are written never to contain the key.
        def _speech_cfg(self) -> "speech.SpeechConfig":
            return speech.load(daemon.state_root)

        def _speech_status(self) -> None:
            if not self._require_owner():
                return
            self._json(200, speech.status(self._speech_cfg()))

        def _speech_token(self) -> None:
            if not self._require_owner():
                return
            try:
                self._json(200, speech.mint_token(self._speech_cfg()))
            except speech.SpeechError as e:
                self._text(e.status, e.message)

        def _speech_script(self) -> None:
            if not self._require_owner():
                return
            b = self._body()
            try:
                out = speech.write_script(
                    self._speech_cfg(), daemon.state_root / speech.CACHE_DIR,
                    b.get("selection"), b.get("context") or "",
                    b.get("glossary"), b.get("page_title") or "")
            except speech.SpeechError as e:
                self._text(e.status, e.message)
                return
            self._json(200, out)
```

- [ ] **Step 4: Run the route tests**

Run: the command from Step 2.
Expected: `9 passed` (the parametrised 403 test counts as 3).

- [ ] **Step 5: Run the doc-claims tests and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_readme_claims.py -q -p no:cacheprovider`
Expected: FAIL in `test_every_served_route_is_documented` with `the server serves routes the contract doc does not list: GET /api/speech/status, POST /api/speech/script, POST /api/speech/token`.

- [ ] **Step 6: Document the routes**

In `docs/contract.md`, in the quick-reference block, after the line `POST   /api/open`, add:

```
GET    /api/speech/status
POST   /api/speech/token
POST   /api/speech/script
```

In the route table, after the `/api/open` row, add:

```markdown
| GET | `/api/speech/status` | write | Whether speech is set up, for a page deciding whether to offer read-aloud and dictation. Returns `{configured, claude, region?, reason?}`. `configured` means `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` are both set in `~/.claude/webcompanion/speech.env`; `claude` means the `claude` binary was found. Owner only, although it reads, because it tells a caller which Azure region the owner pays for. Never contains the key. |
| POST | `/api/speech/token` | write | A ten-minute Azure Speech token for the browser SDK. Returns `{token, region, expires_in: 540}`; the 540 makes a client refresh a minute early. `503` when speech is not configured, `502` when Azure refused or did not answer (the body names the HTTP status, never the key). |
| POST | `/api/speech/script` | write | A spoken explanation of a selection, written by `claude -p --model opus` on the owner's subscription. Body: `{selection, context?, glossary?, page_title?}`, where `glossary` is annotate's `[{term, definition?, role?}]`. Returns `{pieces: [{say, src}], cached}`; `src` is an exact substring of `selection`, or `""` when the model paraphrased. Cached by content for 30 days under `speech-cache/`. `400` for a missing selection or a non-list glossary, `413` over 4,000 characters, `503` when `claude` is not found, `502` when it failed (the body carries its message), `504` after 45 s. |
```

Then add this paragraph directly under the route table:

```markdown
The three `/api/speech` routes are the only ones not about sessions, items,
threads or events. Speech lives in the daemon because every skill's page can
use it, the key then lives in one place, and the page's own origin needs no
CORS. The daemon makes only the token and the script. Synthesis and
recognition run in the browser through Azure's Speech SDK, which keeps the
daemon free of dependencies.
```

- [ ] **Step 7: Run the full suite**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with playwright --with-editable . python -m pytest tests -q -p no:cacheprovider`
Expected: `480 passed` (442 baseline + 29 in `test_speech.py` + 9 in `test_server_speech.py`).

- [ ] **Step 8: Commit**

```bash
cd ~/projects/webcompanion && git add src/webcompanion/server.py docs/contract.md tests/test_server_speech.py && git commit -m "feat(speech): owner-only /api/speech status, token and script routes"
```

---

### Task 5: `doctor` reports speech, then deploy and check live

**Files:**
- Modify: `src/webcompanion/commands/doctor.py`
- Test: `tests/test_doctor.py` (append)

**Interfaces:**
- Consumes: `speech.load`, `speech.status`, `speech.ENV_FILE`, `paths.state_root()`.
- Produces: doctor output lines starting `speech:`. Speech is optional, so it never sets `ok = False`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_doctor.py
def test_doctor_says_speech_is_optional_when_unset(capsys):
    doctor.run([])
    out = capsys.readouterr().out
    assert "speech: not set up (optional)" in out


def test_doctor_reports_speech_without_printing_the_key(capsys):
    from webcompanion import paths
    root = paths.state_root()
    root.mkdir(parents=True, exist_ok=True)
    env = root / "speech.env"
    env.write_text("AZURE_SPEECH_KEY=SECRET-KEY-123\nAZURE_SPEECH_REGION=westeurope\n")
    env.chmod(0o644)
    doctor.run([])
    out = capsys.readouterr().out
    assert "speech: key set, region westeurope" in out
    assert "expected mode 0600" in out
    assert "SECRET-KEY-123" not in out
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with-editable . python -m pytest tests/test_doctor.py -q -p no:cacheprovider -k speech`
Expected: FAIL, with `assert 'speech: not set up (optional)' in out`.

- [ ] **Step 3: Implement**

In `src/webcompanion/commands/doctor.py`, add `from webcompanion import speech` with the other imports. Insert this block in `run()` directly before `tail = _log_tail()`:

```python
    # Speech is optional: a machine without it still serves every page, so
    # nothing here can fail the doctor. It prints only whether the key is
    # set, never the key.
    env_path = paths.state_root() / speech.ENV_FILE
    if not env_path.exists():
        print("speech: not set up (optional) -- read-aloud and dictation need "
              f"AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in {env_path}")
    else:
        scfg = speech.load(paths.state_root())
        st = speech.status(scfg)
        key_state = "key set" if scfg.key else "key MISSING"
        print(f"speech: {key_state}, region {scfg.region or 'MISSING'}, "
              f"claude {speech.resolve_claude(scfg) or 'NOT FOUND'}")
        mode = env_path.stat().st_mode & 0o777
        if mode != 0o600:
            print(f"  warning: {env_path} has mode {oct(mode)}, expected mode 0600 "
                  f"-- the Azure key may be readable by other users")
        if st.get("reason"):
            print(f"  {st['reason']}")
```

- [ ] **Step 4: Run the full suite**

Run: `cd ~/projects/webcompanion && uv run -q --with pytest --with playwright --with-editable . python -m pytest tests -q -p no:cacheprovider`
Expected: `482 passed`.

- [ ] **Step 5: Commit and push**

```bash
cd ~/projects/webcompanion && git add src/webcompanion/commands/doctor.py tests/test_doctor.py && git commit -m "feat(doctor): report speech setup without printing the key" && git push
```

- [ ] **Step 6: Deploy to this machine**

```bash
pipx install --force ~/projects/webcompanion && webcompanion install-service && webcompanion doctor | grep -A2 '^speech:'
```

Expected: `speech: key set, region germanywestcentral, claude /Users/petros.makris/.local/bin/claude`, and no mode warning (the file is already `600`).

- [ ] **Step 7: Live check against the running daemon**

Run as the owner, over loopback, which the gate treats as the owner:

```bash
PORT=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/webcompanion/config.json')))['port'])")
curl -s http://127.0.0.1:$PORT/api/speech/status; echo
curl -s -X POST http://127.0.0.1:$PORT/api/speech/token | python3 -c "import json,sys;d=json.load(sys.stdin);print('token chars:',len(d['token']),d['region'],d['expires_in'])"
time curl -s -X POST http://127.0.0.1:$PORT/api/speech/script -H 'Content-Type: application/json' \
  -d '{"selection":"The spec (use case 06a/07a) says Europe & CH First/Premium. The taxon cannot be defined until EDR confirms.","context":"","glossary":[],"page_title":"ABC-310 ticket draft"}' | python3 -m json.tool
```

Expected:
- **Status:** `{"configured": true, "claude": true, "region": "germanywestcentral"}`.
- **Token:** about 776 characters, then `germanywestcentral 540`.
- **Script:** pieces within about 10 s, `"cached": false`. Every `src` is a substring of the selection.
- **The guessing check (Review Focus 1):** EDR is spoken as "E-D-R" with no invented meaning. If a piece guesses, tighten `SYSTEM_PROMPT`, bump `PROMPT_VERSION` to 2, rerun Task 3's tests, and commit `fix(speech): <what the prompt now forbids>`.
- **The cache:** a second identical `curl` returns `"cached": true` in well under a second.
