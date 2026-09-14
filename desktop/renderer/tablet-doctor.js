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
  function out(text) {
    var d = document.getElementById('tabletDoc');
    if (!d) return;
    d.hidden = false;
    d.textContent = text;
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
    try {
      tell('$ locate the tablet');
      var look = await ask('/api/tablet/look');
      if (!look) { tell('  the station did not answer'); return; }
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
      var good = !!(again && again.fetching && again.adb_port_open);
      mark(good, good ? 'the tablet is here, playing the station, and its port answers'
                      : ((again && again.verdict) || 'still not there'));
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
    } finally {
      busy = false;
    }
  }

  function start() {
    var b = document.getElementById('tabletHeal');
    if (b && !b.__wired) {
      b.__wired = true;
      b.addEventListener('click', function (ev) { ev.stopPropagation(); heal(); });
    }
  }

  root.PineTabletDoctor = {heal: heal};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
