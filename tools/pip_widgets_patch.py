#!/usr/bin/env python3
"""[pip-panel-ready] [pip-art] [pip-free] [pip-playbar] [pip-export-bar] [pip-favorites-az] [cam-words]
Pine PiP on the desk, second wave. 2026-10-05.

[pip-panel-ready] "when i go into pine pip mode, the window looks like this. I have to press F5
                  to get it to show right" / "thats not showing the logo and particle bg either".
                  The station page opens iframes after it loads (the Gazette press, a book, a
                  manual, an embedded video). Each one fires the webview's did-start-loading,
                  which unreadied the panel; no dom-ready follows for an iframe, so the page was
                  never told to switch until a reload. Only a main-frame navigation unreadies it
                  now, every load end re-syncs, and entry confirms the switch.
[pip-art]         "The album already showing up broken." The art route is 404 for a record
                  without artwork; the image now falls back to the placeholder.
                  "If I double click the album art of the music widget, then I want to reduce the
                  music widget to just be the album art image" - musicArtOnly, a preference.
[pip-favorites-az] "List favorites alphabetically."
[cam-words]       "The camera is currently online despite just being unable to connect to it."
                  The popup said the camera was off; what the station knows is that its own
                  Wi-Fi adapter cannot see the camera's network. It says that, with the count of
                  networks it does see, and the title no longer sits on the text.
[pip-free]        "Allow for every widget able to be added in pine pit mode to be able to be
                  freely dragged, repositioned, scaled, trimmed, and adjusted."
                  Every widget has a layout entry {x,y,w,h,s,t,o}: drag its handle anywhere
                  (drop at the top or bottom edge to dock again), edge grips resize, Shift+grip
                  trims a side, Ctrl+wheel scales, right-click the handle for the adjust popover
                  (scale, opacity, trims, dock, reset, hide). Shared with the station like every
                  other PiP preference.
[pip-playbar]     "when a video is playing, show a loading bar going across the bottom
                  representing playback and how much is left. Make the bar 3px and have it go
                  from green to blue to white as it goes across the pip display."
[pip-export-bar]  "When exporting a video, show the loading bar at the bottom with text overlaid
                  showing the progress of the export of the pine app, pine pip." ffmpeg reports
                  its clock (-progress pipe:1); the cut turns it into a share; the window that
                  asked hears every step and draws the same bar with the words over it.

main.js, preload.js, pip-window.cjs, clip-mux.cjs and screen-ring.cjs are the running process:
they take effect at the app's next launch (the menu's "Update and rebuild Pine" does that).
The renderer files wait for a reload. Both copies of pine-pip.js / pine-pip.css are patched.

Usage:  pip_widgets_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        pip_widgets_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- pip-window.cjs
WIN_PREF_OLD = r'''    musicExpanded: value.musicExpanded === true,
    theme: Object.hasOwn(THEMES, value.theme) ? value.theme : 'pine',
'''
WIN_PREF_NEW = r'''    musicExpanded: value.musicExpanded === true,
    musicArtOnly: value.musicArtOnly === true,   /* [pip-art] the player reduced to its artwork */
    /* [pip-free] one layout entry per widget: place (x,y) and size (w,h) as shares of the window,
       scale s, trims t (four sides, % of the widget) and opacity o. Absent = the widget's own default. */
    layout: Object.fromEntries(LAYOUT_NAMES.map(name => [name, layoutEntry(value.layout?.[name])]).filter(([, entry]) => entry)),
    theme: Object.hasOwn(THEMES, value.theme) ? value.theme : 'pine',
'''

WIN_ENTRY_OLD = r'''function preferences(value = {}) {
  value = value || {};
'''
WIN_ENTRY_NEW = r'''/* [pip-free] every widget, and the camera, can carry a layout entry */
const LAYOUT_NAMES = [...Object.keys(WIDGETS), 'camera'];
function layoutEntry(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const out = {};
  for (const [key, low, high] of [['x', 0, 1], ['y', 0, 1], ['w', 0, 1], ['h', 0, 1], ['s', .4, 3], ['o', .1, 1]]) {
    if (Number.isFinite(raw[key])) out[key] = Math.round(Math.max(low, Math.min(high, raw[key])) * 10000) / 10000;
  }
  if (Array.isArray(raw.t) && raw.t.length === 4 && raw.t.every(Number.isFinite) && raw.t.some(v => v > 0)) {
    out.t = raw.t.map(v => Math.round(Math.max(0, Math.min(45, v)) * 10) / 10);
  }
  return Object.keys(out).length ? out : null;
}
function mergeLayout(old, next) {
  const out = { ...(old || {}) };
  for (const [name, entry] of Object.entries(next || {})) {
    if (entry === null) delete out[name];
    else if (entry && typeof entry === 'object') out[name] = { ...(out[name] || {}), ...entry };
  }
  return out;
}
function preferences(value = {}) {
  value = value || {};
'''

WIN_MERGE_OLD = r'''      musicPosition: { ...old.musicPosition, ...next?.musicPosition },
      messageBounds: { ...old.messageBounds, ...next?.messageBounds },
'''
WIN_MERGE_NEW = r'''      musicPosition: { ...old.musicPosition, ...next?.musicPosition },
      layout: next?.layout === null ? {} : mergeLayout(old.layout, next?.layout),   /* [pip-free] null = every widget back to its default */
      messageBounds: { ...old.messageBounds, ...next?.messageBounds },
'''

WIN_FAV_OLD = r'''      click:()=>openTools?openTools({id}):getWindow()?.webContents.send('pip:action',{type:'favorite',id})}));
'''
WIN_FAV_NEW = r'''      click:()=>openTools?openTools({id}):getWindow()?.webContents.send('pip:action',{type:'favorite',id})}))
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base', numeric: true }));   /* [pip-favorites-az] "List favorites alphabetically." */
'''

WIN_RESET_OLD = r'''      { type: 'separator' }, { label: 'Drag widget handles to the top or bottom', enabled: false },
      { label: 'Reset widget layout', click: () => update({ docks: preferences().docks, order: preferences().order, messageBounds: preferences().messageBounds }) }'''
WIN_RESET_NEW = r'''      { type: 'separator' }, { label: 'Drag a widget handle anywhere; drop it at the top or bottom edge to dock it', enabled: false },
      { label: 'Edge grips resize, Shift+grip trims, Ctrl+wheel scales, right-click a handle to adjust', enabled: false },
      /* [pip-free] a reset puts every widget back where it was before any of this */
      { label: 'Reset widget layout', click: () => update({ docks: preferences().docks, order: preferences().order, messageBounds: preferences().messageBounds, layout: null,
        musicPosition: preferences().musicPosition, roulettePosition: preferences().roulettePosition, cameraBounds: preferences().cameraBounds, musicArtOnly: false }) }'''

WIN_MENU_OLD = r"""      ...Object.keys(WIDGETS).filter(name => name !== 'roulette').map(name => ({ label: labels[name], type: 'checkbox', checked: s.widgets[name],
        click: () => update({ widgets: { [name]: !s.widgets[name] } }) })),
"""
WIN_MENU_NEW = r"""      ...Object.keys(WIDGETS).filter(name => name !== 'roulette').map(name => ({ label: labels[name], type: 'checkbox', checked: s.widgets[name],
        click: () => update({ widgets: { [name]: !s.widgets[name] } }) })),
      /* [pip-free] every shown widget's layout options, for a widget whose handle is trimmed away or hard to find */
      { label: 'Widget layout (scale, trim, opacity)...', submenu: Object.keys(WIDGETS).filter(name => name !== 'roulette' && s.widgets[name])
        .map(name => ({ label: labels[name], click: () => getWindow()?.webContents.send('pip:action', { type: 'adjust', name }) }))
        .concat([{ label: 'Pine Cam', click: () => getWindow()?.webContents.send('pip:action', { type: 'adjust', name: 'camera' }) }]) },
"""

WINDOW = [
    ("layout entries and their merge", WIN_ENTRY_OLD, WIN_ENTRY_NEW, "const LAYOUT_NAMES = [...Object.keys(WIDGETS), 'camera'];", 1),
    ("a Widget layout submenu", WIN_MENU_OLD, WIN_MENU_NEW, "label: 'Widget layout (scale, trim, opacity)...'", 1),
    ("musicArtOnly + layout preferences", WIN_PREF_OLD, WIN_PREF_NEW, "musicArtOnly: value.musicArtOnly === true,", 1),
    ("update() merges layout entries", WIN_MERGE_OLD, WIN_MERGE_NEW, "layout: next?.layout === null ? {} : mergeLayout(old.layout, next?.layout),", 1),
    ("favorites sorted by name", WIN_FAV_OLD, WIN_FAV_NEW, "[pip-favorites-az]", 1),
    ("reset covers the free layout", WIN_RESET_OLD, WIN_RESET_NEW, "layout: null,", 1),
]

# --------------------------------------------------------------------------- preload.js
PRELOAD_OLD = r'''  replayExport: (want) => ipcRenderer.invoke("replay:export", want),
'''
PRELOAD_NEW = r'''  replayExport: (want) => ipcRenderer.invoke("replay:export", want),
  /* [pip-export-bar] every step of an export this window asked for: {view, stage, ratio|null, at, ...} */
  onReplayProgress: (callback) => ipcRenderer.on("replay:progress", (_event, note) => callback(note)),
'''
PRELOAD = [("export progress reaches the page", PRELOAD_OLD, PRELOAD_NEW, "onReplayProgress:", 1)]

# --------------------------------------------------------------------------- main.js
MAIN_TELLER_OLD = r'''ipcMain.handle("replay:export", async (_event, want) => {
  const endAt = Date.now();
  const asked = Math.max(1, Number((want || {}).seconds) || 30);
  try {
    await replayFlush(900);
'''
MAIN_TELLER_NEW = r'''/* [pip-export-bar] An export tells the window that asked how far it is; the bar at the
 * foot of Pine (pine-pip.js) draws it with the words over it. ratio null = unknown. */
function replayProgressTeller(sender, want, view) {
  let last = -1, lastAt = 0;
  const tell = (stage, ratio, extra) => {
    try {
      if (!sender || sender.isDestroyed()) return;
      const now = Date.now(), share = Number.isFinite(ratio) ? Math.max(0, Math.min(1, ratio)) : null;
      if (stage === 'encode' && share !== null && share - last < .01 && now - lastAt < 400) return;
      if (share !== null) last = share;
      lastAt = now;
      sender.send("replay:progress", { view: view || (want?.view === 'pip' ? 'pip' : 'app'), audio: want?.audio_only === true,
        stage, ratio: share, at: now, ...(extra || {}) });
    } catch (_) { /* a window that has gone */ }
  };
  return { tell };
}

ipcMain.handle("replay:export", async (_event, want) => {
  const endAt = Date.now();
  const asked = Math.max(1, Number((want || {}).seconds) || 30);
  const teller = replayProgressTeller(_event.sender, want);   /* [pip-export-bar] */
  try {
    teller.tell('flush', .02);
    await replayFlush(900);
'''

MAIN_CUT_OLD = r'''      video_only: !!((want || {}).video_only), view: want?.view === 'pip' ? 'pip' : undefined, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
'''
MAIN_CUT_NEW = r'''      video_only: !!((want || {}).video_only), view: want?.view === 'pip' ? 'pip' : undefined, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg, onProgress: share => teller.tell('encode', .05 + share * .85) });
    if (!made.ok) { teller.tell('failed', null, { detail: made.detail }); return { ok: false, detail: made.detail, held: made.held }; }
'''

MAIN_AUDIO_OLD = r'''      clipMux.forget(made.dir);
      return { ok: false, detail: 'The saved buffer does not contain the complete audio mix heard during this video. Let the audio buffer fill and try again, or choose picture only.', audio: dressed.audio };
'''
MAIN_AUDIO_NEW = r'''      clipMux.forget(made.dir);
      teller.tell('failed', null, { detail: 'the complete audio mix is not in the buffer yet' });
      return { ok: false, detail: 'The saved buffer does not contain the complete audio mix heard during this video. Let the audio buffer fill and try again, or choose picture only.', audio: dressed.audio };
'''

MAIN_SAVE_OLD = r'''    const where = path.join(folder, name.replace(/[^\w.-]+/g, "-"));
    try {
      await fs.promises.copyFile(made.out, where);
'''
MAIN_SAVE_NEW = r'''    const where = path.join(folder, name.replace(/[^\w.-]+/g, "-"));
    teller.tell('save', .93);
    try {
      await fs.promises.copyFile(made.out, where);
'''

MAIN_UPLOAD_OLD = r'''    if (want && want.upload) {
      uploaded = { ok: false, detail: "not attempted" };
'''
MAIN_UPLOAD_NEW = r'''    if (want && want.upload) {
      teller.tell('upload', .96);
      uploaded = { ok: false, detail: "not attempted" };
'''

MAIN_DONE_OLD = r'''    clipMux.forget(made.dir);
    return { ok: true, where, bytes: made.bytes, asked,
      seconds: made.seconds, held: made.held, clamped: !!made.clamped,
      uploaded, audio: dressed.audio, video: made.video || null, detail: "" };
  } catch (error) {
    return { ok: false, detail: error.message };
  }
});
'''
MAIN_DONE_NEW = r'''    clipMux.forget(made.dir);
    teller.tell('done', 1, { seconds: made.seconds, where });
    return { ok: true, where, bytes: made.bytes, asked,
      seconds: made.seconds, held: made.held, clamped: !!made.clamped,
      uploaded, audio: dressed.audio, video: made.video || null, detail: "" };
  } catch (error) {
    teller.tell('failed', null, { detail: error.message });
    return { ok: false, detail: error.message };
  }
});
'''

MAIN_TABLET_OLD = r'''ipcMain.handle('tablet:replay-export', (event, want) => {
  if(event.sender!==win?.webContents)throw Error('Tablet exports belong to the Pine desktop.');
  return tabletReplayExport(want);
});
'''
MAIN_TABLET_NEW = r'''ipcMain.handle('tablet:replay-export', async (event, want) => {
  if(event.sender!==win?.webContents)throw Error('Tablet exports belong to the Pine desktop.');
  /* [pip-export-bar] the tablet's cut has no clock to read: the bar sweeps until it is saved */
  const teller = replayProgressTeller(event.sender, want, 'tablet');
  teller.tell('encode', null);
  try {
    const made = await tabletReplayExport(want);
    if (made?.ok) teller.tell('done', 1, { seconds: made.seconds, where: made.where });
    else teller.tell('failed', null, { detail: made?.detail || made?.why || 'PineTab recording unavailable' });
    return made;
  } catch (error) { teller.tell('failed', null, { detail: error.message }); throw error; }
});
'''

MAIN = [
    ("the export tells its window", MAIN_TELLER_OLD, MAIN_TELLER_NEW, "function replayProgressTeller(sender, want, view) {", 1),
    ("the cut reports its clock", MAIN_CUT_OLD, MAIN_CUT_NEW, "onProgress: share => teller.tell('encode', .05 + share * .85)", 1),
    ("a missing mix is told", MAIN_AUDIO_OLD, MAIN_AUDIO_NEW, "teller.tell('failed', null, { detail: 'the complete audio mix is not in the buffer yet' });", 1),
    ("saving is told", MAIN_SAVE_OLD, MAIN_SAVE_NEW, "teller.tell('save', .93);", 1),
    ("uploading is told", MAIN_UPLOAD_OLD, MAIN_UPLOAD_NEW, "teller.tell('upload', .96);", 1),
    ("done and failed are told", MAIN_DONE_OLD, MAIN_DONE_NEW, "teller.tell('done', 1, { seconds: made.seconds, where });", 1),
    ("the tablet export sweeps", MAIN_TABLET_OLD, MAIN_TABLET_NEW, "const teller = replayProgressTeller(event.sender, want, 'tablet');", 1),
]

# --------------------------------------------------------------------------- clip-mux.cjs
MUX_RUN_OLD = r'''function run(exe, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const worker = execFile(exe, args, { windowsHide: true, maxBuffer: 32 * 1024 * 1024, timeout: timeoutMs || 300000 },
'''
MUX_RUN_NEW = r'''/* [pip-export-bar] ffmpeg's -progress report, line by line, as seconds written so far.
 * out_time_us and out_time_ms are both microseconds (ffmpeg's own quirk); out_time is a clock. */
function progressFeed(onProgress) {
  let rest = '';
  return chunk => {
    rest += String(chunk);
    const lines = rest.split(/\r?\n/); rest = lines.pop();
    for (const line of lines) {
      const micro = /^out_time_(?:us|ms)=(\d+)\s*$/.exec(line);
      const clock = micro ? null : /^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)\s*$/.exec(line);
      const seconds = micro ? Number(micro[1]) / 1e6 : clock ? Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3]) : null;
      if (seconds !== null && Number.isFinite(seconds)) { try { onProgress(seconds); } catch (_) { /* a listener's slip never stops the encode */ } }
    }
  };
}

function run(exe, args, timeoutMs, onProgress) {
  const told = typeof onProgress === 'function' ? onProgress : null;
  /* [pip-export-bar] with a listener, ffmpeg writes its clock to stdout and nothing else goes there */
  const spawnArgs = told ? ['-progress', 'pipe:1', '-nostats', ...args] : args;
  return new Promise((resolve, reject) => {
    const worker = execFile(exe, spawnArgs, { windowsHide: true, maxBuffer: 32 * 1024 * 1024, timeout: timeoutMs || 300000 },
'''

MUX_PRIO_OLD = r'''    // Exports yield CPU time to the live display/audio when the host is busy.
    // A driver/policy that refuses priority changes must not break an export.
    try {
      if (worker?.pid) os.setPriority(worker.pid, os.constants.priority.PRIORITY_BELOW_NORMAL);
'''
MUX_PRIO_NEW = r'''    if (told && worker?.stdout) worker.stdout.on('data', progressFeed(told));
    // Exports yield CPU time to the live display/audio when the host is busy.
    // A driver/policy that refuses priority changes must not break an export.
    try {
      if (worker?.pid) os.setPriority(worker.pid, os.constants.priority.PRIORITY_BELOW_NORMAL);
'''

MUX_ENCODE_OLD = r'''      await run(exe, build(encoder), (options || {}).timeoutMs || 600000);
'''
MUX_ENCODE_NEW = r'''      await run(exe, build(encoder), (options || {}).timeoutMs || 600000, (options || {}).onProgress);
'''

MUX_EXPORT_OLD = r'''module.exports = { planArgs, mux, findFfmpeg, dbToLinear, stash, forget, lastReal,
'''
MUX_EXPORT_NEW = r'''module.exports = { planArgs, mux, findFfmpeg, dbToLinear, stash, forget, lastReal, progressFeed,
'''

MUX = [
    ("ffmpeg's clock is read", MUX_RUN_OLD, MUX_RUN_NEW, "function progressFeed(onProgress) {", 1),
    ("the worker's stdout feeds it", MUX_PRIO_OLD, MUX_PRIO_NEW, "worker.stdout.on('data', progressFeed(told));", 1),
    ("encodeVideo passes the listener", MUX_ENCODE_OLD, MUX_ENCODE_NEW, "(options || {}).timeoutMs || 600000, (options || {}).onProgress);", 1),
    ("progressFeed is exported", MUX_EXPORT_OLD, MUX_EXPORT_NEW, "lastReal, progressFeed,", 1),
]

# --------------------------------------------------------------------------- screen-ring.cjs
RING_OLD = r'''      const encoding = await clipMux.encodeVideo(clipMux.findFfmpeg(opts.ffmpeg).path, build,
        { ...opts, timeoutMs: opts.timeoutMs || Math.max(600000, Math.ceil(got.seconds * 6000 + 120000)) });
'''
RING_NEW = r'''      const total = Math.max(.1, Number(got.seconds) || 0);   /* [pip-export-bar] seconds written so far, as a share of this cut */
      const encoding = await clipMux.encodeVideo(clipMux.findFfmpeg(opts.ffmpeg).path, build,
        { ...opts, onProgress: typeof opts.onProgress === 'function' ? seconds => opts.onProgress(Math.min(1, Math.max(0, seconds) / total)) : undefined,
          timeoutMs: opts.timeoutMs || Math.max(600000, Math.ceil(got.seconds * 6000 + 120000)) });
'''
RING = [("the cut turns the clock into a share", RING_OLD, RING_NEW, "[pip-export-bar] seconds written so far, as a share of this cut", 1)]

# --------------------------------------------------------------------------- webview-preload.js
RELAY_OLD = r'''  if (event.data.type === 'pine-pip-voices' && Array.isArray(event.data.readings)) {
'''
RELAY_NEW = r'''  if (event.data.type === 'pine-pip-time') {   /* [pip-playbar] the playing video's clock, or null when none plays */
    const t = event.data.time;
    ipcRenderer.sendToHost('pine-pip-time', t && typeof t === 'object' ? { at: Math.max(0, Number(t.at) || 0), dur: Math.max(0, Number(t.dur) || 0), playing: t.playing === true } : null); return;
  }
  if (event.data.type === 'pine-pip-voices' && Array.isArray(event.data.readings)) {
'''
RELAY = [("the video clock crosses the webview boundary", RELAY_OLD, RELAY_NEW, "[pip-playbar] the playing video's clock, or null when none plays", 1)]

# --------------------------------------------------------------------------- pine-pip-camera-recovery.js
CAM_OLD = r'''      if(doctor&&!doctor.stale&&doctor.camera===false){
        const name=got&&got.ssid?' ('+got.ssid+')':'';
        return 'The camera\'s Wi-Fi'+name+' is not on the air: the camera is asleep, switched off or out of range. Press its Wi-Fi button and wait for the solid green light.';
      }
'''
CAM_NEW = r'''      if(doctor&&!doctor.stale&&doctor.camera===false){
        /* [cam-words] what the station knows is that ITS adapter cannot see the camera's network; the
           camera may well be on. Say that, with the evidence, and what would put it back on the air. */
        const name=got&&got.ssid?' ('+got.ssid+')':'';
        const seen=Number.isFinite(Number(doctor.nearby))?Number(doctor.nearby):null;
        const evidence=seen===null?'':seen===0?' Its adapter sees no networks at all right now.':' Its adapter sees '+seen+' other network'+(seen===1?'':'s')+' but not the camera\'s.';
        return 'The camera\'s Wi-Fi'+name+' is not on the air for the Pine Box.'+evidence+' The camera may be on with its Wi-Fi asleep, a phone or the Viidure app may hold its only connection, or it may be more than about 10 m from the adapter. Press its Wi-Fi button and wait for the solid green light.';
      }
'''
CAMERA = [("the popup says what it knows", CAM_OLD, CAM_NEW, "[cam-words]", 1)]

# --------------------------------------------------------------------------- pine-pip.js (both copies)
PIP_READY_OLD = r'''    frame.addEventListener('did-start-loading', () => { panelReady = false; });
'''
PIP_READY_NEW = r'''    /* [pip-panel-ready] Only a new page in the main frame unreadies the panel. did-start-loading also
       fires for every iframe the station page opens later (the Gazette press, a book, a manual, an
       embedded video); with no dom-ready to follow, the flag stayed false and PiP showed the raw
       page until F5. A load that ends while PiP is on re-syncs the panel. */
    frame.addEventListener('did-start-navigation', e => { if (e.isMainFrame && !e.isInPlace) panelReady = false; });
    frame.addEventListener('did-stop-loading', () => { if (state?.active) syncPanel().catch(e => say(e.message)); });
'''

PIP_SYNC_OLD = r'''  async function syncPanel() {
    if (!panelReady) return;
'''
PIP_SYNC_NEW = r'''  async function syncPanel() {
    if (!panelReady) {   /* [pip-panel-ready] a page that answers is ready, whatever the flag last heard */
      try { await frame.executeJavaScript('document.readyState'); panelReady = true; } catch (_) { return; }
    }
'''

PIP_CONFIRM_OLD = r'''    const synced = syncPanel().catch(e => say('PiP video display: ' + e.message));
'''
PIP_CONFIRM_NEW = r'''    const synced = syncPanel().catch(e => say('PiP video display: ' + e.message));
    if (next.active && !was) confirmPanel();   /* [pip-panel-ready] and make sure the page really switched */
    layoutWidgets(); paintPlaybar();           /* [pip-free] [pip-playbar] */
'''

PIP_HELPERS_OLD = r'''  async function syncPanel() {
'''
PIP_HELPERS_NEW = r'''  /* [pip-panel-ready] After entering PiP, look at the page a few times: if it has not taken the
     pine-pip class the sync is repeated. A page that is still loading gets a longer look. */
  let confirmTimers = [];
  function confirmPanel() {
    confirmTimers.forEach(clearTimeout); confirmTimers = [];
    for (const wait of [350, 1200, 3000, 7000]) {
      confirmTimers.push(setTimeout(async () => {
        if (!state?.active || !frame) return;
        try {
          const on = await frame.executeJavaScript('document.documentElement.classList.contains("pine-pip")');
          if (on !== true) { panelReady = true; await syncPanel(); }
        } catch (_) { /* a page between loads: dom-ready will sync it */ }
      }, wait));
    }
  }
  async function syncPanel() {
'''

PIP_SHARED_OLD = r'''    for (const key of ['popupFavorites','ui','aspectMode','cameraOverlay','cameraOnly','cameraSource','cameraBounds','messageBounds','messageTile','roulettePosition','theme','transparency','widgets','docks','order','voiceStyles','musicPosition','musicExpanded']) out[key] = value[key];
'''
PIP_SHARED_NEW = r'''    for (const key of ['popupFavorites','ui','aspectMode','cameraOverlay','cameraOnly','cameraSource','cameraBounds','messageBounds','messageTile','roulettePosition','theme','transparency','widgets','docks','order','voiceStyles','musicPosition','musicExpanded','musicArtOnly','layout']) out[key] = value[key];
'''

PIP_ART_PAINT_OLD = r'''    const art = box.querySelector('.pip-music-art'), blank = box.querySelector('.pip-music-blank'), src = track?.art ? root.desktopMusicUrl(track.art) : '';
    art.hidden = !src; blank.hidden = !!src; if (src && art.getAttribute('src') !== src) art.src = src;
'''
PIP_ART_PAINT_NEW = r'''    const art = box.querySelector('.pip-music-art'), blank = box.querySelector('.pip-music-blank'), src = track?.art ? root.desktopMusicUrl(track.art) : '';
    /* [pip-art] a record without artwork is a 404 on the art route: the placeholder stands in, and the broken picture never shows */
    if (src && art.getAttribute('src') !== src) { art.dataset.failed = ''; art.src = src; }
    const shown = !!src && art.dataset.failed !== src;
    art.hidden = !shown; blank.hidden = shown;
    box.classList.toggle('art-only', !!state?.musicArtOnly);
'''

PIP_ART_BUILD_OLD = r'''    const art = node('img', 'pip-music-art'); art.alt = 'Album art'; art.hidden = true; art.draggable = false;
    const blank = node('div', 'pip-music-blank'); if (typeof root.pineIcon === 'function') blank.innerHTML = root.pineIcon('c:music');
'''
PIP_ART_BUILD_NEW = r'''    const art = node('img', 'pip-music-art'); art.alt = 'Album art'; art.hidden = true; art.draggable = false;
    const blank = node('div', 'pip-music-blank'); if (typeof root.pineIcon === 'function') blank.innerHTML = root.pineIcon('c:music');
    /* [pip-art] a picture that does not load gives way to the placeholder; a double-click on either
       reduces the player to the artwork alone, and a second one brings the player back */
    art.addEventListener('error', () => { art.dataset.failed = art.getAttribute('src') || 'x'; art.hidden = true; blank.hidden = false; });
    art.title = 'Double-click: show only the artwork'; blank.title = 'Double-click: show only the artwork';
'''

PIP_ART_PRESS_OLD = r'''    box.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('button, input, .pip-music-pop')) return;
      box.setPointerCapture(e.pointerId);
      musicDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: box.offsetLeft, top: box.offsetTop, moved: false };
    });
'''
PIP_ART_PRESS_NEW = r'''    box.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('button, input, .pip-music-pop')) return;
      /* [pip-art] two presses on the artwork within 400 ms are a double-click (seen here, because the
         player captures the pointer and a dblclick would land on the box): the player becomes the
         artwork alone, or comes back */
      if (e.target.closest('.pip-music-art, .pip-music-blank')) {
        const now = root.performance.now();
        if (musicArtPress && now - musicArtPress.at < 400 && Math.hypot(e.clientX - musicArtPress.x, e.clientY - musicArtPress.y) < 8) {
          musicArtPress = null; e.preventDefault();
          api().pipUpdate({ musicArtOnly: !state?.musicArtOnly }).then(apply).catch(err => say(err.message)); return;
        }
        musicArtPress = { at: now, x: e.clientX, y: e.clientY };
      }
      box.setPointerCapture(e.pointerId);
      musicDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: box.offsetLeft, top: box.offsetTop, moved: false };
    });
'''

PIP_ART_VARS_OLD = r'''  let musicDrag = null, musicSpot = null, musicBig = false, musicTimer = 0, musicClock = null, musicPop = '';
'''
PIP_ART_VARS_NEW = r'''  let musicDrag = null, musicSpot = null, musicBig = false, musicTimer = 0, musicClock = null, musicPop = '', musicArtPress = null;   /* [pip-art] */
'''

PIP_SYNC_MUSIC_OLD = r'''    const big = musicExpanded(); box.classList.toggle('expanded', big);
'''
PIP_SYNC_MUSIC_NEW = r'''    const big = musicExpanded(); box.classList.toggle('expanded', big);
    box.classList.toggle('art-only', !!state?.musicArtOnly);   /* [pip-art] */
'''

PIP_DOCK_OLD = r'''      if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);
'''
PIP_DOCK_NEW = r'''      if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name) && !placedFreely(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);   /* [pip-free] a placed widget leaves the dock */
'''

PIP_GRIP_OLD = r'''    handle.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      e.preventDefault(); handle.setPointerCapture(e.pointerId); widget.classList.add('dragging');
    });
    handle.addEventListener('pointerup', e => {
      if (!widget.classList.contains('dragging')) return;
      widget.classList.remove('dragging');
      const dock = e.clientY < innerHeight / 2 ? 'top' : 'bottom';
      const siblings = [...overlay.querySelectorAll('.pip-dock.pip-dock-' + dock + ' > .pip-widget')].filter(n => n !== widget);
      const before = siblings.find(n => e.clientY < n.getBoundingClientRect().top + n.getBoundingClientRect().height / 2);
      const order = before ? Number(before.style.order) - .5 : Math.max(0, ...siblings.map(n => Number(n.style.order))) + 1;
      api().pipUpdate({ docks: { [name]: dock }, order: { [name]: order } }).catch(err => say(err.message));
    });
    handle.addEventListener('pointercancel', () => widget.classList.remove('dragging'));
'''
PIP_GRIP_NEW = r'''    /* [pip-free] The handle drags the widget anywhere. Dropped within DOCK_ZONE of the top or
       bottom edge it docks there (the old behaviour, with its order); dropped elsewhere it stays
       where it was put, as a layout entry. The box that moves is the widget itself (the chat's
       handle sits in its header). */
    const box = () => freeBox(name) || widget;
    let drag = null;
    handle.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      e.preventDefault(); handle.setPointerCapture(e.pointerId); widget.classList.add('dragging');
      const r = box().getBoundingClientRect();
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: r.left, top: r.top, width: r.width, height: r.height, moved: false, lifted: false };
      root.addEventListener('pointerup', drop, { once: true, capture: true });   /* a pointerup the handle no longer hears still ends the drag */
    });
    handle.addEventListener('pointermove', e => {
      if (!drag || drag.id !== e.pointerId) return;
      if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) return;
      const b = box();
      if (!drag.moved) {
        drag.moved = true;
        if (liftWidget(name, drag)) { drag.lifted = true; try { handle.setPointerCapture(e.pointerId); } catch (_) {} }   /* a new parent loses the capture: take it again */
      }
      const left = Math.max(-b.offsetWidth + 24, Math.min(innerWidth - 24, drag.left + e.clientX - drag.x)), top = Math.max(0, Math.min(innerHeight - 16, drag.top + e.clientY - drag.y));
      b.style.left = left + 'px'; b.style.top = top + 'px';
      overlay.classList.toggle('pip-dock-hint-top', dockable(name) && e.clientY < DOCK_ZONE);
      overlay.classList.toggle('pip-dock-hint-bottom', dockable(name) && e.clientY > innerHeight - DOCK_ZONE);
    });
    const drop = e => {
      if (!drag || drag.id !== e.pointerId) return;
      const d = drag; drag = null; widget.classList.remove('dragging'); overlay.classList.remove('pip-dock-hint-top', 'pip-dock-hint-bottom');
      if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
      if (e.type === 'pointercancel') { layoutWidgets(); return; }
      const zone = e.clientY < DOCK_ZONE ? 'top' : e.clientY > innerHeight - DOCK_ZONE ? 'bottom' : '';
      if (!d.moved && !dockable(name)) return;
      if (dockable(name) && (zone || !d.moved)) {
        const dock = zone || (e.clientY < innerHeight / 2 ? 'top' : 'bottom');
        const siblings = [...overlay.querySelectorAll('.pip-dock.pip-dock-' + dock + ' > .pip-widget')].filter(n => n !== widget);
        const before = siblings.find(n => e.clientY < n.getBoundingClientRect().top + n.getBoundingClientRect().height / 2);
        const order = before ? Number(before.style.order) - .5 : Math.max(0, ...siblings.map(n => Number(n.style.order))) + 1;
        const entry = layoutOf(name); const kept = entry ? { ...entry } : null; if (kept) { delete kept.x; delete kept.y; delete kept.w; delete kept.h; }
        api().pipUpdate({ docks: { [name]: dock }, order: { [name]: order }, layout: { [name]: kept && Object.keys(kept).length ? kept : null } }).then(apply).catch(err => say(err.message));
        return;
      }
      const b = box(), placed = { x: b.offsetLeft / innerWidth, y: b.offsetTop / innerHeight };
      if (d.lifted) { placed.w = b.offsetWidth / innerWidth; if (name === 'chat' || name === 'voices') placed.h = b.offsetHeight / innerHeight; }   /* the width it was lifted at stays its width */
      saveLayout(name, placed);
    };
    handle.addEventListener('pointerup', drop); handle.addEventListener('pointercancel', drop);
    /* a right-click on the handle is answered by the overlay's own contextmenu listener (showAdjust) */
'''

PIP_GRIP_KEYS_OLD = r'''    handle.addEventListener('keydown', e => {
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault(); const dock = e.key === 'Home' ? 'top' : e.key === 'End' ? 'bottom' : state.docks[name];
'''
PIP_GRIP_KEYS_NEW = r'''    handle.addEventListener('keydown', e => {
      if (placedFreely(name) && e.key.startsWith('Arrow') && !e.ctrlKey && !e.altKey) {   /* [pip-free] a placed widget is nudged; Shift takes bigger steps */
        e.preventDefault(); const step = (e.shiftKey ? 24 : 6), b = freeBox(name) || widget;
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0, dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
        saveLayout(name, { x: (b.offsetLeft + dx) / innerWidth, y: (b.offsetTop + dy) / innerHeight }); return;
      }
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault(); const dock = e.key === 'Home' ? 'top' : e.key === 'End' ? 'bottom' : state.docks[name];
'''

PIP_FREE_LIB_OLD = r'''  function grip(widget, name) {
'''
PIP_FREE_LIB_NEW = r'''  /* [pip-free] ----------------------------------------------------------------------------------
     Every widget carries a layout entry {x,y,w,h,s,t,o} (window shares, a scale, four trims in
     % of the widget, an opacity). Widgets with a place of their own (the player, the message
     tile, the slate, the camera) keep their own position preferences; the entry adds the rest.
     Docked widgets leave the dock when placed (x,y) and return when docked again or reset. */
  const DOCK_ZONE = 34, OWN_PLACE = new Set(['music', 'messages', 'roulette', 'camera']), FREE_NAMES = ['dialogue', 'task', 'audit', 'production', 'music', 'chat', 'messages', 'cast', 'voices', 'roulette', 'camera'];
  const WIDGET_WORDS = { dialogue: 'Dialogue + rolling dice', task: 'Task status marquee', audit: 'Station audit marquee', production: 'Production marquee', music: 'Music player', chat: 'Chat + roulette + SFX feed', messages: 'System3 message tile', cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette slate', camera: 'Pine Cam' };
  let layoutSaveTimer = 0, layoutPending = {}, adjustFor = '';
  function freeBox(name) { return name === 'camera' ? camera : widgets[name]; }
  function layoutOf(name) { const entry = state?.layout?.[name]; return entry && typeof entry === 'object' ? entry : null; }
  function dockable(name) { return !OWN_PLACE.has(name) && name !== 'chat' && name !== 'voices'; }
  function placedFreely(name) { const l = layoutOf(name); return !!l && !OWN_PLACE.has(name) && Number.isFinite(l.x) && Number.isFinite(l.y); }
  function trimsOf(entry) { return (entry && Array.isArray(entry.t) && entry.t.length === 4 ? entry.t : [0, 0, 0, 0]).map(v => Math.max(0, Math.min(45, Number(v) || 0))); }
  function saveLayout(name, patch, immediate = true) {
    layoutPending[name] = { ...(layoutPending[name] || {}), ...patch };
    const entry = { ...(layoutOf(name) || {}), ...layoutPending[name] };
    if (state?.layout) state.layout = { ...state.layout, [name]: entry }; else if (state) state.layout = { [name]: entry };
    applyFree(name);
    clearTimeout(layoutSaveTimer);
    const flush = () => { const batch = layoutPending; layoutPending = {}; if (Object.keys(batch).length) api().pipUpdate({ layout: batch }).then(apply).catch(err => say(err.message)); };
    if (immediate) flush(); else layoutSaveTimer = setTimeout(flush, 450);
  }
  /* a docked widget steps out of its dock at the exact place it was, so a drag starts from there */
  function liftWidget(name, from) {
    const b = freeBox(name); if (!b || placedFreely(name) || OWN_PLACE.has(name)) return false;
    if (b.parentElement !== overlay) overlay.appendChild(b);
    b.classList.add('pip-free'); b.style.right = 'auto'; b.style.bottom = 'auto';
    const keep = name === 'chat' || name === 'voices';
    b.style.left = from.left + 'px'; b.style.top = from.top + 'px';
    b.style.width = (keep ? from.width : Math.min(from.width, Math.max(260, innerWidth * .55))) + 'px';   /* a full-width dock row is lifted at a usable width */
    if (keep) b.style.height = from.height + 'px';
    ensureGrips(name);
    return true;
  }
  function applyFree(name) {
    const b = freeBox(name); if (!b) return;
    const l = layoutOf(name), placed = placedFreely(name);
    if (!OWN_PLACE.has(name)) {
      b.classList.toggle('pip-free', placed);
      if (placed) {
        if (b.parentElement !== overlay) overlay.appendChild(b);
        const w = l.w > 0 ? Math.max(48, l.w * innerWidth) : 0, h = l.h > 0 ? Math.max(20, l.h * innerHeight) : 0;
        b.style.width = w ? w + 'px' : ''; b.style.height = h ? h + 'px' : '';
        b.style.left = Math.max(-((w || b.offsetWidth) - 24), Math.min(innerWidth - 24, l.x * innerWidth)) + 'px';
        b.style.top = Math.max(0, Math.min(innerHeight - 16, l.y * innerHeight)) + 'px';
        b.style.right = 'auto'; b.style.bottom = 'auto';
        ensureGrips(name);
      } else { for (const key of ['width', 'height', 'left', 'top', 'right', 'bottom']) b.style[key] = ''; }
    }
    const s = l && Number.isFinite(l.s) ? Math.max(.4, Math.min(3, l.s)) : 1, o = l && Number.isFinite(l.o) ? Math.max(.1, Math.min(1, l.o)) : 1, t = trimsOf(l);
    b.style.transform = s !== 1 ? 'scale(' + s + ')' : ''; b.style.transformOrigin = s !== 1 ? 'top left' : '';
    b.style.opacity = o !== 1 ? String(o) : '';
    b.style.clipPath = t.some(Boolean) ? 'inset(' + t.map(v => v + '%').join(' ') + ')' : '';
    b.classList.toggle('pip-trimmed', t.some(Boolean));
  }
  function layoutWidgets() { if (!overlay) return; for (const name of FREE_NAMES) applyFree(name); }
  /* eight edge grips on a placed widget: drag resizes (the far edge stays); with Shift the same drag trims that side */
  function ensureGrips(name) {
    const b = freeBox(name); if (!b || b.querySelector(':scope > .pip-free-edge') || name === 'camera') return;
    for (const edge of ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']) {
      const grip = node('button', 'pip-free-edge ' + edge); grip.type = 'button'; grip.dataset.edge = edge;
      grip.title = 'Drag to resize; hold Shift to trim this side'; grip.setAttribute('aria-label', 'Resize ' + (WIDGET_WORDS[name] || name) + ' ' + edge);
      let d = null;
      grip.addEventListener('pointerdown', e => {
        if (e.button !== 0) return; e.preventDefault(); e.stopPropagation(); grip.setPointerCapture(e.pointerId);
        const r = b.getBoundingClientRect(), l = layoutOf(name) || {};
        d = { id: e.pointerId, x: e.clientX, y: e.clientY, left: b.offsetLeft, top: b.offsetTop, width: r.width, height: r.height, trim: e.shiftKey, t: trimsOf(l), s: Number.isFinite(l.s) ? l.s : 1 };
        b.classList.add('resizing');
      });
      grip.addEventListener('pointermove', e => {
        if (!d || d.id !== e.pointerId) return;
        const dx = e.clientX - d.x, dy = e.clientY - d.y;
        if (d.trim) {
          const t = [...d.t];
          if (edge.includes('n')) t[0] = d.t[0] + dy / d.height * 100; if (edge.includes('s')) t[2] = d.t[2] - dy / d.height * 100;
          if (edge.includes('w')) t[3] = d.t[3] + dx / d.width * 100; if (edge.includes('e')) t[1] = d.t[1] - dx / d.width * 100;
          d.next = { t: t.map(v => Math.round(Math.max(0, Math.min(45, v)) * 10) / 10) };
          b.style.clipPath = 'inset(' + d.next.t.map(v => v + '%').join(' ') + ')'; return;
        }
        let left = d.left, top = d.top, width = d.width / d.s, height = d.height / d.s;
        if (edge.includes('e')) width = Math.max(48, d.width / d.s + dx / d.s); if (edge.includes('s')) height = Math.max(20, d.height / d.s + dy / d.s);
        if (edge.includes('w')) { width = Math.max(48, d.width / d.s - dx / d.s); left = d.left + (d.width / d.s - width) * d.s; }
        if (edge.includes('n')) { height = Math.max(20, d.height / d.s - dy / d.s); top = d.top + (d.height / d.s - height) * d.s; }
        d.next = { x: left / innerWidth, y: top / innerHeight, w: width / innerWidth, h: height / innerHeight };
        b.style.left = left + 'px'; b.style.top = top + 'px'; b.style.width = width + 'px'; b.style.height = height + 'px';
      });
      const done = e => {
        if (!d || d.id !== e.pointerId) return;
        const got = d; d = null; b.classList.remove('resizing'); if (grip.hasPointerCapture(e.pointerId)) grip.releasePointerCapture(e.pointerId);
        if (e.type === 'pointercancel' || !got.next) { applyFree(name); return; }
        if (!OWN_PLACE.has(name) || got.trim) saveLayout(name, got.trim ? got.next : got.next);
        else saveLayout(name, { w: got.next.w, h: got.next.h });
      };
      grip.addEventListener('pointerup', done); grip.addEventListener('pointercancel', done);
      b.appendChild(grip);
    }
  }
  function widgetNameOf(element) {
    const b = element?.closest?.('.pip-widget, .pip-voices, .pip-camera'); if (!b) return '';
    if (b === camera) return 'camera';
    return Object.keys(widgets).find(key => widgets[key] === b) || '';
  }
  function scaleWidget(name, factor) {
    const l = layoutOf(name) || {}, s = Math.round(Math.max(.4, Math.min(3, (Number.isFinite(l.s) ? l.s : 1) * factor)) * 100) / 100;
    if (!OWN_PLACE.has(name) && !placedFreely(name)) { const r = freeBox(name).getBoundingClientRect(); saveLayout(name, { x: r.left / innerWidth, y: r.top / innerHeight, s }, false); return; }
    saveLayout(name, { s }, false);
  }
  /* the adjust popover: scale, opacity, four trims, dock or free, reset, hide; it has an X */
  function showAdjust(name, near) {
    let pop = overlay.querySelector('.pip-adjust');
    if (pop && adjustFor === name) { pop.remove(); adjustFor = ''; return; }
    pop?.remove(); adjustFor = name;
    pop = node('section', 'pip-adjust'); pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', (WIDGET_WORDS[name] || name) + ' layout');
    const head = node('header', '', WIDGET_WORDS[name] || name), x = node('button', 'pip-adjust-x'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close layout options');
    if (typeof root.pineIcon === 'function') x.innerHTML = root.pineIcon('c:close--filled'); else x.textContent = 'x';
    x.addEventListener('click', () => { pop.remove(); adjustFor = ''; }); head.appendChild(x); pop.appendChild(head);
    const l = () => layoutOf(name) || {};
    const slider = (label, min, max, step, value, unit, onInput) => {
      const row = node('label', 'pip-adjust-row', label), input = node('input'), out = node('output');
      input.type = 'range'; input.min = String(min); input.max = String(max); input.step = String(step); input.value = String(value); input.setAttribute('aria-label', label);
      out.textContent = Math.round(value * (unit === '%' ? 100 : 1)) + unit;
      input.addEventListener('input', () => { out.textContent = Math.round(Number(input.value) * (unit === '%' ? 100 : 1)) + unit; onInput(Number(input.value)); });
      row.append(input, out); pop.appendChild(row); return input;
    };
    slider('Scale', .4, 3, .05, Number.isFinite(l().s) ? l().s : 1, '%', v => scaleWidgetTo(name, v));
    slider('Opacity', .1, 1, .05, Number.isFinite(l().o) ? l().o : 1, '%', v => saveLayout(name, { o: v }, false));
    const trims = node('div', 'pip-adjust-trims'); trims.append(node('b', '', 'Trim')); pop.appendChild(trims);
    ['Top', 'Right', 'Bottom', 'Left'].forEach((side, i) => {
      const row = node('label', 'pip-adjust-trim', side), input = node('input'), out = node('output'); input.type = 'range'; input.min = '0'; input.max = '45'; input.step = '1'; input.value = String(trimsOf(l())[i]); input.setAttribute('aria-label', 'Trim ' + side.toLowerCase());
      out.textContent = input.value + '%'; input.addEventListener('input', () => { const t = trimsOf(l()); t[i] = Number(input.value); out.textContent = input.value + '%'; saveLayout(name, { t }, false); });
      row.append(input, out); trims.appendChild(row);
    });
    const keys = node('div', 'pip-adjust-keys'); pop.appendChild(keys);
    const shut = () => { pop.remove(); if (adjustFor === name) adjustFor = ''; };
    const key = (label, run, closes) => { const button = node('button', '', label); button.type = 'button'; button.addEventListener('click', () => Promise.resolve().then(run).then(() => { if (closes) shut(); }).catch(err => say(err.message))); keys.appendChild(button); };
    if (dockable(name)) { key('Dock top', () => api().pipUpdate({ docks: { [name]: 'top' }, layout: { [name]: null } }).then(apply), true); key('Dock bottom', () => api().pipUpdate({ docks: { [name]: 'bottom' }, layout: { [name]: null } }).then(apply), true); }
    key('Reset size', () => saveLayout(name, { w: 0, h: 0 }));
    key('Reset trim', () => { saveLayout(name, { t: [0, 0, 0, 0] }); pop.querySelectorAll('.pip-adjust-trim input').forEach(input => { input.value = '0'; input.nextElementSibling.textContent = '0%'; }); });
    key('Reset all', () => api().pipUpdate({ layout: { [name]: null } }).then(apply), true);
    if (name !== 'camera') key('Hide widget', () => api().pipUpdate({ widgets: { [name]: false } }).then(apply), true);
    pop.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); pop.remove(); adjustFor = ''; } });
    overlay.appendChild(pop);
    /* beside the handle when it fits (never over it, so a second right-click can close it), else below or above, else clamped */
    const r = near?.getBoundingClientRect?.() || { left: innerWidth / 2, right: innerWidth / 2, bottom: innerHeight / 2, top: innerHeight / 2 };
    const w = pop.offsetWidth, h = pop.offsetHeight, clampY = y => Math.max(4, Math.min(innerHeight - h - 4, y)), clampX = x => Math.max(4, Math.min(innerWidth - w - 4, x));
    const spots = [[r.right + 8, clampY(r.top)], [r.left - w - 8, clampY(r.top)], [clampX(r.left), r.bottom + 6], [clampX(r.left), r.top - h - 6]];
    const fits = spots.find(([x, y]) => x >= 4 && y >= 4 && x + w <= innerWidth - 4 && y + h <= innerHeight - 4) || [clampX(r.left), clampY(r.bottom + 6)];
    pop.style.left = fits[0] + 'px'; pop.style.top = fits[1] + 'px'; pop.querySelector('input')?.focus();
  }
  function scaleWidgetTo(name, s) {
    if (!OWN_PLACE.has(name) && !placedFreely(name)) { const r = freeBox(name).getBoundingClientRect(); saveLayout(name, { x: r.left / innerWidth, y: r.top / innerHeight, s }, false); return; }
    saveLayout(name, { s }, false);
  }
  /* [pip-playbar] a 3 px bar along the foot of the PiP display: the playing video's position, green to
     blue to white across the width; what is left is the unlit part. [pip-export-bar] the same bar, with
     words over it, while an export runs - in PiP and in the full app alike. */
  const videoTime = { panel: null, shell: null };
  let playbar, exportbar, exportTimer = 0, exportQuiet = 0;
  function paintPlaybar() {
    if (!playbar) return;
    const t = videoTime.panel || videoTime.shell, on = !!(state?.active && t && t.dur > 0 && Number.isFinite(t.dur));
    playbar.hidden = !on; if (!on) return;
    const share = Math.max(0, Math.min(1, t.at / t.dur));
    playbar.style.setProperty('--pip-played', (share * 100).toFixed(2) + '%');
    playbar.setAttribute('aria-valuenow', String(Math.round(share * 100)));
    playbar.classList.toggle('paused', !t.playing);
    playbar.title = 'Video ' + musicTime(t.at) + ' of ' + musicTime(t.dur) + ' (' + musicTime(Math.max(0, t.dur - t.at)) + ' left)';
  }
  function heardVideoTime(surface, time) {
    videoTime[surface] = time && typeof time === 'object' && Number(time.dur) > 0 ? { at: Math.max(0, Number(time.at) || 0), dur: Number(time.dur), playing: time.playing === true } : null;
    paintPlaybar();
  }
  const EXPORT_STAGE = { flush: 'gathering the buffer', encode: 'encoding', save: 'saving', upload: 'uploading to the station' };
  function exportName(note) { return note.view === 'pip' ? 'Pine PiP video' : note.view === 'tablet' ? 'PineTab recording' : note.audio ? 'Pine app broadcast mix' : 'Pine app video'; }
  function paintExport(note) {
    if (!exportbar) return;
    clearTimeout(exportTimer); clearTimeout(exportQuiet);
    const text = exportbar.querySelector('span');
    if (!note || note.stage === 'done' || note.stage === 'failed') {
      if (note) {
        exportbar.hidden = false; exportbar.classList.remove('busy'); exportbar.classList.toggle('failed', note.stage === 'failed');
        exportbar.style.setProperty('--pip-done', note.stage === 'done' ? '100%' : '0%');
        text.textContent = note.stage === 'done' ? 'Saved ' + exportName(note) + (Number(note.seconds) > 0 ? ' - ' + Math.round(note.seconds) + ' s' : '') : exportName(note) + ' export failed' + (note.detail ? ': ' + note.detail : '');
      }
      exportTimer = setTimeout(() => { exportbar.hidden = true; exportbar.classList.remove('failed'); }, note ? (note.stage === 'failed' ? 7000 : 3500) : 0);
      return;
    }
    const known = Number.isFinite(note.ratio);
    exportbar.hidden = false; exportbar.classList.toggle('busy', !known); exportbar.classList.remove('failed');
    exportbar.style.setProperty('--pip-done', known ? (Math.max(0, Math.min(1, note.ratio)) * 100).toFixed(1) + '%' : '0%');
    text.textContent = 'Exporting ' + exportName(note) + (known ? ' - ' + Math.round(note.ratio * 100) + '%' : '...') + (EXPORT_STAGE[note.stage] ? ' - ' + EXPORT_STAGE[note.stage] : '');
    exportQuiet = setTimeout(() => paintExport(null), 180000);   /* an export that says nothing for three minutes has stopped */
  }
  function grip(widget, name) {
'''

PIP_BUILD_OLD = r'''    const voices = node('div', 'pip-voices'); widgets.voices = voices; overlay.appendChild(voices);
'''
PIP_BUILD_NEW = r'''    const voices = node('div', 'pip-voices'); widgets.voices = voices; overlay.appendChild(voices);
    grip(voices, 'voices');   /* [pip-free] the bubbles' region has a handle too (it shows on hover) */
    /* [pip-playbar] [pip-export-bar] the bars along the foot */
    playbar = node('div', 'pip-playbar'); playbar.hidden = true; playbar.setAttribute('role', 'progressbar'); playbar.setAttribute('aria-label', 'Video playback'); playbar.setAttribute('aria-valuemin', '0'); playbar.setAttribute('aria-valuemax', '100'); overlay.appendChild(playbar);
    exportbar = node('div', 'pip-exportbar'); exportbar.hidden = true; exportbar.setAttribute('role', 'status'); exportbar.append(node('i'), node('span')); document.body.appendChild(exportbar);
    /* [pip-free] Ctrl+wheel over a widget scales it */
    overlay.addEventListener('wheel', e => {
      if (!e.ctrlKey || !state?.active) return;
      const name = widgetNameOf(e.target); if (!name) return;
      e.preventDefault(); scaleWidget(name, e.deltaY < 0 ? 1.05 : 1 / 1.05);
    }, { passive: false });
    root.addEventListener('resize', () => layoutWidgets());
'''

PIP_CTX_OLD = r'''    overlay.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); showMenu().catch(err => say(err.message)); }, true);
'''
PIP_CTX_NEW = r'''    overlay.addEventListener('contextmenu', e => {
      e.preventDefault(); e.stopPropagation();
      /* [pip-free] a right-click on a widget's own handle opens its layout options instead of the menu */
      const handle = e.target.closest('.pip-grip, .pip-camera-move, .pip-free-edge, .pip-messages header, .pip-slate header');
      const name = handle ? widgetNameOf(handle) : (e.altKey || (e.target.closest('.pip-music') && !e.target.closest('button, input, .pip-music-pop'))) ? widgetNameOf(e.target) : '';
      if (name) { showAdjust(name, handle || freeBox(name)); return; }   /* a trimmed widget may hide its handle: Alt + right-click on it, or the menu's Widget layout */
      showMenu().catch(err => say(err.message));
    }, true);
'''

PIP_IPC_OLD = r'''      if (state?.active && e.channel === 'pine-pip-voices') { voiceReadings.panel = e.args[0] || []; return; }
'''
PIP_IPC_NEW = r'''      if (state?.active && e.channel === 'pine-pip-voices') { voiceReadings.panel = e.args[0] || []; return; }
      if (e.channel === 'pine-pip-time') { heardVideoTime('panel', e.args[0]); return; }   /* [pip-playbar] */
'''

PIP_MSG_OLD = r'''      if (e.data?.type === 'pine-pip-voices') voiceReadings.shell = e.data.readings || [];
'''
PIP_MSG_NEW = r'''      if (e.data?.type === 'pine-pip-voices') voiceReadings.shell = e.data.readings || [];
      if (e.data?.type === 'pine-pip-time') heardVideoTime('shell', e.data.time);   /* [pip-playbar] */
'''

PIP_BOOT_OLD = r'''    api().onPipState(apply); api().pipState().then(apply).catch(e => say(e.message));
'''
PIP_BOOT_NEW = r'''    api().onReplayProgress?.(paintExport);   /* [pip-export-bar] */
    api().onPipState(apply); api().pipState().then(apply).catch(e => say(e.message));
'''

PIP_LEAVE_OLD = r'''      root.PinePipPanel?.set(false, '', true); shellCount = panelCount = 0;
'''
PIP_LEAVE_NEW = r'''      root.PinePipPanel?.set(false, '', true); shellCount = panelCount = 0;
      videoTime.panel = videoTime.shell = null; overlay.querySelector('.pip-adjust')?.remove(); adjustFor = '';   /* [pip-playbar] [pip-free] */
'''

PIP_PANEL_TIME_OLD = r'''      if (Math.floor(now / 500) !== frame.scan) {
        frame.scan = Math.floor(now / 500);
'''
PIP_PANEL_TIME_NEW = r'''      if (Math.floor(now / 250) !== frame.clock) {   /* [pip-playbar] the first playing video's clock, four times a second */
        frame.clock = Math.floor(now / 250);
        const first = [...tiles.values()].find(it => !it.leaving && Number.isFinite(it.video.duration) && it.video.duration > 0);
        const time = first ? { at: first.video.currentTime, dur: first.video.duration, playing: !first.video.paused && !first.video.ended } : null;
        const key = time ? Math.round(time.at * 4) + ':' + Math.round(time.dur) + ':' + time.playing : '';
        if (frame.told !== key) { frame.told = key; w.postMessage({ type: 'pine-pip-time', time }, '*'); }
      }
      if (Math.floor(now / 500) !== frame.scan) {
        frame.scan = Math.floor(now / 500);
'''

PIP_ADJUST_ACTION_OLD = r"""    if(action?.type==='favorite')return api().pipToolsOpen({id:action.id});
"""
PIP_ADJUST_ACTION_NEW = r"""    if(action?.type==='favorite')return api().pipToolsOpen({id:action.id});
    if (action?.type === 'adjust' && action.name) { showAdjust(String(action.name), freeBox(String(action.name))); return; }   /* [pip-free] from the menu's Widget layout */
"""

PIP_VOLUME_OLD = r"""  function musicVolume() {
    openMusicPop('volume', 'Application volume', pop => {
      const row = node('label', 'pip-music-row'), slider = node('input'), value = node('output');
      slider.type = 'range'; slider.min = '0'; slider.max = '100'; slider.step = '1'; slider.setAttribute('aria-label', 'Application volume');
      slider.value = document.getElementById('appVolume')?.value || String(Math.round(Number(localStorage.getItem('pineDesktopAppVolume') ?? .35) * 100)); value.textContent = slider.value + '%';
      slider.oninput = () => {
        const master = document.getElementById('appVolume');
        if (!master) { say('Application volume control unavailable'); return; }
        master.value = slider.value; master.dispatchEvent(new Event('input', { bubbles: true })); value.textContent = slider.value + '%';
      };
      row.append(slider, value); pop.appendChild(row); slider.focus();
    });
  }
"""
PIP_VOLUME_NEW = r"""  /* [pip-levels] "Allow me to adjust the volume of all the items in the mixer, but definitely the music
     volume in the music widget." Every level the Audio mixer has, read off and written through the same
     bus (window.pineLevels): the music first, then master, the DJs, clips, videos, pads; the application's
     own output volume last. The rows follow the bus while the popover is open. */
  const LEVEL_ROWS = [['music', 'Music', 200], ['master', 'Master', 100], ['voice', 'The DJs', 200], ['sfx', 'Clips / SFX', 200], ['video', 'Videos', 200], ['pads', 'Pads', 200]];
  let levelsTimer = 0;
  function musicVolume() {
    clearInterval(levelsTimer); levelsTimer = 0;
    openMusicPop('volume', 'Volume', pop => {
      const bus = root.pineLevels, rows = [];
      const list = node('div', 'pip-music-levels'); pop.appendChild(list);
      const levelRow = (host, key, label, most, read, write) => {
        const row = node('label', 'pip-music-row pip-music-level'), name = node('span', 'pip-music-level-name', label), slider = node('input'), value = node('output');
        slider.type = 'range'; slider.min = '0'; slider.max = String(most); slider.step = '1'; slider.setAttribute('aria-label', label + ' volume'); slider.dataset.level = key;
        const paint = () => { if (slider === document.activeElement) return; const pct = read(); if (pct === null) return; slider.value = String(pct); value.textContent = pct + '%'; };
        slider.oninput = () => { value.textContent = slider.value + '%'; write(Number(slider.value)); };
        row.append(name, slider, value); host.appendChild(row); paint(); rows.push(paint); return slider;
      };
      if (bus && typeof bus.get === 'function' && typeof bus.apply === 'function') {
        const current = () => { try { return bus.get() || {}; } catch (_) { return {}; } };
        for (const [key, label, most] of LEVEL_ROWS) {
          levelRow(list, key, label, most, () => { const v = Number(current()[key]); return Number.isFinite(v) ? Math.round(v * 100) : null; }, pct => { try { bus.apply(key, pct / 100); } catch (err) { say(err.message); } });
        }
        list.firstChild?.classList.add('pip-music-level-music');
      } else {
        list.appendChild(node('small', 'pip-music-note', 'The station levels are still loading; the Audio mixer in the menu has every one.'));
      }
      levelRow(list, 'app', 'Application', 100, () => {
        const master = document.getElementById('appVolume');
        return Math.round(master ? Number(master.value) : Number(localStorage.getItem('pineDesktopAppVolume') ?? .35) * 100);
      }, pct => {
        const master = document.getElementById('appVolume');
        if (!master) { say('Application volume control unavailable'); return; }
        master.value = String(pct); master.dispatchEvent(new Event('input', { bubbles: true }));
      });
      levelsTimer = setInterval(() => { if (musicPop !== 'volume' || !pop.isConnected) { clearInterval(levelsTimer); levelsTimer = 0; return; } rows.forEach(paint => paint()); }, 1000);
      pop.querySelector('input')?.focus();
    });
  }
"""

PIP_FIND_OLD = r"""  function musicFind() {
    openMusicPop('find', 'Ask for a record', pop => {
      const form = node('form', 'pip-music-row'), input = node('input'), go = node('button', '', 'Ask'); let asking = false;
      input.type = 'search'; input.placeholder = 'Title or artist'; input.setAttribute('aria-label', 'Record to ask for'); go.type = 'submit';
      form.append(input, go); pop.appendChild(form);
      form.addEventListener('submit', e => {
        e.preventDefault(); const q = input.value.trim(); if (!q || asking) return;
        asking = true; go.disabled = true; say('Asking for ' + q + '...', 0);
        api().post('/api/dj/request', { q }).then(got => {
          say(got?.ok ? 'Queued: ' + (got.title || q) + (got.artist ? ' - ' + got.artist : '') : (got?.say || got?.detail || 'The library has nothing by that name.'));
          if (got?.ok) closeMusicPop();
        }).catch(err => say(err.message)).finally(() => { asking = false; go.disabled = false; });
      });
      input.focus();
    });
  }
"""
PIP_FIND_NEW = r"""  /* [pip-find] "When searching for a song, show suggestive search results as i type. So I can click on
     the item that's the nearest to the item that I'm searching for in the query." The library is asked
     as the words are typed (/api/music/search, the station's own ranking); the nearest records are
     listed under the field; a click, or the arrow keys and Enter, asks for that very record. */
  function musicFind() {
    openMusicPop('find', 'Ask for a record', pop => {
      const form = node('form', 'pip-music-row'), input = node('input'), go = node('button', '', 'Ask'); let asking = false, seq = 0, hintTimer = 0, hits = [], chosen = -1;
      input.type = 'search'; input.placeholder = 'Title or artist'; input.setAttribute('aria-label', 'Record to ask for'); go.type = 'submit';
      input.autocomplete = 'off'; input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('aria-expanded', 'false');
      const hints = node('ol', 'pip-music-hints'); hints.hidden = true; hints.setAttribute('role', 'listbox'); hints.id = 'pipMusicHints'; input.setAttribute('aria-controls', hints.id);
      form.append(input, go); pop.append(form, hints);
      const ask = (q, hit) => {
        if (!q || asking) return;
        asking = true; go.disabled = true; say('Asking for ' + q + '...', 0);
        api().post('/api/dj/request', hit ? { q, id: hit.id } : { q }).then(got => {
          say(got?.ok ? 'Queued: ' + (got.title || q) + (got.artist ? ' - ' + got.artist : '') : (got?.say || got?.detail || 'The library has nothing by that name.'));
          if (got?.ok) closeMusicPop();
        }).catch(err => say(err.message)).finally(() => { asking = false; go.disabled = false; });
      };
      const paintHints = () => {
        hints.replaceChildren(); hints.hidden = !hits.length; input.setAttribute('aria-expanded', String(!!hits.length));
        hits.forEach((hit, i) => {
          const li = node('li'), button = node('button'); button.type = 'button'; button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(i === chosen));
          if (i === chosen) li.classList.add('chosen');
          button.append(node('b', '', hit.title || 'Untitled'), node('span', '', [hit.artist, hit.album].filter(Boolean).join(' \u00b7 ') || (hit.seconds ? musicTime(hit.seconds) : '')));
          button.title = 'Ask for this record';
          button.addEventListener('click', () => { input.value = hit.title || ''; ask([hit.title, hit.artist].filter(Boolean).join(' '), hit); });
          li.appendChild(button); hints.appendChild(li);
        });
        placeMusic();
      };
      const look = () => {
        const q = input.value.trim(), mine = ++seq;
        if (q.length < 2) { hits = []; chosen = -1; paintHints(); return; }
        api().get('/api/music/search?limit=8&q=' + encodeURIComponent(q)).then(got => {
          if (mine !== seq || musicPop !== 'find') return;
          hits = Array.isArray(got?.results) ? got.results.slice(0, 8) : []; chosen = -1; paintHints();
        }).catch(() => { if (mine === seq) { hits = []; paintHints(); } });
      };
      input.addEventListener('input', () => { clearTimeout(hintTimer); hintTimer = setTimeout(look, 180); });
      input.addEventListener('keydown', e => {
        if (!hits.length || !['ArrowDown', 'ArrowUp'].includes(e.key)) return;
        e.preventDefault(); chosen = e.key === 'ArrowDown' ? (chosen + 1) % hits.length : (chosen - 1 + hits.length) % hits.length; paintHints();
      });
      form.addEventListener('submit', e => {
        e.preventDefault(); const hit = chosen >= 0 ? hits[chosen] : null;
        ask(hit ? [hit.title, hit.artist].filter(Boolean).join(' ') : input.value.trim(), hit);
      });
      input.focus();
    });
  }
"""

PIPJS = [
    ("only a main-frame load unreadies the panel", PIP_READY_OLD, PIP_READY_NEW, "frame.addEventListener('did-start-navigation', e => { if (e.isMainFrame && !e.isInPlace) panelReady = false; });", 1),
    ("the free layout, the bars and the panel confirmation", PIP_FREE_LIB_OLD, PIP_FREE_LIB_NEW, "const DOCK_ZONE = 34, OWN_PLACE = new Set(['music', 'messages', 'roulette', 'camera'])", 1),
    ("confirmPanel()", PIP_HELPERS_OLD, PIP_HELPERS_NEW, "function confirmPanel() {", 1),
    ("a page that answers is ready", PIP_SYNC_OLD, PIP_SYNC_NEW, "a page that answers is ready, whatever the flag last heard", 1),
    ("entry confirms the switch; layout and bar follow every state", PIP_CONFIRM_OLD, PIP_CONFIRM_NEW, "if (next.active && !was) confirmPanel();", 1),
    ("shared preferences carry the new keys", PIP_SHARED_OLD, PIP_SHARED_NEW, "'musicArtOnly','layout']", 1),
    ("broken art gives way to the placeholder", PIP_ART_PAINT_OLD, PIP_ART_PAINT_NEW, "const shown = !!src && art.dataset.failed !== src;", 1),
    ("art error + the double-click's title", PIP_ART_BUILD_OLD, PIP_ART_BUILD_NEW, "art.title = 'Double-click: show only the artwork';", 1),
    ("two presses on the art", PIP_ART_PRESS_OLD, PIP_ART_PRESS_NEW, "if (e.target.closest('.pip-music-art, .pip-music-blank')) {", 1),
    ("the press is remembered", PIP_ART_VARS_OLD, PIP_ART_VARS_NEW, "musicArtPress = null;   /* [pip-art] */", 1),
    ("the player's art-only class", PIP_SYNC_MUSIC_OLD, PIP_SYNC_MUSIC_NEW, "box.classList.toggle('art-only', !!state?.musicArtOnly);   /* [pip-art] */", 1),
    ("a placed widget leaves the dock", PIP_DOCK_OLD, PIP_DOCK_NEW, "&& !placedFreely(name)) overlay.querySelector('.pip-dock-'", 1),
    ("the handle drags anywhere", PIP_GRIP_OLD, PIP_GRIP_NEW, "if (liftWidget(name, drag)) { drag.lifted = true;", 1),
    ("arrow keys nudge a placed widget", PIP_GRIP_KEYS_OLD, PIP_GRIP_KEYS_NEW, "a placed widget is nudged; Shift takes bigger steps", 1),
    ("the bars, the voices handle and Ctrl+wheel", PIP_BUILD_OLD, PIP_BUILD_NEW, "playbar = node('div', 'pip-playbar');", 1),
    ("right-click a handle for its options", PIP_CTX_OLD, PIP_CTX_NEW, "if (name) { showAdjust(name, handle || freeBox(name)); return; }", 1),
    ("the menu reaches the options too", PIP_ADJUST_ACTION_OLD, PIP_ADJUST_ACTION_NEW, "if (action?.type === 'adjust' && action.name) {", 1),
    ("every level in the volume popover", PIP_VOLUME_OLD, PIP_VOLUME_NEW, "[pip-levels]", 1),
    ("records are suggested as you type", PIP_FIND_OLD, PIP_FIND_NEW, "[pip-find]", 1),
    ("the panel's clock arrives", PIP_IPC_OLD, PIP_IPC_NEW, "if (e.channel === 'pine-pip-time') { heardVideoTime('panel', e.args[0]); return; }", 1),
    ("the shell's clock arrives", PIP_MSG_OLD, PIP_MSG_NEW, "if (e.data?.type === 'pine-pip-time') heardVideoTime('shell', e.data.time);", 1),
    ("exports are heard", PIP_BOOT_OLD, PIP_BOOT_NEW, "api().onReplayProgress?.(paintExport);", 1),
    ("leaving PiP clears the clock and the popover", PIP_LEAVE_OLD, PIP_LEAVE_NEW, "videoTime.panel = videoTime.shell = null;", 1),
    ("the panel reports the playing video's clock", PIP_PANEL_TIME_OLD, PIP_PANEL_TIME_NEW, "w.postMessage({ type: 'pine-pip-time', time }, '*');", 1),
]

# --------------------------------------------------------------------------- pine-pip.css (both copies)
CSS_CAMERA_OLD = r'''.pip-camera-status { position: absolute; inset: 0; display: grid; place-content: center; padding: 12px; text-align: center; }
'''
CSS_CAMERA_NEW = r'''.pip-camera-status { position: absolute; inset: 0; display: grid; place-content: center; padding: 30px 12px 12px; text-align: center; }   /* [cam-words] the text starts below the title */
'''
CSS_NEW = r'''
/* [pip-free] placed widgets, their grips, the dock hints and the adjust popover */
#pinePipWidgets .pip-widget.pip-free, #pinePipWidgets .pip-voices.pip-free { position: absolute; z-index: 3; margin: 0; max-width: none; }
#pinePipWidgets .pip-chat.pip-free { right: auto; bottom: auto; }
#pinePipWidgets .pip-voices.pip-free { inset: auto; }
#pinePipWidgets .pip-widget.dragging, #pinePipWidgets .pip-widget.resizing { z-index: 7; transition: none; }
#pinePipWidgets .pip-widget.pip-free .pip-marquee { flex: 1; min-width: 0; }
#pinePipWidgets .pip-voices .pip-grip { position: absolute; left: 4px; top: 50%; transform: translateY(-50%); pointer-events: auto; opacity: 0; transition: opacity .2s; z-index: 2; }
#pinePipWidgets .pip-voices .pip-grip:hover, #pinePipWidgets .pip-voices .pip-grip:focus-visible, #pinePipWidgets .pip-voices.pip-free .pip-grip { opacity: .9; }
#pinePipWidgets .pip-free-edge { position: absolute; border: 0; padding: 0; margin: 0; background: transparent; z-index: 3; opacity: 0; -webkit-app-region: no-drag; }
#pinePipWidgets .pip-free:hover > .pip-free-edge, #pinePipWidgets .pip-free.resizing > .pip-free-edge, #pinePipWidgets .pip-free-edge:focus-visible { opacity: 1; }
#pinePipWidgets .pip-free-edge::after { content: ""; position: absolute; inset: 3px; border-radius: 2px; background: color-mix(in srgb, var(--pip-accent) 70%, transparent); }
#pinePipWidgets .pip-free-edge.n, #pinePipWidgets .pip-free-edge.s { left: 14px; right: 14px; height: 10px; cursor: ns-resize; }
#pinePipWidgets .pip-free-edge.e, #pinePipWidgets .pip-free-edge.w { top: 14px; bottom: 14px; width: 10px; cursor: ew-resize; }
#pinePipWidgets .pip-free-edge.n { top: -5px; } #pinePipWidgets .pip-free-edge.s { bottom: -5px; } #pinePipWidgets .pip-free-edge.e { right: -5px; } #pinePipWidgets .pip-free-edge.w { left: -5px; }
#pinePipWidgets .pip-free-edge.ne, #pinePipWidgets .pip-free-edge.nw, #pinePipWidgets .pip-free-edge.se, #pinePipWidgets .pip-free-edge.sw { width: 14px; height: 14px; }
#pinePipWidgets .pip-free-edge.ne { top: -6px; right: -6px; cursor: nesw-resize; } #pinePipWidgets .pip-free-edge.sw { bottom: -6px; left: -6px; cursor: nesw-resize; }
#pinePipWidgets .pip-free-edge.nw { top: -6px; left: -6px; cursor: nwse-resize; } #pinePipWidgets .pip-free-edge.se { bottom: -6px; right: -6px; cursor: nwse-resize; }
#pinePipWidgets .pip-free-edge.n::after, #pinePipWidgets .pip-free-edge.s::after, #pinePipWidgets .pip-free-edge.e::after, #pinePipWidgets .pip-free-edge.w::after { inset: 4px; }
#pinePipWidgets.pip-dock-hint-top .pip-dock-top, #pinePipWidgets.pip-dock-hint-bottom .pip-dock-bottom { outline: 2px dashed color-mix(in srgb, var(--pip-accent) 70%, transparent); outline-offset: -3px; min-height: 28px; background: color-mix(in srgb, var(--pip-accent) 10%, transparent); }
#pinePipWidgets .pip-adjust { position: absolute; z-index: 9; pointer-events: auto; width: 232px; padding: 8px 10px 10px; background: rgb(var(--pip-surface) / .96); color: var(--pip-text); border: 1px solid color-mix(in srgb, var(--pip-accent) 35%, transparent); border-radius: 8px; box-shadow: 0 8px 28px rgb(0 0 0 / .45); font: 12px/1.35 system-ui, sans-serif; -webkit-app-region: no-drag; }
#pinePipWidgets .pip-adjust header { position: relative; font-weight: 600; font-size: 12px; color: var(--pip-accent); padding-right: 24px; margin-bottom: 6px; }
#pinePipWidgets .pip-adjust .pip-adjust-x { position: absolute; top: -2px; right: 0; width: 20px; height: 20px; padding: 0; border: 0; background: none; color: inherit; display: grid; place-items: center; cursor: pointer; }
#pinePipWidgets .pip-adjust .pip-adjust-x svg { width: 14px; height: 14px; }
#pinePipWidgets .pip-adjust .pip-adjust-row, #pinePipWidgets .pip-adjust .pip-adjust-trim { display: grid; grid-template-columns: 52px 1fr 38px; align-items: center; gap: 6px; margin: 3px 0; }
#pinePipWidgets .pip-adjust .pip-adjust-trim { grid-template-columns: 44px 1fr 34px; font-size: 11px; }
#pinePipWidgets .pip-adjust input[type=range] { width: 100%; min-width: 0; margin: 0; }
#pinePipWidgets .pip-adjust output { text-align: right; font-variant-numeric: tabular-nums; font-size: 11px; opacity: .85; }
#pinePipWidgets .pip-adjust .pip-adjust-trims { margin-top: 6px; padding-top: 6px; border-top: 1px solid color-mix(in srgb, var(--pip-accent) 20%, transparent); }
#pinePipWidgets .pip-adjust .pip-adjust-trims > b { display: block; font-size: 11px; margin-bottom: 2px; }
#pinePipWidgets .pip-adjust .pip-adjust-keys { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
#pinePipWidgets .pip-adjust .pip-adjust-keys button { flex: 1 1 calc(50% - 4px); padding: 4px 6px; border-radius: 5px; border: 1px solid color-mix(in srgb, var(--pip-accent) 30%, transparent); background: var(--pip-button); color: var(--pip-text); font: inherit; font-size: 11px; cursor: pointer; }
#pinePipWidgets .pip-adjust .pip-adjust-keys button:hover { border-color: var(--pip-accent); }
/* [pip-art] the player reduced to its artwork alone */
.pip-music.art-only { grid-template-columns: auto; grid-template-areas: "art"; width: auto; min-width: 0; padding: 0; background: transparent; border-color: transparent; gap: 0; }
.pip-music.art-only .pip-music-side, .pip-music.art-only .pip-music-info, .pip-music.art-only .pip-music-keys, .pip-music.art-only .pip-music-seek, .pip-music.art-only .pip-music-pop { display: none; }
.pip-music.art-only .pip-music-art, .pip-music.art-only .pip-music-blank { grid-area: art; width: 96px; height: 96px; border-radius: 8px; box-shadow: 0 4px 16px rgb(0 0 0 / .45); cursor: pointer; }
.pip-music.art-only.expanded .pip-music-art, .pip-music.art-only.expanded .pip-music-blank { width: clamp(120px, calc(100vh - 150px), 250px); height: auto; aspect-ratio: 1; }
/* [pip-levels] every level of the mixer in the player's volume popover */
.pip-music .pip-music-levels { display: grid; gap: 4px; }
.pip-music .pip-music-level { display: grid; grid-template-columns: 64px minmax(0, 1fr) 40px; align-items: center; gap: 6px; }
.pip-music .pip-music-level .pip-music-level-name { font-size: 11px; opacity: .85; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pip-music .pip-music-level output { text-align: right; font-size: 11px; font-variant-numeric: tabular-nums; }
.pip-music .pip-music-level-music .pip-music-level-name { font-weight: 700; opacity: 1; color: var(--pip-accent); }
.pip-music .pip-music-note { display: block; font-size: 11px; opacity: .75; margin-bottom: 4px; }
/* [pip-find] the nearest records, as the words are typed */
.pip-music .pip-music-hints { margin: 4px 0 0; padding: 0; list-style: none; display: grid; gap: 2px; max-height: min(220px, 40vh); overflow: auto; }
.pip-music .pip-music-hints[hidden] { display: none; }
.pip-music .pip-music-hints li button { display: grid; width: 100%; text-align: left; padding: 4px 6px; border-radius: 4px; border: 1px solid transparent; background: rgb(0 0 0 / .18); color: inherit; font: inherit; cursor: pointer; min-width: 0; }
.pip-music .pip-music-hints li button:hover, .pip-music .pip-music-hints li.chosen button { border-color: var(--pip-accent); background: color-mix(in srgb, var(--pip-accent) 14%, transparent); }
.pip-music .pip-music-hints li b { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pip-music .pip-music-hints li span { font-size: 11px; opacity: .75; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* [pip-playbar] 3 px along the foot: green to blue to white across the display; the unlit part is what is left */
#pinePipWidgets .pip-playbar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; z-index: 6; pointer-events: none; background: linear-gradient(90deg, #22c55e 0%, #3b82f6 55%, #ffffff 100%); clip-path: inset(0 calc(100% - var(--pip-played, 0%)) 0 0); transition: clip-path .25s linear, opacity .3s; }
#pinePipWidgets .pip-playbar.paused { opacity: .55; }
#pinePipWidgets .pip-playbar[hidden] { display: none; }
/* [pip-export-bar] the same bar with the words over it, while an export runs; in PiP and in the full app */
.pip-exportbar { position: fixed; left: 0; right: 0; bottom: 0; height: 3px; z-index: 2147483000; pointer-events: none; font: 11px/1 system-ui, sans-serif; }
.pip-exportbar[hidden] { display: none; }
.pip-exportbar i { position: absolute; inset: 0; background: linear-gradient(90deg, #22c55e 0%, #3b82f6 55%, #ffffff 100%); clip-path: inset(0 calc(100% - var(--pip-done, 0%)) 0 0); transition: clip-path .3s ease-out; }
.pip-exportbar.busy i { clip-path: none; background: linear-gradient(90deg, transparent 0%, #22c55e 30%, #3b82f6 55%, #ffffff 70%, transparent 100%); background-size: 40% 100%; background-repeat: no-repeat; animation: pip-exportbar-sweep 1.4s linear infinite; }
.pip-exportbar.failed i { background: #e05252; clip-path: none; }
.pip-exportbar span { position: absolute; left: 50%; bottom: 7px; transform: translateX(-50%); padding: 4px 10px; border-radius: 10px; background: rgb(0 0 0 / .62); color: #e1f8ea; white-space: nowrap; max-width: 92vw; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
@keyframes pip-exportbar-sweep { from { background-position: -40% 0; } to { background-position: 140% 0; } }
@media (prefers-reduced-motion: reduce) { .pip-exportbar.busy i { animation: none; background: #3b82f6; } #pinePipWidgets .pip-playbar { transition: none; } }
'''
CSS_HIDE_OLD = r'''body.pine-pip > :not(main):not(#pinePipWidgets):not(#pine-pip-panel):not(script):not(link):not(.plv-sheet):not(#pineExportBar)'''
CSS_HIDE_NEW = r'''body.pine-pip > :not(main):not(#pinePipWidgets):not(#pine-pip-panel):not(script):not(link):not(.plv-sheet):not(#pineExportBar):not(.pip-exportbar)'''
CSS = [
    ("the camera's text starts below its title", CSS_CAMERA_OLD, CSS_CAMERA_NEW, "padding: 30px 12px 12px; text-align: center; }   /* [cam-words]", 1),
    ("the export bar is not hidden with the app's body", CSS_HIDE_OLD, CSS_HIDE_NEW, ":not(#pineExportBar):not(.pip-exportbar)", 1),
    ("placed widgets, grips, the popover, art-only and the bars", None, CSS_NEW, "/* [pip-free] placed widgets, their grips, the dock hints and the adjust popover */", 1),
]

# --------------------------------------------------------------------------- tests/test_pip_desk_2026_10_05.cjs (the first wave's checks, told about this one)
DESK_DOCK_OLD = r'''  assert.ok(js.includes("if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name))"), 'apply does not dock it');
'''
DESK_DOCK_NEW = r'''  assert.ok(js.includes("if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name) && !placedFreely(name))"), 'apply does not dock it');   /* [pip-free] nor any placed widget */
'''
DESK_CSS_OLD = r'''  const block = css.slice(css.indexOf('/* [pip-music] The music player is a mini player'));
'''
DESK_CSS_NEW = r'''  const block = css.slice(css.indexOf('/* [pip-music] The music player is a mini player'), css.indexOf('/* [pip-free] placed widgets'));   /* up to the second wave's rules */
'''
DESK_SHARED_OLD = r'''  assert.ok(js.includes("'voiceStyles','musicPosition','musicExpanded']) out[key] = value[key];"), 'its place travels with the shared settings');
'''
DESK_SHARED_NEW = r'''  assert.ok(js.includes("'voiceStyles','musicPosition','musicExpanded','musicArtOnly','layout']) out[key] = value[key];"), 'its place travels with the shared settings');   /* [pip-free] and every layout */
'''
DESK_TEST = [
    ("the shared keys grew", DESK_SHARED_OLD, DESK_SHARED_NEW, "'musicExpanded','musicArtOnly','layout']) out[key] = value[key];", 1),
    ("apply docks no placed widget", DESK_DOCK_OLD, DESK_DOCK_NEW, "&& !placedFreely(name))\"), 'apply does not dock it');", 1),
    ("the player's rules end where the second wave begins", DESK_CSS_OLD, DESK_CSS_NEW, "css.indexOf('/* [pip-free] placed widgets'));", 1),
]

EDITS = {
    "tests/test_pip_desk_2026_10_05.cjs": DESK_TEST,
    "desktop/pip-window.cjs": WINDOW,
    "desktop/preload.js": PRELOAD,
    "desktop/main.js": MAIN,
    "desktop/clip-mux.cjs": MUX,
    "desktop/screen-ring.cjs": RING,
    "desktop/renderer/webview-preload.js": RELAY,
    "desktop/renderer/pine-pip-camera-recovery.js": CAMERA,
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
    "desktop/renderer/pine-pip.css": CSS,
    "app/src/main/assets/pine-views/pine-pip.css": CSS,
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            if old is None:                                   # an addition at the end of the file
                have = text.count(probe)
                state = "applied" if have == count else "ready" if not have else "missing (probe %d)" % have
                if state == "ready":
                    text = text.rstrip("\n") + "\n" + new
                    changed = True
            else:
                forms = [(old, new, probe)]
                if mode == "mixed":                           # each line keeps the ending it has
                    forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
                state = ""
                for old_, new_, probe_ in forms:
                    have = text.count(probe_)
                    if have == count:
                        state = "applied"
                        break
                    if not have and text.count(old_) == count:
                        text = text.replace(old_, new_)
                        assert text.count(probe_) == count, (name, label, "probe after the edit")
                        state, changed = "ready", True
                        break
                if not state:
                    state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-46s %-52s %s" % (name[-46:], label[:52], state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".pipwidgets.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
