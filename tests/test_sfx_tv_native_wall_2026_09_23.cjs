/* Native-wall menu geometry and lifecycle. These are source-lifted because
 * the bug lived at the CSS/device-pixel boundary, outside the ordinary DOM
 * player harness. */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', 'desktop', 'renderer', 'sfx-tv.js');
const source = fs.readFileSync(SRC, 'utf8');
const LISTEN_SRC = path.join(__dirname, '..', 'desktop', 'renderer', 'listen.js');
const listenSource = fs.readFileSync(LISTEN_SRC, 'utf8');

function fn(name) {
  const at = source.indexOf('function ' + name + '(');
  assert.ok(at >= 0, 'missing ' + name);
  let depth = 0;
  let i = source.indexOf('{', at);
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}' && --depth === 0) return source.slice(at, i + 1);
  }
  throw new Error('unterminated ' + name);
}

test('native device pixels are converted once before menu layout', () => {
  const root = {devicePixelRatio: 1.25};
  const build = new Function('root', fn('wallCssRect') + '\nreturn wallCssRect;');
  const rect = build(root)({x: 10, y: 405, w: 663, h: 423});
  assert.deepEqual(rect, {x: 8, y: 324, w: 530.4, h: 338.4});
});

test('a native drag persists its settled CSS rectangle and updates the ghost frame', () => {
  const store = new Map();
  const root = {devicePixelRatio: 1.25, innerWidth: 1154, innerHeight: 690,
    localStorage: {setItem: (key, value) => store.set(key, value)}};
  const host = {style: {}};
  const build = new Function('root', 'MIN', 'KEY', 'host', 'full',
    fn('rememberWallBox') + '\nreturn rememberWallBox;');
  const box = build(root, {w: 180, h: 120}, 'pineSfxTvBox', host, false)(
    70, 341, 663, 423);
  assert.deepEqual(box, {left: 56, top: 272.8, width: 530.4, height: 338.4});
  assert.deepEqual(JSON.parse(store.get('pineSfxTvBox')), box);
  assert.deepEqual(host.style,
    {left: '56px', top: '273px', width: '530px', height: '338px'});
});

test('one fullscreen command releases the menu and owns both renderers', () => {
  assert.match(source, /wallAsk\(on \? 'menu' : 'free'\)/,
    'opening the menu did not retire the native surface');
  assert.match(source,
    /closeAfter\(wallAsk\(wentFull \? 'full' : 'window',[\s\S]{0,100}nativeWallRect\(\)\)\)/,
    'fullscreen does not close and release the held wall');
  assert.doesNotMatch(source, /var fill = tall\(button\(rowD/,
    'the conflicting second fullscreen button came back');
  assert.match(source, /wallAsk\('play', \{id: clipId\(clip\)/,
    'Next is still being left behind the native prefetched runway');
});

test('compact menu fit cannot pulse between two layouts', () => {
  let observed = null;
  const classes = new Set();
  const wrap = {
    parentNode: {}, style: {maxHeight: '330px'},
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
    },
  };
  Object.defineProperty(wrap, 'scrollHeight', {
    get: () => classes.has('sfx-tv-tight') ? 300 : 360,
  });
  const body = {scrollHeight: 300, clientHeight: 300};
  const root = {innerHeight: 800, requestAnimationFrame: fn => fn()};
  const getComputedStyle = () => ({position: 'fixed'});
  class ResizeObserver {
    constructor(fn) { observed = fn; }
    observe() {}
  }
  const build = new Function('root', 'getComputedStyle', 'ResizeObserver',
    fn('sheetFit') + '\nreturn sheetFit;');
  build(root, getComputedStyle, ResizeObserver)(wrap, body);
  assert.equal(classes.has('sfx-tv-tight'), true);
  observed();
  assert.equal(classes.has('sfx-tv-tight'), true,
    'observer relaxed the sheet and restarted the fit loop');
});

test('fullscreen has a dedicated first control row', () => {
  assert.match(source, /fullBtn\.className = 'sfx-tv-full-toggle'/);
  assert.match(source, /rowA\.appendChild\(fullBtn\)/);
  assert.match(source, /var rowTools = document\.createElement\('div'\)/);
  assert.doesNotMatch(source, /button\(rowA, 'Inspect'/);
});

test('wall menu close control stays outside native hot corners', () => {
  assert.match(source,
    /qs\.right = Math\.ceil\(128 \/ \(Number\(root\.devicePixelRatio\) \|\| 1\)\)/);
});

test('only the active Listen view owns and veils the native picture', () => {
  const body = fn('listenUp');
  assert.match(body, /cls\.contains\('open'\)/);
  assert.match(body, /cls\.contains\('active'\)/);
  assert.match(body, /open && face && face\.isConnected/);
});

test('native Listen taps are consumed without opening the clip inspector', () => {
  assert.match(source,
    /if \(listenUp\(\)\) \{[\s\S]{0,300}listen\.nativeTap\(px, py\)/);
  assert.match(listenSource, /function nativeTap\(x, y\)/);
  assert.match(listenSource, /if \(at - tapAt <= DOUBLE_TAP_MS && near\) toggleBare\(\)/);
  assert.match(listenSource, /nativeTap,\s*\n/,
    'native tap handler is not exported to the video wall');
});

test('leaving Listen immediately restores the popup ownership', () => {
  const observerAt = listenSource.indexOf('new root.MutationObserver(function () {');
  const closedAt = listenSource.indexOf('if (viewOpen()) return;', observerAt);
  const leaveAt = listenSource.indexOf('tv.leaveListen()', closedAt);
  assert.ok(observerAt >= 0 && closedAt > observerAt && leaveAt > closedAt,
    'the Listen close observer does not restore the native popup');
  const leave = fn('leaveListen');
  assert.match(leave, /setFull\(false\)/,
    'leaving Listen can retain the fullscreen wall preference');
  assert.match(leave, /wallVisibility\(\)/,
    'the wall is not recomputed after Listen closes');
});

test('ordinary Listen keeps the native PIP authoritative', () => {
  const reconcile = fn('wallReconcile');
  assert.match(reconcile,
    /wide = fullWanted\(\) \|\| \(listenUp\(\) && listenBare\(\)\)/,
    'bare Listen must use the native surface full-bleed');
  assert.match(reconcile, /want = uiOverPicture\(\)/,
    'Listen must not veil the native PIP merely because its tab is open');
  assert.match(reconcile, /pageBackdrop\(!\(wallHas \|\| \(st && st\.on\)\) \|\| want\)/,
    'the WebView backdrop must stop while the native player owns video');
  assert.match(listenSource, /nativeWallActive/,
    'Listen has no authoritative-native handoff');
  assert.match(listenSource, /vid\.removeAttribute\("src"\)/,
    'the competing WebView decoder is not released');
});

test('native endless repair rebuilds the local runway and reports its state', () => {
  assert.match(source, /function repairEndless\(\)/);
  assert.match(source, /bridge\.videoWall\('repair', nativeWallRect\(\)\)/);
  assert.match(source, /repairEndless: repairEndless/);
  assert.match(source, /Repair endless video/);
  const wall = fs.readFileSync(path.join(__dirname, '..', 'app', 'src', 'main', 'java',
    'com', 'pinebox', 'kiosk', 'video', 'PineVideoWall.kt'), 'utf8');
  const bridge = fs.readFileSync(path.join(__dirname, '..', 'app', 'src', 'main', 'java',
    'com', 'pinebox', 'kiosk', 'bridge', 'PineDesktopBridge.kt'), 'utf8');
  assert.match(wall, /fun repair\(\)/);
  assert.match(wall, /ArrayList\(listed\.drop\(from\)\)/);
  assert.match(wall, /\.put\("last_repair", lastRepair\)/);
  assert.match(bridge, /"repair" -> wall\.repair\(\)/);
});

test('Listen resolves native larder clips that have fallen off the short ring', () => {
  const follow = fn('wallFollow');
  const clip = fn('wallClip');
  assert.match(follow, /wallClip\(id\)/);
  assert.match(clip, /wallShowing = id/);
  assert.match(source, /var WALL_FOLLOW_MS = 750/);
  assert.match(source, /wallFollowTimer = setInterval\(wallFollow, WALL_FOLLOW_MS\)/);
  assert.doesNotMatch(source, /wallTimer = setInterval\(wallFollow/,
    'the native follower collided with the touch-hold timer');
  assert.match(follow, /if \(wallFlight\) return wallFlight/);
  assert.match(clip,
    /bridge\.get\('\/api\/sfx\/url\?id=' \+ encodeURIComponent\(id\)\)/);
  assert.match(clip, /ringRemember\(\[info\]\)/);
  assert.match(clip, /if \(wallShowing === id\) \{[\s\S]{0,80}playing = info/);
  assert.match(source, /wallSignal\(id\)/,
    'a followed native clip does not notify Listen to repaint');
});

test('native transitions are push-driven and duplicate controller injection is inert', () => {
  assert.match(source, /root\.PineSfxTv && root\.PineSfxTv\.__pineCanonicalSfxTv/);
  assert.match(source, /__pineCanonicalSfxTv: true/);
  assert.match(source, /wallClip: wallClip/);
  assert.match(source, /function wireWallUi\(\)/,
    'popup changes do not immediately reconcile the native compositor');
});

test('native takeover removes a stale WebView frame without hiding the native picture', () => {
  const takeover = fn('wallTakesOver');
  assert.match(takeover,
    /if \(host && video && !sheetHeld\(\) && !editorBox\) teardown\(video\)/,
    'the browser fallback can remain on its final frame over the native wall');
  const overlap = fn('uiOverPicture');
  assert.match(overlap, /if \(el === host[\s\S]{0,100}continue/,
    'the fallback frame is still mistaken for a popup that veils native video');
  assert.match(overlap, /pine-field-mics/,
    'the transparent field microphone layer must not permanently veil the native PIP');
});

test('an ended Listen backdrop asks the native wall immediately', () => {
  assert.match(listenSource,
    /backdrop\.addEventListener\("ended",[\s\S]{0,500}tv\.syncWall\(\)/);
  assert.match(source, /syncWall: function \(\) \{ return wallFollow\(\); \}/);
  assert.match(fn('wallFollow'), /var flight = bridge\.videoWall\('state'\)/,
    'the immediate sync cannot be awaited by Listen');
  assert.match(listenSource,
    /addEventListener\("pine-wall-clip",[\s\S]{0,160}paintEndless\(Date\.now\(\), true\)/,
    'Listen does not repaint when the native wall changes clip');
});

test('the two APK surfaces carry the exact canonical video controller', () => {
  const android = path.join(__dirname, '../app/src/main/assets');
  const canonical = fs.readFileSync(SRC);
  for (const surface of ['pine-views', 'pine-sampler']) {
    assert.deepEqual(fs.readFileSync(path.join(android, surface, 'sfx-tv.js')), canonical,
      surface + ' drifted from desktop/renderer/sfx-tv.js');
  }
});

test('dice rebuilds the server pool and replaces the whole native runway', () => {
  const shuffle = fn('shuffleSet');
  assert.match(shuffle, /post\('\/api\/sfx\/video\/shuffle'/);
  assert.match(shuffle, /exclude: recent/);
  assert.match(shuffle, /clips: clips/);
  assert.match(shuffle, /wallAsk\('shuffle'/);
  assert.match(shuffle, /queue\.push\(clips\[i\]\)/,
    'the browser fallback discarded the rest of the fresh batch');
  assert.match(source, /'m:casino', 'Shuffle clips'/,
    'the inspector lost the dice control');
});

test('native wall asks the full server deck before its local continuity cache', () => {
  const native = 'C:/_tools/pinebox-android/PineBoxKiosk/app/src/main/java/com/pinebox/kiosk/video/PineVideoWall.kt';
  if (!fs.existsSync(native)) return;
  const kotlin = fs.readFileSync(native, 'utf8');
  const feedAt = kotlin.indexOf('private suspend fun feed()');
  const ringAt = kotlin.indexOf('val got = nextRingClip()', feedAt);
  const cacheAt = kotlin.indexOf('fromLarder()', feedAt);
  assert.ok(feedAt >= 0 && ringAt > feedAt && cacheAt > ringAt,
    'the small tablet cache is still being chosen before the full server deck');
  assert.match(kotlin, /private const val RUNG_KEEP = 400/,
    'the tablet no-repeat memory became too short for a deep playlist');
});

test('native fullscreen long press and replay reach the shared video menu', () => {
  const base = 'C:/_tools/pinebox-android/PineBoxKiosk/app/src/main/java/com/pinebox/kiosk';
  const wallPath = path.join(base, 'video', 'PineVideoWall.kt');
  const activityPath = path.join(base, 'MainActivity.kt');
  const bridgePath = path.join(base, 'bridge', 'PineDesktopBridge.kt');
  if (![wallPath, activityPath, bridgePath].every(fs.existsSync)) return;
  const kotlin = fs.readFileSync(wallPath, 'utf8');
  const activity = fs.readFileSync(activityPath, 'utf8');
  const bridge = fs.readFileSync(bridgePath, 'utf8');
  assert.match(kotlin, /onLongPress: \(\(Float, Float\) -> Unit\)\?/);
  assert.match(kotlin, /postDelayed\(longPressTrigger, TAP_HOLD_MS\)/);
  assert.match(kotlin, /fun replay\(\)/);
  assert.match(activity, /PineSfxTv\.holdPicture\(" \+ x\.toInt\(\)/);
  assert.match(bridge, /"replay" -> wall\.replay\(\)/);
});
