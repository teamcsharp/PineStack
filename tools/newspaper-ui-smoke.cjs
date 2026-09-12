// Exercise the real newspaper UI and vendored renderer in hidden Chromium.
// Fixture responses are local; no station or operating-system clipboard writes.
const {app, BrowserWindow, nativeImage} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const output = path.join(os.tmpdir(), 'pine-newspaper-ui-smoke');
app.setPath('userData', path.join(output, 'profile'));
const source = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
function section(from, to) {
  const start = source.indexOf(from);
  const end = source.indexOf(to, start + from.length);
  assert.ok(start >= 0 && end > start, from);
  return source.slice(start, end);
}
app.whenReady().then(async () => {
  let win;
  try {
    win = new BrowserWindow({show: false, width: 1100, height: 880,
      webPreferences: {contextIsolation: true, nodeIntegration: false, offscreen: true, backgroundThrottling: false}});
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><style>body{margin:0;background:#08101b;color:#ebf4ff;font:16px Arial}.panel{background:#152539;border:1px solid #367797;border-radius:12px}.muted{color:#bbcad8}button{cursor:pointer}#station{padding:30px}</style><main id="station"><h1>Pine Box FM</h1><p>The live hour · Newspaper preview</p><button id="copy">Copy</button><p id="status"></p><iframe id="paper" style="width:420px;height:550px;border:0"></iframe></main>'));
    const setup = `
      let paperBox = null, paperReadBox = null, paperReadSeq = 0, paperSeen = '';
      let paperCur = 'smoke-edition', paperStyle = 'broadsheet', paperSnapBusy = false, paperText = null;
      const paperFrame = document.getElementById('paper'), paperCopyBtn = document.getElementById('copy'), paperImageBtn = null;
      window.el = (tag, cls, text) => {const n = document.createElement(tag); n.className = cls; n.textContent = text; return n;};
      window.callerDossierEsc = (s) => {const n = document.createElement('span'); n.textContent = String(s || ''); return n.innerHTML;};
      window.setStatus = (s) => {document.getElementById('status').textContent = s;};
      window.key = () => '';
      window.paperOpen = async () => {paperBox = {};};
      window.paperShow = async (id) => {window.openedEdition = id;};
      window.paperRefresh = () => {};
      window.paperCopied = '';
      window.pineDesktop = {copyImage: (data) => {window.paperCopied = data; return true;}};
      window.fetch = async () => ({json: async () => ({ok: true, title: 'The midnight market finds its voice',
        byline: 'City correspondent', host: 'example.org', published: '2026-09-06',
        paragraphs: ['A copper bell sounded across the square.', 'Then silence.', 'The market will open again at dawn.'],
        blocks: [{k: 'p', t: 'A copper bell sounded across the square.'}, {k: 'h', t: 'The neighbours respond'},
          {k: 'p', t: 'Then silence.'}, {k: 'q', t: 'We will be back.'}, {k: 'p', t: 'The market will open again at dawn.'}],
        images: [], notice: 'Fixture article: complete publisher text.'})});
      paperFrame.srcdoc = '<!doctype html><style>body{margin:0;background:#ddd}.page{box-sizing:border-box;width:400px;padding:28px;font:18px Georgia;margin:0 0 16px}.page h1{font-size:32px}#page-1{height:400px;background:#ffe0d0}#page-2{height:600px;background:#d0edff}</style><section class="page" id="page-1"><h1>The Pine Box Gazette</h1><p>Page 1 — the midnight market.</p></section><section class="page" id="page-2" hidden><h1>City life</h1><p>Page 2 — the blue bicycle is offered for repair.</p><p>Every page belongs in the copied image.</p></section>';
    `;
    await win.webContents.executeJavaScript(setup);
    await new Promise((resolve) => setTimeout(resolve, 100));
    const renderer = fs.readFileSync(path.join(__dirname, '..', 'data', 'vendor', 'html-to-image.js'), 'utf8');
    await win.webContents.executeJavaScript('paperFrame.contentWindow.eval(' + JSON.stringify(renderer) + '); void 0');
    await win.webContents.executeJavaScript([
      section('let paperBellSeen = null;', '/* #1037: Newspaper | Tabloid.'),
      section('function paperH2I()', 'function paperShrink('),
      section('async function paperEditionPng(what)', '/* #1029 #1020 #1047:'),
      section('function paperReadKeys(ev)', '/* #1020: every new edition gets one snapshot'),
      'paperCopyBtn.onclick = (event) => paperCopy(paperCopyBtn, event);',
    ].join('\n') + '\nvoid 0;');
    fs.mkdirSync(output, {recursive: true});
    await win.webContents.executeJavaScript("paperWatch({paper:{latest:'',running:false}}); paperWatch({paper:{latest:'smoke-edition',headline:'City life enters the next hour',running:false}})");
    const bell = await win.webContents.executeJavaScript("({role:document.getElementById('paperBell')?.getAttribute('role'), animation:getComputedStyle(document.getElementById('paperBell')).animationName})");
    assert.equal(bell.role, 'button'); assert.equal(bell.animation, 'paperBellPulse');
    fs.writeFileSync(path.join(output, 'notification.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript("document.getElementById('paperBell').click()");
    assert.equal(await win.webContents.executeJavaScript('window.openedEdition'), 'smoke-edition');
    await win.webContents.executeJavaScript("document.getElementById('copy').click()");
    for (let i = 0; i < 80; i++) {
      if (await win.webContents.executeJavaScript('!!window.paperCopied')) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const copied = await win.webContents.executeJavaScript('({png:window.paperCopied, hidden:paperFrame.contentDocument.getElementById("page-2").hidden, status:document.getElementById("status").textContent})');
    assert.ok(copied.png.startsWith('data:image/png;base64,'), copied.status);
    assert.equal(copied.hidden, true);
    assert.match(copied.status, /All 2 pages/);
    const png = nativeImage.createFromDataURL(copied.png);
    assert.equal(png.getSize().width, 800);
    assert.ok(png.getSize().height >= 2000, 'both complete pages are captured');
    fs.writeFileSync(path.join(output, 'all-pages.png'), png.toPNG());
    await win.webContents.executeJavaScript("paperReadOpen('https://example.org/story', 'The midnight market')");
    await new Promise((resolve) => setTimeout(resolve, 150));
    const reader = await win.webContents.executeJavaScript('({role:paperReadBox.getAttribute("role"), text:paperReadBox.innerText})');
    assert.equal(reader.role, 'dialog');
    assert.match(reader.text, /Then silence\./); assert.match(reader.text, /market will open again at dawn/);
    assert.match(reader.text, /September 6, 2026/i, 'date-only publication dates stay on their original day');
    fs.writeFileSync(path.join(output, 'reader.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript('document.dispatchEvent(new KeyboardEvent("keydown", {key:"Escape", bubbles:true}))');
    assert.equal(await win.webContents.executeJavaScript('paperReadBox === null'), true);
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ok: true, checks: 12,
      clipboardSize: png.getSize(), screenshots: ['notification.png', 'all-pages.png', 'reader.png'],
      stationWrites: 0, clipboardWrites: 0}, null, 2));
    console.log('Newspaper UI smoke passed: ' + output);
    win.destroy(); app.quit();
  } catch (error) {
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ok: false, error: error.stack}));
    console.error(error); if (win) win.destroy(); app.exit(1);
  }
});
