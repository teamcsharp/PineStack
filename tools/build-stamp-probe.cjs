/* DOES THE MARK NOTICE? - the freshness line, measured instead of trusted.
 *
 *   node tools/build-stamp-probe.cjs <share>/desktop <mirror>/desktop
 *
 * The pine mark in the rail says "newest source" or "older than the share",
 * and the operator presses it on that word alone. It is computed from a
 * file list, and a file list is a blind spot waiting to happen: the first
 * one named six files, the second walked renderer/ and still named main.js
 * and preload.js by hand - leaving their twenty-one .cjs siblings and two
 * .ps1 workers, all loaded by the main process, outside the comparison.
 *
 * This runs BOTH rules over the same pair of trees so the difference is a
 * measurement rather than a claim. Copy desktop/ somewhere, make one file
 * old, and read the two lines.
 *
 * Measured 2026-09-13, against the share and a copy of it:
 *
 *   identical trees          old: no    new: no     (neither cries wolf)
 *   stale renderer/sfx-tv.js old: YES   new: YES    (no coverage lost)
 *   stale clip-mux.cjs       old: no    new: YES    <- the blind spot
 *   stale lcd-serial.ps1     old: no    new: YES    <- and the other one
 *
 * `stale` is computed exactly as desktop:build computes it, bytes first -
 * robocopy /MIR preserves mtimes, so two trees differing in content but
 * not in clock would otherwise compare equal.
 */
const fs = require('node:fs');
const path = require('node:path');

function oldStamp(root) {
  const wanted = ['main.js', 'preload.js'];
  try {
    for (const e of fs.readdirSync(path.join(root, 'renderer'), {withFileTypes: true})) {
      if (e.isFile() && /\.(js|css|html)$/i.test(e.name)) wanted.push('renderer/' + e.name);
    }
  } catch {}
  return tally(root, wanted);
}

function newStamp(root) {
  const wanted = [];
  const walk = (rel) => {
    let entries;
    try { entries = fs.readdirSync(path.join(root, rel) || root, {withFileTypes: true}); }
    catch { return false; }
    for (const e of entries) {
      const name = rel ? rel + '/' + e.name : e.name;
      if (e.isDirectory()) walk(name); else if (e.isFile()) wanted.push(name);
    }
    return true;
  };
  walk('');
  return tally(root, wanted);
}

function tally(root, wanted) {
  let newest = 0, bytes = 0;
  for (const name of wanted) {
    try {
      const info = fs.statSync(path.join(root, name));
      newest = Math.max(newest, info.mtimeMs);
      bytes += info.size;
    } catch {}
  }
  return {newest, bytes, counted: wanted.length};
}

/* desktop:build's own words. */
function stale(mine, theirs) {
  return theirs.bytes !== mine.bytes || theirs.newest > mine.newest + 1500;
}

const share = process.argv[2];
const mirror = process.argv[3];
for (const [label, rule] of [['old (main+preload+renderer)', oldStamp],
                             ['new (the whole tree)', newStamp]]) {
  const mine = rule(mirror);
  const theirs = rule(share);
  console.log(label.padEnd(30)
    + ' counted ' + String(mine.counted).padStart(3)
    + ' | mine ' + mine.bytes + 'b  theirs ' + theirs.bytes + 'b'
    + ' | stale: ' + (stale(mine, theirs) ? 'YES' : 'no'));
}
