/* Geometry and edit decisions shared by the touch preview and export. */
(function (root) {
  'use strict';
  function finite(v, fallback) { return Number.isFinite(Number(v)) ? Number(v) : fallback; }
  function clamp(v, low, high) { return Math.max(low, Math.min(high, v)); }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function rotation(v) { return ((Math.round(finite(v, 0) / 90) * 90) % 360 + 360) % 360; }
  function crop(value) {
    value = value || {};
    var w = clamp(finite(value.w, 1), .02, 1), h = clamp(finite(value.h, 1), .02, 1);
    return {x: clamp(finite(value.x, 0), 0, 1 - w), y: clamp(finite(value.y, 0), 0, 1 - h), w: w, h: h};
  }
  function create(source) {
    return {in_s: 0, out_s: Math.max(0, finite(source.duration, 0)), crop: crop(), rotation: 0,
      brightness: 1, contrast: 1, saturation: 1, include_audio: !!source.has_audio, marks: []};
  }
  function trim(edit, edge, at, duration) {
    var result = copy(edit), total = Math.max(0, finite(duration, 0)), gap = Math.min(.1, total);
    var start = clamp(finite(result.in_s, 0), 0, Math.max(0, total - gap));
    var end = clamp(finite(result.out_s, total), start + gap, total);
    if (edge === 'in') start = clamp(finite(at, start), 0, end - gap);
    else end = clamp(finite(at, end), start + gap, total);
    result.in_s = start; result.out_s = end;
    return result;
  }
  function outputSize(source, edit) {
    var box = crop(edit.crop), w = Math.max(2, Math.floor(Math.round(source.width * box.w) / 2) * 2), h = Math.max(2, Math.floor(Math.round(source.height * box.h) / 2) * 2);
    return rotation(edit.rotation) % 180 ? {width: h, height: w} : {width: w, height: h};
  }
  function project(point, box, turn) {
    box = crop(box); var x = (point.x - box.x) / box.w, y = (point.y - box.y) / box.h;
    switch (rotation(turn)) { case 90: return {x: 1 - y, y: x}; case 180: return {x: 1 - x, y: 1 - y}; case 270: return {x: y, y: 1 - x}; default: return {x: x, y: y}; }
  }
  function unproject(point, box, turn) {
    box = crop(box); var x = point.x, y = point.y, u = x, v = y;
    switch (rotation(turn)) { case 90: u = y; v = 1 - x; break; case 180: u = 1 - x; v = 1 - y; break; case 270: u = 1 - y; v = x; break; }
    return {x: box.x + u * box.w, y: box.y + v * box.h};
  }
  function fit(width, height, ratio) {
    var w = Math.max(1, width), h = Math.max(1, height);
    if (w / h > ratio) w = h * ratio; else h = w / ratio;
    return {x: (width - w) / 2, y: (height - h) / 2, w: w, h: h};
  }
  function aspectCrop(source, ratio) {
    var full = source.width / source.height;
    return ratio > full ? crop({x: 0, y: (1 - full / ratio) / 2, w: 1, h: full / ratio})
      : crop({x: (1 - ratio / full) / 2, y: 0, w: ratio / full, h: 1});
  }
  function filter(edit) { return 'brightness(' + edit.brightness + ') contrast(' + edit.contrast + ') saturate(' + edit.saturation + ')'; }
  function audioNotice(source) {
    var capture = source.audio_capture || {}, state = capture.state || '';
    if (state === 'partial' || capture.complete === false && source.has_audio) {
      var coverage = Number(capture.coverage_ratio), percent = Number.isFinite(coverage) ? ' (' + Math.round(clamp(coverage, 0, 1) * 100) + '% captured)' : '';
      return 'Audio has gaps' + percent + '. Missing sound cannot be restored in this editor.';
    }
    if (!source.has_audio) return capture.video_only_explicit ? 'This recording was captured without audio.' : 'No audio was captured in this recording.';
    if (source.audio_signal === 'silent' || state === 'captured_silence') return 'The recorded audio is silent.';
    if (source.audio_signal === 'unavailable') return 'The audio track is present, but its waveform could not be read.';
    return '';
  }
  function exportBody(source, edit, overlay) {
    var clean = trim(trim(edit, 'in', edit.in_s, source.duration), 'out', edit.out_s, source.duration);
    return {source_id: String(source.id || ''), in_s: clean.in_s, out_s: clean.out_s,
      crop: crop(clean.crop), rotation: rotation(clean.rotation), brightness: clamp(finite(clean.brightness, 1), .5, 1.5),
      contrast: clamp(finite(clean.contrast, 1), .5, 1.5), saturation: clamp(finite(clean.saturation, 1), 0, 2),
      include_audio: !!source.has_audio && !!clean.include_audio, overlay_png: String(overlay || '')};
  }
  function clock(value) {
    var n = Math.max(0, finite(value, 0)), minutes = Math.floor(n / 60), seconds = (n % 60).toFixed(2);
    return minutes + ':' + (n % 60 < 10 ? '0' : '') + seconds;
  }
  var api = {clamp: clamp, copy: copy, crop: crop, rotation: rotation, create: create, trim: trim, outputSize: outputSize,
    project: project, unproject: unproject, fit: fit, aspectCrop: aspectCrop, filter: filter, audioNotice: audioNotice, exportBody: exportBody, clock: clock};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.PineVideoEditModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
