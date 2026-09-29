// node fnbody.js <file> <fnName|line>... [--print] : body of a function + its close words
const fs = require('fs');
const args = process.argv.slice(2);
const print = args.includes('--print');
const f = args[0];
const L = fs.readFileSync(f, 'utf8').replace(/\r\n/g, '\n').split('\n');
for (const key of args.slice(1).filter((a) => a !== '--print')) {
  const want = new RegExp(String.raw`^\s{0,6}(async\s+)?function\s+` + key + String.raw`\s*\(|^\s{0,6}(const|let|var)\s+` + key + String.raw`\s*=`);
  const s = /^\d+$/.test(key) ? +key - 1 : L.findIndex((l) => want.test(l));
  if (s < 0) { console.log('?? ' + key); continue; }
  const ind = (L[s].match(/^\s*/) || [''])[0].length;
  const stop = new RegExp('^\\s{0,' + ind + '}(\\}|(async\\s+)?function\\s)');
  let e = s + 1;
  while (e < L.length && !stop.test(L[e])) e++;
  const body = L.slice(s, e + 1).join('\n');
  const words = (body.match(/Done|Dismiss|Got it|Cancel|\w*[Cc]lose\w*\(\)|\.remove\(\)|Escape|mouseleave|setTimeout|"[✕×✖][^"]*"|'[✕×✖][^']*'|Close["']|PineDismiss\.\w+|pineCloseX/g) || []);
  const c = {};
  words.forEach((w) => { c[w] = (c[w] || 0) + 1; });
  console.log('== ' + key + ' @' + (s + 1) + '-' + (e + 1) + ' :: ' + JSON.stringify(c));
  if (print) console.log(body);
}
