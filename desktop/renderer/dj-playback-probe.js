/* Read-only local proof, evaluated inside the station playback page. */
function probeDjSpeech(target, options) {
  const w = target || (typeof window !== 'undefined' ? window : globalThis);
  const settings = options || {};
  const budget = Math.min(15000, Math.max(500, Number(settings.timeoutMs) || 12000));
  const interval = Math.min(1000, Math.max(100, Number(settings.intervalMs) || 250));
  const now = () => w.Date && typeof w.Date.now === 'function' ? w.Date.now() : Date.now();
  const began = now(), previous = new Map(), blocked = new Set();
  let samples = 0, candidates = 0, activeSeen = false, contextState = 'not created';
  return (async () => {
    if (!w.document || !w.document.querySelectorAll) return {verified: false, reason: 'unavailable', say: 'The station playback document is unavailable.'};
    for (let round = 0; round <= Math.ceil(budget / interval); round += 1) {
      samples += 1;
      const ctx = w.pineAudioCtx || w.__pineAudioCtx;
      contextState = ctx ? String(ctx.state) : 'not created';
      const ctxTime = Number(ctx && ctx.currentTime);
      let gateOpen = true;
      if (typeof w.pineLevelGateState === 'function') {
        try { gateOpen = w.pineLevelGateState().open !== false; } catch (_) { gateOpen = false; }
      }
      for (const player of Array.from(w.document.querySelectorAll('audio'))) {
        const data = player.dataset || {};
        const kind = String(data.pineLive || '').toLowerCase();
        // The rotating station players also carry SFX stingers. Video
        // warmers use the same live tag; neither proves DJ speech.
        if (!(kind === 'voice' || kind === 'reply' || (!kind && /^djVoiceAudio\d+$/.test(String(player.id || ''))))) continue;
        if (data.pineSting === '1' || data.pineWarm === '1' || data.pineDecor === '1' || player.isConnected === false) continue;
        candidates += 1;
        const source = String(player.currentSrc || player.src || '');
        const time = Number(player.currentTime), volume = Number(player.volume);
        const active = !player.paused && !player.ended && !player.error && Number(player.readyState) >= 2 && !!source;
        if (active) activeSeen = true;
        const gagged = data.pineGag === '1' || data.pineShellMuted === '1' || !!w.__pineGagged || w.__pineDesktopAudible === false;
        const audible = active && !player.muted && !gagged && volume > 0 && gateOpen;
        if (active && player.muted) blocked.add('The DJ player is muted.');
        if (active && gagged) blocked.add('Playback ownership or the desktop monitor is silencing the DJ player.');
        if (active && !(volume > 0)) blocked.add('The DJ player volume is zero.');
        if (active && !gateOpen) blocked.add('The audio output gain gate is closed.');
        if (active && contextState !== 'running') blocked.add('The DJ audio graph is ' + contextState + '.');
        const before = previous.get(player);
        if (audible && before && before.audible && before.source === source && before.ctx === ctx
            && contextState === 'running' && before.ctxState === 'running'
            && Number.isFinite(time) && Number.isFinite(ctxTime)
            && time - before.time >= .08 && ctxTime - before.ctxTime >= .08) {
          const advanced = Math.round((time - before.time) * 1000) / 1000;
          return {verified: true, reason: 'playing', samples, elapsedMs: Math.max(0, now() - began),
            proof: {id: String(player.id || ''), kind: kind || 'voice', advanced,
              graphAdvanced: Math.round((ctxTime - before.ctxTime) * 1000) / 1000,
              volume, muted: false, gagged: false, graph: contextState},
            say: 'A live DJ ' + (kind === 'reply' ? 'reply' : 'voice') + ' player advanced ' + advanced
              + 's with audible controls and the audio graph running in this app.'};
        }
        previous.set(player, {source, time, audible, ctx, ctxTime, ctxState: contextState});
      }
      const elapsed = Math.max(0, now() - began);
      if (elapsed >= budget || round === Math.ceil(budget / interval)) break;
      await new Promise(resolve => w.setTimeout(resolve, Math.min(interval, budget - elapsed)));
    }
    return {verified: false, reason: blocked.size ? 'blocked' : activeSeen ? 'stalled' : 'waiting', samples,
      elapsedMs: Math.max(0, now() - began), candidates, graph: contextState,
      say: blocked.size ? Array.from(blocked).join(' ') + ' DJ speech was not verified locally.'
        : activeSeen ? 'A live DJ player was active, but its playback and audio graph did not advance together. DJ speech was not verified locally.'
          : 'No live DJ speech advanced during this sample. Waiting for the next line; music playback does not verify DJ speech.'};
  })();
}

if (typeof module !== 'undefined' && module.exports) module.exports = {probeDjSpeech};
else if (typeof window !== 'undefined') window.PineDjPlaybackProbe = {probeDjSpeech};
