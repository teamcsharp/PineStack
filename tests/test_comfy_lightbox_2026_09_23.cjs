const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const marker = 'CONTROL_PANEL_HTML = r"""';
const start = source.indexOf(marker);
const end = source.indexOf('\n"""', start + marker.length);
assert.ok(start >= 0 && end > start, 'control panel HTML is present');
const panel = source.slice(start + marker.length, end);
const transition = fs.readFileSync(path.join(__dirname, '..', 'desktop',
  'renderer', 'wall-transition.js'), 'utf8');

test('the embedded control-panel JavaScript parses', () => {
  const scripts = [...panel.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map((match) => match[1]);
  assert.ok(scripts.length, 'the panel has an inline controller');
  scripts.forEach((body) => { new Function(body); });
});

test('reference video comparison is synchronized, draggable, and bounded', () => {
  assert.match(panel, /id="lbWipe"/);
  assert.match(panel, /syncLightboxReference/);
  assert.match(panel, /source\.duration \/ made\.duration/);
  assert.match(panel, /source\.playbackRate = rate/);
  assert.match(panel, /toggleLightboxCompare/);
  assert.match(panel, /lightboxComparePosition/);
  assert.match(panel, /grid-template-columns: minmax\(0,1fr\) minmax\(0,1fr\)/);
  assert.match(panel, /\.lb-imgwrap\.lb-video \{\s*width: 100%; height: auto/);
  assert.match(panel, /aspect-ratio: 16 \/ 9/);
  assert.match(panel, /overflow: hidden/);
  assert.match(panel, /id="lightbox"[\s\S]*z-index:2147483200/);
  assert.match(panel, /id="lightboxRefVid" controls playsinline/);
  assert.match(panel, /refVid\.controls = true/);
});

test('reference first-open waits for a real frame and exposes retry failures', () => {
  assert.match(panel, /preload="auto"/);
  assert.match(panel, /let lightboxOpenSerial = 0/);
  assert.match(panel, /let lightboxReferenceSerial = 0/);
  assert.match(panel, /lightboxOpenSerial === openSerial/);
  assert.match(panel, /lightboxReferenceSerial === attempt/);
  assert.match(panel, /video\.readyState < 2 \|\| video\.videoWidth <= 0/);
  assert.match(panel, /video\.onloadeddata = ready/);
  assert.match(panel, /video\.oncanplay = ready/);
  assert.match(panel, /video\.onerror = failed/);
  assert.match(panel, /Retry original/);
  assert.match(panel, /function retryLightboxReference\(\)/);
  assert.match(panel, /ref\.reason/);
  const load = panel.slice(panel.indexOf('async function loadLightboxReference'),
    panel.indexOf('function showLastRender'));
  assert.doesNotMatch(load, /setTimeout/,
    'reference readiness is driven by URL state and media events, not a timeout');
});

test('sequential mode plays original to ended, then generated, and can replay', () => {
  assert.match(panel, /id="lbPlaySequence"/);
  assert.match(panel, /id="lbReplaySequence"/);
  assert.match(panel, /function lightboxSequencePlayback\(replay\)/);
  assert.match(panel, /source\.currentTime = 0; made\.currentTime = 0/);
  assert.match(panel, /lightboxSetPlaybackMode\("sequence", "original"\)/);
  assert.match(panel, /refVid\.onended = \(\) =>/);
  assert.match(panel, /lightboxSequenceStage = "generated"/);
  assert.match(panel, /const started = vid\.play\(\)/);
  assert.match(panel, /lightboxSequenceStage = "complete"/);
  assert.match(panel, /video\.loop = lightboxPlaybackMode === "sync"/);
  assert.match(panel, /id="lightboxVid"[\s\S]*?controls playsinline preload="auto"/);
  assert.match(panel, /refVid\.muted = false/);
  assert.match(panel, /vid\.muted = false/);
});

test('cover reveals only after a painted frame or legacy playback progress', () => {
  const body = panel.slice(panel.indexOf('function lightboxVideoReady('),
    panel.indexOf('function lightboxRadialClip('));
  assert.doesNotMatch(body, /setTimeout/);
  const makeVideo = (frameCallback) => {
    const listeners = {};
    const video = {
      cover: {hidden: true}, listeners, readyState: 0, videoWidth: 0,
      currentTime: 0, paused: false,
      addEventListener(type, fn) { listeners[type] = fn; },
      removeEventListener(type, fn) {
        if (listeners[type] === fn) delete listeners[type];
      },
    };
    if (frameCallback) video.requestVideoFrameCallback = (fn) => {
      video.frame = fn;
      return 1;
    };
    return video;
  };
  const context = {
    lightboxCoverReset(video) { video.cover.hidden = false; },
    lightboxCoverFor(video) { return video.cover; },
  };
  vm.runInNewContext(body, context);
  const video = makeVideo(true);
  let called = 0;
  context.lightboxVideoReady(video, {}, 'VIDEO ASSEMBLING', () => true,
    () => { called++; });
  assert.equal(video.cover.hidden, false);
  video.readyState = 2;
  video.videoWidth = 640;
  video.onloadeddata();
  assert.equal(called, 1);
  assert.equal(video.cover.hidden, false, 'decoding alone does not reveal');
  video.onplaying();
  assert.equal(video.cover.hidden, false, 'playing event alone does not reveal');
  video.frame();
  assert.equal(video.cover.hidden, true);
  video.paused = true;
  video.listeners.pause();
  assert.equal(video.cover.hidden, false, 'pause restores the poster');

  const legacy = makeVideo(false);
  context.lightboxVideoReady(legacy, {}, 'VIDEO ASSEMBLING', () => true);
  legacy.readyState = 2;
  legacy.videoWidth = 640;
  legacy.onplaying();
  assert.equal(legacy.cover.hidden, false);
  legacy.currentTime = 0.04;
  legacy.listeners.timeupdate({type: 'timeupdate'});
  assert.equal(legacy.cover.hidden, true);
});

test('independent players retain their own transport; sync and sequence remain available', () => {
  const body = panel.slice(panel.indexOf('function syncLightboxReference('),
    panel.indexOf('function toggleLightboxCompare('));
  const video = (duration) => ({duration, currentTime: 0, playbackRate: 1,
    paused: true, hidden: false, style: {display: 'block'},
    play() { this.paused = false; return Promise.resolve(); },
    pause() { this.paused = true; }});
  const made = video(10);
  const source = video(20);
  const buttons = Object.fromEntries(['lbIndependent', 'lbPlayBoth',
    'lbPlaySequence', 'lbCompareNote', 'lbStatus'].map((id) =>
    [id, {setAttribute(name, value) { this[name] = value; }}]));
  const context = {
    document: {getElementById(id) {
      return {lightboxVid: made, lightboxRefVid: source}[id] || buttons[id];
    }},
    lightboxReference: {name: 'source'},
    lightboxPlaybackMode: 'independent',
    lightboxSequenceStage: '',
  };
  vm.runInNewContext(body, context);
  context.lightboxSetPlaybackMode('independent', '');
  assert.equal(buttons.lbIndependent['aria-pressed'], 'true');
  source.play();
  source.currentTime = 7;
  made.currentTime = 3;
  context.syncLightboxReference(true);
  assert.equal(source.currentTime, 7, 'independent seeking is not overwritten');
  made.play();
  made.pause();
  assert.equal(source.paused, false, 'pausing generated does not pause original');

  made.play();
  context.lightboxPlayback();
  assert.equal(buttons.lbPlayBoth['aria-pressed'], 'true');
  assert.equal(source.currentTime, 6, 'sync aligns original to generated');
  assert.equal(source.playbackRate, 2);
  context.lightboxIndependentPlayback();
  assert.equal(source.playbackRate, 1);
  assert.equal(source.paused, false, 'leaving sync keeps native playback usable');
  context.lightboxSequencePlayback(true);
  assert.equal(buttons.lbPlaySequence['aria-pressed'], 'true');
  assert.equal(source.paused, false, 'sequence begins with original');
  assert.equal(made.paused, true);
});

test('video comparisons expose both players side by side by default', () => {
  assert.match(panel, /id="lbIndependent"[^>]*onclick="lightboxIndependentPlayback\(\)"/);
  assert.match(panel, /lightboxSide = true;\s*if \(wrap\) wrap\.classList\.add\("lb-side"\)/);
  assert.match(panel, /lightboxSetPlaybackMode\("independent", ""\)/);
  assert.match(panel, /id="lightboxRefVid" controls playsinline preload="auto"/);
  assert.match(panel, /\.lb-pane > \[hidden\] \{ display: none; \}/);
});

test('comparison controls and media remain bounded on a narrow popup', () => {
  assert.match(panel, /\.lb-card \{ position: relative; width: min\(1180px,100%\)/);
  assert.match(panel, /\.lb-media-state \{ position: absolute/);
  assert.match(panel, /#lightbox \{ padding: 6px !important; \}/);
  assert.match(panel, /\.lb-comparebar \{ display: grid; grid-template-columns: repeat\(2,minmax\(0,1fr\)\); \}/);
  assert.match(panel, /\.lb-imgwrap\.lb-video \{ width: 100%; height: auto; max-height: 52dvh; \}/);
  assert.match(panel, /id="lbResizeHandle"/);
  assert.match(panel, /@container \(max-width: 680px\)/);
  assert.match(panel, /event\.target !== overlay/);
});

test('video variants preserve a parent and support recursive references', () => {
  assert.match(panel, /variantLightbox\(false\)/);
  assert.match(panel, /variantLightbox\(true\)/);
  assert.match(panel, /Another from same setup/);
  assert.match(panel, /Use this render as reference/);
  assert.match(panel, /GENERATED VIDEO ASSEMBLING/);
  assert.match(panel, /ORIGINAL ASSEMBLING/);
});

test('parody Edit stays inside the station and reports splice exports', () => {
  const edit = panel.slice(panel.indexOf('async function editLightboxParody()'),
    panel.indexOf('async function loadLightboxGeneratedVideo'));
  assert.doesNotMatch(edit, /window\.open\(/,
    'the kiosk must not launch a second top-level WebView');
  assert.match(edit, /function openLightboxVideoEditor\(path\)/);
  assert.match(edit, /document\.createElement\("iframe"\)/);
  assert.match(edit, /lb-editor-export-name/);
  assert.match(edit, /embed=1/);
  assert.match(edit, /pine-video-editor-command/);
  assert.match(edit, /editorOrigin/);
  assert.match(edit, /pine-video-editor-export/);
  assert.match(edit, /Spliced video saved/);
  assert.match(panel, /\.lb-editor-dialog[\s\S]*resize: both/);
  assert.match(panel, /\.lb-editor-command\[data-command=close\]:before/);
  const backGlyph = panel.match(/lb-editor-command\[data-command=back\]:before \{ content: "(\\+2190)"; \}/);
  assert.ok(backGlyph);
  assert.equal(backGlyph[1].length, 5, 'the CSS icon escape reaches the browser once');
});

test('decorative gallery videos use still posters and full clips open in the player', () => {
  assert.match(panel, /function mediaElement\(filename\)/);
  assert.match(panel, /img\.loading = "lazy"/);
  assert.match(panel, /\/api\/generations\/poster-url\//);
  assert.match(panel, /if \(isVideoFile\(filename\)\) img\.src = "\/spark\/asset\/pinebox\.png"/);
  assert.match(panel, /function lightboxVideoReady\(/);
  assert.match(transition, /'stalled', 'error', 'abort'/);
});

test('a still image can become a traced video ad with exact spoken copy', () => {
  assert.match(panel, /id="lbImageAd"[^>]*>Make video ad</);
  assert.match(panel, /id="lbAdSpeech"/);
  assert.match(panel, /function lightboxQuotedSpeech\(value\)/);
  assert.match(panel, /function makeImageVideoAd\(\)/);
  assert.match(panel, /mode: "frame"/);
  assert.match(panel, /purpose: "image_ad"/);
  assert.match(panel, /source_type: "generation"/);
  assert.match(panel, /source_generation: lightboxItem\.prompt_id/);
  assert.match(panel, /speech: speech/);
});
