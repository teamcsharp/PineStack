/* Bounded, passive evidence for the script report. No DOM or playback writes. */
(function (root) {
  'use strict';
  var RETENTION_MS = 60000, EVENTS_LIMIT = 320, ROWS_LIMIT = 96, TEXT_LIMIT = 240;
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function number(value) { return value !== null && value !== '' && isFinite(Number(value)) ? Number(value) : null; }
  function compactRow(row) {
    row = row || {};
    var text = String(row.text || '');
    return {id: String(row.id || row.line || ''), element_id: String(row.element_id || ''),
      block: number(row.block), ord: number(row.ord), kind: String(row.kind || row.type || ''),
      who: String(row.who || row.name || ''), text: text.slice(0, TEXT_LIMIT),
      text_truncated: text.length > TEXT_LIMIT, media: String(row.media || row.clip_media || ''),
      /* [#1189] every name the row answers to, so the server folds aliases rather than flagging them */
      sfx: String(row.sfx || ''), url: String(row.url || row.clip || '').split('?')[0].split('/').pop() || '',
      aired: String(row.aired || ''),
      from_s: number(row.from_s), until_s: number(row.until_s), document_index: number(row.document_index)};
  }
  function revision(elements) {
    var hash = 2166136261;
    for (var i = 0; i < elements.length; i += 1) {
      var r = elements[i] || {};
      var text = JSON.stringify([r.id, r.line, r.type, r.text, r.block, r.ord]);
      for (var j = 0; j < text.length; j += 1) { hash ^= text.charCodeAt(j); hash = Math.imul(hash, 16777619); }
    }
    return elements.length + '-' + (hash >>> 0).toString(16);
  }
  function readAudio(bridge, player, estimate) {
    var unknown = {player_state_available: false, volume: null, muted: null,
      ready_state: null, network_state: null, buffered_end_s: null};
    if (bridge && number(bridge.t) !== null) return Object.assign({}, unknown,
      {source: 'bridge', file: String(bridge.file || ''), position_s: number(bridge.t), observed_at_ms: number(bridge.at)});
    if (player && !player.paused && !player.ended && number(player.currentTime) !== null) {
      var url = String(player.currentSrc || player.src || '').split('?')[0];
      var bufferEnd = null;
      try {
        for (var i = 0; player.buffered && i < player.buffered.length; i += 1) {
          if (player.buffered.start(i) <= player.currentTime && player.buffered.end(i) >= player.currentTime) bufferEnd = player.buffered.end(i);
        }
      } catch (e) { /* no readable buffered range */ }
      return {source: 'local', file: url.split('/').pop() || '', position_s: number(player.currentTime), observed_at_ms: null,
        player_state_available: true, volume: number(player.volume), muted: typeof player.muted === 'boolean' ? player.muted : null,
        ready_state: number(player.readyState), network_state: number(player.networkState), buffered_end_s: bufferEnd};
    }
    if (number(estimate) !== null && Number(estimate) >= 0) return Object.assign({}, unknown,
      {source: 'estimated', file: '', position_s: Number(estimate), observed_at_ms: null});
    return Object.assign({}, unknown, {source: 'unavailable', file: '', position_s: null, observed_at_ms: null});
  }
  function contextIndex(highlight, active, visible, length) {
    var choices = [highlight, active, visible];
    for (var i = 0; i < choices.length; i += 1) {
      if (Number.isInteger(choices[i]) && choices[i] >= 0 && choices[i] < length) return choices[i];
    }
    return -1;
  }
  function selectMappings(feed, audio, activeId, highlightId) {
    var file = String((audio && audio.file) || ''), position = number(audio && audio.position_s);
    /* [#1189] the same fold script-page.js applies: a board sting's row
       carries no media at all, only `sfx: <16hex>` and `url: /sfx/<16hex>?t=`,
       so the neighbourhood around a sounding sting was always empty and the
       report had no rows to show for #1188, #1197, #1228 or #1234. */
    function rowFile(row) {
      var named = String(row.clip_media || row.media || '');
      if (named) return named;
      var base = String(row.url || row.clip || '').split('?')[0].split('/').pop();
      return base || String(row.sfx || '');
    }
    function offset(row, own, clip) { return number(row[own]) !== null ? number(row[own]) : number(row[clip]); }
    var same = file ? feed.filter(function (r) { return rowFile(r) === file; }) : [];
    same = same.slice().sort(function (a, b) {
      var av = offset(a, 'from', 'clip_from'), bv = offset(b, 'from', 'clip_from');
      return (av === null ? Infinity : av) - (bv === null ? Infinity : bv);
    });
    var named = feed.filter(function (r) { return !!r.id && (String(r.id) === activeId || String(r.id) === highlightId); });
    var all = new Set(same.concat(named).map(function (r) { return String(r.id || ''); }).filter(Boolean));
    var pivot = -1, distance = Infinity;
    same.forEach(function (r, i) {
      var from = offset(r, 'from', 'clip_from'), until = offset(r, 'until', 'clip_until');
      if (position !== null && from !== null) {
        var d = position >= from && until !== null && position < until ? 0
          : Math.min(Math.abs(position - from), until === null ? Infinity : Math.abs(position - until));
        if (d < distance) { distance = d; pivot = i; }
      }
    });
    // A named current cue or a one-row clip supplies context if offsets do not.
    if (pivot < 0) pivot = same.findIndex(function (r) { return String(r.id || '') === activeId || String(r.id || '') === highlightId; });
    if (pivot < 0 && same.length === 1) pivot = 0;
    var neighborhood = pivot < 0 ? [] : same.slice(Math.max(0, pivot - 3), pivot + 4);
    var selected = [], seen = new Set();
    named.concat(neighborhood).forEach(function (r) {
      var id = String(r.id || '');
      if (id && !seen.has(id)) { seen.add(id); selected.push(r); }
    });
    return {rows: selected, total: all.size, omitted: Math.max(0, all.size - selected.length), matching_file_total: same.length};
  }
  function createRecorder(options) {
    options = options || {};
    var retention = options.retention_ms || RETENTION_MS;
    var eventLimit = options.events_limit || EVENTS_LIMIT, rowLimit = options.rows_limit || ROWS_LIMIT;
    var events = [], rows = new Map(), droppedEvents = 0, droppedRows = 0, latest = null;
    function trim(now) {
      while (events.length && events[0].last_ms < now - retention) events.shift();
      events.forEach(function (e) {
        while (e._points.length && e._points[0][0] < now - retention) e._points.shift();
        if (e._points.length) {
          e.first_ms = e._points[0][0]; e.samples = e._points.length;
          e.audio.position_start_s = e._points[0][1];
        }
      });
      while (events.length > eventLimit) { events.shift(); droppedEvents += 1; }
    }
    function observe(sample, records) {
      var at = Number(sample.at_ms), audio = sample.audio || {};
      var event = {first_ms: at, last_ms: at, samples: 1,
        highlight_id: String(sample.highlight_id || ''), active_id: String(sample.active_id || ''),
        document_revision: String(sample.document_revision || ''), element_index: number(sample.element_index),
        block: number(sample.block), ord: number(sample.ord), scroll_top_px: number(sample.scroll_top_px),
        lit_top_px: number(sample.lit_top_px), follow: !!sample.follow, paused: !!sample.paused,
        /* [#1189] the resolver's decision at this sample: how the mark was placed */
        mark: String(sample.mark || ''), road: String(sample.road || ''), sync: String(sample.sync || ''),
        expected_id: String(sample.expected_id || ''), carried_id: String(sample.carried_id || ''),
        scroll_owner: String(sample.scroll_owner || ''),
        scroll_owner_at_ms: number(sample.scroll_owner_at_ms),
        live_segment: String(sample.live_segment || ''),
        highlighted_segment: String(sample.highlighted_segment || ''),
        nodes_transitioning: number(sample.nodes_transitioning),
        audio: {source: String(audio.source || 'unavailable'), file: String(audio.file || ''),
          position_start_s: number(audio.position_s), position_end_s: number(audio.position_s)}};
      var last = events[events.length - 1];
      var signature = JSON.stringify([event.highlight_id, event.active_id, event.document_revision,
        event.element_index, event.block, event.ord, event.scroll_top_px, event.lit_top_px,
        event.follow, event.paused, event.audio.source, event.audio.file,
        event.mark, event.road, event.expected_id, event.carried_id,
        event.scroll_owner, event.scroll_owner_at_ms, event.live_segment,
        event.highlighted_segment, event.nodes_transitioning]);   /* [#1189/#1277] */
      var seek = false;
      if (last && last.audio.position_end_s !== null && event.audio.position_end_s !== null) {
        var delta = event.audio.position_end_s - last.audio.position_end_s;
        seek = delta < -0.25 || delta > (at - last.last_ms) / 1000 + 1.5;
      }
      if (last && last._signature === signature && !seek) {
        last.last_ms = at; last.samples += 1; last.audio.position_end_s = event.audio.position_end_s;
        last._points.push([at, event.audio.position_end_s]);
      } else {
        event.audio_discontinuity = seek;
        event._signature = signature;
        event._points = [[at, event.audio.position_end_s]];
        events.push(event);
      }
      for (var i = 0; i < (records || []).length; i += 1) {
        var row = compactRow(records[i]);
        if (!row.id) continue;
        rows.delete(row.id); rows.set(row.id, row);
      }
      while (rows.size > rowLimit) { rows.delete(rows.keys().next().value); droppedRows += 1; }
      latest = copy(sample.snapshot || {});
      trim(at);
    }
    function capture(now, phase, incident, since, snapshot) {
      trim(now);
      var begin = since === undefined ? now - retention : since;
      var taken = events.filter(function (e) { return e.last_ms >= begin && e.first_ms <= now; }).map(function (e) {
        var out = copy(e), points = e._points.filter(function (p) { return p[0] >= begin && p[0] <= now; });
        delete out._signature; delete out._points;
        if (!points.length) return null;
        out.first_ms = points[0][0]; out.last_ms = points[points.length - 1][0]; out.samples = points.length;
        out.audio.position_start_s = points[0][1]; out.audio.position_end_s = points[points.length - 1][1];
        return out;
      }).filter(Boolean);
      var current = copy(snapshot || latest || {}), wanted = new Set();
      taken.forEach(function (e) {
        if (e.highlight_id) wanted.add(e.highlight_id); if (e.active_id) wanted.add(e.active_id);
        if (e.expected_id) wanted.add(e.expected_id); if (e.carried_id) wanted.add(e.carried_id);   /* [#1189] */
      });
      (current.nearby || []).forEach(function (r) { if (r.id) wanted.add(r.id); });
      (current.mapping_rows || []).forEach(function (id) { wanted.add(id); });
      var kept = {}, missing = 0, truncated = 0;
      wanted.forEach(function (id) { if (rows.has(id)) { kept[id] = copy(rows.get(id)); if (kept[id].text_truncated) truncated += 1; } else missing += 1; });
      return {schema_version: 2, phase: phase, incident_id: incident, captured_at_ms: now,
        window: {start_ms: begin, end_ms: now, retention_ms: retention, sample_ms: 250},
        events: taken, rows: kept, snapshot: current,
        bounds: {events_limit: eventLimit, rows_limit: rowLimit, dropped_events: droppedEvents,
          dropped_rows: droppedRows, missing_rows: missing, text_limit: TEXT_LIMIT, truncated_texts: truncated}};
    }
    return {observe: observe, capture: capture};
  }
  var api = {createRecorder: createRecorder, revision: revision, compactRow: compactRow, readAudio: readAudio,
    contextIndex: contextIndex, selectMappings: selectMappings};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.PineScriptDiagnostics = api;
})(typeof window !== 'undefined' ? window : globalThis);
