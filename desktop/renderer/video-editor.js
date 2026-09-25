/* A non-destructive editor: the source is never rewritten; Save creates a copy. */
(function () {
  'use strict';
  if (new URLSearchParams(location.search).get('parody') === '1') {
    if (new URLSearchParams(location.search).get('embed') === '1') {
      document.documentElement.classList.add('parody-embedded');
    }
    try { startParodyEditor(); }
    catch (error) {
      window.__pineVideoEditorBootError = error;
      if (window.console && typeof window.console.error === 'function') window.console.error('[video-editor] startup failed', error);
      var failedEditor = document.getElementById('parodyEditor');
      var failedRecording = document.getElementById('recordingEditor');
      var failedLoading = document.getElementById('parodyLoading');
      var failedStatus = document.getElementById('parodyStatus');
      if (failedRecording) failedRecording.hidden = true;
      if (failedEditor) failedEditor.hidden = false;
      if (failedLoading) { var failedLabel = failedLoading.querySelector('span'); if (failedLabel) failedLabel.textContent = 'The editor could not open this project.'; }
      if (failedStatus) { failedStatus.textContent = error && error.message || 'The editor could not start.'; failedStatus.classList.add('error'); }
    }
    return;
  }
  function coverPoster(cover, record) {
    var image = cover.querySelector('img'), first = record && Array.isArray(record.thumbnails) && record.thumbnails[0];
    var poster = record && (record.poster_url || record.poster || record.thumbnail_url)
      || (typeof first === 'string' ? first : first && first.url);
    var real = typeof poster === 'string' && !!poster && poster !== '/spark/asset/pinebox.png';
    image.onerror = function () {
      if (!image.classList.contains('ve-real-poster')) return;
      image.classList.remove('ve-real-poster'); image.src = '/spark/asset/pinebox.png';
    };
    image.src = real ? poster : '/spark/asset/pinebox.png';
    image.classList.toggle('ve-real-poster', real);
    return real ? poster : '';
  }
  function bindMediaCover(media, cover, button) {
    var generation = 0;
    function reset() {
      generation += 1;
      media.classList.remove('ve-frame-ready'); cover.hidden = false;
      if (button) button.disabled = !media.getAttribute('src');
    }
    function reveal() {
      if (media.readyState < 2 || !(media.videoWidth > 0 && media.videoHeight > 0)) return;
      var current = generation;
      function show() {
        if (current !== generation || media.readyState < 2 || !(media.videoWidth > 0 && media.videoHeight > 0)) return;
        media.classList.add('ve-frame-ready'); cover.hidden = true;
      }
      if (typeof media.requestVideoFrameCallback === 'function') {
        var fallback = setTimeout(show, 800);
        media.requestVideoFrameCallback(function () { clearTimeout(fallback); show(); });
      }
      else show();
    }
    media.addEventListener('loadstart', reset);
    media.addEventListener('emptied', reset);
    media.addEventListener('loadeddata', reveal);
    media.addEventListener('canplay', reveal);
    media.addEventListener('error', reset);
    if (button) {
      button.addEventListener('click', function () {
        if (!media.getAttribute('src')) return;
        button.disabled = true;
        media.play().catch(function () { button.disabled = false; button.textContent = 'Try play again'; });
      });
      media.addEventListener('waiting', function () { if (!cover.hidden) button.disabled = false; });
    }
    reset();
    return {reset: reset, setPoster: function (record) {
      var poster = coverPoster(cover, record);
      if (poster) media.poster = poster;
    }};
  }
  var M = window.PineVideoEditModel, $ = function (id) { return document.getElementById(id); };
  var video = $('video'), canvas = $('preview'), ctx = canvas.getContext('2d'), viewer = $('viewer');
  var lastFrame = document.createElement('canvas'), frameContext = lastFrame.getContext('2d'), hasFrame = false, exportState = null;
  var source = null, edit = null, past = [], future = [], tab = 'trim', tool = 'pen';
  var frameRect = {x: 0, y: 0, w: 1, h: 1}, gesture = null, raf = 0, busy = false, disposed = false;
  var loadedUrl = '', pendingSeek = null, showFrequencies = false, retryAction = null, sourcePoll = 0, sourceFailed = false, audioChosen = false;
  /* 2026-09-15 (#1213) */
  var frameRing = [], FRAME_RING = 48, spriteImage = null, spriteUrl = '';
  var seekWatch = 0, loadWatch = 0, decodeWatch = 0, loadPhase = '';
  var sourceId = new URLSearchParams(location.search).get('source') || '';
  /* [#1223] The station puts ?sfx=1 on the url it hands back when the
     source it adopted is a clip out of the library. Nothing about the
     editor changes except that a second landing becomes available. */
  var sfxClip = new URLSearchParams(location.search).get('sfx') === '1';
  var sfxPlan = null;
  var sfxSingleMode = false, sfxSplitController = null;
  var host = window;
  try { if (window.parent !== window && window.parent.location.origin === location.origin) host = window.parent; } catch (_) { /* standalone */ }
  var bridge = host.pineDesktop || window.pineDesktop || {};

  function status(text, error, retry) {
    $('status').textContent = text; $('status').parentElement.classList.toggle('error', !!error);
    retryAction = retry || null; $('retry').hidden = !retry;
  }
  function notify(type, detail) {
    var data = {type: type, detail: detail || {}};
    if (host !== window) host.postMessage(data, location.origin);
    window.dispatchEvent(new CustomEvent(type, {detail: detail || {}}));
  }
  async function api(method, path, body, again) {
    var result;
    if (method === 'GET' && typeof bridge.get === 'function') result = await bridge.get(path);
    else if (method === 'POST' && typeof bridge.post === 'function') result = await bridge.post(path, body);
    else if (host !== window && typeof host.api === 'function') result = await host.api(path, {method: method, body: body ? JSON.stringify(body) : undefined});
    else {
      /* [#1242] THIS IS THE BRANCH THE DESK TAKES, AND IT HAD NO CREDENTIAL.
       * The desk opens this page in an iframe from a file:// document, so the
       * parent is cross-origin, Electron's preload is not injected into
       * subframes, and window.__PINE_VIDEO_EDITOR_KEY is assigned nowhere in
       * the tree. The permit below is what the station now accepts instead. */
      var headers = {'Content-Type': 'application/json'}, key = window.__PINE_VIDEO_EDITOR_KEY || '';
      if (key) headers.Authorization = 'Bearer ' + key;
      if (savePermit) headers['X-Pine-Save-Token'] = savePermit;                    /* [#1242] */
      var response = await fetch(path, {method: method, headers: headers, body: body ? JSON.stringify(body) : undefined});
      result = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        /* A refusal is not an answer. One re-mint and one retry happen before
         * the operator is ever shown the word. */
        if (!again && (response.status === 401 || response.status === 403)
          && await permitRenew()) return api(method, path, body, true);            /* [#1242] */
        var refused = new Error(typeof result.detail === 'string' ? result.detail : 'The video could not be processed.');
        refused.status = response.status;
        refused.locked = response.status === 401 || response.status === 403;
        throw refused;
      }
    }
    if (!result || result.ok === false || result.error && !result.status) throw new Error(result && (result.error || result.detail) || 'The station did not answer.');
    return result;
  }
  function remember() { if (!edit || busy) return; past.push(M.copy(edit)); if (past.length > 80) past.shift(); future.length = 0; }
  function changed() { paintControls(); repaint(); }
  function undo() { if (!past.length || busy) return; video.pause(); future.push(M.copy(edit)); edit = past.pop(); changed(); }
  function redo() { if (!future.length || busy) return; video.pause(); past.push(M.copy(edit)); edit = future.pop(); changed(); }
  function displayCrop() { return tab === 'crop' ? M.crop() : edit.crop; }
  function screenPoint(point) {
    var p = M.project(point, displayCrop(), edit.rotation);
    return {x: frameRect.x + p.x * frameRect.w, y: frameRect.y + p.y * frameRect.h};
  }
  function eventPoint(event) {
    var rect = canvas.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  }
  function originalPoint(point) {
    var p = M.unproject({x: (point.x - frameRect.x) / frameRect.w, y: (point.y - frameRect.y) / frameRect.h}, displayCrop(), edit.rotation);
    return {x: M.clamp(p.x, 0, 1), y: M.clamp(p.y, 0, 1)};
  }
  function insideFrame(p) { return p.x >= frameRect.x && p.y >= frameRect.y && p.x <= frameRect.x + frameRect.w && p.y <= frameRect.y + frameRect.h; }
  function drawMarks(context, marks, width, height) {
    context.lineCap = 'round'; context.lineJoin = 'round';
    marks.forEach(function (mark) {
      if (!mark.points || !mark.points.length) return;
      context.strokeStyle = mark.color; context.fillStyle = mark.color;
      context.lineWidth = Math.max(1, mark.weight * width / 1340);
      var first = mark.points[0], last = mark.points[mark.points.length - 1];
      var x = first.x * width, y = first.y * height, x2 = last.x * width, y2 = last.y * height;
      context.beginPath();
      if (mark.kind === 'box') context.rect(Math.min(x, x2), Math.min(y, y2), Math.abs(x2 - x), Math.abs(y2 - y));
      else {
        context.moveTo(x, y);
        mark.points.slice(1).forEach(function (p) { context.lineTo(p.x * width, p.y * height); });
        if (mark.points.length === 1) context.lineTo(x + .01, y + .01);
      }
      context.stroke();
      if (mark.kind === 'arrow') {
        var angle = Math.atan2(y2 - y, x2 - x), length = Math.max(16 * width / 1340, context.lineWidth * 4);
        context.beginPath(); context.moveTo(x2 - length * Math.cos(angle - .5), y2 - length * Math.sin(angle - .5));
        context.lineTo(x2, y2); context.lineTo(x2 - length * Math.cos(angle + .5), y2 - length * Math.sin(angle + .5)); context.stroke();
      }
    });
  }
  function cropCorners() {
    var b = edit.crop;
    return [{x: b.x, y: b.y}, {x: b.x + b.w, y: b.y}, {x: b.x + b.w, y: b.y + b.h}, {x: b.x, y: b.y + b.h}];
  }
  function drawCrop() {
    var points = cropCorners().map(screenPoint), xs = points.map(function (p) { return p.x; }), ys = points.map(function (p) { return p.y; });
    var left = Math.min.apply(null, xs), top = Math.min.apply(null, ys), right = Math.max.apply(null, xs), bottom = Math.max.apply(null, ys);
    ctx.fillStyle = '#0009'; ctx.beginPath(); ctx.rect(frameRect.x, frameRect.y, frameRect.w, frameRect.h); ctx.rect(left, top, right - left, bottom - top); ctx.fill('evenodd');
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.strokeRect(left, top, right - left, bottom - top);
    ctx.strokeStyle = '#ffffff70'; ctx.lineWidth = 1;
    for (var n = 1; n < 3; n += 1) { ctx.beginPath(); ctx.moveTo(left + (right - left) * n / 3, top); ctx.lineTo(left + (right - left) * n / 3, bottom); ctx.moveTo(left, top + (bottom - top) * n / 3); ctx.lineTo(right, top + (bottom - top) * n / 3); ctx.stroke(); }
    points.forEach(function (p) { ctx.fillStyle = '#ffd60a'; ctx.strokeStyle = '#151515'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); });
  }
  function draw() {
    if (!source || !edit) return;
    var w = viewer.clientWidth, h = viewer.clientHeight, dpr = Math.min(1.5, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    var crop = displayCrop(), cw = source.width * crop.w, ch = source.height * crop.h, sideways = edit.rotation % 180;
    frameRect = viewApply(M.fit(w, h, sideways ? ch / cw : cw / ch));              /* [#1242] */
    var scale = frameRect.w / (sideways ? ch : cw);
    ctx.save(); ctx.beginPath(); ctx.rect(frameRect.x, frameRect.y, frameRect.w, frameRect.h); ctx.clip();
    ctx.translate(frameRect.x + frameRect.w / 2, frameRect.y + frameRect.h / 2); ctx.rotate(edit.rotation * Math.PI / 180); ctx.scale(scale, scale);
    ctx.translate(-(crop.x + crop.w / 2) * source.width, -(crop.y + crop.h / 2) * source.height);
    if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0 && !video.seeking) {
      if (lastFrame.width !== source.width || lastFrame.height !== source.height) { lastFrame.width = source.width; lastFrame.height = source.height; }
      frameContext.drawImage(video, 0, 0, source.width, source.height); hasFrame = true;
      $('recordingCover').hidden = true;
      harvestFrame();                                            /* #1213 */
      $('decodingNote').hidden = true;
    }
    /* #1213: the stand-in goes through the SAME crop/rotate/filter transform
     * as the real frame, so the picture does not jump geometry when the
     * decoder lands, and it is dimmed slightly so approximate never passes
     * for exact. */
    var wantAt = pendingSeek !== null ? pendingSeek : (video.currentTime || 0);
    var proxy = ((video.seeking && pendingSeek !== null) || !hasFrame) ? proxyAt(wantAt) : null;
    if (proxy) {
      ctx.filter = M.filter(edit); ctx.globalAlpha = .88;
      ctx.drawImage(proxy.image, proxy.sx, proxy.sy, proxy.sw, proxy.sh,
        0, 0, source.width, source.height);
      ctx.globalAlpha = 1; ctx.filter = 'none';
    } else if (hasFrame) { ctx.filter = M.filter(edit); ctx.drawImage(lastFrame, 0, 0, source.width, source.height); ctx.filter = 'none'; }
    drawMarks(ctx, edit.marks, source.width, source.height); ctx.restore();
    if (tab === 'crop') drawCrop();
  }
  function repaint() {
    if (raf || disposed) return;
    raf = requestAnimationFrame(function () {
      raf = 0;
      if (edit && !video.paused && video.currentTime >= edit.out_s) { video.pause(); seek(edit.out_s); }
      draw(); paintHead();
      if (!video.paused) repaint();
    });
  }
  function seek(at) {
    if (!source) return;
    pendingSeek = M.clamp(at, 0, source.duration);
    paintHead(pendingSeek);
    if (!video.seeking) { try { video.currentTime = pendingSeek; } catch (_) { /* metadata is arriving */ } }
    armSeekWatchdog();
    /* 2026-09-15 (#1213): THE WHOLE OF "UNRESPONSIVE" WAS THIS MISSING LINE.
     *
     * The operator: "wherever I place the playhead or I click around the video
     * instantly updates to show that so it's responsive while I'm editing."
     *
     * repaint() is reachable while paused ONLY from the 'seeked' handler
     * below, and seek() never called it - so between seeks there was no path
     * to the screen AT ALL. The picture could not change until the decoder
     * finished, and the desk cuts at 25 fps with x264's default keyframe
     * interval, which is exactly TEN SECONDS between keyframes. A scrub could
     * be waiting on ten seconds of forward decode with nothing drawn. */
    repaint();
  }
  /* pendingSeek had no timeout and no escape. If one seek never completed,
   * video.seeking stayed true, the gate above silently dropped every later
   * scrub, and the playhead glided over a frozen picture saying nothing -
   * which reads to the operator exactly like the complaint he already made. */
  function armSeekWatchdog() {
    clearTimeout(seekWatch);
    if (pendingSeek === null) return;
    seekWatch = setTimeout(function () {
      if (disposed || pendingSeek === null) return;
      try { video.currentTime = pendingSeek; } catch (_) { /* gone */ }
      seekWatch = setTimeout(function () {
        if (disposed || pendingSeek === null) return;
        pendingSeek = null;
        status('The preview stopped following the playhead. Try again to reopen it.',
          true, reloadMedia);
      }, 4000);
    }, 4000);
  }
  /* #1213: a stand-in while the decoder works. draw() already blits every real
   * frame, so keeping a 160 px copy costs nothing and makes a re-scrub over
   * ground already visited both instant AND exact - and editing is
   * back-and-forth over the same few seconds. */
  function harvestFrame() {
    if (!source || video.seeking || !hasFrame || !(source.width > 0)) return;
    var at = video.currentTime, i;
    for (i = 0; i < frameRing.length; i += 1) if (Math.abs(frameRing[i].t - at) < .2) return;
    var w = 160, h = Math.max(1, Math.round(160 * source.height / source.width));
    var c = document.createElement('canvas'); c.width = w; c.height = h;
    c.getContext('2d').drawImage(lastFrame, 0, 0, w, h);
    frameRing.push({t: at, canvas: c});
    if (frameRing.length > FRAME_RING) frameRing.shift();
  }
  /* In preference order: a real decoded frame within 0.75 s, else the
   * filmstrip sprite tile - already fetched by filmstrip(), so this is a cache
   * hit rather than a download. Coarse on purpose; it is a stand-in, not a
   * claim. */
  function proxyAt(at) {
    var best = null, distance = .75, i, d;
    for (i = 0; i < frameRing.length; i += 1) {
      d = Math.abs(frameRing[i].t - at);
      if (d < distance) { distance = d; best = frameRing[i].canvas; }
    }
    if (best) return {image: best, sx: 0, sy: 0, sw: best.width, sh: best.height};
    var sprite = source && source.thumbnail_sprite;
    if (!spriteImage || !spriteImage.complete || !spriteImage.naturalWidth
        || !sprite || !sprite.count) return null;
    var columns = sprite.columns || sprite.count;
    var index = M.clamp(Math.round(at / Math.max(.001, source.duration) * (sprite.count - 1)),
      0, sprite.count - 1);
    return {image: spriteImage, sx: index % columns * sprite.width,
      sy: Math.floor(index / columns) * sprite.height,
      sw: sprite.width, sh: sprite.height};
  }
  video.addEventListener('seeked', function () {
    if (pendingSeek !== null && Math.abs(video.currentTime - pendingSeek) > .035) { video.currentTime = pendingSeek; return; }
    pendingSeek = null; clearTimeout(seekWatch); repaint();   /* #1213 */
  });
  /* 2026-09-15 (#1213): THE LOAD SURFACE COULD NOT TELL SLOW FROM BROKEN.
   *
   * "for some reason it's just stuck loading video." It was not stuck: the
   * file is valid and the route answers 200 with a correct 206 to a Range
   * request. It was a 3.9 MB fetch behind an indefinite message. The browser
   * fires 'progress' with real byte counts and 'stalled' when it gives up,
   * and every one of those was discarded. Same fault as the flat meter: a
   * surface that cannot say why it is empty. */
  function showLoading(text, fraction) {
    $('loading').hidden = false;
    $('loadingText').textContent = text;
    var determinate = typeof fraction === 'number' && fraction >= 0;
    $('loadingBar').hidden = !determinate;
    if (determinate) $('loadingFill').style.width = M.clamp(fraction, 0, 1) * 100 + '%';
  }
  /* #1213: and the retry button could never retry the VIDEO. loadedUrl is
   * assigned only in hydrate() and reset nowhere, and the server always writes
   * the identical url string - so "Try again" re-fetched the JSON, found
   * loadedUrl === source.url, and never reassigned video.src or called load(). */
  function reloadMedia() {
    loadedUrl = ''; hasFrame = false; pendingSeek = null; frameRing.length = 0;
    $('recordingCover').hidden = false;
    clearTimeout(seekWatch); clearTimeout(decodeWatch);
    loadPhase = 'opening'; showLoading('Opening the recording…', -1);
    $('decodingNote').hidden = true;
    loadSource();
  }
  function armLoadWatchdog() {
    clearTimeout(loadWatch);
    loadWatch = setTimeout(function () {
      if (disposed || loadPhase === 'decoding' || loadPhase === 'ready') return;
      showLoading('Still waiting for the recording - nothing has arrived yet.', -1);
      status('The recording has not started arriving. Try again.', true, reloadMedia);
      loadWatch = setTimeout(function () {
        if (disposed || loadPhase === 'decoding' || loadPhase === 'ready') return;
        showLoading('The recording could not be opened.', -1);
        status('The recording could not be opened. Try again.', true, reloadMedia);
      }, 17000);
    }, 8000);
  }
  function armDecodeWatchdog() {
    clearTimeout(decodeWatch);
    decodeWatch = setTimeout(function () {
      if (disposed || hasFrame) return;
      $('decodingNote').textContent = 'The picture has not decoded yet.';
      status('The recording arrived but the picture has not decoded. Try again.',
        true, reloadMedia);
    }, 10000);
  }
  video.addEventListener('loadstart', function () {
    loadPhase = 'opening'; showLoading('Opening the recording…', -1); armLoadWatchdog();
  });
  video.addEventListener('progress', function () {
    if (loadPhase !== 'opening' && loadPhase !== 'bytes') return;
    var end = video.buffered.length ? video.buffered.end(video.buffered.length - 1) : 0;
    var whole = video.duration || (source && source.duration) || 0;
    if (!(whole > 0)) return;
    loadPhase = 'bytes'; armLoadWatchdog();
    showLoading('Loading the recording… '
      + Math.round(M.clamp(end / whole, 0, 1) * 100) + '%', end / whole);
  });
  /* The overlay lifts one event earlier - at metadata rather than at first
   * frame - so the timeline goes live as soon as duration and dimensions are
   * known. What remains is DECODE, not download, and it gets its own named
   * state instead of a byte bar sitting at 100% explaining nothing. */
  video.addEventListener('loadedmetadata', function () {
    loadPhase = 'decoding'; clearTimeout(loadWatch);
    $('loading').hidden = true;
    $('decodingNote').textContent = 'Decoding the first frame…';
    $('decodingNote').hidden = hasFrame;
    if (!hasFrame) armDecodeWatchdog();
    paintControls(); repaint();
  });
  video.addEventListener('loadeddata', function () {
    loadPhase = 'ready'; clearTimeout(loadWatch); clearTimeout(decodeWatch);
    $('loading').hidden = true; $('decodingNote').hidden = true; repaint();
  });
  ['stalled', 'waiting'].forEach(function (name) {
    video.addEventListener(name, function () {
      if (loadPhase === 'ready' || hasFrame) return;
      showLoading('The recording stopped arriving.', -1);
      status('The recording stopped arriving. Try again.', true, reloadMedia);
    });
  });
  /* The error road used to slam the overlay back over the canvas
   * unconditionally, destroying a live editing session for a fault that may be
   * transient. After the first frame it writes a footer line only. */
  video.addEventListener('error', function () {
    if (hasFrame) { status('The preview dropped out. Try again to reload it.', true, reloadMedia); return; }
    showLoading('The preview could not load.', -1);
    status('Try opening the recording again.', true, reloadMedia);
  });
  ['play', 'pause', 'timeupdate', 'ended'].forEach(function (name) { video.addEventListener(name, function () { $('play').textContent = video.paused ? '▶' : 'Ⅱ'; $('play').setAttribute('aria-label', video.paused ? 'Play selection' : 'Pause preview'); repaint(); }); });
  function play() {
    if (!source || busy) return;
    if (!video.paused) { video.pause(); return; }
    if (video.currentTime < edit.in_s || video.currentTime >= edit.out_s - .03) seek(edit.in_s);
    video.muted = !edit.include_audio;
    video.play().catch(function () { status('Tap Play again to start the preview.', true); });
  }
  function paintHead(at) {
    if (!source) return;
    var t = typeof at === 'number' ? at : video.currentTime;
    $('position').textContent = M.clock(t); $('playhead').style.left = M.clamp(t / source.duration, 0, 1) * 100 + '%';
  }
  function paintControls() {
    if (!source || !edit) return;
    var left = edit.in_s / source.duration * 100, right = edit.out_s / source.duration * 100;
    $('trimBand').style.left = left + '%'; $('trimBand').style.width = right - left + '%';
    $('inHandle').style.left = left + '%'; $('outHandle').style.left = right + '%';
    $('shadeBefore').style.width = left + '%'; $('shadeAfter').style.width = 100 - right + '%';
    [['inHandle', edit.in_s], ['outHandle', edit.out_s]].forEach(function (row) { $(row[0]).setAttribute('aria-valuemax', source.duration); $(row[0]).setAttribute('aria-valuenow', row[1].toFixed(2)); $(row[0]).setAttribute('aria-valuetext', M.clock(row[1])); });
    $('startTime').value = edit.in_s.toFixed(2); $('endTime').value = edit.out_s.toFixed(2); $('startTime').max = source.duration; $('endTime').max = source.duration;
    $('selection').textContent = (edit.out_s - edit.in_s).toFixed(2) + 's selected';
    $('startLabel').textContent = M.clock(edit.in_s); $('endLabel').textContent = M.clock(edit.out_s);
    $('audio').checked = !!edit.include_audio; $('audio').disabled = !source.has_audio || busy; video.muted = !edit.include_audio;
    $('audioLabel').textContent = source.has_audio ? 'Include audio' : 'No audio in recording';
    $('undo').disabled = !past.length || busy; $('redo').disabled = !future.length || busy; $('save').disabled = busy || source.status !== 'ready'; $('play').disabled = busy;
    /* [#1223] the same rule as Save copy. Guarded, because this editor is
       also served to a page whose HTML has not been updated yet. */
    if ($('saveOver')) $('saveOver').disabled = busy || source.status !== 'ready';
    $('clearMarks').disabled = !edit.marks.length;
    ['brightness', 'contrast', 'saturation'].forEach(function (key) { $(key).value = edit[key]; $(key + 'Value').textContent = Math.round((edit[key] - 1) * 100); });
    var size = M.outputSize(source, edit); $('dimensions').textContent = size.width + ' × ' + size.height;
  }
  function trimTo(edge, at) { if (!source || busy) return; video.pause(); edit = M.trim(edit, edge, at, source.duration); changed(); seek(edge === 'in' ? edit.in_s : edit.out_s); }
  function timelineAt(event) { var r = $('timeline').getBoundingClientRect(); return M.clamp((event.clientX - r.left) / r.width, 0, 1) * source.duration; }
  ['in', 'out'].forEach(function (edge) {
    var handle = $(edge + 'Handle');
    handle.addEventListener('pointerdown', function (event) { if (!source || busy) return; event.preventDefault(); event.stopPropagation(); remember(); video.pause(); gesture = {type: 'trim', edge: edge, id: event.pointerId}; handle.setPointerCapture(event.pointerId); });
    handle.addEventListener('pointermove', function (event) { if (gesture && gesture.type === 'trim' && gesture.id === event.pointerId) trimTo(edge, timelineAt(event)); });
    ['pointerup', 'pointercancel'].forEach(function (name) { handle.addEventListener(name, function () { gesture = null; }); });
    handle.addEventListener('keydown', function (event) { if (!source || busy || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); remember(); var at = edge === 'in' ? edit.in_s : edit.out_s; trimTo(edge, event.key === 'Home' ? 0 : event.key === 'End' ? source.duration : at + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 1 : .1)); });
  });
  $('timeline').addEventListener('pointerdown', function (event) { if (!source || gesture || busy) return; event.preventDefault(); video.pause(); gesture = {type: 'scrub', id: event.pointerId}; $('timeline').setPointerCapture(event.pointerId); seek(timelineAt(event)); });
  $('timeline').addEventListener('pointermove', function (event) { if (gesture && gesture.type === 'scrub' && gesture.id === event.pointerId) seek(timelineAt(event)); });
  ['pointerup', 'pointercancel'].forEach(function (name) { $('timeline').addEventListener(name, function () { if (gesture && gesture.type === 'scrub') gesture = null; }); });

  function previewAt(event) {
    var r = canvas.getBoundingClientRect(), x = event.clientX - r.left;
    return M.clamp((x - frameRect.x) / Math.max(1, frameRect.w), 0, 1) * source.duration;
  }
  canvas.addEventListener('pointerdown', function (event) {
    /* 2026-09-15 (#1213): "or I click around the video". Clicking the picture
     * had NEVER done anything - this handler returned early unless the tab was
     * draw or crop. That was not slowness, it was absence. */
    if (source && !busy && !gesture && tab === 'trim' && insideFrame(eventPoint(event))) {
      event.preventDefault(); video.pause(); canvas.setPointerCapture(event.pointerId);
      gesture = {type: 'preview-scrub', id: event.pointerId};
      seek(previewAt(event));
      return;
    }
    if (!source || busy || gesture || !['draw', 'crop'].includes(tab)) return;
    var screen = eventPoint(event); if (!insideFrame(screen)) return;
    event.preventDefault(); video.pause(); remember(); canvas.setPointerCapture(event.pointerId);
    var point = originalPoint(screen);
    if (tab === 'draw') {
      if (edit.marks.length >= 100) { status('Undo or clear a drawing before adding more.', true); return; }
      var mark = {kind: tool, color: $('color').value, weight: Number($('weight').value), points: [point]}; edit.marks.push(mark);
      gesture = {type: 'draw', id: event.pointerId, mark: mark};
    } else {
      var corners = cropCorners(), chosen = -1, distance = 30;
      corners.forEach(function (p, index) { var s = screenPoint(p), d = Math.hypot(s.x - screen.x, s.y - screen.y); if (d < distance) { chosen = index; distance = d; } });
      var b = edit.crop, inside = point.x >= b.x && point.y >= b.y && point.x <= b.x + b.w && point.y <= b.y + b.h;
      gesture = {type: 'crop', id: event.pointerId, start: point, before: M.copy(b), moving: chosen < 0 && inside,
        anchor: chosen >= 0 ? corners[(chosen + 2) % 4] : point};
    }
    changed();
  });
  canvas.addEventListener('pointermove', function (event) {
    if (!gesture || gesture.id !== event.pointerId) return;
    if (gesture.type === 'preview-scrub') { seek(previewAt(event)); return; }  /* #1213 */
    var p = originalPoint(eventPoint(event));
    if (gesture.type === 'draw') {
      var mark = gesture.mark, last = mark.points[mark.points.length - 1];
      if (mark.kind === 'pen') { if (mark.points.length < 1600 && Math.hypot(p.x - last.x, p.y - last.y) > .001) mark.points.push(p); }
      else mark.points = [mark.points[0], p];
    } else if (gesture.type === 'crop') {
      var old = gesture.before, a = gesture.anchor;
      edit.crop = gesture.moving ? M.crop({x: old.x + p.x - gesture.start.x, y: old.y + p.y - gesture.start.y, w: old.w, h: old.h})
        : M.crop({x: Math.min(a.x, p.x), y: Math.min(a.y, p.y), w: Math.abs(p.x - a.x), h: Math.abs(p.y - a.y)});
    }
    changed();
  });
  ['pointerup', 'pointercancel'].forEach(function (name) { canvas.addEventListener(name, function () { gesture = null; changed(); }); });

  /* [#1221] STROKES DRAWN WHILE THIS WINDOW WAS PUSHED OFF THE SCREEN.
   *
   * "For the video editor frame window that pops up when we do a capture, I
   *  want to be able to slide it out of the screen so that way I can draw on
   *  the screen full screen."
   *
   * hot-corners.js parks this window at the edge and puts a transparent ink
   * pad over the live screen behind it. The recording being edited is a
   * recording OF THAT SCREEN, so a stroke's place on the glass is its place in
   * the frame, and the pad hands them over already normalised. They arrive
   * here as ordinary Draw-layer marks: one Undo takes the whole handover back,
   * and Save carries them in the overlay PNG exactly like hand-drawn ones.
   *
   * WHO IS ALLOWED TO SEND THEM. Only the window that embedded this one, and
   * only when there IS one. The desk cannot compare origins with its embedder
   * (the shell is not the station), so the guard is the frame relationship
   * rather than a string - and every number that arrives is clamped, the kind
   * is one of three words, and the colour has to be six hex digits, so the
   * worst a stranger's frame could do is draw on a recording it cannot read. */
  window.addEventListener('message', function (event) {
    if (window.parent === window || event.source !== window.parent) return;
    var data = event.data;
    if (!data || data.type !== 'pine-video-editor-marks' || !Array.isArray(data.marks)) return;
    if (!source || !edit || busy) return;
    remember();
    var added = 0;
    data.marks.forEach(function (mark) {
      if (!mark || !Array.isArray(mark.points) || !mark.points.length) return;
      if (edit.marks.length >= 100) return;
      var points = [];
      mark.points.slice(0, 1600).forEach(function (point) {
        var x = Number(point && point.x), y = Number(point && point.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        points.push({x: M.clamp(x, 0, 1), y: M.clamp(y, 0, 1)});
      });
      if (!points.length) return;
      edit.marks.push({
        kind: mark.kind === 'box' || mark.kind === 'arrow' ? mark.kind : 'pen',
        color: /^#[0-9a-fA-F]{6}$/.test(String(mark.color)) ? String(mark.color) : '#ff2828',
        weight: M.clamp(Number(mark.weight) || 6, 1, 24),
        points: points
      });
      added += 1;
    });
    if (!added) { past.pop(); return; }
    pickTab('draw');
    changed();
    status(added === 1 ? 'One stroke from the screen joined the drawings.'
      : added + ' strokes from the screen joined the drawings.');
  });

  function pickTab(name) { tab = name; document.querySelectorAll('[data-tab]').forEach(function (b) { b.classList.toggle('selected', b.dataset.tab === name); b.setAttribute('aria-pressed', b.dataset.tab === name); }); document.querySelectorAll('[data-panel]').forEach(function (p) { p.hidden = p.dataset.panel !== name; }); $('cropHint').hidden = name !== 'crop'; repaint(); }
  document.querySelectorAll('[data-tab]').forEach(function (b) { b.addEventListener('click', function () { if (!busy) pickTab(b.dataset.tab); }); });
  document.querySelectorAll('[data-tool]').forEach(function (b) { b.addEventListener('click', function () { tool = b.dataset.tool; document.querySelectorAll('[data-tool]').forEach(function (x) { x.classList.toggle('selected', x === b); x.setAttribute('aria-pressed', x === b); }); }); });
  $('play').addEventListener('click', play); $('undo').addEventListener('click', undo); $('redo').addEventListener('click', redo);
  $('startTime').addEventListener('change', function () { remember(); trimTo('in', Number(this.value)); }); $('endTime').addEventListener('change', function () { remember(); trimTo('out', Number(this.value)); });
  $('setStart').addEventListener('click', function () { remember(); trimTo('in', video.currentTime); }); $('setEnd').addEventListener('click', function () { remember(); trimTo('out', video.currentTime); });
  $('whole').addEventListener('click', function () { if (!edit || busy) return; remember(); edit.in_s = 0; edit.out_s = source.duration; changed(); });
  $('audio').addEventListener('change', function () { remember(); audioChosen = true; edit.include_audio = this.checked && source.has_audio; changed(); });
  $('rotate').addEventListener('click', function () { if (!edit || busy) return; remember(); edit.rotation = M.rotation(edit.rotation + 90); changed(); });
  $('fullFrame').addEventListener('click', function () { if (!edit || busy) return; remember(); edit.crop = M.crop(); changed(); });
  document.querySelectorAll('[data-aspect]').forEach(function (b) { b.addEventListener('click', function () { if (!edit || busy) return; remember(); var ratio = Number(b.dataset.aspect); edit.crop = M.aspectCrop(source, edit.rotation % 180 ? 1 / ratio : ratio); changed(); }); });
  $('clearMarks').addEventListener('click', function () { if (!edit || busy) return; remember(); edit.marks = []; changed(); });
  ['brightness', 'contrast', 'saturation'].forEach(function (key) { $(key).addEventListener('pointerdown', remember); $(key).addEventListener('keydown', function (e) { if (!e.repeat && e.key.startsWith('Arrow')) remember(); }); $(key).addEventListener('input', function () { if (edit && !busy) { edit[key] = Number(this.value); changed(); } }); });
  $('resetAdjust').addEventListener('click', function () { if (!edit || busy) return; remember(); edit.brightness = edit.contrast = edit.saturation = 1; changed(); });
  $('retry').addEventListener('click', function () { if (retryAction) retryAction(); });
  $('back').addEventListener('click', function () { video.pause(); if (host !== window) notify('pine-video-editor-close'); else if (history.length > 1) history.back(); else window.close(); });
  document.addEventListener('keydown', function (event) { if ($('recordingEditor').hidden || /INPUT|TEXTAREA/.test(event.target.tagName)) return; if (event.key === ' ') { event.preventDefault(); play(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); } });
  $('soundView').addEventListener('click', function () { showFrequencies = !showFrequencies; $('spectrogram').hidden = !showFrequencies; $('wave').hidden = showFrequencies; this.textContent = showFrequencies ? 'Show waveform' : 'Show frequencies'; });

  /* 2026-09-15 (#1213): A dB RULER, NOT A LINEAR SMEAR.
   *
   * The operator: "the audio visualizer appeared a little flat indicating that
   * maybe it did not pick up the broadcast audio of the station. But I need to
   * always see the audio spectrograph of the station's high points and low
   * points when it comes to broadcasting signal strength."
   *
   * It DID pick it up. ffmpeg on that very recording: mean -42.4 dB, max
   * -24.3 dB. What failed is this drawing. It painted LINEAR amplitude with no
   * reference, so the loudest column in the whole file stood 7.54% of the
   * strip tall and the median 2.38%; and the old floor, Math.max(.5, height),
   * was in DEVICE pixels against an already-scaled canvas, so 1684 of 2048
   * columns collapsed onto one identical line. The strip was not flat because
   * the audio was flat.
   *
   * The floor is ABSOLUTE and never the clip's own maximum. He is asking about
   * signal strength, and under peak-normalisation a -6 dB show and a -40 dB
   * show draw identically - which destroys the one comparison he is making.
   *
   * NOT A MASTERING METER: these peaks come from the server's analyze_audio,
   * where the mono fold sits after the filter chain and is power-preserving,
   * so they read about 3 dB hot by an amount that varies with the material.
   * The labels say dB, never dBFS, and the readout prints the tolerance. */
  var LEVEL_FLOOR_DB = -60, LEVEL_MARKS = [-6, -12, -24, -40];
  function levelDb(amplitude) {
    return amplitude > 0 ? 20 * Math.log10(amplitude) : LEVEL_FLOOR_DB;
  }
  function levelUnit(amplitude) {
    return M.clamp((levelDb(amplitude) - LEVEL_FLOOR_DB) / -LEVEL_FLOOR_DB, 0, 1);
  }
  function levelColour(db) {
    if (db <= LEVEL_FLOOR_DB) return '#3b4048';
    if (db < -39) return '#4e7f72';
    if (db < -12) return '#8cd4c0';
    if (db < -3) return '#ffd60a';
    return '#ff453a';
  }
  /* The ruler is what makes the shape mean anything: without it a tall bar is
   * just a tall bar, and he cannot tell a loud night from a quiet one. */
  function levelRuler(context, c, dpr) {
    var middle = c.height / 2, room = middle - dpr;
    context.lineWidth = Math.max(1, Math.round(dpr));
    LEVEL_MARKS.forEach(function (mark) {
      var offset = (mark - LEVEL_FLOOR_DB) / -LEVEL_FLOOR_DB * room;
      context.strokeStyle = '#ffffff14';
      context.beginPath();
      context.moveTo(0, middle - offset); context.lineTo(c.width, middle - offset);
      context.moveTo(0, middle + offset); context.lineTo(c.width, middle + offset);
      context.stroke();
      if (mark !== -12 && mark !== -40) return;
      context.fillStyle = '#8b8f97'; context.textAlign = 'left';
      context.font = Math.round(9 * dpr) + 'px ui-monospace, system-ui';
      context.fillText(mark + ' dB', 3 * dpr, middle - offset - 2 * dpr);
    });
  }
  /* The numbers were already on the wire and nothing printed them. */
  function levelReadout(src) {
    if (!src || !src.has_audio) return '';
    var peak = Number(src.audio_peak), rms = Number(src.audio_rms);
    if (!(peak > 0)) return 'Broadcast level: silent - the audio track carried no signal.';
    var peakDb = Math.round(levelDb(peak));
    var rmsDb = rms > 0 ? Math.round(levelDb(rms)) : LEVEL_FLOOR_DB;
    return 'Broadcast level: peak ' + peakDb + ' dB, average ' + rmsDb
      + ' dB (approx, +/- 3 dB).' + (peakDb < -30 ? ' Quiet, but present.' : '');
  }
  function waveform() {
    var c = $('wave'), r = c.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(42 * dpr));
    var context = c.getContext('2d'), peaks = source && source.waveform;
    if (peaks && !Array.isArray(peaks)) peaks = peaks.peaks || peaks.values;
    context.fillStyle = '#1a1c21'; context.fillRect(0, 0, c.width, c.height);
    if (!source || !source.has_audio) { context.fillStyle = '#9a9da5'; context.font = 12 * dpr + 'px system-ui'; context.textAlign = 'center'; context.fillText('No audio', c.width / 2, c.height / 2 + 4 * dpr); return; }
    context.font = 12 * dpr + 'px system-ui'; context.textAlign = 'center';
    /* #1213: FOUR STATES, TOLD APART AT A GLANCE. No track at all gets no
     * ruler, because there is nothing to measure - that is how "no audio"
     * reads differently from "silence" and from "quiet". */
    if (!source || !source.has_audio) {
      context.fillStyle = '#9a9da5';
      context.fillText('No audio in this recording', c.width / 2, c.height / 2 + 4 * dpr);
      return;
    }
    if (!Array.isArray(peaks) || !peaks.length) {
      context.fillStyle = '#9a9da5';
      context.fillText(source.status === 'ready' ? 'Audio waveform unavailable' : 'Reading audio…',
        c.width / 2, c.height / 2 + 4 * dpr);
      return;
    }
    levelRuler(context, c, dpr);
    var middle = c.height / 2, room = middle - dpr;
    var step = Math.max(1, Math.round(dpr * 2)), columns = Math.ceil(c.width / step);
    context.lineWidth = Math.max(1, dpr);
    for (var i = 0; i < columns; i += 1) {
      /* #1213: the old draw point-sampled ONE peak per column and threw the
       * rest away, so transients - the "high points" he asked for - were the
       * first thing lost. Max-over-column keeps them. */
      var lo = Math.floor(i * peaks.length / columns);
      var hi = Math.max(lo + 1, Math.floor((i + 1) * peaks.length / columns));
      var amplitude = 0, k, raw, one;
      for (k = lo; k < hi && k < peaks.length; k += 1) {
        raw = peaks[k];
        one = Array.isArray(raw) ? Math.max.apply(null, raw.map(Math.abs)) : Math.abs(Number(raw) || 0);
        if (one > amplitude) amplitude = one;
      }
      amplitude = Math.min(1, amplitude);
      var db = levelDb(amplitude), half = levelUnit(amplitude) * room;
      /* The floor is one CSS pixel, not one device pixel: the old device-pixel
       * floor made the strip literally differ between his two monitors. And a
       * column that carries signal must never share a pixel with one that
       * does not. */
      half = Math.max(amplitude > 0 ? dpr : dpr * 0.5, half);
      context.strokeStyle = levelColour(db);
      context.beginPath();
      context.moveTo(i * step, middle - half);
      context.lineTo(i * step, middle + half);
      context.stroke();
    }
  }
  function filmstrip() {
    var frames = $('frames'), list = source.thumbnails || [], sprite = source.thumbnail_sprite;
    var signature = JSON.stringify([list, sprite]); if (frames.dataset.signature === signature) return; frames.dataset.signature = signature; frames.replaceChildren();
    if (Array.isArray(list) && list.length) list.slice(0, 16).forEach(function (item) { var img = document.createElement('img'); img.alt = ''; img.src = typeof item === 'string' ? item : item.url; frames.appendChild(img); });
    else if (sprite && sprite.url && sprite.count) {
      var count = Math.min(16, sprite.count), columns = sprite.columns || sprite.count, rows = Math.ceil(sprite.count / columns);
      for (var i = 0; i < count; i += 1) { var tile = document.createElement('div'), index = Math.round(i * (sprite.count - 1) / Math.max(1, count - 1)); tile.className = 'sprite'; tile.style.backgroundImage = 'url(' + JSON.stringify(sprite.url) + ')'; tile.style.backgroundSize = columns * 100 + '% ' + rows * 100 + '%'; tile.style.backgroundPosition = (columns > 1 ? index % columns / (columns - 1) * 100 : 0) + '% ' + (rows > 1 ? Math.floor(index / columns) / (rows - 1) * 100 : 0) + '%'; frames.appendChild(tile); }
    }
  }
  function hydrate(result) {
    source = result; source.id = source.id || sourceId; source.duration = Number(source.duration); source.width = Number(source.width); source.height = Number(source.height);
    if (!edit) edit = M.create(source);
    if (!audioChosen && source.status === 'ready') edit.include_audio = !!source.has_audio;
    if (!source.has_audio) edit.include_audio = false;
    $('sourceName').textContent = source.name || 'Captured video';
    coverPoster($('recordingCover'), source);
    if (loadedUrl !== source.url) {
      loadedUrl = source.url; hasFrame = false;
      $('recordingCover').hidden = false;
      loadPhase = 'opening'; showLoading('Opening the recording…', -1);
      video.src = source.url; video.load(); armLoadWatchdog();     /* #1213 */
    }
    var sprite = source.thumbnail_sprite;                          /* #1213 */
    if (sprite && sprite.url && sprite.url !== spriteUrl) {
      spriteUrl = sprite.url; spriteImage = new Image(); spriteImage.src = sprite.url;
    }
    var spectrum = source.spectrogram_url; if (spectrum) { $('spectrogram').src = spectrum; $('soundView').disabled = false; }
    /* #1213: he got no text at all to contradict what his eyes told him.
     * audio_peak and audio_rms were already on the wire and nothing printed
     * them, so a quiet broadcast and a failed capture read identically. */
    var notice = M.audioNotice(source), readout = notice || levelReadout(source);
    $('audioNotice').textContent = readout; $('audioNotice').hidden = !readout;
    $('audioNotice').classList.toggle('level', !notice && !!readout);
    filmstrip(); waveform(); changed();
    if (sfxClip && source.status === 'ready' && source.pine_sfx && source.pine_sfx.audio_only) {
      $('openSplit').hidden = false;
      if (!sfxSplitController) sfxSplitController = createSfxSplitController(source);
      if (!sfxSingleMode) sfxSplitController.open();
    }
  }
  async function retrySource() {
    if (!sourceFailed) return loadSource();
    try { status('Opening your recording…'); await api('POST', '/api/video-editor/sources/' + encodeURIComponent(sourceId) + '/retry', {}); sourceFailed = false; loadSource(); }
    catch (error) { status(error.message || 'The recording could not be reopened.', true, retrySource); }
  }
  async function loadSource() {
    clearTimeout(sourcePoll);
    if (!sourceId) { $('loading').textContent = 'No recording selected'; status('Open a recording to edit it.', true); return; }
    status('Opening your recording…');
    try {
      var result = await api('GET', '/api/video-editor/sources/' + encodeURIComponent(sourceId)); if (disposed) return;
      permitTake(result);                                                          /* [#1242] */
      sourceFailed = result.status === 'failed' || result.status === 'error';
      if (sourceFailed) throw new Error(result.error || 'The recording could not be opened.');
      if (result.url && result.duration > 0 && result.width > 0 && result.height > 0) hydrate(result);
      if (['processing', 'queued', 'working'].includes(result.status) || !edit) { status(edit ? 'Preparing the timeline…' : 'Opening your recording…'); sourcePoll = setTimeout(loadSource, 1200); }
      else status('Your original recording is kept.');
    } catch (error) { status(error.message || 'The recording could not be opened.', true, retrySource); if (!edit) $('loading').textContent = 'Could not open the recording'; }
  }
  function overlayImage() {
    if (!edit.marks.length) return '';
    if (source.width * source.height > 32000000) throw new Error('This recording is too large to draw on here. Clear the drawings and try again.');
    var c = document.createElement('canvas'); c.width = source.width; c.height = source.height;
    drawMarks(c.getContext('2d'), edit.marks, source.width, source.height); return c.toDataURL('image/png');
  }
  async function deliverToShare(result) {
    var endpoint = '/api/video-editor/exports/' + encodeURIComponent(result.id);
    var delivery = await api('GET', endpoint + '/delivery');
    if (delivery.status === 'not_requested' || delivery.status === 'failed') {
      status('Sending your copy to the recordings share...');
      await api('POST', endpoint + '/courier', {});
      delivery = await api('GET', endpoint + '/delivery');
    }
    var deadline = Date.now() + 120000;
    while (['pending', 'verifying', 'not_ready'].includes(delivery.status)) {
      if (Date.now() >= deadline) {
        throw new Error('The copy is rendered, but delivery to the recordings share is still unconfirmed. Try the save again or keep the edited copy on this device.');
      }
      status(delivery.status === 'verifying'
        ? 'Checking the copy on the recordings share...'
        : 'Waiting for the Windows desk to deliver your copy...');
      await exportHold(2000);
      delivery = await api('GET', endpoint + '/delivery');
    }
    if (delivery.status !== 'delivered' || !delivery.path) {
      throw new Error(delivery.error || 'The rendered copy did not reach the recordings share.');
    }
    return delivery;
  }

  async function finishSave(result) {
    lastExport = result;                                                           /* [#1242] */
    $('download').href = result.url || '/api/video-editor/exports/' + result.id + '/file'; $('download').download = result.name || 'edited-video.mp4'; $('download').hidden = false;
    $('save').textContent = 'Delivering...';
    var local = null;
    try {
      if (typeof bridge.replayKeepEdited === 'function') {
        local = await bridge.replayKeepEdited({export_id: result.id, name: result.name});
      } else if (typeof bridge.saveBytes === 'function') {
        local = await keepOnDevice($('download').href, $('download').download);
      }
    } catch (error) { local = {ok: false, detail: error.message}; }
    var delivered;
    try { delivered = await deliverToShare(result); }
    catch (error) {
      if (local && local.ok && local.where) {
        error.message += ' A separate device copy was kept at ' + local.where + '.';
      }
      throw error;
    }
    status('Saved to ' + delivered.path + '. Your original is kept.');
    toast('Saved to ' + delivered.path);
    notify('pine-video-editor-export', {id: result.id, export_id: result.id,
      url: result.url, name: result.name, path: delivered.path});
  }
  async function save(land) {
    if (!source || !edit || busy || source.status !== 'ready') return;
    busy = true; video.pause(); document.body.classList.add('busy'); $('save').textContent = 'Saving…'; changed(); $('download').hidden = true;
    try {
      status('Creating your copy…');
      exportShow(0);                                                               /* [#1207] */
      var body = M.exportBody(source, edit, overlayImage()), signature = JSON.stringify(body);
      if (savePermit) body.save_token = savePermit;             /* [#1242] after the signature, never in it */
      if (!exportState || exportState.signature !== signature) exportState = {signature: signature, result: await api('POST', '/api/video-editor/exports', body)};
      var result = exportState.result, id = result.id;
      while (!['complete', 'done', 'failed', 'error'].includes(result.status)) {
        if (disposed) return;
        await new Promise(function (resolve) { setTimeout(resolve, 1000); });
        result = await api('GET', result.poll_url || '/api/video-editor/exports/' + encodeURIComponent(id));
        result.id = result.id || id; exportState.result = result;
        if (result.progress !== undefined) {
          /* [#1207] one reading, three places: the scan bar, the flat bar and
           * the footer. The number is ffmpeg's own out_time, not a guess. */
          var share = Number(result.progress) <= 1 ? Number(result.progress) : Number(result.progress) / 100;
          exportShow(share);
          status('Creating your copy… ' + Math.round(share * 100) + '%'
            + (result.eta_s > 1 ? ' · about ' + Math.round(result.eta_s) + 's left' : ''));
        }
      }
      if (['failed', 'error'].includes(result.status)) { exportState = null; throw new Error(result.error || 'The copy could not be made.'); }
      lastExport = result; exportShow(1); await exportHold(420);                   /* [#1207] the bar lands on 100 */
      result.id = result.id || id;
      exportHide();
      /* [#1223] the one export loop, two landings. A click Event is not a
         function, so the plain Save copy button still lands in
         finishSave() exactly as it always has. */
      await (typeof land === 'function' ? land(result) : finishSave(result));
    } catch (error) { saveEscape(error); }                                         /* [#1242] */
    finally { exportHide(); busy = false; document.body.classList.remove('busy'); $('save').textContent = 'Save copy'; changed(); }
  }

  /* ---------------- [#1223] back over the library clip ---------------- */

  /* What the save will do, asked of the station rather than guessed here:
     the container has the samples share mounted READ-ONLY, so for most
     clips "save over the original" cannot mean what it says, and the
     honest answer - a copy in the station's own folder that supersedes
     the original - has to be in front of the operator BEFORE the render,
     not in an error after it. */
  async function sfxWhere() {
    var button = $('saveOver'), notice = $('sfxNotice');
    if (!sfxClip || !sourceId || !button) return;
    try {
      sfxPlan = await api('GET', '/api/sfx/edit/where?source=' + encodeURIComponent(sourceId));
    } catch (error) { sfxPlan = null; }
    if (!sfxPlan || !sfxPlan.ok) return;
    button.hidden = false;
    button.textContent = sfxPlan.in_place ? 'Save over the original' : 'Save and replace on air';
    button.title = String(sfxPlan.say || '');
    var line = String(sfxPlan.say || '');
    if (sfxPlan.supports) line += '. This editor gives you ' + sfxPlan.supports + '.';
    if (notice) { notice.textContent = line; notice.hidden = !line; }
  }

  async function landOnClip(result) {
    status('Putting it back in the library…');
    var saved = await api('POST', '/api/sfx/edit/save', {export: result.id});
    status(String(saved.say || 'Saved.'));
    /* The sheet that opened this editor listens for this and reopens on
       whatever clip goes out from now on - the same file when the save
       was in place, the edited copy when it was not. */
    notify('pine-sfx-edit-saved', saved);
  }

  if ($('saveOver')) $('saveOver').addEventListener('click', function () { save(landOnClip); });
  $('openSplit').addEventListener('click', function () { if (sfxSplitController) sfxSplitController.open(); });
  sfxWhere();
  $('save').addEventListener('click', save);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { repaint(); waveform(); }).observe(viewer);
  else window.addEventListener('resize', function () { repaint(); waveform(); });
  window.addEventListener('pagehide', function () { disposed = true; video.pause(); clearTimeout(sourcePoll); cancelAnimationFrame(raf); });

  /* ==========================================================================
   * [#1242] A SAVE THAT CANNOT END IN "UNAUTHORIZED"
   * [#1207] and an export that can be WATCHED, on the footage
   *
   * "There should be no reason that I'm not able to save a clip ever. So it
   *  needs to at least pop up a window letting me export and save a clip."
   *
   * Everything below is additive: new top-level functions inside this IIFE.
   * ======================================================================== */

  var savePermit = new URLSearchParams(location.search).get('save') || '';
  var savePermitAsked = 0, lastExport = null;

  /* The source record carries a permit for ITS OWN source id. Reads are open
   * on this station, so this is the road that works on every surface — the
   * desk's cross-origin iframe included. */
  function permitTake(record) {
    if (record && record.save_token) savePermit = String(record.save_token);
  }

  /* The page that opened us holds the key. hot-corners.js answers this ask by
   * minting on /api/video-editor/sources/<id>/save-token and posting the
   * permit back. The reply is accepted only from our own parent — the only
   * window that could already navigate us anywhere it liked. */
  function permitFromOpener() {
    var up = null;
    try { up = window.parent && window.parent !== window ? window.parent : null; } catch (err) { up = null; }
    if (!up || !sourceId) return Promise.resolve(false);
    return new Promise(function (resolve) {
      var settled = false;
      function heard(event) {
        if (settled || event.source !== up) return;
        var said = event.data;
        if (!said || said.type !== 'pine-video-editor-save-token') return;
        settled = true; window.removeEventListener('message', heard);
        var got = (said.detail && said.detail.save_token) || said.save_token || '';
        if (got) savePermit = String(got);
        resolve(!!got);
      }
      window.addEventListener('message', heard);
      try { up.postMessage({type: 'pine-video-editor-need-save-token', detail: {source_id: sourceId}}, '*'); }
      catch (err) { /* the parent is gone; the timer below closes it out */ }
      setTimeout(function () {
        if (settled) return;
        settled = true; window.removeEventListener('message', heard); resolve(false);
      }, 2500);
    });
  }

  async function permitRenew() {
    if (!sourceId) return false;
    var now = Date.now();
    if (now - savePermitAsked < 1500) return false;
    savePermitAsked = now;
    var had = savePermit;
    try {
      var answer = await fetch('/api/video-editor/sources/' + encodeURIComponent(sourceId)
        + '?mint=' + now, {cache: 'no-store'});
      if (answer.ok) { var record = await answer.json(); permitTake(record); }
    } catch (err) { /* the read door is shut too; ask the opener */ }
    if (savePermit && savePermit !== had) return true;
    await permitFromOpener();
    return !!savePermit && savePermit !== had;
  }

  /* ------------------------------------------------ putting a file on a device */

  function bytesToBase64(buffer) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { var s = String(reader.result || ''); resolve(s.slice(s.indexOf(',') + 1)); };
      reader.onerror = function () { reject(new Error('the clip could not be read back')); };
      reader.readAsDataURL(new Blob([buffer], {type: 'video/mp4'}));
    });
  }

  function safeName(name, fallback) {
    var said = String(name || '').replace(/[^\w.() -]+/g, '-').replace(/\s+/g, ' ').trim();
    if (!said) said = fallback;
    if (!/\.mp4$/i.test(said)) said += '.mp4';
    return said.slice(-120);
  }

  /* Two roads, because the two surfaces are genuinely different. An <a download>
   * is INERT inside the tablet's WebView, so there the bytes go through the
   * native MediaStore road the sampler kits already use. On the desk the anchor
   * IS the road: Electron catches it in will-download (main.js, session-created)
   * and opens the save window on the folder the last save went to. */
  async function keepOnDevice(url, name) {
    var called = safeName(name, 'pine-edited');
    if (typeof bridge.saveBytes === 'function') {
      try {
        var raw = await fetch(url, {cache: 'no-store'});
        if (!raw.ok) throw new Error('the station would not hand the file over (' + raw.status + ')');
        var b64 = await bytesToBase64(await raw.arrayBuffer());
        var kept = await bridge.saveBytes({base64: b64, name: called, folder: 'Pine Box', mime: 'video/mp4'});
        if (kept && kept.ok) return {ok: true, road: 'tablet', where: kept.where || 'Downloads/Pine Box'};
        return {ok: false, road: 'tablet', where: '', detail: (kept && kept.detail) || 'the tablet would not write the file'};
      } catch (err) { return {ok: false, road: 'tablet', where: '', detail: err.message}; }
    }
    try {
      var link = document.createElement('a');
      link.href = url; link.download = called; link.rel = 'noopener'; link.style.display = 'none';
      document.body.appendChild(link); link.click();
      setTimeout(function () { if (link.parentNode) link.parentNode.removeChild(link); }, 4000);
      return {ok: true, road: 'dialog', where: ''};
    } catch (err) { return {ok: false, road: 'dialog', where: '', detail: err.message}; }
  }

  function originalUrl() {
    return (source && source.url) || ('/api/video-editor/sources/' + encodeURIComponent(sourceId) + '/file');
  }

  /* ------------------------------------------------------------------ toast */

  function toast(text) {
    var node = document.getElementById('veToast');
    if (!node) {
      node = document.createElement('div');
      node.id = 'veToast'; node.className = 've-toast'; node.setAttribute('role', 'status');
      document.body.appendChild(node);
    }
    node.textContent = String(text || '');
    node.classList.add('on');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { node.classList.remove('on'); }, 7000);
  }

  /* --------------------------------------------------------- the escape window */

  function escapeClose() {
    var old = document.getElementById('veEscape');
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

  /* Every failure the save can suffer ends here, and this window never offers
   * a road that needs the station's permission. The original recording can
   * always be kept: reading it is the same open read that painted the
   * filmstrip on this very screen. */
  function showEscape(why) {
    escapeClose();
    var box = document.createElement('div');
    box.className = 've-escape'; box.id = 'veEscape';
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Other ways to save this clip');
    var card = document.createElement('div'); card.className = 've-escape-card';
    var head = document.createElement('h2'); head.textContent = 'Save this clip another way';
    var said = document.createElement('p'); said.className = 've-escape-why'; said.textContent = String(why || 'The copy could not be saved.');
    var kept = document.createElement('p'); kept.className = 've-escape-note';
    kept.textContent = 'Your original recording is kept whatever you choose here.';
    var told = document.createElement('p'); told.className = 've-escape-told'; told.setAttribute('role', 'status'); told.hidden = true;
    var rows = document.createElement('div'); rows.className = 've-escape-rows';
    card.appendChild(head); card.appendChild(said); card.appendChild(kept); card.appendChild(rows); card.appendChild(told);
    box.appendChild(card); document.body.appendChild(box);

    function tell(text, bad) { told.textContent = text; told.hidden = !text; told.classList.toggle('bad', !!bad); }
    function row(label, hint, run) {
      var line = document.createElement('div'); line.className = 've-escape-row';
      var press = document.createElement('button'); press.type = 'button'; press.textContent = label;
      var note = document.createElement('span'); note.textContent = hint;
      press.addEventListener('click', async function () {
        press.disabled = true; tell('Working…');
        try { await run(tell); } catch (err) { tell(err.message || 'That road did not answer either.', true); }
        press.disabled = false;
      });
      line.appendChild(press); line.appendChild(note); rows.appendChild(line);
      return press;
    }

    if (lastExport && lastExport.id) {
      row('Keep the edited copy', 'the trimmed clip, on this device', async function (tell) {
        var got = await keepOnDevice(lastExport.url || ('/api/video-editor/exports/' + lastExport.id + '/file'),
          lastExport.name || 'pine-edited.mp4');
        if (got.ok && got.where) { tell('Kept to ' + got.where); toast('Saved to ' + got.where); }
        else if (got.ok) tell('The save window is open — choose where to keep it.');
        else tell(got.detail || 'This device would not take the file.', true);
      });
      row('Send it to recordings', 'copy to the Windows share and verify it', async function (tell) {
        var delivered = await deliverToShare(lastExport);
        tell('Saved to ' + delivered.path);
        toast('Saved to ' + delivered.path);
      });
    }
    row('Keep the original recording', 'untrimmed, and it always works', async function (tell) {
      var got = await keepOnDevice(originalUrl(), source && source.name ? source.name : 'pine-recording');
      if (got.ok && got.where) { tell('Kept to ' + got.where); toast('Saved to ' + got.where); }
      else if (got.ok) tell('The save window is open — choose where to keep it.');
      else tell(got.detail || 'This device would not take the file.', true);
    });
    row('Try the save again', 'ask the station once more', async function () { escapeClose(); save(); });

    var shut = document.createElement('button');
    shut.type = 'button'; shut.className = 'quiet ve-escape-shut'; shut.textContent = 'Close';
    shut.addEventListener('click', escapeClose);
    card.appendChild(shut);
    box.addEventListener('click', function (event) { if (event.target === box) escapeClose(); });
    setTimeout(function () { try { card.querySelector('button').focus(); } catch (err) { /* no focus */ } }, 0);
  }

  function saveEscape(error) {
    var why = (error && error.message) || 'The copy could not be saved.';
    if (error && error.locked) {
      why = 'This editor window has no live permission to render a copy, so the '
        + 'station refused. Everything below saves the clip without it.';
    }
    status(why, true, save);
    showEscape(why);
  }

  /* ====================================================== [#1207] the scan bar
   * "I want to see a 3JS powered visualization of a loading bar happening on
   *  the footage showing the progress of it happening while it's being
   *  exported with a loading bar kind of scrolling across on the footage."
   *
   * three.js is VENDORED — the station serves it at /vendor/three.min.js and
   * this page is served BY the station, so the bare path is right and no CDN
   * is ever reached (the tablet has no internet). Where there is no WebGL the
   * flat bar underneath carries the same number.
   * ======================================================================== */

  var exportLayer = null, exportScene = null, exportTried = false, exportRaf = 0;
  var exportSeen = 0, exportAt = 0, exportT0 = 0;

  function threeReady() {
    if (window.THREE) return Promise.resolve(window.THREE);
    /* Same-origin parent (the tablet's panel) has already paid for three.js. */
    try { if (host !== window && host.THREE) { window.THREE = host.THREE; return Promise.resolve(window.THREE); } }
    catch (err) { /* cross-origin parent; load our own */ }
    if (threeReady.pending) return threeReady.pending;
    threeReady.pending = new Promise(function (resolve) {
      var tag = document.createElement('script');
      tag.src = '/vendor/three.min.js';
      tag.onload = function () { resolve(window.THREE || null); };
      tag.onerror = function () { resolve(null); };
      document.head.appendChild(tag);
    });
    return threeReady.pending;
  }

  function buildExportLayer() {
    var root = document.createElement('div');
    root.className = 've-export'; root.id = 'veExport'; root.hidden = true;
    var glass = document.createElement('canvas'); glass.className = 've-export-gl';
    var say = document.createElement('span'); say.className = 've-export-say'; say.textContent = 'Exporting this segment';
    var pct = document.createElement('span'); pct.className = 've-export-pct'; pct.textContent = '0%';
    var bar = document.createElement('div'); bar.className = 've-export-bar';
    var fill = document.createElement('i'); fill.className = 've-export-fill';
    bar.appendChild(fill);
    root.appendChild(glass); root.appendChild(say); root.appendChild(pct); root.appendChild(bar);
    viewer.appendChild(root);
    return {root: root, glass: glass, bar: bar, fill: fill, pct: pct, say: say};
  }

  function makeScanScene(THREE, glass) {
    var renderer = new THREE.WebGLRenderer({canvas: glass, alpha: true, antialias: false});
    renderer.setClearColor(0x000000, 0);
    var camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0, 10);
    camera.position.z = 2;
    var scene = new THREE.Scene();
    var uniforms = {uHead: {value: 0}, uDone: {value: 0}, uTime: {value: 0}};
    var sheet = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShaderMaterial({
      uniforms: uniforms, transparent: true, depthTest: false, depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: 'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader: [
        'precision mediump float;',
        'varying vec2 vUv;uniform float uHead;uniform float uDone;uniform float uTime;',
        'void main(){',
        '  float d = abs(vUv.x - uHead);',
        '  float core = smoothstep(0.010, 0.0, d);',
        '  float halo = smoothstep(0.100, 0.0, d) * 0.34;',
        '  float ripple = 0.11 * smoothstep(0.24, 0.0, d) * (0.5 + 0.5 * sin(vUv.y * 46.0 - uTime * 4.2));',
        '  float behind = step(vUv.x, uDone) * 0.085;',
        '  float rail = smoothstep(0.006, 0.0, min(vUv.y, 1.0 - vUv.y)) * step(vUv.x, uDone) * 0.30;',
        '  float a = core + halo + ripple + behind + rail;',
        '  vec3 col = mix(vec3(1.00, 0.84, 0.04), vec3(0.22, 0.76, 1.00), clamp(d * 9.0, 0.0, 1.0));',
        '  gl_FragColor = vec4(col, clamp(a, 0.0, 0.85));',
        '}'
      ].join('\n')
    }));
    scene.add(sheet);
    var N = 240, pos = new Float32Array(N * 3), seed = new Float32Array(N * 3);
    for (var i = 0; i < N; i += 1) {
      seed[i * 3] = Math.random();
      seed[i * 3 + 1] = Math.random() - 0.5;
      seed[i * 3 + 2] = 0.4 + Math.random() * 1.8;
    }
    var cloud = new THREE.BufferGeometry();
    cloud.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    scene.add(new THREE.Points(cloud, new THREE.PointsMaterial({
      color: 0xffd60a, size: 2.4, sizeAttenuation: false, transparent: true,
      opacity: .55, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending
    })));
    return {renderer: renderer, camera: camera, scene: scene, uniforms: uniforms,
      pos: pos, seed: seed, n: N, attr: cloud.getAttribute('position'), w: 0, h: 0};
  }

  function startExportGl() {
    exportTried = true;
    var able = false;
    try { var probe = document.createElement('canvas'); able = !!(probe.getContext('webgl2') || probe.getContext('webgl')); }
    catch (err) { able = false; }
    if (!able) { exportLayer.root.classList.add('flat'); return; }
    threeReady().then(function (THREE) {
      if (!THREE || !exportLayer) { if (exportLayer) exportLayer.root.classList.add('flat'); return; }
      try { exportScene = makeScanScene(THREE, exportLayer.glass); }
      catch (err) { exportScene = null; exportLayer.root.classList.add('flat'); }
    });
  }

  function exportTick() {
    exportRaf = 0;
    if (!exportLayer || exportLayer.root.hidden) return;
    var now = (window.performance && performance.now ? performance.now() : Date.now()) / 1000;
    if (!exportT0) exportT0 = now;
    exportAt += (exportSeen - exportAt) * .10;
    var head = Math.min(1, exportAt + .055 * (.5 + .5 * Math.sin((now - exportT0) * 2.1)));
    exportLayer.fill.style.width = (exportAt * 100).toFixed(1) + '%';
    exportLayer.pct.textContent = Math.round(exportSeen * 100) + '%';
    var s = exportScene;
    if (s) {
      var w = viewer.clientWidth, h = viewer.clientHeight;
      if (w !== s.w || h !== s.h) {
        s.w = w; s.h = h;
        s.renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
        s.renderer.setSize(w, h, false);
      }
      s.uniforms.uHead.value = head;
      s.uniforms.uDone.value = exportAt;
      s.uniforms.uTime.value = now - exportT0;
      for (var i = 0; i < s.n; i += 1) {
        var lag = s.seed[i * 3] * .15 * (.45 + .55 * Math.sin((now - exportT0) * s.seed[i * 3 + 2] + i));
        s.pos[i * 3] = head - .5 - Math.abs(lag);
        s.pos[i * 3 + 1] = s.seed[i * 3 + 1] * .96;
        s.pos[i * 3 + 2] = 0;
      }
      s.attr.needsUpdate = true;
      try { s.renderer.render(s.scene, s.camera); }
      catch (err) { exportScene = null; exportLayer.root.classList.add('flat'); }
    }
    exportRaf = requestAnimationFrame(exportTick);
  }

  function exportHold(ms) { return new Promise(function (settle) { setTimeout(settle, ms); }); }

  function exportShow(share) {
    exportSeen = Math.max(0, Math.min(1, Number(share) || 0));
    if (!exportLayer) exportLayer = buildExportLayer();
    exportLayer.root.hidden = false;
    /* Painted here as well as in the tick, so the number is right the instant
     * it is known - the last reading of a short render is otherwise only ever
     * seen by a frame that never gets to run. */
    exportLayer.pct.textContent = Math.round(exportSeen * 100) + '%';
    if (exportSeen >= 1) { exportAt = 1; exportLayer.fill.style.width = '100%'; }
    if (!exportTried) startExportGl();
    if (!exportRaf) exportRaf = requestAnimationFrame(exportTick);
  }

  function exportHide() {
    if (exportRaf) { cancelAnimationFrame(exportRaf); exportRaf = 0; }
    if (exportLayer) { exportLayer.root.hidden = true; exportLayer.fill.style.width = '0%'; }
    exportSeen = 0; exportAt = 0; exportT0 = 0;
  }

  /* ============================================ [#1242] Photoshop navigation
   * The standing rule for every editor window: wheel zoom about the pointer,
   * middle-drag pan, 0 to fit. Space is NOT a pan modifier on this surface —
   * it has a transport, and space is play/pause, which the rule keeps.
   *
   * Zoom is applied to frameRect, the one rectangle the whole editor already
   * measures against, so the crop corners, the ink and the click-to-scrub all
   * follow the zoom without any of them knowing it exists.
   * ======================================================================== */

  var view = {scale: 1, x: 0, y: 0}, viewPan = null;

  function viewApply(r) {
    if (view.scale === 1 && !view.x && !view.y) return r;
    var cx = viewer.clientWidth / 2, cy = viewer.clientHeight / 2;
    return {x: cx + (r.x - cx) * view.scale + view.x, y: cy + (r.y - cy) * view.scale + view.y,
      w: r.w * view.scale, h: r.h * view.scale};
  }

  function viewClamp() {
    if (view.scale <= 1.001) { view.scale = 1; view.x = 0; view.y = 0; }
    else {
      var w = viewer.clientWidth, h = viewer.clientHeight;
      view.x = M.clamp(view.x, -w * view.scale, w * view.scale);
      view.y = M.clamp(view.y, -h * view.scale, h * view.scale);
    }
    viewer.classList.toggle('ve-zoomed', view.scale > 1.001);
  }

  function viewZoom(factor, px, py) {
    var next = M.clamp(view.scale * factor, 1, 12);
    if (Math.abs(next - view.scale) < 1e-6) return;
    var cx = viewer.clientWidth / 2, cy = viewer.clientHeight / 2, k = next / view.scale;
    view.x = px - cx - (px - cx - view.x) * k;
    view.y = py - cy - (py - cy - view.y) * k;
    view.scale = next;
    viewClamp(); repaint();
  }

  function viewFit() { view.scale = 1; view.x = 0; view.y = 0; viewClamp(); repaint(); }

  viewer.addEventListener('wheel', function (event) {
    if (!source || busy) return;
    event.preventDefault();
    var r = viewer.getBoundingClientRect();
    var step = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1);
    viewZoom(Math.pow(.9985, step), event.clientX - r.left, event.clientY - r.top);
  }, {passive: false});

  /* Capture phase on the viewer, so the middle button never reaches the
   * canvas's own pointerdown and starts a scrub, a stroke or a crop. */
  viewer.addEventListener('pointerdown', function (event) {
    if (event.button !== 1 || !source || busy) return;
    event.preventDefault(); event.stopPropagation();
    viewPan = {id: event.pointerId, x: event.clientX, y: event.clientY};
    viewer.classList.add('ve-panning');
    try { viewer.setPointerCapture(event.pointerId); } catch (err) { /* no capture here */ }
  }, true);
  viewer.addEventListener('pointermove', function (event) {
    if (!viewPan || viewPan.id !== event.pointerId) return;
    event.preventDefault(); event.stopPropagation();
    view.x += event.clientX - viewPan.x; view.y += event.clientY - viewPan.y;
    viewPan.x = event.clientX; viewPan.y = event.clientY;
    viewClamp(); repaint();
  }, true);
  ['pointerup', 'pointercancel'].forEach(function (name) {
    viewer.addEventListener(name, function (event) {
      if (!viewPan || viewPan.id !== event.pointerId) return;
      event.stopPropagation(); viewPan = null; viewer.classList.remove('ve-panning');
      try { viewer.releasePointerCapture(event.pointerId); } catch (err) { /* already gone */ }
    }, true);
  });
  viewer.addEventListener('auxclick', function (event) { if (event.button === 1) event.preventDefault(); });
  document.addEventListener('keydown', function (event) {
    if ($('recordingEditor').hidden) return;
    if (/INPUT|TEXTAREA/.test(event.target.tagName) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'Escape' && document.getElementById('veEscape')) { event.preventDefault(); escapeClose(); return; }
    if (event.key === '0') { event.preventDefault(); viewFit(); }
    else if (event.key === '+' || event.key === '=') { event.preventDefault(); viewZoom(1.25, viewer.clientWidth / 2, viewer.clientHeight / 2); }
    else if (event.key === '-' || event.key === '_') { event.preventDefault(); viewZoom(.8, viewer.clientWidth / 2, viewer.clientHeight / 2); }
  });
  window.addEventListener('pagehide', function () {
    exportHide();
    if (exportScene) { try { exportScene.renderer.dispose(); } catch (err) { /* going anyway */ } exportScene = null; }
  });

  function createSfxSplitController(record) {
    var media = $('splitMedia'), scrub = $('splitScrub'), timeline = $('splitTimeline');
    var mediaCover = bindMediaCover(media, $('splitCover'));
    mediaCover.setPoster(record);
    var pieces = [M.audioSplitCreate(record)], selected = 0, at = 0, activeIndex = 0, pending = 0;
    var past = [], future = [], mode = 'sequence', playing = false, exporting = false, waveRaf = 0;
    var trimGesture = null;

    function tell(message, error) {
      $('splitStatus').textContent = message;
      $('splitStatus').classList.toggle('error', !!error);
    }
    function total() { return M.spliceLength(pieces); }
    function startOf(index) {
      var sum = 0;
      for (var i = 0; i < index; i += 1) sum += pieces[i].out_s - pieces[i].in_s;
      return sum;
    }
    function bounds() {
      if (mode === 'piece' && pieces[selected]) return {start: startOf(selected), end: startOf(selected + 1)};
      return {start: 0, end: total()};
    }
    function stop() {
      playing = false; media.pause();
      $('splitPlay').textContent = 'Play'; $('splitPlay').setAttribute('aria-label', 'Play ' + (mode === 'piece' ? 'piece' : 'sequence'));
    }
    function paintPosition() {
      var range = bounds(), local = M.clamp(at - range.start, 0, range.end - range.start);
      $('splitPosition').textContent = M.clock(local) + ' / ' + M.clock(range.end - range.start);
      scrub.min = String(range.start); scrub.max = String(Math.max(range.end, range.start + .01));
      scrub.value = String(M.clamp(at, range.start, range.end));
      var place = M.spliceLocate(pieces, at);
      var sourceAt = mode === 'piece' && pieces[selected] && at >= range.end
        ? pieces[selected].out_s : place ? place.source_s : 0;
      $('splitTrimHead').style.left = M.clamp(sourceAt / record.duration, 0, 1) * 100 + '%';
    }
    function playFailed() { stop(); tell('Tap Play again to start the preview.', true); }
    function applyPending() {
      if (pending === null || media.readyState < 1) return;
      try {
        if (Math.abs(media.currentTime - pending) > .025) media.currentTime = pending;
        else { pending = null; if (playing) media.play().catch(playFailed); }
      } catch (_) { /* metadata is arriving */ }
    }
    function seekGlobal(position) {
      var range = bounds();
      at = M.clamp(position, range.start, range.end);
      var place = M.spliceLocate(pieces, at);
      paintPosition();
      if (!place) { stop(); return; }
      activeIndex = place.index;
      pending = place.source_s;
      applyPending();
    }
    function onTime() {
      if (pending !== null || media.seeking || !pieces[activeIndex]) return;
      var clip = pieces[activeIndex];
      if (media.currentTime >= clip.out_s - .02) {
        if (mode === 'sequence' && activeIndex < pieces.length - 1) seekGlobal(startOf(activeIndex + 1));
        else { at = mode === 'piece' ? startOf(selected + 1) : total(); stop(); paintPosition(); }
        return;
      }
      at = startOf(activeIndex) + M.clamp(media.currentTime - clip.in_s, 0, clip.out_s - clip.in_s);
      paintPosition();
    }
    media.addEventListener('loadedmetadata', function () { $('splitLoading').hidden = true; applyPending(); });
    media.addEventListener('loadeddata', function () { $('splitLoading').hidden = true; applyPending(); });
    media.addEventListener('seeked', function () { pending = null; if (playing) media.play().catch(playFailed); onTime(); });
    media.addEventListener('timeupdate', onTime);
    media.addEventListener('ended', onTime);
    media.addEventListener('error', function () { stop(); tell('The audio preview could not load.', true); });

    function drawWave(canvas, start, end) {
      var rect = canvas.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
      var w = Math.max(1, Math.round(rect.width * dpr)), h = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      var context = canvas.getContext('2d'); context.clearRect(0, 0, w, h);
      var peaks = record.waveform;
      if (peaks && !Array.isArray(peaks)) peaks = peaks.peaks || peaks.values;
      if (!Array.isArray(peaks) || !peaks.length) {
        context.fillStyle = '#a6a9b0'; context.font = 12 * dpr + 'px system-ui';
        context.textAlign = 'center'; context.fillText('Waveform unavailable', w / 2, h / 2 + 4 * dpr);
        return;
      }
      context.strokeStyle = '#6fd4b3'; context.lineWidth = Math.max(1, dpr);
      var columns = Math.min(w, 900), step = w / columns, middle = h / 2;
      for (var x = 0; x < columns; x += 1) {
        var from = Math.floor((start + (end - start) * x / columns) / record.duration * peaks.length);
        var until = Math.max(from + 1, Math.floor((start + (end - start) * (x + 1) / columns) / record.duration * peaks.length));
        var peak = 0;
        for (var k = from; k < until && k < peaks.length; k += 1) {
          var sample = peaks[k], value = Array.isArray(sample) ? Math.max.apply(null, sample.map(Math.abs)) : Math.abs(Number(sample) || 0);
          peak = Math.max(peak, value);
        }
        var half = Math.max(dpr, Math.min(1, peak) * (middle - dpr));
        context.beginPath(); context.moveTo(x * step, middle - half); context.lineTo(x * step, middle + half); context.stroke();
      }
    }
    function drawWaves() {
      waveRaf = 0;
      if ($('splitEditor').hidden) return;
      drawWave($('splitSourceWave'), 0, record.duration);
      Array.from(timeline.children).forEach(function (item, index) {
        var clip = pieces[index];
        if (clip) drawWave(item.querySelector('canvas'), clip.in_s, clip.out_s);
      });
    }
    function scheduleWaves() { if (!waveRaf) waveRaf = requestAnimationFrame(drawWaves); }
    function paintTrim() {
      var clip = pieces[selected], duration = record.duration;
      var left = clip ? clip.in_s / duration * 100 : 0, right = clip ? clip.out_s / duration * 100 : 0;
      $('splitInHandle').style.left = left + '%'; $('splitOutHandle').style.left = right + '%';
      $('splitTrimBand').style.left = left + '%'; $('splitTrimBand').style.width = right - left + '%';
      [['splitInHandle', clip && clip.in_s], ['splitOutHandle', clip && clip.out_s]].forEach(function (row) {
        $(row[0]).disabled = !clip || exporting;
        $(row[0]).setAttribute('aria-valuemax', String(duration));
        $(row[0]).setAttribute('aria-valuenow', String(row[1] || 0));
        $(row[0]).setAttribute('aria-valuetext', M.clock(row[1] || 0));
      });
    }
    function render() {
      timeline.replaceChildren();
      var length = total();
      pieces.forEach(function (clip, index) {
        var button = document.createElement('button'); button.type = 'button';
        button.className = 'split-piece' + (index === selected ? ' selected' : '');
        button.style.flex = Math.max(1, (clip.out_s - clip.in_s) / Math.max(length, .01) * 20) + ' 0 100px';
        button.setAttribute('aria-pressed', index === selected ? 'true' : 'false');
        button.setAttribute('aria-label', 'Piece ' + (index + 1) + ': ' + clip.name + ', ' + M.clock(clip.in_s) + ' to ' + M.clock(clip.out_s));
        var wave = document.createElement('canvas'), name = document.createElement('strong'), time = document.createElement('small');
        wave.setAttribute('aria-hidden', 'true'); name.textContent = (index + 1) + '. ' + clip.name;
        time.textContent = M.clock(clip.out_s - clip.in_s);
        button.append(wave, name, time);
        button.addEventListener('click', function (event) {
          if (exporting) return;
          var rect = button.getBoundingClientRect();
          var share = event.detail ? M.clamp((event.clientX - rect.left) / rect.width, 0, 1) : 0;
          stop(); selected = index; render(); seekGlobal(startOf(index) + share * (clip.out_s - clip.in_s));
          timeline.children[index].focus();
        });
        button.addEventListener('keydown', function (event) {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault(); stop(); selected = M.clamp(index + (event.key === 'ArrowLeft' ? -1 : 1), 0, pieces.length - 1);
          render(); seekGlobal(startOf(selected)); timeline.children[selected].focus();
        });
        timeline.appendChild(button);
      });
      $('splitCount').textContent = pieces.length + (pieces.length === 1 ? ' piece' : ' pieces');
      var clip = pieces[selected], ready = !!clip && !exporting;
      $('splitName').value = clip ? clip.name : '';
      $('splitIn').value = clip ? clip.in_s.toFixed(2) : '';
      $('splitOut').value = clip ? clip.out_s.toFixed(2) : '';
      $('splitIn').max = $('splitOut').max = record.duration;
      ['splitName', 'splitIn', 'splitOut', 'splitSetIn', 'splitSetOut'].forEach(function (id) { $(id).disabled = !ready; });
      $('splitDelete').disabled = !ready || pieces.length <= 1;
      $('splitAtPlayhead').disabled = !pieces.length || pieces.length >= 20 || exporting;
      $('splitMoveLeft').disabled = !ready || selected === 0;
      $('splitMoveRight').disabled = !ready || selected === pieces.length - 1;
      $('splitUndo').disabled = !past.length || exporting;
      $('splitRedo').disabled = !future.length || exporting;
      $('splitPlay').disabled = !pieces.length || exporting;
      scrub.disabled = !pieces.length || exporting;
      $('splitExport').disabled = pieces.length < 2 || pieces.length > 20 || exporting
        || pieces.some(function (piece) { return piece.out_s - piece.in_s < .2 - 1e-6; });
      document.querySelectorAll('input[name="splitOriginal"]').forEach(function (radio) { radio.disabled = exporting; });
      ['splitSequenceMode', 'splitPieceMode'].forEach(function (id) {
        var on = (id === 'splitPieceMode') === (mode === 'piece');
        $(id).classList.toggle('selected', on); $(id).setAttribute('aria-pressed', on ? 'true' : 'false');
        $(id).disabled = exporting || id === 'splitPieceMode' && !clip;
      });
      paintTrim(); paintPosition(); scheduleWaves();
    }
    function snapshot() { return {pieces: M.copy(pieces), selected: selected, at: at}; }
    function remember() { past.push(snapshot()); if (past.length > 80) past.shift(); future.length = 0; }
    function restore(state) { stop(); pieces = state.pieces; selected = state.selected; render(); seekGlobal(state.at); }
    function change(next, nextSelected) {
      if (exporting || JSON.stringify(next) === JSON.stringify(pieces)) return false;
      remember(); stop(); pieces = next; selected = nextSelected;
      if (!pieces.length) mode = 'sequence';
      render(); seekGlobal(pieces[selected] ? startOf(selected) : 0);
      return true;
    }
    function trimPiece(edge, value, live) {
      if (selected < 0 || exporting) return;
      var next = M.audioSplitTrim(pieces, selected, edge, value, record);
      if (JSON.stringify(next) === JSON.stringify(pieces)) { if (!live) render(); return; }
      if (!live) remember();
      stop(); pieces = next;
      if (live) { at = startOf(selected); render(); }
      else { render(); seekGlobal(startOf(selected)); }
    }
    function sourceAt(event) {
      var rect = $('splitTrim').getBoundingClientRect();
      return M.clamp((event.clientX - rect.left) / rect.width, 0, 1) * record.duration;
    }
    ['in', 'out'].forEach(function (edge) {
      var handle = $(edge === 'in' ? 'splitInHandle' : 'splitOutHandle');
      handle.addEventListener('pointerdown', function (event) {
        if (exporting || selected < 0) return;
        event.preventDefault(); event.stopPropagation(); remember(); stop();
        trimGesture = {id: event.pointerId, edge: edge}; handle.setPointerCapture(event.pointerId);
      });
      handle.addEventListener('pointermove', function (event) {
        if (trimGesture && trimGesture.id === event.pointerId && trimGesture.edge === edge) trimPiece(edge, sourceAt(event), true);
      });
      ['pointerup', 'pointercancel'].forEach(function (type) {
        handle.addEventListener(type, function (event) {
          if (!trimGesture || trimGesture.id !== event.pointerId) return;
          trimPiece(edge, sourceAt(event), true); trimGesture = null;
          seekGlobal(startOf(selected));
        });
      });
      handle.addEventListener('keydown', function (event) {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || selected < 0 || exporting) return;
        event.preventDefault();
        var current = pieces[selected][edge === 'in' ? 'in_s' : 'out_s'];
        trimPiece(edge, event.key === 'Home' ? 0 : event.key === 'End' ? record.duration
          : current + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 1 : .1), false);
      });
    });
    $('splitTrim').addEventListener('pointerdown', function (event) {
      if (event.target !== $('splitTrim') && event.target !== $('splitSourceWave') || !pieces[selected]) return;
      stop();
      var clip = pieces[selected], time = M.clamp(sourceAt(event), clip.in_s, clip.out_s);
      seekGlobal(startOf(selected) + time - clip.in_s);
    });
    $('splitIn').addEventListener('change', function () { if (this.value.trim()) trimPiece('in', Number(this.value), false); else render(); });
    $('splitOut').addEventListener('change', function () { if (this.value.trim()) trimPiece('out', Number(this.value), false); else render(); });
    $('splitName').addEventListener('change', function () {
      if (!pieces[selected] || exporting) return;
      var name = this.value.trim();
      if (!name) { tell('Name every piece before exporting.', true); render(); return; }
      var next = M.copy(pieces); next[selected].name = name; change(next, selected);
    });
    ['In', 'Out'].forEach(function (edge) {
      $('splitSet' + edge).addEventListener('click', function () {
        var place = M.spliceLocate(pieces, at);
        if (!place || place.index !== selected) { tell('Place the playhead inside the selected piece.', true); return; }
        trimPiece(edge.toLowerCase(), place.source_s, false);
      });
    });
    $('splitAtPlayhead').addEventListener('click', function () {
      var place = M.spliceLocate(pieces, at);
      if (!place) return;
      if (!change(M.audioSplitAt(pieces, place.index, place.source_s), place.index + 1))
        tell('Move the playhead at least 0.2 seconds from an edge to split.', true);
    });
    $('splitMoveLeft').addEventListener('click', function () { change(M.spliceMove(pieces, selected, selected - 1), selected - 1); });
    $('splitMoveRight').addEventListener('click', function () { change(M.spliceMove(pieces, selected, selected + 1), selected + 1); });
    $('splitDelete').addEventListener('click', function () {
      if (selected < 0) return;
      var next = M.copy(pieces); next.splice(selected, 1);
      change(next, Math.min(selected, next.length - 1));
    });
    $('splitUndo').addEventListener('click', function () {
      if (!past.length || exporting) return;
      future.push(snapshot()); restore(past.pop());
    });
    $('splitRedo').addEventListener('click', function () {
      if (!future.length || exporting) return;
      past.push(snapshot()); restore(future.pop());
    });
    function playSplit() {
      if (!pieces.length || exporting) return;
      if (playing) { stop(); return; }
      var range = bounds(); if (at >= range.end - .02) seekGlobal(range.start);
      playing = true; $('splitPlay').textContent = 'Pause'; $('splitPlay').setAttribute('aria-label', 'Pause preview');
      if (pending === null && media.readyState >= 1) media.play().catch(playFailed);
      else applyPending();
    }
    $('splitPlay').addEventListener('click', playSplit);
    scrub.addEventListener('input', function () { stop(); seekGlobal(Number(this.value)); });
    [['splitSequenceMode', 'sequence'], ['splitPieceMode', 'piece']].forEach(function (row) {
      $(row[0]).addEventListener('click', function () {
        if (exporting || row[1] === 'piece' && selected < 0) return;
        stop(); mode = row[1]; render(); seekGlobal(row[1] === 'piece' ? startOf(selected) : at);
      });
    });
    document.querySelectorAll('input[name="splitOriginal"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (this.checked) tell(this.value === 'keep' ? 'Your original clip will remain in the SFX library.' : 'The original clip will be retired from the SFX library on export.');
      });
    });
    $('splitSingle').addEventListener('click', function () {
      stop(); sfxSingleMode = true; $('splitEditor').hidden = true; $('recordingEditor').hidden = false;
    });
    $('splitBack').addEventListener('click', function () {
      stop();
      if (window.parent !== window) window.parent.postMessage({type: 'pine-video-editor-close'}, '*');
      else if (history.length > 1) history.back(); else window.close();
    });
    document.addEventListener('keydown', function (event) {
      if ($('splitEditor').hidden || /INPUT|TEXTAREA/.test(event.target.tagName) || event.target.isContentEditable || event.altKey) return;
      if (event.key === ' ' && event.target.tagName !== 'BUTTON' && !event.ctrlKey && !event.metaKey) { event.preventDefault(); playSplit(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); $(event.shiftKey ? 'splitRedo' : 'splitUndo').click();
      }
      if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); $('splitDelete').click(); }
    });

    function results(result) {
      var rows = result.outputs || result.files || result.results || result.paths || result.items || result.clips || [];
      if (!Array.isArray(rows)) rows = [rows];
      if (!rows.length && (result.path || result.url || result.name)) rows = [result];
      var list = $('splitOutputList'); list.replaceChildren();
      rows.forEach(function (row, index) {
        var item = document.createElement('li'), path = typeof row === 'string' ? row : row.path || row.name || row.url || '';
        var url = typeof row === 'string' ? '' : row.url || '';
        if (url && (/^\//.test(url) || /^https?:\/\//.test(url))) {
          var link = document.createElement('a'); link.href = url; link.textContent = path || 'Piece ' + (index + 1);
          item.appendChild(link);
        } else item.textContent = path || 'Piece ' + (index + 1);
        list.appendChild(item);
      });
      if (!rows.length) { var item = document.createElement('li'); item.textContent = 'Export complete'; list.appendChild(item); }
      $('splitResults').hidden = false;
    }
    async function exportPieces() {
      if (exporting || !pieces.length) return;
      exporting = true; stop(); render(); $('splitExport').textContent = 'Exporting...'; $('splitResults').hidden = true;
      try {
        var keep = document.querySelector('input[name="splitOriginal"]:checked').value === 'keep';
        try {
          permitTake(await api('GET', '/api/video-editor/sources/' + encodeURIComponent(record.id) + '?mint=' + Date.now()));
        } catch (_) { /* the current permit may still be valid */ }
        var body = M.audioSplitBody(record, pieces, keep, savePermit);
        tell('Starting split export...');
        var job;
        try { job = await api('POST', '/api/sfx/edit/split', body); }
        catch (error) {
          if (error.status !== 401 && error.status !== 403) throw error;
          if (savePermit === body.save_token) await permitRenew();
          if (!savePermit || savePermit === body.save_token) throw error;
          body.save_token = savePermit;
          job = await api('POST', '/api/sfx/edit/split', body);
        }
        var id = job.id || job.job_id;
        if (!id) throw new Error('The station did not return an export ID.');
        while (!['complete', 'done', 'failed', 'error'].includes(job.status)) {
          if (disposed) return;
          await exportHold(1000);
          job = await api('GET', '/api/sfx/edit/split/' + encodeURIComponent(id));
          var progress = Number(job.progress);
          tell(Number.isFinite(progress) ? 'Exporting pieces... ' + Math.round(progress <= 1 ? progress * 100 : progress) + '%' : 'Exporting pieces...');
        }
        if (job.status === 'failed' || job.status === 'error') throw new Error(job.error || 'The split export failed.');
        results(job);
        tell(keep ? 'Pieces exported. Your original clip remains in the SFX library.' : 'Pieces exported. The original clip was retired from the SFX library.');
        window.dispatchEvent(new CustomEvent('pine-sfx-edit-split', {detail: job}));
        if (window.parent !== window) window.parent.postMessage({type: 'pine-sfx-edit-split', detail: job}, '*');
      } catch (error) { tell(error.message || 'The split export failed.', true); }
      finally { exporting = false; $('splitExport').textContent = 'Export pieces'; render(); }
    }
    $('splitExport').addEventListener('click', exportPieces);
    if (typeof ResizeObserver !== 'undefined') {
      var observer = new ResizeObserver(scheduleWaves); observer.observe(timeline); observer.observe($('splitTrim'));
    } else window.addEventListener('resize', scheduleWaves);
    window.addEventListener('pagehide', function () { stop(); if (waveRaf) cancelAnimationFrame(waveRaf); });

    function open() {
      sfxSingleMode = false;
      video.pause(); $('recordingEditor').hidden = true; $('splitEditor').hidden = false;
      $('splitSourceName').textContent = record.pine_sfx.name || record.name || 'Audio clip';
      if (media.getAttribute('src') !== record.url) {
        mediaCover.reset();
        $('splitLoading').hidden = false; media.src = record.url; media.load();
      }
      render(); seekGlobal(at);
    }
    return {open: open};
  }

  function startParodyEditor() {
    var model = window.PineVideoEditModel;
    var el = function (id) { return document.getElementById(id); };
    var requiredIds = ['parodyAudioFadeIn','parodyAudioFadeOut','parodyBack','parodyBinCount','parodyBinToggle','parodyBlendStatus','parodyCover','parodyDelete','parodyDownload','parodyEditor','parodyIn','parodyInspector','parodyInspectorToggle','parodyLibraryStatus','parodyLoading','parodyMaskCanvas','parodyMaskClear','parodyMaskClose','parodyMaskEdit','parodyMaskFeather','parodyMaskFeatherValue','parodyMaskInvert','parodyMaskKeyframe','parodyMaskKeyframeAdd','parodyMaskKeyframeDelete','parodyMaskPen','parodyMediaBin','parodyMoveLeft','parodyMoveRight','parodyName','parodyOpacity','parodyOpacityValue','parodyOut','parodyOverlayLock','parodyOverlayMute','parodyOverlayTimeline','parodyOverlayToggle','parodyOverlayTrack','parodyOverlayVideo','parodyPlay','parodyPosition','parodyPreloadVideo','parodyPreview','parodyProjectSummary','parodyRedo','parodyRetrySources','parodySave','parodyScrub','parodySearch','parodySearchForm','parodySelectedLabel','parodySequenceCount','parodySetIn','parodySetOut','parodySourcePreview','parodySourcePreviewName','parodySplit','parodyStart','parodyStatus','parodyTimeline','parodyTrack','parodyTrackLock','parodyTrackMute','parodyTransition','parodyTransitionDuration','parodyTrimFrame','parodyUndo','parodyVideo','parodyVolume','parodyVolumeValue','parodyWorkspace','recordingEditor'];
    var missingIds = requiredIds.filter(function (id) { return !el(id); });
    if (missingIds.length) throw new Error('Editor markup mismatch; missing: #' + missingIds.join(', #'));
    if (!model) throw new Error('The video edit model did not load.');
    var params = new URLSearchParams(location.search);
    var baseIds = [params.get('source') || '', params.get('secondary') || ''].filter(function (id, index, all) {
      return id && all.indexOf(id) === index;
    });
    var sourceIds = baseIds.slice(), sources = {}, sourceRoles = {}, sourceClipIds = {};
    var libraryRows = [], importJobs = {}, clips = [], selected = -1, at = 0, activeId = '', activeIndex = -1, pending = null;
    var historyPast = [], historyFuture = [], playing = false, exporting = false, gone = false, pollTimer = 0, searchTimer = 0;
    var seeded = false, loadGeneration = 0, searchGeneration = 0, trackLocked = false, trackMuted = false;
    var overlayLocked = false, overlayMuted = false, overlayCollapsed = true, maskEditing = false, maskPen = false, maskFrameIndex = 0;
    var draggingIndex = -1, suppressClickUntil = 0, trimActive = false, previewLayerFrame = 0, previewLayerAt = 0;
    var preview = el('parodyVideo'), scrub = el('parodyScrub');
    var sourcePreview = el('parodySourcePreview'), timeline = el('parodyTimeline'), overlayTimeline = el('parodyOverlayTimeline');
    var overlayPreview = el('parodyOverlayVideo'), preloadPreview = el('parodyPreloadVideo'), maskCanvas = el('parodyMaskCanvas');
    var programPlayers = [preview, preloadPreview], previewCover = el('parodyCover');
    var trimFrameLabel = el('parodyTrimFrame');
    var maskContext = maskCanvas.getContext('2d');
    var parent = window;
    try { if (window.parent !== window && window.parent.location.origin === location.origin) parent = window.parent; } catch (_) { /* standalone */ }
    var desktop = parent.pineDesktop || window.pineDesktop || {};
    el('recordingEditor').hidden = true;
    el('parodyEditor').hidden = false;
    setProgramRoles(preview, preloadPreview);

    function message(value, bad) {
      el('parodyStatus').textContent = value;
      el('parodyStatus').classList.toggle('error', !!bad);
    }
    async function request(method, path, body) {
      return model.editorRequest({desktop: desktop,
        parentApi: parent !== window && typeof parent.api === 'function' ? parent.api.bind(parent) : null,
        sameOriginApi: typeof window.api === 'function' ? window.api.bind(window) : null,
        fetch: typeof window.fetch === 'function' ? window.fetch.bind(window) : null,
        key: window.__PINE_VIDEO_EDITOR_KEY || ''}, method, path, body);
    }
    function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
    function showLoading(text, retry) {
      var loading = el('parodyLoading');
      loading.hidden = false; loading.querySelector('span').textContent = text;
      el('parodyRetrySources').hidden = !retry;
    }
    function sourceName(id) {
      var record = sources[id] || {};
      return String(record.name || sourceRoles[id] || 'Station clip');
    }
    function sourcePoster(record) {
      var first = record && Array.isArray(record.thumbnails) && record.thumbnails[0];
      return record && (record.poster_url || record.poster || record.thumbnail_url)
        || (typeof first === 'string' ? first : first && first.url) || '/spark/asset/pinebox.png';
    }
    function registerSource(record, id, role) {
      id = String(id || record && (record.source_id || record.id) || '');
      if (!id) throw new Error('The station returned a source without an identity.');
      record = Object.assign({}, sources[id] || {}, record || {}, {id: id, source_id: id});
      if (record.duration !== undefined) record.duration = Number(record.duration);
      sources[id] = record;
      sourceRoles[id] = role || sourceRoles[id] || 'Library';
      if (record.clip_id) sourceClipIds[String(record.clip_id)] = id;
      if (sourceIds.indexOf(id) < 0) sourceIds.push(id);
      return record;
    }
    function length() { return model.spliceLength(clips); }
    function startOf(index) { return model.spliceStartOf(clips, index); }
    function setProgramRoles(active, buffer) {
      active.classList.add('parody-program-active'); active.classList.remove('parody-program-buffer');
      active.removeAttribute('aria-hidden'); active.controls = false;
      buffer.classList.remove('parody-program-active'); buffer.classList.add('parody-program-buffer');
      buffer.setAttribute('aria-hidden', 'true'); buffer.controls = false; buffer.muted = true;
    }
    function resetPreviewCover() {
      var image = previewCover.querySelector('img');
      image.onerror = null; image.classList.remove('ve-real-poster');
      image.src = '/spark/asset/pinebox.png'; preview.poster = '/spark/asset/pinebox.png';
      previewCover.hidden = false;
      preview.classList.remove('ve-frame-ready');
    }
    function revealPreviewFrame(media) {
      if (media !== preview || media.readyState < 2 || !(media.videoWidth > 0 && media.videoHeight > 0)) return;
      media.classList.add('ve-frame-ready'); previewCover.hidden = true;
    }
    function setTransportPlaying(isPlaying) {
      var button = el('parodyPlay');
      button.classList.toggle('is-playing', !!isPlaying);
      button.textContent = isPlaying ? 'Pause sequence' : 'Play sequence';
      button.setAttribute('aria-label', isPlaying ? 'Pause sequence' : 'Play sequence');
      button.title = isPlaying ? 'Pause sequence' : 'Play sequence';
    }
    function stop() {
      playing = false; programPlayers.forEach(function (media) { media.pause(); }); overlayPreview.pause();
      setTransportPlaying(false);
    }
    function setTrimMode(on) {
      trimActive = !!on;
      el('parodyPreview').classList.toggle('is-trimming', trimActive);
      trimFrameLabel.hidden = !trimActive;
      if (trimActive) {
        /* Scrubbing must have the decoder to itself. A bin audition, a live
           overlay and mask painting are all optional while the operator is
           choosing one exact source frame. */
        try { sourcePreview.pause(); overlayPreview.pause(); } catch (_) { /* detached media */ }
        maskCanvas.style.visibility = 'hidden';
      } else {
        maskCanvas.style.visibility = '';
      }
    }
    function displayPosition() {
      var total = length();
      el('parodyPosition').textContent = model.clock(at) + ' / ' + model.clock(total);
      scrub.max = String(Math.max(total, .01));
      scrub.value = String(Math.min(at, total));
    }
    function audioEnvelope(clip, local) {
      var duration = clip.out_s - clip.in_s, gain = Number(clip.volume === undefined ? 1 : clip.volume);
      if (clip.audio_fade_in_s > 0) gain *= model.clamp(local / clip.audio_fade_in_s, 0, 1);
      if (clip.audio_fade_out_s > 0) gain *= model.clamp((duration - local) / clip.audio_fade_out_s, 0, 1);
      return model.clamp(gain, 0, 1);
    }
    function transitionOpacity(clip, local) {
      var seconds = Number(clip.transition_s || 0);
      if (!seconds || clip.transition === 'cut') return Number(clip.opacity === undefined ? 1 : clip.opacity);
      return Number(clip.opacity === undefined ? 1 : clip.opacity) * model.clamp(local / seconds, 0, 1);
    }
    function maskFrame(clip) {
      var keyframes = clip && clip.mask && clip.mask.keyframes || [];
      if (!keyframes.length) return null;
      maskFrameIndex = model.clamp(maskFrameIndex, 0, keyframes.length - 1);
      return keyframes[maskFrameIndex];
    }
    function drawMask() {
      var rect = maskCanvas.getBoundingClientRect(), width = Math.max(1, Math.round(rect.width)), height = Math.max(1, Math.round(rect.height));
      if (maskCanvas.width !== width || maskCanvas.height !== height) { maskCanvas.width = width; maskCanvas.height = height; }
      maskContext.clearRect(0, 0, width, height);
      var clip = clips[selected], frame = clip && clip.track === 'overlay' && maskFrame(clip);
      if (!maskEditing || !frame || !frame.points.length) return;
      var points = frame.points;
      maskContext.lineWidth = 2; maskContext.strokeStyle = '#ffd60a'; maskContext.fillStyle = '#ffd60a25';
      maskContext.beginPath(); maskContext.moveTo(points[0].x * width, points[0].y * height);
      for (var i = 1; i < points.length; i += 1) {
        var previous = points[i - 1], point = points[i];
        maskContext.bezierCurveTo(previous.out_x * width, previous.out_y * height, point.in_x * width, point.in_y * height, point.x * width, point.y * height);
      }
      if (clip.mask.closed && points.length > 2) {
        var last = points[points.length - 1], first = points[0];
        maskContext.bezierCurveTo(last.out_x * width, last.out_y * height, first.in_x * width, first.in_y * height, first.x * width, first.y * height); maskContext.closePath(); maskContext.fill();
      }
      maskContext.stroke();
      points.forEach(function (point) {
        maskContext.strokeStyle = '#74d9ff'; maskContext.lineWidth = 1;
        maskContext.beginPath(); maskContext.moveTo(point.in_x * width, point.in_y * height); maskContext.lineTo(point.x * width, point.y * height); maskContext.lineTo(point.out_x * width, point.out_y * height); maskContext.stroke();
        [[point.in_x, point.in_y, '#74d9ff'], [point.out_x, point.out_y, '#74d9ff'], [point.x, point.y, '#ffd60a']].forEach(function (handle) {
          maskContext.beginPath(); maskContext.fillStyle = handle[2]; maskContext.arc(handle[0] * width, handle[1] * height, handle[2] === '#ffd60a' ? 6 : 4, 0, Math.PI * 2); maskContext.fill();
        });
      });
    }
    function applyMaskPreview(media, clip, local) {
      var pointsAtTime = clip && clip.mask ? model.spliceMaskAt(clip.mask, local) : [];
      if (!pointsAtTime.length || !clip.mask.closed) { media.style.clipPath = ''; media.style.filter = ''; return; }
      var points = pointsAtTime.map(function (point) { return (point.x * 100).toFixed(2) + '% ' + (point.y * 100).toFixed(2) + '%'; }).join(',');
      media.style.clipPath = (clip.mask.invert ? '' : 'polygon(' + points + ')');
      media.style.filter = clip.mask.feather ? 'blur(' + Math.min(24, clip.mask.feather / 4) + 'px)' : '';
    }
    function nextBaseIndex(index) {
      for (var i = index + 1; i < clips.length; i += 1) if (clips[i].track !== 'overlay') return i;
      return -1;
    }
    function preloadAdjacent(index) {
      var next = null;
      for (var i = index + 1; i < clips.length; i += 1) if (clips[i].track !== 'overlay') { next = clips[i]; break; }
      var record = next && sources[next.source_id];
      var key = next ? next.source_id + ':' + Number(next.in_s).toFixed(3) : '';
      if (!record || !record.url) return;
      /* Loading the same source again on every playhead frame cancels the
         browser's buffer and causes the exact boundary hitch this player is
         meant to avoid. A keyed prebuffer stays resident until it is used. */
      if (preloadPreview.dataset.preloadKey === key) return;
      preloadPreview.pause(); preloadPreview.dataset.sourceId = next.source_id;
      preloadPreview.dataset.preloadKey = key; preloadPreview.dataset.ready = 'false';
      preloadPreview.src = record.url; preloadPreview.load();
      function sameTarget() { return preloadPreview.dataset.preloadKey === key; }
      function prime() {
        if (!sameTarget()) return;
        try { preloadPreview.currentTime = next.in_s; } catch (_) { /* Metadata is still arriving. */ }
      }
      function warmed() {
        if (!sameTarget() || preloadPreview.readyState < 3) return;
        if (Math.abs(preloadPreview.currentTime - next.in_s) < .18) preloadPreview.dataset.ready = 'true';
      }
      preloadPreview.addEventListener('loadedmetadata', prime, {once: true});
      preloadPreview.addEventListener('seeked', warmed, {once: true});
      preloadPreview.addEventListener('canplay', warmed, {once: true});
    }
    function queuePreviewLayers(position) {
      previewLayerAt = position;
      if (previewLayerFrame) return;
      previewLayerFrame = requestAnimationFrame(function () {
        previewLayerFrame = 0;
        updatePreviewLayers(previewLayerAt);
      });
    }
    function updatePreviewLayers(position) {
      var base = clips[activeIndex], baseLocal = base ? position - startOf(activeIndex) : 0;
      if (base && base.track !== 'overlay') {
        preview.volume = audioEnvelope(base, baseLocal); preview.style.opacity = String(transitionOpacity(base, baseLocal));
        preview.style.clipPath = base.transition === 'wipe' && base.transition_s > 0 ? 'inset(0 ' + ((1 - model.clamp(baseLocal / base.transition_s, 0, 1)) * 100) + '% 0 0)' : '';
        el('parodyBlendStatus').textContent = base.transition === 'cut' ? '' : base.transition + ' ' + Number(base.transition_s || 0).toFixed(2) + 's';
        if (!trimActive) preloadAdjacent(activeIndex);
      }
      if (trimActive) {
        overlayPreview.pause(); overlayPreview.style.opacity = '0';
        return;
      }
      var overlays = model.spliceActiveOverlays(clips, position), layer = overlays.length ? overlays[overlays.length - 1] : null;
      if (!layer || layer.index === activeIndex) {
        overlayPreview.pause(); overlayPreview.style.opacity = '0'; overlayPreview.removeAttribute('data-active-index');
      } else {
        var overlayRecord = sources[layer.clip.source_id], local = position - layer.start_s;
        if (overlayRecord && overlayRecord.url) {
          if (overlayPreview.dataset.sourceId !== layer.clip.source_id) {
            overlayPreview.dataset.sourceId = layer.clip.source_id; overlayPreview.src = overlayRecord.url; overlayPreview.load();
          }
          if (overlayPreview.readyState >= 1 && Math.abs(overlayPreview.currentTime - layer.source_s) > .12) {
            try { overlayPreview.currentTime = layer.source_s; } catch (_) { /* metadata is arriving */ }
          }
          overlayPreview.dataset.activeIndex = String(layer.index); overlayPreview.muted = overlayMuted;
          overlayPreview.volume = audioEnvelope(layer.clip, local); overlayPreview.style.opacity = String(transitionOpacity(layer.clip, local));
          overlayPreview.style.clipPath = layer.clip.transition === 'wipe' && layer.clip.transition_s > 0 ? 'inset(0 ' + ((1 - model.clamp(local / layer.clip.transition_s, 0, 1)) * 100) + '% 0 0)' : '';
          applyMaskPreview(overlayPreview, layer.clip, local);
          if (playing && overlayPreview.paused) {
            overlayPreview.play().catch(function () { /* It resumes on the next time update. */ });
          }
        }
      }
      if (maskEditing) drawMask();
    }
    function preloadedFor(index) {
      var clip = clips[index], key = clip && clip.source_id + ':' + Number(clip.in_s).toFixed(3);
      return !!clip && preloadPreview.dataset.preloadKey === key && preloadPreview.dataset.ready === 'true'
        && preloadPreview.readyState >= 3 && Math.abs(preloadPreview.currentTime - clip.in_s) < .18;
    }
    function promotePreloaded(index, position) {
      if (!preloadedFor(index)) return false;
      var next = clips[index], record = sources[next.source_id], previous = preview, ready = preloadPreview;
      preview = ready; preloadPreview = previous; activeId = next.source_id; activeIndex = index;
      pending = null; at = position;
      setProgramRoles(preview, preloadPreview);
      preview.muted = trackMuted; preview.volume = audioEnvelope(next, 0);
      preview.classList.add('ve-frame-ready'); previewCover.hidden = true;
      var playback = preview.play(); previous.pause();
      if (playback && typeof playback.catch === 'function') playback.catch(playFailed);
      displayPosition(); updatePreviewLayers(at);
      return true;
    }
    function seekSequence(position) {
      at = model.clamp(position, 0, length());
      var place = model.spliceLocate(clips, at);
      if (!place) { stop(); preview.removeAttribute('src'); activeId = ''; activeIndex = -1; return; }
      var record = sources[place.source_id];
      if (!record) return;
      activeIndex = place.index;
      displayPosition(); updatePreviewLayers(at);
      pending = place.source_s;
      if (activeId !== place.source_id) {
        preview.pause(); activeId = place.source_id;
        resetPreviewCover();
        preview.muted = trackMuted; preview.volume = 1; preview.src = record.url;
        preview.load();
      } else applySeek();
    }
    function applySeek() {
      if (pending === null || preview.readyState < 1) return;
      try {
        if (Math.abs(preview.currentTime - pending) > .025) preview.currentTime = pending;
        else { pending = null; if (playing) preview.play().catch(playFailed); }
      } catch (_) { /* metadata is arriving */ }
    }
    function playFailed() { stop(); message('Tap Play again to start the preview.', true); }
    function updateFromVideo() {
      if (pending !== null || !clips.length || preview.seeking) return;
      var clip = clips[activeIndex];
      if (!clip || clip.source_id !== activeId) return;
      var offset = startOf(activeIndex);
      if (preview.currentTime >= clip.out_s - .02) {
        var nextBase = nextBaseIndex(activeIndex);
        if (nextBase >= 0) {
          var nextPosition = startOf(nextBase);
          if (clips[nextBase].source_id === activeId || !promotePreloaded(nextBase, nextPosition)) seekSequence(nextPosition);
        }
        else { at = length(); stop(); displayPosition(); updatePreviewLayers(at); }
        return;
      }
      at = offset + model.clamp(preview.currentTime - clip.in_s, 0, clip.out_s - clip.in_s);
      displayPosition(); queuePreviewLayers(at);
    }
    programPlayers.forEach(function (player) {
      player.addEventListener('loadedmetadata', function () { if (player === preview) applySeek(); });
      player.addEventListener('loadeddata', function () { if (player === preview) { revealPreviewFrame(player); applySeek(); } });
      player.addEventListener('seeked', function () {
        if (player !== preview) return;
        /* A handle drag can issue a newer seek before the decoder reports the
           earlier one. Do not let the stale completion steal the live frame. */
        if (pending !== null && Math.abs(preview.currentTime - pending) > .035) { applySeek(); return; }
        pending = null; if (playing) preview.play().catch(playFailed); updateFromVideo();
      });
      player.addEventListener('timeupdate', function () { if (player === preview) updateFromVideo(); });
      player.addEventListener('ended', function () { if (player === preview) updateFromVideo(); });
      player.addEventListener('play', function () {
        if (player !== preview) return;
        playing = true; setTransportPlaying(true);
      });
      player.addEventListener('error', function () {
        if (player === preview) { stop(); message('The sequence preview could not load this source.', true); }
      });
    });
    overlayPreview.addEventListener('loadedmetadata', function () { updatePreviewLayers(at); if (playing) overlayPreview.play().catch(function () {}); });
    function playSequence() {
      if (!clips.length || exporting) return;
      if (playing) { stop(); return; }
      try { sourcePreview.pause(); } catch (_) { /* source monitor is optional */ }
      if (at >= length() - .02) seekSequence(0);
      playing = true;
      setTransportPlaying(true);
      preloadAdjacent(activeIndex);
      if (pending === null && preview.readyState >= 2) preview.play().catch(playFailed);
      else applySeek();
    }
    function beginTouchReorder(event, node, index) {
      var lane = node.parentNode, locked = clips[index] && clips[index].track === 'overlay' ? overlayLocked : trackLocked;
      if (locked || event.pointerType === 'mouse' || event.target.closest('.clip-edge')) return;
      var startX = event.clientX, startY = event.clientY, target = index, moved = false;
      function move(pointer) {
        if (Math.hypot(pointer.clientX - startX, pointer.clientY - startY) > 9) moved = true;
        if (!moved) return;
        pointer.preventDefault();
        var under = document.elementFromPoint(pointer.clientX, pointer.clientY);
        var segment = under && under.closest && under.closest('.parody-segment');
        Array.prototype.forEach.call(lane.querySelectorAll('.parody-segment'), function (one) { one.classList.remove('drag-target'); });
        if (segment) { target = Number(segment.dataset.index); segment.classList.add('drag-target'); }
      }
      function end() {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end);
        if (moved) {
          suppressClickUntil = Date.now() + 350;
          editClips(model.spliceMove(clips, index, target), target);
        } else render();
      }
      window.addEventListener('pointermove', move, {passive: false}); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
    }
    function startEdgeTrim(event, index, edge, node) {
      event.preventDefault(); event.stopPropagation();
      if (exporting || !clips[index] || (clips[index].track === 'overlay' ? overlayLocked : trackLocked)) return;
      stop(); selected = index;
      var before = JSON.stringify(clips), original = model.copy(clips), clip = original[index];
      var segment = node.parentNode, timeLabel = segment.querySelector('small'), trimReadout = segment.querySelector('.clip-trim-readout');
      var trimPreviewFrame = 0, trimPreviewTarget = null;
      var startX = event.clientX, secondsPerPixel = (clip.out_s - clip.in_s) / Math.max(44, node.parentNode.getBoundingClientRect().width - 44);
      function showTrim(current) {
        trimReadout.textContent = 'In ' + model.clock(current.in_s) + '   Out ' + model.clock(current.out_s) + '   Length ' + model.clock(current.out_s - current.in_s);
        trimReadout.hidden = false;
      }
      function queueTrimFrame(current) {
        var local = edge === 'out' ? Math.max(current.in_s, current.out_s - .03) : current.in_s;
        trimPreviewTarget = {clip: current, local: local,
          boundary: startOf(index) + Math.max(0, local - current.in_s)};
        trimFrameLabel.textContent = (edge === 'out' ? 'OUT FRAME ' : 'IN FRAME ') + model.clock(local);
        if (trimPreviewFrame) return;
        trimPreviewFrame = requestAnimationFrame(function () {
          trimPreviewFrame = 0;
          var target = trimPreviewTarget;
          trimPreviewTarget = null;
          if (!target) return;
          if (activeId === target.clip.source_id && preview.readyState >= 1) {
            at = target.boundary;
            pending = target.local;
            applySeek();
            displayPosition(); queuePreviewLayers(at);
          } else {
            seekSequence(target.boundary);
          }
        });
      }
      remember(); stop(); setTrimMode(true); selected = index;
      segment.classList.add('selected', 'trimming'); node.classList.add('active'); showTrim(clip); queueTrimFrame(clip);
      try { if (navigator.vibrate) navigator.vibrate(8); } catch (_) {}
      try { node.setPointerCapture(event.pointerId); } catch (_) {}
      function move(pointer) {
        pointer.preventDefault();
        var value = (edge === 'in' ? clip.in_s : clip.out_s) + (pointer.clientX - startX) * secondsPerPixel;
        clips = model.spliceTrim(original, index, edge, value, sources); selected = index; at = startOf(index);
        var current = clips[index], duration = current.out_s - current.in_s, total = length();
        node.setAttribute('aria-valuenow', String(edge === 'in' ? current.in_s : current.out_s));
        timeLabel.textContent = model.clock(current.in_s) + ' - ' + model.clock(current.out_s) + '  (' + model.clock(duration) + ')';
        segment.setAttribute('aria-label', 'Segment ' + (index + 1) + ': ' + sourceName(current.source_id) + ', ' + model.clock(current.in_s) + ' to ' + model.clock(current.out_s));
        segment.style.setProperty('--clip-width', Math.min(460, Math.max(100, duration / Math.max(total, .01) * Math.max(660, timeline.clientWidth || 800))) + 'px');
        el('parodyIn').value = current.in_s.toFixed(2); el('parodyOut').value = current.out_s.toFixed(2);
        showTrim(current); displayPosition();
        /* Keep replacing the pending target while the finger moves. The next
           animation frame must seek to the newest handle position, not the
           first pointermove it happened to observe. */
        queueTrimFrame(current);
      }
      function end(pointer) {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end);
        if (trimPreviewFrame) cancelAnimationFrame(trimPreviewFrame);
        trimPreviewFrame = 0; trimPreviewTarget = null;
        try { if (node.hasPointerCapture(pointer.pointerId)) node.releasePointerCapture(pointer.pointerId); } catch (_) {}
        try { if (navigator.vibrate) navigator.vibrate(5); } catch (_) {}
        if (JSON.stringify(clips) === before) historyPast.pop();
        var current = clips[index], boundary = startOf(index) + (edge === 'out'
          ? Math.max(0, current.out_s - current.in_s - .03) : .001);
        setTrimMode(false); render(); seekSequence(boundary);
      }
      window.addEventListener('pointermove', move, {passive: false}); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
    }
    function render() {
      var total = length(), scroll = timeline.scrollLeft, overlayScroll = overlayTimeline.scrollLeft;
      timeline.replaceChildren(); overlayTimeline.replaceChildren();
      var baseCount = clips.filter(function (clip) { return clip.track !== 'overlay'; }).length;
      var overlayCount = clips.length - baseCount;
      function emptyLane(lane, text) { var empty = document.createElement('p'); empty.className = 'parody-empty'; empty.textContent = text; lane.appendChild(empty); }
      if (!baseCount) emptyLane(timeline, 'Drag or tap media to add it');
      if (!overlayCount) emptyLane(overlayTimeline, 'Drop media here for an overlay');
      clips.forEach(function (clip, index) {
        var segment = document.createElement('div'), duration = clip.out_s - clip.in_s, record = sources[clip.source_id] || {};
        var role = sourceRoles[clip.source_id] || 'Library';
        segment.className = 'parody-segment' + (role === 'Generated' ? ' generated' : role === 'Library' ? ' library' : '') + (index === selected ? ' selected' : '');
        var lane = clip.track === 'overlay' ? overlayTimeline : timeline;
        var laneLocked = clip.track === 'overlay' ? overlayLocked : trackLocked;
        segment.dataset.index = String(index); segment.tabIndex = 0; segment.draggable = !laneLocked && !exporting;
        segment.style.setProperty('--clip-width', Math.min(460, Math.max(100, duration / Math.max(total, .01) * Math.max(660, timeline.clientWidth || 800))) + 'px');
        if (clip.track === 'overlay') {
          segment.style.left = (startOf(index) / Math.max(total, .01) * 100) + '%';
          segment.style.width = Math.max(9, duration / Math.max(total, .01) * 100) + '%';
        }
        var poster = sourcePoster(record); if (poster) segment.style.backgroundImage = 'url(' + JSON.stringify(poster) + ')';
        segment.setAttribute('role', 'button');
        segment.setAttribute('aria-label', 'Segment ' + (index + 1) + ': ' + sourceName(clip.source_id) + ', ' + model.clock(clip.in_s) + ' to ' + model.clock(clip.out_s));
        segment.setAttribute('aria-pressed', index === selected ? 'true' : 'false');
        var title = document.createElement('strong'), time = document.createElement('small'), trimReadout = document.createElement('output'), inEdge = document.createElement('button'), outEdge = document.createElement('button');
        title.textContent = (index + 1) + '. ' + sourceName(clip.source_id);
        time.textContent = model.clock(clip.in_s) + ' - ' + model.clock(clip.out_s) + '  (' + model.clock(duration) + ')';
        trimReadout.className = 'clip-trim-readout'; trimReadout.hidden = true; trimReadout.setAttribute('aria-live', 'off');
        [inEdge, outEdge].forEach(function (handle, side) {
          var edge = side ? 'out' : 'in'; handle.type = 'button'; handle.className = 'clip-edge ' + edge; handle.disabled = laneLocked || exporting;
          handle.setAttribute('role', 'slider'); handle.setAttribute('aria-label', (edge === 'in' ? 'Beginning' : 'End') + ' of segment ' + (index + 1));
          handle.setAttribute('aria-valuemin', '0'); handle.setAttribute('aria-valuemax', String(record.duration || 0));
          handle.setAttribute('aria-valuenow', String(edge === 'in' ? clip.in_s : clip.out_s));
          handle.addEventListener('pointerdown', function (event) { startEdgeTrim(event, index, edge, handle); });
        });
        segment.append(inEdge, title, time, trimReadout, outEdge);
        segment.addEventListener('click', function (event) {
          if (exporting || Date.now() < suppressClickUntil || event.target.closest('.clip-edge')) return;
          var rect = segment.getBoundingClientRect();
          var share = event.detail ? model.clamp((event.clientX - rect.left) / rect.width, 0, 1) : 0;
          stop(); selected = index; render();
          seekSequence(startOf(index) + share * duration);
          var focused = document.querySelector('.parody-segment[data-index="' + index + '"]'); if (focused) focused.focus();
        });
        segment.addEventListener('keydown', function (event) {
          if ((event.key === 'Enter' || event.key === ' ') && !event.target.closest('.clip-edge')) {
            event.preventDefault(); stop(); selected = index; render(); seekSequence(startOf(index)); return;
          }
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          var peers = clips.map(function (one, atIndex) { return {clip: one, index: atIndex}; }).filter(function (one) { return (one.clip.track === 'overlay') === (clip.track === 'overlay'); });
          var peer = peers.findIndex(function (one) { return one.index === index; });
          var next = peers[model.clamp(peer + (event.key === 'ArrowLeft' ? -1 : 1), 0, peers.length - 1)].index;
          selected = next; stop(); render(); seekSequence(startOf(next));
          var nextNode = document.querySelector('.parody-segment[data-index="' + next + '"]'); if (nextNode) nextNode.focus();
        });
        segment.addEventListener('dragstart', function (event) {
          if (laneLocked) { event.preventDefault(); return; }
          draggingIndex = index; event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('application/x-pine-timeline-index', String(index));
        });
        segment.addEventListener('dragend', function () { draggingIndex = -1; render(); });
        segment.addEventListener('pointerdown', function (event) { beginTouchReorder(event, segment, index); });
        lane.appendChild(segment);
      });
      timeline.scrollLeft = scroll; overlayTimeline.scrollLeft = overlayScroll;
      el('parodySequenceCount').textContent = clips.length + (clips.length === 1 ? ' segment' : ' segments');
      var clip = clips[selected], ready = !!clip && !exporting, selectedLocked = clip && (clip.track === 'overlay' ? overlayLocked : trackLocked);
      var decorated = clip ? model.spliceDecorate(clip) : null;
      el('parodyProjectSummary').textContent = sourceIds.length + (sourceIds.length === 1 ? ' source' : ' sources') + ' / ' + clips.length + (clips.length === 1 ? ' segment' : ' segments');
      el('parodySelectedLabel').textContent = clip ? (selected + 1) + '. ' + sourceName(clip.source_id) : 'Select a segment';
      el('parodyIn').disabled = el('parodyOut').disabled = !ready || selectedLocked;
      el('parodySetIn').disabled = el('parodySetOut').disabled = !ready || selectedLocked;
      el('parodySplit').disabled = !clips.length || exporting || selectedLocked;
      el('parodyMoveLeft').disabled = !ready || selected === 0 || selectedLocked;
      el('parodyMoveRight').disabled = !ready || selected === clips.length - 1 || selectedLocked;
      el('parodyDelete').disabled = !ready || selectedLocked;
      el('parodyIn').value = clip ? clip.in_s.toFixed(2) : '';
      el('parodyOut').value = clip ? clip.out_s.toFixed(2) : '';
      el('parodyIn').max = el('parodyOut').max = clip && sources[clip.source_id] ? sources[clip.source_id].duration : 0;
      ['parodyTrack', 'parodyStart', 'parodyTransition', 'parodyTransitionDuration', 'parodyVolume', 'parodyAudioFadeIn', 'parodyAudioFadeOut', 'parodyOpacity'].forEach(function (id) {
        el(id).disabled = !ready || selectedLocked;
      });
      el('parodyTrack').value = decorated ? decorated.track : 'base';
      el('parodyStart').value = decorated ? decorated.start_s.toFixed(2) : ''; el('parodyStart').disabled = !ready || selectedLocked || !decorated || decorated.track !== 'overlay';
      el('parodyTransition').value = decorated ? decorated.transition : 'cut';
      el('parodyTransitionDuration').value = decorated ? decorated.transition_s.toFixed(2) : '';
      el('parodyVolume').value = decorated ? decorated.volume : 1; el('parodyVolumeValue').textContent = Math.round((decorated ? decorated.volume : 1) * 100) + '%';
      el('parodyAudioFadeIn').value = decorated ? decorated.audio_fade_in_s.toFixed(2) : '';
      el('parodyAudioFadeOut').value = decorated ? decorated.audio_fade_out_s.toFixed(2) : '';
      el('parodyOpacity').value = decorated ? decorated.opacity : 1; el('parodyOpacityValue').textContent = Math.round((decorated ? decorated.opacity : 1) * 100) + '%';
      var maskReady = !!decorated && decorated.track === 'overlay' && !selectedLocked && !exporting;
      ['parodyMaskEdit', 'parodyMaskPen', 'parodyMaskClose', 'parodyMaskKeyframeAdd', 'parodyMaskKeyframe', 'parodyMaskKeyframeDelete', 'parodyMaskFeather', 'parodyMaskInvert', 'parodyMaskClear'].forEach(function (id) { el(id).disabled = !maskReady; });
      var frames = decorated && decorated.mask.keyframes || [], keyframeSelect = el('parodyMaskKeyframe'); keyframeSelect.replaceChildren();
      frames.forEach(function (frame, index) { var option = document.createElement('option'); option.value = String(index); option.textContent = model.clock(frame.at); keyframeSelect.appendChild(option); });
      maskFrameIndex = frames.length ? model.clamp(maskFrameIndex, 0, frames.length - 1) : 0; keyframeSelect.value = String(maskFrameIndex);
      el('parodyMaskKeyframeDelete').disabled = !maskReady || !frames.length;
      el('parodyMaskClose').disabled = !maskReady || !frames.length || frames[maskFrameIndex].points.length < 3;
      el('parodyMaskFeather').value = decorated ? decorated.mask.feather : 0; el('parodyMaskFeatherValue').textContent = String(decorated ? decorated.mask.feather : 0);
      el('parodyMaskInvert').checked = !!(decorated && decorated.mask.invert);
      el('parodyMaskEdit').setAttribute('aria-pressed', String(maskEditing)); el('parodyMaskPen').setAttribute('aria-pressed', String(maskPen));
      el('parodyPreview').classList.toggle('mask-editing', maskReady && maskEditing);
      el('parodyUndo').disabled = !historyPast.length || exporting;
      el('parodyRedo').disabled = !historyFuture.length || exporting;
      el('parodyPlay').disabled = !clips.length || exporting;
      scrub.disabled = !clips.length || exporting;
      var activeSources = model.spliceSourceIds(clips, sourceIds);
      el('parodySave').disabled = !clips.length || exporting || activeSources.some(function (id) { return !sources[id] || sources[id].status !== 'ready'; });
      displayPosition(); drawMask();
    }
    function snapshot() { return {clips: model.copy(clips), selected: selected, at: at}; }
    function restore(state) { stop(); clips = state.clips; selected = state.selected; render(); seekSequence(state.at); }
    function remember() { historyPast.push(snapshot()); if (historyPast.length > 80) historyPast.shift(); historyFuture.length = 0; }
    function editClips(next, nextSelected) {
      if (exporting || JSON.stringify(next) === JSON.stringify(clips)) return false;
      var previousAt = at;
      remember(); stop(); clips = next; selected = nextSelected;
      render(); seekSequence(clips[selected] ? (arguments.length > 2 ? arguments[2] : startOf(selected)) : 0);
      return true;
    }
    function insert(id, where, track, timelineStart) {
      track = track === 'overlay' ? 'overlay' : 'base';
      if (!sources[id] || exporting || (track === 'overlay' ? overlayLocked : trackLocked)) return;
      if (track === 'overlay') setOverlayCollapsed(false);
      if (clips.length >= 40) { message('A splice may have at most 40 segments.', true); return; }
      var index = Number.isFinite(Number(where)) ? model.clamp(Number(where), 0, clips.length) : selected < 0 ? clips.length : selected + 1;
      var clip = model.spliceDecorate(model.spliceClip(sources[id]), {track: track, start_s: track === 'overlay' ? Math.max(0, Number(timelineStart) || at) : 0});
      editClips(model.spliceInsert(clips, clip, index), index, track === 'overlay' ? clip.start_s : startOf(index));
      message(sourceName(id) + ' added to the timeline.');
    }
    function trimSelected(edge, value) {
      if (selected < 0 || exporting) return;
      var next = model.spliceTrim(clips, selected, edge, value, sources);
      if (!editClips(next, selected)) render();
    }
    function updateSelected(values, keepPosition) {
      if (selected < 0 || !clips[selected] || exporting) return false;
      var next = model.copy(clips);
      next[selected] = model.spliceDecorate(Object.assign({}, next[selected], values || {}));
      return editClips(next, selected, keepPosition === undefined ? at : keepPosition);
    }
    function updateMask(mutator) {
      if (selected < 0 || !clips[selected] || clips[selected].track !== 'overlay') return false;
      var decorated = model.spliceDecorate(clips[selected]), mask = model.copy(decorated.mask);
      mutator(mask, decorated); return updateSelected({mask: mask}, at);
    }
    function bindClipValue(id, field, parser) {
      el(id).addEventListener('change', function () { var value = parser ? parser(this.value) : this.value; updateSelected((function () { var out = {}; out[field] = value; return out; })()); });
    }
    bindClipValue('parodyStart', 'start_s', Number);
    bindClipValue('parodyTransition', 'transition');
    bindClipValue('parodyTransitionDuration', 'transition_s', Number);
    bindClipValue('parodyVolume', 'volume', Number);
    bindClipValue('parodyAudioFadeIn', 'audio_fade_in_s', Number);
    bindClipValue('parodyAudioFadeOut', 'audio_fade_out_s', Number);
    bindClipValue('parodyOpacity', 'opacity', Number);
    el('parodyVolume').addEventListener('input', function () { el('parodyVolumeValue').textContent = Math.round(Number(this.value) * 100) + '%'; });
    el('parodyOpacity').addEventListener('input', function () { el('parodyOpacityValue').textContent = Math.round(Number(this.value) * 100) + '%'; });
    el('parodyTrack').addEventListener('change', function () {
      var track = this.value === 'overlay' ? 'overlay' : 'base';
      if (track === 'overlay') setOverlayCollapsed(false);
      updateSelected({track: track, start_s: track === 'overlay' ? at : 0}, at);
    });
    el('parodyMaskEdit').addEventListener('click', function () { maskEditing = !maskEditing; if (!maskEditing) maskPen = false; render(); });
    el('parodyMaskPen').addEventListener('click', function () { maskPen = !maskPen; maskEditing = true; render(); });
    el('parodyMaskClose').addEventListener('click', function () { updateMask(function (mask) { mask.closed = true; }); });
    el('parodyMaskClear').addEventListener('click', function () { updateMask(function (mask) { mask.closed = false; mask.keyframes = []; }); maskFrameIndex = 0; });
    el('parodyMaskFeather').addEventListener('input', function () { el('parodyMaskFeatherValue').textContent = this.value; });
    el('parodyMaskFeather').addEventListener('change', function () { var value = Number(this.value); updateMask(function (mask) { mask.feather = value; }); });
    el('parodyMaskInvert').addEventListener('change', function () { var value = this.checked; updateMask(function (mask) { mask.invert = value; }); });
    el('parodyMaskKeyframe').addEventListener('change', function () { maskFrameIndex = Number(this.value) || 0; drawMask(); });
    el('parodyMaskKeyframeAdd').addEventListener('click', function () {
      var clip = clips[selected], local = clip ? model.clamp(at - startOf(selected), 0, clip.out_s - clip.in_s) : 0;
      updateMask(function (mask) {
        var prior = mask.keyframes[maskFrameIndex], points = prior ? model.copy(prior.points) : [];
        mask.keyframes.push({at: local, points: points}); mask.keyframes.sort(function (a, b) { return a.at - b.at; });
        maskFrameIndex = mask.keyframes.findIndex(function (frame) { return Math.abs(frame.at - local) < .001; });
      });
    });
    el('parodyMaskKeyframeDelete').addEventListener('click', function () {
      updateMask(function (mask) { mask.keyframes.splice(maskFrameIndex, 1); maskFrameIndex = Math.max(0, maskFrameIndex - 1); });
    });
    maskCanvas.addEventListener('pointerdown', function (event) {
      var clip = clips[selected]; if (!maskEditing || !clip || clip.track !== 'overlay' || overlayLocked) return;
      event.preventDefault();
      var rect = maskCanvas.getBoundingClientRect(), nx = model.clamp((event.clientX - rect.left) / rect.width, 0, 1), ny = model.clamp((event.clientY - rect.top) / rect.height, 0, 1);
      var original = model.copy(clips), before = JSON.stringify(clips), working = model.spliceDecorate(original[selected]);
      if (!working.mask.keyframes.length) {
        working.mask.keyframes.push({at: model.clamp(at - startOf(selected), 0, working.out_s - working.in_s), points: []}); maskFrameIndex = 0;
      }
      var points = working.mask.keyframes[maskFrameIndex].points, hit = null, best = 15;
      points.forEach(function (point, pointIndex) {
        [['anchor', point.x, point.y], ['in', point.in_x, point.in_y], ['out', point.out_x, point.out_y]].forEach(function (candidate) {
          var distance = Math.hypot((candidate[1] - nx) * rect.width, (candidate[2] - ny) * rect.height);
          if (distance < best) { best = distance; hit = {point: pointIndex, kind: candidate[0]}; }
        });
      });
      if (!hit && (maskPen || !points.length)) {
        points.push({x: nx, y: ny, in_x: nx, in_y: ny, out_x: nx, out_y: ny}); hit = {point: points.length - 1, kind: 'out', added: true};
      }
      if (!hit) return;
      original[selected] = working; clips = model.copy(original); remember(); historyPast[historyPast.length - 1].clips = JSON.parse(before); historyFuture.length = 0;
      var anchorStart = model.copy(points[hit.point]);
      function move(pointer) {
        pointer.preventDefault();
        var x = model.clamp((pointer.clientX - rect.left) / rect.width, 0, 1), y = model.clamp((pointer.clientY - rect.top) / rect.height, 0, 1);
        var next = model.copy(original), point = next[selected].mask.keyframes[maskFrameIndex].points[hit.point];
        if (hit.kind === 'anchor') {
          var dx = x - anchorStart.x, dy = y - anchorStart.y; point.x = x; point.y = y;
          point.in_x = anchorStart.in_x + dx; point.in_y = anchorStart.in_y + dy; point.out_x = anchorStart.out_x + dx; point.out_y = anchorStart.out_y + dy;
        } else {
          point[hit.kind + '_x'] = x; point[hit.kind + '_y'] = y;
          var opposite = hit.kind === 'in' ? 'out' : 'in'; point[opposite + '_x'] = model.clamp(point.x * 2 - x, -2, 3); point[opposite + '_y'] = model.clamp(point.y * 2 - y, -2, 3);
        }
        clips = next; render();
      }
      function end() {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end);
        if (JSON.stringify(clips) === before) historyPast.pop(); render(); seekSequence(at);
      }
      window.addEventListener('pointermove', move, {passive: false}); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
    });
    el('parodyPlay').addEventListener('click', playSequence);
    scrub.addEventListener('input', function () { stop(); seekSequence(Number(scrub.value)); });
    el('parodySplit').addEventListener('click', function () {
      var place = model.spliceLocate(clips, at);
      if (!place) return;
      var next = model.spliceSplit(clips, place.index, place.source_s);
      if (!editClips(next, place.index + 1)) message('Move the playhead at least 0.1 seconds from an edge to split.', true);
    });
    el('parodyMoveLeft').addEventListener('click', function () { editClips(model.spliceMove(clips, selected, selected - 1), selected - 1); });
    el('parodyMoveRight').addEventListener('click', function () { editClips(model.spliceMove(clips, selected, selected + 1), selected + 1); });
    el('parodyDelete').addEventListener('click', function () {
      if (selected < 0) return;
      var next = model.copy(clips); next.splice(selected, 1);
      editClips(next, Math.min(selected, next.length - 1));
    });
    el('parodyIn').addEventListener('change', function () { trimSelected('in', Number(this.value)); });
    el('parodyOut').addEventListener('change', function () { trimSelected('out', Number(this.value)); });
    ['In', 'Out'].forEach(function (edge) {
      el('parodySet' + edge).addEventListener('click', function () {
        var place = model.spliceLocate(clips, at);
        if (!place || place.index !== selected) { message('Place the playhead inside the selected segment.', true); return; }
        trimSelected(edge.toLowerCase(), place.source_s);
      });
    });
    el('parodyUndo').addEventListener('click', function () {
      if (!historyPast.length || exporting) return;
      historyFuture.push(snapshot()); restore(historyPast.pop());
    });
    el('parodyRedo').addEventListener('click', function () {
      if (!historyFuture.length || exporting) return;
      historyPast.push(snapshot()); restore(historyFuture.pop());
    });
    el('parodyTrackLock').addEventListener('click', function () {
      trackLocked = !trackLocked; this.setAttribute('aria-pressed', String(trackLocked));
      this.setAttribute('aria-label', trackLocked ? 'Unlock V1 track' : 'Lock V1 track');
      this.title = trackLocked ? 'Unlock V1 track' : 'Lock V1 track'; render();
    });
    el('parodyTrackMute').addEventListener('click', function () {
      trackMuted = !trackMuted; preview.muted = trackMuted; this.setAttribute('aria-pressed', String(trackMuted));
      this.setAttribute('aria-label', trackMuted ? 'Unmute V1 preview' : 'Mute V1 preview');
      this.title = trackMuted ? 'Unmute V1 preview' : 'Mute V1 preview';
    });
    el('parodyOverlayLock').addEventListener('click', function () {
      overlayLocked = !overlayLocked; this.setAttribute('aria-pressed', String(overlayLocked));
      this.setAttribute('aria-label', overlayLocked ? 'Unlock V2 track' : 'Lock V2 track');
      this.title = overlayLocked ? 'Unlock V2 track' : 'Lock V2 track'; render();
    });
    el('parodyOverlayMute').addEventListener('click', function () {
      overlayMuted = !overlayMuted; overlayPreview.muted = overlayMuted; this.setAttribute('aria-pressed', String(overlayMuted));
      this.setAttribute('aria-label', overlayMuted ? 'Unmute V2 overlay' : 'Mute V2 overlay');
      this.title = overlayMuted ? 'Unmute V2 overlay' : 'Mute V2 overlay';
    });
    function setBinCollapsed(collapsed) {
      var hidden = !!collapsed, toggle = el('parodyBinToggle');
      el('parodyWorkspace').classList.toggle('bin-collapsed', hidden);
      toggle.setAttribute('aria-expanded', String(!hidden));
      toggle.setAttribute('aria-label', hidden ? 'Show media panel' : 'Hide media panel');
      toggle.title = hidden ? 'Show media panel' : 'Hide media panel';
    }
    function setInspectorCollapsed(collapsed) {
      var hidden = !!collapsed, toggle = el('parodyInspectorToggle');
      el('parodyWorkspace').classList.toggle('inspector-collapsed', hidden);
      toggle.setAttribute('aria-expanded', String(!hidden));
      toggle.setAttribute('aria-label', hidden ? 'Show segment inspector' : 'Hide segment inspector');
      toggle.title = hidden ? 'Show segment inspector' : 'Hide segment inspector';
    }
    el('parodyBinToggle').addEventListener('click', function () {
      setBinCollapsed(!el('parodyWorkspace').classList.contains('bin-collapsed'));
    });
    el('parodyInspectorToggle').addEventListener('click', function () {
      setInspectorCollapsed(!el('parodyWorkspace').classList.contains('inspector-collapsed'));
    });
    function setOverlayCollapsed(collapsed) {
      overlayCollapsed = !!collapsed;
      el('parodyOverlayTrack').classList.toggle('collapsed', overlayCollapsed);
      el('parodyOverlayTimeline').hidden = overlayCollapsed;
      el('parodyOverlayToggle').setAttribute('aria-expanded', String(!overlayCollapsed));
      el('parodyOverlayToggle').setAttribute('aria-label', overlayCollapsed ? 'Show V2 overlays' : 'Hide V2 overlays');
      el('parodyOverlayToggle').title = overlayCollapsed ? 'Show V2 overlays' : 'Hide V2 overlays';
    }
    el('parodyOverlayToggle').addEventListener('click', function () {
      setOverlayCollapsed(!overlayCollapsed);
    });
    el('parodyBack').addEventListener('click', function () {
      stop();
      if (window.parent !== window) window.parent.postMessage({type: 'pine-video-editor-close'}, '*');
      else if (history.length > 1) history.back(); else window.close();
    });
    window.addEventListener('message', function (event) {
      if (window.parent === window || event.source !== window.parent
        || event.origin !== window.location.origin || !event.data
        || event.data.type !== 'pine-video-editor-command') return;
      var commands = {
        back: 'parodyBack', undo: 'parodyUndo', redo: 'parodyRedo', export: 'parodySave'
      }, target = commands[event.data.command], button = target && el(target);
      if (event.data.command === 'export' && typeof event.data.export_name === 'string') {
        el('parodyName').value = event.data.export_name.slice(0, 120);
      }
      if (button && !button.disabled) button.click();
    });
    document.addEventListener('keydown', function (event) {
      if (/INPUT|TEXTAREA/.test(event.target.tagName) || event.target.isContentEditable || event.altKey) return;
      if (event.key === ' ' && event.target.tagName !== 'BUTTON' && !event.ctrlKey && !event.metaKey) { event.preventDefault(); playSequence(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); el(event.shiftKey ? 'parodyRedo' : 'parodyUndo').click();
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selected >= 0) { event.preventDefault(); el('parodyDelete').click(); }
    });
    function previewSource(record) {
      if (!record || !record.url) return;
      sourcePreview.pause(); sourcePreview.muted = false; sourcePreview.volume = 1;
      sourcePreview.poster = sourcePoster(record); sourcePreview.src = record.url; sourcePreview.load();
      el('parodySourcePreviewName').textContent = record.name || 'Station clip';
      sourcePreview.play().catch(function () { /* Native controls remain available. */ });
    }
    function binRow(entry, sourceId, role) {
      var row = document.createElement('div'), image = document.createElement('img'), title = document.createElement('strong');
      var details = document.createElement('small'), previewButton = document.createElement('button');
      var clipId = String(entry.clip_id || entry.id || ''), resolved = sourceId || sourceClipIds[clipId] || '';
      row.className = 'parody-bin-item' + (importJobs[clipId] ? ' importing' : ''); row.tabIndex = 0; row.setAttribute('role', 'listitem');
      row.draggable = !exporting; row.dataset.sourceId = resolved; row.dataset.clipId = clipId;
      image.src = sourcePoster(entry); image.alt = ''; image.onerror = function () { image.src = '/spark/asset/pinebox.png'; };
      title.textContent = entry.name || role || 'Station clip';
      details.textContent = [role, entry.spoken || entry.topic || entry.folder || '', Number(entry.seconds || entry.duration) ? model.clock(entry.seconds || entry.duration) : ''].filter(Boolean).join(' / ');
      previewButton.type = 'button'; previewButton.textContent = 'Preview'; previewButton.dataset.action = 'preview';
      previewButton.addEventListener('click', function (event) { event.stopPropagation(); previewSource(resolved && sources[resolved] || entry); });
      function add() { addBinEntry(entry, resolved); }
      row.addEventListener('click', function (event) { if (!event.target.closest('[data-action=preview]')) add(); });
      row.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); add(); } });
      row.addEventListener('dragstart', function (event) {
        event.dataTransfer.effectAllowed = 'copy';
        event.dataTransfer.setData('application/x-pine-media', JSON.stringify(resolved ? {source_id: resolved} : {clip_id: clipId}));
      });
      row.append(image, title, details, previewButton); return row;
    }
    function renderBin() {
      var bin = el('parodyMediaBin'), scroll = bin.scrollTop; bin.replaceChildren();
      function heading(text) { var node = document.createElement('h3'); node.className = 'parody-bin-group'; node.textContent = text; bin.appendChild(node); }
      heading('Project sources');
      sourceIds.forEach(function (id) { if (sources[id]) bin.appendChild(binRow(sources[id], id, sourceRoles[id])); });
      if (libraryRows.length) {
        heading('Station library');
        libraryRows.forEach(function (row) { bin.appendChild(binRow(row, sourceClipIds[String(row.clip_id || row.id || '')] || '', 'Library')); });
      }
      el('parodyBinCount').textContent = sourceIds.filter(function (id) { return sources[id]; }).length + ' sources / ' + libraryRows.length + ' results';
      bin.scrollTop = scroll;
    }
    async function ensureLibrarySource(entry) {
      var clipId = String(entry.clip_id || entry.id || ''), known = sourceClipIds[clipId];
      if (known && sources[known] && sources[known].status === 'ready') return sources[known];
      if (importJobs[clipId]) return importJobs[clipId];
      if (sourceIds.length >= 20) throw new Error('This project already has the maximum of 20 sources.');
      importJobs[clipId] = (async function () {
        renderBin(); el('parodyLibraryStatus').textContent = 'Preparing ' + (entry.name || 'station clip') + '...';
        var record = await request('POST', '/api/video-editor/library/import', {clip_id: clipId});
        var id = String(record.source_id || record.id || '');
        record = registerSource(Object.assign({}, entry, record, {clip_id: clipId}), id, 'Library');
        for (var tries = 0; !gone && record.status !== 'ready' && tries < 180; tries += 1) {
          if (record.status === 'failed' || record.status === 'error') throw new Error(record.error || 'The clip could not be prepared.');
          await wait(1000);
          record = registerSource(Object.assign({}, entry, await request('GET', '/api/video-editor/sources/' + encodeURIComponent(id)), {clip_id: clipId}), id, 'Library');
        }
        if (record.status !== 'ready' || !record.url || !(record.duration >= .1)) throw new Error('The clip did not finish preparing.');
        el('parodyLibraryStatus').textContent = record.name + ' is ready.'; renderBin(); render(); return record;
      })();
      try { return await importJobs[clipId]; }
      finally { delete importJobs[clipId]; renderBin(); }
    }
    async function addBinEntry(entry, resolved, where, track, timelineStart) {
      track = track === 'overlay' ? 'overlay' : 'base';
      if (exporting || (track === 'overlay' ? overlayLocked : trackLocked)) return;
      try {
        var record = resolved && sources[resolved] || await ensureLibrarySource(entry);
        insert(record.id, where, track, timelineStart);
      } catch (error) { message(error.message || 'The clip could not be added.', true); el('parodyLibraryStatus').textContent = error.message || ''; }
    }
    function dropIndex(lane, event) {
      var segments = Array.prototype.slice.call(lane.querySelectorAll('.parody-segment'));
      for (var i = 0; i < segments.length; i += 1) {
        var rect = segments[i].getBoundingClientRect(); if (event.clientX < rect.left + rect.width / 2) return Number(segments[i].dataset.index);
      }
      return clips.length;
    }
    function setupDropLane(lane, track) {
      lane.addEventListener('dragover', function (event) {
        if (!(track === 'overlay' ? overlayLocked : trackLocked)) { event.preventDefault(); lane.classList.add('drag-over'); }
      });
      lane.addEventListener('dragleave', function (event) { if (!lane.contains(event.relatedTarget)) lane.classList.remove('drag-over'); });
      lane.addEventListener('drop', function (event) {
        event.preventDefault(); lane.classList.remove('drag-over'); if (track === 'overlay' ? overlayLocked : trackLocked) return;
        var slot = dropIndex(lane, event), fromText = event.dataTransfer.getData('application/x-pine-timeline-index');
        var from = fromText === '' ? draggingIndex : Number(fromText);
        var rect = lane.getBoundingClientRect(), timelineStart = track === 'overlay' ? model.clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1) * Math.max(1, length()) : 0;
        if (Number.isInteger(from) && from >= 0 && from < clips.length) {
          var next = model.copy(clips), moved = next.splice(from, 1)[0], target = from < slot ? slot - 1 : slot;
          moved = model.spliceDecorate(Object.assign({}, moved, {track: track, start_s: track === 'overlay' ? timelineStart : 0}));
          target = model.clamp(target, 0, next.length); next.splice(target, 0, moved);
          editClips(next, target, track === 'overlay' ? timelineStart : model.spliceStartOf(next, target)); draggingIndex = -1; return;
        }
        try {
          var payload = JSON.parse(event.dataTransfer.getData('application/x-pine-media') || '{}');
          if (payload.source_id && sources[payload.source_id]) insert(payload.source_id, slot, track, timelineStart);
          else if (payload.clip_id) {
            var entry = libraryRows.find(function (row) { return String(row.clip_id || row.id) === String(payload.clip_id); }) || {clip_id: payload.clip_id, name: 'Station clip'};
            addBinEntry(entry, '', slot, track, timelineStart);
          }
        } catch (error) { message('That media item could not be added.', true); }
      });
    }
    setupDropLane(timeline, 'base'); setupDropLane(overlayTimeline, 'overlay');
    async function searchLibrary(query) {
      var generation = ++searchGeneration;
      el('parodyLibraryStatus').textContent = 'Searching station clips...';
      try {
        var result = await request('GET', '/api/video-editor/library?q=' + encodeURIComponent(query || '') + '&limit=40');
        if (gone || generation !== searchGeneration) return;
        libraryRows = Array.isArray(result.clips) ? result.clips : Array.isArray(result.results) ? result.results : [];
        el('parodyLibraryStatus').textContent = libraryRows.length ? libraryRows.length + ' matching clips. Tap one to insert it.' : 'No matching video clips.';
        renderBin();
      } catch (error) { if (generation === searchGeneration) el('parodyLibraryStatus').textContent = error.message || 'Search is unavailable.'; }
    }
    el('parodySearchForm').addEventListener('submit', function (event) { event.preventDefault(); clearTimeout(searchTimer); searchLibrary(el('parodySearch').value); });
    el('parodySearch').addEventListener('input', function () {
      clearTimeout(searchTimer); var value = this.value; searchTimer = setTimeout(function () { searchLibrary(value); }, 350);
    });
    async function loadSources() {
      var generation = ++loadGeneration; clearTimeout(pollTimer);
      if (baseIds.length !== 2) {
        showLoading('Choose an original and a generated source.', true);
        message('Choose two different source videos.', true); return;
      }
      try {
        showLoading('Opening sources...', false);
        var records = await Promise.all(baseIds.map(function (id) { return request('GET', '/api/video-editor/sources/' + encodeURIComponent(id)); }));
        if (gone || generation !== loadGeneration) return;
        var waiting = false;
        records.forEach(function (record, index) {
          if (record.status === 'failed' || record.status === 'error') throw new Error(record.error || 'A source could not be opened.');
          if (record.status && record.status !== 'ready' || !record.url || !(Number(record.duration) >= .1)) { waiting = true; return; }
          registerSource(record, baseIds[index], index ? 'Generated' : 'Original');
        });
        renderBin();
        if (waiting) {
          showLoading('Preparing source videos...', false); pollTimer = setTimeout(loadSources, 1200); message('Preparing source videos...'); render(); return;
        }
        if (!seeded) { clips = baseIds.map(function (id) { return model.spliceDecorate(model.spliceClip(sources[id])); }); selected = 0; seeded = true; }
        el('parodyLoading').hidden = true;
        render(); seekSequence(at);
        message('Your source videos are kept.');
      } catch (error) {
        showLoading('Could not open the source videos.', true);
        message(error.message || 'Could not open the source videos.', true);
      }
    }
    el('parodyRetrySources').addEventListener('click', loadSources);
    async function exportSplice() {
      if (exporting || !clips.length) return;
      exporting = true; stop(); render();
      var button = el('parodySave'); button.textContent = 'Exporting...';
      try {
        var activeIds = model.spliceSourceIds(clips, sourceIds), firstSource = sources[activeIds[0]] || {};
        var token = params.get('save') || firstSource.save_token || '';
        var body = model.spliceBody(activeIds, clips, el('parodyName').value, token, sources);
        message('Starting export...');
        var result;
        try { result = await request('POST', '/api/video-editor/splice-exports', body); }
        catch (error) {
          if (error.status !== 401 && error.status !== 403) throw error;
          var fresh = await request('GET', '/api/video-editor/sources/' + encodeURIComponent(activeIds[0]) + '?mint=' + Date.now());
          body.save_token = fresh.save_token || body.save_token;
          result = await request('POST', '/api/video-editor/splice-exports', body);
        }
        var id = result.id;
        if (!id) throw new Error('The station did not return an export ID.');
        while (!['complete', 'done', 'failed', 'error'].includes(result.status)) {
          if (gone) return;
          await new Promise(function (resolve) { setTimeout(resolve, 1000); });
          result = await request('GET', '/api/video-editor/splice-exports/' + encodeURIComponent(id));
          var progress = Number(result.progress);
          if (Number.isFinite(progress)) message('Exporting to /sfx_ads... ' + Math.round(progress <= 1 ? progress * 100 : progress) + '%');
          else message('Exporting to /sfx_ads...');
        }
        if (result.status === 'failed' || result.status === 'error') throw new Error(result.error || 'The export failed.');
        var link = el('parodyDownload');
        if (result.url) link.href = result.url;
        link.download = result.name || 'parody-splice.mp4'; link.hidden = !result.url;
        var path = result.path || (result.name ? '/sfx_ads/' + result.name : '/sfx_ads');
        message('Saved to ' + path + '. Your sources are kept.');
        var detail = {id: id, export_id: id, url: result.url || '', name: link.download, path: path};
        if (window.parent !== window) window.parent.postMessage({type: 'pine-video-editor-export', detail: detail}, '*');
        window.dispatchEvent(new CustomEvent('pine-video-editor-export', {detail: detail}));
      } catch (error) { message(error.message || 'The export failed.', true); }
      finally { exporting = false; button.textContent = 'Export to SFX ads'; render(); }
    }
    el('parodySave').addEventListener('click', exportSplice);
    window.addEventListener('pagehide', function () { gone = true; clearTimeout(pollTimer); clearTimeout(searchTimer); stop(); sourcePreview.pause(); });
    preview.muted = false; preview.volume = 1; sourcePreview.muted = false; sourcePreview.volume = 1;
    render(); renderBin(); loadSources(); searchLibrary('');
  }

  loadSource();
})();
