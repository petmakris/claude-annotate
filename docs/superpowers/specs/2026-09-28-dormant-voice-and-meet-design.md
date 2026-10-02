# Dormant voice for /talk, and /meet — a meeting assistant that speaks only when named

Date: 2026-09-28. Status: approved direction, spec for review.

## Why

GPT-Live is billed for every second a session is open ($0.05 a minute), whether anyone is
talking or not. Two uses make that the wrong shape:

- **/talk while thinking.** Leaving a call open for five or ten minutes of thought costs
  the same as talking through them, and the idle timer ends the call instead.
- **A meeting assistant.** An hour-long meeting where the assistant speaks twice would pay
  for sixty minutes of a model built to converse, and that model would also have to be
  trusted to stay silent through an hour of other people's talk.

The fix is one mechanism shared by both skills: a **dormant** state in which the page
listens with free on-device speech recognition and no GPT-Live session exists, and a
**wake** that opens a GPT-Live session seeded with what was said, so the conversation
continues with the full live experience (interruptions, turn-taking) the moment it is
wanted, and goes dormant again when it is quiet.

Two pieces, built in order:

1. **Dormant mode for /talk** (the shared mechanism).
2. **/meet** on top of it: dormant by default, woken only by its name, silent observer
   instructions while live, meeting-length calls, the stage on a projector.

## Grounding (measured on this Mac, 2026-09-28)

- `parakeet-mlx` (model `mlx-community/parakeet-tdt-0.6b-v3`) installs with
  `uv --with parakeet-mlx` on an Apple M5 Pro and transcribed a 196-second, five-voice
  synthetic meeting in about 2.6 s warm (40 s the first time, downloading the model).
- It heard "Nova, what do you think about lowering the retry limit from five to three"
  exactly, and kept "Nora" distinct.
- Chrome's own on-device Web Speech recognition exists (`processLocally`) but is disabled
  or broken on macOS in current Chromium issues, so the page does not rely on it.
- The GPT-Live silence spike (a live session told to stay silent through a meeting) could
  not run: the OpenAI account had no credits. /meet no longer depends on that property,
  because GPT-Live is only connected after the name is heard.

## States

| State | Audio path | GPT-Live session | Cost |
|---|---|---|---|
| `live` | browser ⇄ GPT-Live over WebRTC, as today | open | $0.05/min |
| `dormant` | browser mic → PCM over a WebSocket → `talk.py` → local recognizer | none | nothing |
| `waking` | recognizer keeps running; page negotiates a new session | being created | from open |

Transitions:

- **live → dormant** when, for `--dormant-after` seconds (default 45; `0` disables
  dormancy), nobody has spoken (no input transcript), the voice has said nothing, no turn
  is waiting on the brain, and the brain is not working. `talk.py` closes the GPT-Live
  session itself (sideband close), tells the page, and the page stops the peer connection
  and starts streaming PCM.
- **dormant → waking**
  - /talk (`--wake speech`): the recognizer produces a non-empty final segment of at least
    two words. A cough or a single "hm" does not wake it.
  - /meet (`--wake name`): a final segment contains the wake name, matched as a whole word
    against the name and its configured sound-alikes, case-insensitively.
- **waking → live** when the new session is up. Its instructions carry the dormant
  transcript since the previous live session (at most the last 6,000 characters, the
  limit the rejoin path already uses), and the wake segment is appended as the words that
  woke it, marked "just said, answer this", so the voice delegates immediately rather
  than greeting.

The first live session of a /talk call starts exactly as today (Start button, greeting).
A /meet call starts dormant after Start and never greets.

## Components

### `skills/talk/ear.py` (new): the local recognizer

A small module, imported by `talk.py` and loaded only when dormancy is enabled.

- Accepts 16 kHz mono 16-bit PCM frames.
- A simple energy gate with hangover splits speech into utterances. An utterance ends after
  700 ms below the gate, or at 15 s whatever happens, so a monologue still produces
  segments.
- Each finished utterance is transcribed with `parakeet-mlx`, off the event loop in one
  worker thread, and becomes a segment `{text, start, end}`.
- The model loads once per call, lazily, at the first dormant period. The first load
  downloads it: `--doctor` reports whether it is cached and offers the one-line warm-up
  command.
- `spot_name(text, names) -> bool`: the whole-word, case-insensitive match used for
  `--wake name`. It is a pure function with its own tests.

`parakeet-mlx` joins `talk.py`'s uv script dependencies with a platform marker
(`sys_platform == 'darwin' and platform_machine == 'arm64'`). On any other machine
dormancy is unavailable: `--dormant-after` is forced to 0 with a printed notice, and /meet
refuses to start.

### `talk.py` changes

- New arguments:
  - `--dormant-after SECONDS`, default 45 for /talk;
  - `--wake speech|name`;
  - `--name NAME` (the wake name, default `Nova`);
  - `--sounds-like "Noa,Nover"`, extra spellings the recognizer may produce;
  - `--mode talk|meeting`.
- `LiveController` gains:
  - a `state` field;
  - `sleep()`, which closes the session with the reason `dormant`, and must not count as
    a dropped connection or open the rejoin window;
  - `wake(segment)`;
  - a list of dormant segments, which also go into the transcript and into `said` for the
    next brain turn.
- The idle-end rule (`--idle-minutes`) no longer ends a call while dormancy is on:
  - a dormant /talk call ends only at `--max-minutes` or when the user ends it;
  - /meet raises `--max-minutes` to 120.
- `session_config()` builds the seeded instructions from the dormant transcript and the
  wake segment, reusing the rejoin path's conversation block.
- New WebSocket route `/api/ear`, authorised with the call token, carrying binary PCM
  frames from the page. Opening it while live is refused.
- `/api/state` gains `state` (`live`/`dormant`/`waking`), the last few dormant segments,
  and for /meet the wake name.

### The call page

- **Going dormant.** On `state: dormant` the page closes the peer connection and captures
  the mic with an `AudioWorklet`. It downsamples to 16 kHz, keeping the same device choice
  and echo cancellation settings, and streams frames to `/api/ear`. The orb reads
  "Dormant · listening on this Mac · free", and a small line shows the last dormant
  segment, so it is visible that recognition is working.
- **Waking.** On `state: waking` the page stops streaming. It then creates the session
  through the existing `POST /api/session` flow, as Rejoin does today.
- **Waiting.** While dormant the Start/Rejoin button is replaced by "Wake now", for the
  user who wants the live voice without speaking first.
- **Ending.** Ending the call works from any state.

### `/meet` (new skill, `skills/meet/SKILL.md`)

- It launches `talk.py --llm session --mode meeting --wake name --name <name>
  --dormant-after 20 --max-minutes 120`, with `--code` and the stage as /talk.
- Meeting-mode voice instructions:
  - The voice is a participant named `<name>` in an in-person meeting.
  - It answers only the person who named it, keeps answers to a few sentences, and never
    greets or backchannels.
  - It hands every named request to the brain, and says nothing while waiting.
  - After answering it stays silent. Follow-up questions within the same live window
    ("and what about…") are answered without the name being repeated. The window closes
    after 20 s of quiet, and then the name is required again.
- The brain's side: `SKILL.md` tells this Claude session that a meeting turn's `said` is
  the room's talk since the last turn, from several unnamed speakers. It should answer the
  question addressed to `<name>` using that context and put anything visual on the stage.
  The existing rules on what a voice turn may do apply unchanged: local files yes, outside
  world only after a typed yes.
- **Layout.** A `?view=projector` query on the call page hides the captions and controls
  behind a thin status bar and gives the stage the whole screen. The status bar shows
  "Listening · say '<name>' to ask", so everyone in the room can see it is on.
- **Recap.** At the end the transcript (dormant segments included) gets the same recap
  flow as /talk, framed as meeting notes: what was asked of `<name>`, what it answered,
  and what it showed.

## What is deliberately not in this version

- Telling speakers apart. Segments carry no speaker names, and the brain reads them as one
  room.
- Teams or other remote meetings, which need meeting audio routed in and the voice routed
  out.
- A dormant wake word for /talk. /talk wakes on any speech; `--wake name` works there too
  if wanted.
- Keeping audio. Dormant PCM is transcribed and discarded, and only text is kept.

## Failure handling

| Situation | Behaviour |
|---|---|
| Not Apple Silicon, or `parakeet-mlx` fails to import | /talk runs as today with dormancy off and says so once; /meet refuses to start with the reason. |
| The model is not downloaded yet | The first dormant period shows "preparing local listening (one-time download)" and wakes on speech energy alone until the model is ready. |
| The session fails to open on wake (network, credits) | The page shows the error and stays dormant, still listening. The wake segment is kept for the next attempt, which follows the next wake or a press of "Wake now". |
| The recognizer falls behind (more than 30 s of audio queued) | The oldest queued audio is dropped, with a transcript note saying so. |
| The page closes while dormant | Same as today: the call ends after the rejoin window. |

## Testing

- `ear.py`:
  - `spot_name` covers whole words, case, sound-alikes, "Nova" against "Nora" and
    "Novak", and punctuation around the name;
  - segmentation uses synthetic PCM (tone bursts and silence) with the transcriber faked.
- One recognizer test runs the real model on a short `say`-generated clip that contains
  the name. It skips unless `parakeet-mlx` is importable and the model is cached.
- The `talk.py` state machine uses a fake clock and faked session and recognizer:
  - live → dormant after `--dormant-after` of quiet;
  - no sleep while the brain works or a turn is pending;
  - wake on two or more words (talk) or the name (meeting);
  - the seeded instructions contain the dormant transcript and the wake segment;
  - `sleep()` does not open the rejoin window;
  - dormant calls do not hit the idle end.
- `/api/ear` checks: authorisation, refusal while live, and frames reaching a fake ear.
- An end-to-end browser test, skipped without Playwright or OpenAI credit:
  - fake-mic Chrome plays a clip with a pause of `--dormant-after` + 5 s followed by "Nova,
    what is two plus two";
  - the test asserts the state goes live → dormant → live, and that a brain turn arrives
    carrying the wake words.
- A manual check by the user: one real /talk call left idle for five minutes, confirming
  on the OpenAI usage page that the idle minutes were not billed.
