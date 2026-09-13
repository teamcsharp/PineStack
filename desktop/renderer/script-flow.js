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

/* ------------------------------------------------------- the chunks */

/* WHAT IS ALREADY CUT, so a row can say so rather than offering to cut it
 * twice. Filled once when the window opens. */
let cutList = [];

/* KIND AND MARK, NOT THE NAME. The two sides of the wire do not always call
 * a chunk the same thing - a crystal shard is `kind` here and `crystal` where
 * the prompt is assembled - so matching on the name would produce a cut that
 * is recorded, shown, and silently never applied. See prompt_cuts.py. */
function isCut(key) {
  return cutList.some((one) => one && one.kind === key.kind
    && one.mark === key.mark);
}

/* A FINGERPRINT OF THE TEXT, so an exclusion names a PASSAGE rather than a
 * position. The name alone would cut every future swath out of that file;
 * the text alone would miss the same passage arriving under another name.
 *
 * Not a cryptographic hash - nothing here is adversarial, and this has to be
 * computed the same way on both sides of the wire. Whitespace is collapsed
 * first so a reflowed copy of the same passage still matches itself. */
/* ONLY THE FIRST 160 CHARACTERS, and that bound is load-bearing. The station
 * keeps its influence rings truncated at 240 while the assembler holds the
 * whole passage, so fingerprinting all of it would hash two different strings
 * for the same chunk and never match. MARK_CHARS in prompt_cuts.py. */
const MARK_CHARS = 160;

function fingerprint(text) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim().toLowerCase()
    .slice(0, MARK_CHARS);
  let a = 0x811c9dc5;
  for (let i = 0; i < flat.length; i += 1) {
    a ^= flat.charCodeAt(i);
    a = (a + ((a << 1) + (a << 4) + (a << 7) + (a << 8) + (a << 24))) >>> 0;
  }
  return ('00000000' + a.toString(16)).slice(-8) + '-' + flat.length;
}

/* DID THIS CHUNK REALLY REACH THE PROMPT?
 *
 * The station sets flags - in_prompt on a shard, quoted on a document - and
 * those are worth reporting. But `written.prompt` is the prompt AS SENT, so
 * the question can be ANSWERED instead of relayed: look for a distinctive run
 * of the chunk in it.
 *
 * A run rather than the whole thing, because what goes into a prompt is
 * usually a trimmed or reflowed version of what was grabbed. Forty characters
 * from the middle is long enough not to match by accident and short enough to
 * survive the trimming. */
function reachedPrompt(text) {
  const p = prov || {};
  const sent = (p.written && p.written.prompt) || '';
  if (!sent) return null;               /* unknowable, not "no" */
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  if (flat.length < 12) return null;
  const hay = String(sent).replace(/\s+/g, ' ').toLowerCase();
  const run = flat.length <= 40 ? flat
    : flat.slice(Math.floor((flat.length - 40) / 2),
      Math.floor((flat.length - 40) / 2) + 40);
  return hay.indexOf(run.toLowerCase()) >= 0;
}

/**
 * One contribution, opened up.
 *
 * `spec` is {kind, name, note, text, flagged} - flagged being what the
 * station CLAIMS about whether it was used, which is shown next to what the
 * prompt itself says.
 */
function chunk(into, spec) {
  const text = String(spec.text || '');
  /* WHEN A CHUNK IS CUT BY ITS LINES, the row's own state follows the FIRST
   * line rather than the joined passage - because the joined passage is not
   * what was stored, and a row that could never see its own cut would offer
   * to make it again every time the window opened. */
  const byLine = Array.isArray(spec.lines) && spec.lines.length
    ? spec.lines.map((one) => String(one || '')).filter((one) => one.trim())
    : null;
  const key = { kind: spec.kind, name: String(spec.name || ''),
    mark: fingerprint(byLine ? byLine[0] : text) };

  const row = document.createElement('div');
  row.className = 'chunk';

  const head = document.createElement('div');
  head.className = 'chunkHead';

  const twist = document.createElement('button');
  twist.type = 'button';
  twist.className = 'twist';
  twist.textContent = '\u25b8';
  head.appendChild(twist);

  const title = document.createElement('span');
  title.className = 'chunkName';
  title.textContent = spec.name || spec.kind;
  head.appendChild(title);

  if (spec.note) {
    const note = document.createElement('span');
    note.className = 'chunkNote';
    note.textContent = spec.note;
    head.appendChild(note);
  }

  /* WHAT THE PROMPT ITSELF SAYS, beside what the station claims. */
  const reached = reachedPrompt(text);
  const mark = document.createElement('span');
  if (reached === null) {
    mark.className = 'chunkMark dim';
    mark.textContent = spec.flagged === undefined ? ''
      : (spec.flagged ? 'marked used' : 'marked unused');
  } else if (reached) {
    mark.className = 'chunkMark in';
    mark.textContent = 'in the prompt';
  } else {
    mark.className = 'chunkMark out';
    mark.textContent = 'not in the prompt';
  }
  head.appendChild(mark);

  /* THE FLAG AND THE TEXT DISAGREEING is worth saying out loud. It is
   * invisible to anyone reading either one on its own, and it means one of
   * them is lying about what the station did. */
  if (reached !== null && spec.flagged !== undefined
      && !!spec.flagged !== reached) {
    const odd = document.createElement('span');
    odd.className = 'chunkOdd';
    odd.textContent = spec.flagged
      ? '(recorded as used, but its text is not in the prompt as sent)'
      : '(recorded as unused, yet its text IS in the prompt as sent)';
    head.appendChild(odd);
  }

  const cut = document.createElement('button');
  cut.type = 'button';
  cut.className = 'cut';
  cut.textContent = '\u00d7';
  /* NO PASSAGE, NO CUT - AND SAY SO RATHER THAN PRETEND.
   *
   * Some of what the station records is a NAME and nothing else: a vector hit
   * is logged with its query, file and score and no text, and a document
   * entry is {file, how, quoted}. There is nothing to fingerprint, so a cut
   * made here could never match anything where the prompt is assembled - it
   * would be recorded, listed, and silently ineffective, which is the worst
   * way for a control to fail.
   *
   * So it is refused outright and the row says what is missing. */
  const cuttable = String(text || '').trim().length >= 12;
  cut.disabled = !cuttable;
  cut.title = cuttable
    ? 'Stop this from being added to future prompts'
    : 'The station recorded only the name of this one, not the passage '
      + '\u2014 so there is nothing here to cut by.';
  head.appendChild(cut);

  row.appendChild(head);

  const body = document.createElement('pre');
  body.className = 'chunkBody';
  body.hidden = true;
  body.textContent = text || '(nothing was recorded here)';
  row.appendChild(body);

  const said = document.createElement('div');
  said.className = 'chunkSaid';
  said.hidden = true;
  row.appendChild(said);

  twist.addEventListener('click', () => {
    body.hidden = !body.hidden;
    twist.textContent = body.hidden ? '\u25b8' : '\u25be';
  });
  head.addEventListener('click', (event) => {
    if (event.target === twist || event.target === cut) return;
    twist.click();
  });

  const paintCut = () => {
    if (!cuttable) return;
    const gone = isCut(key);
    row.classList.toggle('isCut', gone);
    cut.textContent = gone ? '\u21ba' : '\u00d7';
    cut.title = gone
      ? 'Put this back into future prompts'
      : 'Stop this from being added to future prompts';
  };
  paintCut();

  cut.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (!cuttable) return;
    const gone = isCut(key);
    /* CONFIRMED, because this is a standing decision about every future
     * prompt rather than a change to the line being looked at. */
    if (!gone && !window.confirm('Stop this from being added to future '
      + 'prompts?\n\n' + (spec.name || spec.kind) + '\n\n'
      + text.slice(0, 200) + (text.length > 200 ? '\u2026' : '')
      + '\n\nIt can be put back from this window.')) return;
    said.hidden = false;
    said.textContent = gone ? 'Putting it back\u2026' : 'Cutting it\u2026';
    try {
      const done = gone
        ? await api.promptKeep(Object.assign({ lines: byLine }, key))
        : await api.promptCut(Object.assign(
          { text: text.slice(0, 4000), lines: byLine }, key));
      if (!done || !done.ok) {
        said.className = 'chunkSaid bad';
        said.textContent = (done && done.why) || 'the station would not take it';
        return;
      }
      cutList = done.cuts || cutList;
      said.className = 'chunkSaid';
      said.textContent = gone
        ? 'Back in. Future prompts may use it again.'
        : 'Cut. Future prompts will not carry this.';
      paintCut();
    } catch (error) {
      said.className = 'chunkSaid bad';
      said.textContent = error.message;
    }
  });

  into.appendChild(row);
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
    /* THE CHARACTER AND STATION PROMPTS ARE PROMPT WEIGHT AS WELL, and
     * the ask was to be able to simplify what is carried - so they are
     * offered on the same terms as everything else. */
    if (s.text) {
      chunk(body, { kind: 'character', name: s.name || 'character prompt',
        note: 'armed when this was written', text: s.text });
    }
    if (s.station) {
      chunk(body, { kind: 'station', name: 'station prompt',
        note: 'carried on every round', text: s.station });
    }
    if (!has(id)) nothing(body, 'No character prompt is recorded for this line.');
  } else if (id === 'seed') {
    for (const doc of (p.documents || [])) {
      chunk(body, { kind: 'document', name: doc.file || 'document',
        note: doc.how || '', flagged: doc.quoted,
        text: doc.text || doc.passage || doc.swath || doc.quote || '',
        /* CUT BY THE LINE. A swath is assembled fresh each round out of
         * whichever lines are still unused, so the joined passage on screen
         * would never recur - cutting it whole would record something that
         * never matches again. See add_many() in prompt_cuts.py. */
        lines: doc.lines || null });
    }
    for (const bit of (p.material || [])) {
      const words = typeof bit === 'string' ? bit
        : (bit.text || bit.line || JSON.stringify(bit));
      chunk(body, { kind: 'material',
        name: (bit && bit.kind) || 'material',
        note: (bit && bit.road) || '', text: words });
    }
    const asks = p.requests || [];
    if (asks.length) {
      const head = document.createElement('h3');
      head.textContent = 'What the audience had asked for';
      body.appendChild(head);
      for (const ask of asks) {
        chunk(body, { kind: 'request',
          name: (ask.title || 'request')
            + (ask.artist ? ' \u2014 ' + ask.artist : ''),
          note: (ask.count || 0) + '\u00d7 asked',
          text: (ask.asked || []).join('\n') || ask.title || '' });
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
      chunk(body, { kind: 'crystal', name: shard.kind || 'shard',
        note: shard.why || '', flagged: shard.in_prompt,
        text: shard.text || JSON.stringify(shard) });
    }
    if (!has(id)) {
      nothing(body, 'The crystal contributed nothing recorded here'
        + (p.how === 'live' ? ' — it was made live.' : '.'));
    }
  } else if (id === 'vectors') {
    for (const hit of (p.vectors || [])) {
      chunk(body, { kind: 'vector',
        name: hit.file || hit.source || hit.query || 'search',
        note: (hit.query ? 'for \u201c' + hit.query + '\u201d' : '')
          + (hit.score !== undefined ? '  score ' + hit.score : ''),
        text: hit.text || hit.passage || hit.chunk || hit.query || '' });
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

  /* WHAT IS ALREADY CUT, before anything is drawn - so a row that has been
   * dropped already says so rather than offering to drop it again. A station
   * that cannot answer is not an error here: the chart is still worth
   * showing, and the X will say so if it is pressed. */
  try {
    const cuts = await api.promptCuts();
    if (cuts && cuts.ok) cutList = cuts.cuts || [];
  } catch (error) { cutList = []; }

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
