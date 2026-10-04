// Reads webcompanion's own config file -- the fixed, documented path every
// consumer (the CLI, and now this extension) reads, per the daemon's
// "one file, no discovery poll" design.

const fs = require('fs/promises');
const os = require('os');
const path = require('path');

const DEFAULT_PATH = path.join(os.homedir(), '.claude', 'webcompanion', 'config.json');

async function loadConfig(configPath = DEFAULT_PATH) {
  const raw = await fs.readFile(configPath, 'utf8');
  return JSON.parse(raw);
}

module.exports = { loadConfig, DEFAULT_PATH };
