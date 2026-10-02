// Bundles the editor into one IIFE for annotate's no-bundler page:
//   node skills/annotate/editor/build.mjs
// The first line of the output carries a hash of the sources; the test
// test_editor_bundle_fresh.py recomputes it to catch a stale bundle.
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, '..', 'static', 'vendor');
const out = join(outDir, 'editor.min.js');

// sha256 over the src/*.ts files sorted by name, concatenated, then package.json.
export function sourceHash() {
  const h = createHash('sha256');
  const src = join(here, 'src');
  for (const f of readdirSync(src).filter((n) => n.endsWith('.ts')).sort()) h.update(readFileSync(join(src, f)));
  h.update(readFileSync(join(here, 'package.json')));
  return h.digest('hex');
}

const local = join(here, 'node_modules', '.bin', 'esbuild');
const dashboard = join(homedir(), 'projects', 'dashboard', 'app', 'frontend', 'node_modules', '.bin', 'esbuild');
const esbuild = existsSync(local) ? local : dashboard;
if (!existsSync(esbuild)) throw new Error(`no esbuild at ${local} or ${dashboard}`);

mkdirSync(outDir, { recursive: true });
const js = execFileSync(esbuild, [
  join(here, 'src', 'index.ts'),
  '--bundle', '--format=iife', '--global-name=AnnotateEditor',
  '--minify', '--target=es2020', '--legal-comments=eof',
], { cwd: here, maxBuffer: 64 * 1024 * 1024 });
writeFileSync(out, Buffer.concat([Buffer.from(`/* annotate-editor ${sourceHash()} */\n`), js]));
writeFileSync(join(outDir, 'editor.LICENSE'), readFileSync(join(here, 'node_modules', '@codemirror', 'state', 'LICENSE')));
console.log(`${out}: ${js.length + 0} bytes (esbuild ${esbuild})`);
