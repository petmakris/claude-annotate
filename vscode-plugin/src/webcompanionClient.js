// HTTP client for the webcompanion daemon, used by the diff comment UI.
// Zero dependencies, matching the rest of this extension: plain `http`,
// same as diff.js's own git subprocess calls avoid pulling in a library.

const http = require('http');
const https = require('https');
const { URL } = require('url');

const CONTRACT = 1;

class WebCompanionClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  _request(method, path, body) {
    return new Promise((resolve, reject) => {
      const url = new URL(this.baseUrl + path);
      const mod = url.protocol === 'https:' ? https : http;
      const data = body !== undefined ? JSON.stringify(body) : null;
      const headers = { 'X-WebCompanion-Contract': String(CONTRACT) };
      if (data) headers['Content-Type'] = 'application/json';
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

  getPoll(sid) {
    return this._request('GET', `/s/${sid}/poll`);
  }

  getThread(sid, anchor) {
    return this._request('GET', `/s/${sid}/threads/${encodeURIComponent(anchor)}`);
  }

  submit(sid, anchor, text) {
    return this._request('POST', `/s/${sid}/api/submit`, { anchor, text });
  }
}

module.exports = { WebCompanionClient };
