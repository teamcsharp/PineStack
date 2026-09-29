#!/usr/bin/env node
/* closex_test.js - the regression test for "every popup has an X in its
 * corner, and every icon button says what it does".
 *
 *   node closex_test.js <repo-root> [--profile desk|tablet] [--only a,b]
 *
 * 1. static: tips_audit.js - no icon-only button without a title (exit 1 names them)
 * 2. static: the helper copies agree (desktop/renderer vs pine-views, when both exist)
 * 3. runtime: closex_harness.js - headless Edge (--mute-audio), desk 1920x1080 and
 *    tablet 1340x800; every case opens its popup with stubbed data and must show a
 *    visible X in the top-right 64 px corner that a click reaches, that closes it,
 *    and Escape must close it too. NOT-OPENED cases are listed with the reason.
 */
'use strict';
const {spawnSync} = require('child_process');
const path = require('path');
const fs = require('fs');
const root = path.resolve(process.argv[2] || '.');
const rest = process.argv.slice(3);
let fail = 0;

const tips = spawnSync(process.execPath, [path.join(__dirname, 'tips_audit.js'), root], {encoding: 'utf8'});
process.stdout.write(tips.stdout.split('\n').slice(-2).join('\n'));
if (tips.status !== 0) { fail += 1; process.stdout.write(tips.stdout); }

const a = path.join(root, 'desktop/renderer/pine-dismiss.js');
const b = path.join(root, 'app/src/main/assets/pine-views/pine-dismiss.js');
if (fs.existsSync(b) && fs.readFileSync(a, 'utf8') !== fs.readFileSync(b, 'utf8')) {
  console.log('FAIL pine-dismiss.js: kiosk mirror differs from desktop/renderer'); fail += 1;
}

const run = spawnSync(process.execPath, [path.join(__dirname, 'closex_harness.js'), root, ...rest], {encoding: 'utf8', stdio: 'inherit'});
if (run.status !== 0) fail += 1;
console.log(fail ? 'CLOSEX TEST: FAIL' : 'CLOSEX TEST: PASS');
process.exit(fail ? 1 : 0);
