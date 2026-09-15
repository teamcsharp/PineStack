/* A non-destructive editor: the source is never rewritten; Save creates a copy. */
(function () {
  'use strict';
  var M = window.PineVideoEditModel, $ = function (id) { return document.getElementById(id); };
  var video = $('video'), canvas = $('preview'), ctx = canvas.getContext('2d'), viewer = $('viewer');
  var lastFrame = document.createElement('canvas'), frameContext = lastFrame.getContext('2d'), hasFrame = false, exportState = null;
  var source = null, edit = null, past = [], future = [], tab = 'trim', tool = 'pen';
  var frameRect = {x: 0, y: 0, w: 1, h: 1}, gesture = null, raf = 0, busy = false, disposed = false;
  var loadedUrl = '', pendingSeek = null, showFrequencies = false, retryAction = null, sourcePoll = 0, sourceFailed = false, audioChosen = false;
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
    if (video.readyState >= 2) {
      if (lastFrame.width !== source.width || lastFrame.height !== source.height) { lastFrame.width = source.width; lastFrame.height = source.height; }
      frameContext.drawImage(video, 0, 0, source.width, source.height); hasFrame = true;
    }
    if (hasFrame) { ctx.filter = M.filter(edit); ctx.drawImage(lastFrame, 0, 0, source.width, source.height); ctx.filter = 'none'; }
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
  }
  video.addEventListener('seeked', function () {
    if (pendingSeek !== null && Math.abs(video.currentTime - pendingSeek) > .035) { video.currentTime = pendingSeek; return; }
    pendingSeek = null; repaint();
  });
  video.addEventListener('loadeddata', function () { $('loading').hidden = true; repaint(); });
  video.addEventListener('error', function () { $('loading').hidden = false; $('loading').textContent = 'The preview could not load.'; status('Try opening the recording again.', true, loadSource); });
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

  canvas.addEventListener('pointerdown', function (event) {
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

  function waveform() {
    var c = $('wave'), r = c.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(42 * dpr));
    var context = c.getContext('2d'), peaks = source && source.waveform;
    if (peaks && !Array.isArray(peaks)) peaks = peaks.peaks || peaks.values;
    context.fillStyle = '#1a1c21'; context.fillRect(0, 0, c.width, c.height);
    if (!source || !source.has_audio) { context.fillStyle = '#9a9da5'; context.font = 12 * dpr + 'px system-ui'; context.textAlign = 'center'; context.fillText('No audio', c.width / 2, c.height / 2 + 4 * dpr); return; }
    if (!Array.isArray(peaks) || !peaks.length) { context.fillStyle = '#9a9da5'; context.font = 12 * dpr + 'px system-ui'; context.textAlign = 'center'; context.fillText(source.status === 'ready' ? 'Audio waveform unavailable' : 'Reading audio…', c.width / 2, c.height / 2 + 4 * dpr); return; }
    context.strokeStyle = '#8cd4c0'; context.lineWidth = Math.max(1, dpr);
    for (var x = 0; x < c.width; x += Math.max(1, Math.round(dpr * 2))) {
      var index = Math.min(peaks.length - 1, Math.floor(x / c.width * peaks.length)), raw = peaks[index];
      var amplitude = Array.isArray(raw) ? Math.max.apply(null, raw.map(Math.abs)) : Math.abs(Number(raw) || 0);
      var height = Math.min(1, amplitude) * c.height * .44;
      context.beginPath(); context.moveTo(x, c.height / 2 - Math.max(.5, height)); context.lineTo(x, c.height / 2 + Math.max(.5, height)); context.stroke();
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
    if (loadedUrl !== source.url) { loadedUrl = source.url; hasFrame = false; video.src = source.url; video.load(); }
    var spectrum = source.spectrogram_url; if (spectrum) { $('spectrogram').src = spectrum; $('soundView').disabled = false; }
    var notice = M.audioNotice(source); $('audioNotice').textContent = notice; $('audioNotice').hidden = !notice;
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
