/* [airplayers] PLAYING IT: WHICH RECEIVERS SOUND THE STATION.
 *
 * Operator, 2026-09-29: "i want the buttons to redirect audio to be
 * responsive. i want to be able to enable and disable streams from there as
 * well by enabling them from receiving a broadcast. For example the nabu is
 * broadcasting. If it were listed, I would uncheck it from being audible and
 * enable the pinetab to be the active radio. Also I would turn off the pine
 * app audio for now since i am listening throuhg the pinetablet".
 *
 * A SET, not one: every receiver has its own "audible" switch - the PineTab,
 * this app, web pages, the car's tune-in link, the Nabu and the Pine Box
 * speaker - and "only" makes one of them the only one sounding in the house.
 * The station owns the answer (GET/POST /api/air/receivers); this paints it.
 *
 * WHY THE OLD LIST FELT DEAD, and what this does instead:
 *   - a tap showed nothing until a round trip came back, and the answer to
 *     a refused hand-over was painted as if it were a success. Here the
 *     row is pressed on pointerdown, switched and marked "sending" in the
 *     same frame as the tap, then painted from the station's own answer;
 *     a refusal or a network failure is said in words ON THE ROW.
 *   - a poll landing mid-tap repainted the old state over the new one. A
 *     row with a write in flight is never repainted by a poll.
 * Nothing here touches a volume: off is the station's routing switch, and
 * the page that is switched off mutes ITSELF (pineSoloGate, `hushed`).
 */
(function (root) {
  'use strict';

  var ROUTE = '/api/air/receivers';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function ago(s) {
    if (s == null || !isFinite(Number(s))) return '';
    s = Math.round(Number(s));
    return s < 90 ? s + 's ago' : Math.round(s / 60) + 'm ago';
  }

  function now() {
    return (root.performance && performance.now) ? performance.now() : Date.now();
  }

  function Panel(host, opts) {
    this.host = host;
    this.get = opts.get;
    this.post = opts.post;
    this.pollMs = opts.pollMs || 4000;
    this.state = null;
    this.pending = {};          /* receiver id -> {want, at} */
    this.errors = {};           /* receiver id -> words */
    this.times = [];            /* the harness reads these */
    this.timer = null;
    this.build();
  }

  Panel.prototype.build = function () {
    this.host.classList.add('air-recv');
    this.list = el('div', 'air-recv-list');
    this.list.setAttribute('role', 'list');
    this.note = el('p', 'air-recv-note', 'asking the station who is listening…');
    this.note.setAttribute('aria-live', 'polite');
    this.host.replaceChildren(this.list, this.note);
  };

  Panel.prototype.start = function () {
    var self = this;
    this.refresh();
    this.timer = setInterval(function () {
      if (document.hidden) return;
      self.refresh();
    }, this.pollMs);
    return this;
  };

  Panel.prototype.stop = function () {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  };

  Panel.prototype.refresh = function () {
    var self = this;
    return Promise.resolve(this.get(ROUTE)).then(function (state) {
      if (state && state.receivers) self.adopt(state, false);
    }, function (err) {
      if (!self.state) self.say('could not ask the station: ' + ((err && err.message) || err), true);
    });
  };

  /* The station's word replaces ours - except on a row with a write still
   * in flight, which only its own answer may repaint. */
  Panel.prototype.adopt = function (state, fromWrite) {
    if (!fromWrite && this.state && Object.keys(this.pending).length) {
      var keep = {};
      for (var i = 0; i < this.state.receivers.length; i += 1) {
        var r = this.state.receivers[i];
        if (this.pending[r.id]) keep[r.id] = r;
      }
      state = Object.assign({}, state, {
        receivers: state.receivers.map(function (r) { return keep[r.id] || r; })
      });
    }
    this.state = state;
    this.paint();
  };

  Panel.prototype.say = function (text, bad) {
    this.note.textContent = text;
    this.note.classList.toggle('bad', !!bad);
  };

  /* ROWS ARE UPDATED IN PLACE, NEVER REBUILT. Measured in the harness:
   * a poll that replaced the list while a button was held down took the
   * pressed node out of the page, so the release landed on a new node and
   * the click never fired - a tap that did nothing, one in a few. */
  Panel.prototype.paint = function () {
    var st = this.state || {receivers: []};
    var rows = st.receivers || [];
    this.nodes = this.nodes || {};
    var seen = {};
    for (var i = 0; i < rows.length; i += 1) {
      var r = rows[i];
      seen[r.id] = true;
      var n = this.nodes[r.id] || (this.nodes[r.id] = this.make(r.id));
      this.fill(n, r);
      if (this.list.children[i] !== n.line) this.list.insertBefore(n.line, this.list.children[i] || null);
    }
    for (var id in this.nodes) {
      if (!seen[id]) { this.nodes[id].line.remove(); delete this.nodes[id]; }
    }
    var anyBad = Object.keys(this.errors).length > 0;
    if (!anyBad) this.say(st.say || '', false);
  };

  Panel.prototype.current = function (id) {
    var rows = (this.state && this.state.receivers) || [];
    for (var i = 0; i < rows.length; i += 1) if (rows[i].id === id) return rows[i];
    return null;
  };

  Panel.prototype.make = function (id) {
    var self = this;
    var n = {};
    n.line = el('div', 'air-recv-row');
    n.line.setAttribute('role', 'listitem');
    n.line.dataset.id = id;
    n.sw = el('button', 'air-recv-switch');
    n.sw.type = 'button';
    n.sw.setAttribute('role', 'switch');
    n.sw.appendChild(el('i', 'knob'));
    var text = el('div', 'air-recv-text');
    n.name = el('b', 'air-recv-name');
    n.label = el('span', '');
    n.badge = el('span', 'air-recv-badge', 'active radio');
    n.name.append(n.label, n.badge);
    n.detail = el('span', 'air-recv-detail');
    n.err = el('span', 'air-recv-error');
    text.append(n.name, n.detail, n.err);
    n.only = el('button', 'air-recv-only', 'only');
    n.only.type = 'button';
    /* Pressed on the way DOWN, not on the click: a thumb gets its answer in
     * the frame it lands, before the browser has decided it was a tap. */
    [n.sw, n.only].forEach(function (b) {
      b.addEventListener('pointerdown', function () { b.classList.add('pressed'); });
      ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (ev) {
        b.addEventListener(ev, function () { b.classList.remove('pressed'); });
      });
    });
    n.sw.addEventListener('click', function () {
      var r = self.current(id);
      if (!r) return;
      var wait = self.pending[id];
      self.flip(r, !(wait ? wait.want : !!r.audible));
    });
    n.only.addEventListener('click', function () {
      var r = self.current(id);
      if (r) self.only(r);
    });
    n.line.append(n.sw, text, n.only);
    return n;
  };

  Panel.prototype.fill = function (n, r) {
    var wait = this.pending[r.id];
    var on = wait ? wait.want : !!r.audible;
    n.line.classList.toggle('on', on);
    n.line.classList.toggle('active', !!r.active);
    n.line.classList.toggle('away', !r.present && r.kind === 'page');
    n.line.classList.toggle('pending', !!wait);
    n.sw.setAttribute('aria-checked', on ? 'true' : 'false');
    n.sw.title = (on ? 'Stop ' : 'Let ') + r.label + (on ? ' sounding the station' : ' sound the station');
    n.sw.setAttribute('aria-label', r.label + ' audible');
    n.label.textContent = r.label;
    n.badge.hidden = !r.active;
    var bits = [];
    if (wait) bits.push(on ? 'switching on…' : 'switching off…');
    else if (r.kind === 'page' && on && !r.sounding && r.present) bits.push('switched on - another page holds the air');
    bits.push(r.detail || '');
    if (r.heard_ago != null) bits.push('heard ' + ago(r.heard_ago));
    n.detail.textContent = bits.filter(Boolean).join(' · ');
    n.err.textContent = this.errors[r.id] || '';
    n.err.hidden = !this.errors[r.id];
    n.only.title = 'Make ' + r.label + ' the only one sounding in the house';
    n.only.setAttribute('aria-label', n.only.title);
  };

  Panel.prototype.write = function (ids, want, body, label) {
    var self = this;
    var t0 = now();
    var mark = {id: ids[0], label: label, t0: t0};
    ids.forEach(function (id, i) {
      self.pending[id] = {want: want[i], at: t0};
      delete self.errors[id];
    });
    this.say('sending: ' + label + '…', false);
    this.paint();
    mark.painted = now() - t0;
    return Promise.resolve(this.post(ROUTE, body)).then(function (answer) {
      ids.forEach(function (id) { delete self.pending[id]; });
      if (!answer || !answer.receivers) throw new Error('the station gave no answer');
      if (answer.ok === false || answer.refused) {
        self.errors[ids[0]] = 'refused: ' + (answer.why || 'the station said no');
      }
      self.adopt(answer, true);
      if (self.errors[ids[0]]) self.say(self.errors[ids[0]], true);
      mark.confirmed = now() - t0;
      mark.ok = !self.errors[ids[0]];
      self.times.push(mark);
      return answer;
    }).catch(function (err) {
      ids.forEach(function (id) { delete self.pending[id]; });
      self.errors[ids[0]] = 'not changed - could not reach the station: ' + ((err && err.message) || err);
      self.paint();
      self.say(self.errors[ids[0]], true);
      mark.confirmed = now() - t0;
      mark.ok = false;
      self.times.push(mark);
    });
  };

  Panel.prototype.flip = function (r, want) {
    if (this.pending[r.id]) return;
    return this.write([r.id], [want], {id: r.id, audible: want},
      r.label + (want ? ' on' : ' off'));
  };

  Panel.prototype.only = function (r) {
    var rows = (this.state && this.state.receivers) || [];
    var house = rows.filter(function (x) { return x.id !== 'car'; });
    var ids = [r.id].concat(house.map(function (x) { return x.id; })
      .filter(function (id) { return id !== r.id; }));
    var want = ids.map(function (id) { return id === r.id; });
    return this.write(ids, want, {only: r.id}, 'only ' + r.label);
  };

  function mount(host, opts) {
    var panel = new Panel(host, opts || {});
    return panel.start();
  }

  /* The desktop: take over the old "Playing it" list, keep its card. */
  function mountDesktop() {
    var box = document.getElementById('playersBox');
    var bridge = root.pineDesktop;
    if (!box || !bridge || typeof bridge.get !== 'function') return null;
    var host = el('div', 'air-recv-host');
    box.appendChild(host);
    return Promise.resolve(bridge.get(ROUTE)).then(function (state) {
      if (!state || !state.receivers) { host.remove(); return null; }
      box.classList.add('air-recv-on');
      var panel = mount(host, {
        get: function (r) { return bridge.get(r); },
        post: function (r, body) { return bridge.post(r, body); }
      });
      panel.adopt(state, false);
      root.pineAirReceivers = panel;
      return panel;
    }, function () { host.remove(); return null; });
  }

  root.PineAirReceivers = {mount: mount, mountDesktop: mountDesktop, Panel: Panel};
  if (typeof document !== 'undefined' && document.getElementById &&
      document.getElementById('playersBox') && root.pineDesktop) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mountDesktop);
    } else {
      mountDesktop();
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
