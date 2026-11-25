# The server, its service and the activity hook

## A call stays open while this session listens

- A call has no time limit while its doorbell is armed.
- The user can stay silent for hours, or close the page, and open the same link later to carry on.
- Closing the page never ends the call. Only End call, `--end`, or an hour with no turn and no doorbell does.
- So always re-arm the doorbell after an answer.

## Restarting the server

- A call outlives the server process that holds it.
- When the server stops (a crash, a `kill`, a restart to load new code), its open calls are not ended.
- The next server on the port carries each one on with the same link, call id, conversation and stage.
- The page shows "Reconnecting to the call..." and then "Reconnected."
- `talk_client.py` waits up to 90 seconds for that server, starting one itself after a few seconds if nobody else has.
- So a doorbell or reply keeps its `--call` id through a restart, and you do not open a new call.

## The launchd service

- On a Mac the server can run as a launchd agent, `dev.talk`: `uv run --script "$SKILL_DIR/talk.py" --install-service`, run from a shell that has the speech settings.
- The plist keeps `TALK_AZURE_KEY_COMMAND`, the region and the addresses.
- It refuses to install without a key command unless `TALK_SPEECH=voicestudio`.
- From then on no launch or doorbell starts a server itself: each asks launchd.
- So a session opened before the speech settings changed cannot start a server without them.
- Install it again after those settings change. `--uninstall-service` goes back to servers started by launches.

## Loading new code

- `uv run --script "$SKILL_DIR/talk.py" --restart` loads new code into a server that holds calls.
- With the service installed, `--restart` and a launch that finds older code restart it through launchd and hand the calls over.
- A server on code from before the hand-over cannot hand its calls over, so `--restart` leaves it running while it holds an open call and says so.

## The activity hook

- `hooks/talk-activity.sh` lists this session's tool calls on the call page while it works.
- The plugin registers it through its `hooks/hooks.json`, so nothing needs installing.
- Remove any older copy registered in `~/.claude/settings.json`, or every event shows twice.
- It exits at once when no call is running and never fails a tool call.
- Each session shows only on the call its doorbell names, so other sessions on the machine never appear.
