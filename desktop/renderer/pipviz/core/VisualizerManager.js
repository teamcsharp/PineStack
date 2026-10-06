/* PineViz VisualizerManager - owns the loop, the active visualizer and the one coming in, the provider,
 * the processor, the palette, the presets, and the ways to switch (click the background, keys 1-0,
 * the selector). Visualizers are created lazily and kept: switching never rebuilds GPU resources.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp, mulberry32 } = PineViz.util;
  const TRANSITIONS = { crossfade: 0, dissolve: 1, dark: 2 };

  class VisualizerManager {
    /**
     * @param container  the element the canvas fills
     * @param options    {THREE, palette, quality, autoQuality, provider, transition, transitionMs, mode, presets, store, click, keys, demo}
     */
    constructor(container, options = {}) {
      this.THREE = options.THREE || root.THREE;
      if (!this.THREE) throw new Error('PineViz needs THREE on the page before mount()');
      this.container = container;
      this.options = options;
      this.palette = new PineViz.PaletteManager(options.palette || 'playstation');
      this.presets = new PineViz.PresetManager({ key: options.presetKey, store: options.store });
      this.processor = new PineViz.SignalProcessor();
      this.renderer = new PineViz.Renderer(this.THREE, { quality: options.quality || 'high', autoQuality: options.autoQuality, canvas: options.canvas, preserveDrawingBuffer: options.preserveDrawingBuffer });
      this.canvas = this.renderer.canvas;
      Object.assign(this.canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block' });
      this.canvas.className = 'pineviz-canvas';
      if (!options.canvas) container.appendChild(this.canvas);
      this.instances = new Map(); this.active = null; this.incoming = null;
      this.transition = { at: 0, dur: (options.transitionMs || 950) / 1000, mode: TRANSITIONS[options.transition || 'crossfade'] || 0 };
      this.listeners = new Set();
      this.time = 0; this.last = 0; this.raf = 0; this.running = false; this.fps = 60; this.frames = 0; this.fpsAt = 0;
      this.provider = null;
      this.rng = mulberry32(options.seed || 7);
      this.size = { w: 2, h: 2, aspect: 1 };
      this.stateCopy = new PineViz.VisualizerState();
      this.observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => this.resize()) : null;
      if (this.observer) this.observer.observe(container);
      this.palette.onChange(() => { this.renderer.clearColor(this.palette.colors.bg); for (const v of this.instances.values()) v.palette?.(this.palette.colors); });
      this.renderer.onQuality((level, q) => { for (const [id, v] of this.instances) { if (v === this.active || v === this.incoming) this.rebuild(id); else { this.disposeInstance(id); } } this.emit('quality', level); });
      this.presets.onChange((id, key, value) => { const v = this.instances.get(id); if (v) { v.preset = this.presets.get(id); v.presetChanged?.(key, value); } });
      this.renderer.clearColor(this.palette.colors.bg);
      this.clickMode = options.click; if (options.click !== false) this.installClick();
      if (options.keys !== false) this.installKeys();
      this.resize();
      const first = options.mode || this.remembered() || (PineViz.registry[0] && PineViz.registry[0].id);
      if (first) this.set(first, { instant: true });
    }
    /* ---------------------------------------------------------------- providers */
    setProvider(provider) {
      if (this.provider && this.provider !== provider) { try { this.provider.stop?.(); } catch (_) {} }
      this.provider = provider;
      if (provider) { provider.onSample = raw => this.processor.sample(raw); try { provider.start?.(); } catch (e) { this.emit('error', e); } }
      this.emit('provider', provider);
    }
    /* ---------------------------------------------------------------- modes */
    get modes() { return PineViz.modes(); }
    get activeId() { return this.active ? this.active.id : null; }
    remembered() { try { return root.localStorage?.getItem(this.options.modeKey || 'pineviz.mode') || null; } catch (_) { return null; } }
    remember(id) { try { root.localStorage?.setItem(this.options.modeKey || 'pineviz.mode', id); } catch (_) {} }
    context(def) {
      const self = this;
      return {
        THREE: this.THREE, renderer: this.renderer.renderer, gl: this.renderer,
        get palette() { return self.palette.colors; },
        get quality() { return { level: self.renderer.quality, ...self.renderer.q }; },
        get size() { return self.size; },
        preset: this.presets.define(def.id, def.defaults),
        rng: mulberry32((def.index || 1) * 7919 + 17),
        util: PineViz.util,
        manager: this
      };
    }
    instance(id) {
      let v = this.instances.get(id);
      if (v) return v;
      const def = PineViz.registry.find(d => d.id === id);
      if (!def) throw new Error('PineViz: no visualizer ' + id);
      const ctx = this.context(def);
      v = def.create(ctx);
      v.id = def.id; v.def = def; v.ctx = ctx; v.preset = ctx.preset; v.persist = !!def.persist; v.ready = false;
      this.instances.set(id, v);
      return v;
    }
    ensureReady(v) { if (!v.ready) { v.init?.(); v.resize?.(this.size.w, this.size.h); v.ready = true; } return v; }
    rebuild(id) { const v = this.instances.get(id); if (!v) return; try { v.dispose?.(); } catch (_) {} v.ready = false; this.ensureReady(v); if (v === this.active || v === this.incoming) v.activate?.(); }
    disposeInstance(id) { const v = this.instances.get(id); if (!v) return; try { v.deactivate?.(); v.dispose?.(); } catch (_) {} this.instances.delete(id); }
    set(id, options = {}) {
      if (!PineViz.registry.some(d => d.id === id)) return false;
      if (this.active && this.active.id === id && !this.incoming) return true;
      const next = this.ensureReady(this.instance(id));
      if (this.incoming) { try { this.incoming.deactivate?.(); } catch (_) {} this.incoming = null; }
      next.activate?.();
      if (!this.active || options.instant) {
        if (this.active && this.active !== next) { try { this.active.deactivate?.(); } catch (_) {} }
        this.active = next; this.transition.at = 0;
      } else {
        this.incoming = next; this.transition.at = 1e-6;
        this.transition.mode = TRANSITIONS[options.transition] ?? this.transition.mode;
      }
      this.remember(id);
      this.emit('mode', id);
      return true;
    }
    next(step = 1) { const ids = PineViz.registry.map(d => d.id); if (!ids.length) return null; const at = ids.indexOf(this.active?.id); const id = ids[((at < 0 ? 0 : at) + step + ids.length) % ids.length]; this.set(id); return id; }
    setByIndex(index) { const def = PineViz.registry.find(d => d.index === index) || PineViz.registry[index - 1]; if (def) this.set(def.id); return def ? def.id : null; }
    /* ---------------------------------------------------------------- input roads */
    installClick() {
      /* [viz-dblclick] click: true - a click cycles (260 ms wait so a double-click still reaches the surface's owner);
         click: 'double' - a DOUBLE-click cycles and does not reach the owner (the PiP would expand on it); a click is left alone */
      let timer = 0; const dbl = this.clickMode === 'double';
      this.canvas.addEventListener('click', e => {
        if (dbl) return;
        if (e.detail > 1) { clearTimeout(timer); timer = 0; return; }
        clearTimeout(timer);
        timer = setTimeout(() => { timer = 0; this.next(e.shiftKey ? -1 : 1); }, 260);
      });
      this.canvas.addEventListener('dblclick', e => { clearTimeout(timer); timer = 0; if (dbl) { e.stopPropagation(); e.preventDefault(); this.next(e.shiftKey ? -1 : 1); } });
    }
    installKeys() {
      this.keyHandler = e => {
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable) return;
        if (/^[0-9]$/.test(e.key)) { const n = e.key === '0' ? 10 : Number(e.key); if (this.setByIndex(n)) e.preventDefault(); }
        else if (e.key === 'p' || e.key === 'P') this.palette.next();
      };
      (this.options.keyTarget || root).addEventListener('keydown', this.keyHandler);
    }
    /* ---------------------------------------------------------------- the loop */
    resize() {
      const r = this.container.getBoundingClientRect();
      const w = Math.max(2, Math.floor(r.width || this.container.clientWidth || 2)), h = Math.max(2, Math.floor(r.height || this.container.clientHeight || 2));
      if (w === this.size.w && h === this.size.h) return;
      this.size = { w, h, aspect: w / h };
      this.renderer.setSize(w, h);
      for (const v of this.instances.values()) if (v.ready) v.resize?.(w, h);
    }
    start() { if (this.running) return this; this.running = true; this.last = 0; const step = t => { if (!this.running) return; this.raf = root.requestAnimationFrame(step); this.frame(t); }; this.raf = root.requestAnimationFrame(step); return this; }
    stop() { this.running = false; root.cancelAnimationFrame(this.raf); this.raf = 0; return this; }
    frame(now) {
      const t = now / 1000, dt = this.last ? clamp(t - this.last, 1 / 240, .1) : 1 / 60; this.last = t; this.time += dt;
      this.frames++; if (t - this.fpsAt >= .5) { this.fps = this.frames / (t - this.fpsAt); this.frames = 0; this.fpsAt = t; }
      this.provider?.update?.(dt, this.time);
      const state = this.processor.update(dt);
      if (this.active) {
        const p = this.active.preset; const sensed = this.sensed(state, p);
        this.active.update(sensed, dt * (p.speed || 1), this.time * (p.speed || 1));
      }
      let mix = 0;
      if (this.incoming) {
        this.transition.at += dt / this.transition.dur; mix = clamp(this.transition.at, 0, 1);
        const p = this.incoming.preset; this.incoming.update(this.sensed(state, p), dt * (p.speed || 1), this.time * (p.speed || 1));
        if (mix >= 1) { const old = this.active; this.active = this.incoming; this.incoming = null; try { old?.deactivate?.(); } catch (_) {} mix = 0; this.emit('settled', this.active.id); }
      }
      const bloom = this.active ? clamp((this.active.preset.bloom ?? .5), 0, 1.5) : 0;
      this.renderer.draw(this.active, this.incoming, mix, this.transition.mode, this.time, bloom);
      this.renderer.tick(dt);
      this.emit('frame', state);
    }
    /* the visualizer's own sensitivity/smoothing scale what it is handed; the processor stays shared */
    sensed(state, preset) {
      const s = this.stateCopy.copyFrom(state), k = preset.audioSensitivity ?? 1;
      if (k !== 1) { for (const key of ['rms', 'peak', 'bass', 'mid', 'treble', 'beat', 'speechActivity', 'stationActivity', 'energy']) s[key] = clamp(s[key] * k, 0, 1); for (let i = 0; i < s.fft.length; i++) s.fft[i] = clamp(s.fft[i] * k, 0, 1); }
      return s;
    }
    count() { return this.active?.count?.() || 0; }
    on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
    emit(kind, value) { this.listeners.forEach(fn => { try { fn(kind, value, this); } catch (_) {} }); }
    dispose() {
      this.stop(); this.observer?.disconnect(); if (this.keyHandler) (this.options.keyTarget || root).removeEventListener('keydown', this.keyHandler);
      try { this.provider?.stop?.(); } catch (_) {}
      for (const id of [...this.instances.keys()]) this.disposeInstance(id);
      this.renderer.dispose(); this.canvas.remove();
    }
  }
  PineViz.TRANSITIONS = TRANSITIONS; PineViz.VisualizerManager = VisualizerManager;
  /** mount(container, options) -> manager; the one call a host page needs */
  PineViz.mount = (container, options = {}) => {
    const m = new VisualizerManager(container, options);
    if (options.provider) m.setProvider(options.provider);
    else if (options.demo !== false && PineViz.DemoProvider) m.setProvider(new PineViz.DemoProvider());
    if (options.autostart !== false) m.start();
    return m;
  };
})(typeof window !== 'undefined' ? window : globalThis);
