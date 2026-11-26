# tools/promo: the recorder kit for the README clips

Every animated WebP in `docs/img/` is made by a script in `clips/`, so a clip
can be made again when the UI changes: `uv run tools/promo/clips/<id>.py`.
Nothing here is part of the plugins or the test suite. It runs on Linux and
macOS.

| File | What it does |
|---|---|
| `rec.py` | drives a real page with Playwright and takes one 2x PNG per step; a drawn cursor glides (eased, slightly curved) and shows a ring on a click; a hold is a longer delay on the last frame, not more frames |
| `encode.py` | frames to one animated WebP with `img2webp` (lossy q70, `-mixed`, a delay per frame), same frames merged, EXIF and XMP stripped |
| `termcast.py` | `capture` runs a real command once in a pty and keeps its output with timings; `page` replays it in xterm.js 5.5.0 (fetched once into the scratch folder); `record_cast` records the replay with `rec.py` |
| `rekey.py` | swaps only the names, paths and ids a mapping file lists; refuses to touch numbers |
| `scan.py` + `deny.txt` | the privacy gate: source files, OCR of every distinct frame (ocrmac on macOS, tesseract elsewhere), WebP metadata |
| `sheet.py` | one contact sheet page of every final clip |
| `daemon.py` | a webcompanion daemon of the clip's own, on a scratch HOME and port |
| `clips/_smoke.py` | a 2 s glide and click that proves the kit end to end |
| `fixtures/` | the invented projects, plans, answers and worlds the clips share (`fixtures/README.md`) |

## Install once

    sudo apt-get install -y webp tesseract-ocr     # macOS: brew install webp
    uv run --with playwright playwright install chromium

## The rules every clip follows

- Made-up data only: invented projects (`acme-billing`, `shop-app`), people
  (`Dana Example`), machines (`laptop`, `build-box`). No real person, company,
  ticket key, host, session path or token in a frame, caption or fixture.
- A clip that needs webcompanion starts its own daemon (`daemon.py`) on a
  scratch HOME and its own port, and stops it by PID. It never talks to the
  daemon a person uses every day.
- Raw frames, casts and contact sheets stay in the scratch folder
  (`rec.scratch_root()`: `$PROMO_SCRATCH`, else `.scratch/promo` beside the
  checkout, else the system temp folder), never in the repo.
- Terminal output is captured from a real run, never typed by hand. What is
  scripted (the Claude side of a round, a typed command line) is said in the
  clip's section of `docs/SHOTLIST.md`.
- `scan.py` passes on the clip's sources and its final `.webp` before it is
  committed.
- 800 px wide (hero 880), 10 to 12 fps; size caps P0 600 KB, P1 450 KB,
  P2 300 KB. On a flat background lossy q70 can leave faint trails where the
  cursor was: look at the last frames, and encode with `--near-lossless 40`
  when they show (about twice the size). When a frame changes the whole
  layout, lossy encoding can let the frame before show through where pixels
  match; near-lossless or a darker ground fixes it. `--lossless` is exact.

## A clip, in outline

    # /// script
    # dependencies = ["playwright", "pillow"]
    # ///
    import sys; from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from rec import Recorder, frames_dir
    from daemon import Daemon
    from encode import encode

    with Daemon(".scratch/home-ca01", 19120) as d, Recorder(frames_dir("ca-01")) as r:
        d.run(["claude-annotate", "push", "--blocks", "...", "--cwd", "..."])
        r.goto(d.url("/s/<slug>/"))
        r.hold(1.0)
        r.click("text=2 million rows")
    encode(frames_dir("ca-01"), "docs/img/hero.webp", width=880)

## Ports

Every server a clip starts listens on a port of its own. A batch job uses the
ports its job prompt gives it; the kit's own spikes used 19100 to 19119.

## Things the clips ran into

- A clip that changes HOME keeps `PLAYWRIGHT_BROWSERS_PATH` pointing at the
  real browser cache, or Playwright finds no Chromium.
- `tools/canvas.py build` first updates the checkout to the latest main; set
  `CLAUDE_ANNOTATE_UPDATED=1` to skip that.
- `draw.py claim` and `canvas.py build` print a link on port 3080 under a
  scratch HOME. The session itself is on the clip's own daemon: use its port.
- A watcher ends after one event. Ack every left-over event before recording
  (`Daemon.ack_all`).
- `journey.py` lists only comments whose `app` matches the register record:
  a canvas's `comments.canvas` must be the app name.
- `webcompanion` has no `list` command. Forget a session with
  `webcompanion forget --sid <slug> --kind <kind> --force`.
- A key pressed through `frame_locator(...).locator("body").press()` does not
  reach a window keydown handler inside an iframe. Focus the frame's window and
  use `page.keyboard`. `record_cast` drives the main page only, not an iframe.
- OCR can misread the loopback address by one digit, and the IP pattern then
  flags it. Rekey the address to `localhost` in terminal clips.
- Pillow reads 0 ms for every frame of these WebP files. Frame times come
  from `webpmux -info` (`sheet.py` does this).
- `Recorder` always starts its own browser. To record a page you already
  hold (VS Code over CDP), subclass it, as `clips/ca-17-show-diff.py` does.
