# walkthrough

Guided code tours, walked in IntelliJ. `/walkthrough <question>` generates 5–12
anchored steps; the IDE plugin (`ide-plugin`) walks the user through
them and posts per-step questions back for Claude to answer in place.

- Skill contract: `SKILL.md`
- No server of its own: `push.py` writes the steps document straight to the
  **webcompanion daemon** — one always-on service shared by every migrated
  skill and IDE plugin — as the session's `__steps__` item.
- Per-session state (the steps document, comment threads, the event queue)
  lives in the daemon's own session directories, not under the project being
  toured.

Run the tests from the repo root:

```bash
python3 -m pytest skills/walkthrough/tests/ -v
```
