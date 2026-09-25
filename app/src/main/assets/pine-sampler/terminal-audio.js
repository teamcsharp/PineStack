/* WHICH DEVICE IS MAKING THE NOISE, AND HOW LOUD.
 *
 * The station routes each stream to `box`, `here`, `both`, `off` or the
 * Nabu. `here` means "whichever browser is looking" - so with the app open
 * on the desk AND the tablet up, both play, at whatever volume each machine
 * happens to remember. There was no way to say "out loud on the tablet,
 * silent on the desk, and let me set the tablet's levels from the desk".
 *
 * So the station's routes are left exactly as they are, and a table of
 * DEVICES is kept beside them in settings (`terminals`, validated in
 * app.py by validate_terminals). One row per device:
 *
 *     pinetab  play=true   music .8  voice 1   addr 10.89.1.154
 *     desktop  play=false  music .6  voice .6  fallback=true
 *
 * Every client reads the same table and obeys its own row, which is what
 * makes the tablet's volume settable from the computer.
 *
 * THE HAND-OVER. The operator's rule, in his words: the tablet is primary,
 * and the desktop takes over "when i turn the tablet off or switch it's
 * broadcast off". Both halves of that matter and they are different:
 *
 *   - switched off  -> its row says play=false. Deliberate, instant.
 *   - turned off    -> the device simply stops being there.
 *
 * The second needs PRESENCE, and the station already keeps it: every poll
 * of /api/dj?listener=<id> lands in the listener roster with an addr and a
 * `seen` age (GET /api/radio/listeners). A terminal that has not been seen
 * for STALE_SECONDS is gone, and the fallback takes the air.
 *
 * The whole point of putting this in one tested function is that the two
 * clients cannot disagree. If the desktop thought the tablet was present
 * and the tablet thought it was absent, the show would play twice or not
 * at all.
 */
'use strict';

const STREAMS = ['music', 'voice', 'reply'];

/* Three missed polls. The panel polls every 4s, so a device that has not
 * been heard from in 15s has genuinely gone - a screen that blanked, a
 * tablet picked up and carried out of the room, a browser tab closed.
 * Shorter than this and a slow poll on a busy station hands the air back
 * and forth; much longer and a dark tablet holds a silent room. */
const STALE_SECONDS = 15;

/* An <audio> element THROWS above 1.0:
 *   IndexSizeError: The volume provided (1.6) is outside the range [0, 1]
 * The desktop gets away with a 1.6 voice level because it runs through a
 * Web Audio GainNode, which takes boost. The tablet does not, and the
 * exception meant the DJs were silent on it while music played - measured,
 * and the reason this clamp exists rather than trusting stored levels. */
function safeLevel(value, fallback) {
  const level = Number(value);
  if (!Number.isFinite(level)) return fallback === undefined ? 1 : fallback;
  return Math.max(0, Math.min(1, level));
}

function rowsOf(settings) {
  const table = (settings || {}).terminals;
  return table && typeof table === 'object' ? table : {};
}

/* Is this device currently listening? Matched on its chosen listener id
 * first and its address second - DHCP moves an address, a name does not. */
function presenceOf(row, listeners, stale) {
  const limit = Number.isFinite(stale) ? stale : STALE_SECONDS;
  const all = Array.isArray(listeners) ? listeners
    : (listeners && Array.isArray(listeners.listeners) ? listeners.listeners : []);
  let best = null;
  for (const seen of all) {
    const byId = row.listener && String(seen.listener || '') === String(row.listener);
    const byAddr = row.addr && String(seen.addr || '') === String(row.addr);
    if (!byId && !byAddr) continue;
    const age = Number(seen.seen);
    if (!Number.isFinite(age)) continue;
    if (!best || age < best.age) best = {age, listener: String(seen.listener || '')};
  }
  if (!best) return {present: false, seen: null, why: 'not in the listener roster'};
  if (best.age > limit) {
    return {present: false, seen: best.age,
      why: 'last heard from ' + Math.round(best.age) + 's ago'};
  }
  return {present: true, seen: best.age, listener: best.listener, why: ''};
}

/* Who should be making noise, and at what levels. Pure: hand it the
 * settings and the roster, get back a decision every client can act on. */
function decide(settings, listeners, options) {
  const opts = options || {};
  const stale = Number.isFinite(opts.stale) ? opts.stale : STALE_SECONDS;
  const table = rowsOf(settings);
  const rows = {};

  for (const [id, raw] of Object.entries(table)) {
    const row = raw && typeof raw === 'object' ? raw : {};
    const presence = presenceOf(row, listeners, stale);
    rows[id] = {
      id,
      name: String(row.name || id),
      wants: !!row.play,
      fallback: !!row.fallback,
      present: presence.present,
      seen: presence.seen,
      /* Kept even when present, so the takeover can SAY what went missing
       * rather than announcing itself with no reason attached. */
      gone: presence.why,
      levels: {
        music: safeLevel(row.music),
        voice: safeLevel(row.voice),
        reply: safeLevel(row.reply)
      },
      play: false,
      why: ''
    };
  }

  /* EXACTLY ONE ROOM.
   *
   * This used to let any number of rows play, on the reasoning that "the
   * box and the tablet together" was a legitimate thing to want. The
   * operator has since said otherwise, in as many words: "singularly the
   * PineTab or the Pine Box or the Nabu device, the app instance or the
   * application loaded on PC. Individually but never at the same time."
   *
   * So more than one row switched on is a FAULT, not a preference - and it
   * is resolved here rather than reported, because the alternative is two
   * rooms playing a few hundred milliseconds apart while a warning sits in
   * a panel nobody is looking at. The winner is chosen by id order so every
   * client resolves it identically; the losers say why they are quiet. */
  const wanting = Object.values(rows)
    .filter((row) => row.wants && row.present)
    .sort((a, b) => a.id.localeCompare(b.id));
  const live = wanting.slice(0, 1);
  for (const row of live) {
    row.play = true;
    row.why = wanting.length > 1
      ? 'switched on and present - and the only one of ' + wanting.length
        + ' allowed to sound, because the show goes to one place'
      : 'switched on and present';
  }
  for (const row of wanting.slice(1)) {
    row.why = 'switched on, but ' + live[0].name
      + ' has the room - the show goes to one place at a time';
  }
  const contested = wanting.length > 1;

  /* Nothing on the air. Whoever is marked fallback and is here takes it -
   * this is the half of the rule that fires when a tablet is turned off
   * rather than switched off, and it is why presence is tracked at all. */
  let takeover = null;
  if (!live.length) {
    takeover = Object.values(rows)
      .filter((row) => row.fallback && row.present)
      .sort((a, b) => a.id.localeCompare(b.id))[0] || null;
    if (takeover) {
      takeover.play = true;
      const missing = Object.values(rows).filter((row) => row.wants && !row.present);
      takeover.why = missing.length
        ? 'took over - ' + missing.map((r) => r.name + ' ' + r.gone).join(', ')
        : 'took over - nothing else is set to play';
    }
  }

  const playing = Object.values(rows).filter((row) => row.play).map((row) => row.id);
  return {
    rows,
    playing,
    /* Never more than one, by construction. Asserted rather than assumed,
     * because this is the single promise the whole table exists to keep. */
    singular: playing.length <= 1,
    /* True when the operator has more than one device switched on and this
     * silenced the extras. Worth saying in a panel; not worth waiting for. */
    contested,
    takeover: takeover ? takeover.id : '',
    silent: !playing.length,
    stale
  };
}

/* What THIS client should do, from the same decision everyone else reads.
 * A device with no row stays quiet: a machine that has never been given a
 * row has not been asked to play anything, and guessing otherwise is how a
 * show ends up in an empty room. */
function forMe(decision, me) {
  const row = decision && decision.rows ? decision.rows[me] : null;
  if (!row) {
    return {play: false, music: 0, voice: 0, reply: 0,
      why: 'this device has no row in the table'};
  }
  return {
    play: row.play,
    music: row.play ? row.levels.music : 0,
    voice: row.play ? row.levels.voice : 0,
    reply: row.play ? row.levels.reply : 0,
    why: row.why || (row.wants ? 'switched on but not present' : 'switched off')
  };
}

/* Set one device's levels or switch, returning the WHOLE settings document
 * ready to PUT - app.py:82506 replaces the document, so a partial write
 * would silently drop every other setting. */
function update(settings, id, patch) {
  const name = String(id || '').trim().toLowerCase();
  if (!name) return {ok: false, blockers: ['No terminal named.']};
  const next = Object.assign({}, settings || {});
  const table = Object.assign({}, rowsOf(next));
  const row = Object.assign({}, table[name] || {});
  if ('play' in patch) row.play = !!patch.play;
  if ('fallback' in patch) row.fallback = !!patch.fallback;
  if ('name' in patch) row.name = String(patch.name || name).slice(0, 60);
  if ('addr' in patch) row.addr = String(patch.addr || '').slice(0, 60);
  if ('listener' in patch) row.listener = String(patch.listener || '').slice(0, 60);
  for (const stream of STREAMS) {
    if (stream in patch) row[stream] = safeLevel(patch[stream]);
  }
  row.at = Date.now();
  table[name] = row;
  next.terminals = table;
  return {ok: true, settings: next, row};
}

const api = {
  decide, forMe, update, presenceOf, safeLevel, rowsOf,
  STREAMS, STALE_SECONDS
};

/* This file is loaded TWICE, deliberately: by Node in the desktop's main
 * process, and as a plain <script> inside the tablet's WebView. The whole
 * point of the routing table is that both ends reach the same answer from
 * the same two documents, and the only way to guarantee that is for them to
 * run the same bytes. Hence the guard rather than a second copy. */
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.PineTerminalTable = api;
