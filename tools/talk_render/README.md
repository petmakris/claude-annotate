# talk_render: render a /talk answer the way a user sees it

Renders one /talk answer the way a user sees it, from any claude-annotate checkout, with no speech cost.

    uv run --with playwright python tools/talk_render/render.py --repo <checkout> --answer <file> --code <folder> --out <dir> \
        [--question "what the user asked"] [--topic T] [--pace 1.0] [--no-phone] [--no-dark]

- `--answer`: the answer text in talk's tag language (`[[show table | T]] ... [[/show]]`, `[[point: ...]]`, `[[next]]`, `[[key: ...]]`).
  `answers/` holds demo.md answers (`demo_answer.py <repo> --list` lists them; `demo_answer.py <repo> N` prints one).
- `--code`: the folder boards read from (`talk.py --code`); the stage's session is created for it.
- `--question`: typed on the call first, so the answer is a reply to that turn (doorbell + reply). Without it the answer goes in with `talk_client.py say`.
- `--pace`: speaking-time scale of the silent voice (1.0 about 0.4 s a word; 0.6 is quick and still readable).
- Takes 40 to 120 s. Several renders can run at once (each has its own port, run folder and stage session).

## What it does
1. Starts `<repo>`'s own talk.py as a server on a free port (never 8766, never launchd) through `serve.py`, which puts `fake_speech.py`
   (silent WAV, word timings like Azure's) in as the speech engine before talk.py loads. Env of the child is cleaned of every `TALK_*`/`AZURE_*`,
   so the machine's service address and Azure key command never reach it. State lives in `<out>/_run/`.
2. Opens the call with `<repo>`'s launcher (same `serve.py`, `--topic ... --no-open`).
3. Opens the call page in Playwright's Chromium (1440x900 light), sends the answer while the page is open (so it plays by itself, as a new answer does),
   and plays it through. At every moment a board comes to the front, at every `[[point]]` (and other frame cue), it pauses the audio, waits 0.9 s for the
   stage's animation, takes a shot, resumes. After the end it waits 2.6 s (the page holds the last frame 1.5 s) and takes the at-rest shot.
   A stop card (`[[check]]`, `[[guess]]`...) is shot and passed with Play.
4. Replays the same answer at 390x844 (2x, touch, `p*` shots, same moments) and once dark at rest at 4x speed (`k*`).
5. Ends its server, helper and browser by PID, and its stage session by sid (also on failure and on SIGTERM).

## Output in `--out`
`d##-board|point|stop|rest.png` desktop, `p##-...` phone, `k##-rest.png` dark; `frames.json` (list of
`{file, width, theme, t, caption: the sentence being said, board: {title, kind, answer}}`); `reply.txt` (what `talk_client.py` printed:
`sent` and every `board:` problem line); `console.txt` (page errors, console errors/warnings, failed requests, HTTP >= 400, from the page and the stage frame);
`_run/` (server.log, launch.txt, call files).

## Which code draws the stage
The stage page is served by the webcompanion daemon (port 3080) from the static folder that `<repo>/skills/stage/stage.py ensure_stage` registers
for that call's own stage session (`register_assets(sid, STATIC_DIR)`), so `<repo>`'s stage.js, lanes.js, map.js, stage.css are what is drawn, and the call page
(call.js, call.css) comes from `<repo>`'s talk server. Proven 25 Nov 2026: a scratch copy with a red `HARNESS-MARKER` rule added to stage.css showed it
in the shot; the copy is deleted. The daemon is only used, never restarted or reconfigured; the session it makes is ended at the end.

## Limits to know
- The audio is silent: the check is what is drawn and when, not how it sounds. Word times come from the length of each word, not a voice.
- While a moment is shot the audio is paused, so the panel shows the Play button; the stage is as it is while playing.
- Needs the webcompanion daemon up (talk itself needs it) and `uv`, with Playwright's Chromium installed.
- `serve.py` only replaces the engine; nothing in talk.py is patched.
