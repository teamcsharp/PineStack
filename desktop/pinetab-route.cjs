/* WHERE THE BROADCAST GOES - ONE PLACE, NEVER TWO.
 *
 * The operator's rule, stated plainly: "my goal is to have the broadcast
 * going to singularly the PineTab or the Pine Box or the Nabu device, the
 * app instance or the application loaded on PC. Individually but never at
 * the same time."
 *
 * That is a stronger rule than the station's own model, and the difference
 * is the whole reason this file exists.
 *
 * WHY THE STATION CANNOT SAY IT ALONE. Each stream routes to one of `box`,
 * `here`, `both`, `off` or `nabu` (app.py:93361). Two of those five break
 * the rule on their own:
 *
 *   `both` is box AND a page, by definition. It cannot be singular.
 *   `here` means EVERY browser looking at the station - and the tablet, the
 *          Electron app and any web page open on the PC are all "here"
 *          clients. Routing to `here` with three of them up plays the show
 *          three times, a few hundred milliseconds apart. That is what "I'm
 *          hearing a different broadcast coming out of the application than
 *          out of the Pine Box tab" actually was.
 *
 * So a destination is TWO decisions, and both have to be made together or
 * the rule leaks:
 *
 *   1. the route      - POST /api/dj/output, one value for all three streams
 *   2. who owns the air - POST /api/radio/solo (#1008, app.py:93246), which
 *                       hands ONE listener the air and gags every other page
 *
 * EXCLUSIVITY IS BY CONSTRUCTION HERE, not by discipline. A route is a
 * single value, so at most one of {box, nabu, pages} can sound; and when
 * the route is `here`, exactly one listener id holds the air. There is no
 * combination of the two that produces two rooms. `both` is deliberately
 * not offered: it is the one route that cannot be singular, and leaving it
 * in the picker would mean the picker could break its own rule.
 *
 * TELLING THE PAGES APART. The roster (GET /api/radio/listeners) gives an
 * addr and a listener id per player. Two discriminators, both measured
 * against the live station:
 *
 *   - the station labels the collapsed physical endpoint as `desktop` or
 *     `pinetab`
 *   - old stations fall back to the Electron id prefix and terminal address
 *
 * A listener id is NOT an identity: it is minted fresh on every page load.
 * Measured across three relaunches of the tablet app: pbnvgdtefn, then
 * pbq8gj5qvq, then another. So nothing durable is ever stored against one.
 * The durable statement is the DESTINATION, kept in settings, and the
 * listener id is re-resolved from the roster every time it is needed.
 *
 * NOTE on writing settings: PUT /api/settings REPLACES the document
 * (app.py:82506 hands the payload straight to save_settings). Every write
 * here is read-modify-write. Never PUT a partial settings object.
 */
'use strict';

const STREAMS = ['music', 'voice', 'reply'];

/* The Electron app's listener id prefix. renderer.js mints
 * `desktop-${random}`, which makes the app self-identifying in the roster
 * without any configuration. */
const APP_PREFIX = 'desktop-';

/* The five sinks and Off.
 *
 * `to`   the route all three streams get.
 * `page` when set this destination is a PAGE and needs a solo owner; the
 *        value names WHICH page, resolved against the roster.
 * `row`  the `terminals` row this destination is, or '' for none.
 *
 * `page` and `row` are separate on purpose, and the difference is not
 * cosmetic. A page is identified LIVE, from the roster - by an id prefix
 * for the app, by address for the tablet. A row is a durable settings key
 * that predates this picker, and the app's row has always been called
 * `desktop`. Folding the two together silently left every device row set
 * to play:false when the app was chosen, because 'app' never matched
 * 'desktop'. The map is written out rather than inferred.
 */
const DESTINATIONS = {
  pinetab: {to: 'here', page: 'pinetab', row: 'pinetab', label: 'PineTab',
    why: 'The tablet plays it. Everything else is silent.'},
  app: {to: 'here', page: 'app', row: 'desktop', label: 'This app',
    why: 'The Pine Box app on this PC plays it. Everything else is silent.'},
  box: {to: 'box', page: '', row: '', label: 'Pine Box',
    why: 'The box speaker plays it. No page sounds.'},
  nabu: {to: 'nabu', page: '', row: '', label: 'Nabu',
    why: 'The Nabu device plays it. No page sounds.'},
  off: {to: 'off', page: '', row: '', label: 'Off',
    why: 'Nothing plays it anywhere.'}
};

function destinations() {
  return Object.entries(DESTINATIONS).map(([key, value]) =>
    ({key, label: value.label, why: value.why, route: value.to,
      page: !!value.page}));
}

/* ---- reading the roster -------------------------------------------- */

function rosterRows(roster) {
  if (Array.isArray(roster)) return roster;
  const rows = (roster || {}).listeners;
  return Array.isArray(rows) ? rows : [];
}

function ownerOf(roster) {
  return String((roster || {}).audio_owner || '');
}

/* Which `terminals` row a player is, matched on address. A row that names a
 * listener will not be matched by address to anything else: two tabs on one
 * machine share an address - the Electron app and a browser window both sat
 * on 10.89.1.13 when this was written - so an address alone cannot tell
 * them apart. */
function deviceOf(terminals, row) {
  const named = String((row || {}).device || '');
  if (named) return named;
  const addr = String(row.addr || '');
  const listener = String(row.listener || '');
  let byAddr = '';
  for (const [key, entry] of Object.entries(terminals || {})) {
    const pinned = String((entry || {}).listener || '');
    if (pinned) {
      if (pinned === listener) return key;
      continue;
    }
    if (addr && String((entry || {}).addr || '') === addr && !byAddr) byAddr = key;
  }
  return byAddr;
}

/* Which player IS this destination, right now. Returns a listener id, or ''
 * when that page is not currently looking at the station. */
function playerFor(page, roster, settings) {
  const terminals = ((settings || {}).terminals) || {};
  const rows = rosterRows(roster);
  const fresh = (row) => {
    const seen = Number(row.seen);
    return !Number.isFinite(seen) || seen <= 30;
  };
  const app = (row) => String(row.listener || '').startsWith(APP_PREFIX);

  if (page === 'app') {
    const found = rows.filter((row) =>
      (String(row.device || '') === 'desktop' || app(row)) && fresh(row));
    return found.length ? String(found[0].listener) : '';
  }
  if (page === 'pinetab') {
    const found = rows.filter((row) =>
      deviceOf(terminals, row) === 'pinetab' && fresh(row));
    return found.length ? String(found[0].listener) : '';
  }
  return '';
}

/* ---- where it is going now ------------------------------------------ */

function currentDestination(state, settings, roster) {
  const routes = STREAMS.map((stream) =>
    String((state || {})[stream + '_to'] || '')).filter(Boolean);

  /* Streams pointing different ways is reachable through the per-stream
   * selects. It is not one of the destinations, and saying so is more
   * honest than picking a winner - it is also the state that plays the show
   * in two rooms, so it is worth naming. */
  const agreed = routes.length && routes.every((route) => route === routes[0])
    ? routes[0] : '';
  if (!agreed) {
    return {key: '', label: 'Mixed', route: '', singular: false,
      why: 'The three streams are routed differently. That can sound in more than one place at once.'};
  }

  if (agreed === 'both') {
    return {key: '', label: 'Pine Box + a page', route: 'both', singular: false,
      why: 'The box AND a page are both sounding. Pick one destination to stop that.'};
  }

  for (const [key, value] of Object.entries(DESTINATIONS)) {
    if (value.to !== agreed) continue;
    if (!value.page) {
      return {key, label: value.label, route: agreed, singular: true, why: value.why};
    }
  }

  /* Routed to a page. WHICH page is decided by the air owner, so the answer
   * is only singular if somebody actually holds it. */
  const owner = ownerOf(roster);
  if (!owner) {
    const playing = rosterRows(roster).length;
    return {key: '', label: 'Every page', route: 'here', singular: playing <= 1,
      why: playing > 1
        ? playing + ' pages are sounding at once. Pick one destination.'
        : 'One page is looking, so only one is sounding.'};
  }
  for (const page of ['pinetab', 'app']) {
    if (playerFor(page, roster, settings) === owner) {
      const value = DESTINATIONS[page];
      return {key: page, label: value.label, route: 'here', singular: true,
        why: value.why};
    }
  }
  return {key: '', label: 'A page', route: 'here', singular: true,
    why: 'One page holds the air, but it is not a device this app knows.'};
}

/* ---- changing it ---------------------------------------------------- */

/* The calls a destination change needs, as data. The caller makes them;
 * this decides what they are, so the decision stays testable without a
 * station on the other end.
 *
 * ORDER MATTERS and the caller must keep it: claim the air FIRST, then move
 * the route. The other way round there is a window where the show is routed
 * to a page and no page believes it is the sink, which is silence - the one
 * outcome worse than playing in the wrong room.
 */
function planFor(key, settings, roster) {
  const chosen = DESTINATIONS[key];
  if (!chosen) {
    return {ok: false, blockers: ['Unknown destination: ' + String(key)]};
  }

  const output = {};
  for (const stream of STREAMS) output[stream] = chosen.to;

  /* Read-modify-write, because the PUT replaces the document. The
   * destination is the durable statement - not the listener id, which is
   * minted fresh on every page load. */
  const next = Object.assign({}, settings || {});
  next.pinetab = Object.assign({}, next.pinetab || {}, {
    audio: chosen.page === 'pinetab',
    at: Date.now()
  });
  next.broadcast_to = key;

  /* Every device's row follows the one destination, so nothing is left
   * switched on behind the operator's back. */
  const terminals = Object.assign({}, next.terminals || {});
  for (const [id, row] of Object.entries(terminals)) {
    terminals[id] = Object.assign({}, row, {play: id === chosen.row});
  }
  next.terminals = terminals;

  let solo = null;
  const blockers = [];
  if (chosen.page) {
    const listener = playerFor(chosen.page, roster, settings);
    if (listener) {
      solo = {listener};
    } else {
      /* Refuse rather than route to `here` with nobody holding the air:
       * that is exactly the state where every page sounds at once. */
      return {ok: false, destination: key, blockers: [
        chosen.label + ' is not looking at the station right now, so it '
        + 'cannot be given the air. Open it and try again.']};
    }
  } else {
    /* Not a page destination. Release the air so a stale owner cannot gag
     * the house, or claim it, the next time a page destination is picked. */
    solo = {clear: true};
  }

  return {
    ok: true,
    destination: key,
    label: chosen.label,
    why: chosen.why,
    blockers,
    /* POST /api/radio/solo - FIRST */
    solo,
    /* POST /api/dj/output */
    output,
    /* PUT /api/settings - the WHOLE document */
    settings: next,
    /* True when this app is not the destination and must stay quiet. */
    muteThisApp: chosen.page !== 'app'
  };
}

/* Whether the tablet should be making noise. Deliberately the same function
 * the desktop uses, so the two cannot drift into disagreeing about who is
 * the sink. */
function tabShouldPlay(state, settings, roster) {
  const now = currentDestination(state, settings, roster);
  if (now.key === 'pinetab') {
    return {play: true, why: 'The PineTab is the destination.'};
  }
  if (now.key) {
    return {play: false, why: now.label + ' is the destination, not the PineTab.'};
  }
  return {play: false, why: now.why};
}

const api = {
  destinations, currentDestination, planFor, tabShouldPlay,
  playerFor, deviceOf, STREAMS, DESTINATIONS, APP_PREFIX
};

if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.PineBroadcastTo = api;
