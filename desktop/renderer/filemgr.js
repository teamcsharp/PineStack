/* FILE MANAGEMENT - THE DISK ON THE BASE BAR AND THE POPUP BEHIND IT.
 *
 * "i also want an icon of a disk here that is a file management icon that
 *  brings up a popup where i can adjust a slider to clear the various caches
 *  of pine-box and even clear settings, lists, stored configs, and be able to
 *  reinitilize the station cleanly."                 - the operator, 2026-09-29
 *
 * WHERE IT LIVES. console-line.js's #pineConsoleLine on both glasses (the desk
 * chrome and the tablet's panel page). Like voice-actor.js, this file puts its
 * button INTO that bar - right after the person (voice actor), else right
 * after the "i" - and does not edit console-line.js. The bar answers any
 * click it does not recognise by opening the audit list, so the button stops
 * its own click.
 *
 * THE ROADS (filemgr.py, all keyed):
 *   GET  /api/filemgr/groups    every wipe group, its live size, tiers, presets
 *   POST /api/filemgr/plan      exactly what would go: files, bytes, snapshot, free
 *   POST /api/filemgr/run       snapshot, hot groups live, cold across a restart
 *   GET  /api/filemgr/jobs      the jobs (they survive the restart) + snapshots
 *   POST /api/filemgr/restore   the undo road
 *
 * Nothing here decides what a group holds; the server's manifest does. A
 * preset only sets the toggles. EXECUTE is a hold, and the settings / configs
 * / System 3 tiers also need the typed word the server names.
 *
 * ITS WAYS OUT (#1450's rule): the close button, a tap off it (PineDismiss),
 * Escape, and the tablet's BACK key.
 */
(function (root) {
  'use strict';
  if (!root || !root.document || root.PineFileMgr) return;
  var document = root.document;

  var REQUEST_MS = 15000;
  var HOLD_MS = 1600;
  var POLL_MS = 1500;
  var JOB_KEY = 'pineFilemgrJob';
  var TIER_LABEL = {
    cache: 'Caches', lines: 'Lines', history: 'History', backups: 'Backups',
    lists: 'Lists', settings: 'Settings', configs: 'Stored configs', system3: 'System 3'
  };

  var ui = {
    badge: null, pop: null, visible: false, barObserver: null,
    groups: null, picked: {}, snapshot: true, plan: null, planSeq: 0, planTimer: 0,
    jobs: null, pollTimer: 0, hold: null, unwatch: null, unback: null, restoreOpen: false
  };

  /* ================================================== roads */

  function bridge() {
    var b = root.pineDesktop;
    return b && typeof b.get === 'function' ? b : null;
  }
  function httpPage() {
    try { return /^https?:$/.test(String(root.location.protocol)); } catch (err) { return false; }
  }
  function stationUrl(u) {
    if (httpPage()) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (err) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }
  function stationKey() {
    try { if (typeof root.key === 'function') { var k = root.key(); if (typeof k === 'string' && k) return k; } } catch (err) { /* not the panel page */ }
    try {
      /* eslint-disable-next-line no-undef */
      if (typeof SERVER_KEY === 'string' && SERVER_KEY) return SERVER_KEY;
    } catch (err) { /* not declared on this page */ }
    try { return String(root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || ''); } catch (err) { return ''; }
  }
  function withTimeout(promise, ms, what) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = root.setTimeout(function () {
        if (done) return; done = true;
        reject(new Error(what + ' took longer than ' + Math.round(ms / 1000) + ' s'));
      }, ms);
      Promise.resolve(promise).then(function (v) {
        if (done) return; done = true; root.clearTimeout(timer); resolve(v);
      }, function (e) {
        if (done) return; done = true; root.clearTimeout(timer); reject(e);
      });
    });
  }
  function request(method, path, body) {
    var b = bridge();
    var fn = b && (method === 'GET' ? b.get : b.post);
    if (fn) return withTimeout(fn.call(b, path, method === 'GET' ? undefined : (body || {})), REQUEST_MS, path);
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to the station on this screen'));
    var headers = {};
    var key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    if (method !== 'GET') headers['Content-Type'] = 'application/json';
    return withTimeout(root.fetch(stationUrl(path), {
      method: method, headers: headers, cache: 'no-store',
      body: method === 'GET' ? undefined : JSON.stringify(body || {})
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (err) { data = {detail: text.slice(0, 200)}; }
        if (!res.ok) {
          var e = new Error(String((data && data.detail) || (res.status + ' ' + res.statusText)));
          e.status = res.status;
          throw e;
        }
        return data;
      });
    }), REQUEST_MS, path);
  }
  function get(path) { return request('GET', path); }
  function post(path, body) { return request('POST', path, body); }

  /* ================================================== helpers */

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function icon(mark, label) {
    try { if (typeof root.pineIcon === 'function') return root.pineIcon(mark, label) || ''; } catch (err) { /* words */ }
    return '';
  }
  function ico(mark, fallback) {
    var s = make('span', 'fm-ico');
    var m = icon(mark, '');
    if (m) s.innerHTML = m; else s.textContent = fallback || '';
    return s;
  }
  function bytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    var u = ['KB', 'MB', 'GB', 'TB'], i = -1;
    do { n /= 1024; i += 1; } while (n >= 1024 && i < u.length - 1);
    return (n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)) + ' ' + u[i];
  }
  function count(n, word) { n = Number(n) || 0; return n.toLocaleString() + ' ' + word + (n === 1 ? '' : 's'); }
  function store(k, v) {
    try { if (v === null) root.localStorage.removeItem(k); else root.localStorage.setItem(k, v); } catch (err) { /* private */ }
  }
  function load(k) { try { return root.localStorage.getItem(k) || ''; } catch (err) { return ''; } }
  function when(t) {
    try { return new Date(Number(t) * 1000).toLocaleString(); } catch (err) { return ''; }
  }

  /* ================================================== the badge */

  function attachBadge() {
    var bar = document.getElementById('pineConsoleLine');
    if (!bar) return false;
    var have = bar.querySelector('.pine-console-filemgr');
    if (have) { ui.badge = have; return true; }
    var b = make('button', 'pine-console-filemgr');
    b.type = 'button';
    b.setAttribute('aria-haspopup', 'dialog');
    b.setAttribute('aria-label', 'File management - clear caches, lists, settings; reinitialize');
    b.title = 'File management - clear caches, lists, settings; reinitialize';
    b.appendChild(make('span', 'fm-badge-ico'));
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      if (ui.visible) closePopup(); else openPopup();
    });
    /* where the operator marked it: right after the person, else after the "i" */
    var actor = bar.querySelector('.pine-console-actor');
    var info = bar.querySelector('.pine-console-change');
    var after = actor || info;
    var before = after ? after.nextSibling : bar.querySelector('.pine-console-viewport');
    bar.insertBefore(b, before || null);
    ui.badge = b;
    paintBadge();
    return true;
  }
  function placeBadge() {
    /* the person may arrive after us; it inserts itself after the "i", so
     * we stay to its right - re-seat only if something else got between */
    var b = ui.badge;
    if (!b || !b.isConnected) return;
    var actor = b.parentNode.querySelector('.pine-console-actor');
    if (actor && actor.nextSibling !== b) b.parentNode.insertBefore(b, actor.nextSibling);
  }
  function paintBadge() {
    var b = ui.badge;
    if (!b || !b.isConnected) return;
    var i = b.querySelector('.fm-badge-ico');
    if (i && !i.__fmDrawn) {
      var mark = icon('c:save', '');
      if (mark) { i.innerHTML = mark; i.__fmDrawn = true; } else i.textContent = 'DISK';
    }
    b.classList.toggle('open', ui.visible);
    var job = ui.jobs && ui.jobs.active;
    b.classList.toggle('busy', !!job);
  }
  function watchForBar() {
    attachBadge();
    if (ui.barObserver || typeof root.MutationObserver !== 'function' || !document.body) return;
    ui.barObserver = new root.MutationObserver(function () {
      var bar = document.getElementById('pineConsoleLine');
      if (bar && !bar.querySelector('.pine-console-filemgr')) attachBadge();
      placeBadge();
      paintBadge();
    });
    ui.barObserver.observe(document.body, {childList: true, subtree: false});
    var bar = document.getElementById('pineConsoleLine');
    if (bar) ui.barObserver.observe(bar, {childList: true});
  }

  /* ================================================== the popup */

  function buildPopup() {
    if (ui.pop) return ui.pop;
    var pop = make('div', 'fm-pop');
    pop.hidden = true;
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'File management');

    var head = make('div', 'fm-head');
    head.appendChild(ico('c:save', ''));
    var t = make('div', 'fm-title');
    t.appendChild(make('b', '', 'File management'));
    ui.sub = make('span', 'fm-sub', 'reading the station\'s files...');
    t.appendChild(ui.sub);
    head.appendChild(t);
    var refresh = make('button', 'fm-iconbtn');
    refresh.type = 'button';
    refresh.title = 'Measure again';
    refresh.setAttribute('aria-label', 'Measure again');
    refresh.appendChild(ico('c:renew', 'R'));
    refresh.addEventListener('click', function () { loadGroups(true); });
    head.appendChild(refresh);
    var x = make('button', 'fm-iconbtn fm-close');
    x.type = 'button';
    x.title = 'Close';
    x.setAttribute('aria-label', 'Close');
    x.appendChild(ico('c:close--filled', 'X'));
    x.addEventListener('click', closePopup);
    head.appendChild(x);
    pop.appendChild(head);

    ui.presets = make('div', 'fm-presets');
    pop.appendChild(ui.presets);

    ui.list = make('div', 'fm-list');
    pop.appendChild(ui.list);

    var foot = make('div', 'fm-foot');
    ui.status = make('div', 'fm-status');
    foot.appendChild(ui.status);

    var snapRow = make('label', 'fm-snaprow');
    ui.snapBox = make('input', 'fm-switch');
    ui.snapBox.type = 'checkbox';
    ui.snapBox.checked = true;
    ui.snapBox.addEventListener('change', function () { ui.snapshot = ui.snapBox.checked; schedulePlan(); });
    snapRow.appendChild(ui.snapBox);
    snapRow.appendChild(ico('c:archive', ''));
    snapRow.appendChild(make('span', 'fm-snapword', 'Snapshot first'));
    ui.snapNote = make('span', 'fm-snapnote', '');
    snapRow.appendChild(ui.snapNote);
    foot.appendChild(snapRow);

    ui.summary = make('div', 'fm-summary');
    foot.appendChild(ui.summary);

    var act = make('div', 'fm-act');
    ui.typed = make('input', 'fm-typed');
    ui.typed.type = 'text';
    ui.typed.autocomplete = 'off';
    ui.typed.spellcheck = false;
    ui.typed.hidden = true;
    ui.typed.addEventListener('input', paintExecute);
    act.appendChild(ui.typed);
    ui.exec = make('button', 'fm-exec');
    ui.exec.type = 'button';
    ui.exec.appendChild(make('span', 'fm-exec-fill'));
    ui.exec.appendChild(ico('c:trash-can', ''));
    ui.execWord = make('span', 'fm-exec-word', 'Hold to execute');
    ui.exec.appendChild(ui.execWord);
    wireHold(ui.exec, execute);
    act.appendChild(ui.exec);
    foot.appendChild(act);

    ui.jobBox = make('div', 'fm-job');
    ui.jobBox.hidden = true;
    foot.appendChild(ui.jobBox);

    var rs = make('div', 'fm-restore');
    var rh = make('button', 'fm-restore-head');
    rh.type = 'button';
    rh.appendChild(ico('c:renew', ''));
    rh.appendChild(make('span', '', 'Restore from snapshot'));
    ui.restoreCount = make('span', 'fm-restore-n', '');
    rh.appendChild(ui.restoreCount);
    rh.addEventListener('click', function () {
      ui.restoreOpen = !ui.restoreOpen;
      paintRestore();
    });
    rs.appendChild(rh);
    ui.restoreList = make('div', 'fm-restore-list');
    ui.restoreList.hidden = true;
    rs.appendChild(ui.restoreList);
    foot.appendChild(rs);

    /* [qrelease] the SFX quarantine: clips no player could decode, and folders
       gone from the share. A release re-checks the file on the station (it is
       on the share and ffmpeg decodes it, one at a time) before it may air
       again; a failed check keeps it here with the reason. */
    var qs = make('div', 'fm-restore fm-quarantine');
    var qh = make('button', 'fm-restore-head');
    qh.type = 'button';
    qh.title = 'Clips kept off the air because they could not be decoded';
    qh.appendChild(ico('c:warning--alt', ''));
    qh.appendChild(make('span', '', 'Quarantined clips'));
    ui.qCount = make('span', 'fm-restore-n', '');
    qh.appendChild(ui.qCount);
    qh.addEventListener('click', function () {
      ui.qOpen = !ui.qOpen;
      paintQuarantine();
      if (ui.qOpen) loadQuarantine();
    });
    qs.appendChild(qh);
    ui.qList = make('div', 'fm-restore-list');
    ui.qList.hidden = true;
    qs.appendChild(ui.qList);
    foot.appendChild(qs);
    /* [memprefs] the tablet's memory limits, as preferences */
    var ms = make('div', 'fm-restore fm-memprefs');
    var mh = make('div', 'fm-restore-head');
    mh.appendChild(ico('c:save', ''));
    mh.appendChild(make('span', '', 'Memory (this device) - applies the next time the app starts'));
    ms.appendChild(mh);
    var memPref = function (key, def) {
      try { var v = parseInt(root.localStorage.getItem(key), 10); return isNaN(v) ? def : v; } catch (e) { return def; }
    };
    var memRow = function (label, key, def, lo, hi, step, unit, after) {
      var row = make('label', 'fm-memrow');
      row.appendChild(make('span', 'fm-memlabel', label));
      var inp = make('input', ''); inp.type = 'range'; inp.min = lo; inp.max = hi; inp.step = step;
      inp.value = memPref(key, def); inp.title = label + ' (default ' + def + unit + ')';
      var val = make('span', 'fm-memval', inp.value + unit);
      inp.addEventListener('input', function () { val.textContent = inp.value + unit; });
      inp.addEventListener('change', function () {
        try { root.localStorage.setItem(key, String(inp.value)); } catch (e) { /* private window */ }
        if (after) { try { after(parseInt(inp.value, 10)); } catch (e) { /* no bridge */ } }
      });
      row.appendChild(inp); row.appendChild(val);
      ms.appendChild(row);
    };
    memRow('Message history', 'pine.mem.history', 50, 20, 300, 10, ' bubbles');
    memRow('Playing muted loops (plus a pinned one)', 'pine.mem.loops', 2, 1, 6, 1, '');
    memRow('Screen replay ring', 'pine.mem.replay', 48, 16, 100, 4, ' MB', function (mb) {
      var b = root.pineDesktop;
      if (b && typeof b.memPrefs === 'function') b.memPrefs({replayMb: mb});
    });
    foot.appendChild(ms);
    pop.appendChild(foot);

    document.body.appendChild(pop);
    ui.pop = pop;

    var dismiss = root.PineDismiss;
    if (dismiss && typeof dismiss.watch === 'function') {
      ui.unwatch = dismiss.watch(pop, closePopup, [function () { return ui.badge; }],
        function () { return ui.visible; });
    } else {
      document.addEventListener('keydown', function (e) {
        if (ui.visible && e.key === 'Escape') closePopup();
      });
    }
    var probe = function () { return ui.visible ? {node: pop, close: closePopup} : null; };
    if (dismiss && typeof dismiss.onBack === 'function') {
      ui.unback = dismiss.onBack(probe);
    } else {
      var was = root.pineBack;
      root.pineBack = function () {
        var p = probe();
        if (p) { try { p.close(); } catch (err) { /* closed anyway */ } return true; }
        return typeof was === 'function' ? was() : false;
      };
    }
    return pop;
  }

  function openPopup() {
    buildPopup();
    ui.visible = true;
    ui.pop.hidden = false;
    paintBadge();
    loadGroups(false);
    loadJobs();
    loadQuarantine();     /* [qrelease] */
  }
  function closePopup() {
    if (!ui.pop) return;
    ui.visible = false;
    ui.pop.hidden = true;
    cancelHold();
    var j = ui.jobs && ui.jobs.jobs && ui.jobs.jobs[0];
    if (j && (j.state === 'done' || j.state === 'failed') && load(JOB_KEY) === j.id) store(JOB_KEY, null);
    paintBadge();
  }

  /* ================================================== groups + presets */

  function loadGroups(fresh) {
    ui.sub.textContent = 'measuring...';
    return get('/api/filemgr/groups' + (fresh ? '?fresh=1' : '')).then(function (g) {
      ui.groups = g;
      paintPresets();
      paintList();
      schedulePlan();
      var total = 0, files = 0;
      (g.groups || []).forEach(function (r) { total += r.bytes || 0; files += r.files || 0; });
      ui.sub.textContent = count((g.groups || []).length, 'group') + ' - ' + count(files, 'file')
        + ', ' + bytes(total) + ' - measured in ' + (g.took_s || 0) + ' s';
    }, function (e) {
      ui.sub.textContent = 'the station did not answer: ' + e.message;
    });
  }

  function paintPresets() {
    var box = ui.presets;
    box.textContent = '';
    ((ui.groups && ui.groups.presets) || []).forEach(function (p) {
      var b = make('button', 'fm-preset');
      b.type = 'button';
      b.appendChild(make('b', '', p.label));
      if (p.hint) b.appendChild(make('span', '', p.hint));
      b.addEventListener('click', function () {
        var tiers = {};
        (p.tiers || []).forEach(function (t) { tiers[t] = true; });
        ui.picked = {};
        (ui.groups.groups || []).forEach(function (g) {
          /* a light preset leaves out what the manifest keeps from its own clean slate */
          if (tiers[g.tier] && !(p.suggested_only && g.suggested === false)) ui.picked[g.id] = true;
        });
        paintToggles();
        schedulePlan();
      });
      box.appendChild(b);
    });
    var none = make('button', 'fm-preset fm-preset-none');
    none.type = 'button';
    none.appendChild(make('b', '', 'None'));
    none.addEventListener('click', function () { ui.picked = {}; paintToggles(); schedulePlan(); });
    box.appendChild(none);
  }

  function paintList() {
    var list = ui.list;
    list.textContent = '';
    var g = ui.groups || {};
    var destructive = {};
    (g.destructive || []).forEach(function (t) { destructive[t] = true; });
    var divided = false;
    (g.tiers || []).forEach(function (tier) {
      var rows = (g.groups || []).filter(function (r) { return r.tier === tier; });
      if (!rows.length) return;
      if (destructive[tier] && !divided) {
        divided = true;
        var d = make('div', 'fm-divider');
        d.appendChild(ico('c:warning--alt', '!'));
        d.appendChild(make('span', '', 'Destructive - these hold what the station is, not what it made'));
        list.appendChild(d);
      }
      var th = make('div', 'fm-tier' + (destructive[tier] ? ' fm-tier-danger' : ''));
      th.textContent = TIER_LABEL[tier] || tier;
      list.appendChild(th);
      rows.forEach(function (r) { list.appendChild(buildRow(r)); });
    });
    if ((g.kept || []).length) {
      list.appendChild(make('div', 'fm-kept', count(g.kept.length, 'group') + ' kept by the manifest and never cleared: '
        + g.kept.map(function (k) { return k.label; }).join(', ')));
    }
    if ((g.problems || []).length) {
      list.appendChild(make('div', 'fm-problem', g.problems.join(' - ')));
    }
    paintToggles();
  }

  function buildRow(r) {
    var row = make('label', 'fm-row');
    row.setAttribute('data-id', r.id);
    var sw = make('input', 'fm-switch');
    sw.type = 'checkbox';
    sw.addEventListener('change', function () {
      if (sw.checked) ui.picked[r.id] = true; else delete ui.picked[r.id];
      row.classList.toggle('on', sw.checked);
      schedulePlan();
    });
    row.appendChild(sw);
    var mid = make('div', 'fm-row-mid');
    var top = make('div', 'fm-row-top');
    top.appendChild(make('b', 'fm-row-label', r.label));
    var hot = r.effective_mode === 'hot';
    var badge = make('span', 'fm-mode ' + (hot ? 'fm-hot' : 'fm-cold'), hot ? 'HOT' : 'COLD');
    badge.title = hot ? 'Clears live, through the store\'s own lock'
      : 'Clears across a controlled restart' + (r.mode === 'hot' && (r.unowned || []).length
        ? ' (no live owner is wired for ' + r.unowned.join(', ') + ')' : '');
    top.appendChild(badge);
    mid.appendChild(top);
    mid.appendChild(make('div', 'fm-row-desc', r.description || r.reason || ''));
    row.appendChild(mid);
    row.appendChild(make('span', 'fm-row-size', r.files ? bytes(r.bytes) + ' / ' + count(r.files, 'file') : 'empty'));
    return row;
  }

  function paintToggles() {
    if (!ui.list) return;
    var rows = ui.list.querySelectorAll('.fm-row');
    for (var i = 0; i < rows.length; i += 1) {
      var on = !!ui.picked[rows[i].getAttribute('data-id')];
      rows[i].querySelector('input').checked = on;
      rows[i].classList.toggle('on', on);
    }
  }

  function pickedIds() {
    return ((ui.groups && ui.groups.groups) || []).filter(function (g) { return ui.picked[g.id]; })
      .map(function (g) { return g.id; });
  }

  /* ================================================== the plan */

  function schedulePlan() {
    root.clearTimeout(ui.planTimer);
    ui.planTimer = root.setTimeout(runPlan, 220);
  }
  function runPlan() {
    var ids = pickedIds();
    var seq = ++ui.planSeq;
    if (!ids.length) { ui.plan = null; paintSummary(); return; }
    ui.summary.textContent = 'counting...';
    post('/api/filemgr/plan', {groups: ids, snapshot: ui.snapshot}).then(function (p) {
      if (seq !== ui.planSeq) return;
      ui.plan = p;
      paintSummary();
    }, function (e) {
      if (seq !== ui.planSeq) return;
      ui.plan = null;
      ui.summary.textContent = 'the plan could not be read: ' + e.message;
      paintExecute();
    });
  }

  function paintSummary() {
    var p = ui.plan;
    var s = ui.summary;
    s.textContent = '';
    if (!p) {
      s.appendChild(make('span', 'fm-dim', 'Pick groups, or a preset above.'));
      ui.snapNote.textContent = '';
      ui.typed.hidden = true;
      paintExecute();
      return;
    }
    var go = make('div', 'fm-sum-line');
    go.appendChild(make('b', '', count(p.files, 'file') + ' / ' + bytes(p.bytes)));
    go.appendChild(make('span', '', ' will go from ' + count(p.groups.length, 'group')
      + (p.hot.length ? ' - ' + p.hot.length + ' live' : '') + (p.cold.length ? ' - ' + p.cold.length + ' across a restart' : '')));
    s.appendChild(go);
    var sn = p.snapshot || {};
    ui.snapNote.textContent = sn.on
      ? '~' + bytes(sn.bytes) + ' as ' + sn.name + ' - ' + (sn.local_free != null ? bytes(sn.local_free) + ' free here' : 'free space unknown')
        + (sn.quickswap_dest ? '; the desk carries a copy to QuickSwap' + (sn.quickswap_free != null ? ' (' + bytes(sn.quickswap_free) + ' free)' : '')
          : sn.kept_local_why ? '; stays on the box - ' + sn.kept_local_why
            : '; no QuickSwap folder is set, so it stays on the box')
      : (ui.snapshot ? 'nothing to pack' : 'off - there will be no undo');
    if (p.restart) {
      s.appendChild(make('div', 'fm-sum-warn', 'The station restarts to clear the cold groups (about 20 s off the air). The job runs between the stop and the start.'));
    }
    if (p.refusal) s.appendChild(make('div', 'fm-sum-refuse', 'Refused: ' + p.refusal));
    if ((p.unknown || []).length) s.appendChild(make('div', 'fm-sum-warn', 'Not in the manifest: ' + p.unknown.join(', ')));
    ui.typed.hidden = !p.typed_word;
    ui.typed.placeholder = p.typed_word ? 'type ' + p.typed_word : '';
    paintExecute();
  }

  function ready() {
    var p = ui.plan;
    if (!p || !p.groups.length || p.refusal) return false;
    if (ui.jobs && ui.jobs.active) return false;
    if (p.typed_word && String(ui.typed.value || '').trim().toUpperCase() !== p.typed_word) return false;
    return true;
  }
  function paintExecute() {
    var ok = ready();
    ui.exec.disabled = !ok;
    ui.exec.classList.toggle('fm-danger', !!(ui.plan && ui.plan.destructive));
    var p = ui.plan;
    ui.execWord.textContent = !p ? 'Hold to execute'
      : (ui.jobs && ui.jobs.active) ? 'A job is running'
        : p.typed_word && !ok && !p.refusal ? 'Type ' + p.typed_word + ' first'
          : 'Hold to clear ' + bytes(p.bytes);
  }

  /* ================================================== hold to confirm */

  function wireHold(btn, fire) {
    var start = function (e) {
      if (btn.disabled) return;
      if (e && e.type === 'keydown' && e.key !== ' ' && e.key !== 'Enter') return;
      if (e && e.type === 'keydown' && e.repeat) return;
      if (e) e.preventDefault();
      cancelHold();
      btn.classList.add('holding');
      ui.hold = {btn: btn, timer: root.setTimeout(function () {
        btn.classList.remove('holding');
        ui.hold = null;
        fire(btn);
      }, HOLD_MS)};
    };
    btn.addEventListener('pointerdown', start);
    btn.addEventListener('keydown', start);
    ['pointerup', 'pointerleave', 'pointercancel', 'keyup', 'blur'].forEach(function (ev) {
      btn.addEventListener(ev, function () { if (ui.hold && ui.hold.btn === btn) cancelHold(); });
    });
    btn.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); });
  }
  function cancelHold() {
    if (!ui.hold) return;
    root.clearTimeout(ui.hold.timer);
    ui.hold.btn.classList.remove('holding');
    ui.hold = null;
  }

  function execute() {
    if (!ready()) return;
    var p = ui.plan;
    ui.exec.disabled = true;
    ui.execWord.textContent = 'Starting...';
    post('/api/filemgr/run', {groups: pickedIds(), snapshot: ui.snapshot, typed: ui.typed.value || ''})
      .then(function (got) {
        store(JOB_KEY, got.job && got.job.id);
        ui.typed.value = '';
        ui.picked = {};
        paintToggles();
        ui.plan = null;
        paintSummary();
        loadJobs();
      }, function (e) {
        ui.summary.appendChild(make('div', 'fm-sum-refuse', 'Refused: ' + e.message));
        ui.plan = p;
        paintExecute();
      });
  }

  /* ================================================== jobs, progress, restore */

  function loadJobs() {
    root.clearTimeout(ui.pollTimer);
    return get('/api/filemgr/jobs').then(function (j) {
      ui.jobs = j;
      ui.lost = 0;
      paintJob();
      paintRestore();
      paintBadge();
      paintExecute();
      var watching = load(JOB_KEY);
      var mine = (j.jobs || []).filter(function (r) { return r.id === watching; })[0];
      var settled = !mine || mine.state === 'done' || mine.state === 'failed';
      var more = !!j.active || (!!watching && !settled);
      if (ui.wasBusy && !more && ui.visible) loadGroups(true);   /* the sizes moved */
      ui.wasBusy = more;
      if (more) ui.pollTimer = root.setTimeout(loadJobs, POLL_MS);
    }, function () {
      /* the station is away - most likely the restart this job asked for */
      ui.lost = (ui.lost || 0) + 1;
      if (ui.jobBox && load(JOB_KEY)) {
        ui.jobBox.hidden = false;
        ui.jobBox.classList.add('fm-job-away');
        var w = ui.jobBox.querySelector('.fm-job-state');
        if (w) w.textContent = 'The station is restarting - waiting for it to come back (' + ui.lost + ')';
      }
      if (load(JOB_KEY)) ui.pollTimer = root.setTimeout(loadJobs, POLL_MS * 2);
    });
  }

  function paintJob() {
    var box = ui.jobBox;
    if (!box) return;
    var j = ui.jobs || {};
    var watching = load(JOB_KEY);
    var job = j.active || (j.jobs || []).filter(function (r) { return r.id === watching; })[0];
    box.textContent = '';
    box.classList.remove('fm-job-away');
    if (!job) { box.hidden = true; return; }
    box.hidden = false;
    var state = String(job.state || '');
    box.className = 'fm-job fm-job-' + state;
    var head = make('div', 'fm-job-head');
    head.appendChild(ico(state === 'done' ? 'c:checkmark--filled' : state === 'failed' ? 'c:misuse' : 'c:hourglass', ''));
    var words = {
      queued: 'Queued', snapshot: 'Packing the snapshot', clearing: 'Clearing the live groups',
      restarting: 'Restarting to clear the cold groups', done: 'Done', failed: 'Failed'
    };
    head.appendChild(make('b', 'fm-job-state', (words[state] || state) + (job.kind === 'restore' ? ' (restore)' : '')));
    head.appendChild(make('span', 'fm-dim', ' ' + when(job.at)));
    box.appendChild(head);
    var pr = job.progress || {};
    if (state === 'snapshot' && pr.total) {
      var bar = make('div', 'fm-bar');
      var fill = make('i', '');
      fill.style.width = Math.min(100, Math.round(100 * (pr.done || 0) / pr.total)) + '%';
      bar.appendChild(fill);
      box.appendChild(bar);
    }
    (job.steps || []).forEach(function (s) { box.appendChild(make('div', 'fm-job-step', s)); });
    if (job.error) box.appendChild(make('div', 'fm-sum-refuse', job.error));
    var res = (job.result && job.result.groups) || null;
    if (state === 'done' && res) {
      var f = 0, b = 0;
      Object.keys(res).forEach(function (k) { f += res[k].files || 0; b += res[k].bytes || 0; });
      box.appendChild(make('div', 'fm-job-sum', 'Cleared ' + count(f, 'file') + ', freed ' + bytes(b)
        + (job.snapshot_name ? ' - snapshot ' + job.snapshot_name : '')));
    } else if (state === 'done' && job.result && job.result.files != null) {
      box.appendChild(make('div', 'fm-job-sum', 'Restored ' + count(job.result.files, 'file') + ', ' + bytes(job.result.bytes)));
    }
  }

  function paintRestore() {
    if (!ui.restoreList) return;
    var snaps = (ui.jobs && ui.jobs.snapshots) || [];
    ui.restoreCount.textContent = snaps.length ? String(snaps.length) : 'none yet';
    ui.restoreList.hidden = !ui.restoreOpen;
    if (!ui.restoreOpen) return;
    ui.restoreList.textContent = '';
    if (!snaps.length) {
      ui.restoreList.appendChild(make('div', 'fm-dim', 'No snapshots on the box. Leave "Snapshot first" on and every clear makes one.'));
      return;
    }
    snaps.forEach(function (s) {
      var row = make('div', 'fm-snap');
      var words = make('div', 'fm-snap-words');
      words.appendChild(make('b', '', s.name));
      words.appendChild(make('span', 'fm-dim', bytes(s.bytes) + ' - ' + when(s.at)));
      row.appendChild(words);
      var b = make('button', 'fm-exec fm-restore-btn');
      b.type = 'button';
      b.appendChild(make('span', 'fm-exec-fill'));
      b.appendChild(make('span', 'fm-exec-word', 'Hold to restore'));
      b.disabled = !!(ui.jobs && ui.jobs.active);
      wireHold(b, function () {
        b.disabled = true;
        post('/api/filemgr/restore', {name: s.name, confirm: true}).then(function (got) {
          store(JOB_KEY, got.job && got.job.id);
          loadJobs();
        }, function (e) {
          row.appendChild(make('div', 'fm-sum-refuse', 'Refused: ' + e.message));
          b.disabled = false;
        });
      });
      row.appendChild(b);
      ui.restoreList.appendChild(row);
    });
  }

  /* ================================================== [qrelease] quarantine */

  function loadQuarantine() {
    return get('/api/sfx/quarantine').then(function (q) {
      ui.quarantine = q || {};
      paintQuarantine();
      var job = ui.quarantine.job || {};
      if (job.running && ui.visible) root.setTimeout(loadQuarantine, 3000);
    }, function (e) {
      ui.quarantine = {error: e.message};
      paintQuarantine();
    });
  }
  function releaseHold(word, body, row) {
    var b = make('button', 'fm-exec fm-restore-btn');
    b.type = 'button';
    b.title = 'Check the file again and let it air if it passes';
    b.appendChild(make('span', 'fm-exec-fill'));
    b.appendChild(make('span', 'fm-exec-word', word));
    wireHold(b, function () {
      b.disabled = true;
      post('/api/sfx/quarantine/release', body).then(function (got) {
        var passed = got && got.ok;
        row.appendChild(make('div', passed ? 'fm-dim' : 'fm-sum-refuse',
          (got && got.say) || (passed ? 'Released' : 'It stays quarantined')));
        root.setTimeout(loadQuarantine, 1500);
      }, function (e) {
        row.appendChild(make('div', 'fm-sum-refuse', 'Refused: ' + e.message));
        b.disabled = false;
      });
    });
    return b;
  }
  function paintQuarantine() {
    if (!ui.qList) return;
    var q = ui.quarantine || {};
    var clips = q.clips || [];
    var folders = (q.folders || []).filter(function (f) { return f.gone || f.clips > 1; });
    ui.qCount.textContent = q.error ? '?' : (ui.quarantine ? (clips.length ? String(clips.length) : 'none') : '');
    ui.qList.hidden = !ui.qOpen;
    if (!ui.qOpen) return;
    ui.qList.textContent = '';
    if (q.error) {
      ui.qList.appendChild(make('div', 'fm-sum-refuse', 'Could not read the quarantine: ' + q.error));
      return;
    }
    if (q.job && (q.job.running || q.job.say)) {
      ui.qList.appendChild(make('div', 'fm-dim', q.job.running
        ? 'Checking ' + q.job.folder + ': ' + (q.job.done || 0) + ' of ' + (q.job.total || 0)
        : q.job.say));
    }
    if (!clips.length && !folders.length) {
      ui.qList.appendChild(make('div', 'fm-dim', 'Nothing is quarantined.'));
      return;
    }
    folders.forEach(function (f) {
      var row = make('div', 'fm-snap');
      var words = make('div', 'fm-snap-words');
      words.appendChild(make('b', '', f.folder));
      words.appendChild(make('span', 'fm-dim', count(f.clips, 'clip') +
        (f.back ? ' - the folder is back on the share' : (f.gone ? ' - the folder is gone from the share' : ''))));
      row.appendChild(words);
      row.appendChild(releaseHold('Hold to release folder', {folder: f.folder}, row));
      ui.qList.appendChild(row);
    });
    clips.slice(0, 80).forEach(function (c) {
      var row = make('div', 'fm-snap');
      var words = make('div', 'fm-snap-words');
      words.appendChild(make('b', '', c.name || c.sid));
      words.appendChild(make('span', 'fm-dim', (c.why || 'quarantined') + (c.at ? ' - ' + when(c.at) : '')));
      if (c.last_check) words.appendChild(make('span', 'fm-sum-refuse', 'Last check: ' + c.last_check));
      row.appendChild(words);
      row.appendChild(releaseHold('Hold to release', {sid: c.sid}, row));
      ui.qList.appendChild(row);
    });
    if (clips.length > 80) {
      ui.qList.appendChild(make('div', 'fm-dim', '... and ' + (clips.length - 80) + ' more - release their folder'));
    }
  }

  /* ================================================== boot */

  function boot() {
    watchForBar();
    /* a job this glass started is still owed its result: show it again */
    if (load(JOB_KEY)) root.setTimeout(function () { attachBadge(); openPopup(); }, 1200);
  }

  root.PineFileMgr = {
    open: openPopup, close: closePopup, isOpen: function () { return ui.visible; },
    attach: attachBadge
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(typeof window !== 'undefined' ? window : this);
