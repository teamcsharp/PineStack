/* [pinetab-update] THE TABLET BUTTON, under the mark.
 *
 * "Put an icon of a tablet here that represents updating the tablet. Have it pulse
 * if the tablet is out of date ... if I click the button, have it locate the tablet
 * and update the firmware with the latest version after compiling it ... I want to
 * be able to click this button to do any and all troubleshooting whenever it comes
 * to the tablet."                                          - the operator, 2026-10-01
 *
 * The desk's main process does the work (desktop/pinetab-update.cjs); this paints
 * the button (pulsing when stale, busy while an update runs, red when the tablet
 * cannot be found) and the panel: the state, the update, and every repair.
 */
(function (root) {
  'use strict';

  var CHECK_MS = 60000;
  var api = root.pineDesktop;
  var btn = document.getElementById('pinetabBtn');
  if (!btn || !api || typeof api.pinetabCheck !== 'function') {
    if (btn) btn.hidden = true;           /* not the desktop app: no adb, no deploy.sh */
    return;
  }
  var ui = {panel: null, log: null, state: null, say: null, buttons: [], last: null, running: false};

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  function paintButton(c) {
    ui.last = c || ui.last;
    c = ui.last || {};
    btn.classList.toggle('busy', ui.running || !!c.busy);
    btn.classList.toggle('stale', !ui.running && !c.busy && !!c.stale);
    btn.classList.toggle('gone', !ui.running && !c.busy && !c.stale && c.host && !c.on_network);
    var tip = ui.running ? 'The PineTab is being updated - click to watch'
      : (c.say || 'The PineTab') + (c.host ? ' (' + c.host + ')' : '')
        + '\nClick to build, sign and install the newest PineTab app now (the repairs are in the panel).';
    btn.title = tip;
    btn.setAttribute('aria-label', tip);
    paintState();
  }

  function paintState() {
    if (!ui.state) return;
    var c = ui.last || {};
    ui.state.textContent = '';
    [['source builds', c.wanted || '-'], ['tablet has', (c.installed || c.installed_name || 'no stamp yet')
      + (c.via ? '  (' + c.via + ')' : '')], ['where', c.host ? c.host + ':' + c.port : 'unknown'],
     ['on the network', c.on_network ? 'yes' : 'no'], ['adb port', c.adb_open ? 'open' : 'closed']]
      .forEach(function (r) { ui.state.appendChild(make('span', '', r[0])); ui.state.appendChild(make('span', '', r[1])); });
    ui.say.textContent = c.say || '';
    ui.say.className = 'pt-say' + (c.stale ? ' stale' : (c.wanted && !c.stale ? ' ok' : ''));
    ui.buttons.forEach(function (b) { b.disabled = ui.running; });
    if (ui.update) ui.update.textContent = c.stale || !c.installed ? 'Update the tablet' : 'Rebuild and install anyway';
  }

  function logLine(ev) {
    if (!ui.log) return;
    var t = new Date(ev.at || Date.now());
    var row = make('div', ev.state === 'step' ? 'step' : (ev.state || ''));
    row.textContent = ('0' + t.getHours()).slice(-2) + ':' + ('0' + t.getMinutes()).slice(-2) + ':'
      + ('0' + t.getSeconds()).slice(-2) + '  ' + (ev.state === 'step' ? '== ' : '') + ev.line;
    ui.log.appendChild(row);
    while (ui.log.childNodes.length > 1200) ui.log.removeChild(ui.log.firstChild);
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  function check(adb) {
    return Promise.resolve(api.pinetabCheck({adb: !!adb})).then(function (c) { paintButton(c); if (c && c.wanted) station('/api/tablet/update-ask', {wanted: c.wanted}); return c; },
      function () { return null; });
  }

  function act(label, fn) {
    var b = make('button', '', label);
    b.type = 'button';
    b.addEventListener('click', function () {
      if (ui.running) return;
      fn(b);
    });
    ui.buttons.push(b);
    return b;
  }

  function show(obj, title) {
    logLine({state: 'step', line: title});
    var text = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 1);
    String(text || '').split(/\r?\n/).slice(0, 200).forEach(function (l) { if (l.trim()) logLine({line: l}); });
  }

  /* [tablet-update-ask] the station, for the tablet's own "update me" ask. */
  var cfgP = null;
  function station(route, body) {
    cfgP = cfgP || Promise.resolve(typeof api.readConfig === 'function' ? api.readConfig() : null);
    return cfgP.then(function (cfg) {
      cfg = cfg || {};
      var head = {'Content-Type': 'application/json'};
      if (cfg.apiKey) head.Authorization = 'Bearer ' + cfg.apiKey;
      var url = String(cfg.baseUrl || '').replace(/\/+$/, '') + route;
      var controller = new AbortController();
      var timeout = root.setTimeout(function () { controller.abort(); }, 15000);
      var options = body ? {method: 'POST', headers: head, body: JSON.stringify(body)} : {headers: head};
      options.signal = controller.signal;
      return fetch(url, options).then(function (r) { return r.ok ? r.json() : null; })
        .finally(function () { root.clearTimeout(timeout); });
    }).catch(function () { return null; });
  }

  /* The ask being served, so its progress goes back to the tablet. */
  var serving = null;
  var reportQueue = Promise.resolve(), reportBusy = false, nextReport = null;
  var servingPhase = "running";
  var pendingLines = [], lineTimer = null;
  function flushLines() {
    if (lineTimer) root.clearTimeout(lineTimer);
    lineTimer = null;
    var lines = pendingLines.splice(0);
    lines.forEach(function (line) { report(servingPhase, line); });
  }
  function reportLine(line) {
    pendingLines.push(line);
    pendingLines = pendingLines.slice(-2);
    if (!lineTimer) lineTimer = root.setTimeout(flushLines, 500);
  }
  function report(state, line) {
    if (!serving) return;
    nextReport = {ask_at: serving, state: state, line: String(line || '').slice(0, 240)};
    sendReports();
  }
  function sendReports() {
    if (reportBusy || !nextReport) return;
    reportBusy = true;
    reportQueue = reportQueue.catch(function () {}).then(async function () {
      while (nextReport) {
        var body = nextReport;
        nextReport = null;
        await station('/api/tablet/update-ask', body);
      }
    }).finally(function () { reportBusy = false; sendReports(); });
  }

  function update(mode, ask) {
    ui.running = true;
    serving = ask || null;
    paintButton();
    logLine({state: 'step', line: (mode === 'prepare' ? 'build and sign the newest PineTab update' : mode === 'install' ? 'install the compiled PineTab update' : mode === 'resign' ? 're-sign and install' : 'build, sign and install the newest PineTab app')
      + (ask ? ' - the tablet asked for it' : '')});
    servingPhase = mode === 'install' ? 'installing' : 'running';
    report(servingPhase, mode === 'install' ? 'installing the compiled update' : 'the desk is building the newest PineTab app');
    Promise.resolve(api.pinetabUpdate(mode)).then(function (r) {
      var ok = !!(r && r.ok);
      var said = ok && r.ready ? 'compiled and signed - tap again on the tablet to install' : ok ? (r.skipped ? 'nothing to do - it was current' : 'done: the tablet runs ' + (r.after || '?'))
        : 'not done: ' + ((r && r.why) || 'see above');
      logLine({state: ok ? 'ok' : 'fail', line: said});
      /* a desk whose main process predates the relaunch step: open the app here */
      var opened = ok && !r.ready && !r.skipped && !r.relaunched
        ? Promise.resolve(api.pinetabAction('restart-app')).then(function () { logLine({state: 'ok', line: 'the PineBox app is open on the tablet again'}); })
        : Promise.resolve();
      return opened.then(function () {
        flushLines();
        report(ok ? (r.ready ? 'ready' : 'done') : 'failed', said);
        serving = null;
        ui.running = false;
        return check(true);
      });
    }, function (e) {
      flushLines();
      report('failed', String((e && e.message) || e));
      serving = null;
      ui.running = false;
      logLine({state: 'fail', line: String((e && e.message) || e)});
      paintButton();
    });
  }

  /* The tablet's Reinitialise card asks through the station; the desk takes the ask
   * once, runs the same update, and the tablet reads the progress back. */
  var ASK_MS = 5000;
  var takenAsk = 0;
  var installedAsk = 0;
  function watchAsks() {
    if (ui.running) return;
    station('/api/tablet/update-ask').then(function (v) {
      if (v && v.open && v.state === 'install-requested' && v.ask_at > installedAsk && !ui.running) {
        installedAsk = v.ask_at;
        update('install', v.ask_at);
        return;
      }
      if (!v || !v.open || v.state !== 'asked' || !(v.ask_at > takenAsk) || ui.running) return;
      takenAsk = v.ask_at;
      serving = v.ask_at;
      report('taken', 'the desk took it - building now');
      var p = ui.panel || build();
      p.hidden = false;
      update('prepare', v.ask_at);
    });
  }

  function simple(name, title) {
    return function () {
      logLine({state: 'step', line: title});
      Promise.resolve(api.pinetabAction(name)).then(function (r) {
        show(r, title + ' - ' + (r && r.ok === false ? 'failed' : 'done'));
        check(false);
      }, function (e) { logLine({state: 'fail', line: String((e && e.message) || e)}); });
    };
  }

  function build() {
    var p = make('section', 'pt-panel');
    p.hidden = true;
    p.setAttribute('role', 'dialog');
    p.setAttribute('aria-label', 'The PineTab');
    var head = make('div', 'pt-head');
    head.appendChild(make('b', '', 'THE PINETAB'));
    var x = make('button', 'pt-x', 'close');
    x.type = 'button';
    x.addEventListener('click', function () { p.hidden = true; });
    head.appendChild(x);
    p.appendChild(head);
    ui.say = make('div', 'pt-say', 'checking...');
    p.appendChild(ui.say);
    ui.state = make('div', 'pt-state');
    p.appendChild(ui.state);
    var r1 = make('div', 'pt-row');
    ui.update = act('Update the tablet', function () {
      var c = ui.last || {};
      update(c.stale || !c.installed ? 'update' : 'force');
    });
    ui.update.classList.add('main');
    r1.appendChild(ui.update);
    r1.appendChild(act('Re-sign and install (no build)', function () { update('resign'); }));
    r1.appendChild(act('Preflight report', function () {
      logLine({state: 'step', line: 'preflight (read-only)'});
      Promise.resolve(api.pinetabPreflight()).then(function (r) { show((r && r.text) || '', 'preflight ' + (r && r.ok ? 'passed' : 'found problems')); });
    }));
    r1.appendChild(act('Check now', function () { logLine({state: 'step', line: 'checking'}); check(true).then(function (c) { if (c) logLine({line: c.say, state: c.stale ? 'warn' : 'ok'}); }); }));
    p.appendChild(r1);
    var r2 = make('div', 'pt-row');
    r2.appendChild(act('Find the tablet', simple('find', 'finding the tablet on the network')));
    r2.appendChild(act('Reconnect adb', simple('connect', 'connecting adb')));
    r2.appendChild(act('Wake', simple('wake', 'waking the screen')));
    r2.appendChild(act('Restart the app', simple('restart-app', 'restarting the PineBox app')));
    r2.appendChild(act('Re-grant permissions', simple('grant', 're-granting the microphone and camera')));
    r2.appendChild(act('Installed version', simple('version', 'reading the installed version')));
    var reboot = act('Reboot', function (b) {
      if (!b.classList.contains('armed')) {
        b.classList.add('armed'); b.textContent = 'Tap again to reboot';
        root.setTimeout(function () { b.classList.remove('armed'); b.textContent = 'Reboot'; }, 4000);
        return;
      }
      b.classList.remove('armed'); b.textContent = 'Reboot';
      simple('reboot', 'rebooting the tablet')();
    });
    reboot.classList.add('danger');
    r2.appendChild(reboot);
    p.appendChild(r2);
    ui.log = make('div', 'pt-log');
    p.appendChild(ui.log);
    document.body.appendChild(p);
    ui.panel = p;
    return p;
  }

  /* [tablet-update-ask] "When I click this button, I want to make and export and
   * upload and install the latest version of PineTab to the Pine tab" (the operator,
   * 2026-10-01). A press builds, signs, installs and reopens it at once; while that
   * runs, a press shows or hides the panel. The repairs stay in the panel. */
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    var p = ui.panel || build();
    Promise.resolve(api.pinetabJob && api.pinetabJob()).then(function (job) {
      if (job && job.log && !ui.log.childNodes.length) job.log.forEach(logLine);
      if (job && job.running) { ui.running = true; paintButton(); }
      if (ui.running) {
        p.hidden = !p.hidden;
        return;
      }
      p.hidden = false;
      update('force');
    });
  });
  if (typeof api.onPinetabProgress === 'function') api.onPinetabProgress(function (ev) {
    logLine(ev);
    if (serving && ev) reportLine(ev.line);
  });

  check(false);
  root.setInterval(function () { if (!ui.running) check(false); }, CHECK_MS);
  root.setInterval(watchAsks, ASK_MS);
  watchAsks();
})(typeof window !== 'undefined' ? window : globalThis);
