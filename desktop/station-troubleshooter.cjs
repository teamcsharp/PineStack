const { BrowserWindow, screen } = require('electron');
const path = require('node:path');
const { repair: repairMedia } = require(path.join(__dirname, 'renderer', 'playback-recovery.js'));
const { probeDjSpeech } = require(path.join(__dirname, 'renderer', 'dj-playback-probe.js'));

function install({isToolsSender,publishTools, ipcMain, getWindow, getToolsWindow, restoreDesktop, request, audioOutput, rendererDir = path.join(__dirname, 'renderer') }) {
  let window, busy = false;
  const state = { busy: false, title: 'Ready to check the station', entries: [] };
  function publish() { state.busy = busy; publishTools?.(state); if (window && !window.isDestroyed()) window.webContents.send('station-troubleshooter:state', state); }
  function note(label, status, detail) { state.entries.push({ label, status, detail: String(detail || '') }); publish(); }
  function open() {
    if (window && !window.isDestroyed()) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); return { ok: true }; }
    const area = screen.getDisplayMatching(getWindow()?.getBounds() || { x: 0, y: 0, width: 1, height: 1 }).workArea;
    window = new BrowserWindow({ title: 'Pine station troubleshooting', width: Math.min(720, area.width), height: Math.min(740, area.height),
      minWidth: Math.min(420, area.width), minHeight: Math.min(300, area.height), show: false, autoHideMenuBar: true, alwaysOnTop: true,
      backgroundColor: '#0b1511', webPreferences: { preload: path.join(__dirname, 'station-troubleshooter-preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false } });
    window.setAlwaysOnTop(true, 'floating');
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.once('ready-to-show', () => { if (window && !window.isDestroyed()) window.show(); });
    window.on('closed', () => { window = null; });
    window.loadFile(path.join(rendererDir, 'station-troubleshooter.html')).catch(error => note('Troubleshooting window', 'failed', error.message));
    return { ok: true };
  }
  async function desktopWindow() {
    let host = getWindow();
    if ((!host || host.isDestroyed()) && restoreDesktop) { await restoreDesktop(); host = getWindow(); }
    if (!host || host.isDestroyed()) throw new Error('The Pine desktop is closed. Reopen Pine and try again.');
    return host;
  }
  async function showDesktop() {
    if (restoreDesktop) await restoreDesktop();
    else { const host = await desktopWindow(); if (host.isMinimized?.()) host.restore(); host.show?.(); host.focus?.(); }
    note('Pine window', 'changed', 'Restored the Pine app window.');
    window?.minimize?.();
  }
  async function inDesktop(code, timeout = 15000) {
    const host = await desktopWindow();
    let timer;
    try { return await Promise.race([host.webContents.executeJavaScript(code, true), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('The app display did not respond. Use Reload app display below, then retry.')), timeout); })]); }
    finally { clearTimeout(timer); }
  }
  function describe(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  async function check() {
    const checks = [
      ['Broadcast', '/api/broadcast/health', value => value.say || (value.stuck ? 'Broadcast delivery is stuck' : 'Broadcast health received')],
      ['Broadcast delivery', '/api/broadcast/console', value => value.say || value.triage?.why || 'Delivery diagnostics received'],
      ['Pine Cam', '/api/pinelink/ladder', value => value.verdict || value.say || 'Camera diagnostics received'],
      ['Pine Tab', '/api/tablet/look', value => value.verdict || 'Tablet diagnostics received'],
      ['Live broadcast', '/api/pinelive/state', value => value.say || value.state || 'Live broadcast diagnostics received']
    ];
    const results = await Promise.allSettled(checks.map(async ([label, route, summary]) => {
      const value = await request(route);
      const bad = value.ok === false || value.stuck === true || value.live === false || (label === 'Pine Tab' && value.fetching === false);
      const rungs = value.rungs || [];
      note(label, bad || rungs.some(r => r.state === 'bad') ? 'attention' : 'checked', summary(value) + '\n' +
        (rungs.length ? rungs.map(r => r.label + ': ' + r.detail + ((r.help || []).length ? '\n' + r.help.join('\n') : '')).join('\n\n') : describe(value)));
    }));
    results.forEach((result, i) => { if (result.status === 'rejected') note(checks[i][0], 'failed', result.reason.message); });
    try {
      const audio = await inDesktop(`(async()=>{const frame=document.getElementById('controlFrame');return {appVolume:document.getElementById('appVolume')?.value,panel:frame?await frame.executeJavaScript('({graph:window.pineAudioCtx?.state||"not created",media:[...document.querySelectorAll("audio,video")].filter(el=>/voice|reply/.test(el.dataset.pineLive||el.id)).map(el=>({id:el.id,paused:el.paused,muted:el.muted,volume:el.volume,ready:el.readyState,gagged:el.dataset.pineGag==="1"}))})'):null}})()`);
      note('Audio in this app', 'checked', describe({ ...audio, appMuted: getWindow().webContents.isAudioMuted() }));
    } catch (error) { note('Audio in this app', 'failed', error.message); }
  }
  async function audioRepair(broadcast = false) {
    const host = await desktopWindow();
    if (host?.webContents.isAudioMuted()) { host.webContents.setAudioMuted(false); note('Application audio', 'changed', 'Removed application mute.'); }
    const local = await inDesktop(`(()=>{const did=[],slider=document.getElementById('appVolume');if(slider&&Number(slider.value)<=0){slider.value='35';slider.dispatchEvent(new Event('input',{bubbles:true}));did.push('Restored application volume to 35%.')}if(typeof streamVolumes!=='undefined'&&typeof setStreamVolume==='function'){for(const key of ['voice','reply'])if(streamVolumes[key]<=0){setStreamVolume(key,.6);did.push('Restored '+key+' stream volume to 60%.')}}const mixer=window.pineMixer,values=mixer?.get?.()||{},restore={};for(const key of ['voice','sfx','video'])if(Number(values[key])===0)restore[key]=1;if(Object.keys(restore).length){mixer.set(restore);mixer.apply?.();did.push('Restored muted DJ/SFX/video mixer channels.')}const frame=document.getElementById('controlFrame');if(frame?.isAudioMuted?.()){frame.setAudioMuted(false);did.push('Unmuted the station playback window.')}return did})()`);
    if (local?.length) note('Local audio controls', 'changed', local.join('\n'));
    if (audioOutput) {
      const output = await audioOutput(true);
      note('Windows audio output', output.ok ? (output.changed?.length ? 'changed' : 'checked') : 'attention', [output.say, ...(output.changed || [])].filter(Boolean).join('\n'));
    }
    try {
      const consoleState = await request('/api/broadcast/console');
      if (consoleState.triage?.cure === 'release') {
        await request('/api/radio/solo', { clear: true });
        note('Playback ownership', 'changed', 'Released the exclusive playback owner that was silencing a clip playback surface.');
      }
    } catch (error) { note('Station connection', 'attention', error.message + '. Continuing with app audio recovery.'); }
    note('App audio recovery', 'running', 'Checking playback, audio graph, output device and station delivery. Stops when output is measured.');
    const result = await inDesktop(`(async()=>{if(!window.PineRevive?.run)throw new Error('Audio recovery is unavailable in this desktop build.');const result=await PineRevive.run({${broadcast ? "only:['look','own','loud','release','unwedge','device','claim','panel','pages']," : ''}onProgress:value=>window.pineDesktop?.troubleshootProgress(value)});return {lines:result.lines,verdict:result.verdict,busy:result.busy}})()`, 180000);
    note('App audio result', result.verdict?.good ? 'verified' : 'attention', [result.verdict?.say, result.verdict?.because].filter(Boolean).join('\n'));
    if (result.lines) note('Audio recovery steps', 'checked', result.lines.map(line => line.label + ' [' + line.state + ']\n' + [...(line.found || []), ...(line.did || []), line.proof, line.cannot].filter(Boolean).join('\n')).join('\n\n'));
    if (audioOutput) {
      const output = await audioOutput(false);
      note('Audio leaving the app', output.peak > .0001 ? 'verified' : 'attention', output.peak > .0001 ? 'Windows measured audio from this Pine application.' : 'No app audio measured during this check. If the DJs are speaking, check the selected output device and run recovery again.');
    }
  }
  async function playbackRepair() {
    let stationJob;
    try {
      stationJob = await request('/api/station/troubleshoot', {fix:true,allow_restarts:true});
      if (!stationJob.id) throw Error('The station did not return a recovery job.');
      state.stationJob = stationJob;
      note('Station and orchestrator', 'running', 'Started recovery job ' + stationJob.id + '. Checking production, queues, services and sustained DJ delivery.');
    } catch (error) { note('Station and orchestrator', 'failed', error.message); }
    // Clean up the local decoders first. An unreachable station must not
    // leave a hidden H3 clip looping, or prevent another repair stage.
    note('Playback recovery', 'running', 'Stopping hidden H3 previews, reconnecting playback and restoring DJ delivery.');
    const mediaCode = `(${repairMedia.toString()})(window)`;
    const cleanupCode = `(async()=>{const rooms=[{name:'Pine',result:await ${mediaCode}}];await Promise.all([...document.querySelectorAll('webview')].filter(frame=>frame.src&&typeof frame.executeJavaScript==='function').map(async frame=>{let timer;try{const result=await Promise.race([frame.executeJavaScript(${JSON.stringify(mediaCode)},true),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Playback page did not respond.')),8000);})]);rooms.push({name:frame.id||'Playback page',result});}catch(error){rooms.push({name:frame.id||'Playback page',result:{ok:false,errors:[{error:error.message}]}});}finally{clearTimeout(timer);}}));return rooms;})()`;
    try {
      const rooms = await inDesktop(cleanupCode, 15000);
      for (const room of rooms || []) {
        const r = room.result || {};
        note(room.name + ' video playback', r.ok === false ? 'attention' : 'changed',
          `Stopped ${r.stoppedPreviews || 0} H3 previews; reset ${r.walls || 0} video walls and ${r.sfx || 0} SFX players; resumed ${r.restartedVideos || 0} videos.` +
          ((r.errors || []).length ? '\n' + r.errors.map(e => e.error).join('\n') : ''));
      }
    } catch (error) { note('Video playback', 'failed', error.message); }
    const tools = getToolsWindow?.();
    if (tools && !tools.isDestroyed()) {
      let timer;
      try {
        const r = await Promise.race([tools.webContents.executeJavaScript(cleanupCode, true), new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Pine tools did not respond.')), 15000); })]);
        note('Pine tools playback', r.some(room => room.result?.ok === false) ? 'attention' : 'changed', describe(r));
      } catch (error) { note('Pine tools playback', 'failed', error.message); }
      finally { clearTimeout(timer); }
    }
    async function wakePlayers() {
      const notes = await inDesktop(`(async()=>{window.pineReconnectStationFrames?.();const frame=document.getElementById('controlFrame');if(!frame)throw Error('The station playback page is unavailable.');return await frame.executeJavaScript('(async()=>{if(typeof window.pineRecoverPlayback!=="function")throw Error("The station playback page needs a reload.");return await window.pineRecoverPlayback();})()',true);})()`, 12000);
      note('DJ players', 'changed', describe(notes));
    }
    try { await wakePlayers(); }
    catch (error) {
      note('Station playback page', 'attention', error.message + ' Reloading this playback page once.');
      try {
        await inDesktop(`(async()=>{const frame=document.getElementById('controlFrame');if(!frame)throw Error('The station playback page is unavailable.');await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{frame.removeEventListener('dom-ready',ready);reject(Error('The station did not reconnect.'));},20000);function ready(){clearTimeout(timer);frame.removeEventListener('dom-ready',ready);resolve();}frame.addEventListener('dom-ready',ready);frame.reload();});return true;})()`, 22000);
        await wakePlayers();
      } catch (reloadError) { note('Station connection', 'failed', reloadError.message); }
    }
    // Music output is not evidence that the DJs are delivering speech.
    // Always run the station's diagnosis even if the local audio ladder
    // stops early because it measures the music player.
    // Production recovery belongs to the durable station job started above;
    // local decoder/audio repair proceeds independently while it runs.
    try { await audioRepair(); } catch (error) { note('DJ audio controls', 'failed', error.message); }
    try {
      const health = await request('/api/broadcast/health');
      const quiet = health.dialogue_quiet;
      const heard = quiet !== null && quiet !== undefined && Number.isFinite(Number(quiet)) && Number(quiet) >= 0 && Number(quiet) < 30;
      note('DJ delivery verification', heard && !health.stuck ? 'checked' : 'attention',
        heard && !health.stuck ? 'The station received a recent DJ speech playback acknowledgement.\n' + health.say :
          (health.say || 'DJ speech has not yet been verified. The orchestrator continues recovery.') + '\n' + describe(health.bank || {}));
    } catch (error) { note('DJ delivery verification', 'failed', error.message); }
    // A station acknowledgement can belong to another listening device,
    // and the audio ladder can prove music alone. Sample this app's actual
    // live speech players independently, including a legitimate line gap.
    try {
      note('DJ speech in this app', 'running', 'Waiting up to 12 seconds for a live DJ voice or reply player to advance.');
      const speechCode = `(${probeDjSpeech.toString()})(window)`;
      const local = await inDesktop(`(async()=>{const frame=document.getElementById('controlFrame');if(!frame||typeof frame.executeJavaScript!=='function')throw Error('The station playback page is unavailable.');const speech=await frame.executeJavaScript(${JSON.stringify(speechCode)},true);return {panelMuted:!!frame.isAudioMuted?.(),speech};})()`, 15000);
      const muted = getWindow()?.webContents.isAudioMuted() || local.panelMuted;
      const speech = local.speech || {};
      note('DJ speech in this app', speech.verified === true && !muted ? 'verified' : 'attention',
        (muted ? 'The application or station playback window is muted. ' : '') + (speech.say || 'DJ speech has not yet been verified in this app.')
        + (speech.proof ? '\n' + describe(speech.proof) : ''));
    } catch (error) { note('DJ speech in this app', 'attention', error.message + ' Waiting for the next live line to verify speech in this app.'); }
    if (stationJob?.id) {
      try {
        for (let poll=0;poll<30;poll++) {
          const job = await request('/api/station/troubleshoot/' + encodeURIComponent(stationJob.id));
          state.stationJob = job; publish();
          if (!job.running) {
            note('Station flow verification', job.verified === true ? 'verified' : 'attention', job.report || 'Review the station recovery report.');
            return;
          }
          if (poll<29) await new Promise(resolve=>setTimeout(resolve,2000));
        }
        note('Station flow verification', 'attention', 'Recovery continues in the saved station job ' + stationJob.id + '. Sustained speech is not verified yet.');
      } catch (error) { note('Station flow verification', 'attention', 'Recovery job ' + stationJob.id + ' remains saved. ' + error.message); }
    }
  }
  async function cameraRepair() {
    const selected = await inDesktop(`window.PinePip?.state()?.cameraSource || 'pine'`);
    const isTablet = selected === 'tab-front' || selected === 'tab-rear';
    if (isTablet) {
      note('PineTab camera', 'running', 'Reconnecting the selected tablet camera and desktop stream.');
      await inDesktop(`(async()=>{await window.PineTabletDoctor?.heal?.();return true})()`, 90000);
    } else {
    const doctor = await request('/api/pinelink/doctor');
    note('Camera diagnosis', 'checked', [doctor.verdict, ...(doctor.steps || [])].filter(Boolean).join('\n'));
    let reading = await request('/api/pinelink/state');
    if (!(reading.state === 'live' && reading.fresh)) {
      const route = doctor.cure === 'reset' ? '/api/pinelink/reset-radio' : doctor.camera ? '/api/pinelink/connect' : '';
      if (!route) { note('Pine Cam', 'attention', 'The camera is not available on the network. Turn it on and enable its Wi-Fi, then retry.'); return; }
      const repaired = await request(route, {});
      note('Camera connection', repaired.ok === false ? 'attention' : 'changed', repaired.say || describe(repaired));
      for (let i = 0; i < 8; i++) {
        await new Promise(resolve => setTimeout(resolve, 3000)); reading = await request('/api/pinelink/state');
        if (reading.state === 'live' && reading.fresh) break;
        note('Waiting for Pine Cam', 'running', 'Checking the camera connection (' + (i + 1) + '/8).');
      }
    }
    if (!(reading.state === 'live' && reading.fresh)) { note('Pine Cam', 'attention', 'Camera is still offline. Check its power and Wi-Fi; the station has not received a fresh live signal.'); return; }
    }
    const display = await inDesktop(`(async()=>{if(!window.PinePip?.repairCamera)throw new Error('Pine Cam PiP is unavailable in this desktop build.');return await PinePip.repairCamera()})()`);
    note(isTablet ? 'PineTab camera PiP' : 'Pine Cam PiP', display.ok ? 'changed' : 'attention', display.say);
    let picture;
    for (let i = 0; i < 12; i++) {
      await new Promise(resolve => setTimeout(resolve, 500));
      picture = await inDesktop(`(()=>{const box=document.querySelector('.pip-camera'),img=box?.querySelector('img');return {visible:!!box&&!box.hidden,image:!!img&&!img.hidden&&img.naturalWidth>0,status:box?.querySelector('[role="status"]')?.textContent}})()`);
      if (picture.visible && picture.image) break;
    }
    note('Camera picture', picture?.image ? 'verified' : 'attention', picture?.image ? 'A live ' + (isTablet ? 'PineTab camera' : 'Pine Cam') + ' picture is displayed in PiP.' : picture?.status || 'Camera connected, but its picture has not arrived.');
  }
  async function tabletRepair() {
    note('Pine Tab recovery', 'running', 'Locating the tablet, checking Wi-Fi and reconnecting the desktop bridge.');
    const result = await inDesktop(`(async()=>{if(!window.PineTabletDoctor?.heal)throw new Error('Tablet recovery is unavailable in this desktop build.');await PineTabletDoctor.heal();return {transcript:document.getElementById('tabletDoc')?.textContent}})()`, 90000);
    const reading = await request('/api/tablet/look');
    note('Pine Tab result', reading.fetching && reading.adb_port_open ? 'verified' : 'attention', (reading.verdict || '') + '\n' + (result.transcript || ''));
    if (reading.fetching && reading.adb_port_open) {
      const display = await inDesktop(`window.pineDesktop.mirrorShow()`);
      note('Tablet display', display?.ok === false ? 'attention' : 'changed', display?.detail || 'Opened the tablet display.');
    }
  }
  async function reload() {
    const host = await desktopWindow();
    await new Promise((resolve, reject) => {
      const contents = host.webContents;
      const cleanup = () => { clearTimeout(timer); contents.removeListener('did-finish-load', loaded); contents.removeListener('did-fail-load', failed); };
      const loaded = () => { cleanup(); resolve(); };
      const failed = (_event, _code, description, _url, mainFrame) => { if (mainFrame) { cleanup(); reject(new Error(description)); } };
      const timer = setTimeout(() => { cleanup(); reject(new Error('The app display did not finish loading. Close and reopen Pine.')); }, 30000);
      contents.once('did-finish-load', loaded); contents.on('did-fail-load', failed); contents.reload();
    });
    note('App display', 'changed', 'Reloaded the app display. Run Check everything to verify connections and playback.');
  }
  const actions = { check, reload, show: showDesktop, playback: playbackRepair, audio: () => audioRepair(), broadcast: () => audioRepair(true), camera: cameraRepair, tablet: tabletRepair,
    all: async () => { await check(); for (const [label, action] of [['Playback and DJs', playbackRepair], ['Pine Cam', cameraRepair], ['Pine Tab', tabletRepair]]) { try { await action(); } catch (error) { note(label, 'failed', error.message); } } } };
  async function run(action) {
    if (!Object.hasOwn(actions, action)) throw new Error('Unknown troubleshooting action.');
    if (busy) return { ...state, busy: true };
    busy = true; state.entries = []; state.audioSteps = []; state.stationJob = null; state.title = action === 'check' ? 'Checking the station...' : 'Repair in progress...'; publish();
    try { await actions[action](); }
    catch (error) { note('Troubleshooting', 'failed', error.message); }
    finally { busy = false; state.title = 'Finished - review the results below'; publish(); }
    return state;
  }
  ipcMain.handle('station-troubleshooter:open', (event, action) => {
    if (event.sender !== getWindow()?.webContents) throw new Error('Open troubleshooting from the Pine desktop.');
    const opened = open();
    if (action === 'playback' || action === undefined) run('playback').catch(error => note('Playback recovery', 'failed', error.message));
    return opened;
  });
  ipcMain.handle('station-troubleshooter:state', event => { if (event.sender !== window?.webContents && !isToolsSender?.(event)) throw new Error('Not the troubleshooting window.'); return state; });
  ipcMain.handle('station-troubleshooter:run', (event, action) => { if (event.sender !== window?.webContents && !isToolsSender?.(event)) throw new Error('Not the troubleshooting window.'); return run(action); });
  ipcMain.on('station-troubleshooter:progress', (event, value) => {
    if (!busy || event.sender !== getWindow()?.webContents || !Array.isArray(value?.lines)) return;
    const lines = value.lines.slice(0, 12).map(line => ({ label: String(line.label || '').slice(0, 200), state: String(line.state || ''), detail: [...(line.found || []), ...(line.did || []), line.proof, line.cannot].filter(Boolean).map(text => String(text).slice(0, 3000)).join('\n') }));
    state.audioSteps = lines; publish();
  });
  return { open, run };
}
module.exports = { install };
