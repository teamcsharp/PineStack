#!/usr/bin/env python3
"""[pip-rec] [pip-video-folder] [cam-words] The PiP's album recorder, the Video folder menu, the camera text. 2026-10-05.

[pip-rec]  "a widget that allows me to record albums and interact with the interface and to do
           troubleshooting with the connected interface" - the operator's drawing (inbox #1577):
           album art (click: choose a recent render or a clip's picture as the set's cover), total
           session time, a falling-peak meter of the live input, the record button that becomes
           stop, the current track's time as HH:MM:SS:FF, its growing MP3 size in a rolodex (KB then
           MB), the recording bar (six minutes, growing by two when passed), the track number large,
           next track, a move notch that collapses the widget to the mini form (art, record, next,
           bar) and back. The connected interface's state sits under it; the wrench runs the
           station's own troubleshoot and lists its checks. It drives the station's MX Live
           (/api/pinelive/*): the K.O. Sidekick's set, recorded as cut pairs, MP3 320 kb/s.
[pip-video-folder] "I want an option for 'video' and it lists every folder from the SFX database
           and I am able to select a folder and it plays for the next hour and is used by the SFX
           guy when using clips" - the station's folder pin (/api/sfx/folder-pin), one hour.
[cam-words] the Pine Cam popup's title no longer sits on its text.

Both copies of pine-pip.js / pine-pip.css are patched. pip-window.cjs is the running process:
its Video submenu and the new widget's menu entry arrive at the next relaunch.

Usage:  pip_recorder_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_recorder_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- pip-window.cjs
WIN_WIDGETS_OLD = r'''const WIDGETS = { dialogue: true, task: false, audit: false, production: false, music: false, chat: false, messages: false, cast: false, voices: false, roulette: false };
'''
WIN_WIDGETS_NEW = r'''const WIDGETS = { dialogue: true, task: false, audit: false, production: false, music: false, chat: false, messages: false, cast: false, voices: false, roulette: false, rec: false };   /* [pip-rec] */
'''
WIN_LABELS_OLD = r'''cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette RNG digital slate' };'''
WIN_LABELS_NEW = r'''cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette RNG digital slate', rec: 'Album recorder (K.O. Sidekick)' };'''
WIN_VIDEO_OLD = r'''      { label: 'Endless video', '''
WIN_VIDEO_NEW = r'''      /* [pip-video-folder] every folder of the SFX collection; the chosen one owns the clips for an hour */
      { label: 'Video', submenu: [
        { label: playback?.pin ? ('Every folder (clear: ' + playback.pin.name + ', ' + playback.pin.minutes_left + ' min left)') : 'Every folder (no pin)', type: 'radio', checked: !playback?.pin, click: () => getWindow()?.webContents.send('pip:action', { type: 'video-folder', clear: true }) },
        { type: 'separator' },
        ...(Array.isArray(playback?.folders) ? playback.folders : []).filter(f => f && typeof f.path === 'string').slice(0, 300)
          .map(f => ({ label: (f.name || f.path) + '  (' + (f.video || 0) + ' video, ' + (f.audio || 0) + ' audio)', type: 'radio', checked: !!playback?.pin && playback.pin.path === f.path,
            click: () => getWindow()?.webContents.send('pip:action', { type: 'video-folder', path: f.path }) }))
      ] },
      { label: 'Endless video', '''
WINDOW = [
    ("the recorder is a widget", WIN_WIDGETS_OLD, WIN_WIDGETS_NEW, "roulette: false, rec: false };", 1),
    ("its menu label", WIN_LABELS_OLD, WIN_LABELS_NEW, "rec: 'Album recorder (K.O. Sidekick)' };", 1),
    ("the Video submenu", WIN_VIDEO_OLD, WIN_VIDEO_NEW, "{ label: 'Video', submenu: [", 1),
]

# --------------------------------------------------------------------------- pine-pip.js (both copies)
PIP_FREE_OLD = r'''  const DOCK_ZONE = 34, OWN_PLACE = new Set(['music', 'messages', 'roulette', 'camera']), FREE_NAMES = ['dialogue', 'task', 'audit', 'production', 'music', 'chat', 'messages', 'cast', 'voices', 'roulette', 'camera'];
  const WIDGET_WORDS = { dialogue: 'Dialogue + rolling dice', task: 'Task status marquee', audit: 'Station audit marquee', production: 'Production marquee', music: 'Music player', chat: 'Chat + roulette + SFX feed', messages: 'System3 message tile', cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette slate', camera: 'Pine Cam' };
'''
PIP_FREE_NEW = r'''  const DOCK_ZONE = 34, OWN_PLACE = new Set(['music', 'messages', 'roulette', 'camera']), FREE_NAMES = ['dialogue', 'task', 'audit', 'production', 'music', 'chat', 'messages', 'cast', 'voices', 'roulette', 'camera', 'rec'];
  const WIDGET_WORDS = { dialogue: 'Dialogue + rolling dice', task: 'Task status marquee', audit: 'Station audit marquee', production: 'Production marquee', music: 'Music player', chat: 'Chat + roulette + SFX feed', messages: 'System3 message tile', cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette slate', camera: 'Pine Cam', rec: 'Album recorder' };
  const DEFAULT_LAYOUT = { rec: { x: .3, y: .5 } };   /* [pip-rec] a widget born free sits here until it is moved */
'''
PIP_LAYOUTOF_OLD = r'''  function layoutOf(name) { const entry = state?.layout?.[name]; return entry && typeof entry === 'object' ? entry : null; }
  function dockable(name) { return !OWN_PLACE.has(name) && name !== 'chat' && name !== 'voices'; }
'''
PIP_LAYOUTOF_NEW = r'''  function layoutOf(name) { const entry = state?.layout?.[name]; return entry && typeof entry === 'object' ? entry : (DEFAULT_LAYOUT[name] || null); }
  function dockable(name) { return !OWN_PLACE.has(name) && name !== 'chat' && name !== 'voices' && name !== 'rec'; }
'''
PIP_DOCKLIST_OLD = r'''      if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name) && !placedFreely(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);   /* [pip-free] a placed widget leaves the dock */
'''
PIP_DOCKLIST_NEW = r'''      if (!['chat', 'voices', 'roulette', 'messages', 'music', 'rec'].includes(name) && !placedFreely(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);   /* [pip-free] a placed widget leaves the dock */
'''
PIP_GRIP_SIG_OLD = r'''  function grip(widget, name) {
    const handle = node('button', 'pip-grip', '\u283f'); handle.type = 'button'; handle.title = 'Drag to reorder or dock at top / bottom';
    handle.setAttribute('aria-label', 'Move ' + name + ' widget'); widget.prepend(handle);
'''
PIP_GRIP_SIG_NEW = r'''  function grip(widget, name, given) {
    const handle = given || node('button', 'pip-grip', '\u283f'); handle.type = 'button'; if (!given) handle.title = 'Drag to reorder or dock at top / bottom';
    handle.setAttribute('aria-label', 'Move ' + name + ' widget'); if (!given) widget.prepend(handle);
'''
PIP_SYNC_OLD = r'''    placeSlate(); syncMusic(); syncMessages(); syncMessageTileSettings();
'''
PIP_SYNC_NEW = r'''    placeSlate(); syncMusic(); syncMessages(); syncMessageTileSettings(); syncRecorder();   /* [pip-rec] */
'''
PIP_BUILD_OLD = r'''    buildMusic();   /* [pip-music] a mini player placed freely, not a strip in the top dock */
'''
PIP_BUILD_NEW = r'''    buildMusic();   /* [pip-music] a mini player placed freely, not a strip in the top dock */
    buildRecorder();   /* [pip-rec] the album recorder, placed freely */
'''
PIP_PLAYBACK_OLD = r'''      const opening = api().pipMenu({...playbackCache,favorites});
'''
PIP_PLAYBACK_NEW = r'''      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin});   /* [pip-video-folder] */
      refreshFolders();
'''
PIP_REFRESH_OLD = r'''  function refreshPlayback() {
'''
PIP_REFRESH_NEW = r'''  /* [pip-video-folder] every folder of the SFX collection and the hour's pin, for the menu; a minute old at most */
  let foldersCache = { folders: [], pin: null }, foldersAt = 0, foldersPending = false;
  function refreshFolders() {
    if (foldersPending || Date.now() - foldersAt < 60000) return; foldersPending = true;
    Promise.resolve().then(() => api().get('/api/sfx/folders')).then(got => {
      const rows = Array.isArray(got?.folders) ? got.folders : [];
      foldersCache = { folders: rows.map(f => ({ path: String(f.path || ''), name: String(f.name || f.path || ''), video: Number(f.video) || 0, audio: Number(f.audio) || 0 })).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })), pin: got?.pin || null };
      foldersAt = Date.now();
    }).catch(() => {}).finally(() => { foldersPending = false; });
  }
  function refreshPlayback() {
'''
PIP_ACTION_OLD = r'''    if (action?.type === 'background') {   /* [pip-viz] the menu names a mode, or asks for the next */
'''
PIP_ACTION_NEW = r'''    if (action?.type === 'video-folder') {   /* [pip-video-folder] the folder owns the clips for an hour */
      const body = action.clear || !action.path ? { clear: true } : { path: String(action.path), hours: 1 };
      return api().post('/api/sfx/folder-pin', body).then(got => { foldersAt = 0; refreshFolders(); say(got?.say || (body.clear ? 'Every folder again' : 'Clips come from ' + action.path + ' for the next hour'), 7000); }).catch(err => say(err.message));
    }
    if (action?.type === 'background') {   /* [pip-viz] the menu names a mode, or asks for the next */
'''

PIP_RECORDER_OLD = r'''  function grip(widget, name, given) {
'''
PIP_RECORDER_NEW = r'''  /* [pip-rec] ------------------------------------------------------------------------------------
     THE ALBUM RECORDER. The operator's drawing: album art, total time, the falling-peak meter, the
     record button that becomes stop, the current track's clock and growing size, the recording bar,
     the track number large, next track, the move notch (drag anywhere; tap: the mini form). It drives
     the station's MX Live: the K.O. Sidekick's set, recorded as cut pairs and decanted to MP3 320 kb/s.
     State comes from /api/pinelive/state once a second while the widget shows; the meter follows the
     levels stream (Server-Sent Events) when it opens, the state's reading when it does not. */
  const REC_KBPS = 320, REC_BAR_S = 360, REC_BAR_GROW_S = 120, clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;
  let recState = null, recSettings = null, recPoll = 0, recRaf = 0, recLevels = null, recLevelsUrl = '', recFed = 0, recBusy = false, recPop = '', recMini = false, recSheenAt = 0;
  const recMeter = { level: 0, peak: 0, hold: 0, at: 0 }, recClock = { elapsed: 0, stamp: 0, on: false }, recSession = { total: 0, event: '', live: 0 };
  function recTime(seconds) {
    const s = Math.max(0, Number(seconds) || 0), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = Math.floor(s) % 60, cs = Math.floor((s - Math.floor(s)) * 100);
    return [h, m, sec, cs].map(n => String(n).padStart(2, '0')).join(':');
  }
  function recShort(seconds) { const s = Math.max(0, Math.round(Number(seconds) || 0)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60; return (h ? h + ':' : '') + String(m).padStart(h ? 2 : 1, '0') + ':' + String(sec).padStart(2, '0'); }
  function recSize(bytes) { const kb = bytes / 1000; return kb < 1000 ? Math.floor(kb) + ' KB' : (kb / 1000).toFixed(2) + ' MB'; }
  function recDb(db) { const v = Number(db); return Number.isFinite(v) ? clamp((v + 60) / 60, 0, 1) : 0; }
  function recElapsed() { return recClock.on ? recClock.elapsed + (performance.now() - recClock.stamp) / 1000 : recClock.elapsed; }
  function buildRecorder() {
    const box = node('section', 'pip-widget pip-rec'); widgets.rec = box; box.setAttribute('aria-label', 'Album recorder');
    const notch = node('button', 'pip-grip pip-rec-notch'); notch.type = 'button'; notch.title = 'Drag to move the recorder; tap to fold it to the mini form and back';
    const art = node('div', 'pip-rec-art'); const img = node('img'); img.alt = 'Album art'; img.draggable = false; img.hidden = true;
    const blank = node('div', 'pip-rec-blank'); if (typeof root.pineIcon === 'function') blank.innerHTML = root.pineIcon('c:music'); art.append(img, blank, node('div', 'pip-rec-total', 'TOTAL 0:00'));
    art.title = 'The set\u2019s cover - click to choose a render or a clip\u2019s picture';
    const main = node('div', 'pip-rec-main');
    const record = node('button', 'pip-rec-record'); record.type = 'button'; record.title = 'Record'; record.setAttribute('aria-label', 'Record'); record.appendChild(node('i'));
    const meter = node('canvas', 'pip-rec-meter'); meter.width = 72; meter.height = 30; meter.setAttribute('aria-hidden', 'true');
    const bar = node('div', 'pip-rec-bar'); bar.append(node('i'), node('span', 'pip-rec-range', '6:00')); bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-label', 'Recording progress');
    const next = node('button', 'pip-rec-next'); next.type = 'button'; next.title = 'Next track'; next.setAttribute('aria-label', 'Next track'); musicIcon(next, 'c:skip--forward--filled');
    const size = node('output', 'pip-rec-size'); size.title = 'The track\u2019s MP3 size so far (320 kb/s)'; const time = node('output', 'pip-rec-time', '00:00:00:00'); time.title = 'Current track HH:MM:SS:FF';
    const track = node('div', 'pip-rec-track', '1'); track.title = 'Track number';
    const readout = node('div', 'pip-rec-readout'); readout.append(size, time);
    main.append(record, meter, bar, next, readout, track);
    const status = node('div', 'pip-rec-status'); const line = node('span', 'pip-rec-line', 'Connecting to the station...'); const tools = node('button', 'pip-rec-tools'); tools.type = 'button'; tools.title = 'Troubleshoot the connected interface'; tools.setAttribute('aria-label', 'Troubleshoot the connected interface'); musicIcon(tools, 'c:tools');
    status.append(line, tools);
    const pop = node('div', 'pip-rec-pop'); pop.hidden = true;
    box.append(notch, art, main, status, pop);
    overlay.appendChild(box);
    grip(notch, 'rec', notch);
    /* a tap on the notch (no drag) folds the widget; the grip's own drop handler ignores a still pointer for a widget that cannot dock */
    let press = null;
    notch.addEventListener('pointerdown', e => { press = { x: e.clientX, y: e.clientY }; });
    notch.addEventListener('pointerup', e => { if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) < 4) { recMini = !recMini; try { localStorage.setItem('pinePipRecMini', recMini ? '1' : ''); } catch (_) {} syncRecorder(); } press = null; });
    record.addEventListener('click', () => recToggle());
    next.addEventListener('click', () => recNext());
    tools.addEventListener('click', () => recTroubleshoot());
    art.addEventListener('click', () => recArtPicker());
    try { recMini = localStorage.getItem('pinePipRecMini') === '1'; } catch (_) {}
    try { const saved = JSON.parse(localStorage.getItem('pinePipRecSession') || 'null'); if (saved && Date.now() - (saved.at || 0) < 12 * 3600 * 1000) { recSession.total = Number(saved.total) || 0; recSession.event = String(saved.event || ''); } } catch (_) {}
  }
  function recPost(route, body, said) {
    if (recBusy) return Promise.resolve(); recBusy = true;
    return api().post(route, body || {}).then(got => { if (got && got.ok === false) say(got.say || got.detail || 'The station declined.', 7000); else if (said) say(typeof said === 'function' ? said(got) : said); if (got?.state) recTake(got.state); return recRefresh(); }).catch(err => say(err.message)).finally(() => { recBusy = false; });
  }
  function recToggle() {
    const st = recState || {};
    if (st.armed || st.live) return recPost('/api/pinelive/stop', {}, 'The set is stopped; the track is cut and decanted.');
    const settings = recSettings?.settings || {}, kind = st.source?.kind || (settings.device ? 'usb' : 'usb');
    const body = { source: kind === 'network' ? 'network' : 'usb' }; if (body.source === 'usb' && settings.device) body.device = settings.device;
    return recPost('/api/pinelive/start', body, 'Recording - the set is live.');
  }
  function recNext() { if (!(recState?.armed || recState?.live)) { say('Start recording first; next track cuts the running track.'); return; } return recPost('/api/dj/next', {}, 'Next track.'); }
  function recTake(st) {
    if (!st || typeof st !== 'object') return;
    recState = st;
    const on = !!(st.recording && st.recording.on && (st.live || st.armed));
    recClock.elapsed = Number(st.recording?.cut_elapsed) || 0; recClock.stamp = performance.now(); recClock.on = on;
    const event = st.event?.id || '';
    if (event && event !== recSession.event) { recSession.event = event; recSession.live = 0; }
    if (!event && recSession.event) { recSession.total += recSession.live; recSession.live = 0; recSession.event = ''; }
    if (event) recSession.live = Number(st.event?.live_seconds) || 0;
    try { localStorage.setItem('pinePipRecSession', JSON.stringify({ total: recSession.total, event: recSession.event, at: Date.now() })); } catch (_) {}
    if (!recLevels && Number.isFinite(Number(st.source?.level_db))) { recMeter.level = recDb(st.source.level_db); const p = recDb(st.source.peak_db); if (p >= recMeter.peak) { recMeter.peak = p; recMeter.hold = performance.now() + 700; } }
    recOpenLevels(st);
    paintRecorder();
  }
  function recRefresh() {
    if (!state?.active || !state.widgets?.rec || state.ui === false) return Promise.resolve();
    return api().get('/api/pinelive/state').then(recTake).catch(err => { const line = widgets.rec?.querySelector('.pip-rec-line'); if (line) line.textContent = 'The station is not answering: ' + err.message; });
  }
  function recOpenLevels(st) {
    const want = state?.active && state.widgets?.rec && state.ui !== false && (st.armed || st.live) && st.levels_url && typeof root.EventSource === 'function';
    const url = want ? (root.pineStationBase?.() || '') + st.levels_url : '';
    if (!want || url !== recLevelsUrl) { if (recLevels) { try { recLevels.close(); } catch (_) {} recLevels = null; recLevelsUrl = ''; } }
    if (!want || recLevels) return;
    try {
      recLevels = new root.EventSource(url); recLevelsUrl = url;
      recLevels.addEventListener('frame', e => { try { const f = JSON.parse(e.data); recFed = performance.now(); const lv = recDb(f.rms), pk = recDb(f.peak); recMeter.level = lv; if (pk >= recMeter.peak) { recMeter.peak = pk; recMeter.hold = performance.now() + 700; } } catch (_) {} });
      recLevels.onerror = () => { try { recLevels.close(); } catch (_) {} recLevels = null; recLevelsUrl = ''; };
    } catch (_) { recLevels = null; }
  }
  function recTick(now) {
    recRaf = 0;
    const box = widgets.rec; if (!box || box.hidden || !state?.active) return;
    recRaf = root.requestAnimationFrame(recTick);
    const dt = recMeter.at ? Math.min(.1, (now - recMeter.at) / 1000) : 1 / 60; recMeter.at = now;
    if (now > recMeter.hold) recMeter.peak = Math.max(recMeter.level, recMeter.peak - .55 * dt);   /* held, then falling */
    if (!recClock.on && !recLevels) recMeter.level = Math.max(0, recMeter.level - 1.6 * dt);
    const canvas = box.querySelector('.pip-rec-meter'), ctx = canvas.getContext('2d'); const w = canvas.width, h = canvas.height, n = 12, gap = 2, bw = (w - gap * (n - 1)) / n;
    ctx.clearRect(0, 0, w, h);
    const accent = getComputedStyle(box).getPropertyValue('--pip-accent').trim() || '#98e9ae';
    for (let i = 0; i < n; i++) { const f = (i + 1) / n; const lit = recMeter.level >= f - 1 / n / 2; ctx.fillStyle = lit ? (f > .92 ? '#ff5a5a' : f > .75 ? '#ffd166' : accent) : 'rgba(255,255,255,.12)'; const bh = h * (.35 + .65 * f); ctx.fillRect(i * (bw + gap), h - bh, bw, bh); }
    const px = clamp(Math.round(recMeter.peak * n) - 1, 0, n - 1); if (recMeter.peak > .02) { ctx.fillStyle = '#ffffff'; ctx.fillRect(px * (bw + gap), h - h * (.35 + .65 * (px + 1) / n) - 3, bw, 2); }
    const elapsed = recElapsed(); let range = REC_BAR_S; while (elapsed > range) range += REC_BAR_GROW_S;   /* six minutes; two more each time it is passed */
    const bar = box.querySelector('.pip-rec-bar'); bar.firstChild.style.width = (clamp(elapsed / range, 0, 1) * 100).toFixed(2) + '%'; bar.querySelector('.pip-rec-range').textContent = recShort(range); bar.setAttribute('aria-valuenow', String(Math.round(clamp(elapsed / range, 0, 1) * 100)));
    box.querySelector('.pip-rec-time').textContent = recTime(elapsed);
    recRolodex(box.querySelector('.pip-rec-size'), recSize(elapsed * REC_KBPS * 1000 / 8));
    box.querySelector('.pip-rec-total').textContent = 'TOTAL ' + recShort(recSession.total + recSession.live + (recClock.on ? (performance.now() - recClock.stamp) / 1000 : 0));
    if (recClock.on && now - recSheenAt > 7000) { recSheenAt = now; const a = box.querySelector('.pip-rec-art'); a.classList.remove('sheen'); void a.offsetWidth; a.classList.add('sheen'); }
  }
  /* the size as flipping digits: each character that changed turns over */
  function recRolodex(out, text) {
    if (out.dataset.text === text) return; out.dataset.text = text;
    const have = [...out.children];
    text.split('').forEach((ch, i) => { let cell = have[i]; if (!cell) { cell = node('b'); out.appendChild(cell); } if (cell.textContent !== ch) { cell.textContent = ch; cell.classList.remove('flip'); void cell.offsetWidth; cell.classList.add('flip'); } });
    while (out.children.length > text.length) out.lastChild.remove();
  }
  function paintRecorder() {
    const box = widgets.rec; if (!box) return; const st = recState || {};
    const on = !!(st.recording && st.recording.on && (st.live || st.armed)), armed = !!(st.armed || st.live);
    box.classList.toggle('recording', on); box.classList.toggle('armed', armed); box.classList.toggle('mini', recMini);
    const record = box.querySelector('.pip-rec-record'); record.title = armed ? 'Stop - cut the track and end the set' : 'Record - start the set and the first track'; record.setAttribute('aria-label', record.title); record.setAttribute('aria-pressed', String(armed));
    box.querySelector('.pip-rec-track').textContent = String(armed ? (st.event?.track || st.recording?.split?.track || st.recording?.cut_index || 1) : 1);   /* idle: the next set begins at track 1 */
    const img = box.querySelector('.pip-rec-art img'), blank = box.querySelector('.pip-rec-blank');
    const art = st.art_url ? (root.pineStationBase?.() || '') + st.art_url : '';
    if (art && img.dataset.src !== art) { img.dataset.src = art; img.src = art; img.hidden = false; blank.hidden = true; img.onerror = () => { img.hidden = true; blank.hidden = false; }; }
    if (!art) { img.hidden = true; img.removeAttribute('src'); img.dataset.src = ''; blank.hidden = false; }
    const src = st.source || {}, host = st.host || {};
    let words = !host.up ? ('The PineLive host is down' + (host.why ? ': ' + host.why : '')) : !src.kind ? 'No interface chosen - the wrench lists what the station sees' : (src.label || src.device || 'interface') + ' \u00b7 ' + String(src.kind).toUpperCase() + (src.connected ? ' \u00b7 connected' : ' \u00b7 not open') + (Number.isFinite(Number(src.level_db)) ? ' \u00b7 ' + Math.round(src.level_db) + ' dBFS' : '') + (src.clipping ? ' \u00b7 CLIPPING' : '');
    if (st.recording?.why) words += ' \u00b7 ' + st.recording.why;
    if (st.cover_override?.set) words += ' \u00b7 cover: ' + st.cover_override.name;
    if (st.air?.why_not) words += ' \u00b7 ' + st.air.why_not;
    box.querySelector('.pip-rec-line').textContent = words;
    box.querySelector('.pip-rec-next').hidden = recMini && !armed;
  }
  function syncRecorder() {
    const box = widgets.rec; if (!box) return;
    const on = !!(state?.active && state.widgets?.rec && state.ui !== false);
    if (on) {
      if (!recPoll) { recPoll = setInterval(recRefresh, 1000); recRefresh(); if (!recSettings) api().get('/api/pinelive/settings').then(got => { recSettings = got || null; }).catch(() => {}); }
      if (!recRaf) recRaf = root.requestAnimationFrame(recTick);
      paintRecorder();
    } else {
      clearInterval(recPoll); recPoll = 0; root.cancelAnimationFrame(recRaf); recRaf = 0;
      if (recLevels) { try { recLevels.close(); } catch (_) {} recLevels = null; recLevelsUrl = ''; }
      recClosePop();
    }
  }
  function recClosePop() { const pop = widgets.rec?.querySelector('.pip-rec-pop'); recPop = ''; if (pop) { pop.hidden = true; pop.replaceChildren(); } }
  function recOpenPop(kind, title, fill) {
    const pop = widgets.rec.querySelector('.pip-rec-pop');
    if (recPop === kind) { recClosePop(); return null; }
    recPop = kind; pop.replaceChildren(); pop.hidden = false;
    const head = node('header', '', title), x = node('button', 'pip-rec-pop-x'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close ' + title); musicIcon(x, 'c:close--filled');
    x.addEventListener('click', e => { e.stopPropagation(); recClosePop(); }); head.appendChild(x); pop.appendChild(head);
    fill(pop); return pop;
  }
  /* the wrench: the station's own ordered checks of the connected interface, with what to do */
  function recTroubleshoot() {
    recOpenPop('tools', 'The connected interface', pop => {
      const list = node('ol', 'pip-rec-checks'); list.appendChild(node('li', 'wait', 'Asking the station...')); pop.appendChild(list);
      const keys = node('div', 'pip-rec-keys'); pop.appendChild(keys);
      const key = (label, run) => { const b = node('button', '', label); b.type = 'button'; b.addEventListener('click', () => Promise.resolve().then(run).catch(err => say(err.message))); keys.appendChild(b); };
      key('Check again', () => recTroubleshoot() || recTroubleshoot());
      key('Rescan USB', () => api().get('/api/pinelive/devices?fresh=1').then(got => { say(((got?.usb || []).length) + ' USB interface(s) seen'); recRefresh(); }));
      key('Use USB', () => { recSettings = { ...(recSettings || {}), settings: { ...((recSettings || {}).settings || {}), road: 'usb' } }; say('The next recording opens the USB interface'); });
      key('Use network', () => { recSettings = { ...(recSettings || {}), settings: { ...((recSettings || {}).settings || {}), road: 'network' } }; say('The next recording takes the network sender'); });
      api().get('/api/pinelive/troubleshoot').then(got => {
        list.replaceChildren();
        for (const c of (got?.checks || [])) { const li = node('li', String(c.result || 'unknown')); li.append(node('b', '', c.label || ''), node('span', '', c.evidence || '')); if (c.fix) li.appendChild(node('small', '', c.fix)); list.appendChild(li); }
        if (got?.say) list.appendChild(node('li', 'say', got.say));
        if (!(got?.checks || []).length) list.appendChild(node('li', 'unknown', 'The station reported no checks.'));
      }).catch(err => { list.replaceChildren(node('li', 'fail', 'The troubleshoot road failed: ' + err.message)); });
    });
  }
  /* the art: recent renders from the gallery (H3 / ComfyUI) and the clips' own pictures, as the set's cover */
  function recArtPicker() {
    recOpenPop('art', 'The set\u2019s cover', pop => {
      const grid = node('div', 'pip-rec-grid'); grid.appendChild(node('small', 'pip-rec-note', 'Looking through the gallery and the clips...')); pop.appendChild(grid);
      const keys = node('div', 'pip-rec-keys'); const clear = node('button', '', 'Rolled covers again'); clear.type = 'button'; clear.addEventListener('click', () => recPost('/api/pinelive/cover', { clear: true }, 'The covers roll again.').then(recClosePop)); keys.appendChild(clear); pop.appendChild(keys);
      const tile = (label, src, body) => { const b = node('button', 'pip-rec-tile'); b.type = 'button'; b.title = label; const im = node('img'); im.alt = label; im.loading = 'lazy'; im.src = src; im.onerror = () => b.remove(); b.append(im, node('span', '', label)); b.addEventListener('click', () => recPost('/api/pinelive/cover', body, got => 'The cover is ' + (got?.cover?.name || label)).then(recClosePop)); return b; };
      Promise.all([api().get('/api/generations?limit=24').catch(() => null), api().get('/api/sfx/folders').catch(() => null)]).then(([gens, folders]) => {
        grid.replaceChildren();
        const base = root.pineStationBase?.() || '';
        let count = 0;
        for (const g of (gens?.generations || [])) {
          const files = Array.isArray(g.files) ? g.files : []; const file = files.find(f => /\.(png|jpe?g|webp|mp4|webm|mov)$/i.test(String(f))); if (!file) continue;
          const label = (g.kind === 'video' ? 'Render: ' : 'Image: ') + String(g.request || file).slice(0, 48);
          if (/\.(mp4|webm|mov)$/i.test(file)) { api().get('/api/generations/poster-url/' + encodeURIComponent(file)).then(p => { if (p?.poster) grid.appendChild(tile(label, base + p.poster, { generation: file })); }).catch(() => {}); }
          else grid.appendChild(tile(label, safeImage('/api/generations/image/' + encodeURIComponent(file)), { generation: file }));
          if (++count >= 24) break;
        }
        for (const f of (folders?.folders || [])) for (const s of (f.samples || [])) {
          if (!s.video || !s.id || !s.url) continue;
          const t = String(s.url).split('t=')[1] || '';
          grid.appendChild(tile('Clip: ' + (s.name || s.id) + ' (' + f.name + ')', base + '/api/sfx/poster/' + s.id + (t ? '?t=' + t : ''), { clip_id: s.id }));
          if (++count >= 60) break;
        }
        if (!grid.children.length) grid.appendChild(node('small', 'pip-rec-note', 'No finished renders or video clips to choose from yet.'));
      });
    });
  }
  function grip(widget, name, given) {
'''

PIPJS = [
    ("the recorder is a free widget with a home", PIP_FREE_OLD, PIP_FREE_NEW, "const DEFAULT_LAYOUT = { rec: { x: .3, y: .5 } };", 1),
    ("a default place; the recorder never docks", PIP_LAYOUTOF_OLD, PIP_LAYOUTOF_NEW, "(DEFAULT_LAYOUT[name] || null); }", 1),
    ("the dock loop leaves it be", PIP_DOCKLIST_OLD, PIP_DOCKLIST_NEW, "'messages', 'music', 'rec'].includes(name)", 1),
    ("a grip may be given its handle", PIP_GRIP_SIG_OLD, PIP_GRIP_SIG_NEW, "function grip(widget, name, given) {", 1),
    ("the recorder follows every state", PIP_SYNC_OLD, PIP_SYNC_NEW, "syncRecorder();   /* [pip-rec] */", 1),
    ("it is built with the rest", PIP_BUILD_OLD, PIP_BUILD_NEW, "buildRecorder();   /* [pip-rec] the album recorder, placed freely */", 1),
    ("the menu hears the folders", PIP_PLAYBACK_OLD, PIP_PLAYBACK_NEW, "folders:foldersCache.folders,pin:foldersCache.pin", 1),
    ("the folders are fetched", PIP_REFRESH_OLD, PIP_REFRESH_NEW, "function refreshFolders() {", 1),
    ("the Video folder action", PIP_ACTION_OLD, PIP_ACTION_NEW, "if (action?.type === 'video-folder') {", 1),
    ("the recorder itself", PIP_RECORDER_OLD, PIP_RECORDER_NEW, "function buildRecorder() {", 1),
]

# --------------------------------------------------------------------------- pine-pip.css (both copies)
CSS_CAMERA_OLD = r'''.pip-camera-status { position: absolute; inset: 0; display: grid; place-content: center; padding: 30px 12px 12px; text-align: center; }   /* [cam-words] the text starts below the title */
'''
CSS_CAMERA_NEW = r'''.pip-camera-status { position: absolute; left: 0; right: 0; top: 28px; bottom: 0; display: grid; place-content: center; padding: 4px 10px 8px; text-align: center; font-size: 11px; line-height: 1.3; overflow: hidden; }   /* [cam-words] the text lives below the title, never under it */
'''
CSS_NEW = r'''
/* [pip-rec] the album recorder */
#pinePipWidgets .pip-rec { position: absolute; z-index: 4; display: grid; grid-template-columns: 96px minmax(0, 1fr); grid-template-areas: "notch notch" "art main" "status status" "pop pop"; column-gap: 10px; row-gap: 4px; width: min(380px, calc(100vw - 8px)); padding: 6px 10px 8px; align-items: start; }
#pinePipWidgets .pip-rec .pip-rec-notch { grid-area: notch; justify-self: center; width: 56px; height: 8px; margin: 0 0 2px; padding: 0; border: 0; border-radius: 4px; background: color-mix(in srgb, var(--pip-text) 55%, transparent); cursor: grab; transition: transform .15s, background .15s; font-size: 0; }
#pinePipWidgets .pip-rec .pip-rec-notch:hover, #pinePipWidgets .pip-rec .pip-rec-notch:focus-visible { transform: scale(1.1); background: var(--pip-accent); }
#pinePipWidgets .pip-rec .pip-rec-art { grid-area: art; position: relative; width: 96px; height: 96px; border-radius: 8px; overflow: hidden; background: rgb(0 0 0 / .3); cursor: pointer; }
#pinePipWidgets .pip-rec .pip-rec-art img { width: 100%; height: 100%; object-fit: cover; display: block; filter: grayscale(1) brightness(.8); transition: filter .4s; }
#pinePipWidgets .pip-rec.recording .pip-rec-art img { filter: none; }
#pinePipWidgets .pip-rec .pip-rec-art::after { content: ""; position: absolute; inset: 0; background: linear-gradient(115deg, transparent 35%, rgb(255 255 255 / .55) 50%, transparent 65%); transform: translateX(-120%); pointer-events: none; }
#pinePipWidgets .pip-rec .pip-rec-art.sheen::after { animation: pip-rec-sheen .9s ease-out 1; }
@keyframes pip-rec-sheen { from { transform: translateX(-120%); } to { transform: translateX(120%); } }
#pinePipWidgets .pip-rec .pip-rec-blank { position: absolute; inset: 0; display: grid; place-items: center; color: var(--pip-accent); opacity: .7; }
#pinePipWidgets .pip-rec .pip-rec-blank svg { width: 40%; height: 40%; }
#pinePipWidgets .pip-rec .pip-rec-total { position: absolute; left: 0; right: 0; top: 0; padding: 2px 6px; font: 600 10px/1.3 system-ui, sans-serif; letter-spacing: .08em; background: rgb(0 0 0 / .55); color: #fff; font-variant-numeric: tabular-nums; }
#pinePipWidgets .pip-rec .pip-rec-main { grid-area: main; display: grid; grid-template-columns: 40px 1fr 34px 60px; grid-template-areas: "record bar next track" "meter readout readout track"; align-items: center; column-gap: 8px; row-gap: 6px; min-width: 0; }
#pinePipWidgets .pip-rec .pip-rec-record { grid-area: record; width: 40px; height: 40px; border-radius: 50%; border: 2px solid color-mix(in srgb, var(--pip-text) 70%, transparent); background: rgb(0 0 0 / .25); display: grid; place-items: center; cursor: pointer; padding: 0; }
#pinePipWidgets .pip-rec .pip-rec-record i { display: block; width: 18px; height: 18px; border-radius: 50%; background: #ff4b4b; transition: border-radius .2s, transform .2s; }
#pinePipWidgets .pip-rec.armed .pip-rec-record i { border-radius: 3px; transform: scale(.85); animation: pip-rec-blink 1.4s ease-in-out infinite; }
@keyframes pip-rec-blink { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
#pinePipWidgets .pip-rec .pip-rec-meter { grid-area: meter; width: 40px; height: 18px; justify-self: center; }
#pinePipWidgets .pip-rec .pip-rec-bar { grid-area: bar; position: relative; height: 16px; border-radius: 8px; border: 2px solid color-mix(in srgb, var(--pip-text) 60%, transparent); background: rgb(0 0 0 / .25); overflow: hidden; }
#pinePipWidgets .pip-rec .pip-rec-bar i { display: block; height: 100%; width: 0; background: var(--pip-accent); border-radius: 6px; transition: width .25s linear; }
#pinePipWidgets .pip-rec .pip-rec-bar .pip-rec-range { position: absolute; right: 6px; top: 0; font: 600 9px/12px system-ui, sans-serif; color: var(--pip-text); opacity: .8; }
#pinePipWidgets .pip-rec .pip-rec-next { grid-area: next; width: 34px; height: 34px; border-radius: 50%; border: 2px solid color-mix(in srgb, var(--pip-text) 70%, transparent); background: rgb(0 0 0 / .25); display: grid; place-items: center; cursor: pointer; padding: 0; color: var(--pip-text); }
#pinePipWidgets .pip-rec .pip-rec-next svg { width: 16px; height: 16px; }
#pinePipWidgets .pip-rec .pip-rec-next[hidden] { display: none; }
#pinePipWidgets .pip-rec .pip-rec-readout { grid-area: readout; display: flex; gap: 8px; align-items: center; min-width: 0; font: 600 12px/1.2 ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums; }
#pinePipWidgets .pip-rec .pip-rec-readout output { display: inline-flex; padding: 2px 6px; border: 1px solid color-mix(in srgb, var(--pip-text) 40%, transparent); border-radius: 4px; background: rgb(0 0 0 / .25); white-space: nowrap; }
#pinePipWidgets .pip-rec .pip-rec-size b { display: inline-block; font-weight: inherit; min-width: .5ch; }
#pinePipWidgets .pip-rec .pip-rec-size b.flip { animation: pip-rec-flip .32s ease-out 1; }
@keyframes pip-rec-flip { 0% { transform: translateY(-60%); opacity: 0; } 55% { transform: translateY(10%); opacity: 1; } 100% { transform: none; } }
#pinePipWidgets .pip-rec .pip-rec-track { grid-area: track; font: 700 70px/1 "Inter", "Segoe UI", system-ui, sans-serif; color: var(--pip-text); text-align: center; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
#pinePipWidgets .pip-rec .pip-rec-status { grid-area: status; display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 11px; opacity: .9; }
#pinePipWidgets .pip-rec .pip-rec-line { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#pinePipWidgets .pip-rec .pip-rec-tools { flex: none; width: 24px; height: 24px; border-radius: 50%; border: 1px solid color-mix(in srgb, var(--pip-text) 40%, transparent); background: rgb(0 0 0 / .25); color: var(--pip-text); display: grid; place-items: center; padding: 0; cursor: pointer; }
#pinePipWidgets .pip-rec .pip-rec-tools svg { width: 14px; height: 14px; }
#pinePipWidgets .pip-rec .pip-rec-pop { grid-area: pop; position: relative; padding: 6px 0 2px; border-top: 1px solid color-mix(in srgb, var(--pip-accent) 25%, transparent); max-height: 46vh; overflow: auto; }
#pinePipWidgets .pip-rec .pip-rec-pop[hidden] { display: none; }
#pinePipWidgets .pip-rec .pip-rec-pop header { font-weight: 600; font-size: 11px; padding-right: 22px; margin-bottom: 4px; color: var(--pip-accent); }
#pinePipWidgets .pip-rec .pip-rec-pop-x { position: absolute; top: 4px; right: 0; width: 18px; height: 18px; padding: 0; border: 0; background: none; color: inherit; display: grid; place-items: center; cursor: pointer; }
#pinePipWidgets .pip-rec .pip-rec-pop-x svg { width: 14px; height: 14px; }
#pinePipWidgets .pip-rec .pip-rec-checks { margin: 0; padding: 0; list-style: none; display: grid; gap: 3px; font-size: 11px; }
#pinePipWidgets .pip-rec .pip-rec-checks li { display: grid; grid-template-columns: 1fr; gap: 1px; padding: 3px 6px 3px 18px; position: relative; border-radius: 4px; background: rgb(0 0 0 / .18); }
#pinePipWidgets .pip-rec .pip-rec-checks li::before { content: ""; position: absolute; left: 6px; top: 7px; width: 7px; height: 7px; border-radius: 50%; background: #8a94a6; }
#pinePipWidgets .pip-rec .pip-rec-checks li.pass::before { background: #41d17a; } #pinePipWidgets .pip-rec .pip-rec-checks li.fail::before { background: #ff5a5a; } #pinePipWidgets .pip-rec .pip-rec-checks li.warn::before { background: #ffd166; }
#pinePipWidgets .pip-rec .pip-rec-checks li b { font-weight: 600; } #pinePipWidgets .pip-rec .pip-rec-checks li span { opacity: .8; } #pinePipWidgets .pip-rec .pip-rec-checks li small { color: var(--pip-accent); }
#pinePipWidgets .pip-rec .pip-rec-keys { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
#pinePipWidgets .pip-rec .pip-rec-keys button { padding: 3px 8px; border-radius: 5px; border: 1px solid color-mix(in srgb, var(--pip-accent) 30%, transparent); background: var(--pip-button); color: var(--pip-text); font: inherit; font-size: 11px; cursor: pointer; }
#pinePipWidgets .pip-rec .pip-rec-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 6px; }
#pinePipWidgets .pip-rec .pip-rec-tile { padding: 0; border: 1px solid transparent; border-radius: 6px; background: rgb(0 0 0 / .25); overflow: hidden; cursor: pointer; display: grid; color: var(--pip-text); }
#pinePipWidgets .pip-rec .pip-rec-tile:hover { border-color: var(--pip-accent); }
#pinePipWidgets .pip-rec .pip-rec-tile img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
#pinePipWidgets .pip-rec .pip-rec-tile span { font-size: 9px; padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#pinePipWidgets .pip-rec .pip-rec-note { font-size: 11px; opacity: .75; }
/* the mini form: art, record, next (while recording), the bar, time and size small, the notch */
#pinePipWidgets .pip-rec.mini { grid-template-columns: 112px; grid-template-areas: "notch" "art" "main" "pop"; width: 132px; }
#pinePipWidgets .pip-rec.mini .pip-rec-art { width: 112px; height: 112px; }
#pinePipWidgets .pip-rec.mini .pip-rec-status { display: none; }
#pinePipWidgets .pip-rec.mini .pip-rec-main { grid-template-columns: 34px 1fr 30px; grid-template-areas: "record bar next" "readout readout readout"; column-gap: 6px; row-gap: 4px; }
#pinePipWidgets .pip-rec.mini .pip-rec-record { width: 34px; height: 34px; } #pinePipWidgets .pip-rec.mini .pip-rec-record i { width: 14px; height: 14px; }
#pinePipWidgets .pip-rec.mini .pip-rec-next { width: 30px; height: 30px; }
#pinePipWidgets .pip-rec.mini .pip-rec-meter, #pinePipWidgets .pip-rec.mini .pip-rec-track { display: none; }
#pinePipWidgets .pip-rec.mini .pip-rec-readout { font-size: 10px; gap: 4px; } #pinePipWidgets .pip-rec.mini .pip-rec-readout output { padding: 1px 4px; }
#pinePipWidgets .pip-rec.mini .pip-rec-total { font-size: 9px; }
'''
CSS = [
    ("the camera's text lives below its title", CSS_CAMERA_OLD, CSS_CAMERA_NEW, "/* [cam-words] the text lives below the title, never under it */", 1),
    ("the recorder's styles", None, CSS_NEW, "/* [pip-rec] the album recorder */", 1),
]

EDITS = {
    "desktop/pip-window.cjs": WINDOW,
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
            if old is None:
                have = text.count(probe)
                state = "applied" if have == count else "ready" if not have else "missing (probe %d)" % have
                if state == "ready":
                    text = text.rstrip("\n") + "\n" + new
                    changed = True
            else:
                forms = [(old, new, probe)]
                if mode == "mixed":
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
        tmp = path.with_name(path.name + ".piprec.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
