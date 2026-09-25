/* The live station-flow marquee and its 300-entry audit terminal. */
(function (root) {
  'use strict';

  var ID = 'pineConsoleLine';
  var SEEN_MAX = 300;
  var FLOW_POLL_MS = 2500;
  var SPEED_KEY = 'pineConsoleMarqueeSpeed';
  var SPEED_MIN = 0.2;
  var SPEED_MAX = 6;
  var seen = [];
  var keys = Object.create(null);
  var flowCursor = 0;
  var flowBusy = false;
  var flowTimer = null;
  var speed = readSpeed();
  var speedGesture = null;
  var suppressClickUntil = 0;
  var pendingMarqueeRows = null;

  function clampSpeed(value) {
    value = Number(value);
    return isFinite(value) ? Math.max(SPEED_MIN, Math.min(SPEED_MAX, value)) : 1;
  }

  function readSpeed() {
    try { return clampSpeed(root.localStorage.getItem(SPEED_KEY) || 1); }
    catch (err) { return 1; }
  }

  function saveSpeed() {
    try { root.localStorage.setItem(SPEED_KEY, String(speed)); }
    catch (err) { /* a locked profile still gets the live adjustment */ }
  }

  function applySpeed(track) {
    if (!track) return;
    var usedAnimation = false;
    try {
      var animations = track.getAnimations ? track.getAnimations() : [];
      if (animations.length && typeof animations[0].updatePlaybackRate === 'function') {
        animations[0].updatePlaybackRate(speed);
        usedAnimation = true;
      }
    } catch (err) { /* duration fallback below */ }
    if (!usedAnimation) track.style.animationDuration = (70 / speed) + 's';
    var viewport = track.parentNode;
    if (viewport) {
      viewport.title = 'Station audit - ' + speed.toFixed(1) + 'x';
      viewport.setAttribute('aria-valuetext', speed.toFixed(1) + ' times speed');
    }
  }

  function wireSpeed(bar) {
    var viewport = bar && bar.querySelector('.pine-console-viewport');
    if (!viewport || viewport.__pineSpeedWired) return;
    viewport.__pineSpeedWired = true;

    viewport.addEventListener('pointerdown', function (event) {
      if (event.button !== undefined && event.button !== 0) return;
      speedGesture = {id: event.pointerId, x: event.clientX,
        base: speed, moved: false};
      try { viewport.setPointerCapture(event.pointerId); } catch (err) { /* fine */ }
    });
    viewport.addEventListener('pointermove', function (event) {
      if (!speedGesture || (event.pointerId !== undefined
          && speedGesture.id !== undefined && event.pointerId !== speedGesture.id)) return;
      var dx = Number(event.clientX) - speedGesture.x;
      if (!speedGesture.moved && Math.abs(dx) < 7) return;
      speedGesture.moved = true;
      var width = Math.max(160, Number(viewport.clientWidth) || 600);
      speed = clampSpeed(speedGesture.base * Math.exp(-dx / width * 2.2));
      applySpeed(viewport.querySelector('.pine-console-track'));
      event.preventDefault();
      event.stopPropagation();
    });
    function finishSpeed(event) {
      if (!speedGesture) return;
      var moved = speedGesture.moved;
      speedGesture = null;
      try { viewport.releasePointerCapture(event.pointerId); } catch (err) { /* fine */ }
      if (!moved) return;
      saveSpeed();
      suppressClickUntil = Date.now() + 400;
      event.preventDefault();
      event.stopPropagation();
    }
    viewport.addEventListener('pointerup', finishSpeed);
    viewport.addEventListener('pointercancel', finishSpeed);
  }

  function el() { return document.getElementById(ID); }

  function normalizeActivity(row) {
    if (!row) return null;
    var stage = String(row.stage || '').trim();
    var detail = String(row.detail || row.text || '').trim();
    if (!stage && !detail) return null;
    return {stage: stage || 'station', detail: detail, at: Number(row.at) || 0,
      line: row.line || '', text: row.text || ''};
  }

  function latest(state) {
    var rows = (state && state.activity_log) || [];
    for (var i = rows.length - 1; i >= 0; i -= 1) {
      var row = normalizeActivity(rows[i]);
      if (row) return row;
    }
    return null;
  }

  function normalizeFlow(row) {
    if (!row) return null;
    return {id: row.id, stage: String(row.node || 'station'),
      detail: String(row.summary || ''), at: Number(row.at) || 0,
      status: String(row.status || ''), _flow: row};
  }

  function keyOf(row) {
    if (row && row.id !== undefined && row.id !== null) return 'flow:' + row.id;
    return 'activity:' + String(row && row.at || 0) + ':'
      + String(row && row.stage || '') + ':' + String(row && row.detail || '');
  }

  function remember(row) {
    if (!row) return false;
    var key = keyOf(row);
    if (keys[key]) return false;
    keys[key] = true;
    seen.push(row);
    seen.sort(function (a, b) { return (Number(a.at) || 0) - (Number(b.at) || 0); });
    while (seen.length > SEEN_MAX) {
      var gone = seen.shift();
      delete keys[keyOf(gone)];
    }
    return true;
  }

  function history() { return seen.slice().reverse(); }

  function icon(mark, label) {
    try {
      if (typeof root.pineIcon === 'function') return root.pineIcon(mark, label) || '';
    } catch (err) { /* text fallback */ }
    return '';
  }

  function mount() {
    if (el()) return el();
    var bar = document.createElement('div');
    bar.id = ID;
    bar.className = 'pine-console';
    bar.setAttribute('aria-label', 'Live station audit');
    bar.innerHTML = '<i class="pine-console-dot"></i>'
      + '<button class="pine-console-audit" type="button" title="Open the detailed audit log"'
      + ' aria-label="Open the detailed audit log"><em>AUDIT</em><span>waiting for the station journal</span></button>'
      + '<button class="pine-console-change" type="button" title="Open Pine Box changelog"'
      + ' aria-label="Open Pine Box changelog">i</button>'
      + '<div class="pine-console-viewport"><div class="pine-console-track"></div></div>'
      + '<button class="pine-console-more" type="button" title="Open the last 300 audit events"'
      + ' aria-label="Open the last 300 audit events">'
      + (icon('c:terminal', 'Open audit terminal') || '&gt;_') + '</button>';
    document.body.appendChild(bar);
    wireSpeed(bar);
    var track = bar.querySelector('.pine-console-track');
    if (track) track.addEventListener('animationiteration', function () {
      if (!pendingMarqueeRows) return;
      var rows = pendingMarqueeRows;
      pendingMarqueeRows = null;
      fillMarquee(track, rows);
      applySpeed(track);
    });
    bar.addEventListener('click', function (event) {
      event.stopPropagation();
      if (Date.now() < suppressClickUntil) {
        event.preventDefault();
        return;
      }
      if (event.target && event.target.closest && event.target.closest('.pine-console-change')) {
        if (root.PineChangeLog) root.PineChangeLog.open();
        return;
      }
      if (event.target && event.target.closest && event.target.closest('.pine-console-audit')) {
        openList(bar);
        return;
      }
      var entry = event.target && event.target.closest
        ? event.target.closest('.pine-console-entry') : null;
      if (entry && entry.__row) {
        if (root.PineConsoleTrace) root.PineConsoleTrace.open(entry.__row);
        return;
      }
      openList(bar);
    });
    return bar;
  }

  function entryNode(row) {
    var item = document.createElement('button');
    item.type = 'button';
    item.className = 'pine-console-entry';
    item.__row = row;
    var when = row.at ? new Date(Number(row.at) * 1000).toLocaleTimeString() : '';
    item.innerHTML = '<time></time><b></b><span></span>';
    item.querySelector('time').textContent = when;
    item.querySelector('b').textContent = row.stage || 'station';
    item.querySelector('span').textContent = row.detail || '';
    item.title = (row.stage || 'station') + ': ' + (row.detail || '');
    return item;
  }

  function paintMarquee() {
    var bar = el() || mount();
    var track = bar.querySelector('.pine-console-track');
    if (!track) return;
    var rows = seen.slice(-24);
    var audit = bar.querySelector('.pine-console-audit span');
    var current = rows[rows.length - 1];
    if (audit && current) {
      audit.textContent = String(current.stage || 'station') + ': ' + String(current.detail || '');
      audit.parentNode.title = 'Open the detailed audit log - ' + audit.textContent;
    }
    /* Audit polls arrive every 2.5 seconds. Rebuilding here used to reset
       the compositor animation on every poll, producing the visible hitch.
       Install the newest snapshot at the animation seam instead. */
    if (track.classList.contains('running')) {
      pendingMarqueeRows = rows;
      return;
    }
    fillMarquee(track, rows);
    track.classList.add('running');
    applySpeed(track);
  }

  function fillMarquee(track, rows) {
    track.replaceChildren();
    if (!rows.length) {
      track.appendChild(entryNode({stage: 'idle', detail: 'waiting for the station journal', at: 0}));
      return;
    }
    for (var copy = 0; copy < 2; copy += 1) {
      for (var i = 0; i < rows.length; i += 1) track.appendChild(entryNode(rows[i]));
    }
  }

  function paint(state) {
    var rows = (state && state.activity_log) || [];
    var changed = false;
    for (var i = 0; i < rows.length; i += 1) {
      changed = remember(normalizeActivity(rows[i])) || changed;
    }
    if (changed || !el()) {
      paintMarquee();
      var bar = el();
      if (bar) {
        bar.classList.remove('pulse');
        void bar.offsetWidth;
        bar.classList.add('pulse');
      }
    }
  }

  function flowGet(path) {
    try {
      if (root.pineDesktop && typeof root.pineDesktop.get === 'function') {
        return Promise.resolve(root.pineDesktop.get(path));
      }
    } catch (err) { /* same-origin fallback */ }
    var headers = {};
    try {
      var key = root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || '';
      if (key) headers.Authorization = 'Bearer ' + key;
    } catch (err) { /* read-only deployments may not need one */ }
    return root.fetch(path, {headers: headers, cache: 'no-store'}).then(function (res) {
      if (!res.ok) throw new Error('station flow ' + res.status);
      return res.json();
    });
  }

  function syncFlow(full) {
    if (flowBusy) return Promise.resolve(null);
    flowBusy = true;
    var path = '/api/dj/flow?lean=1&limit=' + (full ? '300' : '80');
    if (!full && flowCursor) path += '&after=' + encodeURIComponent(String(flowCursor));
    return flowGet(path).then(function (got) {
      flowBusy = false;
      var rows = (got && got.events) || [];
      var changed = false;
      for (var i = 0; i < rows.length; i += 1) {
        changed = remember(normalizeFlow(rows[i])) || changed;
      }
      if (got && got.cursor) flowCursor = Math.max(flowCursor, Number(got.cursor) || 0);
      if (changed) paintMarquee();
      return got;
    }, function () { flowBusy = false; return null; });
  }

  function renderList(list) {
    var body = list.querySelector('.pine-console-list-body');
    var count = list.querySelector('.pine-console-list-count');
    if (!body) return;
    body.replaceChildren();
    var rows = history().slice(0, SEEN_MAX);
    if (count) count.textContent = rows.length + ' / ' + SEEN_MAX;
    rows.forEach(function (row) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'pine-console-item';
      var when = row.at ? new Date(Number(row.at) * 1000).toLocaleTimeString() : '';
      item.innerHTML = '<i></i><b></b><span></span>';
      item.querySelector('i').textContent = when;
      item.querySelector('b').textContent = row.stage || 'station';
      item.querySelector('span').textContent = row.detail || '';
      item.addEventListener('click', function (event) {
        event.stopPropagation();
        list.remove();
        if (root.PineConsoleTrace) root.PineConsoleTrace.open(row);
      });
      body.appendChild(item);
    });
  }

  function openList(bar) {
    var old = document.getElementById('pineConsoleList');
    if (old) { old.remove(); return; }
    var list = document.createElement('div');
    list.id = 'pineConsoleList';
    list.className = 'pine-console-list';
    list.setAttribute('role', 'dialog');
    list.setAttribute('aria-label', 'Station audit terminal');
    list.setAttribute('data-pine-drag', '');
    list.innerHTML = '<div class="pine-console-list-head" data-pine-drag-handle>'
      + '<b>Station audit</b><span class="pine-console-list-count"></span>'
      + '<button type="button" class="pine-console-list-close" aria-label="Close" title="Close">x</button>'
      + '</div><div class="pine-console-list-body"></div>';
    list.querySelector('.pine-console-list-close').addEventListener('click', function (event) {
      event.stopPropagation();
      list.remove();
    });
    document.body.appendChild(list);
    renderList(list);
    syncFlow(true).then(function () { if (list.isConnected) renderList(list); });
    if (root.PineDismiss) root.PineDismiss.watch(list, function () { list.remove(); }, [bar]);
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function start() {
    mount();
    syncFlow(true);
    if (!flowTimer) {
      flowTimer = root.setInterval(function () { syncFlow(false); }, FLOW_POLL_MS);
      if (flowTimer && typeof flowTimer.unref === 'function') flowTimer.unref();
    }
    var feed = root.PineStationFeed;
    if (feed && typeof feed.subscribe === 'function') {
      return feed.subscribe(function (payload) {
        paint((payload && payload.station) || payload || {});
      });
    }
    return function () {};
  }

  root.PineConsoleLine = {start: start, paint: paint, latest: latest,
    mount: mount, history: history, sync: syncFlow, open: openList,
    speed: function () { return speed; }};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineConsoleLine;
})(typeof window !== 'undefined' ? window : globalThis);
