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

  function start() {
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

  root.PineTabletDoctor = {heal: heal};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
