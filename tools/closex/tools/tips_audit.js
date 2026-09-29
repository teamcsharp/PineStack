#!/usr/bin/env node
/* tips_audit.js - icon-only buttons with no hover tooltip.
 *
 *   node tips_audit.js <repo-root> [--json] [--files a,b]
 *
 * An icon-only button is one whose visible text carries no letter or digit:
 * a glyph ("\u2715", "\u27f3", an emoji the icon font draws), an SVG from
 * pineIcon(), or nothing but a data-pine-icon. It needs a `title` (the hover
 * tooltip) - and an aria-label, which the title also serves when there is
 * none. Found in three shapes:
 *   A  V = el|make|mk|node("button", cls, "TEXT")  then V.title within 14 lines
 *   B  V = document.createElement("button") ... V.textContent = "TEXT" |
 *      V.innerHTML = pineIcon(..) | iconInto(V, ..)  then V.title
 *   C  <button ...>INNER</button> in markup, with no title= on the tag
 * Exit 1 when any is found (the regression test's static half).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(process.argv[2] || '.');
const asJson = process.argv.includes('--json');
const onlyFiles = process.argv.includes('--files') ? process.argv[process.argv.indexOf('--files') + 1].split(',') : null;

const decode = (s) => s.replace(/\\u\{([0-9a-fA-F]+)\}/g, (m, h) => String.fromCodePoint(parseInt(h, 16)))
  .replace(/\\u([0-9a-fA-F]{4})/g, (m, h) => String.fromCharCode(parseInt(h, 16)))
  .replace(/&#(\d+);/g, (m, d) => String.fromCodePoint(+d)).replace(/&#x([0-9a-f]+);/gi, (m, h) => String.fromCodePoint(parseInt(h, 16)))
  .replace(/&[a-z]+;/g, '\u2022');
const iconOnly = (text) => { const t = decode(text).replace(/<[^>]*>/g, '').replace(/\s+/g, ''); return !/[\p{L}\p{N}]/u.test(t); };

function sources() {
  const out = [];
  const src = fs.readFileSync(path.join(root, 'app.py'), 'utf8').replace(/\r\n/g, '\n');
  const a = src.indexOf('CONTROL_PANEL_HTML = r"""');
  const b = src.indexOf('\n"""', a + 30);
  out.push({name: 'app.py', text: src.slice(a, b), base: src.slice(0, a).split('\n').length - 1});
  for (const dir of ['desktop/renderer', 'frontend']) {
    for (const f of fs.readdirSync(path.join(root, dir)).sort()) {
      if (!/\.(js|html)$/.test(f) || f === 'pine-icons.js') continue;
      out.push({name: dir + '/' + f, text: fs.readFileSync(path.join(root, dir, f), 'utf8').replace(/\r\n/g, '\n'), base: 0});
    }
  }
  return onlyFiles ? out.filter((s) => onlyFiles.some((f) => s.name.endsWith(f))) : out;
}

/* labelled at runtime (their words are set when they are painted) - read
   and allowed, each with why */
const ALLOW = [
  ['desktop/renderer/renderer.js', 'const b = mk("button", "", "");', 'trackPick rows: filled with the track name'],
  ['desktop/renderer/script-page.js', "var line = make('button', 'sp-itin-message', '');", 'itinerary rows: filled with the line text'],
  ['desktop/renderer/presentation.js', '<button id="pvHear" class="pv-mini"></button>', 'labelled on every transport paint: Hear it here / Quiet here'],
  ['desktop/renderer/pine-cam.js', '<button type="button" class="pcl-run" hidden></button>', 'hidden until the ladder names its step'],
];
const allowed = (file, line) => ALLOW.some(([f, snip]) => file === f && line.includes(snip));
const hits = [];
for (const s of sources()) {
  const L = s.text.split('\n');
  const titled = (v, i, span) => {
    const re = new RegExp('\\b' + v.replace(/[$]/g, '\\$') + '\\.(title\\s*=|setAttribute\\(\\s*["\']title["\'])|\\b' + v + '\\b[^;]*\\btitle\\s*:');
    for (let k = i; k < Math.min(L.length, i + span); k += 1) if (re.test(L[k])) return true;
    /* replaced by the corner X (pineCloseX presses it, and it steps aside) */
    for (let k = i; k < Math.min(L.length, i + span + 40); k += 1) {
      if (L[k].includes('pineCloseX(') && new RegExp('\\b' + v + '\\.(click\\(\\)|remove\\(\\)|style\\.display)').test(L[k])) return true;
    }
    /* a shared "say what it does" pass: [[v, "..."], ...].forEach(... title ...) */
    for (let k = i; k < Math.min(L.length, i + span + 20); k += 1) {
      if (new RegExp('\\[\\s*' + v + '\\s*,\\s*["\']').test(L[k])) return true;
    }
    return false;
  };
  L.forEach((ln, i) => {
    if (allowed(s.name, ln)) return;
    let m = ln.match(/(?:const|let|var)\s+([\w$]+)\s*=\s*(?:el|make|mk|node|h)\(\s*["']button["']\s*,\s*(?:["'][^"']*["']|null|undefined|'')\s*,\s*(["'])((?:(?!\2).)*)\2\s*\)/);
    if (!m) m = ln.match(/(?:const|let|var)\s+([\w$]+)\s*=\s*node\(\s*["']button["']\s*,\s*(["'])((?:(?!\2).)*)\2\s*\)/);
    /* built empty and labelled a line or two later: labelled if a word goes in */
    const labelledLater = (v) => {
      if (!v) return false;
      for (let k = i + 1; k < Math.min(L.length, i + 12); k += 1) {
        const t = L[k];
        if (new RegExp('\\b' + v + '\\.(textContent|innerText)\\s*=').test(t) && !/=\s*["'][^"'\p{L}\p{N}]*["']\s*;/u.test(t)) return true;
        if (new RegExp('\\b' + v + '\\.(append|appendChild)\\(').test(t) && !/pineIcon|Glyph|svg|icon/i.test(t)) return true;
        if (new RegExp('\\b' + v + '\\.innerHTML\\s*=').test(t) && /[\p{L}]{3,}/u.test(t.replace(/<[^>]*>|pineIcon\([^)]*\)|class=\S+/g, ''))) return true;
      }
      return false;
    };
    if (m && m[3] === '' && labelledLater(m[1])) return;
    if (m && iconOnly(m[3]) && !titled(m[1], i, 14)) {
      hits.push({file: s.name, line: s.base + i + 1, shape: 'A', v: m[1], text: decode(m[3]).slice(0, 12)});
      return;
    }
    const c = ln.match(/(?:const|let|var)\s+([\w$]+)\s*=\s*document\.createElement\(\s*["']button["']\s*\)/);
    if (c) {
      const v = c[1];
      let icon = null;
      for (let k = i; k < Math.min(L.length, i + 8); k += 1) {
        const t = L[k].match(new RegExp('\\b' + v + '\\.(?:textContent|innerText)\\s*=\\s*(["\'])((?:(?!\\1).)*)\\1'));
        if (t) { icon = iconOnly(t[2]) ? decode(t[2]) : null; break; }
        if (new RegExp('\\b' + v + '\\.innerHTML\\s*=\\s*pineIcon|iconInto\\(\\s*' + v + '\\b').test(L[k])) { icon = '(svg)'; break; }
      }
      if (icon !== null && !titled(v, i, 14)) hits.push({file: s.name, line: s.base + i + 1, shape: 'B', v, text: icon.slice(0, 12)});
      return;
    }
    const re = /<button\b([^>]*)>([^<]*(?:<(?!\/button)[^<]*)*)<\/button>/g;
    let h;
    while ((h = re.exec(ln))) {
      if (/\btitle\s*=/.test(h[1])) continue;
      if (/\$\{|["']\s*\+/.test(h[2])) continue;                    /* a label filled in at runtime */
      if (!iconOnly(h[2])) continue;
      if (/data-pine-icon/.test(h[1] + h[2]) && /aria-label\s*=/.test(h[1])) {
        hits.push({file: s.name, line: s.base + i + 1, shape: 'C', v: '', text: '(icon, aria only)'}); continue;
      }
      hits.push({file: s.name, line: s.base + i + 1, shape: 'C', v: '', text: decode(h[2]).replace(/<[^>]*>/g, '').trim().slice(0, 12)});
    }
  });
}

if (asJson) process.stdout.write(JSON.stringify(hits, null, 1) + '\n');
else {
  const by = {};
  for (const h of hits) by[h.file] = (by[h.file] || 0) + 1;
  for (const h of hits) console.log([h.file + ':' + h.line, h.shape, h.v, JSON.stringify(h.text)].join('\t'));
  console.log('ICON-ONLY WITHOUT TITLE', hits.length, JSON.stringify(by));
}
process.exit(hits.length ? 1 : 0);
