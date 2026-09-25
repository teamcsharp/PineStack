/* THE TABLET DOCTOR - find the tablet and reattach this app to it, from one
 * press.
 *
 * "Put a button here that allows me to locate on the network and reconnect
 *  to and reattach the application to the tablet" (#1096); "go to a
 *  troubleshooter to resolve the connection with the tablet over the
 *  network locating the tablet and pinging a connection to it and doing
 *  troubleshooting to force a connection no matter what. There should be
 *  fallback systems" (#1097); "scan and locate and identify and triage and
 *  locate and ping on the network this tablet" (#1109).
 *
 * Two halves that neither side could do alone. The station (#1367) knows
 * three things this app never did: whether the tablet has FETCHED the show
 * lately (a tablet that asked for the show three seconds ago is not
 * missing, whatever adb says), whether its address is in the neighbour
 * table, and whether its debugging port answers - and it can sweep the /24
 * for a tablet whose lease moved and adopt the new address. This app knows
 * the one thing the station cannot do: `adb connect`, which is the actual
 * attachment. The ladder here walks the station's rungs, then does the
 * connect, then asks the station to look again - so "attached" at the end
 * is measured, not assumed.
 *
 * Desktop only. The tablet cannot reattach itself to itself, so this file
 * is deliberately not in the tablet's bundle.
 */
(function (root) {
  'use strict';

  var busy = false;
  var lines = [];

  function api() { return root.pineDesktop || {}; }
  function ask(path) {
    return api().get ? api().get(path) : Promise.reject(new Error('no bridge'));
  }
  function post(path, body) {
    return api().post ? api().post(path, body || {}) : Promise.reject(new Error('no bridge'));
  }
  /* #1116: "Collapse the output for the tablet troubleshooter into an
   * icon." The transcript is still written in full to the <pre>, but the
   * <pre> is no longer un-hidden by writing to it. What appears instead is
   * the receipt icon (#tabletDocFold) beside the wrench; the operator opens
   * the transcript from there, and the choice is remembered in
   * localStorage['pineTabletDocOpen'] ('1'/'0') so a run that starts with
   * the transcript left open shows live, and one that starts with it shut
   * stays out of the way. */
  var DOC_OPEN_KEY = 'pineTabletDocOpen';
  function docOpenPref() {
    try { return localStorage.getItem(DOC_OPEN_KEY) === '1'; } catch (err) { return false; }
  }
  function rememberDocOpen(open) {
    try { localStorage.setItem(DOC_OPEN_KEY, open ? '1' : '0'); } catch (err) { /* private window; the choice lasts the session */ }
  }
  function setDocOpen(open) {
    var d = document.getElementById('tabletDoc');
    var f = document.getElementById('tabletDocFold');
    if (d) d.hidden = !open;
    /* 2026-09-14: the doctor is a diagnostic - the broadcast steps back to
       10% while its transcript is open. */
    try {
      if (window.PineDuck) {
        if (open && d) window.PineDuck.hold('tablet-doctor', window.PineDuck.REPORT);
        else window.PineDuck.release('tablet-doctor');
      }
    } catch (err) { /* no duck on this page */ }
    if (f) f.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  /* The icon's state: 'busy' while the ladder climbs, 'ok' when the last
   * run ended with the tablet here, 'bad' when it did not or the run
   * failed. The dot is CSS on the class; the title carries the one-line
   * verdict so a hover answers without opening the transcript. */
  function docState(state, brief) {
    var f = document.getElementById('tabletDocFold');
    if (!f) return;
    f.hidden = false;
    f.classList.remove('ok', 'bad', 'busy');
    if (state) f.classList.add(state);
    f.title = (brief ? brief + ' \u00b7 ' : '') + 'click for the troubleshooter\'s transcript';
  }
  function out(text) {
    var d = document.getElementById('tabletDoc');
    if (!d) return;
    d.textContent = text;
    /* Never un-hide the <pre> here - only honour a fold the operator left
     * open, so a live run shows only where it was wanted. */
    var f = document.getElementById('tabletDocFold');
    if (f) f.hidden = false;
    if (docOpenPref()) setDocOpen(true);
  }
  function tell(t) { lines.push(t); out(lines.join(String.fromCharCode(10))); }
  function mark(ok, t) { tell((ok ? '  ✓ ' : '  ✗ ') + t); }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function said(r) {
    if (!r) return 'no answer';
    return String(r.say || r.verdict || r.why || r.detail || JSON.stringify(r).slice(0, 140));
  }

  async function heal() {
    if (busy) return;
    busy = true;
    lines = [];
    var brief = document.getElementById('vitalsBrief');
    var verdict = 'ended without a verdict';   /* #1116: what the icon's title will say */
    var good = false;
    docState('busy', 'running');
    try {
      tell('$ locate the tablet');
      var look = await ask('/api/tablet/look');
      if (!look) { tell('  the station did not answer'); verdict = 'the station did not answer'; return; }
      (look.steps || []).forEach(function (s) { tell('  - ' + s); });
      tell('  verdict: ' + (look.verdict || ''));
      var host = String(look.host || '');

      if (look.cure === 'sweep') {
        tell('$ sweep the network for it');
        var sw = null;
        try { sw = await post('/api/tablet/doctor/sweep', {}); } catch (err) { sw = {ok: false, why: String(err && err.message || err)}; }
        mark(!!(sw && sw.ok), said(sw));
        var found = sw && (sw.host || sw.found || (sw.hosts && sw.hosts[0]));
        if (found && found !== host) {
          tell('$ adopt ' + found + ' as the tablet\'s address');
          var ad = null;
          try { ad = await post('/api/tablet/doctor/adopt', {host: found}); } catch (err) { ad = {ok: false, why: String(err && err.message || err)}; }
          mark(!!(ad && ad.ok), said(ad));
          if (ad && ad.ok) host = String(found);
        }
      }
      if (look.cure === 'wake' || look.cure === 'sweep') {
        tell('$ wake the kiosk (the station stamps it; this app carries it out)');
        var wk = null;
        try { wk = await post('/api/tablet/doctor/wake', {}); } catch (err) { wk = {ok: false, why: String(err && err.message || err)}; }
        mark(!!(wk && wk.ok), said(wk));
      }

      /* The one rung only this side can press. */
      tell('$ adb connect ' + host + ':5555');
      var c = null;
      try {
        if (typeof api().terminalWirelessConnect !== 'function') throw new Error('this app has no adb bridge');
        c = await api().terminalWirelessConnect(host, 5555);
      } catch (err) { c = {ok: false, why: String(err && err.message || err)}; }
      var attached = !!(c && (c.ok || c.connected || /connected/i.test(String(c.say || c.out || c.stdout || ''))));
      mark(attached, said(c));

      await wait(4000);
      tell('$ look again');
      var again = null;
      try { again = await ask('/api/tablet/look'); } catch (err) { again = null; }
      ((again && again.steps) || []).forEach(function (s) { tell('  - ' + s); });
      good = !!(again && again.fetching && again.adb_port_open);
      mark(good, good ? 'the tablet is here, playing the station, and its port answers'
                      : ((again && again.verdict) || 'still not there'));
      verdict = good ? 'attached' : ((again && again.verdict) || 'still not there');
      if (!good) {
        tell('  fallbacks, in order:');
        tell('   1. on the tablet, toggle Wi-Fi off and on - the station keeps sweeping and adopts a moved address');
        tell('   2. Reset in the DGX Terminal card re-enables wireless debugging over the cable');
        tell('   3. a force-stop of the kiosk clears a wedged net stack (docs/pinetab.md 19.1)');
      }
      if (brief && again) {
        brief.textContent = good ? 'attached'
          : (again.fetching ? 'playing, not attached'
             : again.on_network ? 'on the network, silent' : 'not on the network');
      }
    } catch (err) {
      tell('  failed: ' + String(err && err.message || err));
      verdict = 'failed: ' + String(err && err.message || err);
    } finally {
      busy = false;
      docState(good ? 'ok' : 'bad', verdict);
    }
  }

  /* ==== [#1209] THE FINDER =============================================
   *
   * "Put a searchable radio display up for the Pine tablet as well,
   *  allowing me to search and locate the Pine tablet on the network."
   *
   * The doctor above is a LADDER: it climbs on its own and prints a
   * transcript. This is a LIST: every device on the station's network,
   * what is known about each, and a click to say "that one is the
   * tablet". They answer different questions and both are wanted - the
   * ladder when it should just work, the list when it does not.
   *
   * The station does the looking (GET /api/tablet/find, on a thread: it
   * is 254 connects plus the neighbour table). This draws it, filters it
   * as you type, and posts the pick to the `use` rung.
   *
   * Built entirely from here, stylesheet included, so this file
   * hot-reloads off the share on its own - no index.html, no styles.css,
   * no relaunch.
   */
  var FIND_OPEN_KEY = 'pineTabletFindOpen';
  var findRows = [];
  var findSay = '';
  var findBusy = false;

  function findStyle() {
    if (document.getElementById('tabletFindStyle')) return;
    var s = document.createElement('style');
    s.id = 'tabletFindStyle';
    s.textContent = [
      '.tfind{padding:0 9px 9px;display:none}',
      '.vitals-box .tfind.on{display:block}',
      '.vitals-box.shut .tfind{display:none}',
      '.tfind-bar{display:flex;gap:5px;align-items:center;margin-bottom:5px}',
      '.tfind-bar input{flex:1;min-width:0;background:#070c11;border:1px solid #1b2831;',
      '  border-radius:4px;color:#cfe0ec;font:inherit;font-size:11px;padding:3px 6px}',
      '.tfind-bar button{background:#111922;border:1px solid #1b2831;border-radius:4px;',
      '  color:#9fb3c2;font:inherit;font-size:11px;padding:3px 7px;cursor:pointer}',
      '.tfind-bar button:hover{background:#17222c}',
      '.tfind-say{color:#7e94a6;font-size:10.5px;line-height:1.45;margin:0 0 5px}',
      '.tfind-list{max-height:210px;overflow:auto;display:flex;flex-direction:column;gap:3px}',
      '.tfind-row{display:block;width:100%;text-align:left;background:#0b1015;',
      '  border:1px solid #16212a;border-radius:4px;color:#9fb3c2;font:inherit;',
      '  font-size:11px;padding:4px 6px;cursor:pointer}',
      '.tfind-row:hover{background:#121b24;border-color:#24404f}',
      '.tfind-row.best{border-color:#2f6d4f;background:#0c1712}',
      '.tfind-row.mine{border-color:#7a5a1f}',
      '.tfind-row b{color:#cfe0ec;font-variant-numeric:tabular-nums}',
      '.tfind-row i{font-style:normal;color:#6d8294;margin-left:6px}',
      '.tfind-row em{display:block;font-style:normal;color:#6d8294;',
      '  font-size:10px;line-height:1.4;margin-top:2px}'
    ].join('');
    document.head.appendChild(s);
  }

  function findOpenPref() {
    try { return localStorage.getItem(FIND_OPEN_KEY) === '1'; } catch (err) { return false; }
  }
  function rememberFindOpen(open) {
    try { localStorage.setItem(FIND_OPEN_KEY, open ? '1' : '0'); } catch (err) { /* session only */ }
  }

  /* The list is a diagnostic surface, so the broadcast steps back to 10%
   * while it is open - the standing duck rule, same as the transcript. */
  function findDuck(open) {
    try {
      if (!window.PineDuck) return;
      if (open) window.PineDuck.hold('tablet-finder', window.PineDuck.REPORT);
      else window.PineDuck.release('tablet-finder');
    } catch (err) { /* no duck on this page */ }
  }

  function findBox() {
    findStyle();
    var box = document.getElementById('tabletFind');
    if (box) return box;
    var housing = document.getElementById('vitalsBox');
    if (!housing) return null;
    box = document.createElement('div');
    box.id = 'tabletFind';
    box.className = 'tfind';
    box.innerHTML = '<div class="tfind-bar">'
      + '<input id="tabletFindQ" type="search" placeholder="search the network…" '
      + 'title="Search every column at once: an address, part of a hardware address, '
      + 'a maker, a port, or a word like kiosk">'
      + '<button id="tabletFindGo" type="button" title="Scan the network again">scan</button>'
      + '</div><p class="tfind-say" id="tabletFindSay"></p>'
      + '<div class="tfind-list" id="tabletFindList"></div>';
    var doc = document.getElementById('tabletDoc');
    if (doc && doc.parentNode === housing) housing.insertBefore(box, doc);
    else housing.appendChild(box);
    var q = box.querySelector('#tabletFindQ');
    if (q) {
      q.addEventListener('input', function () { paintFind(); });
      q.addEventListener('keydown', function (ev) {
        ev.stopPropagation();                 /* the app's hot keys are global */
        if (ev.key === 'Enter') scanFind();
      });
    }
    var go = box.querySelector('#tabletFindGo');
    if (go) go.addEventListener('click', function (ev) { ev.stopPropagation(); scanFind(); });
    return box;
  }

  function setFindOpen(open) {
    var box = findBox();
    if (!box) return;
    box.classList.toggle('on', !!open);
    var b = document.getElementById('tabletFindBtn');
    if (b) b.setAttribute('aria-expanded', open ? 'true' : 'false');
    findDuck(!!open);
    if (open && !findRows.length && !findBusy) scanFind();
  }

  function findQuery() {
    var q = document.getElementById('tabletFindQ');
    return String((q && q.value) || '').trim().toLowerCase();
  }

  /* The station already searches, but it searches the answer it is about
   * to send. Filtering here as well means typing is instant and costs no
   * scan - the same rows, narrowed. */
  function findHit(row, want) {
    if (!want) return true;
    var hay = [row.host, row.mac, row.vendor, row.iface, row.agent, row.why,
               row.asked_for, row.port, Object.keys(row.ports || {}).join(' '),
               row.known ? 'remembered current known tablet' : '',
               row.kiosk ? 'kiosk pinetab tablet' : '']
      .join(' ').toLowerCase();
    return want.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function paintFind() {
    var list = document.getElementById('tabletFindList');
    var say = document.getElementById('tabletFindSay');
    if (!list) return;
    var want = findQuery();
    var rows = findRows.filter(function (r) { return findHit(r, want); });
    list.replaceChildren();
    if (!findRows.length) {
      if (say) say.textContent = findBusy ? 'looking at the network…'
        : 'press scan to look at the network.';
      return;
    }
    if (say && !findBusy) {
      say.textContent = (want
        ? rows.length + ' of ' + findRows.length + ' match “' + want + '”. '
        : '') + (findSay || '');
    }
    if (!rows.length) {
      var none = document.createElement('div');
      none.className = 'tfind-say';
      none.textContent = 'nothing on this network matches that.';
      list.appendChild(none);
      return;
    }
    rows.forEach(function (r) {
      var line = document.createElement('button');
      line.type = 'button';
      line.className = 'tfind-row'
        + ((r.score >= 40) ? ' best' : '')
        + (r.known ? ' mine' : '');
      var bits = [];
      if (r.mac) bits.push(r.mac);
      if (r.vendor) bits.push(r.vendor);
      if (r.open) bits.push('port ' + r.port + ' · ' + Math.round(r.ms) + 'ms');
      Object.keys(r.ports || {}).forEach(function (p) {
        bits.push('port ' + p + ' · ' + Math.round(r.ports[p]) + 'ms');
      });
      if (r.known) bits.push('the remembered tablet');
      var head = document.createElement('b');
      head.textContent = r.host;
      var tail = document.createElement('i');
      tail.textContent = bits.join(' · ');
      var why = document.createElement('em');
      why.textContent = r.why || '';
      line.appendChild(head); line.appendChild(tail); line.appendChild(why);
      line.title = r.known
        ? 'The station already uses this address.'
        : 'Use ' + r.host + ' as the tablet from now on.';
      line.onclick = function (ev) {
        ev.stopPropagation();
        useFind(r.host);
      };
      list.appendChild(line);
    });
  }

  async function scanFind() {
    if (findBusy) return;
    findBusy = true;
    var say = document.getElementById('tabletFindSay');
    if (say) say.textContent = 'looking at the network…';
    try {
      var got = await ask('/api/tablet/find?deep=1');
      findRows = (got && got.rows) || [];
      findSay = String((got && got.say) || '');
    } catch (err) {
      findRows = [];
      findSay = 'the station did not answer: ' + String(err && err.message || err);
    } finally {
      findBusy = false;
      paintFind();
    }
  }

  async function useFind(host) {
    var say = document.getElementById('tabletFindSay');
    try {
      var got = await post('/api/tablet/doctor/use', {host: host});
      findSay = String((got && got.say) || ('the tablet is ' + host + ' from now on'));
      findRows = findRows.map(function (r) {
        return Object.assign({}, r, {known: r.host === host});
      });
    } catch (err) {
      findSay = 'could not write that down: ' + String(err && err.message || err);
    }
    if (say) say.textContent = findSay;
    paintFind();
  }

  function wireFind() {
    var heal = document.getElementById('tabletHeal');
    if (!heal || document.getElementById('tabletFindBtn')) return;
    var b = document.createElement('button');
    b.id = 'tabletFindBtn';
    b.type = 'button';
    b.className = 'vitals-tool vitals-tool-2';
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', 'tabletFind');
    b.title = 'Find the tablet on the network: every device, searchable, '
      + 'with what is known about each. Click one to use it.';
    b.innerHTML = '<span data-pine-icon="c:search" aria-hidden="true"></span>';
    heal.parentNode.insertBefore(b, heal);
    /* The sprite painter walks the document for data-pine-icon; a node
     * added afterwards has to ask for itself. */
    try {
      if (typeof root.pineIcon === 'function') {
        b.firstChild.innerHTML = root.pineIcon('c:search') || '';
      }
    } catch (err) { b.textContent = 'find'; }
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var box = findBox();
      var open = !!(box && !box.classList.contains('on'));
      setFindOpen(open);
      rememberFindOpen(open);
    });
    if (findOpenPref()) setFindOpen(true);
  }

  function start() {
    wireFind();                                             /* [#1209] */
    var b = document.getElementById('tabletHeal');
    if (b && !b.__wired) {
      b.__wired = true;
      b.addEventListener('click', function (ev) { ev.stopPropagation(); heal(); });
    }
    /* #1116: the receipt icon opens and shuts the transcript, and the
     * choice is remembered for the next run. */
    var f = document.getElementById('tabletDocFold');
    if (f && !f.__wired) {
      f.__wired = true;
      f.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var d = document.getElementById('tabletDoc');
        var open = !!(d && d.hidden);
        setDocOpen(open);
        rememberDocOpen(open);
      });
    }
  }

  root.PineTabletDoctor = {heal: heal, find: scanFind,   /* [#1209] */
                           show: setFindOpen};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
