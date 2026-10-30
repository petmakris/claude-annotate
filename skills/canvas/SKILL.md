---
name: canvas
description: Show a set of screenshots (an app's screens, every state of a UI, a journey's boards, before and after) as one Figma-like canvas that pans and zooms, with comments pinned on the shots. Use whenever a session would otherwise hand-write an HTML page of screenshots, or when the user says "/canvas", "put the screenshots on a canvas", or asks to see a set of captured screens side by side. Only shows; each project keeps its own capture.
argument-hint: "<manifest.json> [--out DIR]"
allowed-tools:
  - Bash
---

# /canvas — screenshots on one canvas

`$SKILL_DIR` is this skill's base directory. Never hand-write a screenshot page: write a
manifest and build it with the viewer, so every canvas pans, zooms, loads and takes comments
the same way.

1. **Write the manifest** next to the images (`canvas.json`). Groups are the chapters or flows,
   in reading order; each board has a stable number (`#board-N` links and comments use it), or,
   where each group numbers its boards from 1, a stable `id` as well (`#board-<id>` and comments
   use it), a title, an optional caption, and its shots. Give a shot its size in CSS pixels and, for a
   full-page shot, the window it was taken in (`viewport`): the canvas draws that first screen,
   the click viewer the whole image. The full format is in `$SKILL_DIR/canvas.py`.

   ```json
   {
     "title": "Billpod journey", "subtitle": "petros-billpod", "id": "billpod",
     "groups": [{"name": "Overview", "boards": [
       {"number": 1, "title": "Nothing yet", "caption": "A new household, before any bill",
        "shots": [
          {"label": "Desktop", "file": "01-overview.png", "width": 1600, "height": 1000, "viewport": {"width": 1600, "height": 1000}},
          {"label": "Phone", "file": "01-overview.phone.png", "width": 390, "height": 1240, "viewport": {"width": 390, "height": 844}}]}]}],
     "comments": {"url": "https://journey-comments.main.okimotus.com", "canvas": "billpod", "name": "Billpod"}
   }
   ```

   To mark what changed since an earlier capture, give each board a `change` (`changed`,
   `unchanged`, `new`), each shot its `previous` image (and `diff`, the box that differs), and the
   manifest `changes` with `since` and the `removed` boards; the format is in `$SKILL_DIR/canvas.py`.
   The page then outlines changed and new boards, adds Changed only and a count to the toolbar, and
   opens a changed shot now, before or side by side. The project does the comparing.

   Leave `comments` out unless pins on the shots are wanted. Its `canvas` id is where they are kept
   in the journey-comments service on main; never reuse another canvas's id.

2. **Check and build** (Pillow makes the thumbnails):

   ```bash
   python3 "$SKILL_DIR/../../tools/canvas.py" check canvas.json
   uv run --with pillow "$SKILL_DIR/../../tools/canvas.py" build canvas.json --out ~/Outbox/<name>
   ```

   `--out` gets `index.html`, the images and `thumbs/`. Without it, the manifest's folder does.

3. **Share** the folder's page: `@devdomains share` on the first build. A later build goes to the
   same `~/Outbox/<name>` folder, so the link stays the same; never share it again under a new name.

The page: one surface for every board at one size, 4 to 6 to a line under each group's title;
two fingers or the wheel pan, a pinch or Ctrl + wheel zooms round the pointer, Fit all and 100 %
are buttons, the view is remembered, a toggle shows one shot label alone, a click opens the full
image. A project that cannot reach this repo vendors the empty page from
`python3 "$SKILL_DIR/../../tools/canvas.py" template -o viewer.html` and puts its data in itself.
