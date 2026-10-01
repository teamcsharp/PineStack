/* [speech-gates] THE SPEECH GATES PANEL.
 *
 * "what station speech gate? where is the panel for that? i need to be able to
 * edit any gate for speech by the station"                 - the operator, 2026-10-01
 *
 * Every gate that can refuse the station's speech, in one place:
 *  - the content gates (master and each editorial gate - the switches that
 *    already existed, from /api/orchestrator/content-gates), and
 *  - the thresholds written into the code (speech_gates.py, /api/speech-gates):
 *    nothing twice inside a day, the rerun check, the advert copy check, System
 *    3's copy gate, the hourly video's sentence rules, call novelty, the re-air
 *    copy check, the English check. Each number is editable within its safe
 *    range; each rule of a gate can be switched off; Reset puts the station's
 *    own values back. A change takes effect on the next line and survives a
 *    restart. Opened from the script view's toolbar (PineSpeechGates.open()).
 */
(function (root) {
  'use strict';

  var ui = {panel: null, body: null, note: null, data: null, busy: false};

  function api() { return root.pineDesktop || {}; }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function say(text) { if (ui.note) ui.note.textContent = text || ''; }
  function why(err) { return (err && (err.detail || err.message)) || String(err || 'no answer'); }

  function load(message) {
    var get = api().get;
    if (typeof get !== 'function') { say('This screen cannot reach the station.'); return; }
    Promise.resolve(get('/api/speech-gates')).then(function (got) {
      ui.data = got; paint(); if (message) say(message);
    }, function (err) { say('Could not load the gates: ' + why(err)); });
  }

  function post(route, body, done) {
    if (ui.busy) return;
    ui.busy = true;
    Promise.resolve(api().post(route, body)).then(function (got) {
      ui.busy = false;
      if (route === '/api/speech-gates' && got && got.gates) { ui.data = got; paint(); say(done); }
      else load(done);
    }, function (err) { ui.busy = false; say('Not changed: ' + why(err)); load(); });
  }

  function contentSection() {
    var c = (ui.data && ui.data.content) || null;
    var sec = make('section', 'sg-gate sg-content');
    var head = make('div', 'sg-head');
    head.append(make('b', '', 'Content gates'), make('span', 'sg-road', 'Editorial - every road'));
    sec.appendChild(head);
    sec.appendChild(make('p', 'sg-says', 'The editorial gates. While the master is off none of them can refuse a line '
      + '(technical checks - missing media, incomplete takes - always bind). Turning one on asks for your approval.'));
    if (!c || !c.gates) { sec.appendChild(make('p', 'sg-says', 'Not available.')); return sec; }
    var grid = make('div', 'sg-rules');
    function toggle(name, label, on, tip) {
      var b = make('button', 'sg-rule' + (on ? ' on' : ''), (on ? 'On  ' : 'Off  ') + label);
      b.type = 'button'; b.title = tip || '';
      b.setAttribute('aria-pressed', String(on));
      b.addEventListener('click', function () {
        var body = {expected_revision: c.revision};
        if (name === 'master') {
          body.master_enabled = !on;
          body.gates = {};
          Object.keys(c.gates).forEach(function (k) { body.gates[k] = false; });
        } else {
          if (!c.master_enabled && !on) { say('Turn the master on first.'); return; }
          body.gates = {}; body.gates[name] = !on;
        }
        if (!on) {
          if (!b.classList.contains('armed')) {
            b.classList.add('armed'); b.textContent = 'Tap again to turn on: ' + label;
            root.setTimeout(function () { if (b.isConnected) { b.classList.remove('armed'); b.textContent = 'Off  ' + label; } }, 4000);
            return;
          }
          body.approval = 'enable';
        }
        post('/api/orchestrator/content-gates', body, label + (on ? ' off.' : ' on.'));
      });
      return b;
    }
    grid.appendChild(toggle('master', 'Master', !!c.master_enabled, 'Every content gate at once'));
    var inv = c.inventory || {};
    Object.keys(c.gates).forEach(function (k) {
      var info = inv[k], label = (info && (info.label || info.name)) || k.replace(/_/g, ' ');
      var tip = info && (info.description || info.says || (typeof info === 'string' ? info : '')) || '';
      grid.appendChild(toggle(k, label, !!c.gates[k], tip));
    });
    sec.appendChild(grid);
    return sec;
  }

  function gateSection(g) {
    var sec = make('section', 'sg-gate');
    var head = make('div', 'sg-head');
    head.append(make('b', '', g.name), make('span', 'sg-road', g.road));
    var reset = make('button', 'sg-reset', 'Reset');
    reset.type = 'button';
    reset.title = 'Put the station\'s own values back for this gate';
    reset.addEventListener('click', function () { post('/api/speech-gates', {gate: g.id, reset: true}, g.name + ': the station\'s own values.'); });
    head.appendChild(reset);
    sec.appendChild(head);
    sec.appendChild(make('p', 'sg-says', g.says));
    var st = g.stats || {};
    if (st.refused != null) {
      var by = Object.keys(st.by_road || {}).map(function (k) { return k + ' ' + st.by_road[k]; }).join(', ');
      sec.appendChild(make('p', 'sg-stat', 'Refused ' + st.refused + ' since the station started' + (by ? ' (' + by + ')' : '') + '.'));
    }
    if (st.block_rate != null) {
      sec.appendChild(make('p', 'sg-stat', 'Blocking ' + Math.round(st.block_rate * 100) + '% of the last ' + st.of_last + ' turns.'));
    }
    (g.params || []).forEach(function (p) {
      var row = make('label', 'sg-param' + (p.changed ? ' changed' : ''));
      var input = make('input');
      input.type = 'number'; input.min = p.min; input.max = p.max;
      input.step = p.type === 'int' ? '1' : '0.01';
      input.value = p.value == null ? '' : p.value;
      var text = make('span', 'sg-plabel', p.label);
      var hint = make('i', '', (p.says ? p.says + ' ' : '') + 'Range ' + p.min + '-' + p.max + '; station value ' + p.default
        + (p.changed ? ' (changed)' : '') + '.');
      input.addEventListener('change', function () {
        var v = Number(input.value);
        if (!isFinite(v)) { say('That is not a number.'); return; }
        post('/api/speech-gates', {gate: g.id, key: p.key, value: v}, g.name + ': ' + p.label + ' is now ' + v + '.');
      });
      row.append(text, input, hint);
      sec.appendChild(row);
    });
    if (g.rules && g.rules.length) {
      var grid = make('div', 'sg-rules');
      g.rules.forEach(function (r) {
        var b = make('button', 'sg-rule' + (r.on ? ' on' : ''), (r.on ? 'Refuses  ' : 'Allows  ') + r.label);
        b.type = 'button'; b.setAttribute('aria-pressed', String(r.on));
        b.title = r.on ? 'This rule refuses a line. Tap to let such lines through.' : 'Switched off. Tap to refuse such lines again.';
        b.addEventListener('click', function () {
          post('/api/speech-gates', {gate: g.id, rule: r.id, on: !r.on}, r.label + (r.on ? ': let through.' : ': refused again.'));
        });
        grid.appendChild(b);
      });
      sec.appendChild(grid);
    }
    return sec;
  }

  function paint() {
    if (!ui.body) return;
    ui.body.replaceChildren();
    ui.body.appendChild(contentSection());
    ((ui.data && ui.data.gates) || []).forEach(function (g) { ui.body.appendChild(gateSection(g)); });
    var more = make('section', 'sg-gate');
    more.appendChild(make('b', '', 'Edited elsewhere'));
    more.appendChild(make('p', 'sg-says', 'Banned words: the control panel\'s word bans (/api/dj/banned). Banned phrases: the script view\'s '
      + 'phrase ban (/api/phrase/ban). Phrase cooldowns and the repeat window: the control panel\'s "Never say it twice". '
      + 'A single line: forget it (/api/said/forget) or bin it from the script.'));
    ui.body.appendChild(more);
  }

  function build() {
    var p = make('section', 'sg-panel');
    p.setAttribute('role', 'dialog');
    p.setAttribute('aria-label', 'Speech gates');
    var head = make('div', 'sg-top');
    head.appendChild(make('b', '', 'SPEECH GATES'));
    head.appendChild(make('span', 'sg-sub', 'every check that can refuse the station\'s speech'));
    var x = make('button', 'sg-x', 'close');
    x.type = 'button';
    x.addEventListener('click', close);
    head.appendChild(x);
    ui.note = make('p', 'sg-note'); ui.note.setAttribute('role', 'status');
    ui.body = make('div', 'sg-body');
    p.append(head, ui.note, ui.body);
    p.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    document.body.appendChild(p);
    ui.panel = p;
    return p;
  }

  function open() {
    var p = ui.panel || build();
    p.hidden = false;
    say('Loading...');
    load('');
  }
  function close() { if (ui.panel) ui.panel.hidden = true; }

  root.PineSpeechGates = {open: open, close: close};
})(typeof window !== 'undefined' ? window : globalThis);
