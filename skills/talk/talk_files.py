"""Where a running talk server and its calls are found. One server per port holds every open call; it
writes `servers/<port>.json` (its port and token) and one `calls/<call id>.json` per call (the port,
that call's token). A server only ever writes or removes its own files, so a second server on another
port (a test run) never hides the first one or its calls. Each open call also keeps `state/<call id>.json`,
what it has said and shown so far: a server that replaces another on the same port takes over its open
calls from these, under the same id and token, so their pages and sessions carry on.

talk.py writes them, talk_client.py reads a call's file, and the activity hook reads the server's.
`TALK_RUN_DIR` moves the folder, which the tests use.
"""

import json
import os
from pathlib import Path

CALL_FORMAT = 2


def run_dir() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "talk"
    return Path(os.environ.get("TALK_RUN_DIR") or data / "run")


def server_file(port: int) -> Path:
    return run_dir() / "servers" / f"{int(port)}.json"


def legacy_server_file() -> Path:
    """Where a server on code from before servers/<port>.json wrote its file: one for every port."""
    return run_dir() / "server.json"


def servers() -> list[dict]:
    """Every server's file, whether or not that server still answers."""
    try:
        paths = sorted((run_dir() / "servers").glob("*.json"))
    except OSError:
        return []
    return [data for path in paths if (data := read(path))]


def calls_dir() -> Path:
    return run_dir() / "calls"


def call_file(call_id: str) -> Path:
    return calls_dir() / f"{Path(call_id).name}.json"


def state_file(call_id: str) -> Path:
    """What a call has said and shown so far, for the next server on its port to carry on with."""
    return run_dir() / "state" / f"{Path(call_id).name}.json"


def adoptable(data: dict | None) -> bool:
    """A call file a later server can take over: written by code that saves its state, and not ended."""
    return bool(data) and data.get("format") == CALL_FORMAT and not data.get("ended")


def read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_private(path: Path, data: dict) -> None:
    """Readable by this user only, since it holds a token. Replaced whole, never half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def remove_if_pid(path: Path, pid: int) -> None:
    """Remove a file only if this process wrote it: a newer server may have written its own since."""
    data = read(path)
    if data is not None and data.get("pid") == pid:
        path.unlink(missing_ok=True)


def mark_ended(path: Path, pid: int) -> None:
    """Say in a call's file that the call has ended, if this process wrote it."""
    data = read(path)
    if data is not None and data.get("pid") == pid and not data.get("ended"):
        write_private(path, {**data, "ended": True})


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def call_ids() -> list[str]:
    """Every call file's id, open or not."""
    try:
        return sorted(p.stem for p in calls_dir().glob("*.json"))
    except OSError:
        return []


def open_calls() -> list[str]:
    """The calls a session can still talk in: not ended, and their server process is alive."""
    try:
        paths = sorted(calls_dir().glob("*.json"))
    except OSError:
        return []
    return [p.stem for p in paths
            if (data := read(p)) is not None and not data.get("ended") and pid_alive(data.get("pid"))]
