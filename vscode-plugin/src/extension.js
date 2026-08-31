// Personal VS Code extension — petros-makris-vscode
//
// Two unrelated jobs share one extension because an extension is the unit
// VS Code installs: the markdown preview theme switcher below, and the
// branch-diff URI handler in ./diff.js.
//
// Switches the markdown preview theme by copying the chosen theme's CSS
// into dist/markdown-themes/active.css. That single file is the one
// declared in `contributes.markdown.previewStyles`, so the markdown
// preview's webview is allowed to load it (its resource-roots allowlist
// includes paths declared by extensions, but NOT arbitrary absolute
// paths placed in the user-level `markdown.styles` setting).

const vscode = require('vscode');
const fs = require('fs/promises');
const path = require('path');
const diff = require('./diff');
const reviewComments = require('./reviewComments');

const STATE_KEY = 'petrosMakris.markdownTheme';
const OWN_SLOT_MARKER = 'petros-makris.petros-makris-vscode';
const DEFAULT_SLUG = 'dracula-mono';

const THEMES = [
  { slug: 'dracula-mono',  label: 'Dracula (Mono)' },
  { slug: 'rosepine-mono', label: 'Rose Pine (Mono)' },
  { slug: 'neon-mono',     label: 'Neon (Mono)' },
];

function themeDir(context) {
  return path.join(context.extensionUri.fsPath, 'dist', 'markdown-themes');
}

function maxWidthPx() {
  return vscode.workspace
    .getConfiguration('petrosMakris')
    .get('markdownPreviewMaxWidth', 1200);
}

async function writeActiveCss(context, slug) {
  const dir = themeDir(context);
  const src = path.join(dir, `${slug}.css`);
  const dst = path.join(dir, 'active.css');
  const prelude = `:root { --pm-max-width: ${maxWidthPx()}px; }\n`;
  const css = await fs.readFile(src, 'utf8');
  await fs.writeFile(dst, prelude + css);
}

// Markdown previews keep their CSS in webview memory across reloads; the
// safest way to make a CSS change take effect is to close & reopen each
// preview tab. We iterate tab groups, identify markdown preview tabs by
// their webview viewType, close them, then re-open one preview for the
// currently active markdown editor.
async function reopenMarkdownPreviews() {
  const closed = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      const input = tab.input;
      if (input && typeof input === 'object' && 'viewType' in input
          && String(input.viewType).includes('markdown.preview')) {
        closed.push(tab);
      }
    }
  }
  if (closed.length === 0) return;
  await vscode.window.tabGroups.close(closed);
  // Re-open one preview for the active markdown editor, if any.
  const active = vscode.window.activeTextEditor;
  if (active && active.document.languageId === 'markdown') {
    await vscode.commands.executeCommand('markdown.showPreviewToSide');
  }
}

async function pickTheme(context) {
  const items = THEMES.map(t => ({ label: t.label, description: t.slug, slug: t.slug }));
  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: 'Pick a markdown preview theme',
    matchOnDescription: true,
  });
  if (!picked) return;
  await context.globalState.update(STATE_KEY, picked.slug);
  await writeActiveCss(context, picked.slug);
  await reopenMarkdownPreviews();
  vscode.window.showInformationMessage(`Markdown theme set to ${picked.label}.`);
}

async function refreshOnActivation(context) {
  let slug = context.globalState.get(STATE_KEY);
  if (!slug || !THEMES.some(t => t.slug === slug)) slug = DEFAULT_SLUG;
  await writeActiveCss(context, slug);
}

// One-shot migration: older versions wrote absolute paths into the
// user-level `markdown.styles` setting. Strip those entries so the
// preview stops trying to load them.
async function migrateMarkdownStyles() {
  const config = vscode.workspace.getConfiguration('markdown');
  const current = config.get('styles');
  if (!Array.isArray(current) || current.length === 0) return;
  const cleaned = current.filter(p => typeof p !== 'string' || !p.includes(OWN_SLOT_MARKER));
  if (cleaned.length === current.length) return;
  const next = cleaned.length === 0 ? undefined : cleaned;
  await config.update('styles', next, vscode.ConfigurationTarget.Global);
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'petrosMakris.setMarkdownTheme',
      () => pickTheme(context),
    ),
    // When the width setting changes, re-write active.css with the new
    // value baked into the :root prelude.
    vscode.workspace.onDidChangeConfiguration(async e => {
      if (!e.affectsConfiguration('petrosMakris.markdownPreviewMaxWidth')) return;
      const slug = context.globalState.get(STATE_KEY);
      if (!slug || !THEMES.some(t => t.slug === slug)) return;
      try {
        await writeActiveCss(context, slug);
        await reopenMarkdownPreviews();
      } catch (err) { console.error(err); }
    }),
  );
  // Branch-to-branch diffs opened from outside the editor. Kept in its own
  // module: it shares nothing with the markdown themes above except this
  // extension's activation.
  diff.register(context);
  // Makes every line of a diff diff.js opens askable: a CommentController that turns a
  // clicked line into a webcompanion anchor. Kept in its own module, same reasoning as
  // diff.js above.
  reviewComments.register(context);
  // Fire-and-forget: refresh active.css from persisted slug, and strip
  // stale markdown.styles entries left by older versions.
  refreshOnActivation(context).catch(err => console.error(err));
  migrateMarkdownStyles().catch(err => console.error(err));
}

function deactivate() {}

module.exports = { activate, deactivate };
