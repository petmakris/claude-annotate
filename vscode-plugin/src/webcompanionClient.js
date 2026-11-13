// HTTP client for the webcompanion daemon, used by the diff comment UI.
// Zero dependencies, matching the rest of this extension: plain `http`,
// same as diff.js's own git subprocess calls avoid pulling in a library.

const http = require('http');
const https = require('https');
const { URL } = require('url');

const CONTRACT = 1;
// The kind of session this extension reviews: show-diff.sh is the only thing that opens it.
// A slug is unique within a kind, so a session route says which kind it means.
const KIND = 'show-diff';
// The same bound as the Python client's TIMEOUT_S: a daemon that accepts and never answers
// must not leave a poll, a thread read or a reply hanging.
const REQUEST_TIMEOUT_MS = 15000;

class WebCompanionClient {
  constructor(baseUrl, { timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
    this.timeoutMs = timeoutMs;
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  _request(method, path, body) {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const mod = url.protocol === 'https:' ? https : http;
      const data = body !== undefined ? JSON.stringify(body) : null;
      const headers = { 'X-WebCompanion-Contract': String(CONTRACT) };
      // Without an explicit Content-Length, Node's http client defaults to
      // chunked transfer-encoding once write()/end() are called separately --
      // and the daemon's plain http.server never decodes a chunked body, so
      // it silently sees an empty one. Every POST from this client carries a
      // body known in full upfront, so declaring its length here is always
      // correct and avoids chunking entirely.
      if (data) {
        headers['Content-Type'] = 'application/json';
        headers['Content-Length'] = Buffer.byteLength(data);
      }
      const req = mod.request(url, { method, headers }, (res) => {
        let raw = '';
        res.on('data', (c) => (raw += c));
        res.on('end', () => {
          let parsed = raw;
          try { parsed = JSON.parse(raw); } catch { /* plain text error body */ }
          if (res.statusCode === 426) {
            reject(new Error(`webcompanion contract mismatch: ${raw}`));
            return;
          }
          if (res.statusCode >= 400) {
            reject(new Error(`webcompanion ${method} ${path} -> ${res.statusCode}: ${raw}`));
            return;
          }
          resolve(parsed);
        });
      });
      req.setTimeout(this.timeoutMs, () => {
        req.destroy(new Error(`webcompanion ${method} ${path} timed out after ${this.timeoutMs} ms`));
      });
      req.on('error', reject);
      if (data) req.write(data);
      req.end();
    });
  }

  listSessions(cwd, kind) {
    let path = `/api/sessions?cwd=${encodeURIComponent(cwd)}`;
    if (kind) path += `&kind=${encodeURIComponent(kind)}`;
    return this._request('GET', path);
  }

  _session(sid, route) {
    return `/s/${sid}/${route}?kind=${encodeURIComponent(KIND)}`;
  }

  getPoll(sid) {
    return this._request('GET', this._session(sid, 'poll'));
  }

  getThread(sid, anchor) {
    return this._request('GET', this._session(sid, `threads/${encodeURIComponent(anchor)}`));
  }

  submit(sid, anchor, text) {
    return this._request('POST', this._session(sid, 'api/submit'), { anchor, text });
  }
}

module.exports = { WebCompanionClient, REQUEST_TIMEOUT_MS };
