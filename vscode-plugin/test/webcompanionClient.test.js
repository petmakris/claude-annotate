const assert = require('assert');
const http = require('http');
const { WebCompanionClient } = require('../src/webcompanionClient');

function fakeDaemon(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

describe('WebCompanionClient', () => {
  let server;
  afterEach(() => server && server.close());

  it('listSessions sends cwd and kind as query params', async () => {
    let seenUrl;
    server = await fakeDaemon((req, res) => {
      seenUrl = req.url;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify([{ sid: 's1', kind: 'show-diff' }]));
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    const rows = await client.listSessions('/repo', 'show-diff');
    assert.strictEqual(rows[0].sid, 's1');
    assert.ok(seenUrl.includes('cwd=%2Frepo'));
    assert.ok(seenUrl.includes('kind=show-diff'));
  });

  it('submit posts anchor and text as JSON, returns event_id', async () => {
    let body = '';
    let contentLength;
    server = await fakeDaemon((req, res) => {
      contentLength = req.headers['content-length'];
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        res.writeHead(202, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ event_id: 'e1' }));
      });
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    const result = await client.submit('sid1', 'a.py:R:1', 'why?');
    assert.strictEqual(result.event_id, 'e1');
    assert.deepStrictEqual(JSON.parse(body), { anchor: 'a.py:R:1', text: 'why?' });
    // The daemon is a bare Python http.server, which never decodes a chunked
    // body -- Node defaults to chunked whenever a POST body's length isn't
    // declared up front, and a Node fake server (unlike the real daemon)
    // decodes chunked transparently, so this is the one thing standing
    // between a passing suite and a submit that silently reaches the real
    // daemon as an empty body.
    assert.strictEqual(contentLength, String(Buffer.byteLength(body)));
  });

  it('a 426 response rejects with a ContractMismatch-shaped error', async () => {
    server = await fakeDaemon((req, res) => {
      res.writeHead(426, { 'Content-Type': 'text/plain' });
      res.end('the client speaks contract 1, this daemon speaks 2');
    });
    const client = new WebCompanionClient(`http://127.0.0.1:${server.address().port}`);
    await assert.rejects(client.getPoll('sid1'), /contract/);
  });
});
