#!/usr/bin/env python3
"""[pip-viz] The Pine PiP's living background. 2026-10-05.

"for the pine pip display, I want it able to show variant animated reactive backgrounds ... When i
 click the background of the pinepip, cycle through these." Ten visualizers, one telemetry road:
desktop/renderer/pipviz (core, audio, visualizers, ui), bundled by tools/pineviz_bundle.py into
dist/pineviz.bundle.js and served by the station from its vendor route.

This tool wires the bundle into the PiP panel that pine-pip.js injects into the station page:
  - the panel loads /vendor/pineviz.bundle.js after three.js and mounts PineViz on its background;
    the old particle cloud stays as the fallback when the bundle cannot be had
  - the panel's own analysers (the voice, reply and sting players it already reads, plus the
    program monitor when it plays) feed an ExternalProvider every 70 ms; the shell adds station
    telemetry (speaking, music, activity) so a muted PiP still breathes with the station
  - a click on the background cycles the mode (a double-click still expands); the mode is kept
  - the PiP palette (the Color theme) becomes the visualizer palette
  - the PiP menu gets a Background submenu naming the ten modes
Both copies of pine-pip.js are patched (the tablet takes its copy at the next kiosk build).

Usage:  pip_viz_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_viz_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- pine-pip.js (both copies)
VARS_OLD = r'''    let shell = false, otherCount = 0, reportedCount = '', voiceMeters = false, lastMeters = 0;
'''
VARS_NEW = r'''    let shell = false, otherCount = 0, reportedCount = '', voiceMeters = false, lastMeters = 0;
    /* [pip-viz] the living background: PineViz on the panel's background, fed by this page's analysers and the station's telemetry */
    let viz = null, vizProvider = null, vizLoading = null, vizFailed = false, vizMode = '', telemetry = { speaking: 0, music: 0, activity: 0, at: 0 };
    const programBands = new Float32Array(24); let programLevel = 0;
'''

THREE_OLD = r'''    function three() {
'''
THREE_NEW = r'''    /* [pip-viz] the visualizer bundle, from the station's own vendor route (built by tools/pineviz_bundle.py) */
    function vizLibrary() {
      if (w.PineViz && w.PineViz.mount) return Promise.resolve(w.PineViz);
      if (vizLoading) return vizLoading;
      vizLoading = new Promise((resolve, reject) => {
        const tag = doc.createElement('script'); tag.src = '/vendor/pineviz.bundle.js?v=' + Math.floor(Date.now() / 3600000);
        tag.onload = () => w.PineViz && w.PineViz.mount ? resolve(w.PineViz) : reject(new Error('PineViz unavailable'));
        tag.onerror = () => { vizLoading = null; reject(new Error('PineViz unavailable')); };
        doc.head.appendChild(tag);
      });
      return vizLoading;
    }
    function vizPalette(P) {
      /* the PiP theme as a visualizer palette: the surface is the night, the accent the light */
      const rgb = String(palette.surface || '8 23 19').split(/[\s,]+/).map(Number);
      const hex = (r, g, b) => '#' + [r, g, b].map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
      P.PALETTES.pinepip = { name: 'Pine PiP', bg: hex(rgb[0] * .5, rgb[1] * .5, rgb[2] * .6), bg2: palette.button || '#17382c', primary: palette.accent || '#98e9ae', secondary: palette.text || '#e1f8ea', accent: '#ffffff', glow: palette.accent || '#98e9ae', ink: palette.text || '#e1f8ea' };
      return 'pinepip';
    }
    function mountViz(P) {
      if (viz || !enabled || shell) return;
      vizProvider = new P.ExternalProvider();
      viz = P.mount(background, { provider: vizProvider, palette: vizPalette(P), quality: 'high', keys: false, click: true, modeKey: 'pinePipVizMode', presetKey: 'pinePipVizPresets', transition: 'crossfade' });
      viz.on((kind, value) => { if (kind === 'mode') { vizMode = value; try { w.postMessage({ type: 'pine-pip-background', mode: value }, '*'); } catch (_) {} } });
      vizMode = viz.activeId || '';
      if (particles) { particles.dispose(); particles = null; }
    }
    function vizFeed() {
      if (!vizProvider) return;
      const stale = telemetry.at && Date.now() - telemetry.at > 15000;
      const bands = programLevel > voiceLevel ? programBands : voiceBands, level = Math.max(voiceLevel, programLevel);
      vizProvider.feed({ fft: bands, rms: level, speech: Math.max(voiceLevel > .035 ? Math.min(1, voiceLevel * 2.5) : 0, stale ? 0 : telemetry.speaking * .6), activity: Math.max(level * 1.3, stale ? 0 : telemetry.activity), music: Math.max(programLevel > .05 ? .6 : 0, stale ? 0 : telemetry.music) });
    }
    function three() {
'''

LAYOUT_OLD = r'''      logo.style.display = count || shell ? 'none' : ''; background.style.display = count || shell ? 'none' : '';
'''
LAYOUT_NEW = r'''      logo.style.display = count || shell ? 'none' : ''; background.style.display = count || shell ? 'none' : '';
      if (viz) { if (count || shell) viz.stop(); else if (enabled) viz.start(); }   /* [pip-viz] a background under tiles is not drawn */
'''

METERS_OLD = r'''        if (voiceMeters) w.postMessage({ type: 'pine-pip-voices', readings }, '*');
'''
METERS_NEW = r'''        if (voiceMeters) w.postMessage({ type: 'pine-pip-voices', readings }, '*');
        /* [pip-viz] the program monitor (the broadcast mix this page plays) is the fuller signal for the background */
        programLevel = 0; programBands.fill(0);
        if (vizProvider && w.pineAudioCtx?.state === 'running') {
          for (const el of media) {
            if (el.paused || el.ended || !/monitor|hear|radio|stream|music|player/i.test(el.dataset.pineLive || el.id || '')) continue;
            let scope; try { scope = typeof w.audioScope === 'function' ? w.audioScope(el) : null; } catch (_) { continue; }
            if (!scope?.analyser) continue;
            const bins = scope.bins || new Uint8Array(scope.analyser.frequencyBinCount);
            scope.analyser.getByteFrequencyData(bins);
            let sum = 0; for (const n of bins) sum += n * n;
            const step = Math.max(1, Math.floor(bins.length / 24));
            for (let i = 0; i < 24; i++) { let value = 0; for (let j = 0; j < step; j++) value += bins[i * step + j] || 0; programBands[i] = Math.max(programBands[i], Math.min(1, value / step / 180)); }
            programLevel = Math.max(programLevel, Math.min(1, Math.sqrt(sum / Math.max(1, bins.length)) / 128));
          }
        }
        vizFeed();
'''

API_OLD = r'''    }, meters(on) { voiceMeters = !!on; }, layout(count) { otherCount = Number(count) || 0; layout(); }, set(on, logoSrc, isShell) {
'''
API_NEW = r'''      if (viz) { vizPalette(w.PineViz); viz.palette.set('pinepip'); }   /* [pip-viz] the theme is the background's palette */
    }, meters(on) { voiceMeters = !!on; }, layout(count) { otherCount = Number(count) || 0; layout(); },
    /* [pip-viz] what the station is doing, from the shell: a muted PiP still breathes with it */
    telemetry(next) { if (next && typeof next === 'object') telemetry = { speaking: Number(next.speaking) || 0, music: Number(next.music) || 0, activity: Number(next.activity) || 0, at: Date.now() }; },
    /* [pip-viz] the background mode: a name, 'next', or nothing to read it */
    background(mode) { if (!viz) return { mode: vizMode, modes: w.PineViz ? w.PineViz.modes() : [] }; if (mode === 'next') viz.next(); else if (mode === 'previous') viz.next(-1); else if (mode) viz.set(String(mode)); return { mode: viz.incoming ? viz.incoming.id : viz.activeId, modes: viz.modes }; },
    viz() { return viz; },   /* [pip-viz] the manager, for the HUD and the tests */
    set(on, logoSrc, isShell) {
'''

ENTER_OLD = r'''        if (!shell && !particles) three().then(T => { if (enabled && !particles) particles = createParticles(T); }).catch(() => {
          if (!host.querySelector('.pip-failure')) { const note = doc.createElement('span'); note.className = 'pip-failure'; note.textContent = 'Particle visualization unavailable'; host.appendChild(note); }
        });
'''
ENTER_NEW = r'''        /* [pip-viz] the living background first; the particle cloud only when the bundle cannot be had */
        if (!shell && viz) viz.start();
        if (!shell && !viz && !particles) three().then(T => {
          if (!enabled || shell) return;
          if (vizFailed) { if (!particles) particles = createParticles(T); return; }
          return vizLibrary().then(P => { if (enabled && !shell) mountViz(P); }).catch(() => { vizFailed = true; if (enabled && !shell && !particles) particles = createParticles(T); });
        }).catch(() => {
          if (!host.querySelector('.pip-failure')) { const note = doc.createElement('span'); note.className = 'pip-failure'; note.textContent = 'Particle visualization unavailable'; host.appendChild(note); }
        });
'''

LEAVE_OLD = r'''        if (particles) { particles.dispose(); particles = null; } reportedCount = ''; otherCount = 0; voiceLevel = 0; voiceBands.fill(0);
'''
LEAVE_NEW = r'''        if (particles) { particles.dispose(); particles = null; } reportedCount = ''; otherCount = 0; voiceLevel = 0; voiceBands.fill(0);
        if (viz) viz.stop();   /* [pip-viz] kept for the next entry; nothing rebuilt */
'''

# the shell: station telemetry to the panel, and the Background action from the menu
SHELL_RECEIVE_OLD = r'''    messageTile?.receive(payload);
    station = payload.station || {}; track = station.now; updateCast(); updatePainting();
'''
SHELL_RECEIVE_NEW = r'''    messageTile?.receive(payload);
    station = payload.station || {}; track = station.now; updateCast(); updatePainting();
    tellPanelTelemetry(payload);   /* [pip-viz] */
'''

SHELL_TELL_OLD = r'''  function eventText(it) {
'''
SHELL_TELL_NEW = r'''  /* [pip-viz] what the station is doing, for the background in the panel: at most every two seconds */
  let telemetryAt = 0;
  function tellPanelTelemetry(payload) {
    if (!panelReady || !state?.active || Date.now() - telemetryAt < 2000) return;
    telemetryAt = Date.now();
    const live = payload.now || (payload.rows || []).find(r => r.lcdStatus === 'Playing' && !r.music);
    const note = { speaking: live && live.text ? 1 : 0, music: station?.playing && !station?.paused ? 1 : 0, activity: live && live.text ? 1 : station?.playing && !station?.paused ? .6 : .15 };
    frame.executeJavaScript('window.PinePipPanel?.telemetry(' + JSON.stringify(note) + ')').catch(() => {});
  }
  function eventText(it) {
'''

SHELL_ACTION_OLD = r'''    if (action?.type === 'adjust' && action.name) { showAdjust(String(action.name), freeBox(String(action.name))); return; }   /* [pip-free] from the menu's Widget layout */
'''
SHELL_ACTION_NEW = r'''    if (action?.type === 'adjust' && action.name) { showAdjust(String(action.name), freeBox(String(action.name))); return; }   /* [pip-free] from the menu's Widget layout */
    if (action?.type === 'background') {   /* [pip-viz] the menu names a mode, or asks for the next */
      if (!panelReady) { say('The background changes once the station page is ready.'); return; }
      return frame.executeJavaScript('window.PinePipPanel?.background(' + JSON.stringify(String(action.mode || 'next')) + ')').then(got => { if (got && got.mode) say('Background: ' + got.mode); }).catch(err => say(err.message));
    }
'''

PIPJS = [
    ("the background's state", VARS_OLD, VARS_NEW, "let viz = null, vizProvider = null, vizLoading = null, vizFailed = false, vizMode = ''", 1),
    ("the bundle, the palette, the mount and the feed", THREE_OLD, THREE_NEW, "function vizLibrary() {", 1),
    ("a background under tiles is not drawn", LAYOUT_OLD, LAYOUT_NEW, "if (viz) { if (count || shell) viz.stop(); else if (enabled) viz.start(); }", 1),
    ("the program monitor feeds it", METERS_OLD, METERS_NEW, "programLevel = 0; programBands.fill(0);", 1),
    ("telemetry() and background() on the panel", API_OLD, API_NEW, "background(mode) { if (!viz) return { mode: vizMode, modes: w.PineViz ? w.PineViz.modes() : [] };", 1),
    ("the living background first, particles as the fallback", ENTER_OLD, ENTER_NEW, "return vizLibrary().then(P => { if (enabled && !shell) mountViz(P); })", 1),
    ("leaving PiP stops it", LEAVE_OLD, LEAVE_NEW, "if (viz) viz.stop();   /* [pip-viz] kept for the next entry; nothing rebuilt */", 1),
    ("the shell tells the panel what the station does", SHELL_RECEIVE_OLD, SHELL_RECEIVE_NEW, "tellPanelTelemetry(payload);   /* [pip-viz] */", 1),
    ("tellPanelTelemetry()", SHELL_TELL_OLD, SHELL_TELL_NEW, "function tellPanelTelemetry(payload) {", 1),
    ("the menu's Background action", SHELL_ACTION_OLD, SHELL_ACTION_NEW, "if (action?.type === 'background') {", 1),
]

# --------------------------------------------------------------------------- pip-window.cjs
MENU_OLD = r'''      { label: 'Color theme', submenu: Object.entries(THEMES).map(([theme, label]) => ({ label, type: 'radio', checked: s.theme === theme, click: () => update({ theme }) }))'''
MENU_NEW = r'''      /* [pip-viz] the living background: ten modes; a click on the background cycles them too */
      { label: 'Background', submenu: [
        { label: 'Next background (click the background)', click: () => getWindow()?.webContents.send('pip:action', { type: 'background', mode: 'next' }) },
        { type: 'separator' },
        ...BACKGROUNDS.map(([mode, label]) => ({ label, click: () => getWindow()?.webContents.send('pip:action', { type: 'background', mode }) }))
      ] },
      { label: 'Color theme', submenu: Object.entries(THEMES).map(([theme, label]) => ({ label, type: 'radio', checked: s.theme === theme, click: () => update({ theme }) }))'''

BACKGROUNDS_OLD = r'''const WIDGETS = { dialogue: true, task: false, audit: false, production: false, music: false, chat: false, messages: false, cast: false, voices: false, roulette: false };
'''
BACKGROUNDS_NEW = r'''const WIDGETS = { dialogue: true, task: false, audit: false, production: false, music: false, chat: false, messages: false, cast: false, voices: false, roulette: false };
/* [pip-viz] the ten backgrounds of desktop/renderer/pipviz, in their order */
const BACKGROUNDS = [['smooth-wave', '01 Smooth Wave - flowing ribbons'], ['particle-flow', '02 Particle Flow - luminous matter'], ['line-spectrum', '03 Line Spectrum - contour lines'], ['geometric-space', '04 Geometric Space - floating glass'],
  ['speed-lines', '05 Speed Lines - hyperdrive'], ['anime-ink', '06 Anime Ink Wave - hand-drawn seas'], ['audio-bars', '07 Audio Bars - dimensional spectrum'], ['liquid-glass', '08 Liquid Glass - refractive membrane'],
  ['retro-grid', '09 Retro Grid - wireframe landscape'], ['shape-burst', '10 Shape Burst - reactive symbols']];
'''
WINDOW = [
    ("the ten backgrounds", BACKGROUNDS_OLD, BACKGROUNDS_NEW, "const BACKGROUNDS = [['smooth-wave'", 1),
    ("a Background submenu", MENU_OLD, MENU_NEW, "{ label: 'Background', submenu: [", 1),
]

EDITS = {
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
    "desktop/pip-window.cjs": WINDOW,
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
        tmp = path.with_name(path.name + ".pipviz.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
