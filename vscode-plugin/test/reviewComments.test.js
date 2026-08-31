const assert = require('assert');
const { anchorFor } = require('../src/reviewComments');

describe('anchorFor', () => {
  const files = [
    { name: 'src/a.py', originalRef: 'base-sha', modifiedRef: 'head-sha' },
  ];

  it('builds an L-side anchor for the original document', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: 'base-sha' }, 5),
      'src/a.py:L:6');
  });

  it('builds an R-side anchor for the modified document', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: 'head-sha' }, 5),
      'src/a.py:R:6');
  });

  it('builds an R-side anchor for a live worktree file (no ref)', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/a.py', ref: '' }, 5, { worktree: true }),
      'src/a.py:R:6');
  });

  it('returns null for a file not part of the tracked diff', () => {
    assert.strictEqual(
      anchorFor(files, { gitPath: 'src/unrelated.py', ref: 'head-sha' }, 5),
      null);
  });
});
