const http = require('node:http');

const port = Number(process.env.PINE_CDP_PORT || 9222);
const sampleMs = Math.max(1000, Number(process.argv[2] || 10000));
const styleMode = String(process.argv[3] || '');
const styles = {
  'no-past-filter': '.sp-el.sp-segment-past { filter: none !important; }',
  'no-marquee': '.sp-msg-marquee.is-moving .sp-msg-marquee-track, .sp-now-orch-track { animation: none !important; will-change: auto !important; }',
  'offscreen-lines': '#spScript > .sp-el { content-visibility: auto !important; contain-intrinsic-size: auto 64px !important; }'
};

function readJson(path) {
  return new Promise((resolve, reject) => {
    http.get({hostname: '127.0.0.1', port, path}, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const pages = await readJson('/json');
  const page = pages.find((item) => item.type === 'page' && item.webSocketDebuggerUrl);
  if (!page) throw new Error('No debuggable tablet WebView is available.');
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', reject, {once: true});
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const {resolve, reject} = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result || {});
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
  try {
    if (styleMode) {
      if (styleMode !== 'clear' && !styles[styleMode]) {
        throw new Error(`Unknown style mode: ${styleMode}`);
      }
      const css = styles[styleMode] || '';
      await send('Runtime.evaluate', {expression: `(() => {
        let node = document.getElementById('pine-profile-style');
        if (!node) { node = document.createElement('style'); node.id = 'pine-profile-style'; document.head.appendChild(node); }
        node.textContent = ${JSON.stringify(css)};
      })()`});
    }
    const counts = await send('Runtime.evaluate', {expression: `(() => {
      const decision = window.PineScriptPage?.marks?.decision?.() || {};
      const feed = window.PineStationFeed?.now?.() || {};
      const row = (window.PineStationFeed?.rows?.() || [])
        .find((item) => String(item.id || '') === String(decision.line_id || '')) || {};
      const rowMedia = String(row.media || row.clip_media || row.url || row.sfx || '');
      return JSON.stringify({
        scriptLines: document.querySelectorAll('.sp-el').length,
        pastLines: document.querySelectorAll('.sp-el.sp-segment-past').length,
        movingMarquees: document.querySelectorAll('.sp-msg-marquee.is-moving').length,
        highlightedLines: [...document.querySelectorAll('.sp-el.sp-now')]
          .map((line) => line.dataset.line || '').filter(Boolean),
        decisionLine: decision.mark === 'air' ? String(decision.line_id || '') : '',
        decisionRoad: String(decision.road || ''),
        decisionFile: String(decision.file || ''),
        decisionOffset: decision.t == null ? null : Number(decision.t),
        rowMedia: rowMedia.split('?')[0].split('/').pop(),
        feedLine: String(feed.id || '')
      });
    })()`, returnByValue: true});
    await send('Performance.enable');
    await send('Profiler.enable');
    await send('Profiler.setSamplingInterval', {interval: 100});
    const before = await send('Performance.getMetrics');
    await send('Profiler.start');
    await new Promise((resolve) => setTimeout(resolve, sampleMs));
    const {profile} = await send('Profiler.stop');
    const after = await send('Performance.getMetrics');
    const nodes = new Map((profile.nodes || []).map((node) => [node.id, node.callFrame]));
    const hot = new Map();
    (profile.samples || []).forEach((id, index) => {
      const frame = nodes.get(id) || {};
      const key = `${frame.functionName || '(anonymous)'} ${frame.url || ''}:${frame.lineNumber || 0}`;
      hot.set(key, (hot.get(key) || 0) + Number((profile.timeDeltas || [])[index] || 0));
    });
    const first = Object.fromEntries((before.metrics || []).map((item) => [item.name, item.value]));
    const last = Object.fromEntries((after.metrics || []).map((item) => [item.name, item.value]));
    const delta = {};
    for (const name of ['TaskDuration', 'ScriptDuration', 'LayoutDuration',
                        'RecalcStyleDuration', 'LayoutCount', 'RecalcStyleCount']) {
      delta[name] = Number(((last[name] || 0) - (first[name] || 0)).toFixed(3));
    }
    console.log(JSON.stringify({title: page.title, url: page.url, sampleMs,
      styleMode: styleMode || 'none', counts: JSON.parse(counts.result.value),
      sampledCpuMs: Math.round([...hot.values()].reduce((a, b) => a + b, 0) / 1000),
      delta, jsHeapMb: Number(((last.JSHeapUsedSize || 0) / 1048576).toFixed(1)),
      hot: [...hot].sort((a, b) => b[1] - a[1]).slice(0, 18)
        .map(([name, microseconds]) => ({name, ms: Math.round(microseconds / 1000)}))}, null, 2));
  } finally {
    socket.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
