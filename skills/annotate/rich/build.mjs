// Bundles the rich editor into one IIFE for annotate's no-bundler page:
//   (cd skills/annotate/rich && npm ci) && node skills/annotate/rich/build.mjs
// The bundle uses the page's markdown-it (window.markdownit) through
// src/markdown-it-shim.js instead of carrying a second copy. The first line
// of the output carries a hash of the sources; test_rich_bundle_fresh.py
// recomputes it to catch a stale bundle.
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, '..', 'static', 'vendor');
const out = join(outDir, 'rich.min.js');

// sha256 over the src/*.js files sorted by name, concatenated, then package-lock.json.
export function sourceHash() {
  const h = createHash('sha256');
  const src = join(here, 'src');
  for (const f of readdirSync(src).filter((n) => n.endsWith('.js')).sort()) h.update(readFileSync(join(src, f)));
  h.update(readFileSync(join(here, 'package-lock.json')));
  return h.digest('hex');
}

const esbuild = join(here, 'node_modules', '.bin', 'esbuild');
if (!existsSync(esbuild)) throw new Error(`no esbuild at ${esbuild}: run npm ci in ${here}`);

mkdirSync(outDir, { recursive: true });
const js = execFileSync(esbuild, [
  join(here, 'src', 'index.js'),
  '--bundle', '--format=iife', '--global-name=AnnotateRich',
  '--minify', '--target=es2020', '--legal-comments=eof',
  `--alias:markdown-it=${join(here, 'src', 'markdown-it-shim.js')}`,
], { cwd: here, maxBuffer: 64 * 1024 * 1024 });
const buf = Buffer.concat([Buffer.from(`/* annotate-rich ${sourceHash()} */\n`), js]);
writeFileSync(out, buf);
writeFileSync(join(outDir, 'rich.LICENSE'), readFileSync(join(here, 'node_modules', 'prosemirror-model', 'LICENSE')));
console.log(`${out}: ${buf.length} bytes, ${gzipSync(buf).length} gzipped`);
