/* [pinetab-stamp] What the PineTab's APK would be built from right now - the same
 * stamp tools/pinetab-stamp.sh computes inside deploy.sh, computed WITHOUT running
 * the sync: every file deploy.sh would copy from desktop/renderer into the APK's
 * assets is read from the renderer instead. tests/test_pinetab_stamp.cjs runs both
 * on one tree and holds them equal.
 *
 * Lines, one per file, sorted bytewise by path: "<sha1 of bytes>  <path>\n";
 * the stamp is the first 12 hex of their sha1. A file's hash is cached by its
 * size and mtime, so a poll re-reads only what changed (the tree is on a share). */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const CACHE = new Map();

function sha1(buf) { return crypto.createHash('sha1').update(buf).digest('hex'); }

function fileSha(abs) {
  const st = fs.statSync(abs);
  const key = abs + '|' + st.size + '|' + st.mtimeMs;
  const hit = CACHE.get(abs);
  if (hit && hit.key === key) return hit.sha;
  const sha = sha1(fs.readFileSync(abs));
  CACHE.set(abs, { key, sha });
  return sha;
}

function walk(root, rel, out) {
  let names;
  try { names = fs.readdirSync(path.join(root, rel), { withFileTypes: true }); } catch (e) { return; }
  for (const d of names) {
    const r = rel + '/' + d.name;
    if (d.isDirectory()) walk(root, r, out);
    else if (d.isFile()) out.push(r);
  }
}

/* The sync deploy.sh does (its "syncing canonical shared views" step), as a map
 * from a repo path to the file its bytes would come from. */
function syncedFrom(root, canon, files) {
  const src = new Map();
  const panel = 'app/src/main/assets/pine-views/';
  const sampler = 'app/src/main/assets/pine-sampler/';
  const has = (p) => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } };
  for (const f of files) {
    if (f.startsWith(panel) && f.indexOf('/', panel.length) < 0) {
      const asset = f.slice(panel.length);
      if (asset !== 'talk-dot.js' && has(path.join(canon, asset))) src.set(f, path.join(canon, asset));
    }
  }
  for (const asset of ['sfx-tv.js', 'sfx-tv.css']) {
    if (has(path.join(canon, asset))) src.set(sampler + asset, path.join(canon, asset));
  }
  for (const asset of ['sampler-air.js', 'sampler-feed.js', 'sampler.js']) {
    if (has(path.join(canon, asset)) && has(path.join(root, sampler + asset))) {
      src.set(sampler + asset, path.join(canon, asset));
    }
  }
  return src;
}

function stamp(root, canon, opts) {
  opts = opts || {};
  canon = canon || path.join(root, 'desktop', 'renderer');
  const files = [];
  walk(root, 'app/src', files);
  const rel = files.map((f) => f.replace(/^\//, ''));
  const from = opts.synced === false ? new Map() : syncedFrom(root, canon, rel);
  for (const f of from.keys()) if (rel.indexOf(f) < 0) rel.push(f);
  rel.push('app/build.gradle.kts');
  rel.sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  const lines = rel.map((f) => fileSha(from.get(f) || path.join(root, f)) + '  ' + f + '\n');
  return { stamp: sha1(Buffer.from(lines.join(''))).slice(0, 12), files: rel.length };
}

/* The stamp a kiosk carries: its versionName "1.0.0+<stamp>" (in its user agent
 * "PineBoxKiosk/1.0.0+<stamp>", or in dumpsys package's versionName). */
function stampOf(text) {
  const m = /(?:PineBoxKiosk\/|versionName=)?\d+\.\d+\.\d+\+([0-9a-f]{12})/.exec(String(text || ''));
  return m ? m[1] : '';
}

module.exports = { stamp, stampOf, syncedFrom };
