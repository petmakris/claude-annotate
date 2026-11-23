# Decks

One folder per deck, named `YYYY.MM.DD-Short-Slug/`, holding `YYYY.MM.DD-Short-Slug.html`
(the deck, named after its folder), `notes.md` (the talk plan), `assets/` (editable
originals of anything embedded) and, when you export, the regenerated `.pdf` and `png/`.

**Reference deck:** none yet. Once a deck here is the one new decks should look like,
name its folder on this line; the `slides` skill reads it before writing slides.

Rules:

- Nothing else at the top level of a deck folder — drafts and studies go in `assets/`.
- Decks embed their own content: every image as a `data:` URI, the framework and theme
  as inlined snapshots.
- A folder ending in `-working-draft` is local-only and never published.
- `python3 export-pdf.py` regenerates every `.pdf` and `png/`; never hand-edit either.
