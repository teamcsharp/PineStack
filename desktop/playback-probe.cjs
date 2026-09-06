// Explicit one-launch observation of the real app. No debug port, playback
// controls, station writes, clip text, or signed media query strings.
const fs = require('node:fs/promises');
const path = require('node:path');

const expression = `(() => {
  const finite = value => Number.isFinite(value) ? value : null;
  const queue = typeof djVoiceQueue !== 'undefined' ? djVoiceQueue
    : typeof voiceQueue !== 'undefined' ? voiceQueue : [];
  const audio = [...new Set([...document.querySelectorAll('audio'),
    ...(typeof djVoiceEls === 'undefined' ? [] : djVoiceEls)])];
  return {title: document.title, preset: document.getElementById('broadcastTarget')?.value,
    routeSummary: document.getElementById('routeSummary')?.textContent,
    retimingLoaded: typeof djVoiceRetime === 'function',
    voiceBusy: typeof djVoiceBusy === 'undefined' ? null : djVoiceBusy,
    voiceLive: typeof djVoiceLive === 'undefined' ? null : djVoiceLive,
    stationPaused: typeof pineAirPaused === 'undefined' ? null : pineAirPaused,
    gagged: !!window.__pineGagged, cacheHold: !!window.cacheHold,
    pending: queue.length, queue: queue.slice(0, 3).map(clip => ({
      delivery_id: clip.delivery_id, ts: clip.ts,
      dueInSeconds: finite((Number(clip.broadcastAt) - Date.now()) / 1000),
      seconds: Number(clip.stream?.length || clip.seconds || 0)})),
    audio: audio.filter(Boolean).map(a => ({id: a.id, paused: a.paused,
      ended: a.ended, loop: a.loop, currentTime: finite(a.currentTime),
      duration: finite(a.duration), volume: a.volume, muted: a.muted,
      readyState: a.readyState, networkState: a.networkState, error: a.error?.code || null,
      delivery_id: a.pineDeliveryClip?.delivery_id,
      source: a.currentSrc ? new URL(a.currentSrc, location.href).pathname : ''}))};
})()`;

async function inspect(contents) {
  let timer;
  try {
    return await Promise.race([contents.executeJavaScript(expression),
      new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('Observation timed out')), 2500);})]);
  } catch (error) { return {id: contents.id, error: error.message}; }
  finally { clearTimeout(timer); }
}

async function capture({lcdState, lcdFrame, durationMs = 180000} = {}) {
  const {app, webContents} = require('electron');
  const output = path.join(app.getPath('temp'), 'pine-desktop-playback-probe');
  const started = Date.now();
  // A caller cannot accidentally leave continuous diagnostics running.
  const duration = Math.max(5000, Math.min(180000, Number(durationMs) || 180000));
  const report = {started, finished: false, debugPort: false, samples: []};
  await fs.mkdir(output, {recursive: true});
  do {
    const pages = webContents.getAllWebContents().filter(c => !c.isDestroyed()
      && ['window', 'webview'].includes(c.getType()));
    const state = lcdState?.() || {};
    report.samples.push({at: Date.now(), pages: await Promise.all(pages.map(inspect)),
      lcd: {running: state.running, connected: state.connected, host: state.host,
        frames: state.frames, failed: state.failed, lastAck: state.lastAck, error: state.error,
        lastFrameBytes: state.lastFrameBytes, frameBudget: state.frameBudget,
        identity: state.device?.identity, mode: state.device?.displayMode}});
    report.finished = Date.now() - started >= duration;
    const drawn = lcdFrame?.();
    if (drawn) await fs.writeFile(path.join(output, 'lcd-last-acknowledged.jpg'), Buffer.from(drawn, 'base64'));
    await fs.writeFile(path.join(output, 'result.tmp'), JSON.stringify(report, null, 2));
    await fs.rename(path.join(output, 'result.tmp'), path.join(output, 'result.json'));
    if (!report.finished) await new Promise(resolve => setTimeout(resolve, 5000));
  } while (!report.finished);
  return output;
}

module.exports = {capture, expression};
