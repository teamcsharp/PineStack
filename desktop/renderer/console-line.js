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
    // A full snapshot must not reinsert history already outside the retained window.
    if (seen.length >= SEEN_MAX && Number(row.at || 0) <= Number(seen[0].at || 0)) return false;
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

  function paintOrchestratorButton(bar) {
    bar = bar || el();
    if (!bar) return;
    var button = bar.querySelector('.pine-console-orchestrator');
    if (!button) return;
    var hidden = false;
    try {
      hidden = !!(root.PineOrchGlass && typeof root.PineOrchGlass.isDotHidden === 'function'
        && root.PineOrchGlass.isDotHidden());
    } catch (err) { hidden = false; }
    button.hidden = false;                      /* [plbar] the face is always there */
    var t = hidden ? 'Restore the orchestrator control' : 'Open the orchestrator';
    if (button.title !== t) { button.title = t; button.setAttribute('aria-label', t); }
  }

  function paintTalkRestoreButton(bar) {
    bar = bar || el();
    if (!bar) return;
    var button = bar.querySelector('.pine-console-talk-dot');
    if (!button) return;
    var talk = root.PineTalkDot;
    button.hidden = !(talk && typeof talk.enabled === 'function' && talk.enabled()
      && typeof talk.collapsed === 'function' && talk.collapsed());
  }

  /* [station-pulse] "a small loading bar above the base status bar showing the
     health of the station and how much of it is being grabbed out of the bank
     database versus being rendered in real time ... relaxing ... more full ...
     a single line scrolling marquee giving up to date status information on the
     current status of the station and how the orchestrator is handing the rooms
     and the tasks with the broadcast." /api/station/pulse every five seconds:
     the fill is the pressure (empty = the hour is in the bank, full = everything
     made live and locked up), eased so it visibly relaxes and tightens; the
     marquee is the station's own lines, swapped in only when a pass ends so it
     never jumps under the eye. */
  var PULSE_ID = 'pinePulse';
  var pulseTimer = 0, pulseText = '', pulseNext = '';
  function pulseMount() {
    if (document.getElementById(PULSE_ID)) return;
    var p = document.createElement('div');
    p.id = PULSE_ID;
    p.className = 'pine-pulse';
    p.innerHTML = '<div class="pine-pulse-bar" role="meter" aria-valuemin="0" aria-valuemax="100"'
      + ' aria-label="Station pressure: the bank against rendering live"><i class="pine-pulse-fill"></i></div>'
      + '<div class="pine-pulse-line"><div class="pine-pulse-track"></div></div>';
    document.body.appendChild(p);
    pulseSeat(p);
    var track = p.querySelector('.pine-pulse-track');
    track.addEventListener('animationiteration', function () {
      if (pulseNext && pulseNext !== pulseText) pulsePaintText(track, pulseNext);
    });
    pulseRead();
    if (!pulseTimer) pulseTimer = root.setInterval(function () {
      try { if (document.hidden) return; } catch (err) { /* read anyway */ }
      pulseRead();
    }, 5000);
  }
  function pulseSeat(p) {                      /* on top of the strip, however tall it is */
    var cb = el();
    if (p && cb && cb.offsetHeight) p.style.bottom = cb.offsetHeight + 'px';
    /* [chrome-bottom] "the last item in the list ... is being cut off": the
       views that set their own padding (Script, Listen, Presentation) kept
       the strip's old 26px and the marquee covered their last row. Both
       strips' real height, for every view to pad by. */
    var tall = (cb ? cb.offsetHeight : 0) + (p ? p.offsetHeight : 0);
    if (tall) document.documentElement.style.setProperty('--pine-chrome-bottom', tall + 'px');
  }
  function pulsePaintText(track, text) {
    pulseText = text;
    track.textContent = '';
    for (var k = 0; k < 2; k += 1) {                 /* two copies: the loop has no seam */
      var s = document.createElement('span');
      s.textContent = text + '     \u2022     ';
      track.appendChild(s);
    }
    var secs = Math.max(30, Math.round(text.length / 7));
    track.style.animationDuration = secs + 's';
  }
  function pulseRead() {
    Promise.resolve(flowGet('/api/station/pulse')).then(function (v) {
      var p = document.getElementById(PULSE_ID);
      if (!p || !v || typeof v.pressure !== 'number') return;
      pulseSeat(p);
      var pct = Math.round(Math.max(0, Math.min(1, v.pressure)) * 100);
      var bar = p.querySelector('.pine-pulse-bar');
      var fill = p.querySelector('.pine-pulse-fill');
      fill.style.width = Math.max(2, pct) + '%';
      p.setAttribute('data-state', String(v.state || ''));
      bar.setAttribute('aria-valuenow', String(pct));
      var parts = v.parts || {};
      var n = v.numbers || {};
      bar.title = 'Station pressure ' + pct + '% - ' + (v.state || '') + '. '
        + Math.round((v.banked || 0) * 100) + '% of the next hour is in the bank. '
        + 'Still to make: ' + Math.round((parts.bank || 0) * 100) + '% of the hour; '
        + 'made live: ' + Math.round((parts.live || 0) * 100) + '% of its lines; '
        + (n.voice_queue || 0) + ' line(s) waiting for a voice; '
        + (n.writers_waiting || 0) + ' writer(s) waiting, ' + (n.deferred || 0) + ' deferred.';
      var text = (v.marquee || []).join('     \u2022     ');
      var track = p.querySelector('.pine-pulse-track');
      if (!pulseText) pulsePaintText(track, text);
      else pulseNext = text;
      p.querySelector('.pine-pulse-line').title = (v.marquee || []).join('\n');
    }, function () { /* the next read */ });
  }

  /* [tip-marquee] "This text should be scrolling in the marquee as well. And
     I should be able to tap on it to bring up a pop up to see additional
     information on it ... But also it is covering the UI." A hover tip is not
     a box over the page any more: it takes the status marquee's line (TIP),
     scrolls there when it is longer than the line, stays fifteen seconds
     after the pointer leaves so it can be reached, and a tap opens the whole
     of it - its full words, what the thing is, where it lives, its line id -
     with a way to open the thing itself. renderer.js hands its tips here. */
  var TIP_KEEP_MS = 15000;
  var tipNow = {text: '', el: null, timer: 0};
  function tipLane() {
    var p = document.getElementById(PULSE_ID);
    if (!p) return null;
    var tip = p.querySelector('.pine-pulse-tip');
    if (tip) return tip;
    tip = document.createElement('button');
    tip.type = 'button';
    tip.className = 'pine-pulse-tip';
    tip.hidden = true;
    tip.setAttribute('aria-label', 'Tip - tap for the whole of it');
    tip.innerHTML = '<em>TIP</em><span class="pine-pulse-tip-view"><span class="pine-pulse-tip-track"></span></span>';
    tip.addEventListener('click', function (ev) { ev.stopPropagation(); tipOpen(); });
    p.appendChild(tip);
    return tip;
  }
  function tipShow(text, target) {
    var tip = tipLane();
    if (!tip) return false;
    text = String(text || '').replace(/\s+/g, ' ').trim();
    if (!text) return false;
    if (tipNow.timer) { root.clearTimeout(tipNow.timer); tipNow.timer = 0; }
    tipNow.text = text;
    tipNow.el = target || null;
    var view = tip.querySelector('.pine-pulse-tip-view');
    var track = tip.querySelector('.pine-pulse-tip-track');
    track.classList.remove('pine-pulse-tip-run');
    track.textContent = text;
    tip.hidden = false;
    if (track.scrollWidth > view.clientWidth + 4) {          /* longer than the line: it scrolls */
      track.textContent = '';
      for (var k = 0; k < 2; k += 1) {
        var s = document.createElement('span');
        s.textContent = text + '     •     ';
        track.appendChild(s);
      }
      track.style.animationDuration = Math.max(8, Math.round(text.length / 9)) + 's';
      track.classList.add('pine-pulse-tip-run');
    }
    return true;
  }
  function tipRelease() {                        /* the pointer left: keep it long enough to reach */
    if (!tipNow.text || tipNow.timer) return;
    tipNow.timer = root.setTimeout(function () {
      tipNow.timer = 0;
      var tip = tipLane();
      if (tip && !tip.matches(':hover') && !document.querySelector('.pine-tip-pop')) tip.hidden = true;
      else tipRelease();
    }, TIP_KEEP_MS);
  }
  function tipWhat(el) {
    var raw = String((el.getAttribute && el.getAttribute('class')) || '').split(/\s+/)[0] || el.id || el.tagName || '';
    var w = String(raw).replace(/^(sp|va|pine|pv|s3|sfx|pl|rt|mv|pmi|pav|gs|tf|cf|lb)-/, '')
      .replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[-_]+/g, ' ').trim().toLowerCase();
    return w ? w.charAt(0).toUpperCase() + w.slice(1) : '';
  }
  function tipOpen() {
    var old = document.querySelector('.pine-tip-pop');
    if (old) old.remove();
    var el = tipNow.el;
    var live = !!(el && document.body.contains(el));
    var pop = document.createElement('div');
    pop.className = 'pine-tip-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'About this');
    var head = document.createElement('b');
    head.textContent = live ? (tipWhat(el) || 'About this') : 'About this';
    pop.appendChild(head);
    var said = document.createElement('p');
    said.className = 'pine-tip-pop-text';
    said.textContent = tipNow.text;
    pop.appendChild(said);
    if (live) {
      var full = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (full && full !== tipNow.text && full.length > 3) {
        var all = document.createElement('p');
        all.className = 'pine-tip-pop-full';
        all.textContent = full;
        pop.appendChild(all);
      }
      var facts = [];
      var lineAt = el.closest && el.closest('[data-line]');
      if (lineAt) facts.push('line #' + String(lineAt.getAttribute('data-line')).slice(0, 12));
      var host = el.closest && el.closest('.pine-view-host, [id]');
      if (host && host !== el && host.id) facts.push('in ' + host.id);
      if (el.id) facts.push('#' + el.id);
      if (facts.length) {
        var f = document.createElement('i');
        f.className = 'pine-tip-pop-facts';
        f.textContent = facts.join('  ·  ');
        pop.appendChild(f);
      }
      var go = document.createElement('button');
      go.type = 'button';
      go.className = 'pine-tip-pop-go';
      go.textContent = 'Open it';
      go.title = 'Do what tapping it would do';
      go.addEventListener('click', function () {
        pop.remove();
        try { el.click(); } catch (err) { /* it has gone */ }
      });
      pop.appendChild(go);
    }
    document.body.appendChild(pop);
    if (typeof root.pineCloseX === 'function') {
      try { root.pineCloseX(pop, function () { pop.remove(); }, {label: 'Close'}); } catch (err) { /* Escape still closes */ }
    }
  }
  root.PinePulseTip = {show: tipShow, release: tipRelease, open: tipOpen};

  function mount() {
    if (el()) return el();
    var bar = document.createElement('div');
    bar.id = ID;
    bar.className = 'pine-console';
    bar.setAttribute('aria-label', 'Live station audit');
    bar.innerHTML = '<i class="pine-console-dot"></i>'
      + '<button class="pine-console-audit" type="button" title="Open the detailed audit log"'
      + ' aria-label="Open the detailed audit log"><em>AUDIT</em><span>waiting for the station journal</span></button>'
      + '<button class="pine-console-gallery" type="button"'
      + ' title="Pine Box Gallery" aria-label="Pine Box Gallery">'
      + (icon('c:image', 'Pine Box Gallery') || 'G') + '</button>'
      + '<button class="pine-console-orchestrator" type="button" hidden'
      + ' title="Restore the orchestrator control" aria-label="Restore the orchestrator control">'
      + (icon('c:bot', 'Restore orchestrator') || '') + '</button>'
      + '<button class="pine-console-talk-dot" type="button" hidden'
      + ' title="Restore voice control" aria-label="Restore voice control">'
      + (icon('c:microphone', 'Restore voice control') || 'V') + '</button>'
      + '<button class="pine-console-change" type="button" title="Open Pine Box changelog"'
      + ' aria-label="Open Pine Box changelog">i</button>'
      + '<div class="pine-console-viewport"><div class="pine-console-track"></div></div>'
      + '<button class="pine-console-more" type="button" title="Open the last 300 audit events"'
      + ' aria-label="Open the last 300 audit events">'
      + (icon('c:terminal', 'Open audit terminal') || '&gt;_') + '</button>';
    document.body.appendChild(bar);
    pulseMount();                              /* [station-pulse] the bar and the marquee above it */
    wireSpeed(bar);
    paintTalkRestoreButton(bar);
    if (root.addEventListener && !bar.__pineTalkRestoreWired) {
      bar.__pineTalkRestoreWired = true;
      root.addEventListener('pine-talk-dot-change', function () {
        paintTalkRestoreButton(bar);
      });
    }
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
      if (event.target && event.target.closest && event.target.closest('.pine-console-gallery')) {
        if (root.PineAdViewer) root.PineAdViewer.openGallery();
        return;
      }
      if (event.target && event.target.closest && event.target.closest('.pine-console-orchestrator')) {
        /* [plbar] tucked away: bring the face back; face up: open the orchestrator */
        var og = root.PineOrchGlass;
        if (og && typeof og.isDotHidden === 'function' && !og.isDotHidden()
            && typeof og.toggle === 'function') og.toggle();
        else if (og && typeof og.undot === 'function') og.undot();
        paintOrchestratorButton(bar);
        return;
      }
      if (event.target && event.target.closest && event.target.closest('.pine-console-talk-dot')) {
        if (root.PineTalkDot && typeof root.PineTalkDot.restoreFromBar === 'function') {
          root.PineTalkDot.restoreFromBar();
          paintTalkRestoreButton(bar);
          var dot = document.getElementById('pineTalkDot');
          if (dot && typeof dot.focus === 'function') dot.focus();
        }
        return;
      }
      if (event.target && event.target.closest && event.target.closest('.pine-console-audit')) {
        openList(bar);
        return;
      }
      var entry = event.target && event.target.closest
        ? event.target.closest('.pine-console-entry') : null;
      if (entry && entry.__row) {
        if (outlOpenRow(entry.__row)) return;          /* [outl-audit-marquee] an OUTLANDISH row opens its line */
        if (root.PineConsoleTrace) root.PineConsoleTrace.open(entry.__row);
        return;
      }
      openList(bar);
    });
    paintOrchestratorButton(bar);
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
        if (outlOpenRow(row)) return;                  /* [outl-audit-terminal] */
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

  /* [s3-account] THE UNTRACED ALARM. An item that airs with no System 3 origin
     airs (the air is never held) and lands on the Untraced list; this button
     before the gallery shows while the list is not empty (24 h) and opens it:
     the code paths that aired them, each item's origin chain on tap, and the
     24 h coverage by road. Polls /api/system3/untraced every 30 s. */
  var UNTRACED_POLL_MS = 30000;
  var untraced = {count: 0, total: 0, items: [], by: [], timer: null, busy: false};

  function untracedStyle() {
    if (typeof document === 'undefined' || document.getElementById('pineUntracedStyle')) return;
    var s = document.createElement('style');
    s.id = 'pineUntracedStyle';
    s.textContent = '.pine-console-untraced{display:inline-flex;align-items:center;gap:3px;color:#e8a33d;'
      + 'background:none;border:0;padding:0 6px;cursor:pointer;font:600 11px/1 system-ui,sans-serif}'
      + '.pine-console-untraced[hidden]{display:none}.pine-console-untraced svg{width:14px;height:14px}'
      + '#pineUntracedList .pine-untraced-sum{padding:6px 10px;opacity:.85}'
      + '#pineUntracedList .pine-untraced-row{display:block;width:100%;text-align:left;padding:6px 10px;'
      + 'border:0;border-top:1px solid rgba(127,127,127,.25);background:none;color:inherit;font:inherit;cursor:pointer}'
      + '#pineUntracedList .pine-untraced-row b{margin-right:6px}'
      + '#pineUntracedList .pine-untraced-chain{padding:4px 10px 8px 22px;font-size:12px;opacity:.9}'
      + '#pineUntracedList .pine-untraced-chain div{padding:1px 0}';
    (document.head || document.body).appendChild(s);
  }

  function untracedButton(bar) {
    bar = bar || el();
    if (!bar || !bar.querySelector) return null;
    var b = bar.querySelector('.pine-console-untraced');
    if (b) return b;
    untracedStyle();
    b = document.createElement('button');
    b.type = 'button';
    b.className = 'pine-console-untraced';
    b.hidden = true;
    b.innerHTML = (icon('c:warning--alt', 'Untraced air') || '!') + '<span class="pine-console-untraced-n"></span>';
    b.addEventListener('click', function (event) {
      event.stopPropagation();
      event.preventDefault();
      untracedOpen(bar);
    });
    bar.insertBefore(b, bar.querySelector('.pine-console-gallery') || bar.firstChild);
    untracedPaint();
    return b;
  }

  function untracedPaint() {
    var b = untracedButton();
    if (!b) return;
    b.hidden = !(untraced.count > 0);
    var n = b.querySelector('.pine-console-untraced-n');
    if (n) n.textContent = untraced.count > 99 ? '99+' : String(untraced.count || '');
    var t = untraced.count + ' item' + (untraced.count === 1 ? '' : 's')
      + ' aired in the last 24 h with no System 3 origin - open the Untraced list';
    if (b.title !== t) { b.title = t; b.setAttribute('aria-label', t); }
  }

  function untracedPoll() {
    if (untraced.busy) return Promise.resolve();
    untraced.busy = true;
    var done = function () { untraced.busy = false; };
    return flowGet('/api/system3/untraced?hours=24&limit=60').then(function (got) {
      got = got || {};
      untraced.count = Number(got.count) || 0;
      untraced.total = Number(got.items_total) || 0;
      untraced.items = got.items || [];
      untraced.by = got.by_path || [];
      untracedPaint();
      var list = document.getElementById('pineUntracedList');
      if (list) untracedRender(list);
    }).then(done, done);
  }

  function untracedLine(text, cls) {
    var d = document.createElement('div');
    if (cls) d.className = cls;
    d.textContent = text;
    return d;
  }

  function untracedChainText(n) {
    var keys = {air: ['aired', 'seconds'], script: ['block', 'ord', 'sid'], road: ['label', 'who'],
      conversation: ['conversation_id', 'turn_id'], roll: ['table', 'picked', 'dice', 'of'],
      store: ['kind', 'folder', 'db', 'pool', 'product', 'key', 'file'],
      forced: ['road', 'trigger', 'by'], rogue: ['producer', 'why', 'path']}[n.node] || [];
    var out = [];
    keys.forEach(function (k) { if (n[k] !== undefined && n[k] !== null && n[k] !== '') out.push(String(n[k])); });
    return (n.node || '') + ': ' + out.join(' - ');
  }

  function untracedRender(list) {
    var body = list.querySelector('.pine-console-list-body');
    var count = list.querySelector('.pine-console-list-count');
    if (count) count.textContent = untraced.count + ' of ' + untraced.total + ' in 24 h';
    if (!body) return;
    body.textContent = '';
    var sum = untracedLine(untraced.count
      ? 'These aired with no System 3 origin. Each is a road to bring under System 3.'
      : 'Nothing untraced in the last 24 hours: every item traced to a roll or a named forced node.',
      'pine-untraced-sum');
    body.appendChild(sum);
    untraced.by.slice(0, 6).forEach(function (p) {
      body.appendChild(untracedLine(p.count + ' x ' + (p.producer || 'unknown') + ' (' + (p.road || '') + ')', 'pine-untraced-sum'));
    });
    var cov = untracedLine('coverage: reading...', 'pine-untraced-sum');
    body.appendChild(cov);
    flowGet('/api/system3/coverage?hours=24').then(function (rep) {
      var t = (rep && rep.totals) || {};
      cov.textContent = 'coverage 24 h: ' + (t.traced_pct == null ? '-' : t.traced_pct + '%') + ' traced - '
        + (t.rolled || 0) + ' rolled, ' + (t.forced || 0) + ' forced, ' + (t.rogue || 0) + ' rogue of '
        + (t.items || 0) + ' items. The daily report: /system3-coverage';
    }, function () { cov.textContent = 'coverage: not available'; });
    untraced.items.forEach(function (it) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'pine-untraced-row';
      var when = '';
      try { when = new Date(Number(it.air_at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
      catch (err) { when = ''; }
      var b = document.createElement('b');
      b.textContent = when + ' ' + (it.road || '');
      row.appendChild(b);
      row.appendChild(document.createTextNode((it.producer || 'unknown') + ' - ' + String(it.text || '').slice(0, 120)));
      row.addEventListener('click', function (event) {
        event.stopPropagation();
        var open = row.nextSibling && row.nextSibling.className === 'pine-untraced-chain' ? row.nextSibling : null;
        if (open) { open.remove(); return; }
        var chain = document.createElement('div');
        chain.className = 'pine-untraced-chain';
        chain.textContent = 'reading the origin ledger...';
        body.insertBefore(chain, row.nextSibling);
        flowGet('/api/system3/origin/' + encodeURIComponent(it.line_id)).then(function (got) {
          chain.textContent = '';
          chain.appendChild(untracedLine((got && got.verdict || '') + ' - ' + (got && got.why || '')));
          var rounds = 0;
          ((got && got.nodes) || []).forEach(function (n) {
            if (n.node === 'roll' && n.scope === 'round') { rounds += 1; return; }
            chain.appendChild(untracedLine(untracedChainText(n)));
          });
          if (rounds) chain.appendChild(untracedLine(rounds + ' roll(s) on the round - open the line in System 3 for them'));
        }, function () { chain.textContent = 'no origin record for ' + it.line_id; });
      });
      body.appendChild(row);
    });
  }

  function untracedOpen(bar) {
    if (typeof document === 'undefined') return;
    var old = document.getElementById('pineUntracedList');
    if (old) { old.remove(); return; }
    var list = document.createElement('div');
    list.id = 'pineUntracedList';
    list.className = 'pine-console-list';
    list.setAttribute('role', 'dialog');
    list.setAttribute('aria-label', 'Untraced air');
    list.setAttribute('data-pine-drag', '');
    list.innerHTML = '<div class="pine-console-list-head" data-pine-drag-handle>'
      + '<b>Untraced air</b><span class="pine-console-list-count"></span>'
      + '<button type="button" class="pine-console-list-close" aria-label="Close" title="Close">x</button>'
      + '</div><div class="pine-console-list-body"></div>';
    list.querySelector('.pine-console-list-close').addEventListener('click', function (event) {
      event.stopPropagation();
      list.remove();
    });
    document.body.appendChild(list);
    untracedRender(list);
    untracedPoll();
    if (root.PineDismiss) root.PineDismiss.watch(list, function () { list.remove(); }, [bar || el()]);
  }

  function untracedStart() {
    if (typeof document === 'undefined') return;
    untracedButton();
    untracedPoll();
    if (!untraced.timer) {
      untraced.timer = root.setInterval(function () { untracedButton(); untracedPoll(); }, UNTRACED_POLL_MS);
      if (untraced.timer && typeof untraced.timer.unref === 'function') untraced.timer.unref();
    }
  }

  /* [outl-audit] THE OUTLANDISH REVIEW. The meter (outlandish.py) scores every
     aired line 0-100 and never filters it; a line at or above the audit
     threshold lands on the AUDIT line (station flow node "outlandish") and
     here: #code, seat, words, score, tags, whether a dispute followed (aired /
     planned but cut / none) and the SFX Guy's reaction. Filters, CSV/JSON
     export for the scientists, and a tap opens the line's popup. Polls
     /api/outlandish every 30 s. */
  var OUTL_POLL_MS = 30000;
  var outl = {count: 0, items: [], got: null, timer: null, busy: false, hours: 6, min: -1, tag: ''};

  function outlStyle() {
    if (typeof document === 'undefined' || document.getElementById('pineOutlStyle')) return;
    var s = document.createElement('style');
    s.id = 'pineOutlStyle';
    s.textContent = '.pine-console-outl{display:inline-flex;align-items:center;gap:3px;color:#ff6b8b;'
      + 'background:none;border:0;padding:0 6px;cursor:pointer;font:600 11px/1 system-ui,sans-serif}'
      + '.pine-console-outl svg{width:14px;height:14px}'
      + '#pineOutlList .pine-outl-ctl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:6px 10px}'
      + '#pineOutlList .pine-outl-ctl select,#pineOutlList .pine-outl-ctl input{font:inherit;max-width:9em}'
      + '#pineOutlList .pine-outl-ctl button{font:inherit;cursor:pointer}'
      + '#pineOutlList .pine-outl-sum{padding:4px 10px;opacity:.85;font-size:12px}'
      + '#pineOutlList .pine-outl-row{display:block;width:100%;text-align:left;padding:6px 10px;border:0;'
      + 'border-top:1px solid rgba(127,127,127,.25);background:none;color:inherit;font:inherit;cursor:pointer}'
      + '#pineOutlList .pine-outl-row b{display:inline-block;min-width:2.2em;color:#ff6b8b;margin-right:6px}'
      + '#pineOutlList .pine-outl-row i{opacity:.75;font-style:normal;margin-left:6px}'
      + '#pineOutlList .pine-outl-row span{display:block;opacity:.9;font-size:12px;margin-top:2px}';
    (document.head || document.body).appendChild(s);
  }

  function outlButton(bar) {
    bar = bar || el();
    if (!bar || !bar.querySelector) return null;
    var b = bar.querySelector('.pine-console-outl');
    if (b) return b;
    outlStyle();
    b = document.createElement('button');
    b.type = 'button';
    b.className = 'pine-console-outl';
    b.innerHTML = (icon('c:scales', 'OUTLANDISH review') || 'O') + '<span class="pine-console-outl-n"></span>';
    b.addEventListener('click', function (event) {
      event.stopPropagation();
      event.preventDefault();
      outlOpen(bar);
    });
    bar.insertBefore(b, bar.querySelector('.pine-console-gallery') || bar.firstChild);
    outlPaint();
    return b;
  }

  function outlPaint() {
    var b = outlButton();
    if (!b) return;
    var n = b.querySelector('.pine-console-outl-n');
    if (n) n.textContent = outl.count > 99 ? '99+' : String(outl.count || 0);
    var t = 'OUTLANDISH: ' + outl.count + ' aired line' + (outl.count === 1 ? '' : 's')
      + ' at or above the audit threshold in the last 6 h - open the review (measured, never filtered)';
    if (b.title !== t) { b.title = t; b.setAttribute('aria-label', t); }
  }

  function outlPath(hours, full) {
    return '/api/outlandish?hours=' + encodeURIComponent(String(hours)) + '&limit=' + (full ? '1000' : '80')
      + '&follow=' + (full ? '1' : '0') + (outl.min >= 0 && full ? '&min=' + encodeURIComponent(String(outl.min)) : '');
  }

  function outlPoll() {
    if (outl.busy) return Promise.resolve();
    outl.busy = true;
    var done = function () { outl.busy = false; };
    return flowGet(outlPath(6, false)).then(function (got) {
      outl.count = Number(got && got.count) || 0;
      outlPaint();
    }).then(done, done);
  }

  function outlOpenRow(row) {
    var f = row && row._flow;
    var d = f && f.details;
    if (!f || f.node !== 'outlandish' || !d || !d.line_id) return false;
    return outlOpenLine({line_id: d.line_id, text: d.text, who: d.who});
  }

  function outlOpenLine(it) {
    var line = {id: String(it.line_id || ''), said: String(it.text || ''), who: String(it.who || '')};
    if (!line.id) return false;
    try {
      if (root.PineLineActions && typeof root.PineLineActions.open === 'function') { root.PineLineActions.open(line); return true; }
    } catch (err) { /* the trace below */ }
    return false;
  }

  function outlFollowWord(f) {
    return f === 'aired' ? 'dispute aired' : f === 'planned_cut' ? 'dispute planned, cut' : f === 'none' ? 'no dispute' : '';
  }

  function outlCsv(items) {
    var q = function (v) { v = String(v == null ? '' : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var out = ['code,aired_utc,who,road,score,level,tags,cues,follow,reaction,text,line_id,conversation_id,turn_id'];
    items.forEach(function (r) {
      var rx = r.reaction || {};
      out.push([r.code, new Date(Number(r.at) * 1000).toISOString(), r.who, r.road, r.score, r.level,
        (r.tags || []).join('|'), (r.cues || []).map(function (c) { return c.label + ': ' + c.match; }).join('|'),
        r.follow || '', rx.label || '', r.text, r.line_id, r.conversation_id || '', r.turn_id || ''].map(q).join(','));
    });
    return out.join('\n') + '\n';
  }

  function outlSave(name, text, type) {
    try {
      var url = URL.createObjectURL(new Blob([text], {type: type}));
      var a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
    } catch (err) { /* nothing to save into here */ }
  }

  function outlRender(list) {
    var body = list.querySelector('.pine-console-list-body');
    var count = list.querySelector('.pine-console-list-count');
    var got = outl.got || {};
    var th = got.thresholds || {};
    var items = (got.items || []).filter(function (r) { return !outl.tag || (r.tags || []).indexOf(outl.tag) >= 0; });
    if (count) count.textContent = items.length + ' in ' + outl.hours + ' h';
    if (!body) return;
    body.textContent = '';
    var ctl = document.createElement('div');
    ctl.className = 'pine-outl-ctl';
    var hours = document.createElement('select');
    hours.setAttribute('aria-label', 'hours');
    [1, 6, 24, 72].forEach(function (h) {
      var o = document.createElement('option');
      o.value = String(h); o.textContent = 'last ' + h + ' h'; o.selected = h === outl.hours;
      hours.appendChild(o);
    });
    hours.addEventListener('change', function () { outl.hours = Number(hours.value) || 6; outlLoad(list); });
    var min = document.createElement('input');
    min.type = 'number'; min.min = '0'; min.max = '100'; min.step = '5';
    min.value = String(outl.min >= 0 ? outl.min : (got.floor != null ? got.floor : ''));
    min.title = 'the lowest score listed (the audit threshold is ' + (th.audit != null ? th.audit : '?') + ')';
    min.setAttribute('aria-label', min.title);
    min.addEventListener('change', function () { outl.min = Math.max(0, Math.min(100, Number(min.value) || 0)); outlLoad(list); });
    var tag = document.createElement('select');
    tag.setAttribute('aria-label', 'tag');
    var any = document.createElement('option');
    any.value = ''; any.textContent = 'every tag';
    tag.appendChild(any);
    Object.keys(got.by_tag || {}).forEach(function (k) {
      var o = document.createElement('option');
      o.value = k; o.textContent = k + ' (' + got.by_tag[k] + ')'; o.selected = k === outl.tag;
      tag.appendChild(o);
    });
    tag.addEventListener('change', function () { outl.tag = tag.value; outlRender(list); });
    var csv = document.createElement('button');
    csv.type = 'button'; csv.textContent = 'CSV'; csv.title = 'Export the list as CSV';
    csv.addEventListener('click', function (e) { e.stopPropagation(); outlSave('outlandish-' + outl.hours + 'h.csv', outlCsv(items), 'text/csv'); });
    var js = document.createElement('button');
    js.type = 'button'; js.textContent = 'JSON'; js.title = 'Export the list and its summary as JSON';
    js.addEventListener('click', function (e) { e.stopPropagation(); outlSave('outlandish-' + outl.hours + 'h.json', JSON.stringify(got, null, 1), 'application/json'); });
    [hours, min, tag, csv, js].forEach(function (x) { ctl.appendChild(x); });
    body.appendChild(ctl);
    var f = got.follow || {};
    var cost = got.cost || {};
    body.appendChild(untracedLine(items.length + ' of ' + (got.lines || 0) + ' measured lines at or above '
      + (got.floor != null ? got.floor : '?') + ' - dispute aired ' + (f.aired || 0) + ', planned but cut '
      + (f.planned_cut || 0) + ', none ' + (f.none || 0) + ' - thresholds audit ' + (th.audit != null ? th.audit : '?')
      + ' / react ' + (th.react != null ? th.react : '?') + ' / dispute ' + (th.dispute != null ? th.dispute : '?')
      + ' - the meter costs ' + (cost.rule_us_per_line != null ? cost.rule_us_per_line : '?') + ' us a line. Measured, never filtered.',
      'pine-outl-sum'));
    var dist = got.distribution || {};
    body.appendChild(untracedLine('scores: ' + Object.keys(dist).map(function (k) { return k + ' ' + dist[k]; }).join(' | '), 'pine-outl-sum'));
    items.forEach(function (it) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'pine-outl-row';
      var b = document.createElement('b');
      b.textContent = String(it.score);
      row.appendChild(b);
      var when = '';
      try { when = new Date(Number(it.at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
      catch (err) { when = ''; }
      row.appendChild(document.createTextNode((it.code || '') + ' ' + (it.who || '') + ' ' + when));
      var meta = document.createElement('i');
      var rx = it.reaction || {};
      meta.textContent = [(it.tags || []).join(', '), outlFollowWord(it.follow), rx.label ? 'SFX: ' + rx.label : '']
        .filter(Boolean).join(' - ');
      row.appendChild(meta);
      var words = document.createElement('span');
      words.textContent = String(it.text || '').slice(0, 220);
      row.appendChild(words);
      row.title = (it.cues || []).map(function (c) { return c.label + ': "' + c.match + '"'; }).join('; ')
        + (it.follow_why ? ' - ' + it.follow_why : '');
      row.addEventListener('click', function (event) {
        event.stopPropagation();
        outlOpenLine(it);
      });
      body.appendChild(row);
    });
  }

  function outlLoad(list) {
    return flowGet(outlPath(outl.hours, true)).then(function (got) {
      outl.got = got || {};
      if (outl.hours === 6) { outl.count = Number(got && got.count) || 0; outlPaint(); }
      if (list.isConnected) outlRender(list);
    }, function (err) {
      var body = list.querySelector('.pine-console-list-body');
      if (body) body.textContent = 'The OUTLANDISH review is not available: ' + String((err && err.message) || err);
    });
  }

  function outlOpen(bar) {
    if (typeof document === 'undefined') return;
    var old = document.getElementById('pineOutlList');
    if (old) { old.remove(); return; }
    outlStyle();
    var list = document.createElement('div');
    list.id = 'pineOutlList';
    list.className = 'pine-console-list';
    list.setAttribute('role', 'dialog');
    list.setAttribute('aria-label', 'OUTLANDISH review');
    list.setAttribute('data-pine-drag', '');
    list.innerHTML = '<div class="pine-console-list-head" data-pine-drag-handle>'
      + '<b>OUTLANDISH review</b><span class="pine-console-list-count"></span>'
      + '<button type="button" class="pine-console-list-close" aria-label="Close" title="Close">x</button>'
      + '</div><div class="pine-console-list-body">reading the meter...</div>';
    list.querySelector('.pine-console-list-close').addEventListener('click', function (event) {
      event.stopPropagation();
      list.remove();
    });
    document.body.appendChild(list);
    outlLoad(list);
    if (root.PineDismiss) root.PineDismiss.watch(list, function () { list.remove(); }, [bar || el()]);
  }

  function outlStart() {
    if (typeof document === 'undefined') return;
    outlButton();
    outlPoll();
    if (!outl.timer) {
      outl.timer = root.setInterval(function () { outlButton(); outlPoll(); }, OUTL_POLL_MS);
      if (outl.timer && typeof outl.timer.unref === 'function') outl.timer.unref();
    }
  }

  function start() {
    mount();
    untracedStart();                                   /* [s3-account] */
    outlStart();                                       /* [outl-audit-start] */
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
    speed: function () { return speed; }, refreshOrchestrator: paintOrchestratorButton,
    refreshTalkRestore: paintTalkRestoreButton,
    untraced: function () { return untracedOpen(el()); },   /* [s3-account] */
    outlandish: function () { return outlOpen(el()); }};   /* [outl-audit-api] */
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineConsoleLine;
})(typeof window !== 'undefined' ? window : globalThis);
