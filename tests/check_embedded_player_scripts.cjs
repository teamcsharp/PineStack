const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const vm = require('node:vm');
const interpreter = process.env.PINE_PYTHON || (process.platform === 'win32' ? 'py' : 'python3');
const run = spawnSync(interpreter, [path.join(__dirname, 'extract_embedded_players.py')],
  {encoding: 'utf8', maxBuffer: 50 * 1024 * 1024});
assert.equal(run.status, 0, run.stderr || String(run.error || 'Extraction failed'));
const pages = JSON.parse(run.stdout);
let scripts = 0;
for (const page of pages) {
  for (const match of page.html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)) {
    if (!match[2].trim()) continue;
    // The modified players are classic scripts. Module-only visuals are separate assets.
    if (/\btype\s*=\s*['"]module['"]/i.test(match[1])) continue;
    new vm.Script(match[2], {filename: `app.py:${page.line}:script${++scripts}`});
  }
}
assert(scripts >= 2, 'Both complete playback scripts must be parsed');
console.log(`Parsed Python AST and ${scripts} complete embedded playback scripts.`);
