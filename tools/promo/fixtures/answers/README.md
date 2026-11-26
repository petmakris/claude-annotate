# Talk answers for the promo clips

`tools/talk_render/answers/` holds the demo answers talk_render plays. The
promo clips use these copies instead wherever an original names a real work
codebase (found by `scan.py` in spike CA-A3, 26 November 2026):

| Answer | Use |
|---|---|
| `demo-before-after.txt` | this folder: the same board shape, shop-app names (checkout, order service, pricing module, tax service) |
| `demo-sequence.txt`, `demo-table.txt`, `demo-map.txt`, `demo-flowchart.txt` | the originals in `tools/talk_render/answers/`: they describe talk itself and name no work codebase |
| `r2b3-cmp.txt` | never: it repeats the work-codebase board; use `demo-before-after.txt` here |

Run talk_render with `HOME` set to the clip's scratch home (`daemon.py`), so
the stage session it registers lands on the clip's own daemon, not the one a
person uses every day.
