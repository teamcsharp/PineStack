/* Why is a book cover a strip? Builds three library cards with the desk's own stylesheets (styles.css +
   book-mode.css from PINE_DESKTOP_DIR), measures the cover box, then tries two fixes in turn and measures again.
   electron probe_book_cover.cjs      (env: PINE_DESKTOP_DIR, PINE_PROBE_OUT for a PNG of the last state) */
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const desktop = path.resolve(process.env.PINE_DESKTOP_DIR || '.');
const OUT = process.env.PINE_PROBE_OUT || '';
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-bookcover-')));
const delay = ms => new Promise(r => setTimeout(r, ms));
setTimeout(() => { console.error('timed out'); process.exit(1); }, 60000);
const fileUrl = p => 'file:///' + p.replace(/\\/g, '/');
const cover = (w, h, color) => 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '"><rect width="100%" height="100%" fill="' + color + '"/><rect x="8%" y="8%" width="84%" height="84%" fill="none" stroke="white" stroke-width="6"/><text x="50%" y="50%" fill="white" font-size="48" text-anchor="middle">' + w + 'x' + h + '</text></svg>');
const card = (title, author, img) => '<div class="bm-card"><button class="bm-cover bm-cover-loaded"><span class="bm-cover-title">' + title + '</span><img src="' + img + '" alt=""></button><button class="bm-card-title">' + title + '</button><small>' + author + '</small><button class="bm-read">Read</button><button>Preview</button></div>';
const html = '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="' + fileUrl(path.join(desktop, 'renderer', 'styles.css')) + '"><link rel="stylesheet" href="' + fileUrl(path.join(desktop, 'renderer', 'book-mode.css')) + '"><style>html,body{margin:0;background:#101b22}</style></head><body><section class="bm-panel bm-inline" style="position:static;inset:auto"><div class="bm-shelf"><div class="bm-books">'
  + card('1066 and All That', 'W. C. Sellar', cover(400, 600, '#8a3b2d')) + card('100 Million Years of Food', 'Stephen Le', cover(600, 900, '#2d5f8a')) + card('A square cover', 'Someone', cover(500, 500, '#3b7a4a'))
  + '</div></div></section></body></html>';
const fixture = path.join(app.getPath('userData'), 'books.html'); fs.writeFileSync(fixture, html);
const FIXES = {
  none: '',
  align: '.bm-card>.bm-cover{align-self:start}',
  pad: '.bm-card .bm-cover{height:0;padding:0 0 140%;box-sizing:content-box;aspect-ratio:auto}',
  both: '.bm-card>.bm-cover{align-self:start;height:0;padding:0 0 140%;box-sizing:content-box;aspect-ratio:auto}',
};
const MEASURE = `JSON.stringify([...document.querySelectorAll('.bm-cover')].map(b => { const r = b.getBoundingClientRect(); const i = b.querySelector('img'); const ir = i.getBoundingClientRect(); const cs = getComputedStyle(b); return { w: Math.round(r.width), h: Math.round(r.height), ratio: (r.height / Math.max(1, r.width)).toFixed(2), display: cs.display, aspect: cs.aspectRatio, alignSelf: cs.alignSelf, img: Math.round(ir.width) + 'x' + Math.round(ir.height), fit: getComputedStyle(i).objectFit }; }))`;
app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 760, height: 900, webPreferences: { offscreen: true, sandbox: false } });
  win.webContents.on('console-message', e => { if (e.level >= 2) console.log('  console:', String(e.message).slice(0, 160)); });
  await win.loadFile(fixture); await delay(800);
  for (const [name, css] of Object.entries(FIXES)) {
    await win.webContents.executeJavaScript('(() => { let s = document.getElementById("fix"); if (!s) { s = document.createElement("style"); s.id = "fix"; document.head.appendChild(s); } s.textContent = ' + JSON.stringify(css) + '; })()');
    await delay(300);
    console.log(name.padEnd(6), await win.webContents.executeJavaScript(MEASURE));
    if (OUT && name === 'pad') { fs.writeFileSync(OUT, (await win.webContents.capturePage()).toPNG()); console.log('saved', OUT); }
  }
  console.log('chrome', process.versions.chrome);
  win.destroy(); process.exit(0);
}).catch(e => { console.error(e); process.exit(1); });
