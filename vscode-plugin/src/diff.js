// Branch-to-branch diffs, opened from outside VS Code.
//
// The `code` CLI takes files and folders and nothing else: there is no flag
// that runs a command, and no built-in URI that opens a diff of two refs. A
// URI handler is the only way anything outside the editor can make a running
// window do something, so this module registers one:
//
//   vscode://petros-makris.petros-makris-vscode/diff
//     ?repo=<absolute path to a checkout>
//     &base=<any rev>            # left side
//     &head=<any rev|worktree>   # right side; `worktree` means the files on disk
//     &title=<optional label>
//
// It resolves the two revs, asks git which files differ, and hands the whole
// set to `vscode.changes` — the multi-file diff editor — so 54 changed files
// are one scrollable review rather than 54 tabs.
//
// Alongside the editor it registers a Source Control provider holding the same files, so
// the sidebar carries a tree of what changed and a click on any entry opens that one file
// side by side. The provider is where the file list has to live: VS Code's own git view
// only ever shows the working tree, and the API that would let a custom group reopen the
// whole multi-diff (`multiDiffEditorOriginalUri`) is proposed, so an installed extension
// cannot use it.
//
// The left side is served by this extension's own read-only filesystem
// (scheme `pmdiff`), which shells out to `git show <ref>:<path>`. The built-in
// git extension offers a `git:` scheme that would do the same, but only for
// repositories that window already has open — and the window a URI lands in
// is whichever one was last focused. Serving the bytes ourselves means a diff
// opens correctly in any window, whatever folder it holds.

const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');

const SCHEME = 'pmdiff';
// The value `head` takes to mean "the files on disk" rather than a commit. Spelled out
// rather than expressed by omitting `head`, so a caller that forgot to pass one gets the
// error instead of silently being shown its uncommitted work.
const WORKTREE = 'worktree';
// Where a run records what it did. An extension failing inside a window is otherwise
// unobservable from outside it: a thrown error becomes a toast nobody screenshots, and
// whatever went wrong is gone when the window reloads.
const LOG = path.join(os.homedir(), '.pmdiff.log');
// The log is a diagnostic, not a record, so it is capped rather than rotated: past a
// quarter of a megabyte it is truncated to its newest half, dropping the partial line
// the cut lands in. The newest half is the half that matters — the run being diagnosed
// is always the most recent one — and one file means there is still one path to look at.
const LOG_MAX = 256 * 1024;

let extensionVersion = 'unknown';

function trimLog() {
  try {
    if (fs.statSync(LOG).size <= LOG_MAX) return;
    const kept = fs.readFileSync(LOG, 'utf8').slice(-Math.floor(LOG_MAX / 2));
    fs.writeFileSync(LOG, kept.slice(kept.indexOf('\n') + 1));
  } catch { /* a log that cannot be trimmed is still a log that can be appended to */ }
}

function note(fields) {
  try {
    trimLog();
    fs.appendFileSync(LOG, JSON.stringify({
      at: new Date().toISOString(), version: extensionVersion, ...fields,
    }) + '\n');
  } catch { /* a log that cannot be written must not break the diff */ }
}
const MAX_BUFFER = 64 * 1024 * 1024;   // a generated file can be large; 1MB (the default) is not enough

function run(repo, args, encoding) {
  return new Promise(resolve => {
    execFile('git', ['-C', repo, ...args], { encoding, maxBuffer: MAX_BUFFER },
      (err, stdout, stderr) => resolve({
        ok: !err,
        stdout: stdout ?? (encoding === 'buffer' ? Buffer.alloc(0) : ''),
        stderr: String(stderr ?? (err ? err.message : '')),
      }));
  });
}

const text = (repo, args) => run(repo, args, 'utf8');
const bytes = (repo, args) => run(repo, args, 'buffer');

// ---------------------------------------------------------------------------
// A file as it stood at a ref.
//
// The ref travels in the query rather than the path so that the same file at
// two different refs is two distinct URIs — VS Code's URI identity includes
// the query, and the diff editor needs both sides to be separately
// addressable. The path is the file's real absolute path, which does two
// things: the editor picks the language mode from the extension, and the two
// sides of an unmodified path agree. They have to agree — the diff editor reads
// a differing path as a RENAME, so a repo-relative path on the left against the
// absolute file on the right labelled every single file "renamed from".
//
// An empty ref means the empty file. That is how an added file's left side and
// a deleted file's right side are expressed: git has no blob to show, and an
// empty document is exactly what the diff editor should render.
// ---------------------------------------------------------------------------

function blobUri(repo, ref, gitPath) {
  return vscode.Uri.from({
    scheme: SCHEME,
    path: path.join(repo, gitPath),
    query: Buffer.from(JSON.stringify({ repo, ref, gitPath }), 'utf8').toString('base64'),
  });
}

function decodeBlobUri(uri) {
  return JSON.parse(Buffer.from(uri.query, 'base64').toString('utf8'));
}

class BlobFileSystem {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeFile = this._emitter.event;
  }

  // Nothing here ever changes: a blob at a ref is immutable, so there is
  // nothing to watch and nothing to write.
  watch() { return new vscode.Disposable(() => {}); }
  readDirectory() { throw vscode.FileSystemError.NoPermissions(SCHEME); }
  createDirectory() { throw vscode.FileSystemError.NoPermissions(SCHEME); }
  writeFile() { throw vscode.FileSystemError.NoPermissions(SCHEME); }
  delete() { throw vscode.FileSystemError.NoPermissions(SCHEME); }
  rename() { throw vscode.FileSystemError.NoPermissions(SCHEME); }

  async stat(uri) {
    const content = await this.readFile(uri);
    return {
      type: vscode.FileType.File,
      ctime: 0,
      mtime: 0,
      size: content.byteLength,
      permissions: vscode.FilePermission.Readonly,
    };
  }

  async readFile(uri) {
    const { repo, ref, gitPath } = decodeBlobUri(uri);
    if (!ref) return new Uint8Array(0);
    const res = await bytes(repo, ['show', `${ref}:${gitPath}`]);
    // A missing blob is not an error to report: a rename's old path, a file
    // added on one side, a path git resolves differently than --name-status
    // named it — all render correctly as an empty side.
    return res.ok ? new Uint8Array(res.stdout) : new Uint8Array(0);
  }
}

// ---------------------------------------------------------------------------
// The file list in the sidebar.
//
// It lives in a view container this extension contributes — its own icon in the activity
// bar — rather than in VS Code's Source Control panel, which is where it started. That
// panel is not ours: GitLens takes it over wholesale, and a Source Control provider
// registered into it is created without error and then never rendered. Verified on
// 2026-08-30 by launching with `--disable-extension eamodio.gitlens`, at which point the
// list appeared; no setting in either extension changes it. Owning a container is also
// what lets the panel be titled with the diff rather than with the repository.
//
// One tree per diff, replaced rather than accumulated: the question a reader has is
// "what is in the diff I just opened", and three stale sections above it answer a
// question nobody asked.
//
// Files are split by status into their own groups instead of carrying a letter badge.
// The badge would come from a FileDecorationProvider keyed on the real file path, and
// git already decorates those same paths — two providers arguing over one filename.
// A group heading says the same thing and cannot collide.
// ---------------------------------------------------------------------------

const GROUPS = [
    ["modified", "Modified", kind => kind === "M" || kind === "T"],
    ["added",    "Added",    kind => kind === "A"],
    ["deleted",  "Deleted",  kind => kind === "D"],
    ["renamed",  "Renamed",  kind => kind === "R" || kind === "C"],
];

const VIEW_ID = "petrosMakris.diffFiles";

// The tree holds one diff at a time. `groups` is an array of {name, entries}; a status
// with no files is not in it, so an empty heading can never be drawn.
class DiffTree {
    constructor() {
        this._emitter = new vscode.EventEmitter();
        this.onDidChangeTreeData = this._emitter.event;
        this.groups = [];
    }

    set(groups) {
        this.groups = groups;
        this._emitter.fire();
    }

    getChildren(node) {
        if (!node) return this.groups;
        return node.entries || [];
    }

    getTreeItem(node) {
        if (node.entries) {
            const item = new vscode.TreeItem(
                `${node.name} (${node.entries.length})`,
                vscode.TreeItemCollapsibleState.Expanded);
            item.contextValue = "pmdiffGroup";
            return item;
        }
        // The label is the filename and the description is the directory, the way VS
        // Code's own lists read: a column of full paths is unscannable, and the path is
        // what the reader falls back to only when two files share a name.
        const item = new vscode.TreeItem(path.basename(node.name));
        item.description = path.dirname(node.name) === "." ? "" : path.dirname(node.name);
        item.resourceUri = node.resourceUri;
        item.tooltip = `${node.groupName} — ${node.name}`;
        item.contextValue = "pmdiffFile";
        item.command = {
            title: "Open diff",
            command: "vscode.diff",
            arguments: [node.originalUri, node.modifiedUri, node.label],
        };
        return item;
    }
}

const tree = new DiffTree();
let view = null;        // the TreeView, created once at activation

function clearFileList() {
    tree.set([]);
    if (view) {
        view.title = "No diff open";
        view.description = undefined;
        view.badge = undefined;
    }
}

function showFileList(repo, label, entries) {
    const groups = [];
    const built = [];
    for (const [, name, matches] of GROUPS) {
        const mine = entries.filter(entry => matches(entry.status[0]));
        if (mine.length === 0) continue;
        groups.push({ name, entries: mine.map(entry => ({ ...entry, groupName: name })) });
        built.push(`${name}=${mine.length}`);
    }
    tree.set(groups);

    if (view) {
        // The panel is titled with the diff, not with the repository: two windows each
        // showing a different pair of revs of the same checkout is the normal case, and
        // a title naming only the repo cannot tell them apart.
        view.title = label;
        view.description = `${entries.length} file${entries.length === 1 ? "" : "s"}`;
        view.badge = { value: entries.length, tooltip: label };
    }

    note({ event: 'file-list', label, groups: built, entries: entries.length,
           treeApi: typeof vscode.window?.createTreeView });
}

// ---------------------------------------------------------------------------
// What changed between two revs.
// ---------------------------------------------------------------------------

// `--name-status -z` emits NUL-separated fields, not tab-separated ones: a
// status, then one path, or for a rename or copy a status then two paths. A
// path containing a tab or a newline is therefore parsed correctly, which the
// non-`-z` form cannot promise.
function parseNameStatus(stdout) {
  const fields = stdout.split('\0');
  const out = [];
  let i = 0;
  while (i < fields.length) {
    const status = fields[i++];
    if (!status) continue;                      // trailing NUL
    const kind = status[0];
    if (kind === 'R' || kind === 'C') {
      const from = fields[i++];
      const to = fields[i++];
      if (!to) break;
      out.push({ status, oldPath: from, newPath: to });
    } else {
      const file = fields[i++];
      if (!file) break;
      out.push({
        status,
        oldPath: kind === 'A' ? null : file,
        newPath: kind === 'D' ? null : file,
      });
    }
  }
  return out;
}

async function resolveRev(repo, rev) {
  const res = await text(repo, ['rev-parse', '--verify', '--quiet', rev + '^{commit}']);
  return res.ok ? res.stdout.trim() : null;
}

const short = sha => sha.slice(0, 10);

// A URI reaches whichever window was in front, and `show-diff.sh` picks that window by
// its title — which is the checkout's folder name. Two workspaces holding the same
// repository produce two windows both titled `montblanc`, so the title cannot tell them
// apart, and a diff fired a moment too early lands in the wrong one. That was survivable
// while a stale diff merely piled up another tab; now that opening one closes the last,
// a misfire costs the reader the review he was in the middle of.
//
// The window knows something the script cannot: which folder it actually holds. So the
// URI's repo is checked against it, and a mismatch is refused and named rather than
// rendered. Refusing loses a diff the reader can reopen; rendering loses the one he was
// reading.
//
// A window with no folder open — a bare editor — is not refused. It holds nothing to
// contradict, and it is where a diff should go when nothing else claims it.
function windowHolds(repo) {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return true;
  const target = path.resolve(repo);
  return folders.some(folder => {
    const root = path.resolve(folder.uri.fsPath);
    return target === root || target.startsWith(root + path.sep);
  });
}

async function openDiff({ repo, base, head, title }) {
  if (!windowHolds(repo)) {
    const held = (vscode.workspace.workspaceFolders || []).map(f => f.uri.fsPath).join(', ');
    note({ event: 'wrong-window', repo, held });
    vscode.window.showWarningMessage(
      `This window holds ${held || 'no folder'}, not ${repo}. ` +
      `The diff was not opened here — bring that project's window to the front and run it again.`);
    return;
  }
  const inside = await text(repo, ['rev-parse', '--is-inside-work-tree']);
  if (!inside.ok) {
    vscode.window.showErrorMessage(`Not a git checkout: ${repo}`);
    return;
  }

  const worktree = head === WORKTREE;
  const baseSha = await resolveRev(repo, base);
  const headSha = worktree ? null : await resolveRev(repo, head);
  // Naming which rev failed matters more than that one did: `base` and `head`
  // come from a caller that resolved them from a branch name, and an unknown
  // rev usually means the ref exists in another clone but was never fetched
  // into this one.
  const unknown = [!baseSha && `base '${base}'`,
                   !worktree && !headSha && `head '${head}'`].filter(Boolean);
  if (unknown.length) {
    vscode.window.showErrorMessage(
      `${path.basename(repo)}: cannot resolve ${unknown.join(' or ')}. Fetch it, or name a rev this clone has.`);
    return;
  }

  // Against the working tree the range is open-ended: `git diff <base>` compares the
  // files on disk to that rev, which is the whole point of the mode — staged and
  // unstaged changes both count, because both are things the author has done and
  // neither is in any commit.
  const range = worktree ? [baseSha] : [`${baseSha}..${headSha}`];
  const listed = await text(repo, ['diff', '--name-status', '-M', '-z', ...range]);
  if (!listed.ok) {
    vscode.window.showErrorMessage(`git diff failed in ${path.basename(repo)}: ${listed.stderr.trim()}`);
    return;
  }

  const changes = parseNameStatus(listed.stdout);

  // `git diff` knows nothing about a file git has never been told about, so a new file
  // would be missing from exactly the review most likely to be about new files. They are
  // added here as what they are: a file with no left-hand side.
  if (worktree) {
    const untracked = await text(repo, ['ls-files', '--others', '--exclude-standard', '-z']);
    for (const file of untracked.stdout.split('\0')) {
      if (file) changes.push({ status: 'A', oldPath: null, newPath: file });
    }
    changes.sort((a, b) => (a.newPath || a.oldPath).localeCompare(b.newPath || b.oldPath));
  }
  if (changes.length === 0) {
    vscode.window.showInformationMessage(
      `${path.basename(repo)}: nothing differs from ${worktree ? 'the working tree' : short(headSha)}.`);
    return;
  }

  // When the checkout already sits on `head` with nothing uncommitted, the
  // right-hand side can be the real file on disk instead of a blob. That is
  // worth the two extra git calls: a real file is navigable and editable, so
  // go-to-definition works while reading the diff and a fix can be typed in
  // place. Any drift at all — a different HEAD, one dirty file — and every
  // right-hand side becomes a blob, because a diff that silently mixes
  // committed and uncommitted content is worse than one that is merely
  // read-only.
  let live = worktree;      // the working tree IS the right-hand side in that mode
  if (!worktree) {
    const at = await text(repo, ['rev-parse', 'HEAD']);
    const dirty = await text(repo, ['status', '--porcelain']);
    live = at.ok && at.stdout.trim() === headSha && dirty.ok && dirty.stdout.trim() === '';
  }

  note({ event: 'diff', repo, base, head, worktree, files: changes.length });

  const right = worktree ? 'working tree' : short(headSha);
  const label = title
    || `${path.basename(repo)} · ${short(baseSha)}..${right} · ${changes.length} files`;

  // Built once and handed to both views, so the sidebar and the editor can never
  // disagree about which files are in the diff or which two revs a file is between.
  const entries = changes.map(({ status, oldPath, newPath }) => {
    const name = newPath || oldPath;
    return {
      status,
      name,
      label: `${name} · ${short(baseSha)}..${right}`,
      resourceUri: vscode.Uri.file(path.join(repo, name)),
      originalUri: blobUri(repo, oldPath ? baseSha : '', oldPath || name),
      modifiedUri: newPath
        ? (live ? vscode.Uri.file(path.join(repo, newPath)) : blobUri(repo, headSha, newPath))
        : blobUri(repo, '', name),
    };
  });

  // The sidebar first, then the editor: opening the multi-diff last is what leaves it
  // focused, which is where the reader wants to be.
  try {
    showFileList(repo, label, entries);
  } catch (err) {
    // The file list is an addition; losing it must not cost the diff itself.
    note({ event: 'file-list-failed', label, error: String(err && err.stack || err) });
  }
  await closeOurDiffTabs('replaced');
  rememberLabel(label);
  await vscode.commands.executeCommand(
    'vscode.changes', label,
    entries.map(e => [e.resourceUri, e.originalUri, e.modifiedUri]));

  await focusReview();
}

// ---------------------------------------------------------------------------
// One diff, one tab.
//
// `vscode.changes` opens a new multi-file editor every time, and VS Code restores those
// tabs on the next launch — but the content behind one lives in this extension's memory,
// which the restart threw away. So a restored tab is an empty shell with the right title,
// and the reviewer who relaunches after opening a diff finds two identical tabs, one of
// which shows nothing. Repeated runs stack them up even without a restart.
//
// So every run closes the diff tabs it recognises before opening a new one, and the sweep
// runs again at activation to clear the shells a restart left behind.
//
// Recognising them takes two signals together, because either alone is wrong. The tab's
// input must be a multi-diff — VS Code's own git opens those too, from a commit's "open
// changes", and closing someone else's tab is not ours to do — and its label must be one
// this extension opened. The labels are kept in globalState because the tabs outlive the
// process that made them, which is the whole problem.
//
// `TabInputTextMultiDiff` is absent from the type definitions VS Code 1.135 ships while
// being present in its extension host, so it is read off the namespace and guarded rather
// than named directly. Where it is missing, nothing is recognised and nothing is closed —
// a stale tab is a smaller cost than a wrongly closed one.
// ---------------------------------------------------------------------------

const OPENED_LABELS = 'petrosMakris.diffLabels';
const LABELS_KEPT = 50;

let store = null;       // context.globalState, set at activation

function rememberLabel(label) {
  if (!store) return;
  const kept = [label, ...(store.get(OPENED_LABELS) || []).filter(l => l !== label)];
  store.update(OPENED_LABELS, kept.slice(0, LABELS_KEPT));
}

function isOurs(tab) {
  const MultiDiff = vscode.TabInputTextMultiDiff;
  if (!MultiDiff || !(tab.input instanceof MultiDiff)) return false;
  // VS Code renders the tab as `<label> (N files)`, so the stored label is a prefix of
  // what the tab shows rather than the whole of it.
  const labels = (store && store.get(OPENED_LABELS)) || [];
  return labels.some(l => tab.label === l || tab.label.startsWith(`${l} (`));
}

async function closeOurDiffTabs(reason) {
  const doomed = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) if (isOurs(tab)) doomed.push(tab);
  }
  if (doomed.length === 0) return;
  try {
    await vscode.window.tabGroups.close(doomed, true);
    note({ event: 'closed-diff-tabs', reason, count: doomed.length });
  } catch (err) {
    note({ event: 'close-tabs-failed', reason, error: String(err && err.message || err) });
  }
}

// ---------------------------------------------------------------------------
// Put the window into the shape a review wants.
//
// A window that has been used for anything else opens the diff behind whatever was
// already there — the Explorer on the left, a chat panel on the right, a terminal below —
// and the reader's first act is three clicks of tidying before he can read. So the diff
// brings its own layout with it.
//
// Only chrome is touched: the two side bars and the bottom panel. Editor tabs are left
// exactly as they were, because a tab is a file someone opened on purpose and closing it
// throws away work in a window that is usually also a working checkout. Every one of these
// is one click to undo, which is what makes doing them unasked defensible.
//
// Failures are swallowed individually. These are workbench commands, not API calls; one
// renamed in a future VS Code must cost its own line and not the diff.
// ---------------------------------------------------------------------------

async function focusReview() {
  const steps = [
    // The file list, not the Explorer: the reader's next move is choosing a file in the
    // diff he just opened, never browsing the repository.
    ['petrosMakris.diffFiles.focus'],
    // The right-hand bar is where a chat panel sits, and it is the widest thing competing
    // with the diff for the screen it needs.
    ['workbench.action.closeAuxiliaryBar'],
    ['workbench.action.closePanel'],
  ];
  for (const [command, ...args] of steps) {
    try {
      await vscode.commands.executeCommand(command, ...args);
    } catch (err) {
      note({ event: 'focus-step-failed', command, error: String(err && err.message || err) });
    }
  }
}

// ---------------------------------------------------------------------------

function register(context) {
  extensionVersion = context.extension?.packageJSON?.version || 'unknown';
  store = context.globalState;
  note({ event: 'activated' });
  view = vscode.window.createTreeView(VIEW_ID, { treeDataProvider: tree });
  clearFileList();
  // Nothing can be live this early — the process that held the last diff is gone — so any
  // tab still standing is a shell VS Code restored, and it is swept before it is read.
  closeOurDiffTabs('restored');
  context.subscriptions.push(
    view,
    { dispose: clearFileList },
    vscode.commands.registerCommand('petrosMakris.clearDiff', async () => {
      clearFileList();
      await closeOurDiffTabs('cleared');
    }),
    vscode.workspace.registerFileSystemProvider(SCHEME, new BlobFileSystem(), {
      isReadonly: true,
      isCaseSensitive: true,
    }),
    vscode.window.registerUriHandler({
      handleUri(uri) {
        if (uri.path !== '/diff') {
          vscode.window.showErrorMessage(`Unknown petros-makris-vscode URI: ${uri.path}`);
          return;
        }
        const q = new URLSearchParams(uri.query);
        const repo = q.get('repo');
        const base = q.get('base');
        const head = q.get('head');
        if (!repo || !base || !head) {
          vscode.window.showErrorMessage('diff URI needs repo, base and head.');
          return;
        }
        openDiff({ repo, base, head, title: q.get('title') || undefined })
          .catch(err => vscode.window.showErrorMessage(`diff failed: ${err.message}`));
      },
    }),
  );
}

module.exports = { register, openDiff, clearFileList, SCHEME };
