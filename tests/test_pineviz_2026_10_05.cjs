'use strict';
/* [pip-viz] PineViz without a GPU: the registry, the signal road, the providers, the presets, the bundle.
 *
 * Run on local disk, never from the share:  node --test tests/test_pineviz_2026_10_05.cjs
 * The drawn side (every mode renders, click cycles, the PiP panel mounts it): tests/test_pip_viz_browser_2026_10_05.cjs, with Electron.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'desktop', 'renderer', 'pipviz');
const ORDER = ['core/PineViz.js', 'core/Renderer.js', 'core/VisualizerManager.js', 'audio/Providers.js', 'ui/Overlay.js', 'visualizers/_shared.js',
  'visualizers/00-Classic.js', 'visualizers/01-SmoothWave.js', 'visualizers/02-ParticleFlow.js', 'visualizers/03-LineSpectrum.js', 'visualizers/04-GeometricSpace.js', 'visualizers/05-SpeedLines.js',
  'visualizers/06-AnimeInk.js', 'visualizers/07-AudioBars.js', 'visualizers/08-LiquidGlass.js', 'visualizers/09-RetroGrid.js', 'visualizers/10-ShapeBurst.js'];

function load() {
  const context = { console, setTimeout, clearTimeout, setInterval, clearInterval, Float32Array, Uint8Array, Uint32Array, Math, Date, JSON, Object, Array, Number, String, Map, Set, Promise, Error, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, performance: { now: () => Date.now() } };
  context.globalThis = context;
  vm.createContext(context);
  for (const name of ORDER) vm.runInContext(fs.readFileSync(path.join(SRC, name), 'utf8'), context, { filename: name });
  return context.PineViz;
}

test('[pip-viz] every source parses, stays ASCII, and the ten modes register in order with distinct identities', () => {
  const PineViz = load();
  for (const name of ORDER) assert.doesNotMatch(fs.readFileSync(path.join(SRC, name), 'utf8'), /[^\x00-\x7f]/, name + ' is ASCII');
  const modes = PineViz.modes();
  const plain = v => JSON.parse(JSON.stringify(v));   /* values born in the vm context are compared by value */
  assert.deepEqual(plain(modes.map(m => m.index)), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.deepEqual(plain(modes.map(m => m.id)), ['classic', 'smooth-wave', 'particle-flow', 'line-spectrum', 'geometric-space', 'speed-lines', 'anime-ink', 'audio-bars', 'liquid-glass', 'retro-grid', 'shape-burst']);
  assert.equal(new Set(modes.map(m => m.name)).size, 11);
  for (const def of PineViz.registry) { assert.equal(typeof def.create, 'function', def.id); assert.ok(def.defaults && typeof def.defaults === 'object', def.id + ' exposes properties'); }
  assert.deepEqual(plain(Object.keys(PineViz.PALETTES)), ['playstation', 'neon', 'mono', 'radioNight']);
  const presets = JSON.parse(fs.readFileSync(path.join(SRC, 'presets.json'), 'utf8'));
  for (const def of PineViz.registry) assert.ok(presets[def.id], 'presets.json names ' + def.id);
});

test('[pip-viz] the signal road: bands have their own attack and decay, beats are impulses, a silent provider reads as silence', () => {
  const PineViz = load();
  const sp = new PineViz.SignalProcessor();
  const fft = new Float32Array(256);
  const dt = 1 / 60;
  /* a quiet floor for a second */
  for (let i = 0; i < 60; i++) { fft.fill(.02); sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.rms < .08 && sp.state.bass < .1, 'quiet is quiet: ' + JSON.stringify({ rms: sp.state.rms, bass: sp.state.bass }));
  /* a bass hit */
  for (let i = 0; i < 256; i++) fft[i] = i < 12 ? .95 : .03;
  sp.sample({ fft }); sp.update(dt);
  const bassAfterOne = sp.state.bass, trebleAfterOne = sp.state.treble;
  for (let i = 0; i < 6; i++) { sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.bass > bassAfterOne && sp.state.bass > .3, 'bass rises over its attack: ' + sp.state.bass);
  assert.ok(trebleAfterOne < .1 && sp.state.treble < .1, 'treble stays down when only the low bins move');
  assert.ok(sp.state.beat > .4, 'the onset reads as a beat: ' + sp.state.beat); assert.equal(sp.state.beatCount, 1);
  const peakBass = sp.state.bass;
  /* back to the floor: the beat decays fastest, treble would be fastest of the bands, bass slowest */
  for (let i = 0; i < 256; i++) fft[i] = .02;
  for (let i = 0; i < 6; i++) { sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.beat < .5, 'a tenth of a second later the beat is going: ' + sp.state.beat);
  assert.ok(sp.state.bass > peakBass * .5, 'the bass still carries: ' + sp.state.bass + ' of ' + peakBass);
  for (let i = 0; i < 14; i++) { sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.beat < .15, 'a third of a second later the beat is gone: ' + sp.state.beat);
  for (let i = 0; i < 90; i++) { sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.bass < .12, 'and settles: ' + sp.state.bass);
  /* a provider that stops sampling reads as silence within two seconds */
  for (let i = 0; i < 256; i++) fft[i] = .9;
  for (let i = 0; i < 30; i++) { sp.sample({ fft }); sp.update(dt); }
  assert.ok(sp.state.rms > .4);
  for (let i = 0; i < 180; i++) sp.update(dt);
  assert.ok(sp.state.rms < .08, 'stale: ' + sp.state.rms);
  /* byte FFTs (0..255) are read the same as unit ones */
  const bytes = new Uint8Array(512).fill(200); const sp2 = new PineViz.SignalProcessor(); for (let i = 0; i < 30; i++) { sp2.sample({ fft: bytes }); sp2.update(dt); }
  assert.ok(sp2.state.rms > .3, 'bytes read: ' + sp2.state.rms);
});

test('[pip-viz] the demo provider cycles its scenes and sounds like each; the external provider takes frames of either shape', () => {
  const PineViz = load();
  const demo = new PineViz.DemoProvider({ seed: 3 });
  const seen = []; demo.onSample = raw => seen.push(raw);
  let t = 0; const scenes = new Set();
  for (let i = 0; i < 60 * 95; i++) { t += 1 / 60; demo.update(1 / 60, t); if (i % 60 === 0) scenes.add(demo.sceneName); }
  assert.ok(scenes.size >= 6, 'the scenes come round in 95 s: ' + [...scenes].join(', '));
  assert.ok(seen.length > 5000); assert.ok(seen[seen.length - 1].fft.length === 128);
  const held = new PineViz.DemoProvider({ hold: 'bass-heavy music' }); let sum = 0; held.onSample = raw => { sum = raw.fft.slice(0, 8).reduce((a, b) => a + b, 0) / 8; };
  for (let i = 0; i < 300; i++) held.update(1 / 60, i / 60);
  assert.equal(held.sceneName, 'bass-heavy music'); assert.ok(sum > .3, 'bass-heavy has bass: ' + sum);
  const silent = new PineViz.DemoProvider({ hold: 'silence' }); let level = 1; silent.onSample = raw => { level = raw.rms; };
  for (let i = 0; i < 300; i++) silent.update(1 / 60, i / 60);
  assert.ok(level < .05, 'silence is silent: ' + level);
  const ext = new PineViz.ExternalProvider(); const got = []; ext.onSample = raw => got.push(raw);
  ext.feed({ fft: [1, 2, 3], rms: .5, speechActivity: .7, stationActivity: .9 });
  ext.feed({ bands: new Float32Array([.1, .2]), rms: .2, speech: .1, activity: .2, music: 1 });
  assert.equal(got.length, 2); assert.ok(got[0].fft instanceof Float32Array); assert.equal(got[0].speech, .7); assert.equal(got[0].activity, .9); assert.equal(got[1].music, 1);
});

test('[pip-viz] presets are JSON, per visualizer, with defaults underneath; palettes switch and notify', () => {
  const PineViz = load();
  let saved = '{}'; const store = { get: () => saved, set: v => { saved = v; } };
  const pm = new PineViz.PresetManager({ store });
  pm.define('smooth-wave', { ribbons: 6, bloom: .55 });
  assert.equal(pm.get('smooth-wave').ribbons, 6); assert.equal(pm.get('smooth-wave').intensity, 1, 'the common eight are underneath');
  pm.set('smooth-wave', 'ribbons', 8); assert.equal(JSON.parse(saved)['smooth-wave'].ribbons, 8);
  const pm2 = new PineViz.PresetManager({ store }); pm2.define('smooth-wave', { ribbons: 6 }); assert.equal(pm2.get('smooth-wave').ribbons, 8, 'kept across a reload');
  pm2.load({ 'retro-grid': { density: 1.5 } }); assert.equal(pm2.get('retro-grid').density, 1.5);
  pm2.reset('smooth-wave'); assert.equal(pm2.get('smooth-wave').ribbons, 6);
  const pal = new PineViz.PaletteManager('neon'); let told = ''; pal.onChange((_, name) => { told = name; });
  pal.next(); assert.equal(pal.name, 'mono'); assert.equal(told, 'mono'); pal.set('nothing'); assert.equal(pal.name, 'playstation');
});

test('[pip-viz] the bundle is current with the sources, parses, and is what the PiP panel loads', () => {
  const out = execFileSync(process.platform === 'win32' ? 'python' : 'python3', [path.join(ROOT, 'tools', 'pineviz_bundle.py'), '--check'], { encoding: 'utf8' });
  assert.match(out, /bundle current/);
  const bundle = fs.readFileSync(path.join(SRC, 'dist', 'pineviz.bundle.js'), 'utf8');
  assert.match(bundle, /pineviz-build:[0-9a-f]{12}/);
  const context = { console, setTimeout, clearTimeout, setInterval, clearInterval, requestAnimationFrame: () => 0, cancelAnimationFrame() {}, performance: { now: () => Date.now() } }; context.globalThis = context; vm.createContext(context);
  vm.runInContext(bundle, context, { filename: 'pineviz.bundle.js' });
  assert.equal(context.PineViz.modes().length, 11);
  const page = fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'pine-pip.js'), 'utf8');
  assert.match(page, /tag\.src = '\/vendor\/pineviz\.bundle\.js\?v='/, 'the panel loads the bundle from the station');
  assert.match(page, /vizProvider = new P\.ExternalProvider\(\)/); assert.match(page, /viz = P\.mount\(background, \{ provider: vizProvider/);
  assert.match(page, /background\(mode\) \{/); assert.match(page, /telemetry\(next\) \{/);
  assert.equal(fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'pine-pip.js'), 'utf8'), fs.readFileSync(path.join(ROOT, 'app', 'src', 'main', 'assets', 'pine-views', 'pine-pip.js'), 'utf8'), 'the tablet copy is the same file');
  const menu = fs.readFileSync(path.join(ROOT, 'desktop', 'pip-window.cjs'), 'utf8');
  assert.match(menu, /label: 'Background', submenu: \[/); assert.equal((menu.match(/\['[a-z-]+', '\d\d [A-Za-z ]+ - [a-zA-Z -]+'\]/g) || []).length, 11, 'the menu names the eleven');
});
