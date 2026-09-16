/* A non-destructive editor: the source is never rewritten; Save creates a copy. */
(function () {
  'use strict';
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
  async function api(method, path, body) {
    var result;
    if (method === 'GET' && typeof bridge.get === 'function') result = await bridge.get(path);
    else if (method === 'POST' && typeof bridge.post === 'function') result = await bridge.post(path, body);
    else if (host !== window && typeof host.api === 'function') result = await host.api(path, {method: method, body: body ? JSON.stringify(body) : undefined});
    else {
      var headers = {'Content-Type': 'application/json'}, key = window.__PINE_VIDEO_EDITOR_KEY || '';
      if (key) headers.Authorization = 'Bearer ' + key;
      var response = await fetch(path, {method: method, headers: headers, body: body ? JSON.stringify(body) : undefined});
      result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The video could not be processed.');
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
    frameRect = M.fit(w, h, sideways ? ch / cw : cw / ch);
    var scale = frameRect.w / (sideways ? ch : cw);
    ctx.save(); ctx.beginPath(); ctx.rect(frameRect.x, frameRect.y, frameRect.w, frameRect.h); ctx.clip();
    ctx.translate(frameRect.x + frameRect.w / 2, frameRect.y + frameRect.h / 2); ctx.rotate(edit.rotation * Math.PI / 180); ctx.scale(scale, scale);
    ctx.translate(-(crop.x + crop.w / 2) * source.width, -(crop.y + crop.h / 2) * source.height);
    if (video.readyState >= 2 && !video.seeking) {
      if (lastFrame.width !== source.width || lastFrame.height !== source.height) { lastFrame.width = source.width; lastFrame.height = source.height; }
      frameContext.drawImage(video, 0, 0, source.width, source.height); hasFrame = true;
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
  document.addEventListener('keydown', function (event) { if (/INPUT|TEXTAREA/.test(event.target.tagName)) return; if (event.key === ' ') { event.preventDefault(); play(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); } });
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
    if (loadedUrl !== source.url) {
      loadedUrl = source.url; hasFrame = false;
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
  async function finishSave(result) {
    $('download').href = result.url || '/api/video-editor/exports/' + result.id + '/file'; $('download').download = result.name || 'edited-video.mp4'; $('download').hidden = false;
    notify('pine-video-editor-export', {id: result.id, export_id: result.id, url: result.url, name: result.name});
    if (typeof bridge.replayKeepEdited === 'function') {
      status('Saving your copy…');
      var saved = await bridge.replayKeepEdited({export_id: result.id, name: result.name});
      if (!saved || saved.ok === false) throw new Error(saved && (saved.detail || saved.error) || 'The copy is ready, but could not be saved on this device.');
      status('Saved copy. Your original is kept.');
    } else status('Your copy is ready to download.');
  }
  async function save() {
    if (!source || !edit || busy || source.status !== 'ready') return;
    busy = true; video.pause(); document.body.classList.add('busy'); $('save').textContent = 'Saving…'; changed(); $('download').hidden = true;
    try {
      status('Creating your copy…');
      var body = M.exportBody(source, edit, overlayImage()), signature = JSON.stringify(body);
      if (!exportState || exportState.signature !== signature) exportState = {signature: signature, result: await api('POST', '/api/video-editor/exports', body)};
      var result = exportState.result, id = result.id;
      while (!['complete', 'done', 'failed', 'error'].includes(result.status)) {
        if (disposed) return;
        await new Promise(function (resolve) { setTimeout(resolve, 1000); });
        result = await api('GET', result.poll_url || '/api/video-editor/exports/' + encodeURIComponent(id));
        result.id = result.id || id; exportState.result = result;
        if (result.progress !== undefined) status('Creating your copy… ' + Math.round(Number(result.progress) <= 1 ? Number(result.progress) * 100 : Number(result.progress)) + '%');
      }
      if (['failed', 'error'].includes(result.status)) { exportState = null; throw new Error(result.error || 'The copy could not be made.'); }
      result.id = result.id || id; await finishSave(result);
    } catch (error) { status(error.message || 'The copy could not be saved.', true, save); }
    finally { busy = false; document.body.classList.remove('busy'); $('save').textContent = 'Save copy'; changed(); }
  }
  $('save').addEventListener('click', save);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { repaint(); waveform(); }).observe(viewer);
  else window.addEventListener('resize', function () { repaint(); waveform(); });
  window.addEventListener('pagehide', function () { disposed = true; video.pause(); clearTimeout(sourcePoll); cancelAnimationFrame(raf); });
  loadSource();
})();
