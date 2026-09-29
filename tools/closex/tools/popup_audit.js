#!/usr/bin/env node
/* popup_audit.js - enumerate popup / sheet / modal / overlay builders and
 * classify each as has-X / no-X.
 *
 *   node popup_audit.js <tree> [--json]
 *
 * <tree> is a checkout root (app.py, desktop/renderer, frontend). A builder is
 * the enclosing function of any site that lays an element over the page:
 * position:fixed in a cssText / style.position, or a class whose stylesheet
 * rule is position:fixed. The builder "has-X" when its body carries a close
 * control: pineCloseX(, c:close, a ✕/×/✖ glyph on a clickable, or a
 * button labelled Close. Everything else is no-X and must be looked at.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const tree = process.argv[2] || '.';
const asJson = process.argv.includes('--json');

function read(p) { return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n'); }

/* The panel is one raw string inside app.py. */
function panelSource() {
  const src = read(path.join(tree, 'app.py'));
  const a = src.indexOf('CONTROL_PANEL_HTML = r"""');
  const b = src.indexOf('\n"""', a + 30);
  const pre = src.slice(0, a).split('\n').length;
  return {name: 'app.py#CONTROL_PANEL_HTML', text: src.slice(a, b), base: pre - 1};
}

function sources() {
  const out = [panelSource()];
  for (const dir of ['desktop/renderer', 'frontend']) {
    const d = path.join(tree, dir);
    for (const f of fs.readdirSync(d).sort()) {
      if (!/\.(js|html)$/.test(f)) continue;
      if (f === 'pine-icons.js') continue;            // generated sprite
      out.push({name: dir + '/' + f, text: read(path.join(d, f)), base: 0});
    }
  }
  return out;
}

/* Every class whose rule is position:fixed, from every stylesheet we ship. */
function fixedClasses() {
  const set = new Set();
  const css = [];
  for (const dir of ['desktop/renderer', 'frontend']) {
    const d = path.join(tree, dir);
    for (const f of fs.readdirSync(d)) if (/\.css$/.test(f)) css.push(read(path.join(d, f)));
  }
  css.push(panelSource().text);
  for (const text of css) {
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(text))) {
      if (!/position\s*:\s*fixed/.test(m[2])) continue;
      for (const sel of m[1].split(',')) {
        const c = sel.trim().match(/\.([A-Za-z][\w-]*)\s*$/);
        if (c) set.add(c[1]);
      }
    }
  }
  return set;
}

const FN_RE = /^(\s{0,6})(?:async\s+)?function\s*\*?\s*([\w$]+)\s*\(|^(\s{0,6})(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>)|^(\s{0,6})([\w$.]+)\s*=\s*(?:async\s*)?function\b/;
const X_RE = /pineCloseX\s*\(|c:close|["'`>]\s*(?:[✕×✖╳]|\\u2715|\\u00d7|\\u2716|&times;)\s*|[✕✖]\s*Close/;
const CLOSEWORD_RE = /["'`>]\s*(?:Close|close|Done|Dismiss|Got it)\s*["'`<]|aria-label=["']Close|['"]aria-label['"]\s*:\s*['"]Close/;

function audit() {
  const fixed = fixedClasses();
  const rows = [];
  for (const src of sources()) {
    const lines = src.text.split('\n');
    /* function starts: index -> name, indentation */
    const starts = [];
    lines.forEach((ln, i) => {
      const m = ln.match(FN_RE);
      if (m) starts.push({i, name: m[2] || m[4] || m[6], ind: (m[1] || m[3] || m[5] || '').length});
    });
    const byFn = new Map();
    lines.forEach((ln, i) => {
      let why = null;
      if (/position\s*:\s*fixed/.test(ln) || /\.position\s*=\s*["']fixed/.test(ln)) why = 'fixed';
      else {
        /* any quoted token that names a position:fixed class */
        const toks = [];
        ln.replace(/(["'`])((?:(?!\1).)*?)\1/g, (m, q, body) => { toks.push(...body.split(/\s+/)); return m; });
        if (toks.some((c) => fixed.has(c))) why = 'class';
      }
      if (!why) return;
      if (/^\s*(\/\/|\*|\/\*)/.test(ln)) return;     // a comment
      let fn = null;
      for (let k = starts.length - 1; k >= 0; k -= 1) {
        if (starts[k].i <= i && starts[k].ind <= 4) { fn = starts[k]; break; }
      }
      const key = fn ? fn.name + '@' + fn.i : '(top)@' + i;
      if (!byFn.has(key)) byFn.set(key, {fn, first: i, why});
    });
    for (const [key, v] of byFn) {
      const from = v.fn ? v.fn.i : Math.max(0, v.first - 20);
      /* the body: to the next function start at the same-or-lower indent */
      let to = lines.length;
      for (const s of starts) {
        if (s.i > from && s.ind <= (v.fn ? v.fn.ind : 0)) { to = s.i; break; }
      }
      to = Math.min(to, from + 1200);
      const body = lines.slice(from, to).join('\n');
      const hasX = X_RE.test(body);
      const word = CLOSEWORD_RE.test(body);
      const helper = /pineCloseX\s*\(/.test(body);
      rows.push({
        file: src.name, line: src.base + v.first + 1,
        builder: v.fn ? v.fn.name : '(top level)',
        via: v.why, x: helper ? 'helper' : hasX ? 'has-X' : word ? 'word' : 'no-X',
      });
    }
  }
  return rows;
}

const rows = audit();
if (asJson) { process.stdout.write(JSON.stringify(rows, null, 1) + '\n'); return; }
const tally = {};
for (const r of rows) tally[r.x] = (tally[r.x] || 0) + 1;
for (const r of rows) console.log([r.x.padEnd(6), r.file + ':' + r.line, r.builder, r.via].join('\t'));
console.log('TOTAL', rows.length, JSON.stringify(tally));
