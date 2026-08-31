// Makes every line of an open diff askable, via a vscode.CommentController.
//
// `vscode` itself is only resolvable inside a running extension host, so the
// one piece of real logic here -- turning a clicked (uri, range) into a
// path:side:line anchor -- is a small pure function, exported separately
// from the vscode.CommentController wiring that calls it, so it is testable
// without a running extension host at all.

// Turns a document + 0-based line into this session's <path>:<side>:<line>
// anchor, or null when the document isn't part of the diff currently open.
// Kept separate from the vscode.CommentController wiring below so it is
// testable without a running extension host.
function anchorFor(files, { gitPath, ref }, line, { worktree = false } = {}) {
  const file = files.find((f) => f.name === gitPath);
  if (!file) return null;
  let side;
  if (worktree && !ref) side = 'R';
  else if (ref === file.originalRef) side = 'L';
  else if (ref === file.modifiedRef) side = 'R';
  else return null;
  return `${gitPath}:${side}:${line + 1}`; // anchors are 1-based, VS Code ranges are 0-based
}

let vscode;
try { vscode = require('vscode'); } catch { /* loaded outside an extension host, e.g. under mocha */ }

const path = require('path');
const { WebCompanionClient } = require('./webcompanionClient');
const { loadConfig } = require('./webcompanionConfig');

let controller = null;
let current = null; // { repo, worktree, sid, files }

const POLL_MS = 2000;
let pollTimer = null;
const openThreads = new Map(); // anchor -> { vsThread, version }

function commentingRangeProvider(document) {
  if (!current) return [];
  const decoded = decodeDocumentRef(document.uri);
  if (!decoded) return [];
  const anchor = anchorFor(current.files, decoded, 0, { worktree: current.worktree });
  if (anchor === null && !current.files.some((f) => f.name === decoded.gitPath)) return [];
  return [new vscode.Range(0, 0, document.lineCount - 1, 0)];
}

// pmdiff:// URIs carry {repo, ref, gitPath} base64-encoded in the query,
// exactly as diff.js's own decodeBlobUri does -- duplicated rather than
// imported, since diff.js does not export it and this module must not
// reach into diff.js's private encoding to stay independently testable.
function decodeDocumentRef(uri) {
  if (uri.scheme === 'pmdiff') {
    try {
      const { repo, ref, gitPath } = JSON.parse(Buffer.from(uri.query, 'base64').toString('utf8'));
      return { repo, ref, gitPath };
    } catch { return null; }
  }
  if (current && uri.scheme === 'file' && current.worktree) {
    const rel = path.relative(current.repo, uri.fsPath).split(path.sep).join('/');
    if (current.files.some((f) => f.name === rel)) return { repo: current.repo, ref: '', gitPath: rel };
  }
  return null;
}

function setCurrentDiff(info) {
  current = info;
  openThreads.clear();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (!info.sid) return;
  pollTimer = setInterval(() => pollOnce().catch(() => {}), POLL_MS);
}

// Polls the daemon for every anchor whose thread has moved since we last
// rendered it, and re-renders just those. `status.threads` maps anchor to a
// version marker the daemon bumps on every reply, so a poll that finds no
// version change costs one small GET and touches no CommentThread.
async function pollOnce() {
  if (!current || !current.sid) return;
  const cfg = await loadConfig();
  const client = new WebCompanionClient(`http://${cfg.bind}:${cfg.port}`);
  const status = await client.getPoll(current.sid);
  for (const [anchor, version] of Object.entries(status.threads || {})) {
    const known = openThreads.get(anchor);
    if (known && known.version === version) continue;
    const thread = await client.getThread(current.sid, anchor);
    renderThread(anchor, thread, version);
  }
}

// Anchors are 1-based (<path>:<side>:<linenum>, matching real file line
// numbers); VS Code ranges are 0-based, hence the -1 here mirroring the +1
// in anchorFor above.
function renderThread(anchor, thread, version) {
  const [gitPath, side, lineStr] = anchor.split(':');
  const line = parseInt(lineStr, 10) - 1;
  const file = current.files.find((f) => f.name === gitPath);
  if (!file) return;
  const uri = side === 'L'
    ? vscode.Uri.from({ scheme: 'pmdiff', path: gitPath,
        query: Buffer.from(JSON.stringify({ repo: current.repo, ref: file.originalRef, gitPath })).toString('base64') })
    : (current.worktree
        ? vscode.Uri.file(path.join(current.repo, gitPath))
        : vscode.Uri.from({ scheme: 'pmdiff', path: gitPath,
            query: Buffer.from(JSON.stringify({ repo: current.repo, ref: file.modifiedRef, gitPath })).toString('base64') }));
  const range = new vscode.Range(line, 0, line, 0);
  const comments = (thread.messages || []).map((m) => ({
    body: m.text,
    mode: vscode.CommentMode.Preview,
    author: { name: m.role === 'agent' ? 'Claude' : 'You' },
  }));
  let entry = openThreads.get(anchor);
  if (!entry) {
    const vsThread = controller.createCommentThread(uri, range, comments);
    entry = { vsThread, version };
    openThreads.set(anchor, entry);
  } else {
    entry.vsThread.comments = comments;
    entry.vsThread.contextValue = undefined; // reply has landed; no longer waiting on Claude
    entry.version = version;
  }
}

function register(context) {
  if (!vscode) return;
  controller = vscode.comments.createCommentController('petrosMakrisReview', 'Diff review');
  controller.commentingRangeProvider = { provideCommentingRanges: commentingRangeProvider };
  context.subscriptions.push(controller);

  context.subscriptions.push(
    vscode.commands.registerCommand('petrosMakris.submitReviewComment', async (reply) => {
      const decoded = decodeDocumentRef(reply.thread.uri);
      if (!current || !decoded) return;
      const line = reply.thread.range.start.line;
      const anchor = anchorFor(current.files, decoded, line, { worktree: current.worktree });
      if (!anchor) return;
      const cfg = await loadConfig();
      const client = new WebCompanionClient(`http://${cfg.bind}:${cfg.port}`);
      await client.submit(current.sid, anchor, reply.text);
      reply.thread.comments = [
        ...reply.thread.comments,
        { body: reply.text, mode: vscode.CommentMode.Preview,
          author: { name: 'You' } },
      ];
      reply.thread.contextValue = 'pending';
      // VS Code created this thread itself (the user typed into the "+" gutter
      // widget), so the poll loop has never seen it. Track it under its anchor
      // now, with no known version, so the next pollOnce() that finds this
      // anchor's version changed updates THIS thread instead of standing up a
      // second, duplicate one at the same spot.
      const existing = openThreads.get(anchor);
      if (!existing) {
        openThreads.set(anchor, { vsThread: reply.thread, version: null });
      }
    }),
  );
}

module.exports = { anchorFor, setCurrentDiff, register };
