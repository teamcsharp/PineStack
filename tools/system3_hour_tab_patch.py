#!/usr/bin/env python3
"""[hour-tab] The System 3 window's Hour tab (wave I of the Hour Director, docs/system3-hour-director-plan.md s.8).

The hour as a road of legs: the current hour and the next ones, each entry a node with its instruction, minutes,
enabled, move, insert after, remove, and its inner shape (PineHourFlow). The director's legs add the leg on air,
the row booked and the ledger of why, and the engine switch asks before it switches. While the director is not on
the station the tab is the sheet editor. 2026-10-06.

Edits:
  frontend/system3.js            the Hour tab (makeHourTab), its tab in the row, the router, the window's dispose.
  frontend/system3.css           the Hour tab's styles (appended).
  desktop/renderer/renderer.js   worksSchedule: the line "Edited in the System 3 window's Hour tab now" and its button.
  desktop/renderer/script-page.js the window opens on the desk's event; the ?v= of system3.js and system3.css
                                 (the window's script is loaded at these two places, both bumped).

Usage:  system3_hour_tab_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        system3_hour_tab_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

BLOCK = r"""/* [hour-tab] THE HOUR AS A ROAD OF LEGS - the System 3 window's Hour tab (wave I, the Hour Director).
 *
 * The sheet stays the store. Entries are read and saved through the schedule APIs: GET /api/schedule/hours
 * (the hours), POST /api/schedule/hours (the whole list of one hour), POST /api/schedule/hours/{key}/prompt
 * (one entry's instruction), GET /api/schedule/kinds. When the Hour Director is the engine (system3), each leg
 * adds what the director did with the entry: GET /api/system3/hour?hour=<key> gives the leg on air, the row
 * booked and the ledger of why. GET and POST /api/system3/engine switch the engine, and a switch asks first.
 * While the director is not on the station (404, or the engine is not system3) this tab is the sheet editor and
 * says the director is not on this station yet. Nothing here scrolls: a repaint keeps the reader's place and the
 * on-air leg is lit, never brought into view. The hour's own dice open the Tables tab on their table. */
const HOUR_DYNAMIC = {book_time: 'Book Time window', sfx_supercut: 'Station supercut window'};
const HOUR_ENGINES = [['legacy', 'Legacy clock'], ['system2', 'System 2'], ['system3', 'System 3']];
const HOUR_DICE = [['HOUR1', 'When the sheet is silent'], ['HOUR2', 'Quota pressure'], ['HOUR3', 'The jam']];
const HOUR_DERIVED = ['state', 'past', 'prep', 'slot_prep', 'starts_epoch', 'ends_epoch'];

function hourIcon(name) {
  const span = el('span', {class: 's3-hour-ic', 'aria-hidden': 'true'});
  if (typeof window.pineIcon === 'function') span.innerHTML = window.pineIcon(name) || '';
  return span;
}
function hourButton(text, onclick, o = {}) {
  const extra = {class: 's3-hour-btn' + (o.cls ? ' ' + o.cls : ''), title: o.title || text || 'button',
    'aria-label': o.title || text || 'button'};
  if (o.pressed !== undefined) extra['aria-pressed'] = String(!!o.pressed);
  const b = btn(text, onclick, extra);
  if (o.icon) b.prepend(hourIcon(o.icon));
  if (o.disabled) b.disabled = true;
  return b;
}
const hourClock = t => (typeof t === 'number' || /^\d+(\.\d+)?$/.test(String(t == null ? '' : t)) ? clock(Number(t)) : String(t == null ? '' : t));
const hourSince = s => (s == null || s === '' ? '-' : typeof s === 'number' ? day(s) : String(s));

function makeHourTab({request, scroll = () => null, busy = () => false, active = () => true, openTable = () => {},
  notice = () => {}, report = () => {}} = {}) {
  const root = el('div', {class: 's3-hour', 'data-tab': 'hour'});
  const state = {hours: [], key: '', hour: null, hourErr: '', engine: null, engineErr: '', kinds: [],
    loadedAt: 0, inserting: ''};
  const drafts = new Map();                       /* an instruction being typed, kept across repaints */
  let token = 0, alive = true;
  const post = (path, body) => request(path, {method: 'POST', body: JSON.stringify(body)});
  const kindLabel = kind => { const k = state.kinds.find(x => x.kind === kind); return k ? (k.label || kind) : String(kind || ''); };
  const currentRow = () => state.hours.find(h => h.key === state.key) || null;
  const directorLive = () => !!(state.hour && Array.isArray(state.hour.legs)
    && (!state.hour.engine || state.hour.engine === 'system3'));
  const legOf = id => (directorLive() ? state.hour.legs : []).find(l => l.id === id) || null;
  const instructionOf = (s, leg) => (leg && leg.act ? String(leg.act) : String(s.flow_prompt || ''));
  const editing = () => {
    const a = document.activeElement;
    return (!!a && root.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) || !!document.querySelector('.s3-hour-back');
  };

  /* ---- reading: the hours, the engine, one hour's legs - each answer on its own ---- */
  async function loadAll() {
    const mine = ++token;
    try {
      const hours = await request('/api/schedule/hours?count=6');
      state.hours = (hours && hours.hours) || [];
      if (!state.hours.some(h => h.key === state.key)) {
        const now = state.hours.find(h => h.is_now) || state.hours[0];
        state.key = now ? now.key : '';
      }
    } catch (e) { report(e); }
    const ask = p => request(p).then(v => ({v, err: ''}), e => ({v: null, err: (e && e.message) || String(e)}));
    const [engine, hour, kinds] = await Promise.all([
      ask('/api/system3/engine'),
      state.key ? ask('/api/system3/hour?hour=' + encodeURIComponent(state.key)) : Promise.resolve({v: null, err: ''}),
      state.kinds.length ? Promise.resolve({v: state.kinds, err: ''}) : ask('/api/schedule/kinds'),
    ]);
    if (!alive || mine !== token) return;
    state.engine = engine.v; state.engineErr = engine.err;
    state.hour = hour.v; state.hourErr = hour.err;
    if (Array.isArray(kinds.v) && kinds.v.length) state.kinds = kinds.v;
    state.loadedAt = Date.now();
    paint();
  }

  /* ---- painting: the whole tab is rebuilt, and the reader's scroll place is kept ---- */
  function paint() {
    const box = scroll();
    const top = box ? box.scrollTop : 0;
    fill(root, topBar(), sheet());
    if (box && box.scrollTop !== top) box.scrollTop = top;
  }
  function topBar() {
    return el('div', {class: 's3-hour-top'}, engineBar(), hourPicker(), diceBar());
  }
  function engineBar() {
    const eng = state.engine;
    if (!eng) {
      return el('div', {class: 's3-hour-engine s3-hour-off', role: 'status'},
        el('b', {text: 'The Hour Director is not on this station yet.'}),
        ' This tab is the sheet editor. ',
        el('span', {class: 's3-muted', text: state.engineErr ? '(' + state.engineErr + ')' : ''}));
    }
    const cur = String(eng.engine || '');
    const fallback = !!eng.fallback;
    return el('div', {class: 's3-hour-engine'},
      el('div', {class: 's3-hour-line'},
        el('span', {class: 's3-muted', text: 'Engine'}),
        HOUR_ENGINES.map(([id, label]) => hourButton(label, () => askEngine(id, fallback),
          {cls: 'eng' + (cur === id ? ' on' : ''), pressed: cur === id, title: 'Engine: ' + label}))),
      el('label', {class: 's3-hour-fb'},
        el('input', {type: 'checkbox', checked: fallback, onchange: e => askEngine(cur, e.target.checked)}),
        ' fallback to the legacy chain'),
      el('div', {class: 's3-muted', text: 'since ' + hourSince(eng.since)}),
      el('div', {class: 's3-hour-say', text: String(eng.say || '')}));
  }
  function hourPicker() {
    return el('div', {class: 's3-hour-pick', role: 'group', 'aria-label': 'hours'},
      state.hours.map(h => hourButton(h.label + (h.is_now ? ' now' : '') + (h.overridden ? ' own' : ''), () => {
        state.key = h.key; state.inserting = ''; loadAll();
      }, {cls: 'hr' + (h.key === state.key ? ' on' : ''), pressed: h.key === state.key,
        title: h.key + (h.overridden ? ' - its own orders' : ' - running the plan')})));
  }
  function diceBar() {
    return el('div', {class: 's3-hour-dice'},
      el('span', {class: 's3-muted', text: 'The hour\'s dice'}),
      HOUR_DICE.map(([id, words]) => hourButton(id + ' - ' + words, () => openTable(id),
        {title: id + ': ' + words + ' - the Tables tab, on this table'})));
  }
  function sheet() {
    const row = currentRow();
    if (!row) return el('p', {class: 's3-muted', text: 'No hour to show. The schedule did not answer.'});
    return el('div', {class: 's3-hour-body'}, directorNote(), road(row, row.slots || []));
  }
  function directorNote() {
    if (directorLive() || !state.engine) return null;
    if (state.engine.engine !== 'system3') {
      return el('div', {class: 's3-muted', text: 'The director is not the engine (engine ' + (state.engine.engine || '?')
        + '). The entries below are the sheet\'s own; the legs and the ledger show when the engine is System 3.'});
    }
    return el('div', {class: 's3-muted', text: 'The legs of this hour could not be read'
      + (state.hourErr ? ' (' + state.hourErr + ')' : '') + '. The entries below are the sheet\'s own.'});
  }
  function road(row, slots) {
    const start = el('div', {class: 's3-hour-start'},
      hourIcon('c:time'),
      el('b', {text: row.label + ' - the hour'}),
      el('span', {class: 's3-muted', text: (row.preset ? ' preset ' + row.preset : '')
        + (row.overridden ? ' - its own orders' : ' - running the plan')
        + (row.is_now ? ' - on air now' : row.is_past ? ' - gone by' : '')}),
      hourButton('Insert first', () => { state.inserting = '@top'; paint(); },
        {icon: 'c:add', title: 'Insert an entry at the top of this hour'}));
    const nodes = [];
    if (state.inserting === '@top') nodes.push(insertForm(-1));
    slots.forEach((s, i) => {
      nodes.push(entryNode(s, i, slots));
      if (state.inserting === s.id) nodes.push(insertForm(i));
    });
    if (!slots.length) nodes.push(el('p', {class: 's3-muted', text: 'This hour has no entries yet.'}));
    return el('div', {class: 's3-hour-road', 'aria-label': 'the hour, entry by entry'}, start, nodes);
  }
  function insertForm(i) {
    const sel = el('select', {class: 's3-hour-sel', 'aria-label': 'kind of the new entry', title: 'kind of the new entry'},
      state.kinds.map(k => el('option', {value: k.kind, text: k.label || k.kind})));
    return el('div', {class: 's3-hour-insert'},
      el('span', {class: 's3-muted', text: 'new entry, kind'}), sel,
      hourButton('Insert', () => insertAfter(i, sel.value), {icon: 'c:checkmark', cls: 'primary', title: 'Insert the entry'}),
      hourButton('Cancel', () => { state.inserting = ''; paint(); }, {icon: 'c:close--filled', title: 'Cancel'}));
  }
  function entryNode(s, i, slots) {
    const leg = legOf(s.id);
    const kind = String(s.kind || '');
    const dyn = (leg && leg.dynamic_kind) || (HOUR_DYNAMIC[kind] ? kind : '');
    const onAir = !!((leg && leg.on_air) || s.state === 'on air');
    const inner = Array.isArray(s.flow) && s.flow.length > 0;
    const enabled = s.enabled !== false;
    const ta = el('textarea', {rows: '2', value: drafts.has(s.id) ? drafts.get(s.id) : instructionOf(s, leg),
      'aria-label': 'standing instruction for this entry', title: 'the standing instruction for this entry',
      oninput: e => drafts.set(s.id, e.target.value)});
    return el('div', {class: 's3-hour-node' + (onAir ? ' on-air' : '') + (inner ? ' inner' : '') + (enabled ? '' : ' off'),
        'data-slot': String(s.id || '')},
      el('div', {class: 's3-hour-nhead'},
        el('span', {class: 's3-hour-idx', text: String(i + 1)}),
        el('b', {text: s.label || kindLabel(kind)}),
        el('span', {class: 's3-hour-chip', text: kindLabel(kind)}),
        dyn ? el('span', {class: 's3-hour-chip dyn', text: HOUR_DYNAMIC[dyn] || 'Dynamic window',
          title: 'a dynamic window: it takes its own segment door'}) : null,
        onAir ? el('span', {class: 's3-hour-chip air', text: 'on air'}) : null,
        inner ? el('span', {class: 's3-hour-chip', text: 'own inner shape'}) : null),
      el('div', {class: 's3-hour-ctl'},
        el('label', {class: 's3-hour-mins'}, el('span', {text: 'minutes '}),
          el('input', {type: 'number', min: '0.25', max: '600', step: '0.25', value: String(s.minutes),
            'aria-label': 'minutes', title: 'minutes for this entry', onchange: e => setMinutes(i, e.target.value)})),
        el('label', {class: 's3-hour-en'},
          el('input', {type: 'checkbox', checked: enabled, onchange: e => setEnabled(i, e.target.checked)}),
          el('span', {text: ' enabled'})),
        hourButton('', () => move(i, -1), {icon: 'c:arrow--up', title: 'Move up', disabled: i === 0}),
        hourButton('', () => move(i, 1), {icon: 'c:arrow--up', cls: 'down', title: 'Move down', disabled: i === slots.length - 1}),
        hourButton('', () => { state.inserting = s.id; paint(); }, {icon: 'c:add', title: 'Insert an entry after this one'}),
        hourButton('', () => removeAt(i), {icon: 'c:trash-can', title: 'Remove this entry'}),
        hourButton('Inner shape', () => openInner(s),
          {icon: 'c:chart--network', title: 'Open the inner shape of this entry in the hour-flow editor'})),
      el('div', {class: 's3-hour-instr'}, ta,
        hourButton('Save instruction', () => saveInstruction(s, ta.value),
          {icon: 'c:save', title: 'Save the standing instruction of this entry in this hour'})),
      leg ? el('div', {class: 's3-hour-leg'},
        el('span', {class: 's3-muted', text: 'road ' + (leg.road || kind) + ' - ' + (leg.minutes != null ? leg.minutes + ' min' : '')
          + (leg.start ? ' - starts ' + hourClock(leg.start) : '') + (leg.deadline ? ' - deadline ' + hourClock(leg.deadline) : '')})) : null,
      leg ? el('div', {class: 's3-hour-booked', text: leg.booked
        ? 'booked ' + (leg.booked.label || leg.booked.id) + ' (' + leg.booked.kind + ')' : 'nothing booked for this leg yet'}) : null,
      leg ? ledgerView(leg.ledger || []) : null);
  }
  function ledgerView(rows) {
    if (!rows.length) return el('div', {class: 's3-muted', text: 'no draw on this leg yet'});
    return el('ol', {class: 's3-hour-ledger', 'aria-label': 'the ledger of this leg'}, rows.slice(-8).map(r => el('li', null,
      el('span', {class: 's3-muted', text: hourClock(r.at) + ' '}),
      'named ', el('b', {text: String(r.named || '-')}), ' - policy ', el('b', {text: String(r.policy || '-')}),
      r.booked ? ' - booked ' + (r.booked.label || r.booked.id) : '',
      ' - served ', el('b', {text: String(r.served || '-')}),
      r.why ? el('div', {class: 's3-muted', text: 'why: ' + r.why}) : null)));
  }

  /* ---- the engine: a switch asks first, and says what it does ---- */
  function modal(title, kids, onDismiss = () => {}) {
    const back = el('div', {class: 's3 s3-modal-back s3-hour-back'});
    let open = true;
    const close = dismissed => { if (!open) return; open = false; back.remove(); if (dismissed) onDismiss(); };
    const x = hourButton('', () => close(true), {cls: 's3-hour-x', icon: 'c:close--filled', title: 'Close'});
    back.append(el('div', {class: 's3-hour-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title},
      el('div', {class: 's3-hour-mhead'}, el('b', {text: title}), x), kids));
    back.addEventListener('click', e => { if (e.target === back) close(true); });
    document.body.append(back);
    return {close: () => close(false), dismiss: () => close(true)};
  }
  function askEngine(engine, fallback) {
    const cur = state.engine || {};
    if (engine === cur.engine && !!fallback === !!cur.fallback) return paint();
    const label = (HOUR_ENGINES.find(x => x[0] === engine) || [engine, engine])[1];
    const m = modal('Switch the engine?', [
      el('p', {text: 'Engine ' + (cur.engine || 'unknown') + ' -> ' + engine + ', fallback ' + (fallback ? 'on' : 'off') + '.'}),
      el('p', {class: 's3-muted', text: engine === 'system3'
        ? 'System 3 takes the hour: System 2 stands down, and its store stays readable. '
          + (fallback ? 'The fallback stays armed: the legacy chain still serves an entry the director aired nothing for.'
            : 'The fallback is off: the legacy chain does not cover an entry the director aired nothing for.')
        : 'The chosen engine takes the clock from the next entry. The fallback setting goes with it.'}),
      el('div', {class: 's3-hour-mact'},
        hourButton('Switch to ' + label, async () => {
          m.close();
          try {
            await post('/api/system3/engine', {engine, fallback: !!fallback});
            notice('Engine set to ' + label + (fallback ? ', fallback on.' : ', fallback off.'));
          } catch (e) { report(e); }
          loadAll();
        }, {cls: 'primary', icon: 'c:checkmark', title: 'Switch the engine'}),
        hourButton('Cancel', () => m.dismiss(), {icon: 'c:close--filled', title: 'Cancel - keep the engine'}))], () => paint());
    return m;
  }

  /* ---- the sheet: every write posts the whole hour's list (the list you send IS that hour) ---- */
  const cleanSlot = s => { const o = {...s}; HOUR_DERIVED.forEach(k => { delete o[k]; }); return o; };
  const slotsNow = () => (currentRow() ? (currentRow().slots || []) : []).map(s => ({...s}));
  async function writeSlots(slots, done) {
    try {
      await post('/api/schedule/hours', {key: state.key, slots: slots.map(cleanSlot)});
      notice(done);
    } catch (e) { report(e); }
    loadAll();
  }
  function setMinutes(i, value) {
    const n = Number(value);
    if (!(n > 0)) { report(new Error('minutes must be a number above zero')); return paint(); }
    const slots = slotsNow();
    if (!slots[i]) return;
    slots[i].minutes = Math.max(0.25, Math.min(600, n));
    writeSlots(slots, 'Saved the minutes for ' + (slots[i].label || 'the entry') + '.');
  }
  function setEnabled(i, on) {
    const slots = slotsNow();
    if (!slots[i]) return;
    slots[i].enabled = !!on;
    writeSlots(slots, (on ? 'Enabled ' : 'Disabled ') + (slots[i].label || 'the entry') + '.');
  }
  function move(i, d) {
    const slots = slotsNow();
    const j = i + d;
    if (!slots[i] || j < 0 || j >= slots.length) return;
    [slots[i], slots[j]] = [slots[j], slots[i]];
    writeSlots(slots, 'Moved ' + (slots[j].label || 'the entry') + ' ' + (d < 0 ? 'up' : 'down') + '.');
  }
  function removeAt(i) {
    const slots = slotsNow();
    if (!slots[i]) return;
    const gone = slots.splice(i, 1)[0];
    writeSlots(slots, 'Removed ' + (gone.label || 'the entry') + '.');
  }
  function insertAfter(i, kind) {
    if (!kind) return;
    const slots = slotsNow();
    slots.splice(i + 1, 0, {kind, label: kindLabel(kind), minutes: 3, enabled: true, notes: ''});
    state.inserting = '';
    writeSlots(slots, 'Inserted ' + kindLabel(kind) + '.');
  }
  async function saveInstruction(s, text) {
    const words = String(text || '').trim();
    if (!words) { report(new Error('An instruction needs words. Remove the entry to drop it.')); return; }
    try {
      await post('/api/schedule/hours/' + encodeURIComponent(state.key) + '/prompt', {slot_id: s.id, text: words});
      drafts.delete(s.id);
      notice('Saved the instruction for ' + (s.label || 'the entry') + '.');
    } catch (e) { report(e); }
    loadAll();
  }
  /* the inner shape is the hour-flow editor's; on the desk it is a global, on the tablet it may not be */
  function openInner(s) {
    const P = window.PineHourFlow;
    if (!P || typeof P.open !== 'function') {
      report(new Error('The hour-flow editor is not loaded here - open the hour-flow editor on the desk.'));
      return;
    }
    try {
      P.open({road: s.kind, kind: s.kind, slot_id: s.id, label: s.label || kindLabel(s.kind), hour: state.key,
        onBack: () => loadAll()});
    } catch (e) { report(e); }
  }

  /* ---- the tab's life: shown by the router, polled while shown and not being edited ---- */
  function show(host) {
    if (host && host.firstChild !== root) fill(host, root);
    if (!state.loadedAt) fill(root, el('p', {class: 's3-muted', text: 'Reading the hour...'}));
    if (!state.loadedAt || Date.now() - state.loadedAt > 1500) loadAll(); else paint();
  }
  const timer = setInterval(() => {
    if (!alive || !active() || document.hidden || busy() || editing()) return;
    loadAll();
  }, 15000);
  return {node: root, show, refresh: loadAll, stop() { alive = false; clearInterval(timer); }};
}
/* [hour-tab-end] */

"""

CSS_BLOCK = r"""/* [hour-tab] the Hour tab: the hour as a road of legs (wave I). Phone width: the road keeps its rail, the buttons wrap. */
.s3-hour { display: grid; gap: 10px; min-width: 0; max-width: 100%; }
.s3-hour-top { display: grid; gap: 8px; min-width: 0; }
.s3-hour-engine { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; border: 1px solid rgba(127,160,146,.35); border-radius: 8px; padding: 8px 10px; }
.s3-hour-engine.s3-hour-off { display: block; color: var(--ink-2); }
.s3-hour-line, .s3-hour-pick, .s3-hour-dice { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-width: 0; }
.s3-hour-say { flex-basis: 100%; font-size: 12px; opacity: .85; overflow-wrap: anywhere; }
.s3-hour-fb { display: inline-flex; gap: 4px; align-items: center; font-size: 12px; }
.s3-hour-btn { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; line-height: 1.2; padding: 3px 9px; min-height: 28px; max-width: 100%; border-radius: 6px; border: 1px solid rgba(127,160,146,.45); background: transparent; color: inherit; cursor: pointer; }
.s3-hour-btn.primary { background: #2f5a4a; border-color: #5f8a76; }
.s3-hour-btn:disabled { opacity: .4; cursor: default; }
.s3-hour-ic { display: inline-flex; width: 14px; height: 14px; flex: 0 0 14px; }
.s3-hour-ic svg { width: 14px; height: 14px; fill: currentColor; }
.s3-hour-btn.down .s3-hour-ic svg { transform: rotate(180deg); }
.s3-hour-road { position: relative; display: grid; gap: 8px; padding-left: 22px; min-width: 0; max-width: 100%; }
.s3-hour-road::before { content: ""; position: absolute; left: 8px; top: 14px; bottom: 14px; width: 2px; background: rgba(127,160,146,.5); }
.s3-hour-start, .s3-hour-node { position: relative; border-radius: 9px; padding: 8px 10px; min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.s3-hour-start { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; background: rgba(47,90,74,.25); border: 1px solid #5f8a76; }
.s3-hour-node { border: 1px solid rgba(127,160,146,.4); background: rgba(255,255,255,.02); }
.s3-hour-node.inner { border-style: dashed; }
.s3-hour-node.on-air { border-color: #7fbf9f; box-shadow: 0 0 0 2px rgba(127,191,159,.35); }
.s3-hour-node.off { opacity: .6; }
.s3-hour-node::before { content: ""; position: absolute; left: -18px; top: 14px; width: 9px; height: 9px; border-radius: 50%; background: #5f8a76; }
.s3-hour-node.on-air::before { background: #7fbf9f; }
.s3-hour-nhead { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.s3-hour-idx { font-size: 11px; opacity: .7; min-width: 16px; }
.s3-hour-chip { font-size: 11px; border: 1px solid rgba(127,160,146,.45); border-radius: 999px; padding: 0 7px; }
.s3-hour-chip.dyn { border-style: dashed; }
.s3-hour-chip.air { background: rgba(127,191,159,.25); }
.s3-hour-ctl, .s3-hour-insert { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px; }
.s3-hour-mins input { width: 74px; max-width: 100%; }
.s3-hour-instr { display: grid; gap: 4px; margin-top: 6px; }
.s3-hour-instr textarea, .s3-hour-sel { width: 100%; max-width: 100%; font: inherit; font-size: 12px; background: transparent; color: inherit; border: 1px solid rgba(127,160,146,.4); border-radius: 6px; padding: 4px 6px; }
.s3-hour-instr textarea { min-height: 44px; resize: vertical; }
.s3-hour-instr .s3-hour-btn { justify-self: start; }
.s3-hour-insert .s3-hour-sel { width: auto; max-width: 100%; }
.s3-hour-leg, .s3-hour-booked { font-size: 12px; margin-top: 6px; overflow-wrap: anywhere; }
.s3-hour-ledger { font-size: 11.5px; margin: 4px 0 0; padding-left: 18px; }
.s3-hour-ledger li { margin: 0 0 4px; overflow-wrap: anywhere; }
.s3.s3-hour-back { z-index: 2147483600; }
.s3-hour-modal { position: relative; margin: 10vh auto 0; max-width: min(460px, 100%); background: var(--bg, #0d1714); color: var(--ink, inherit); border: 1px solid #5f8a76; border-radius: 10px; padding: 12px 14px; display: grid; gap: 8px; box-sizing: border-box; }
.s3-hour-mhead { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.s3-hour-x { padding: 4px; min-height: 0; border: 0; }
.s3-hour-mact { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
@media (max-width: 560px) {
  .s3-hour-road { padding-left: 16px; }
  .s3-hour-road::before { left: 5px; }
  .s3-hour-node::before { left: -15px; }
  .s3-hour-btn { min-height: 34px; }
}
/* [hour-tab-end] */
"""

MOUNT_ANCHOR = "export async function mount(root, {request, onClose, tab: startTab = '', table: startTable = '', conversationId = '', details = true} = {}) {"
TABS_OLD = "    ['director', 'Director'], ['structure', 'Structure'], ['controls', 'Controls']];"
TABS_NEW = "    ['hour', 'Hour'], ['director', 'Director'], ['structure', 'Structure'], ['controls', 'Controls']];"
PAINT_OLD = '  function paint() {\n    paintTabs();\n'
PAINT_NEW = "  /* [hour-tab] the Hour tab: the hour as a road of legs (wave I); the router shows it through hourTab.show */\n  const hourTab = makeHourTab({request, scroll: () => scrollBox(), busy: () => reading(), active: () => tab === 'hour',\n    openTable: id => { stopExtras(); listId = ''; tableId = id; draft = null; tab = 'tables'; paint(); },\n    notice, report});\n  function paint() {\n    paintTabs();\n"
ROUTER_OLD = "      else if (tab === 'sys3') paintSys3();\n"
ROUTER_NEW = "      else if (tab === 'hour') hourTab.show(body);\n      else if (tab === 'sys3') paintSys3();\n"
DISPOSE_OLD = 'timers.forEach(clearInterval); stopExtras(); fill(root); }};'
DISPOSE_NEW = 'timers.forEach(clearInterval); stopExtras(); hourTab.stop(); fill(root); }};'
CSS_OLD = '.s3 .s3-system3-tile .sp-rr{margin:0;}\n'
NAV_OLD = '  pop.appendChild(nav);\n\n  const body = mk("div", "");\n'
NAV_NEW = '  pop.appendChild(nav);\n  /* [hour-tab] the sheet\'s entries are edited in the System 3 window\'s Hour tab now */\n  const s3Line = mk("div", "wk-note", "Edited in the System 3 window\'s Hour tab now. ");\n  s3Line.style.cssText = "font-size:11px;margin:2px 0 6px";\n  const s3Open = mk("button", "", "Open the Hour tab");\n  s3Open.title = "Open the System 3 window on the Hour tab";\n  s3Open.setAttribute("aria-label", "Open the System 3 window on the Hour tab");\n  s3Open.onclick = (e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent("pine:system3-open", {detail: {tab: "hour"}})); };\n  s3Line.appendChild(s3Open);\n  pop.appendChild(s3Line);\n\n  const body = mk("div", "");\n'
LISTEN_OLD = '  function rejectionPolicyOpen() {\n'
LISTEN_NEW = "  /* [hour-tab] the desk's sheet opens System 3 on the Hour tab (renderer.js worksSchedule) */\n  root.addEventListener('pine:system3-open', function (event) {\n    s3Window((event && event.detail && event.detail.tab) || 'tables');\n  });\n\n  function rejectionPolicyOpen() {\n"

EDITS = {
    "frontend/system3.js": [
        ("the Hour tab (makeHourTab) before mount", MOUNT_ANCHOR, BLOCK + MOUNT_ANCHOR, 1),
        ("the Hour tab in the tab row", TABS_OLD, TABS_NEW, 1),
        ("the Hour tab built beside the router", PAINT_OLD, PAINT_NEW, 1),
        ("the router shows the Hour tab", ROUTER_OLD, ROUTER_NEW, 1),
        ("the window stops the Hour tab's poll", DISPOSE_OLD, DISPOSE_NEW, 1),
    ],
    "frontend/system3.css": [
        ("the Hour tab styles", CSS_OLD, CSS_OLD + CSS_BLOCK, 1),
    ],
    "desktop/renderer/renderer.js": [
        ("worksSchedule: the Hour tab line and button", NAV_OLD, NAV_NEW, 1),
    ],
    "desktop/renderer/script-page.js": [
        ("the desk opens System 3 on the Hour tab", LISTEN_OLD, LISTEN_NEW, 1),
        ("System 3 module ?v= (the four window openers)",
         "import(techUrl('/system3/system3.js?v=9')).then(function (mod) {",
         "import(techUrl('/system3/system3.js?v=10')).then(function (mod) {", 4),
        ("System 3 module ?v= (the embedded panel)",
         "var mod = await import(techUrl('/system3/system3.js?v=9'));",
         "var mod = await import(techUrl('/system3/system3.js?v=10'));", 1),
        ("System 3 styles ?v= (the five openers)",
         "style.href = techUrl('/system3/system3.css?v=7');",
         "style.href = techUrl('/system3/system3.css?v=8');", 5),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".hourtab.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
