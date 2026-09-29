// node gen_legacy_py.js <app.py> <legacy.json> > rows : Python L(...) rows for closex_panel_legacy.py
'use strict';
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const a = src.indexOf('CONTROL_PANEL_HTML = r"""');
const b = src.indexOf('\n"""', a + 30);
const L = src.slice(a, b).split('\n');
const j = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const keep = j.patches.filter((p) => /^(x|shut|close)$/.test(p.v) && !/^(row|line|r|buttons)$/.test(p.P));
let py = '';
for (const p of keep) {
  const s = L.indexOf(p.sig);
  let k = s;
  while (k < L.length && !L[k].includes('const ' + p.v + ' = el(')) k += 1;
  let m = k;
  while (m < L.length && L[m] !== p.anchor) m += 1;
  const within = m - s + 3;
  py += '    L(' + [p.fname, p.sig, p.anchor, p.Q, p.v, p.ind].map((x) => JSON.stringify(x)).join(', ') + ', ' + within + '),\n';
}
process.stdout.write(py);
console.error(keep.length);
