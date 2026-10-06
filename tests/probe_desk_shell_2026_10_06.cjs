const http = require('node:http');
const PORT = process.argv[2] || '9333';
const Q = `new Promise(r => { const b = document.getElementById('books'); const wasOpen = b && b.classList.contains('open'); if (b) b.classList.remove('open'); setTimeout(() => { const m = document.querySelector('main'); const w = document.getElementById('controlFrame'); const rc = w.getBoundingClientRect(); r(JSON.stringify({ booksWasOpen: wasOpen, mainDisplay: getComputedStyle(m).display, webviewRect: [Math.round(rc.width), Math.round(rc.height)] })); }, 400); })`;
http.get({ host: '127.0.0.1', port: Number(PORT), path: '/json', timeout: 5000 }, res => { let b = ''; res.on('data', d => { b += d; }); res.on('end', async () => {
  const t = JSON.parse(b).find(x => /renderer\/index\.html/.test(x.url || ''));
  if (!t) { console.log('no shell target'); process.exit(2); }
  const ws = new WebSocket(t.webSocketDebuggerUrl); let id = 0; const waiting = new Map();
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); } };
  const send = (method, params = {}) => new Promise(r => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = () => j(new Error('socket')); setTimeout(() => j(new Error('timeout')), 15000); });
  const a = await send('Runtime.evaluate', { expression: Q, awaitPromise: true, returnByValue: true }); console.log('shell:', a.result && a.result.result && a.result.result.value);
  ws.close();
  const st = JSON.parse(b).find(x => /8096/.test(x.url || ''));
  const ws2 = new WebSocket(st.webSocketDebuggerUrl); let id2 = 0; const waiting2 = new Map();
  ws2.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && waiting2.has(m.id)) { waiting2.get(m.id)(m); waiting2.delete(m.id); } };
  const send2 = (method, params = {}) => new Promise(r => { const n = ++id2; waiting2.set(n, r); ws2.send(JSON.stringify({ id: n, method, params })); });
  await new Promise((r, j) => { ws2.onopen = r; ws2.onerror = () => j(new Error('socket2')); setTimeout(() => j(new Error('timeout2')), 15000); });
  await new Promise(r => setTimeout(r, 3000));
  const c = await send2('Runtime.evaluate', { expression: `new Promise(r => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 2000) requestAnimationFrame(f); else { const v = window.PinePipPanel.viz(); r(JSON.stringify({ rafIn2s: n, vizFps: Math.round(v.fps || 0), quality: v.renderer.quality, mode: v.activeId, running: v.running, viewport: [innerWidth, innerHeight] })); } }; requestAnimationFrame(f); })`, awaitPromise: true, returnByValue: true });
  console.log('station page after release:', c.result && c.result.result && c.result.result.value);
  ws2.close(); process.exit(0);
}); }).on('error', e => { console.log('http error', e.message); process.exit(1); });
setTimeout(() => { console.log('timed out'); process.exit(1); }, 40000);
