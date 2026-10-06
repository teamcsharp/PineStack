#!/usr/bin/env python3
"""[pip-shift] [pip-music] [pip-update] Three changes to Pine PiP on the desk. 2026-10-05.

[pip-shift]   "I want the picture in picture transition process to be smoother
              ... Whenever it's changing it looks distorted and cropped when
              really I need all the elements to fade out and I need the system
              to be replaced with three JS particles that are flying in and
              swirling and representing the system changing."
              The window was resized BEFORE the page changed layout. The shell
              now tells the page first; the page fades out under a particle
              sheet (renderer/pine-pip-shift.js) and answers; only then does the
              window move, and the sheet lifts once the new layout is painted.

[pip-music]   "Allow me to be able to freely drag and reposition the music
              player in pip mode. have it look like the 2nd image but expanable
              to the third image."
              The docked strip is a mini player: artwork, transport, progress
              and time; drag it anywhere; one button opens it to the artwork
              view. Its place and size are PiP preferences. The strip's
              mis-encoded glyphs (a double-encoded file) are fixed with it.

[pip-update]  "If the Pineapp is out of date, then at the top of the right
              click menu, offer an option to update and rebuild."
              The shell's watcher already sees every file of the app change on
              the share; the menu now says so and offers the rebuild.

main.js, preload.js and pip-window.cjs are the running process: they take
effect at the app's next launch. The renderer files wait for a reload.
Both copies of pine-pip.js / pine-pip.css are patched; the tablet takes its
copy at its next kiosk build.

Usage:  pip_desk_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        pip_desk_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- pip-window.cjs
WIN_PREF_OLD = r'''    roulettePosition: Object.fromEntries(Object.entries({ x: .04, y: .18 }).map(([key, fallback]) => [key, Number.isFinite(value.roulettePosition?.[key]) ? Math.max(0, Math.min(1, value.roulettePosition[key])) : fallback])),
'''
WIN_PREF_NEW = WIN_PREF_OLD + r'''    /* [pip-music] where the mini player sits (its top-left, as a share of the window) and whether it is opened out */
    musicPosition: Object.fromEntries(Object.entries({ x: .03, y: .6 }).map(([key, fallback]) => [key, Number.isFinite(value.musicPosition?.[key]) ? Math.max(0, Math.min(1, value.musicPosition[key])) : fallback])),
    musicExpanded: value.musicExpanded === true,
'''

WIN_MERGE_OLD = r'''      roulettePosition: { ...old.roulettePosition, ...next?.roulettePosition },
'''
WIN_MERGE_NEW = WIN_MERGE_OLD + r'''      musicPosition: { ...old.musicPosition, ...next?.musicPosition },
'''

WIN_INSTALL_OLD = r'''function install({ ipcMain, getWindow, readConfig, writeConfig, troubleshoot, repairPlayback, openTools, isToolsSender, publishTools }) {
'''
WIN_INSTALL_NEW = r'''function install({ ipcMain, getWindow, readConfig, writeConfig, troubleshoot, repairPlayback, openTools, isToolsSender, publishTools, updateOwed, rebuild }) {
'''

WIN_ENTER_OLD = r'''  function enter() {
    const w = getWindow();
    if (!w || w.isDestroyed() || w.__pinePip) return state();
    full = {'''
WIN_ENTER_NEW = r'''  /* [pip-shift] THE PAGE COVERS ITSELF BEFORE THE WINDOW CHANGES SHAPE.
   *
   * "Whenever it's changing it looks distorted and cropped." The window was
   * resized first and the page was told afterwards, so for a moment the whole
   * app sat squeezed in the small window. Now the page is told first
   * ('pip:shift'), fades everything out under its particle sheet, and answers
   * ('pip:shift-covered'); only then does the window move. Both waits are
   * bounded - a page that is loading, reloading or gone must never be able to
   * hold the window where it is. A window nobody can see changes at once. */
  let shifting = null, shiftSeq = 0;
  const SHIFT_HEARD_MS = 220, SHIFT_COVER_MS = 1500;
  function coverable(w) { try { return !!ipcMain.on && w.isVisible() && !w.isMinimized(); } catch (_) { return false; } }
  function askCover(w, to, target) {
    return new Promise(resolve => {
      let from = null;
      try { from = w.getContentBounds(); } catch (_) { resolve(false); return; }
      const id = ++shiftSeq;
      let settled = false, heardTimer = null, coverTimer = null;
      const done = ok => {
        if (settled) return;
        settled = true; clearTimeout(heardTimer); clearTimeout(coverTimer);
        ipcMain.removeListener('pip:shift-heard', heard); ipcMain.removeListener('pip:shift-covered', covered);
        resolve(ok);
      };
      const mine = (event, got) => event.sender === w.webContents && got === id;
      const heard = (event, got) => { if (mine(event, got)) clearTimeout(heardTimer); };
      const covered = (event, got) => { if (mine(event, got)) done(true); };
      ipcMain.on('pip:shift-heard', heard); ipcMain.on('pip:shift-covered', covered);
      heardTimer = setTimeout(() => done(false), SHIFT_HEARD_MS);   // no page is listening: change now
      coverTimer = setTimeout(() => done(false), SHIFT_COVER_MS);   // it heard and never covered: change anyway
      try { w.webContents.send('pip:shift', { id, to, from, target }); } catch (_) { done(false); }
    });
  }
  function plannedPip(w) {
    const b = w.getBounds(), c = w.getContentBounds(), saved = readConfig().pip?.bounds;
    const display = saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)
      ? screen.getDisplayNearestPoint({ x: saved.x, y: saved.y }) : screen.getDisplayMatching(b);
    return fitBounds(saved, display.workArea, [b.width - c.width, b.height - c.height]);
  }
  function plannedFull() {
    if (!full) return null;
    const display = screen.getDisplayMatching(full.bounds);
    return full.fullscreen ? display.bounds : full.maximized ? display.workArea : full.bounds;
  }
  function shift(to, change) {
    if (shifting) return shifting;                 // one change at a time: a second press joins the first
    const w = getWindow();
    if (!coverable(w)) return change();
    shifting = (async () => {
      let target = null;
      try { target = to === 'pip' ? plannedPip(w) : plannedFull(); } catch (_) {}
      await askCover(w, to, target);
      if (!w.isDestroyed()) change();
      return state();
    })().catch(error => { if (typeof console !== 'undefined') console.error('[pip shift] ' + error.message); return state(); })
      .finally(() => { shifting = null; });
    return shifting;
  }
  function enter() {
    const w = getWindow();
    if (!w || w.isDestroyed() || w.__pinePip) return state();
    return shift('pip', enterNow);
  }
  function enterNow() {
    const w = getWindow();
    if (!w || w.isDestroyed() || w.__pinePip) return state();
    full = {'''

WIN_EXIT_OLD = r'''  function exit() {
    const w = getWindow();
    if (!w?.__pinePip) return state();
    clearTimeout(timer); saveBounds();
'''
WIN_EXIT_NEW = r'''  function exit() {
    const w = getWindow();
    if (!w?.__pinePip) return state();
    return shift('app', exitNow);
  }
  function exitNow() {
    const w = getWindow();
    if (!w?.__pinePip) return state();
    clearTimeout(timer); saveBounds();
'''

WIN_MENU_OLD = r'''    activeMenu = Menu.buildFromTemplate([
      { label: 'Resolve playback + restore DJs','''
WIN_MENU_NEW = r'''    /* [pip-update] "If the Pineapp is out of date, then at the top of the right
       click menu, offer an option to update and rebuild." The shell knows: its
       watcher sees every file of this app change on the share, and the build
       stamp compares the running tree with the source. */
    let owed = null;
    try { owed = updateOwed ? updateOwed() : null; } catch (_) { owed = null; }
    const owedCount = owed ? new Set([...(owed.relaunch || []), ...(owed.reload || [])]).size : 0;
    const updateItems = owed?.owed && rebuild ? [
      { label: 'Update and rebuild Pine' + (owedCount ? ' (' + owedCount + ' newer file' + (owedCount === 1 ? '' : 's') + ')' : ' (this app is older than its source)'),
        click: () => { Promise.resolve().then(rebuild).catch(error => { if (typeof console !== 'undefined') console.error('[pip update] ' + error.message); }); } },
      { type: 'separator' }
    ] : [];
    activeMenu = Menu.buildFromTemplate([
      ...updateItems,
      { label: 'Resolve playback + restore DJs','''

WINDOW = [
    ("the player's place is a preference", WIN_PREF_OLD, WIN_PREF_NEW, "musicExpanded: value.musicExpanded === true,", 1),
    ("an update keeps the player's place", WIN_MERGE_OLD, WIN_MERGE_NEW, "musicPosition: { ...old.musicPosition, ...next?.musicPosition },", 1),
    ("the shell hands in what is owed", WIN_INSTALL_OLD, WIN_INSTALL_NEW, "publishTools, updateOwed, rebuild })", 1),
    ("entering waits for the cover", WIN_ENTER_OLD, WIN_ENTER_NEW, "return shift('pip', enterNow);", 1),
    ("leaving waits for the cover", WIN_EXIT_OLD, WIN_EXIT_NEW, "return shift('app', exitNow);", 1),
    ("the menu offers the rebuild first", WIN_MENU_OLD, WIN_MENU_NEW, "      ...updateItems,\n", 1),
]

# --------------------------------------------------------------------------- preload.js
PRE_OLD = r'''  pipMenu: (playback) => ipcRenderer.invoke('pip:menu', playback),
'''
PRE_NEW = PRE_OLD + r'''  /* [pip-shift] the shell says the window is about to change; the page covers itself and answers */
  onPipShift: (callback) => ipcRenderer.on('pip:shift', (_event, value) => callback(value)),
  pipShiftHeard: (id) => ipcRenderer.send('pip:shift-heard', id),
  pipShiftCovered: (id) => ipcRenderer.send('pip:shift-covered', id),
'''
PRELOAD = [
    ("the page can hear and answer", PRE_OLD, PRE_NEW, "pipShiftCovered: (id) => ipcRenderer.send('pip:shift-covered', id),", 1),
]

# --------------------------------------------------------------------------- main.js
MAIN_SET_OLD = r'''const hotPending = new Set();   /* copied JS/HTML waiting for explicit reload */
'''
MAIN_SET_NEW = MAIN_SET_OLD + r'''/* [pip-update] IS THIS APP OLDER THAN ITS SOURCE?
 *
 * "If the Pineapp is out of date, then at the top of the right click menu,
 *  offer an option to update and rebuild."
 *
 * Three things already know. The watcher copies renderer files and holds them
 * for an explicit reload (hotPending). It also sees this process's own files
 * change - main.js, preload.js, the .cjs modules - and until now only wrote a
 * line in the log about it (hotOwed keeps the names). And the build stamp
 * compares the whole running tree with the share whenever it is asked. The
 * PiP menu asks pineUpdateOwed(); it adds nothing of its own. */
const hotOwed = new Set();      /* this process's own files that changed: a relaunch is owed */
let desktopBuildLast = null;    /* the last answer of desktop:build */
function pineUpdateOwed() {
  const relaunch = Array.from(hotOwed), reload = Array.from(hotPending);
  const stale = !!(desktopBuildLast && desktopBuildLast.stale);
  return { owed: relaunch.length > 0 || reload.length > 0 || stale, relaunch, reload, stale };
}
'''

MAIN_SELF_OLD = r'''          if (hotSelf.has(key) && hotSelf.get(key) !== stamp) hotSayRelaunch(name);
'''
MAIN_SELF_NEW = r'''          if (hotSelf.has(key) && hotSelf.get(key) !== stamp) { hotOwed.add(name); hotSayRelaunch(name); }  /* [pip-update] */
'''

MAIN_BUILD_OLD = r'''  })().finally(()=>{desktopBuildInFlight=null;});return desktopBuildInFlight;
'''
MAIN_BUILD_NEW = r'''  })().then(got=>{desktopBuildLast=got;return got;}).finally(()=>{desktopBuildInFlight=null;});return desktopBuildInFlight;  /* [pip-update] */
'''

MAIN_INSTALL_OLD = r'''  ipcMain, getWindow: () => win, readConfig, writeConfig, troubleshoot: () => stationTroubleshooter.open()
});
let backend = null;
'''
MAIN_INSTALL_NEW = r'''  ipcMain, getWindow: () => win, readConfig, writeConfig, troubleshoot: () => stationTroubleshooter.open(),
  /* [pip-update] what this app owes itself, and the rebuild that settles it */
  updateOwed: () => pineUpdateOwed(), rebuild: () => reconstituteDesktop()
});
let backend = null;
'''
MAIN = [
    ("what the app owes itself", MAIN_SET_OLD, MAIN_SET_NEW, "function pineUpdateOwed() {", 1),
    ("a changed shell file is remembered", MAIN_SELF_OLD, MAIN_SELF_NEW, "{ hotOwed.add(name); hotSayRelaunch(name); }", 1),
    ("the build stamp is remembered", MAIN_BUILD_OLD, MAIN_BUILD_NEW, ".then(got=>{desktopBuildLast=got;return got;})", 1),
    ("the PiP menu is handed both", MAIN_INSTALL_OLD, MAIN_INSTALL_NEW, "updateOwed: () => pineUpdateOwed(), rebuild: () => reconstituteDesktop()", 1),
]

# --------------------------------------------------------------------------- index.html
HTML_OLD = r'''  <script src="./pine-pip.js"></script>
'''
HTML_NEW = r'''  <script src="./pine-pip-shift.js"></script>  <!-- [pip-shift] the change between the app and PiP, as one move -->
''' + HTML_OLD
HTML = [
    ("the sheet is loaded before PiP", HTML_OLD, HTML_NEW, '<script src="./pine-pip-shift.js"></script>', 1),
]

# --------------------------------------------------------------------------- pine-pip.js
JS_SHARED_OLD = r''''theme','transparency','widgets','docks','order','voiceStyles']) out[key] = value[key];'''
JS_SHARED_NEW = r''''theme','transparency','widgets','docks','order','voiceStyles','musicPosition','musicExpanded']) out[key] = value[key];'''

JS_STRIP_OLD = r'''    const music = node('div', 'pip-widget'); widgets.music = music; grip(music, 'music');
    const art = node('img', 'pip-music-art'); art.alt = 'Album art'; art.hidden = true;
    const info = node('div', 'pip-music-info'); info.append(node('b', '', 'No track playing'), node('small'));
    music.append(art, info);
    const action = (label, title, run) => { const b = node('button', '', label); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title); b.onclick = () => Promise.resolve().then(run).catch(e => say(e.message)); music.appendChild(b); return b; };
    action('\u25b6/\u2161', 'Play / pause this device\u2019s broadcast', () => {
      const button = document.getElementById('boothMonitor') || document.getElementById('pvHear');
      if (button) button.click();
      else { const player = document.getElementById('desktopRadioPlayer'); if (!player) throw new Error('Broadcast player unavailable'); return player.paused ? player.play() : player.pause(); }
    });
    action('\u25b2', 'Play this track more', () => vote(1)); action('\u25bc', 'Never play this track again', () => vote(-1));
    overlay.querySelector('.pip-dock-top').appendChild(music);
'''
JS_STRIP_NEW = r'''    buildMusic();   /* [pip-music] a mini player placed freely, not a strip in the top dock */
'''

JS_BUILD_OLD = r'''  function build() {
    overlay = node('div'); overlay.id = 'pinePipWidgets';
'''
JS_BUILD_NEW = r'''  /* [pip-music] THE MUSIC PLAYER IS A MINI PLAYER, PLACED FREELY.
   *
   * "Allow me to be able to freely drag and reposition the music player in pip
   *  mode. have it look like the 2nd image but expanable to the third image."
   *
   * It was a strip pinned in the top dock. It is now its own small player:
   * artwork, transport, a progress bar and the time. Drag it anywhere by any
   * part that is not a control (or focus it and use the arrow keys); the
   * corner button opens it out to the artwork view - title, artist, the large
   * cover, the votes - and folds it back. Where it sits and which size it is
   * are PiP preferences like the slate's place, so they survive a relaunch.
   * A shell that does not know those two preferences yet (one launched before
   * this change) drops them; the player then remembers them until a reload. */
  let musicDrag = null, musicSpot = null, musicBig = false, musicTimer = 0, musicClock = null, musicPop = '';
  function musicTime(seconds) { const s = Math.max(0, Math.round(Number(seconds) || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function musicExpanded() { return typeof state?.musicExpanded === 'boolean' ? state.musicExpanded : musicBig; }
  function musicIcon(button, ref) {
    if (!button || button.dataset.icon === ref) return;
    button.dataset.icon = ref;
    if (typeof root.pineIcon === 'function') button.innerHTML = root.pineIcon(ref); else button.textContent = ref.replace(/^.*:/, '').slice(0, 2);
  }
  function musicButton(host, cls, ref, title, run) {
    const b = node('button', cls); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title); musicIcon(b, ref);
    b.addEventListener('click', e => { e.stopPropagation(); Promise.resolve().then(run).catch(err => say(err.message)); });
    host.appendChild(b); return b;
  }
  function placeMusic(position) {
    const box = widgets.music; if (!box || (musicDrag && !position)) return;
    const p = position || state?.musicPosition || musicSpot || { x: .03, y: .6 };
    box.style.left = Math.max(0, Math.min(innerWidth - box.offsetWidth, p.x * innerWidth)) + 'px';
    box.style.top = Math.max(0, Math.min(innerHeight - box.offsetHeight, p.y * innerHeight)) + 'px';
  }
  function syncMusic() {
    const box = widgets.music; if (!box) return;
    const big = musicExpanded(); box.classList.toggle('expanded', big);
    const title = big ? 'Fold back to the mini player' : 'Open out to the artwork view', sizer = box.querySelector('.pip-music-size');
    sizer.title = title; sizer.setAttribute('aria-label', title); sizer.setAttribute('aria-expanded', String(big));
    placeMusic();
  }
  function closeMusicPop() {
    const pop = widgets.music?.querySelector('.pip-music-pop'); musicPop = '';
    if (pop) { pop.hidden = true; pop.replaceChildren(); }
    placeMusic();
  }
  function openMusicPop(kind, title, fill) {
    const pop = widgets.music.querySelector('.pip-music-pop');
    if (musicPop === kind) { closeMusicPop(); return null; }
    musicPop = kind; pop.replaceChildren(); pop.hidden = false;
    const head = node('header', '', title), x = node('button', 'pip-music-pop-x'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close ' + title); musicIcon(x, 'c:close--filled');
    x.addEventListener('click', e => { e.stopPropagation(); closeMusicPop(); }); head.appendChild(x); pop.appendChild(head);
    fill(pop); placeMusic(); return pop;
  }
  function paintMusicList() {
    const pop = widgets.music?.querySelector('.pip-music-pop'); if (!pop || musicPop !== 'next') return;
    pop.querySelectorAll('ol, small').forEach(n => n.remove());
    const rows = (Array.isArray(station?.upcoming) ? station.upcoming : []).slice(0, 5);
    if (!rows.length) { pop.appendChild(node('small', '', 'Nothing is lined up yet.')); placeMusic(); return; }
    const list = node('ol');
    for (const row of rows) { const item = node('li'); item.append(node('b', '', row.title || 'Untitled'), node('span', '', [row.artist, row.seconds ? musicTime(row.seconds) : ''].filter(Boolean).join(' \u00b7 '))); list.appendChild(item); }
    pop.appendChild(list); placeMusic();   /* the list made the player taller: keep it inside the window */
  }
  function musicVolume() {
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
  function musicFind() {
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
  function musicTick() {
    const box = widgets.music;
    if (!box || !state?.active || state.ui === false || !state.widgets.music) { clearInterval(musicTimer); musicTimer = 0; return; }
    const c = musicClock; if (!c) return;
    const at = Math.max(0, Math.min(c.total || Infinity, c.at + (c.running ? (root.performance.now() - c.stamp) / 1000 : 0)));
    box.querySelector('.pip-music-bar i').style.width = (c.total ? Math.min(100, at / c.total * 100) : 0).toFixed(2) + '%';
    box.querySelector('.pip-music-at').textContent = musicTime(at);
    box.querySelector('.pip-music-left').textContent = c.total ? '-' + musicTime(c.total - at) : '';
  }
  function paintMusic() {
    const box = widgets.music; if (!box) return;
    box.querySelector('.pip-music-info b').textContent = track?.title || 'No track playing';
    box.querySelector('.pip-music-info small').textContent = [station?.paused ? 'Paused' : station?.playing ? 'Playing' : 'Ready', track?.artist, track?.album].filter(Boolean).join(' \u00b7 ');
    const art = box.querySelector('.pip-music-art'), blank = box.querySelector('.pip-music-blank'), src = track?.art ? root.desktopMusicUrl(track.art) : '';
    art.hidden = !src; blank.hidden = !!src; if (src && art.getAttribute('src') !== src) art.src = src;
    box.title = (track?.title ? [track.title, track.artist].filter(Boolean).join(' \u00b7 ') + ' \u2014 ' : '') + 'drag to move the player';
    const playing = !!station?.playing && !station?.paused;
    musicIcon(box.querySelector('.pip-music-play'), playing ? 'c:pause--filled' : 'c:play--filled--alt');
    const total = Number(track?.seconds) || 0, elapsed = Number(station?.elapsed), remaining = Number(station?.remaining);
    const at = Number.isFinite(elapsed) ? elapsed : total && Number.isFinite(remaining) ? total - remaining : 0;
    musicClock = { at, total: total || (Number.isFinite(remaining) ? at + remaining : 0), stamp: root.performance.now(), running: playing };
    musicTick();
    if (!musicTimer) musicTimer = setInterval(musicTick, 500);
    paintMusicList();
  }
  function buildMusic() {
    const box = node('section', 'pip-widget pip-music'); widgets.music = box; box.tabIndex = 0;
    box.setAttribute('aria-label', 'Music player'); box.title = 'drag to move the player';
    const side = node('div', 'pip-music-side');
    musicButton(side, 'pip-music-x', 'c:close--filled', 'Hide the music player', () => api().pipUpdate({ widgets: { music: false } }).then(apply));
    musicButton(side, 'pip-music-size', 'c:maximize', 'Open out to the artwork view', () => { musicBig = !musicExpanded(); return api().pipUpdate({ musicExpanded: musicBig }).then(apply); });
    const art = node('img', 'pip-music-art'); art.alt = 'Album art'; art.hidden = true; art.draggable = false;
    const blank = node('div', 'pip-music-blank'); if (typeof root.pineIcon === 'function') blank.innerHTML = root.pineIcon('c:music');
    const info = node('div', 'pip-music-info'); info.append(node('b', '', 'No track playing'), node('small'));
    const keys = node('div', 'pip-music-keys');
    const turn = (route, said) => () => api().post(route, {}).then(() => { say(said); root.PineStationFeed?.refresh?.(); });
    musicButton(keys, 'pip-music-queue', 'c:caret--right', 'Up next', () => { if (openMusicPop('next', 'Up next', () => {})) paintMusicList(); });
    musicButton(keys, 'pip-music-back', 'm:fast_rewind', 'Back to the last record', turn('/api/dj/prev', 'Back to the last record'));
    musicButton(keys, 'pip-music-play', 'c:play--filled--alt', 'Play / pause this device\u2019s broadcast', () => {
      const button = document.getElementById('boothMonitor') || document.getElementById('pvHear');
      if (button) button.click();
      else { const player = document.getElementById('desktopRadioPlayer'); if (!player) throw new Error('Broadcast player unavailable'); return player.paused ? player.play() : player.pause(); }
    });
    musicButton(keys, 'pip-music-skip', 'm:fast_forward', 'Skip to the next record', turn('/api/dj/next', 'Skipped to the next record'));
    musicButton(keys, 'pip-music-up', 'c:thumbs-up', 'Play this track more', () => vote(1));
    musicButton(keys, 'pip-music-down', 'c:thumbs-down', 'Never play this track again', () => vote(-1));
    musicButton(keys, 'pip-music-vol', 'c:volume--up--filled', 'Volume', musicVolume);
    musicButton(keys, 'pip-music-find', 'c:search', 'Ask for a record', musicFind);
    const seek = node('div', 'pip-music-seek'), bar = node('div', 'pip-music-bar'); bar.appendChild(node('i'));
    seek.append(node('output', 'pip-music-at', '0:00'), bar, node('output', 'pip-music-left'));
    const pop = node('div', 'pip-music-pop'); pop.hidden = true;
    box.append(side, art, blank, info, keys, seek, pop);
    overlay.appendChild(box);
    const save = () => { musicSpot = { x: box.offsetLeft / innerWidth, y: box.offsetTop / innerHeight }; api().pipUpdate({ musicPosition: musicSpot }).catch(e => say(e.message)); };
    box.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('button, input, .pip-music-pop')) return;
      box.setPointerCapture(e.pointerId);
      musicDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: box.offsetLeft, top: box.offsetTop, moved: false };
    });
    box.addEventListener('pointermove', e => {
      const d = musicDrag; if (!d || d.id !== e.pointerId) return;
      if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 3) return;
      d.moved = true; box.classList.add('dragging');
      placeMusic({ x: (d.left + e.clientX - d.x) / innerWidth, y: (d.top + e.clientY - d.y) / innerHeight });
    });
    const drop = e => {
      const d = musicDrag; if (!d || d.id !== e.pointerId) return;
      musicDrag = null; box.classList.remove('dragging');
      if (box.hasPointerCapture(e.pointerId)) box.releasePointerCapture(e.pointerId);
      if (d.moved) save();
    };
    box.addEventListener('pointerup', drop); box.addEventListener('pointercancel', drop);
    box.addEventListener('keydown', e => {
      if (e.key === 'Escape' && musicPop) { e.stopPropagation(); closeMusicPop(); box.focus(); return; }
      const delta = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] }[e.key];
      if (e.target !== box || !delta || e.ctrlKey || e.altKey) return;
      e.preventDefault(); placeMusic({ x: (box.offsetLeft + delta[0]) / innerWidth, y: (box.offsetTop + delta[1]) / innerHeight }); save();
    });
    root.addEventListener('resize', () => placeMusic());
  }
''' + JS_BUILD_OLD

JS_DBL_OLD = r'''.pip-camera, .pip-messages')) api().pipExit().catch(err => say(err.message)); });'''
JS_DBL_NEW = r'''.pip-camera, .pip-messages, .pip-music')) expand(); });'''

JS_DOCK_OLD = r'''      if (!['chat', 'voices', 'roulette', 'messages'].includes(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);'''
JS_DOCK_NEW = r'''      if (!['chat', 'voices', 'roulette', 'messages', 'music'].includes(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);'''

JS_PLACE_OLD = r'''    placeSlate(); syncMessages(); syncMessageTileSettings();
'''
JS_PLACE_NEW = r'''    placeSlate(); syncMusic(); syncMessages(); syncMessageTileSettings();
'''

JS_PAINT_OLD = r'''    const music = widgets.music; music.querySelector('b').textContent = track?.title || 'No track playing';
    music.querySelector('small').textContent = [station.paused ? 'Paused' : station.playing ? '\u266b Playing' : 'Ready', track?.artist, track?.album,
      Number(station.remaining) > 0 ? Math.ceil(station.remaining) + 's left' : ''].filter(Boolean).join(' \u00b7 ');
    const art = music.querySelector('img'); const src = track?.art ? root.desktopMusicUrl(track.art) : '';
    art.hidden = !src; if (src && art.getAttribute('src') !== src) art.src = src;
'''
JS_PAINT_NEW = r'''    paintMusic();
'''

JS_ENTER_OLD = r'''    syncPanel().catch(e => say('PiP video display: ' + e.message));
  }
  async function enter() {
    if (entering) return;
    entering = true;
    try { if (api().replayHold) await api().replayHold(3600); apply(await api().pipEnter()); } catch (e) { say(e.message); } finally { entering = false; }
  }
'''
JS_ENTER_NEW = r'''    const synced = syncPanel().catch(e => say('PiP video display: ' + e.message));
    /* [pip-shift] The mode changed: the sheet stays down until this layout is
       painted, then lifts. If nobody covered the page first (a shell from
       before this change moves the window without a word) it covers now. */
    if (was !== undefined && !!was !== !!next.active) root.PinePipShift?.landed(next.active ? 'pip' : 'app', synced);
  }
  /* [pip-shift] ONE ROAD INTO AND OUT OF PIP for every button and gesture.
     A shell that announces the change (onPipShift) has the page cover itself
     before it moves the window. An older shell moves the window at once, so
     here the page covers first and only then asks. */
  async function shiftTo(to) {
    const sheet = root.PinePipShift, led = !!sheet && !api().onPipShift, before = !!state?.active;
    try {
      if (led && before !== (to === 'pip')) await sheet.begin(to);
      apply(await (to === 'pip' ? api().pipEnter() : api().pipExit()));
    } finally { if (led && !!state?.active === before) sheet.reveal(); }   /* nothing changed: uncover */
  }
  function expand() { return shiftTo('app').catch(e => say(e.message)); }
  async function enter() {
    if (entering) return;
    entering = true;
    try { if (api().replayHold) await api().replayHold(3600); await shiftTo('pip'); } catch (e) { say(e.message); } finally { entering = false; }
  }
'''

JS_ARGS_OLD = r'''      if (e.args[0] === 'expand') api().pipExit().catch(err => say(err.message));'''
JS_ARGS_NEW = r'''      if (e.args[0] === 'expand') expand();'''
JS_DATA_OLD = r'''        if (e.data.action === 'expand') api().pipExit().catch(err => say(err.message));'''
JS_DATA_NEW = r'''        if (e.data.action === 'expand') expand();'''
JS_KEY_OLD = r'''state?.active ? api().pipExit().catch(err => say(err.message)) : enter(); } });'''
JS_KEY_NEW = r'''state?.active ? expand() : enter(); } });'''
JS_API_OLD = r'''    root.PinePip = { enter, exit: () => api().pipExit(), state: () => state,'''
JS_API_NEW = r'''    root.PinePip = { enter, exit: () => shiftTo('app'), state: () => state,'''

JS_HEAR_OLD = r'''    api().onPipState(apply); api().pipState().then(apply).catch(e => say(e.message));
'''
JS_HEAR_NEW = r'''    /* [pip-shift] The shell is about to change the window: cover first, then say so. */
    api().onPipShift?.(note => {
      const sheet = root.PinePipShift, id = note?.id;
      api().pipShiftHeard?.(id);
      if (!sheet) { api().pipShiftCovered?.(id); return; }
      sheet.begin(note?.to, { from: note?.from, target: note?.target }).then(() => api().pipShiftCovered?.(id));
    });
''' + JS_HEAR_OLD

PIPJS = [
    ("the player's place is shared", JS_SHARED_OLD, JS_SHARED_NEW, "'voiceStyles','musicPosition','musicExpanded']", 1),
    ("the strip gives way to the player", JS_STRIP_OLD, JS_STRIP_NEW, "    buildMusic();   /* [pip-music]", 1),
    ("the mini player", JS_BUILD_OLD, JS_BUILD_NEW, "  function buildMusic() {", 1),
    ("a double click on the player stays", JS_DBL_OLD, JS_DBL_NEW, ".pip-messages, .pip-music')) expand(); });", 1),
    ("the player is not docked", JS_DOCK_OLD, JS_DOCK_NEW, "'messages', 'music'].includes(name)", 1),
    ("the player is placed with the layout", JS_PLACE_OLD, JS_PLACE_NEW, "placeSlate(); syncMusic(); syncMessages();", 1),
    ("the feed paints the player", JS_PAINT_OLD, JS_PAINT_NEW, "    paintMusic();\n", 1),
    ("the sheet lifts on the new layout", JS_ENTER_OLD, JS_ENTER_NEW, "  async function shiftTo(to) {", 1),
    ("the panel's gesture takes the road", JS_ARGS_OLD, JS_ARGS_NEW, "if (e.args[0] === 'expand') expand();", 1),
    ("the page's gesture takes the road", JS_DATA_OLD, JS_DATA_NEW, "if (e.data.action === 'expand') expand();", 1),
    ("the key takes the road", JS_KEY_OLD, JS_KEY_NEW, "state?.active ? expand() : enter(); } });", 1),
    ("PinePip.exit takes the road", JS_API_OLD, JS_API_NEW, "exit: () => shiftTo('app'), state: () => state,", 1),
    ("the page hears the shell", JS_HEAR_OLD, JS_HEAR_NEW, "    api().onPipShift?.(note => {", 1),
]

# --------------------------------------------------------------------------- pine-pip.css
CSS_NEW = r'''
/* [pip-shift] One sheet over the whole window while the mode changes: the old
   view fades out under it, the particles swirl on it, the new view fades in. */
#pinePipShift { position: fixed; inset: 0; z-index: 2147483647; background: var(--pip-shift-surface, rgb(8 23 19)); opacity: 0; pointer-events: auto; -webkit-app-region: no-drag; transition: opacity var(--pip-shift-in, 240ms) ease-out; }
#pinePipShift[hidden] { display: none !important; }
#pinePipShift.on { opacity: 1; }
#pinePipShift.instant { transition: none; }
#pinePipShift.leaving { opacity: 0; pointer-events: none; transition: opacity var(--pip-shift-out, 420ms) ease-in; }
#pinePipShift > canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
#pinePipShift > .pip-shift-logo { position: absolute; left: 0; top: 0; width: 64px; height: 64px; opacity: 0; pointer-events: none; user-select: none; -webkit-user-drag: none; will-change: transform, opacity; filter: drop-shadow(0 0 22px color-mix(in srgb, var(--pip-accent, #98e9ae) 45%, transparent)); }
#pinePipShift > .pip-shift-logo[hidden] { display: none; }

/* [pip-music] The music player is a mini player placed freely: artwork,
   transport, progress and time; it opens out to the artwork view. Every rule
   is under .pip-music so a page still running the old strip is untouched. */
.pip-music { position: absolute; z-index: 5; box-sizing: border-box; display: grid; grid-template-columns: auto auto minmax(0, 1fr); grid-template-areas: "side art keys" "side art seek" "pop pop pop"; align-items: center; column-gap: 8px; row-gap: 3px; width: min(336px, calc(100vw - 8px)); padding: 6px 10px 6px 5px; border-radius: 9px; cursor: grab; touch-action: none; user-select: none; box-shadow: 0 10px 28px rgb(0 0 0 / .45); }
.pip-music.dragging { cursor: grabbing; opacity: var(--pip-opacity); outline: 1px solid var(--pip-accent); }
.pip-music:focus-visible { outline: 1px solid var(--pip-accent); }
.pip-music .pip-music-side { grid-area: side; display: flex; flex-direction: column; gap: 4px; align-self: start; padding-top: 2px; }
.pip-music .pip-music-side button { width: 15px; height: 15px; padding: 0; border: 0; background: none; display: grid; place-items: center; opacity: .7; cursor: pointer; }
.pip-music .pip-music-side button:hover, .pip-music .pip-music-side button:focus-visible { opacity: 1; color: var(--pip-accent); }
.pip-music .pip-music-side svg { width: 13px; height: 13px; }
.pip-music .pip-music-art, .pip-music .pip-music-blank { grid-area: art; width: 46px; height: 46px; border-radius: 4px; box-sizing: border-box; }
.pip-music .pip-music-art { object-fit: cover; -webkit-user-drag: none; }
.pip-music .pip-music-blank { display: grid; place-items: center; background: var(--pip-button, #17382c); color: var(--pip-accent); }
.pip-music .pip-music-blank svg { width: 22px; height: 22px; }
.pip-music .pip-music-art[hidden], .pip-music .pip-music-blank[hidden], .pip-music .pip-music-pop[hidden] { display: none; }
.pip-music .pip-music-info { display: none; min-width: 0; overflow: hidden; }
.pip-music .pip-music-keys { grid-area: keys; display: flex; align-items: center; justify-content: space-between; gap: 2px; min-width: 0; }
.pip-music .pip-music-keys button { flex: 0 0 auto; width: 30px; height: 26px; padding: 0; border: 0; border-radius: 5px; background: none; display: grid; place-items: center; cursor: pointer; }
.pip-music .pip-music-keys button:hover, .pip-music .pip-music-keys button:focus-visible { background: color-mix(in srgb, var(--pip-accent) 18%, transparent); }
.pip-music .pip-music-keys svg { width: 19px; height: 19px; }
.pip-music .pip-music-keys .pip-music-play svg { width: 26px; height: 26px; }
.pip-music .pip-music-keys .pip-music-up, .pip-music .pip-music-keys .pip-music-down { display: none; }
.pip-music .pip-music-seek { grid-area: seek; display: flex; align-items: center; gap: 8px; min-width: 0; font: 11px/1 system-ui, sans-serif; font-variant-numeric: tabular-nums; }
.pip-music .pip-music-bar { flex: 1; min-width: 0; height: 4px; border-radius: 2px; overflow: hidden; background: color-mix(in srgb, var(--pip-text, #e1f8ea) 22%, transparent); }
.pip-music .pip-music-bar i { display: block; height: 100%; width: 0; border-radius: 2px; background: var(--pip-accent); transition: width .45s linear; }
.pip-music .pip-music-at { order: 2; }
.pip-music .pip-music-left { display: none; }
.pip-music .pip-music-pop { grid-area: pop; position: relative; margin-top: 4px; padding: 6px 0 2px; border-top: 1px solid color-mix(in srgb, var(--pip-accent) 25%, transparent); cursor: default; min-width: 0; }
.pip-music .pip-music-pop header { font-weight: 600; font-size: 11px; padding-right: 22px; margin-bottom: 4px; color: var(--pip-accent); }
.pip-music .pip-music-pop .pip-music-pop-x { position: absolute; top: 4px; right: 0; width: 18px; height: 18px; padding: 0; border: 0; background: none; display: grid; place-items: center; cursor: pointer; }
.pip-music .pip-music-pop .pip-music-pop-x svg { width: 14px; height: 14px; }
.pip-music .pip-music-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pip-music .pip-music-row input { flex: 1; min-width: 0; }
.pip-music .pip-music-row input[type=search] { background: rgb(0 0 0 / .25); color: inherit; border: 1px solid color-mix(in srgb, var(--pip-accent) 25%, transparent); border-radius: 4px; padding: 3px 6px; font: inherit; user-select: text; }
.pip-music .pip-music-pop ol { margin: 0; padding: 0; list-style: none; display: grid; gap: 3px; }
.pip-music .pip-music-pop li { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.pip-music .pip-music-pop li b { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.pip-music .pip-music-pop li span { flex: 0 1 auto; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; opacity: .75; font-size: 11px; }
.pip-music.expanded { grid-template-columns: auto minmax(0, 1fr); grid-template-areas: "side info" "art art" "keys keys" "seek seek" "pop pop"; width: clamp(196px, calc(100vh - 150px), 250px); max-width: calc(100vw - 8px); padding: 6px 8px 8px; row-gap: 6px; }
.pip-music.expanded .pip-music-info { grid-area: info; display: block; text-align: center; padding-right: 15px; }
.pip-music.expanded .pip-music-info b, .pip-music.expanded .pip-music-info small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pip-music.expanded .pip-music-info small { opacity: .75; font-size: 11px; }
.pip-music.expanded .pip-music-art, .pip-music.expanded .pip-music-blank { width: 100%; height: auto; aspect-ratio: 1; max-height: calc(100vh - 150px); min-height: 60px; }
.pip-music.expanded .pip-music-blank svg { width: 38%; height: 38%; }
.pip-music.expanded .pip-music-keys { justify-content: space-around; }
.pip-music.expanded .pip-music-keys .pip-music-up, .pip-music.expanded .pip-music-keys .pip-music-down { display: grid; }
.pip-music.expanded .pip-music-keys .pip-music-queue, .pip-music.expanded .pip-music-keys .pip-music-find { display: none; }
.pip-music.expanded .pip-music-at { order: 0; }
.pip-music.expanded .pip-music-left { display: block; }
'''
CSS = [
    ("the sheet and the mini player", None, CSS_NEW, "#pinePipShift.leaving {", 1),
]

# --------------------------------------------------------------------------- tests/test_pine_pip.cjs
TEST_OLD = r'''  const dock = await win.webContents.executeJavaScript(`document.querySelector('.pip-music-info').parentElement.parentElement.className`); assert.match(dock, /bottom/);'''
TEST_NEW = r'''  const dock = await win.webContents.executeJavaScript(`document.querySelector('.pip-music').parentElement.id`); assert.equal(dock, 'pinePipWidgets', '[pip-music] the player is placed freely, not held in a dock');'''
# That test enlarges the System 3 tile to most of a 440 px window. The old strip lay in a
# dock underneath the tile; a free player has nowhere in that window that is not on it, and
# would take the clicks meant for the tile. It steps out there and stays out: the later checks
# read its text and press its vote button, which work the same on a hidden player.
TEST_AWAY_OLD = r'''messageBounds:{width:.56,height:.78}})");await delay(100);'''
TEST_AWAY_NEW = r'''messageBounds:{width:.56,height:.78},widgets:{music:false}})");await delay(100);   /* [pip-music] the free player steps off the enlarged tile (its text and votes are still checked below) */'''
TEST = [
    ("the shell test expects a free player", TEST_OLD, TEST_NEW, "'[pip-music] the player is placed freely, not held in a dock'", 1),
    ("the player steps off the enlarged tile", TEST_AWAY_OLD, TEST_AWAY_NEW, "/* [pip-music] the free player steps off the enlarged tile (", 1),
]

EDITS = {
    "desktop/pip-window.cjs": WINDOW,
    "desktop/preload.js": PRELOAD,
    "desktop/main.js": MAIN,
    "desktop/renderer/index.html": HTML,
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
    "desktop/renderer/pine-pip.css": CSS,
    "app/src/main/assets/pine-views/pine-pip.css": CSS,
    "tests/test_pine_pip.cjs": TEST,
}
DEMOJI = ("desktop/renderer/pine-pip.js", "app/src/main/assets/pine-views/pine-pip.js")
NON_ASCII = re.compile(r"[^\x00-\x7f]+")


def demoji(text: str) -> tuple[str, int, str]:
    """A file saved as UTF-8, read as Windows-1252 and saved again: every glyph
    in it is two or three wrong letters. Put each back, as a \\uXXXX escape so
    the next tool that misreads the file cannot do it again."""
    bad: list[str] = []

    def fix(match: "re.Match[str]") -> str:
        try:
            good = match.group(0).encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            bad.append(match.group(0))
            return match.group(0)
        return "".join("\\u%04x" % ord(char) for char in good)

    out, count = NON_ASCII.subn(fix, text)
    return out, count, ("%d run(s) are not a double encoding" % len(bad)) if bad else ""


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
        if name in DEMOJI:
            fixed, count, trouble = demoji(text)
            state = "applied" if not count else ("missing (%s)" % trouble) if trouble else "ready"
            print("%-46s %-38s %s" % (name[-46:], "its glyphs are read back (%d)" % count, state))
            if state == "ready":
                text, changed, ready = fixed, True, True
            elif state != "applied":
                missing = True
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
            print("%-46s %-38s %s" % (name[-46:], label, state))
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
        tmp = path.with_name(path.name + ".pipdesk.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
