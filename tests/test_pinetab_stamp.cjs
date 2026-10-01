/* [pinetab-stamp] deploy.sh's bash stamp (after its view sync) and the desk's node
 * stamp (simulating that sync) must agree, or the tablet button pulses for ever. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { stamp, stampOf } = require('../desktop/pinetab-stamp.cjs');

const repo = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pinestamp-'));
try {
  execFileSync('bash', ['-c', `mkdir -p "${tmp}/app" "${tmp}/desktop" "${tmp}/tools" && cp -r "${repo}/app/src" "${tmp}/app/src" && cp "${repo}/app/build.gradle.kts" "${tmp}/app/" && cp -r "${repo}/desktop/renderer" "${tmp}/desktop/renderer" && cp "${repo}/tools/pinetab-stamp.sh" "${tmp}/tools/"`]);
  // make the sync matter: the canonical copy moves on, the APK's copy has not
  fs.appendFileSync(path.join(tmp, 'desktop/renderer/sfx-tv.js'), '\n/* changed on the desk */\n');
  fs.appendFileSync(path.join(tmp, 'desktop/renderer/script-page.js'), '\n/* changed on the desk */\n');
  const wanted = stamp(tmp).stamp;
  const before = stamp(tmp, null, { synced: false }).stamp;
  assert.notStrictEqual(wanted, before, 'the simulated sync changes the stamp');
  // deploy.sh's sync, verbatim in effect, then its stamp
  const sync = `
HERE="${tmp}"; VIEW_CANON="$HERE/desktop/renderer"
VIEW_PANEL="$HERE/app/src/main/assets/pine-views"; VIEW_SAMPLER="$HERE/app/src/main/assets/pine-sampler"
for target in "$VIEW_PANEL"/*; do [ -f "$target" ] || continue; asset=\${target##*/}
  [ "$asset" = talk-dot.js ] && continue; [ -f "$VIEW_CANON/$asset" ] && cp "$VIEW_CANON/$asset" "$target"; done
for asset in sfx-tv.js sfx-tv.css; do [ -f "$VIEW_CANON/$asset" ] && cp "$VIEW_CANON/$asset" "$VIEW_SAMPLER/$asset"; done
for asset in sampler-air.js sampler-feed.js sampler.js; do [ -f "$VIEW_CANON/$asset" ] && [ -f "$VIEW_SAMPLER/$asset" ] && cp "$VIEW_CANON/$asset" "$VIEW_SAMPLER/$asset"; done
. "$HERE/tools/pinetab-stamp.sh"; pine_stamp "$HERE"`;
  const built = execFileSync('bash', ['-c', sync]).toString().trim();
  assert.strictEqual(built, wanted, 'bash after the sync == node before it');
  assert.strictEqual(stamp(tmp).stamp, wanted, 'and node after it too');
  assert.strictEqual(stampOf('Mozilla/5.0 ... PineBoxKiosk/1.0.0+' + wanted), wanted);
  assert.strictEqual(stampOf('versionName=1.0.0+' + wanted), wanted);
  assert.strictEqual(stampOf('PineBoxKiosk/1.0.0'), '');
  console.log('pinetab stamp: ok (' + wanted + ', ' + stamp(tmp).files + ' files)');
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
