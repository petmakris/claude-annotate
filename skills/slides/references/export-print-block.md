# What the export's print block does

Moved out of SKILL.md. Read it when an exported PDF looks wrong (fonts, extra pages, scaling) or when the print block sits somewhere unexpected in a deck's head.

### What the print block does, and why

```css
:root{--body:Helvetica,Arial,sans-serif!important}
body>*:not(.deck){display:none!important}
.deck{display:block!important;gap:0!important;zoom:1!important}
```

- **Helvetica is forced** because the on-screen `--body` stack ends in a generic
  `sans-serif` that macOS resolves to San Francisco, and Chrome cannot embed SF as a real
  font — it writes each glyph as an unhinted Type 3 procedure that most PDF viewers
  render badly. Helvetica embeds as TrueType. Georgia (`--head`) and Menlo (`--mono`)
  already do, so they are left alone. (The comment in `export-pdf.py` says the stack ends
  in `system-ui`; the decks now end in `sans-serif`, which resolves the same way.)
- **`body>*:not(.deck)` is hidden** because the harness script appends the present button
  to `<body>`. Only `.deck` is content.
- **`.deck` zoom is undone** because the script sets an inline zoom to fit the browser
  window, and that zoom would otherwise scale the printed page.

A consequence worth remembering: `Cmd+P` in the browser gives the same PDF, because the
rules are baked into the file rather than passed on the command line.

The `.html` never leaves the repo. `.pptx` is retired.
