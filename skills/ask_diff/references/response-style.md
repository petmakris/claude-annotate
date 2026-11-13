# ask-diff — response style

Read this before composing any reply to a question on a diff line. The IDE
panel shows only the newest reply on a thread, and renders the patterns below
specially.

- **Self-contained synthesis.** Each reply should stand on its own as the
  answer to *all* questions asked so far on this anchor, not just the
  latest one. Absorb prior questions; do not assume the reader has scrolled
  back. The IDE surface renders only your most recent reply — older replies
  are stored for audit but not displayed.
- **Link references inline.** When you reference a specific file, method,
  or symbol from the code, render it as a markdown link whose target is
  the project-relative file path optionally followed by `:line`, e.g.
  `[forDashboard](src/main/java/.../OrderListService.java:18)`. For
  ticket IDs and external URLs, use a normal markdown link with the
  absolute URL.
- **Short.** 2–4 sentences in most cases. Answer the question; don't
  review the whole PR.
- **Code-aware.** Reference specific lines, variable names, and functions
  from the diff.
- **Suggest, don't ask.** When a fix is warranted, show it as a markdown
  code block immediately. The user copies it themselves.
- **Honest uncertainty.** If you need more context, name exactly what you
  need ("I'd need to see `<file>:<function>` to know"). Don't hedge.
- **No general reviews per event.** Each wake-up is one question on one
  anchor. Answer that; let the user iterate.
- **Headline title.** Pass a `title` to `append_thread`: plain text (no
  markdown), ≤ ~6 words / 60 chars, a noun phrase naming the thread's topic
  (e.g. "Null check on portfolio lookup", "Why the fee branch is skipped").
  Refresh it each answer so it stays accurate as the synthesis absorbs new
  questions. The IDE panel shows this as the row's title.
- **Structure, don't just write prose.** The IDE renders four markdown
  patterns specially — use them, don't just write one dense paragraph:
  - **Opening verdict.** If the reply has a one-line takeaway, open with a
    block quote whose first character is a severity symbol: `✓` (agrees /
    correct), `!` (critical), or `⚠` (important). It renders as a colour-coded
    pill instead of quoted text, and also drives the thread list's severity
    dot (see `AnnotationsPanel.severityColor`) — so use it whenever the
    finding actually has one of those three severities, not decoratively. A
    second line in the same quote renders as a dimmer subtitle underneath.
  - **Section labels.** Use `####` to break the answer into named sections
    (e.g. `#### Why one method, not two`, `#### Evidence`) — it renders as a
    small-caps label with a trailing rule, not a fourth heading weight.
  - **Evidence as code, not inline chips.** When you're citing something
    provable — two call sites that differ by one argument, a stack trace,
    the shape of a fix — put it in a fenced code block rather than stringing
    inline `` `code` `` spans through a sentence. Inline code stays for
    naming a symbol mid-sentence; fenced code is for showing something.
  - **Later block quotes are asides.** Any `>` block that is *not* the
    opening line renders as an accent-tinted callout card, for a genuinely
    separate side note (e.g. "one thing this doesn't fix").

  Example:
  ````markdown
  > ✓ Correct and intentional
  > confirmed against the OpenAPI contract and the test file

  #### Why one method, not two

  `sendOrders` isn't defined in `HttpDatasourceHttpClient` itself — it comes
  from `CoreBankingOrdersContract` in the external `wp_integration_layer_contract`
  library. The contract already models a check and a real transmission as
  one endpoint with a `dryRun` flag, not two endpoints.

  #### Evidence

  ```java
  httpClient.sendOrders(BANK_ID_STRING, false, "fr", ...) // real send
  httpClient.sendOrders(BANK_ID_STRING, true,  "fr", ...) // pre-trade check
  ```

  > New at this boundary: `OrdersEndpointTimeoutClient` applies a dedicated
  > read timeout only to `/orders`, because this call now runs synchronously
  > while an advisor waits.
  ````
  Not every reply needs all four — a quick factual answer with no verdict and
  no aside is still fine as plain prose. Reach for structure when the reply
  actually has a verdict, distinct sections, or provable evidence to show.
