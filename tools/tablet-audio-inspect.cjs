'use strict';

const http = require('node:http');

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (part) => { body += part; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const port = Number(process.argv[2] || 9222);
  const guardZero = process.argv.includes('--guard-zero');
  const jack = process.argv.includes('--jack');
  const jackOn = process.argv.includes('--jack-on');
  const customAt = process.argv.indexOf('--eval');
  const encodedAt = process.argv.indexOf('--eval64');
  const customExpression = customAt >= 0 ? process.argv[customAt + 1]
    : encodedAt >= 0 ? Buffer.from(process.argv[encodedAt + 1], 'base64').toString('utf8') : '';
  const pages = await getJson(`http://127.0.0.1:${port}/json`);
  const page = pages.find((row) => row.type === 'page' &&
    /127\.0\.0\.1:8096|10\.89\.1\.246/.test(row.url)) || pages[0];
  if (!page) throw new Error('No tablet WebView page');
  let expression = (jack || jackOn) ? `(async () => {
    return window.pineDesktop && typeof window.pineDesktop.jack === 'function'
      ? await window.pineDesktop.jack(${jackOn ? '{on: true}' : ''})
      : {ok: false, why: 'jack bridge unavailable'};
  })()` : guardZero ? `(() => {
    if (typeof window.djLevels !== 'function' || !window.pineLevels) {
      return {guarded: false, why: 'audio controls unavailable'};
    }
    if (!window.djLevels.__pineCanonicalMusic) {
      const original = window.djLevels;
      const guarded = function () {
        const levels = original.apply(this, arguments);
        const shared = Number((window.pineLevels.get() || {}).music);
        if (Number.isFinite(shared)) levels.music = Math.max(0, shared);
        return levels;
      };
      guarded.__pineCanonicalMusic = true;
      window.djLevels = guarded;
    }
    window.pineLevels.refresh('music');
    const record = document.getElementById('musicPlayer');
    if (record && !record.__pineZeroPauseGuard) {
      record.__pineZeroPauseGuard = true;
      record.addEventListener('play', () => {
        if (Number((window.pineLevels.get() || {}).music) === 0) record.pause();
      });
    }
    if (record && Number((window.pineLevels.get() || {}).music) === 0) record.pause();
    return {guarded: true, listener: window.pineLevels.get(),
      slider: document.getElementById('djGainMusic')?.value,
      recordPaused: record?.paused};
  })()` : `(() => {
    const player = document.getElementById('musicPlayer');
    const slider = document.getElementById('djGainMusic');
    const levels = window.pineLevels;
    const gain = typeof gains !== 'undefined' && gains.music && gains.music.node;
    return {
      href: location.href,
      view: localStorage.getItem('pineLastView'),
      slider: slider && slider.value,
      listener: levels && levels.get(),
      stored: localStorage.getItem('pineListenerLevels'),
      mixer: localStorage.getItem('pineMixer'),
      player: player && {volume: player.volume, muted: player.muted,
        paused: player.paused, currentTime: player.currentTime,
        source: !!player.currentSrc},
      media: Array.from(document.querySelectorAll('audio, video')).map((node) => ({
        id: node.id, tag: node.tagName, volume: node.volume,
        muted: node.muted, paused: node.paused,
        source: node.currentSrc && new URL(node.currentSrc).pathname,
        time: Math.round(node.currentTime || 0)
      })).filter((node) => !!node.source && !node.paused),
      gain: gain && gain.gain.value,
      duck: window.PineAir && window.PineAir.duckState(),
      temporaryGuard: !!(window.djLevels && window.djLevels.__pineCanonicalMusic),
      route: typeof lastDjState !== 'undefined' && lastDjState && {
        music_to: lastDjState.music_to, voice_to: lastDjState.voice_to,
        voice_device: lastDjState.voice_device
      }
    };
  })()`;
  if (customExpression) expression = customExpression;
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const timer = setTimeout(() => { ws.close(); process.exitCode = 1; }, 8000);
  ws.onopen = () => ws.send(JSON.stringify({id: 1, method: 'Runtime.evaluate',
    params: {expression, returnByValue: true, awaitPromise: true}}));
  ws.onmessage = (event) => {
    clearTimeout(timer);
    const message = JSON.parse(event.data);
    console.log(JSON.stringify(message.result?.result?.value ||
      message.result?.exceptionDetails || message, null, 2));
    ws.close();
  };
  ws.onerror = (event) => {
    clearTimeout(timer);
    console.error(event.message || 'WebSocket error');
    process.exitCode = 1;
  };
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
