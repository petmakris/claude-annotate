const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadConfig } = require('../src/webcompanionConfig');

describe('loadConfig', () => {
  it('reads bind and port from the config file', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wc-'));
    const file = path.join(dir, 'config.json');
    fs.writeFileSync(file, JSON.stringify({ bind: '127.0.0.1', port: 4242, token: 'x' }));
    const cfg = await loadConfig(file);
    assert.strictEqual(cfg.port, 4242);
    assert.strictEqual(cfg.bind, '127.0.0.1');
  });

  it('rejects when the config file does not exist', async () => {
    await assert.rejects(loadConfig('/nonexistent/config.json'));
  });
});
