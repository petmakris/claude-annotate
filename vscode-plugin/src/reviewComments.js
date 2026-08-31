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

const { WebCompanionClient } = require('./webcompanionClient');
const { loadConfig } = require('./webcompanionConfig');

let controller = null;
let current = null; // { repo, base, head, worktree, sid, files }

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
    const path = require('path');
    const rel = path.relative(current.repo, uri.fsPath).split(path.sep).join('/');
    if (current.files.some((f) => f.name === rel)) return { repo: current.repo, ref: '', gitPath: rel };
  }
  return null;
}

function setCurrentDiff(info) {
  current = info;
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
    }),
  );
}

module.exports = { anchorFor, setCurrentDiff, register };
