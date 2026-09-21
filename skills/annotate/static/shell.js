// annotate's page shell — the markup the old server used to print.
//
// Held as a line-continued template literal, NOT as a one-line JSON string.
// It used to be the latter, and the whole 8.6KB of markup lived on a single
// source line: unreadable in a diff, and unmergeable in practice. Two branches
// that each added one control to the header both edited "line 8" and conflicted
// on a 7KB escaped string that nobody can resolve by eye. Measured, on exactly
// that pair of branches.
//
// Every line below ends with a backslash, so no newline and no leading
// whitespace enters the string. The value is byte-identical to what this file
// has always exported — test_smoke_shell_source.py holds that invariant — while
// the source is ~90 diffable lines. Break lines only between tags.
export const SHELL_HTML = `\
<header class="page-header"><div class="header-title"><span class="header-emoji">📝</span>\
<span class="header-text" id="hdr-title"></span><span class="header-respid" id="hdr-respid"></span></div>\
<div class="header-actions"><div class="header-search">\
<svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\
<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>\
<input id="block-search" class="search-input" type="text" placeholder="Search blocks…" autocomplete="off" spellcheck="false" aria-label="Search blocks">\
<span class="search-kbd">/</span>\
<button id="block-search-clear" type="button" class="search-clear" aria-label="Clear search" tabindex="-1">&times;</button>\
</div>\
<button id="highlighter-toggle" type="button" class="icon-btn hl-btn" aria-pressed="false" title="Reading highlighter — drag over text to mark it read" aria-label="Reading highlighter">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 4.5l4 4L10 18H6v-4z"/>\
<line x1="4" y1="21" x2="20" y2="21"/></svg></button>\
<span class="icon-btn-wrap">\
<button id="menu-toggle" type="button" class="icon-btn menu-btn" aria-expanded="false" aria-controls="menu-pop" title="Menu" aria-label="Menu">\
<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="4" y1="7" x2="20" y2="7"/>\
<line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg></button>\
<div id="menu-pop" class="menu-pop" data-pane="root" role="dialog" aria-label="Menu" hidden>\
<div class="menu-pane" data-pane-name="root">\
<div class="menu-status" id="menu-status"><span class="menu-status-dot" aria-hidden="true"></span>\
<div class="menu-status-text"><div class="menu-status-title" id="menu-status-title">Checking…</div>\
<div class="menu-status-sub" id="menu-status-sub"></div>\
<div class="menu-resume" id="menu-resume" hidden>\
<p class="resume-hint">Paste this in any terminal to open <code id="resume-cwd"></code> and attach a live session here:</p>\
<div class="resume-cmd-row"><code id="resume-cmd" class="resume-cmd"></code>\
<button id="resume-copy" type="button" class="resume-copy-btn" title="Copy the command">Copy</button></div>\
<p class="resume-status" id="resume-status" aria-live="polite"></p></div>\
<div class="menu-readonly read-only-badge" title="This link can read the document but not change it.">&#128065; Read-only</div>\
</div></div>\
<div class="menu-sec">This response</div>\
<button id="composer-toggle" type="button" class="menu-item" aria-expanded="false" aria-controls="general-composer" title="Comment on the whole response (G)">\
<svg viewBox="0 0 24 24" aria-hidden="true">\
<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>\
</svg><span class="menu-item-label">Comment on the whole response</span><span class="menu-item-hint">G</span></button>\
<button id="menu-highlighter" type="button" class="menu-item" aria-pressed="false">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 4.5l4 4L10 18H6v-4z"/>\
<line x1="4" y1="21" x2="20" y2="21"/></svg>\
<span class="menu-item-label">Reading highlighter</span><span class="menu-item-hint" data-state>off</span></button>\
<button id="highlighter-clear" type="button" class="menu-item" title="Clear every highlight on this page">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5l7-7 6.5 6.5-4 4H7z"/>\
<line x1="12.5" y1="8" x2="19" y2="14.5"/><line x1="4" y1="21" x2="20" y2="21"/></svg>\
<span class="menu-item-label">Clear every highlight</span></button>\
<div class="menu-sec">View</div>\
<button id="fullscreen-toggle" type="button" class="menu-item" aria-pressed="false" title="Full screen — hide the browser chrome">\
<span class="menu-item-icon" data-icon><svg viewBox="0 0 24 24" aria-hidden="true">\
<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>\
<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg></span>\
<span class="menu-item-label">Full screen</span></button>\
<button type="button" class="menu-item" data-pane-to="settings">\
<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/>\
<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>\
</svg><span class="menu-item-label">Settings</span>\
<svg class="menu-chev" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg></button>\
<div class="menu-sec">Document</div>\
<button id="export-btn" type="button" class="menu-item" title="Save this document as a single standalone HTML file you can send to anyone">\
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/>\
<polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>\
<span class="menu-item-label" data-label>Share a copy…</span></button>\
<button type="button" class="menu-item" data-pane-to="help">\
<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>\
<path d="M9.2 9.3a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.4-2.8 4"/><path d="M12 17.2h.01"/></svg>\
<span class="menu-item-label">Buttons &amp; keyboard</span>\
<svg class="menu-chev" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg></button>\
</div>\
<div class="menu-pane" data-pane-name="settings">\
<button type="button" class="menu-back" data-pane-to="root">\
<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>\
<span>Settings</span></button>\
<div id="settings-pop" class="settings-pop">\
<div id="settings-groups"></div><div class="set-group" id="set-group-highlight">\
<span class="set-label">Highlight colour</span>\
<div id="palette-pop" class="palette-pop" role="group" aria-label="Highlight colour">\
<button type="button" data-color="yellow" aria-pressed="false" title="Yellow" aria-label="Yellow highlight">\
</button>\
<button type="button" data-color="green" aria-pressed="false" title="Green" aria-label="Green highlight">\
</button>\
<button type="button" data-color="orange" aria-pressed="false" title="Orange" aria-label="Orange highlight">\
</button>\
<button type="button" data-color="blue" aria-pressed="false" title="Blue" aria-label="Blue highlight">\
</button>\
<button type="button" data-color="pink" aria-pressed="false" title="Pink" aria-label="Pink highlight">\
</button></div></div>\
<button id="settings-reset" type="button" class="set-reset" title="Back to defaults. Fonts and reading size are shared with every annotate document.">Reset</button>\
</div></div>\
<div class="menu-pane" data-pane-name="help">\
<button type="button" class="menu-back" data-pane-to="root">\
<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>\
<span>Buttons &amp; keyboard</span></button>\
<div id="legend-pop" class="legend-pop">\
<div class="legend-body"><div class="legend-entry"><div class="legend-entry-name">\
<svg class="legend-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/>\
<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>\
<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg><span>Trash</span></div>\
<p class="legend-entry-tells">&ldquo;This is irrelevant &mdash; cut it&rdquo;</p>\
<p class="legend-entry-does">Removed from the document for good, and Claude is told never to bring it back</p></div>\
<div class="legend-entry"><div class="legend-entry-name">\
<svg class="legend-icon" viewBox="0 0 24 24" aria-hidden="true">\
<polyline points="20 6 9 17 4 12"/></svg><span>Leave as written</span></div>\
<p class="legend-entry-tells">&ldquo;This is fine &mdash; don&rsquo;t touch it&rdquo;</p>\
<p class="legend-entry-does">Stays exactly as written; Claude skips rewriting it</p></div>\
<div class="legend-entry"><div class="legend-entry-name">\
<svg class="legend-icon" viewBox="0 0 24 24" aria-hidden="true">\
<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>\
</svg><span>Comment</span></div>\
<p class="legend-entry-tells">&ldquo;Respond to this&rdquo;</p>\
<p class="legend-entry-does">Stays, rewritten to fold Claude&rsquo;s answer into the prose</p></div>\
<div class="legend-entry"><div class="legend-entry-name">\
<svg class="legend-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\
<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>\
<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>\
<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg><span>Compact</span></div>\
<p class="legend-entry-tells">&ldquo;I&rsquo;m fine with this &mdash; it just doesn&rsquo;t need the space&rdquo;</p>\
<p class="legend-entry-does">Taken off the page. What it contributes is folded into the sentences that stay, so the plan gets shorter without losing the thread. Detail that nothing else can carry is lost &mdash; this cannot be undone once the round is submitted</p></div><div class="legend-keys"><h4 class="legend-keys-head">Keyboard</h4>\
<table class="legend-keytable"><tbody><tr><td><kbd>j</kbd> <kbd>k</kbd></td>\
<td>Move to the next / previous block</td></tr><tr><td><kbd>c</kbd></td>\
<td>Comment on the block you are on</td></tr><tr><td><kbd>f</kbd></td><td>Fold or unfold that block</td></tr>\
<tr><td><kbd>/</kbd></td><td>Search the blocks</td></tr><tr><td><kbd>g</kbd></td>\
<td>Comment on the whole response</td></tr><tr><td><kbd>&#8984;K</kbd> <kbd>&#8984;0</kbd></td>\
<td>Fold every block (<kbd>&#8984;K</kbd> <kbd>&#8984;J</kbd> unfolds)</td></tr><tr><td><kbd>Esc</kbd></td>\
<td>Close what is open, then drop the cursor</td></tr></tbody></table></div>\
<p class="legend-note">All of these are feedback, and none of them does anything until you submit the round. Until then every mark is local and clicking the same button again takes it back.</p>\
</div></div>\
</div></div></span>\
<button id="done-btn" type="button" class="done-btn">Done</button></div></header>\
<section id="general-composer" class="general-composer" hidden>  <textarea id="general-input" class="general-input" rows="2"    placeholder="Comment on the whole response (not a specific block)…">\
</textarea>  <div class="general-composer-bar">    <span class="general-hint"><kbd>⌘</kbd>\
<kbd>↩</kbd> to send      &middot; <kbd>Esc</kbd> to close</span>    <span id="general-status" class="general-status" aria-live="polite">\
</span>    <button id="general-send" type="button" class="general-send-btn" disabled>Send</button>  </div>\
</section><main class="prose"></main>`;
