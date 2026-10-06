/* Run with Electron: full desktop DOM, no station writes or media playback. */
const {app, BrowserWindow, ipcMain} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
app.disableHardwareAcceleration();
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-view-test-')));
app.whenReady().then(async () => {
  const root = process.env.PINE_LENS_TEST_ROOT || path.resolve(__dirname, '..');
  const desktop = path.join(root, 'desktop');
  const channels = [...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer.invoke\(["']([^"']+)/g)].map(m => m[1]);
  for (const channel of new Set(channels)) ipcMain.handle(channel, async () => channel === 'config:read'
    ? {baseUrl: 'http://127.0.0.1:1', mode: 'attach', apiKey: ''}
    : {ok: true, lines: [], items: [], rows: [], hosts: []});
  const win = new BrowserWindow({show: false, width: 1340, height: 900,
    webPreferences: {offscreen: true, webviewTag: true, preload: path.join(desktop, 'preload.js')}});
  await win.loadFile(path.join(desktop, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 2500));
  const result = await win.webContents.executeJavaScript(`(async () => {
    PineViewRail.closeAll(); document.getElementById('pineViewTab-script').click();
    await new Promise(r => setTimeout(r, 300));
    const script = document.getElementById('script');
    const lens = document.getElementById('pinelens');
    const visible = {script: getComputedStyle(script).display, scriptHeight: script.clientHeight,
      scriptChildren: script.childElementCount, lens: getComputedStyle(lens).display};
    const pane = document.createElement('section'); document.body.appendChild(pane);
    PineFlowChart.show(pane, true);
    const turn = {id:'t:two', type:'turn', turn_id:'two', index:1, who:'Skip', leg:'reply',
      asked:'Answer Host', reply_to:{turn_id:'one', name:'Host', index:0}, turn_credit:1, inner_reply:true};
    const flow = {key:'test', revision:1, road:'banter', edges:[], counts:{}, nodes:[
      {id:'start:test',type:'start',label:'Test'},
      {id:'t:one',type:'turn',turn_id:'one',index:0,who:'Host',leg:'initiator'}, turn,
      {id:'end:test',type:'end',label:'planned'}]};
    PineFlowChart._paint(flow);
    const technical = pane.textContent;
    pane.querySelector('.fc-mode').click();
    const design = pane.textContent;
    const next = JSON.parse(JSON.stringify(flow)); next.revision=2;
    next.nodes[2].reply_to.name='Sam'; next.nodes[2].cast_reaction=true;
    PineFlowChart._paint(next);
    const revisedDesign=pane.textContent;
    pane.querySelector('.fc-mode').click();
    const revisedTechnical=pane.textContent;
    PineFlowChart.show(pane,false); pane.remove();
    document.querySelectorAll('.pine-splash').forEach(n => n.remove());
    return {visible, technical, design, revisedDesign, revisedTechnical};
  })()`);
  assert.equal(result.visible.lens, 'none');
  assert.equal(result.visible.script, 'grid');
  assert.ok(result.visible.scriptHeight > 500 && result.visible.scriptChildren > 1);
  for (const content of [result.technical, result.design]) {
    assert.match(content, /Inner reply.*Host/); assert.match(content, /\+1 turn restored/);
    assert.match(content, /View answered turn/);
  }
  for (const content of [result.revisedTechnical, result.revisedDesign]) assert.match(content, /Cast reaction.*Sam/);
  fs.mkdirSync(path.join(root, 'artifacts'), {recursive: true});
  fs.writeFileSync(path.join(root, 'artifacts', 'desktop-script-regression.png'), (await win.webContents.capturePage()).toPNG());
  console.log('Desktop views: closed PineLens stays hidden; Script renders; both flow charts refresh reply targets and credits.');
  win.destroy(); app.quit();
}).catch(error => {console.error(error); app.exit(1);});
