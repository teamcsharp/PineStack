const { Menu, screen } = require('electron');

const VOICE_STYLES = ['Cyan bars', 'Green wave', 'Amber equalizer', 'Purple wave', 'Red blocks', 'Blue spikes', 'Green blocks', 'Gold wave', 'Violet spikes', 'Teal filled wave', 'Pink blocks', 'Sky bars', 'Lime bars', 'Orange spikes', 'Cyan dots', 'Violet bars'];
const WIDGETS = { dialogue: true, task: false, audit: false, production: false, music: false, chat: false, messages: false, cast: false, voices: false, roulette: false };
/* [pip-viz] the ten backgrounds of desktop/renderer/pipviz, in their order */
const BACKGROUNDS = [['smooth-wave', '01 Smooth Wave - flowing ribbons'], ['particle-flow', '02 Particle Flow - luminous matter'], ['line-spectrum', '03 Line Spectrum - contour lines'], ['geometric-space', '04 Geometric Space - floating glass'],
  ['speed-lines', '05 Speed Lines - hyperdrive'], ['anime-ink', '06 Anime Ink Wave - hand-drawn seas'], ['audio-bars', '07 Audio Bars - dimensional spectrum'], ['liquid-glass', '08 Liquid Glass - refractive membrane'],
  ['retro-grid', '09 Retro Grid - wireframe landscape'], ['shape-burst', '10 Shape Burst - reactive symbols']];
const EXPORT_SECONDS = [60,120,180,300,600,900,1800,3600];
const durationLabel = s => s===3600?'1 hour':(s/60)+(s===60?' minute':' minutes');
const THEMES = { pine: 'Pine green', midnight: 'Midnight blue', plum: 'Plum', amber: 'Amber', graphite: 'Graphite' };
const MESSAGE_TILE_MODES = { hold: 'Hold until the next message', fade: 'Fade after a delay', history: 'Keep a scrolling history' };
function messageTilePreferences(value = {}) {
  const bounded = (key, fallback, min, max) => Number.isFinite(value?.[key]) ? Math.max(min, Math.min(max, value[key])) : fallback;
  return { mode: Object.hasOwn(MESSAGE_TILE_MODES, value?.mode) ? value.mode : 'hold',
    fontSize: bounded('fontSize', 12, 8, 28), opacity: bounded('opacity', .85, 0, 1),
    rollSpeed: bounded('rollSpeed', 1, .25, 4), typingSpeed: bounded('typingSpeed', 1, .25, 4),
    followPlayback: value?.followPlayback !== false, fadeDelay: bounded('fadeDelay', 4, 0, 60) };
}
/* [pip-free] every widget, and the camera, can carry a layout entry */
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
  const widgets = {}, docks = {}, order = {}, voiceStyles = {};
  for (const [key, fallback] of Object.entries({ host: 0, cohost: 1, sfx: 2, callers: 3 })) voiceStyles[key] = Number.isInteger(value.voiceStyles?.[key]) && value.voiceStyles[key] >= 0 && value.voiceStyles[key] < VOICE_STYLES.length ? value.voiceStyles[key] : fallback;
  for (const name of Object.keys(WIDGETS)) {
    widgets[name] = typeof value.widgets?.[name] === 'boolean' ? value.widgets[name] : WIDGETS[name];
    docks[name] = value.docks?.[name] === 'top' ? 'top' : name === 'music' && !value.docks?.[name] ? 'top' : 'bottom';
    order[name] = Number.isFinite(value.order?.[name]) ? value.order[name] : Object.keys(WIDGETS).indexOf(name);
  }
  // Either previous roulette overlay now uses the canonical shared tile.
  widgets.messages = widgets.messages || widgets.roulette;
  widgets.roulette = false;
  return { popupFavorites: Array.isArray(value.popupFavorites) ? [...new Set(value.popupFavorites.filter(id => typeof id==='string' && id.length<160))].slice(0,80) : [], ui: value.ui !== false, alwaysOnTop: value.alwaysOnTop !== false, aspectMode: value.aspectMode === 'square' ? 'square' : 'video',
    cameraOverlay: value.cameraOverlay === true, cameraOnly: value.cameraOnly === true,
    cameraSource: ['pine', 'tab-front', 'tab-rear'].includes(value.cameraSource) ? value.cameraSource : 'pine',
    cameraBounds: Object.fromEntries(Object.entries({ x: .58, y: .12, width: .38, height: .38 }).map(([key, fallback]) => [key, Number.isFinite(value.cameraBounds?.[key]) ? Math.max(key === 'x' || key === 'y' ? 0 : .001, Math.min(1, value.cameraBounds[key])) : fallback])),
    messageBounds: Object.fromEntries(Object.entries({ x: .02, y: .04, width: .44, height: .34 }).map(([key,fallback])=>[key,Number.isFinite(value.messageBounds?.[key])?Math.max(key==='x'||key==='y'?0:.001,Math.min(1,value.messageBounds[key])):fallback])),
    messageTile: messageTilePreferences(value.messageTile),
    roulettePosition: Object.fromEntries(Object.entries({ x: .04, y: .18 }).map(([key, fallback]) => [key, Number.isFinite(value.roulettePosition?.[key]) ? Math.max(0, Math.min(1, value.roulettePosition[key])) : fallback])),
    /* [pip-music] where the mini player sits (its top-left, as a share of the window) and whether it is opened out */
    musicPosition: Object.fromEntries(Object.entries({ x: .03, y: .6 }).map(([key, fallback]) => [key, Number.isFinite(value.musicPosition?.[key]) ? Math.max(0, Math.min(1, value.musicPosition[key])) : fallback])),
    musicExpanded: value.musicExpanded === true,
    musicArtOnly: value.musicArtOnly === true,   /* [pip-art] the player reduced to its artwork */
    /* [pip-free] one layout entry per widget: place (x,y) and size (w,h) as shares of the window,
       scale s, trims t (four sides, % of the widget) and opacity o. Absent = the widget's own default. */
    layout: Object.fromEntries(LAYOUT_NAMES.map(name => [name, layoutEntry(value.layout?.[name])]).filter(([, entry]) => entry)),
    theme: Object.hasOwn(THEMES, value.theme) ? value.theme : 'pine',
    transparency: Number.isFinite(value.transparency) ? Math.max(0, Math.min(90, value.transparency)) : 15,
    widgets, docks, order, voiceStyles };
}
function fitBounds(saved, area, frame = [0, 0]) {
  const maxWidth = Math.max(1, area.width - frame[0]), maxHeight = Math.max(1, area.height - frame[1]);
  const desiredWidth = Number(saved?.width || saved?.side) || 440;
  const desiredHeight = Number(saved?.height || saved?.side) || desiredWidth;
  const width = Math.round(Math.min(Math.max(160, desiredWidth), maxWidth)) + frame[0];
  const height = Math.round(Math.min(Math.max(90, desiredHeight), maxHeight)) + frame[1];
  const x = Number.isFinite(saved?.x) ? saved.x : area.x + area.width - width - 24;
  const y = Number.isFinite(saved?.y) ? saved.y : area.y + 24;
  return { x: Math.round(Math.max(area.x, Math.min(x, area.x + area.width - width))),
    y: Math.round(Math.max(area.y, Math.min(y, area.y + area.height - height))), width, height };
}
function install({ ipcMain, getWindow, readConfig, writeConfig, troubleshoot, repairPlayback, openTools, isToolsSender, publishTools, updateOwed, rebuild }) {
  let full = null, timer = null, activeMenu = null;
  const state = () => ({ active: !!getWindow()?.__pinePip, ...preferences(readConfig().pip) });
  const publish = () => { const w = getWindow(); if (w && !w.isDestroyed()) w.webContents.send('pip:state', state()); publishTools?.(state()); return state(); };
  function saveBounds() {
    const w = getWindow();
    if (!w?.__pinePip || w.__pinePipSwitching || w.isDestroyed() || w.isMinimized()) return;
    const b = w.getBounds(), c = w.getContentBounds();
    writeConfig({ pip: { ...readConfig().pip, ...preferences(readConfig().pip), bounds: { x: b.x, y: b.y, side: c.width, width: c.width, height: c.height } } });
  }
  /* [pip-shift] THE PAGE COVERS ITSELF BEFORE THE WINDOW CHANGES SHAPE.
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
    full = { bounds: w.getNormalBounds(), maximized: w.isMaximized(), fullscreen: w.isFullScreen(),
      top: w.isAlwaysOnTop(), menu: w.isMenuBarVisible(), title: w.getTitle(), maximizable: w.isMaximizable() };
    writeConfig({ bounds: full.bounds, pip: { ...readConfig().pip, enabled: true } });
    w.__pinePipSwitching = true;
    w.__pinePip = true;
    if (full.fullscreen) w.setFullScreen(false);
    if (full.maximized) w.unmaximize();
    w.setMaximizable(false);
    w.setMenuBarVisibility(false);
    w.setMinimumSize(160, 90);
    const b = w.getBounds(), c = w.getContentBounds();
    const frame = [b.width - c.width, b.height - c.height];
    const saved = readConfig().pip?.bounds;
    const display = saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)
      ? screen.getDisplayNearestPoint({ x: saved.x, y: saved.y }) : screen.getDisplayMatching(b);
    w.setAspectRatio(0);
    w.setBounds(fitBounds(saved, display.workArea, frame));
    w.setAlwaysOnTop(state().alwaysOnTop, 'floating');
    w.setTitle('PinePiP');
    w.__pinePipSwitching = false;
    saveBounds();
    return publish();
  }
  function exit() {
    const w = getWindow();
    if (!w?.__pinePip) return state();
    return shift('app', exitNow);
  }
  function exitNow() {
    const w = getWindow();
    if (!w?.__pinePip) return state();
    clearTimeout(timer); saveBounds();
    w.__pinePipSwitching = true;
    w.__pinePip = false;
    writeConfig({ pip: { ...readConfig().pip, enabled: false } });
    w.setAspectRatio(0); w.setMinimumSize(520, 420);
    w.setMaximizable(full?.maximizable ?? true);
    w.setAlwaysOnTop(full?.top || false);
    w.setMenuBarVisibility(full?.menu ?? true);
    w.setTitle(full?.title || 'Pine Box');
    if (full) { w.setBounds(full.bounds); if (full.maximized) w.maximize(); if (full.fullscreen) w.setFullScreen(true); }
    w.__pinePipSwitching = false;
    return publish();
  }
  function update(next) {
    const old = preferences(readConfig().pip);
    const cfg = preferences({ ...old, ...next, widgets: { ...old.widgets, ...next?.widgets },
      cameraBounds: { ...old.cameraBounds, ...next?.cameraBounds },
      roulettePosition: { ...old.roulettePosition, ...next?.roulettePosition },
      musicPosition: { ...old.musicPosition, ...next?.musicPosition },
      layout: next?.layout === null ? {} : mergeLayout(old.layout, next?.layout),   /* [pip-free] null = every widget back to its default */
      messageBounds: { ...old.messageBounds, ...next?.messageBounds },
      messageTile: { ...old.messageTile, ...next?.messageTile },
      docks: { ...old.docks, ...next?.docks }, order: { ...old.order, ...next?.order }, voiceStyles: { ...old.voiceStyles, ...next?.voiceStyles } });
    writeConfig({ pip: { ...readConfig().pip, ...cfg } });
    if (getWindow()?.__pinePip && old.alwaysOnTop !== cfg.alwaysOnTop) getWindow().setAlwaysOnTop(cfg.alwaysOnTop, 'floating');
    return publish();
  }
  function source() {
    // Older renderers may still report source dimensions. Media never owns
    // the window geometry; only the operator changes its size.
    return state();
  }
  function windowControl(value) {
    const w = getWindow(); if (!w || w.isDestroyed()) return;
    if (value === 'minimize') w.minimize();
    if (value === 'maximize' && !w.__pinePip) w.isMaximized() ? w.unmaximize() : w.maximize();
    if (value === 'close') w.close();
  }
  function position(value) {
    const w = getWindow(); if (!w?.__pinePip || w.isDestroyed()) return state();
    const b = w.getBounds(), area = screen.getDisplayMatching(b).workArea;
    const deltas = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] };
    const delta = deltas[value]; if (!delta) return state();
    w.setPosition(Math.round(Math.max(area.x, Math.min(area.x + area.width - b.width, b.x + delta[0]))), Math.round(Math.max(area.y, Math.min(area.y + area.height - b.height, b.y + delta[1])))); return state();
  }
  function size(width) {
    const w = getWindow(); if (!w?.__pinePip || w.isDestroyed()) return;
    const b = w.getBounds(), c = w.getContentBounds(), area = screen.getDisplayMatching(b).workArea;
    w.setBounds(fitBounds({ ...b, width, height: c.height * width / c.width }, area, [b.width - c.width, b.height - c.height]));
  }
  function menu(playback = {}) {
    if (!getWindow()?.__pinePip || activeMenu) return state();
    const s = state();
    const labels = { dialogue: 'Dialogue + rolling dice', task: 'Task status marquee', audit: 'Station audit marquee',
      production: 'Production / recording / banking / emotion marquee', music: 'Music player', chat: 'Chat + roulette + SFX feed', messages: 'System3 message tile', cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette RNG digital slate' };
    const names=new Map((Array.isArray(playback?.favorites)?playback.favorites:[]).filter(item=>item&&typeof item.id==='string'&&typeof item.label==='string').map(item=>[item.id,item.label.slice(0,120)]));
    const favoriteItems=s.popupFavorites.map(id=>({label:names.get(id)||id.slice(id.indexOf(':')+1).replace(/^Pine/,'').replace(/([a-z])([A-Z])/g,'$1 $2').replace(/[-_]/g,' '),
      click:()=>openTools?openTools({id}):getWindow()?.webContents.send('pip:action',{type:'favorite',id})}))
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base', numeric: true }));   /* [pip-favorites-az] "List favorites alphabetically." */
    /* [pip-update] "If the Pineapp is out of date, then at the top of the right
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
      { label: 'Resolve playback + restore DJs', click: () => repairPlayback ? repairPlayback() : getWindow()?.webContents.send('pip:action', 'repair-playback') },
      { label: 'Troubleshoot station...', click: () => troubleshoot ? troubleshoot() : getWindow()?.webContents.send('pip:action', 'troubleshoot') },
      { type: 'separator' },
      { label: 'Favorites', submenu: favoriteItems.length?favoriteItems:[{label:'No favorites yet - right-click a tool to add it',enabled:false}] },
      { label: 'Popups, 3JS and orchestra...', click: () => openTools ? openTools() : getWindow()?.webContents.send('pip:action','popups') },
      { label: 'Expand Pine', click: exit },
      { label: (s.cameraSource === 'pine' ? 'Pine Cam' : 'PineTab camera') + ' overlay', type: 'checkbox', checked: s.cameraOverlay, enabled: !s.cameraOnly, click: item => update({ cameraOverlay: item.checked }) },
      { label: (s.cameraSource === 'pine' ? 'Pine Cam' : 'PineTab camera') + ' only', type: 'checkbox', checked: s.cameraOnly, click: item => update({ cameraOnly: item.checked }) },
      { label: 'Camera source', submenu: Object.entries({ pine: 'Pine Cam', 'tab-front': 'PineTab front camera', 'tab-rear': 'PineTab rear camera' }).map(([cameraSource, label]) => ({ label, type: 'radio', checked: s.cameraSource === cameraSource, click: () => update({ cameraSource, cameraOverlay: true }) })) },
      { label: 'Export last...', submenu: EXPORT_SECONDS.map(seconds => ({ label: durationLabel(seconds), submenu: [
        { label: 'Broadcast mix (WAV)', click: () => getWindow()?.webContents.send('pip:action', { type: 'recording', seconds, format: 'audio' }) },
        { label: 'PiP video + broadcast mix (MP4)', click: () => getWindow()?.webContents.send('pip:action', { type: 'recording', seconds, format: 'video' }) }
      ] })) },
      { label: 'Export PineTab recording (MP4)', submenu: EXPORT_SECONDS.map(seconds => ({ label: durationLabel(seconds), click: () => getWindow()?.webContents.send('pip:action',{type:'tablet-recording',seconds}) })) },
      { label: 'Video window size', submenu: [240, 320, 480, 640, 960].map(width => ({ label: width + ' px wide', click: () => size(width) })) },
      { label: 'Move with Ctrl+Alt+arrow keys', enabled: false },
      { label: 'Open tablet display', click: () => getWindow()?.webContents.send('pip:action', 'tablet') },
      { label: 'Export tablet recording time range...', click: () => getWindow()?.webContents.send('pip:action', 'export') },
      { label: 'Voice indicator styles', submenu: Object.entries({ host: 'Host', cohost: 'Co-host', sfx: 'SFX', callers: 'Callers' }).map(([key, label]) => ({ label, submenu: VOICE_STYLES.map((label, index) => ({ label, type: 'radio', checked: s.voiceStyles[key] === index, click: () => update({ voiceStyles: { [key]: index } }) })) })) },
      { label: 'Audio mixer...', click: () => getWindow()?.webContents.send('pip:action', 'mixer') },
      /* [pip-viz] the living background: ten modes; a click on the background cycles them too */
      { label: 'Background', submenu: [
        { label: 'Next background (click the background)', click: () => getWindow()?.webContents.send('pip:action', { type: 'background', mode: 'next' }) },
        { type: 'separator' },
        ...BACKGROUNDS.map(([mode, label]) => ({ label, click: () => getWindow()?.webContents.send('pip:action', { type: 'background', mode }) }))
      ] },
      { label: 'Color theme', submenu: Object.entries(THEMES).map(([theme, label]) => ({ label, type: 'radio', checked: s.theme === theme, click: () => update({ theme }) })) },
      { label: 'Overlay transparency...', click: () => getWindow()?.webContents.send('pip:action', 'appearance') },
      { label: 'Always on top', type: 'checkbox', checked: s.alwaysOnTop, click: () => update({ alwaysOnTop: !s.alwaysOnTop }) },
      { label: 'Endless video', type: 'checkbox', checked: playback?.on === true,
        click: item => getWindow()?.webContents.send('pip:playback', { on: item.checked }) },
      { label: 'Seamless video', type: 'checkbox', checked: playback?.seamless === true,
        click: item => getWindow()?.webContents.send('pip:playback', { seamless: item.checked }) },
      { type: 'separator' },
      { label: 'Show overlays / UI', type: 'checkbox', checked: s.ui, click: () => update({ ui: !s.ui }) },
      ...Object.keys(WIDGETS).filter(name => name !== 'roulette').map(name => ({ label: labels[name], type: 'checkbox', checked: s.widgets[name],
        click: () => update({ widgets: { [name]: !s.widgets[name] } }) })),
      /* [pip-free] every shown widget's layout options, for a widget whose handle is trimmed away or hard to find */
      { label: 'Widget layout (scale, trim, opacity)...', submenu: Object.keys(WIDGETS).filter(name => name !== 'roulette' && s.widgets[name])
        .map(name => ({ label: labels[name], click: () => getWindow()?.webContents.send('pip:action', { type: 'adjust', name }) }))
        .concat([{ label: 'Pine Cam', click: () => getWindow()?.webContents.send('pip:action', { type: 'adjust', name: 'camera' }) }]) },
      { label: 'System3 message tile options', submenu: [
        ...Object.entries(MESSAGE_TILE_MODES).map(([mode, label]) => ({ label, type: 'radio', checked: s.messageTile.mode === mode,
          click: () => update({ messageTile: { mode } }) })),
        { type: 'separator' },
        { label: 'Pause animation with playback', type: 'checkbox', checked: s.messageTile.followPlayback,
          click: item => update({ messageTile: { followPlayback: item.checked } }) },
        { label: 'Configure text, opacity and animation...', click: () => getWindow()?.webContents.send('pip:action', 'message-tile-settings') }
      ] },
      { type: 'separator' }, { label: 'Drag a widget handle anywhere; drop it at the top or bottom edge to dock it', enabled: false },
      { label: 'Edge grips resize, Shift+grip trims, Ctrl+wheel scales, right-click a handle to adjust', enabled: false },
      /* [pip-free] a reset puts every widget back where it was before any of this */
      { label: 'Reset widget layout', click: () => update({ docks: preferences().docks, order: preferences().order, messageBounds: preferences().messageBounds, layout: null,
        musicPosition: preferences().musicPosition, roulettePosition: preferences().roulettePosition, cameraBounds: preferences().cameraBounds, musicArtOnly: false }) }
    ]);
    activeMenu.popup({ window: getWindow(), callback: () => { activeMenu = null; } });
    return state();
  }
  for (const [name, fn] of Object.entries({ state, enter, exit, update, menu, source, windowControl, position })) {
    ipcMain.handle('pip:' + name, (event, args) => {
      if (event.sender !== getWindow()?.webContents && !(['state','update'].includes(name) && isToolsSender?.(event))) throw new Error('PiP controls belong to the Pine desktop.');
      return fn(args);
    });
  }
  function attach(w) {
    const shortcut = (event, input) => {
      if (input.type !== 'keyDown' || !input.control || !input.shift || String(input.key).toLowerCase() !== 'p') return;
      event.preventDefault();
      if (!input.isAutoRepeat) w.__pinePip ? exit() : enter();
    };
    w.webContents.on('before-input-event', shortcut);
    w.webContents.on('did-attach-webview', (_event, guest) => guest.on('before-input-event', shortcut));
    const remember = () => { clearTimeout(timer); timer = setTimeout(saveBounds, 400); };
    w.on('system-context-menu', event => { if (w.__pinePip) { event.preventDefault(); w.webContents.send('pip:action', 'menu'); } });
    w.on('move', remember); w.on('resize', remember); w.on('close', saveBounds);

  }
  return { attach };
}
module.exports = { install, preferences, fitBounds, EXPORT_SECONDS, durationLabel };
