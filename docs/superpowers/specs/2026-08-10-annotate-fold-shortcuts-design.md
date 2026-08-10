# Annotate: fold-all / unfold-all chords + bigger fold control

Date: 2026-08-10
Status: approved (chords chosen over single keys; chevron restyle added)

## Goal

Two additions to the annotate reading page:

1. Global keyboard shortcuts to collapse and expand **all** sections at once,
   using the user's VS Code fold bindings — the macOS defaults, since their
   `keybindings.json` has no custom fold entries: **⌘K ⌘0** folds all,
   **⌘K ⌘J** unfolds all.
2. Make the per-section fold chevron a full-size round button, the same
   26×26px family as the header's trash/check/comment/eye actions, so it is
   easy to hit.

## 1. Chord shortcuts

**Behavior.** A global `keydown` listener in `skills/annotate/static/script.js`
implements a two-step chord:

- **⌘K** arms the chord. `preventDefault()` fires immediately so Chrome does
  not focus the address bar. A small transient pill (bottom corner) shows
  "⌘K …" while armed — the role VS Code's status bar plays.
- While armed, **⌘0** collapses every section; **⌘J** expands every section.
  Both `preventDefault()` (⌘0 would otherwise reset browser zoom).
- Any other key, or a ~2 s timeout, silently disarms. Escape disarms too.
- The chord is ignored while the user is typing — same guard as the existing
  "g" composer shortcut (`script.js` ~1319): input, textarea, or
  contentEditable focused.

**State.** Fold-all / unfold-all iterate the rendered sections and reuse the
existing per-section machinery: call `applyCollapsed(section, chev, v)` and
write the same `annotate.collapsed:<responseId>:<blockId>` localStorage key
the chevron click writes. A fold-all therefore survives reload, and clicking
one chevron afterwards toggles just that section. No new state concept.

**Where.** One new self-contained IIFE block in `script.js`, placed next to
the "g" shortcut block. Pill styles go in `style.css`. No server or HTML
changes.

## 2. Bigger fold control

Restyle `.card-chevron` (`style.css:615`) to match `.hover-actions button`
(`style.css:276`): 26×26px, `border-radius: 50%`, 1px dashed
`var(--border)`, `background: var(--surface)`, dim color strengthening on
hover. Keep the existing glyph (▸/▾) and all behavior: only the chevron
toggles the fold, the rest of the header keeps its current roles. Header
layout must still align (the chevron grows from 14px wide to 26px; check
the card-head flex row still lines up).

## Out of scope

- No per-section keyboard fold, no fold levels (⌘K ⌘1…), no rebinding UI.
- No change to which element toggles a single section.

## Testing

Browser smoke test alongside the existing ones (same harness as
`tests/test_smoke_reading_chrome.py`):

- Open a workspace with ≥3 sections.
- Send ⌘K then ⌘0 → every `section.block.card` has class `collapsed`.
- Send ⌘K then ⌘J → none has `collapsed`.
- Focus a comment textarea, send the chord → nothing folds.
- Assert the chevron button's rendered size is 26×26.
