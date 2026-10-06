/* PineViz UI - DOM layers over the canvas: the radio overlay (station, program, host, now playing,
 * caller, time, signal), the development HUD (toggled with the backquote key; off in production) and
 * the visualizer selector (01..10, keys 1-0). Nothing here is drawn in WebGL.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp } = PineViz.util;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  const CSS = `
.pineviz-ui{position:absolute;inset:0;pointer-events:none;font:13px/1.35 "Inter","Segoe UI",system-ui,sans-serif;color:#e6f0ff;letter-spacing:.01em}
.pineviz-ui *{box-sizing:border-box}
.pineviz-radio{position:absolute;inset:0;display:grid;grid-template-rows:auto 1fr auto;padding:clamp(14px,2.6vw,34px)}
.pineviz-radio .pv-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.pineviz-radio .pv-row.bottom{align-items:flex-end}
.pineviz-radio .pv-station{font-weight:700;font-size:clamp(14px,1.5vw,20px);letter-spacing:.14em;text-transform:uppercase;display:flex;align-items:center;gap:10px}
.pineviz-radio .pv-onair{display:inline-flex;align-items:center;gap:6px;font-size:11px;letter-spacing:.2em;padding:3px 8px;border:1px solid rgba(255,255,255,.35);border-radius:3px;text-transform:uppercase}
.pineviz-radio .pv-onair i{width:7px;height:7px;border-radius:50%;background:#ff3b3b;box-shadow:0 0 10px #ff3b3b;animation:pv-blink 1.6s ease-in-out infinite}
.pineviz-radio .pv-onair.off i{background:#5b6b86;box-shadow:none;animation:none}
.pineviz-radio .pv-time{font-variant-numeric:tabular-nums;font-size:clamp(13px,1.4vw,18px);opacity:.9}
.pineviz-radio .pv-block{display:grid;gap:2px;max-width:46%}
.pineviz-radio .pv-label{font-size:10px;letter-spacing:.22em;text-transform:uppercase;opacity:.55}
.pineviz-radio .pv-big{font-size:clamp(16px,2vw,26px);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pineviz-radio .pv-small{font-size:clamp(12px,1.2vw,15px);opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pineviz-radio .pv-right{text-align:right;justify-items:end}
.pineviz-radio .pv-signal{display:inline-grid;grid-auto-flow:column;gap:3px;align-items:end;height:16px;margin-top:4px}
.pineviz-radio .pv-signal i{display:block;width:4px;background:rgba(255,255,255,.35);border-radius:1px;transition:height .12s}
.pineviz-radio .pv-note{position:absolute;left:50%;top:clamp(14px,2.6vw,34px);transform:translateX(-50%);padding:5px 12px;border-radius:14px;background:rgba(0,0,0,.45);font-size:12px;opacity:0;transition:opacity .3s}
.pineviz-radio .pv-note.show{opacity:1}
@keyframes pv-blink{0%,100%{opacity:1}50%{opacity:.35}}
.pineviz-selector{position:absolute;left:50%;bottom:10px;transform:translateX(-50%);display:flex;gap:4px;pointer-events:auto;padding:4px;border-radius:10px;background:rgba(3,8,22,.55);backdrop-filter:blur(6px);opacity:.25;transition:opacity .25s}
.pineviz-selector:hover,.pineviz-selector:focus-within,.pineviz-selector.show{opacity:1}
.pineviz-selector button{border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.04);color:#dbe9ff;border-radius:6px;padding:4px 7px;font:11px/1 system-ui,sans-serif;cursor:pointer;min-width:30px}
.pineviz-selector button[aria-pressed=true]{background:rgba(120,170,255,.28);border-color:rgba(140,190,255,.7)}
.pineviz-selector button:hover{border-color:rgba(255,255,255,.45)}
.pineviz-hud{position:absolute;right:10px;top:10px;width:264px;max-height:calc(100% - 20px);overflow:auto;pointer-events:auto;padding:10px 12px;border-radius:10px;background:rgba(2,6,18,.86);border:1px solid rgba(120,170,255,.25);font:11px/1.4 ui-monospace,Consolas,monospace;color:#cfe3ff;display:none}
.pineviz-hud.show{display:block}
.pineviz-hud h4{margin:0 0 6px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#8fc4ff}
.pineviz-hud .pv-kv{display:grid;grid-template-columns:92px 1fr 42px;gap:4px 6px;align-items:center;margin:2px 0}
.pineviz-hud .pv-bar{height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden}
.pineviz-hud .pv-bar i{display:block;height:100%;background:linear-gradient(90deg,#1f66ff,#49d8ff);width:0}
.pineviz-hud .pv-val{text-align:right;font-variant-numeric:tabular-nums}
.pineviz-hud label{display:grid;grid-template-columns:92px 1fr 42px;gap:4px 6px;align-items:center;margin:3px 0}
.pineviz-hud input[type=range]{width:100%;margin:0;accent-color:#49d8ff}
.pineviz-hud select,.pineviz-hud button{font:inherit;background:#0d1a33;color:inherit;border:1px solid rgba(120,170,255,.3);border-radius:4px;padding:2px 4px}
.pineviz-hud .pv-hudrow{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.pineviz-hud .pv-stats{opacity:.8;white-space:pre-wrap}
`;
  function ensureStyle(doc) { if (doc.getElementById('pineviz-ui-style')) return; const s = doc.createElement('style'); s.id = 'pineviz-ui-style'; s.textContent = CSS; doc.head.appendChild(s); }

  /** The radio layer: placeholders a host fills with setInfo({...}); optional; the canvas works without it. */
  class RadioOverlay {
    constructor(container, info = {}) {
      ensureStyle(container.ownerDocument);
      this.root = el('div', 'pineviz-ui pineviz-radio'); container.appendChild(this.root);
      const top = el('div', 'pv-row'), bottom = el('div', 'pv-row bottom');
      this.station = el('div', 'pv-station'); this.onair = el('span', 'pv-onair'); this.onair.append(el('i'), document.createTextNode('On air'));
      this.stationName = el('span', '', 'Pine Box FM'); this.station.append(this.stationName, this.onair);
      this.time = el('div', 'pv-time', '');
      top.append(this.station, this.time);
      const left = el('div', 'pv-block'); this.programLabel = el('div', 'pv-label', 'Program'); this.program = el('div', 'pv-big', ''); this.host = el('div', 'pv-small', ''); this.nowLabel = el('div', 'pv-label', 'Now playing'); this.track = el('div', 'pv-small', ''); this.artist = el('div', 'pv-small', '');
      left.append(this.programLabel, this.program, this.host, this.nowLabel, this.track, this.artist);
      const right = el('div', 'pv-block pv-right'); this.callerLabel = el('div', 'pv-label', 'Caller'); this.caller = el('div', 'pv-small', ''); this.statusLabel = el('div', 'pv-label', 'Signal'); this.status = el('div', 'pv-small', '');
      this.signal = el('div', 'pv-signal'); for (let i = 0; i < 12; i++) this.signal.appendChild(el('i'));
      right.append(this.callerLabel, this.caller, this.statusLabel, this.status, this.signal);
      bottom.append(left, right);
      this.note = el('div', 'pv-note', '');
      this.root.append(top, el('div'), bottom, this.note);
      this.setInfo({ station: 'Pine Box FM', onAir: true, program: 'The Pine Box Hour', host: 'Dill and Skip', track: '', artist: '', caller: '', status: 'Live', ...info });
      this.clock = setInterval(() => this.tick(), 1000); this.tick();
    }
    setInfo(info) {
      if (info.station != null) this.stationName.textContent = info.station;
      if (info.onAir != null) this.onair.classList.toggle('off', !info.onAir);
      if (info.program != null) this.program.textContent = info.program;
      if (info.host != null) this.host.textContent = info.host;
      if (info.track != null) this.track.textContent = info.track; if (info.artist != null) this.artist.textContent = info.artist;
      this.nowLabel.style.display = this.track.textContent || this.artist.textContent ? '' : 'none';
      if (info.caller != null) { this.caller.textContent = info.caller; this.callerLabel.style.display = info.caller ? '' : 'none'; this.caller.style.display = info.caller ? '' : 'none'; }
      if (info.status != null) this.status.textContent = info.status;
      if (info.recording != null) this.status.textContent = (this.status.textContent.replace(/ \u00b7 REC$/, '')) + (info.recording ? ' \u00b7 REC' : '');
    }
    tick() { const d = new Date(); this.time.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
    /** called every frame by whoever has the state */
    update(state) { const bars = this.signal.children; for (let i = 0; i < bars.length; i++) { const v = state.fft[Math.floor(i / bars.length * state.fft.length)] || 0; bars[i].style.height = Math.max(8, Math.round(v * 100)) + '%'; } }
    notify(text, ms = 2600) { this.note.textContent = text; this.note.classList.add('show'); clearTimeout(this.noteTimer); this.noteTimer = setTimeout(() => this.note.classList.remove('show'), ms); }
    show(on = true) { this.root.style.display = on ? '' : 'none'; }
    dispose() { clearInterval(this.clock); this.root.remove(); }
  }

  /** 01..10 buttons; keys 1-0 are the manager's. */
  class VisualizerSelector {
    constructor(container, manager, options = {}) {
      ensureStyle(container.ownerDocument);
      this.manager = manager; this.root = el('div', 'pineviz-selector' + (options.alwaysShow ? ' show' : '')); container.appendChild(this.root);
      this.buttons = new Map();
      for (const mode of manager.modes) { const b = el('button', '', String(mode.index).padStart(2, '0')); b.title = mode.name + (mode.blurb ? ' - ' + mode.blurb : ''); b.setAttribute('aria-label', mode.name); b.addEventListener('click', () => manager.set(mode.id)); this.root.appendChild(b); this.buttons.set(mode.id, b); }
      this.off = manager.on((kind, id) => { if (kind === 'mode') this.paint(id); });
      this.paint(manager.activeId);
    }
    paint(id) { for (const [key, b] of this.buttons) b.setAttribute('aria-pressed', String(key === id)); }
    dispose() { this.off(); this.root.remove(); }
  }

  /** The development HUD. Toggled with the backquote key (or options.key); `production: true` never builds it. */
  class DebugHUD {
    constructor(container, manager, options = {}) {
      this.manager = manager; this.options = options;
      if (options.production) { this.root = null; return; }
      ensureStyle(container.ownerDocument);
      this.root = el('div', 'pineviz-hud'); container.appendChild(this.root);
      this.root.appendChild(el('h4', '', 'PineViz'));
      this.lines = {};
      const kv = (key, label) => { const row = el('div', 'pv-kv'); const bar = el('div', 'pv-bar'); bar.appendChild(el('i')); const val = el('span', 'pv-val', '0'); row.append(el('span', '', label), bar, val); this.root.appendChild(row); this.lines[key] = { bar: bar.firstChild, val }; };
      this.fps = el('div', 'pv-stats', ''); this.root.appendChild(this.fps);
      for (const [k, l] of [['rms', 'rms'], ['peak', 'peak'], ['bass', 'bass'], ['mid', 'mid'], ['treble', 'treble'], ['beat', 'beat'], ['speechActivity', 'speech'], ['stationActivity', 'activity'], ['energy', 'energy']]) kv(k, l);
      const row = el('div', 'pv-hudrow');
      this.modeSel = el('select'); for (const m of manager.modes) { const o = el('option', '', String(m.index).padStart(2, '0') + ' ' + m.name); o.value = m.id; this.modeSel.appendChild(o); } this.modeSel.addEventListener('change', () => manager.set(this.modeSel.value));
      this.palSel = el('select'); for (const n of manager.palette.names) { const o = el('option', '', PineViz.PALETTES[n].name); o.value = n; this.palSel.appendChild(o); } this.palSel.value = manager.palette.name; this.palSel.addEventListener('change', () => manager.palette.set(this.palSel.value));
      this.qSel = el('select'); for (const q of PineViz.QUALITY_LADDER) { const o = el('option', '', q); o.value = q; this.qSel.appendChild(o); } this.qSel.value = manager.renderer.quality; this.qSel.addEventListener('change', () => manager.renderer.setQuality(this.qSel.value));
      this.transSel = el('select'); for (const t of Object.keys(PineViz.TRANSITIONS)) { const o = el('option', '', t); o.value = t; this.transSel.appendChild(o); } this.transSel.addEventListener('change', () => { manager.transition.mode = PineViz.TRANSITIONS[this.transSel.value]; });
      row.append(this.modeSel, this.palSel, this.qSel, this.transSel); this.root.appendChild(row);
      const prov = el('div', 'pv-hudrow');
      this.provSel = el('select'); for (const [v, l] of [['demo', 'demo'], ['microphone', 'microphone'], ['external', 'external']]) { const o = el('option', '', l); o.value = v; this.provSel.appendChild(o); }
      this.provSel.value = manager.provider?.name || 'demo';
      this.provSel.addEventListener('change', () => { const v = this.provSel.value; if (v === 'demo') manager.setProvider(new PineViz.DemoProvider()); else if (v === 'microphone') manager.setProvider(new PineViz.MicrophoneProvider()); else manager.setProvider(new PineViz.ExternalProvider({ url: options.externalUrl || '' })); this.sceneSel.style.display = v === 'demo' ? '' : 'none'; });
      this.sceneSel = el('select'); const auto = el('option', '', 'scenes: cycle'); auto.value = ''; this.sceneSel.appendChild(auto); for (const s of PineViz.DEMO_SCENES) { const o = el('option', '', s); o.value = s; this.sceneSel.appendChild(o); }
      this.sceneSel.addEventListener('change', () => { const p = manager.provider; if (p && p.name === 'demo') { if (this.sceneSel.value) p.setScene(this.sceneSel.value); else p.hold = null; } });
      const reset = el('button', '', 'reset preset'); reset.addEventListener('click', () => { if (manager.activeId) { manager.presets.reset(manager.activeId); this.buildSliders(); } });
      prov.append(this.provSel, this.sceneSel, reset); this.root.appendChild(prov);
      this.sliders = el('div'); this.root.appendChild(this.sliders);
      this.stats = el('div', 'pv-stats', ''); this.root.appendChild(this.stats);
      this.off = manager.on((kind, value, m) => { if (kind === 'frame') this.paint(value); if (kind === 'mode') { this.modeSel.value = value; this.buildSliders(); } if (kind === 'quality') this.qSel.value = value; });
      this.keyHandler = e => { if (e.key === (options.key || '`') && !e.ctrlKey && !e.metaKey) { e.preventDefault(); this.toggle(); } };
      (options.keyTarget || root).addEventListener('keydown', this.keyHandler);
      this.buildSliders(); this.shown = false; this.frameSkip = 0;
      if (options.show) this.toggle(true);
    }
    buildSliders() {
      if (!this.root) return; this.sliders.replaceChildren();
      const id = this.manager.activeId; if (!id) return;
      const values = this.manager.presets.get(id);
      const ranges = { intensity: [0, 2, .05], speed: [0, 3, .05], audioSensitivity: [0, 3, .05], smoothing: [.2, 3, .05], bloom: [0, 1.5, .05], opacity: [0, 1, .05], complexity: [.2, 2, .05], motionAmount: [0, 2, .05] };
      for (const [key, value] of Object.entries(values)) {
        if (typeof value !== 'number') continue;
        const [lo, hi, step] = ranges[key] || [0, Math.max(1, value * 3), value >= 10 ? 1 : .05];
        const label = el('label', '', key), input = el('input'), out = el('span', 'pv-val', String(value));
        input.type = 'range'; input.min = String(lo); input.max = String(hi); input.step = String(step); input.value = String(value);
        input.addEventListener('input', () => { const n = Number(input.value); out.textContent = String(n); this.manager.presets.set(id, key, n); });
        label.append(input, out); this.sliders.appendChild(label);
      }
    }
    toggle(force) { if (!this.root) return; this.shown = force == null ? !this.shown : !!force; this.root.classList.toggle('show', this.shown); }
    paint(state) {
      if (!this.shown || !this.root) return;
      if ((this.frameSkip = (this.frameSkip + 1) % 3) !== 0) return;
      const m = this.manager;
      for (const [k, line] of Object.entries(this.lines)) { const v = clamp(state[k] || 0, 0, 1); line.bar.style.width = (v * 100).toFixed(0) + '%'; line.val.textContent = v.toFixed(2); }
      this.fps.textContent = `fps ${m.fps.toFixed(0)}  mode ${m.activeId || '-'}  quality ${m.renderer.quality}  objects ${m.count()}  beats ${state.beatCount}`;
      const info = m.renderer.info; this.stats.textContent = `calls ${info.render.calls}  tris ${info.render.triangles}  points ${info.render.points}  lines ${info.render.lines}\ngeometries ${info.memory.geometries}  textures ${info.memory.textures}  programs ${(info.programs || []).length}` + (m.provider?.name === 'demo' && m.provider.sceneName ? `\nscene ${m.provider.sceneName}` : '');
    }
    dispose() { if (!this.root) return; this.off(); (this.options.keyTarget || root).removeEventListener('keydown', this.keyHandler); this.root.remove(); }
  }

  PineViz.RadioOverlay = RadioOverlay; PineViz.VisualizerSelector = VisualizerSelector; PineViz.DebugHUD = DebugHUD;
})(typeof window !== 'undefined' ? window : globalThis);
