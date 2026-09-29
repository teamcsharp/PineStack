#!/usr/bin/env node
/* gen_legacy.js - find the hand-rolled X of every panel popup and emit the
 * patch that hands it to pineCloseX (corner, 40 px, title, Escape), calling
 * the old X's own handler as the close road.
 *
 *   node gen_legacy.js <app.py> > legacy.json
 *
 * For a builder: `const V = el("span"|"button", "...", "✕"|"✕"|"×")`,
 * then `P.appendChild(V)`; the popup is the element P is appended to (Q),
 * or P itself when P is the popup root. Only emitted when Q is declared
 * before the insertion line (no temporal-dead-zone trap). */
'use strict';
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const a = src.indexOf('CONTROL_PANEL_HTML = r"""');
const b = src.indexOf('\n"""', a + 30);
const L = src.slice(a, b).split('\n');
const XRE = /^(\s*)const (\w+) = el\("(span|button|b|div)", "[^"]*", "(✕|\\u2715|×|\\u00d7|✖)"\);/;
const out = [], skipped = [];
for (let i = 0; i < L.length; i += 1) {
  const m = L[i].match(XRE);
  if (!m) continue;
  const [, ind, v] = m;
  // the enclosing function signature
  let s = i;
  while (s >= 0 && !/^(async\s+)?function\s+\w+\s*\(/.test(L[s])) s -= 1;
  if (s < 0) { skipped.push({line: i, why: 'no function'}); continue; }
  const sig = L[s];
  const fname = sig.match(/function\s+(\w+)/)[1];
  // P.appendChild(V) after i
  let j = i + 1, P = null;
  for (; j < Math.min(L.length, i + 30); j += 1) {
    const q = L[j].match(new RegExp('^\\s*(\\w+)\\.appendChild\\(' + v + '\\);\\s*$'));
    if (q) { P = q[1]; break; }
    const q2 = L[j].match(new RegExp('^\\s*\\[([^\\]]*\\b' + v + '\\b[^\\]]*)\\]\\.forEach\\(\\(\\w+\\) => (\\w+)\\.appendChild'));
    if (q2) { P = q2[2]; break; }
  }
  if (!P) { skipped.push({fname, line: i, v, why: 'no appendChild of the X'}); continue; }
  // popup Q: where P is appended, else P
  let Q = P;
  const decl = (name) => { for (let k = s; k <= j; k += 1) if (new RegExp('^\\s*(const|let|var)\\s+' + name + '\\b|^\\s*' + name + ' = ').test(L[k])) return k; return -1; };
  for (let k = j + 1; k < Math.min(L.length, j + 200); k += 1) {
    if (/^(async\s+)?function\s/.test(L[k])) break;
    const q = L[k].match(new RegExp('^\\s*(\\w+)\\.appendChild\\(' + P + '\\);'));
    if (q) { Q = q[1]; break; }
  }
  for (let k = s; k < i; k += 1) {                       // P appended before the X was made
    const q = L[k].match(new RegExp('^\\s*(\\w+)\\.appendChild\\(' + P + '\\);'));
    if (q) Q = q[1];
  }
  if (Q !== P && decl(Q) < 0) { skipped.push({fname, line: i, v, P, Q, why: 'popup declared after the X'}); continue; }
  const anchor = L[j];
  const sigCount = L.filter((x) => x === sig).length;
  out.push({fname, sig, sigCount, anchor, v, P, Q, ind});
}
process.stdout.write(JSON.stringify({patches: out, skipped}, null, 1) + '\n');
console.error('patches', out.length, 'skipped', skipped.length);
