#!/usr/bin/env python3
"""Claude Code hook: tell a running talk call what the session is doing, one tool call at a time.

Reads the hook event on stdin. Does nothing, quickly and silently, when no call is running.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talk_files  # noqa: E402

# The doorbell's command, with its path quoted or not, and the call it names.
DOORBELL = re.compile(r"talk_client\.py['\"]?\s+doorbell\b")
CALL_ARG = re.compile(r"--call[= ]+['\"]?([A-Za-z0-9_-]+)")
HIDDEN = {"ToolSearch", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList"}
# Events that end one tool call (it succeeded, failed, or was denied), and events that end them all.
END_EVENTS = {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}
STOP_EVENTS = {"Stop", "StopFailure"}
KEY_ARGS = ("issueIdOrKey", "query", "jql", "cql", "pageId", "channel", "url", "slug", "q")


def _name(path: str) -> str:
    return Path(path).name or path


def _service(server: str) -> str:
    for prefix in ("plugin_", "claude_ai_"):
        server = server.removeprefix(prefix)
    words = []
    for word in server.replace("-", " ").split("_"):
        if word and word not in words:
            words.append(word)
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def describe(tool: str, args: dict) -> str | None:
    if tool in HIDDEN:
        return None
    if tool == "Bash":
        command = str(args.get("command", ""))
        if "talk_client.py" in command:
            return None
        return str(args.get("description") or command)[:80]
    if tool == "Read":
        label = f"Reading {_name(str(args.get('file_path', '')))}"
        offset, limit = args.get("offset"), args.get("limit")
        if offset and limit:
            label += f" lines {offset}–{int(offset) + int(limit) - 1}"
        return label
    if tool == "Grep":
        label = f'Searching for "{args.get("pattern", "")}"'
        return label + (f" in {_name(str(args['path']))}" if args.get("path") else "")
    if tool == "Glob":
        return f"Finding files {args.get('pattern', '')}"
    if tool in ("Edit", "Write"):
        return f"{'Editing' if tool == 'Edit' else 'Writing'} {_name(str(args.get('file_path', '')))}"
    if tool == "WebSearch":
        return f"Searching the web for {args.get('query', '')}"
    if tool == "WebFetch":
        return f"Opening {args.get('url', '')}"[:80]
    if tool == "Agent":
        return f"Asking a helper: {args.get('description', '')}"
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        label = f"{_service(parts[1])}: {parts[-1]}"
        key = next((str(args[k]) for k in KEY_ARGS if args.get(k)), "")
        return f"{label} {key}"[:80].strip()
    return tool


def main() -> int:
    # A server holds every call on its port. It matches this event to the call whose doorbell this
    # session armed, and ignores sessions that answer no call. Usually there is one server; a test
    # server on another port gets the event too, and ignores it.
    states = talk_files.servers()
    if not states:
        return 0
    try:
        event = json.load(sys.stdin)
        tool, args = event.get("tool_name", ""), event.get("tool_input") or {}
        name = event.get("hook_event_name")
        phase = "stop" if name in STOP_EVENTS else "end" if name in END_EVENTS else "start"
        body = {
            "session_id": event.get("session_id", ""),
            "phase": phase,
            "tool": tool,
            "label": describe(tool, args) if tool else None,
            "doorbell": tool == "Bash" and bool(DOORBELL.search(str(args.get("command", "")))),
        }
        if body["doorbell"]:
            found = CALL_ARG.search(str(args.get("command", "")))
            body["call"] = found.group(1) if found else ""
    except Exception:
        return 0
    for state in states:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{state['port']}/api/activity", method="POST", data=json.dumps(body).encode(),
                headers={"X-Talk-Token": state["token"], "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=0.5).close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
