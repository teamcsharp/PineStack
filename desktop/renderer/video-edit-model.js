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
  async function editorRequest(environment, method, path, body) {
    environment = environment || {};
    var desktop = environment.desktop || {}, result;
    if (method === 'GET' && typeof desktop.get === 'function') result = await desktop.get(path);
    else if (method === 'POST' && typeof desktop.post === 'function') result = await desktop.post(path, body);
    else {
      var api = typeof environment.parentApi === 'function' ? environment.parentApi
        : typeof environment.sameOriginApi === 'function' ? environment.sameOriginApi : null;
      if (api) result = await api(path, {method: method, body: body ? JSON.stringify(body) : undefined});
      else {
        if (typeof environment.fetch !== 'function') throw new Error('No station request transport is available.');
        var headers = {'Content-Type': 'application/json'}, key = String(environment.key || '');
        if (key) headers.Authorization = 'Bearer ' + key;
        if (body && body.save_token) headers['X-Pine-Save-Token'] = body.save_token;
        var response = await environment.fetch(path, {method: method, headers: headers, body: body ? JSON.stringify(body) : undefined});
        result = await response.json().catch(function () { return {}; });
        if (!response.ok) {
          var error = new Error(result.detail || result.error || 'The station did not answer.'); error.status = response.status; throw error;
        }
      }
    }
    if (!result || result.ok === false || result.error && !result.status) throw new Error(result && (result.error || result.detail) || 'The station did not answer.');
    return result;
  }
  var MIN_SPLICE = .1;
  var TRANSITIONS = ['cut', 'dissolve', 'fade', 'wipe'];
  function spliceMask(value, duration) {
    value = value || {};
    var keyframes = Array.isArray(value.keyframes) ? value.keyframes.slice(0, 24).map(function (frame) {
      var points = Array.isArray(frame.points) ? frame.points.slice(0, 48).map(function (point) {
        var x = clamp(finite(point.x, .5), 0, 1), y = clamp(finite(point.y, .5), 0, 1);
        return {x: x, y: y,
          in_x: clamp(finite(point.in_x, x), -2, 3), in_y: clamp(finite(point.in_y, y), -2, 3),
          out_x: clamp(finite(point.out_x, x), -2, 3), out_y: clamp(finite(point.out_y, y), -2, 3)};
      }) : [];
      return {at: clamp(finite(frame.at, 0), 0, Math.max(0, duration)), points: points};
    }) : [];
    keyframes.sort(function (a, b) { return a.at - b.at; });
    return {closed: !!value.closed, feather: clamp(finite(value.feather, 0), 0, 32), invert: !!value.invert, keyframes: keyframes};
  }
  function spliceDecorate(clip, options) {
    var result = Object.assign({}, copy(clip), options || {}), duration = Math.max(MIN_SPLICE, result.out_s - result.in_s);
    result.track = result.track === 'overlay' ? 'overlay' : 'base';
    result.start_s = Math.max(0, finite(result.start_s, 0));
    result.volume = clamp(finite(result.volume, 1), 0, 2);
    result.audio_fade_in_s = clamp(finite(result.audio_fade_in_s, 0), 0, duration);
    result.audio_fade_out_s = clamp(finite(result.audio_fade_out_s, 0), 0, duration);
    result.transition = TRANSITIONS.indexOf(result.transition) >= 0 ? result.transition : 'cut';
    result.transition_s = clamp(finite(result.transition_s, 0), 0, Math.min(10, duration));
    result.opacity = clamp(finite(result.opacity, 1), 0, 1);
    result.mask = spliceMask(result.mask, duration);
    return result;
  }
  function spliceMaskAt(mask, at) {
    var frames = mask && Array.isArray(mask.keyframes) ? mask.keyframes : [];
    if (!frames.length) return [];
    var position = Math.max(0, finite(at, 0)), before = frames[0], after = frames[frames.length - 1];
    for (var i = 0; i < frames.length; i += 1) {
      if (frames[i].at <= position) before = frames[i];
      if (frames[i].at >= position) { after = frames[i]; break; }
    }
    if (before === after || before.points.length !== after.points.length) return copy(before.points);
    var share = clamp((position - before.at) / Math.max(.000001, after.at - before.at), 0, 1);
    return before.points.map(function (point, index) {
      var other = after.points[index], out = {};
      ['x','y','in_x','in_y','out_x','out_y'].forEach(function (field) { out[field] = point[field] + (other[field] - point[field]) * share; });
      return out;
    });
  }
  function spliceClip(source, start, end) {
    var duration = Math.max(0, finite(source.duration, 0));
    if (duration < MIN_SPLICE) throw new Error('This source is too short to insert.');
    var inside = clamp(finite(start, 0), 0, duration - MIN_SPLICE);
    var outside = clamp(finite(end, duration), inside + MIN_SPLICE, duration);
    return {source_id: String(source.id), in_s: inside, out_s: outside};
  }
  function spliceStartOf(clips, index) {
    var clip = clips[index];
    if (!clip) return 0;
    if (clip.track === 'overlay') return Math.max(0, finite(clip.start_s, 0));
    var total = 0;
    for (var i = 0; i < index; i += 1) if (clips[i].track !== 'overlay') total += clips[i].out_s - clips[i].in_s;
    return total;
  }
  function spliceLength(clips) {
    var base = 0, end = 0;
    clips.forEach(function (clip, index) {
      var duration = clip.out_s - clip.in_s;
      if (clip.track === 'overlay') end = Math.max(end, spliceStartOf(clips, index) + duration);
      else { base += duration; end = Math.max(end, base); }
    });
    return end;
  }
  function spliceLocate(clips, at) {
    var total = spliceLength(clips), position = clamp(finite(at, 0), 0, total), offset = 0;
    for (var i = 0; i < clips.length; i += 1) {
      if (clips[i].track === 'overlay') continue;
      var length = clips[i].out_s - clips[i].in_s;
      var lastBase = !clips.slice(i + 1).some(function (clip) { return clip.track !== 'overlay'; });
      if (position < offset + length || lastBase && position <= offset + length + 1e-6)
        return {index: i, source_id: clips[i].source_id, source_s: clips[i].in_s + clamp(position - offset, 0, length), start_s: offset};
      offset += length;
    }
    var overlays = spliceActiveOverlays(clips, position);
    return overlays.length ? {index: overlays[0].index, source_id: overlays[0].clip.source_id,
      source_s: overlays[0].clip.in_s + position - overlays[0].start_s, start_s: overlays[0].start_s} : null;
  }
  function spliceActiveOverlays(clips, at) {
    var position = Math.max(0, finite(at, 0)), out = [];
    clips.forEach(function (clip, index) {
      if (clip.track !== 'overlay') return;
      var start = spliceStartOf(clips, index), end = start + clip.out_s - clip.in_s;
      if (position >= start && position < end) out.push({index: index, clip: clip, start_s: start, source_s: clip.in_s + position - start});
    });
    return out;
  }
  function spliceSplit(clips, index, sourceTime) {
    var result = copy(clips), clip = result[index];
    if (!clip) return result;
    var at = finite(sourceTime, clip.in_s);
    if (at - clip.in_s < MIN_SPLICE - 1e-6 || clip.out_s - at < MIN_SPLICE - 1e-6) return result;
    var left = Object.assign({}, clip, {out_s: at}), right = Object.assign({}, clip, {in_s: at});
    if (clip.track === 'overlay') right.start_s = Math.max(0, finite(clip.start_s, 0)) + at - clip.in_s;
    result.splice(index, 1, left, right);
    return result;
  }
  function spliceTrim(clips, index, edge, at, sources) {
    var result = copy(clips), clip = result[index], source = clip && sources[clip.source_id];
    if (!source) return result;
    if (edge === 'in') clip.in_s = clamp(finite(at, clip.in_s), 0, clip.out_s - MIN_SPLICE);
    if (edge === 'out') clip.out_s = clamp(finite(at, clip.out_s), clip.in_s + MIN_SPLICE, source.duration);
    return result;
  }
  function spliceMove(clips, from, to) {
    var result = copy(clips);
    if (from < 0 || from >= result.length || to < 0 || to >= result.length) return result;
    result.splice(to, 0, result.splice(from, 1)[0]);
    return result;
  }
  function spliceInsert(clips, clip, at) {
    var result = copy(clips), index = clamp(Math.round(finite(at, result.length)), 0, result.length);
    result.splice(index, 0, copy(clip));
    return result;
  }
  function spliceSourceIds(clips, preferred) {
    var used = new Set(clips.map(function (clip) { return String(clip.source_id); }));
    var out = [];
    (preferred || []).forEach(function (id) {
      id = String(id || '');
      if (id && used.has(id) && out.indexOf(id) < 0) out.push(id);
    });
    clips.forEach(function (clip) {
      var id = String(clip.source_id || '');
      if (id && out.indexOf(id) < 0) out.push(id);
    });
    return out;
  }
  function spliceBody(sourceIds, clips, name, saveToken, sources) {
    if (!Array.isArray(sourceIds) || !sourceIds.length || sourceIds.length > 20 || !clips.length)
      throw new Error('Add clips from up to twenty sources.');
    if (new Set(sourceIds.map(String)).size !== sourceIds.length) throw new Error('Every source must be distinct.');
    if (clips.length > 40) throw new Error('A splice may have at most 40 segments.');
    if (spliceLength(clips) > 600) throw new Error('A splice may be at most ten minutes.');
    var allowed = new Set(sourceIds.map(String));
    var clean = clips.map(function (clip, index) {
      var id = String(clip.source_id), source = sources[id];
      if (!allowed.has(id) || !source || !Number.isFinite(Number(clip.in_s)) || !Number.isFinite(Number(clip.out_s))
        || clip.in_s < 0 || clip.out_s - clip.in_s < MIN_SPLICE - 1e-6 || clip.out_s > source.duration + 1e-6)
        throw new Error('A segment is outside its source.');
      var decorated = spliceDecorate(Object.assign({}, clip, {source_id: id, in_s: Number(clip.in_s), out_s: Number(clip.out_s)}));
      decorated.start_s = decorated.track === 'overlay' ? decorated.start_s : spliceStartOf(clips, index);
      return decorated;
    });
    return {source_ids: sourceIds.map(String), clips: clean, name: String(name || '').trim(), save_token: String(saveToken || '')};
  }
  function audioSplitCreate(source) {
    var clip = spliceClip(source);
    clip.name = String(source.pine_sfx && source.pine_sfx.name || source.name || 'Part 1').trim();
    return clip;
  }
  function audioSplitAt(clips, index, at) {
    var result = copy(clips), clip = result[index], cut = finite(at, NaN);
    if (!clip || !Number.isFinite(cut) || cut - clip.in_s < .2 - 1e-6
      || clip.out_s - cut < .2 - 1e-6) return result;
    result.splice(index, 1, Object.assign({}, clip, {out_s: cut}),
      Object.assign({}, clip, {in_s: cut, name: 'Part ' + (clips.length + 1)}));
    return result;
  }
  function audioSplitTrim(clips, index, edge, at, source) {
    var result = copy(clips), clip = result[index];
    if (!clip || !source || !(source.duration >= .2)) return result;
    if (edge === 'in') clip.in_s = clamp(finite(at, clip.in_s), 0, clip.out_s - .2);
    if (edge === 'out') clip.out_s = clamp(finite(at, clip.out_s), clip.in_s + .2, source.duration);
    return result;
  }
  function audioSplitBody(source, clips, keepOriginal, saveToken) {
    if (!source || !source.id || !Array.isArray(clips) || clips.length < 2 || clips.length > 20)
      throw new Error('Select between 2 and 20 pieces.');
    var duration = finite(source.duration, 0);
    var clean = clips.map(function (clip) {
      var start = Number(clip.in_s), end = Number(clip.out_s), name = String(clip.name || '').trim();
      if (clip.source_id !== String(source.id) || !Number.isFinite(start) || !Number.isFinite(end)
        || start < 0 || end - start < .2 - 1e-6 || end > duration + 1e-6)
        throw new Error('A piece is outside the source.');
      if (!name) throw new Error('Name every piece before exporting.');
      return {in_s: start, out_s: end, name: name};
    });
    return {source_id: String(source.id), clips: clean, keep_original: !!keepOriginal,
      save_token: String(saveToken || '')};
  }
  var api = {clamp: clamp, copy: copy, crop: crop, rotation: rotation, create: create, trim: trim, outputSize: outputSize,
    project: project, unproject: unproject, fit: fit, aspectCrop: aspectCrop, filter: filter, audioNotice: audioNotice, exportBody: exportBody, clock: clock,
    editorRequest: editorRequest,
    spliceClip: spliceClip, spliceDecorate: spliceDecorate, spliceMask: spliceMask, spliceMaskAt: spliceMaskAt, spliceStartOf: spliceStartOf,
    spliceLength: spliceLength, spliceLocate: spliceLocate, spliceActiveOverlays: spliceActiveOverlays, spliceSplit: spliceSplit,
    spliceTrim: spliceTrim, spliceMove: spliceMove, spliceInsert: spliceInsert, spliceSourceIds: spliceSourceIds, spliceBody: spliceBody,
    audioSplitCreate: audioSplitCreate, audioSplitAt: audioSplitAt, audioSplitTrim: audioSplitTrim, audioSplitBody: audioSplitBody};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.PineVideoEditModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
