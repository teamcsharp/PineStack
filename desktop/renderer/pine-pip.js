/* Compact the existing window. No new video/audio players or playback clocks.
 * The panel paints its own live video elements into disposable canvas tiles;
 * the desktop overlays widgets from its existing station subscription. */
(function (root) {
  'use strict';

  // This function is injected into the station webview; keep it self contained.
  function pinePipPanel(w) {
    if (w.PinePipPanel) return;
    const doc = w.document;
    let host, background, logo, particles, raf = 0, last = 0, enabled = false, loading;
    let shell = false, otherCount = 0, reportedCount = '', voiceMeters = false, lastMeters = 0;
    /* [pip-viz] the living background: PineViz on the panel's background, fed by this page's analysers and the station's telemetry */
    let viz = null, vizProvider = null, vizLoading = null, vizFailed = false, vizMode = '', telemetry = { speaking: 0, music: 0, activity: 0, at: 0 };
    const programBands = new Float32Array(24); let programLevel = 0;
    let media = [], voiceHead = {}, voiceLevel = 0;
    const voiceBands = new Float32Array(24);
    w.addEventListener('pine-reply-gap', e => { if (e.detail?.phase === 'start') voiceHead = e.detail; });
    let palette = { surface: '8 23 19', text: '#e1f8ea', accent: '#98e9ae', button: '#17382c' };
    const tiles = new Map();
    const previewSelector = 'video.pav-media,#lightboxVid,#lightboxRefVid,.film video,#galleryGrid video';
    /* [pip-once] every source the tube has shown: when, and whether it has left. A source that
       comes back inside SHOWN_ONCE_MS is a repeat and is not tiled; a jump back to the start is one too. */
    const shownSrc = new Map(); const SHOWN_ONCE_MS = 600000;
    function srcOf(v) { return String(v.currentSrc || v.src || (v.srcObject ? 'stream' : '')); }
    function repeatOf(v) {
      if (v.loop) return 'loops';                                        /* a looping element is never program */
      const key = srcOf(v); if (!key || key === 'stream') return '';
      const seen = shownSrc.get(key);
      if (seen && seen.left && Date.now() - seen.left < SHOWN_ONCE_MS) return 'already shown';
      return '';
    }
    function noteShown(v) { const key = srcOf(v); if (key && key !== 'stream') shownSrc.set(key, { at: Date.now(), left: 0 }); if (shownSrc.size > 200) shownSrc.delete(shownSrc.keys().next().value); }
    function noteLeft(v) { const key = srcOf(v); const seen = key ? shownSrc.get(key) : null; if (seen) seen.left = Date.now(); }
    function stopPreview(video) {
      video.autoplay = false; video.loop = false;
      video.muted = true;
      if (!video.paused) video.pause();
    }
    function closePreviews() {
      w.PineAdViewer?.close();
      // Invalidate pending loads and release the preview's audio hold.
      const lightbox = doc.getElementById?.('lightbox');
      if (lightbox && lightbox.style.display !== 'none') w.closeLightbox?.();
      w.lightboxDuckReset?.();
      doc.querySelectorAll(previewSelector).forEach(video => {
        if (video.matches?.(previewSelector)) stopPreview(video);
      });
    }
    function previewPlayback(event) {
      if (!enabled || !event.target.matches?.(previewSelector)) return;
      closePreviews();
      stopPreview(event.target);
    }
    // Catch late H3 loads even when animation frames are throttled.
    doc.addEventListener?.('play', previewPlayback, true);
    doc.addEventListener?.('playing', previewPlayback, true);
    const style = doc.createElement('style');
    style.textContent = 'html.pine-pip{overflow:hidden!important;width:100%;height:100%}'
      + 'html.pine-pip body{overflow:hidden!important;width:100%;height:100%;margin:0!important}'
      + 'html.pine-pip,html.pine-pip *{scrollbar-width:none!important}'
      + 'html.pine-pip::-webkit-scrollbar,html.pine-pip *::-webkit-scrollbar{display:none!important;width:0!important;height:0!important}'
      + '#pine-pip-panel{position:fixed;inset:0;z-index:2147483600;background:rgb(var(--pip-surface,8 23 19));overflow:hidden;display:none}'
      + '#pine-pip-panel>.pip-bg{position:absolute;inset:0;background:radial-gradient(ellipse at 40% 65%,var(--pip-button,#17382c),rgb(var(--pip-surface,8 23 19)) 75%)}'
      + '#pine-pip-panel .pip-logo{position:absolute;left:50%;top:50%;width:8.4%;transform:translate(-50%,-50%);filter:drop-shadow(0 0 24px color-mix(in srgb,var(--pip-accent,#98e9ae) 35%,transparent))}'
      + '#pine-pip-panel .pip-tile{position:absolute;overflow:hidden;background:rgb(var(--pip-surface,8 23 19));transform-origin:center}'
      + '#pine-pip-panel .pip-tile canvas{width:100%;height:100%;object-fit:contain}'
      + '#pine-pip-panel .pip-label{position:absolute;left:6px;top:5px;display:none;font:10px system-ui;color:var(--pip-text,#e1f8ea);background:rgb(var(--pip-surface,8 23 19) / .8);padding:2px 5px;border-radius:3px}'
      + '#pine-pip-panel .pip-failure{position:absolute;bottom:28%;left:12%;right:12%;color:var(--pip-text,#e1f8ea);text-align:center;font:12px system-ui}';
    doc.head.appendChild(style);
    host = doc.createElement('div'); host.id = 'pine-pip-panel';
    background = doc.createElement('div'); background.className = 'pip-bg';
    logo = doc.createElement('img'); logo.className = 'pip-logo'; logo.alt = 'Pine Box';
    host.append(background, logo); doc.body.appendChild(host);
    host.addEventListener('dblclick', () => w.postMessage({ type: 'pine-pip-gesture', action: 'expand' }, '*'));
    host.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); w.postMessage({ type: 'pine-pip-gesture', action: 'menu' }, '*'); });

    /* [pip-viz] the visualizer bundle, from the station's own vendor route (built by tools/pineviz_bundle.py) */
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
      if (w.THREE) return Promise.resolve(w.THREE);
      if (loading) return loading;
      loading = new Promise((resolve, reject) => {
        const tag = doc.createElement('script'); tag.src = '/vendor/three.min.js';
        tag.onload = () => w.THREE ? resolve(w.THREE) : reject(new Error('Three.js unavailable'));
        tag.onerror = () => { loading = null; reject(new Error('Three.js unavailable')); };
        doc.head.appendChild(tag);
      });
      return loading;
    }
    function createParticles(T) {
      const renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(w.devicePixelRatio || 1, 1.5));
      background.appendChild(renderer.domElement);
      const scene = new T.Scene(), camera = new T.PerspectiveCamera(48, 1, .1, 100);
      camera.position.z = 9;
      const count = 1800, positions = new Float32Array(count * 3), seeds = new Float32Array(count * 4);
      for (let i = 0; i < count; i++) { seeds[i * 4] = (Math.random() - .5) * 16; seeds[i * 4 + 1] = Math.random() * Math.PI * 2; seeds[i * 4 + 2] = Math.random() * 2; seeds[i * 4 + 3] = Math.random() * Math.PI * 2; }
      const geo = new T.BufferGeometry(); geo.setAttribute('position', new T.BufferAttribute(positions, 3));
      const mat = new T.PointsMaterial({ color: palette.accent, size: .035, transparent: true, opacity: .65, blending: T.AdditiveBlending, depthWrite: false });
      const cloud = new T.Points(geo, mat); scene.add(cloud);
      let size = '', level = 0, previous = 0;
      const bands = new Float32Array(24);
      return { draw(t, still = false) {
        const dt = previous ? Math.min(.1, t - previous) : 1 / 30; previous = t;
        const targetLevel = still ? 0 : voiceLevel;
        // Quick attack, gentle release: syllables gather the cloud, pauses let it drift.
        level = still ? 0 : level + (targetLevel - level) * (1 - Math.exp(-dt / (targetLevel > level ? .06 : .3)));
        for (let b = 0; b < bands.length; b++) bands[b] = still ? 0 : bands[b] + (voiceBands[b] - bands[b]) * (1 - Math.exp(-dt / (voiceBands[b] > bands[b] ? .05 : .22)));
        const width = host.clientWidth, height = host.clientHeight, next = width + ':' + height;
        if (size !== next) { size = next; renderer.setSize(width, height); camera.aspect = width / Math.max(1, height); camera.updateProjectionMatrix(); }
        for (let i = 0; i < count; i++) {
          const x = seeds[i * 4], a = seeds[i * 4 + 1], r = seeds[i * 4 + 2], phase = seeds[i * 4 + 3];
          const clump = .25 + .75 * (.5 + .5 * Math.sin(t * .19 + x * .38 + phase));
          const bandAt = Math.max(0, Math.min(23, (x + 8) / 16 * 23)), b = Math.floor(bandAt);
          const energy = bands[b] + ((bands[Math.min(23, b + 1)] || 0) - bands[b]) * (bandAt - b);
          const gather = 1 - level * .38, spread = clump * (1 - level * .6);
          const ripple = Math.sin(x * 1.8 - t * 5.5) * energy * .75 + Math.sin(x * .75 + t * 3) * level * .35;
          const staticAmount = .012 + energy * .055;
          positions[i * 3] = x * gather + Math.sin(t * .13 + a) * .7 + Math.sin(t * 31 + phase) * staticAmount;
          positions[i * 3 + 1] = Math.sin(x * .55 + t * .45) * .65 + ripple + Math.cos(a + t * .12) * r * spread - 1 + Math.sin(t * 37 + a) * staticAmount;
          positions[i * 3 + 2] = Math.sin(a + t * .09) * r * spread;
        }
        mat.opacity = .65 + level * .25; mat.size = .035 + level * .012;
        geo.attributes.position.needsUpdate = true; cloud.rotation.z = Math.sin(t * .08) * .14;
        renderer.render(scene, camera);
      }, appearance(next) { mat.color.set(next.accent); }, dispose() { geo.dispose(); mat.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); } };
    }
    function transition(tile, on) {
      if (w.PineVcr) return w.PineVcr.set(tile, on);
      // Same CRT timing as PineVcr for a panel which has not loaded that module.
      const frames = on ? [
        { transform: 'scale(.004,.004)', filter: 'brightness(4)', opacity: 1, offset: 0 },
        { transform: 'scale(1,.006)', filter: 'brightness(3.4)', offset: .34 },
        { transform: 'scale(1,.06)', filter: 'brightness(2)', offset: .58 },
        { transform: 'scale(1)', filter: 'brightness(1)', opacity: 1, offset: 1 }
      ] : [
        { transform: 'scale(1)', opacity: 1, offset: 0 },
        { transform: 'scale(1,.014)', filter: 'brightness(3.2)', offset: .40 },
        { transform: 'scale(1,.006)', filter: 'brightness(5)', offset: .62 },
        { transform: 'scale(.004,.004)', opacity: 0, offset: 1 }
      ];
      tile.getAnimations().forEach(a => a.cancel());
      return tile.animate(frames, { duration: on ? 420 : 460, fill: 'forwards', easing: on ? 'cubic-bezier(.18,.9,.3,1)' : 'cubic-bezier(.7,0,.9,.35)' }).finished.catch(() => false);
    }
    function active(video) {
      if (host.contains(video) || !video.isConnected) return false;
      // Gallery previews are not live program. A late autoplay callback
      // must not resurrect a closed H3 popup behind the compact display.
      if (video.matches(previewSelector)) {
        stopPreview(video);
        return false;
      }
      if (repeatOf(video)) return false;                                  /* [pip-once] */
      const it = tiles.get(video);
      if (it && it.lastTime != null && video.currentTime + 1 < it.lastTime && video.currentTime < 2) { it.rewound = true; }   /* [pip-once] it started over */
      if (it && it.rewound) return false;
      // A buffering player still owns its last picture. Do not collapse the
      // tile merely because the decoder temporarily has no current frame.
      if (video.paused || video.ended || (!tiles.has(video) && (video.readyState < 2 || !video.videoWidth))) return false;
      if (shell) return true;
      for (let n = video; n && n !== doc.body; n = n.parentElement) {
        const cs = w.getComputedStyle(n);
        if (!shell && (n.hidden || cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0)) return false;
      }
      return true;
    }
    function add(video) {
      const tile = doc.createElement('div'); tile.className = 'pip-tile';
      const canvas = doc.createElement('canvas'), label = doc.createElement('span'); label.className = 'pip-label';
      label.textContent = /sfx/i.test(video.id + ' ' + video.className + ' ' + video.parentElement?.className) ? 'SFX' : video.id || 'Live video';
      tile.append(canvas, label); host.appendChild(tile);
      const item = { tile, canvas, label, dirty: true, callback: 0, ctx: canvas.getContext('2d', { alpha: false }), video, src: video.currentSrc || video.srcObject, leaving: false };
      tiles.set(video, item);
      if (video.requestVideoFrameCallback) {
        const decoded = () => {
          item.callback = 0;
          if (!enabled || tiles.get(video) !== item) return;
          item.dirty = true;
          paint(item);
          item.callback = video.requestVideoFrameCallback(decoded);
        };
        item.callback = video.requestVideoFrameCallback(decoded);
      }
      transition(tile, true); return item;
    }
    function layout() {
      const items = [...tiles.values()], count = items.length + otherCount;
      const cols = Math.ceil(Math.sqrt(count)), rows = Math.ceil(count / Math.max(1, cols));
      items.forEach((it, local) => { const i = local + (shell ? otherCount : 0); Object.assign(it.tile.style, { left: (i % cols * 100 / cols) + '%', top: (Math.floor(i / cols) * 100 / rows) + '%', width: (100 / cols) + '%', height: (100 / rows) + '%' }); });
      logo.style.display = count || shell ? 'none' : ''; background.style.display = count || shell ? 'none' : '';
      if (viz) { if (count || shell) viz.stop(); else if (enabled) viz.start(); }   /* [pip-viz] a background under tiles is not drawn */
      const slots = items.filter(it => !it.leaving).map(it => ({ label: it.label.textContent,
        width: it.video.videoWidth, height: it.video.videoHeight, poster: it.video.poster || it.thumbnail || '',
        source: (it.video.title || it.video.getAttribute('aria-label') || String(it.video.currentSrc || '').split('/').pop().split('?')[0] || 'Live stream').slice(0, 200) }));
      const signature = JSON.stringify([items.length, slots]);
      if (reportedCount !== signature) { reportedCount = signature; w.postMessage({ type: 'pine-pip-count', count: items.length, slots }, '*'); }
    }
    function frame(now) {
      if (!enabled) return;
      raf = w.requestAnimationFrame(frame);
      if(doc.hidden||w.__pinePipTools)return;
      if (Math.floor(now / 250) !== frame.clock) {   /* [pip-playbar] the first playing video's clock, four times a second */
        frame.clock = Math.floor(now / 250);
        const first = [...tiles.values()].find(it => !it.leaving && Number.isFinite(it.video.duration) && it.video.duration > 0);
        const time = first ? { at: first.video.currentTime, dur: first.video.duration, playing: !first.video.paused && !first.video.ended } : null;
        const key = time ? Math.round(time.at * 4) + ':' + Math.round(time.dur) + ':' + time.playing : '';
        if (frame.told !== key) { frame.told = key; w.postMessage({ type: 'pine-pip-time', time }, '*'); }
      }
      if (Math.floor(now / 500) !== frame.scan) {
        frame.scan = Math.floor(now / 500);
        media = [...doc.querySelectorAll('audio,video')];
        const videos = new Set(media.filter(v => v.tagName === 'VIDEO' && active(v)));
        videos.forEach(v => { if (!tiles.has(v)) { add(v); noteShown(v); } else if (tiles.get(v).leaving) { tiles.get(v).leaving = false; transition(tiles.get(v).tile, true); } });
        tiles.forEach((it, v) => { if (!it.leaving) it.lastTime = v.currentTime; });   /* [pip-once] where each tube's picture stands */
        tiles.forEach((it, v) => {
          if (!videos.has(v) && !it.leaving) {
            it.leaving = true; noteLeft(v);                               /* [pip-once] */
            transition(it.tile, false).then(() => { if (tiles.get(v) === it && it.leaving) { if (it.callback) v.cancelVideoFrameCallback?.(it.callback); it.tile.remove(); tiles.delete(v); layout(); } });
          }
        });
        layout();
      }
      tiles.forEach(it => {
        // Modern players paint at the decoded frame cadence. Older players
        // use the display cadence without an extra 30 fps sampling clock.
        if (!it.video.requestVideoFrameCallback || it.dirty) paint(it);
      });
      if ((voiceMeters || (!shell && !tiles.size && !otherCount)) && now - lastMeters >= 70) {
        lastMeters = now;
        voiceLevel = 0; voiceBands.fill(0);
        const readings = [];
        for (const el of media) {
          if (el.paused || el.ended || !/voice|reply|sfx/i.test(el.dataset.pineLive || el.id)) continue;
          // Borrow the player's existing scope: never build a second audio route.
          // audioScope can create a media source; a suspended graph would silence
          // a native player. Only sample while the player's shared graph is awake.
          if (w.pineAudioCtx?.state !== 'running') continue;
          let scope;
          try { scope = typeof w.audioScope === 'function' ? w.audioScope(el) : null; } catch (_) { continue; }
          if (!scope?.analyser) continue;
          const bins = scope.bins || new Uint8Array(scope.analyser.frequencyBinCount);
          scope.analyser.getByteFrequencyData(bins);
          let sum = 0; for (const n of bins) sum += n * n;
          const bars = []; const step = Math.max(1, Math.floor(bins.length / 24));
          for (let i = 0; i < 24; i++) { let value = 0; for (let j = 0; j < step; j++) value += bins[i * step + j] || 0; bars.push(Math.min(1, value / step / 180)); }
          const level = Math.min(1, Math.sqrt(sum / Math.max(1, bins.length)) / 128);
          voiceLevel = Math.max(voiceLevel, level);
          bars.forEach((value, b) => { voiceBands[b] = Math.max(voiceBands[b], value); });
          readings.push({ bars, who: el.dataset.pineSting === '1' ? 'sfx' : el.dataset.speaker || el.pineDeliveryClip?.who || el.pineDeliveryClip?.name || voiceHead.who || voiceHead.name || '', level });
        }
        if (voiceMeters) w.postMessage({ type: 'pine-pip-voices', readings }, '*');
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
      }
      if (!tiles.size && !otherCount && particles && now - last >= 33) {
        last = now;
        // Render a still cloud for reduced motion, including its first frame.
        const still = w.matchMedia('(prefers-reduced-motion: reduce)').matches;
        particles.draw(still ? 0 : now / 1000, still);
      }
    }
    function paint(it) {
        if(it.leaving||doc.hidden||w.__pinePipTools)return;
        const v = it.video;
        if (v.readyState < 2 || !v.videoWidth || !v.videoHeight) return;
        if ((v.currentSrc || v.srcObject) !== it.src) {
          // Keep the old canvas until the replacement has a drawable frame.
          // A source cut must not add another close/open animation in PiP.
          it.src = v.currentSrc || v.srcObject; it.thumbnail = ''; it.dirty = true;
        }
        if (v.requestVideoFrameCallback && !it.dirty) return;
        it.dirty = false;
        const width = Math.max(1, Math.min(v.videoWidth, 960, Math.ceil(it.tile.clientWidth * Math.min(w.devicePixelRatio || 1, 1.5)))), height = Math.round(width * v.videoHeight / Math.max(1, v.videoWidth));
        if (it.canvas.width !== width || it.canvas.height !== height) { it.canvas.width = width; it.canvas.height = height; }
        try { it.ctx.drawImage(v, 0, 0, width, height);
          if (!it.thumbnail && !v.poster) {
            const preview = doc.createElement('canvas'); preview.width = 80; preview.height = Math.max(1, Math.round(80 * height / width));
            try { preview.getContext('2d').drawImage(it.canvas, 0, 0, preview.width, preview.height); it.thumbnail = preview.toDataURL('image/jpeg', .65); layout(); } catch (_) { it.thumbnail = 'unavailable'; }
          }
        } catch (_) { /* retain last drawable frame */ }
    }
    w.PinePipPanel = { appearance(next) {
      palette = next;
      for (const key of ['surface', 'text', 'accent', 'button']) host.style.setProperty('--pip-' + key, palette[key]);
      particles?.appearance(palette);
      if (viz) { vizPalette(w.PineViz); viz.palette.set('pinepip'); }   /* [pip-viz] the theme is the background's palette */
    }, meters(on) { voiceMeters = !!on; }, layout(count) { otherCount = Number(count) || 0; layout(); },
    /* [pip-viz] what the station is doing, from the shell: a muted PiP still breathes with it */
    telemetry(next) { if (next && typeof next === 'object') telemetry = { speaking: Number(next.speaking) || 0, music: Number(next.music) || 0, activity: Number(next.activity) || 0, at: Date.now() }; },
    /* [pip-viz] the background mode: a name, 'next', or nothing to read it */
    background(mode) { if (!viz) return { mode: vizMode, modes: w.PineViz ? w.PineViz.modes() : [] }; if (mode === 'next') viz.next(); else if (mode === 'previous') viz.next(-1); else if (mode) viz.set(String(mode)); return { mode: viz.incoming ? viz.incoming.id : viz.activeId, modes: viz.modes }; },
    viz() { return viz; },   /* [pip-viz] the manager, for the HUD and the tests */
    set(on, logoSrc, isShell) {
      shell = !!isShell;
      if (shell) { host.style.zIndex = '20001'; host.style.background = 'transparent'; host.style.pointerEvents = 'none';  }
      if (logoSrc) logo.src = logoSrc;
      enabled = !!on; host.style.display = enabled ? 'block' : 'none';
      doc.documentElement.classList.toggle('pine-pip', enabled);
      w.cancelAnimationFrame(raf);
      if (enabled) {
        closePreviews();
        last = 0; lastMeters = 0; voiceLevel = 0; voiceBands.fill(0); raf = w.requestAnimationFrame(frame);
        /* [pip-viz] the living background first; the particle cloud only when the bundle cannot be had */
        if (!shell && viz) viz.start();
        if (!shell && !viz && !particles) three().then(T => {
          if (!enabled || shell) return;
          if (vizFailed) { if (!particles) particles = createParticles(T); return; }
          return vizLibrary().then(P => { if (enabled && !shell) mountViz(P); }).catch(() => { vizFailed = true; if (enabled && !shell && !particles) particles = createParticles(T); });
        }).catch(() => {
          if (!host.querySelector('.pip-failure')) { const note = doc.createElement('span'); note.className = 'pip-failure'; note.textContent = 'Particle visualization unavailable'; host.appendChild(note); }
        });
      } else {
        tiles.forEach(it => { if (it.callback) it.video.cancelVideoFrameCallback?.(it.callback); w.PineVcr?.cancel(it.tile); it.tile.getAnimations().forEach(a => a.cancel()); it.tile.remove(); }); tiles.clear();
        if (particles) { particles.dispose(); particles = null; } reportedCount = ''; otherCount = 0; voiceLevel = 0; voiceBands.fill(0);
        if (viz) viz.stop();   /* [pip-viz] kept for the next entry; nothing rebuilt */
      }
    } };
  }

  let state, overlay, frame, leave, timer, diceScene, diceRaf = 0, productionBusy = false, voiceTimer, portraitsBusy = false;
  let lastPayload, liveSpeaker = '', portraitPool = [], castSignature = '';
  const castMembers = {}, voiceReadings = { panel: [], shell: [] };
  let cursor = { s3: 0, n: 0, t: 0 }, station, track, roll = null, seen = new Set(), flow = [], production = [];
  let panelReady = false, entering = false, shellCount = 0, panelCount = 0, currentLine = '', rollLine = '', activeRolls = [], activeRollIndex = 0;
  let painting, paintingKey = '', paintingTimer, slateTimers = [], slateDrag;
  const widgets = {}, api = () => root.pineDesktop;
  let sharedReady = false, sharedLoading = false, sharedSignature = '', sharedSaveTimer = 0;
  function sharedPreferences(value) {
    const out = {};
    for (const key of ['popupFavorites','ui','aspectMode','cameraOverlay','cameraOnly','cameraSource','cameraBounds','messageBounds','messageTile','roulettePosition','theme','transparency','widgets','docks','order','voiceStyles','musicPosition','musicExpanded','musicArtOnly','layout']) out[key] = value[key];
    return out;
  }
  function publishShared(value) {
    if (!sharedReady || sharedLoading || !api()?.post) return;
    const prefs = sharedPreferences(value), signature = JSON.stringify(prefs);
    if (signature === sharedSignature) return;
    clearTimeout(sharedSaveTimer);
    sharedSaveTimer = setTimeout(() => api().post('/api/pip/config', prefs).then(result => {
      sharedSignature = JSON.stringify(sharedPreferences(result.settings || prefs));
    }).catch(() => {}), 250);
  }
  const videoSlots = { panel: [], shell: [] };
  let camera, cameraImage, cameraStatus, cameraTimer, cameraPoll, cameraGeneration = 0, cameraBase = '', cameraStream = '', cameraQuery = '', cameraStill = '', cameraSourceActive = '', cameraFailed = 0, cameraLive = false, cameraFramePending = false, cameraDrag, exportBusy = false;
  const cameraLabel = () => ({ pine: 'Pine Cam', 'tab-front': 'PineTab front camera', 'tab-rear': 'PineTab rear camera' }[state?.cameraSource || 'pine']);
  const tabletFacing = () => state?.cameraSource === 'tab-front' ? 'front' : 'rear';
  function node(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function say(text, duration = 5000) {
    if (!overlay) return;
    let note = overlay.querySelector('.pip-note'); if (!note) { note = node('div', 'pip-note'); note.setAttribute('role', 'status'); overlay.appendChild(note); }
    note.textContent = text; clearTimeout(say.timer); if (duration > 0) say.timer = setTimeout(() => note.remove(), duration);
  }
  let menuPending = false, playbackCache = {}, playbackAt = 0, playbackPending = false;
  async function showMenu() {
    if (menuPending || !state?.active) return;
    menuPending = true;
    try {
      const favorites=(root.PinePipPopups?.catalog?.()||[]).map(({id,label})=>({id,label}));
      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin});   /* [pip-video-folder] */
      refreshFolders();
      refreshPlayback();
      await opening;
    } finally { menuPending = false; }
  }
  /* [pip-video-folder] every folder of the SFX collection and the hour's pin, for the menu; a minute old at most */
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
    if(playbackPending || Date.now()-playbackAt<3000)return;playbackPending=true;
    Promise.resolve().then(()=>api().get('/api/sfx/video/mode')).then(value=>{playbackCache=value||{};playbackAt=Date.now();}).catch(()=>{}).finally(()=>{playbackPending=false;});
  }
  const themes = {
    pine: ['Pine green', '8 23 19', '#e1f8ea', '#98e9ae', '#17382c'],
    midnight: ['Midnight blue', '10 20 38', '#e1edff', '#8ac5ff', '#1c3559'],
    plum: ['Plum', '30 15 36', '#f5e6ff', '#dbadff', '#493052'],
    amber: ['Amber', '32 23 10', '#fff1d5', '#ffd180', '#4e381c'],
    graphite: ['Graphite', '22 24 28', '#f0f1f4', '#bdc6d4', '#353a43']
  };
  function themePalette(next = state) {
    const [, surface, text, accent, button] = themes[next?.theme] || themes.pine;
    return { surface, text, accent, button };
  }
  function applyAppearance(next) {
    const palette = themePalette(next);
    const { surface, text, accent, button } = palette;
    for (const [key, value] of Object.entries(palette)) document.documentElement.style.setProperty('--pip-' + key, value);
    root.PinePipPanel?.appearance(palette);
    diceScene?.material.color.set(accent);
    diceScene?.light.color.set(text);
    diceScene?.ambient.color.set(text);
    overlay.style.setProperty('--pip-surface', surface);
    overlay.style.setProperty('--pip-text', text);
    overlay.style.setProperty('--pip-accent', accent);
    overlay.style.setProperty('--pip-button', button);
    overlay.style.setProperty('--pip-opacity', String(1 - (next.transparency ?? 15) / 100));
    const panel = overlay.querySelector('.pip-appearance');
    if (panel) {
      panel.querySelector('select').value = next.theme || 'pine';
      panel.querySelector('input').value = next.transparency ?? 15;
      panel.querySelector('output').textContent = (next.transparency ?? 15) + '%';
    }
  }
  function showAppearance() {
    let panel = overlay.querySelector('.pip-appearance');
    if (!panel) {
      panel = node('section', 'pip-appearance'); panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'PiP appearance');
      const header = node('header', '', 'PiP appearance'), close = node('button', '', '\u00d7');
      close.type = 'button'; close.setAttribute('aria-label', 'Close appearance settings'); close.onclick = () => { panel.hidden = true; };
      header.appendChild(close);
      const themeLabel = node('label', '', 'Color theme'), select = node('select');
      select.setAttribute('aria-label', 'Color theme');
      for (const [key, [title]] of Object.entries(themes)) { const option = node('option', '', title); option.value = key; select.appendChild(option); }
      select.onchange = () => api().pipUpdate({ theme: select.value }).catch(e => say(e.message)); themeLabel.appendChild(select);
      const label = node('label', '', 'Overlay transparency'), slider = node('input'), output = node('output');
      slider.type = 'range'; slider.min = '0'; slider.max = '90'; slider.step = '1'; slider.setAttribute('aria-label', 'Overlay transparency');
      slider.oninput = () => { overlay.style.setProperty('--pip-opacity', String(1 - Number(slider.value) / 100)); output.textContent = slider.value + '%'; };
      slider.onchange = () => api().pipUpdate({ transparency: Number(slider.value) }).catch(e => say(e.message));
      label.append(slider, output); panel.append(header, themeLabel, label, node('small', '', '0% is solid. 90% is mostly transparent.'));
      panel.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); panel.hidden = true; } });
      overlay.appendChild(panel);
    }
    panel.hidden = false; applyAppearance(state); panel.querySelector('select').focus();
  }
  function marquee(widget, text, immediate = false) {
    const viewport = widget.querySelector('.pip-marquee');
    if (!viewport) return;
    if (viewport.dataset.text === text) { viewport.pending = null; return; }
    // Do not restart a running strip on each poll: commit at the loop boundary.
    viewport.pending = String(text || 'Waiting for station activity');
    if (viewport.firstChild) { if ((immediate || /^Waiting for /.test(viewport.dataset.text || '')) && viewport.commit) { viewport.commit(); const strip = viewport.firstChild; strip.style.animation = 'none'; void strip.offsetWidth; strip.style.animation = ''; } return; }
    const strip = node('div', 'pip-track'); viewport.appendChild(strip);
    const fill = () => {
      if (viewport.pending == null) return;
      const text = viewport.pending; viewport.pending = null; viewport.dataset.text = text;
      strip.replaceChildren(node('span', '', text), node('span', '', text));
      strip.style.setProperty('--pip-duration', Math.max(14, text.length / 9) + 's');
    };
    viewport.commit = fill; fill(); strip.addEventListener('animationiteration', fill);
  }
  /* [pip-free] ----------------------------------------------------------------------------------
     Every widget carries a layout entry {x,y,w,h,s,t,o} (window shares, a scale, four trims in
     % of the widget, an opacity). Widgets with a place of their own (the player, the message
     tile, the slate, the camera) keep their own position preferences; the entry adds the rest.
     Docked widgets leave the dock when placed (x,y) and return when docked again or reset. */
  const DOCK_ZONE = 34, OWN_PLACE = new Set(['music', 'messages', 'roulette', 'camera']), FREE_NAMES = ['dialogue', 'task', 'audit', 'production', 'music', 'chat', 'messages', 'cast', 'voices', 'roulette', 'camera', 'rec'];
  const WIDGET_WORDS = { dialogue: 'Dialogue + rolling dice', task: 'Task status marquee', audit: 'Station audit marquee', production: 'Production marquee', music: 'Music player', chat: 'Chat + roulette + SFX feed', messages: 'System3 message tile', cast: 'DJ booth cast portraits', voices: 'Voice bubbles + falling peaks', roulette: 'Roulette slate', camera: 'Pine Cam', rec: 'Album recorder' };
  const DEFAULT_LAYOUT = { rec: { x: .3, y: .5 } };   /* [pip-rec] a widget born free sits here until it is moved */
  let layoutSaveTimer = 0, layoutPending = {}, adjustFor = '';
  function freeBox(name) { return name === 'camera' ? camera : widgets[name]; }
  function layoutOf(name) { const entry = state?.layout?.[name]; return entry && typeof entry === 'object' ? entry : (DEFAULT_LAYOUT[name] || null); }
  function dockable(name) { return !OWN_PLACE.has(name) && name !== 'chat' && name !== 'voices' && name !== 'rec'; }
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
  /* [pip-rec] ------------------------------------------------------------------------------------
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
    const handle = given || node('button', 'pip-grip', '\u283f'); handle.type = 'button'; if (!given) handle.title = 'Drag to reorder or dock at top / bottom';
    handle.setAttribute('aria-label', 'Move ' + name + ' widget'); if (!given) widget.prepend(handle);
    handle.addEventListener('keydown', e => {
      if (placedFreely(name) && e.key.startsWith('Arrow') && !e.ctrlKey && !e.altKey) {   /* [pip-free] a placed widget is nudged; Shift takes bigger steps */
        e.preventDefault(); const step = (e.shiftKey ? 24 : 6), b = freeBox(name) || widget;
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0, dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
        saveLayout(name, { x: (b.offsetLeft + dx) / innerWidth, y: (b.offsetTop + dy) / innerHeight }); return;
      }
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault(); const dock = e.key === 'Home' ? 'top' : e.key === 'End' ? 'bottom' : state.docks[name];
      const order = (Number(state.order[name]) || 0) + (e.key === 'ArrowUp' ? -1 : 1);
      api().pipUpdate({ docks: { [name]: dock }, order: { [name]: order } }).catch(err => say(err.message));
    });
    /* [pip-free] The handle drags the widget anywhere. Dropped within DOCK_ZONE of the top or
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
  }
  /* [pip-music] THE MUSIC PLAYER IS A MINI PLAYER, PLACED FREELY.
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
  let musicDrag = null, musicSpot = null, musicBig = false, musicTimer = 0, musicClock = null, musicPop = '', musicArtPress = null;   /* [pip-art] */
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
    box.classList.toggle('art-only', !!state?.musicArtOnly);   /* [pip-art] */
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
  /* [pip-levels] "Allow me to adjust the volume of all the items in the mixer, but definitely the music
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
  /* [pip-find] "When searching for a song, show suggestive search results as i type. So I can click on
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
    /* [pip-art] a record without artwork is a 404 on the art route: the placeholder stands in, and the broken picture never shows */
    if (src && art.getAttribute('src') !== src) { art.dataset.failed = ''; art.src = src; }
    const shown = !!src && art.dataset.failed !== src;
    art.hidden = !shown; blank.hidden = shown;
    box.classList.toggle('art-only', !!state?.musicArtOnly);
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
    /* [pip-art] a picture that does not load gives way to the placeholder; a double-click on either
       reduces the player to the artwork alone, and a second one brings the player back */
    art.addEventListener('error', () => { art.dataset.failed = art.getAttribute('src') || 'x'; art.hidden = true; blank.hidden = false; });
    art.title = 'Double-click: show only the artwork'; blank.title = 'Double-click: show only the artwork';
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
  function build() {
    overlay = node('div'); overlay.id = 'pinePipWidgets';
    const drag = node('div', 'pip-drag-surface'); drag.title = 'Drag to move Pine PIP; right-click for options';
    overlay.append(drag, node('div', 'pip-dock pip-dock-top'), node('div', 'pip-dock pip-dock-bottom'));
    buildAudio();
    buildCamera();
    buildSlate(); buildPainting(); buildMessages();
    const cast = node('div', 'pip-widget pip-cast'); widgets.cast = cast; grip(cast, 'cast'); overlay.querySelector('.pip-dock-bottom').appendChild(cast);
    const voices = node('div', 'pip-voices'); widgets.voices = voices; overlay.appendChild(voices);
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
    for (const [key, title] of [['host', 'Host'], ['cohost', 'Co-host'], ['sfx', 'SFX'], ['callers', 'Callers']]) {
      const bubble = node('div', 'pip-voice ' + key); bubble.setAttribute('role', 'meter'); bubble.setAttribute('aria-label', title + ' voice level');
      bubble.setAttribute('aria-valuemin', '0'); bubble.setAttribute('aria-valuemax', '100');
      const image = node('img'); image.alt = ''; image.hidden = true;
      const wave = node('canvas', 'pip-waveform'); wave.setAttribute('aria-hidden', 'true');
      bubble.append(wave, node('span', '', title), node('i', 'pip-peak')); voices.appendChild(bubble);
      castMembers[key] = { title, bubble, level: 0, peak: 0, image, portrait: '' };
    }
    for (const name of ['dialogue', 'task', 'audit', 'production']) {
      const widget = node('div', 'pip-widget'); widgets[name] = widget; widget.dataset.widget = name;
      grip(widget, name);
      if (name === 'dialogue') { const die = node('div', 'pip-dice'); die.append(node('output', '', '\u2014')); widget.appendChild(die); }
      const viewport = node('div', 'pip-marquee'); viewport.title = name; widget.appendChild(viewport); marquee(widget, 'Waiting for ' + name);
      overlay.querySelector('.pip-dock-bottom').appendChild(widget);
    }
    buildMusic();   /* [pip-music] a mini player placed freely, not a strip in the top dock */
    buildRecorder();   /* [pip-rec] the album recorder, placed freely */
    const chat = node('section', 'pip-widget pip-chat'); widgets.chat = chat;
    const header = node('header', '', 'Live feed \u00b7 roulette \u00b7 SFX'); grip(header, 'chat'); chat.append(header, node('small', 'pip-sfx-slots', 'SFX slot: idle'), node('div', 'pip-chat-list')); overlay.appendChild(chat);
    overlay.addEventListener('contextmenu', e => {
      e.preventDefault(); e.stopPropagation();
      /* [pip-free] a right-click on a widget's own handle opens its layout options instead of the menu */
      const handle = e.target.closest('.pip-grip, .pip-camera-move, .pip-free-edge, .pip-messages header, .pip-slate header');
      const name = handle ? widgetNameOf(handle) : (e.altKey || (e.target.closest('.pip-music') && !e.target.closest('button, input, .pip-music-pop'))) ? widgetNameOf(e.target) : '';
      if (name) { showAdjust(name, handle || freeBox(name)); return; }   /* a trimmed widget may hide its handle: Alt + right-click on it, or the menu's Widget layout */
      showMenu().catch(err => say(err.message));
    }, true);
    overlay.addEventListener('dblclick', e => { if (!e.target.closest('button, input, select, label, .pip-volume-panel, .pip-appearance, .pip-message-settings, .pip-camera, .pip-messages, .pip-music')) expand(); });
    document.body.appendChild(overlay);
  }
  let messageTile=null,messageHover=false,messageDrag=null,messageBoundsDraft=null,messageFontDraft=null,messageLayout=null,messageClickUntil=0,messagePlaceRaf=0;
  const MESSAGE_TILE_DEFAULTS={mode:'hold',fontSize:12,opacity:.85,rollSpeed:1,typingSpeed:1,followPlayback:true,fadeDelay:4};
  function messageTileOptions(value=state?.messageTile){return {...MESSAGE_TILE_DEFAULTS,...value};}
  function placeMessages(bounds=messageBoundsDraft||state?.messageBounds){
    const box=widgets.messages;if(!box)return;const b=bounds||{x:.02,y:.04,width:.44,height:.34};
    const wrapWidth=Math.min(innerWidth,Math.max(Math.min(140,innerWidth),b.width*innerWidth));
    // Content can grow below this anchor, but cannot move or scale the item.
    const left=Math.max(0,Math.min(innerWidth-wrapWidth,b.x*innerWidth));
    const top=Math.max(0,Math.min(Math.max(0,innerHeight-32),b.y*innerHeight));
    const availableHeight=Math.max(1,innerHeight-top);
    const stage=messageTile?.element||box.querySelector('.pip-system3-stage');
    let review=null;
    // Establish the held viewport before measuring, so review panes never
    // briefly expand and clamp the reader's independent scroll positions.
    if(messageTile?.state().reviewing&&!messageDrag){
      box.__messageReviewLayout ||= {left,top,width:wrapWidth,wrapWidth,...messageLayout,height:Math.min(availableHeight,Math.max(messageLayout?.height||0,Math.min(availableHeight,(b.height||.25)*innerHeight)))};
      review=box.__messageReviewLayout;
      review.width=Math.min(review.width,innerWidth);review.wrapWidth=review.width;
      review.left=Math.max(0,Math.min(innerWidth-review.width,review.left));
      review.top=Math.max(0,Math.min(Math.max(0,innerHeight-32),review.top));
      review.height=Math.min(review.height,Math.max(1,innerHeight-review.top));
    }else box.__messageReviewLayout=null;
    let naturalHeight=24;
    if(stage){
      const paneWidth=review?.wrapWidth||wrapWidth,paneBudget=review?.height||availableHeight;
      stage.style.width=paneWidth+'px';stage.style.maxHeight=paneBudget+'px';stage.style.transform='';stage.style.transformOrigin='';
      // The shared card divides this physical viewport budget by its font zoom.
      // Pane limits use the screen budget, so growing reels cannot resize the header.
      stage.style.setProperty('--pip-message-max-height',paneBudget+'px');
      if(messageFontDraft!=null){stage.style.setProperty('--pip-message-font',messageFontDraft+'px');stage.style.setProperty('--pip-message-scale',String(messageFontDraft/12));}
      // Measure rendered pane-constrained cards without uncapping either scroll pane.
      const stageTop=stage.getBoundingClientRect().top,scrollTop=stage.scrollTop;
      const children=Array.from(stage.children).filter(child=>!child.hidden);
      naturalHeight=Math.max(1,...children.map(child=>child.getBoundingClientRect().bottom-stageTop+scrollTop));
    }
    // A review session keeps its viewport and controls still while replies arrive.
    if(review){
      box.style.width=review.width+'px';box.style.height=review.height+'px';box.style.left=review.left+'px';box.style.top=review.top+'px';
      if(stage)stage.style.height=review.height+'px';
      messageLayout={...review,naturalHeight,scrolling:naturalHeight>review.height,...messagePaneScrolling(stage)};return;
    }
    const height=Math.min(naturalHeight,availableHeight);
    box.style.width=wrapWidth+'px';box.style.height=height+'px';box.style.left=left+'px';box.style.top=top+'px';
    if(stage)stage.style.height=height+'px';
    messageLayout={left,top,width:wrapWidth,height,wrapWidth,naturalHeight,availableHeight,scale:1,scrolling:naturalHeight>height,...messagePaneScrolling(stage)};
  }
  function messagePaneScrolling(stage){
    const words=stage?.querySelectorAll('.pip-system3-words')||[],rolls=stage?.querySelectorAll('.pip-system3-rolls')||[];
    const overflows=panes=>Array.from(panes).some(pane=>!pane.hidden&&pane.scrollHeight>pane.clientHeight+1);
    return {textScrolling:overflows(words),rouletteScrolling:overflows(rolls)};
  }
  function requestMessagePlacement(){
    if(messagePlaceRaf)return;
    messagePlaceRaf=requestAnimationFrame(()=>{messagePlaceRaf=0;placeMessages();});
  }
  function mountMessageTile(into){
    return root.PineSystem3MessageTile.mount(into,{make:node,load:(row,payload,mode)=>root.PineMessageView.tileData(row,payload,mode),
      wireEntry:(element,rows,index,which)=>root.PineMessageView.tileEntry?.(element,rows,index,which),
      clock:()=>root.PineStationFeed?.clock?root.PineStationFeed.clock():Date.now(),options:messageTileOptions(),onLayout:info=>{const box=widgets.messages;if(box.__messageObservedItem!==info.item){if(box.__messageObservedItem)box.__messageObserver?.unobserve(box.__messageObservedItem);box.__messageObservedItem=info.item;if(info.item)box.__messageObserver?.observe(info.item);}placeMessages();}});
  }
  function messageTileState(){
    if(!messageTile)return;
    const panes=messagePaneScrolling(messageTile.element);
    return {...messageTile.state(),geometry:messageLayout?{...messageLayout,...panes,scrolling:messageLayout.scrolling||panes.textScrolling||panes.rouletteScrolling}:null};
  }
  function buildMessages(){
    const box=node('section','pip-widget pip-messages');widgets.messages=box;box.dataset.widget='messages';box.setAttribute('aria-label','System3 message tile');box.tabIndex=0;
    box.title='Use the arrows to review messages; move away to show the latest; drag to move; resize at the edges; hold Shift to select text; right-click for options';
    overlay.appendChild(box);
    box.addEventListener('pointerenter',e=>{if(e.pointerType==='touch')return;messageHover=true;messageTile?.hold(true);});
    box.addEventListener('pointerleave',()=>{messageHover=false;messageTile?.hold(false);});
    // Pointer-only edge hit areas stay invisible; the item itself is the handle.
    for(const edge of ['n','s','e','w','ne','nw','se','sw']){const hit=node('span','pip-messages-edge '+edge);hit.dataset.edge=edge;hit.setAttribute('aria-hidden','true');box.appendChild(hit);}
    function save(){
      if(!messageLayout)return;const draft=messageBoundsDraft,font=messageFontDraft;
      const update={messageBounds:{x:messageLayout.left/innerWidth,y:messageLayout.top/innerHeight,width:messageLayout.wrapWidth/innerWidth,height:messageLayout.height/innerHeight}};
      if(font!=null)update.messageTile={fontSize:font};
      return api().pipUpdate(update).catch(e=>say(e.message)).finally(()=>{if(messageBoundsDraft===draft&&!messageDrag){messageBoundsDraft=null;messageFontDraft=null;placeMessages();}});
    }
    box.addEventListener('pointerdown',e=>{
      if(e.button!==0||e.isPrimary===false||e.shiftKey||e.target.closest('button,input,select,a'))return;
      const edge=e.target.closest('.pip-messages-edge')?.dataset.edge||'';
      if(e.pointerType==='touch'&&!edge&&e.target.closest('.pip-system3-words,.pip-system3-rolls'))return;
      placeMessages();const rect=box.getBoundingClientRect();
      messageDrag={id:e.pointerId,x:e.clientX,y:e.clientY,edge,target:edge?e.target:box,moved:!!edge,rect:{left:rect.left,top:rect.top,width:rect.width,height:rect.height},font:messageFontDraft??messageTileOptions().fontSize,
        bounds:{x:rect.left/innerWidth,y:rect.top/innerHeight,width:messageLayout.wrapWidth/innerWidth,height:rect.height/innerHeight}};
      if(edge){e.preventDefault();messageDrag.target.setPointerCapture(e.pointerId);}box.focus({preventScroll:true});
    });
    root.addEventListener('pointermove',e=>{
      const drag=messageDrag;if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
      if(!drag.moved){if(Math.hypot(dx,dy)<5)return;drag.moved=true;drag.target.setPointerCapture(e.pointerId);const selection=root.getSelection?.();if(selection&&box.contains(selection.anchorNode))selection.removeAllRanges();}
      e.preventDefault();const b={...drag.bounds};
      if(!drag.edge){b.x=(drag.rect.left+dx)/innerWidth;b.y=(drag.rect.top+dy)/innerHeight;box.classList.add('moving');}
      else{
        if(/[ew]/.test(drag.edge)){const delta=drag.edge.includes('w')?-dx:dx;b.width=(drag.bounds.width*innerWidth+delta)/innerWidth;}
        if(/[ns]/.test(drag.edge)){const delta=drag.edge.includes('n')?-dy:dy;messageFontDraft=Math.max(8,Math.min(28,Math.round(drag.font*(1+delta/Math.max(1,drag.rect.height)))));}
      }
      messageBoundsDraft=b;placeMessages(b);
      if(drag.edge.includes('w'))b.x=(drag.rect.left+drag.rect.width-messageLayout.width)/innerWidth;
      if(drag.edge.includes('n'))b.y=(drag.rect.top+drag.rect.height-messageLayout.height)/innerHeight;
      placeMessages(b);
    },{passive:false});
    const finish=e=>{
      const drag=messageDrag;if(!drag||drag.id!==e.pointerId)return;messageDrag=null;box.classList.remove('moving');
      if(drag.target.hasPointerCapture(e.pointerId))drag.target.releasePointerCapture(e.pointerId);
      if(drag.moved){messageClickUntil=Date.now()+250;save();}
    };
    root.addEventListener('pointerup',finish);root.addEventListener('pointercancel',finish);
    box.addEventListener('click',e=>{if(Date.now()<messageClickUntil){e.preventDefault();e.stopImmediatePropagation();}},true);
    box.addEventListener('keydown',e=>{
      if(e.target!==box)return;const d={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]}[e.key];if(!d)return;
      e.preventDefault();placeMessages();const b={x:messageLayout.left/innerWidth,y:messageLayout.top/innerHeight,width:messageLayout.wrapWidth/innerWidth,height:messageLayout.height/innerHeight};
      if(e.shiftKey){if(d[0])b.width+=d[0]/innerWidth;else messageFontDraft=Math.max(8,Math.min(28,messageTileOptions().fontSize+(d[1]>0?1:-1)));}
      else{b.x+=d[0]/innerWidth;b.y+=d[1]/innerHeight;}
      messageBoundsDraft=b;placeMessages(b);save();
    });
    const resize=typeof root.ResizeObserver==='function'?new root.ResizeObserver(requestMessagePlacement):null;
    box.__messageObserver=resize;
    root.addEventListener('resize',()=>{placeMessages();messageTile?.requestLayout?.();});
  }
  function syncMessages(){
    const on=!!(state?.active&&state.ui!==false&&state.widgets.messages);
    if(on&&!messageTile){
      if(!root.PineSystem3MessageTile?.mount||!root.PineMessageView?.tileData){widgets.messages.dataset.unavailable='true';return;}
      delete widgets.messages.dataset.unavailable;messageTile=mountMessageTile(widgets.messages);widgets.messages.__messageObserver?.observe(messageTile.element);
    }
    if(!on)messageHover=false;messageTile?.configure(state?.messageTile);messageTile?.visible(on);if(on&&messageTile){messageTile.hold(messageHover);if(lastPayload)messageTile.receive(lastPayload);}
    if(!state?.active&&messageTile){widgets.messages.__messageObserver?.unobserve(messageTile.element);if(widgets.messages.__messageObservedItem)widgets.messages.__messageObserver?.unobserve(widgets.messages.__messageObservedItem);widgets.messages.__messageObservedItem=null;messageTile.dispose();messageTile=null;messageLayout=null;}
    if(!state?.active)overlay.querySelector('.pip-message-settings')?.setAttribute('hidden','');placeMessages();
  }
  function showMessageTileSettings(){
    let panel=overlay.querySelector('.pip-message-settings');
    if(!panel){
      panel=node('section','pip-message-settings');panel.setAttribute('role','dialog');panel.setAttribute('aria-label','System3 message tile settings');
      const header=node('header','','System3 message tile'),close=node('button','','\u00d7');close.type='button';close.setAttribute('aria-label','Close message tile settings');close.onclick=()=>{panel.hidden=true;};header.appendChild(close);panel.appendChild(header);
      const update=(name,value)=>api().pipUpdate({messageTile:{[name]:value}}).catch(e=>say(e.message));
      const modeLabel=node('label','','Completed message'),mode=node('select');mode.name='mode';mode.setAttribute('aria-label','Completed message');for(const [value,label] of [['hold','Hold until next message'],['fade','Fade after delay'],['history','Keep recent messages']]){const option=node('option','',label);option.value=value;mode.appendChild(option);}mode.onchange=()=>update('mode',mode.value);modeLabel.appendChild(mode);panel.appendChild(modeLabel);
      for(const [name,label,min,max,step,suffix] of [['fontSize','Text size',8,28,1,' px'],['opacity','Tile opacity',0,1,.05,''],['rollSpeed','Roll speed',.25,4,.25,'\u00d7'],['typingSpeed','Typing speed',.25,4,.25,'\u00d7'],['fadeDelay','Fade delay',0,60,1,' s']]){
        const row=node('label','',label),input=node('input'),output=node('output');input.name=name;input.type='range';input.min=String(min);input.max=String(max);input.step=String(step);input.setAttribute('aria-label',label);input.dataset.suffix=suffix;
        input.oninput=()=>{output.textContent=input.value+suffix;if(name==='fontSize'||name==='opacity')messageTile?.configure({...messageTileOptions(),[name]:Number(input.value)});};input.onchange=()=>update(name,Number(input.value));row.append(input,output);panel.appendChild(row);
      }
      const syncLabel=node('label','pip-message-playback'),sync=node('input');sync.type='checkbox';sync.name='followPlayback';sync.onchange=()=>update('followPlayback',sync.checked);syncLabel.append(sync,node('span','','Pause animation with playback'));panel.appendChild(syncLabel);
      panel.appendChild(node('small','','Every reply types at the configured speed while its rolls unfold below. History keeps up to 12 messages.'));
      panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();panel.hidden=true;}});overlay.appendChild(panel);
    }
    syncMessageTileSettings();panel.hidden=false;panel.querySelector('select').focus();
  }
  function syncMessageTileSettings(){
    const panel=overlay.querySelector('.pip-message-settings');if(!panel)return;const options=messageTileOptions();
    for(const input of panel.querySelectorAll('input,select')){if(input.type==='checkbox')input.checked=options[input.name];else input.value=String(options[input.name]);if(input.nextElementSibling?.tagName==='OUTPUT')input.nextElementSibling.textContent=input.value+(input.dataset.suffix||'');}
  }
  function clearSlate() {
    slateTimers.forEach(clearTimeout); slateTimers = [];
    widgets.roulette.querySelector('.pip-slate-rolls').replaceChildren();
    widgets.roulette.querySelector('.pip-slate-line').textContent = '';
  }
  function placeSlate(position = state?.roulettePosition) {
    if (!widgets.roulette || slateDrag) return;
    const slate = widgets.roulette, p = position || { x: .04, y: .18 };
    slate.style.left = Math.max(0, Math.min(innerWidth - slate.offsetWidth, p.x * innerWidth)) + 'px';
    slate.style.top = Math.max(0, Math.min(innerHeight - slate.offsetHeight, p.y * innerHeight)) + 'px';
  }
  function buildSlate() {
    const slate = node('section', 'pip-widget pip-slate'); widgets.roulette = slate;
    slate.setAttribute('aria-label', 'Roulette RNG digital slate');
    const handle = node('button', 'pip-slate-move', 'Roulette RNG'); handle.type = 'button';
    handle.title = 'Drag to move the slate; arrow keys to reposition';
    slate.append(handle, node('small', 'pip-slate-topic', 'Waiting for active dialogue'), node('div', 'pip-slate-rolls'), node('div', 'pip-slate-line'));
    overlay.appendChild(slate);
    const save = () => api().pipUpdate({ roulettePosition: { x: slate.offsetLeft / innerWidth, y: slate.offsetTop / innerHeight } }).catch(e => say(e.message));
    handle.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      e.preventDefault(); handle.setPointerCapture(e.pointerId);
      slateDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: slate.offsetLeft, top: slate.offsetTop };
    });
    handle.addEventListener('pointermove', e => {
      const d = slateDrag; if (!d || d.id !== e.pointerId) return;
      const p = { x: (d.left + e.clientX - d.x) / innerWidth, y: (d.top + e.clientY - d.y) / innerHeight };
      slateDrag = null; placeSlate(p); slateDrag = d;
    });
    const finish = e => { if (slateDrag?.id !== e.pointerId) return; slateDrag = null; if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId); save(); };
    handle.addEventListener('pointerup', finish); handle.addEventListener('pointercancel', finish);
    handle.addEventListener('keydown', e => {
      const delta = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] }[e.key];
      if (!delta) return; e.preventDefault();
      placeSlate({ x: (slate.offsetLeft + delta[0]) / innerWidth, y: (slate.offsetTop + delta[1]) / innerHeight }); save();
    });
    root.addEventListener('resize', () => placeSlate());
  }
  function assembleSlate(data, lineId) {
    clearSlate();
    const slate = widgets.roulette, live = lastPayload?.now || (lastPayload?.rows || []).find(r => String(r.id) === lineId) || {};
    slate.querySelector('.pip-slate-topic').textContent = [live.name || live.who || liveSpeaker, data.turn?.topic_override || data.turn?.topic_material?.text || (data.decisions || []).find(d => /TOPIC|SUBJECT/i.test(d.family || d.selected?.table || ''))?.selected?.label || 'Current conversation'].filter(Boolean).join(' \u00b7 ');
    const rolls = [];
    for (const decision of data.decisions || []) for (const stage of decision.stages || []) {
      if (!stage.draw && stage.stage !== 'fixed') continue;
      rolls.push({ table: decision.selected?.table || decision.family || 'Roulette', stage: stage.stage,
        dice: stage.draw?.dice ?? (stage.draw?.u != null ? 'u ' + Number(stage.draw.u).toFixed(4) : decision.rng?.dice), label: stage.candidates?.find(c => c.id === stage.selected)?.label || stage.draw?.label || stage.selected || decision.selected?.label || decision.selected?.id || 'Recorded result',
        options: (stage.candidates || []).map(c => c.label || c.id) });
    }
    const step = root.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : Math.min(650, 3000 / Math.max(1, rolls.length));
    rolls.forEach((result, i) => slateTimers.push(setTimeout(() => {
      if (!state?.active || state.ui === false || !state.widgets.roulette || currentLine !== lineId) return;
      const card = node('article', 'pip-slate-roll');
      card.append(node('b', '', result.table + ' \u00b7 ' + result.stage), node('span', '', (result.dice == null ? 'Pinned' : 'Roll ' + result.dice) + ' \u2192 ' + result.label));
      card.title = 'Options: ' + result.options.join(', ');
      if (result.options.length > 1) {
        const viewport = node('div', 'pip-roll-window'), reel = node('div', 'pip-roll-reel');
        const options = result.options.concat(result.label);
        options.forEach(label => reel.appendChild(node('div', '', String(label))));
        reel.style.setProperty('--pip-land', (-20 * (options.length - 1)) + 'px'); viewport.appendChild(reel); card.appendChild(viewport);
      }
      slate.querySelector('.pip-slate-rolls').appendChild(card); placeSlate();
      card.scrollIntoView({ block: 'nearest' });
    }, i * step)));
    slateTimers.push(setTimeout(() => {
      if (state?.active && state.ui !== false && state.widgets.roulette && currentLine === lineId) {
        slate.querySelector('.pip-slate-line').textContent = live.text || data.line?.text || '';
        if (!rolls.length) slate.querySelector('.pip-slate-rolls').textContent = 'No roulette recorded for this line';
        placeSlate();
      }
    }, rolls.length * step));
  }
  function buildPainting() {
    painting = node('figure', 'pip-painting'); const image = node('img'); image.alt = 'Active painting'; image.draggable = false;
    painting.append(image, node('figcaption')); overlay.appendChild(painting);
    image.onload = () => {
      if (!state?.active || state.ui === false || !paintingKey) return;
      painting.classList.add('show'); clearTimeout(paintingTimer);
      paintingTimer = setTimeout(() => painting.classList.remove('show'), Number(painting.dataset.seconds) * 1000);
    };
    image.onerror = () => painting.classList.remove('show');
  }
  function updatePainting() {
    if (root.PineGeneratedMedia) return; // Completion notices own the clickable media tile.
    const sale = station.selling_now || {}, filename = sale.image || station.gallery_now?.images?.[0] || '';
    const key = filename ? filename + ':' + (sale.at || '') : '';
    if (key === paintingKey) return;
    paintingKey = key; clearTimeout(paintingTimer); painting.classList.remove('show');
    if (!filename) { painting.querySelector('img').removeAttribute('src'); return; }
    // Six equally likely durations: the local display roll never changes station decisions.
    let die; if (root.crypto?.getRandomValues) { const n = new Uint32Array(1); do { root.crypto.getRandomValues(n); } while (n[0] >= 4294967292); die = n[0] % 6 + 1; }
    else die = Math.floor(Math.random() * 6) + 1;
    const seconds = die + 4; painting.dataset.seconds = seconds;
    painting.querySelector('figcaption').textContent = (sale.title || filename) + ' \u00b7 d6 ' + die + ' \u00b7 ' + seconds + 's';
    const image = painting.querySelector('img'); image.alt = sale.title || filename;
    image.src = safeImage('/api/generations/image/' + encodeURIComponent(filename));
  }
  function cameraWanted() { return !!(state?.active && (state.cameraOverlay || state.cameraOnly)); }
  function placeCamera(bounds = state?.cameraBounds) {
    if (!camera || cameraDrag) return;
    if (state?.cameraOnly) { Object.assign(camera.style, { left: '0px', top: '0px', width: '100%', height: '100%' }); return; }
    const b = bounds || { x: .58, y: .12, width: .38, height: .38 };
    const width = Math.min(innerWidth, Math.max(Math.min(80, innerWidth), b.width * innerWidth));
    const height = Math.min(innerHeight, Math.max(Math.min(50, innerHeight), b.height * innerHeight));
    Object.assign(camera.style, { left: Math.min(innerWidth - width, Math.max(0, b.x * innerWidth)) + 'px', top: Math.min(innerHeight - height, Math.max(0, b.y * innerHeight)) + 'px', width: width + 'px', height: height + 'px' });
  }
  function saveCamera() {
    const r = camera.getBoundingClientRect();
    api().pipUpdate({ cameraBounds: { x: r.left / innerWidth, y: r.top / innerHeight, width: r.width / innerWidth, height: r.height / innerHeight } }).catch(e => say(e.message));
  }
  function buildCamera() {
    camera = node('section', 'pip-camera'); camera.hidden = true; camera.setAttribute('aria-label', 'Pine Cam');
    cameraImage = node('img', 'pip-camera-image'); cameraImage.alt = 'Live Pine Cam'; cameraImage.draggable = false;
    cameraStatus = node('div', 'pip-camera-status', 'Connecting to Pine Cam...'); cameraStatus.setAttribute('role', 'status');
    camera.append(cameraImage, cameraStatus);
    const move = node('button', 'pip-camera-move', 'Pine Cam'); move.title = 'Drag to move Pine Cam'; move.setAttribute('aria-label', 'Move Pine Cam'); camera.appendChild(move);
    for (const edge of ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']) {
      const handle = node('button', 'pip-camera-resize ' + edge); handle.dataset.edge = edge;
      handle.title = 'Drag to resize Pine Cam'; handle.setAttribute('aria-label', 'Resize Pine Cam ' + edge); camera.appendChild(handle);
    }
    const begin = e => {
      if (e.button !== 0 || state?.cameraOnly) return;
      e.preventDefault(); e.stopPropagation();
      const r = camera.getBoundingClientRect();
      cameraDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: r.left, top: r.top, width: r.width, height: r.height, edge: e.target.dataset.edge || '' };
      camera.setPointerCapture(e.pointerId);
    };
    camera.addEventListener('pointerdown', begin);
    camera.addEventListener('pointermove', e => {
      const d = cameraDrag; if (!d || e.pointerId !== d.id) return;
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      let left = d.left, top = d.top, right = left + d.width, bottom = top + d.height;
      const minWidth = Math.min(80, innerWidth), minHeight = Math.min(50, innerHeight);
      if (!d.edge) { left = Math.max(0, Math.min(innerWidth - d.width, left + dx)); top = Math.max(0, Math.min(innerHeight - d.height, top + dy)); right = left + d.width; bottom = top + d.height; }
      else {
        if (d.edge.includes('w')) left = Math.max(0, Math.min(right - minWidth, left + dx));
        if (d.edge.includes('e')) right = Math.min(innerWidth, Math.max(left + minWidth, right + dx));
        if (d.edge.includes('n')) top = Math.max(0, Math.min(bottom - minHeight, top + dy));
        if (d.edge.includes('s')) bottom = Math.min(innerHeight, Math.max(top + minHeight, bottom + dy));
      }
      Object.assign(camera.style, { left: left + 'px', top: top + 'px', width: (right - left) + 'px', height: (bottom - top) + 'px' });
    });
    const finish = e => { if (!cameraDrag || e.pointerId !== cameraDrag.id) return; cameraDrag = null; if (camera.hasPointerCapture(e.pointerId)) camera.releasePointerCapture(e.pointerId); saveCamera(); };
    camera.addEventListener('pointerup', finish); camera.addEventListener('pointercancel', finish);
    camera.addEventListener('keydown', e => {
      if (state?.cameraOnly || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const r = camera.getBoundingClientRect(), dx = e.key === 'ArrowLeft' ? -10 : e.key === 'ArrowRight' ? 10 : 0, dy = e.key === 'ArrowUp' ? -10 : e.key === 'ArrowDown' ? 10 : 0;
      const resizing = !!e.target.dataset.edge || e.shiftKey;
      placeCamera({ x: (r.left + (resizing ? 0 : dx)) / innerWidth, y: (r.top + (resizing ? 0 : dy)) / innerHeight, width: (r.width + (resizing ? dx : 0)) / innerWidth, height: (r.height + (resizing ? dy : 0)) / innerHeight }); saveCamera();
    });
    cameraImage.onload = () => { cameraFramePending = false; cameraStatus.hidden = true; cameraImage.hidden = false; };
    cameraImage.onerror = () => { cameraFramePending = false; cameraFailed = Date.now(); cameraImage.dataset.stream = ''; cameraImage.hidden = true; cameraStatus.hidden = false; cameraStatus.textContent = cameraLabel() + ' picture unavailable - retrying...'; };
    overlay.appendChild(camera); root.addEventListener('resize', () => placeCamera());
  }
  function paintCamera() {
    if (!cameraWanted() || !cameraLive) return;
    if (cameraStream && Date.now() - cameraFailed > 5000) {
      if (cameraImage.dataset.stream !== cameraStream) { cameraImage.dataset.stream = cameraStream; cameraImage.src = cameraStream; }
    } else if (!cameraFramePending) {
      cameraFramePending = true; cameraImage.dataset.stream = ''; cameraImage.src = cameraStill + (cameraStill.includes('?') ? '&' : '?') + 'c=' + Date.now();
    }
  }
  async function pollCamera(generation) {
    try {
      const isTablet = cameraSourceActive !== 'pine';
      let got = isTablet ? await api().cameraWhere() : await api().get('/api/pinelink/state');
      if (generation !== cameraGeneration || !cameraWanted()) return;
      if (isTablet && (!got?.ok || !got.running || (got.frames > 0 && got.sinceFrameMs > 8000))) {
        got = await api().cameraPip({ facing: tabletFacing() });
        if (generation !== cameraGeneration || !cameraWanted()) return;
      }
      cameraLive = isTablet ? !!got?.ok : !!(got?.state === 'live' && got.fresh);
      if (!cameraLive) {
        cameraImage.removeAttribute('src'); cameraImage.dataset.stream = ''; cameraImage.hidden = true; cameraFramePending = false;
        cameraStatus.hidden = false; cameraStatus.textContent = cameraLabel() + ' offline - ' + (got?.why || 'waiting for the camera'); cameraStream = '';
      } else {
        const ts = got.ts;
        cameraStream = isTablet ? got.stream || got.url : ts?.ok && ts.port ? (/\/live\.ts/.test(ts.url || '') ? String(ts.url).replace(/\/live\.ts.*$/, '/live.mjpg') : 'http://' + new URL(cameraBase).hostname + ':' + Number(ts.port) + '/live.mjpg') + cameraQuery : '';
        cameraStill = isTablet ? got.still : cameraBase + '/api/pinelink/frame.jpg';
        paintCamera();
      }
    } catch (e) {
      if (generation !== cameraGeneration) return;
      cameraLive = false; cameraStream = ''; cameraFramePending = false; cameraImage.removeAttribute('src'); cameraImage.hidden = true;
      cameraStatus.hidden = false; cameraStatus.textContent = 'Cannot reach ' + cameraLabel() + ': ' + e.message;
    } finally { if (generation === cameraGeneration && cameraWanted()) cameraPoll = setTimeout(() => pollCamera(generation), 3000); }
  }
  function syncCamera() {
    const source = state?.cameraSource || 'pine';
    if (cameraSourceActive && (cameraSourceActive !== source || !cameraWanted())) {
      if (cameraSourceActive !== 'pine') api().cameraPip?.({ off: true }).catch(e => say(e.message));
      cameraGeneration++; clearInterval(cameraTimer); clearTimeout(cameraPoll); cameraTimer = null; cameraImage.removeAttribute('src'); cameraImage.dataset.stream = ''; cameraFramePending = false;
      cameraLive = false; cameraStream = ''; cameraStill = '';
      cameraSourceActive = '';
    }
    if (cameraDrag && (!cameraWanted() || state?.cameraOnly)) { const id = cameraDrag.id; cameraDrag = null; if (camera.hasPointerCapture(id)) camera.releasePointerCapture(id); }
    document.body.classList.toggle('pine-pip-camera-only', !!(state?.active && state.cameraOnly));
    camera.hidden = !cameraWanted(); camera.classList.toggle('main', !!state?.cameraOnly); placeCamera();
    if (!cameraWanted()) {
      cameraGeneration++; clearInterval(cameraTimer); clearTimeout(cameraPoll); cameraTimer = null; cameraLive = false; cameraStream = ''; cameraDrag = null; cameraFramePending = false;
      cameraImage.removeAttribute('src'); cameraImage.dataset.stream = ''; return;
    }
    if (cameraTimer) return;
    cameraSourceActive = source; cameraImage.alt = 'Live ' + cameraLabel();
    cameraLive = false; cameraStream = ''; cameraStill = '';
    const generation = ++cameraGeneration; cameraFailed = 0; cameraImage.hidden = true; cameraStatus.hidden = false; cameraStatus.textContent = 'Connecting to ' + cameraLabel() + '...';
    cameraTimer = setInterval(paintCamera, 250);
    if (source !== 'pine') {
      api().cameraPip({ facing: tabletFacing() }).then(got => {
        if (generation !== cameraGeneration || !cameraWanted()) return;
        if (!got?.ok) { cameraStatus.textContent = got?.why || 'Tablet camera unavailable'; }
        pollCamera(generation);
      }).catch(e => { if (generation === cameraGeneration) { cameraStatus.textContent = e.message; cameraPoll = setTimeout(() => pollCamera(generation), 3000); } });
      return;
    }
    Promise.allSettled([api().readConfig(), api().get('/api/pinecam/config')]).then(results => {
      if (generation !== cameraGeneration) return;
      if (results[0].status === 'rejected') throw results[0].reason;
      const cfg = results[0].value, quality = results[1].status === 'fulfilled' ? results[1].value?.desk_mjpeg : null;
      cameraQuery = quality ? '?fps=' + (Number(quality.fps) || 25) + '&q=' + (Number(quality.q) || 5) + (Number(quality.w) ? '&w=' + Number(quality.w) : '') : '';
      cameraBase = String(root.pineStationBase?.() || cfg.baseUrl || '').replace(/\/$/, '');
      pollCamera(generation);
    }).catch(e => { if (generation === cameraGeneration) { cameraStatus.textContent = e.message; clearInterval(cameraTimer); cameraTimer = null; } });
  }
  function buildTitlebar() {
    if (!api().pipWindowControl) return;
    const bar = node('div', 'pine-window-bar'); bar.appendChild(node('span', '', 'Pine Box'));
    for (const [action, text, label] of [['minimize', '\u2212', 'Minimize Pine'], ['maximize', '\u25a1', 'Maximize or restore Pine'], ['close', '\u00d7', 'Close Pine']]) {
      const button = node('button', '', text); button.type = 'button'; button.setAttribute('aria-label', label);
      button.onclick = () => api().pipWindowControl(action).catch(e => say(e.message)); bar.appendChild(button);
    }
    document.body.classList.add('pine-frameless'); document.body.appendChild(bar);
  }
  function buildAudio() {
    const controls = node('div', 'pip-audio');
    const dot = node('button', 'pip-volume-dot', '\u25cf'); dot.type = 'button'; dot.title = 'Audio controls'; dot.setAttribute('aria-label', 'Audio controls'); dot.setAttribute('aria-expanded', 'false');
    const mixer = node('button', 'pip-mixer-open', 'Stream audio mixer'); mixer.type = 'button'; mixer.setAttribute('aria-label', 'Open stream audio mixer');
    const panel = node('div', 'pip-volume-panel'); panel.id = 'pinePipVolume'; panel.hidden = true; dot.setAttribute('aria-controls', panel.id);
    const label = node('label', '', 'Application volume'); const slider = node('input'); slider.type = 'range'; slider.min = '0'; slider.max = '100'; slider.step = '1'; slider.setAttribute('aria-label', 'Application volume');
    const value = node('output');
    const sync = () => { slider.value = document.getElementById('appVolume')?.value || String(Math.round(Number(localStorage.getItem('pineDesktopAppVolume') ?? .35) * 100)); value.textContent = slider.value + '%'; };
    label.append(slider, value); panel.append(label, mixer); controls.append(dot, panel); overlay.appendChild(controls);
    dot.onclick = () => { panel.hidden = !panel.hidden; dot.setAttribute('aria-expanded', String(!panel.hidden)); if (!panel.hidden) { sync(); slider.focus(); } };
    slider.oninput = () => {
      const master = document.getElementById('appVolume');
      if (!master) { say('Application volume control unavailable'); return; }
      master.value = slider.value; master.dispatchEvent(new Event('input', { bubbles: true })); value.textContent = slider.value + '%';
    };
    mixer.onclick = () => runAction('mixer');
    panel.addEventListener('keydown', e => { if (e.key === 'Escape') { panel.hidden = true; dot.setAttribute('aria-expanded', 'false'); dot.focus(); } });
    document.addEventListener('pointerdown', e => { if (!controls.contains(e.target)) { panel.hidden = true; dot.setAttribute('aria-expanded', 'false'); } });
  }
  async function runAction(action) {
    if(action?.type==='favorite')return api().pipToolsOpen({id:action.id});
    if (action?.type === 'adjust' && action.name) { showAdjust(String(action.name), freeBox(String(action.name))); return; }   /* [pip-free] from the menu's Widget layout */
    if (action?.type === 'video-folder') {   /* [pip-video-folder] the folder owns the clips for an hour */
      const body = action.clear || !action.path ? { clear: true } : { path: String(action.path), hours: 1 };
      return api().post('/api/sfx/folder-pin', body).then(got => { foldersAt = 0; refreshFolders(); say(got?.say || (body.clear ? 'Every folder again' : 'Clips come from ' + action.path + ' for the next hour'), 7000); }).catch(err => say(err.message));
    }
    if (action?.type === 'background') {   /* [pip-viz] the menu names a mode, or asks for the next */
      if (!panelReady) { say('The background changes once the station page is ready.'); return; }
      return frame.executeJavaScript('window.PinePipPanel?.background(' + JSON.stringify(String(action.mode || 'next')) + ')').then(got => { if (got && got.mode) say('Background: ' + got.mode); }).catch(err => say(err.message));
    }
    try {
      if (action?.type === 'recording') {
        if (exportBusy) { say('A recording is already being exported.'); return; }
        if (![30,60,120,180,300,600,900,1200,1800,3600].includes(action.seconds) || !['audio', 'video'].includes(action.format)) throw new Error('Unknown recording export.');
        exportBusy = true; say('Exporting the last ' + action.seconds + ' seconds to Pine Box recordings...', 0);
        try {
          const result = await api().replayExport({ seconds: action.seconds, audio_only: action.format === 'audio', require_audio: true, view: 'pip' });
          if (!result?.ok) throw new Error(result?.detail || 'Recording export failed.');
          say('Saved ' + result.seconds + ' seconds' + (result.clamped ? ' (available buffer)' : '') + ': ' + result.where, 15000);
        } finally { exportBusy = false; }
        return;
      }
      if(action?.type==='tablet-recording'){
        if(exportBusy){say('A recording is already being exported.');return;}
        if(![60,120,180,300,600,900,1800,3600].includes(action.seconds))throw Error('Unknown tablet duration.');
        exportBusy=true;say('Exporting PineTab recording...',0);
        try{const r=await api().tabletReplayExport({seconds:action.seconds});if(!r?.ok)throw Error(r?.detail||r?.why||'Tablet recording unavailable');say('Saved PineTab '+r.seconds+' seconds'+(r.clamped?' (available buffer)':'')+': '+r.where,15000);}finally{exportBusy=false;}return;
      }
      if(action==='message-tile-settings'||action?.type==='message-tile-settings'){showMessageTileSettings();return;}
      if(action==='popups'){if(api().pipToolsOpen)api().pipToolsOpen().catch(e=>say(e.message));else root.PinePipPopups?.open();}
      if (action === 'menu') await showMenu();
      if (action === 'troubleshoot') await api().troubleshootStation();
      if (action === 'repair-playback') await api().troubleshootStation('playback');
      if (action === 'appearance') showAppearance();
      if (action === 'tablet') { const result = await api().mirrorShow(); if (result?.ok === false) throw new Error(result.detail || 'Tablet display unavailable'); }
      if (action === 'export') { say('Opening tablet recording range editor...'); const result = await api().glassClip(0, { target: 'tablet', replay: true }); if (result?.ok === false) throw new Error(result.detail || 'Tablet recording unavailable'); }
      if (action === 'mixer') {
        if (api().audioMixerOpen) await api().audioMixerOpen();
        else { if (!root.PineLevels?.open) throw new Error('Audio mixer unavailable'); root.PineLevels.open(); }
      }
    } catch (e) { say(e.message); }
  }
  function safeImage(src) {
    if (!src || typeof src !== 'string') return '';
    if (/^data:image\/(png|jpeg|webp);base64,/i.test(src)) return src.length < 100000 ? src : '';
    if (!/^(https?:\/\/|\/)/i.test(src)) return '';
    return src.startsWith('/') ? String(root.desktopMusicUrl?.(src) || src) : src;
  }
  function updateCast() {
    const names = station?.dj_names || {};
    const labels = { host: names.host || root.pineCastName?.('host') || 'Host', cohost: names.cohost || root.pineCastName?.('cohost') || 'Co-host', sfx: names.sfx || root.pineCastName?.('sfx') || 'SFX', callers: names.caller || 'Callers' };
    for (const [key, member] of Object.entries(castMembers)) {
      member.title = String(labels[key]); member.bubble.querySelector('span').textContent = member.title;
      member.bubble.setAttribute('aria-label', member.title + ' voice level');
      if (!member.portrait && portraitPool.length) member.portrait = portraitPool[Math.floor(Math.random() * portraitPool.length)];
      if (member.portrait) { member.image.src = member.portrait; member.image.hidden = false; }
    }
    const signature = JSON.stringify(Object.values(castMembers).map(m => [m.title, m.portrait]));
    if (signature === castSignature) return; castSignature = signature;
    const handle = widgets.cast.querySelector('.pip-grip'); widgets.cast.replaceChildren(handle);
    const viewport = node('div', 'pip-marquee'), strip = node('div', 'pip-track'); viewport.appendChild(strip); widgets.cast.appendChild(viewport);
    for (let copy = 0; copy < 2; copy++) {
      const group = node('span', 'pip-cast-group'); if (copy) group.setAttribute('aria-hidden', 'true');
      for (const member of Object.values(castMembers)) {
        const badge = node('span', 'pip-cast-member');
        if (member.portrait) { const img = node('img'); img.alt = ''; img.src = member.portrait; badge.appendChild(img); }
        else badge.appendChild(node('i', '', member.title.slice(0, 1)));
        badge.appendChild(node('b', '', member.title)); group.appendChild(badge);
      }
      strip.appendChild(group);
    }
  }
  async function loadPortraits() {
    if (portraitsBusy || !state?.active || state.ui === false || (!state.widgets.cast && !state.widgets.voices)) return;
    const posters = videoSlots.panel.concat(videoSlots.shell).map(it => safeImage(it.poster)).filter(Boolean);
    portraitPool = [...new Set(portraitPool.concat(posters))].slice(-64); updateCast();
    if (loadPortraits.loaded) return;
    portraitsBusy = true;
    try {
      const results = await Promise.allSettled([api().get('/api/generations?limit=40'), api().get('/api/sfx/history?limit=40')]);
      if (!state?.active) return;
      for (const result of results) if (result.status === 'fulfilled') {
        const book = result.value || {};
        for (const row of book.rows || book.generations || []) {
          const image = safeImage(row.thumbnail || row.thumb || row.poster);
          if (image) portraitPool.push(image);
          for (const file of row.files || []) if (typeof file === 'string' && /\.(png|jpe?g|webp)$/i.test(file)) {
            portraitPool.push(safeImage('/api/generations/image/' + encodeURIComponent(file) + (book.sig?.[file] ? '?t=' + encodeURIComponent(book.sig[file]) : '')));
          }
        }
      }
      portraitPool = [...new Set(portraitPool.filter(Boolean))].slice(-64); loadPortraits.loaded = true; updateCast();
    } catch (e) { say('Cast portraits: ' + e.message); } finally { portraitsBusy = false; }
  }
  function drawVoice(member, preset) {
    const canvas = member.bubble.querySelector('canvas'), ctx = canvas.getContext('2d'); if (!ctx) return;
    const modes = ['bars','wave','equalizer','wave','blocks','spikes','equalizer','wave','spikes','fill','blocks','bars','bars','spikes','dots','bars'];
    const colour = themePalette().accent, mode = modes[preset] || 'bars';
    const width = 88, height = 32, dpr = Math.min(root.devicePixelRatio || 1, 1.5);
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) { canvas.width = width * dpr; canvas.height = height * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = colour; ctx.fillStyle = colour; ctx.lineWidth = 1.4; ctx.shadowColor = colour; ctx.shadowBlur = 4;
    const bars = Array.isArray(member.bars) && member.bars.length ? member.bars : Array(24).fill(member.level);
    const values = bars.map(v => Math.max(.012, Math.min(1, Number(v) || 0)) * (height / 2 - 2));
    member.bubble.style.setProperty('--voice-colour', colour);
    if (['wave','fill'].includes(mode)) {
      ctx.beginPath(); ctx.moveTo(0, height / 2);
      for (let i = 0; i < values.length; i++) {
        const x = (i + .5) * width / values.length, y = height / 2 + values[i] * (i % 2 ? -1 : 1);
        ctx.lineTo(x, y);
      }
      ctx.lineTo(width, height / 2); if (mode === 'fill') { ctx.closePath(); ctx.globalAlpha = .7; ctx.fill(); } else ctx.stroke();
    } else {
      const step = width / values.length;
      for (let i = 0; i < values.length; i++) {
        const x = i * step + 1, amplitude = values[i];
        if (mode === 'blocks' || mode === 'equalizer' || mode === 'dots') {
          for (let y = 0; y <= amplitude; y += 4) {
            if (mode === 'dots') { ctx.beginPath(); ctx.arc(x + 1, height / 2 - y, 1, 0, Math.PI * 2); ctx.arc(x + 1, height / 2 + y, 1, 0, Math.PI * 2); ctx.fill(); }
            else { ctx.fillRect(x, height / 2 - y, step - 1, 2); if (mode !== 'equalizer') ctx.fillRect(x, height / 2 + y, step - 1, 2); }
          }
        } else { ctx.fillRect(x, height / 2 - amplitude, mode === 'spikes' ? 1 : step - 1.5, Math.max(1, amplitude * 2)); }
      }
    }
    ctx.globalAlpha = 1; ctx.shadowBlur = 0;
  }
  function speakerKey(who) {
    who = String(who || '').toLowerCase();
    for (const [key, member] of Object.entries(castMembers)) if (who && who === member.title.toLowerCase()) return key;
    if (/sfx|sting/.test(who)) return 'sfx';
    if (/co.?host|dj2|^b$/.test(who)) return 'cohost';
    if (/host|dj1|^dj$|^a$/.test(who)) return 'host';
    return 'callers';
  }
  function paintVoices() {
    if (!state?.active || state.ui === false || !state.widgets.voices || document.hidden) return;
    const levels = { host: 0, cohost: 0, sfx: 0, callers: 0 };
    for (const member of Object.values(castMembers)) member.bars = null;
    for (const reading of voiceReadings.panel.concat(voiceReadings.shell)) {
      const key = speakerKey(reading.who || liveSpeaker), level = Number(reading.level) || 0;
      if (level >= levels[key]) {
        levels[key] = level; castMembers[key].bars = reading.bars;
        if (key === 'callers' && reading.who) { castMembers[key].bubble.querySelector('span').textContent = reading.who; castMembers[key].bubble.setAttribute('aria-label', reading.who + ' voice level'); }
      }
    }
    for (const [key, member] of Object.entries(castMembers)) {
      member.level = Math.max(levels[key], member.level * .7); member.peak = Math.max(member.level, member.peak - .035);
      member.bubble.style.setProperty('--voice-level', member.level.toFixed(3)); member.bubble.style.setProperty('--voice-peak', member.peak.toFixed(3));
      member.bubble.setAttribute('aria-valuenow', String(Math.round(member.level * 100)));
      drawVoice(member, state.voiceStyles?.[key] ?? ['host','cohost','sfx','callers'].indexOf(key));
    }
  }
  async function vote(value) {
    if (!track?.id) throw new Error('No current music track to vote on');
    await api().post('/api/music/vote', { id: track.id, vote: value }); say(value > 0 ? 'Track upvoted' : 'Track downvoted');
  }
  function appendChat(id, label, text, kind) {
    if (!id || seen.has(id)) return;
    seen.add(id); if (seen.size > 800) seen.delete(seen.values().next().value);
    const list = widgets.chat.querySelector('.pip-chat-list'), follow = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
    const item = node('article', kind); item.append(node('b', '', label), node('div', '', text)); list.appendChild(item);
    while (list.childNodes.length > 160) list.firstChild.remove();
    if (follow) list.scrollTop = list.scrollHeight;
    return item;
  }
  function receive(payload) {
    lastPayload = payload;
    if (!state?.active || state.ui === false) return;
    messageTile?.receive(payload);
    station = payload.station || {}; track = station.now; updateCast(); updatePainting();
    tellPanelTelemetry(payload);   /* [pip-viz] */
    const live = payload.now || (payload.rows || []).find(r => r.lcdStatus === 'Playing' && !r.music);
    liveSpeaker = String(live?.who || live?.speaker || live?.name || '');
    const lineId = String(live?.id || '');
    if (lineId !== currentLine) { currentLine = lineId; activeRolls = []; rollLine = ''; clearSlate(); widgets.roulette.querySelector('.pip-slate-topic').textContent = live?.text ? 'Assembling current line...' : 'Waiting for active dialogue'; pollExtra(); widgets.dialogue.querySelector('output').textContent = '\u2014'; }
    marquee(widgets.dialogue, live?.text ? [live.name || live.who || live.speaker, live.text].filter(Boolean).join(': ') : 'Waiting for active dialogue', true);
    (payload.rows || []).forEach(r => appendChat('line:' + r.id, r.name || r.who || r.speaker || 'Dialogue', r.text || '', /sfx/i.test(r.who || '') ? 'sfx' : ''));
    paintMusic();
  }
  /* [pip-viz] what the station is doing, for the background in the panel: at most every two seconds */
  let telemetryAt = 0;
  function tellPanelTelemetry(payload) {
    if (!panelReady || !state?.active || Date.now() - telemetryAt < 2000) return;
    telemetryAt = Date.now();
    const live = payload.now || (payload.rows || []).find(r => r.lcdStatus === 'Playing' && !r.music);
    const note = { speaking: live && live.text ? 1 : 0, music: station?.playing && !station?.paused ? 1 : 0, activity: live && live.text ? 1 : station?.playing && !station?.paused ? .6 : .15 };
    frame.executeJavaScript('window.PinePipPanel?.telemetry(' + JSON.stringify(note) + ')').catch(() => {});
  }
  function eventText(it) {
    if (it.type === 'roll') return (it.rows || []).map(r => {
      const m = r.main || {}; return (r.table || 'roulette') + ': d100 ' + (m.dice ?? 'pinned') + ' \u2192 ' + (m.label || m.opts?.[m.hit] || r.winner?.label || '?')
        + ((r.losers || []).length ? ' \u00b7 alternatives: ' + r.losers.map(l => l.label).join(', ') : '');
    }).join(' | ');
    return [it.stage || it.kind || it.type, it.speaker || it.caller, it.title, it.text || it.detail || it.why,
      it.made != null ? it.made + ' lines recorded' : '', it.shelf != null ? it.shelf + ' banked' : '',
      it.shaped ? 'emotion shaping applied' : '', it.engine, it.voice, it.state,
      Object.entries(it.es || {}).map(([key, value]) => key + '=' + value).join(', '),
      it.off_brief ? 'off brief: will not air' : '', it.discarded ? 'discarded' : '', it.outcome].filter(Boolean).join(' \u00b7 ');
  }
  function updateSlots(surface, slots) {
    videoSlots[surface] = Array.isArray(slots) ? slots : [];
    loadPortraits();
    const all = videoSlots.panel.concat(videoSlots.shell), sfx = all.filter(slot => /sfx/i.test(slot.label));
    widgets.chat.querySelector('.pip-sfx-slots').textContent = sfx.length ? sfx.map((slot, i) => 'SFX slot ' + (i + 1) + ': ' + slot.source).join(' \u00b7 ') : 'SFX slot: idle';
    for(const slot of videoSlots[surface]){const id='clip:'+surface+':'+slot.label+':'+slot.source,label=slot.label+' slot',text='Playing: '+slot.source;appendChat(id,label,text,'sfx');}
  }
  async function pollExtra() {
    if (!state?.active || state.ui === false || productionBusy) return;
    productionBusy = true;
    try {
      // One additional request in flight, only for visible widgets.
      if ((state.widgets.dialogue || state.widgets.roulette) && currentLine && currentLine !== rollLine) {
        const requestedLine = currentLine;
        try {
          const data = await api().get('/api/system3/line?line_id=' + encodeURIComponent(requestedLine));
          if (!state?.active) return;
          if (currentLine === requestedLine) { rollLine = requestedLine; if (state.widgets.roulette) assembleSlate(data, requestedLine); }
          if (currentLine === requestedLine) activeRolls = (data.decisions || []).filter(d => d.selected).map(d => {
            const stages = d.stages || [], item = stages.filter(s => s.stage === 'item' || s.stage === 'fixed').pop() || stages[stages.length - 1] || {};
            return { dice: d.rng?.dice ?? item.draw?.dice, label: d.selected.label || d.selected.id, table: d.selected.table,
              options: (item.candidates || []).map(c => c.label || c.id) };
          });
        } catch (_) { widgets.dialogue.querySelector('.pip-dice').title = 'No roulette recorded for this dialogue line'; if (currentLine === requestedLine) widgets.roulette.querySelector('.pip-slate-topic').textContent = 'Roulette unavailable - retrying...'; }
      }
      if (activeRolls.length) {
        const result = activeRolls[activeRollIndex++ % activeRolls.length];
        widgets.dialogue.querySelector('output').textContent = result.dice == null ? '\u2014' : String(result.dice);
        widgets.dialogue.querySelector('.pip-dice').title = [result.table, 'd100: ' + (result.dice ?? 'pinned'), 'Selected: ' + result.label, 'Options: ' + result.options.join(', ')].filter(Boolean).join(' \u00b7 ');
      }
      if (state.widgets.production || state.widgets.chat || state.widgets.dialogue) {
        const data = await api().get('/api/production/feed?s3=' + cursor.s3 + '&n=' + cursor.n + '&t=' + cursor.t);
        if (!state?.active) return;
        cursor = data.cursor || cursor;
        for (const it of data.items || []) {
          const text = eventText(it); production.push(text);
          const eventId='prod:'+JSON.stringify([it.type,it.id,it.at,it.stage,text]),eventLabel=it.type==='roll'?'Roulette selection':it.speaker||it.stage||it.type||'Production';
          const entry=appendChat(eventId,eventLabel,text,it.type);
          if (entry && it.type === 'roll') for (const result of it.rows || []) {
            const m = result.main || {}, opts = m.opts || [m.label || '?'];
            const viewport = node('div', 'pip-roll-window'), reel = node('div', 'pip-roll-reel');
            opts.concat(opts).forEach(label => reel.appendChild(node('div', '', String(label))));
            reel.style.setProperty('--pip-land', (-20 * (opts.length + Math.min(opts.length - 1, Math.max(0, Number(m.hit) || 0)))) + 'px');
            viewport.appendChild(reel); entry.appendChild(viewport);
          }
          if (it.type === 'roll') {
            roll = it;
          }
        }
        production = production.slice(-40); marquee(widgets.production, production.join('   \u2022   '));
      }
      if (state.widgets.audit || state.widgets.task) {
        const data = await api().get('/api/dj/flow?lean=1&limit=80');
        if (!state?.active) return;
        flow = (data.events || []).slice().sort((a, b) => Number(a.at) - Number(b.at));
        const describe = r => [r.node, r.summary].filter(Boolean).join(': ');
        marquee(widgets.audit, flow.map(describe).join('   \u2022   '));
        const current = flow.filter(r => !['playing', 'canplay'].includes(r.node)).pop() || flow[flow.length - 1];
        marquee(widgets.task, current ? describe(current) : 'Waiting for task activity');
      }
    } catch (e) { if (state?.active) say('Live feed: ' + e.message); }
    finally { productionBusy = false; }
  }
  async function loadDice() {
    if (!state?.active || state.ui === false || !state.widgets.dialogue || root.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (!root.THREE) await new Promise((resolve, reject) => {
      const script = node('script'); script.src = root.pineThreeUrl(); script.onload = resolve; script.onerror = () => reject(new Error('Three.js unavailable')); document.head.appendChild(script);
    });
    if (!state?.active || state.ui === false || !state.widgets.dialogue || diceScene || root.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const T = root.THREE, renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2)); renderer.setSize(48, 40);
    const scene = new T.Scene(), camera = new T.PerspectiveCamera(38, 1.2, .1, 20); camera.position.z = 4.8;
    const geo = new T.BoxGeometry(1.4, 1.4, 1.4), material = new T.MeshStandardMaterial({ color: themePalette().accent, roughness: .25, metalness: .3 });
    const cube = new T.Mesh(geo, material), ambient = new T.AmbientLight(themePalette().text, .8); scene.add(cube); scene.add(ambient);
    const light = new T.DirectionalLight(themePalette().text, 1.8); light.position.set(2, 3, 4); scene.add(light);
    widgets.dialogue.querySelector('.pip-dice').prepend(renderer.domElement);
    diceScene = { renderer, geo, material, cube, scene, camera, light, ambient };
    const animate = t => { if (!state?.active || !diceScene) return; diceRaf = root.requestAnimationFrame(animate); if (state.ui === false || !state.widgets.dialogue || document.hidden || t - (animate.last || 0) < 50) return; animate.last = t; cube.rotation.set(t * .0008, t * .0011, t * .0004); renderer.render(scene, camera); };
    diceRaf = root.requestAnimationFrame(animate);
  }
  /* [pip-panel-ready] After entering PiP, look at the page a few times: if it has not taken the
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
    if (!panelReady) {   /* [pip-panel-ready] a page that answers is ready, whatever the flag last heard */
      try { await frame.executeJavaScript('document.readyState'); panelReady = true; } catch (_) { return; }
    }
    await frame.executeJavaScript('(' + pinePipPanel.toString() + ')(window);window.PinePipPanel.appearance(' + JSON.stringify(themePalette()) + ');window.PinePipPanel.set(' + !!state?.active + ',' + JSON.stringify(root.__pineLogo || '') + ');window.PinePipPanel.layout(' + shellCount + ');window.PinePipPanel.meters(' + !!(state?.ui !== false && state?.widgets.voices) + ');');
  }
  function apply(next) {
    const was = state?.active, wasUi = state?.ui, wasRoulette = state?.active && state?.ui !== false && state?.widgets.roulette; state = next;
    publishShared(next);
    document.body.classList.toggle('pine-pip', next.active);
    document.body.classList.toggle('pine-pip-ui-hidden', next.active && next.ui === false);
    root.PinePipPopups?.sync(next);
    syncCamera();
    if (next.active && next.ui !== false && next.widgets.roulette && !wasRoulette) { rollLine = ''; pollExtra(); }
    if (!next.active || next.ui === false || !next.widgets.roulette) clearSlate();
    if (!next.active || next.ui === false) { clearTimeout(paintingTimer); painting.classList.remove('show'); paintingKey = ''; }
    applyAppearance(next);
    for (const [name, widget] of Object.entries(widgets)) {
      widget.hidden = !next.widgets[name]; widget.style.order = next.order[name]; widget.dataset.dock = next.docks[name];
      if (!['chat', 'voices', 'roulette', 'messages', 'music', 'rec'].includes(name) && !placedFreely(name)) overlay.querySelector('.pip-dock-' + next.docks[name]).appendChild(widget);   /* [pip-free] a placed widget leaves the dock */
    }
    placeSlate(); syncMusic(); syncMessages(); syncMessageTileSettings(); syncRecorder();   /* [pip-rec] */
    if (next.active && !was) {
      root.PineAdViewer?.close();
      pinePipPanel(root); root.PinePipPanel.appearance(themePalette()); root.PinePipPanel.set(true, '', true);
      leave = root.PineStationFeed.subscribe(receive);
      pollExtra(); timer = setInterval(pollExtra, 2500);
      voiceTimer = setInterval(paintVoices, 70); loadPortraits();
      loadDice().catch(e => say('Dice visualization: ' + e.message));
    } else if (!next.active && was) {
      overlay.querySelector('.pip-appearance')?.setAttribute('hidden', '');
      root.PinePipPanel?.set(false, '', true); shellCount = panelCount = 0;
      videoTime.panel = videoTime.shell = null; overlay.querySelector('.pip-adjust')?.remove(); adjustFor = '';   /* [pip-playbar] [pip-free] */
      leave?.(); leave = null; clearInterval(voiceTimer); voiceReadings.panel = []; voiceReadings.shell = []; videoSlots.panel = []; videoSlots.shell = []; clearInterval(timer); timer = null;
      root.cancelAnimationFrame(diceRaf);
      if (diceScene) { diceScene.geo.dispose(); diceScene.material.dispose(); diceScene.renderer.dispose(); diceScene.renderer.forceContextLoss(); diceScene.renderer.domElement.remove(); diceScene = null; }
    }
    root.PinePipPanel?.meters(next.active && next.ui !== false && next.widgets.voices);
    if (next.active) { if (wasUi === false && next.ui !== false && lastPayload) receive(lastPayload); if (next.widgets.dialogue && !diceScene) loadDice().catch(e => say(e.message)); if (next.widgets.cast || next.widgets.voices) loadPortraits(); }
    const synced = syncPanel().catch(e => say('PiP video display: ' + e.message));
    if (next.active && !was) confirmPanel();   /* [pip-panel-ready] and make sure the page really switched */
    layoutWidgets(); paintPlaybar();           /* [pip-free] [pip-playbar] */
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
  function installPipDetailDismiss(w) {
    if (w.__pinePipDetailDismiss) return;
    const doc = w.document;
    const closeAway = event => {
      if (!w.PinePip?.state()?.active) return;
      const box = doc.querySelector('#spRrPop .sp-rrp');
      if (!box || (event.type !== 'blur' && box.contains(event.target))) return;
      box.querySelector('.sp-rrp-x')?.click();
    };
    // Capture sees outside presses even when another overlay stops bubbling.
    doc.addEventListener('pointerdown', closeAway, true);
    w.addEventListener('blur', closeAway);
    w.__pinePipDetailDismiss = closeAway;
  }
  function bootstrap() {
    if (!api()?.pipEnter) return;
    frame = document.getElementById('controlFrame'); if (!frame) return;
    build(); buildTitlebar();
    installPipDetailDismiss(root);
    const button = node('button', 'pine-view-tab', 'PiP'); button.id = 'pinePipBtn'; button.type = 'button';
    button.title = 'Reduce Pine to a frameless picture-in-picture window'; button.addEventListener('click', enter);
    const rail = document.getElementById('pineViewRail') || document.getElementById('techRail'); rail.appendChild(button);
    frame.addEventListener('dom-ready', () => { panelReady = true; if (state) syncPanel().catch(e => say(e.message)); });
    /* [pip-panel-ready] Only a new page in the main frame unreadies the panel. did-start-loading also
       fires for every iframe the station page opens later (the Gazette press, a book, a manual, an
       embedded video); with no dom-ready to follow, the flag stayed false and PiP showed the raw
       page until F5. A load that ends while PiP is on re-syncs the panel. */
    frame.addEventListener('did-start-navigation', e => { if (e.isMainFrame && !e.isInPlace) panelReady = false; });
    frame.addEventListener('did-stop-loading', () => { if (state?.active) syncPanel().catch(e => say(e.message)); });
    frame.addEventListener('ipc-message', e => {
      if (state?.active && e.channel === 'pine-pip-voices') { voiceReadings.panel = e.args[0] || []; return; }
      if (e.channel === 'pine-pip-time') { heardVideoTime('panel', e.args[0]); return; }   /* [pip-playbar] */
      if (state?.active && e.channel === 'pine-pip-count') { panelCount = Number(e.args[0]) || 0; root.PinePipPanel?.layout(panelCount); updateSlots('panel', e.args[1]); return; }
      if (!state?.active || e.channel !== 'pine-pip-gesture') return;
      if (e.args[0] === 'expand') expand();
      if (e.args[0] === 'menu') showMenu().catch(err => say(err.message));
    });
    root.addEventListener('message', e => {
      if (e.source !== root || !state?.active) return;
      if (e.data?.type === 'pine-pip-voices') voiceReadings.shell = e.data.readings || [];
      if (e.data?.type === 'pine-pip-time') heardVideoTime('shell', e.data.time);   /* [pip-playbar] */
      if (e.data?.type === 'pine-pip-count') {
        shellCount = Number(e.data.count) || 0;
        updateSlots('shell', e.data.slots);
        if (panelReady) frame.executeJavaScript('window.PinePipPanel?.layout(' + shellCount + ')').catch(err => say(err.message));
      }
      if (e.data?.type === 'pine-pip-gesture') {
        if (e.data.action === 'expand') expand();
        if (e.data.action === 'menu') showMenu().catch(err => say(err.message));
      }
    });
    let toolsFeedLeave; api().onPipToolsWatch?.(on=>{toolsFeedLeave?.();toolsFeedLeave=null;if(on)toolsFeedLeave=root.PineStationFeed.subscribe(payload=>api().pipToolsFeed(payload));});
    api().onPipAction?.(runAction);
    /* [pip-shift] The shell is about to change the window: cover first, then say so. */
    api().onPipShift?.(note => {
      const sheet = root.PinePipShift, id = note?.id;
      api().pipShiftHeard?.(id);
      if (!sheet) { api().pipShiftCovered?.(id); return; }
      sheet.begin(note?.to, { from: note?.from, target: note?.target }).then(() => api().pipShiftCovered?.(id));
    });
    api().onReplayProgress?.(paintExport);   /* [pip-export-bar] */
    api().onPipState(apply); api().pipState().then(apply).catch(e => say(e.message));
    api().get('/api/pip/config').then(remote => {
      sharedLoading = true;
      const finish = () => { sharedLoading = false; sharedReady = true; };
      if (remote?.configured && remote.settings) {
        sharedSignature = JSON.stringify(sharedPreferences(remote.settings));
        return api().pipUpdate(remote.settings).then(apply).catch(() => {}).finally(finish);
      }
      finish();
      api().pipState().then(publishShared).catch(() => {});
    }).catch(() => { sharedReady = true; api().pipState().then(publishShared).catch(() => {}); });
    api().onPipPlayback(value => api().post('/api/sfx/video/mode', value).then(() => say('Video mode updated')).catch(e => say(e.message)));
    root.addEventListener('keydown', e => { if (state?.active && (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10'))) { e.preventDefault(); showMenu().catch(err => say(err.message)); }
      if (state?.active && e.ctrlKey && e.altKey && e.key.startsWith('Arrow') && api().pipPosition) { e.preventDefault(); api().pipPosition(e.key).catch(err => say(err.message)); }
      if (e.ctrlKey && e.shiftKey && e.code === 'KeyP') { e.preventDefault(); state?.active ? expand() : enter(); } });
    root.PinePip = { enter, exit: () => shiftTo('app'), state: () => state, messageTile: messageTileState, digitalFeed: messageTileState, repairCamera: async () => {
      if (state?.cameraSource && state.cameraSource !== 'pine') await api().cameraPip({ off: true });
      cameraGeneration++; clearInterval(cameraTimer); clearTimeout(cameraPoll); cameraTimer = null;
      cameraImage.removeAttribute('src'); cameraImage.dataset.stream = ''; cameraFramePending = false;
      if (!state?.active) await enter();
      if (!state.cameraOnly && !state.cameraOverlay) apply(await api().pipUpdate({ cameraOverlay: true }));
      else syncCamera();
      return { ok: true, say: cameraLabel() + ' display reconnected; waiting for a live picture.' };
    } };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootstrap); else bootstrap();
})(window);
