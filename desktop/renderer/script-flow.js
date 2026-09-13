/* HOW THIS LINE CAME TO BE.
 *
 * "A pop-up window that shows a flow chart of how the script came to be."
 *
 * THE STAGES ARE READ OFF A REAL PROVENANCE, not borrowed from a diagram.
 * /api/dj/provenance answers with exactly these parts, measured against the
 * live station:
 *
 *   schedule  {kind, prompt, kind_now, prompt_now} and a prose line naming
 *             the entry and the sheet it came from
 *   system    {name, armed_now, text, followed} - the character armed when
 *             this was written, and whether the writer actually followed it
 *   documents [{file, how, quoted}] - the swaths it was seeded from
 *   material  the station's own past work reused
 *   requests  what the audience had asked for
 *   crystal   the shards offered, with in_prompt flags
 *   vectors   what was searched for
 *   written   the prompt as sent and the script that came back
 *   render    {engine, voice, seconds, kb, service, tried[], fallback}
 *   line      {aired, air_at, clip_media, clip_from, clip_until}
 *
 * AN EMPTY STAGE IS DRAWN, NOT HIDDEN. "made live, while you were listening"
 * is a real answer for why the crystal and the material have nothing in
 * them, and a chart that quietly dropped those boxes would be describing a
 * different station than the one that made this line.
 */
'use strict';

const api = window.pineDesktop || {};

const STAGES = [
  { id: 'schedule', name: 'Schedule', said: 'what asked for it' },
  { id: 'system', name: 'Character', said: 'who was armed' },
  { id: 'seed', name: 'Material', said: 'what it was seeded from' },
  { id: 'written', name: 'Written', said: 'the prompt and the answer' },
  { id: 'crystal', name: 'Crystal', said: 'shards offered' },
  { id: 'vectors', name: 'Vectors', said: 'what was searched' },
  { id: 'render', name: 'Recorded', said: 'engine and voice' },
  { id: 'air', name: 'Air', said: 'when it went out' }
];

let region = null;
let prov = null;
let chosen = '';

function has(id) {
  const p = prov || {};
  switch (id) {
    case 'schedule':
      return !!(p.schedule && (p.schedule.kind_now || p.schedule.kind
        || p.schedule.prompt_now || p.schedule.prompt)) || !!p.scheduleSaid;
    case 'system':
      return !!(p.system && (p.system.name || p.system.text));
    case 'seed':
      return !!((p.documents || []).length || (p.material || []).length
        || (p.requests || []).length);
    case 'written':
      return !!(p.written && Object.keys(p.written).length) || !!p.prepared;
    case 'crystal': return !!(p.crystal || []).length;
    case 'vectors': return !!(p.vectors || []).length;
    case 'render':
      /* The VOICE counts as well as the engine. A line whose render block
       * was not kept can still name the voice it was spoken in, and a box
       * drawn empty while its panel has something in it is the chart
       * disagreeing with itself. */
      return !!(p.render && Object.keys(p.render).length)
        || !!(region && (region.engine || region.voice));
    case 'air':
      return !!((p.line && p.line.air_at) || (region && region.air_at)
        || (region && region.aired));
    default: return false;
  }
}

/* ------------------------------------------------------------- the chart */

const BOX_W = 132;
const BOX_H = 62;
const GAP = 28;

function draw() {
  const svg = document.getElementById('spine');
  const wide = STAGES.length * BOX_W + (STAGES.length - 1) * GAP + 8;
  svg.setAttribute('width', String(wide));
  svg.setAttribute('height', String(BOX_H + 34));
  svg.setAttribute('viewBox', '0 0 ' + wide + ' ' + (BOX_H + 34));
  svg.textContent = '';

  const ns = 'http://www.w3.org/2000/svg';

  STAGES.forEach((stage, i) => {
    const x = 4 + i * (BOX_W + GAP);
    const y = 4;

    if (i > 0) {
      /* The connector carries the state of the stage BEFORE it, so the eye
       * can follow how far the line actually got. */
      const line = document.createElementNS(ns, 'path');
      const from = x - GAP;
      line.setAttribute('d', 'M' + from + ' ' + (y + BOX_H / 2)
        + ' H' + x);
      line.setAttribute('class', 'link' + (has(STAGES[i - 1].id) ? ' live' : ''));
      svg.appendChild(line);
    }

    const group = document.createElementNS(ns, 'g');
    group.setAttribute('class', 'box ' + (has(stage.id) ? 'has' : 'empty')
      + (chosen === stage.id ? ' on' : ''));
    group.addEventListener('click', () => pick(stage.id));

    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x', String(x));
    rect.setAttribute('y', String(y));
    rect.setAttribute('width', String(BOX_W));
    rect.setAttribute('height', String(BOX_H));
    group.appendChild(rect);

    /* The per-stage emissive edge, which is the station's own visual
     * language for "this part is alight". */
    const edge = document.createElementNS(ns, 'rect');
    edge.setAttribute('class', 'edge');
    edge.setAttribute('x', String(x));
    edge.setAttribute('y', String(y));
    edge.setAttribute('width', '4');
    edge.setAttribute('height', String(BOX_H));
    group.appendChild(edge);

    const name = document.createElementNS(ns, 'text');
    name.setAttribute('class', 'name');
    name.setAttribute('x', String(x + 14));
    name.setAttribute('y', String(y + 24));
    name.textContent = stage.name;
    group.appendChild(name);

    const said = document.createElementNS(ns, 'text');
    said.setAttribute('class', 'said');
    said.setAttribute('x', String(x + 14));
    said.setAttribute('y', String(y + 42));
    said.textContent = has(stage.id) ? stage.said : 'nothing recorded';
    group.appendChild(said);

    svg.appendChild(group);
  });
}

/* ------------------------------------------------------------ the detail */

function pair(into, name, value) {
  if (value === undefined || value === null || value === '') return;
  const line = document.createElement('div');
  line.className = 'pair';
  const b = document.createElement('b');
  b.textContent = name;
  const s = document.createElement('span');
  s.textContent = String(value);
  line.appendChild(b);
  line.appendChild(s);
  into.appendChild(line);
}

function block(into, text) {
  if (!text) return;
  const el = document.createElement('div');
  el.className = 'block';
  el.textContent = String(text);
  into.appendChild(el);
}

function nothing(into, why) {
  const el = document.createElement('div');
  el.className = 'none';
  el.textContent = why;
  into.appendChild(el);
}

function when(stamp) {
  const at = Number(stamp);
  if (!isFinite(at) || at <= 0) return '';
  return new Date(at > 1e12 ? at : at * 1000).toLocaleString();
}

function pick(id) {
  chosen = id;
  draw();
  const stage = STAGES.find((s) => s.id === id);
  const body = document.getElementById('detailBody');
  document.getElementById('detailWhat').textContent = stage ? stage.name : '';
  body.textContent = '';
  const p = prov || {};

  if (id === 'schedule') {
    const s = p.schedule || {};
    pair(body, 'slot now', s.kind_now);
    pair(body, 'slot when written', s.kind);
    block(body, s.prompt_now || s.prompt);
    if (p.scheduleSaid) block(body, p.scheduleSaid);
    if (!has(id)) nothing(body, 'No schedule entry is recorded for this line.');
  } else if (id === 'system') {
    const s = p.system || {};
    pair(body, 'character', s.name);
    pair(body, 'armed now', s.armed_now);
    pair(body, 'followed', s.followed === undefined ? '' : (s.followed ? 'yes' : 'no'));
    block(body, s.text);
    if (s.station) { pair(body, 'station prompt', ''); block(body, s.station); }
    if (!has(id)) nothing(body, 'No character prompt is recorded for this line.');
  } else if (id === 'seed') {
    for (const doc of (p.documents || [])) {
      pair(body, doc.file || 'document',
        (doc.how || '') + (doc.quoted ? ' (quoted)' : ''));
    }
    for (const bit of (p.material || [])) {
      pair(body, 'material', typeof bit === 'string' ? bit : JSON.stringify(bit).slice(0, 200));
    }
    const asks = p.requests || [];
    if (asks.length) {
      const head = document.createElement('h3');
      head.textContent = 'What the audience had asked for';
      body.appendChild(head);
      for (const ask of asks.slice(0, 8)) {
        pair(body, ask.title || 'request',
          (ask.artist ? ask.artist + ' · ' : '') + (ask.count || 0) + '×');
      }
    }
    if (!has(id)) nothing(body, 'Nothing is recorded as having seeded this line.');
  } else if (id === 'written') {
    pair(body, 'how', p.how);
    pair(body, 'prepared', p.prepared);
    const w = p.written || {};
    for (const key of Object.keys(w)) {
      const value = w[key];
      if (typeof value === 'string' && value.length > 90) {
        const head = document.createElement('h3');
        head.textContent = key;
        body.appendChild(head);
        block(body, value);
      } else {
        pair(body, key, typeof value === 'object' ? JSON.stringify(value) : value);
      }
    }
    if (!Object.keys(w).length) {
      nothing(body, 'The prompt and the answer are not kept for this one'
        + (p.prepared ? ' — ' + p.prepared + '.' : '.'));
    }
  } else if (id === 'crystal') {
    for (const shard of (p.crystal || [])) {
      pair(body, shard.kind || 'shard',
        (shard.text || JSON.stringify(shard)).slice(0, 200)
        + (shard.in_prompt ? '  (used)' : '  (offered, not used)'));
    }
    if (!has(id)) {
      nothing(body, 'The crystal contributed nothing recorded here'
        + (p.how === 'live' ? ' — it was made live.' : '.'));
    }
  } else if (id === 'vectors') {
    for (const hit of (p.vectors || [])) {
      pair(body, hit.query || 'search',
        (hit.file || hit.source || '') + ' ' + (hit.score !== undefined ? hit.score : ''));
    }
    if (!has(id)) nothing(body, 'No vector search is recorded for this line.');
  } else if (id === 'render') {
    const r = p.render || {};
    pair(body, 'engine', r.engine || (region && region.engine));
    pair(body, 'voice', r.voice || (region && region.voice));
    pair(body, 'seconds', r.seconds);
    pair(body, 'size', r.kb ? r.kb + ' kB' : '');
    pair(body, 'took', r.ms ? r.ms + ' ms' : '');
    pair(body, 'service', r.service);
    if ((r.tried || []).length) pair(body, 'tried first', (r.tried || []).join(', '));
    if (r.fallback) pair(body, 'fell back to', r.fallback);
    if (!has(id)) nothing(body, 'No recording details are kept for this line.');
  } else if (id === 'air') {
    const l = p.line || {};
    pair(body, 'aired', l.aired || (region && region.aired ? 'yes' : 'not yet'));
    pair(body, 'written at', when(l.ts || (region && region.ts)));
    pair(body, 'went out at', when(l.air_at || (region && region.air_at)));
    pair(body, 'from', l.source || (region && region.source));
    pair(body, 'clip', l.clip_media || (region && region.clip_media));
    if (l.clip_from !== undefined) {
      pair(body, 'cut', l.clip_from + 's → ' + l.clip_until + 's');
    }
    if (!has(id)) nothing(body, 'This line has not gone out yet.');
  }
}

/* ----------------------------------------------------------------- start */

(async function open() {
  let held = null;
  try {
    held = await api.flowPending();
  } catch (error) {
    document.getElementById('note').textContent = error.message;
    return;
  }
  if (!held || !held.ok) {
    document.getElementById('note').textContent =
      (held && held.why) || 'there is nothing waiting for this window';
    return;
  }
  region = held.region || null;
  prov = held.provenance || null;

  document.getElementById('who').textContent =
    (region && (region.name || region.who || region.kind)) || 'a line';
  document.getElementById('said').textContent =
    (region && (region.said || region.text)) || '';

  if (!prov) {
    /* SAID, NOT HIDDEN. The booth keeps paperwork only while a line is in
     * its live ring; past that the chart can still be drawn from what the
     * feed knew, and the reason belongs on screen. */
    document.getElementById('note').textContent = held.why
      || 'The booth has no paperwork for this line any more - the chart below '
        + 'is what the feed still knows.';
  } else {
    document.getElementById('note').textContent =
      'Click a stage to see what the station recorded there.';
  }

  draw();
  /* Open on the first stage that actually has something, so the window is
   * useful before anything is clicked. */
  const first = STAGES.find((s) => has(s.id));
  pick(first ? first.id : 'air');
})();
