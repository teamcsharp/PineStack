/* Attach to the LIVE desk through its DevTools port and read the PiP panel as it really is.
   ELECTRON_RUN_AS_NODE=1 electron.exe desk_attach.cjs [PORT] [OUT_DIR]   (needs Node 22's global WebSocket) */
const fs = require('node:fs'), path = require('node:path');
const PORT = process.argv[2] || '9333', OUT = process.argv[3] || '.';
const STATE = `JSON.stringify((() => {
  const h = document.getElementById('pine-pip-panel');
  const v = window.PinePipPanel && window.PinePipPanel.viz && window.PinePipPanel.viz();
  const bg = h && h.querySelector('.pip-bg'); const c = bg && bg.querySelector('canvas');
  const cs = c ? getComputedStyle(c) : null; const bgs = bg ? getComputedStyle(bg) : null;
  return {
    url: location.href.slice(0, 60), pinePip: document.documentElement.classList.contains('pine-pip'),
    host: h ? [getComputedStyle(h).display, getComputedStyle(h).opacity, h.getBoundingClientRect().width + 'x' + h.getBoundingClientRect().height] : 'no host',
    bg: bg ? [bg.style.display, bgs.display, bgs.opacity, bgs.visibility, bg.getBoundingClientRect().width + 'x' + bg.getBoundingClientRect().height, bg.children.length] : 'no bg',
    canvas: c ? [c.width, c.height, cs.display, cs.opacity, cs.visibility, c.getBoundingClientRect().width + 'x' + c.getBoundingClientRect().height] : 'no canvas',
    PineViz: !!window.PineViz, THREE: !!window.THREE, viz: !!v, running: v ? v.running : null, mode: v ? v.activeId : null, incoming: v ? v.incoming : null,
    fps: v ? Math.round(v.fps || 0) : null, quality: v && v.renderer ? v.renderer.quality : null,
    sceneChildren: v && v.active && v.active.scene ? v.active.scene.children.length : null,
    scripts: [...document.scripts].filter(s => /pineviz|three/.test(s.src)).map(s => s.src.split('/').slice(-1)[0].slice(0, 40)),
    failure: h ? ((h.querySelector('.pip-failure') || {}).textContent || '') : '',
    logo: h ? (h.querySelector('.pip-logo') || {}).style && h.querySelector('.pip-logo').style.display : '',
    tiles: h ? h.querySelectorAll('.pip-tile').length : 0,
    storage: (() => { try { return { mode: localStorage.getItem('pinePipVizMode'), presets: (localStorage.getItem('pinePipVizPresets') || '').slice(0, 80) }; } catch (e) { return 'err'; } })(),
    gl: (() => { try { const g = c && (c.getContext('webgl2') || c.getContext('webgl')); return g ? { err: g.getError(), lost: g.isContextLost() } : 'none'; } catch (e) { return 'err ' + e.message; } })()
  };
})())`;
async function main() {
  if (typeof WebSocket === 'undefined') { console.log('no global WebSocket in this Node'); process.exit(3); }
  const http = require('node:http');
  const targets = await new Promise((resolve, reject) => { const req = http.get({ host: '127.0.0.1', port: Number(PORT), path: '/json', timeout: 5000 }, res => { let b = ''; res.on('data', d => { b += d; }); res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } }); }); req.on('timeout', () => { req.destroy(new Error('json list timed out')); }); req.on('error', reject); });
  console.log('targets:', targets.map(t => t.type + ' ' + (t.url || '').slice(0, 70)).join(' | '));
  const station = targets.find(t => /10\.89\.1\.246:8096/.test(t.url || '')) || targets.find(t => t.type === 'webview');
  if (!station) { console.log('no station target'); process.exit(2); }
  const ws = new WebSocket(station.webSocketDebuggerUrl);
  let id = 0; const waiting = new Map(); const logs = [];
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); } else if (m.method === 'Runtime.consoleAPICalled' && (m.params.type === 'error' || m.params.type === 'warning')) logs.push(m.params.type + ': ' + m.params.args.map(a => a.value || a.description || '').join(' ').slice(0, 160)); else if (m.method === 'Runtime.exceptionThrown') logs.push('exception: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 220)); };
  const send = (method, params = {}) => new Promise(r => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  console.log('socket:', station.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = e => j(new Error('socket error ' + (e && e.message || ''))); ws.onclose = e => j(new Error('socket closed ' + e.code + ' ' + (e.reason || ''))); setTimeout(() => j(new Error('socket open timed out after 15 s')), 15000); });
  console.log('attached');
  await send('Runtime.enable');
  const delay = ms => new Promise(r => setTimeout(r, ms));
  for (let round = 0; round < 3; round++) {
    const res = await send('Runtime.evaluate', { expression: STATE, returnByValue: true });
    console.log('t' + round + ':', res.result && res.result.result ? res.result.result.value : JSON.stringify(res).slice(0, 300));
    await delay(3000);
  }
  try { const shot = await send('Page.captureScreenshot', { format: 'png' }); if (shot.result && shot.result.data) { const out = path.join(OUT, 'desk_live.png'); fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64')); console.log('saved', out); } } catch (e) { console.log('no screenshot:', e.message); }
  console.log('console since attach (' + logs.length + '):'); logs.slice(0, 12).forEach(l => console.log('  ' + l));
  ws.close(); process.exit(0);
}
main().catch(e => { console.error('attach failed:', e.message); process.exit(1); });
