# Fixtures the promo clips share

Everything here is invented. A batch adds its own under `fixtures/<clip id>/`.

| Folder | What | How to use it |
|---|---|---|
| `acme-billing/` | a small billing repo (invoices in cents, migration 0042), one commit by Dana Example | `sh make_repo.sh <dest>`: same sha every run |
| `shop-app/` | a shop repo: `main`, and `checkout-retry` one commit on top (3 files changed, 1 added) | `sh make_repo.sh <dest>`; for show-diff, stage code boards, talk `--code` |
| `annotate/plan.v1.blocks.json`, `plan.v2.blocks.json` | the hero plan: part 3 says 2 million rows, v2 rewrites only part 3 for 40 million rows and an online job | push v1, comment on part 3, push v2 with `--slug` (`annotate/ui-strings.md` has the round in order) |
| `annotate/decisions-mockup.blocks.json` | one decision (where the backfill runs, three ways, one suggested) and a mockup with working toggles | ca-02 and ca-04 |
| `annotate/ui-strings.md` | the words the annotate page shows today, read from the live page | write beats from this, not from older loops |
| `answers/` | talk answers with invented names where the originals name a work codebase | `answers/README.md` |
| `fleet/` | a fleet world with invented machines, members and to-dos | `fleet/README.md` |

Demo files in the repo that still hold names from a real work codebase are
listed in the foundation job's report; clips never use them as they are.
