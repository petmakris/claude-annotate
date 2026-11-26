"""The one transcript parser of the session index: names, prompts and turns.

Built on `fleet_history`'s readers (`records`, `newest_names`, `human_prompt`), with the registry's `custom-title`
rule folded in: a `/rename` title wins over an AI title or an agent name, and a session with no title is named by
its first prompt, cut to 60. Contract: `fleet/docs/session-index.md`, section 2.3. Stdlib only, no fleet imports.
"""
import glob
import json
import os
import re

import fleet_history as hist

SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$")
SOURCE_OF = (("name_custom", "custom"), ("name_ai", "ai"), ("name_agent", "agent"))


def cut(text, n):
    """The registry's cut: one space for each run of white space, a longer text is n-1 characters plus an ellipsis."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _prompt_of_hook(hook):
    """The prompt a UserPromptSubmit hook carries, when it is what a person typed."""
    p = hook.get("prompt") if isinstance(hook, dict) else None
    if not isinstance(p, str) or not p.strip():
        return None
    return hist.human_prompt({"type": "user", "message": {"role": "user", "content": p}})


def session_facts(transcript_path, *, event, hook):
    """{name, name_source, first_prompt, last_prompt, last_answer} of a session, from the transcript's end (names,
    the newest turn) and start (the first prompt). A key is left out when the transcript does not hold it."""
    hook = hook or {}
    out = {}
    tail = list(hist.records(transcript_path, tail=hist.TAIL_BYTES)) if transcript_path else []
    names = hist.newest_names(tail)
    first = None
    if transcript_path:
        for rec in hist.records(transcript_path, head=hist.HEAD_BYTES):
            first = hist.human_prompt(rec)
            if first:
                break
    last_prompt = last_answer = None
    for rec in tail:
        p = hist.human_prompt(rec)
        if p:
            last_prompt, last_answer = p, ""
            continue
        a = hist.assistant_text(rec)
        if a and last_prompt is not None:
            last_answer = a
    typed = _prompt_of_hook(hook) if event == "prompt" else None
    if typed:
        last_prompt, last_answer = typed, ""
        first = first or typed
    for col, src in SOURCE_OF:
        if names.get(col):
            out["name"], out["name_source"] = cut(names[col], 200), src
            break
    else:
        if first:
            out["name"], out["name_source"] = cut(first, 60), "prompt"
    if first:
        out["first_prompt"] = cut(first, 300)
    if last_prompt is not None:
        out["last_prompt"] = cut(last_prompt, 200)
        out["last_answer"] = cut(last_answer, 200)
    return out


# ---------------------------------------------------------------- env tail's rule

def _entries(path):
    out = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        pass
    return out


def _prompt_text(e):
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return None
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if len(parts) != len(content):
            return None
        content = "\n".join(parts)
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    return text


def _answer_text(e):
    if e.get("type") != "assistant" or e.get("isSidechain"):
        return None
    content = (e.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text").strip()
        return text or None
    return None


def turns(transcript_path, n=20):
    """The last n turns, oldest first: each prompt, and the text of its answers joined (env `tail`'s rule)."""
    out = []
    for e in _entries(transcript_path):
        p = _prompt_text(e)
        if p:
            out.append({"role": "user", "text": p, "at": e.get("timestamp")})
            continue
        a = _answer_text(e)
        if a and out:
            if out[-1]["role"] == "assistant":
                out[-1]["text"] += "\n\n" + a
                out[-1]["at"] = e.get("timestamp") or out[-1]["at"]
            else:
                out.append({"role": "assistant", "text": a, "at": e.get("timestamp")})
    starts = [i for i, t in enumerate(out) if t["role"] == "user"]
    return out[starts[-n]:] if n and len(starts) > n else out


def find_transcript(sid, home=None):
    """The newest transcript of sid in any Claude config folder of this machine, or None."""
    if not isinstance(sid, str) or not SID_RE.match(sid):
        return None
    home = home or os.path.expanduser("~")
    dirs = [os.path.join(home, ".claude", "projects")] + sorted(glob.glob(os.path.join(home, ".claude-*", "projects")))
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg and home == os.path.expanduser("~"):
        dirs.insert(0, os.path.join(cfg, "projects"))
    found, seen = [], set()
    for d in dirs:
        real = os.path.realpath(d)
        if real in seen:
            continue
        seen.add(real)
        found += glob.glob(os.path.join(glob.escape(d), "*", sid + ".jsonl"))
    return max(found, key=os.path.getmtime) if found else None
