import './system3-message-tile.js';
/* System 3 - the conversation director's instrument.
 *
 * Three synchronised views of one conversation (docs/system3_blueprint.md
 * section 13): A. the messenger, B. the RNG Rolodex, C. the final script.
 * Selecting a line, a decision or a script row selects the same turn in
 * the other two. Every roll shown is a RECORDED event from
 * /api/system3/*: the drum only ever scrolls through the candidates that
 * were actually in the draw and stops on the one that was selected, and a
 * die shows no number until it lands on the one that was rolled. Nothing
 * here invents a roll for effect.
 */
const FAM = {INJECT: 'var(--obs)', CTS: 'var(--cts)', ES: 'var(--es)', RS: 'var(--rs)', IRS: 'var(--irs)', FL: 'var(--fl)', TRACK_TALK: 'var(--topic)',
  SPEAKERBOX: 'var(--sb)', SFX: 'var(--sfx)', TOPIC: 'var(--topic)', SFXGUY: 'var(--sfxguy)', LINE: 'var(--line)',
  COMMIT: 'var(--obs)', REPAIR: 'var(--repair)', TINT: 'var(--tint)', ROOM: 'var(--room)',   /* [s3-rewrite] */
  FAV: 'var(--fav)', DIRECTIVE: 'var(--directive)', EVENT: 'var(--repair)', STATION: 'var(--obs)',   /* [s3-cast] [s3-events] [s3-dice-door] */
  TEMPER: 'var(--es)', SHOCK: 'var(--rs)', INTERJECT: 'var(--fl)', MENTION: 'var(--cts)', CARRY: 'var(--es)'};   /* [s3-rounds] [s3-carry] */
FAM.MEMORY = 'var(--memory, #d9c9a3)';   /* [s3-memory] */
FAM.RESOLVE = 'var(--tint)'; FAM.WRAP = 'var(--room)';   /* [s3-callend] the caller's wheel, wrap call */
Object.assign(FAM, {CALLOPEN:'var(--line)', CALLANGLE:'var(--topic)', CALLSTAKES:'var(--rs)', CALLPROBE:'var(--cts)', CALLSOURCE:'var(--sb)', RW:'var(--repair)', RWFEATURE:'var(--topic)'});
FAM.GRAPH = 'var(--topic)';
Object.assign(FAM, {SPLIT: 'var(--line)', IL: 'var(--irs)', HANDOFF: 'var(--line)'});   /* [s3-split] the split roll and the insertion list */
const SIDE = {A: 'left', B: 'right', D: 'left', C: 'right', E: 'right'};
const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const json = value => JSON.stringify(value, null, 2);
const clock = t => t ? new Date(t * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '';
const day = t => t ? new Date(t * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
const pct = x => (x == null ? '-' : Math.round(x * 100) + '%');
const num = (x, d = 2) => (x == null || Number.isNaN(+x) ? '-' : (+x).toFixed(d));
/* [cast-names] A character's name as the station answers it now - Dill,
   Skip and Sam unless the DJ options say otherwise - for the labels that
   used to say "The SFX Guy" or "the host". The host page's own poll
   carries it: window.pineCastName on the desktop and the tablet
   (sampler-feed.js), djLastState.dj_names on the control panel. */
const CAST_NAME_KEY = {dj: 'host', host: 'host', a: 'host', cohost: 'cohost', b: 'cohost',
  sfxguy: 'sfx', sfx: 'sfx', drop: 'sfx', third: 'third', d: 'third', guest: 'guest'};
const CAST_NAME_DEFAULT = {host: 'Dill', cohost: 'Skip', sfx: 'Sam'};
function castName(role, fallback) {
  const key = CAST_NAME_KEY[String(role || '').toLowerCase()] || String(role || '');
  try {
    if (typeof window.pineCastName === 'function') return window.pineCastName(key, fallback);
  } catch (e) { /* the panel's poll, below */ }
  let names = {};
  try { names = ((typeof djLastState !== 'undefined' && djLastState) || {}).dj_names || {}; } catch (e) { names = {}; }
  const got = String(names[key] || (key === 'third' ? names.guest : '') || '').trim();
  if (got) return got;
  return fallback !== undefined ? fallback : (CAST_NAME_DEFAULT[key] || '');
}

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  if (typeof props === 'string') node.className = props;
  else if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'style') node.style.cssText = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (k in node && k !== 'list') node[k] = v;
      else node.setAttribute(k, v === true ? '' : v);
    }
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return node;
}
/* replaceChildren() and append() turn a null into the text "null"; these do not. */
function fill(node, ...kids) { node.replaceChildren(...kids.flat().filter(k => k != null && k !== false)); return node; }
function put(node, ...kids) { node.append(...kids.flat().filter(k => k != null && k !== false)); return node; }
const btn = (text, onclick, extra = {}) => el('button', {type: 'button', text, onclick, ...extra});
function block(title, value, open = false) {
  return el('details', {open}, el('summary', {text: title}), el('pre', {text: typeof value === 'string' ? value : json(value)}));
}

/* --- reading recorded events ------------------------------------------- */
function stage(ev, name) { return (ev.stages || []).find(s => s.stage === name); }
function itemDraw(ev) { return stage(ev, 'item') || stage(ev, 'dice') || null; }
function diceOf(ev) { const d = (itemDraw(ev) || {}).draw || ev.rng; return d ? d.dice : null; }

function eventLine(ev, conv) {
  const fam = ev.family, sel = ev.selected || {};
  if (fam === 'GRAPH') {
    const meta = ev.meta || {};
    return {fam, dice: ev.rng ? ev.rng.dice : null,
      text: `${meta.kind || 'Conversation graph'} → ${sel.label || sel.id || ''}${meta.turn_credit ? ' · +1 turn restored' : ''}`};
  }
  if (ev.kind === 'observation' || ev.stage) return observationLine(ev);
  if (fam === 'CTS' && !ev.rng) return {fam, dice: null, text: (sel.id || '').toLowerCase() + ' → ' + (sel.label || '')};
  if (fam === 'HANDOFF') return {fam, dice: diceOf(ev), text: String(sel.label || sel.id || (ev.meta || {}).why || 'length check')};
  if (fam === 'SPLIT' && !ev.rng) return {fam, dice: null, text: String(sel.label || sel.id || '').toLowerCase()};   /* [s3-split] the rule: no draw */
  if (fam === 'SPEAKERBOX') {
    const meta = ev.meta || {};
    if (meta.door) return {fam, dice: ev.rng ? ev.rng.dice : null, text: `door ${meta.door} rolled u=${num(ev.rng && ev.rng.u, 3)} → decided by the station at bind`};
    if (meta.mark === 'act') return {fam, dice: null, text: `${meta.act} is a quote → ${sel.id}`};
    const dice = stage(ev, 'dice');
    if (!dice) return {fam, dice: null, text: `${meta.mark} → not rolled: ${meta.why || ''}`};
    const mat = (conv && conv.material || []).find(m => m.decided_by === ev.event_id);
    let tail = sel.id === 'NONE' ? (dice.selected === 'PASS' ? ' → ' + (meta.why || 'NONE') : '') : ' → ' + sel.id;
    if (mat) tail += ` → ${mat.selected.file}` + (mat.selected.passage && mat.selected.passage.index ? ` → passage ${mat.selected.passage.index}/${mat.selected.passage.of}` : '');
    return {fam, dice: dice.draw.dice, text: `${meta.mark} ${dice.draw.dice}/100 (needs > ${dice.threshold}) → ${dice.selected}${tail}`};
  }
  if (fam === 'TINT' || fam === 'REPAIR' || fam === 'ROOM') {
    const meta = ev.meta || {};
    const d = stage(ev, 'dice');
    if (meta.applies === false || !d) return {fam, dice: null, text: (sel.label || sel.id || '').toLowerCase()};
    return {fam, dice: d.draw ? d.draw.dice : null, text: `${pct(meta.rate)} odds → ${sel.id === 'NONE' || sel.id === 'PLAIN' ? (fam === 'TINT' ? 'plain' : 'stands') : (fam === 'TINT' ? 'rhyme' : fam === 'REPAIR' ? 'goes back if it misses' : 'the Room may touch it')}`};
  }
  if (fam === 'TOPIC') {
    const meta = ev.meta || {};
    const d = stage(ev, 'dice');
    if (meta.applies === false) return {fam, dice: null, text: 'not rolled: ' + (meta.why || 'the round has its own subject')};
    return {fam, dice: d && d.draw ? d.draw.dice : null,
      text: sel.id === 'NONE' ? `${pct(meta.rate)} odds → nothing off the board`
        : `${pct(meta.rate)} odds → "${sel.label}" → turn ${Number(meta.turn_index) + 1}`};
  }
  if (fam === 'TRACK_TALK') {
    const meta = ev.meta || {}, d = stage(ev, 'dice');
    return {fam, dice: d && d.draw ? d.draw.dice : null,
      text: sel.id === 'TRACK_TALK' ? `${pct(meta.rate)} odds → ${sel.label}`
        : `${pct(meta.rate)} odds → no record comment in this banter round`};
  }
  if (fam === 'SFX') {
    const d = stage(ev, 'dice'), p = stage(ev, 'placement');
    return {fam, dice: d && d.draw ? d.draw.dice : null,
      text: `${d ? d.draw.dice + '/100' : ''} (p ${num(d && d.threshold)}) → ${d ? d.selected : ''}${p ? ' ' + p.selected : ''}` +
        ((sel.intent || []).length ? ` · intent: ${sel.intent.slice(0, 3).join(', ')}` : '')};
  }
  const item = stage(ev, 'item');
  const inten = sel.intensity != null ? ` (.${String(Math.round(sel.intensity * 100)).padStart(2, '0')})` : '';
  const where = item ? ` · ${item.selected_index}/${item.of}` : '';
  return {fam, dice: diceOf(ev), text: `${diceOf(ev) || ''}/100${where} → ${(sel.label || sel.id || '').toUpperCase()}${inten}`};
}

function observationLine(o) {
  const fam = o.family;
  if (fam === 'SFX') {
    const m = o.matcher || {}, clip = (o.played || [])[0];
    const cand = m.cands != null ? `candidates ${m.cands} / eligible ${m.eligible} → ` : '';
    return {fam, dice: null, text: `at air (${o.due}) ${cand}${clip ? clip.clip : 'nothing played'}${(o.sfx_guy || []).length ? ' + ' + castName('sfx') : ''}`};   /* [cast-names] */
  }
  if (fam === 'SPEAKERBOX') return {fam, dice: null,
    text: `door ${o.door}: ${o.applies === false ? 'did not apply' : `roll ${num(o.roll, 3)} vs ${num((o.rate || 0) + (o.lift || 0), 2)} → ${o.hit ? 'HIT ' + (o.file || '') : 'miss'}`} (${o.rolled_by})`};
  if (fam === 'INJECT') return {fam, dice: null,
    text: o.card || ('forced: no roll - injected by ' + (o.by || 'the station') + ' because ' + (o.why || 'no reason was recorded'))};   /* [s3-inject] */
  if (fam === 'COMMIT') return {fam, dice: null, text: `script ledger block ${o.block} · ${(o.lines || []).length} line(s) frozen`};
  if (fam === 'REPAIR') return {fam, dice: null, text: 'repair requested: ' + (o.why || '')};
  return {fam, dice: null, text: o.stage || fam};
}

/* A speaker-box mark that brought no passage in: lost the roll, won it with
   no room left in the round, or never rolled (the dial at 0%, or a road
   that carries its own material). Its chip says so - the number it rolled
   against the number it needed - and goes gray. */
function sbOutcome(ev) {
  if (!ev || ev.family !== 'SPEAKERBOX' || ev.kind === 'observation' || ev.stage) return null;
  const meta = ev.meta || {};
  if (meta.door) return null;                       /* engine 1: the station's door decided at bind */
  const got = ((ev.selected || {}).id || 'NONE') !== 'NONE';
  if (meta.mark === 'act') {
    const full = /already carries/.test(String(meta.why || ''));
    return {won: got, label: got ? 'quote' : full ? 'full' : 'none',
      why: got ? 'the response act asked for a quote' : (meta.why || 'no passage came of it')};
  }
  const d = stage(ev, 'dice');
  if (!d || !d.draw) return {won: false, label: 'off', why: 'not rolled: ' + (meta.why || 'the dial is at 0%')};
  const hit = d.draw.dice > d.threshold;
  if (got) return {won: true, label: String(d.draw.dice), why: `rolled ${d.draw.dice}, needed over ${d.threshold} - won`};
  if (hit) return {won: false, label: `${d.draw.dice} full`, why: `rolled ${d.draw.dice}, needed over ${d.threshold} - won, but ${meta.why || 'the round had no room for another passage'}`};
  return {won: false, label: `${d.draw.dice}/${d.threshold}`, why: `rolled ${d.draw.dice}, needed over ${d.threshold} - lost`};
}
function chipOf(ev, conv) {
  const line = eventLine(ev, conv);
  const sb = sbOutcome(ev);
  if (sb) return {text: `${sb.label} ${ev.family}`, miss: !sb.won, title: `${ev.family} ${(ev.meta || {}).mark || ''}: ${sb.why} - tap for how it was decided`};
  return {text: (line.dice != null ? line.dice + ' ' : '') + ev.family, miss: false, title: `${ev.family}: ${line.text} - tap for how it was decided`};
}

function turnEvents(conv, turn) {
  const ids = new Set();
  for (const d of turn.decisions || []) ids.add(d.event_id);
  for (const s of turn.speakerbox || []) ids.add(s.event_id);
  if (turn.sfx) ids.add(turn.sfx.event_id);
  if (turn.sfxguy && turn.sfxguy.event_id) ids.add(turn.sfxguy.event_id);   /* [s3-roads] his node */
  return (conv.decision_events || []).filter(e => ids.has(e.event_id));
}

function replyCaption(turn) {
  if (!turn.reply_to) return '';
  return `${turn.cast_reaction ? 'Cast reaction' : String(turn.graph_node || '').startsWith('__return_') ? 'Topic returns' : turn.inner_reply ? 'Inner reply' : 'Reply'} → ${turn.reply_to.name} · turn ${turn.reply_to.index + 1}${turn.turn_credit ? ' · +1 turn restored' : ''}`;
}

/* --- the moving parts ------------------------------------------------------ */
function drum(candidates, selectedId) {
  const list = el('ul');
  const labels = (candidates || []).map(c => ({id: c.id, label: c.label || c.id}));
  const box = el('div', 'drum s3-drum', list);
  const target = Math.max(0, labels.findIndex(c => c.id === selectedId));
  const render = (rows, hit) => fill(list, ...rows.map((c, i) => el('li', {class: i === hit ? 'hit' : '', text: c.label})));
  render(labels, target);
  list.style.transform = `translateY(${-target * 22}px)`;
  box.roll = async (ms) => {
    if (!labels.length || reduced() || ms <= 0) return;
    // Two passes through the REAL candidate list, then the recorded pick.
    const reel = [...labels, ...labels, ...labels.slice(0, target + 1)];
    render(reel, reel.length - 1);
    list.style.transition = 'none'; list.style.transform = 'translateY(0)';
    await sleep(20);
    list.style.transition = `transform ${ms}ms cubic-bezier(.12,.72,.18,1)`;
    list.style.transform = `translateY(${-(reel.length - 1) * 22}px)`;
    await sleep(ms);
    list.style.transition = 'none'; render(labels, target);
    list.style.transform = `translateY(${-target * 22}px)`;
  };
  /* [s3-imsg] the same reel in two halves: spun so it comes to rest on the
     recorded pick in `ms`, and land() puts it there now */
  box.spin = (ms) => {
    if (labels.length < 2 || reduced() || !(ms > 0)) return;
    const reel = [...labels, ...labels, ...labels.slice(0, target + 1)];
    render(reel, reel.length - 1);
    list.style.transition = 'none'; list.style.transform = 'translateY(0)';
    void list.offsetHeight;                     /* from the top of the reel, not from where it stood */
    list.style.transition = `transform ${Math.round(ms)}ms cubic-bezier(.12,.72,.18,1)`;
    list.style.transform = `translateY(${-(reel.length - 1) * 22}px)`;
  };
  box.land = () => {
    list.style.transition = 'none'; render(labels, target);
    list.style.transform = `translateY(${-target * 22}px)`;
  };
  /* [msgview] parked: the reel at the top of its real candidates, no pick
     shown, until its turn in landInOrder comes */
  box.park = () => {
    if (labels.length < 2 || reduced()) return;
    list.style.transition = 'none'; render(labels, -1);
    list.style.transform = 'translateY(0)';
  };
  return box;
}

function die(value) {
  const node = el('span', {class: 's3-die' + (value == null ? ' none' : ''), text: value == null ? '—' : String(value),
    title: value == null ? 'no random number: this was not a draw' : `d100 landed on ${value} (recorded)`});
  node.roll = async (ms) => {
    if (value == null || reduced() || ms <= 0) return;
    node.classList.add('rolling');
    await sleep(ms);
    node.classList.remove('rolling'); node.classList.add('pop');
    setTimeout(() => node.classList.remove('pop'), 400);
  };
  /* [s3-imsg] the same roll in two halves: tumbling from spin() until
     land() brings its number down with a pop */
  node.rolls = value != null;
  node.spin = () => {
    if (!node.rolls || reduced()) return;
    node.classList.remove('pop');
    node.classList.add('rolling');
  };
  node.land = () => {
    if (!node.classList.contains('rolling')) return;
    node.classList.remove('rolling');
    void node.offsetWidth;                      /* the pop plays again on a die that popped before */
    node.classList.add('pop');
    setTimeout(() => node.classList.remove('pop'), 400);
  };
  return node;
}

function rollRow(ev, conv) {
  const line = eventLine(ev, conv);
  const item = stage(ev, 'item') || stage(ev, 'mode') || stage(ev, 'dice');
  const cands = item && item.candidates ? item.candidates
    : item ? [{id: 'PASS', label: 'PASS'}, {id: 'MISS', label: 'MISS'}, {id: 'PLAY', label: 'PLAY'}].filter(c => c.id === item.selected) : [];
  const d = drum(cands, item ? item.selected : null);
  const face = die(line.dice);
  const sbRoll = sbOutcome(ev);
  if (sbRoll && !sbRoll.won) { face.classList.add('miss'); face.title = sbRoll.why; }
  const row = el('div', {class: 's3-roll', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`},
    el('b', {style: `color:${FAM[ev.family]};min-width:74px`, text: ev.family}), d, face);
  row.roll = async (ms) => { await Promise.all([d.roll(ms), face.roll(ms * 0.85)]); };
  return row;
}

/* [s3-es-reel] THE ES ROLL, IN ITS TWO STAGES. "when animating the RNG roulette
   indent the subcategory for the ES item. The intention is for categories to be
   scrolled via RNG and then the subcategories which is fed to the LLM for
   direction on how to write that particular line in the correspondence and also
   is fed to the intonation engine" (the operator, 2026-09-28). One ES event holds
   both recorded stages of the draw (weighted_decision: the category by its
   weight, then the item inside the won category by the items' weights): the
   category reel scrolls and lands first, with its own die and "k of N
   categories", then the item's reel - indented under it - scrolls and lands,
   with its die and "k of M". Nothing is re-rolled. Anything else (another
   family, a pinned ES row with no stages) gets rollRow. The row it returns has
   .roll(ms) like rollRow's, so any renderer can swap it in - the Messenger's
   reels too. */
function esTwoStageReel(ev, conv) {
  const cat = ev && ev.family === 'ES' && !ev.stage ? stage(ev, 'category') : null;
  const item = cat ? stage(ev, 'item') : null;
  if (!cat || !item) return rollRow(ev, conv);
  const fam = FAM.ES;
  const sel = ev.selected || {};
  const catDrum = drum((cat.candidates || []).map(c => ({id: c.id, label: String(c.label || c.id).toUpperCase()})), cat.selected);
  const catDie = die(cat.draw ? cat.draw.dice : null);
  const itemDrum = drum(item.candidates || [], item.selected);
  const itemDie = die(item.draw ? item.draw.dice : null);
  const catOf = cat.of ? `${cat.selected_index} of ${cat.of} categories` : 'the category';
  const itemOf = (item.of ? `${item.selected_index} of ${item.of}` : 'the feeling')
    + (sel.intensity != null ? ` · intensity .${String(Math.round(sel.intensity * 100)).padStart(2, '0')}` : '');
  const catRow = el('div', {class: 's3-roll s3-es-cat', style: `--fam:${fam}`,
      title: `the category: d100 ${cat.draw ? cat.draw.dice : '-'} landed on ${cat.selected} - ${catOf}, each weighted by its category weight`},
    el('b', {style: `color:${fam};min-width:74px`, text: 'ES'}), catDrum, catDie,
    el('span', {class: 's3-muted', style: 'flex:none;font-size:11px', text: catOf}));
  const itemRow = el('div', {class: 's3-roll s3-es-item', style: `--fam:${fam};margin-left:26px;padding-left:10px;border-left:2px solid ${fam}`,
      title: `the feeling inside ${cat.selected}: d100 ${item.draw ? item.draw.dice : '-'} landed on ${item.selected} - ${itemOf}`},
    el('b', {style: `color:${fam};min-width:38px`, text: 'item'}), itemDrum, itemDie,
    el('span', {class: 's3-muted', style: 'flex:none;font-size:11px', text: itemOf}));
  const box = el('div', {class: 's3-roll s3-es-reel', style: `--fam:${fam};display:grid;gap:2px;align-items:stretch`}, catRow, itemRow);
  box.roll = async (ms) => {
    if (!(ms > 0)) return;
    itemRow.style.opacity = '.35';
    await Promise.all([catDrum.roll(ms), catDie.roll(ms * 0.85)]);
    itemRow.style.opacity = '';
    await Promise.all([itemDrum.roll(ms), itemDie.roll(ms * 0.85)]);
  };
  return box;
}
/* [s3-es-reel] the two stages in one line, for the caption under the reel ("" when not an ES draw) */
function esStagesText(ev) {
  const cat = ev && ev.family === 'ES' && !ev.stage ? stage(ev, 'category') : null;
  const item = cat ? stage(ev, 'item') : null;
  if (!cat || !item) return '';
  const sel = ev.selected || {};
  const inten = sel.intensity != null ? ` (.${String(Math.round(sel.intensity * 100)).padStart(2, '0')})` : '';
  return `${String(sel.category_label || cat.selected || '').toUpperCase()} ${cat.draw ? cat.draw.dice + '/100' : ''} · ${cat.selected_index}/${cat.of}`
    + ` → ${sel.label || item.selected} ${item.draw ? item.draw.dice + '/100' : ''} · ${item.selected_index}/${item.of}${inten}`;
}

/* --- [s3-messenger] the air, line by line ------------------------------------
 *
 * "upcoming showed as their roulette RNG then transitioning to as written. I
 *  want them popping one at a time becoming text live with the audio showing
 *  a loading bar going across each entry during playback as they take place
 *  sequentially" - "one message after another like a script or a text
 *  message. Messages never appear above the current message."
 *
 * A round's line rows are the script ledger's own ({line_id, turn_id, block,
 * ord, who, text}); a board row (a sting) may carry `poster` and `sfx_roll`.
 * The segment inspector's receipt for a line says whether it aired. */
const STALE_S = 45 * 60;            /* a round with no receipt this old is history: its receipts are gone, not pending */
const convAt = c => Number((c && (c.created || (c.inputs || {}).at)) || 0);
const byLedger = (a, b) => ((Number(a.block) || 0) - (Number(b.block) || 0)) || ((Number(a.ord) || 0) - (Number(b.ord) || 0));
const isBoard = l => !!l && (l.who === 'board' || /^(sfx|sfxguy|sting)$/.test(String(l.kind || '')));
const isSpoken = l => !!l && !!l.turn_id && !isBoard(l) && l.who !== 'drop';
const AIRED = new Set(['published', 'stream', 'both', 'box', 'page', 'airing']);
const airOn = a => !!a && (!!a.heard || AIRED.has(a.aired));
const airOff = a => !!a && (a.aired === 'withdrawn' || a.aired === 'never' || !!a.cut_why);
function turnLines(conv, t) {
  return ((conv && conv.lines) || []).filter(l => l.turn_id === t.turn_id && isSpoken(l)).sort(byLedger);
}
/* [s3-banks-roll] what a turn's ledger lines carry past their words: a banked
   round going out again, a gold bar fired off this turn, a listening response
   rolled at its seam - each a chip on the message, in the stamp's own words */
const BANK_TAG_WHY = {
  replay: 'went out again on the roulette (bank.reair, bank.reair_pick)',
  gold: 'a gold bar minted from this turn, fired on the roulette (gold.run / gold.pick)',
  listening: 'a listening response rolled at this seam (listen.seam, listen.pick)'};
function bankTags(conv, t) {
  const seen = new Set(), out = [];
  for (const l of turnLines(conv, t)) {
    for (const k of Object.keys(BANK_TAG_WHY)) {
      const s = l && l[k];
      const label = s && typeof s === 'object' ? String(s.label || '') : '';
      if (!label || seen.has(label)) continue;
      seen.add(label);
      out.push(el('span', {class: 's3-bank-tag s3-bank-' + k, text: label, title: BANK_TAG_WHY[k]}));
    }
  }
  return out;
}
/* 'aired' | 'off' (every line withdrawn or cut) | 'waiting' (receipts, none aired) | 'unknown' (no receipt) */
function airOfLines(lines, air) {
  let seen = 0, off = 0;
  for (const l of lines) {
    const a = air && air.get(l.line_id);
    if (!a) continue;
    seen += 1;
    if (airOn(a)) return 'aired';
    if (airOff(a)) off += 1;
  }
  if (!seen) return 'unknown';
  return off === lines.length ? 'off' : 'waiting';
}
/* Each sting sits after the spoken line before it on the ledger - before the
   first turn when nothing was said yet. Memoised per round object: a refresh
   hands a new object, so the plan is drawn again from the new rows. */
const BOARD_PLAN = new WeakMap();
function boardPlan(conv) {
  if (!conv) return new Map();
  if (BOARD_PLAN.has(conv)) return BOARD_PLAN.get(conv);
  const plan = new Map();
  const turns = new Set((conv.turns || []).map(t => t.turn_id));
  const first = ((conv.turns || [])[0] || {}).turn_id || '';
  let last = '';
  for (const l of (conv.lines || []).slice().sort(byLedger)) {
    if (isSpoken(l)) { if (turns.has(l.turn_id)) last = l.turn_id; continue; }
    if (!isBoard(l) || !l.line_id) continue;
    const host = last || (turns.has(l.turn_id) ? l.turn_id : first);
    if (!host) continue;
    const slot = plan.get(host) || {before: [], after: []};
    (last || host !== first ? slot.after : slot.before).push(l);
    plan.set(host, slot);
  }
  BOARD_PLAN.set(conv, plan);
  return plan;
}
/* A board row's clip name, without the speaker glyph the ledger puts first. */
const boardName = l => String((l && l.text) || '').replace(/^[^\p{L}\p{N}\s]+\s+/u, '').trim();

/* One recorded decision on a turn not yet on air: its d100, its family and
   what it landed on - a drum of the real candidates when there were several,
   so on air it spins through them and stops on the recorded pick. */
function rouletteChip(ev, conv, onclick) {
  const two = esTwoStage(ev, conv, onclick);                        /* [s3-imsg] ES: its category, then its item */
  if (two) return two;
  const line = eventLine(ev, conv);
  const face = die(line.dice);
  const sb = sbOutcome(ev);
  if (sb && !sb.won) face.classList.add('miss');
  const item = stage(ev, 'item') || stage(ev, 'mode') || (ev.family === 'GRAPH' ? (ev.stages || [])[0] : null);
  const pick = String(landedWords(ev, conv) || '').replace(/\s+/g, ' ').slice(0, 48);
  const reel = item && (item.candidates || []).length > 1 ? drum(item.candidates, item.selected)
    : el('span', {class: 's3-rl-pick', text: pick});
  const chip = el('span', {class: 's3-rl-chip' + (sb && !sb.won ? ' miss' : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`,
      'data-event': ev.event_id, role: 'button', tabindex: '0', title: `${ev.family} - tap for how it was decided`, onclick,
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
    face, el('b', {text: ev.family === 'GRAPH' ? (ev.meta || {}).kind || 'GRAPH' : ev.family}), reel);
  chip.roll = ms => Promise.all([face.roll(ms * 0.85), reel.roll ? reel.roll(ms) : null]);
  chip.piece = landPiece(chip, face, reel.spin ? reel : null);      /* [s3-imsg] */
  chip.pieces = [chip.piece];
  return chip;
}
/* [s3-imsg] THE EMOTION IS ROLLED IN TWO. "when animating the RNG roulette
   indent the subcategory for the ES item. The intention is for categories
   to be scrolled via RNG and then the subcategories which is fed to the LLM
   ... and also is fed to the intonation engine" (operator, 2026-09-28). An
   ES decision records a 'category' stage and an 'item' stage, each with its
   own draw: the card shows the category as its chip (its die, the reel of
   the categories) and the item under it, indented (its die, the reel of that
   category's items). On air the category lands first, then the item, then
   the card holds - the same landInOrder as every die. The shape - a parent
   row, an indented child row joined by an elbow - is the two-stage reel the
   line card and the Rolodex use. null when the event has not both stages. */
function esTwoStage(ev, conv, onclick) {
  if (!ev || ev.family !== 'ES') return null;
  const cat = stage(ev, 'category'), item = stage(ev, 'item');
  if (!cat || !item || !cat.draw || !item.draw) return null;
  const sel = ev.selected || {};
  const row = (st, cls, label, pickText) => {
    const face = die(st.draw.dice);
    const reel = (st.candidates || []).length > 1 && st.candidates.some(c => c.id === st.selected) ? drum(st.candidates, st.selected)
      : el('span', {class: 's3-rl-pick', text: pickText});
    const r = el('span', {class: 's3-rl-chip ' + cls, style: `--fam:${FAM.ES}`}, face, label ? el('b', {text: label}) : null, reel);
    r.piece = landPiece(r, face, reel.spin ? reel : null);
    return r;
  };
  const catText = String(sel.category_label || sel.category || cat.selected || '').toLowerCase();
  const itemText = String(sel.label || sel.id || item.selected || '').replace(/^[^.]*\./, '');
  const parent = row(cat, 's3-rl-es-cat', 'ES', catText);
  const child = row(item, 's3-rl-es-item', '', itemText);
  child.prepend(el('i', {class: 's3-rl-elbow', 'aria-hidden': 'true'}));
  const chip = el('span', {class: 's3-rl-es', style: `--fam:${FAM.ES}`, 'data-event': ev.event_id, role: 'button', tabindex: '0',
      title: `ES - the category (d${cat.draw.dice}), then the item in it (d${item.draw.dice}) - tap for how it was decided`, onclick,
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
    parent, child);
  chip.pieces = [parent.piece, child.piece];
  chip.piece = parent.piece;
  chip.roll = ms => Promise.all([...chip.querySelectorAll('.s3-die')].map(d => d.roll(ms * 0.85)));
  return chip;
}
/* [s3-imsg] THE DICE COME DOWN ONE AFTER ANOTHER. "I want them sequentially
   landing on their numbers. So it's one, two, three, four, landing on their
   result, and then it cycles over to showing the result of what was
   generated" (operator, 2026-09-28). A card's pieces - each chip's die and
   its reel - all tumble from the start; the first lands one step in, the
   next a step later, each with its pop, in the card's order; then, "sit
   ... before transitioning to the message so that way there's an impact" -
   and long enough to read each result: every die holds still on its number
   for DICE_HOLD_MS (1.5 s, the operator's figure, 2026-09-28; it was half a
   second) and only then does the promise settle. hurry() brings the rest
   down fast, still in order, and cuts the hold: the air moved on
   mid-sequence (nothing else shortens it). A step is DIE_STEP ms, tighter
   when there are many, so the dice stay inside DICE_CAP. Frames AND timers
   drive it: a tablet WebView can stall either. */
const DIE_STEP = 400, DICE_CAP = 2000, DICE_HOLD_MS = 1500, DIE_HURRY = 90;
function landPiece(chip, face, reel) {
  return {
    rolls: !!(face && face.rolls) || !!reel,
    face, reel, chip,                                   /* [msgview] the phases land each part */
    sub: !!(chip && chip.classList && chip.classList.contains('s3-rl-es-item')),
    spin(ms) {
      chip.classList.remove('s3-landed');
      chip.classList.add('s3-spinning');
      if (face && face.spin) face.spin();
      if (reel) reel.spin(ms);
    },
    land() {
      if (face && face.land) face.land();
      if (reel) reel.land();
      chip.classList.remove('s3-spinning');
      chip.classList.add('s3-landed');
      setTimeout(() => chip.classList.remove('s3-landed'), 700);
    },
  };
}
function landInOrderOne(pieces) {       /* [msgview] the one-phase original, kept, unused */
  const list = (pieces || []).filter(p => p && p.rolls);
  const step = list.length ? Math.min(DIE_STEP, DICE_CAP / list.length) : 0;
  const t0 = performance.now();
  const at = list.map((p, i) => t0 + (i + 1) * step);
  let next = 0, hurried = false, over = false, restAt = 0, raf = 0, timer = 0, settle = null;
  const done = new Promise(resolve => { settle = resolve; });
  const tick = () => {
    if (over) return;
    const now = performance.now();
    while (next < list.length && now >= at[next] - 4) { list[next].land(); next += 1; }
    if (next >= list.length) {
      if (!restAt) restAt = list.length && !hurried ? now + DICE_HOLD_MS : now;
      if (now >= restAt - 4) {
        over = true;
        cancelAnimationFrame(raf); clearTimeout(timer);
        settle();
        return;
      }
    }
    cancelAnimationFrame(raf); clearTimeout(timer);
    raf = requestAnimationFrame(tick);
    timer = setTimeout(tick, Math.max(12, (next < list.length ? at[next] : restAt) - now));
  };
  done.count = list.length;
  done.step = step;
  done.hurry = () => {
    if (hurried || over) return;
    hurried = true;
    const now = performance.now();
    for (let i = next; i < list.length; i += 1) at[i] = Math.min(at[i], now + (i - next + 1) * DIE_HURRY);
    if (restAt) restAt = Math.min(restAt, now);
    tick();
  };
  list.forEach((p, i) => p.spin(at[i] - t0));
  tick();
  return done;
}
/* [msgview] THE DICE FIRST, THEN THE ROLODEX, THEN THE SUB-RESULT. "With every
   message ... I want to see the RNG dice rolls first, where they each stop in
   succession one, two, three, four, five, so on. Then the roulette system
   rolling through the roller deck for the result, and then the roll of deck's
   rolling for the sub result for each item" (operator, 2026-09-28). One clock,
   three phases: every die tumbles from the start and they stop one after
   another (DIE_STEP apart, inside DICE_CAP) while the reels stand parked at
   the top of their real candidates; then, table by table, each reel scrolls
   through its real candidates and lands on the recorded pick - a table's
   result, then its sub-result (the ES item under its category) - REEL_STEP
   apart inside REEL_CAP; then everything holds DICE_HOLD_MS. hurry() brings
   the rest down fast, still in order, and cuts the hold. Frames AND timers
   drive it (a tablet WebView can stall either). done.total is the whole run. */
const REEL_STEP = 650, REEL_CAP = 3200, REEL_GAP = 220;
function landInOrder(pieces) {
  const list = (pieces || []).filter(p => p && p.rolls);
  const dice = list.filter(p => p.face && p.face.rolls);
  const reels = list.filter(p => p.reel && typeof p.reel.spin === 'function');
  const stepD = dice.length ? Math.min(DIE_STEP, DICE_CAP / dice.length) : 0;
  const stepR = reels.length ? Math.min(REEL_STEP, REEL_CAP / reels.length) : 0;
  const t0 = performance.now();
  const dEnd = t0 + dice.length * stepD + (dice.length && reels.length ? REEL_GAP : 0);
  const parts = new Map(list.map(p => [p, (p.face && p.face.rolls ? 1 : 0) + (reels.includes(p) ? 1 : 0)]));
  const partDone = p => {
    const left = (parts.get(p) || 1) - 1;
    parts.set(p, left);
    if (left > 0 || !p.chip) return;
    p.chip.classList.remove('s3-spinning');
    p.chip.classList.add('s3-landed');
    setTimeout(() => p.chip.classList.remove('s3-landed'), 700);
  };
  const steps = [];
  dice.forEach((p, i) => steps.push({at: t0 + (i + 1) * stepD, go: () => { p.face.land(); partDone(p); }}));
  reels.forEach((p, j) => {
    const from = dEnd + j * stepR;
    steps.push({at: from, spin: true, go: () => p.reel.spin(Math.max(120, stepR - 60))});
    steps.push({at: from + stepR, go: () => { p.reel.land(); partDone(p); }});
  });
  let next = 0, hurried = false, over = false, restAt = 0, raf = 0, timer = 0, settle = null;
  const done = new Promise(resolve => { settle = resolve; });
  const tick = () => {
    if (over) return;
    const now = performance.now();
    while (next < steps.length && now >= steps[next].at - 4) { steps[next].go(); next += 1; }
    if (next >= steps.length) {
      if (!restAt) restAt = list.length && !hurried ? now + DICE_HOLD_MS : now;
      if (now >= restAt - 4) {
        over = true;
        cancelAnimationFrame(raf); clearTimeout(timer);
        settle();
        return;
      }
    }
    cancelAnimationFrame(raf); clearTimeout(timer);
    raf = requestAnimationFrame(tick);
    timer = setTimeout(tick, Math.max(12, (next < steps.length ? steps[next].at : restAt) - now));
  };
  done.count = list.length;
  done.step = stepD;
  done.total = (steps.length ? steps[steps.length - 1].at - t0 : 0) + DICE_HOLD_MS;
  done.hurry = () => {
    if (hurried || over) return;
    hurried = true;
    const now = performance.now();
    let k = 0;
    for (let i = next; i < steps.length; i += 1) {
      if (!steps[i].spin) k += 1;
      steps[i].at = Math.min(steps[i].at, now + k * DIE_HURRY);
    }
    if (restAt) restAt = Math.min(restAt, now);
    tick();
  };
  list.forEach(p => {
    if (p.chip) { p.chip.classList.remove('s3-landed'); p.chip.classList.add('s3-spinning'); }
    if (p.face && p.face.spin) p.face.spin();
    if (p.reel && typeof p.reel.park === 'function') p.reel.park();
  });
  tick();
  return done;
}
/* A wait on frames, not timers: a tablet WebView's timers can stall while its
   frames keep coming, and a roll must never hold the words back for ever. */
function frameSleep(ms) {
  const t0 = performance.now();
  return new Promise(resolve => {
    const step = () => { if (performance.now() - t0 >= ms) resolve(); else requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });
}

/* --- the decision card -----------------------------------------------------
 *
 * "If I tap on any of these buttons in messenger view, I want to bring up a
 *  pop up with detailed information on what it is and be able to see what
 *  information was being accessed and how it got to this value."
 *
 * Built only from what was recorded: the event's own stages (candidates,
 * effective weights and their reasons, the raw u and its d100), the state
 * it read and left, the dials and inputs of its conversation, the material
 * the station fetched for it and what played at air. The arithmetic shown
 * - d100 = floor(u x 100) + 1, and u x total weight landing in one
 * candidate's slice - is the engine's own (system3.pick_index), re-done
 * here from the recorded numbers, never estimated. */
const FAMILY_WHAT = {
  /* [s3-memory] rules, then roulette */
  MEMORY: ['Memory context (MEMORY1)',
    'What the writer is reminded of for this round, and only when it is relevant: the clock near the top of the hour or the end of a segment, the last topic when this round carries it on or turns from it, the last segment and how it went at the start of the next, the calls against the hourly quota when the booth is behind or ahead, the manager\'s last word while it is fresh. Each kind\'s rule - its numbers in Tables > MEMORY1 - decides whether it is eligible, and every verdict is on the card; then the roulette draws among the eligible kinds (at least one, at most two a round by default - how many is itself a die when those differ), and a die picks the way each is put when more than one fits. The items drawn are the round\'s memory block, word for word, landed on its first turn; nothing else of the old "Tonight so far" reaches a round a MEMORY roll stands behind. A round written now to air later is told none of it unless a rule\'s on_banked switch says so.'],
  CTS: ['Conversation / Segment Topic (CTS1)',
    'What the round is about. System 3 draws a subject only where it has the authority to: a road that arrives with its own material (a speakerbox seed, a wire story, a memo, a painting) has that as an obligation, recorded here and never drawn over. A frame that cancels the topic lets the next cycle draw a new one.'],
  ES: ['Emotional Set (ES1)',
    'The emotion this turn is spoken in. It is written into the running order the writer follows, and it reaches the voice: the emotion becomes the six performance dimensions that set pace, pitch movement, energy and pauses on the rendered take.'],
  RS: ['Response Set (RS1 / RS2)',
    'How this speaker takes what was just said - agree, argue, mock, push back, ask. The writer is told to perform it and quote back the word or claim it answers.'],
  IRS: ["Initiator's Response (IRS1 / IRS2)",
    'How the one who started the exchange answers the responses - hold the line, double down, counter, concede, laugh it off. Conceding is one outcome among many, not the default.'],
  FL: ['Flow (FL1 frames, FL2 moves)',
    'Where the conversation goes next: the frame at the end of a cycle (reframe, cancel the topic, acquiesce, anger, enjoyment) or the move a response makes. Weighted by the radio clock: tangents fade and closing moves rise as the time runs out.'],
  get SFXGUY() { return [castName('sfx') + "'s mouth",   /* [cast-names] his name, read when shown */
    "Whether " + castName('sfx') + " (the SFX guy) pipes up after this line, at the desk's own interjections dial, and what kind of line: a story off the wire, a reaction fired back at this very line, or a saying off his shelf. The line itself is drawn at air from the first kind that has something to say, and that draw - every candidate and the die - is recorded under his line."]; },
  LINE: ['Line draw',
    'A single-voice road handed System 3 its list - the stock lines, the ad book - and one entry was drawn here, every candidate and its weight recorded. This is the Rolodex where the station used to call random.choice().'],
  SPEAKERBOX: ['Speaker-box',
    "Whether a passage from your speakerbox documents is read with this line - before it (prepend), after it (append), worked in, or as an opening monologue. A d100 against your slider decides whether; the station's own rotation (locks, themes, cooldowns) decides which document. When a line's prepend and append both win, the prepend-or-append roulette (SBEND1 in Tables) picks the one that is read and the other is withdrawn."],   /* [s3-sb-end] */
  get SFX() { return [castName('sfx') + "'s clips",   /* [cast-names] */
    "Whether " + castName('sfx') + " (the SFX guy) wants a clip at this line, before or after it, and what it should be about. The station's matcher and rotation choose the real file from the indexed book; the two-line cadence is never reduced."]; },
  TOPIC: ["Topic (the operator's board)",
    'Whether something off your topics board comes up in this round, which one, and on which turn - three draws, all recorded. The Topics dial sets the odds (0.5: 40% of rounds, 1.0: 80%, 0: never) and the least-sprung topics weigh most. The chosen turn still answers the line before it, then brings the topic up in its own words; a "1. / 2." entry is said word for word and answered word for word on the next turn. Nothing else puts a topic into a conversation.'],
  TRACK_TALK: ['Live record comment', 'A recorded roulette draw decides whether one turn of live banter briefly connects to the record playing under it. Banked rounds never name a record that may have changed before air.'],
  COMMIT: ['Script ledger', 'The round was frozen into the script ledger in the order it will be heard.'],
  /* [s3-rounds] dj_banter's prompt randoms, as rolls */
  TEMPER: ['Temper (TEMPER1)',
    'The temper this host is caught in tonight - one draw per seat per round when the desk\'s dice_hosts switch is on. It goes into the running order\'s head and colours every turn underneath its own rolled feeling; a temper worn in the last rounds weighs a quarter.'],
  SHOCK: ['Shock beat (SHOCK1)',
    'Whether one speaker is openly taken aback by what the other has JUST said - says so, and the rest of the round is driven by it - which reaction, and on which turn. Three recorded draws; the shock_beat control sets the odds (0.5: one round in two).'],
  INTERJECT: ['Interjections (INTERJECT1 or the desk\'s list)',
    'Whether one host goes on a roll and the other gets a word in edgewise, on which turn, and which three phrases. The interjection and the carry-on are turns of their own in the running order, so the seat order the bind aligns on is exactly what the writer was told. Banter only; never on a call.'],
  MENTION: ['Station-name mention',
    'Whether the station\'s name is worked in once this round, and on which turn (the mention control: 0.5 is the old 30%). Otherwise the station IDs carry it.'],
  CARRY: ['Carry (the last round\'s ending)',
    'No draw. The round that aired last handed on each host seat\'s ending emotion, position and energy, the dynamics, its unresolved points and the line it landed on; decayed by its age over 20 minutes, that is where this round starts - and turn 1 picks up from that landing. A banked round takes it in the voice only, at air.'],
  WITHHELD: ['Withheld', 'The round was planned and will not air: the reason is on the card (the writer was deferred, came back with no turns, or the draft was refused). Nothing stands in for it.'],
  ABANDONED: ['Abandoned', 'Planned and never bound within half an hour - the station took an exit System 3 was not told about. Filed by the sweep so every spin of the Rolodex is accounted for.'],
  REPAIR: ['Sent back to the writer',
    'Whether a round that misses its target - the running order ignored, the richness target missed, a call contract failed - goes back to the writer for one rewrite, or stands as written. Rolled once per round at the odds of the Repair control; on System 3 rounds the review gates no longer decide it.'],
  TINT: ['Rhyme this line (the crystal tint)',
    "Whether the crystal tint's rhyme pass may touch this line. The station used to take the first N eligible lines for its coverage; under System 3 the dice choose the lines, at the odds of the Tint control (0.5 = half the lines). When the station's tint pass is off, one event on the round says so and nothing rolls."],
  ROOM: ["The Writers' Room",
    "Whether the Writers' Room may add to or rewrite this round later (its two tickets: add turns to a round that owes structure, rewrite a round whose topic or words drifted). Rolled once per round at the odds of the Room control; a round that rolled no is left alone."],
  LENGTH: ['Length', 'How many turns the round runs: one roll over the segment\'s budget band - never shorter than the slot asked for, at most one and a half times it - so the round fits its hour.'],
  VARIANT: ['Structure variant', 'Which structure of the road runs this round: the road\'s own segment or one of its variants on the desk, one weighted draw among them.'],
  FAV: ['Favourite (FAV1)',
    'Whether a line the operator liked comes up in this round or line, which one, and on which turn - three draws, all recorded. The pool is every thumbs-up from the whole cast; the Favorites control is the odds (0.25: one in four). A favourite that came up lately weighs a quarter. The writer is told to say something NEW in its spirit and attitude - never to repeat or quote it - and a turn that copies it fails validation.'],
  STATION: ['Station roll (STATION1 / POOLS1)',
    'A roll a station road made for the air before this round was planned - a caller preferring a host, a prize, a hostile turn, which state they ring in, how the call ends. System 3 rolled it: the odds are its STATION1 row (or the desk dial the row follows), and the options of a pick are its POOLS1 list - both edited in Tables. Recorded here, not re-planned.'],
  EVENT: ['Happening (CALLEVENT1 and any EVENT table)',
    'Something that happens in the segment - a caller who gets emotional, wins a prize, turns on the hosts, hears from upstairs, goes off on a tangent, gets interrupted by what is going on around them, or loses the line. Each kind has its own odds per segment (a die); a hit draws which variant and which turn of its seat. An ending cuts the segment on that turn and a host reacts to the dead line. Edited in Tables: odds, seat, place, ends, earliest turn.'],
  DIRECTIVE: ["Operator's directive (DIRECTIVE1)",
    'One of your directives for this seat, from System 3 > Tables > DIRECTIVE1. Each row has its own odds: 100% is a standing rule (recorded, not drawn), lower is a die. A hit lands on one of that seat\'s turns, drawn here. A row can expire by date or after a number of airings.'],
};
/* [s3-mgrtopics] the manager's message downstairs: its main topic, his approach, the sub message */
Object.assign(FAM, {MGRTOPIC: 'var(--topic)', MGRAPPROACH: 'var(--rs)', MGRSUB: 'var(--irs)'});
Object.assign(FAMILY_WHAT, {
  RWFEATURE: ['Rewrite application feature', 'A recorded equal draw from the same tagged application-feature release-log catalog used by H3.'],
  RW: ['Scenario rewrite pass (RW1)', 'An equally likely approved rewrite request for rejected dialogue. Required source/feature material must be available. A special pass grants a bounded rewrite attempt and keeps recording and broadcast validation in force.'],
  CALLOPEN: ['Caller opening intent', 'Equally likely approved ways to pick up the call in fresh words. Repairs exclude the failed intent for one retry.'],
  CALLANGLE: ['Caller premise angle', 'An equally likely way to develop the caller premise; preserve its source, facts and story continuity.'],
  CALLSTAKES: ['Caller stakes', 'An equally likely fictional complication or stakes lens connected to the premise.'],
  CALLPROBE: ['Grounded caller follow-up', 'An equally likely follow-up action responding to a concrete detail the previous speaker supplied. Emotion rolls remain independent and can agree or oppose.'],
  CALLSOURCE: ['Caller premise source', 'Equal chances among available Speakerbox, topic database, internet search and station context. Failed or unavailable sources show their exclusion reasons. A repair retains its premise.']
});
Object.assign(FAMILY_WHAT, {
  MGRTOPIC: ["The manager's topic (MGRTOPIC1 + the topics board)",
    "The main topic of the station manager's message downstairs. Two stages: a group of his own topics or the station's topics board (each group's weight), then the topic. A topic he said in his last few messages cannot come up and one said a little longer ago weighs less (the 'rest' knobs on MGRTOPIC1); a row switched off never lands. Edited in Tables > MGRTOPIC1 (the board is the Topics board list)."],
  MGRAPPROACH: ["The manager's approach (MGRSUB1)",
    "How he comes at them about the topic: intimidate, ingratiate, horrify or discuss - the categories of MGRSUB1, each weight its odds. The approach he used last time weighs half."],
  MGRSUB: ["The manager's sub message (MGRSUB1)",
    "The angle he uses on the topic, inside the approach drawn ({topic} is the topic). A row written for particular topics only comes up for them, and weighs three times as much when it does; one he used in his last few messages is out. Edited in Tables > MGRSUB1."],
});
/* [s3-callend] how a call ends: the caller's wheel and the wrap call */
Object.assign(FAMILY_WHAT, {
  RESOLVE: ["Resolution - the caller's wheel (RESOLVE1)",
    "How the call resolves, rolled at the end of its node tree. The caller's wheel lands on one outcome - when the last segment was selling a painting, the painting wheel (buys it, wins it in the raffle as caller number N, turns it down, turns it down in a speakerbox passage, buys it and sets it on fire, ignores it, can't afford it); otherwise the general wheel - then which station seat sets it up, how many station turns answer it (the response chain) and who. Each is its own die, every candidate and why it could or could not come up recorded. The caller then gets the last word (the rebuttal) and WRAP CALL ends it. Edited in Tables > RESOLVE1: rows, weights, offers, effects, the chain's weights."],
  WRAP: ['Wrap call (WRAP1)',
    "Who on the station ends the call, and how - in answer to the caller's last word. Two dice: the way (a polite goodbye, cutting them off mid-sentence, hold forever, the dial tone ... - some only after a resolution, like enjoying the ashes after a painting was set on fire; a call a happening cut short draws from the dead-line wheel) and who says it (the desk's weights by seat). The station's checker takes this node as the sign-off whatever its words. Edited in Tables > WRAP1."],
});
Object.assign(FAMILY_WHAT, {   /* [supercut-react] the booth's stance on the supercut */
  BOOK: ['Book work (BK1 manner, BK2 angle, BK3 errand)',
    'What a host does with the book in hand on the Book Time roads (book_open, book_read, book_close): the manner the next passage is read in, the angle the other host takes on it, and the errand run with the book - rolled per turn, never gated.'],
  WELCOME: ['The welcome (BK4)',
    'The shape Book Time opens in tonight, rolled on the two welcome legs of the book_open road: the book first, as if the listener just walked in, one word then the book, a question, a confession, formally, already reading, mid-argument, a promise. The station and the book are always named; the words are never the same welcome twice.'],
  SIGNOFF: ['The sign-off (BK5)',
    'The shape Book Time closes in tonight, rolled on the sign-off leg of the book_close road: the book has the last word, a promise for next time, plain thanks, a verdict, a question left open, abruptly, a dedication, the argument unsettled, quietly, a recommendation. The book is named and the music handed back every time.'],
  REACT: ['Supercut stance (REACT1)',
    'How a host takes the supercut that just played, rolled once per turn on the supercut_react road: loves it, hates it, split, wants it as the jingle, baffled, moved, suspicious, reviews it - each item a direction the host performs and never names. The wheel decides whether they love it or not.'],
});
Object.assign(FAMILY_WHAT, {   /* [s3-split] */
  SPLIT: ['Split (a long read shared out)',
    'Whether a long read on a node whose split box is ticked is shared out among the studio. The rule decides it with no dice: the read\'s characters over the voice\'s pace, against the threshold in Config > split (45 s), cut at sentence ends into the fewest parts that fit - up to the node\'s 1 to 3 splits, never inside a sentence. Then one roll per part after the first picks who carries it on: the studio as it is now, never the one reading, never the same voice twice in a row, at the split section\'s weights.'],
  IL: ['Insertion list (IL1)',
    'How the voice the split roll picked takes the read over: the way (grabs the sheet, finishes the sentence, cuts in, picks up where they trailed off, politely, heckles) and the few words said on the way in, before the read carries straight on. Edited in Tables > IL1; a way already used on this read weighs a quarter.']});
Object.assign(FAMILY_WHAT, {HANDOFF: ['Sentence handoff roulette', 'A character threshold is drawn once for each speaker turn. At sentence endings at or above it, the recorded checkpoint chooses whether that voice continues or hands off. A handoff chooses another studio voice, then whether they respond or carry the remaining ideas. Hard caps, extra-turn limits, protected text and any dropped tail are shown in Length and handoffs. Edit future rounds in Controls > Sentence handoff roulette.']});
Object.assign(FAMILY_WHAT, {   /* [s3-inject] the honest forced card */
  INJECT: ['Forced onto the air (no roll)',
    'Something the station forced onto the air with no dice: the dead-air rescue putting a finished round out of turn, boot recovery republishing what a restart cut off, the level gate covering a live set that dropped out, MX Live taking or giving back the air, or a fixed surface (the Pine Cam) standing on the wall. The card says who injected it and why, at its point in the timeline - an injected node in the segment\'s executed tree, never an orphan, and never a faked roll.'],
});
const DIAL_FOR = {ES: ['emotional_volatility'], RS: ['disagreement', 'escalation', 'tangent', 'callback', 'novelty'],
  IRS: ['disagreement', 'escalation'], FL: ['tangent', 'callback', 'novelty', 'closure_aggressiveness', 'escalation'],
  SPEAKERBOX: ['speakerbox_density'], SFX: ['sfx_aggression'], CTS: ['novelty'], TOPIC: ['topics'],
  TINT: ['tint'], REPAIR: ['repair'], ROOM: ['room'], FAV: ['favorites'],
  SHOCK: ['shock_beat'], INTERJECT: ['interjections'], MENTION: ['mention'], TRACK_TALK: ['track_talk']};   /* [s3-rounds] */

/* [s3-split] THE SPLIT NODE'S SWITCH on a step or a leg: "splits being a checkbox we
   can enable to a particular message node" (the operator, 2026-09-28) - and how many
   times one read may be split, 1 to 3. A read past the threshold in Config > split is
   shared out among the studio: SPLIT rolls who carries it on, IL1 how they take over. */
function splitBox(node, redraw, where) {
  const on = node.splits === true;
  const most = el('select', {'aria-label': 'most splits', disabled: !on,
    onchange: e => { node.max_splits = +e.target.value; if (redraw) redraw(); }},
    ...[1, 2, 3].map(n => el('option', {value: String(n), text: 'up to ' + n + (n === 1 ? ' split' : ' splits'), selected: (node.max_splits || 3) === n})));
  return el('div', 's3-row s3-split-box',
    el('label', {class: 's3-row', title: where === 'step'
      ? 'a speaker-box monologue read on this step is shared out when it runs past the split threshold'
      : 'a read on this node that runs past the split threshold is shared out: the roulette picks who carries it on (SPLIT) and how they take over (IL1)'},
      el('input', {type: 'checkbox', checked: on, onchange: e => {
        node.splits = e.target.checked; if (e.target.checked && !node.max_splits) node.max_splits = 3; if (redraw) redraw(); }}),
      'split a long read'), most);
}

function kv(pairs) {
  return el('div', 's3-kv', ...pairs.filter(p => p && p[1] !== undefined && p[1] !== null && p[1] !== '')
    .map(([k, val]) => el('div', null, el('span', {text: k}), el('b', {text: String(val)}))));
}
function sectionOf(title, ...kids) { return el('section', 's3-dsec', el('h3', {text: title}), ...kids); }
function para(text, cls) { return el('p', {class: cls || '', text}); }
/* [s3-handoff] These controls edit the next round's policy. Historical lines
   retain their recorded policy and rolls; desk defaults are never their proof. */
const HANDOFF_DEFAULTS = {enabled: true, thresholds: [250, 350, 450, 550],
  continue_probability: 0.25, respond_probability: 0.75, hard_chars: 800,
  max_extra_turns: 3, writer_retries: 2};
function handoffPolicyEditor(current, savePolicy) {
  const draft = {...HANDOFF_DEFAULTS, ...JSON.parse(JSON.stringify(current || {}))};
  const note = el('span', {class: 's3-muted', role: 'status'});
  const field = (label, input, help) => el('label', 's3-row', el('span', {text: label}), input,
    help ? el('span', {class: 's3-muted', text: help}) : null);
  const enabled = el('input', {type: 'checkbox', checked: draft.enabled, 'aria-label': 'Sentence handoffs enabled'});
  const thresholds = el('input', {type: 'text', value: draft.thresholds.join(', '), 'aria-label': 'Handoff thresholds in characters'});
  const numbers = {};
  const number = (key, min, max, step = 1) => numbers[key] = el('input', {type: 'number', min, max, step,
    value: draft[key], 'aria-label': key.replace(/_/g, ' ')});
  const continuing = number('continue_probability', 0, 1, 0.01);
  const responding = number('respond_probability', 0, 1, 0.01);
  const continuationShare = el('b');
  const responseShare = el('b');
  const shares = () => {
    continuationShare.textContent = `${pct(Number(continuing.value))} continue / ${pct(1 - Number(continuing.value))} hand off`;
    responseShare.textContent = `${pct(Number(responding.value))} respond / ${pct(1 - Number(responding.value))} carry remaining ideas`;
  };
  continuing.addEventListener('input', shares); responding.addEventListener('input', shares); shares();
  const cap = number('hard_chars', 20, 2000);
  const extra = number('max_extra_turns', 0, 24);
  const retries = number('writer_retries', 0, 3);
  const save = btn('Save handoff policy', async () => {
    const raw = thresholds.value.split(',').map(x => x.trim());
    const values = raw.map(Number);
    if (!raw.length || raw.length > 16 || raw.some(x => !x) || values.some(x => !Number.isInteger(x) || x < 20 || x > 800) || new Set(values).size !== values.length) {
      note.textContent = 'Use up to 16 distinct whole character counts from 20 to 800, separated by commas.'; return;
    }
    for (const input of Object.values(numbers)) if (!input.checkValidity() || input.value.trim() === '') {
      note.textContent = 'Check the numeric limits before saving.'; input.reportValidity(); return;
    }
    if (Math.max(...values) > Number(cap.value)) { note.textContent = 'Thresholds must not exceed the hard character cap.'; return; }
    const next = {...draft, enabled: enabled.checked, thresholds: values};
    for (const [key, input] of Object.entries(numbers)) next[key] = Number(input.value);
    save.disabled = true; note.textContent = 'Saving handoff policy...';
    try { await savePolicy(next); note.textContent = 'Saved. Future rounds use this policy; this message keeps its recorded decisions.'; }
    catch (e) { note.textContent = 'Not saved: ' + ((e && e.message) || e); }
    finally { save.disabled = false; }
  });
  return el('div', 's3-card s3-handoff-policy', el('h2', {text: 'Sentence handoff roulette'}),
    para('One equally weighted character threshold is drawn for each speaker turn. At sentence endings at or above it, the roulette chooses whether that speaker continues or another voice takes over.', 's3-muted'),
    field('Enabled', enabled), field('Threshold candidates', thresholds, 'characters; equal weight'),
    field('Continue probability', continuing), continuationShare,
    field('Respond probability', responding), responseShare,
    field('Hard character cap', cap), field('Extra turns per conversation', extra), field('Writer retries', retries),
    el('div', 's3-row', save, note));
}



/* Recorded lengths only. Older originals may have words and a replay receipt,
   but those do not recover their missing draft or assembly provenance. */
function handoffReceiptData(conv, turn) {
  const parentId = turn.handoff_parent || (turn.handoff || {}).parent_turn_id || '';
  const parent = (conv.turns || []).find(t => t.turn_id === parentId) || null;
  const trace = turn.length_trace || (parent && parent.length_trace) || null;
  const receiptEvent = trace && typeof trace.receipt === 'string' ? (conv.decision_events || []).find(e => e.event_id === trace.receipt) : null;
  const receipt = trace && typeof trace.receipt === 'object' && trace.receipt ? trace.receipt : (receiptEvent && receiptEvent.meta) || {};
  const assembly = (trace && trace.assembly) || receipt.assembly || {};
  const roundScope = assembly.scope === 'round';
  const sourceChanges = [trace && trace.source_changes, trace && trace.mutations,
    receipt.source_changes, receipt.mutations].find(Array.isArray) || [];
  const refs = new Set();
  const ref = value => { if (typeof value === 'string' && value) refs.add(value); };
  if (trace) {
    ref(trace.threshold_event); ref(trace.receipt);
    for (const point of trace.checkpoints || []) ref(point.event_id);
    for (const row of trace.insertions || []) for (const key of ['speaker_event', 'mode_event', 'threshold_event']) ref(row[key]);
    ref((trace.duplicate_repair || {}).event_id);
  }
  for (const key of ['speaker_event', 'mode_event', 'threshold_event']) ref((turn.handoff || {})[key]);
  const own = new Set(turnEvents(conv, turn).filter(e => ['HANDOFF', 'SPLIT', 'IL'].includes(e.family)).map(e => e.event_id));
  const events = (conv.decision_events || []).filter(e => refs.has(e.event_id) || own.has(e.event_id));
  return {trace, receipt, assembly, roundScope, sourceChanges, parentId, inherited: !!(trace && !turn.length_trace), events,
    draftChars: trace && !roundScope ? (trace.draft_chars ?? receipt.draft_chars ?? null) : null};
}
function handoffReceipt(conv, turn, openEvent) {
  const data = handoffReceiptData(conv, turn);
  const {trace, receipt, assembly, roundScope, sourceChanges, events} = data;
  const out = el('div', 's3-handoff-receipt');
  const showEvent = ev => {
    const name = (ev.meta || {}).kind || ev.family;
    const line = eventLine(ev, conv);
    return btn(`${name}: ${line.text}${line.dice != null ? ' - d100 ' + line.dice : ''}`,
      () => openEvent(ev), {class: 's3-fx-open', title: ev.event_id});
  };
  if (data.parentId) out.append(para('Handoff from turn ' + data.parentId + (data.inherited ? '. The receipt below belongs to that original turn.' : '.'), 's3-muted'));
  if (!trace) {
    out.append(para('No length or handoff receipt was recorded for this original. Its draft length, source changes and reason for staying whole are unavailable. A later replay does not establish what happened to this recording.', 's3-muted'));
  } else {
    out.append(kv([
      ['Draft characters', data.draftChars ?? 'unavailable'],
      ['Before handoff', trace.original_chars ?? 'unavailable'],
      ['Final characters', trace.final_chars ?? 'unavailable'],
      ['Drawn threshold', trace.threshold != null ? trace.threshold + ' characters' : 'not drawn'],
      ['Hard cap', trace.hard_chars != null ? trace.hard_chars + ' characters' : 'unavailable'],
      ['Outcome', trace.status || 'unavailable'],
      ['Recorded policy', trace.policy_hash || 'unavailable'],
      ['Why', trace.why || receipt.why || trace.exemption_reason || trace.skip_reason || receipt.skip_reason || ''],
      ['Exemption', trace.exemption_reason || (trace.protected === true || trace.protected_copy === true ? 'explicit exact reading is preserved' : trace.protected || trace.protected_copy || trace.exemption || receipt.exemption || 'none recorded')],
      ['Extra turns', trace.extra_before != null || trace.extra_after != null ? `${trace.extra_before ?? '?'} before / ${trace.extra_after ?? '?'} after (limit ${trace.max_extra_turns ?? '?'})` : null],
      ['Dropped tail', trace.dropped_chars != null ? trace.dropped_chars + ' characters' : 'unavailable'],
      ['Replay of', receipt.replay_of || trace.replay_of || '']
    ]));
    if (trace.dropped_text) out.append(block('The tail that was dropped', trace.dropped_text));
    const measured = assembly.stages || [];
    if (measured.length) out.append(el('h4', {text: 'Assembly stages' + (roundScope ? ' (whole round)' : '')}),
      para('Evidence: ' + (assembly.provenance || 'unknown') + '; scope: ' + (assembly.scope || 'unavailable') +
        (roundScope ? '. These totals cover all speakers. They do not establish this turn\'s draft length or its individual insertion amounts.' : '.'), 's3-muted'),
      el('table', 's3-table', el('thead', null, el('tr', null, ...['Stage', 'Spoken characters', 'Net change', 'Turn measurements'].map(label => el('th', {text: label})))),
        el('tbody', null, ...measured.map(row => el('tr', null,
          el('td', {text: row.stage || 'unavailable'}), el('td', {text: row.spoken_chars ?? 'unavailable'}),
          el('td', {text: row.added_chars ?? 'unavailable'}),
          el('td', {text: (row.turns || []).map((t, index) => `${index + 1}. ${t.speaker}: ${t.chars} chars`).join('; ') || 'unavailable'}))))));
    out.append(el('h4', {text: roundScope ? 'Source changes in the round' : 'Source changes before handoff'}));
    if (!sourceChanges.length) out.append(para('No source insertion ledger was captured. Insertion amounts and caps are unavailable; the original draft cannot be recovered from the final words.', 's3-muted'));
    for (const change of sourceChanges) {
      const scope = change.scope || (roundScope ? 'round' : 'turn');
      const source = typeof change.source === 'object' && change.source ? change.source : {};
      const certainty = change.provenance || (change.exact === true ? 'exact' : 'unknown');
      out.append(el('div', 's3-card', el('b', {text: (change.stage || change.door || change.kind || 'Source change') + ' - ' + certainty + ' (' + scope + ')'}),
        kv([['Source', source.file || (typeof change.source === 'string' ? change.source : '') || change.file || change.source_id || 'unavailable'],
          ['Before', change.before_chars ?? 'unavailable'], [scope === 'round' ? 'Net change in round' : 'Inserted', (scope === 'round' ? change.added_chars : change.inserted_chars) ?? 'unavailable'],
          ['After', change.after_chars ?? 'unavailable'], ['Cap', change.cap ?? change.cap_chars ?? 'unavailable'],
          ['Full source', change.source_chars ?? source.source_chars ?? 'unavailable'], ['Retained excerpt', change.retained_excerpt_chars ?? source.retained_excerpt_chars ?? change.excerpt_chars ?? 'unavailable']]),
        change.why ? para(change.why, 's3-muted') : null, block('Captured source change', change)));
    }
    const checkpoints = trace.checkpoints || [];
    if (checkpoints.length) out.append(el('h4', {text: 'Sentence boundary decisions'}), el('table', 's3-table',
      el('thead', null, el('tr', null, ...['Character offset', 'Outcome', 'Reason'].map(label => el('th', {text: label})))),
      el('tbody', null, ...checkpoints.map(point => {
        const ev = events.find(e => e.event_id === point.event_id);
        return el('tr', null, el('td', {text: point.offset}), el('td', null, ev ? showEvent(ev) : point.outcome || 'unavailable'),
          el('td', {text: point.why || (point.forced ? 'hard cap; forced handoff' : 'roulette')}));
      }))));
    for (const entry of trace.insertions || []) {
      out.append(el('details', null, el('summary', {text: `${entry.mode || 'Handoff'} to ${entry.speaker || entry.turn_id || 'another voice'} - ${entry.status || 'unavailable'}`}),
        ...((entry.attempts || []).map(attempt => el('div', null,
          para(`Writer attempt ${attempt.attempt ?? '?'}: ${attempt.chars ?? '?'} characters; ${attempt.kept_chars ?? '?'} kept${attempt.rejection ? ' - ' + attempt.rejection : ''}`, 's3-muted'),
          attempt.writing_receipt ? block('Writer receipt', attempt.writing_receipt) : null))),
        block('Insertion receipt', entry)));
    }
    if (trace.original_text != null) out.append(block('The recorded body before handoff', trace.original_text));
    if (trace.final_text != null) out.append(block('The recorded body after handoff', trace.final_text));
    if (trace.reanchor) out.append(block('Following turn rewritten to answer the handoff', trace.reanchor));
    if (trace.duplicate_repair) out.append(block('Duplicate repair on this turn', trace.duplicate_repair));
    out.append(block('Full recorded length receipt', trace));
  }
  out.append(el('h4', {text: 'Recorded handoff rolls'}));
  out.append(events.length ? el('div', 's3-fx-mini-list', ...events.map(showEvent))
    : para('No handoff roll is on this recording. No decision is inferred from the current policy.', 's3-muted'));
  return out;
}
function stageStory(st, ev, conv, turn) {
  const out = [];
  const d = st.draw;
  if (st.stage === 'dice' && ev.family === 'SPEAKERBOX') {
    const meta = ev.meta || {};
    const slider = Number(((conv.inputs || {}).speakerbox_rates || {})[meta.mark] || 0);
    const density = Number((((conv.settings || {}).controls) || {}).speakerbox_density ?? 0.5);
    out.push(para(`The ${meta.mark} dial on the DJ desk is ${pct(slider)}; the Speakerbox density control is ${num(density)}, which multiplies it by 4^(density - 0.5) = ${num(Math.pow(4, density - 0.5), 2)} - so the odds are ${pct(meta.rate)}.`));
    out.push(para(`A hit needs the d100 to land above ${st.threshold} (100 - ${Math.round((meta.rate || 0) * 100)}).`));
    if (d) out.push(para(`Rolled u = ${num(d.u, 6)}, so d100 = floor(u x 100) + 1 = ${d.dice}. ${d.dice} ${d.dice > st.threshold ? '>' : '<='} ${st.threshold}: ${st.selected === 'PASS' ? 'a hit' : 'a miss'}.`, 's3-dmath'));
    return out;
  }
  if (st.stage === 'dice' && ev.family === 'SFX') {
    const forced = /first exchange/.test(st.rule || '');
    out.push(para('The chance of a planned clip at this line was built up like this:'));
    out.push(el('ul', 's3-dlist', ...(st.why || []).map(w => el('li', {text: w}))));
    if (forced) out.push(para(`${st.rule}: this is the first exchange's third line, so a clip is planned whatever the dice say (u = ${num(d && d.u, 6)}).`, 's3-dmath'));
    else if (d) out.push(para(`Rolled u = ${num(d.u, 6)} (d100 ${d.dice}). A clip is planned when u < ${num(st.threshold, 3)}: ${st.selected === 'PLAY' ? 'play' : 'no clip'}.`, 's3-dmath'));
    return out;
  }
  if (st.stage === 'placement') {
    out.push(para(`Where it goes: u = ${num(d && d.u, 6)}; before the line when u < 0.50 - so ${String(st.selected || '').toLowerCase()} the line.`, 's3-dmath'));
    return out;
  }
  if (st.stage === 'intensity') {
    const perf = (turn && turn.performance) || {};
    const tension = ev.state_before ? Number(ev.state_before.tension) : NaN;
    const arousal = Number(perf.arousal);
    out.push(para('How strongly: intensity = 0.2 + 0.6 x u + 0.25 x (tension - 0.5) + 0.2 x (arousal - 0.5), kept between 0.1 and 1.'));
    if (d) {
      const got = Math.min(1, Math.max(0.1, 0.2 + 0.6 * d.u + 0.25 * (tension - 0.5) + 0.2 * (arousal - 0.5)));
      out.push(para(Math.abs(got - Number(st.selected)) < 0.002
        ? `= 0.2 + 0.6 x ${num(d.u, 4)} + 0.25 x (${num(tension)} - 0.5) + 0.2 x (${num(arousal)} - 0.5) = ${num(st.selected, 3)}.`
        : `u = ${num(d.u, 6)}, tension ${num(tension)} -> ${num(st.selected, 3)} (recorded).`, 's3-dmath'));
    }
    return out;
  }
  if (!st.candidates) { if (st.rule) out.push(para(st.rule, 's3-dmath')); return out; }
  // A weighted draw: the candidates, their effective weights, and where u landed.
  const total = st.candidates.reduce((a, c) => a + (c.weight || 0), 0);
  const named = (ev.family === 'TOPIC' && st.stage === 'item') || st.stage === 'topic' ? 'Which topic'
    : ({table: 'Which table', category: 'Which category', item: 'Which outcome', mode: 'Which way', dice: 'Whether', turn: 'Which turn', end: 'Prepend or append (both won)'}[st.stage] || st.stage);   /* [s3-sb-end] */
  if (!d) {
    out.push(para(`${named}: ${st.candidates.length === 1 ? 'only one was eligible, so nothing was drawn' : 'decided without a random number'} - ${st.selected}.`));
    return out;
  }
  const target = d.u * total;
  out.push(para(`${named}: rolled u = ${num(d.u, 6)} (d100 = floor(u x 100) + 1 = ${d.dice}). The eligible weights add up to ${num(total, 3)}; u x ${num(total, 3)} = ${num(target, 3)}, which lands in the marked slice.`, 's3-dmath'));
  let acc = 0;
  const rows = st.candidates.map(c => {
    const from = acc; acc += c.weight || 0;
    const hit = c.id === st.selected;
    return el('tr', {class: hit ? 'hit' : ''},
      el('td', null, el('b', {text: c.label || c.id}), c.text ? el('p', {text: c.text}) : null),
      el('td', {text: num(c.base, 2)}), el('td', {text: num(c.weight, 3)}), el('td', {text: pct(c.p)}),
      el('td', {text: `${num(from, 2)}-${num(acc, 2)}`}),
      el('td', {class: 'why', text: (c.why || []).join(' · ') || 'base weight only'}));
  });
  out.push(el('div', 's3-dtable-wrap', el('table', 's3-dtable',
    el('thead', null, el('tr', null, ...['candidate', 'base', 'weight', 'chance', 'slice', 'why the weight moved'].map(h => el('th', {text: h})))),
    el('tbody', null, ...rows))));
  if ((st.excluded || []).length) {
    out.push(el('details', null, el('summary', {text: `not eligible here (${st.excluded.length})`}),
      el('ul', 's3-dlist', ...st.excluded.map(x => el('li', {text: `${x.label || x.id}: ${x.why}`})))));
  }
  return out;
}

function decisionCard(conv, ev, turn, api) {
  const line = eventLine(ev, conv);
  const [what, blurb] = FAMILY_WHAT[ev.family] || [ev.family, ''];
  const sel = ev.selected || {};
  const meta = ev.meta || {};
  const card = el('div', {class: 's3-dcard', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`});
  const turns = conv.turns || [];
  const prev = turn ? turns[turn.index - 1] : null;
  card.append(el('div', 's3-dhead',
    el('span', {class: 's3-dfam', text: ev.family}), die(line.dice),
    el('div', null, el('b', {text: line.text}),
      el('div', {class: 's3-muted', text: turn ? `turn ${turn.index + 1} · ${turn.name || turn.speaker} · ${turn.step_label} · ${turn.phase}` : 'before the first turn'}))));
  card.append(sectionOf('What it is', el('p', null, el('b', {text: what + '. '}), blurb)));
  if (ev.kind === 'observation' || !Array.isArray(ev.stages)) {
    const plain = Object.entries(ev).filter(([k, val]) => !['kind', 'family', 'conversation_id', 'cursor', 'body'].includes(k) && (typeof val !== 'object' || val === null));
    card.append(sectionOf('What happened', kv(plain.map(([k, val]) => [k.replace(/_/g, ' '), val]))));
    if (ev.matcher && Object.keys(ev.matcher).length) card.append(sectionOf('How the station chose the clip', kv(Object.entries(ev.matcher))));
    card.append(el('details', null, el('summary', {text: 'the raw record'}), el('pre', {text: json(ev)})));
    return card;
  }
  // How it came to this value.
  const how = sectionOf('How it came to this');
  if ((ev.stages || []).length) {
    const rolled = esTwoStageReel(ev, conv);                /* [s3-es-reel] */
    const reels = docReels(conv, ev, turn, api);
    how.append(rolled, ...reels);
    setTimeout(() => playReels(rolled, reels, 900), 60);
  }
  if (line.dice != null) how.append(para(`The number on the chip, ${line.dice}, is the d100 of the draw that decided it.`, 's3-muted'));
  if (!(ev.stages || []).length) {
    how.append(para(meta.why || (sel.authority ? `Not drawn: ${sel.authority}.` : 'Not a draw: decided by a rule, not a random number.')));
    if (meta.act) how.append(para(`The response act "${meta.act}" is itself a speaker-box quote, so it asked for a passage without a dice of its own.`));
    const reels = docReels(conv, ev, turn, api);
    if (reels.length) { how.append(...reels); setTimeout(() => playReels(null, reels, 900), 60); }
  }
  for (const st of ev.stages || []) how.append(...stageStory(st, ev, conv, turn));
  if (meta.applies === false) how.append(para('It did not roll: ' + (meta.why || 'the dial does not apply to this round') + '.'));
  /* [s3-dice] "allow me to see the adjacent tables associated with them" */
  if (sel.table && api && typeof api.request === 'function') {
    how.append(el('div', 's3-row',
      btn('Open table ' + sel.table, () => openSystem3({request: api.request, tab: 'tables', table: sel.table}),
        {title: 'the Tables tab, on this table'}),
      el('span', {class: 's3-muted', text: 'the table this roll drew from - its categories and weights as they stand now, beside the other tables of its family'})));
  }
  card.append(how);
  // What it read.
  const before = ev.state_before || {};
  const controls = ((conv.settings || {}).controls) || {};
  const read = sectionOf('What it read');
  read.append(para('The conversation as it stood when this was decided:', 's3-muted'),
    kv([['phase', before.phase], ['tension', num(before.tension)], ['agreement', num(before.agreement)],
      ['energy', num(before.energy)], ['novelty', num(before.novelty)], ['closure pressure', num(before.closure_pressure)],
      ['topic worn', num(before.topic_exhaustion)], ['unresolved points', before.unresolved],
      ['speaker', before.speaker], ["speaker's emotion", before.speaker_emotion ? `${before.speaker_emotion} (${num(before.speaker_intensity)})` : null],
      ['initiator', before.initiator]]));
  if (prev && ['ES', 'RS', 'IRS', 'FL'].includes(ev.family)) {
    const acts = (prev.directions || []).map(x => x.text).join('; ');
    read.append(para(`The turn it answers - ${prev.name || prev.speaker}, turn ${prev.index + 1}${acts ? ' (' + acts + ')' : ''}:`, 's3-muted'),
      el('blockquote', {class: 's3-dquote', text: prev.text || '(its words were not written yet)'}));
  }
  const dials = (DIAL_FOR[ev.family] || []).filter(k => k in controls);
  if (dials.length) read.append(para('The operator controls it answered to (0.5 is neutral):', 's3-muted'), kv(dials.map(k => [k.replace(/_/g, ' '), num(controls[k])])));
  const avail = Object.entries(((conv.inputs || {}).availability) || {}).filter(([, on]) => on).map(([k]) => k);
  const draw = (ev.stages || []).map(s => s.draw).filter(Boolean).pop() || ev.rng;
  read.append(kv([['material on this road', avail.join(', ') || 'none'], ['seed', conv.seed], ['draw number', draw ? draw.n : 'no draw'],
    ['config', ev.config_hash || conv.config_hash], ['engine', ev.engine || conv.engine]]));
  card.append(read);
  // The passage, and the document draw behind it.
  const mats = (conv.material || []).filter(m => m.decided_by === ev.event_id);
  const sbRec = turn ? (turn.speakerbox || []).find(x => x.event_id === ev.event_id) : null;
  if (mats.length || (sbRec && (sbRec.material || sbRec.unmet))) {
    const sec = sectionOf('The passage it fetched');
    for (const m of mats) {
      const cands = Array.isArray(m.candidates) ? m.candidates : [];
      sec.append(para(m.draw, 's3-muted'),
        kv([['document', m.selected.file], ['passage', m.selected.passage && m.selected.passage.index ? `${m.selected.passage.index} of ${m.selected.passage.of}` : '?'],
          ['documents it chose from', cands.length || String((m.candidates && m.candidates.unavailable) || '')], ['fetched in', m.ms + ' ms']]));
      if (cands.length) {
        const top = [...cands].sort((a, b) => b.weight - a.weight).slice(0, 12);
        sec.append(el('details', null, el('summary', {text: `the ${cands.length} documents and their weights`}),
          el('ul', 's3-dlist', ...top.map(c => el('li', {text: `${c.id}: weight ${c.weight}${c.id === m.selected.file ? '  <- drawn' : ''}`})),
            cands.length > 12 ? el('li', {text: `... and ${cands.length - 12} more`}) : null)));
      }
    }
    if (sbRec && sbRec.material) sec.append(el('blockquote', {class: 's3-dquote', text: sbRec.material.text}));
    if (sbRec && sbRec.unmet) sec.append(para('Not fetched: ' + sbRec.unmet));
    card.append(sec);
  }
  // The station's own door, when this was a door roll (engine 1).
  const door = (conv.observations_air || []).find(o => o.family === 'SPEAKERBOX' && o.decided_by === ev.event_id);
  if (door) {
    card.append(sectionOf('What the station did with the roll', kv([['door', door.door], ['applies', door.applies],
      ['slider + lift', num((door.rate || 0) + (door.lift || 0))], ['roll', num(door.roll, 3)], ['hit', door.hit], ['document', door.file],
      ['turns dealt', door.turns], ['why', door.why]])));
  }
  // What it changed.
  const after = ev.state_after || {};
  const change = sectionOf('What it changed');
  const keys = ['tension', 'agreement', 'energy', 'novelty', 'closure_pressure', 'topic_exhaustion'];
  const moved = keys.filter(k => Math.abs((after[k] || 0) - (before[k] || 0)) > 0.0005);
  change.append(moved.length ? kv(moved.map(k => [k.replace('_', ' '), `${num(before[k])} -> ${num(after[k])}`])) : para('No change to the conversation state.', 's3-muted'));
  if (ev.family === 'ES' && turn && turn.performance) {
    const p = turn.performance;
    change.append(para('The voice it asked for (applied to the rendered take):', 's3-muted'),
      kv([['pace', num(p.pace)], ['energy', num(p.energy)], ['warmth', num(p.warmth)], ['pauses', p.pause_style],
        ...Object.entries(p.dims || {}).filter(([, x]) => x > 0).map(([k, x]) => [k, num(x)])]));
  }
  if (ev.family === 'SFX' && turn) {
    const air = (conv.observations_air || []).find(o => o.family === 'SFX' && turn.script_index != null && o.turn_index === turn.script_index);
    if (air) {
      const clip = (air.played || [])[0] || {};
      change.append(para('At air:', 's3-muted'), kv([['due by', air.due], ['clip', clip.clip || 'nothing'], ['matched on', clip.why],
        ['candidates', (air.matcher || {}).cands], ['eligible', (air.matcher || {}).eligible], ['score', (air.matcher || {}).score]]));
    } else if (turn.sfx && turn.sfx.play) {
      change.append(para(`Asked the matcher for a clip about: ${(turn.sfx.intent || []).join(', ') || 'the line itself'}. Not observed at air yet.`, 's3-muted'));
    }
  }
  if (turn && turn.text) change.append(para('The line it helped shape:', 's3-muted'), el('blockquote', {class: 's3-dquote', text: turn.text}));
  card.append(change);
  card.append(el('details', null, el('summary', {text: 'the raw record'}), el('pre', {text: json(ev)})));
  return card;
}

/* --- the document it drew, and the line the passage starts on -------------
 *
 * "After showing the roll of the speaker box, show another line of the
 *  sentences rolling through the document. Show the document that it comes
 *  up with, and then show the line scrolling in that document, scrolling
 *  like a roll to the result - when pertinent."
 *
 * Pertinent means a roll that fetched a passage: a material record
 * (conv.material, decided_by = this event). Two reels follow the roll.
 * The first is the station's own weighted document list landing on the
 * document it drew - speakbox_quote's rotation made that choice, not a
 * System 3 number, and the caption says so. The second is that document's
 * lines - the same non-empty lines _passage_position counted for "passage
 * 18/43" - rolling once through the document and then down to the line
 * the passage starts on, which opens out into the passage in place. */
const DOC_LINES = new Map();   // "file|mind" -> Promise<string[]>

/* Python's str.splitlines() + strip(), so a line number here is the one
   System 3 recorded. */
function docSplit(text) {
  return String(text || '').split(/\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/).map(x => x.trim()).filter(Boolean);
}

function docLines(ask, file, mind) {
  const key = file + '|' + (mind || '');
  if (!DOC_LINES.has(key)) {
    const got = (ask || defaultRequest())('/api/speakbox/' + encodeURIComponent(file) + '?lines=1' + (mind ? '&mind=' + encodeURIComponent(mind) : ''))
      .then(doc => Array.isArray(doc && doc.lines)
        ? {lines: doc.lines.map(x => String(x).trim()).filter(Boolean), source: doc.source || 'harvest'}
        : {lines: docSplit(doc && doc.text), source: 'file'});   // a station without ?lines=1
    got.catch(() => DOC_LINES.delete(key));
    DOC_LINES.set(key, got);
    while (DOC_LINES.size > 8) DOC_LINES.delete(DOC_LINES.keys().next().value);
  }
  return DOC_LINES.get(key);
}

/* The document as it stands on disk, in its own lines (paragraphs, for a
   transcript) - for a passage the station's current harvest no longer holds. */
function docText(ask, file, mind) {
  const key = file + '|' + (mind || '') + '|file';
  if (!DOC_LINES.has(key)) {
    const got = (ask || defaultRequest())('/api/speakbox/' + encodeURIComponent(file) + (mind ? '?mind=' + encodeURIComponent(mind) : ''))
      .then(doc => ({lines: docSplit(doc && doc.text), source: 'file'}));
    got.catch(() => DOC_LINES.delete(key));
    DOC_LINES.set(key, got);
    while (DOC_LINES.size > 8) DOC_LINES.delete(DOC_LINES.keys().next().value);
  }
  return DOC_LINES.get(key);
}

/* The material a roll fetched, when it fetched one. */
function materialOf(conv, ev, turn) {
  const m = (conv.material || []).find(x => x.decided_by === ev.event_id && x.selected && x.selected.file);
  if (!m) return null;
  const sb = turn ? (turn.speakerbox || []).find(x => x.event_id === ev.event_id) : null;
  const top = turn && turn.topic_material && turn.topic_material.file === m.selected.file ? turn.topic_material : null;
  return {m, rec: (sb && sb.material) || top || null};
}

const share = (w, total) => {
  if (!(total > 0) || w == null) return '?';
  const x = 100 * w / total;
  return (x >= 1 ? x.toFixed(1) : x >= 0.01 ? x.toFixed(2) : x.toPrecision(1)) + '%';
};

function docRoll(mat) {
  const {m} = mat;
  const file = m.selected.file;
  const known = Array.isArray(m.candidates);
  const all = known ? m.candidates.filter(c => c && c.id) : [];
  if (!all.some(c => c.id === file)) all.push({id: file, weight: null});
  // Up to 36 of the real documents in shelf order, the drawn one always among them.
  const at = all.findIndex(c => c.id === file);
  const step = Math.max(1, Math.ceil(all.length / 36));
  const reel = all.filter((c, i) => i === at || i % step === 0).map(c => ({id: c.id, label: c.id}));
  const d = drum(reel, file);
  const total = all.reduce((a, c) => a + (Number(c.weight) || 0), 0);
  const pick = all[at] || {};
  const cap = el('div', {class: 's3-rollcap', text: known
    ? `${file}: weight ${pick.weight == null ? '?' : pick.weight} of ${total} across ${all.length} documents (${share(pick.weight, total)}) - the station's rotation drew it (weighted, unrepeated, locks and cooldowns), not a System 3 number`
    : `${file} - the document list was not recorded: ${(m.candidates || {}).unavailable || 'unavailable'}`});
  cap.hidden = true;
  const wrap = el('div', 's3-rollgroup',
    el('div', {class: 's3-roll s3-docroll', style: `--fam:${FAM.SPEAKERBOX}`},
      el('b', {style: `color:${FAM.SPEAKERBOX};min-width:74px`, text: 'document'}), d), cap);
  wrap.roll = async (ms) => { await d.roll(known && all.length > 1 ? ms : 0); cap.hidden = false; };
  return wrap;
}

function lineRoll(mat, api) {
  const {m, rec} = mat;
  const file = m.selected.file;
  const mind = (rec && rec.mind) || '';
  const pos = m.selected.passage || null;
  const plines = ((rec && rec.lines) || []).map(x => String(x).trim()).filter(Boolean);
  const first = plines[0] || String((rec && rec.text) || '').trim();
  const read = () => (api && api.doc ? api.doc(file, mind) : docLines(null, file, mind));
  const readFile = () => (api && api.docText ? api.docText(file, mind) : docText(null, file, mind));
  read().catch(() => {});             // start reading now; the reel waits its turn
  const list = el('ol');
  const reel = el('div', {class: 's3-linereel', 'aria-label': 'the lines of ' + file}, list);
  const cap = el('div', {class: 's3-rollcap', text: 'reading ' + file + '...'});
  const wrap = el('div', 's3-rollgroup',
    el('div', {class: 's3-roll s3-lineroll', style: `--fam:${FAM.SPEAKERBOX}`},
      el('b', {style: `color:${FAM.SPEAKERBOX};min-width:74px`, text: 'line'}), reel), cap);
  const li = (lines, i, cls) => el('li', {class: cls || null},
    el('span', {class: 's3-ln', text: i >= 0 ? String(i + 1) : '-'}), el('span', {class: 's3-lt', text: i >= 0 ? lines[i] : ''}));
  const flat = x => String(x || '').replace(/\s+/g, ' ').trim();
  // Where a passage line sits among the lines the draw was cut from: the
  // exact line, else the test _passage_position has always made (its
  // first 40 characters inside one).
  const whereOf = (lines, text) => {
    const exact = lines.indexOf(text);
    if (exact >= 0) return exact;
    const probe = text.slice(0, 60).trim().slice(0, 40);
    return probe ? lines.findIndex(x => x.includes(probe)) : -1;
  };
  const locate = (lines) => {
    const next = plines.length > 1 ? whereOf(lines, plines[1]) : -1;
    const copies = [];
    lines.forEach((x, i) => { if (x === first) copies.push(i); });
    // A harvest can hold a line twice: the copy the passage went on from.
    let at = pos && pos.index && lines[pos.index - 1] === first ? pos.index - 1
      : copies.length ? (next >= 0 ? (copies.filter(i => i < next).pop() ?? copies[0]) : copies[0]) : whereOf(lines, first);
    if (at < 0) return null;
    return {lines, at, where: [at, ...plines.slice(1).map(x => whereOf(lines, x))]};
  };
  // In the document's own text a passage line can start mid-paragraph,
  // and the harvest re-cases and de-brackets what it keeps ("Charlie
  // [Music]" is kept as "charlie music"), so the line is found by its
  // words - any punctuation between them - the whole line first, then its
  // first eight and five words.
  const wordsOf = x => String(x || '').toLowerCase().match(/[\p{L}\p{N}']+/gu) || [];
  const esc = w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const spanOf = (text, words) => {
    const hit = new RegExp(words.map(esc).join("[^\\p{L}\\p{N}']+"), 'iu').exec(text);
    return hit ? {k: hit.index, end: hit.index + hit[0].length} : null;
  };
  const locateInFile = (lines) => {
    const words = wordsOf(first);
    for (const n of [words.length, 8, 5]) {
      if (n < 3 || n > words.length) continue;
      for (let i = 0; i < lines.length; i++) {
        const span = spanOf(lines[i], words.slice(0, n));
        if (span) return {lines, at: i, where: [i], span};
      }
    }
    return null;
  };
  let found = null, source = '';
  const settle = () => {
    const {lines, at, where, span} = found;
    const rows = at > 0 ? [li(lines, at - 1, 'ctx')] : [];
    where.forEach((i, j) => {
      const row = li(lines, i, 'hit');
      if (i < 0) row.lastChild.textContent = plines[j];
      if (span && i >= 0) {
        // The paragraph around the passage, the passage marked in it.
        const text = lines[i];
        const from = Math.max(0, span.k - 90);
        fill(row.lastChild, from > 0 ? '...' : '', text.slice(from, span.k), el('mark', {text: text.slice(span.k, span.end)}),
          text.slice(span.end, span.end + 140), span.end + 140 < text.length ? '...' : '');
      }
      rows.push(row);
    });
    fill(list, ...rows);
    list.style.transition = 'none'; list.style.transform = '';
    reel.classList.add('landed');
    const run = where.every((i, j) => i >= 0 && (j === 0 || i === where[j - 1] + 1));
    const of = {harvest: 'the lines the station harvested from it', sentences: 'its sentences', file: 'its paragraphs'}[source] || 'its lines';
    cap.textContent = `${source === 'file' ? 'paragraph' : 'line'} ${at + 1} of ${lines.length} in ${file} (${of})`
      + (where.length > 1 ? (run ? ` - the passage runs ${where.length} lines`
        : ` - the passage's ${where.length} lines were taken in the draw's own order, from lines ${where.map(i => (i >= 0 ? i + 1 : '?')).join(', ')}`) : '')
      + (source === 'file' ? ' - the station has read this document again since, and its current lines no longer hold the passage, so it is shown in the document itself' : '');
  };
  wrap.roll = async (ms) => {
    const within = (got) => Promise.race([got, sleep(8000).then(() => { throw Error('it did not come back in 8s'); })]);
    let doc;
    try {
      doc = await within(read());
      source = doc.source;
      found = locate(doc.lines);
      if (!found && doc.source !== 'file') {
        const whole = await within(readFile());
        found = locateInFile(whole.lines);
        if (found) source = 'file';
      }
    } catch (err) {
      reel.hidden = true;
      cap.textContent = `${file} could not be read: ${err.message}` + (pos && pos.index ? ` - the passage was recorded at line ${pos.index} of ${pos.of}` : '');
      return;
    }
    if (!found) {
      reel.hidden = true;
      cap.textContent = `the passage is not in ${file} as it stands now - neither among the ${doc.lines.length} lines the station holds for it nor in its text, so the document has been edited since it was drawn`;
      return;
    }
    if (reduced() || ms <= 0) { settle(); return; }
    // Once through the whole document, then from the top down to the line, in document order.
    const {lines, at} = found;
    const idx = [];
    const sweep = Math.min(20, lines.length);
    for (let j = 0; j < sweep; j++) idx.push(Math.floor(j * lines.length / sweep));
    const lead = Math.max(0, at - 3);
    const down = Math.min(14, lead);
    for (let j = 0; j < down; j++) idx.push(Math.floor(j * lead / down));
    for (let i = lead; i <= at; i++) idx.push(i);
    const target = idx.length - 1;
    for (const i of [at + 1, at + 2]) if (i < lines.length) idx.push(i);
    reel.classList.remove('landed');
    fill(list, ...idx.map((i, k) => li(lines, i, k === target ? 'hit' : null)));
    list.style.transition = 'none'; list.style.transform = 'translateY(22px)';
    await sleep(20);
    list.style.transition = `transform ${ms}ms cubic-bezier(.12,.72,.18,1)`;
    list.style.transform = `translateY(${-(target - 1) * 22}px)`;
    await sleep(ms + 250);
    settle();
  };
  return wrap;
}

/* The two reels for an event, hidden until their turn - [] when the event
   fetched nothing. */
function docReels(conv, ev, turn, api) {
  const mat = conv && ev ? materialOf(conv, ev, turn) : null;
  if (!mat) return [];
  const reels = [docRoll(mat), lineRoll(mat, api)];
  for (const r of reels) r.hidden = true;
  return reels;
}

/* The roll first, then each reel in turn. */
async function playReels(rolled, reels, ms) {
  const still = reduced();
  if (rolled) await rolled.roll(still ? 0 : ms);
  for (const r of reels) {
    r.hidden = false;
    try { await r.roll(still ? 0 : ms * 1.3); } catch (err) { /* its caption says what went wrong */ }
  }
}

function drumAnimated2(cands, selected) { const d = drum(cands, selected); setTimeout(() => d.roll(reduced() ? 0 : 1100), 80); return d; }

function movableModal(panel) {
  panel.setAttribute('data-pine-drag', '');
  const handle = el('div', {class: 's3-modal-drag', 'data-pine-drag-handle': '', text: 'Drag to move'});
  const close = panel.querySelector('.s3-modal-close');
  if (close && close.parentNode === panel) close.after(handle);
  else panel.prepend(handle);
  /* [closex:s3-modal] Every System 3 card and menu gets the corner X. It
     presses the card's own Close, or taps its own backdrop - the road
     PineDismiss's BACK already takes. A header Close steps aside for it;
     a menu's Close at the foot stays where the list ends. */
  if (window.pineCloseX) {
    const own = panel.querySelector('.s3-modal-close');
    window.pineCloseX(panel, () => {
      if (own) { own.click(); return; }
      const back = panel.closest('.s3-modal-back');
      if (back) back.click();
    });
    if (own && own.parentNode === panel) own.style.display = 'none';
  }
  return panel;
}

function openDecision(conv, ev, turn, api) {
  if (!conv || !ev) return null;
  const back = el('div', {class: 's3 s3-modal-back'});
  const before = document.activeElement;
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); if (before && before.focus) before.focus(); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const shut = btn('Close', close, {class: 's3-modal-close', 'aria-label': 'Close'});
  const panel = el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How this was decided'},
    shut, decisionCard(conv, ev, turn, api));
  back.append(movableModal(panel));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  /* A diagnostic surface: the broadcast ducks to the report level while it
     is open, and comes back when it leaves the page (PineDuck, 2026-09-14). */
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-decision-card', window.PineDuck.REPORT, back);
  shut.focus({preventScroll: true});
  return close;
}

/* --- how a segment was assembled ------------------------------------------
 *
 * "If I tap and hold on the segment name ... and if I tap on inspect it, I
 *  want to see a node graph of how this segment was put together and how
 *  the dialogue was generated for the amount of time that the segment was
 *  for, along with the additional information on how the segment was
 *  assembled." The station's own scheduled node graph opens beside this
 * (PineSegmentFlow); this is System 3's side of it: the chain from subject
 * to air, the time it was written for against the time it took, the plan,
 * the checker's verdict and the material. */
function assemblyCard(conv, air) {
  const inputs = conv.inputs || {};
  const val = conv.validation || {};
  const turns = conv.turns || [];
  const lines = conv.lines || [];
  const spoken = lines.filter(l => l.turn_id);
  const heard = spoken.filter(l => (air.get(l.line_id) || {}).heard).length;
  const gone = spoken.filter(l => (air.get(l.line_id) || {}).aired === 'withdrawn').length;
  const sfxPlanned = turns.filter(t => t.sfx && t.sfx.play).length;
  const sfxAired = (conv.observations_air || []).filter(o => o.family === 'SFX').length;
  const passages = turns.flatMap(t => (t.speakerbox || []).filter(sb => sb.material && sb.material.text));
  const est = turns.reduce((a, t) => a + (Number(t.estimated_seconds) || 0), 0);
  const fams = {};
  for (const ev of conv.decision_events || []) fams[ev.family] = (fams[ev.family] || 0) + 1;
  const node = (title, value, detail, cls) => el('div', {class: 's3-anode ' + (cls || '')},
    el('b', {text: title}), el('span', {text: value}), detail ? el('small', {text: detail}) : null);
  const chain = el('div', 's3-achain',
    node('Subject', (conv.subject || {}).authority === 'obligated' ? 'given' : 'drawn',
      String((conv.subject || {}).category || '') + (inputs.seed_file ? ' · ' + inputs.seed_file : '')),
    node('Running order', `${turns.length} turns`, Object.entries(fams).map(([k, n]) => `${n} ${k}`).join(' · ')),
    node('Writer', val.written != null ? `${val.written} lines written` : 'not written yet',
      val.verdict ? `${val.verdict} ${num(val.score)}` + ((val.echo || {}).loop ? ' · ECHO LOOP' : '') : '',
      val.verdict === 'non_compliant' ? 'bad' : ''),
    node('Script', `${spoken.length} spoken lines`, `${lines.length - spoken.length} board / drop rows`),
    node('Air', `${heard} heard`, gone ? `${gone} withdrawn` : '', gone ? 'bad' : ''),
    node(castName('sfx'), `${sfxAired} played`, `${sfxPlanned} scheduled`));   /* [cast-names] */
  const card = el('div', 's3-dcard s3-acard',
    el('div', 's3-dhead', el('span', {class: 's3-dfam', text: String(conv.identity.road_kind || '').toUpperCase()}),
      el('div', null, el('b', {text: String((conv.subject || {}).topic || '').replace(/\s+/g, ' ').slice(0, 160)}),
        el('div', {class: 's3-muted', text: `${conv.mode} · ${clock(Number(conv.created || 0))} · ${conv.engine || ''} · ` +
          (inputs.bank ? 'written ahead for the bank' : 'written live')}))),
    sectionOf('How it was put together', chain),
    sectionOf('The time it was written for',
      kv([['segment budget', inputs.target_seconds ? `${num(inputs.target_seconds, 0)} s` : 'none given'],
        ['seconds a turn runs here', inputs.turn_seconds ? `${num(inputs.turn_seconds, 1)} s` : '-'],
        ['turns asked for', inputs.turns], ['turns planned', turns.length],
        ['planned length', `${num(est, 0)} s`], ['words a turn', inputs.words_per_turn],
        ['turns written', val.written], ['lines heard', `${heard} of ${spoken.length}`]])),
    sectionOf('What the checker found', val.verdict ? kv([['verdict', `${val.verdict} ${num(val.score)}`],
      ['turns written / planned', `${val.written} / ${val.planned}`], ['seat order', pct(val.seat_order)],
      ['acts met', val.acts ? `${val.acts.met} met · ${val.acts.missed} missed · ${val.acts.unchecked} unchecked` : '-'],
      ['echo loop', (val.echo || {}).loop ? `yes - turns ${(val.echo.turns || []).map(i => i + 1).join(', ')}` : 'no'],
      ['rewrite asked for', val.repair_wanted ? 'yes' : 'no']]) : para('Not written yet.', 's3-muted')),
    passages.length ? sectionOf('Speaker-box material', el('ul', 's3-dlist',
      ...passages.map(sb => el('li', {text: `${String(sb.mode).toLowerCase()}: ${sb.material.file}`})))) : null,
    conv.plan && conv.plan.sheet ? el('details', null, el('summary', {text: 'the running order the writer was given'}),
      el('pre', {text: conv.plan.sheet})) : null);
  return card;
}

function openAssembly(conv, air) {
  const back = el('div', {class: 's3 s3-modal-back'});
  const before = document.activeElement;
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); if (before && before.focus) before.focus(); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const shut = btn('Close', close, {class: 's3-modal-close', 'aria-label': 'Close'});
  back.append(movableModal(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How this segment was assembled'},
    shut, assemblyCard(conv, air || new Map()))));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-assembly', window.PineDuck.REPORT, back);
  shut.focus({preventScroll: true});
}

/* --- a line, opened into its parts ----------------------------------------
 *
 * "If I tap on a line that has been expanded by speaker box, then I want to
 *  see that line expanded with the speaker box lines above and below
 *  showing how they've been integrated with the source sentence in the
 *  setup."
 *
 * Opened, a bubble becomes: the passage read BEFORE the line (and the
 * round's seed, or the opening monologue), the line as written with every
 * word it took from a passage marked, the passage read AFTER it - each
 * passage laid out as its document's own lines with the words that reached
 * the air lit - and under them the setup: the running-order row the writer
 * was given. A match is a run of three or more words in the same order; a
 * single common word is not evidence.
 *
 * A line that is not the writer's at all - one piece of a passage the old
 * engine-1 doors dealt across the seats - says so, and shows the pieces
 * above and below it, seat by seat, in the order they were dealt. */
const MARK_OF = {PREPEND: 'pre', APPEND: 'app', FULL_SWATH: 'full', REFERENCE: 'ref', CALLBACK_TO_PRIOR: 'cb', SEED: 'seed'};
const SB_WORD = {PREPEND: 'read before the line, word for word', APPEND: 'read after the line, word for word',
  FULL_SWATH: 'the opening monologue, word for word', REFERENCE: 'worked in, in their own words',
  CALLBACK_TO_PRIOR: 'a callback to a passage read earlier', SEED: "the round's seed passage, read at the top"};

function tokens(text) {
  const out = [];
  const re = /\S+/g;
  let m;
  while ((m = re.exec(String(text || '')))) {
    const w = m[0].toLowerCase().replace(/[‘’]/g, "'").replace(/[^a-z0-9']/g, '').replace(/^'+|'+$/g, '');
    out.push({raw: m[0], w, tag: '', hit: false});
  }
  return out;
}

/* Tag the line's words that came from a passage (runs of three or more
   words in the passage's order) and light the passage words they used.
   Returns how many line words it tagged. */
function alignRuns(lineToks, passToks, tag) {
  const at = new Map();
  passToks.forEach((x, i) => { if (x.w) { if (!at.has(x.w)) at.set(x.w, []); at.get(x.w).push(i); } });
  let used = 0;
  let i = 0;
  while (i < lineToks.length) {
    let best = 0, from = -1;
    if (lineToks[i].w) {
      for (const j of at.get(lineToks[i].w) || []) {
        let k = 0;
        while (i + k < lineToks.length && j + k < passToks.length && lineToks[i + k].w && lineToks[i + k].w === passToks[j + k].w) k += 1;
        if (k > best) { best = k; from = j; }
      }
    }
    if (best >= 3) {
      for (let k = 0; k < best; k += 1) {
        if (!lineToks[i + k].tag) { lineToks[i + k].tag = tag; used += 1; }
        passToks[from + k].hit = true;
      }
      i += best;
    } else {
      i += 1;
    }
  }
  return used;
}

function scriptIndexOf(conv, t) {
  if (t.script_index != null) return t.script_index;
  const b = (conv.shadow_bindings || []).find(x => x.turn_id === t.turn_id);
  return b && b.script_index != null ? b.script_index : null;
}
function lineText(conv, t) {
  if (t.text) return t.text;
  const i = scriptIndexOf(conv, t);
  const a = i != null && Array.isArray(conv.actual) ? conv.actual[i] : null;
  return a ? String(a.text || '') : '';
}
function setupRow(conv, t) {
  const sheet = String((conv.plan && conv.plan.sheet) || '');
  const m = sheet.match(new RegExp('^\\s*' + (t.index + 1) + '\\s+' + t.speaker + '\\s+[-\\u2013\\u2014]\\s*(.+)$', 'm'));
  return m ? m[1] : '';
}
const opensOnSeed = (conv, t) => t.index === 0 && /opens with the passage above/i.test(setupRow(conv, t));

/* Engine 1's doors spliced whole passages in AFTER the writing: prepend,
   then full, at the head; append at the tail. The last outcome recorded
   for each door is the one that shaped the words on show. */
function dealtBy(conv, idx) {
  if (idx == null) return null;
  const doors = (conv.observations_air || []).filter(o => o.family === 'SPEAKERBOX' && o.stage === 'door-outcome');
  const last = d => { const o = [...doors].reverse().find(x => x.door === d); return o && o.hit && Number(o.turns) > 0 ? o : null; };
  let from = 0;
  for (const d of [last('prepend'), last('full')]) {
    if (!d) continue;
    const n = Number(d.turns);
    if (idx >= from && idx < from + n) return {door: d.door, file: d.file, from, of: n, piece: idx - from + 1};
    from += n;
  }
  const app = last('append');
  const written = Number((conv.validation || {}).written || (Array.isArray(conv.actual) ? conv.actual.length : 0));
  if (app && written) {
    const n = Number(app.turns), start = written - n;
    if (idx >= start && idx < written) return {door: 'append', file: app.file, from: start, of: n, piece: idx - start + 1};
  }
  return null;
}
function piecesOf(conv, dealt) {
  const out = [];
  for (let k = 0; k < dealt.of; k += 1) {
    const i = dealt.from + k;
    const t = (conv.turns || []).find(x => scriptIndexOf(conv, x) === i);
    const a = !t && Array.isArray(conv.actual) ? conv.actual[i] : null;
    out.push({piece: k + 1, i, seat: t ? t.speaker : a ? a.speaker : '?', name: t ? (t.name || t.speaker) : a ? a.speaker : '',
      text: t ? lineText(conv, t) : a ? String(a.text || '') : '', turn: t || null});
  }
  return out;
}
/* A turn opens when a passage went into it, or when a speaker-box roll on it
   could have put one there and did not - its odds are then the thing to see
   and to turn. A mark on a road that carries its own material cannot win at
   any setting, so it does not invite a tap. */
const sbWon = t => (t.speakerbox || []).some(sb => sb.mode && sb.mode !== 'NONE');
const sbTried = t => (t.speakerbox || []).some(sb => sb.mark && sb.applies !== false);
function canCompose(conv, t) {
  if (!conv) return false;
  if (sbWon(t) || sbTried(t)) return true;
  return !!dealtBy(conv, scriptIndexOf(conv, t)) || opensOnSeed(conv, t);
}

/* --- the odds of a speaker-box roll, and the dials behind them -------------
 *
 * "If an item fails to win the ability to bring in the speaker box text,
 *  allow me to expand it still and see the sliders and parameters for how
 *  we got the ratio to be at that value so I'm able to adjust it."
 *
 * Every roll on the turn, won or lost: what the d100 needed and why - the
 * DJ desk's dial for that mark times the Speakerbox density control,
 * 4^(density - 0.5) - read from the round's own record. Under it the same
 * dials as the station holds them NOW, as sliders: moving one re-works each
 * roll's odds on the spot and says whether this line's roll would win at
 * that setting; Save turns the station's own dials (POST /api/dj/dial,
 * POST /api/system3/settings, the speakerbox config section), so the next
 * round is rolled at the new odds. A past roll is never re-rolled. */
const MARK_NAME = {prepend: 'Prepend - read before the line', append: 'Append - read after the line',
  full: 'Full swath - the opening monologue', act: 'Asked for by its response act'};
const DIAL_KEY = {prepend: 'speakbox_prepend_rate', append: 'speakbox_append_rate', full: 'speakbox_full_swath_rate'};
const oddsOf = (dial, density) => Math.max(0, Math.min(1, Number(dial || 0) * Math.pow(4, Number(density) - 0.5)));
const needOf = rate => Math.round(100 - rate * 100);

function rollVerdict(sb) {
  if (sb.mark === 'act') return {cls: 'won', text: 'no dice: the response act was itself a speaker-box quote'};
  if (sb.applies === false) return {cls: 'off', text: 'not rolled: ' + (sb.why || 'the dial does not apply to this round')};
  if (sb.dice == null) return {cls: 'lost', text: 'not rolled: ' + (sb.why || 'the dial is at 0%')};
  const hit = sb.dice > sb.threshold;
  if (hit && (!sb.mode || sb.mode === 'NONE')) return {cls: 'lost', text: `rolled ${sb.dice}, needed over ${sb.threshold} - won, but ${String(sb.why || 'no passage came of it').replace(/^a hit, but /, '')}`};
  if (hit) return {cls: 'won', text: `rolled ${sb.dice}, needed over ${sb.threshold} - won: ${String(sb.mode).toLowerCase().replace(/_/g, ' ')}` + (sb.unmet ? ` (the passage was not fetched: ${sb.unmet})` : '')};
  return {cls: 'lost', text: `rolled ${sb.dice}, needed over ${sb.threshold} - lost`};
}

function oddsPanel(conv, t, api) {
  const marks = (t.speakerbox || []).filter(sb => sb.mark && sb.applies !== false);
  if (!marks.length) return null;
  const recDials = ((conv.inputs || {}).speakerbox_rates) || {};
  const recDensity = Number((((conv.settings || {}).controls) || {}).speakerbox_density ?? 0.5);
  const box = el('div', {class: 's3-odds', 'data-keep': ''});
  box.append(el('div', 's3-sb-head', el('b', {text: 'Speaker-box odds on this line'}),
    el('span', {text: 'what each roll needed, and the dials that set it'})));
  const now = {};                       /* mark -> the "at these dials" line */
  for (const sb of marks) {
    const verdict = rollVerdict(sb);
    const dial = recDials[sb.mark];
    const math = sb.mark === 'act' ? '' : `the ${sb.mark} dial was ${pct(dial)}, x ${num(Math.pow(4, recDensity - 0.5), 2)} for density ${num(recDensity)}` +
      ` = ${pct(sb.rate)} odds, so the d100 had to land over ${sb.threshold != null ? sb.threshold : needOf(Number(sb.rate || 0))}`;
    now[sb.mark] = el('div', 's3-odds-now');
    box.append(el('div', {class: 's3-odds-row ' + verdict.cls},
      el('div', 's3-odds-mark', el('b', {text: MARK_NAME[sb.mark] || sb.mark}), die(sb.dice != null ? sb.dice : null)),
      el('div', {text: verdict.text}), math ? el('div', 's3-muted', math) : null, now[sb.mark]));
  }
  const ctl = el('div', 's3-odds-ctl', para('Reading the station\'s dials as they are now...', 's3-muted'));
  box.append(ctl);
  const rework = (vals) => {
    for (const sb of marks) {
      if (!now[sb.mark] || sb.mark === 'act') continue;
      const rate = oddsOf(vals[DIAL_KEY[sb.mark]], vals.density);
      const need = needOf(rate);
      const full = /already carries (\d+)/.exec(String(sb.why || ''));
      if (full && sb.dice != null && sb.dice > sb.threshold) {
        const room = Number(vals.max_inline) > Number(full[1]);
        fill(now[sb.mark], room ? `At ${vals.max_inline} passages per round this roll would have come in.`
          : `This roll already won; the round held ${full[1]} passages, the limit - raise Passages per round below to let it in.`);
        now[sb.mark].className = 's3-odds-now ' + (room ? 'won' : '');
        continue;
      }
      const would = sb.dice != null ? (sb.dice > need ? 'this roll would WIN' : 'this roll would still lose') : 'a roll at these odds';
      fill(now[sb.mark], `At the dials below: ${pct(rate)} odds, a d100 over ${need} wins - ${sb.dice != null ? `rolled ${sb.dice}: ` : ''}${would}.`);
      now[sb.mark].className = 's3-odds-now ' + (sb.dice != null && sb.dice > need ? 'won' : '');
    }
  };
  api.dials().then(live => {
    const vals = {...live};
    const slider = (label, key, max, step, fmt, help) => {
      const out = el('b', {text: fmt(vals[key])});
      const input = el('input', {type: 'range', min: 0, max, step, value: vals[key], 'aria-label': label,
        oninput: e => { vals[key] = +e.target.value; out.textContent = fmt(vals[key]); rework(vals); status.textContent = ''; }});
      return el('label', 's3-odds-slider', el('span', {text: label}), input, out, help ? el('small', {text: help}) : null);
    };
    const status = el('span', 's3-muted');
    const budget = el('input', {type: 'number', min: 0, max: 8, step: 1, value: vals.max_inline, 'aria-label': 'passages per round',
      oninput: e => { vals.max_inline = Math.max(0, Math.min(8, Math.round(+e.target.value || 0))); rework(vals); status.textContent = ''; }});
    const save = btn('Save to the station', async () => {
      save.disabled = true; status.textContent = 'saving...';
      try {
        const done = await api.saveDials(live, vals);
        Object.assign(live, vals);
        status.textContent = done.length ? `saved ${done.join(', ')} - the next round rolls at these odds` : 'nothing changed';
      } catch (err) { status.textContent = 'not saved: ' + err.message; }
      save.disabled = false;
    }, {class: 's3-odds-save'});
    const reset = btn('Put them back', () => { Object.assign(vals, live); paint(); rework(vals); status.textContent = ''; });
    let open = false;                   /* folded until tapped; a repaint keeps it as it was */
    const paint = () => {
      const fold = el('details', {class: 's3-odds-fold', open},
      el('summary', {class: 's3-odds-title', text: 'The dials, as the station holds them now'}), el('div', 's3-odds-body',
      slider('Prepend dial (DJ desk)', DIAL_KEY.prepend, 1, 0.01, pct),
      slider('Append dial (DJ desk)', DIAL_KEY.append, 1, 0.01, pct),
      slider('Full-swath dial (DJ desk)', DIAL_KEY.full, 1, 0.01, pct, 'the opening monologue on turn 1'),
      slider('Speakerbox density (System 3)', 'density', 1, 0.05, x => `${num(x)} (x${num(Math.pow(4, Number(x) - 0.5), 2)})`,
        'multiplies every dial: 0.5 leaves them as they are, 1.0 doubles them'),
      el('label', 's3-odds-slider', el('span', {text: 'Passages per round (System 3)'}), budget,
        el('small', {text: 'a winning roll places nothing once the round holds this many'})),
      el('div', 's3-row', save, reset, status)));
      fold.addEventListener('toggle', () => { open = fold.open; });
      fill(ctl, fold);
    };
    paint();
    rework(vals);
  }).catch(err => fill(ctl, para('The station\'s dials could not be read: ' + err.message, 's3-muted')));
  return box;
}

/* The passage as its document's own lines, each word lit if it reached the line. */
function sourceLines(passToks, lines) {
  const counts = (Array.isArray(lines) ? lines : []).map(l => tokens(l).length);
  const rows = [];
  if (counts.length && counts.reduce((a, b) => a + b, 0) === passToks.length) {
    let at = 0;
    for (const n of counts) { rows.push(passToks.slice(at, at + n)); at += n; }
  } else {
    rows.push(passToks);
  }
  return el('div', 's3-src', ...rows.map(r => runs(el('div', 's3-src-line'), r, x => x.hit ? 'hit' : 'miss', 'span')));
}

/* Words into a node, one element per run of words that share a class, so
   a passage read out reads as one highlighted stretch, not word boxes. */
function runs(node, toks, classOf, tag) {
  let run = null;
  toks.forEach((x, i) => {
    const sep = i ? ' ' : '';
    const cls = classOf(x);
    if (run && run.cls === cls) { run.node.append(sep + x.raw); return; }
    if (sep) node.append(sep);
    if (cls) { run = {cls, node: el(tag, {class: cls, text: x.raw})}; node.append(run.node); }
    else { run = {cls, node}; node.append(x.raw); }
  });
  return node;
}

function passageBlock(conv, p) {
  const sb = p.sb || {};
  const mat = sb.material || {};
  const m = sb.request_id ? (conv.material || []).find(x => x.request_id === sb.request_id) || {} : {};
  const pos = m.selected && m.selected.passage && m.selected.passage.index ? `passage ${m.selected.passage.index} of ${m.selected.passage.of}` : '';
  const roll = sb.dice != null ? `rolled ${sb.dice}, needed over ${sb.threshold} (${pct(sb.rate)})` : sb.mark === 'act' ? 'asked for by its response act' : '';
  const file = p.seed ? p.file : mat.file;
  const text = p.seed ? p.text : mat.text;
  let foot = null;
  if (text) {
    const words = p.toks.filter(x => x.w).length;
    const lit = p.toks.filter(x => x.w && x.hit).length;
    const share = lit / Math.max(1, words);
    foot = p.mode === 'REFERENCE' || p.mode === 'CALLBACK_TO_PRIOR'
      ? `${pct(share)} of its words reached the line in runs of three or more. A reference is meant to be put in their own words, so a low figure is not a fault.`
      : p.used ? `${pct(share)} of it reached the line word for word: ${p.used} of the line's words${p.where ? ', ' + p.where : ''}.`
        : 'None of it reached the line: no run of three or more of its words appears in what was written.';
  }
  return el('div', {class: 's3-sb s3-sb-' + (MARK_OF[p.mode] || 'ref')},
    el('div', 's3-sb-head', el('b', {text: 'Speaker-box · ' + (SB_WORD[p.mode] || p.mode)}),
      el('span', {text: [file, pos, roll].filter(Boolean).join(' · ')})),
    text ? sourceLines(p.toks, p.seed ? null : mat.lines)
      : para(p.seed ? `The seed passage from ${file || 'the speakerbox'} is not kept on this round's record; rounds planned after this change keep it.`
        : 'The passage was not fetched (' + (sb.unmet || 'nothing came back') + '), so the writer was never given it.', 's3-muted'),
    foot ? el('div', 's3-sb-foot', foot) : null);
}

function wordSpan(toks, tag) {
  const at = toks.map((x, i) => x.tag === tag ? i : -1).filter(i => i >= 0);
  if (!at.length) return '';
  const a = at[0] + 1, b = at[at.length - 1] + 1;
  return a === b ? `word ${a} of ${toks.length}` : `words ${a}-${b} of ${toks.length}`;
}

function composeLine(conv, t, api) {
  /* A tap anywhere on it closes it again (the bubble's own handler); only
     its sliders, buttons and inputs keep it open. */
  const box = el('div', 's3-compose');
  setTimeout(() => {
    if (box.isConnected && window.PineDuck && typeof window.PineDuck.hold === 'function') {
      window.PineDuck.hold('s3-line-' + t.turn_id, window.PineDuck.REPORT, box);
    }
  }, 0);
  const idx = scriptIndexOf(conv, t);
  const text = lineText(conv, t);
  const toks = tokens(text);
  const row = setupRow(conv, t);
  const dealt = dealtBy(conv, idx);
  const parts = (t.speakerbox || []).filter(sb => sb.mode && sb.mode !== 'NONE')
    .map(sb => ({sb, mode: sb.mode, toks: tokens((sb.material || {}).text || '')}));
  if (opensOnSeed(conv, t)) {
    const inp = conv.inputs || {};
    parts.unshift({mode: 'SEED', seed: true, file: inp.seed_file || ((conv.subject || {}).sources || [])[0] || '',
      text: String(inp.seed_text || ''), toks: tokens(inp.seed_text || '')});
  }
  for (const p of parts) {
    const tag = MARK_OF[p.mode] || 'ref';
    p.used = p.toks.length ? alignRuns(toks, p.toks, tag) : 0;
    p.where = wordSpan(toks, tag);
  }
  const checks = ((((conv.validation || {}).turns) || []).find(r => r.turn_id === t.turn_id) || {}).checks || [];
  const sbChecks = checks.filter(c => /^speakerbox /.test(c.what || ''));
  const verdict = sbChecks.length ? el('div', 's3-muted s3-sbcheck', 'The validator: ' +
    sbChecks.map(c => `${c.what} ${c.result}${c.how ? ' (' + c.how + ')' : ''}`).join(' · ')) : null;
  const setup = el('div', 's3-setup', el('b', {text: `The setup - row ${t.index + 1} of the running order the writer was given`}),
    el('div', {text: row || 'The running order was not kept for this round.'}));

  if (dealt) {
    const pieces = piecesOf(conv, dealt);
    box.append(el('div', 's3-sb s3-sb-dealt',
      el('div', 's3-sb-head', el('b', {text: 'Not written for this turn'}),
        el('span', {text: `the old ${dealt.door} door · ${dealt.file || 'a speakerbox document'} · piece ${dealt.piece} of ${dealt.of}`})),
      para(`This line is piece ${dealt.piece} of ${dealt.of} of one passage from ${dealt.file || 'the speakerbox'}, which the engine-1 ${dealt.door} door dealt across the seats after the writer had finished. Nothing in it answers the line before - it is one document split between voices. Engine 2 stands those doors down: a passage is read by one speaker inside the running order, and the next speaker answers it.`),
      el('ol', 's3-pieces', ...pieces.map(x => el('li', {class: 'seat-' + x.seat + (x.i === idx ? ' this' : '')},
        el('span', 's3-piece-who', `${x.piece} · ${x.name || x.seat}` + (x.i === idx ? ' · this line' : '')),
        el('span', {text: x.text || '(this piece is not bound to a planned turn)'}))))));
    const planned = parts.filter(p => !p.seed);
    if (planned.length) {
      box.append(para('What System 3 had placed on this turn - never heard, because the dealt passage took its place:', 's3-muted s3-join'));
      for (const p of planned) box.append(passageBlock(conv, p));
    }
    put(box, oddsPanel(conv, t, api), verdict, setup);
    return box;
  }

  const above = parts.filter(p => p.mode === 'SEED' || p.mode === 'FULL_SWATH' || p.mode === 'PREPEND');
  const below = parts.filter(p => p.mode === 'APPEND');
  const inside = parts.filter(p => !above.includes(p) && !below.includes(p));
  for (const p of above) box.append(passageBlock(conv, p), el('div', 's3-join', p.mode === 'PREPEND' ? 'then, in the same breath, the line' : 'then the line'));
  const said = el('div', {class: 's3-said seat-' + t.speaker});
  if (toks.length) {
    runs(said, toks, x => x.tag ? 's3-mk-' + x.tag : '', 'mark');
  } else {
    said.append(el('i', {text: t.status === 'dropped' ? '(dropped: the writer wrote fewer turns than planned)' : '(no words were written for this turn yet)'}));
  }
  const own = toks.filter(x => !x.tag).length;
  const bits = parts.filter(p => p.used).map(p => `${p.used} from the ${p.mode === 'SEED' ? 'seed' : p.mode.toLowerCase().replace(/_/g, ' ')} passage`);
  box.append(el('div', 's3-said-wrap',
    el('div', 's3-said-head', 'The line as written' + (parts.length ? ' - words taken from a passage are marked'
      : ' - no speaker-box passage was placed on this turn')),
    said,
    toks.length ? el('div', {class: 's3-strip', 'aria-hidden': 'true'}, ...toks.map(x => el('i', {class: x.tag ? 's3-mk-' + x.tag : null, style: `flex-grow:${x.raw.length + 1}`}))) : null,
    toks.length ? el('div', 's3-muted', `Of the ${toks.length} words: ${[...bits, `${own} their own`].join(', ')}.`) : null));
  for (const p of below) box.append(el('div', 's3-join', 'then, in the same breath, the passage'), passageBlock(conv, p));
  for (const p of inside) box.append(el('div', 's3-join', 'worked into the line'), passageBlock(conv, p));
  put(box, oddsPanel(conv, t, api), verdict, setup);
  return box;
}

/* --- the systems that cut lines, and their switches ---------------------------
 *
 * "Whenever I look at why entries are being cut, I want to be able to see
 *  why they're being cut and to toggle that reason and to be able to toggle
 *  off the system that's cutting those lines. We shouldn't be cutting any
 *  lines." Each road is a standing policy in the orchestrator's own book,
 * turned through its own door (POST /api/orchestrator/policy {does}) and
 * read from GET /api/orchestrator/logic. Unset means on. */
const CUT_ROADS = [
  {key: 'talk_cut', verb: 'cut', name: 'Cutting a round mid-flight',
    what: 'a round stopped at a turn boundary when something urgent took the floor, or at the turn cap ("round cut mid-flight"). A cut you ask for yourself - Next, Previous, a mixtape, the dice, the break-in button - still lands.'},
  {key: 'overrun_withdraw', verb: 'withdraw', name: 'Withdrawing a round that does not fit its entry',
    what: 'a finished round refused at hand-over because it runs past the time its entry has left ("the banter round runs 146s and its entry has 100s left"), because its entry has ended, or because the sheet has moved on to another road\'s entry. Off, it airs and the sheet waits for it.'},
  {key: 'record_bound', verb: 'bound', name: 'Withdrawing a line about a record that has moved on',
    what: 'an introduction or send-off withdrawn - or cut while it waits - when its record is no longer where the line says it is (#1237).'},
  {key: 'floor_yield', verb: 'floor', on: 'yield', off: 'hold', name: 'Giving the floor to a due entry',
    what: 'a round asked to end at its next turn when the entry that is due has something ready (#1192). With mid-flight cutting off, this asks and nothing is cut.'},
  {key: 'manager_breaks_in', verb: 'breakin', name: 'The manager breaking in',
    what: 'a memo from upstairs asking for the floor (#1261). With mid-flight cutting off, it waits for the round to finish.'},
];
const CUT_ROAD = Object.fromEntries(CUT_ROADS.map(r => [r.key, r]));

/* Which road a recorded reason came from. */
function cutRoadOf(why) {
  const w = String(why || '');
  if (/bound to |#1237|its record |the record moved on/.test(w)) return 'record_bound';
  if (/mid-flight/.test(w)) return 'talk_cut';
  if (/entry has \d+s left|entry on the sheet has already ended|the sheet is on the |would not put it out|so it overruns by/.test(w)) return 'overrun_withdraw';
  if (/process restarted/.test(w)) return 'restart';
  return '';
}

/* Reasons with no switch, said plainly instead of "no switch yet". */
const CUT_PLAIN = {
  restart: 'Nothing chose this: the station restarted while the round waited for its air, and the player holding it ended with the process. A restart is not a policy, so there is no switch for it.',
};

/* The note under a line that was never heard: why, and the switch for the
   system that did it (when it has one). */
function cutNote(why, v) {
  const road = CUT_ROAD[cutRoadOf(why)];
  const state = el('span', {class: 's3-muted'});
  const toggle = road ? el('button', {type: 'button', class: 's3-cut-toggle', 'data-keep': '', text: '...'}) : null;
  const paint = (on) => {
    if (!toggle) return;
    toggle.textContent = on ? 'turn this system off' : 'this system is off - turn it back on';
    toggle.classList.toggle('off', !on);
    state.textContent = on ? road.name + ' is ON' : road.name + ' is OFF - lines like this now air';
  };
  if (toggle) {
    v.api.policy().then(p => paint(p[road.key] !== false)).catch(() => { state.textContent = road.name; });
    toggle.addEventListener('click', async e => {
      e.stopPropagation();
      toggle.disabled = true;
      try {
        const p = await v.api.policy();
        const next = !(p[road.key] !== false);
        await v.api.setPolicy(road, next);
        paint(next);
      } catch (err) { state.textContent = 'not changed: ' + err.message; }
      toggle.disabled = false;
    });
  }
  return el('div', {class: 's3-cutnote', 'data-keep': ''},
    el('b', {text: 'Never heard'}), el('span', {text: why}),
    road ? el('div', 's3-row', state, toggle)
      : el('div', {class: 's3-muted', text: CUT_PLAIN[cutRoadOf(why)] || 'No switch exists for this system yet.'}));
}

/* All of them at once, from the bar. */
async function openCutPanel(v) {
  const back = el('div', {class: 's3 s3-modal-back'});
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const list = el('div', 's3-cutlist', para('Reading the switches...', 's3-muted'));
  back.append(movableModal(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'The systems that cut lines'},
    btn('Close', close, {class: 's3-modal-close'}),
    el('div', 's3-dcard',
      el('div', 's3-dhead', el('div', null, el('b', {text: 'The systems that cut lines'}),
        el('div', {class: 's3-muted', text: 'Each one is a switch in the station\'s policy book. A line one of them cut shows why on its message, with this same switch.'}))),
      list))));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-cut-panel', window.PineDuck.REPORT, back);
  const paint = async () => {
    let p = {};
    try { p = await v.api.policy(true); } catch (err) { fill(list, para('The switches could not be read: ' + err.message, 's3-muted')); return; }
    fill(list, ...CUT_ROADS.map(road => {
      const on = p[road.key] !== false;
      const b = el('button', {type: 'button', class: 's3-cut-toggle' + (on ? '' : ' off'), text: on ? 'ON - turn off' : 'OFF - turn on'});
      b.addEventListener('click', async () => {
        b.disabled = true;
        try { await v.api.setPolicy(road, !on); await paint(); } catch (err) { b.textContent = 'not changed: ' + err.message; b.disabled = false; }
      });
      return el('div', {class: 's3-cutrow' + (on ? '' : ' off')}, el('div', null, el('b', {text: road.name}), el('div', {class: 's3-muted', text: road.what})), b);
    }));
  };
  paint();
}

/* --- the live feed's pieces ------------------------------------------------ */
/* A tap on these never opens or closes the line they sit in. */
const KEEP_OPEN = 'button, a, summary, input, select, textarea, label, video, audio, canvas, [role=button], [data-keep]';

/* The dialogue typing itself over the direction it was written from. Driven
   by requestAnimationFrame - on the tablet a WebView's timers can stall
   while its frames keep coming. */
function typewriter(node,text,ms,{current=null,paused=null,onFrame=null}={}){
  const total=Math.max(500,Math.min(2600,ms||String(text).length*20));
  let last=performance.now(),elapsed=0;node.textContent='';node.classList.add('typing');
  return new Promise(resolve=>{
    const step=now=>{
      const dt=Math.max(0,now-last);last=now;
      if(paused?.()&&node.isConnected){requestAnimationFrame(step);return;}
      elapsed+=dt;const value=String(current?current():text),k=Math.min(1,elapsed/total);
      const n=window.PineSystem3MessageTile.typeCount(node.textContent.length,k,value.length);node.textContent=value.slice(0,n);onFrame?.();
      if((k<1||n<value.length)&&node.isConnected)requestAnimationFrame(step);
      else{node.textContent=value;node.classList.remove('typing');resolve();}
    };requestAnimationFrame(step);
  });
}
/* The SFX Guy: the page's own Carbon speaker-person when the set is loaded,
   a drawn speaker when it is not. */
function sfxAvatar() {
  const node = el('span', {class: 's3-avatar s3-avatar-sfx', 'aria-hidden': 'true'});
  const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:user--speaker') : '';
  if (svg) node.innerHTML = svg; else node.append(el('i'));
  return node;
}

/* A URL the station handed out, made absolute against where this module was
   loaded from - the station - so it plays from the desktop's file:// page as
   well as from the tablet's own origin. */
function stationUrl(u) { try { return new URL(u, import.meta.url).href; } catch (e) { return u; } }

/* SFX Guy scheduling a clip: the plan's own decision, as a line in the
   correspondence where it was placed (before or after the turn). */
function sfxPlanRow(conv, t, ev, aired, v) {
  const d = stage(ev, 'dice');
  const plan = t.sfx || {};
  const intent = (plan.intent || []).slice(0, 4).join(', ');
  return el('div', {class: 's3-sysrow s3-sfxplan' + (aired ? ' aired' : ''), 'data-event': ev.event_id, 'data-turn': t.turn_id,
      role: 'button', tabindex: '0', title: 'how ' + castName('sfx') + ' came to schedule this clip',   /* [cast-names] */
      onclick: e => { e.stopPropagation(); v.select(t.turn_id, ev.event_id, e.currentTarget); openDecision(conv, ev, t, v.api); },
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
    sfxAvatar(),
    el('span', 's3-sysrow-text', el('b', {text: castName('sfx')}),   /* [cast-names] */
      ` schedules a clip ${plan.placement === 'before' ? 'before' : 'after'} ${t.name || t.speaker}'s line` + (intent ? `, about ${intent}` : '')),
    die(d && d.draw ? d.draw.dice : null),
    el('span', {class: 's3-muted', text: aired ? 'played' : 'waiting for air'}));
}

/* What the station actually played for The SFX Guy on this line: his entry
   in the conversation - his quip, the clip itself, and why the matcher chose
   it. A tap on the entry brings up the station's menu for the clip. */
function sfxEntry(conv, t, obs, v) {
  const played = (obs.played || [])[0] || null;
  const quips = (obs.sfx_guy || []).map(q => q && q.text).filter(Boolean);
  const m = obs.matcher || {};
  const due = {system3: 'scheduled by System 3', both: 'the cadence and System 3', cadence: 'the two-line cadence'}[obs.due] || 'the cadence';
  const why = [played && played.why ? `matched on "${played.why}"` : '', m.cands != null ? `${m.cands} candidates, ${m.eligible} eligible` : '',
    played && played.seconds ? `${num(played.seconds, 1)} s` : ''].filter(Boolean).join(' · ');
  const who = el('div', 'who', sfxAvatar(), el('b', {text: castName('sfx')}), el('span', {text: `${due} · after turn ${t.index + 1}`}));   /* [cast-names] */
  /* [s3-imsg] coming together again (its play button, a tap): no die was rolled for the clip the
     station matched - its card holds, and then the clip plays */
  const key = v && v.obsKey ? v.obsKey('clip', obs, t, played) : '';
  if (v && v.replayAs && v.replayAs.get(key) === 'upcoming') {
    const card = el('article', {class: 's3-msg left s3-sfxguy s3-upcoming', 'data-turn': t.turn_id, 'data-stage': 'upcoming'}, who,
      el('div', 's3-bubble s3-sfx-bubble s3-roulette', el('span', {class: 's3-rl-hint', text: played ? `the clip the station matched${played.why ? ' on "' + played.why + '"' : ''}` : 'his line - no clip'})));
    card.s3 = {conv, t, obs, played};
    card.roll = () => landInOrder([]);
    return card;
  }
  const node = el('article', {class: 's3-msg left s3-sfxguy', 'data-turn': t.turn_id,
      title: v && v.tapAssembles ? 'tap to see it come together again; tap and hold for what to do with this clip' : 'tap for what to do with this clip'},
    who,
    el('div', 's3-bubble s3-sfx-bubble',
      quips.length ? el('div', {class: 's3-words', text: quips.join(' ')}) : null,
      played ? sfxClipCard(played, v) : el('div', {class: 's3-muted', text: 'no clip played - his line only'}),
      why ? el('div', {class: 's3-sfx-why', text: why}) : null),
    v && v.assemble ? el('div', 's3-reacts', assembleBtn(v)) : null);
  node.s3 = {conv, t, obs, played};
  if(v?.tileAttach)v.tileAttach(node,conv,t);
  if (v && v.dropDress) v.dropDress(node, 'clip:' + (obs.cursor || obs.at || t.turn_id), 'full', () => dropClipPanel(v, conv, t, obs, played));   /* [s3-msgdrop] */
  node.addEventListener('click', e => {
    if (v && v.tapAssembles) {                         /* [s3-imsg] the Messenger: a tap plays it coming together - never the radial */
      if (e.target.closest(TAP_CONTROLS)) return;
      e.stopPropagation();
      v.tapAssembles(node, e);
      return;
    }
    if (e.target.closest(KEEP_OPEN + ', .s3-vthumb, .s3-aplayer')) return;
    e.stopPropagation();
    openSfxMenu(conv, t, obs, played, v, node, e);
  });
  return node;
}

/* [s3-roads] The SFX Guy's own LINE, as System 3 drew it at air: what his
   node had planned, the kind that had something to say, the pool it came
   from with the die that picked it, and the words. */
const SFXGUY_KIND = {news: 'broke a story off the wire', reaction: 'fired back at the line', quip: 'a saying off his shelf',
  bank: 'a take off his speech bank'};
function sfxGuyLineEntry(conv, t, obs, v) {
  const draws = obs.draws || [];
  const last = draws[draws.length - 1] || null;
  const kind = SFXGUY_KIND[obs.kind] || obs.kind || '';
  const fell = (obs.fell_through || []).length
    ? 'nothing to ' + obs.fell_through.map(k => ({news: 'break', reaction: 'fire back', quip: 'say'}[k] || k)).join(' or ') + ', so '
    : '';
  const how = last ? `d${last.dice} landed on ${last.index} of ${last.of} in the ${last.pool} pool` : String(obs.how || '');
  const planned = obs.planned && obs.planned !== obs.kind ? ` · his node had planned: ${SFXGUY_KIND[obs.planned] || obs.planned}` : '';
  const who = el('div', 'who', sfxAvatar(), el('b', {text: castName('sfx')}), el('span', {text: `${kind} · after turn ${t.index + 1}`}));   /* [cast-names] */
  /* [s3-imsg] coming together again: his line as the dice that drew it at air, landing one after
     another, then his words */
  const key = v && v.obsKey ? v.obsKey('guy', obs, t, null) : '';
  if (v && v.replayAs && v.replayAs.get(key) === 'upcoming') {
    const chips = draws.map(d => {
      const face = die(d.dice == null || d.dice === '' ? null : Number(d.dice));
      const chip = el('span', {class: 's3-rl-chip', style: `--fam:${FAM.SFXGUY}`}, face, el('b', {text: 'LINE'}),
        el('span', {class: 's3-rl-pick', text: `the ${d.pool || ''} pool: ${d.index} of ${d.of}`}));
      chip.piece = landPiece(chip, face, null);
      return chip;
    });
    const card = el('article', {class: 's3-msg left s3-sfxguy s3-sfxguy-line s3-upcoming', 'data-turn': t.turn_id, 'data-stage': 'upcoming'}, who,
      el('div', 's3-bubble s3-roulette', chips.length ? el('div', 's3-rl-dice', ...chips) : null,
        el('span', {class: 's3-rl-hint', text: kind ? 'his line: ' + kind : 'his line'})));
    card.s3 = {conv, t, obs};
    card.roll = () => landInOrder(chips.map(c => c.piece));
    return card;
  }
  const node = el('article', {class: 's3-msg left s3-sfxguy s3-sfxguy-line', 'data-turn': t.turn_id,
      title: 'the SFX Guy\'s line: how System 3 drew it'},
    who,
    el('div', 's3-bubble',
      el('span', {class: 's3-words', text: obs.line || ''}),
      el('span', {class: 'dir', text: fell + how + planned}),
      last && last.candidates && last.candidates.length > 1
        ? el('div', {class: 's3-muted s3-reel-text', text: 'rolled through: ' + last.candidates.join(' · ')}) : null),
    v && v.assemble ? el('div', 's3-reacts', assembleBtn(v)) : null);
  node.s3 = {conv, t, obs};
  if(v?.tileAttach)v.tileAttach(node,conv,t);
  if (v && v.dropDress) v.dropDress(node, 'guy:' + (obs.cursor || obs.at || t.turn_id), 'full', () => dropGuyPanel(v, conv, t, obs));   /* [s3-msgdrop] */
  if (v && v.tapAssembles) {                           /* [s3-imsg] a tap plays it coming together */
    node.addEventListener('click', e => {
      if (e.target.closest(TAP_CONTROLS)) return;
      e.stopPropagation();
      v.tapAssembles(node, e);
    });
  }
  return node;
}

/* The script-ledger board row a played clip aired as: its name after the
   speaker glyph, after the turn's own line. */
function boardLineFor(conv, t, media) {
  const lines = (conv.lines || []).slice().sort((a, b) => (a.block - b.block) || (a.ord - b.ord));
  const bare = x => String(x || '').replace(/^\S+\s+/, '');
  if (media && media.name) {
    const hit = lines.find(l => l.who === 'board' && bare(l.text) === media.name);
    if (hit) return hit;
  }
  const mine = lines.findIndex(l => l.turn_id === t.turn_id);
  return mine >= 0 ? lines.slice(mine + 1).find(l => l.who === 'board') || null : null;
}

/* The clip, playable where it sits: a video as its poster that plays muted,
   small, in place when tapped; an audio clip with a visualiser that plays
   with sound or muted. */
function sfxClipCard(played, v) {
  const name = el('b', {text: played.clip || 'clip'});
  const card = el('div', {class: 's3-clip'}, el('div', 's3-clip-name', name));
  if (v && v.tapAssembles) {                  /* [s3-imsg] the Messenger: the clip plays in its card, one at a time */
    card.append(stingMedia(v, stingInfo(null, played)));
    return card;
  }
  const stagebox = el('div', 's3-clip-stage');
  card.append(stagebox);
  Promise.resolve(v.api.sfxMedia(played)).then(media => {
    if (!media || !media.url) { stagebox.remove(); return; }
    if (media.name) name.textContent = media.name;
    fill(stagebox, media.kind === 'video' ? videoThumb(media) : audioPlayer(media));
  }).catch(() => stagebox.remove());
  return card;
}

/* Posters are cut on the station two at a time; asking for more at once
   only queues them there. */
const posterQueue = [];
let postersBusy = 0;
function loadPoster(img, url) { posterQueue.push([img, url]); pumpPosters(); }
function pumpPosters() {
  while (postersBusy < 2 && posterQueue.length) {
    const [img, url] = posterQueue.shift();
    postersBusy += 1;
    const done = () => { postersBusy -= 1; pumpPosters(); };
    img.addEventListener('load', done, {once: true});
    img.addEventListener('error', () => { img.classList.add('broken'); done(); }, {once: true});
    img.src = url;
  }
}

/* ONE CLIP AT A TIME, ONCE THROUGH, ONLY ON SCREEN. A thumbnail used to
   loop forever once tapped, scrolled away or not: six of them measured at
   once on the tablet, six hardware decoders beside its own video wall. */
const THUMB = {stop: null};
const thumbSeen = typeof IntersectionObserver === 'function'
  ? new IntersectionObserver(rows => { for (const r of rows) if (!r.isIntersecting && r.target.s3stop) r.target.s3stop(); })
  : null;

function videoThumb(media) {
  const box = el('div', {class: 's3-vthumb', title: 'tap to watch it here, muted'});
  const still = () => {
    const img = el('img', {alt: 'the clip ' + castName('sfx') + ' played'});   /* [cast-names] */
    if (media.poster) loadPoster(img, media.poster);
    fill(box, media.poster ? img : el('span', 's3-vthumb-blank'), el('span', {class: 's3-play', 'aria-hidden': 'true'}),
      el('span', {class: 's3-vthumb-tag', text: media.seconds ? `${num(media.seconds, 1)} s` : 'video'}));
  };
  const stop = () => {
    const vid = box.querySelector('video');
    if (vid) { try { vid.pause(); vid.removeAttribute('src'); vid.load(); } catch (e) { /* gone */ } }
    box.classList.remove('on');
    if (THUMB.stop === stop) THUMB.stop = null;
    still();
  };
  box.s3stop = () => { if (box.classList.contains('on')) stop(); };
  const play = () => {
    if (THUMB.stop && THUMB.stop !== stop) THUMB.stop();
    THUMB.stop = stop;
    const vid = el('video', {src: media.url, autoplay: true, preload: 'metadata', 'aria-label': 'the clip, playing muted'});
    vid.addEventListener('ended', stop);
    vid.muted = true;
    vid.defaultMuted = true;
    vid.playsInline = true;
    vid.setAttribute('muted', '');
    vid.setAttribute('playsinline', '');
    if (media.poster) vid.poster = media.poster;
    if (window.PineAir && typeof window.PineAir.mine === 'function') window.PineAir.mine(vid);
    fill(box, vid, el('span', {class: 's3-vthumb-tag', text: 'muted'}));
    box.classList.add('on');
    vid.play().catch(() => {});
  };
  box.addEventListener('click', e => {
    e.stopPropagation();
    if (box.classList.contains('on')) stop(); else play();
  });
  still();
  if (thumbSeen) thumbSeen.observe(box);
  return box;
}

function audioPlayer(media) {
  const box = el('div', {class: 's3-aplayer'});
  if (media.spec) box.style.setProperty('--spec', `url("${media.spec}")`);
  const canvas = el('canvas', {width: 220, height: 44, class: 's3-viz', 'aria-hidden': 'true'});
  const audio = el('audio', {src: media.url, preload: 'none'});
  if (window.PineAir && typeof window.PineAir.mine === 'function') window.PineAir.mine(audio);
  let ctx = null, gain = null, analyser = null, raf = 0, loud = false;
  const wire = () => {
    if (ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = new AC();
    const src = ctx.createMediaElementSource(audio);
    analyser = ctx.createAnalyser();
    analyser.fftSize = 64;
    gain = ctx.createGain();
    src.connect(analyser); analyser.connect(gain); gain.connect(ctx.destination);
  };
  const draw = () => {
    const g = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    g.clearRect(0, 0, w, h);
    if (analyser) {
      const bins = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(bins);
      const bw = w / bins.length;
      g.fillStyle = getComputedStyle(canvas).color || '#7fe0d6';
      bins.forEach((b, i) => { const bh = Math.max(2, (b / 255) * h); g.fillRect(i * bw + 1, h - bh, bw - 2, bh); });
    }
    if (!audio.paused && !audio.ended) raf = requestAnimationFrame(draw);
  };
  /* With sound, the broadcast ducks under the audition, the way the
     sampler's own auditions do; muted, nothing on air moves. */
  const air = (on) => {
    const pa = window.PineAir;
    if (!pa) return;
    if (on && typeof pa.duck === 'function') pa.duck('s3-sfx-preview', audio.duration || media.seconds || 8);
    if (!on && typeof pa.release === 'function') pa.release('s3-sfx-preview');
  };
  const status = el('span', {class: 's3-muted', text: media.seconds ? `${num(media.seconds, 1)} s` : ''});
  const start = (withSound) => {
    wire();
    loud = !!withSound;
    if (gain) gain.gain.value = withSound ? 1 : 0;
    else audio.muted = !withSound;
    if (ctx && ctx.state === 'suspended') ctx.resume();
    audio.currentTime = 0;
    audio.play().then(() => {
      air(loud);
      cancelAnimationFrame(raf); raf = requestAnimationFrame(draw);
      status.textContent = withSound ? 'playing' : 'playing muted';
    }).catch(err => { status.textContent = 'could not play: ' + err.message; });
  };
  const stop = () => { audio.pause(); air(false); status.textContent = 'stopped'; };
  audio.addEventListener('ended', () => { air(false); status.textContent = 'played'; });
  box.append(canvas, el('div', 's3-row', btn('Play', e => { e.stopPropagation(); start(true); }),
    btn('Play muted', e => { e.stopPropagation(); start(false); }),
    btn('Stop', e => { e.stopPropagation(); stop(); }), status), audio);
  requestAnimationFrame(draw);
  return box;
}

/* sample id -> {kind, url, poster, spec, name, seconds}: one replay-source
   lookup per clip (the station finds the file off its event loop), the
   poster and spectrogram signed with the same token. */
const MEDIA = new Map();
async function sfxMedia(request, played) {
  const sid = String((played && played.sample_id) || '');
  if (!/^[a-f0-9]{16}$/.test(sid)) return null;
  if (!MEDIA.has(sid)) {
    MEDIA.set(sid, (async () => {
      const got = await request('/api/sfx/' + sid + '/replay-source');
      if (!got || !got.url) return null;
      const tok = (/[?&]t=([^&]+)/.exec(String(got.url)) || [])[1] || '';
      return {id: sid, name: String(got.name || ''), url: stationUrl(got.url), video: !!got.video,
        kind: got.video ? 'video' : 'audio', seconds: Number(got.seconds || 0) || null,
        poster: got.video && tok ? stationUrl('/api/sfx/poster/' + sid + '?t=' + tok) : '',
        spec: tok ? stationUrl('/api/sfx/spec/' + sid + '?t=' + tok) : ''};
    })().catch(() => { MEDIA.delete(sid); return null; }));
  }
  return MEDIA.get(sid);
}

/* [s3-imsg] A STING'S CLIP IN ITS MESSAGE. "I want to see the video play in
   the messenger view, but if I tap the message for the SFX in the messenger
   view, then I want to see it animated with the assembly of the dice rolling
   and then it transitioning into the video where it then shows the video
   play or it shows the audio waveform for the audio that's referenced"
   (operator, 2026-09-28).
   A video: its own frame (the poster) until it plays; then the clip, MUTED -
   the air carries the sound - once through, and back to its frame. An audio
   clip: its spectrogram with a playhead that crosses it in the clip's length.
   On air it plays with the air (face.clock: from where the clip has got to,
   drawn back into step when it drifts); a replay plays it from the start.
   ONE VIDEO DECODES AT A TIME, ONLY ON SCREEN, ONCE THROUGH: starting one
   unloads the one before (THUMB, shared with the old thumbnails); one that
   leaves the view, or the page, is unloaded at once; a clip off screen never
   starts; nothing loops - the tablet choked on six looping muted thumbnails.
   The file is asked for only when it plays (sfxMedia: one replay-source per
   clip); the frame and the spectrogram ride the ledger row (_sfx_roll_media).
   A tap on any of it is the message's tap: it plays the message coming
   together again (the Messenger's assemble), never the SFX TV's radial. */
const SFX_THUMB = /\/api\/sfx\/(poster|spec)\/([0-9a-f]{16})\?t=([^&#\s"]+)/;
function stingInfo(line, played) {
  const roll = line && line.sfx_roll && typeof line.sfx_roll === 'object' ? line.sfx_roll : {};
  const out = {sid: '', kind: '', poster: '', spec: '', seconds: Number((played && played.seconds) || 0) || null,
    name: boardName(line) || String((played && played.clip) || '')};
  const take = (u, kind) => {
    const m = SFX_THUMB.exec(String(u || ''));
    if (m) out.sid = out.sid || m[2];
    if (kind === 'video' || (m && m[1] === 'poster')) { out.kind = 'video'; out.poster = out.poster || String(u); }
    else if (kind === 'audio' || (m && m[1] === 'spec')) { out.kind = out.kind || 'audio'; out.spec = out.spec || String(u); }
  };
  if (line && typeof line.poster === 'string' && line.poster) take(line.poster, 'video');
  if (roll.thumb) take(roll.thumb, roll.thumb_kind === 'frame' ? 'video' : roll.thumb_kind === 'spectrogram' ? 'audio' : '');
  if (played && /^[0-9a-f]{16}$/.test(String(played.sample_id || ''))) out.sid = out.sid || String(played.sample_id);
  return out;
}
const stingSeen = typeof IntersectionObserver === 'function'
  ? new IntersectionObserver(rows => {
    for (const r of rows) { r.target.s3inView = r.isIntersecting; if (!r.isIntersecting && r.target.s3unload) r.target.s3unload(); }
  }) : null;
function stingMedia(v, info, {live = false} = {}) {
  const box = el('div', {class: 's3-sting-media ' + (info.kind === 'audio' ? 'audio' : 'video')});
  let media = null, vid = null, raf = 0, head = null, run = null;
  const still = () => {
    if (info.kind === 'audio') {
      head = el('i', {class: 's3-playhead', 'aria-hidden': 'true'});
      const img = el('img', {class: 's3-sting-spec', alt: 'the clip\'s spectrogram', decoding: 'async'});
      if (info.spec) loadPoster(img, stationUrl(info.spec));
      fill(box, el('div', 's3-sting-wave', img, head),
        el('span', {class: 's3-sting-len', text: info.seconds ? `${num(info.seconds, 1)} s` : 'audio'}));
      return;
    }
    const img = el('img', {class: 's3-sfxposter s3-sting-poster' + (live ? ' s3-popin' : ''), alt: info.name || 'the clip', decoding: 'async',
      onerror: e => { e.currentTarget.hidden = true; }});
    if (info.poster) img.src = stationUrl(info.poster); else img.hidden = true;
    fill(box, img);
  };
  /* back to its frame: the decoder is let go (src out, load()) - a detached <video> keeps decoding */
  const unload = () => {
    cancelAnimationFrame(raf); raf = 0; run = null;
    if (vid) { try { vid.pause(); vid.removeAttribute('src'); vid.load(); } catch (e) { /* gone */ } vid.remove(); vid = null; }
    box.classList.remove('on');
    if (THUMB.stop === unload) THUMB.stop = null;
    if (info.kind !== 'audio' && !box.querySelector('img')) still();
  };
  box.s3unload = () => { if (vid || raf) unload(); };
  const playhead = (from, seconds) => {
    if (!head || !(seconds > 0)) return;
    cancelAnimationFrame(raf);
    run = {t0: performance.now() - from * 1000, seconds};
    box.classList.add('on');
    const step = () => {
      raf = 0;
      if (!run || !box.isConnected) { run = null; return; }
      const k = Math.min(1, (performance.now() - run.t0) / 1000 / run.seconds);
      head.style.setProperty('--k', k.toFixed(4));
      if (k < 1) raf = requestAnimationFrame(step);
      else { run = null; box.classList.remove('on'); }
    };
    step();
  };
  box.play = async ({from = 0, seconds = 0} = {}) => {
    if (seconds > 0 && !info.seconds) info.seconds = seconds;          /* the air's own length for the clip */
    if (box.s3inView === false || !box.isConnected) return false;       /* off screen: it never starts */
    if (info.kind === 'audio' && info.seconds) { playhead(from, info.seconds); return true; }
    if (!info.sid || !v || !v.api) return false;
    media = media || await v.api.sfxMedia({sample_id: info.sid});
    if (!media || !media.url || !box.isConnected || box.s3inView === false) return false;
    if (!info.kind) info.kind = media.kind;
    if (media.kind === 'audio') {
      info.seconds = info.seconds || media.seconds;
      if (!info.spec && media.spec) info.spec = media.spec;
      if (!head) { box.className = 's3-sting-media audio'; still(); }
      playhead(from, info.seconds || 0);
      return true;
    }
    if (THUMB.stop && THUMB.stop !== unload) THUMB.stop();              /* one decoder: the last one lets go */
    THUMB.stop = unload;
    if (vid) unload();
    vid = el('video', {preload: 'auto', 'aria-label': 'the clip, playing muted - the air carries its sound', class: 's3-sting-video'});
    vid.muted = true; vid.defaultMuted = true; vid.playsInline = true; vid.loop = false;
    vid.setAttribute('muted', ''); vid.setAttribute('playsinline', '');
    if (media.poster || info.poster) vid.poster = media.poster || stationUrl(info.poster);
    if (window.PineAir && typeof window.PineAir.mine === 'function') window.PineAir.mine(vid);
    const me = vid;
    vid.addEventListener('ended', () => { if (vid === me) unload(); });
    vid.addEventListener('timeupdate', () => { if (vid === me && !box.isConnected) unload(); });
    vid.addEventListener('error', () => { if (vid === me) unload(); });
    if (from > 0.05) vid.addEventListener('loadedmetadata', () => { try { if (from < (vid.duration || 0)) vid.currentTime = from; } catch (e) { /* not seekable */ } }, {once: true});
    vid.src = media.url;
    fill(box, vid);
    box.classList.add('on');
    vid.play().catch(() => {});
    return true;
  };
  /* on air: kept with the air's clock for this clip */
  box.sync = (at) => {
    if (!(at >= 0)) return;
    if (vid && !vid.paused && isFinite(vid.duration) && Math.abs(vid.currentTime - at) > 0.45 && at < vid.duration - 0.2) {
      try { vid.currentTime = at; } catch (e) { /* not seekable yet */ }
    }
    if (run && info.seconds) { const want = performance.now() - at * 1000; if (Math.abs(run.t0 - want) > 300) run.t0 = want; }
  };
  box.playing = () => !!(vid && !vid.paused) || !!run;
  still();
  if (stingSeen) stingSeen.observe(box);
  return box;
}
/* [s3-imsg] "I want that little play button on every message so I can play it and see how the
   message was assembled by just clicking it": at the end of the dice row of every message - a
   spoken line, a card still to come, a sting, the SFX Guy's line and clip - ONE SPLIT BUTTON.
   The play half runs the compact assembly (v.assemble: the chip row landing one by one, the hold,
   the words); the arrow half runs the extended one (v.assembleExtended: every decision as its own
   big card - the roulette strip, the dice bar with its arithmetic, the Rolodex - opening and
   landing in the same order, then the words). The arrow is a Carbon caret from the vendored set
   (c:caret--right, turned down: the set has no caret--down), and Carbon's chevron inline when the
   icon set is not on the page. Neither moves the page. */
const TAP_CONTROLS = 'button, a[href], summary, input, select, textarea, label, [role="button"], .s3-drop, .s3-compose, .s3-gone-tag';
function assembleBtn(v) {
  const itemOf = e => e.currentTarget.closest('[data-item]') || e.currentTarget.closest('.s3-msg');
  const play = el('button', {type: 'button', class: 's3-assemble-btn', innerHTML: PLAY_SVG,
    title: 'play how this message came together - its dice landing one by one, then its words',
    'aria-label': 'play how this message came together',
    onclick: e => { e.stopPropagation(); const n = itemOf(e); if (n && v && v.assemble) v.assemble(n); }});
  const more = el('button', {type: 'button', class: 's3-assemble-more',
    title: 'the long version: every decision behind this message as its own card - the roulette, the dice and the Rolodex with their arithmetic',
    'aria-label': 'play the long version: every decision as its own card',
    onclick: e => { e.stopPropagation(); const n = itemOf(e); if (n && v && v.assembleExtended) v.assembleExtended(n); }});
  const caret = typeof window.pineIcon === 'function' ? window.pineIcon('c:caret--right') : '';
  if (caret) { more.innerHTML = caret; more.classList.add('s3-caret-down'); }
  else more.innerHTML = DROP_CHEVRON;
  return el('span', {class: 's3-assemble', role: 'group', 'aria-label': 'replay how this message came together'}, play, more);
}

/* The operator's menu for a clip The SFX Guy played - the station's own: the
   SFX TV's radial (send to the sampler, make a parody, examine it, make it a
   favourite, replay it, delete it), with Replay set to THIS clip on this
   screen only; an audio sting gets the universal line sheet instead. Away
   from the Script tab (the stand-alone instrument has neither), the record
   of the play. */
async function openSfxMenu(conv, t, obs, played, v, node, e) {
  const media = played ? await v.api.sfxMedia(played) : null;
  const tv = window.PineSfxTv;
  const at = {x: e && e.clientX ? e.clientX : innerWidth / 2, y: e && e.clientY ? e.clientY : innerHeight / 2};
  if (media && media.video && tv && typeof tv.openRadial === 'function') {
    const clip = {id: media.id, url: media.url, sting: media.name, text: media.name, seconds: media.seconds, video: true};
    clip.__pineActions = {replay: () => {
      if (typeof tv.cut === 'function') tv.cut({id: media.id, url: media.url, sting: media.name, seconds: media.seconds, video: true}, {ring: false});
    }};
    try { tv.openRadial(clip, at); return; } catch (err) { /* fall through to the record */ }
  }
  const la = window.PineLineActions;
  if (media && la && typeof la.open === 'function') {
    const board = boardLineFor(conv, t, media);
    if (board) {
      node.pineItem = {tag: 'sting', sfx: media.id, line: board.line_id, deleted: false, text: media.name};
      node.dataset.line = board.line_id;
      try { la.open({id: board.line_id, said: media.name, node}); return; } catch (err) { /* fall through */ }
    }
  }
  openDecision(conv, obs, t, v.api);
}

/* --- one message, replayed: how each value on it came to be ----------------
 *
 * "For each entry in messenger view, put a small play icon that when tapped
 *  animates the Rolodex and the roulette and the RNG system to show how this
 *  result was acquired. When animating show how each value came to be."
 *
 * Per recorded decision on the turn, in the order they were drawn: each stage
 * as it was drawn - a weighted draw as its roulette strip (every eligible
 * candidate a slice the width of its effective weight, a marker sweeping
 * round and landing where u put it), a dice roll as its 1-100 line with the
 * number it needed, a rule with no random number said as the rule - with the
 * arithmetic under it; then the Rolodex drum and the d100 settle on the
 * recorded outcome. Only recorded numbers are used. */
const PLAY_SVG = '<svg class="pi-icon" viewBox="0 0 32 32" aria-hidden="true" focusable="false">' +
  '<path d="M7 28a1 1 0 0 1-1-1V5a1 1 0 0 1 1.48-.88l20 11a1 1 0 0 1 0 1.76l-20 11A1 1 0 0 1 7 28Z"/></svg>';
const STAGE_NAME = {table: 'which table', category: 'which category', item: 'which one', mode: 'which way',
  dice: 'the dice', placement: 'where', intensity: 'how strongly', door: 'the door', turn: 'which turn', topic: 'which topic'};

Object.assign(STAGE_NAME, {threshold: 'character threshold', checkpoint: 'sentence boundary', speaker: 'next speaker', who: 'who', number: 'the number', count: 'how many', prize: 'which prize',   /* [s3-callend] */
  fixed: 'pinned'});

function rouletteBar(st) {
  const total = st.candidates.reduce((a, c) => a + (Number(c.weight) || 0), 0) || 1;
  const bar = el('div', 's3-rbar');
  let acc = 0;
  for (const c of st.candidates) {
    const w = (Number(c.weight) || 0) / total * 100;
    bar.append(el('i', {class: c.id === st.selected ? 'hit' : '', style: `left:${acc}%;width:${w}%`,
      title: `${c.label || c.id}: weight ${num(c.weight, 3)} (${pct(c.p)})`}));
    acc += w;
  }
  const mark = el('b', 's3-rbar-mark');
  bar.append(mark);
  bar.spin = async (ms) => {
    const land = Math.max(0, Math.min(100, (Number(st.draw && st.draw.u) || 0) * 100));
    if (ms <= 0) { mark.style.left = land + '%'; return; }
    mark.style.transition = 'none'; mark.style.left = '0%';
    await sleep(20);
    mark.style.transition = `left ${Math.round(ms * 0.4)}ms linear`; mark.style.left = '100%';     /* once round */
    await sleep(ms * 0.4);
    mark.style.transition = 'none'; mark.style.left = '0%';
    await sleep(20);
    mark.style.transition = `left ${Math.round(ms * 0.6)}ms cubic-bezier(.12,.72,.2,1)`; mark.style.left = land + '%';
    await sleep(ms * 0.6);
  };
  return bar;
}

function thresholdBar(st, ev) {
  const bar = el('div', 's3-tbar');
  const sfx = ev.family === 'SFX';
  const need = sfx ? Math.round((Number(st.threshold) || 0) * 100) : Number(st.threshold) || 0;
  /* the winning stretch: over the threshold for a speaker-box mark, under
     p for a planned clip */
  bar.append(el('i', {class: 'zone', style: sfx ? `left:0;width:${need}%` : `left:${need}%;width:${100 - need}%`}),
    el('span', {class: 'need', style: `left:${need}%`}));
  const mark = el('b', 's3-rbar-mark');
  bar.append(mark);
  bar.spin = async (ms) => {
    const land = sfx ? (Number(st.draw && st.draw.u) || 0) * 100 : (Number(st.draw && st.draw.dice) || 0);
    if (ms <= 0) { mark.style.left = land + '%'; return; }
    mark.style.transition = 'none'; mark.style.left = '0%';
    await sleep(20);
    mark.style.transition = `left ${ms}ms cubic-bezier(.12,.72,.2,1)`; mark.style.left = Math.max(0, Math.min(100, land)) + '%';
    await sleep(ms);
  };
  return bar;
}

function stepCaption(st, ev, turn) {
  const d = st.draw;
  if (st.candidates && st.candidates.length && d) {
    const total = st.candidates.reduce((a, c) => a + (Number(c.weight) || 0), 0);
    let acc = 0, from = 0, to = 0;
    for (const c of st.candidates) { const w = Number(c.weight) || 0; if (c.id === st.selected) { from = acc; to = acc + w; } acc += w; }
    const pick = st.candidates.find(c => c.id === st.selected) || {};
    return `u ${num(d.u, 4)} x total weight ${num(total, 2)} = ${num(d.u * total, 2)}, inside ${pick.label || st.selected}'s slice ` +
      `(${num(from, 2)}-${num(to, 2)}, ${pct(pick.p)} of the wheel)` + ((pick.why || []).length ? ` - its weight: ${pick.why.join(', ')}` : '');
  }
  if (st.stage === 'dice' && d && ev.family === 'SFX') {
    return /first exchange/.test(st.rule || '') ? `the first exchange always carries a clip (u ${num(d.u, 3)})`
      : `u ${num(d.u, 3)} ${d.u < st.threshold ? '<' : '>='} p ${num(st.threshold, 3)} (${(st.why || []).join(', ')}) - ${st.selected === 'PLAY' ? 'a clip' : 'no clip'}`;
  }
  if (st.stage === 'dice' && d) {
    const meta = ev.meta || {};
    return `d100 = floor(u ${num(d.u, 4)} x 100) + 1 = ${d.dice}; the ${meta.mark || ''} odds ${pct(meta.rate)} need over ${st.threshold} - ` +
      (d.dice > st.threshold ? 'a hit' : 'a miss');
  }
  if (st.stage === 'intensity' && d) {
    const perf = (turn && turn.performance) || {};
    const tension = ev.state_before ? Number(ev.state_before.tension) : NaN;
    return `0.2 + 0.6 x ${num(d.u, 3)} + 0.25 x (tension ${num(tension)} - 0.5) + 0.2 x (arousal ${num(perf.arousal)} - 0.5) = ${num(st.selected, 2)}`;
  }
  if (st.stage === 'placement' && d) return `u ${num(d.u, 3)}: before the line when u < 0.50 - ${String(st.selected || '').toLowerCase()}`;
  if (st.candidates && st.candidates.length === 1) return `only ${st.candidates[0].label || st.selected} was eligible - no draw`;
  return st.rule || (st.selected != null ? `decided without a random number: ${st.selected}` : 'no random number');
}

function replayCard(ev, conv, turn, api) {
  const line = eventLine(ev, conv);
  const face = die(line.dice);
  const out = sbOutcome(ev);
  if (out && !out.won) face.classList.add('miss');
  const card = el('div', {class: 's3-rcard', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`},
    el('div', 's3-rcard-head', el('b', {text: ev.family}),
      el('span', {text: (FAMILY_WHAT[ev.family] || [''])[0]}), face));
  const steps = [];
  for (const st of ev.stages || []) {
    const row = el('div', 's3-rstep');
    let spin = null;
    row.append(el('span', {class: 's3-rstep-name', text: STAGE_NAME[st.stage] || st.stage}));
    if (st.candidates && st.candidates.length > 1 && st.draw) { const bar = rouletteBar(st); row.append(bar); spin = bar.spin; }
    else if (st.stage === 'dice' && st.draw) { const bar = thresholdBar(st, ev); row.append(bar); spin = bar.spin; }
    const cap = el('div', {class: 's3-rcap', text: stepCaption(st, ev, turn)});
    cap.hidden = true;
    row.append(cap);
    row.hidden = true;
    card.append(row);
    steps.push({row, spin, cap});
  }
  if (!(ev.stages || []).length) {
    const meta = ev.meta || {};
    card.append(el('div', {class: 's3-rcap', text: 'not a draw: ' + (meta.why || (ev.selected || {}).authority || 'decided by a rule')}));
  }
  const item = stage(ev, 'item') || stage(ev, 'mode');
  let drumEl = null;
  if (item && item.candidates && item.candidates.length) {
    drumEl = drum(item.candidates, item.selected);
    card.append(el('div', 's3-roll', el('b', {text: 'the Rolodex'}), drumEl));
  }
  const result = el('div', {class: 's3-rcard-result', text: '= ' + line.text});
  result.hidden = true;
  const reels = docReels(conv, ev, turn, api);
  card.append(result, ...reels);
  card.play = async (base) => {
    for (const s of steps) {
      s.row.hidden = false;
      if (s.spin) await s.spin(base);
      s.cap.hidden = false;
      await sleep(base * 0.3);
    }
    await Promise.all([face.roll(base * 0.8), drumEl ? drumEl.roll(base) : null].filter(Boolean));
    result.hidden = false;
    await sleep(base * 0.3);
    if (reels.length) await playReels(null, reels, base);
  };
  return card;
}
/* [s3-imsg] One pick recorded with its row rather than as an event - a
   sting's category or clip, the SFX Guy's line - as a card of the long
   version: its die, a strip with a mark that lands where the pick sits in
   its pool, and what it landed on. Only recorded numbers. */
function pickCard(fam, name, r) {
  const face = die(r.dice == null || r.dice === '' ? null : Number(r.dice));
  const where = [r.index != null && r.of ? `landed on ${r.index} of ${r.of}` : r.of ? 'of ' + r.of : '',
    r.u != null ? 'u ' + num(r.u, 4) : '', r.by ? 'by ' + r.by : ''].filter(Boolean).join(' · ');
  const mark = el('b', 's3-rbar-mark');
  const bar = el('div', 's3-tbar s3-pbar', mark);
  const cap = el('div', {class: 's3-rcap', text: `${r.label ? '"' + String(r.label) + '"' : 'recorded with the row'}${where ? ' - ' + where : ''}`});
  cap.hidden = true;
  const card = el('div', {class: 's3-rcard', style: `--fam:${FAM[fam] || 'var(--obs)'}`},
    el('div', 's3-rcard-head', el('b', {text: fam}), el('span', {text: name}), face), bar, cap);
  const at = r.index != null && Number(r.of) > 0 ? (Number(r.index) - 0.5) / Number(r.of) * 100 : r.u != null ? Number(r.u) * 100 : 50;
  card.play = async (base) => {
    if (base > 0) {
      mark.style.transition = 'none'; mark.style.left = '0%';
      await sleep(20);
      mark.style.transition = `left ${Math.round(base)}ms cubic-bezier(.12,.72,.2,1)`;
    }
    mark.style.left = Math.max(0, Math.min(100, at)) + '%';
    await Promise.all([face.roll(base * 0.8), sleep(base)]);
    cap.hidden = false;
    await sleep(base * 0.3);
  };
  return card;
}

/* --- request ------------------------------------------------------------- */
function defaultRequest() {
  return async (path, options = {}) => {
    const key = localStorage.getItem('sparkAgentKey') || localStorage.getItem('pineboxApiKey') || localStorage.getItem('apiKey') || '';
    const response = await fetch(path, {...options, headers: {...(options.headers || {}),
      ...(key ? {Authorization: 'Bearer ' + key} : {}), ...(options.body ? {'Content-Type': 'application/json'} : {})}});
    const text = await response.text();
    let data; try { data = JSON.parse(text); } catch (e) { data = {detail: text}; }
    if (!response.ok) throw Error(data.detail || response.statusText);
    return data;
  };
}

/* ======================================================================== */
/* [s3-msgdrop] WHAT BUILT THIS MESSAGE.

   "on the right side of each message, put a dropdown arrow that expands to
    drop down showing the prompt / system prompt and connected values that
    made this conversational piece happen. I need to be able to see what
    built this message" (operator, 2026-09-28)

   A chevron at the right of each message's header line opens a panel under
   the message, inside it: the row System 3 wrote into the running order for
   the line (its protocol, its directions), every roll on it with its d100 (a
   tap opens the decision card), the prompt blocks System 3 sent, stripped or
   rolled for the writer's prompt, the prompt and the system prompt the writer
   was sent (folded, monospace, a copy button), and the ids that tie the line
   to its round, its ledger rows and its model call. Nothing is fetched until
   a panel is first opened; what was fetched is kept, and an open panel
   travels with its message when the message is drawn again (the air turning
   a card into words, a receipt, a refresh) - it never costs the live line a
   word. The same data calls as the line tabs: the round the Messenger holds
   (/api/system3/conversation/<id>), the model call found by findWriterCall
   (/api/prompt-history), the block decisions by the prompt's digest
   (/api/system3/prompt-blocks).

   A message not on air yet opens to its dice and the row planned for it -
   never its words, never its prompt (a writer's prompt can carry the words
   before it). A sting opens to its two dice and the SFX node behind it; the
   SFX Guy's line to his node and the draw at air.

   The prompts are operator data: makeViews / mountEmbedded / mount take
   `details` (mountEmbedded and mount: true). The public tune page mounts the
   Messenger with `details: false` and no chevron is drawn at all. */
const DROP_CHEVRON = '<svg class="s3-drop-chev" viewBox="0 0 32 32" aria-hidden="true" focusable="false">' +
  '<path d="M16 22 6 12l1.4-1.4 8.6 8.6 8.6-8.6L26 12z"/></svg>';
const dropSec = (title, ...kids) => el('section', 's3-drop-sec', el('h4', {text: title}), ...kids);
function dropPanel(...kids) {
  const panel = el('div', {class: 's3-drop', role: 'region', 'aria-label': 'What built this message', 'data-keep': ''}, ...kids);
  /* its own ground: a tap, a hold or a right-click in it is for the panel (selecting, copying), not the message */
  for (const type of ['click', 'pointerdown', 'contextmenu']) panel.addEventListener(type, e => e.stopPropagation());
  return panel;
}
function dropIds(pairs) {
  const rows = pairs.filter(p => p && p[1] != null && p[1] !== '');
  return el('div', 's3-drop-ids', ...rows.flatMap(([k, val]) => [el('span', {text: k}), el('code', {text: String(val)})]));
}
function dropCopy(text) {
  const b = el('button', {type: 'button', class: 's3-drop-copy', text: 'Copy', title: 'copy the whole text'});
  b.addEventListener('click', async e => {
    e.preventDefault(); e.stopPropagation();                /* in a summary: copy, do not fold */
    let ok = false;
    try { await navigator.clipboard.writeText(String(text)); ok = true; } catch (err) { ok = false; }
    if (!ok) {
      const area = el('textarea', {value: String(text), readonly: true, style: 'position:fixed;left:-9999px;top:0;opacity:0'});
      document.body.append(area);
      try { area.select(); ok = document.execCommand('copy'); } catch (err) { ok = false; }
      area.remove();
    }
    b.textContent = ok ? 'Copied' : 'Select it and copy by hand';
    setTimeout(() => { b.textContent = 'Copy'; }, 1800);
  });
  return b;
}
function dropText(title, text) {
  const raw = String(text || '');
  return el('details', 's3-drop-fold',
    el('summary', null, el('span', {text: title}), el('span', {class: 's3-muted', text: ` · ${raw.length.toLocaleString()} characters`}), dropCopy(raw)),
    el('pre', {class: 's3-drop-pre', text: raw || '(empty)'}));
}
/* one recorded decision: its d100, its family, what it landed on and why - a tap opens its card */
function dropRoll(ev, conv, t, api) {
  const line = eventLine(ev, conv);
  const face = die(line.dice);
  const sb = sbOutcome(ev);
  if (sb && !sb.won) { face.classList.add('miss'); face.title = sb.why; }
  const open = () => openDecision(conv, ev, t, api);
  return el('div', {class: 's3-drop-roll', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`, role: 'button', tabindex: '0',
      title: `${ev.family} - tap for how it was decided`,
      onclick: e => { e.stopPropagation(); open(); },
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); open(); } }},
    face, el('b', {text: ev.family}), el('span', {class: 's3-drop-item', text: String(landedWords(ev, conv) || '').replace(/\s+/g, ' ')}),
    el('span', {class: 's3-drop-why', text: sb ? sb.why : line.text}));
}
function dropDice(conv, evs, t, api) {
  return evs.length ? el('div', 's3-drop-dice', ...evs.map(ev => dropRoll(ev, conv, t, api))) : para('No roll was recorded on this message.', 's3-muted');
}
/* the row System 3 wrote for the line, its node's protocol, its directions; the whole running order folded */
function dropTold(conv, t) {
  const sheet = String((conv.plan || {}).sheet || '');
  const row = sheetRowOf(sheet, t).trim();
  const protocol = String(t.protocol || '').trim();
  const dirs = (t.directions || []).map(d => d && d.text).filter(Boolean);
  const perf = t.performance || {};
  const facts = [t.step_label ? 'node: ' + t.step_label : '', t.phase ? 'phase: ' + t.phase : '',
    perf.emotion ? `feeling: ${perf.emotion}${perf.intensity != null ? ' ' + num(perf.intensity) : ''}` : ''].filter(Boolean).join(' · ');
  return el('div', 's3-drop-told',
    row ? el('div', {class: 's3-drop-rowtext', text: row}) : para('The running order kept for this round has no row for this turn.', 's3-muted'),
    protocol && !normWs(row).toLowerCase().includes(normWs(protocol).toLowerCase())
      ? el('div', 's3-drop-line', el('b', {text: 'Its protocol: '}), protocol) : null,
    dirs.length ? el('div', 's3-drop-line', el('b', {text: 'Directions: '}), dirs.join('; ')) : null,
    facts ? el('div', {class: 's3-drop-line s3-muted', text: facts}) : null,
    sheet.trim() ? el('details', 's3-drop-fold', el('summary', {text: 'the whole running order System 3 wrote for the round'}),
      el('pre', {class: 's3-drop-pre'}, ...markIn(sheet.replace(/^\n+/, ''), row))) : null);
}
function dropTurnIds(conv, t) {
  const id = conv.identity || {};
  const lines = turnLines(conv, t);
  return [['conversation', id.conversation_id], ['turn', `${t.turn_id} · turn ${t.index + 1} of ${(conv.turns || []).length}`],
    ...(lines.length ? lines.map((l, i) => [lines.length > 1 ? `line ${i + 1}` : 'line', `${l.line_id} · block ${l.block}, line ${l.ord}`])
      : [['line', 'not in the script ledger yet']]),
    ['road', id.road_kind], ['mode', [conv.mode, conv.generation_mode].filter(Boolean).join(' · ')],
    ['seat', `${t.speaker}${t.name ? ' - ' + t.name : ''}`], ['node', [t.step, t.leg && t.leg !== t.step ? 'leg ' + t.leg : ''].filter(Boolean).join(' · ')],
    ['script index', t.script_index], ['planned', day(Number(conv.created || 0))], ['engine', conv.engine], ['config', conv.config_hash],
    ['schedule slot', id.system2_slot_id], ['trace', id.trace_id]];
}
/* The blocks System 3 decided for the writer's prompt: the round's PROMPT
   record (by its digest; the one decided last before this message's call
   when the round sent several), else asked by the prompt's own words. */
async function dropBlocks(box, v, conv, w, parts, cache, onDigest) {
  const request = v.api.request;
  const prompts = (conv.observations_air || []).filter(o => o && o.family === 'PROMPT' && o.digest);
  const callAt = w && w.row ? Number(w.row.at || 0) : 0;
  let obs = null, note = '';
  if (prompts.length === 1) obs = prompts[0];
  else if (prompts.length > 1) {
    const before = callAt ? prompts.filter(o => Number(o.at || 0) <= callAt + 5) : [];
    obs = before.length ? before.reduce((a, b) => (Number(b.at || 0) > Number(a.at || 0) ? b : a)) : prompts[0];
    note = `${prompts.length} prompts were decided for this round; ` + (before.length ? 'this is the last one decided before this message\'s model call.'
      : 'this message\'s call could not be placed among them, so this is the first.');
  }
  let got = null;
  try {
    if (obs) {
      got = cache.blocks.get(obs.digest);
      if (!got) { got = await request('/api/system3/prompt-blocks?digest=' + encodeURIComponent(obs.digest)); cache.blocks.set(obs.digest, got); }
    } else if (parts && parts.user) {
      const key = 'call:' + (w.row && w.row.id);
      got = cache.blocks.get(key);
      if (!got) {
        got = await request('/api/system3/prompt-blocks', {method: 'POST', body: JSON.stringify({text: String(parts.user)})});
        cache.blocks.set(key, got);
      }
    }
  } catch (e) { got = {error: (e && e.message) || String(e)}; }
  const rec = (got && got.prompt) || null;
  const rows = (rec && rec.blocks) || (obs && obs.blocks) || [];
  const digest = (rec && rec.digest) || (obs && obs.digest) || (got && got.digest) || '';
  if (digest && onDigest) onDigest(digest, rec ? Number(rec.at || 0) : obs ? Number(obs.at || 0) : 0);
  if (!rows.length) {
    fill(box, el('h4', {text: 'The prompt blocks'}), para(got && got.error ? 'System 3 could not be asked: ' + got.error
      : 'System 3 holds no block record for this prompt - it was written before prompt blocks were nodes, on a road System 3 does not decide, or the record has aged out.', 's3-muted'));
    return;
  }
  const rules = (got && got.rules) || {};
  const evs = new Map((conv.decision_events || []).filter(e => e.family === 'BLOCK').map(e => [e.event_id, e]));
  const rolledOf = b => b.odds != null || b.u != null;
  const kept = rows.filter(b => b.keep).length, rolled = rows.filter(rolledOf).length;
  const list = el('div', 's3-drop-blocks', ...rows.map(b => {
    const ev = b.event_id ? evs.get(b.event_id) : null;
    const roll = rolledOf(b);
    const dice = ev && ev.rng && ev.rng.dice != null ? ev.rng.dice : b.u != null ? Math.floor(Number(b.u) * 100) + 1 : null;
    const open = ev ? () => openDecision(conv, ev, null, v.api) : null;
    return el('div', {class: 's3-drop-block ' + (b.keep ? 'kept' : 'stripped') + (roll ? ' rolled' : ''), role: open ? 'button' : null, tabindex: open ? '0' : null,
        title: open ? 'tap for how System 3 decided this block' : null,
        onclick: open ? e => { e.stopPropagation(); open(); } : null,
        onkeydown: open ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); open(); } } : null},
      el('span', {class: 's3-drop-state', text: b.keep ? 'sent' : 'stripped'}),
      roll ? die(dice) : el('span', 's3-drop-nodie'),
      el('span', 's3-drop-bname', el('b', {text: b.label || (rules[b.name] || {}).label || b.name}), ' ', el('code', {text: b.name})),
      el('span', {class: 's3-drop-why', text: [b.kind === 'wedge' ? 'a wedge - no node claims it' : b.kind, roll ? `rolled at ${pct(b.odds)} odds` : '',
        b.why].filter(Boolean).join(' - ')}),
      !b.keep && b.text ? el('details', 's3-drop-fold', el('summary', {text: 'the text it would have sent'}), el('pre', {class: 's3-drop-pre', text: String(b.text)})) : null);
  }));
  fill(box, el('h4', {text: 'The prompt blocks - what System 3 sent, stripped or rolled'}),
    para(`${rows.length} block${rows.length === 1 ? '' : 's'}: ${kept} sent, ${rows.length - kept} stripped, ${rolled} rolled` +
      ((rec || obs) && (rec || obs).at ? ` - decided ${clock(Number((rec || obs).at))}` : '') + (note ? '. ' + note : ''), 's3-muted'),
    el('details', {class: 's3-drop-fold', open: rows.length <= 10 || rows.length !== kept || rolled > 0},
      el('summary', {text: 'every block, in the order the prompt carries them'}), list));
}
/* A spoken message: what System 3 told the writer, the dice, and - once it
   has aired - the blocks, the prompt and the system prompt, and the model call. */
function dropTurnPanel(v, conv, t, cache, card) {
  const id = conv.identity || {};
  const evs = turnEvents(conv, t);
  const head = el('div', 's3-drop-head', el('b', {text: card ? 'What will build this message' : 'What built this message'}),
    el('span', {class: 's3-muted', text: `${id.road_kind || 'a'} round · turn ${t.index + 1} of ${(conv.turns || []).length} · ${t.name || t.speaker}`}));
  const told = dropSec('What System 3 told the writer for this line', dropTold(conv, t));
  const dice = dropSec(`The dice - ${evs.length} roll${evs.length === 1 ? '' : 's'} on this line`, dropDice(conv, evs, t, v.api));
  const base = dropTurnIds(conv, t), extra = [];
  const idsBox = el('div', null, dropIds(base));
  const paintIds = () => fill(idsBox, dropIds([...base, ...extra]));
  const ids = dropSec('Connected values', idsBox);
  if (card) {
    return dropPanel(head, para('Not on air yet: its dice and the row planned for it. Its words, and the prompt that writes them, open here once the air reaches it.',
      's3-muted s3-drop-note'), told, dice, ids);
  }
  const blocks = el('section', 's3-drop-sec', el('h4', {text: 'The prompt blocks'}), para('Waiting for the model call...', 's3-muted'));
  const promptBox = el('div', 's3-drop-prompt', para('Looking for the model call that wrote this message...', 's3-muted'));
  const panel = dropPanel(head, told, dice, blocks, dropSec('The prompt to the writer, and the system prompt', promptBox), ids);
  const load = async (fresh = false) => {
    if (fresh) cache.writer.delete(t.turn_id);
    let w = cache.writer.get(t.turn_id);
    if (!w) {
      try { w = await findWriterCall(v.api.request, conv, t, cache.calls); }
      catch (e) { w = {row: null, detail: null, why: 'the prompt history could not be read: ' + ((e && e.message) || e)}; }
      cache.writer.set(t.turn_id, w);
    }
    extra.length = 0;
    const parts = w.row ? promptParts(w.detail || {}) : null;
    if (w.row) {
      const r = w.row, at = Number(r.at || 0), end = Number(r.finished || 0);
      const took = end && at ? ` · took ${num(end - at, 1)} s` : '';
      fill(promptBox,
        el('div', 's3-drop-line', el('b', {text: 'The model call: '}), `${r.model || '?'} - ${r.purpose || ''} - ${day(at)}${took}`),
        para((w.exact ? 'Proven by its words: ' : 'Nearest by time: ') + (w.why || ''), 's3-muted'),
        dropText('The prompt to the writer', parts.user),
        parts.sys ? dropText('The system prompt, as it was sent', parts.sys)
          : el('div', 's3-drop-line', el('b', {text: 'The system prompt: '}), parts.user ? NO_SYSTEM : '(none)'));
      extra.push(['model call', `${r.model || '?'} · ${r.purpose || ''}`], ['call id', r.id], ['called', day(at) + took],
        ['found', w.exact ? 'proven by its words' : 'nearest by time'], ['model settings', JSON.stringify(parts.opts)]);
    } else {
      fill(promptBox, para('No prompt for this message: ' + (w.why || 'no model call was found.'), 's3-muted'),
        el('div', 's3-row', btn('Look again', () => { fill(promptBox, para('Looking again...', 's3-muted')); load(true); }, {class: 's3-drop-again'})));
    }
    paintIds();
    await dropBlocks(blocks, v, conv, w, parts, cache, (digest, at) => { extra.push(['prompt digest', digest + (at ? ' · ' + clock(at) : '')]); paintIds(); });
  };
  load();
  return panel;
}
/* what the station played at a turn's air: the clip, why it matched, the SFX Guy's words with it */
function dropPlayed(obs, played) {
  const m = (obs && obs.matcher) || {};
  const quips = obs ? (obs.sfx_guy || []).map(q => q && q.text).filter(Boolean) : [];
  if (!played && !quips.length && m.cands == null) return null;
  return dropSec('What the station played',
    dropIds([['clip', played && played.clip], ['matched on', played && played.why], ['length', played && played.seconds ? num(played.seconds, 1) + ' s' : ''],
      ['candidates', m.cands != null ? `${m.cands} (${m.eligible} eligible)` : ''], ['sample', played && played.sample_id],
      ['due', obs && obs.due], ['the SFX Guy said', quips.join(' ')]]));
}
/* the SFX node on the turn: its die and the plan it made */
function dropSfxNode(v, conv, t) {
  const plan = t.sfx || {};
  const ev = plan.event_id ? (conv.decision_events || []).find(e => e.event_id === plan.event_id) : null;
  const said = [plan.play ? ('play ' + (plan.placement || '')).trim() : plan.play === false ? 'no clip planned' : '',
    plan.p != null ? 'odds ' + pct(plan.p) : '', plan.reason ? 'why: ' + plan.reason : '',
    (plan.intent || []).length ? 'about: ' + plan.intent.slice(0, 5).join(', ') : '', plan.gain ? 'gain: ' + plan.gain : ''].filter(Boolean).join(' · ');
  return dropSec(`The SFX node on turn ${t.index + 1}`, ev ? el('div', 's3-drop-dice', dropRoll(ev, conv, t, v.api)) : null,
    said ? el('div', {class: 's3-drop-line', text: said}) : ev ? null : para('No SFX node was recorded on this turn.', 's3-muted'));
}
/* A sting on the ledger: its two dice, the SFX node behind it, and - once it aired - what played */
function dropStingPanel(v, conv, t, line, pair, card) {
  const roll = line.sfx_roll && typeof line.sfx_roll === 'object' ? line.sfx_roll : {};
  const rows = [['category', roll.category], ['clip', roll.clip]].filter(([, r]) => r && typeof r === 'object').map(([name, r]) =>
    el('div', {class: 's3-drop-roll', style: '--fam:var(--sfx)'}, die(r.dice == null || r.dice === '' ? null : Number(r.dice)), el('b', {text: name.toUpperCase()}),
      el('span', {class: 's3-drop-item', text: String(r.label || '')}),
      el('span', {class: 's3-drop-why', text: [r.index != null && r.of ? `landed on ${r.index} of ${r.of}` : r.of ? 'of ' + r.of : '', r.by ? 'by ' + r.by : '',
        r.u != null ? 'u = ' + num(r.u, 6) : '', r.tries > 1 ? r.tries + ' tries' : ''].filter(Boolean).join(' · ') || 'recorded with the row'})));
  const id = conv.identity || {};
  return dropPanel(
    el('div', 's3-drop-head', el('b', {text: card ? 'What will play here' : 'What built this sting'}),
      el('span', {class: 's3-muted', text: `a sting after turn ${t.index + 1}`})),
    card ? para('Not on air yet: its dice and the node that asked for it. What the station plays opens here once the air reaches it.', 's3-muted s3-drop-note') : null,
    dropSec('Its dice' + (roll.road ? ' - the ' + roll.road + ' road' : ''), rows.length ? el('div', 's3-drop-dice', ...rows) : para('No roll was recorded with this row.', 's3-muted')),
    dropSfxNode(v, conv, t),
    card ? null : dropPlayed(pair && pair.obs, pair && pair.played),
    dropSec('Connected values', dropIds([['line', `${line.line_id} · block ${line.block}, line ${line.ord}`], ['row', line.who || line.kind],
      ['conversation', id.conversation_id], ['after turn', `${t.turn_id} · turn ${t.index + 1}`], ['road', id.road_kind],
      card ? null : ['poster', typeof line.poster === 'string' ? line.poster : '']])));
}
/* The SFX Guy's clip at a turn with no ledger row of its own */
function dropClipPanel(v, conv, t, obs, played) {
  const id = conv.identity || {};
  return dropPanel(
    el('div', 's3-drop-head', el('b', {text: 'What built this clip'}), el('span', {class: 's3-muted', text: `the SFX Guy after turn ${t.index + 1}`})),
    dropSfxNode(v, conv, t), dropPlayed(obs, played),
    dropSec('Connected values', dropIds([['conversation', id.conversation_id], ['after turn', `${t.turn_id} · turn ${t.index + 1}`],
      ['script index', obs.turn_index], ['at', obs.at ? clock(Number(obs.at)) : ''], ['cursor', obs.cursor]])));
}
/* The SFX Guy's line: his node on the turn, the draw at air, the ledger row it aired as */
function dropGuyPanel(v, conv, t, obs) {
  const id = conv.identity || {};
  const g = t.sfxguy || {};
  const node = g.event_id ? (conv.decision_events || []).find(e => e.event_id === g.event_id) : null;
  const draws = (obs.draws || []).map(d => el('div', {class: 's3-drop-roll', style: `--fam:${FAM.SFXGUY}`}, die(d.dice), el('b', {text: 'LINE'}),
    el('span', {class: 's3-drop-item', text: `the ${d.pool || ''} pool: ${d.index} of ${d.of}`}),
    el('span', {class: 's3-drop-why', text: (d.candidates || []).length ? 'rolled through: ' + d.candidates.join(' · ') : ''})));
  const said = normWs(obs.line).toLowerCase();
  const row = said ? (conv.lines || []).find(l => l.who === 'drop' && normWs(l.text).toLowerCase() === said) : null;
  return dropPanel(
    el('div', 's3-drop-head', el('b', {text: 'What built this line'}), el('span', {class: 's3-muted', text: `the SFX Guy after turn ${t.index + 1}`})),
    dropSec(`His node on turn ${t.index + 1}`, node ? el('div', 's3-drop-dice', dropRoll(node, conv, t, v.api)) : para('His node on this turn was not recorded.', 's3-muted'),
      el('div', {class: 's3-drop-line', text: [g.speak ? 'speaks' : g.speak === false ? 'passes' : '', g.kind ? 'planned: ' + g.kind : '',
        (g.order || []).length ? 'order: ' + g.order.join(', ') : '', g.p != null ? 'odds ' + pct(g.p) : ''].filter(Boolean).join(' · ')})),
    dropSec('The draw at air', draws.length ? el('div', 's3-drop-dice', ...draws) : para(obs.how || 'No draw was recorded with his line.', 's3-muted'),
      (obs.fell_through || []).length ? el('div', {class: 's3-drop-line', text: 'nothing to ' + obs.fell_through.join(' or ') + ' first'}) : null),
    dropSec('Connected values', dropIds([['line', row ? `${row.line_id} · block ${row.block}, line ${row.ord}` : ''], ['kind', obs.kind], ['planned', obs.planned],
      ['conversation', id.conversation_id], ['after turn', `${t.turn_id} · turn ${t.index + 1}`], ['at', obs.at ? clock(Number(obs.at)) : ''], ['cursor', obs.cursor]])));
}

/* [s3-msgdrop] THE FEELING, AT A GLANCE. "for messages that get an ES result
   from the roulette, have them display relevant emojis for each category in
   the bottom right of each message" (operator, 2026-09-28). A written
   message whose turn rolled an ES shows, at the right end of its direction
   line, the ES category's emoji and then the item's own when it has a
   different one. The engine stamps them on the turn's ES decision
   (`t.decisions` family 'ES': `emoji: [category, item]`); a round written
   before that falls back to the category's own, ES_EMOJI_FALLBACK. Real
   colour emoji - the operator's exception to the Carbon-only rule - drawn in
   an emoji face, never through PineIcons (whose cmap turns emoji codepoints
   into Carbon outlines). Not operator data: it shows wherever the message
   does, `details` or not. Never on a roulette card - that one shows its ES
   die. */
const ES_EMOJI_FALLBACK = {surprise: '\u{1F62E}', anger: '\u{1F620}', fear: '\u{1F628}', sadness: '\u{1F622}', joy: '\u{1F604}',
  disgust: '\u{1F922}', interest: '\u{1F914}', social: '\u{1F633}', low_arousal: '\u{1F610}'};   /* [es-emoji-contract] = system3_tables._ES_EMOJI */
function esEmojiOf(t) {
  const dec = (t.decisions || []).find(d => d && d.family === 'ES') || null;
  if (!dec) return {list: [], words: ''};
  const item = String(dec.item || '');
  const cat = String(dec.category || item.split('.')[0] || '');
  const word = String(dec.label || item.split('.').slice(1).join('.') || '');
  /* [es-emoji-contract] the key present (even []) is the table's word - [] is cleared, nothing shows;
     absent is a turn planned before the badges: its category's default */
  let list = Array.isArray(dec.emoji) ? dec.emoji.map(x => String(x || '').trim()).filter(x => x && x.length <= 16)
    : (dec.item && ES_EMOJI_FALLBACK[cat] ? [ES_EMOJI_FALLBACK[cat]] : []);
  list = list.slice(0, 2).filter((x, i, all) => all.indexOf(x) === i);
  return {list, words: [cat.replace('_', ' '), word].filter(Boolean).join(' · ')};
}
function esDress(node, t) {
  const got = esEmojiOf(t);
  const bubble = got.list.length ? node.querySelector(':scope > .s3-bubble') : null;
  if (!bubble) return;
  const say = 'ES: ' + (got.words || 'the feeling it was rolled');
  const badge = el('span', {class: 's3-es-badge', role: 'img', 'aria-label': say, title: say},
    ...got.list.map(x => el('span', {class: 's3-es-emo', text: x})));
  const dir = bubble.querySelector(':scope > .dir');
  if (dir) { dir.classList.add('s3-has-es'); dir.append(badge); }
  else bubble.append(el('span', 's3-es-row', badge));
}

/* ======================================================================== */
/* Follow the active category/sub-entry or the typed tail only when it clips
   its existing viewport. Scrolling leaves the tile's geometry unchanged. */
function tileFocus(node){
  const state=node?.s3Tile;
  if(state?.seq){const table=state.sheet.tables[parseInt(state.sheet.now,10)]||state.sheet.tables.find(t=>state.sheet.elapsed>=t.at&&state.sheet.elapsed<t.end)||state.sheet.tables.at(-1);if(table)return table.sub&&state.sheet.now.includes('sub-')?table.sub.el:table.cat.el;}
  const words=node?.querySelector(':scope > .s3-bubble .s3-words');
  return words&&!words.hidden&&words.textContent?words:node;
}
function tileViewport(box,topInset=8){
  const view=box.getBoundingClientRect();let top=Math.max(0,view.top)+topInset,bottom=Math.min(innerHeight,view.bottom)-8;
  for(let parent=box.parentElement;parent;parent=parent.parentElement)if(/auto|scroll|hidden|clip/.test(getComputedStyle(parent).overflowY)){
    const rect=parent.getBoundingClientRect();top=Math.max(top,rect.top+parent.clientTop);bottom=Math.min(bottom,rect.top+parent.clientTop+parent.clientHeight);
  }
  return {top,bottom};
}
function followTile(node,box,topInset=8){
  const focus=tileFocus(node);if(!focus?.isConnected||!box?.isConnected||!box.clientHeight)return;
  const rect=focus.getBoundingClientRect(),{top,bottom}=tileViewport(box,topInset);
  if(!rect.height||bottom<=top)return;
  const by=rect.bottom>bottom?rect.bottom-bottom:rect.bottom<top?rect.top-top:0;
  if(Math.abs(by)>1)box.scrollTop+=by;
}
function revealTilePane(pane,box){
  const rect=pane.getBoundingClientRect(),{top,bottom}=tileViewport(box);if(bottom<=top)return;
  const by=rect.bottom<=top?rect.top-top:rect.top>=bottom?(rect.height<=bottom-top?rect.bottom-bottom:rect.top-top):0;
  if(Math.abs(by)>1)box.scrollTop+=by;
}

/* The three views, shared by the full instrument (mount) and the Script
   tab's embedded Messenger / Technical views (mountEmbedded). One renderer,
   so the two hosts can never disagree about what a roll looked like. */
function makeViews({request, onSelect, details = false} = {}) {
  const v = {conv: null, convs: new Map(), air: new Map(), sel: {turn: '', event: ''}, speed: 1, playing: false, open: new Set(),
    token: 0, alive: true, onBuildState: null,
    paneA: el('section', {class: 's3-pane', 'aria-label': 'Conversation view'}),
    paneB: el('section', {class: 's3-pane', 'aria-label': 'Technical RNG Rolodex'}),
    paneC: el('section', {class: 's3-pane', 'aria-label': 'Final script and provenance'})};
  const inspectCache = new Map();
  /* [s3-msgdrop] "what built this message": a chevron on each message's
     header, its panel under the message (dropTurnPanel). Off unless the host
     asks (mountEmbedded and mount do; the tune page passes details: false).
     The open set and the built panels are kept by key, so a message drawn
     again comes back with its panel open where it was, fetched once. */
  v.details = !!details;
  v.dropHook = null;                              /* the host's word when a panel opens or closes */
  const drop = {open: new Set(), panels: new Map(), writer: new Map(), calls: new Map(), blocks: new Map()};
  v.dropOpen = key => drop.open.has(key);
  v.dropDress = (node, key, mode, make) => {
    const who = v.details && node && key ? node.querySelector(':scope > .who') : null;
    if (!who) return node;
    const id = key + '|' + mode;
    const dom = 's3drop-' + String(key).replace(/[^\w-]+/g, '-');
    const chev = el('button', {type: 'button', class: 's3-drop-btn', innerHTML: DROP_CHEVRON, 'aria-controls': dom});
    const paint = open => {
      chev.setAttribute('aria-expanded', String(open));
      chev.title = open ? 'Close what built this message' : 'What built this message: the prompt, the system prompt, the dice and the values behind it';
      chev.setAttribute('aria-label', chev.title);
      node.classList.toggle('s3-drop-open', open);
    };
    const attach = () => {
      let panel = drop.panels.get(id);
      if (!panel) {
        panel = make(drop);
        panel.id = dom;
        drop.panels.set(id, panel);
        for (const k of drop.panels.keys()) {       /* the oldest closed ones go first */
          if (drop.panels.size <= 60) break;
          if (!drop.open.has(k.split('|')[0])) drop.panels.delete(k);
        }
      }
      node.append(panel);
    };
    chev.addEventListener('pointerdown', e => e.stopPropagation());     /* a tap, not the start of a hold */
    chev.addEventListener('click', e => {
      e.stopPropagation();
      const open = !drop.open.has(key);
      if (open) { drop.open.add(key); attach(); }
      else { drop.open.delete(key); const p = node.querySelector(':scope > .s3-drop'); if (p) p.remove(); }
      paint(open);
      if (typeof v.dropHook === 'function') v.dropHook(node, open, key);
    });
    who.append(chev);
    paint(drop.open.has(key));
    if (drop.open.has(key)) attach();
    return node;
  };
  /* [s3-still] "If I'm looking at something, do not reset my view or scroll
     my view ever." The window sets `quiet`: no programmatic select, build
     or refresh scrolls a pane - a tap on a turn still finds it in the OTHER
     panes. `newestFirst` lists a round's turns latest first ("the latest
     entry always at the top as the first thing listed"). */
  v.quiet = false;
  v.newestFirst = false;
  v.turnsInOrder = conv => (v.newestFirst ? [...((conv && conv.turns) || [])].reverse() : ((conv && conv.turns) || []));

  /* Several rounds can be on show at once (the Script tab's live feed), so
     every renderer finds a turn's own conversation: turn ids are
     "<conversation>:tNN". */
  v.convOf = (t) => {
    const id = String((t && t.turn_id) || '').split(':')[0];
    return v.convs.get(id) || v.conv;
  };
  v.remember = (conv) => { if (conv && conv.identity) v.convs.set(conv.identity.conversation_id, conv); };
  v.forget = (id) => { v.convs.delete(id); };
  v.setConversation = (conv, air) => {
    v.token += 1;
    v.conv = conv;
    if (conv) v.remember(conv);
    if (air) for (const [k, x] of air) v.air.set(k, x);
  };

  v.inspectBlocks = async (c, fresh = false) => {
    const out = new Map();
    const blocks = [...new Set((c.lines || []).map(l => l.block))].filter(Boolean);
    for (const b of blocks) {
      const cached = inspectCache.get(b);
      let got = !fresh && cached && Date.now() - cached.at < 20000 ? cached.data : null;
      if (!got) {
        try { got = await request('/api/segment/inspect?block=' + b); inspectCache.set(b, {at: Date.now(), data: got}); }
        catch (e) { got = {lines: [], why: e.message}; }
      }
      for (const l of got.lines || []) out.set(l.line_id, l);
    }
    return out;
  };

  /* The dials the opened line's odds panel reads and turns: the DJ desk's
     speaker-box dials through the station's own dial door, the density
     control and the inline budget through System 3's settings and config. */
  let dialsAt = 0, dialsLive = null, policyAt = 0, policyLive = null;
  v.api = {
    request,   /* [s3-dice] so a card can open the Tables tab on its table */
    async dials() {
      if (dialsLive && Date.now() - dialsAt < 15000) return {...dialsLive};
      const [settings, s3, cfg] = await Promise.all([request('/api/settings'), request('/api/system3/settings'),
        request('/api/system3/config')]);
      const dj = (settings && (settings.dj || (settings.settings || {}).dj)) || {};
      const sb = (((cfg || {}).config) || {}).speakerbox || {};
      dialsLive = {speakbox_prepend_rate: Number(dj.speakbox_prepend_rate ?? 0), speakbox_append_rate: Number(dj.speakbox_append_rate ?? 0),
        speakbox_full_swath_rate: Number(dj.speakbox_full_swath_rate ?? 0),
        density: Number(((((s3 || {}).settings) || {}).controls || {}).speakerbox_density ?? 0.5),
        max_inline: Number(sb.max_inline ?? 2), speakerbox: sb};
      dialsAt = Date.now();
      return {...dialsLive};
    },
    async saveDials(was, now) {
      const done = [];
      for (const key of Object.values(DIAL_KEY)) {
        if (Math.abs(Number(now[key]) - Number(was[key])) < 0.0005) continue;
        await request('/api/dj/dial', {method: 'POST', body: JSON.stringify({key, value: Number(now[key]), was: was[key],
          word: 'System 3 messenger: speaker-box odds'})});
        done.push(key.replace('speakbox_', '').replace('_rate', '').replace('_', ' ') + ' ' + pct(now[key]));
      }
      if (Math.abs(Number(now.density) - Number(was.density)) >= 0.0005) {
        await request('/api/system3/settings', {method: 'POST', body: JSON.stringify({controls: {speakerbox_density: Number(now.density)}})});
        done.push('density ' + num(now.density));
      }
      if (Number(now.max_inline) !== Number(was.max_inline)) {
        await request('/api/system3/config/section/speakerbox', {method: 'PUT',
          body: JSON.stringify({...(was.speakerbox || {}), max_inline: Number(now.max_inline)})});
        done.push('passages per round ' + now.max_inline);
      }
      dialsLive = null;
      return done;
    },
    sfxMedia: (played) => sfxMedia(request, played),
    /* the orchestrator's policy book: {key: true|false}, unset = on */
    async policy(fresh = false) {
      if (!fresh && policyLive && Date.now() - policyAt < 10000) return {...policyLive};
      const logic = await request('/api/orchestrator/logic');
      const book = (logic && logic.policy) || {};
      policyLive = Object.fromEntries(CUT_ROADS.map(r => [r.key, (book[r.key] || {}).value !== false]));
      policyAt = Date.now();
      return {...policyLive};
    },
    async setPolicy(road, on) {
      const arg = on ? (road.on || 'on') : (road.off || 'off');
      await request('/api/orchestrator/policy', {method: 'POST', body: JSON.stringify({does: road.verb + ':' + arg})});
      policyLive = null;
    },
    /* one speaker-box document as the lines System 3 counted (the line reel) */
    doc: (file, mind) => docLines(request, file, mind),
    docText: (file, mind) => docText(request, file, mind),
  };

  /* Shadow: the words the legacy writer actually put on this turn's seat,
     when the planned turn aligned to one. */
  v.aired = (t, conv) => {
    const c = conv || v.convOf(t);
    if (!c || c.mode !== 'shadow' || !Array.isArray(c.actual)) return null;
    const bind = (c.shadow_bindings || []).find(b => b.turn_id === t.turn_id);
    if (!bind || bind.script_index == null) return null;
    return c.actual[bind.script_index] || null;
  };

  v.turnStatus = (t, conv) => {
    const c = conv || v.convOf(t);
    const line = (c.lines || []).find(l => l.turn_id === t.turn_id);
    if (c.mode === 'simulation') return {word: 'simulated', cls: ''};
    const a = line ? v.air.get(line.line_id) : null;
    const shadow = c.mode === 'shadow';
    if (!line) return {word: shadow ? (v.aired(t, c) ? 'shadow plan · aired words' : 'shadow plan only') : (t.status || 'planned'), cls: ''};
    if (!a) return {word: shadow ? 'shadow plan · frozen words' : 'frozen', cls: '', line};
    const pre = shadow ? 'shadow plan · ' : '';
    if (a.heard) return {word: pre + 'heard ' + (a.at || ''), cls: 'heard', line, air: a};
    if (a.aired === 'withdrawn') return {word: pre + 'withdrawn', cls: 'gone', line, air: a};
    if (a.published) return {word: pre + 'published', cls: '', line, air: a};
    return {word: pre + (a.aired || 'frozen'), cls: '', line, air: a};
  };

  /* [s3-messenger] THE MESSENGER'S STAGES. A Messenger (the Script tab's, and
     the window's conversation pane) sets `sequenced`: a line not yet on air
     is drawn as its roulette - its dice, never its words - until the air
     reaches it. Stages: 'upcoming' (the roulette card), 'live' (on air, its
     words shown as far as `revealed` says), 'past' (aired), 'skipped' (the
     air's own receipt says withdrawn or cut), 'written' (drawn whole, no
     sequence: a shadow round, a history). Keys: a turn id, or 'sfx:<line>'
     for a sting. The window reads each line's receipt; the Script tab knows
     the air line by line and replaces stageOf / revealed / dressItem. */
  v.sequenced = false;
  v.wordsOf = (t, conv) => t.text || ((v.aired(t, conv) || {}).text) || '';
  /* [s3-imsg] A TURN THE AIR TAKES IN RUNS. When a sting (or any row that is
     not the turn's own) airs between two lines of one turn, the turn is
     heard as runs of lines with the sting between them - so the Messenger
     shows one message per run (the tune page's per-clip messages), each
     released when ITS first line reaches the air: the words of a line whose
     clip has not aired are never on screen. The first run keeps the turn's
     key; a later one is 'part:<its first line>'. null when the turn's lines
     run unbroken (one message, as before), or a run has no words of its own. */
  const PARTS = new WeakMap();
  v.partsOf = (conv, t) => {
    if (!v.sequenced || !conv || !t) return null;
    let memo = PARTS.get(conv);
    if (!memo) { memo = new Map(); PARTS.set(conv, memo); }
    if (memo.has(t.turn_id)) return memo.get(t.turn_id);
    let out = null;
    if (turnLines(conv, t).length > 1) {
      const runs = [];
      let cur = null;
      for (const l of (conv.lines || []).filter(x => Number(x.block) > 0).slice().sort(byLedger)) {
        if (l.turn_id === t.turn_id && isSpoken(l)) { if (!cur) runs.push(cur = []); cur.push(l); }
        else if (cur) cur = null;
      }
      if (runs.length > 1 && runs.every(r => r.some(l => String(l.text || '').trim()))) {
        out = runs.map((r, i) => ({key: i ? 'part:' + r[0].line_id : t.turn_id, index: i, of: runs.length, lines: r,
          text: r.map(l => String(l.text || '').trim()).filter(Boolean).join(' ')}));
      }
    }
    memo.set(t.turn_id, out);
    return out;
  };
  /* the ledger lines an item speaks: a run's own, else the turn's */
  v.linesOf = (key, conv, t) => {
    const parts = v.partsOf(conv, t);
    const p = parts && parts.find(x => x.key === key);
    return p ? p.lines : turnLines(conv, t);
  };
  v.airStage = (key, conv, t) => {
    if (!conv || conv.mode === 'shadow' || conv.mode === 'simulation') return 'written';
    const lines = key.startsWith('sfx:') ? (conv.lines || []).filter(l => 'sfx:' + l.line_id === key) : v.linesOf(key, conv, t);
    const got = airOfLines(lines, v.air);
    if (got === 'aired') return 'written';
    if (got === 'off') return 'skipped';
    if (got === 'waiting') return 'upcoming';
    return Date.now() / 1000 - convAt(conv) > STALE_S ? 'written' : 'upcoming';
  };
  v.stageOf = (key, conv, t) => (v.replayAs.has(key) ? v.replayAs.get(key) : v.sequenced ? v.airStage(key, conv, t) : 'written');
  v.revealed = (key, len) => len;
  v.dressItem = null;
  /* a line on air shows its words as the audio reaches them: nothing types them in whole over it */
  const typable = n => !!n && n.dataset.stage !== 'live';
  const offWhy = (conv, lines) => {
    for (const l of lines) { const a = v.air.get(l.line_id); if (airOff(a)) return a.cut_why || a.withdrawn_why || a.aired; }
    return '';
  };

  v.select = (turnId, eventId, from) => {
    v.sel = {turn: turnId || '', event: eventId || ''};
    for (const pane of [v.paneA, v.paneB, v.paneC]) {
      for (const n of pane.querySelectorAll('[data-turn]')) n.classList.toggle('sel', n.dataset.turn === v.sel.turn && (!n.dataset.event || !v.sel.event || n.dataset.event === v.sel.event));
      for (const n of pane.querySelectorAll('[data-event]')) n.classList.toggle('sel', n.dataset.event === v.sel.event);
    }
    for (const pane of [v.paneA, v.paneB, v.paneC]) {
      if (from && pane.contains(from)) continue;
      const target = (v.sel.event && pane.querySelector(`[data-event="${CSS.escape(v.sel.event)}"]`)) || (v.sel.turn && pane.querySelector(`[data-turn="${CSS.escape(v.sel.turn)}"]`));
      if (target && pane.isConnected && (from || !v.quiet)) target.scrollIntoView({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'});
    }
    const c = v.convOf({turn_id: v.sel.turn});
    if (from && onSelect && c) onSelect(c, v.sel.turn, v.sel.event);
  };

  // The feed, PiP and Messenger render the same recorded roulette DOM.
  const tileEngine=window.PineSystem3MessageTile;
  const tileCore=tileEngine.createRenderer({make:(tag,cls,text)=>el(tag,{class:cls,text}),
    wireEntry:(element,rows,index)=>{
      const row=rows[index];element.setAttribute('role','button');element.tabIndex=0;if(row.event)element.dataset.event=row.event;
      const open=e=>{e.stopPropagation();const article=element.closest('.s3-msg'),state=article?.s3Tile;
        const conv=state?.conv,t=state?.turn;if(!conv||!t)return;
        const ev=(conv.decision_events||[]).find(x=>x.event_id===row.event);
        v.select(t.turn_id,row.event||'',element);
        if(ev)openDecision(conv,ev,t,v.api);else article?.querySelector(':scope > .who > .s3-drop-btn')?.click();
      };
      element.addEventListener('click',open);element.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open(e);}});
    }});
  const tileRowKey=row=>tileEngine.rowKey(row);
  v.tileRows=(node,conv,t,part)=>{
    const own=node.s3||{},line=own.line,obs=own.obs;
    if(line){const roll=line.sfx_roll||{};if(roll.category||roll.clip)return [tileEngine.countedRow('SFX','SFX',roll.category||roll.clip,roll.category?roll.clip:null)];
      const pid=String(line.line_id||'').replace(/-punct-\d+$/,'');const parent=(conv.lines||[]).find(x=>x.line_id===pid&&x.turn_id);
      const turn=parent?(conv.turns||[]).find(x=>x.turn_id===parent.turn_id)||t:t;
      return tileEngine.decisionRows(turnEvents(conv,turn).filter(ev=>ev.family==='SFX'));}
    if(obs&&node.classList.contains('s3-sfxguy-line'))return (obs.draws||[]).map(d=>tileEngine.countedRow('SFXGUY','LINE',{...d,label:d.label||('the '+(d.pool||'')+' pool')}));
    if(obs)return [];
    return part&&part.index>0?[]:tileEngine.decisionRows(turnEvents(conv,t));
  };
  v.tileAttach=(node,conv,t,{part=null,stage=node.dataset.stage||'written'}={})=>{
    if(node.s3Tile)return node;const body=[...node.children].find(x=>x.classList.contains('s3-bubble'));if(!body)return node;
    const rows=v.tileRows(node,conv,t,part),sheet=tileCore.sheet({},rows,Math.max(6000,rows.length*tileEngine.BUILD.per));
    sheet.keep=true;sheet.box.classList.add('sp-rr-keep');body.prepend(sheet.box);node.classList.add('s3-system3-tile');
    const words=body.querySelector('.s3-words'),text=words?.textContent||'';
    node.s3Tile={conv,turn:t,part,rows,sheet,core:tileCore,text,stage,seq:null};
    if(stage==='upcoming')tileCore.at(sheet,0,false);else{tileCore.results(sheet);sheet.elapsed=sheet.rolled;}
    if(words)words.hidden=stage==='upcoming'||!text;
    node.roll=()=>v.tileRoll(node);return node;
  };
  v.tileStage=(node,stage)=>{
    const state=node?.s3Tile;if(!state)return node;state.stage=stage;node.dataset.stage=stage;
    for(const [cls,on]of [['s3-upcoming',stage==='upcoming'],['live',stage==='live'],['past',stage==='past'],['skipped',stage==='skipped']])node.classList.toggle(cls,on);
    const body=node.querySelector(':scope > .s3-bubble'),words=body?.querySelector('.s3-words');
    if(words){words.hidden=stage==='upcoming'||!state.text;
      const count=stage==='live'?Math.max(0,v.revealed(v.itemKey(node),state.text.length)):state.text.length;
      const text=stage==='upcoming'?'':state.text.slice(0,count);if((!state.seq||stage!=='live')&&words.textContent!==text)words.textContent=text;}
    const payload=body?.querySelector('.s3-tile-payload');if(payload)payload.hidden=stage==='upcoming';
    if(v.dressItem)v.dressItem(node,v.itemKey(node),stage);return node;
  };
  v.syncTile=(node,fresh)=>{
    const state=node?.s3Tile,next=fresh?.s3Tile;if(!state||!next)return false;
    const known=new Set(state.rows.map(tileRowKey)),added=[];for(const row of next.rows){const key=tileRowKey(row);if(!known.has(key)){known.add(key);added.push(row);}}
    if(added.length){tileCore.append(state.sheet,added,{},Math.max(6000,added.length*tileEngine.BUILD.per));state.rows.push(...added);if(!state.seq&&next.stage!=='upcoming')v.tileRoll(node,{resume:true});}
    state.conv=next.conv;state.turn=next.turn;state.part=next.part;state.text=next.text;if(fresh.s3)node.s3=fresh.s3;
    for(const table of state.sheet.tables)for(const step of [table.cat,table.sub])if(step)step.el.dataset.turn=next.turn.turn_id;
    const oldWho=node.querySelector(':scope > .who > b'),newWho=fresh.querySelector(':scope > .who > b');if(oldWho&&newWho&&oldWho.textContent!==newWho.textContent)oldWho.textContent=newWho.textContent;
    const oldDir=node.querySelector(':scope > .s3-bubble > .dir'),newDir=fresh.querySelector(':scope > .s3-bubble > .dir');
    if(oldDir&&newDir){const text=[...newDir.childNodes].filter(child=>child.nodeType===3).map(child=>child.data).join('');let words=[...oldDir.childNodes].find(child=>child.nodeType===3);if(!words){words=document.createTextNode('');oldDir.prepend(words);}if(words.data!==text)words.data=text;}
    const reacts=node.querySelector(':scope > .s3-reacts'),newReacts=fresh.querySelector(':scope > .s3-reacts');
    if(reacts&&newReacts){const events=new Set([...reacts.children].map(child=>child.dataset.event).filter(Boolean));for(const child of [...newReacts.children])if(child.dataset.event&&!events.has(child.dataset.event)){events.add(child.dataset.event);reacts.insertBefore(child,reacts.querySelector('.s3-assemble'));}}
    const body=node.querySelector(':scope > .s3-bubble'),newBody=fresh.querySelector(':scope > .s3-bubble');
    if(body&&newBody){
      if(next.text&&!body.querySelector('.s3-words'))(body.querySelector('.s3-tile-payload')||body).append(el('span','s3-words'));
      const oldMedia=body.querySelector('.s3-sting-media'),newMedia=newBody.querySelector('.s3-sting-media');
      if(!oldMedia&&newMedia)(body.querySelector('.s3-tile-payload')||body).append(newMedia);
      else if(newMedia?.s3unload)newMedia.s3unload();
      for(const cls of ['s3-clip-name','s3-sfx-why']){const incoming=newBody.querySelector('.'+cls),present=body.querySelector('.'+cls);if(incoming){if(present)present.textContent=incoming.textContent;else(body.querySelector('.s3-tile-payload')||body).append(incoming);}}
    }
    if(node.dataset.replaying)state.stage=next.stage;else v.tileStage(node,next.stage);return true;
  };
  v.tileRoll=(node,{resume=false}={})=>{
    const state=node.s3Tile;if(!state)return landInOrder([]);state.seq?.hurry?.();
    if(!resume)tileCore.reset(state.sheet);
    const from=resume?state.sheet.elapsed:0,t0=performance.now(),speed=Math.max(.25,Number(v.speed)||1);
    let raf=0,over=false,resolve;const done=new Promise(r=>{resolve=r;});
    const settle=()=>{if(over)return;over=true;if(raf)cancelAnimationFrame(raf);raf=0;tileCore.results(state.sheet);state.sheet.elapsed=Math.max(state.sheet.elapsed,state.sheet.rolled);if(state.seq===done)state.seq=null;resolve();};
    const frame=now=>{raf=0;if(over)return;if(!v.alive||!node.isConnected){settle();return;}
      const at=from+(now-t0)*speed;tileCore.at(state.sheet,at,reduced());if(v.onTileFrame)v.onTileFrame(node);
      if(reduced()||at>=state.sheet.total)settle();else raf=requestAnimationFrame(frame);};
    done.count=state.rows.length;done.total=Math.max(0,state.sheet.total-from)/speed;done.hurry=settle;done.cancel=settle;state.seq=done;
    tileCore.at(state.sheet,from,reduced());raf=requestAnimationFrame(frame);return done;
  };

  /* A. conversation view */
  v.bubble = (t, opts = {}) => {
    const conv = opts.conv || v.convOf(t);
    /* [s3-imsg] one run of the turn's lines, when a sting airs between them (v.partsOf) */
    const part = opts.part || null;
    const key = part ? part.key : t.turn_id;
    const later = !!(part && part.index > 0);
    /* [s3-messenger] not on air yet: its roulette, never its words */
    const stg = opts.forceStage || (opts.slot ? '' : v.stageOf(key, conv, t));
    const st = v.turnStatus(t, conv);
    const perf = t.performance || {};
    const whole = part ? part.text : v.wordsOf(t, conv);
    /* on air: only as many of its words as the audio has reached */
    const text = stg === 'upcoming' ? '' : stg === 'live' ? whole.slice(0, Math.max(0, v.revealed(key, whole.length))) : whole;
    const planned = !whole;
    const directions = (t.directions || []).map(d => d.text).join('; ');
    const plan = `${perf.emotion ? perf.emotion + ' · ' : ''}${directions || t.step_label}`;
    const body = el('div', {class: 's3-bubble'},el('span', {class:'s3-words',text}),
      el('span', {class:'dir',text:(conv.mode === 'shadow' ? 'System 3 would have directed: ' : '')+plan}));
    const reacts = el('div', 's3-reacts', ...(later ? [] : turnEvents(conv, t)).map(ev => {
      const chip = chipOf(ev, conv);
      return el('span', {class: 's3-diamond' + (chip.miss ? ' miss' : ''), style: `--fam:${FAM[ev.family]}`, 'data-event': ev.event_id, 'data-turn': t.turn_id,
        title: chip.title, text: chip.text,
        role: 'button', tabindex: '0',
        onclick: e => { e.stopPropagation(); v.select(t.turn_id, ev.event_id, e.currentTarget); openDecision(conv, ev, t, v.api); },
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }});
    }));
    if (!opts.slot) reacts.append(assembleBtn(v));                      /* [s3-imsg] on every message */
    const sb = (t.speakerbox || []).filter(s => s.mode !== 'NONE');
    const chips = later ? null : el('div', 's3-chips',
      el('span', {text: t.phase}), perf.emotion ? el('span', {text: `${perf.emotion} ${num(perf.intensity)}`}) : null,
      sb.length ? el('span', {text: 'speakerbox ' + sb.map(s => s.mode.toLowerCase()).join(', ')}) : null,
      t.sfx && t.sfx.play ? el('span', {text: 'SFX ' + t.sfx.placement}) : null,
      t.sfxguy && t.sfxguy.speak ? el('span', {text: castName('sfx') + ': ' + (t.sfxguy.kind || 'speaks')})   /* [cast-names] */ : null,
      bankTags(conv, t),                                   /* [s3-banks-roll] */
      el('span', {text: '~' + num(t.estimated_seconds, 0) + 's'}), el('span', {class: st.cls, text: st.word}));
    /* A line a speaker-box passage went into opens, in place, into its
       parts: the passages above and below it and the setup row. A line
       whose roll lost opens to its odds and the dials behind them. */
    const composed = !opts.slot && !later && canCompose(conv, t);
    const passages = composed && (sbWon(t) || !!dealtBy(conv, scriptIndexOf(conv, t)) || opensOnSeed(conv, t));
    const open = composed && v.open.has(t.turn_id);
    if (composed) {
      chips.append(el('button', {type: 'button', class: 's3-sbopen', 'aria-expanded': String(open),
        text: open ? (passages ? 'close the passages' : 'close the odds') : (passages ? 'open the passages' : 'see the speaker-box odds'),
        onclick: e => { e.stopPropagation(); v.toggle(t, node); }}));
    }
    const cutWhy = st.air && (st.air.cut_why || (st.air.aired === 'withdrawn' ? st.air.withdrawn_why : ''));
    /* [s3-messenger] struck out only on the air's own word; aired, it is past */
    const skipTitle = stg === 'skipped' ? 'not heard: ' + (offWhy(conv, v.linesOf(key, conv, t)) || 'withdrawn or cut before air') : null;
    const node = el('article', {class: `s3-msg ${SIDE[t.speaker] || 'left'} seat-${t.speaker}${opts.slot ? ' building' : ''}` +
      `${composed ? (passages ? ' has-sb' : ' sb-miss') : ''}${open ? ' open' : ''}${later ? ' s3-part' : ''}` +
      `${stg === 'live' ? ' live' : stg === 'past' ? ' past' : stg === 'skipped' ? ' skipped' : ''}`,
      'data-turn': t.turn_id, 'data-key': opts.slot ? null : key, 'data-stage': stg || null, 'data-part': part ? String(part.index) : null,
      title: skipTitle || (v.tapAssembles && !opts.slot ? 'tap to see it come together again; tap and hold for what to do with it'
        : composed ? (open ? 'tap to close' : passages ? 'tap to open this line with its speaker-box passages'
          : 'tap to see why no speaker-box passage won this line, and turn the odds') : null),
      onclick: e => {
        v.select(t.turn_id, '', e.currentTarget);
        const pick = window.getSelection ? window.getSelection() : null;
        if (pick && !pick.isCollapsed && node.contains(pick.anchorNode)) return;   /* selecting words, not tapping */
        /* [s3-imsg] the Messenger: a tap plays the message coming together (its passages open by their button) */
        if (v.tapAssembles && !opts.slot) { if (!e.target.closest(TAP_CONTROLS)) v.tapAssembles(node, e); return; }
        if (!composed || e.target.closest(KEEP_OPEN)) return;
        v.toggle(t, node);
      }},
      el('div', 'who', el('b', {text: t.name || t.speaker}),
        msgCodeOf(v.linesOf(key, conv, t)),   /* [s3-account-code] the line's code, as every view shows it */
        el('span', {text: `${t.step_label} · turn ${t.index + 1}` + (part ? ` · ${part.index + 1} of ${part.of}` : '')})),
      opts.slot || body, opts.slot ? null : reacts, opts.slot ? null : chips,!opts.slot&&open?composeLine(conv,t,v.api):null,
      !opts.slot && cutWhy ? cutNote(cutWhy, v) : null);
    node.fill = () => { node.classList.remove('building'); fill(node, node.firstChild, body, reacts, chips); };
    if (!opts.slot) esDress(node, t);                                    /* [s3-msgdrop] the ES emoji, bottom right */
    if (!opts.slot && !later) v.dropDress(node, t.turn_id, 'full|' + turnLines(conv, t).map(l => l.line_id).join(','), c => dropTurnPanel(v,node.s3Tile?.conv||conv,node.s3Tile?.turn||t,c,false));   /* [s3-msgdrop] */
    if (!opts.slot) { v.tileAttach(node,conv,t,{part,stage:stg||'written'});node.s3Tile.text=whole;v.tileStage(node,stg||'written'); }
    if (stg && v.dressItem) v.dressItem(node, key, stg);
    return node;
  };

  /* [s3-imsg] a later run of a turn before the air reaches it: no dice of its
     own (they were rolled for the turn, on its first run) - a slim card that
     waits its turn, never its words */
  v.partCard = (t,conv,part) => v.bubble(t,{conv,part,forceStage:'upcoming'});

  /* [s3-messenger] THE ROULETTE CARD: a turn not yet on air, as the rolls
     that made it - who speaks, the step, each recorded decision as its die
     and what it landed on - and whether its words are written yet. The
     words are not in it anywhere, not even in a title. On air the card pops,
     its dice roll, and it turns into the written message. */
  v.card = (t,conv) => v.bubble(t,{conv,forceStage:'upcoming'});

  /* [s3-messenger] A STING ON THE LEDGER, in the correspondence where it airs.
     Before air: its two dice, the category and then the clip. On air they
     roll in that order and the clip's poster pops in. What the station
     played for it (the SFX observation it pairs with) rides along: the
     menu, the why, and the clip card when no poster came with the row. */
  v.sfxNode = (conv, t, line, pair) => {
    const key = 'sfx:' + line.line_id;
    const stg = v.stageOf(key, conv, t);
    const upcoming = stg === 'upcoming';
    const roll = line.sfx_roll && typeof line.sfx_roll === 'object' ? line.sfx_roll : {};
    const faces = [];
    const dice = [['category', roll.category], ['clip', roll.clip]].filter(([, r]) => r && typeof r === 'object').map(([name, r]) => {
      const face = die(r.dice == null || r.dice === '' ? null : Number(r.dice));
      faces.push(face);
      return el('span', {class: 's3-rl-chip', style: '--fam:var(--sfx)'}, face, el('b', {text: name}),
        r.label ? el('span', {class: 's3-rl-pick', text: String(r.label).slice(0, 48)}) : null,
        r.of ? el('span', {class: 's3-muted', text: 'of ' + r.of}) : null);
    });
    /* [s3-inject][gap1] A clip with no roll of its own: a board clip welded
       as punctuation (line id "<parent>-punct-N" - app.py's _sfx_single_clip
       stamp) or one played without a stamp. Its dice EXIST - on the turn it
       punctuates - so the card borrows that turn's SFX-family rolls and says
       where they live, never a dice-less shrug. */
    let parentNote = null;
    if (!dice.length) {
      const pid = String(line.line_id || '').replace(/-punct-\d+$/, '');
      let pt = t;
      if (pid && pid !== String(line.line_id || '')) {
        const pl = (conv.lines || []).find(x => x && x.line_id === pid && x.turn_id);
        if (pl) pt = (conv.turns || []).find(x => x.turn_id === pl.turn_id) || t;
      }
      const pevs = turnEvents(conv, pt).filter(e => e.family === 'SFX' && e.kind !== 'observation' && !e.stage);
      for (const ev of pevs) {
        const ln = eventLine(ev, conv);
        const face = die(ln.dice);
        faces.push(face);
        dice.push(el('span', {class: 's3-rl-chip', style: '--fam:var(--sfx)', role: 'button', tabindex: '0',
          title: "the punctuated turn's SFX roll - tap for how it was decided",
          onclick: e => { e.stopPropagation(); openDecision(conv, ev, pt, v.api); },
          onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
          face, el('b', {text: 'SFX'}),
          el('span', {class: 's3-rl-pick', text: String(ln.text || '').slice(0, 48)})));
      }
      if (pevs.length) parentNote = el('div', {class: 's3-sfx-why s3-sfx-parent',
        text: 'no roll of its own - the dice live on the turn it punctuates (turn ' + (pt.index + 1) + ')'});
    }
    const name = boardName(line);
    const played = pair && pair.played;
    const quips = pair ? ((pair.obs.sfx_guy || []).map(q => q && q.text).filter(Boolean)) : [];
    const why = played && played.why ? `matched on "${played.why}"` : '';
    /* [s3-imsg] its clip, in the message: the frame until it plays, the clip muted once through; an
       audio clip's spectrogram with its playhead (stingMedia) */
    const info = stingInfo(line, played);
    const media = (info.kind || info.sid) ? stingMedia(v, info, {live: stg === 'live'}) : null;
    /* the sheet's heading, and the station's hold sheet's: one line, not the card's text run together */
    const clipName = String((roll.clip && roll.clip.label) || name || (played && played.clip) || '');
    const said = [`Sting after turn ${t.index + 1}`, roll.category && roll.category.label ? String(roll.category.label) : '',
      clipName ? `clip '${clipName}'` : ''].filter(Boolean).join(' · ');
    const rlDice = null;
    const node = el('article', {class: `s3-msg left s3-sfxguy s3-sfxnode${upcoming ? ' s3-upcoming' : ''}` +
        `${stg === 'live' ? ' live' : stg === 'past' ? ' past' : stg === 'skipped' ? ' skipped' : ''}`,
        'data-turn': t.turn_id, 'data-line': line.line_id, 'data-key': key, 'data-stage': stg, 'data-said': said,
        title: stg === 'skipped' ? 'not heard: ' + (offWhy(conv, [line]) || 'withdrawn or cut before air')
          : v.tapAssembles ? 'tap to see it come together again; tap and hold for what to do with it' : null},
      el('div', 'who', sfxAvatar(), el('b', {text: 'SFX'}), el('span', {text: `a sting after turn ${t.index + 1}`})),
      el('div','s3-bubble s3-sfx-bubble',parentNote,el('div',{class:'s3-tile-payload',hidden:upcoming},
        media || (played ? sfxClipCard(played,v) : null),name?el('div',{class:'s3-clip-name',text:name}):null,
        quips.length?el('div',{class:'s3-words',text:quips.join(' ')}):null,why?el('div',{class:'s3-sfx-why',text:why}):null)));
    /* [s3-imsg] the split play button at the end of its dice row (its own row with no dice) */
    if (rlDice) rlDice.append(assembleBtn(v)); else node.append(el('div', 's3-reacts', assembleBtn(v)));
    node.s3 = {conv, t, obs: pair ? pair.obs : null, played: played || null, line};
    v.dropDress(node, key, upcoming ? 'card' : 'full' + (pair ? '|played' : ''), () => dropStingPanel(v, conv, t, line, pair, upcoming));   /* [s3-msgdrop] */
    node.addEventListener('click', e => {
      if (v.tapAssembles) {                     /* [s3-imsg] the Messenger: a tap - on the clip too - plays it coming together */
        if (e.target.closest(TAP_CONTROLS)) return;
        e.stopPropagation();
        v.tapAssembles(node, e);
        return;
      }
      if (e.target.closest(KEEP_OPEN + ', .s3-vthumb, .s3-aplayer')) return;
      e.stopPropagation();
      if (pair && !upcoming) openSfxMenu(conv, t, pair.obs, played, v, node, e);
    });
    /* the category die, then the clip die - [s3-imsg] landing one after the
       other like a card's, then the poster pops in */
    v.tileAttach(node,conv,t,{stage:stg});v.tileStage(node,stg);
    if (v.dressItem) v.dressItem(node, key, stg);
    return node;
  };
  /* Open or close one line where it stands, keeping what the host painted on it. */
  v.toggle=(t,node)=>{
    const conv=node.s3Tile?.conv||v.convOf(t),turn=node.s3Tile?.turn||t;
    if(v.open.has(t.turn_id))v.open.delete(t.turn_id);else v.open.add(t.turn_id);
    const open=v.open.has(t.turn_id);node.classList.toggle('open',open);
    const panel=node.querySelector(':scope > .s3-compose');if(open&&!panel)node.append(composeLine(conv,turn,v.api));else if(!open&&panel)panel.remove();
    const button=node.querySelector('.s3-sbopen');if(button){button.setAttribute('aria-expanded',String(open));button.textContent=open?'close the passages':sbWon(turn)?'open the passages':'see the speaker-box odds';}
  };
  v.keepPaint = (from, to) => {
    /* [s3-messenger] in a Messenger the builder draws the stage (past, skipped); only the host's marks carry over */
    for (const c of v.sequenced ? ['sel', 'onair'] : ['sel', 'onair', 'past', 'skipped']) if (from.classList.contains(c)) to.classList.add(c);
    if (!v.sequenced && from.classList.contains('skipped')) to.title = from.title;
  };

  /* ---- [s3-imsg] ONE ASSEMBLY, EVERY ROAD ------------------------------------
     "Whenever I click on the play button for a message, I want to see the
      simple play of how the message was assembled. Like whenever a new
      message appears." - "Do not bring up this radial whenever I tap on
      videos in the messenger view. Instead animate the message coming
      together." (operator, 2026-09-28)
     A message comes together one way, whoever asks: it stands as its
     roulette card, its dice land one after another (an ES roll: its
     category, then its item under it), everything holds still DICE_HOLD_MS,
     and it becomes its message - the words typing out, or its clip playing.
     The Messenger's live arrival runs it on the air's clock (v.rollIn); a
     tap on a message or on its clip, and the play half of its split button,
     run it again from the recorded rolls (v.assemble); the arrow half runs
     the long version, every decision as its own card (v.assembleExtended).
     A replay is drawn where the message stands and in the room it already
     has (its height held), so nothing around it moves, the page is not
     scrolled and the sync is not touched; a card still to come lands its
     dice and stays a card (never its words); the message on air is left to
     its own reveal (the host's assembleGate). */
  v.replayAs = new Map();          /* key -> the stage a message is drawn in while it comes together again */
  v.assembling = new Set();        /* keys coming together again right now */
  v.extending = 0;                 /* long versions running: the host keeps its view where it is */
  v.assembleGate = null;           /* host: (key, node) -> false to refuse */
  v.onPut = null;                  /* host: (key, node) - a node now stands in an item's place */
  v.onAssembled = null;            /* host: (key, node) - done */
  v.tapAssembles = null;           /* host: set, a tap on a message plays it coming together */
  const REPLAY_TYPE_MS = [700, 2600];   /* the words again: ~16 ms a character, inside this */
  /* the key of what hangs off a turn - the SFX Guy's line ('guy:'), a clip he played ('clip:') */
  v.obsKey = (kind, obs, t, played) => kind + ':' + ((obs && (obs.cursor || obs.at)) || (((t || {}).turn_id || '') + ':' + ((played || {}).clip || '')));
  v.itemKey = n => {
    if (!n || !n.dataset) return '';
    if (n.dataset.item) return n.dataset.item;
    if (n.dataset.key) return n.dataset.key;
    const s = n.s3;
    return s && s.obs ? v.obsKey(n.classList.contains('s3-sfxguy-line') ? 'guy' : 'clip', s.obs, s.t, s.played) : '';
  };
  /* the item drawn again as it stands now - as its card while v.replayAs says so */
  v.redrawItem = (key, node) => {
    const s = node && node.s3;
    const turnId = (node && node.dataset && node.dataset.turn) || (s && s.t && s.t.turn_id) || '';
    const conv = v.convOf({turn_id: turnId});
    const t = conv && (conv.turns || []).find(x => x.turn_id === turnId);
    if (!conv || !t) return null;
    if (key.startsWith('sfx:')) {
      const id = key.slice(4);
      const line = (conv.lines || []).find(l => l.line_id === id) || (s && s.line);
      return line ? v.sfxNode(conv, t, line, s && s.obs ? {obs: s.obs, played: s.played} : null) : null;
    }
    if (key.startsWith('guy:')) return s && s.obs ? sfxGuyLineEntry(conv, t, s.obs, v) : null;
    if (key.startsWith('clip:')) return s && s.obs ? sfxEntry(conv, t, s.obs, v) : null;
    if (key !== t.turn_id && !key.startsWith('part:')) return null;
    return v.bubble(t, {conv, part: (v.partsOf(conv, t) || []).find(p => p.key === key) || null});
  };
  /* one node put in another's place: the host's marks carried, a clip playing in the old one let
     go, the room it had held (`h`) */
  v.putItem = (key, old, fresh, h) => {
    v.keepPaint(old, fresh);
    if (old.dataset.item) fresh.dataset.item = old.dataset.item;
    if (old.style.minHeight) fresh.style.minHeight = old.style.minHeight;   /* the host's "never shorter" stays */
    for (const m of old.querySelectorAll('.s3-sting-media')) if (m.s3unload) m.s3unload();
    fresh.dataset.replaying = '1';
    fresh.classList.add('s3-assembling');
    if (h > 0) { fresh.style.height = h + 'px'; fresh.style.overflow = 'hidden'; }
    old.replaceWith(fresh);
    if (typeof v.onPut === 'function') v.onPut(key, fresh);
    return fresh;
  };
  const settleItem = n => {
    if (!n) return;
    n.style.height = ''; n.style.overflow = '';
    delete n.dataset.replaying;
    n.classList.remove('s3-assembling', 's3-extending');
  };
  /* Replay the same shared sheet, category followed by its indented sub-entry,
     leaving every completed row in place when words start. */
  v.rollIn = (card,{hold=false}={}) => {
    const seq=card.s3Tile?v.tileRoll(card):typeof card.roll==='function'?card.roll():landInOrder([]);
    return {seq,done:seq};
  };

  /* the message itself, once its dice are down: its words typed out again (fast - a long line in
     two or three seconds), its clip played from the start */
  v.messageIn = async (node) => {
    if (!node) return;
    const media = node.querySelector('.s3-sting-media');
    if (media && typeof media.play === 'function') media.play({from: 0});
    const words=node.dataset.stage==='live'?null:node.querySelector(':scope > .s3-bubble .s3-words');
    if(!words)return;
    const text=node.s3Tile?.text??words.textContent;
    if(words)words.hidden=!text;
    if (!text || reduced()) return;
    await typewriter(words,text,Math.max(REPLAY_TYPE_MS[0],Math.min(REPLAY_TYPE_MS[1],text.length*16)),{current:()=>node.s3Tile?.text??text,paused:()=>!!node.s3Tile?.seq,onFrame:()=>v.onTileFrame?.(node)});
  };
  v.assemble = async (node,{build=false}={}) => {
    const key=v.itemKey(node);if(!node?.isConnected||!key||v.assembling.has(key))return false;
    if(!build&&typeof v.assembleGate==='function'&&!v.assembleGate(key,node))return false;
    v.assembling.add(key);const stage=node.dataset.stage||'written';
    try{node.dataset.replaying='1';node.classList.add('s3-assembling');const words=node.querySelector(':scope > .s3-bubble .s3-words');if(words){words.textContent='';words.hidden=true;}
      await v.rollIn(node,{hold:true}).done;if(!node.isConnected)return false;
      const currentStage=node.s3Tile?.stage||stage;v.tileStage(node,currentStage);if(currentStage!=='upcoming')await v.messageIn(node);return true;
    }finally{v.assembling.delete(key);if(node.s3Tile)v.tileStage(node,node.s3Tile.stage);v.onTileFrame?.(node);settleItem(node);if(typeof v.onAssembled==='function')v.onAssembled(key,node);}
  };

  /* [msgview] A NEW MESSAGE, IN AIR ORDER - the one entry the [msgorder]
     hook calls (key, node). The item on air is left to its own reveal
     (startReveal: dice, Rolodex, sub-result, then its words on the audio's
     clock); any other newly arrived message comes together ONCE, the
     assembly its play button runs (card, the dice stopping one after another,
     the Rolodex, the sub-result, the words typed). A key plays once: history
     drawn again on a scroll or a repaint is never replayed. */
  v.arrivedSeen = new Set();
  v.arrived = (key, node) => {
    key = String(key || v.itemKey(node) || '');
    if (!key || !node || !node.isConnected || v.arrivedSeen.has(key)) return Promise.resolve(false);
    v.arrivedSeen.add(key);
    if (v.arrivedSeen.size > 800) v.arrivedSeen.delete(v.arrivedSeen.values().next().value);
    const stg = node.dataset ? node.dataset.stage : '';
    if (stg === 'live' || stg === 'upcoming' || (node.dataset && node.dataset.replaying) || reduced()) return Promise.resolve(false);
    return v.assemble(node);
  };
  /* the recorded decisions behind an item, in the order they were drawn, as the long version's cards */
  v.decisionsOf = (key, node) => {
    const s = node && node.s3;
    const turnId = (node && node.dataset && node.dataset.turn) || (s && s.t && s.t.turn_id) || '';
    const conv = v.convOf({turn_id: turnId});
    const t = conv && (conv.turns || []).find(x => x.turn_id === turnId);
    if (!conv || !t) return [];
    const byId = id => (id ? (conv.decision_events || []).find(e => e.event_id === id) : null);
    const card = ev => () => replayCard(ev, conv, t, v.api);
    if (key.startsWith('sfx:')) {
      const line = (conv.lines || []).find(l => 'sfx:' + l.line_id === key) || (s && s.line) || {};
      const roll = line.sfx_roll && typeof line.sfx_roll === 'object' ? line.sfx_roll : {};
      const node0 = byId((t.sfx || {}).event_id);
      return [node0 ? card(node0) : null,
        ...[['which category', roll.category], ['which clip', roll.clip]].filter(([, r]) => r && typeof r === 'object')
          .map(([name, r]) => () => pickCard('SFX', name, r))].filter(Boolean);
    }
    if (key.startsWith('guy:')) {
      const g = byId((t.sfxguy || {}).event_id);
      return [g ? card(g) : null, ...((s && s.obs && s.obs.draws) || []).map(d => () => pickCard('SFXGUY', 'which line',
        {dice: d.dice, label: `the ${d.pool || ''} pool`, index: d.index, of: d.of, u: d.u}))].filter(Boolean);
    }
    if (key.startsWith('clip:')) { const ev = byId((t.sfx || {}).event_id); return ev ? [card(ev)] : []; }
    return turnEvents(conv, t).map(card);
  };
  /* The extended replay uses the same retained category/subcategory listing
     and words as the compact replay; completed rows keep their geometry. */
  v.assembleExtended = async node => {
    v.extending+=1;try{return await v.assemble(node);}finally{v.extending=Math.max(0,v.extending-1);}
  };

  /* SFX Guy in the correspondence: the clip he scheduled for this line (the
     plan's own roll, before or after it) and, once the line aired, what the
     station actually played - his entry, the clip, and why it was chosen. */
  v.sfxRows = (conv, t) => {
    const before = [], after = [];
    const plan = t.sfx || {};
    const ev = plan.event_id ? (conv.decision_events || []).find(e => e.event_id === plan.event_id) : null;
    const idx = scriptIndexOf(conv, t);
    const played = idx == null ? [] : (conv.observations_air || []).filter(o => o.family === 'SFX' && o.turn_index === idx);
    if (plan.play && ev) (plan.placement === 'before' ? before : after).push(sfxPlanRow(conv, t, ev, played.length > 0, v));
    /* [s3-messenger] a Messenger draws each sting on the ledger around this
       turn as its own node in the sequence, paired in order with the clips
       the station reported playing after the turn; a clip with no row of
       its own keeps its entry as before */
    const slot = v.sequenced ? boardPlan(conv).get(t.turn_id) : null;
    const paired = new Set();
    if (slot) {
      const clips = played.flatMap(o => (o.played || []).map(p => ({obs: o, played: p})));
      for (const l of slot.before) before.push(v.sfxNode(conv, t, l, null));
      slot.after.forEach((l, i) => { const p = clips[i] || null; if (p) paired.add(p.obs); after.push(v.sfxNode(conv, t, l, p)); });
    }
    for (const o of played) if (!paired.has(o)) after.push(sfxEntry(conv, t, o, v));
    /* [s3-roads] and his LINE, drawn at air from his node on this turn */
    const said = idx == null ? [] : (conv.observations_air || []).filter(o => o.family === 'SFXGUY' && o.turn_index === idx);
    for (const o of said) after.push(sfxGuyLineEntry(conv, t, o, v));
    return {before, after};
  };
  v.turnNodes = (conv, t) => {
    const s = v.sfxRows(conv, t);
    const parts = v.partsOf(conv, t);
    if (!parts) return [...s.before, v.bubble(t, {conv}), ...s.after];
    /* [s3-imsg] each run of the turn, and the stings that air between them where they air */
    const out = [...s.before], rest = s.after.slice();
    parts.forEach((p, i) => {
      for (let k = 0; i && k < rest.length;) {
        const l = rest[k].s3 && rest[k].s3.line;
        if (l && byLedger(l, p.lines[0]) < 0) out.push(rest.splice(k, 1)[0]); else k += 1;
      }
      out.push(v.bubble(t, {conv, part: p}));
    });
    return [...out, ...rest];
  };
  v.roundChat = (conv) => el('div', 's3-chat', ...v.turnsInOrder(conv).flatMap(t => v.turnNodes(conv, t)));   /* [s3-still] newest first when asked */

  const conversationItemKey=node=>v.itemKey(node)||(node.dataset.event?'event:'+node.dataset.event:'');
  v.syncConversationChat=(chat,conv)=>{
    const old=new Map([...chat.children].map(node=>[conversationItemKey(node),node]).filter(([key])=>key));
    const next=v.turnsInOrder(conv).flatMap(t=>v.turnNodes(conv,t)),retained=[];
    for(const fresh of next){const key=conversationItemKey(fresh),was=key?old.get(key):null;
      if(was?.s3Tile&&fresh.s3Tile){
        v.syncTile(was,fresh);retained.push(was);
      }else retained.push(fresh);
    }
    const keep=new Set(retained);for(const node of [...chat.children])if(!keep.has(node))node.remove();
    let before=chat.firstChild;for(const node of retained){if(node===before)before=before.nextSibling;else chat.insertBefore(node,before);}
    return retained;
  };
  v.paintConversation=()=>{
    const conv=v.conv,cid=String(conv?.identity?.conversation_id||'');
    let chat=v.paneA.querySelector(':scope > .s3-chat');
    if(chat&&cid&&v.paneA.dataset.conversation===cid){
      v.syncConversationChat(chat,conv);
      const count=v.paneA.querySelector(':scope > h2 > span');if(count)count.textContent=conv.turns.length+' turns';
      return chat;
    }
    chat=conv?v.roundChat(conv):el('div','s3-chat');v.paneA.dataset.conversation=cid;
    fill(v.paneA,el('h2',null,'Conversation',el('span',{class:'s3-muted',text:conv?conv.turns.length+' turns':''})),
      conv?.mode==='shadow'?el('p',{class:'s3-muted',text:'Shadow: System 3 planned this round beside the legacy writer and none of its plan reached air. Each bubble shows the words that were written for that seat, with what System 3 would have directed underneath.'}):null,chat);
    return chat;
  };
  /* Replay retained messages in round order: each shared sheet rolls its
     category and sub-entry, then words type below the completed rows.
     latest supplies recorded data that arrives while the round is playing. */
  v.buildRound = async (conv,chat,{base=700/v.speed,live=()=>true,grow=null,latest=null,settled=null,quiet=false,existing=null}={}) => {
    const now=()=>latest?latest()||conv:conv,played=new Set();
    while(true){if(!v.alive||!live())return false;const c=now(),t=(c.turns||[]).find(x=>!played.has(x.turn_id));if(!t)break;played.add(t.turn_id);
      const old=new Map([...(existing?existing():chat.children)].map(node=>[conversationItemKey(node),node]).filter(([key])=>key));
      const made=v.turnNodes(c,t).map(fresh=>{const was=old.get(conversationItemKey(fresh));if(was?.s3Tile&&fresh.s3Tile){v.syncTile(was,fresh);return was;}if(was&&!fresh.s3Tile)was.replaceWith(fresh);return fresh;});
      for(const node of made)if(!node.parentNode)chat.append(node);if(grow)grow(made[made.length-1]);
      if(!quiet)for(const node of made){if(node.classList.contains('s3-msg')&&node.dataset.stage!=='live')await v.assemble(node,{build:true});if(grow)grow(node);}
      if(settled)settled(c,t);
    }return true;
  };

  /* Replay the existing tile and its shared reels without replacing its body. */
  v.rebuildTurn = async (node,conv,t,base=700/v.speed) => {await v.assemble(node);return node;};

  /* One message replayed where it stands: each decision's roulette, dice
     and Rolodex with its arithmetic, then the words type back in. */
  /* [s3-imsg] the long version is the split button's arrow now (v.assembleExtended); the hold
     menu's "Replay how this line was decided" runs the same */
  v.replayTurn = (node) => v.assembleExtended(node);

  /* Words arriving for a turn that was only a direction: the direction steps
     down to its small line and the dialogue types itself in. */
  v.arrive = (node,conv,t) => {const fresh=v.bubble(t,{conv});if(v.syncTile(node,fresh)){v.messageIn(node);return node;}v.keepPaint(node,fresh);node.replaceWith(fresh);v.messageIn(fresh);return fresh;};

  /* B. the Rolodex */
  v.eventCard = (ev, turn) => {
    const conv = v.conv;
    const line = eventLine(ev, conv);
    const card = el('div', {class: 's3-ev', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`, 'data-event': ev.event_id || '', 'data-turn': ev.turn_id || (turn && turn.turn_id) || '',
      onclick: e => v.select(ev.turn_id || (turn && turn.turn_id), ev.event_id, e.currentTarget)},
      el('div', 'line', el('span', {class: 'fam', text: ev.family}), (() => { const f = die(line.dice), o = sbOutcome(ev);
        if (o && !o.won) { f.classList.add('miss'); f.title = o.why; } return f; })(), el('span', {class: 'res', text: line.text}),
        btn('How it got here', e => { e.stopPropagation(); openDecision(v.conv, ev, turn || (v.conv.turns || []).find(x => x.turn_id === ev.turn_id), v.api); },
          {class: 's3-explain'})));
    /* [s3-messenger] a pick that landed on a clip (the station's SFX pick) shows the clip's poster on its node */
    const poster = [(ev.meta || {}).poster, (ev.selected || {}).poster].find(p => typeof p === 'string' && p);
    if (poster) card.append(el('img', {class: 's3-evposter', src: stationUrl(poster), alt: 'the clip it picked', loading: 'lazy',
      decoding: 'async', onerror: e => { e.currentTarget.hidden = true; }}));
    /* [s3-live-event] a roll that landed on a station event's row says so */
    const evTag = (ev.meta || {}).event || (ev.selected || {}).event;
    if (evTag) card.append(el('div', {class: 's3-muted', text: 'landed on a station-event row (' + evTag + ') - in the wheel only while that event is on'}));
    const details = el('details', {onclick: e => e.stopPropagation()}, el('summary', {text: 'candidates, weights and state'}));
    details.addEventListener('toggle', () => {
      if (!details.open || details.dataset.filled) return;
      details.dataset.filled = '1';
      for (const st of ev.stages || []) {
        const head = el('div', 's3-muted', `${st.stage}` + (st.draw ? ` · u=${num(st.draw.u, 6)} · d${st.draw.dice} · draw #${st.draw.n} of seed ${st.draw.seed}` : ' · no random number') +
          (st.rule ? ` · ${st.rule}` : '') + (st.total != null ? ` · total weight ${num(st.total, 3)}` : ''));
        const rows = (st.candidates || []).map(c => el('div', {class: 's3-cand' + (c.id === st.selected ? ' hit' : '')},
          el('span', {text: c.label}), el('span', 'bar', el('i', {style: `width:${Math.round((c.p || 0) * 100)}%`})), el('span', {text: pct(c.p)}),
          (c.why || []).length ? el('span', {class: 'why', text: `base ${num(c.base, 2)} → ${num(c.weight, 3)}: ${c.why.join(' · ')}`}) : null));
        details.append(head, el('div', 's3-cands', ...rows));
        if ((st.excluded || []).length) details.append(block(`excluded (${st.excluded.length})`, st.excluded.map(x => `${x.label || x.id}: ${x.why}`).join('\n')));
      }
      if (ev.state_before) details.append(v.delta(ev.state_before, ev.state_after));
      const mat = (conv.material || []).filter(m => m.decided_by === ev.event_id);
      for (const m of mat) {
        const cands = Array.isArray(m.candidates) ? m.candidates : [];
        details.append(el('div', 's3-muted', `document draw: ${m.draw}`),
          cands.length ? el('div', 's3-roll', el('b', {text: 'documents'}), v.drumAnimated(cands.map(c => ({id: c.id, label: `${c.id} (w${c.weight})`})), m.selected.file)) : block('documents', m.candidates),
          el('div', 's3-muted', `landed on ${m.selected.file}` + (m.selected.passage && m.selected.passage.index ? `, passage ${m.selected.passage.index} of ${m.selected.passage.of}` : '') + ` in ${m.ms} ms`));
      }
      details.append(block('raw event', ev));
    });
    card.append(details);
    return card;
  };
  v.drumAnimated = (cands, selected) => { const d = drum(cands, selected); setTimeout(() => d.roll(900 / v.speed), 30); return d; };
  v.delta = (a, b) => {
    if (!b) return el('div', 's3-delta', 'state: ' + json(a));
    const keys = ['tension', 'agreement', 'energy', 'novelty', 'closure_pressure', 'topic_exhaustion'];
    return el('div', 's3-delta', `phase ${a.phase}` + (a.speaker_emotion ? ` · ${a.speaker} ${a.speaker_emotion} → ${b.speaker_emotion}` : '') + ' · ',
      ...keys.map(k => { const d = (b[k] || 0) - (a[k] || 0);
        return el('span', null, `${k} ${num(a[k])}`, Math.abs(d) > 0.0005 ? el('b', {class: d > 0 ? 'up' : 'down', text: ` ${d > 0 ? '+' : ''}${num(d, 3)}`}) : '', '  '); }));
  };

  /* [s3-feedentry] "for each entry show the feed entry for it allowing it to be
     expanded and every roulette roll examined": the message card (speaker, the
     words that aired, its id, and a line of what each roll landed on), open by
     default, holding the turn's Rolodex cards - each with How it got here and
     its candidates, weights and state. */
  v.feedEntry = (t, evs, conv) => {
    let st = {};
    try { st = v.turnStatus(t, conv) || {}; } catch (err) { st = {}; }
    const words = (st.line && st.line.text) || t.text || '';
    const lid = (st.line && st.line.line_id) || '';
    const landed = evs.map(ev => {
      let res = '';
      try { res = eventLine(ev, conv).text; } catch (err) { res = ''; }
      return `${ev.family || '?'} ${res}`.trim();
    }).filter(Boolean);
    const box = el('details', {class: 's3-feedentry', open: true, onclick: e => e.stopPropagation()});
    const sum = el('summary', {class: 's3-fe-sum', title: 'The feed entry for this turn - tap to fold or open its rolls'},
      el('div', 's3-fe-top',
        el('b', {class: 's3-fe-who', text: String(t.name || t.speaker || '').toUpperCase()}),
        el('span', {class: 's3-fe-count', text: `${evs.length} roll${evs.length === 1 ? '' : 's'}`}),
        lid ? el('span', {class: 's3-fe-id', text: '#' + lid.slice(0, 8), title: 'line ' + lid}) : null),
      el('div', {class: 's3-fe-words', text: words || '(no words - ' + (t.status || 'planned') + ')'}),
      landed.length ? el('div', {class: 's3-fe-landed', text: landed.join('  ·  '), title: landed.join('\n')}) : null);
    box.append(sum);
    const body = el('div', 's3-fe-body');
    for (const ev of evs) body.append(v.eventCard(ev, t));
    if (!evs.length) body.append(el('div', 's3-muted', 'No roll was recorded for this turn.'));
    box.append(body);
    return box;
  };

  v.paintRolodex = () => {
    const conv = v.conv;
    const out = [el('h2', null, 'Technical / RNG Rolodex', el('span', {class: 's3-muted', text: conv ? `${(conv.decision_events || []).length} recorded decisions` : ''}))];
    if (!conv) { fill(v.paneB, ...out); return; }
    if (conv.mode === 'shadow') out.push(el('p', {class: 's3-muted', text: 'Shadow: every roll below is recorded, and none of them reached air.'}));
    const pre = (conv.decision_events || []).filter(e => !e.turn_id);
    if (pre.length) out.push(el('div', 's3-turnhead', 'BEFORE THE FIRST TURN'), ...pre.map(e => v.eventCard(e)));
    for (const t of v.turnsInOrder(conv)) {
      out.push(el('div', {class: 's3-turnhead', 'data-turn': t.turn_id, text: `SYSTEM 3 — TURN ${String(t.index + 1).padStart(4, '0')} · ${t.speaker} ${t.name || ''} · ${t.step_label} · ${t.phase}`}));
      /* [s3-feedentry] the turn as the feed shows it, with every roll inside */
      const evs = [...turnEvents(conv, t),
        ...(conv.observations_air || []).filter(o => o.turn_id === t.turn_id || ((o.family === 'SFX' || o.family === 'SFXGUY') && t.script_index != null && o.turn_index === t.script_index))];
      out.push(v.feedEntry(t, evs, conv));
    }
    const late = (conv.observations_air || []).filter(o => !o.turn_id && !((o.family === 'SFX' || o.family === 'SFXGUY') && o.turn_index != null));
    if (late.length) out.push(el('div', 's3-turnhead', 'OBSERVED AFTER THE PLAN (doors, commits, repairs)'), ...late.map(o => v.eventCard(o)));
    for (const r of conv.replans || []) out.push(el('div', 's3-muted', `turn-by-turn: re-decided from turn ${r.from + 1} (revision ${r.revision}); ${r.dropped.length} planned turn(s) replaced`));
    fill(v.paneB, ...out);
  };

  /* C. the final script */
  v.paintScript = () => {
    const conv = v.conv;
    const out = [el('h2', null, 'Final script', el('span', {class: 's3-muted', text: conv ? `revision ${conv.identity.revision}` : ''}))];
    if (!conv) { fill(v.paneC, ...out); return; }
    const paper = el('div', 's3-paper');
    if (conv.mode === 'shadow') {
      paper.append(el('p', {class: 's3-muted', text: 'Shadow mode. Left: what System 3 would have directed (never aired). Right: the script the legacy writer actually produced.'}),
        el('div', 's3-cols',
          el('div', null, ...v.turnsInOrder(conv).map(t => el('div', {class: 's3-sline', 'data-turn': t.turn_id, onclick: e => v.select(t.turn_id, '', e.currentTarget)},
            el('b', {text: `${t.index + 1} · ${t.name || t.speaker}`}),
            el('p', {text: `${(t.performance || {}).emotion ? 'In ' + t.performance.emotion + ': ' : ''}${(t.directions || []).map(d => d.text).join('; ') || t.step_label}`})))),
          el('div', null, ...(conv.actual || []).map((a, i) => el('div', 's3-sline', el('b', {text: `${i + 1} · ${a.speaker}`}), el('p', {text: a.text}))))));
    } else {
      if (conv.mode === 'simulation') paper.append(el('p', {class: 's3-muted', text: 'Simulation: a plan with no words. It never reaches the writer or the air.'}));
      for (const t of v.turnsInOrder(conv)) {
        const st = v.turnStatus(t), perf = t.performance || {}, a = st.air || {};
        const sfxAir = (conv.observations_air || []).find(o => o.family === 'SFX' && o.turn_index === t.script_index);
        paper.append(el('div', {class: 's3-sline', 'data-turn': t.turn_id, onclick: e => v.select(t.turn_id, '', e.currentTarget)},
          el('b', {text: `${st.line ? `block ${st.line.block} · ord ${st.line.ord}` : `turn ${t.index + 1}`} · ${t.name || t.speaker}`}),
          el('p', {text: (st.line && st.line.text) || t.text || '(no words - ' + (t.status || 'planned') + ')'}),
          el('div', 's3-prov',
            el('span', {text: `performance: ${perf.emotion || '-'} ${num(perf.intensity)} · pace ${num(perf.pace)} · ${perf.pause_style || '-'} pauses · warmth ${num(perf.warmth)}`}),
            a.voice ? el('span', {text: `voice ${a.voice}` + (a.engine ? ` on ${a.engine}` : '')}) : null,
            t.sfx && t.sfx.play ? el('span', {text: `SFX planned ${t.sfx.placement} (${(t.sfx.intent || []).slice(0, 3).join(', ')})`}) : null,
            sfxAir ? el('span', {text: 'SFX at air: ' + ((sfxAir.played || [])[0] || {}).clip}) : null,
            (t.speakerbox || []).filter(s => s.material).map(s => el('span', {text: `speakerbox ${s.mode.toLowerCase()}: ${s.material.file}`})),
            st.line ? el('span', {text: 'line ' + st.line.line_id.slice(0, 8)}) : null,
            el('span', {class: st.cls, text: st.word}),
            a.withdrawn_why ? el('span', {class: 'gone', text: a.withdrawn_why}) : null)));
      }
    }
    out.push(paper);
    if (conv.plan && conv.plan.sheet) out.push(block('the running order the writer was given', conv.plan.sheet));
    fill(v.paneC, ...out);
  };

  /* Replay the retained message tiles in sequence. Routine event refreshes
     extend their recorded rows and update words while this build continues. */
  v.build = async () => {
    if (!v.conv || v.playing) return;
    const token = ++v.token, subject = v.conv;
    v.playing = true;
    if (v.onBuildState) v.onBuildState(true);
    const chat=v.paintConversation();
    const count=v.paneA.querySelector(':scope > h2 > span');if(count)count.textContent='building from the recorded rolls';
    try {
      await v.buildRound(subject, chat, {base: 700 / v.speed,
        live: () => token === v.token && v.conv?.identity?.conversation_id === subject.identity.conversation_id,
        latest: () => v.conv,
        grow: node => { if (!v.quiet) node.scrollIntoView({block: 'nearest'}); }});
    } finally {
      v.playing = false;
      if (v.onBuildState) v.onBuildState(false);
      if(v.conv&&v.alive){const count=v.paneA.querySelector(':scope > h2 > span');if(count)count.textContent=v.conv.turns.length+' turns';v.select(v.sel.turn,v.sel.event,null);}
    }
  };
  return v;
}

/* The Script tab's own Messenger and Technical views (PDF p.5: "the script
   view needs to be able to cycle between the developing conversation view,
   the technical RNG generative view ... and back to the script view in
   sync"). The host says which conversation and turn the air is on - the line
   on air, or the one the operator tapped - and hears back which turn the
   operator picked here, so returning to the script lands on its line.

   THE MESSENGER IS AN ENDLESS FEED, MESSAGE BY MESSAGE, LIKE AN INSTANT
   MESSAGE: "I need it to continuously show segments being added to it and
   rolled up through the roulette and the roller deck systems as each entry
   is being added ... then it convert into being the text entry ... I am
   still seeing it jump up the list ... I need the messenger feed to be
   message by message by message." Every round System 3 plans joins the
   bottom of the feed one message at a time - its slot appears, each decision
   rolls its drum and die, and it converts into its text - and the next
   message waits for it. [s3-messenger] A message not yet on air stands as
   its roulette card (its dice, not its words); the air turns them into
   words one at a time, in the air's order, as the audio plays (see "THE
   AIR, ONE LINE AT A TIME" below), in the ledger's order ("THE THREAD").
   [s3-imsg] Synced (the on-air pill pressed), the message on air sits at
   the bottom of the view like the newest text in a thread and each new one
   is brought up as it comes; a hand scroll either way, or opening,
   selecting or holding something, unsyncs it and then nothing moves the
   view until the operator scrolls back to the latest message or presses
   the pill. It reads the station's event cursor (one small request every few
   seconds, only while the view is on screen) and fetches a round only when
   it has news - never a request per line, never a repaint of the feed. */
export async function mountEmbedded(root, {request, view = 'conversation', onSelect, onOpenFull, chrome, details = true} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-embed');
  /* [s3-imsg] its holds are its own (holdMenu, with the item it knows): the station's line sheet
     (line-actions.js) does not open a second time on the same press */
  root.setAttribute('data-own-hold', '');
  const v = makeViews({request, details, onSelect: (conv, turnId, eventId) => {
    if (!onSelect) return;
    onSelect({conversation: conv.identity.conversation_id, turn: turnId, event: eventId,
      lines: (conv.lines || []).filter(l => l.turn_id === turnId).map(l => l.line_id)});
  }});
  let current = view === 'rolodex' || view === 'technical' ? 'rolodex' : 'conversation';
  let cid = '', note = '';
  let liveTurn = '', liveLine = '', handAt = 0, selfUntil = 0;
  /* [s3-imsg] SYNCED TO THE CURRENT MESSAGE. "Make this button the synced to
     current message button that whenever I click it it keeps the
     messengers synced to the current message like a instant messenger ...
     if I scroll away from it it basically turns this off or if I toggle it
     off it allows me to freely scroll around this without my view being
     reset to any location." - "do not move the page for me ... unless I am
     already looking at the latest message ... I don't like any sort of auto
     scroll taking over when I'm already looking at something specific."
     (operator, 2026-09-28). `follow` IS the sync, and the on-air pill is its
     one switch (pressed = synced). Synced, the message on air sits at the
     bottom of the view and each new one is brought up as it comes. A hand
     scroll away (either way), a panel opened, words selected or a message
     held turns it off, and then NOTHING moves the view - no timer, no
     refresh, no build - until the operator scrolls back to the latest
     message or presses the pill. It starts on; nothing is kept across
     reloads. */
  let follow = true;
  let liveKey = '';                            /* the item the host's focus is on: a turn id, or 'sfx:<line>' */
  let hold = null;                             /* a finger held down on something */
  let unseen = 0;                              /* lines that went on air while the view was not synced */
  const title = el('b', 's3-embed-title');
  const facts = el('span', 's3-muted s3-embed-facts');
  const onAir = el('button', {type: 'button', class: 's3-pill s3-embed-air s3-sync', 'aria-pressed': 'true',
    onclick: () => { if (follow) unsync(); else toAir(); }});
  const syncText = el('span', 's3-sync-text');
  const syncCount = el('b', 's3-sync-count');
  {
    const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:link') : '';
    const ico = el('span', {class: 's3-sync-ico', 'aria-hidden': 'true'});
    if (svg) ico.innerHTML = svg;
    onAir.append(ico, syncText, syncCount);
  }
  /* the sync off: nothing moves the view from here on */
  function unsync() {
    if (!follow) return;
    follow = false;
    handAt = Date.now();
    paintJump();
  }
  /* The pill pressed: synced, and the view goes to the current message - in
     whichever of the two views is up. */
  function toAir() {
    follow = true; unseen = 0;
    paintJump();
    if (current === 'rolodex') {
      const n = nodesFor(liveTurn)[0];
      if (!n) return false;
      ownScroll(true);
      n.scrollIntoView({block: 'center', behavior: reduced() ? 'auto' : 'smooth'});
      n.classList.remove('s3-flash'); void n.offsetWidth; n.classList.add('s3-flash');
      return true;
    }
    const n = itemNode(anchorKey());
    toAnchor(true, true);                          /* asked for: it goes now, whatever the hand did last */
    if (!n) return false;
    n.classList.remove('s3-flash'); void n.offsetWidth; n.classList.add('s3-flash');
    return true;
  }
  /* "jump me to the line and then animate that particular tile of dialogue
     that's being spoken". The LINE decides, not the view's last idea of the
     air: the host's focus follows a line tapped in the script while its card
     is open, so liveTurn could be another round's turn. The line is the one
     passed, else the one the page's own now-playing card carries. A line
     this feed does not hold is looked up, and its round joins the feed. */
  async function jumpTo(lineId) {
    const saying = document.getElementById('spSaying');
    const line = String(lineId || (saying && saying.dataset && saying.dataset.line) || liveLine || '');
    if (line && face.live(line) !== 'here') {
      try {
        const got = await request('/api/system3/line?line_id=' + encodeURIComponent(line));
        if (got && got.conversation && got.line) {
          await face.show({conversationId: got.conversation.conversation_id, turnId: (got.turn && got.turn.turn_id) || ''});
          face.live(got.line.line_id);
        }
      } catch (e) { /* the view keeps what it has */ }
    }
    await sleep(60);
    if (!toAir()) return false;
    if (current !== 'conversation') return true;
    const node = nodesFor(liveTurn)[0];
    const entry = [...feed.values()].find(e => (e.conv.turns || []).some(t => t.turn_id === liveTurn));
    const t = entry && entry.conv.turns.find(x => x.turn_id === liveTurn);
    /* [s3-messenger] the line on air is already moving with the audio, and a
       line not yet on air is its roulette: only a past line is rebuilt */
    if (node && t && !entry.building && !['live', 'upcoming'].includes(node.dataset.stage)) {
      await sleep(reduced() ? 0 : 450);         /* let the scroll land first */
      if (await v.assemble(node)) dressAir();   /* [s3-imsg] the one assembly: card, dice, hold, words */
    }
    return true;
  }
  /* One line of header, icons for the three actions: the conversation gets
     the room. The page's own Carbon set when it is there, words when not. */
  const iconBtn = (ref, label, onclick, extra = {}, short = '') => {
    const b = el('button', {type: 'button', class: 's3-ibtn', title: label, 'aria-label': label, onclick, ...extra});
    const svg = typeof window.pineIcon === 'function' ? window.pineIcon(ref) : '';
    if (svg) b.innerHTML = svg; else { b.textContent = short || label; b.classList.add('txt'); }
    return b;
  };
  /* [s3-imsg] "Back to the line on air" is the on-air pill now: one switch, one truth */
  const playBtn = iconBtn('c:repeat', 'Play the build again: the newest round, message by message', () => replay(), {}, 'Replay');
  const fullBtn = onOpenFull ? iconBtn('c:maximize', 'Open System 3', () => onOpenFull(cid), {}, 'Open') : null;
  /* TURN BY TURN (System 3 Mode B): "we might need System 3 turn-by-turn
     generation, for each reply to coordinate with the last reply. I want a
     toggle to enable / disable that." On, a banked round is written one
     reply at a time, each planned after the last one is written - so every
     reply answers the line before it, and its dice decide how the speaker
     feels about THAT line. Off, the round's running order is planned whole. */
  let genMode = '';
  const turnBtn = iconBtn('m:linked_services', 'Turn by turn', () => toggleTurn(),
    {class: 's3-ibtn s3-turn-toggle', 'aria-pressed': 'false', hidden: true}, 'Turns');
  function paintTurn() {
    const on = genMode === 'turn';
    turnBtn.classList.toggle('on', on);
    turnBtn.setAttribute('aria-pressed', String(on));
    turnBtn.hidden = !genMode;
    const say = on ? 'Turn by turn is ON: each reply in a banked round is planned after the last one is written, so it answers it. Tap to plan rounds whole again.'
      : 'Turn by turn is OFF: each round is planned whole. Tap so each reply in a banked round is planned after the last one is written.';
    turnBtn.title = say;
    turnBtn.setAttribute('aria-label', say);
  }
  async function readTurn() {
    try { genMode = String(((await request('/api/system3/settings') || {}).settings || {}).generation_mode || 'batch'); }
    catch (e) { genMode = ''; }
    paintTurn();
  }
  async function toggleTurn() {
    const next = genMode === 'turn' ? 'batch' : 'turn';
    turnBtn.disabled = true;
    try {
      const got = await request('/api/system3/settings', {method: 'POST', body: JSON.stringify({generation_mode: next})});
      genMode = String(((got || {}).settings || {}).generation_mode || next);
    } catch (e) { turnBtn.title = 'Turn by turn could not be changed: ' + e.message; }
    turnBtn.disabled = false;
    paintTurn();
  }
  const cutBtn = iconBtn('c:cut', 'The systems that cut lines, and their switches', () => openCutPanel(v), {}, 'Cuts');
  const tools = el('span', 's3-bar-tools', turnBtn, cutBtn, playBtn, fullBtn);
  /* THE HOST'S OWN HEADER. "The items at five and six, I want added to the
     top header ... so that way this can be consolidated and the messenger
     can just be a pure messenger view." A host that passes chrome = {tools,
     air, facts} gets the buttons, the on-air pill and the round's facts in
     places of its own; each goes in a span.s3.s3-chrome so this view's
     tokens and button rules reach it, and a piece with no place stays on a
     bar here. The title is not handed over: the host's own toggle already
     says which view is up. */
  const docked = [];
  const dock = (slot, piece) => {
    if (!slot || typeof slot.append !== 'function') return false;
    const wrap = el('span', 's3 s3-chrome', piece);
    slot.append(wrap);
    docked.push(wrap);
    return true;
  };
  const left = [onAir, facts, tools].filter((piece, i) => !(chrome && dock([chrome.air, chrome.facts, chrome.tools][i], piece)));
  const head = left.length ? el('div', 's3-embed-head s3-bar', title, ...left) : null;
  const noteBox = el('p', 's3-muted s3-embed-note');
  const bodyBox = el('div', 's3-embed-body');
  const feedBox = el('div', 's3-feed');
  const emptyBox = el('p', {class: 's3-muted s3-feed-empty', text: 'Waiting for System 3 to plan a round...'});
  fill(v.paneA, emptyBox, feedBox);
  fill(root, head, noteBox, bodyBox);

  /* ---- [s3-imsg] synced to the current message ------------------------------ */
  const EDGE = 12;         /* the message on air sits this far above the view's bottom: nothing still to come shows above the fold */
  const TOL = 48;          /* this close to where the sync would put the view is "at the latest message" */
  const HAND_MS = 900;     /* a scroll this soon after the operator's own wheel, drag, key or scrollbar is theirs */
  let handInput = 0, handDown = false;
  const handOn = () => handDown || Date.now() - handInput < HAND_MS;
  const cover = () => (head && head.isConnected ? head.offsetHeight : 0);     /* the sticky bar over the top of the view */
  /* The message the sync keeps at the bottom: the newest one that has
     appeared (the one on air, or what came in under it), else (nothing on
     air here yet) the newest one that has happened - never a card still to
     come, never the bottom of the feed (where rounds still being written
     grow). */
  function anchorKey() {
    for (const k of [shownKey, airHead]) if (k && itemNode(k)) return k;    /* the newest message that has appeared, else the one on air */
    for (let i = thread.length - 1; i >= 0; i -= 1) {
      const n = itemNode(thread[i]);
      if (n && n.dataset.key && n.dataset.stage && n.dataset.stage !== 'upcoming') return thread[i];
    }
    return '';
  }
  /* Where the sync puts the view: the anchor's bottom EDGE px above the
     view's bottom - with what hangs under it that has happened (its clip,
     the SFX Guy's line, an arrival that came late) - or, when that is
     taller than the view, its head under the bar. null: nothing to anchor. */
  function anchorTop(){
    const key=anchorKey(),node=key?itemNode(key):null;if(!node)return null;
    const box=root.getBoundingClientRect();let focus=node;
    const state=node.s3Tile;
    if(state?.seq)focus=tileFocus(node);
    else if(rv?.key===key&&rv.phase==='roll'&&state){const table=state.sheet.tables[parseInt(state.sheet.now,10)];if(table)focus=table.sub&&state.sheet.now.includes('sub-')?table.sub.el:table.el;}
    else if(rv?.key===key&&rv.phase==='words')focus=node.querySelector(':scope > .s3-bubble .s3-words')||node;
    const rect=focus.getBoundingClientRect();if(!box.height||!rect.height)return null;
    let top=root.scrollTop;if(rect.bottom>box.bottom-EDGE)top+=rect.bottom-(box.bottom-EDGE);
    else if(rect.bottom<box.top+cover()+8)top+=rect.top-(box.top+cover()+8);
    return Math.max(0,Math.min(root.scrollHeight-root.clientHeight,Math.round(top)));
  }

  /* The one scroll the sync makes. It waits while a finger is down or the
     operator's hand is on the scroll; `force` is the operator's own request. */
  function toAnchor(smooth, force = false) {
    if (current !== 'conversation' || hold || (!force && (handOn() || replaying || v.extending))) return;
    const top = anchorTop();
    if (top == null || Math.abs(top - root.scrollTop) < 2) return;
    ownScroll(smooth);
    if (smooth && !reduced()) root.scrollTo({top, behavior: 'smooth'});
    else root.scrollTop = top;
  }
  /* a scroll of the view's own (or one the operator asked for): its scroll events are not their hand */
  function ownScroll(smooth) {
    selfUntil = Date.now() + (smooth && !reduced() ? 700 : 160);
    handInput = 0;
  }
  /* at the latest message: where the sync would put the view, give or take */
  const atLatest = () => {
    const top = anchorTop();
    if (top == null) return root.scrollHeight - root.scrollTop - root.clientHeight < TOL;
    return Math.abs(root.scrollTop - top) <= TOL;
  };
  /* the Technical view's latest: the lit turn in sight */
  const rxAtLatest = () => {
    const n = nodesFor(liveTurn)[0];
    if (!n) return false;
    const box = root.getBoundingClientRect(), r = n.getBoundingClientRect();
    return r.height > 0 && r.bottom > box.top + cover() + 8 && r.top < box.bottom - 8;
  };
  /* The operator is examining something: a finger down, a card open over
     the page, words selected, or something opened (a panel, a fold, a line
     opened into its passages, a replay, a withdrawn line) on screen. The
     sync does not come back on by itself while this is so. */
  const OPENED = '.s3-drop, details[open], .s3-msg.open, .s3-replay, .s3-gone-open';
  function examining() {
    if (hold || document.querySelector('.s3-modal-back')) return true;
    const sel = window.getSelection ? window.getSelection() : null;
    if (sel && !sel.isCollapsed && sel.anchorNode && root.contains(sel.anchorNode)) return true;
    const box = root.getBoundingClientRect();
    for (const n of root.querySelectorAll(OPENED)) {
      const r = n.getBoundingClientRect();
      if (r.height && r.bottom > box.top && r.top < box.bottom) return true;
    }
    return false;
  }
  /* A panel the operator opened on the message at the bottom opens out of
     sight: it is brought into the view, head first (their own request). */
  function revealOpened(node) {
    if (!node || current !== 'conversation') return;
    requestAnimationFrame(() => {
      if (!root.contains(node)) return;
      const panel = node.querySelector(':scope > .s3-drop') || node;
      const box = root.getBoundingClientRect(), r = node.getBoundingClientRect(), p = panel.getBoundingClientRect();
      if (p.top < box.bottom - 40) return;                          /* it opened in sight: nothing moves */
      const by = Math.min(r.bottom - (box.bottom - EDGE), r.top - (box.top + cover() + 8));
      if (by < 2) return;
      ownScroll(true);
      root.scrollBy({top: by, behavior: reduced() ? 'auto' : 'smooth'});
    });
  }
  /* the pill: pressed while synced, the turn on air, and how many went on air while it was not */
  function paintJump() {
    const on = follow;
    onAir.classList.toggle('s3-synced', on);
    onAir.setAttribute('aria-pressed', String(on));
    syncCount.textContent = !on && unseen ? (unseen > 99 ? '99+' : String(unseen)) : '';
    const say = on ? 'Synced to the current message: each new message comes into view as it airs. Tap to scroll freely.'
      : unseen ? `Not synced - ${unseen} went on air since. Tap to sync to the current message.`
        : 'Not synced: the view stays where you put it. Tap to sync to the current message.';
    onAir.title = say;
    onAir.setAttribute('aria-label', (syncText.textContent ? syncText.textContent + '. ' : '') + say);
  }
  /* The operator's hand: a wheel, a finger dragging, a scrolling key, the
     scrollbar or a middle-button scroll. A scroll with none of them near it
     is the view's own (or the browser keeping it still) and changes nothing. */
  const markHand = () => { handInput = Date.now(); };
  root.addEventListener('wheel', markHand, {passive: true});
  root.addEventListener('touchmove', markHand, {passive: true});
  root.addEventListener('pointerdown', e => {
    const box = root.getBoundingClientRect();
    if (e.button === 1 || (e.pointerType === 'mouse' && e.clientX >= box.left + root.clientLeft + root.clientWidth)) { handDown = true; markHand(); }
  }, {passive: true});
  const handUp = () => { if (handDown) { handDown = false; markHand(); } };
  const handKey = e => {
    if (!/^(PageUp|PageDown|ArrowUp|ArrowDown|Home|End| |Spacebar)$/.test(e.key)) return;
    if (e.target && e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]')) return;
    markHand();
  };
  window.addEventListener('pointerup', handUp, true);
  window.addEventListener('pointercancel', handUp, true);
  document.addEventListener('keydown', handKey, true);
  root.addEventListener('scroll', () => {
    if (!handOn()) return;
    handInput = Date.now();                       /* a fling's tail is still the operator's */
    handAt = Date.now();
    const latest = current === 'rolodex' ? rxAtLatest() : atLatest();
    if (follow && !latest) follow = false;                                  /* scrolled away, either way */
    else if (!follow && latest && !examining()) { follow = true; unseen = 0; }   /* back at the latest message */
    paintJump();
  }, {passive: true});
  /* examining something turns the sync off: words selected, a fold or a
     panel opened, a control in the feed used (a die's card, a replay, a
     line's passages), a message held (holdMenu) */
  const onSelection = () => {
    const sel = window.getSelection ? window.getSelection() : null;
    if (sel && !sel.isCollapsed && sel.anchorNode && root.contains(sel.anchorNode)) unsync();
  };
  document.addEventListener('selectionchange', onSelection);
  root.addEventListener('toggle', e => { if (e.target && e.target.open) unsync(); }, true);
  bodyBox.addEventListener('click', e => {
    /* [s3-imsg] a message played again (its split button) is watched where it stands - the sync is
       not touched; a panel's chevron is the dropHook's to judge */
    if (!e.target.closest || e.target.closest('.s3-assemble, .s3-drop-btn')) return;
    if (e.target.closest('button, [role="button"], summary, a[href], input, select, textarea, [data-event]')) unsync();
  }, true);
  const toggleLine = v.toggle;
  v.toggle = (t, node) => { toggleLine(t, node); if (v.open.has(t.turn_id)) unsync(); dressThread(); };
  /* "what built this message" (its panel, when the host has it): opened on anything but the
     message on air, it is examining - the sync goes off, and the view stays where it is; opened on
     the message on air while synced, the sync carries on. No re-sync while an open panel is in
     sight (examining()). */
  v.dropHook = (node, open) => {
    if (!open || current !== 'conversation') return;
    if (follow && node !== itemNode(liveKey)) { follow = false; handAt = Date.now(); paintJump(); }
    revealOpened(node);
  };

  /* [s3-imsg] ONE ASSEMBLY (makeViews): here a tap on a message plays it coming together; the
     message on air is left to its own reveal; a node that stands in an item's place is the item's
     node; a long version holds the view still while it runs (glide) */
  v.tapAssembles = (node) => {
    if (Date.now() - heldAt < 700) return;                 /* the release of a hold is not a tap */
    v.assemble(node);
  };
  v.assembleGate = (key) => current === 'conversation' && !replaying && !(rv && rv.key === key) &&
    ![...feed.values()].some(e => e.building && ownerOf.get(key) === e.conv.identity.conversation_id);
  v.onPut = (key, fresh) => { nodes.set(key, fresh); dressThread(); };
  v.onAssembled = () => { dressThread(); if (!v.extending) glide(); };
  /* [s3-imsg] BACK (window.pineBack in pine-dismiss.js; the kiosk's BACK key) closes the topmost
     overlay; here that is the newest "what built this message" panel open in sight - closed by
     its own chevron. Overlays that sit above the page (the hold sheet, a decision card, the SFX
     TV) are above it and go first. */
  const unBack = window.PineDismiss && typeof window.PineDismiss.onBack === 'function'
    ? window.PineDismiss.onBack(() => {
      if (!root.isConnected || current !== 'conversation') return null;
      const box = root.getBoundingClientRect();
      const open = [...root.querySelectorAll('.s3-feed .s3-drop')].filter(p => {
        const r = p.getBoundingClientRect();
        return r.height > 0 && r.bottom > box.top && r.top < box.bottom;
      });
      const panel = open[open.length - 1];
      const chev = panel && panel.parentElement ? panel.parentElement.querySelector(':scope > .who > .s3-drop-btn') : null;
      return chev ? {node: panel, close: () => chev.click()} : null;
    }) : null;

  /* TAP AND HOLD, EVERYWHERE: "If I tap and hold on a thumbnail or a piece
     of media, then show the what do I want to do with this menu always.
     Nothing should be unresponsive to me tapping and holding." A spoken
     line opens the station's own "What would you like to do with this?"
     sheet for its script line; the SFX Guy's entry, a thumbnail or an audio
     player opens that sheet as the sting it aired as (or the SFX TV's menu);
     a line with no words yet, or an SFX plan, opens System 3's own menu.
     Right-click does the same on the desktop. */
  const HOLD_MS = 520;
  let heldAt = 0;
  const cancelHold = () => { if (hold) clearTimeout(hold.timer); hold = null; };
  root.addEventListener('pointerdown', e => {
    if (e.button) return;
    cancelHold();
    heldAt = 0;                                  /* [s3-imsg] a new press: its click is its own, not a hold's release */
    const at = {x: e.clientX, y: e.clientY, target: e.target};
    hold = {x: at.x, y: at.y, timer: setTimeout(() => { cancelHold(); heldAt = Date.now(); holdMenu(at.target, at); }, HOLD_MS)};
  }, {passive: true});
  root.addEventListener('pointermove', e => {
    if (hold && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 12) cancelHold();
  }, {passive: true});
  for (const type of ['pointerup', 'pointercancel']) root.addEventListener(type, cancelHold, {passive: true});
  /* a scroll the operator makes ends a hold; the feed's own pinning to the
     newest message does not (and waits while a finger is down) */
  root.addEventListener('scroll', () => { if (Date.now() >= selfUntil) cancelHold(); }, {passive: true});
  root.addEventListener('contextmenu', e => {
    if (!e.target.closest('.s3-msg, .s3-sysrow, .s3-clip, .s3-round-head, .s3-sgf-head')) return;   /* [s3-segment-feed] a segment's head too */
    e.preventDefault();
    /* [s3-imsg] a touch screen's long press is a contextmenu AND this hold: one press, one menu */
    if (Date.now() - heldAt < 1000) return;
    cancelHold();
    heldAt = Date.now();
    holdMenu(e.target, {x: e.clientX, y: e.clientY});
  });
  /* the tap that ends a hold is not also a tap on what was held */
  root.addEventListener('click', e => { if (Date.now() - heldAt < 700) { e.stopPropagation(); e.preventDefault(); } }, true);

  async function holdMenu(target, at) {
    unsync();                                    /* [s3-imsg] a message held: the operator is examining it */
    const la = window.PineLineActions;
    const segEl = target.closest('.s3-sgf-head');         /* [s3-segment-feed] a segment's head: the segment's menu */
    if (segEl) { segMenu(segEl.dataset.seg); return; }
    const headEl = target.closest('.s3-round-head');
    if (headEl) {
      /* by its own id: the header is redrawn whenever the round has news,
         and a hold can outlast the node it started on */
      const entry = feed.get(headEl.dataset.conv);
      if (entry) roundMenu(entry, (headEl.closest('.s3-round') || headEl).dataset.seg || '');   /* [s3-segment-feed] the segment this part of it went out in */
      return;
    }
    const sfxNode = target.closest('.s3-sfxguy');
    if (sfxNode && sfxNode.s3) {
      const {conv, t, obs, played, line} = sfxNode.s3;
      /* [s3-imsg] the SFX Guy's own line is a spoken row of the ledger ('drop'): it opens as a
         line, headed with his name and his words */
      if (sfxNode.classList.contains('s3-sfxguy-line')) {
        const words = normWs(obs && obs.line);
        const drop = words ? (conv.lines || []).find(l => l.who === 'drop' && normWs(l.text).toLowerCase() === words.toLowerCase()) : null;
        if (la && typeof la.open === 'function' && drop) {
          try { la.open({id: drop.line_id, said: (castName('sfx') + ': ' + words).slice(0, 220), node: sfxNode}); return; }
          catch (e) { /* System 3's menu */ }
        }
        turnMenu(conv, t, sfxNode);
        return;
      }
      /* [s3-imsg] a sting opens at once, as itself: its clip's id off the play it pairs with or its
         row's own frame, its name, and a one-line heading - never the card's text run together.
         The clip itself is looked up only when "Play it" asks for it (line-actions.js). */
      const media = !line && played ? await v.api.sfxMedia(played) : null;
      const board = line || boardLineFor(conv, t, media);          /* [s3-messenger] a sting node knows its own row */
      if (la && typeof la.open === 'function' && board) {
        const info = stingInfo(board, played);
        const roll = board.sfx_roll && typeof board.sfx_roll === 'object' ? board.sfx_roll : {};
        const name = String((roll.clip && roll.clip.label) || (media && media.name) || info.name || (played && played.clip) || '');
        sfxNode.pineItem = {tag: 'sting', sfx: (media && media.id) || info.sid || '', line: board.line_id, deleted: false, text: name};
        sfxNode.dataset.line = board.line_id;
        const said = sfxNode.dataset.said || [`Sting after turn ${t.index + 1}`, name ? `clip '${name}'` : ''].filter(Boolean).join(' · ');
        try { la.open({id: board.line_id, said, node: sfxNode}); return; }
        catch (e) { /* the SFX TV's menu instead */ }
      }
      if (obs) openSfxMenu(conv, t, obs, played, v, sfxNode, {clientX: at.x, clientY: at.y});
      return;
    }
    const row = target.closest('.s3-sysrow[data-event]');
    const msg = target.closest('.s3-msg[data-turn]');
    const holder = row || msg;
    const turnId = holder ? holder.dataset.turn : '';
    const conv = turnId ? v.convOf({turn_id: turnId}) : null;
    const t = conv ? conv.turns.find(x => x.turn_id === turnId) : null;
    if (!conv || !t) return;
    if (row) {
      const ev = (conv.decision_events || []).find(x => x.event_id === row.dataset.event);
      if (ev) openDecision(conv, ev, t, v.api);
      return;
    }
    /* [s3-imsg] a run of the turn opens as its own first line; the heading is the speaker and the
       words - a card still to come says so, never its words */
    const key = (msg && msg.dataset.key) || t.turn_id;
    const part = key.startsWith('part:') ? (v.partsOf(conv, t) || []).find(p => p.key === key) : null;
    const line = part ? part.lines[0] : (conv.lines || []).find(l => l.turn_id === t.turn_id);
    if (la && typeof la.open === 'function' && line) {
      const who = t.name || castName(t.speaker === 'B' ? 'cohost' : 'host', t.speaker);
      const said = msg && msg.dataset.stage === 'upcoming' ? `${who} · turn ${t.index + 1} - not on air yet`
        : `${who}: ${normWs(part ? part.text : (lineText(conv, t) || line.text || ''))}`;
      try { la.open({id: line.line_id, said: said.slice(0, 220), node: msg}); return; } catch (e) { /* System 3's menu */ }
    }
    turnMenu(conv, t, msg);
  }

  /* What to do with a segment: its node graph, how it was assembled, its
     build again, the full instrument. */
  function roundMenu(entry, seg = '') {
    const conv = entry.conv;
    const block = ((conv.lines || []).find(l => l.block) || {}).block || 0;
    const flow = window.PineSegmentFlow;
    const back = el('div', {class: 's3 s3-modal-back s3-hold-back'});
    const close = () => { back.remove(); document.removeEventListener('keydown', key, true); };
    const key = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const note = el('p', {class: 's3-muted'});
    const inspect = async () => {
      openAssembly(conv, v.air);
      if (flow && typeof flow.openForSegment === 'function' && block) {
        try { await flow.openForSegment({block, round: conv.identity.road_kind}); }
        catch (e) { /* the graph is only drawn for a segment still on the running order; System 3's account stands */ }
      }
    };
    const items = [
      btn('Inspect it - the node graph and how it was assembled', () => { close(); inspect(); }),
      btn('Open its pine-graph - the conversation graph editor on this road', () => { close(); openSystem3({request, tab: 'segments:' + ((conv.identity || {}).road_kind || '')}); }),   /* [pine-graph] */
      /* [s3-segment-feed] the segment it went out in, and the others */
      btn('Inspect the segment it went out in', () => { close(); openSegmentInspector({request, segment: seg, conversation: conv.identity.conversation_id}); }),
      btn('Inspect other segments', () => { close(); openSegmentInspector({request, segment: seg, conversation: conv.identity.conversation_id, pick: true}); }),
      btn('How System 3 assembled it', () => { close(); openAssembly(conv, v.air); }),
      btn('Replay this round\'s build, message by message', () => { close(); replay(entry); }),
      onOpenFull ? btn('Open it in System 3', () => { close(); onOpenFull(conv.identity.conversation_id); }) : null];
    back.append(movableModal(el('section', {class: 's3-modal s3-holdmenu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this conversation?'},
      el('b', {text: 'What would you like to do with this conversation?'}),
      el('p', {class: 's3-muted', text: `${conv.identity.road_kind} · ${clock(convTime(conv))} · ` + String((conv.subject || {}).topic || '').replace(/\s+/g, ' ').slice(0, 140)}),
      note, el('div', 's3-holdmenu-items', ...items.filter(Boolean)), btn('Close', close))));
    back.addEventListener('click', e => { if (e.target === back) close(); });
    document.addEventListener('keydown', key, true);
    document.body.append(back);
  }

  /* System 3's own menu for a line that has no script line yet. */
  function turnMenu(conv, t, msg) {
    const back = el('div', {class: 's3 s3-modal-back s3-hold-back'});
    const close = () => { back.remove(); document.removeEventListener('keydown', key, true); };
    const key = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const go = (fn) => () => { close(); fn(); };
    const node = () => (msg && msg.isConnected) ? msg : v.paneA.querySelector('.s3-msg[data-turn="' + CSS.escape(t.turn_id) + '"]');
    const items = [
      btn('Replay how this line was decided', go(() => { const n = node(); if (n) v.replayTurn(n, conv, t); })),
      canCompose(conv, t) ? btn(v.open.has(t.turn_id) ? 'Close its speaker-box view' : 'Open its speaker-box passages and odds',
        go(() => { const n = node(); if (n) v.toggle(t, n); })) : null,
      ...turnEvents(conv, t).map(ev => btn('How ' + ev.family + ' was decided: ' + chipOf(ev, conv).text, go(() => openDecision(conv, ev, t, v.api))))];
    back.append(movableModal(el('section', {class: 's3-modal s3-holdmenu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this line?'},
      el('b', {text: 'What would you like to do with this?'}),
      el('p', {class: 's3-muted', text: (t.name || t.speaker) + ', turn ' + (t.index + 1) + ': ' +
        (v.stageOf(t.turn_id, conv, t) === 'upcoming' ? 'not on air yet - its words show when the air reaches it'   /* [s3-messenger] */
          : lineText(conv, t) || 'no words yet - ' + ((t.directions || []).map(d => d.text).join('; ') || t.step_label))}),
      el('div', 's3-holdmenu-items', ...items.filter(Boolean)), btn('Close', close))));
    back.addEventListener('click', e => { if (e.target === back) close(); });
    document.addEventListener('keydown', key, true);
    document.body.append(back);
  }
  /* Whatever grows the feed - a message arriving, words coming in with the
     audio, a picture loading - the line on air stays where it is in the view
     while the view follows the air. [s3-messenger] */
  let replaying = false;
  if (window.ResizeObserver) new ResizeObserver(() => { if (follow && !replaying && !v.extending && current === 'conversation') glide(); }).observe(feedBox);
  const grew = () => { if (follow && !replaying && !v.extending) glide(); };      /* [s3-imsg] eased, never a jump; still while a long version runs */

  /* ---- the feed ---------------------------------------------------------- */
  const FEED_MAX = 14;             /* 40 kept 316 messages and 58k nodes on the tablet */
  const feed = new Map();                     /* conversation id -> entry */
  const queue = [];                           /* rounds waiting to be added, message by message */
  let pumping = false, cursor = null, timer = 0, busy = false;
  let seqCache = null;                        /* [s3-messenger] the air's order of every item on show */
  /* ---- [s3-segment-feed] THE SECTIONS ARE THE STATION'S SEGMENTS -------------
     "every conversation should be chained as the "segment" per the station
      that is scheduled with everything for that segment occuring within the
      section of the messenger view" - "Interjection shouldn't be displayed
      here as segments. If a thing is interjected, that should just be in the
      instant messenger chain ... each segment is the only way these are
      sectioned." (operator, 2026-09-28)
     A segment is one entry of the running order as the station's clock put
     it on air. Every line of the script names the one it took its place in
     (the line's `segment`, System 3's register), so every item of the thread
     has one: a turn its first line's, a run of a turn or a sting its own
     line's, what hangs off a turn its turn's. The thread is cut where the
     segment changes: a head (.s3-sgf-head[data-seg]), then every run of every
     conversation in it in the thread's order - a round under its own
     sub-head (its road, its state, its rolls, the station's dozens folded to
     one chip), a single line (an interjection, a station ID, an ad spot) with
     no head at all: a message in the chain. A round the air takes across two
     segments is in both, its later part under a slim "continues". An item of
     a round not in the script yet waits in the segment on air now; one whose
     line carries no segment (written before the stamp, or while the station
     runs no schedule) goes with the item before it - with no stamp anywhere
     the feed is drawn as it always was. The head carries the segment's node
     view (its icon) and its fold, and a hold or a right-click on it the
     segment's menu: inspect it, inspect the others. Nothing here scrolls:
     heads take their places under the thread's own rule, below the air like
     any item, and their words change in place. */
  const SEG_LINE_ROADS = new Set(['track_talk', 'station_id', 'upstairs', 'interject', 'ad_spot', 'reply', 'request', 'open', 'aside']);
  const singleLine = c => SEG_LINE_ROADS.has(String(((c || {}).identity || {}).road_kind || '')) || ((c || {}).turns || []).length < 2;
  const segBook = new Map();                   /* segment id -> the station's word on it (/api/system3/segments) */
  const segHeads = new Map();                  /* 'id#n' -> the head of the segment's n-th stretch in the thread */
  const segFold = new Set();                   /* segments the operator folded shut */
  const segNoded = new Map();                  /* segment id -> its node chain, shown in place of its conversations */
  const stationOpen = new Set();               /* rounds whose station rolls the operator opened */
  let segNow = '', segsAt = 0, segsAsk = null, segsWant = false;
  const segStart = id => Number((segBook.get(id) || {}).start) || 0;
  const SEG_LINES = new WeakMap();
  /* a round's lines -> their segments: by line, by turn (its first spoken line) and its last line's */
  function segLines(conv) {
    let p = SEG_LINES.get(conv);
    if (p) return p;
    const lines = (conv.lines || []).filter(l => Number(l.block) > 0).sort(byLedger);
    const byLine = new Map(), byTurn = new Map();
    for (const l of lines) {
      const s = String(l.segment || '');
      if (l.line_id) byLine.set(l.line_id, s);
      if (isSpoken(l) && l.turn_id && !byTurn.has(l.turn_id)) byTurn.set(l.turn_id, s);
    }
    p = {byLine, byTurn, scripted: lines.length > 0, last: lines.length ? String(lines[lines.length - 1].segment || '') : ''};
    SEG_LINES.set(conv, p);
    return p;
  }
  /* The segment an item went out in: '' when its line carries none, null when
     its round has no line in the script yet. */
  function segOfItem(entry, key, n) {
    const p = segLines(entry.conv);
    if (!p.scripted) return null;
    const at = key.indexOf(':');
    if (at > 0 && /^(sfx|part)$/.test(key.slice(0, at)) && p.byLine.has(key.slice(at + 1))) return p.byLine.get(key.slice(at + 1));
    const turnId = p.byTurn.has(key) ? key : (n && n.dataset && n.dataset.turn) || key;
    return p.byTurn.has(turnId) ? p.byTurn.get(turnId) : p.last;     /* a turn with no line of its own stands after the round's last */
  }
  /* The station's word on the segments on show - their names, windows and
     counts, and the one on air - read every 20 s, and sooner (5 s) when the
     thread meets a segment it does not know. A station without the register
     answers nothing and the feed is drawn as it always was. */
  function readSegs(now = false) {
    if (segsAsk) return segsAsk;
    if (!now && Date.now() - segsAt < 20000) return Promise.resolve(false);
    segsAt = Date.now();
    segsWant = false;
    const t = Date.now() / 1000;
    let oldest = t;
    for (const e of feed.values()) for (const l of e.conv.lines || []) { const a = Number(l.at) || 0; if (a && a < oldest) oldest = a; }
    const since = Math.max(t - 6 * 3600, Math.min(oldest, t - 1800) - 600);
    segsAsk = (async () => {
      let moved = false;
      try {
        const got = await request('/api/system3/segments?' + new URLSearchParams({since: String(Math.floor(since)), limit: '60'}));
        for (const s of (got && got.segments) || []) if (s && s.id) segBook.set(String(s.id), s);
        const on = got && got.now && got.now.id ? String(got.now.id) : '';
        if (on && !segBook.has(on)) segBook.set(on, got.now);
        moved = on !== segNow;
        segNow = on;
      } catch (e) { segsAt = Date.now() + 40000; }   /* no register here (or it did not answer): asked again in a minute */
      segsAsk = null;
      if (!v.alive) return false;
      if (moved) relayout();                     /* a round not in the script yet waits in the segment on air */
      paintSegHeads();
      return true;
    })();
    return segsAsk;
  }
  /* One head per stretch of a segment in the thread: the first carries its
     fold, its kind and name, its window, the one on air marked, its counts
     and its node view; a later stretch (the thread came back to it) is slim. */
  function segHeadFor(id, n) {
    const k = id + '#' + n;
    let h = segHeads.get(k);
    if (!h) {
      const head = el('div', {class: 's3-sgf-head' + (n ? ' s3-sgf-cont' : ''), 'data-seg': id,
        title: 'tap and hold (or right-click) for what to do with this segment'});
      h = {id, n, head, kind: el('b', 's3-sgf-kind'), label: el('span', 's3-sgf-label'), when: el('span', 's3-muted s3-sgf-when'),
        air: el('span', {class: 's3-pill s3-sgf-air', text: 'on air', hidden: true}), count: el('span', 's3-muted s3-sgf-count')};
      if (!n) {
        h.fold = iconBtn('c:caret--right', 'Fold this segment away', e => { e.stopPropagation(); foldSeg(id); },
          {class: 's3-ibtn s3-sgf-fold', 'aria-expanded': 'true'}, 'Fold');
        h.nodes = iconBtn('c:chart--network', 'Show how this segment was built, as its nodes', e => { e.stopPropagation(); toggleNodes(id); },
          {class: 's3-ibtn s3-sgf-nodes', 'aria-pressed': 'false'}, 'Nodes');
      }
      head.append(...[h.fold, h.kind, h.label, h.when, h.air, h.count, h.nodes].filter(Boolean));
      segHeads.set(k, h);
    }
    paintSegHead(h);
    return h;
  }
  const segText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
  function paintSegHead(h) {
    const known = segBook.get(h.id);
    if (!known) segsWant = true;
    const s = known || {};
    segText(h.kind, String(s.kind || 'segment').replace(/_/g, ' '));
    segText(h.label, h.n ? 'continues' : String(s.label || s.kind || s.template || h.id.split(':').pop()));
    segText(h.when, h.n || !s.start ? '' : `${sgHm(s.start)} - ${sgHm(s.ends)}`);
    h.air.hidden = h.n > 0 || h.id !== segNow;
    const rounds = Number(s.rounds) || 0, singles = Number(s.singles) || 0, lines = Number(s.lines) || 0;
    segText(h.count, h.n || !known ? '' : [rounds ? `${rounds} round${rounds === 1 ? '' : 's'}` : '',
      singles ? `${singles} single line${singles === 1 ? '' : 's'}` : '', `${lines} line${lines === 1 ? '' : 's'} in the script`].filter(Boolean).join(' · '));
    if (h.fold) {
      const shut = segFold.has(h.id);
      h.fold.classList.toggle('on', shut);
      h.fold.setAttribute('aria-expanded', String(!shut));
      const say = shut ? 'Unfold this segment' : 'Fold this segment away';
      if (h.fold.title !== say) { h.fold.title = say; h.fold.setAttribute('aria-label', say); }
    }
    if (h.nodes) {
      const on = segNoded.has(h.id);
      h.nodes.classList.toggle('on', on);
      h.nodes.setAttribute('aria-pressed', String(on));
      const say = on ? 'Back to the conversation' : 'Show how this segment was built, as its nodes';
      if (h.nodes.title !== say) { h.nodes.title = say; h.nodes.setAttribute('aria-label', say); }
    }
  }
  function paintSegHeads() { for (const h of segHeads.values()) paintSegHead(h); }
  /* a head with nothing left under it goes with it (the round at the top trimmed away) */
  function pruneSegHeads() {
    for (const [k, h] of [...segHeads]) {
      const x = h.n ? null : segNoded.get(h.id);
      let under = h.head.nextElementSibling;
      if (x && under === x.host) under = under.nextElementSibling;
      if (h.head.isConnected && under && under.classList.contains('s3-round') && under.dataset.seg === h.id) continue;
      h.head.remove();
      segHeads.delete(k);
      if (x) { segNoded.delete(h.id); x.dispose(); }
    }
  }
  /* The operator's switches on a segment - folded shut, or shown as its
     nodes: its conversations are hidden where they stand, never removed, so
     they come back exactly as they were. */
  function applySeg(id) {
    const hide = segFold.has(id) || segNoded.has(id);
    for (const sec of feedBox.querySelectorAll(':scope > .s3-round')) if (sec.dataset.seg === id) sec.classList.toggle('s3-sgf-hide', hide);
    const first = segHeads.get(id + '#0'), x = segNoded.get(id);
    if (x && first && first.head.isConnected && first.head.nextElementSibling !== x.host) first.head.after(x.host);
    if (first) paintSegHead(first);
  }
  function foldSeg(id) {
    if (segFold.has(id)) segFold.delete(id); else segFold.add(id);
    applySeg(id);
  }
  /* "add an icon ... for converting the convo view ... into a nodal view of
     how the segment was constructed" (operator, 2026-09-28): the head's icon
     turns the segment into its node chain in place, and back */
  function toggleNodes(id) {
    const had = segNoded.get(id);
    if (had) { segNoded.delete(id); had.dispose(); applySeg(id); return; }
    unsync();                                              /* [s3-imsg] the operator is examining this segment */
    const host = el('div', {class: 's3-sgf-chain', 'data-seg': id});
    const x = {host, view: null, gone: false, dispose() { this.gone = true; host.remove(); if (this.view) this.view.dispose(); }};
    segNoded.set(id, x);
    applySeg(id);
    mountSegmentNodes(host, {request, segment: id}).then(view => { if (x.gone) view.dispose(); else x.view = view; }, () => {});
  }
  /* a block of the segment on show: the director's graph finds its entry from one */
  function segBlock(id) {
    for (const sec of feedBox.querySelectorAll(':scope > .s3-round')) {
      if (sec.dataset.seg !== id) continue;
      const e = feed.get(sec.dataset.conv);
      const l = e && (e.conv.lines || []).find(x => String(x.segment || '') === id && Number(x.block) > 0);
      if (l) return Number(l.block);
    }
    return 0;
  }
  /* "I also want to be able to expand and select and investigate and inspect
     other segments via the right click menu" (operator, 2026-09-28): what to
     do with a segment - inspect it (every conversation of it, node by node,
     down to its dice), pick another to inspect, its node view here, its fold,
     its entry on the director's running order. */
  function segMenu(id) {
    const s = segBook.get(id) || {id};
    const back = el('div', {class: 's3 s3-modal-back s3-hold-back'});
    const close = () => { back.remove(); document.removeEventListener('keydown', key, true); };
    const key = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const go = fn => () => { close(); fn(); };
    const flow = window.PineSegmentFlow, block = segBlock(id);
    const others = [...segBook.values()].filter(x => x && x.id && x.id !== id && x.start)
      .sort((a, b) => Number(b.start) - Number(a.start)).slice(0, 8);
    const items = [
      btn('Inspect this segment - every conversation in it, node by node, down to its dice', go(() => openSegmentInspector({request, segment: id}))),
      btn('Inspect other segments - pick one from the running order', go(() => openSegmentInspector({request, segment: id, pick: true}))),
      btn(segNoded.has(id) ? 'Back to the conversation' : 'Show it here as its nodes', go(() => toggleNodes(id))),
      btn(segFold.has(id) ? 'Unfold it' : 'Fold it away', go(() => foldSeg(id))),
      flow && typeof flow.openForSegment === 'function' && block
        ? btn("Its entry on the director's running order", go(() => { flow.openForSegment({block, round: String(s.kind || '')}).catch(() => {}); })) : null];
    const list = others.length ? el('div', 's3-sgf-others', el('b', {text: 'Other segments'}),
      ...others.map(o => btn(`${sgHm(o.start)} ${sgName(o)}${o.id === segNow ? ' - on air' : ''}`, go(() => openSegmentInspector({request, segment: o.id}))))) : null;
    back.append(movableModal(el('section', {class: 's3-modal s3-holdmenu s3-sgf-menu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this segment?'},
      el('b', {text: 'What would you like to do with this segment?'}),
      el('p', {class: 's3-muted', text: [sgName(s.label || s.kind ? s : {label: id}), s.start ? `${sgHm(s.start)} - ${sgHm(s.ends)}` : '',
        id === segNow ? 'on air now' : ''].filter(Boolean).join(' · ')}),
      el('div', 's3-holdmenu-items', ...items.filter(Boolean)), list, btn('Close', close))));
    back.addEventListener('click', e => { if (e.target === back) close(); });
    document.addEventListener('keydown', key, true);
    document.body.append(back);
  }
  const convTime = c => Number(c.created || (c.inputs || {}).at || 0);
  const byTime = () => [...feed.values()].sort((a, b) => convTime(a.conv) - convTime(b.conv));
  const sfxCount = (conv, t) => {
    const idx = scriptIndexOf(conv, t);
    return idx == null ? 0 : (conv.observations_air || []).filter(o => (o.family === 'SFX' || o.family === 'SFXGUY') && o.turn_index === idx).length;
  };
  /* [s3-messenger] the stings around a turn: their rows, their posters and rolls, their receipts */
  const boardSig = (conv, t) => {
    const slot = boardPlan(conv).get(t.turn_id);
    if (!slot) return '';
    return [...slot.before, ...slot.after].map(l => l.line_id + (l.poster ? 'p' : '') + (l.sfx_roll ? 'r' : '') +
      (airOn(v.air.get(l.line_id)) ? 'a' : airOff(v.air.get(l.line_id)) ? 'x' : '')).join(',');
  };
  const sigOf = (conv, t) => [lineText(conv, t) ? 'w' : '-', v.turnStatus(t, conv).word, sfxCount(conv, t),
    (t.speakerbox || []).map(s => s.mode + (s.material ? '+' : '')).join(','), v.open.has(t.turn_id) ? 'o' : '',
    boardSig(conv,t),airOfLines(turnLines(conv,t),v.air),window.PineSystem3MessageTile.decisionRows(turnEvents(conv,t)).map(window.PineSystem3MessageTile.rowKey).join(','),v.wordsOf(t,conv)].join('|');

  function roundHead(conv) {
    const lines = (conv.lines || []).length;
    const written = conv.turns.filter(t => lineText(conv, t)).length;
    const state = conv.status === 'planned' ? 'planned - waiting for the writer'
      : lines ? `${lines} line${lines === 1 ? '' : 's'} in the script`
        : written ? `${written} of ${conv.turns.length} turns written` : String(conv.status || '');
    return el('div', {class: 's3-round-head', 'data-conv': conv.identity.conversation_id, title: 'tap and hold (or right-click) for what to do with this conversation'},
      el('b', {text: conv.identity.road_kind}), el('span', {class: 's3-pill ' + conv.mode, text: conv.mode}),
      el('span', {class: 's3-muted', text: clock(convTime(conv))}),
      el('span', {class: 's3-round-state', text: state}),
      el('span', {class: 's3-round-topic', text: String((conv.subject || {}).topic || '').replace(/\s+/g, ' ').slice(0, 150)}),
      roundRolls(conv));
  }
  /* [s3-rewrite] THE ROUND'S OWN ROLLS, on its head: every decision recorded
     with no turn (the length, the tempers, the shock beat, the topic, the
     variant, whether it goes back to the writer, whether the Room may touch
     it, the tint pass being off) as a chip that opens its card. */
  function roundRolls(conv) {
    const pre = (conv.decision_events || []).filter(e => !e.turn_id && e.family && !e.stage && e.kind !== 'observation');
    if (!pre.length) return null;
    const chip = ev => {
      const c = chipOf(ev, conv);
      return el('span', {class: 's3-diamond' + (c.miss ? ' miss' : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`, 'data-event': ev.event_id,
        title: c.title, text: c.text, role: 'button', tabindex: '0',
        onclick: e => { e.stopPropagation(); openDecision(conv, ev, null, v.api); },
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }});
    };
    /* [s3-segment-feed] the station's own dice - dozens of them, rolled on the
       task before the round was planned - fold to one chip that opens them
       (and they stay open while the round is redrawn) */
    const id = conv.identity.conversation_id;
    const station = pre.filter(e => e.family === 'STATION');
    const box = el('div', {class: 's3-round-rolls', 'data-keep': ''}, ...pre.filter(e => e.family !== 'STATION').map(chip));
    if (station.length) {
      const open = stationOpen.has(id);
      box.append(el('span', {class: 's3-diamond s3-sgf-station' + (open ? ' open' : ''), style: `--fam:${FAM.STATION || 'var(--obs)'}`,
        role: 'button', tabindex: '0', 'aria-expanded': String(open),
        title: open ? "Fold the station's own rolls" : `The station rolled ${station.length} dice on this task before the round was planned - tap to open them`,
        text: open ? `STATION ${station.length} - fold` : `STATION · ${station.length} roll${station.length === 1 ? '' : 's'}`,
        onclick: e => { e.stopPropagation(); if (open) stationOpen.delete(id); else stationOpen.add(id); redrawHead(id); },
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }}));
      if (open) box.append(...station.map(chip));
    }
    return box;
  }
  /* a round's head drawn again where it stands */
  function redrawHead(id) {
    const entry = feed.get(id);
    if (!entry || !entry.headEl) return;
    const h = roundHead(entry.conv);
    entry.headEl.replaceWith(h);
    entry.headEl = h;
  }


  /* ---- [s3-imsg] THE THREAD: ONE ORDER, KEYED ON ITEMS ----------------------
     "The entire point of system three was to design things in a way where we
      are fully accountable of each and every message and therefore we can
      finally display things sequentially and follow things sequentially
      without erratically jumping the view around inserting messages
      willy-nilly in places that have already taken place." (operator,
      2026-09-28)
     Every node in the feed is an ITEM with a key (data-item): a turn (its
     id), a sting ('sfx:<line>'), or what hangs off a turn - the SFX Guy's
     plan ('plan:<event>'), a clip the station played ('clip:<obs>'), his
     line ('guy:<obs>'). Its PLACE is the station's commitment order, the
     script ledger's (block, ord) that the air executes: a turn at its first
     line, a sting at its own row, what hangs off a turn beside it; a turn
     not in the script yet after its round's last line; a round with no line
     yet after everything in the script, oldest first. `thread` is the order
     AS DRAWN, under the Script view's rule ([s3-script-linear]):
       1. at and above the item on air (`airHead`) nothing ever moves and
          nothing is ever put in;
       2. an item whose place is up there but is not drawn there - it came
          late: a round fetched after its neighbours, a re-ranked line, a
          sting or an interject filed late - goes directly BELOW the item on
          air, in the ledger's order;
       3. below that, everything in the ledger's order.
     The DOM follows the thread: each run of consecutive items of one round
     is a section.s3-round[data-conv] - the round's first run carries its
     head (.s3-round-head), a later run a slim one (.s3-round-cont) - so a
     round the air interleaves with another (an ad's parts around a station
     ID) reads in the order it airs. A round that will never air (withheld,
     abandoned, dropped, or no line long after it was planned) is not in the
     thread; the Technical view and the inspector still reach it. */
  let thread = [];                             /* item keys, top to bottom, as drawn */
  let lateSet = new Set();                     /* items put under the air by rule 2 */
  const nodes = new Map();                     /* item key -> its node */
  const ownerOf = new Map();                   /* item key -> its round's id */
  const outside = new Set();                   /* rounds that will never air */
  const NEVER = new Set(['withheld', 'abandoned', 'dropped']);
  const blockOf = c => { let b = Infinity; for (const l of c.lines || []) { const n = Number(l.block); if (n > 0 && n < b) b = n; } return b; };
  const ghost = c => blockOf(c) === Infinity && Date.now() / 1000 - convTime(c) > STALE_S;
  const inChain = c => !!c && c.mode !== 'simulation' && !NEVER.has(String(c.status || '')) && !ghost(c);
  const chatsOf = entry => [entry.chat, ...entry.runs.map(r => r.chat)];
  /* a node's item key: its own, or what it hangs off (a turn built again where it stands keeps its turn's) */
  function keyOfNode(n) {
    if (!n || n.nodeType !== 1) return '';
    if (n.dataset.item) return n.dataset.item;
    if (n.dataset.key) return n.dataset.key;
    if (n.classList.contains('building') && n.dataset.turn) return n.dataset.turn;
    if (n.classList.contains('s3-sfxplan') && n.dataset.event) return 'plan:' + n.dataset.event;
    const s = n.s3;
    if (s && s.obs) return v.obsKey(n.classList.contains('s3-sfxguy-line') ? 'guy' : 'clip', s.obs, s.t, s.played);   /* [s3-imsg] one key, makeViews' */
    return '';
  }
  /* [msgorder] THE LEDGER'S PLACE OF EACH ITEM, AND ONLY THE LEDGER'S:
     [block, ord, sub] - sub orders what shares a line: -1 hangs before it
     (a plan the turn's placement puts before it), 0 is the line's own
     message, 1 hangs after it, 2 a sting drawn off it. A spoken turn stands
     at its first spoken line; a later run or a sting at its own row; a turn
     the SFX board speaks airs as a board row stamped with its turn - that
     sting IS its message, so the turn card itself has no place, and what
     hangs off it hangs off the sting. null = the ledger has no place for it
     yet (planned, not written - most of an interject round's turns never
     are): it is not in the correspondence. The made-up places that stood
     here (a planned turn "after its round's last line", which is history)
     are what put roulette cards in the middle of what already aired. */
  const PLACES = new WeakMap();
  function placesOf(conv) {
    if (PLACES.has(conv)) return PLACES.get(conv);
    const lines = (conv.lines || []).filter(l => Number(l.block) > 0).sort(byLedger);
    const first = new Map(), rows = new Map(), board = new Map();
    for (const l of lines) {
      const at = [Number(l.block), Number(l.ord) || 0, 0];
      if (isSpoken(l)) { if (!first.has(l.turn_id)) first.set(l.turn_id, at); }
      else if (l.line_id) {
        rows.set('sfx:' + l.line_id, at);
        if (isBoard(l) && l.turn_id && !board.has(l.turn_id)) board.set(l.turn_id, at);
      }
    }
    /* [s3-imsg] a later run of a turn stands at its own first line */
    for (const t of conv.turns || []) {
      for (const part of (v.partsOf(conv, t) || []).slice(1)) {
        const l = part.lines[0];
        rows.set(part.key, [Number(l.block), Number(l.ord) || 0, 0]);
      }
    }
    const out = {first, rows, board, turns: new Map((conv.turns || []).map(t => [t.turn_id, t]))};
    PLACES.set(conv, out);
    return out;
  }
  /* where a turn's message stands: its first spoken line, else (a board turn) its sting; null when unwritten */
  function turnPlace(conv, turnId) {
    const p = placesOf(conv);
    return p.first.get(turnId) || p.board.get(turnId) || null;
  }
  function placeOf(entry, key, n) {
    const conv = entry.conv, p = placesOf(conv), turnId = n.dataset.turn || '';
    if ((key.startsWith('sfx:') || key.startsWith('part:')) && p.rows.has(key)) return p.rows.get(key);
    if (p.turns.has(key)) return p.first.get(key) || null;                 /* a board turn: its sting is its message */
    const host = turnPlace(conv, turnId), t = p.turns.get(turnId);
    if (!host) return null;
    const before = key.startsWith('plan:') && t && t.sfx && t.sfx.placement === 'before';
    return [host[0], host[1], key.startsWith('sfx:') ? 2 : before ? -1 : 1];
  }
  const cmpPlace = (x, y) => (x[0] - y[0]) || (x[1] - y[1]) || (x[2] - y[2]);
  /* [msgorder] out of sight while it has no place - kept, never removed, so it comes back as it was */
  function unplaced(n, off) {
    if (off) { if (n.dataset.unplaced !== '1') { n.dataset.unplaced = '1'; n.style.display = 'none'; } }
    else if (n.dataset.unplaced) { delete n.dataset.unplaced; n.style.display = ''; }
  }
  /* every item of the rounds in the thread, in the ledger's order */
  function collect() {
    const rows = [], seen = new Set();
    for (const entry of feed.values()) {
      if (entry.building) continue;                /* its nodes are moving: its keys keep their places */
      for (const chat of chatsOf(entry)) {
        for (const n of [...chat.children]) {
          const k = keyOfNode(n);
          if (!k) continue;
          if (seen.has(k)) { n.remove(); continue; }  /* one node per item */
          seen.add(k);
          const place = placeOf(entry, k, n);
          unplaced(n, !place);                         /* [msgorder] no place in the ledger: not in the thread */
          if (place) rows.push({key: k, entry, node: n, place, i: rows.length});
        }
      }
    }
    return rows.sort((a, b) => cmpPlace(a.place, b.place) || (a.i - b.i));
  }
  /* The rule, over keys: the drawn order down to the item on air, then the
     late ones, then the ledger's order. */
  function linearThread(keys, high) {
    const hi = high ? thread.indexOf(high) : -1;
    if (hi < 0) return {order: keys.slice(), late: new Set()};
    const sIx = new Map(keys.map((k, i) => [k, i]));
    const frozen = thread.slice(0, hi + 1).filter(k => feed.has(ownerOf.get(k)));
    let bound = sIx.has(high) ? sIx.get(high) : -1;
    for (let i = hi - 1; bound < 0 && i >= 0; i -= 1) if (sIx.has(thread[i])) bound = sIx.get(thread[i]);
    const fz = new Set(frozen), late = [], rest = [];
    for (const k of keys) { if (!fz.has(k)) (sIx.get(k) < bound ? late : rest).push(k); }
    return {order: [...frozen, ...late, ...rest], late: new Set(late)};
  }
  /* a round's later run: its own section with a slim head */
  function moreRun(entry, i) {
    while (entry.runs.length <= i) {
      const id = entry.conv.identity.conversation_id;
      const chat = el('div', 's3-chat');
      const headEl = el('div', {class: 's3-round-head s3-round-cont', 'data-conv': id, title: 'tap and hold (or right-click) for what to do with this conversation'},
        el('b', {text: entry.conv.identity.road_kind}), el('span', {class: 's3-muted', text: 'continues'}));
      entry.runs.push({section: el('section', {class: 's3-round s3-round-more', 'data-conv': id}, headEl, chat), chat, headEl});
    }
    return entry.runs[i];
  }
  /* The DOM brought to the thread. Only what is out of place moves, so at and
     above the air nothing is touched. */
  function layoutThread(rows) {
    const byKey = new Map(rows.map(r => [r.key, r]));
    /* [s3-segment-feed] each item's segment, and the runs: one per stretch of
       one conversation within one segment */
    const runs = [];
    let before = '';
    for (const k of thread) {
      const r = byKey.get(k);
      if (!r) continue;
      let seg = segOfItem(r.entry, k, r.node);
      if (seg === null) seg = segNow && (!before || segStart(segNow) >= segStart(before)) ? segNow : before;   /* not in the script yet: the segment on air */
      else if (!seg) seg = before;                                                                           /* no stamp: with the item before it */
      before = seg;
      const last = runs[runs.length - 1];
      if (last && last.entry === r.entry && last.seg === seg) last.nodes.push(r.node); else runs.push({entry: r.entry, seg, nodes: [r.node]});
    }
    const used = new Map(), stretch = new Map(), order = [];
    let open = null;
    for (const run of runs) {
      if (run.seg !== open) {                      /* a segment's stretch opens with its head (and its node view) */
        open = run.seg;
        if (open) {
          const n = stretch.get(open) || 0;
          stretch.set(open, n + 1);
          order.push(segHeadFor(open, n).head);
          const x = n ? null : segNoded.get(open);
          if (x) order.push(x.host);
        }
      }
      const e = run.entry, i = used.get(e) || 0;
      used.set(e, i + 1);
      const box = i === 0 ? {section: e.section, chat: e.chat} : moreRun(e, i - 1);
      if (box.section.dataset.seg !== run.seg) box.section.dataset.seg = run.seg;
      box.section.classList.toggle('s3-single', singleLine(e.conv));             /* an interjection is a message, never a section */
      box.section.classList.toggle('s3-sgf-hide', !!run.seg && (segFold.has(run.seg) || segNoded.has(run.seg)));
      order.push(box.section);
      let at = box.chat.firstElementChild;
      for (const n of run.nodes) {
        if (n === at) { at = at.nextElementSibling; continue; }
        box.chat.insertBefore(n, at);
      }
    }
    let prev = null;
    for (const x of order) {
      const want = prev ? prev.nextElementSibling : feedBox.firstElementChild;
      if (x !== want) feedBox.insertBefore(x, want);
      prev = x;
    }
    for (const e of feed.values()) {
      const n = used.get(e) || 0;
      unplaced(e.section, !n && !e.building);      /* [msgorder] nothing of it written yet: out of sight */
      while (e.runs.length > Math.max(0, n - 1)) e.runs.pop().section.remove();
    }
    /* heads of stretches the thread no longer has, node views of segments no longer on show */
    for (const [k, h] of [...segHeads]) if ((stretch.get(h.id) || 0) <= h.n) { h.head.remove(); segHeads.delete(k); }
    for (const [id, x] of [...segNoded]) if (!stretch.has(id)) { segNoded.delete(id); x.dispose(); }
  }

  /* [s3-imsg] the edge of what has happened: the later of where the air is and the newest message shown */
  function liveEdge() {
    let best = '', at = -1;
    for (const k of [airKey, shownKey, airHead]) { const i = k ? thread.indexOf(k) : -1; if (i > at) { at = i; best = k; } }
    /* [msgorder] and the last message on show that has aired, when that is
       further down: the air is often on a record or an ad no round owns, and
       a sting fetched after it aired must land under what is already there,
       never inside it (the feed filled at mount is drawn in the ledger's order) */
    if (!seeding) {
      for (let i = thread.length - 1; i > at; i -= 1) {
        const n = nodes.get(thread[i]);
        if (n && AIRED_STAGES.has(n.dataset.stage)) { at = i; best = thread[i]; break; }
      }
    }
    return best;
  }
  const AIRED_STAGES = new Set(['past', 'written', 'skipped', 'live']);
  let seeding = false;
  /* the thread worked out again and the DOM brought to it */
  function relayout() {
    if (replaying) return;                       /* a round building again where it stands: after it */
    const rows = collect();
    for (const r of rows) {
      if (r.node.dataset.item !== r.key) r.node.dataset.item = r.key;
      ownerOf.set(r.key, r.entry.conv.identity.conversation_id);
    }
    const got = linearThread(rows.map(r => r.key), liveEdge());
    thread = got.order;
    lateSet = got.late;
    nodes.clear();
    for (const r of rows) nodes.set(r.key, r.node);
    layoutThread(rows);
    seqCache = null;
    emptyBox.hidden = feed.size > 0;
  }
  function mountRound(conv) {
    const id = conv.identity.conversation_id;
    const entry = {conv, section: el('section', {class: 's3-round', 'data-conv': id}), headEl: roundHead(conv),
      chat: el('div', 's3-chat'), runs: [], building: false, dirty: false, pending: null, fetchedAt: Date.now(), airAt: Date.now(), sig: new Map()};
    entry.section.append(entry.headEl, entry.chat);
    feed.set(id, entry);
    feedBox.append(entry.section);                 /* [s3-imsg] its place is the thread's to give (relayout) */
    v.remember(conv);
    emptyBox.hidden = true;
    return entry;
  }
  /* [s3-imsg] a round that will never air leaves the thread - never from at
     or above the air (a round with anything there has aired) */
  function dropRound(entry) {
    const id = entry.conv.identity.conversation_id;
    const edge = liveEdge(), h = edge ? thread.indexOf(edge) : -1;
    if (h >= 0 && thread.some((k, i) => i <= h && ownerOf.get(k) === id)) return false;
    for (const s of [entry.section, ...entry.runs.map(r => r.section)]) s.remove();
    feed.delete(id);
    v.forget(id);
    thread = thread.filter(k => ownerOf.get(k) !== id);
    for (const [k, c] of [...ownerOf]) if (c === id) { ownerOf.delete(k); nodes.delete(k); }
    seqCache = null;
    relayout();
    return true;
  }

  function paintRound(entry) {
    seqCache = null;
    const old=new Map(chatsOf(entry).flatMap(chat=>[...chat.children]).map(node=>[keyOfNode(node),node]).filter(([key])=>key)),kept=new Set();
    for(const fresh of entry.conv.turns.flatMap(t=>v.turnNodes(entry.conv,t))){
      const was=old.get(keyOfNode(fresh));let node=fresh;
      if(was?.s3Tile&&fresh.s3Tile){v.syncTile(was,fresh);node=was;}
      else if(was){was.replaceWith(fresh);}
      kept.add(node);if(!node.parentNode)entry.chat.append(node);
    }
    for(const node of old.values())if(!kept.has(node))node.remove();
    for (const t of entry.conv.turns) entry.sig.set(t.turn_id, sigOf(entry.conv, t));
  }

  async function fetchRound(id, fresh = false) {
    const conv = await request('/api/system3/conversation/' + encodeURIComponent(id));
    if (conv.lines && conv.lines.length) for (const [k, x] of await v.inspectBlocks(conv, fresh)) v.air.set(k, x);
    return conv;
  }

  /* Rounds that arrive are added one message at a time, and one round at a
     time: the next round's first message waits for the last one's. */
  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (queue.length && v.alive) {
        const job = queue.shift();
        const id = job.conv.identity.conversation_id;
        if (feed.has(id)) continue;
        const entry = mountRound(job.conv);
        entry.building = true;
        grew();
        try {
          await v.buildRound(job.conv, entry.chat, {base: 420, quiet: true, live: () => v.alive && feed.get(id) === entry,
            grow: () => grew(), latest: () => entry.pending || entry.conv,
            settled: (c, t) => entry.sig.set(t.turn_id, sigOf(c, t))});
        } finally {
          entry.building = false;
          /* Whatever landed while it was building - words, script lines, the
             SFX Guy's plays - is drawn now, turn by turn, against what each
             message was actually built from. */
          const next = entry.pending || entry.conv;
          entry.pending = null;
          patchRound(entry, next);
          trim();
        }
      }
    } finally { pumping = false; }
  }

  async function addRound(id, {animate = false} = {}) {
    if (feed.has(id) || outside.has(id) || queue.some(j => j.conv.identity.conversation_id === id)) return;
    const conv = await fetchRound(id);
    if (feed.has(id) || queue.some(j => j.conv.identity.conversation_id === id)) return;
    if (!inChain(conv)) { if (NEVER.has(String(conv.status || ''))) outside.add(id); return; }   /* [s3-imsg] never to air: not in the thread */
    /* [msgorder] built in front of the operator only when every turn has its place in the air's order */
    if (animate && !reduced() && (conv.turns || []).every(t => turnPlace(conv, t.turn_id))) { queue.push({conv}); pump(); return; }
    const entry = mountRound(conv);
    paintRound(entry);
    relayout();
    trim();
    dressAir();
  }

  /* News for a round on show: only the turns whose words, status, SFX or
     speaker-box state moved are redrawn, where they stand. A turn that just
     got its words types them over its direction. Nothing here scrolls. */
  function patchRound(entry, next) {
    if(entry.building){entry.pending=next;v.remember(next);if(cid===next.identity.conversation_id)v.conv=next;
      const turns=new Map((next.turns||[]).map(t=>[t.turn_id,t]));
      for(const chat of chatsOf(entry))for(const node of [...chat.children])if(node.s3Tile){const turn=turns.get(node.dataset.turn);if(turn){const fresh=v.turnNodes(next,turn).find(item=>keyOfNode(item)===keyOfNode(node));if(fresh)v.syncTile(node,fresh);}}
      return;
    }
    const before = entry.conv;
    entry.conv = next;
    v.remember(next);
    if (cid === next.identity.conversation_id) v.conv = next;
    seqCache = null;
    if (!inChain(next) && dropRound(entry)) return;          /* [s3-imsg] withheld, abandoned or long gone: out of the thread */
    if (before.turns.map(t => t.turn_id).join() !== next.turns.map(t => t.turn_id).join()) {
      paintRound(entry);
    } else {
      for (const t of next.turns) {
        const sig = sigOf(next, t);
        const old = entry.sig.get(t.turn_id) || '';
        if (old === sig) continue;
        const rolling = rv && rv.phase === 'roll' ? itemNode(rv.key) : null;
        if (rolling && rolling.dataset.turn === t.turn_id) continue;     /* [s3-imsg] its dice are landing: drawn when they are down */
        const was = before.turns.find(x => x.turn_id === t.turn_id);
        const hadWords = old.startsWith('w|') || !!(was && lineText(before, was));
        const fresh = regroup(entry, t);                                   /* [s3-imsg] each item where it stands */
        const bubble = fresh.find(n => n.classList.contains('s3-msg') && !n.classList.contains('s3-sfxguy'));
        if (!hadWords && lineText(next, t) && bubble && !v.open.has(t.turn_id) && !['upcoming', 'live'].includes(bubble.dataset.stage)) {   /* [s3-messenger] */
          const words = bubble.querySelector('.s3-words');
          bubble.classList.add('arriving');
          if (words && !reduced()) typewriter(words, words.textContent);
          setTimeout(() => bubble.classList.remove('arriving'), 2800);
        }
        if (sfxCount(next, t) > Number(old.split('|')[2] || 0)) {
          for (const n of fresh) if (n.classList.contains('s3-sfxguy')) n.classList.add('arriving');
        }
        entry.sig.set(t.turn_id, sig);
      }
    }
    const h = roundHead(next);
    entry.headEl.replaceWith(h);
    entry.headEl = h;
    relayout();                                                            /* [s3-imsg] the thread's order, the air's rule */
    dressAir();
  }
  /* [s3-imsg] One turn's items drawn again where each stands (`only`: just
     those keys); what the turn no longer has goes, what is new is put by it
     for the thread to place; the item whose dice are landing is left alone. */
  function regroup(entry, t, only = null) {
    const fresh = v.turnNodes(entry.conv, t);
    const old = new Map();
    for (const chat of chatsOf(entry)) {
      for (const n of chat.children) if (n.dataset && n.dataset.turn === t.turn_id) { const k = keyOfNode(n); if (k && !old.has(k)) old.set(k, n); }
    }
    const rolling = rv && rv.phase === 'roll' ? rv.key : '';
    const seen = new Set();
    let last = null;
    for (const f of fresh) {
      const k = keyOfNode(f);
      seen.add(k);
      const was = old.get(k);
      if (was && ((only && !only.has(k)) || (k === rolling && !was.s3Tile) || (v.assembling.has(k) && !was.s3Tile))) { last = was; continue; }   /* [s3-imsg] coming together again: after */
      if (was) { if(v.syncTile(was,f)){last=was;fresh[fresh.indexOf(f)]=was;continue;}v.keepPaint(was, f); holdHeight(was, f); }
      else if (last) last.after(f);
      else { const first = old.values().next().value; if (first) first.before(f); else entry.chat.append(f); }
      last = f;
    }
    if (!only) for (const [k, n] of old) if (!seen.has(k) && k !== rolling && !v.assembling.has(k)) n.remove();
    return fresh;
  }

  /* [s3-messenger] Rounds go from the top, above the air only: a round at
     or after the line on air (what is airing, what comes next) is never
     dropped, and a round the operator holds (a pick, an open line) is kept.
     [s3-imsg] Only a round wholly at the top of the thread, and not while
     the operator is looking at it. */
  const UNPLACED_MAX = 12;         /* [msgorder] rounds with nothing written yet, kept out of sight */
  function trim() {
    /* [msgorder] a round with nothing in the thread waits out of sight: not
       counted, and only the newest UNPLACED_MAX are kept (the oldest were
       planned and never written) */
    const placed = new Set(thread.map(k => ownerOf.get(k)));
    const waiting = [...feed.values()].filter(e => !e.building && !placed.has(e.conv.identity.conversation_id))
      .sort((a, b) => convTime(a.conv) - convTime(b.conv));
    while (waiting.length > UNPLACED_MAX) {
      const e = waiting.shift(), id = e.conv.identity.conversation_id;
      for (const s of [e.section, ...e.runs.map(r => r.section)]) s.remove();
      feed.delete(id);
      v.forget(id);
    }
    while (feed.size - waiting.length > FEED_MAX) {
      const edge = liveEdge(), h = edge ? thread.indexOf(edge) : thread.length;
      const held = e => e.building || e.conv.turns.some(t => t.turn_id === v.sel.turn || v.open.has(t.turn_id) ||
        (typeof v.dropOpen === 'function' && v.dropOpen(t.turn_id)));
      /* the round at the very top, and only when all of it is above the air - never one out of the middle */
      const lastAt = new Map();
      thread.forEach((k, i) => { const e = feed.get(ownerOf.get(k)); if (e) lastAt.set(e, i); });
      const topKey = thread.find(k => feed.has(ownerOf.get(k)));
      const victim = topKey ? feed.get(ownerOf.get(topKey)) : null;
      if (!victim || (lastAt.get(victim) ?? Infinity) >= h || held(victim)) break;
      const secs = [victim.section, ...victim.runs.map(r => r.section)];
      const box = root.getBoundingClientRect();
      const above = secs.every(s => !s.isConnected || s.getBoundingClientRect().bottom <= box.top + 1);
      if (!above && !follow && current === 'conversation') break;   /* in sight of an operator looking: it stays */
      const keep = root.scrollHeight - root.scrollTop;          /* dropping from above the view keeps the view still */
      const id = victim.conv.identity.conversation_id;
      for (const s of secs) s.remove();
      pruneSegHeads();                                /* [s3-segment-feed] a head with nothing left under it goes too */
      feed.delete(id);
      v.forget(id);
      thread = thread.filter(k => ownerOf.get(k) !== id);
      for (const [k, c] of [...ownerOf]) if (c === id) { ownerOf.delete(k); nodes.delete(k); }
      seqCache = null;
      if (above) { selfUntil = Date.now() + 120; root.scrollTop = root.scrollHeight - keep; }
    }
  }

  async function seed() {
    seeding = true;                                /* [msgorder] the first fill: the ledger's order, whole */
    await Promise.race([readSegs(true), sleep(2500)]);   /* [s3-segment-feed] the segments' names before the first section */
    let rows = [];
    try { rows = (await request('/api/system3/conversations?limit=4')).conversations || []; } catch (e) { rows = []; }
    for (const row of rows.slice().reverse()) {
      if (row.mode === 'simulation' || NEVER.has(String(row.status || ''))) continue;   /* [s3-imsg] never to air */
      try { await addRound(row.conversation_id); } catch (e) { /* that round is skipped */ }
    }
    if (cid && !feed.has(cid)) { try { await addRound(cid); } catch (e) { /* keep going */ } }
    seeding = false;                               /* [msgorder] from here on, what arrives lands under what is there */
    paintHead();
    if (follow) toAnchor(false);                   /* [s3-imsg] synced: the latest message; not, nothing moves */
  }

  /* Rounds with news are fetched again (at most every 3 s each); the newest
     round is looked at every 10 s while it is still being written, and a
     round in the script has its heard receipts read every 15 s until every
     line has aired or gone. */
  async function refresh() {
    const now = Date.now();
    const newest = byTime().pop();
    for (const job of queue) {
      if (job.dirty && now - (job.fetchedAt || 0) > 3000) {
        try { job.conv = await fetchRound(job.conv.identity.conversation_id); job.fetchedAt = Date.now(); job.dirty = false; } catch (e) { /* later */ }
      }
    }
    for (const entry of [...feed.values()]) {
      if (!entry.building && !inChain(entry.conv) && dropRound(entry)) continue;     /* [s3-imsg] a plan long gone unbound */
      const lines = (entry.conv.lines || []).length;
      const settled = lines > 0 && entry.conv.turns.every(t => {
        const st = v.turnStatus(t, entry.conv);
        return !st.line || /heard|withdrawn/.test(st.word);
      });
      const due = entry.dirty ? now - entry.fetchedAt > 3000 : (entry === newest && !settled && now - entry.fetchedAt > 10000);
      const airDue = lines > 0 && !settled && now - entry.airAt > 15000;
      if (!due && !airDue) continue;
      try {
        let next = entry.building ? (entry.pending || entry.conv) : entry.conv;
        if (due) {
          next = await request('/api/system3/conversation/' + encodeURIComponent(entry.conv.identity.conversation_id));
          entry.fetchedAt = Date.now();
          entry.dirty = false;
        }
        if ((next.lines || []).length) {
          for (const [k, x] of await v.inspectBlocks(next, true)) v.air.set(k, x);
          entry.airAt = Date.now();
        }
        patchRound(entry, next);
      } catch (e) { /* tried again on the next pass */ }
    }
  }

  const onScreen = () => root.isConnected && !document.hidden && root.getClientRects().length > 0;
  function schedule(ms) { clearTimeout(timer); if (v.alive) timer = setTimeout(poll, ms); }
  async function poll() {
    if (!v.alive) return;
    if (busy || !onScreen()) { schedule(2500); return; }
    busy = true;
    let again = 2500;
    try {
      if (cursor == null) {
        const top = await request('/api/system3/events?after=0&limit=1');
        cursor = Number(top.head || 0);
        await seed();
      } else {
        const got = await request('/api/system3/events?' + new URLSearchParams({after: cursor, limit: 300}));
        cursor = Number(got.cursor || cursor);
        const news = new Map();
        for (const ev of got.events || []) {
          if (!ev.conversation_id) continue;
          const n = news.get(ev.conversation_id) || {decisions: 0, observations: 0};
          n[ev.kind === 'decision' ? 'decisions' : 'observations'] += 1;
          news.set(ev.conversation_id, n);
        }
        for (const [id, n] of news) {
          const entry = feed.get(id);
          const job = queue.find(j => j.conv.identity.conversation_id === id);
          if (entry) entry.dirty = true;
          else if (job) job.dirty = true;
          else if (n.decisions) {
            try { await addRound(id, {animate: true}); } catch (e) { /* the next poll tries again */ }
            if (current === 'rolodex') { cid = id; const e2 = feed.get(id) || queue.find(j => j.conv.identity.conversation_id === id);
              if (e2) { v.conv = e2.conv; v.remember(e2.conv); paintBody(); } }
          }
        }
        if ((got.events || []).length >= 300) again = 250;
      }
      await refresh();
      readSegs(segsWant && Date.now() - segsAt > 5000);   /* [s3-segment-feed] */
      paintHead();
    } catch (e) {
      again = 6000;
    } finally { busy = false; }
    schedule(again);
  }

  /* ---- the air ----------------------------------------------------------- */
  function nodesFor(turnId) {
    const pane = current === 'rolodex' ? v.paneB : v.paneA;
    if (!turnId) return [];
    const q = CSS.escape(turnId);
    return [...pane.querySelectorAll('.s3-msg[data-turn="' + q + '"]:not(.s3-sfxguy), .s3-turnhead[data-turn="' + q + '"]')];
  }

  /* The ON AIR mark on the item the host's focus is on; in the Technical
     view, the turn heads before it past, and struck out only when the air's
     own receipt says the turn was withdrawn or cut. [s3-messenger] */
  function dressAir() {
    if (current === 'conversation') restage();
    const c = [...feed.values()].map(e => e.conv).find(x => x.turns.some(t => t.turn_id === liveTurn)) || v.conv;
    if (current === 'rolodex' && c) {
      const order = c.turns.map(t => t.turn_id);
      const at = order.indexOf(liveTurn);
      for (const t of c.turns) {
        const i = order.indexOf(t.turn_id);
        const off = airOfLines(turnLines(c, t), v.air) === 'off';
        for (const n of nodesFor(t.turn_id)) {
          n.classList.toggle('onair', t.turn_id === liveTurn);
          n.classList.toggle('past', at >= 0 && i < at && !off);
          n.classList.toggle('skipped', off);
          if (off) n.title = 'not heard: withdrawn or cut before air';
        }
      }
    }
    const mark = current === 'rolodex' ? null : itemNode(liveKey);
    for (const n of (current === 'rolodex' ? v.paneB : v.paneA).querySelectorAll('.onair')) {
      if (current === 'rolodex' ? n.dataset.turn !== liveTurn : n !== mark) n.classList.remove('onair');
    }
    if (mark) mark.classList.add('onair');
    const t = c && c.turns.find(x => x.turn_id === liveTurn);
    /* [s3-imsg] the pill is the sync switch: always there in the Messenger, the turn on air on it */
    onAir.hidden = !t && current !== 'conversation';
    syncText.textContent = !t ? 'latest message' : liveKey.startsWith('sfx:') ? 'on air: a sting after turn ' + (t.index + 1)
      : 'on air: turn ' + (t.index + 1) + ' · ' + (t.name || t.speaker);
    if (current === 'conversation') dressThread();
    paintJump();
  }

  /* [s3-imsg] THE FUTURE IS BELOW AND FADED. "I almost don't even want to
     see the entries in the future after it because that doesn't happen in a
     text message. If I scroll down to reveal that stuff, it should show up
     and be slightly faded out. So that way I know that this is for a future
     that hasn't happened yet. And I'm able to see the technical scaffolding
     of everything that's assembled for the future." (operator, 2026-09-28)
     Everything after the item on air - its cards, what hangs off them - is
     .s3-future; a section with nothing but future in it (a round still to
     come) is faded whole. The item on air never is, from its first die. And
     a line the air's own receipt says was withdrawn or cut is ONE QUIET LINE
     where it stood (.s3-gone), opened by a tap on it. */
  const goneOpen = new Set();                  /* withdrawn lines the operator opened */
  function isOff(n) {
    const key = n.dataset.key || '';
    if (key.startsWith('sfx:')) return airOff(v.air.get(n.dataset.line || key.slice(4)));
    const turnId = n.dataset.turn || key;
    const conv = v.convOf({turn_id: turnId});
    const t = conv && (conv.turns || []).find(x => x.turn_id === turnId);
    return !!t && airOfLines(v.linesOf(key, conv, t), v.air) === 'off';     /* [s3-imsg] a run: its own lines */
  }
  function goneDress(n, key) {
    const off = !!n.dataset.key && n.dataset.key !== airHead && isOff(n);      /* never the item on air */
    const open = off && goneOpen.has(key);
    n.classList.toggle('s3-gone', off);
    n.classList.toggle('s3-gone-open', open);
    const who = n.querySelector(':scope > .who');
    let tag = who ? who.querySelector(':scope > .s3-gone-tag') : null;
    if (!off) { if (tag) tag.remove(); return; }
    if (!who) return;
    if (!tag) {
      tag = el('button', {type: 'button', class: 's3-gone-tag', onclick: e => {
        e.stopPropagation();
        if (goneOpen.has(key)) goneOpen.delete(key); else goneOpen.add(key);
        dressThread();
      }});
      who.insertBefore(tag, who.querySelector(':scope > .s3-drop-btn'));
    }
    const text = n.dataset.stage === 'upcoming' ? 'withdrawn - it will not air' : 'withdrawn - never aired';
    if (tag.textContent !== text) tag.textContent = text;
    tag.setAttribute('aria-expanded', String(open));
    tag.title = (open ? 'Close it' : 'Open it') + ': ' + (n.title || 'withdrawn or cut before air');
  }
  function dressThread() {
    const lit = rv ? rv.key : '';
    const pos = seqPos(), shown = shownKey && pos.has(shownKey) ? pos.get(shownKey) : null;
    for (const sec of feedBox.children) {
      const chat = sec.querySelector(':scope > .s3-chat');
      let any = 0, ahead = 0;
      for (const n of chat ? chat.children : []) {
        const key = keyOfNode(n);
        if (!key) continue;
        any += 1;
        /* after the newest message shown, it has not happened here yet; before
           any has been shown, the receipts say (what hangs off a turn goes with it) */
        const at = pos.get(key);
        const host = n.dataset.key ? n : (itemNode(n.dataset.turn || '') || n);
        const future = shown != null && at != null ? at > shown : host.dataset.stage === 'upcoming' && (host.dataset.key || '') !== lit;
        n.classList.toggle('s3-future', future);
        if (future) ahead += 1;
        goneDress(n, key);
      }
      sec.classList.toggle('s3-future', any > 0 && ahead === any);
    }
  }
  /* where the operator was looking in the Messenger: the first item in sight and how far down the view it sat */
  function viewMark() {
    const box = root.getBoundingClientRect(), top = box.top + cover();
    for (const k of thread) {
      const n = itemNode(k);
      const r = n ? n.getBoundingClientRect() : null;
      if (r && r.height && r.bottom > top) return {key: k, y: r.top - box.top, top: root.scrollTop};
    }
    return {key: '', y: 0, top: root.scrollTop};
  }
  function viewBack(m) {
    if (!m) return;
    const n = m.key ? itemNode(m.key) : null;
    ownScroll(false);
    if (n) root.scrollTop += n.getBoundingClientRect().top - root.getBoundingClientRect().top - m.y;
    else root.scrollTop = m.top;
  }
  let msgMark = null;

  /* The Technical view follows the lit turn of the round on show, gently -
     [s3-imsg] only while synced, like the Messenger. */
  function placeRolodex(force) {
    if (current !== 'rolodex' || !liveTurn) return;
    if (!force && (!follow || handOn())) return;
    const target = nodesFor(liveTurn)[0];
    if (!target) return;
    ownScroll(true);
    target.scrollIntoView({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'});
  }

  /* ---- [s3-messenger] THE AIR, ONE LINE AT A TIME ----------------------------
     "upcoming showed as their roulette RNG then transitioning to as written.
      I want them popping one at a time becoming text live with the audio
      showing a loading bar going across each entry during playback as they
      take place sequentially." (operator, 2026-09-28)
     The feed is one sequence in the order the air takes: each round's turns
     in order, each sting after the line before it. `airHead` is the furthest
     item the air has reached. Before it everything is drawn written (past);
     after it everything is its roulette card. When the air reaches a new
     item (face.live) the one before it is finished at once - its words
     whole, its bar full - anything the view did not see air is drawn
     written, and the new one pops: [s3-imsg] its dice land one after
     another (landInOrder), all hold still on their numbers for
     DICE_HOLD_MS, and only then does it turn into its message (a sting: its
     poster pops), the words typing from the first
     character and catching the audio up within CATCH_MS, then keeping
     step with it (face.clock: this line's own position and length; the
     turn's earlier lines are already whole). The air moving on while the
     dice come down brings them down fast; the next item waits for them.
     With no clock the words come at about 14 characters a second, so they never stall.
     Every tick touches the one live node, nothing else. The host's focus
     can go BACK (a line tapped in the script): the ON AIR mark follows it,
     nothing is re-played and nothing already shown is hidden again. */
  const PACE = 14, CLOCK_FRESH = 2500, CATCH_MS = 1600;
  let clockAt = {line: '', at: 0, total: 0, when: 0};
  let airHead = '';                  /* the item whose reveal ran last (the message on air) */
  let rv = null;                     /* the reveal running on the head */
  let raf = 0;
  const doneBars = new Set();        /* items that played out here: their bar stays, full */
  const mmss = x => { const n = Math.max(0, Math.floor(Number(x) || 0)); return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0'); };
  const sfxKey = l => 'sfx:' + l.line_id;
  /* every item on show -> its place in the air's order: [s3-imsg] its place in the thread */
  function seqPos() {
    if (seqCache) return seqCache;
    seqCache = new Map(thread.map((k, i) => [k, i]));
    return seqCache;
  }
  function itemNode(key) {
    if (!key) return null;
    const n = nodes.get(key);
    if (n && v.paneA.contains(n)) return n;
    const q = CSS.escape(key);
    const m = v.paneA.querySelector(key.startsWith('sfx:') ? '.s3-sfxnode[data-key="' + q + '"]'
      : '.s3-msg[data-key="' + q + '"]:not(.s3-sfxguy), .s3-feed [data-item="' + q + '"]');
    if (m) nodes.set(key, m);
    return m;
  }
  function itemAt(key) {
    for (const entry of feed.values()) {
      if (key.startsWith('sfx:')) {
        for (const [tid, slot] of boardPlan(entry.conv)) {
          const before = slot.before.find(l => sfxKey(l) === key), line = before || slot.after.find(l => sfxKey(l) === key);
          if (line) return {entry, conv: entry.conv, t: entry.conv.turns.find(x => x.turn_id === tid), line, side: before ? 'before' : 'after'};
        }
        continue;
      }
      if (key.startsWith('part:')) {                /* [s3-imsg] a later run of a turn */
        const row = (entry.conv.lines || []).find(x => x.line_id === key.slice(5));
        const t = row && (entry.conv.turns || []).find(x => x.turn_id === row.turn_id);
        const part = t && (v.partsOf(entry.conv, t) || []).find(x => x.key === key);
        if (part) return {entry, conv: entry.conv, t, line: null, part};
        continue;
      }
      const t = (entry.conv.turns || []).find(x => x.turn_id === key);
      if (t) return {entry, conv: entry.conv, t, line: null, part: (v.partsOf(entry.conv, t) || [])[0] || null};
    }
    return null;
  }

  /* the stage of any item, from the air's head (the window's receipts-only
     reading while the air has not been seen yet) */
  v.sequenced = true;
  v.stageOf = (key, conv, t) => {
    const base = v.airStage(key, conv, t);
    if (!conv || conv.mode === 'shadow' || conv.mode === 'simulation') return 'written';
    if (v.replayAs.has(key)) return v.replayAs.get(key);       /* [s3-imsg] a message coming together again (its play button) */
    if (rv && rv.key === key) return rv.phase === 'roll' ? 'upcoming' : 'live';
    /* [s3-imsg] what has appeared (up to the newest message shown) is past;
       what has not is its card - still to come, or waiting its turn to appear */
    if (!shownKey) return base;
    const pos = seqPos(), at = pos.get(key), s = pos.get(shownKey);
    if (at == null || s == null) return base;
    if (at > s) return 'upcoming';
    return base === 'skipped' ? 'skipped' : lateSet.has(key) && base === 'written' ? 'written' : 'past';
  };
  const charsOf=(r,len)=>tileEngineCount(r,len);
  function tileEngineCount(r,len){return Math.min(len,window.PineSystem3MessageTile.typeCount(Math.max(0,r.n||0),r.k>=1?1:r.k,len));}
  v.revealed = (key, len) => (rv && rv.key === key && rv.phase === 'words' ? charsOf(rv, len) : len);
  /* the bar goes across the message, inside it, along its bottom edge; its
     clock sits small in the header line */
  v.dressItem = (node, key, stg) => {
    const bubble = [...node.children].find(n => n.classList.contains('s3-bubble'));
    if (!bubble || (stg !== 'live' && !(stg === 'past' && doneBars.has(key)))) return;
    const live = stg === 'live';
    bubble.classList.add('has-bar');
    let bar=bubble.querySelector(':scope > .s3-airbar');if(!bar){bar=el('div',{'aria-hidden':'true'},el('i'));bubble.append(bar);}bar.className='s3-airbar'+(live?'':' done');bar.style.setProperty('--k',(live&&rv?barOf(rv,performance.now()):1).toFixed(4));
    const who = node.querySelector(':scope > .who');
    if(live&&who&&!who.querySelector('.s3-airclock'))who.append(el('span',{class:'s3-airclock','aria-hidden':'true'}));
    const words = live && bubble.querySelector(':scope > .s3-words');
    if (words && rv && rv.text && rv.k < 1) words.classList.add('typing');
  };

  /* Where the audio is in the item on air, 0..1: this line's clock over the
     turn's lines, each weighted by its words; null with no fresh clock. */
  function clockK(r, now) {
    const c = clockAt;
    if (!(c.total > 0) || now - c.when > CLOCK_FRESH || !r.idx.has(c.line)) return null;
    const i = r.idx.get(c.line);
    const at = Math.max(0, Math.min(c.total, c.at + Math.min(1, (now - c.when) / 1000)));   /* between two ticks the clip plays on */
    return Math.min(1, (r.before[i] + r.w[i] * (at / c.total)) / r.sum);
  }
  const barOf = (r, now) => { const k = clockK(r, now); return k == null ? r.k : Math.max(k, r.bar || 0); };
  function stepK(r, now) {
    const k = clockK(r, now);
    let next = k != null ? k : r.k + Math.max(0, now - r.lastT) / 1000 / r.secs;      /* no clock: paced */
    r.lastT = now;
    if (k != null) {
      r.bar = Math.max(r.bar || 0, k);
      /* [s3-imsg] behind the audio (its dice took their time): the words type
         up to it from where they stand, easing into its pace within CATCH_MS
         - never a jump. Reduced motion: where the audio is, at once. */
      if (!r.chase && !reduced() && (k - r.k) * Math.max(1, r.text.length || 40) > 3) r.chase = {from: r.k, t0: now};
      if (r.chase) {
        const f = Math.min(1, (now - r.chase.t0) / CATCH_MS);
        next = r.chase.from + (k - r.chase.from) * f * (1 + f - f * f);
        if (f >= 1) r.chase = null;
      }
    }
    r.k = Math.max(r.k, Math.min(1, next));
  }
  function paintReveal(now) {
    const r = rv;
    if (!r || r.phase !== 'words') return;
    if (!r.node || r.node.dataset.key !== r.key || r.node.dataset.stage !== 'live' || !v.paneA.contains(r.node)) r.node = itemNode(r.key);
    const node = r.node;
    if (!node || node.dataset.stage !== 'live' || node.dataset.replaying || node.s3Tile?.seq) return;
    const words = r.text ? node.querySelector(':scope > .s3-bubble > .s3-words') : null;
    if (words) {
      const n = charsOf(r, r.text.length);
      const tn = words.childNodes.length === 1 && words.firstChild.nodeType === 3 ? words.firstChild : null;
      if (tn && n > tn.data.length && r.text.startsWith(tn.data)) tn.appendData(r.text.slice(tn.data.length, n));   /* [s3-imsg] added to: words selected in it stay selected */
      else if (n !== r.n || words.textContent.length !== n) words.textContent = r.text.slice(0, n);
      r.n = n;
      if (n >= r.text.length) words.classList.remove('typing');
    }
    const bar = node.querySelector(':scope > .s3-bubble > .s3-airbar');
    if (bar) bar.style.setProperty('--k', barOf(r, now).toFixed(4));
    const label = node.querySelector(':scope > .who > .s3-airclock');
    if (label) {
      const c = clockAt, fresh = c.total > 0 && now - c.when < CLOCK_FRESH && r.idx.has(c.line);
      const text = fresh ? mmss(c.at) + ' / ' + mmss(c.total) : '';
      if (label.textContent !== text) label.textContent = text;
    }
  }
  function frame() {
    raf = 0;
    if (!rv || rv.phase !== 'words' || !v.alive) return;
    const now = performance.now();
    stepK(rv, now);
    paintReveal(now);
    if (rv.k < 1 || (rv.text.length && rv.n < rv.text.length)) raf = requestAnimationFrame(frame);
  }
  function tickReveal() {
    if (!rv || rv.phase !== 'words') return;
    const now = performance.now();
    stepK(rv, now);
    paintReveal(now);
    if (!raf && (rv.k < 1 || (rv.text.length && rv.n < rv.text.length))) raf = requestAnimationFrame(frame);
    if (rv.line) liveMedia();
  }

  /* The item on air finished where it stands: its words whole, its bar
     full and quiet. In place - its clip, if one is playing, plays on. */
  function finishReveal() {
    const r = rv;
    if (!r) return;
    rv = null;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    doneBars.add(r.key);
    if (doneBars.size > 600) doneBars.delete(doneBars.values().next().value);
    const node = r.phase === 'words' ? itemNode(r.key) : null;
    if (!node || node.dataset.stage !== 'live') return;          /* still its card: the restage draws it whole */
    const words = r.text ? node.querySelector(':scope > .s3-bubble > .s3-words') : null;
    if (words) { words.textContent = r.text; words.classList.remove('typing'); }
    node.classList.remove('live');
    node.classList.add('past');
    node.dataset.stage = 'past';
    const bar = node.querySelector(':scope > .s3-bubble > .s3-airbar');
    if (bar) { bar.classList.add('done'); bar.style.setProperty('--k', '1'); }
    const label = node.querySelector(':scope > .who > .s3-airclock');
    if (label) label.remove();
  }

  /* Apply the air's stage to each retained shared tile. Older status rows
     can still refresh through their existing renderer. */
  const WHOLE = ['written', 'past', 'skipped'];
  function restage(again = false) {
    let redrawn = false;
    for (const entry of feed.values()) {
      if (entry.building) continue;
      const redo = new Map();                      /* [s3-imsg] turn -> the items of it to draw again */
      for (const chat of chatsOf(entry)) for (const n of chat.querySelectorAll(':scope > [data-key]')) {
        if (n.dataset.replaying) continue;
        const t = entry.conv.turns.find(x => x.turn_id === n.dataset.turn);
        if (!t) continue;
        const want = v.stageOf(n.dataset.key, entry.conv, t), have = n.dataset.stage || 'written';
        if (want === have) continue;
        if(n.s3Tile){v.tileStage(n,want);continue;}
        if (WHOLE.includes(want) && WHOLE.includes(have) && !(want === 'past' && doneBars.has(n.dataset.key))) {
          n.classList.toggle('past', want === 'past');
          n.classList.toggle('skipped', want === 'skipped');
          n.dataset.stage = want;
          if (want === 'skipped') n.title = 'not heard: withdrawn or cut before air';
          continue;
        }
        if (!redo.has(t)) redo.set(t, new Set());
        redo.get(t).add(n.dataset.key);
      }
      for (const [t, keys] of redo) { regroup(entry, t, keys); redrawn = true; }
    }
    if (redrawn) { relayout(); if (!again) restage(true); }   /* anything new by them takes its place, then its stage */
  }
  /* Reveal words/media in the retained tile; its category/subcategory rows stay. */
  function swapItem(key) {
    const it = itemAt(key);
    const node = itemNode(key);
    if (!it || !it.t || !node) return null;
    if(node.s3Tile){v.tileStage(node,v.stageOf(key,it.conv,it.t));nodes.set(key,node);return node;}
    const fresh = it.line ? v.sfxRows(it.conv, it.t)[it.side].find(n => n.dataset && n.dataset.key === key)
      : v.bubble(it.t, {conv: it.conv, part: it.part || null});
    if (!fresh) return null;
    v.keepPaint(node, fresh);
    fresh.dataset.item = key;                      /* [s3-imsg] the same item, in the same place, never shorter */
    holdHeight(node, fresh);
    nodes.set(key, fresh);
    return fresh;
  }

  /* A line id -> its row and the round on show that holds it (the round
     the host last showed, when the feed does not). */
  function lineRow(lineId) {
    for (const e of feed.values()) {
      const row = (e.conv.lines || []).find(l => l.line_id === lineId);
      if (row) return {row, owner: e};
    }
    const row = v.conv ? (v.conv.lines || []).find(l => l.line_id === lineId) : null;
    return {row: row || null, owner: null};
  }
  /* a row -> its item in the sequence (a sting is its own; a spoken line is
     its turn's) and the turn the ON AIR pill names */
  function itemOfRow(row, conv) {
    let key = '', turnId = row.turn_id || '';
    if (isBoard(row)) {
      key = sfxKey(row);
      for (const [tid, slot] of boardPlan(conv)) if (slot.before.includes(row) || slot.after.includes(row)) turnId = tid;
    } else if (isSpoken(row)) {
      key = row.turn_id;
      /* [s3-imsg] a line of a turn the air takes in runs: its own run */
      const t = (conv.turns || []).find(x => x.turn_id === row.turn_id);
      const part = t && (v.partsOf(conv, t) || []).find(x => x.lines.some(l => l.line_id === row.line_id));
      if (part) key = part.key;
    }
    return {key, turnId};
  }
  let liveOwned = false, pending = '', pendingAt = 0, clockLine = '';
  /* The host's focus is the line on air - or a line tapped in the script
     while its card is open, which can be BEHIND the air or AHEAD of it. The
     clock is always the line sounding, so it decides: the focus moves the
     air only when it is the line sounding, or, with nothing sounding (no
     clock), when it is the next few items on, or has stayed put 4 s. A line
     tapped ahead while the audio plays marks ON AIR and reveals nothing.
     True when there is nothing more to decide for it. */
  function tryReach(key, lineId) {
    const pos = seqPos(), at = pos.get(key), h = airKey ? pos.get(airKey) : null;
    if (at == null || (h != null && at <= h)) return true;       /* reached already, or behind the air */
    const c = clockAt, sounding = c.total > 0 && performance.now() - c.when < CLOCK_FRESH;
    if (sounding ? c.line !== lineId : (h != null && at > h + 3 && performance.now() - pendingAt < 4000)) return false;
    airReached(key);
    return true;
  }

  /* The air reached `key` (a line of it is on air). [s3-imsg] The
     messages up to it appear in their rhythm (release); a card whose dice
     are still coming down when the air moves past it brings them down fast. */
  function airReached(key) {
    const pos = seqPos();
    const at = pos.get(key), a = airKey && pos.has(airKey) ? pos.get(airKey) : -1;
    if (at == null || at <= a) return;                       /* at or behind the air: the operator's focus, nothing re-plays */
    airKey = key;
    if (rv && rv.phase === 'roll' && rv.seq) rv.seq.hurry();  /* never two at once */
    release();
  }

  /* ---- [s3-imsg] ONE MESSAGE AT A TIME, WITH A GRACE ---------------------------
     "the goal for me is that the view animates message to message like a
      messenger window. So there's a grace between one message appearing and
      then another message appearing, then another message appearing.
      There's no jumping up and down a message correspondence" (operator,
      2026-09-28). Messages APPEAR in the thread's order, one at a time: the
      one the air reaches with its dice (they land, hold, then its words
      start); one the air went past, or a late arrival that aired, rises
      into place (ENTER_MS). The next waits GRACE_MS after the last entrance
      ended; when the air is ahead of the rhythm (a skip, a burst of news, a
      catch-up after a pause) the grace shortens (never under GRACE_MIN_MS),
      the order never changes. `shownKey` is the newest message that has
      appeared: everything after it is drawn still to come (its card,
      faded). Synced, the view GLIDES down by the room each one takes -
      eased, never a jump, never up. Each entrance is announced on the
      view's root as an 's3-appear' event {key, kind, phase, grace, t}. */
  const GRACE_MS = 800, GRACE_MIN_MS = 240, ENTER_MS = 320;
  let shownKey = '', airKey = '', releasing = false, enteredAt = -1e9;     /* the first one never waits */
  const rhythm = () => current === 'conversation' && !reduced() && onScreen();
  const announce = (key, kind, phase, grace) => {
    try { root.dispatchEvent(new CustomEvent('s3-appear', {detail: {key, kind, phase, grace, t: performance.now()}})); } catch (e) { /* an old engine */ }
  };
  const wait = ms => Promise.race([frameSleep(ms), sleep(ms + 30)]);   /* frames or timers: a tablet can stall either */
  /* the newest message shown - before any, the newest the receipts say has happened */
  function shownIndex() {
    const pos = seqPos();
    if (shownKey && pos.has(shownKey)) return pos.get(shownKey);
    /* [msgorder] once the air has been seen, the air decides: the station's
       receipt says 'published' before a line is heard, and read as "shown"
       it left nothing ever due - no message ever appeared, the feed was
       drawn written in one go. The one on air comes in next; what follows it
       is still to come. */
    if (airKey && pos.has(airKey)) return pos.get(airKey) - 1;
    for (let i = thread.length - 1; i >= 0; i -= 1) {
      const it = itemAt(thread[i]);
      if (it && it.t && v.airStage(thread[i], it.conv, it.t) !== 'upcoming') return i;
    }
    return -1;
  }
  /* what has to have appeared: up to the air, and any late arrival that aired right under it */
  const airedLate = key => { const it = itemAt(key); return it && it.t ? v.airStage(key, it.conv, it.t) === 'written' : /^(clip|guy):/.test(key); };
  function dueIndex() {
    const pos = seqPos();
    let i = airKey && pos.has(airKey) ? pos.get(airKey) : -1;
    while (i >= 0 && i + 1 < thread.length && lateSet.has(thread[i + 1]) && airedLate(thread[i + 1])) i += 1;
    return i;
  }
  const graceFor = waiting => (waiting > 1 ? Math.max(GRACE_MIN_MS, GRACE_MS / waiting) : GRACE_MS);
  async function release() {
    if (releasing) return;
    releasing = true;
    try {
      for (;;) {
        if (!v.alive) return;
        const s = shownIndex(), due = dueIndex();
        if (due <= s) return;
        const key = thread[s + 1];
        if (!itemNode(key)) { shownKey = key; continue; }        /* nothing drawn for it: nothing to show */
        let grace = graceFor(due - s);
        while (rhythm() && performance.now() < enteredAt + grace) {
          await wait(Math.max(16, Math.min(60, enteredAt + grace - performance.now())));
          if (!v.alive) return;
          grace = graceFor(dueIndex() - shownIndex());              /* more arriving: the grace shortens */
        }
        if (key === airKey) await enterLive(key, grace);
        else await enterPast(key, grace);
        enteredAt = performance.now();
      }
    } finally { releasing = false; }
  }
  /* one the air went past (or a late arrival that aired): it rises into place, whole */
  async function enterPast(key, grace) {
    const pos = seqPos();
    if (rv && (pos.get(rv.key) ?? -1) < (pos.get(key) ?? -1)) finishReveal();
    shownKey = key;
    if (!follow) { unseen += 1; paintJump(); }
    announce(key, 'past', 'start', grace);
    restage();
    dressAir();
    const n = itemNode(key);
    if (n && rhythm()) { n.classList.remove('s3-enter'); void n.offsetWidth; n.classList.add('s3-enter'); setTimeout(() => n.classList.remove('s3-enter'), ENTER_MS + 80); }
    glide();
    const came = arrive(key);                      /* [msgorder] the one hook: a new message, in air order */
    if (rhythm()) await wait(ENTER_MS);
    if (came && rhythm() && dueIndex() <= shownIndex()) await Promise.race([came, wait(ARRIVE_CAP_MS)]);   /* nothing else due: it plays out before the next */
    announce(key, 'past', 'end', grace);
  }
  /* [msgorder] A NEW MESSAGE ARRIVED, IN AIR ORDER. Called once per message
     as release() lets it appear - the thread's order, one at a time - with
     its node where it stands. The builder of the arrival ([msgview]:
     v.arrived) decides how it comes together; the order is never its
     business. A promise (or nothing). */
  const ARRIVE_CAP_MS = 9000;
  function arrive(key) {
    const n = itemNode(key);
    if (!n || typeof v.arrived !== 'function') return null;
    try { return Promise.resolve(v.arrived(key, n)).catch(() => false); } catch (e) { return null; }
  }
  /* the one the air is on: its dice, the hold, then its words start */
  async function enterLive(key, grace) {
    finishReveal();
    shownKey = key;
    announce(key, 'live', 'start', grace);
    arrive(key);                                   /* [msgorder] the one hook; on air, the reveal is its arrival */
    await startReveal(key);
    announce(key, 'live', 'end', grace);
  }
  /* ---- [s3-imsg] the glide: follow the active reel at the viewport edge.
     A fresh reel above an existing typed tail can be followed upward while
     it rolls; the words then advance downward. The operator's hand yields it. */
  let glideRaf = 0;
  v.onTileFrame=node=>{
    if(node?.dataset.replaying&&current==='conversation'&&!hold&&!handOn()){ownScroll(false);followTile(node,root,cover()+8);}
    else if(follow)glide();
  };
  function glide() {
    if (current !== 'conversation' || !follow) return;
    if (reduced()) { toAnchor(false); return; }
    if (!glideRaf) glideRaf = requestAnimationFrame(glideStep);
  }
  function glideStep() {
    glideRaf = 0;
    if (current !== 'conversation' || !follow || hold || handOn() || replaying || !v.alive) return;
    const top = anchorTop();
    if (top == null) return;
    const was = root.scrollTop, gap = top - was, rolling = !!itemNode(anchorKey())?.s3Tile?.seq;
    if(Math.abs(gap)<1||(gap<0&&!rolling))return;
    ownScroll(false);
    const step=Math.max(1,Math.ceil(Math.abs(gap)*.2));
    root.scrollTop=gap>0?Math.min(top,was+step):Math.max(top,was-step);
    if(Math.abs(root.scrollTop-was)>0)glideRaf=requestAnimationFrame(glideStep);
  }
  /* [s3-imsg] a message drawn again where it stands keeps its height - it may
     grow, it never shrinks - so nothing under it moves up (and the view has
     no reason to) */
  function holdHeight(was, fresh) {
    const h = was.isConnected ? was.getBoundingClientRect().height : 0;
    was.replaceWith(fresh);
    if (h && fresh.getBoundingClientRect().height < h - 0.5) fresh.style.minHeight = Math.ceil(h) + 'px';
  }
  async function startReveal(key) {
    const it = itemAt(key);
    if (!it || !it.t) return;
    airHead = key;
    const lines = it.line ? [it.line] : it.part ? it.part.lines : turnLines(it.conv, it.t);   /* [s3-imsg] a run: its own lines */
    const w = lines.map(l => Math.max(1, String(l.text || '').length));
    const before = [];
    let sum = 0;
    for (const x of w) { before.push(sum); sum += x; }
    const text = it.line ? '' : it.part ? it.part.text : v.wordsOf(it.t, it.conv);
    const receipt = it.line ? v.air.get(it.line.line_id) : null;
    const secs = it.line ? Math.max(2, Number((receipt && receipt.seconds) || 5)) : Math.max(2, (text.length || 40) / PACE);
    const me = rv = {key, text, idx: new Map(lines.map((l, i) => [l.line_id, i])), w, before, sum: sum || 1, secs,
      k: 0, bar: 0, n: -1, phase: 'roll', lastT: performance.now(), node: null, seq: null, chase: null, line: it.line || null};
    /* everything before it drawn whole, everything after it its card - this one its card, about to pop */
    restage();
    dressAir();
    if (follow) glide(); else { unseen += 1; paintJump(); }
    const card = itemNode(key);
    /* [s3-imsg] its dice land one after another and hold; the words wait for that */
    const rolls = current === 'conversation' && !reduced() && onScreen() && !!card && card.dataset.stage === 'upcoming' &&
      typeof card.roll === 'function';
    if (rolls) {
      const go = v.rollIn(card);                             /* [s3-imsg] the one assembly: the same pop, dice and hold as a replay */
      me.seq = go.seq;
      await go.done;
    }
    if (rv !== me) return;                                   /* taken down: the view closed */
    const at = seqPos();
    if ((at.get(airKey) ?? -1) > (at.get(key) ?? -1)) {      /* the air moved on while they came down: history now, whole */
      finishReveal();
      restage();
      dressAir();
      return;
    }
    me.phase = 'words';
    me.lastT = performance.now();
    const fresh = swapItem(key);
    if(fresh?.s3Tile)v.tileStage(fresh,'live');
    dressAir();
    tickReveal();
    liveMedia(true);                                         /* [s3-imsg] a sting's clip plays as it airs */
    glide();
  }
  /* [s3-imsg] The sting on air: its clip in its message plays with the air - from where the air's
     clock says the clip has got to, drawn back into step on each tick when it drifts - once
     through, then rests on its frame. Drawn again while it airs (a round's news), it picks up
     where the air is. */
  function liveMedia(start = false) {
    const r = rv;
    if (!r || r.phase !== 'words' || !r.line || current !== 'conversation') return;
    const node = itemNode(r.key);
    const m = node && node.querySelector('.s3-sting-media');
    if (!m || typeof m.play !== 'function') return;
    const c = clockAt, now = performance.now();
    const fresh = c.total > 0 && now - c.when < CLOCK_FRESH && r.idx.has(c.line);
    const at = fresh ? Math.min(c.total, c.at + Math.min(1, (now - c.when) / 1000)) : 0;
    if (!m.dataset.played && (start || fresh) && !m.playing()) {
      m.dataset.played = '1';
      m.play({from: at, seconds: fresh ? c.total : 0});
    } else if (fresh && m.sync) m.sync(at);
  }

  /* ---- painting ----------------------------------------------------------- */
  function paintHead() {
    title.textContent = current === 'rolodex' ? 'Technical' : 'Messenger';
    title.classList.toggle('live', current === 'conversation');
    const c = current === 'rolodex' ? v.conv : (byTime().pop() || {}).conv;
    facts.textContent = current === 'rolodex'
      ? (c ? c.identity.road_kind + ' · ' + c.mode + ' · ' + c.turns.length + ' turns · ' + String(c.subject.topic || '').slice(0, 90) : '')
      : (queue.length ? `${queue.length} arriving · ` : '') + (c ? `${c.identity.road_kind} · ${c.turns.length} turns · ` +
        String(c.subject.topic || '').replace(/\s+/g, ' ').slice(0, 80) : 'waiting for a round');
    playBtn.hidden = current !== 'conversation' || !feed.size;
    noteBox.textContent = note;
    noteBox.hidden = !note || current !== 'rolodex';
    paintJump();
  }

  function paintBody() {
    if (current === 'rolodex') {
      if (!v.conv) { const n = byTime().pop(); if (n) v.conv = n.conv; }
      const keep = root.scrollTop;
      v.paintRolodex();
      fill(bodyBox, v.paneB);
      selfUntil = Date.now() + 300;
      root.scrollTop = keep;
      v.select(v.sel.turn, v.sel.event, null);
    } else {
      fill(bodyBox, v.paneA);
    }
    dressAir();
    if (current === 'conversation' && follow) toAnchor(false);       /* [s3-messenger] */
  }

  /* Play the build: the newest round builds again from its recorded rolls,
     message by message, where it stands. */
  async function replay(which) {
    const entry = which && which.chat ? which : byTime().pop();
    if (!entry || entry.building) return;
    playBtn.disabled = true;
    entry.building = true;
    /* Each item stays in its existing run while its shared sheet replays. */
    /* [s3-messenger] the build is watched where it grows - [s3-imsg] only
       while synced; the sync picks up the air after it */
    replaying = true;
    try {
      await v.buildRound(entry.conv, entry.chat, {base: 700 / v.speed, live: () => v.alive && feed.get(entry.conv.identity.conversation_id) === entry,
        grow: n => { if (follow && n && n.isConnected && !hold) bringIntoView(n); },
        latest: () => entry.pending || entry.conv,
        existing: () => chatsOf(entry).flatMap(chat=>[...chat.children])});
    } finally {
      replaying = false;
      entry.building = false;
      if (entry.pending) { entry.conv = entry.pending; entry.pending = null; }
      paintRound(entry);
      relayout();
      dressAir();
      if (follow) toAnchor(false);
      playBtn.disabled = false;
    }
  }
  /* [s3-imsg] a node brought just into the view - the view's own scroller only, never the page around it */
  function bringIntoView(n) {
    if (handOn()) return;                          /* the operator's hand is on the view */
    const box = root.getBoundingClientRect(), r = n.getBoundingClientRect();
    const by = r.bottom > box.bottom - EDGE ? r.bottom - (box.bottom - EDGE) : r.top < box.top + cover() ? r.top - (box.top + cover()) : 0;
    if (Math.abs(by) < 2) return;
    ownScroll(false);
    root.scrollTop += by;
  }

  paintHead();
  paintBody();
  readTurn();
  schedule(50);
  const face = {
    setView(next) {
      /* [s3-imsg] the switch does not sync: synced, each view opens on the air; not, the Messenger where it was left */
      if (current === 'conversation' && bodyBox.contains(v.paneA)) msgMark = viewMark();
      current = next === 'rolodex' || next === 'technical' ? 'rolodex' : 'conversation';
      paintHead(); paintBody();
      if (current === 'conversation') { if (follow) toAnchor(false, true); else viewBack(msgMark); schedule(50); }
      else if (follow) placeRolodex(true);
    },
    get conversation() { return v.conv; },
    get conversationId() { return cid; },
    /* The round the air (or the operator's tap) is on: it joins the feed in
       time order if it is not in it, and its turn is picked. The Messenger
       does not scroll for it. */
    async show({conversationId = '', turnId = '', note: why = '', refresh = false} = {}) {
      note = why || '';
      if (!conversationId) { paintHead(); return; }
      const changed = conversationId !== cid;
      cid = conversationId;
      let entry = feed.get(conversationId);
      if (!entry && !queue.some(j => j.conv.identity.conversation_id === conversationId)) {
        try { await addRound(conversationId); } catch (e) { /* nothing to add */ }
        entry = feed.get(conversationId);
      } else if (entry && refresh) {
        entry.dirty = true;
      }
      if (entry) v.conv = entry.conv;
      else { try { v.setConversation(await fetchRound(conversationId), null); } catch (e) { /* nothing to show */ } }
      if (turnId && turnId !== v.sel.turn) {
        if (current === 'rolodex') v.select(turnId, '', null);
        else {
          v.sel = {turn: turnId, event: ''};
          for (const n of v.paneA.querySelectorAll('.s3-msg[data-turn]')) n.classList.toggle('sel', n.dataset.turn === turnId);
        }
      }
      if (current === 'rolodex' && changed) paintBody();
      paintHead();
    },
    /* The line on air: 'here' when it belongs to a round in the feed (lit
       with no request at all), 'elsewhere' when the host must resolve it to
       a conversation first. */
    live(lineId) {
      if (!lineId) return 'elsewhere';
      const {row, owner} = lineRow(lineId);
      if (!row) return 'elsewhere';
      /* the same line again is no news - unless its round has joined the
         feed since (it was still arriving when the line was first named) */
      let news = false;
      if (lineId !== liveLine || (owner && !liveOwned)) {
        news = true;
        liveLine = lineId;
        liveOwned = !!owner;
        /* [s3-messenger] a sting is an item of its own in the sequence (after
           the turn before it); a spoken line is its turn's */
        const {key, turnId} = itemOfRow(row, owner ? owner.conv : v.conv);
        if (turnId && turnId !== liveTurn) { liveTurn = turnId; placeRolodex(false); }
        if (key) liveKey = key;
        pending = key && owner ? key : '';
        pendingAt = performance.now();
      }
      if (pending && tryReach(pending, lineId)) { pending = ''; news = true; }
      if (news) dressAir();
      return 'here';
    },
    /* The page's clock for the line on air - where the clip has got to and
       how long it is - so the words and the bar of the live message keep
       step with the audio. Blank or zero: nothing is sounding. Every tick:
       it touches the one live node and nothing else. [s3-messenger] */
    clock(lineId, at, total) {
      clockAt = {line: String(lineId || ''), at: Number(at) || 0, total: Number(total) || 0, when: performance.now()};
      /* the clock is always the line SOUNDING (the focus can be a line tapped
         in the script): a new sounding line of a round on show moves the air */
      if (clockAt.line !== clockLine && clockAt.total > 0) {
        clockLine = clockAt.line;
        const {row, owner} = lineRow(clockLine);
        const {key} = row && owner ? itemOfRow(row, owner.conv) : {key: ''};
        if (key) airReached(key);
      }
      tickReveal();
    },
    message(text) { note = text || ''; paintHead(); noteBox.hidden = !note; },
    /* "If I tap on this, jump to the active message in whatever view I have
       up": the host's now-playing card calls this while a System 3 view is
       showing. False when the air is not in this view. */
    jumpToAir(lineId) { return jumpTo(lineId); },
    dispose() {
      v.alive = false; v.token += 1; clearTimeout(timer);
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      rv = null;
      if (glideRaf) { cancelAnimationFrame(glideRaf); glideRaf = 0; }
      /* [s3-imsg] the listeners that live on the page, not on this view */
      window.removeEventListener('pointerup', handUp, true);
      window.removeEventListener('pointercancel', handUp, true);
      document.removeEventListener('keydown', handKey, true);
      document.removeEventListener('selectionchange', onSelection);
      if (unBack) unBack();                                   /* [s3-imsg] BACK no longer asks this view */
      for (const m of root.querySelectorAll('.s3-sting-media')) if (m.s3unload) m.s3unload();
      /* a video taken out of the page keeps decoding until it is collected */
      for (const vid of root.querySelectorAll('video, audio')) { try { vid.pause(); } catch (e) { /* gone */ } }
      for (const x of segNoded.values()) x.dispose();      /* [s3-segment-feed] the node views in the feed */
      for (const w of docked) w.remove();
      fill(root);
    }
  };
  /* Hidden (the Script tab went back to the script): nothing plays. */
  const hush = () => { if (!root.offsetParent) for (const vid of root.querySelectorAll('video, audio')) { try { vid.pause(); } catch (e) { /* gone */ } } };
  if (typeof ResizeObserver === 'function') new ResizeObserver(hush).observe(root);
  document.addEventListener('visibilitychange', hush);
  return face;
}

/* ======================================================================== */
/* HOW SYSTEM 3 BUILT THIS LINE - its section of the line inspector
   ("How this line came to be", desktop/renderer/line-deep.js).

   "In this window also do a section for system three showing how the R N G
    system constructed this line and how it resulted in the system prompt
    that resulted in this particular dialogue coming together. So I want to
    see the roller deck, I want to see the R and G system, I wanna see
    everything involved with system three and how this line came to be."

   In order: the tile built again (its dice and Rolodex rolling into place,
   then the words); every roll on the line, each one opening its decision
   card; the row System 3 wrote into the running order for it, inside the
   whole running order; where that row sits in the prompt the writer was
   actually given (the inspector passes the prompt it already fetched); the
   line as it came back, passages marked; and the checker's verdict on the
   turn. A line System 3 did not direct says so, and why nothing here can
   explain it. */
function sheetRowOf(sheet, t) {
  const want = new RegExp('^\\s*' + (t.index + 1) + '\\s+' + t.speaker + '\\s+[-\u2013\u2014]');
  return String(sheet || '').split('\n').find(ln => want.test(ln)) || '';
}

function markIn(text, needle, cls = 's3-hit') {
  const at = needle ? text.indexOf(needle) : -1;
  if (at < 0) return [text];
  return [text.slice(0, at), el('mark', {class: cls, text: needle}), text.slice(at + needle.length)];
}

/* [s3-link] THE SFX GUY'S ROW: his node on the turn it followed (SPEAK or
   PASS at the dial, the kind drawn), then the draw at air that chose the
   line - the pool, the candidates it rolled through, the die - and the
   words. Every number shown was recorded; the reel is the real candidates. */
function sfxGuyStory(conv, sg, v) {
  const node = sg.node, obs = sg.line || {}, t = sg.turn;
  const box = el('div', 's3-story-sfxguy');
  box.append(el('div', 's3-story-head',
    el('b', {text: castName('sfx') + "'s line" + (t ?   /* [cast-names] */ ` - after turn ${t.index + 1} (${t.name || t.speaker})` : '')}),
    el('span', {class: 's3-muted', text: (obs.kind ? {news: 'broke a story off the wire', reaction: 'fired back at the line',
      quip: 'a saying off his shelf', bank: 'a take off his speech bank'}[obs.kind] || obs.kind : '')})));
  if (node) {
    const row = rollRow(node, conv);
    const line = eventLine(node, conv);
    box.append(el('div', {class: 's3-story-roll', role: 'button', tabindex: '0', title: 'his node on this turn',
        onclick: () => openDecision(conv, node, t || {}, v.api),
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDecision(conv, node, t || {}, v.api); } }},
      row, el('div', {class: 's3-muted s3-story-why', text: 'his node: ' + line.text})));
  } else {
    box.append(para('His node on this turn was not recorded (the round was planned before he had one).', 's3-muted'));
  }
  const draws = obs.draws || [];
  if (draws.length) {
    for (const d of draws) {
      const cands = (d.candidates || []).map((c, i) => ({id: String(i + 1), label: String(c)}));
      const drum_ = drum(cands, String(d.index));
      const face = die(d.dice);
      const row = el('div', {class: 's3-roll', style: `--fam:${FAM.SFXGUY}`},
        el('b', {style: `color:${FAM.SFXGUY};min-width:74px`, text: 'LINE'}), drum_, face);
      row.roll = async ms => { await Promise.all([drum_.roll(ms), face.roll(ms * 0.85)]); };
      box.append(el('div', 's3-story-roll', row,
        el('div', {class: 's3-muted s3-story-why', text: `the ${d.pool} pool: d${d.dice} landed on ${d.index} of ${d.of}`
          + ((obs.fell_through || []).length ? ` - nothing to ${obs.fell_through.join(' or ')} first` : '')
          + (obs.planned && obs.planned !== obs.kind ? ` - his node had planned ${obs.planned}` : '')})));
      setTimeout(() => { if (row.isConnected && !reduced()) row.roll(700); }, 300);
    }
  } else if (obs.how) {
    box.append(para(obs.how, 's3-muted'));
  }
  if (obs.line) box.append(el('div', 's3-story-row', el('b', {text: 'What he said: '}), obs.line));
  return box;
}

/* [s3-account-code] A Messenger message wears its line's code - the same
   "#3c4782" the Script view's feed, the line popup and the hold sheet show
   (msg-id.js) - so tools/why_line.py and /api/system3/origin/<id> answer for
   what is on screen. The turn's spoken line (not a welded board clip); a tap
   copies the code and never plays the message. */
function msgCodeOf(lines) {
  const all = (lines || []).filter(l => l && l.line_id);
  const ln = all.find(l => l.who !== 'board') || all[0];
  if (!ln) return null;
  const id = String(ln.line_id).toLowerCase();
  const short = s => (/^[0-9a-f]{9,}$/.test(s) ? s.slice(0, 8) : s);
  const pm = /^(.*)-punct-(\d+)$/.exec(id);
  const code = '#' + (pm ? short(pm[1]) + '-p' + pm[2] : short(id));
  return el('span', {class: 's3-msgcode', text: code, role: 'button', tabindex: '0',
    style: 'font:11px ui-monospace,monospace;opacity:.6;margin:0 6px;cursor:copy',
    title: 'this message\'s code (' + ln.line_id + ') - tap to copy; tools/why_line.py ' + code.slice(1),
    onclick: e => {
      e.stopPropagation();
      try {
        const M = window.PineMsgId;
        if (M && M.copy) M.copy(code);
        else if (navigator.clipboard) navigator.clipboard.writeText(code);
      } catch (err) { /* the code still shows */ }
    }});
}

/* [s3-account] THE ORIGIN LEDGER ON EVERY ITEM. "trace its origin for each and
   every thing down to either a table that is accessed via a roulette option or
   whatever system is needing to encompass the rogue element" (the operator).
   /api/system3/origin/<id> answers for any aired item of any age: rolled (the
   tables and the dice), forced (the named road and its trigger - no dice), or
   rogue (the code path that aired it, on the Untraced list). */
const ORIGIN_WORD = {rolled: 'Rolled by System 3', forced: 'A forced node', rogue: 'Rogue - aired with no System 3 origin'};
const ORIGIN_TONE = {rolled: 'var(--s3-good, #2e7d4f)', forced: 'var(--s3-warn, #8a6d1a)', rogue: 'var(--s3-bad, #b3261e)'};
function originLabel(n) {
  return ({air: 'On air', script: 'In the script', road: 'The road', conversation: 'System 3',
    roll: n.scope === 'round' ? 'A round roll' : 'A roll', store: 'Drawn from', forced: 'Forced by',
    rogue: 'Aired by'})[n.node] || String(n.node || '');
}
function originText(n) {
  const bits = [];
  const add = (v, pre) => { if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length)) bits.push((pre || '') + (Array.isArray(v) ? v.join(' - ') : String(v))); };
  if (n.node === 'air') {
    add(n.at ? new Date(Number(n.at) * 1000).toLocaleString([], {weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '');
    add(n.aired, 'published: '); add(n.heard_at ? 'heard' : ''); add(n.seconds ? Number(n.seconds).toFixed(1) + ' s' : '');
  } else if (n.node === 'script') {
    add(n.block != null ? 'block ' + n.block + (n.ord != null ? '.' + n.ord : '') : ''); add(n.sid, 'round '); add(n.segment, 'segment ');
  } else if (n.node === 'road') {
    add(n.label); add(n.who, 'seat ');
  } else if (n.node === 'conversation') {
    add(n.conversation_id, 'conversation '); add(n.turn_id, 'turn '); add(n.road, 'road '); add(n.via);
  } else if (n.node === 'roll') {
    add(n.table); add(n.path); add(n.picked || n.label);
    add(n.dice != null ? 'd100 ' + n.dice : ''); add(n.index != null && n.of ? n.index + ' of ' + n.of : '');
    add(n.odds != null ? 'odds ' + Math.round(Number(n.odds) * 100) + '%' : '');
  } else if (n.node === 'store') {
    add(n.kind); add(n.folder, 'folder '); add(n.db, 'db '); add(n.pool, 'pool '); add(n.product);
    add(n.key, 'key '); add(n.file, 'file '); add(n.index != null && n.of ? n.index + ' of ' + n.of : '');
  } else if (n.node === 'forced') {
    add(n.road); add(n.trigger); add(n.detail); add(n.by, 'by '); add(n.how);
  } else if (n.node === 'rogue') {
    add(n.producer); add(n.why); add(n.path, 'path ');
  }
  return bits.join(' - ');
}
function originNodes(got) {
  const v = String((got && got.verdict) || '');
  const head = el('div', {class: 's3-origin-head s3-origin-' + v, style: 'margin:4px 0 6px;color:' + (ORIGIN_TONE[v] || 'inherit')},
    el('b', {text: ORIGIN_WORD[v] || v || 'Unknown'}), (got && got.why) ? ' - ' + got.why : '');
  const mk = n => el('div', {class: 's3-origin-node s3-origin-' + String(n.node || ''),
    style: 'padding:2px 0 2px 10px;border-left:2px solid ' + (n.node === 'rogue' ? ORIGIN_TONE.rogue : n.node === 'forced' ? ORIGIN_TONE.forced : 'rgba(127,127,127,.35)')},
    el('b', {text: originLabel(n) + ': '}), originText(n));
  const all = (got && got.nodes) || [];
  const round = all.filter(n => n.node === 'roll' && n.scope === 'round');
  const rows = all.filter(n => !(n.node === 'roll' && n.scope === 'round')).map(mk);
  /* the conversation's own rolls (the station's dice door, the round's shape) are
     many and shared by every line of the round: folded, never hidden */
  const folded = round.length ? el('details', {class: 's3-origin-round'},
    el('summary', {text: round.length + ' roll' + (round.length === 1 ? '' : 's') + ' on the round (its conversation)'}),
    ...round.map(mk)) : null;
  const kept = (got && got.retention) ? para('Kept: ' + got.retention + (got.settled === false ? ' - still settling' : ''), 's3-muted') : null;
  return [head, ...rows, folded, kept];
}
function originSection(request, lineId) {
  const box = el('div', 's3-origin', para('Reading the origin ledger...', 's3-muted'));
  if (!lineId) { fill(box, para('No line id - nothing to trace.', 's3-muted')); return box; }
  Promise.resolve().then(() => request('/api/system3/origin/' + encodeURIComponent(lineId))).then(
    got => fill(box, ...originNodes(got)),
    () => fill(box, para('The origin ledger holds no record of this line yet - it writes each item within a minute or two of the air.', 's3-muted')));
  return box;
}
export function mountOrigin(root, {request, lineId = ''} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3');
  fill(root, originSection(request, lineId));
  return {dispose() { fill(root); }};
}

export async function mountLineStory(root, {request, lineId = '', prompt = '', onResolved = null, conv: given = null, turn: givenTurn = null} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-story');
  const say = text => fill(root, para(text, 's3-muted'));
  say('Asking System 3 about this line...');
  let got = null, conv = null;
  if (given && givenTurn) {
    /* [s3-line-tabs] the host holds the round and the turn (the cursor moved
       along the round's messages, which may not be in the ledger yet) */
    got = {line: {line_id: lineId}, turn: givenTurn, conversation: given.identity || {}, healed: ''};
    conv = given;
  } else {
    try { got = await request('/api/system3/line?line_id=' + encodeURIComponent(lineId)); } catch (e) { got = null; }
  }
  /* [s3-inject][gap1] a board clip welded as punctuation carries no stamp of
     its own - its dice live on the line it punctuates. Strip the "-punct-N"
     the station welds onto the parent's id and ask again. */
  let punctOf = '';
  if ((!got || !got.conversation) && /-punct-\d+$/.test(String(lineId || ''))) {
    const pid = String(lineId).replace(/-punct-\d+$/, '');
    try {
      const p = await request('/api/system3/line?line_id=' + encodeURIComponent(pid));
      if (p && p.conversation) { got = p; punctOf = pid; }
    } catch (e) { /* the parent is not stamped either - the plain words below say so */ }
  }
  if (got && got.conversation && !conv) {
    try { conv = await request('/api/system3/conversation/' + encodeURIComponent(got.conversation.conversation_id)); } catch (e) { conv = null; }
  }
  let t = conv && got.turn ? (conv.turns || []).find(x => x.turn_id === got.turn.turn_id) : null;
  /* [s3-inject][gap1] a round's board row: the dice live on the turn it
     punctuates - resolve that turn (the sting's slot in the ledger's order)
     and tell the whole story on it, never a one-sentence deflection. */
  let boardNote = punctOf ? 'a board clip welded as punctuation of line ' + punctOf.slice(0, 8) + '\u2026 - the dice below live on the turn it punctuates' : '';
  if (conv && !t && String(((got || {}).line || {}).who || '') === 'board') {
    const bid = String(((got || {}).line || {}).line_id || lineId || '');
    for (const [tid, slot] of boardPlan(conv)) {
      if ([...slot.before, ...slot.after].some(l => l && l.line_id === bid)) {
        t = (conv.turns || []).find(x => x.turn_id === tid) || null;
        if (t) boardNote = 'a board clip - the dice below live on the turn it punctuates (turn ' + (t.index + 1) + ')';
        break;
      }
    }
  }
  const tell = (directed, why) => { try { if (typeof onResolved === 'function') onResolved({directed, why, got, conv, turn: t}); } catch (e) { /* the host's own */ } };
  if (conv && got && got.sfxguy) {
    /* [s3-link] the SFX Guy's row: his node and the draw that chose it */
    const v = makeViews({request});
    v.conv = conv;
    fill(root, sfxGuyStory(conv, got.sfxguy, v),
      sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */
    tell(true, 'the SFX Guy\'s node on the turn he followed');
    return {dispose() { fill(root); }};
  }
  if (conv && !t) {
    const cid = (conv.identity || {}).conversation_id || '';
    const who = String((got.line || {}).who || '');
    const old = conv.engine && Number(String(conv.engine).split('/').pop()) < 3;   /* engine /4+ is not old */
    say(`Part of a System 3 round (${(conv.identity || {}).road_kind || 'a'} round ${cid}) but not one of its planned turns: `
      + (who === 'drop' ? (old ? 'the SFX Guy spoke here before he had a node (this round was planned by ' + conv.engine + '), so the dial\'s own random chose the line.'
          : 'the SFX Guy\'s line; its draw was not recorded on this row.')
        : who === 'board' ? 'a board clip. The dice for the clip are on the turn it punctuates.'
        : 'a line the station put into the round at air - a passage dealt in front by the old door, a caller\'s hello - which no node made. The dice for the round are on its turns.'));
    root.append(sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */
    tell(false, 'in a System 3 round, but not one of its turns');
    return {dispose() { fill(root); }};
  }
  if (!conv || !t) {
    say('Not directed by System 3. This line came from a road System 3 does not run yet - a gold bar replayed as filler, '
      + 'a punctuation row on a single line - or from a round written before it was switched on. Nothing '
      + 'was rolled for it, and nothing in its prompt came from the Rolodex.');
    root.append(sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */
    tell(false, 'not directed by System 3');
    return {dispose() { fill(root); }};
  }
  tell(true, got.healed ? 'directed by System 3 (' + got.healed + ')' : 'directed by System 3');
  const v = makeViews({request});
  v.conv = conv;
  const id = conv.identity || {};
  const evs = turnEvents(conv, t);
  const tile = el('div', 's3-chat s3-story-tile', v.bubble(t, {conv}));
  const again = btn('Roll it again', () => { const n = tile.querySelector('.s3-msg'); if (n) v.rebuildTurn(n, conv, t); }, {class: 's3-story-again'});
  const head = el('div', 's3-story-head',
    el('b', {text: `${id.road_kind || 'a'} round - turn ${t.index + 1} of ${conv.turns.length} - ${t.name || t.speaker}`}),
    el('span', {class: 's3-muted', text: `${t.step_label || ''} - ${t.phase || ''} - ${conv.mode || ''} - ${evs.length} roll${evs.length === 1 ? '' : 's'}`
      + (got.healed ? ' - ' + got.healed : '')}),
    again);

  if (boardNote) head.append(el('div', {class: 's3-muted s3-story-why', text: boardNote}));   /* [s3-inject][gap1] */
  const rolls = el('div', 's3-story-rolls');
  for (const ev of evs) {
    const row = esTwoStageReel(ev, conv);                  /* [s3-es-reel] */
    const line = eventLine(ev, conv);
    rolls.append(el('div', {class: 's3-story-roll', role: 'button', tabindex: '0', title: 'how this was decided',
        onclick: () => openDecision(conv, ev, t, v.api),
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDecision(conv, ev, t, v.api); } }},
      row, el('div', {class: 's3-muted s3-story-why', text: esStagesText(ev) || line.text})));   /* [s3-es-reel] */
  }
  if (!evs.length) rolls.append(para('No roll was recorded on this turn.', 's3-muted'));

  const sheet = String((conv.plan || {}).sheet || '');
  const row = sheetRowOf(sheet, t);
  const told = el('div', 's3-story-sheet',
    row ? el('div', 's3-story-row', el('b', {text: 'The row for this line: '}), row.trim())
      : para('The running order kept for this round has no row for this turn.', 's3-muted'),
    sheet ? el('details', null, el('summary', {text: 'the whole running order System 3 wrote for the round'}),
      el('pre', null, ...markIn(sheet.replace(/^\n+/, ''), row))) : null);

  const text = String(prompt || '');
  const anchorText = 'THE RUNNING ORDER OF THIS EXCHANGE';
  let inPrompt;
  if (text && row && text.includes(row.trim())) {
    const at = text.indexOf(row.trim());
    const from = Math.max(0, at - 420), to = Math.min(text.length, at + row.trim().length + 260);
    inPrompt = el('div', null,
      para(`Found in the prompt the writer was given: character ${at + 1} of ${text.length}.`, 's3-muted'),
      el('pre', {class: 's3-story-prompt'}, from > 0 ? '...' : '', ...markIn(text.slice(from, to), row.trim()), to < text.length ? '...' : ''));
  } else if (text && text.includes(anchorText)) {
    const at = text.indexOf(anchorText);
    inPrompt = el('div', null,
      para('The prompt on record carries System 3\'s running order, but not this row word for word (the round was re-planned or re-written after it was sent).', 's3-muted'),
      el('pre', {class: 's3-story-prompt'}, ...markIn(text.slice(at, at + 900), anchorText)));
  } else {
    inPrompt = para(text ? 'The prompt on record for this line does not carry System 3\'s running order.'
      : 'No prompt was kept for this line, so only the running order System 3 wrote can be shown.', 's3-muted');
  }

  const val = conv.validation || {};
  const checks = (((val.turns || []).find(r => r.turn_id === t.turn_id) || {}).checks) || [];
  const echo = (val.echo && val.echo.turns || []).includes(t.index);
  const verdict = el('div', 's3-story-checks',
    para(`The round's verdict: ${val.verdict || 'not checked'}${val.score != null ? ' (score ' + num(val.score) + ')' : ''}${echo ? ' - this turn echoed an earlier line' : ''}.`, 's3-muted'),
    checks.length ? kv(checks.map(c => [c.what, `${c.result}${c.how ? ' - ' + c.how : ''}`])) : null);

  fill(root,
    head, tile,
    sectionOf('The Rolodex - every roll on this line', rolls),
    sectionOf('What System 3 told the writer for this line', told),
    sectionOf('Where it sits in the prompt the writer was given', inPrompt),
    canCompose(conv, t) ? sectionOf('The line as it came back', composeLine(conv, t, v.api)) : null,
    sectionOf('Length and handoffs', handoffReceipt(conv, t, ev => openDecision(conv, ev, t, v.api))),
    sectionOf('The checks on this turn', verdict),
    sectionOf('Where it came from - the origin ledger', originSection(request, lineId)));   /* [s3-account] */
  // the tile builds itself again as the section opens: the dice, then the words
  const first = tile.querySelector('.s3-msg');
  if (first && !reduced()) setTimeout(() => { if (first.isConnected) v.rebuildTurn(first, conv, t); }, 250);
  for (const r of rolls.querySelectorAll('.s3-roll')) if (r.roll) r.roll(reduced() ? 0 : 900);
  return {dispose() { v.alive = false; fill(root); }};
}

/* ======================================================================== */
export async function mount(root, {request, onClose, tab: startTab = '', table: startTable = '', conversationId = '', details = true} = {}) {
  request ||= defaultRequest();
  /* [s3-cast] 'tables:DIRECTIVE1' opens a tab on a table - the Mind desk's buttons use it */
  if (typeof startTab === 'string' && startTab.includes(':') && !startTable) [startTab, startTable] = startTab.split(':', 2);
  const send = (path, method, body) => request(path, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  root.classList.add('s3');
  let alive = true, tab = startTab || 'director', view = 'split', cursor = 0, follow = false;   /* [s3-still] follow live only when asked */
  let status = null, list = [], config = null, settings = null, lastLoaded = '', deferredBuildCid = '';
  const timers = [];
  const v = makeViews({request, details});                                /* [s3-msgdrop] */
  v.quiet = true;                                                        /* [s3-still] */
  v.sequenced = true;          /* [s3-messenger] the conversation pane is a Messenger: a line not on air yet is its roulette */
  try { v.newestFirst = localStorage.getItem('s3.newestFirst') !== '0'; } catch (e) { v.newestFirst = true; }
  /* [s3-still] a refresh of the round on show keeps the reader's place: the
     first turn on screen is found again after the repaint and the scroll is
     moved by exactly its drift; nothing else moves. */
  const scrollBox = () => { let n = body; while (n && n !== document.body) { if (n.scrollHeight > n.clientHeight + 4) return n; n = n.parentElement; } return root; };
  async function keepPlace(fn) {
    const box = scrollBox(); const top = box.scrollTop; const lip = box.getBoundingClientRect();
    let anchor = null;
    for (const n of body.querySelectorAll('[data-turn]')) {
      const r = n.getBoundingClientRect();
      if (r.height > 0 && r.bottom > lip.top) { anchor = {id: n.dataset.turn, pane: n.closest('.s3-pane'), was: r.top}; break; }
    }
    await fn();
    let again = null;
    if (anchor) { const pane = anchor.pane && anchor.pane.isConnected ? anchor.pane : body; again = pane.querySelector(`[data-turn="${CSS.escape(anchor.id)}"]`); }
    if (again) box.scrollTop = box.scrollTop + (again.getBoundingClientRect().top - anchor.was);
    else box.scrollTop = top;
  }
  /* [s3-hold] "When I'm scrolling in the system3 popup, do not reset my view
     or change what I am reading. I do not like windows auto resetting while
     I am analyzing it." Any scroll, wheel, touch, key or pointer in this
     window marks the operator as reading; for 25 s after the last one (and
     always while a decision card is open) no poll repaints, reloads or
     re-sorts anything on its own. A tap still acts at once. New entries
     wait behind a "N new" pill unless the list is at its top and idle. */
  let readingAt = 0, directorScrollUntil = 0, readingInputAt = 0;
  const reading = () => Date.now() - readingAt < 25000 || !!document.querySelector('.s3-modal-back');
  const noteReading = event => {
    const now=Date.now();if(event.type==='scroll'){if(now<directorScrollUntil||now-readingInputAt>1200)return;}else readingInputAt=now;
    readingAt=now;
  };
  v.onTileFrame=node=>{
    if(!alive||tab!=='director'||!node?.isConnected||(!node.dataset.replaying&&!node.s3Tile?.seq))return;
    directorScrollUntil=Date.now()+180;const ancestors=[];
    for(let box=v.paneA.parentElement;box;box=box.parentElement)if(/auto|scroll/.test(getComputedStyle(box).overflowY)&&box.scrollHeight>box.clientHeight+1)ancestors.push(box);
    for(const box of ancestors.slice().reverse())revealTilePane(v.paneA,box);
    followTile(node,v.paneA,(v.paneA.querySelector(':scope > h2')?.offsetHeight||0)+8);
    for(const box of ancestors)followTile(node,box);
  };
  ['scroll', 'wheel', 'touchstart', 'touchmove', 'pointerdown', 'keydown'].forEach(n => root.addEventListener(n, noteReading, {capture: true, passive: true}));
  const scrolledTop = node => { let n = node; while (n && n !== document.body) { if (n.scrollHeight > n.clientHeight + 4) return n.scrollTop <= 6; n = n.parentElement; } return true; };
  const newPill = (listNode, count, show) => {
    let pill = listNode.querySelector(':scope > .s3-newpill');
    if (!count) { if (pill) pill.remove(); return; }
    if (!pill) { pill = btn('', show, {class: 's3-newpill'}); listNode.prepend(pill); }
    pill.textContent = count + ' new - show';
  };

  const message = el('div', {role: 'status', 'aria-live': 'polite'});
  const report = (error) => { message.className = 's3-error'; message.textContent = error.message || String(error); };
  const quiet = () => { message.className = ''; message.replaceChildren(); };
  const retryStartup = btn('Retry loading', () => initialize(), {class: 's3-retry'});
  /* [s3-save] a save is confirmed with the version it made - the live config's
     hash and note - so "did that take?" is never a question (the ledger held
     the default cycle while the operator believed the graph was saved) */
  let noticeTimer = 0;
  const notice = (text) => { message.className = 's3-ok'; message.textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { if (message.className === 's3-ok') quiet(); }, 9000); };
  const saved = (what, res) => notice('Saved ' + what + (res && res.hash ? ' - live config ' + res.hash : '') + (res && res.structure && res.structure.version ? ' (v' + res.structure.version + ')' : '') + '. The desk uses it from the next round.');
  const metrics = el('div', 's3-metrics');
  const modePill = el('span', 's3-pill');
  const tabs = el('div', 's3-tabs');
  const body = el('div');
  fill(root,
    el('header', 's3-head',
      el('div', 's3-row', el('h1', {text: 'System 3'}), modePill,
        el('span', {class: 's3-muted', text: 'the conversation director · decides what kind of conversational action happens; the model writes the words'})),
      el('div', 's3-row', tabs, onClose ? btn('Close', () => onClose()) : null)),
    metrics, message, body);

  /* [s3-window] "a button icon '3' ... opening a popup": Tables, Segments, Prompts, Audit, Sys3 - and the
     director, the cycle's structure view and the controls behind them. */
  const TABS = [['visual', 'Visual Prompt'], ['tables', 'Tables'], ['segments', 'Segments'], ['prompts', 'Prompts'], ['audit', 'Audit'], ['sys3', 'Sys3'],
    ['director', 'Director'], ['structure', 'Structure'], ['controls', 'Controls']];
  function stopExtras() {
    if (sys3) { try { sys3.stop(); } catch (e) { /* gone */ } sys3 = null; }
    if (visualScene) { visualScene.stop(); visualScene = null; }
    if (segGraphScene) { segGraphScene.stop(); segGraphScene = null; }
    clearInterval(auditTimer); clearInterval(promptsTimer);
    if (menuNode) { menuNode.remove(); menuNode = null; }
  }
  function paintTabs() {
    fill(tabs, ...TABS.map(([id, label]) => btn(label, () => { stopExtras(); tab = id; paint(); }, {'aria-pressed': String(tab === id)})));
  }

  function paintStatus() {
    if (!status) return;
    const s = status.settings, m = status.metrics, st = status.store || {};
    modePill.className = 's3-pill ' + (s.mode === 'off' ? 'off' : s.mode === 'shadow' ? 'shadow' : 'active');
    modePill.textContent = s.mode.replaceAll('_', ' ') + (s.mode === 'active_selected_roads' ? ': ' + (s.roads.join(', ') || 'none') : '');
    const verdicts = Object.entries(m.verdicts || {}).map(([k, n]) => `${k} ${n}`).join(' · ') || 'none yet';
    fill(metrics,
      ...[['planned', m.planned], ['active', m.active], ['shadow', m.shadow], ['plan', num(m.plan_ms_ema, 1) + ' ms'],
        ['max plan', num(m.plan_ms_max, 1) + ' ms'], ['material', `${m.material_resolved} / ${m.material_timeouts} timeouts`],
        ['verdicts', verdicts], ['voice from ES', m.perf_applied], ['SFX extra', `${m.sfx_extra} / observed ${m.sfx_observed}`],
        ['lines linked', m.lines_linked], ['turn-by-turn beats', m.mode_b_beats], ['failures', m.failures],
        ['writes pending', m.pending_writes], ['dropped', m.writes_dropped],
        ['ledger', `${st.conversations || 0} conversations · ${st.events || 0} events · ${((st.bytes || 0) / 1e6).toFixed(1)} MB`],
        ['config', status.config_hash]]
        .map(([k, n]) => el('span', null, k + ' ', el('b', {text: String(n)}))),
      m.last_failure ? el('span', {class: 's3-pill bad', text: 'last fault: ' + m.last_failure}) : null);
  }

  /* ---------------- the director ------------------------------------------ */
  const listBox = el('div', 's3-list');
  const main = el('div', 's3-main');
  const director = el('div', 's3-director', listBox, main);
  let listFilter = '';

  function paintList() {
    const filter = el('select', {onchange: e => { listFilter = e.target.value; refreshList(); }},
      ...[['', 'all modes'], ['active', 'active'], ['shadow', 'shadow'], ['simulation', 'simulations']]
        .map(([val, t]) => el('option', {value: val, text: t, selected: val === listFilter})));
    const followBox = el('div', 's3-row',
      el('label', 's3-row', el('input', {type: 'checkbox', checked: follow, onchange: e => { follow = e.target.checked; }}), 'follow live'),
      /* [s3-still] "put an option to reverse the feed so that it shows the latest entry first and have that on by default" */
      el('label', 's3-row', el('input', {type: 'checkbox', checked: v.newestFirst, onchange: e => {
        v.newestFirst = e.target.checked;
        try { localStorage.setItem('s3.newestFirst', v.newestFirst ? '1' : '0'); } catch (_) { /* no storage */ }
        v.paintConversation(); v.paintRolodex(); v.paintScript();
      }}), 'newest first'));
    const items = list.map(c => el('li', null, btn('', () => load(c.conversation_id), {
      class: c.conversation_id === (v.conv && v.conv.identity.conversation_id) ? 'sel' : ''})));
    list.forEach((c, i) => {
      const b = items[i].firstChild;
      b.append(el('span', 's3-row', el('span', {class: 's3-pill ' + c.mode, text: c.mode}), el('b', {text: c.road}),
        el('span', {class: 's3-muted', text: day(c.created)})),
        el('span', {class: 't', text: c.topic || '(no subject text)'}),
        el('span', {class: 's3-muted', text: `${c.turns} turns · ${c.events} decisions` +
          (c.verdict ? ` · ${c.verdict} ${num(c.score)}` : '') + (c.shadow != null ? ` · shadow match ${pct(c.shadow)}` : '') +
          (c.status === 'planned' && c.mode !== 'simulation' ? ' · not written to air yet' : '')}));
    });
    fill(listBox, el('h2', {text: 'Conversations'}), el('div', 's3-row', filter, followBox),
      el('ol', null, ...items), list.length ? null : el('p', {class: 's3-muted',
        text: 'Nothing recorded yet. In shadow mode every banter round the station writes is planned here too; use Simulate to see the Rolodex now.'}));
  }

  async function refreshList() {
    const q = new URLSearchParams({limit: 60, ...(listFilter ? {mode: listFilter} : {})});
    list = (await request('/api/system3/conversations?' + q)).conversations || [];
    paintList();
  }

  const convHead = el('div', 's3-card');
  const viewBar = el('div', 's3-row');
  const views = el('div', 's3-views');
  main.append(convHead, viewBar, views);
  v.onBuildState = busy => {
    paintHead();
    if(!busy&&alive&&tab==='director'&&follow&&deferredBuildCid){
      const cid=deferredBuildCid;deferredBuildCid='';
      queueMicrotask(()=>{if(alive&&tab==='director'&&follow)keepPlace(()=>load(cid,true));});
    }
  };

  function paintHead() {
    const conv = v.conv;
    if (!conv) { fill(convHead, el('p', {class: 's3-muted', text: 'Select a conversation, or simulate one.'}), simulator()); return; }
    const id = conv.identity, val = conv.validation, cmp = conv.comparison;
    const facts = [['road', id.road_kind], ['mode', conv.mode], ['revision', id.revision], ['seed', conv.seed],
      ['config', conv.config_hash], ['trace', id.trace_id], ['System 2 slot', id.system2_slot_id || '-'],
      ['generation', conv.generation_mode], ['plan', (conv.plan && conv.plan.plan_ms != null) ? conv.plan.plan_ms + ' ms' : '-']];
    const replayOut = el('span', 's3-muted');
    fill(convHead,
      el('div', 's3-row', el('h2', {text: conv.subject.topic ? conv.subject.topic.slice(0, 140) : 'Conversation ' + id.conversation_id}),
        el('span', {class: 's3-pill ' + conv.mode, text: conv.mode}),
        val ? el('span', {class: 's3-pill ' + (val.verdict === 'non_compliant' ? 'bad' : ''), text: `${val.verdict} ${num(val.score)}`}) : null),
      el('div', 's3-row s3-muted', ...facts.map(([k, val2]) => el('span', null, k + ': ', el('b', {text: String(val2 ?? '-')})))),
      el('div', 's3-row',
        btn(v.playing ? 'Building…' : 'Play the build', () => v.build(), {disabled: v.playing}),
        el('label', 's3-row s3-muted', 'speed', el('select', {onchange: e => { v.speed = +e.target.value; }},
          ...[[0.5, 'slow'], [1, 'normal'], [2.5, 'fast']].map(([sp, t]) => el('option', {value: sp, text: t, selected: sp === v.speed})))),
        btn('Decision replay', async (e) => {
          e.target.disabled = true;
          try {
            const r = await send('/api/system3/replay/' + id.conversation_id, 'POST');
            replayOut.textContent = r.ok ? `replayed: all ${r.events} draws reproduced from seed, inputs and config` : `diverged at event ${r.first_difference}: ${r.why}`;
          } catch (err) { replayOut.textContent = err.message; }
          e.target.disabled = false;
        }),
        btn('Export JSON', () => {
          const url = URL.createObjectURL(new Blob([json(conv)], {type: 'application/json'}));
          const a = el('a', {href: url, download: `system3-${id.conversation_id}.json`}); a.click();
          setTimeout(() => URL.revokeObjectURL(url), 1500);
        }), replayOut),
      cmp ? el('div', 's3-compare', ...[
        ['shadow: seat order match', pct(cmp.seat_similarity)], ['planned turns', cmp.planned_turns],
        ['written turns', cmp.actual_turns], ['acts met if planned', `${cmp.actual_met_planned_acts.met} / ${cmp.actual_met_planned_acts.met + cmp.actual_met_planned_acts.missed}`],
        ['verdict had it been planned', `${cmp.verdict_if_planned} ${num(cmp.score_if_planned)}`],
        ['planned seats', cmp.planned_seats], ['written seats', cmp.actual_seats]]
        .map(([k, n]) => el('div', null, k, el('b', {text: String(n)})))) : null,
      val ? el('div', 's3-compare', ...[['seat order', pct(val.seat_order)], ['turns written / planned', `${val.written} / ${val.planned}`],
        ['acts met', `${val.acts.met} met · ${val.acts.missed} missed · ${val.acts.unchecked} unchecked`],
        ['closing', val.closing == null ? 'not required' : val.closing ? 'lands' : 'missing'], ['violations', val.violations],
        ['method', val.method]].map(([k, n]) => el('div', null, k, el('b', {text: String(n)})))) : null,
      el('details', null, el('summary', {text: 'simulate another'}), simulator()));
  }

  function simulator() {
    const topic = el('input', {type: 'text', placeholder: 'subject', value: 'the raccoon that stole the station van', style: 'min-width:260px'});
    const turns = el('input', {type: 'number', min: 2, max: 40, value: 12, style: 'width:70px'});
    const seats = el('select', null, el('option', {value: 'AB', text: 'two in the booth'}), el('option', {value: 'ABD', text: 'three in the booth'}));
    const seed = el('input', {type: 'text', placeholder: 'seed (blank = random)', style: 'width:170px'});
    return el('div', 's3-row', topic, el('label', 's3-row s3-muted', 'turns', turns), seats, seed,
      btn('Simulate', async (e) => {
        e.target.disabled = true;
        try {
          const c = await send('/api/system3/simulate', 'POST', {topic: topic.value, turns: +turns.value, seats: seats.value.split(''),
            seed: seed.value || undefined, seeded: false});
          c.lines = []; c.observations_air = [];
          v.setConversation(c, new Map()); lastLoaded = c.identity.conversation_id; paintDirector(); await v.build();
        } catch (err) { report(err); }
        e.target.disabled = false;
      }), el('span', {class: 's3-muted', text: 'a simulation is planned with the live tables and can never reach air'}));
  }

  function paintViewBar() {
    const modes = [['split', 'All three'], ['conversation', 'Conversation'], ['rolodex', 'Rolodex'], ['script', 'Script']];
    fill(viewBar, ...modes.map(([id, label]) => btn(label, () => { view = id; paintViews(); }, {'aria-pressed': String(view === id)})),
      btn('Cycle view', () => { const order = ['conversation', 'rolodex', 'script']; view = order[(order.indexOf(view) + 1) % 3]; paintViews(); }),
      el('span', {class: 's3-muted', text: 'select anything to find it in the other views'}));
  }

  function paintViews() {
    paintViewBar();
    const show = view === 'split' ? [v.paneA, v.paneB, v.paneC] : [{conversation: v.paneA, rolodex: v.paneB, script: v.paneC}[view]];
    views.className = 's3-views' + (show.length === 1 ? ' single' : '');
    fill(views, ...show);
    v.select(v.sel.turn, v.sel.event, null);
  }

  function paintDirector() {
    paintList(); paintHead(); v.paintConversation(); v.paintRolodex(); v.paintScript(); paintViews();
  }

  async function load(cid, animate = false, {refresh = false} = {}) {
    try {
      const selected=v.conv?.identity?.conversation_id;
      const c = await request('/api/system3/conversation/' + encodeURIComponent(cid));
      const air = c.lines && c.lines.length ? await v.inspectBlocks(c) : new Map();
      if(!alive||(refresh&&(selected!==cid||v.conv?.identity?.conversation_id!==cid)))return;
      if(refresh){v.conv=c;v.remember(c);for(const [key,line]of air)v.air.set(key,line);}
      else{deferredBuildCid='';v.setConversation(c,air);}
      lastLoaded = cid;
      paintDirector();
      if (animate) await v.build();
      quiet();
    } catch (e) { report(e); }
  }

  /* ---------------- tables ------------------------------------------------- */
  let tableId = startTable || 'ES1', draft = null;   /* [s3-dice] a card can open on its table */
  let tableDrag = null; const foldedCats = new Set();   /* [s3-window] */
  /* [s3-cast] every family that keeps a table, the round rolls and the two pools included */
  const TABLE_FAMILIES = ['CTS', 'ES', 'RS', 'IRS', 'FL', 'TEMPER', 'SHOCK', 'INTERJECT', 'SPEAKERBOX', 'FAV', 'DIRECTIVE', 'EVENT', 'CHANCE', 'POOL', 'RESOLVE', 'WRAP', 'IL',
    'MGRTOPIC', 'MGRSUB', 'REACT', 'BOOK', 'WELCOME', 'SIGNOFF'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages - [supercut-react] REACT1 - [book-nodes] BK1-BK3 */
  TABLE_FAMILIES.push('CALLOPEN', 'CALLANGLE', 'CALLSTAKES', 'CALLPROBE', 'CALLSOURCE', 'RW');
  TABLE_FAMILIES.push('MEMORY');   /* [s3-memory] the kinds of memory: each a rule, then the roulette */
  /* [s3-memory] one kind of memory: the numbers and switches its rule decides eligibility by */
  function memoryFields(cat) {
    cat.rule = cat.rule && typeof cat.rule === 'object' && !Array.isArray(cat.rule) ? cat.rule : {};
    const said = k => k.replace(/_/g, ' ');
    const rows = Object.entries(cat.rule).map(([k, v]) => typeof v === 'boolean'
      ? el('label', 's3-row', el('input', {type: 'checkbox', checked: v, onchange: e => { cat.rule[k] = e.target.checked; }}), said(k))
      : el('label', 's3-row', el('span', {class: 's3-muted', text: said(k)}),
          el('input', {type: 'number', min: 0, step: 'any', value: v, style: 'width:5em', 'aria-label': said(k),
            onchange: e => { const x = parseFloat(e.target.value); if (!Number.isNaN(x) && x >= 0) cat.rule[k] = x; }})));
    return el('div', 's3-row s3-pool', el('span', {class: 's3-muted', text: 'its rule:'}), ...rows,
      rows.length ? null : el('span', {class: 's3-muted', text: 'no numbers - eligible whenever the station holds this kind of memory'}));
  }
  /* [s3-memory] how many memories a round: at least, at most (0 to 5) */
  function memoryKnobs(t) {
    const n = (key, def, label) => [el('label', {class: 's3-muted', text: label}),
      el('input', {type: 'number', min: 0, max: 5, step: 1, value: t[key] ?? def, style: 'width:4em', 'aria-label': label,
        onchange: e => { t[key] = Math.max(0, Math.min(5, parseInt(e.target.value || '0', 10) || 0)); }})];
    return el('div', 's3-row s3-pool', ...n('least', 1, 'at least'), ...n('most', 2, 'at most'),
      el('span', {class: 's3-muted', text: 'memories a round, drawn among the kinds whose rule makes them relevant right now'}));
  }
  /* [s3-events] one kind of happening: its odds, whose turn, where, whether it ends the segment */
  function eventFields(cat) {
    const pct = el('span', {text: Math.round((cat.odds ?? 0.1) * 100) + '%'});
    const pick = (value, options, set, label) => el('select', {'aria-label': label, onchange: e => set(e.target.value)},
      ...options.map(([v, t]) => el('option', {value: v, text: t, selected: v === value})));
    return el('div', 's3-row s3-pool',
      el('label', {class: 's3-muted', text: 'odds per segment'}),
      el('input', {type: 'range', min: 0, max: 1, step: 0.01, value: cat.odds ?? 0.1, 'aria-label': 'odds',
        oninput: e => { cat.odds = +e.target.value; pct.textContent = Math.round(cat.odds * 100) + '%'; }}), pct,
      el('label', {class: 's3-muted', text: 'happens to'}),
      pick(cat.seat || 'any', [['caller', 'the caller'], ['host', 'a host'], ['any', 'anyone']], v => { cat.seat = v; }, 'seat'),
      el('label', {class: 's3-muted', text: 'where'}),
      pick(cat.place || 'middle', [['any', 'anywhere'], ['open', 'the opening'], ['middle', 'the middle'], ['close', 'the close']], v => { cat.place = v; }, 'place'),
      el('label', 's3-row', el('input', {type: 'checkbox', checked: !!cat.ends, onchange: e => { cat.ends = e.target.checked; }}), 'ends the segment'),
      el('label', {class: 's3-muted', text: 'not before turn'}),
      el('input', {type: 'number', min: 1, max: 40, step: 1, value: (cat.min_turn || 1), style: 'width:4.5em', 'aria-label': 'earliest turn',
        onchange: e => { cat.min_turn = Math.max(1, parseInt(e.target.value || '1', 10) || 1); }}));
  }
  const castState = id => ((status && status.cast && status.cast.directives) || []).find(d => d.id === id);
  const dateOf = secs => { if (!secs) return ''; const d = new Date(secs * 1000); const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
  /* [s3-callend] THE CALL'S END ON THE DESK: RESOLVE's chain (how many station turns
     answer the outcome, and who) and WRAP's who, weighted by seat; each row's own
     fields. The seats are the booth: A the host, B the co-host, D the third seat, S the
     SFX guy (a seat only a call that carries his has). */
  const CALLEND_SEATS = [['A', () => castName('host') || 'the host'], ['B', () => castName('cohost') || 'the co-host'],
    ['D', () => castName('third') || 'the third seat'], ['S', () => castName('sfx') || 'the SFX guy']];
  function callendWeights(obj, keys, label) {
    const row = el('div', 's3-row s3-pool', el('label', {class: 's3-muted', text: label}));
    for (const [k, name] of keys) {
      const out = el('span', {text: num(obj[k] ?? 0)});
      row.append(el('label', {class: 's3-muted', text: typeof name === 'function' ? name() + ' (' + k + ')' : name}),
        el('input', {type: 'range', min: 0, max: 5, step: 0.05, value: obj[k] ?? 0, 'aria-label': label + ' ' + k,
          oninput: e => { obj[k] = +e.target.value; out.textContent = num(obj[k]); }}), out);
    }
    return row;
  }
  function callendTableFields(t) {
    if (t.family === 'RESOLVE') {
      t.responses ||= {1: 2, 2: 1}; t.responders ||= {A: 1, B: 1, D: 0.6, S: 0.8};
      return el('div', null,
        callendWeights(t.responses, [['1', 'one station turn'], ['2', 'two station turns']], 'the response chain:'),
        callendWeights(t.responders, CALLEND_SEATS, 'who sets it up and answers:'));
    }
    t.who ||= {A: 1, B: 1, D: 0.6, S: 0.8};
    return el('div', null, callendWeights(t.who, CALLEND_SEATS, 'who wraps the call:'));
  }
  function callendItemFields(item) {
    const txt = (key, placeholder) => el('input', {type: 'text', class: 'txt', value: item[key] || '', placeholder,
      oninput: e => { if (e.target.value.trim()) item[key] = e.target.value; else delete item[key]; }});
    const list = (key, placeholder) => el('input', {type: 'text', class: 'txt', value: (item[key] || []).join(', '), placeholder,
      onchange: e => { const got = e.target.value.split(',').map(x => x.trim()).filter(Boolean); if (got.length) item[key] = got; else delete item[key]; }});
    if (draft.family === 'WRAP') {
      return el('div', 's3-row s3-pool',
        el('label', 's3-row', el('input', {type: 'checkbox', checked: !!item.polite, onchange: e => { item.polite = e.target.checked; }}), 'a spoken goodbye'),
        list('only_after', 'only after (e.g. RESOLVE:buys_burns, tag:fire) - blank: any call'),
        txt('rebuttal', "what it does to the caller's last word (e.g. they never get to finish it)"));
    }
    const effect = el('select', {'aria-label': 'what it does to the painting',
      onchange: e => { if (e.target.value) item.effect = e.target.value; else delete item.effect; }},
      ...[['', 'no effect on the gallery'], ['sold', 'sold - off the pile'], ['awarded', 'awarded - off the pile'],
        ['burnt', 'burnt - off the pile'], ['unsold', 'unsold - on the pile, still for sale']]
        .map(([v, t]) => el('option', {value: v, text: t, selected: (item.effect || '') === v})));
    const raffle = !!item.raffle;
    return el('div', 's3-row s3-pool',
      txt('offer', "the station's setup - blank: the category's offer ({painting}, {price}, {number}, {prize})"),
      txt('respond', 'what the response chain answers'), txt('rebuttal', "the caller's last word"),
      effect,
      el('label', 's3-row', el('input', {type: 'checkbox', checked: raffle,
        onchange: e => { if (e.target.checked) item.raffle = {low: 2, high: 99}; else delete item.raffle; paintTables(); }}), 'raffle: caller number'),
      raffle ? el('input', {type: 'number', min: 1, max: 9999, value: item.raffle.low ?? 2, style: 'width:5em', 'aria-label': 'lowest caller number',
        onchange: e => { item.raffle.low = Math.max(1, parseInt(e.target.value || '1', 10) || 1); }}) : null,
      raffle ? el('input', {type: 'number', min: 1, max: 9999, value: item.raffle.high ?? 99, style: 'width:5em', 'aria-label': 'highest caller number',
        onchange: e => { item.raffle.high = Math.max(1, parseInt(e.target.value || '1', 10) || 1); }}) : null,
      el('label', 's3-row', el('input', {type: 'checkbox', checked: !!item.speakerbox,
        onchange: e => { if (e.target.checked) item.speakerbox = 'verbatim'; else delete item.speakerbox; }}), 'said in a speakerbox passage'),
      list('tags', 'tags (the wrap call can follow them: tag:fire)'));
  }
  function mgrSubFields(item) {   /* [s3-mgrtopics] a sub message kept to some of his topics */
    return el('div', 's3-row s3-pool', el('label', {class: 's3-muted', text: 'only for topics'}),
      el('input', {type: 'text', value: (item.topics || []).join(', '), placeholder: 'MGRTOPIC1 row ids, e.g. consultant (blank = any topic)',
        style: 'min-width:16em', 'aria-label': 'only for these topics',
        onchange: e => { const got = e.target.value.split(',').map(x => x.trim()).filter(Boolean); if (got.length) item.topics = got; else delete item.topics; }}));
  }
  function poolFields(item) {
    if (draft.family === 'MGRSUB') return mgrSubFields(item);   /* [s3-mgrtopics] */
    /* a directive's odds and lifetime; a favourite's origin */
    if (draft.family === 'RESOLVE' || draft.family === 'WRAP') return callendItemFields(item);   /* [s3-callend] */
    if (draft.family === 'DIRECTIVE') {
      const pct = el('span', {text: Math.round((item.odds ?? 1) * 100) + '%'});
      const st = castState(item.id);
      return el('div', 's3-row s3-pool',
        el('label', {class: 's3-muted', text: 'odds'}),
        el('input', {type: 'range', min: 0, max: 1, step: 0.05, value: item.odds ?? 1, 'aria-label': 'odds',
          oninput: e => { item.odds = +e.target.value; pct.textContent = Math.round(item.odds * 100) + '%' + (item.odds >= 1 ? ' (standing)' : ''); }}), pct,
        el('label', {class: 's3-muted', text: 'until'}),
        el('input', {type: 'datetime-local', value: dateOf(item.until), 'aria-label': 'expires',
          onchange: e => { item.until = e.target.value ? Math.round(new Date(e.target.value).getTime() / 1000) : 0; }}),
        el('label', {class: 's3-muted', text: 'airings'}),
        el('input', {type: 'number', min: 0, step: 1, value: item.airings || 0, style: 'width:5em', 'aria-label': 'airings (0 = unlimited)',
          onchange: e => { item.airings = Math.max(0, parseInt(e.target.value || '0', 10) || 0); }}),
        el('span', {class: 's3-muted', text: st ? `${st.state} · aired ${st.aired}` : 'not rolled yet'}));
    }
    if (draft.family === 'CHANCE') {   /* [s3-dice-door] one station roll: its odds, or the dial it follows */
      if (item.dial) return el('div', 's3-row s3-pool', el('span', {class: 's3-muted',
        text: `follows the station's own value "${item.dial}" (a desk dial or a live figure) - its odds are set there, not here. ${item.text && item.text !== item.label ? item.text : ''}`}));
      const pct = el('span', {text: Math.round((item.odds ?? 0.5) * 100) + '%'});
      return el('div', 's3-row s3-pool',
        el('label', {class: 's3-muted', text: 'odds'}),
        el('input', {type: 'range', min: 0, max: 1, step: 0.01, value: item.odds ?? 0.5, 'aria-label': 'odds',
          oninput: e => { item.odds = +e.target.value; pct.textContent = Math.round(item.odds * 100) + '%'; }}), pct,
        el('span', {class: 's3-muted', text: item.id}));
    }
    if (draft.family === 'MEMORY') {   /* [s3-memory] the state of its kind's rule this way of putting it fits */
      return el('div', 's3-row s3-pool', el('label', {class: 's3-muted', text: 'fits'}),
        el('input', {type: 'text', value: Array.isArray(item.when) ? item.when.join(', ') : (item.when || ''), style: 'min-width:12em',
          placeholder: 'the rule state it fits, e.g. top, past, segment (blank = any)', 'aria-label': 'fits',
          onchange: e => { const got = e.target.value.split(',').map(x => x.trim()).filter(Boolean);
            if (!got.length) delete item.when; else item.when = got.length === 1 ? got[0] : got; }}),
        el('span', {class: 's3-muted', text: '{words} in its text are the station\'s facts'}));
    }
    if (draft.family === 'FAV') {
      const when = item.at ? new Date(item.at * 1000).toLocaleString() : '';
      return el('div', 's3-row s3-pool', el('span', {class: 's3-muted',
        text: `said by ${item.name || item.who || 'the cast'}${when ? ' · liked ' + when : ''}${item.line_id ? ' · line ' + item.line_id : ''}${item.source ? ' · ' + item.source : ''}`}));
    }
    return null;
  }

  /* ---------------- [s3-lists] banks & lists --------------------------------
     "Any list to do with conversation or the roulette needs to be listed here
     as an editable table" (operator). Each list is its store's own rows,
     served by /api/system3/lists: a change is written to the store at once
     and recorded (who, when, what) - there is no draft to save. A table id
     never has a dot and a list id always does, so 'tables:sfxguy.bank' opens
     the Tables tab on the SFX Guy's speech bank. */
  let listId = String(startTable || '').includes('.') ? String(startTable) : '';
  let listReg = null, listRegAsked = false, listRegError = '';
  const listView = {q: '', state: '', offset: 0, limit: 50};
  const LIST_STATES = {ready: 'ready', waiting: 'waiting to record', queued: 'queued - not in the bank yet',
    suspended: 'suspended', off: 'off', dormant: 'dormant - another voice or profile', on: 'on',
    resting: 'resting - aired inside the hour', produced: 'produced spot', read: 'read live', banked: 'banked'};
  async function loadListReg() {
    try { listReg = (await request('/api/system3/lists')).lists || []; listRegError = ''; }
    catch (e) { listReg = []; listRegError = e.message || String(e); }   /* an older station has no such door: say so in the nav, quietly */
  }
  function paintListNav(listNode) {
    if (listReg === null) {
      if (!listRegAsked) { listRegAsked = true; loadListReg().then(() => { if (tab === 'tables') paintTables(); }); }
      return;
    }
    /* a table button clears the list selection before its own handler repaints */
    listNode.addEventListener('click', e => { const b = e.target.closest('button'); if (b && !b.closest('.s3-lists-nav')) listId = ''; }, true);
    if (listId) for (const b of listNode.querySelectorAll('button[aria-pressed="true"]')) b.setAttribute('aria-pressed', 'false');
    const nav = el('div', {class: 's3-lists-nav', style: 'display:grid;gap:6px'}, el('h3', {text: 'BANKS & LISTS'}));
    for (const l of listReg) {
      const b = btn('', () => { listId = l.id; listView.q = ''; listView.state = ''; listView.offset = 0; paintTables(); },
        {'aria-pressed': String(l.id === listId), title: l.what || ''});
      b.append(el('span', {text: l.label || l.id}), el('span', {class: 's3-muted', text: l.error ? 'unreadable' : l.count == null ? '' : String(l.count)}));
      nav.append(b);
    }
    if (!listReg.length) nav.append(el('span', {class: 's3-muted', text: listRegError ? 'the station did not answer: ' + listRegError : 'none registered on this station'}));
    listNode.append(nav);
  }
  function listEditor() {
    const meta = (listReg || []).find(l => l.id === listId) || {id: listId, label: listId, family: 'LIST', what: '', can: {}};
    const can = meta.can || {}, bank = meta.family === 'BANK';
    const base = '/api/system3/lists/' + encodeURIComponent(meta.id);
    const card = el('div', 's3-card');
    const rowsBox = el('div'), pager = el('div', 's3-row'), log = el('div');
    const stateSel = el('select', {'aria-label': 'show', onchange: e => { listView.state = e.target.value; listView.offset = 0; loadRows(); }});
    let searchTimer = 0;
    const search = el('input', {type: 'search', value: listView.q, placeholder: 'search the words', 'aria-label': 'search', style: 'min-width:16em',
      oninput: e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { listView.q = e.target.value; listView.offset = 0; loadRows(); }, 300); }});
    async function write(call, said) {
      try { await call(); notice(said + ' - written to the store and recorded on the desk log.'); } catch (e) { report(e); }
      await loadRows();
    }
    const rowPath = r => base + '/rows/' + encodeURIComponent(r.id);
    function rowOf(r) {
      const words = el('input', {type: 'text', value: r.text || '', 'aria-label': 'the words', style: 'width:100%', disabled: !can.edit,
        onchange: e => { const t = e.target.value.trim(); if (!t || t === (r.text || '')) { e.target.value = r.text || ''; return; }
          write(() => send(rowPath(r), 'PUT', {text: t}), bank ? 'Saved - the old recording is dropped; the line is recorded in the new words before it can air' : 'Saved'); }});
      const facts = [LIST_STATES[r.state] || r.state || '', r.plays > 0 ? 'played ' + r.plays : r.plays === 0 ? 'never played' : '', r.last_played ? 'last ' + day(r.last_played) : '',
        r.takes > 1 ? r.takes + ' takes' : '', r.reserved ? 'on air now' : '', r.origin && r.origin !== 'station' ? 'from the ' + r.origin : '', r.note || ''].filter(Boolean).join(' · ');
      return el('div', {class: 's3-list-row', 'data-row': r.id, style: 'display:grid;grid-template-columns:3.2em minmax(0,1fr) auto;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)'},
        can.switch ? el('label', 's3-row', el('input', {type: 'checkbox', checked: r.on !== false, 'aria-label': 'on',
          onchange: e => write(() => send(rowPath(r), 'PUT', {on: e.target.checked}), e.target.checked ? 'Switched on - back in the draw' : 'Switched off - kept, never picked')}), 'on') : el('span'),
        el('div', {style: 'display:grid;gap:2px;min-width:0'}, words,
          el('span', {class: 's3-muted', text: facts}),
          r.airs_as ? el('span', {class: 's3-muted', text: 'airs as: ' + r.airs_as}) : null,
          r.why ? el('span', {class: 's3-muted', text: r.why}) : null),
        can.remove ? btn('x', () => {
          if (!confirm('Remove "' + String(r.text || '').slice(0, 80) + '" from ' + (meta.label || meta.id) + '?' +
            (bank ? ' Every recording of it goes too, and the station will not bring the words back.' : ''))) return;
          write(() => send(rowPath(r), 'DELETE'), 'Removed');
        }, {'aria-label': 'remove item', style: 'padding:0 6px'}) : el('span'));
    }
    function paintRows(got) {
      const rows = got.rows || [], total = got.total || 0, states = got.states || {};
      const all = Object.values(states).reduce((a, n) => a + n, 0);
      fill(stateSel, el('option', {value: '', text: 'every row (' + all + ')', selected: !listView.state}),
        ...Object.entries(states).map(([k, n]) => el('option', {value: k, text: (LIST_STATES[k] || k) + ' (' + n + ')', selected: k === listView.state})),
        listView.state && !(listView.state in states) ? el('option', {value: listView.state, text: LIST_STATES[listView.state] || listView.state, selected: true}) : null);
      fill(rowsBox, ...rows.map(rowOf), rows.length ? null : el('p', {class: 's3-muted', text: listView.q || listView.state ? 'nothing matches' : 'this list is empty'}));
      const from = total ? got.offset + 1 : 0, to = got.offset + rows.length;
      fill(pager,
        btn('previous', () => { listView.offset = Math.max(0, listView.offset - listView.limit); loadRows(); }, {disabled: got.offset <= 0}),
        el('span', {class: 's3-muted', text: 'rows ' + from + '-' + to + ' of ' + total}),
        btn('next', () => { listView.offset += listView.limit; loadRows(); }, {disabled: to >= total}));
      const edits = got.edits || [];
      fill(log, edits.length ? el('details', null, el('summary', {text: 'desk edits on this list (' + edits.length + ' newest)'}),
        ...edits.map(e => el('div', {class: 's3-muted', text: [day(e.at), (e.who && (e.who.what + ' ' + e.who.addr)) || '', e.op,
          e.before && e.before.text ? '"' + String(e.before.text).slice(0, 60) + '"' : '',
          e.asked && e.asked.text ? '-> "' + String(e.asked.text).slice(0, 60) + '"' : e.asked && 'on' in e.asked ? '-> ' + (e.asked.on ? 'on' : 'off') : '',
          e.failed ? 'FAILED: ' + e.failed : ''].filter(Boolean).join(' · ')}))) : null);
    }
    async function loadRows() {
      let got;
      try { got = await request(base + '?' + new URLSearchParams({offset: listView.offset, limit: listView.limit, q: listView.q, state: listView.state})); }
      catch (e) { report(e); fill(rowsBox, el('p', {class: 's3-muted', text: 'could not read this list'})); return; }
      if (got.total && listView.offset >= got.total) { listView.offset = Math.max(0, Math.floor((got.total - 1) / listView.limit) * listView.limit); return loadRows(); }
      paintRows(got);
    }
    let addInput = null;
    const addRow = can.add ? el('div', 's3-row',
      addInput = el('input', {type: 'text', placeholder: bank ? 'a new line, word for word (recorded in his voice before it can air)' : 'a new row, word for word',
        style: 'flex:1;min-width:16em', 'aria-label': 'new item', onkeydown: e => { if (e.key === 'Enter') e.target.nextSibling.click(); }}),
      btn('Add item', () => { const t = addInput.value.trim(); if (!t) return;
        write(async () => { await send(base + '/rows', 'POST', {text: t}); addInput.value = ''; listView.q = ''; search.value = ''; },
          bank ? 'Added - queued to be recorded' : 'Added'); })) : null;
    card.append(
      el('div', 's3-row', el('h2', {text: (meta.label || meta.id) + ' · ' + (meta.family || 'LIST')}),
        el('span', {class: 's3-muted', text: meta.store ? 'store ' + meta.store : ''})),
      el('p', {class: 's3-muted', text: meta.what || ''}),
      el('div', 's3-row', search, stateSel, pager),
      addRow, rowsBox, log,
      el('p', {class: 's3-muted', text: 'Changes here go to the store at once - there is nothing to save.' +
        (can.switch ? ' Off keeps a row but it is never picked.' : '') + (bank ? ' A rewritten line airs only once it is recorded again.' : '')}));
    loadRows();
    return card;
  }

  function paintTables() {
    const tables = config.config.tables;
    if (!draft || draft.id !== tableId) draft = JSON.parse(JSON.stringify(tables.find(t => t.id === tableId) || tables[0]));
    const listNode = el('div', 's3-tlist', el('h2', {text: 'Tables'}),
      ...TABLE_FAMILIES.filter(f => tables.some(t => t.family === f)).flatMap(f => [el('h3', {text: f}), ...tables.filter(t => t.family === f).map(t =>
        btn('', () => { tableId = t.id; draft = null; paintTables(); }, {'aria-pressed': String(t.id === draft.id)}))]));
    let i = 0;
    for (const f of TABLE_FAMILIES) for (const t of tables.filter(x => x.family === f)) {
      const b = listNode.querySelectorAll('button')[i++];
      b.append(el('span', {text: `${t.id} · ${t.label}`}), el('span', {class: 's3-muted', text: t.enabled === false ? 'off' : 'w' + t.weight}));
    }
    const editor = el('div', 's3-card');
    /* [s3-es-emoji] AN ES ROW'S BADGE. "For messages that get an ES result from the
       roulette, have them display relevant emojis for each category in the bottom
       right of each message" (the operator, 2026-09-28): real colour emoji, the one
       exception to the Carbon-only rule, so the input names an emoji font first. A
       category's emoji sits beside its name; an item's beside its label - blank, it
       wears its category's (the placeholder). A cleared one is kept as "" and stays
       cleared. Space and Enter are held back: in a category's summary they fold it. */
    const esEmoji = (row, inherit, box) => el('input', {type: 'text', class: box ? 's3-emoji' : 's3-emoji s3-emoji-item',
      value: row.emoji || '', placeholder: inherit, maxlength: 16,
      'aria-label': box ? 'emoji for this feeling' : "emoji for this item (blank: its category's)",
      title: box ? 'the badge a message rolled in this feeling wears, at the bottom right of its bubble (blank: none)'
        : "this item's own badge (blank: it wears its category's)",
      style: "width:3em;flex:none;text-align:center;font-size:1.15em;font-family:'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif",
      onclick: e => e.stopPropagation(),
      onkeydown: e => { if (e.key === ' ' || e.key === 'Enter') e.preventDefault(); },
      oninput: e => { row.emoji = e.target.value.trim();
        if (box) for (const x of box.querySelectorAll('input.s3-emoji-item')) x.placeholder = row.emoji; }});
    const slider = (value, set, max = 5) => {
      const out = el('span', {text: num(value)});
      return [el('input', {type: 'range', min: 0, max, step: 0.05, value, oninput: e => { set(+e.target.value); out.textContent = num(+e.target.value); }}), out];
    };
    editor.append(el('div', 's3-row', el('h2', {text: `${draft.id} · ${draft.family}`}),
      el('input', {type: 'text', value: draft.label, oninput: e => { draft.label = e.target.value; }}),
      el('label', 's3-row', el('input', {type: 'checkbox', checked: draft.enabled !== false, onchange: e => { draft.enabled = e.target.checked; }}), 'enabled'),
      el('span', {class: 's3-muted', text: `version ${draft.version}`})),
      el('div', 's3-slider', el('label', {text: 'table weight in the raffle'}), ...slider(draft.weight, v => { draft.weight = v; }, 10)),
      ...(draft.family === 'EVENT' ? [el('div', 's3-row s3-pool',   /* [s3-events] */
        el('label', {class: 's3-muted', text: 'rolls on roads'}),
        el('input', {type: 'text', value: (draft.roads || []).join(', '), placeholder: 'caller, banter, news ... (blank = every road)', style: 'min-width:18em',
          onchange: e => { draft.roads = e.target.value.split(',').map(x => x.trim()).filter(Boolean); }}),
        el('label', {class: 's3-muted', text: 'at most'}),
        el('input', {type: 'number', min: 0, max: 8, step: 1, value: draft.max_events ?? 2, style: 'width:4em', 'aria-label': 'most happenings per segment',
          onchange: e => { draft.max_events = Math.max(0, parseInt(e.target.value || '0', 10) || 0); }}),
        el('span', {class: 's3-muted', text: 'happenings per segment (0 = no limit)'}))] : []),
      ...(draft.family === 'MEMORY' ? [memoryKnobs(draft)] : []),   /* [s3-memory] */
      el('p', {class: 's3-muted', text: draft.description || ''}));
    if (['CALLOPEN','CALLANGLE','CALLSTAKES','CALLPROBE','CALLSOURCE','RW'].includes(draft.family)) editor.append(para('Equal chances among eligible options. Positive weights are saved as 1; zero disables an option. Generated options stay proposed until operator approval.', 's3-muted'));
    if (draft.family === 'RESOLVE' || draft.family === 'WRAP') editor.append(callendTableFields(draft));   /* [s3-callend] */
    for (const cat of draft.categories) {
      /* [s3-window] each category folds; it can be dropped, or consolidated into another */
      const foldKey = draft.id + '/' + cat.id;
      const others = draft.categories.filter(c => c !== cat);
      const box = el('details', {class: 's3-cat', open: !foldedCats.has(foldKey),
        ontoggle: e => { if (e.target !== box) return; if (box.open) foldedCats.delete(foldKey); else foldedCats.add(foldKey); }});
      box.append(el('summary', null, el('b', {text: cat.label || cat.id}),
        draft.family === 'ES' ? esEmoji(cat, 'none', box) : null,   /* [s3-es-emoji] the feeling's badge, beside its name */
        el('span', {class: 's3-muted', text: `${(cat.items || []).length} items · w${num(cat.weight)}`}), el('span', {style: 'flex:1'}),
        others.length ? el('select', {'aria-label': 'consolidate into', title: 'move every item of this category into another one and drop it',
          onclick: e => e.stopPropagation(),
          onchange: e => { const into = draft.categories.find(c => c.id === e.target.value); if (!into) return;
            if (!confirm(`Move ${(cat.items || []).length} items of "${cat.label || cat.id}" into "${into.label || into.id}" and drop the category?`)) { e.target.value = ''; return; }
            into.items = (into.items || []).concat(cat.items || []); draft.categories.splice(draft.categories.indexOf(cat), 1); paintTables(); }},
          el('option', {value: '', text: 'consolidate into...'}), ...others.map(c => el('option', {value: c.id, text: c.label || c.id}))) : null,
        btn('remove', e => { e.preventDefault(); e.stopPropagation(); if (confirm(`Remove category "${cat.label || cat.id}" and its ${(cat.items || []).length} items?`)) { draft.categories.splice(draft.categories.indexOf(cat), 1); paintTables(); } })));
      box.append(el('div', 's3-slider', el('label', null, el('b', {text: 'category weight'})), ...slider(cat.weight, v => { cat.weight = v; })));
      if (draft.family === 'EVENT') box.append(eventFields(cat));   /* [s3-events] */
      if (draft.family === 'MEMORY') box.append(memoryFields(cat));   /* [s3-memory] */
      for (const item of cat.items) {
        const labelIn = el('input', {type: 'text', value: item.label, 'aria-label': 'label', style: draft.family === 'ES' ? 'min-width:0;flex:1' : null,
          oninput: e => { item.label = e.target.value; }});
        const row = el('div', 's3-item',
          draft.family === 'ES' ? el('span', {style: 'display:flex;gap:6px;align-items:center;min-width:0'},   /* [s3-es-emoji] its own badge */
            esEmoji(item, cat.emoji || '', null), labelIn) : labelIn,
          ...slider(item.weight ?? 1, v => { item.weight = v; }),
          el('label', 's3-row', el('input', {type: 'checkbox', checked: item.enabled !== false, onchange: e => { item.enabled = e.target.checked; }}), 'on'),
          el('input', {type: 'text', class: 'txt', value: item.text || '', placeholder: draft.family === 'DIRECTIVE' ? 'the directive, as the writer is told it' : draft.family === 'FAV' ? 'the line, word for word'
            : draft.family === 'ES' ? "Write {name}'s message with {feeling}, reflecting the mood."   /* [s3-es-dir] system3_tables.ES_DIRECTION: {feeling} = this item, {name} = the speaker */
            : draft.family === 'IL' ? 'the words said on the way in - {prev} is the one who was reading, {name} the one taking over'   /* [s3-split] */
            : 'what the writer is told this turn does', oninput: e => { item.text = e.target.value; }}),
          poolFields(item),
          /* [s3-flow] follow-on odds: after what the turn before rolled, this row weighs more (or less) */
          ['CTS', 'ES', 'RS', 'IRS', 'FL', 'EVENT'].includes(draft.family) ? el('input', {type: 'text', class: 'txt s3-after',
            value: Object.entries(item.after || {}).map(([k, m]) => `${k}=${m}`).join(', '),
            placeholder: 'follow-on odds, e.g. RS:argue=1.6, ES:anger=0.5 (after the turn before rolled it)',
            onchange: e => { const got = {}; for (const part of e.target.value.split(',')) { const [k, m] = part.split('=').map(x => (x || '').trim()); if (k && m && !isNaN(+m)) got[k] = +m; }
              if (Object.keys(got).length) item.after = got; else delete item.after; }}) : null);
        /* [s3-window] drag to reorder inside the category; x removes */
        const wrap = el('div', {class: 's3-item-row', draggable: false,   /* [s3-grip-drag] only the grip arms the drag */
          ondragstart: e => { if (!wrap.draggable) { e.preventDefault(); return; } tableDrag = {cat, item}; wrap.classList.add('s3-dragging'); try { e.dataTransfer.setData('text/plain', item.id); } catch (_) { /* older engine */ } },
          ondragend: () => { wrap.classList.remove('s3-dragging'); wrap.draggable = false; tableDrag = null; },
          ondragover: e => { if (tableDrag && tableDrag.cat === cat && tableDrag.item !== item) { e.preventDefault(); wrap.classList.add('s3-drop-before'); } },
          ondragleave: () => wrap.classList.remove('s3-drop-before'),
          ondrop: e => { wrap.classList.remove('s3-drop-before'); if (!tableDrag || tableDrag.cat !== cat) return; e.preventDefault();
            const from = cat.items.indexOf(tableDrag.item); if (from < 0) return; const [moved] = cat.items.splice(from, 1);
            const to = cat.items.indexOf(item); cat.items.splice(to < 0 ? cat.items.length : to, 0, moved); tableDrag = null; paintTables(); }},
          el('span', {class: 's3-grip', title: 'drag to reorder', text: '\u22ee\u22ee',
            onpointerdown: () => { wrap.draggable = true; }, onpointerup: () => { wrap.draggable = false; }}), row,
          btn('x', () => { cat.items.splice(cat.items.indexOf(item), 1); paintTables(); }, {'aria-label': 'remove item', style: 'padding:0 6px'}));
        box.append(wrap);
      }
      const adv = el('textarea', {value: json(Object.fromEntries(Object.entries(cat).filter(([k]) => !['items', 'label', 'weight', 'id', 'emoji'].includes(k))))});   /* [s3-es-emoji] */
      box.append(btn(draft.family === 'DIRECTIVE' ? 'Add directive' : draft.family === 'FAV' ? 'Add favourite' : 'Add item', () => {
          if (draft.family === 'EVENT') {   /* [s3-events] a variant of the happening is what the writer is told happens */
            const text = prompt('What happens (the writer is told this on the turn it lands on; {first} is the caller)'); if (!text || !text.trim()) return;
            cat.items.push({id: 'ev_' + Date.now().toString(36), label: text.slice(0, 60), text: text.trim(), weight: 1}); paintTables(); return;
          }
          if (draft.family === 'DIRECTIVE' || draft.family === 'FAV') {   /* [s3-cast] a pool row is its words */
            const text = prompt(draft.family === 'DIRECTIVE' ? 'The directive (what the writer is told on the turn it lands on)' : 'The line, word for word'); if (!text || !text.trim()) return;
            const id = (draft.family === 'DIRECTIVE' ? 'dir_' : 'fav_') + Date.now().toString(36);
            cat.items.push(draft.family === 'DIRECTIVE' ? {id, label: text.slice(0, 60), text: text.trim(), weight: 1, odds: 1, until: 0, airings: 0, source: 'the System 3 desk'}
              : {id, label: text.slice(0, 60), text: text.trim(), weight: 1, source: 'the System 3 desk', at: Math.round(Date.now() / 1000)});
            paintTables(); return;
          }
          const id = prompt('New item id'); if (id) { cat.items.push({id, label: id, weight: 1, text: ''}); paintTables(); } }),
        el('details', null, el('summary', {text: 'rules for this category (requires, phases, modifiers, emotions, effects, tags ...)'}), adv,
          btn('Apply rules', () => { try { Object.assign(cat, JSON.parse(adv.value)); quiet(); } catch (e) { report(e); } })));
      editor.append(box);
    }
    editor.append(el('div', 's3-row',
      btn('Save table', async () => { try { const res = await send('/api/system3/tables/' + draft.id, 'PUT', draft); await loadConfig(); draft = null; paint(); saved('table ' + (res && res.table ? res.table.id : ''), res); } catch (e) { report(e); } }),
      btn('Add category', () => { const id = prompt('New category id'); if (id) { draft.categories.push({id, label: id.toUpperCase(), weight: 1, items: [{id: id + '.one', label: 'one', weight: 1}]}); paintTables(); } }),
      btn('Make a supplemental table from this one', async () => {
        const id = prompt('New table id (for example ES2)'); if (!id) return;
        const copy = JSON.parse(JSON.stringify(draft)); copy.id = id; copy.label = draft.label + ' (' + id + ')'; copy.version = 1;
        try { await send('/api/system3/tables/' + id, 'PUT', copy); await loadConfig(); tableId = id; draft = null; paint(); } catch (e) { report(e); }
      }),
      btn('Delete table', async () => { if (!confirm('Delete ' + draft.id + '?')) return; try { await send('/api/system3/tables/' + draft.id, 'DELETE'); await loadConfig(); tableId = 'ES1'; draft = null; paint(); } catch (e) { report(e); } }),
      btn('Discard changes', () => { draft = null; paintTables(); }),
      el('span', {class: 's3-muted', text: 'Every save is a new config version; conversations keep the version they were planned under.'})));
    fill(body, el('div', 's3-edit', listNode, listId ? listEditor() : editor));   /* [s3-lists] */
    paintListNav(listNode);
  }

  /* ---------------- structure: the node view -------------------------------- */
  let steps = null;
  /* [s3-roads] every road's structure is on the desk: the banter cycle, and
     one legs structure per segment road and single-voice road. */
  let structRoad = 'banter';
  let legs = null, legsRoad = '';
  function roadPicker() {
    const roads = ['banter', ...Object.keys(config.config.structures || {})];
    return el('div', 's3-row', el('label', {class: 's3-muted', text: 'road'}),
      el('select', {'aria-label': 'road', onchange: e => { structRoad = e.target.value; steps = null; legs = null; paintStructure(); }},
        ...roads.map(r => el('option', {value: r, text: r === 'banter' ? 'banter (the cycle)' : r + ' (' + ((config.config.structures[r] || {}).kind || 'legs') + ')', selected: r === structRoad}))));
  }
  function paintLegs(road) {
    const st = (config.config.structures || {})[road] || {legs: []};
    if (!legs || legsRoad !== road) { legs = JSON.parse(JSON.stringify(st.legs || [])); legsRoad = road; }
    const famChoice = ['ES', 'RS', 'IRS', 'FL', 'CTS'];
    const nodes = el('div', 's3-nodes');
    legs.forEach((lg, i) => {
      lg.draws ||= [];
      const draws = el('div', 's3-row', ...lg.draws.map((d, k) => el('span', {class: 's3-pill', style: `border-color:${FAM[d.family]}`},
        `[${d.family}${d.tables ? ':' + d.tables.join('/') : ''}${d.closes ? ' closes' : ''}]`,
        btn('x', () => { lg.draws.splice(k, 1); paintStructure(); }, {'aria-label': 'remove draw', style: 'padding:0 6px'}))),
        el('select', {'aria-label': 'add a draw', onchange: e => { if (e.target.value) { lg.draws.push(e.target.value === 'FL' ? {family: 'FL', tables: ['FL2']} : {family: e.target.value}); paintStructure(); } }},
          el('option', {value: '', text: '+ draw'}), ...famChoice.map(f => el('option', {value: f, text: f}))));
      nodes.append(el('div', 's3-node s3-leg',
        el('div', 's3-row',
          el('input', {type: 'text', value: lg.label || lg.id || '', 'aria-label': 'leg', oninput: e => { lg.label = e.target.value; }}),
          el('select', {'aria-label': 'place', onchange: e => { lg.place = e.target.value; }},
            ...['open', 'middle', 'close'].map(p => el('option', {value: p, text: p, selected: lg.place === p}))),
          el('select', {'aria-label': 'seat', onchange: e => { lg.seat = e.target.value; }},
            ...['A', 'B', 'C', 'D', 'E', 'alternate'].map(p => el('option', {value: p, text: p === 'alternate' ? 'alternating' : 'seat ' + p, selected: lg.seat === p})))),
        el('textarea', {class: 's3-leg-act', 'aria-label': 'what this leg does', value: lg.act || '', oninput: e => { lg.act = e.target.value; }}),
        draws, st.kind === 'line' ? splitBox(lg, paintStructure, 'leg') : null,   /* [s3-split] a line road's read */
        el('div', 's3-row',
          btn('up', () => { if (i) { [legs[i - 1], legs[i]] = [legs[i], legs[i - 1]]; paintStructure(); } }),
          btn('down', () => { if (i < legs.length - 1) { [legs[i + 1], legs[i]] = [legs[i], legs[i + 1]]; paintStructure(); } }),
          btn('remove', () => { legs.splice(i, 1); paintStructure(); }))));
      nodes.append(el('div', 's3-arrow'));
    });
    const budget = st.kind === 'line' ? 'One voice, one leg per line.' : `Turn budget ${st.min_turns || '?'} to ${st.max_turns || '?'}: the open legs first, the middle leg repeated to the budget with the seats alternating, the closing legs last.`;
    fill(body, el('div', 's3-card', el('h2', {text: (st.label || road) + ' structure'}), roadPicker(),
      el('p', {class: 's3-muted', text: 'Each leg is one node of this road: what the turn does (the act the writer is given), where it sits, whose seat, and the families it rolls. ' + budget + ' Every leg rolls ES for how it is said.'}),
      nodes, el('div', 's3-row',
        btn('Add leg', () => { legs.push({id: 'leg' + (legs.length + 1), label: 'New leg', place: 'middle', seat: 'alternate', act: 'answers the line before.', draws: [{family: 'ES'}, {family: 'RS'}]}); paintStructure(); }),
        btn('Save structure', async () => {
          try {
            legs.forEach((lg, i) => { lg.id ||= 'leg' + i; });
            await send('/api/system3/structures/' + encodeURIComponent(road), 'PUT', {...st, legs});
            await loadConfig(); legs = null; paint();
          } catch (e) { report(e); }
        }),
        btn('Discard', () => { legs = null; paintStructure(); }))));
  }
  function paintStructure() {
    if (structRoad !== 'banter') { paintLegs(structRoad); return; }
    const structure = config.config.structure;
    if (!steps) steps = JSON.parse(JSON.stringify(structure.steps));
    const nodes = el('div', 's3-nodes');
    const famChoice = ['CTS', 'ES', 'RS', 'IRS', 'FL'];
    steps.forEach((st, i) => {
      const draws = el('div', 's3-row', ...st.draws.map((d, k) => el('span', {class: 's3-pill', style: `border-color:${FAM[d.family]}`},
        `[${d.family}${d.tables ? ':' + d.tables.join('/') : ''}]`, btn('x', () => { st.draws.splice(k, 1); paintStructure(); }, {'aria-label': 'remove draw', style: 'padding:0 6px'}))),
        el('select', {onchange: e => { if (e.target.value) { st.draws.push({family: e.target.value}); paintStructure(); } }},
          el('option', {value: '', text: '+ draw'}), ...famChoice.map(f => el('option', {value: f, text: f}))));
      const mark = (m) => el('label', {class: 'mark' + ((st.speakerbox || []).includes(m) ? ' on' : '')},
        el('input', {type: 'checkbox', checked: (st.speakerbox || []).includes(m), onchange: e => {
          st.speakerbox = (st.speakerbox || []).filter(x => x !== m); if (e.target.checked) st.speakerbox.push(m); paintStructure(); }}), m === 'prepend' ? 'Prepend' : 'Append');
      nodes.append(el('div', 's3-node',
        el('div', 's3-row', el('input', {type: 'text', value: st.label, oninput: e => { st.label = e.target.value; }}),
          el('select', {onchange: e => { st.speaker = e.target.value; }},
            ...['initiator', 'responder_a', 'responder_b', 'frame'].map(s => el('option', {value: s, text: s.replace('_', ' '), selected: st.speaker === s}))),
          el('label', 's3-row s3-muted', el('input', {type: 'checkbox', checked: !!st.optional, onchange: e => { st.optional = e.target.checked; }}), 'optional')),
        draws, splitBox(st, paintStructure, 'step'),   /* [s3-split] a speaker-box monologue on this step */
        el('div', 's3-row', mark('prepend'), mark('append'),
          btn('up', () => { if (i) { [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]]; paintStructure(); } }),
          btn('down', () => { if (i < steps.length - 1) { [steps[i + 1], steps[i]] = [steps[i], steps[i + 1]]; paintStructure(); } }),
          btn('remove', () => { steps.splice(i, 1); paintStructure(); }))));
      nodes.append(el('div', 's3-arrow'));
    });
    nodes.append(el('div', 's3-node', el('b', {text: 'Closing turn'}), el('div', 's3-muted',
      'The last turn of every scene draws: ' + structure.closing.draws.map(d => d.family + (d.closes ? ' (closing moves only)' : '')).join(', '))),
      el('div', 's3-loop', 'Handoff initiator role to the other party → loop the cycle for the segment duration. The structure loops, not the dialogue.'));
    fill(body, el('div', 's3-card', el('h2', {text: structure.label + ' structure'}), roadPicker(),
      el('p', {class: 's3-muted', text: 'Mark the lines that roll for a speakerbox insertion before (prepend) or after (append) them. The odds are the prepend and append sliders on the DJ desk, scaled by the Speakerbox density control. When both win on one line, the prepend-or-append roulette (SBEND1 in Tables) picks one.'}),   /* [s3-sb-end] */
      nodes, el('div', 's3-row',
        btn('Add step', () => { steps.push({id: 'step' + (steps.length + 1), label: 'New step', speaker: 'responder_a', draws: [{family: 'ES'}, {family: 'RS'}], speakerbox: []}); paintStructure(); }),
        btn('Save structure', async () => { try { steps.forEach((s, i) => { s.id ||= 'step' + i; }); const res = await send('/api/system3/structure', 'PUT', {steps}); await loadConfig(); steps = null; paint(); saved('the banter cycle', res); } catch (e) { report(e); } }),
        btn('Discard', () => { steps = null; paintStructure(); }))));
  }

  /* ---------------- segments: the node editor ------------------------------
   *
   * "a vertical node editor from top to bottom, a sidebar with the categories
   *  and nodes ... drag and drop into the segment ... remove and rearrange
   *  inline ... properties in the sidebar ... a dice icon to lock a node to
   *  a static value (uncheck = roulette off, dropdown sets the static prop)
   *  ... a dropdown listing all segments ... duplicate a segment into a
   *  variant runnable on the station with unique parameters."
   *
   * A segment is a road's structure: legs (or, for the banter cycle, steps),
   * each with its draws. A pinned draw carries `fixed` - the engine records
   * it without a roll. A variant is saved as "<road>~vN" with a weight; the
   * engine rolls VARIANT among the base and its variants when the road runs. */
  let segRoad = (startTab === 'segments' && startTable) ? startTable : '', segNodes = null, segRoadOf = '', segSel = {node: -1, draw: -1}, segDrag = null;   /* [pine-graph] segments:<road> lands on that road */
  let segGraph = null, segGraphOf = '', segGraphSel = '', segGraphScene = null, segGraphPresets = null;
  let segGraphEdgeSel = -1, segGraphArm = null;   /* [pine-graph] the tapped flow line; the palette chip armed to drop */
  let segGraphViewState = {zoom: 1, panX: 0, panY: 0};
  let segInitiator = null;   /* [s3-flow] who opens the banter cycle (null: as saved) */
  const SEG_FAMS = ['CTS', 'ES', 'RS', 'IRS', 'FL'];
  function segStructures() { return config.config.structures || {}; }
  function segLoad(road) {
    if (segNodes && segRoadOf === road) return;
    if (segGraphOf !== road) segGraphViewState = {zoom: 1, panX: 0, panY: 0};
    segRoadOf = road; segSel = {node: -1, draw: -1};
    segNodes = road === 'banter' ? JSON.parse(JSON.stringify(config.config.structure.steps || []))
      : JSON.parse(JSON.stringify((segStructures()[road] || {}).legs || []));
    segGraphOf = road;
    const saved = road === 'banter' ? config.config.structure.graph : (segStructures()[road] || {}).graph;
    const fallback = road === 'banter' ? {nodes: [], edges: [], start: '', topic_options: [], max_steps: 48}
      : {enabled: true, start: 'protocol', nodes: [{id: 'protocol', type: 'protocol', label: road + ' protocol',
          protocol_road: road, x: 0, y: 0, seconds: 60, chance: 1, draws: []}],
        edges: [], topic_options: [], max_steps: 48};
    segGraph = JSON.parse(JSON.stringify(saved || fallback));
    segGraphSel = (segGraph.nodes[0] || {}).id || '';
  }
  function segTableCats(fam) {   /* [s3-flow] */
    const seen = new Map();
    for (const t of (config.config.tables || []).filter(x => x.family === fam))
      for (const c of t.categories || []) if (!seen.has(c.id)) seen.set(c.id, {id: c.id, label: `${t.id} · ${c.label || c.id}`});
    return [...seen.values()];
  }
  function segTableItems(fam) {
    return (config.config.tables || []).filter(t => t.family === fam)
      .flatMap(t => (t.categories || []).flatMap(c => (c.items || []).map(it => ({id: it.id, label: `${t.id} · ${c.label || c.id} · ${it.label || it.id}`}))));
  }
  function segGraphView(repaint) {
    const graph = segGraph, nodes = graph.nodes || (graph.nodes = []), edges = graph.edges || (graph.edges = []);
    const selected = nodes.find(n => n.id === segGraphSel);
    const box = el('section', 's3-card s3-graph-editor', el('h2', {text: 'Conversation graph'}));
    if (segGraphPresets === null) request('/api/system3/graph/presets').then(got => {
      segGraphPresets = got.presets || {}; if (tab === 'segments') repaint();
    }).catch(() => { segGraphPresets = {}; });
    const presetNames = Object.keys(segGraphPresets || {}).sort();
    const presetPick = el('select', {'aria-label': 'Conversation graph preset'},
      el('option', {value: '', text: 'Choose a saved preset'}),
      ...presetNames.map(name => el('option', {value: name, text: name})));
    const canvas = el('canvas', {class: 's3-graph-canvas', 'aria-label': 'Three dimensional conversation flowchart'});
    const preview = el('pre', 's3-graph-preview'); preview.hidden = true;
    const previewMinutes = el('input', {type: 'number', min: .5, max: 60, step: .5, value: 3,
      'aria-label': 'Preview segment minutes', style: 'width:70px'});
    const previewCaller = el('input', {type: 'checkbox', 'aria-label': 'Caller available in preview'});
    const refresh = () => { if (segGraphScene) { segGraphScene.stop(); segGraphScene = null; } repaint(); };
    box.append(el('div', 's3-seg-bar',
      el('label', 's3-row', el('input', {type: 'checkbox', checked: !!graph.enabled,
        onchange: e => { graph.enabled = e.target.checked; }}), 'Run this graph when System 3 writes this road'),
      btn('Start from talk template', async () => { try { const got = await request('/api/system3/graph/template');
        segGraph = JSON.parse(JSON.stringify(got.graph)); segGraph.enabled = true;
        segGraphSel = (segGraph.nodes[0] || {}).id || ''; refresh(); }
        catch (e) { report(e); } }),
      segRoad !== 'banter' ? btn("Start from this road's own segment", async () => { try {   /* [pine-graph] road_graph */
        const got = await request('/api/system3/graph/template?road=' + encodeURIComponent(segRoad.split('~')[0]));
        segGraph = JSON.parse(JSON.stringify(got.graph)); segGraph.enabled = true;
        segGraphSel = (segGraph.nodes[0] || {}).id || ''; refresh(); } catch (e) { report(e); } }) : null,
      segRoad !== 'banter' ? btn('Wrap existing protocol', () => { segGraph = {enabled: true, start: 'protocol',
        nodes: [{id: 'protocol', type: 'protocol', label: segRoad + ' protocol', protocol_road: segRoad,
          x: 0, y: 0, seconds: 60, chance: 1, draws: []}], edges: [], topic_options: [], max_steps: 48};
        segGraphSel = 'protocol'; refresh(); }) : null,
      btn('Save as preset', async () => { const name = prompt('Preset name:', 'Talk chapter'); if (!name) return;
        try { const got = await send('/api/system3/graph/presets/' + encodeURIComponent(name), 'PUT', {graph});
          segGraphPresets = segGraphPresets || {}; segGraphPresets[got.name] = got.graph;
          refresh(); saved('graph preset ' + got.name, got); } catch (e) { report(e); } }),
      presetPick,
      btn('Load preset', () => { const copy = (segGraphPresets || {})[presetPick.value]; if (!copy) return;
        segGraph = JSON.parse(JSON.stringify(copy)); segGraphSel = (segGraph.nodes[0] || {}).id || ''; refresh(); }),
      btn('Delete preset', async () => { if (!presetPick.value) return; const name = presetPick.value;
        try { await send('/api/system3/graph/presets/' + encodeURIComponent(name), 'DELETE');
          delete segGraphPresets[name]; refresh(); } catch (e) { report(e); } }),
      btn('Add node', () => { const id = 'node-' + Date.now().toString(36); graph.enabled = true;
        nodes.push({id, label: 'Reply', type: 'reply', x: 0, y: nodes.length * 100, seconds: 15, chance: 1,
          draws: [{family: 'ES'}, {family: 'RS'}]}); if (!graph.start) graph.start = id;
        segGraphSel = id; refresh(); }),
      el('label', 's3-row', 'Preview minutes', previewMinutes),
      el('label', 's3-row', previewCaller, 'Caller available'),
      btn('Preview dice', async () => { try { const seconds = Math.max(30, Math.min(3600, Number(previewMinutes.value) * 60 || 180));
        const got = await send('/api/system3/graph/preview', 'POST',
        {road: segRoad, graph, seconds, turns: Math.max(2, Math.round(seconds / 15)),
          caller_available: previewCaller.checked, seed: 'editor-preview'});
        preview.textContent = (got.protocol ? `${got.protocol} runs its existing internal protocol nodes below.` : '')
          + (got.protocol ? '\n' : `Planned ${got.estimated_seconds || 0}s inside ${got.budget_seconds || seconds}s.\n`)
        + (got.turns || []).map((t, i) => `${i + 1}. ${t.name || t.speaker} / ${t.node}: ${t.work || t.protocol || ''}${t.feeling ? ' [' + t.feeling + (t.intonation ? ', ' + t.intonation : '') + ']' : ''}`).join('\n')   /* [pine-graph] the contract's preview fields */
          + '\n\n' + (got.rolls || []).map(r => `${r.node} ${r.kind}: d${r.dice || '?'} → ${r.selected}`).join('\n');
        preview.hidden = false; } catch (e) { report(e); } })));
    const props = el('aside', 's3-graph-properties');
    const replies = graph.reply_roulette || (graph.reply_roulette = {enabled: true, react_all: true,
      initiator_weight: 1, last_weight: 1, answer_weight: 2, other_weight: 1, return_weight: 2, max_credits: 8});
    const replyControls = el('section', 's3-card', el('h3', {text: 'Reply roulette'}),
      el('p', {text: 'A reply to another DJ restores its turn. A fresh wheel chooses an answer, another voice, or the topic instigator. Every extreme line gives each other person an independent emotion and response roll.'}));
    for (const [label, key] of [['Enable reply targets and inner exchanges', 'enabled'], ['Roll reactions for every person after an extreme line', 'react_all']]) {
      replyControls.append(el('label', 's3-row', el('input', {type: 'checkbox', checked: !!replies[key],
        onchange: e => { replies[key] = e.target.checked; }}), label));
    }
    for (const [label, key] of [['Target: topic instigator weight', 'initiator_weight'], ['Target: latest speaker weight', 'last_weight'],
      ['Follow-up: addressed person weight', 'answer_weight'], ['Follow-up: another DJ weight', 'other_weight'],
      ['Follow-up: return to topic weight', 'return_weight'], ['Extra turn budget', 'max_credits'], ['Cast reaction group budget', 'max_reaction_groups']]) {
      replyControls.append(el('label', 's3-row', label, el('input', {type: 'number', min: 0,
        max: key.startsWith('max_') ? 32 : 100, step: key.startsWith('max_') ? 1 : .1, value: replies[key] ?? 4,
        onchange: e => { replies[key] = Number(e.target.value); }})));
    }
    box.append(replyControls);
    const field = (label, control) => props.append(el('label', null, label, control));
    if (selected) {
      props.append(el('h3', {text: selected.label || selected.id}));
      field('Type', el('select', {onchange: e => { selected.type = e.target.value; refresh(); }},
        ...(selected.type === 'protocol' ? ['protocol'] : ['initiator', 'reply', 'rebuttal', 'decision', 'topic_change', 'call', 'book_reader', 'end'])
          .map(type => el('option', {value: type, text: type.replace('_', ' '), selected: selected.type === type}))));
      for (const [label, key, lines] of [['Label', 'label', 0], ['Speaker / seat (blank: cast raffle)', 'speaker', selected.type === 'protocol' ? -1 : 0],
        ['Reply as the speaker from node ID', 'respond_to', selected.type === 'reply' ? 0 : -1],
        ['Specific topic', 'topic', selected.type === 'protocol' ? -1 : 2],
        ['Writer direction', 'prompt', selected.type === 'protocol' ? -1 : 3],
        ['Protocol road (a call node: caller = rob the caller road; an initiator on a LINE road: its leg is the opening)', 'protocol_road', (selected.type === 'protocol' || selected.type === 'initiator' || selected.type === 'call') ? 0 : -1]]) {   /* [pine-graph] contract rev 2 */
        if (lines === -1) continue;
        const control = lines ? el('textarea', {rows: lines, value: selected[key] || '', onchange: e => { selected[key] = e.target.value; }})
          : el('input', {value: selected[key] || '', onchange: e => { selected[key] = e.target.value; refresh(); }});
        field(label, control);
      }
      if (selected.type === 'book_reader') {
        field('Reader roles, in order', el('input', {value: (selected.readers || ['host', 'cohost', 'third']).join(', '), onchange: e => { selected.readers = e.target.value.split(',').map(r => r.trim()).filter(Boolean); }}));
        field('Routing', el('select', {onchange: e => { selected.routing = e.target.value; }}, ...['single', 'sequential', 'roulette'].map(r => el('option', {value: r, text: r, selected: (selected.routing || 'sequential') === r}))));
        props.append(para('Host, cohost, third, sfx, manager and caller are available. This node assigns the next reader in Book Mode. FM passes through it.', 's3-muted'));
        props.append(el('button', {type: 'button', text: 'Use this node for book narration', onclick: async e => {
          try { await request('/api/books/preferences', {method: 'POST', body: JSON.stringify({readers: selected.readers || ['host', 'cohost', 'third'], routing: selected.routing || 'sequential', reader_node: {id: selected.id, label: selected.label, weights: selected.weights || {}}})}); e.target.textContent = 'Book reader node applied'; }
          catch (err) { e.target.textContent = String(err.message || err); }
        }}));
      }
      if (selected.type === 'protocol') props.append(para('This node runs the existing road protocol. Its individual turns and table rolls are edited in the leg list below.', 's3-muted'));
      else {
      for (const [label, key, min, max, step] of [['Chance to speak', 'chance', 0, 1, .01],
        ['Estimated seconds', 'seconds', 0, 300, 1], ['X position', 'x', -2000, 2000, 10], ['Y position', 'y', -2000, 2000, 10]])
        field(label, el('input', {type: 'number', min, max, step, value: selected[key] == null ? 0 : selected[key],
          onchange: e => { selected[key] = Number(e.target.value); refresh(); }}));
      if (selected.type === 'rebuttal' || (selected.type === 'reply' && selected.respond_to)) {
        for (const [label, key] of [['How this argument lands (one option per line)', 'moods'],
          ['Intonation (one option per line)', 'intonations']])
          field(label, el('textarea', {rows: 3, value: (selected[key] || []).join('\n'),
            placeholder: 'Blank uses the System 3 defaults', onchange: e => {
              selected[key] = e.target.value.split('\n').map(s => s.trim()).filter(Boolean); }}));
      }
      if (selected.type === 'call') field('Call chain leg (where this turn sits in the nested call; close carries the rolled RESOLVE)',   /* [pine-graph] */
        el('select', {onchange: e => { if (e.target.value) selected.call_leg = e.target.value; else delete selected.call_leg; refresh(); }},
          ...['', 'open', 'middle', 'close'].map(lg => el('option', {value: lg, text: lg || 'unmarked', selected: (selected.call_leg || '') === lg}))));
      props.append(el('h4', {text: 'System 3 table rolls'}));
      for (const family of ['CTS', 'ES', 'RS', 'IRS', 'FL']) {
        const draw = (selected.draws || []).find(d => d.family === family);
        props.append(el('label', 's3-row', el('input', {type: 'checkbox', checked: !!draw,
          onchange: e => { selected.draws = (selected.draws || []).filter(d => d.family !== family);
            if (e.target.checked) selected.draws.push({family}); refresh(); }}), family));
        if (draw) props.append(el('select', {'aria-label': family + ' table',
          onchange: e => { draw.tables = e.target.value ? [e.target.value] : []; }},
          el('option', {value: '', text: 'all ' + family + ' tables'}),
          ...(config.config.tables || []).filter(t => t.family === family)
            .map(t => el('option', {value: t.id, text: t.label || t.id, selected: (draw.tables || []).includes(t.id)}))));
      }
      }
      props.append(btn('Remove node', () => { graph.nodes = nodes.filter(n => n.id !== selected.id);
        graph.edges = edges.filter(e => e.from !== selected.id && e.to !== selected.id);
        if (graph.start === selected.id) graph.start = (graph.nodes[0] || {}).id || '';
        segGraphSel = (graph.nodes[0] || {}).id || ''; refresh(); }));
      props.append(el('div', 's3-row',   /* [pine-graph] */
        btn('Duplicate', () => { const copy = JSON.parse(JSON.stringify(selected));
          copy.id = 'node-' + Date.now().toString(36);
          copy.x = (Number(copy.x) || 0) + 40; copy.y = (Number(copy.y) || 0) + 70;
          nodes.push(copy); segGraphSel = copy.id; segGraphEdgeSel = -1; refresh(); }),
        graph.start === selected.id ? null
          : btn('Make this the start', () => { graph.start = selected.id; refresh(); })));
    } else if (segGraphEdgeSel >= 0 && edges[segGraphEdgeSel]) {   /* [pine-graph] a flow line's own card */
      const edge = edges[segGraphEdgeSel];
      const among = edges.filter(e2 => e2.from === edge.from);
      const total = among.reduce((s, e2) => s + Math.max(0, Number(e2.weight) || 0), 0);
      const share = total > 0 ? Math.max(0, Number(edge.weight) || 0) / total : 0;
      props.append(el('h3', {text: 'Flow line'}),
        para(edge.from + ' -> ' + edge.to + (among.length > 1 && share > 0
          ? '  -  ' + Math.round(share * 100) + '% (' + pgOdds(share) + ')' : ''), 's3-muted'));
      field('Weight - the branch dice against its brothers from the same node',
        el('input', {type: 'number', min: 0, max: 100, step: .01, value: edge.weight == null ? 1 : edge.weight,
          onchange: e => { edge.weight = Number(e.target.value); refresh(); }}));
      field('Label written on the line, in your own hand - say (1:2) Reply',
        el('input', {value: edge.label || '', onchange: e => {
          if (e.target.value.trim()) edge.label = e.target.value.trim().slice(0, 60); else delete edge.label;
          refresh(); }}));
      props.append(btn('Cut this flow line', () => { edges.splice(segGraphEdgeSel, 1); segGraphEdgeSel = -1; refresh(); }));
    } else props.append(para('Tap a node or a flow line for its card. Drag a chip onto the paper for a new node; '
      + 'drag a node by its body to move it; drag the pip under a node onto another node to ink a flow line.', 's3-muted'));
    const list = el('div', 's3-graph-list', ...nodes.map(n => btn(n.label || n.id,
      () => { segGraphSel = n.id; refresh(); }, {'aria-pressed': String(n.id === segGraphSel)})));
    const viewControls = el('div', 's3-graph-view-controls',
      btn('−', () => { if (segGraphScene) segGraphScene.zoomBy(1 / 1.25); }, {'aria-label': 'Zoom graph out'}),
      btn('+', () => { if (segGraphScene) segGraphScene.zoomBy(1.25); }, {'aria-label': 'Zoom graph in'}),
      btn('Fit', () => { if (segGraphScene) segGraphScene.fit(); }),
      btn('Tidy', () => pgTidy(), {'aria-label': 'Lay the chain out top to bottom'}),   /* [pine-graph] */
      el('span', {class: 's3-muted', text: 'Pinch or roll to zoom. Drag the paper to pan; drag a node to move it; drag the pip under a node onto another node to ink a flow line; tap a line for its dice.'}));   /* [pine-graph] */
    /* [pine-graph] the drawing's parts, dragged onto the paper. A chip rides
       the pointer as an ink ghost and lands as a new node where it is let go;
       a plain tap arms the chip so the next tap on the paper places it - the
       tablet's two-tap road. pgPlace is also the scene's own place() hook. */
    function pgPlace(kind, gx, gy) {
      if (!kind) return;
      segGraphArm = null;
      const names = {initiator: 'Initiator', reply: 'Reply', rebuttal: 'Rebuttal', decision: 'Dice gate',
        call: 'Phone call', topic_change: 'Topic Change', book_reader: 'Book reader', end: 'End'};
      const id = 'node-' + Date.now().toString(36);
      graph.enabled = true;
      nodes.push({id, type: kind, label: names[kind] || kind,
        x: Math.round(Math.max(-2000, Math.min(2000, gx))), y: Math.round(Math.max(-2000, Math.min(2000, gy))),
        seconds: kind === 'decision' ? 0 : 15, chance: 1,
        draws: kind === 'decision' || kind === 'end' ? [] : kind === 'rebuttal'
          ? [{family: 'ES'}, {family: 'IRS'}] : [{family: 'ES'}, {family: 'RS'}]});
      if (!graph.start) graph.start = id;
      segGraphSel = id; segGraphEdgeSel = -1; refresh();
    }
    function pgOdds(p) { return p >= 1 ? 'sure' : p <= 0 ? 'never' : '1:' + Math.max(2, Math.round(1 / p)); }
    function pgTidy() {   /* [pine-graph] the chain laid top to bottom, staggered like the sketch */
      const out = new Map(nodes.map(n => [n.id, []]));
      edges.forEach(e2 => { if (out.has(e2.from) && out.has(e2.to)) out.get(e2.from).push(e2.to); });
      const depth = new Map(); const queue = [[graph.start || (nodes[0] || {}).id, 0]];
      while (queue.length) { const [id, d] = queue.shift();
        if (!id || depth.has(id)) continue;
        depth.set(id, d); (out.get(id) || []).forEach(to => queue.push([to, d + 1])); }
      let stray = 0;
      const most = Math.max(0, ...depth.values());
      const rows = new Map();
      nodes.forEach(n => { const d = depth.has(n.id) ? depth.get(n.id) : most + (++stray);
        if (!rows.has(d)) rows.set(d, []); rows.get(d).push(n); });
      [...rows.keys()].sort((d1, d2) => d1 - d2).forEach((d, ri) => { const row = rows.get(d);
        row.forEach((n, ci) => { n.y = ri * 130; n.x = (ci - (row.length - 1) / 2) * 270 + ((ri % 2) ? 70 : -70); }); });
      segGraphViewState = {zoom: 1, panX: 0, panY: 0};
      refresh();
    }
    function pgProblems(g) {   /* [pine-graph] the engine's validate(), read before the save */
      const ns = g.nodes || []; if (!ns.length) return [];
      if (ns.some(n => n.type === 'protocol'))
        return (ns.length !== 1 || (g.edges || []).length) ? ['a protocol node stands alone: one node, no flow lines'] : [];
      const problems = [];
      if (!ns.some(n => n.type === 'end')) problems.push('no end node, so the segment cannot close');
      const replyIds = new Set(ns.filter(n => n.type === 'reply').map(n => n.id));
      const badRef = ns.filter(n => n.respond_to && !replyIds.has(n.respond_to)).map(n => n.label || n.id);
      if (badRef.length) problems.push('reply source must name a reply node: ' + badRef.slice(0, 3).join(', '));
      const out = new Map(ns.map(n => [n.id, []]));
      (g.edges || []).forEach(e2 => { if ((Number(e2.weight) || 0) > 0 && out.has(e2.from)) out.get(e2.from).push(e2.to); });
      const seen = new Set(); const pending = [g.start];
      while (pending.length) { const id = pending.pop(); if (!id || seen.has(id)) continue;
        seen.add(id); (out.get(id) || []).forEach(t2 => pending.push(t2)); }
      if (!ns.some(n => n.type === 'end' && seen.has(n.id))) problems.push('the start cannot reach an end');
      const lost = ns.filter(n => !seen.has(n.id)).map(n => n.label || n.id);
      if (lost.length) problems.push('unreachable: ' + lost.slice(0, 3).join(', '));
      const dead = ns.filter(n => n.type !== 'end' && !(out.get(n.id) || []).length).map(n => n.label || n.id);
      if (dead.length) problems.push('no way onward from: ' + dead.slice(0, 3).join(', '));
      return problems;
    }
    const PG_KINDS = [['initiator', 'Initiator'], ['reply', 'Reply'], ['rebuttal', 'Rebuttal'],
      ['decision', 'Dice gate'], ['call', 'Phone call'], ['topic_change', 'Topic change'], ['book_reader', 'Book reader'], ['end', 'End']];
    const palette = el('div', 's3-pg-palette', el('span', {class: 's3-muted', text: 'drag onto the paper:'}));
    for (const [kind, kindName] of PG_KINDS) {
      const chip = el('button', {type: 'button', class: 's3-pg-chip pgk-' + kind,
        'aria-pressed': String(segGraphArm === kind)}, el('span', 's3-pg-chip-shape'), kindName);
      chip.addEventListener('pointerdown', ev => {
        ev.preventDefault(); let ghost = null; const pid = ev.pointerId;
        try { chip.setPointerCapture(pid); } catch (err) { /* a synthetic pointer */ }
        const unhook = () => { chip.removeEventListener('pointermove', onMove);
          chip.removeEventListener('pointerup', onUp); chip.removeEventListener('pointercancel', onCancel); };
        const onMove = m => { if (m.pointerId !== pid) return;
          if (!ghost && Math.hypot(m.clientX - ev.clientX, m.clientY - ev.clientY) > 6) {
            ghost = el('div', {class: 's3-pg-ghost pgk-' + kind, text: kindName});
            document.body.append(ghost); }
          if (ghost) { ghost.style.left = m.clientX + 'px'; ghost.style.top = m.clientY + 'px'; } };
        const onUp = m => { unhook();
          if (!ghost) { segGraphArm = segGraphArm === kind ? null : kind; refresh(); return; }
          ghost.remove(); ghost = null;
          const r = canvas.getBoundingClientRect();
          if (m.clientX >= r.left && m.clientX <= r.right && m.clientY >= r.top && m.clientY <= r.bottom
              && segGraphScene && segGraphScene.graphPointAt) {
            const g = segGraphScene.graphPointAt(m.clientX, m.clientY);
            if (g) pgPlace(kind, g.x, g.y); } };
        const onCancel = () => { unhook(); if (ghost) { ghost.remove(); ghost = null; } };
        chip.addEventListener('pointermove', onMove); chip.addEventListener('pointerup', onUp);
        chip.addEventListener('pointercancel', onCancel);
      });
      palette.append(chip);
    }
    box.append(el('div', 's3-graph-layout', el('div', 's3-graph-visual', palette, canvas, viewControls, list), props));
    const pgTrouble = pgProblems(graph);
    if (pgTrouble.length) box.append(para('The path has holes the engine will refuse: ' + pgTrouble.join(' - '), 's3-error'));
    const flows = el('div', 's3-graph-flows', el('h3', {text: 'Flow lines · weights are the branch dice'}));
    edges.forEach((edge, i) => flows.append(el('div', 's3-graph-edge',
      el('span', {text: edge.from + ' → ' + edge.to + ' (' + Math.round(100 * (Number(edge.weight) || 0)
        / Math.max(.001, edges.filter(e => e.from === edge.from).reduce((sum, e) => sum + (Number(e.weight) || 0), 0))) + '%)'}),
      el('input', {type: 'number', min: 0, max: 100, step: .01, value: edge.weight == null ? 1 : edge.weight,
        'aria-label': 'Flow weight', onchange: e => { edge.weight = Number(e.target.value); refresh(); }}),
      btn('×', () => { edges.splice(i, 1); refresh(); }, {'aria-label': 'Remove flow line'}))));
    const from = el('select', {'aria-label': 'Flow from'}, ...nodes.map(n => el('option', {value: n.id, text: n.label || n.id, selected: n.id === segGraphSel})));
    const to = el('select', {'aria-label': 'Flow to'}, ...nodes.map(n => el('option', {value: n.id, text: n.label || n.id})));
    flows.append(el('div', 's3-row', from, to, btn('Connect', () => { if (from.value && to.value) {
      edges.push({from: from.value, to: to.value, weight: 1}); refresh(); } })));
    if (selected && edges.length) {
      const split = el('select', {'aria-label': 'Flow line to insert into'}, ...edges.map((e, i) =>
        el('option', {value: String(i), text: e.from + ' → ' + e.to})));
      flows.append(el('div', 's3-row', split, btn('Insert selected node into flow', () => {
        const i = Number(split.value), edge = edges[i];
        if (!edge || edge.from === selected.id || edge.to === selected.id) return;
        edges.splice(i, 1, {from: edge.from, to: selected.id, weight: edge.weight},
          {from: selected.id, to: edge.to, weight: 1}); refresh();
      })));
    }
    flows.append(el('label', null, 'Topic change options, one per line', el('textarea', {rows: 2,
      value: (graph.topic_options || []).join('\n'), onchange: e => {
        graph.topic_options = e.target.value.split('\n').map(s => s.trim()).filter(Boolean); }})));
    box.append(flows, preview);
    /* [pine-graph] the scene IS the editor: taps choose, drags move, the pip
       inks a new flow line, an armed chip lands where the paper is tapped */
    setTimeout(() => segGraph3D(canvas, graph, segGraphSel, {
      choose: id => { if (segGraphSel === id && segGraphEdgeSel === -1) return;
        segGraphSel = id; segGraphEdgeSel = -1; refresh(); },
      edge: i => { segGraphEdgeSel = i; segGraphSel = ''; refresh(); },
      move: (id, gx, gy) => { const n = nodes.find(n2 => n2.id === id); if (!n) return;
        n.x = Math.round(Math.max(-2000, Math.min(2000, gx)));
        n.y = Math.round(Math.max(-2000, Math.min(2000, gy))); refresh(); },
      link: (from, to) => { if (from === to || edges.some(e2 => e2.from === from && e2.to === to)) { refresh(); return; }
        edges.push({from, to, weight: 1}); segGraphEdgeSel = edges.length - 1; segGraphSel = ''; refresh(); },
      armed: () => segGraphArm,
      place: (gx, gy) => pgPlace(segGraphArm, gx, gy)})
      .then(scene => { if (canvas.isConnected) segGraphScene = scene; else if (scene) scene.stop(); })
      .catch(e => { canvas.replaceWith(para('3D view unavailable: ' + e.message, 's3-muted')); }), 0);
    return box;
  }

  function segGraph3D(canvas, graph, active, hooks) {
    /* [pine-graph] The paper. The conversation graph drawn the way the operator
       drew it (docs/NodePlan/NODE_img.png): wobbly ink boxes for statements,
       diamonds for the dice, a circle-and-diamond badge where the speaker is
       raffled from the cast, DASHED boxes for replies that only happen on a
       roll, and curved ink flow lines with their odds written beside them in
       the drawing's own voice - (1:2), (1:3). three.js on an orthographic
       camera: the paper is flat, the GPU pans it.
       Every part is edited by hand, on the desk's mouse or the tablet's
       finger: drag a node by its body to move it, drag the pip under a node
       onto another node to ink a new flow line, tap a node or a line for its
       card, drag the paper to pan, pinch or roll to zoom, tap empty paper to
       put down an armed palette chip (or to put the cards away).
       hooks: choose(id), edge(i), move(id, gx, gy), link(from, to),
       armed() -> a palette chip kind or null, place(gx, gy). */
    return threeLoad().then(THREE => {
      if (!canvas.isConnected) return null;
      const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      const w = Math.max(320, canvas.clientWidth), h = Math.max(280, canvas.clientHeight);
      renderer.setSize(w, h, false);
      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-6, 6, 6 * h / w, -6 * h / w, .1, 100);
      const nodes = graph.nodes || [], edges = graph.edges || [];
      /* the paper's own units: 80 graph units to a world unit, y down like the sketch */
      const G = 80;
      const point = n => new THREE.Vector3((Number(n.x) || 0) / G, -(Number(n.y) || 0) / G, 0);
      const toGraph = v => ({x: v.x * G, y: -v.y * G});
      const css = getComputedStyle(canvas);
      const themed = (name, fallback) => (css.getPropertyValue(name) || '').trim() || fallback;
      const INK = themed('--ink', '#e2e9e6'), INK2 = themed('--ink-3', '#7e9496'), SEL = themed('--accent', '#90dab9');
      const TINT = {initiator: '#65c7da', reply: '#8ccf9d', rebuttal: '#e9af70', topic_change: '#b49ced',
        call: '#e68db4', decision: '#f0d274', end: '#e2e9e6', protocol: '#95a8ed'};
      const FONT = "'Segoe Print','Bradley Hand','Comic Sans MS','Chalkboard SE',cursive";
      /* seeded wobble: the ink shakes, but the same way every repaint */
      const seeded = str => { let a = 2166136261 >>> 0;
        for (let i = 0; i < str.length; i++) { a ^= str.charCodeAt(i); a = Math.imul(a, 16777619); }
        return () => { a = Math.imul(a ^ (a >>> 15), 2246822507); a = Math.imul(a ^ (a >>> 13), 3266489909);
          return ((a ^= a >>> 16) >>> 0) / 4294967296; }; };
      const odds = p => p >= 1 ? '' : p <= 0 ? 'never' : '1:' + Math.max(2, Math.round(1 / p));
      const wobbly = (cx, pts, rnd, amp, open) => { cx.beginPath();
        pts.forEach(([px, py], i) => { const dx = (rnd() - .5) * amp, dy = (rnd() - .5) * amp;
          if (i === 0) cx.moveTo(px + dx, py + dy); else cx.lineTo(px + dx, py + dy); });
        if (!open) cx.closePath(); };
      const rectOutline = (x, y, wd, ht, r) => { const pts = [];
        const seg = (x1, y1, x2, y2) => { const n = Math.max(2, Math.round(Math.hypot(x2 - x1, y2 - y1) / 12));
          for (let i = 0; i < n; i++) pts.push([x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n]); };
        const arc = (ax, ay, a0, a1) => { for (let i = 0; i <= 3; i++) { const a = a0 + (a1 - a0) * i / 3;
          pts.push([ax + Math.cos(a) * r, ay + Math.sin(a) * r]); } };
        seg(x + r, y, x + wd - r, y); arc(x + wd - r, y + r, -Math.PI / 2, 0);
        seg(x + wd, y + r, x + wd, y + ht - r); arc(x + wd - r, y + ht - r, 0, Math.PI / 2);
        seg(x + wd - r, y + ht, x + r, y + ht); arc(x + r, y + ht - r, Math.PI / 2, Math.PI);
        seg(x, y + ht - r, x, y + r); arc(x + r, y + r, Math.PI, Math.PI * 1.5);
        return pts; };
      const diamondOutline = (ax, ay, rx, ry) => { const pts = [];
        const corners = [[ax, ay - ry], [ax + rx, ay], [ax, ay + ry], [ax - rx, ay]];
        for (let k = 0; k < 4; k++) { const [x1, y1] = corners[k], [x2, y2] = corners[(k + 1) % 4];
          for (let i = 0; i < 5; i++) pts.push([x1 + (x2 - x1) * i / 5, y1 + (y2 - y1) * i / 5]); }
        return pts; };
      const nodeCanvas = n => {
        const dia = n.type === 'decision';
        const cw = dia ? 288 : 512, ch = dia ? 288 : 224;
        const c = document.createElement('canvas'); c.width = cw; c.height = ch;
        const cx = c.getContext('2d'); const rnd = seeded(n.id + '|' + (n.label || '') + '|' + n.type);
        const tint = TINT[n.type] || INK; const isSel = n.id === active;
        /* dashed = conditional, as in the drawing: it speaks only on a won roll */
        const conditional = !dia && (Number(n.chance) < 1 || n.respond_to);
        cx.lineJoin = 'round'; cx.lineCap = 'round';
        const stroke = (pts, width, color, dashed) => { cx.save();
          if (dashed) cx.setLineDash([15, 11]);
          cx.strokeStyle = color; cx.lineWidth = width; wobbly(cx, pts, rnd, 5); cx.stroke(); cx.restore(); };
        if (dia) {
          const pts = diamondOutline(cw / 2, ch / 2 - 8, 100, 88);
          cx.fillStyle = 'rgba(16,29,38,.94)'; wobbly(cx, pts, rnd, 4); cx.fill();
          stroke(pts, isSel ? 11 : 8, isSel ? SEL : tint, false);
          stroke(diamondOutline(cw / 2, ch / 2 - 8, 100, 88), 3, INK, false);
          const out = edges.filter(e2 => e2.from === n.id);
          const tot = out.reduce((s, e2) => s + Math.max(0, Number(e2.weight) || 0), 0);
          const low = out.length > 1 && tot > 0 ? Math.min(...out.map(e2 => Math.max(0, Number(e2.weight) || 0))) / tot : 0;
          cx.fillStyle = INK; cx.font = '44px ' + FONT; cx.textAlign = 'center'; cx.textBaseline = 'middle';
          cx.fillText(low > 0 ? odds(low) : 'roll', cw / 2, ch / 2 - 26);
          cx.font = '26px ' + FONT; cx.fillStyle = INK2;
          cx.fillText(String(n.label || 'dice').slice(0, 13), cw / 2, ch / 2 + 22);
          cx.fillStyle = INK; cx.beginPath(); cx.arc(cw / 2, ch - 14, 9, 0, Math.PI * 2); cx.fill();
        } else {
          const pts = rectOutline(26, 30, cw - 52, ch - 64, 26);
          cx.fillStyle = 'rgba(16,29,38,.94)'; wobbly(cx, pts, rnd, 4); cx.fill();
          stroke(pts, isSel ? 11 : 7.5, isSel ? SEL : tint, conditional);
          if (!conditional) stroke(rectOutline(30, 34, cw - 60, ch - 72, 23), 3, INK, false);
          cx.fillStyle = INK; cx.font = '46px ' + FONT; cx.textAlign = 'center'; cx.textBaseline = 'middle';
          cx.fillText(String(n.label || n.id).slice(0, 16), cw / 2, ch / 2 - 20);
          const bits = [];
          const chance = Number(n.chance);
          if (chance >= 0 && chance < 1) bits.push('(' + odds(chance) + ')');
          if (Number(n.seconds) > 0) bits.push(Math.round(n.seconds) + 's');
          if (n.speaker) bits.push(String(n.speaker).slice(0, 12));
          if ((n.draws || []).length) bits.push((n.draws || []).map(d => d.family).join('+'));
          cx.font = '25px ' + FONT; cx.fillStyle = INK2;
          cx.fillText(bits.join('  ').slice(0, 36), cw / 2, ch / 2 + 30);
          if (graph.start === n.id) { cx.font = '26px ' + FONT; cx.fillStyle = SEL; cx.textAlign = 'left';
            cx.fillText('start', 36, 18); }
          /* the raffle badge: circle and diamond - anyone from the cast can win the seat */
          if (!n.speaker && (n.type === 'initiator' || n.type === 'reply' || n.type === 'rebuttal' || n.type === 'call')) {
            const bx = cw - 46, by = 34; cx.save(); cx.strokeStyle = INK; cx.lineWidth = 4.5;
            const ring = []; for (let i = 0; i <= 14; i++) { const a = i / 14 * Math.PI * 2;
              ring.push([bx + Math.cos(a) * 27, by + Math.sin(a) * 24]); }
            wobbly(cx, ring, rnd, 3); cx.stroke();
            cx.fillStyle = INK; cx.beginPath(); cx.arc(bx - 10, by - 2, 4.5, 0, Math.PI * 2); cx.fill();
            cx.beginPath(); cx.moveTo(bx + 9, by - 11); cx.lineTo(bx + 17, by - 1); cx.lineTo(bx + 9, by + 9);
            cx.lineTo(bx + 1, by - 1); cx.closePath(); cx.stroke(); cx.restore();
          }
          /* the out-pip: a new flow line is picked up here and dropped on another node */
          cx.fillStyle = INK; cx.beginPath(); cx.arc(cw / 2, ch - 18, 9, 0, Math.PI * 2); cx.fill();
          cx.strokeStyle = tint; cx.lineWidth = 3; cx.beginPath(); cx.arc(cw / 2, ch - 18, 14, 0, Math.PI * 2); cx.stroke();
        }
        return c;
      };
      const meshes = [], byId = new Map();
      nodes.forEach(n => {
        const size = n.type === 'decision' ? [1.2, 1.2] : [2.35, 1.03];
        const tex = new THREE.CanvasTexture(nodeCanvas(n)); tex.anisotropy = 4;
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]),
          new THREE.MeshBasicMaterial({map: tex, transparent: true}));
        mesh.position.copy(point(n)); mesh.userData.id = n.id; mesh.userData.node = n; mesh.userData.size = size;
        scene.add(mesh); meshes.push(mesh); byId.set(n.id, mesh);
      });
      const textSprite = (said, color) => { const c = document.createElement('canvas'); c.width = 256; c.height = 64;
        const cx = c.getContext('2d'); cx.font = '34px ' + FONT; cx.textAlign = 'center'; cx.textBaseline = 'middle';
        cx.fillStyle = color; cx.fillText(String(said).slice(0, 16), 128, 34);
        const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true}));
        sp.scale.set(1.7, .42, 1); return sp; };
      const edgeObjs = [];
      edges.forEach((edge, i) => {
        const a = byId.get(edge.from), b = byId.get(edge.to); if (!a || !b) return;
        const rnd = seeded('edge|' + edge.from + '|' + edge.to + '|' + i);
        const start = a.position.clone().add(new THREE.Vector3(0, -a.userData.size[1] / 2 + .04, 0));
        const stop = b.position.clone().add(new THREE.Vector3(0, b.userData.size[1] / 2 + .02, 0));
        const dx = stop.x - start.x, dy = stop.y - start.y;
        const bow = Math.abs(dx) < .6 ? ((i % 2) ? -.55 : .55) : dx * .18;
        const curve = new THREE.CubicBezierCurve3(start,
          new THREE.Vector3(start.x + bow, start.y + dy * .3, 0),
          new THREE.Vector3(stop.x - bow * .4, start.y + dy * .75, 0), stop);
        const pts = curve.getPoints(26).map(v => new THREE.Vector3(v.x + (rnd() - .5) * .05, v.y + (rnd() - .5) * .05, -.05));
        const isSel = i === segGraphEdgeSel;
        const mat = new THREE.LineBasicMaterial({color: isSel ? SEL : INK, transparent: true, opacity: isSel ? 1 : .62});
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat);
        scene.add(line); edgeObjs.push({index: i, pts});
        const tip = pts[pts.length - 2], back = pts[pts.length - 5] || pts[0];
        const dir = tip.clone().sub(back).normalize(); const side = new THREE.Vector3(-dir.y, dir.x, 0);
        scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          tip.clone().addScaledVector(dir, -.2).addScaledVector(side, .11), tip.clone(),
          tip.clone().addScaledVector(dir, -.2).addScaledVector(side, -.11)]), mat.clone()));
        const among = edges.filter(e2 => e2.from === edge.from);
        const tot = among.reduce((s, e2) => s + Math.max(0, Number(e2.weight) || 0), 0);
        const share = tot > 0 ? Math.max(0, Number(edge.weight) || 0) / tot : 0;
        const auto = among.length > 1 && share > 0 && share < 1 ? '(' + odds(share) + ')' : '';
        const said = edge.label || auto;
        if (said) { const mid = pts[13];
          const sprite = textSprite(said, isSel ? SEL : INK2);
          sprite.position.set(mid.x + .58, mid.y + .1, .1); scene.add(sprite); }
      });
      const render = () => renderer.render(scene, camera);
      camera.position.set(segGraphViewState.panX, segGraphViewState.panY, 30);
      camera.zoom = segGraphViewState.zoom; camera.updateProjectionMatrix();
      /* all=true frames the whole chain (the Fit button); all=false fits its
         WIDTH and starts at the top, the way the drawing is read */
      const contentFit = all => { if (!meshes.length) { camera.position.set(0, 0, 30); camera.zoom = 1; }
        else { const bb = new THREE.Box3(); meshes.forEach(m => bb.expandByPoint(m.position)); bb.expandByScalar(1.7);
          const fitW = 12 / Math.max(1, bb.max.x - bb.min.x), fitH = 12 * h / w / Math.max(1, bb.max.y - bb.min.y);
          camera.zoom = Math.max(.16, Math.min(2.4, all ? Math.min(fitW, fitH) : Math.min(1.3, fitW)));
          camera.position.x = (bb.min.x + bb.max.x) / 2;
          camera.position.y = all ? (bb.min.y + bb.max.y) / 2
            : bb.max.y + .4 - (6 * h / w) / camera.zoom; }
        camera.updateProjectionMatrix();
        segGraphViewState = {zoom: camera.zoom, panX: camera.position.x, panY: camera.position.y}; };
      if (segGraphViewState.zoom === 1 && !segGraphViewState.panX && !segGraphViewState.panY) contentFit(false);
      const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
      const floor = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
      const pointAt = (x, y) => { const r = canvas.getBoundingClientRect();
        mouse.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
        camera.updateMatrixWorld(); ray.setFromCamera(mouse, camera);
        return ray.ray.intersectPlane(floor, new THREE.Vector3()); };
      const screenAt = v => { const sv = v.clone().project(camera); const r = canvas.getBoundingClientRect();
        return {x: r.left + (sv.x + 1) / 2 * r.width, y: r.top + (1 - (sv.y + 1) / 2) * r.height}; };
      const nodeHit = (x, y) => { const r = canvas.getBoundingClientRect();
        mouse.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
        camera.updateMatrixWorld(); ray.setFromCamera(mouse, camera);
        const hit = ray.intersectObjects(meshes)[0];
        return hit ? {id: hit.object.userData.id, mesh: hit.object, uv: hit.uv, point: hit.point} : null; };
      const distToSeg = (x, y, a2, b2) => { const vx = b2.x - a2.x, vy = b2.y - a2.y;
        const t = Math.max(0, Math.min(1, ((x - a2.x) * vx + (y - a2.y) * vy) / Math.max(1e-6, vx * vx + vy * vy)));
        return Math.hypot(x - (a2.x + vx * t), y - (a2.y + vy * t)); };
      const edgeHitAt = (x, y) => { let best = null;
        for (const eo of edgeObjs) for (let i = 0; i < eo.pts.length - 1; i++) {
          const d = distToSeg(x, y, screenAt(eo.pts[i]), screenAt(eo.pts[i + 1]));
          if (d < 9 && (!best || d < best.d)) best = {d, index: eo.index}; }
        return best; };
      let band = null;
      const bandTo = (from, v) => {
        if (band) { scene.remove(band); band.geometry.dispose(); band.material.dispose(); band = null; }
        if (from && v) { band = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
            [from, new THREE.Vector3(v.x, v.y, .2)]),
          new THREE.LineDashedMaterial({color: SEL, dashSize: .16, gapSize: .1}));
          band.computeLineDistances(); scene.add(band); }
        render(); };
      const pan = (from, to) => { const a = pointAt(from.x, from.y), b = pointAt(to.x, to.y);
        if (!a || !b) return;
        camera.position.x += a.x - b.x; camera.position.y += a.y - b.y;
        segGraphViewState.panX = camera.position.x; segGraphViewState.panY = camera.position.y; render(); };
      const zoom = (x, y, factor) => { const before = pointAt(x, y);
        const next = Math.max(.16, Math.min(8, camera.zoom * factor));
        if (next === camera.zoom) return;
        camera.zoom = next; camera.updateProjectionMatrix();
        const after = pointAt(x, y);
        if (before && after) { camera.position.x += before.x - after.x; camera.position.y += before.y - after.y; }
        segGraphViewState.zoom = camera.zoom;
        segGraphViewState.panX = camera.position.x; segGraphViewState.panY = camera.position.y; render(); };
      const fingers = new Map(); let press = null, pinch = null, moved = false, grab = null;
      const pinchMeasure = () => { const [a, b] = [...fingers.values()];
        return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2,
          distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y))}; };
      const down = e => { e.preventDefault(); fingers.set(e.pointerId, {x: e.clientX, y: e.clientY});
        try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic pointer */ }
        if (fingers.size === 1) { press = {x: e.clientX, y: e.clientY}; moved = false;
          const hit = nodeHit(e.clientX, e.clientY);
          if (hit) { const port = hit.uv && hit.uv.y < .22 && Math.abs(hit.uv.x - .5) < .24;
            grab = port ? {kind: 'connect', id: hit.id,
                fromWorld: hit.mesh.position.clone().add(new THREE.Vector3(0, -hit.mesh.userData.size[1] / 2, 0))}
              : {kind: 'node', id: hit.id, mesh: hit.mesh, offset: hit.mesh.position.clone().sub(hit.point)};
          } else { const eh = edgeHitAt(e.clientX, e.clientY);
            grab = eh ? {kind: 'edge', edgeIndex: eh.index} : {kind: 'pan'}; }
        } else if (fingers.size === 2) { pinch = pinchMeasure(); moved = true; grab = null; bandTo(null, null); } };
      const move = e => { if (!fingers.has(e.pointerId)) return;
        const last = fingers.get(e.pointerId); fingers.set(e.pointerId, {x: e.clientX, y: e.clientY});
        if (fingers.size === 2) { const next = pinchMeasure();
          if (pinch) { zoom(pinch.x, pinch.y, next.distance / pinch.distance); pan(pinch, next); }
          pinch = next; moved = true;
        } else if (fingers.size === 1 && press) {
          if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 5) moved = true;
          if (!moved) return;
          if (grab && grab.kind === 'node') { const p2 = pointAt(e.clientX, e.clientY);
            if (p2) { grab.mesh.position.set(p2.x + grab.offset.x, p2.y + grab.offset.y, 0); render(); } }
          else if (grab && grab.kind === 'connect') bandTo(grab.fromWorld, pointAt(e.clientX, e.clientY));
          else pan(last, {x: e.clientX, y: e.clientY});
        } };
      const end = (e, cancelled = false) => { if (!fingers.has(e.pointerId)) return;
        const tapped = !cancelled && fingers.size === 1 && !moved && press
          && Math.hypot(e.clientX - press.x, e.clientY - press.y) <= 5;
        fingers.delete(e.pointerId); pinch = null;
        if (fingers.size === 1) { press = [...fingers.values()][0]; moved = true; grab = null; bandTo(null, null); return; }
        press = null; const g = grab; grab = null;
        if (cancelled) { bandTo(null, null); moved = false;
          if (g && g.kind === 'node' && g.mesh) { g.mesh.position.copy(point(g.mesh.userData.node)); render(); }
          return; }
        if (tapped) { bandTo(null, null); moved = false;
          if (g && (g.kind === 'node' || g.kind === 'connect')) hooks.choose(g.id);
          else if (g && g.kind === 'edge') hooks.edge(g.edgeIndex);
          else if (hooks.armed && hooks.armed()) { const p2 = pointAt(e.clientX, e.clientY);
            if (p2) { const gp = toGraph(p2); hooks.place(gp.x, gp.y); } }
          else hooks.choose('');
          return; }
        moved = false;
        if (g && g.kind === 'node' && g.mesh) { const gp = toGraph(g.mesh.position); hooks.move(g.id, gp.x, gp.y); }
        else if (g && g.kind === 'connect') { bandTo(null, null);
          const hit = nodeHit(e.clientX, e.clientY);
          if (hit && hit.id !== g.id) hooks.link(g.id, hit.id); } };
      const up = e => end(e), cancel = e => end(e, true);
      const wheel = e => { e.preventDefault(); zoom(e.clientX, e.clientY, Math.exp(-e.deltaY * .001)); };
      canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move);
      canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', cancel);
      canvas.addEventListener('wheel', wheel, {passive: false}); render();
      const api = {zoomBy(factor) { const r = canvas.getBoundingClientRect();
          zoom(r.left + r.width / 2, r.top + r.height / 2, factor); },
        fit() { contentFit(true); render(); },
        graphPointAt(x, y) { const p2 = pointAt(x, y); return p2 ? toGraph(p2) : null; },
        screenOf(id) { const m = byId.get(id); if (!m) return null;
          const c2 = screenAt(m.position);
          const tl = screenAt(m.position.clone().add(new THREE.Vector3(-m.userData.size[0] / 2, m.userData.size[1] / 2, 0)));
          return {x: c2.x, y: c2.y, w: (c2.x - tl.x) * 2, h: (c2.y - tl.y) * 2}; },
        stop() { canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move);
          canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', cancel);
          canvas.removeEventListener('wheel', wheel); scene.traverse(obj => {
            if (obj.geometry) obj.geometry.dispose(); if (obj.material) {
              if (obj.material.map) obj.material.map.dispose(); obj.material.dispose(); } });
          renderer.dispose();
          try { if (renderer.forceContextLoss) renderer.forceContextLoss(); } catch (err) { /* already lost */ } }};
      try { const dbg = window.__pineGraphDebug = window.__pineGraphDebug || {};
        dbg.scene = api; dbg.graph = graph; } catch (err) { /* sealed window */ }
      return api;
    });
  }

  function paintSegments() {
    const roads = ['banter', ...Object.keys(segStructures())];
    if (!segRoad || !roads.includes(segRoad)) segRoad = roads[1] || 'banter';
    segLoad(segRoad);
    const cycle = segRoad === 'banter';
    const st = cycle ? config.config.structure : (segStructures()[segRoad] || {});
    const nodes = segNodes;
    const sel = segSel.node >= 0 && segSel.node < nodes.length ? nodes[segSel.node] : null;
    const repaint = () => paintSegments();
    const chip = (label, data, fam) => el('div', {class: 's3-chip' + (fam ? ' fam' : ''), draggable: true, style: fam ? `--fam:${FAM[fam]}` : '',
      ondragstart: e => { segDrag = data; try { e.dataTransfer.setData('text/plain', label); } catch (_) { /* older engine */ } },
      ondragend: () => { segDrag = null; }}, label);
    const palette = el('div', 's3-palette', el('h4', {text: 'Nodes'}), chip(cycle ? '+ step' : '+ leg', {kind: 'node'}),
      el('h4', {text: 'Draws - the roulette'}), ...SEG_FAMS.map(f => chip(f + ' - ' + String((FAMILY_WHAT[f] || [f])[0]).split(' (')[0], {kind: 'draw', family: f}, f)),
      cycle ? el('h4', {text: 'Speaker box'}) : null, cycle ? chip('prepend mark', {kind: 'mark', mark: 'prepend'}) : null, cycle ? chip('append mark', {kind: 'mark', mark: 'append'}) : null,
      el('p', {class: 's3-muted', text: 'Drag a node between two nodes; drag a draw onto a node. Tap a node for its properties. Tap a draw\'s die to turn its roulette off and pin a value.'}));
    if (!cycle && segRoad.split('~')[0] === 'caller') palette.insertBefore(el('div', null,   /* [s3-callend] the call's end */
      el('h4', {text: "The call's end"}), ...['RESOLVE', 'WRAP'].map(f => chip(f + ' - ' + String((FAMILY_WHAT[f] || [f])[0]).split(' (')[0],
        {kind: 'draw', family: f}, f))), palette.lastChild);
    const props = el('div', 's3-seg-props');
    if (cycle) props.append(el('label', null, 'who opens the round ',   /* [s3-flow] */
      el('select', {onchange: e => { segInitiator = e.target.value; }},
        ...[['', 'the first seat (as always)'], ['A', 'seat A (' + castName('host') + ', the host)'], ['B', 'seat B (' + castName('cohost') + ', the co-host)'], ['D', 'seat D (the third seat)']]   /* [cast-names] */
          .map(([v, t]) => el('option', {value: v, text: t, selected: v === (segInitiator ?? (st.initiator || ''))})))));
    if (!sel) props.append(para('Tap a node to edit it.', 's3-muted'));
    else {
      const field = (label, input) => el('label', null, label, input);
      const labelEl = () => body.querySelector('.s3-seg-node.sel b');
      props.append(el('h4', {text: cycle ? 'Step' : 'Leg'}),
        field('label', el('input', {type: 'text', value: sel.label || sel.id || '', oninput: e => { sel.label = e.target.value; const b = labelEl(); if (b) b.textContent = e.target.value; }})));
      /* [s3-flow] the operator's own topic on this node - everything else still rolls */
      props.append(field('topic in your own words (blank: the roulette and the road decide)', el('textarea', {value: sel.topic || '', rows: 2,
        oninput: e => { if (e.target.value.trim()) sel.topic = e.target.value; else delete sel.topic; }})));
      /* [s3-source] the initiator node may pin the document the round opens from */
      if (segSel.node === 0) {
        const pick = el('select', {onchange: e => { if (e.target.value) sel.source = e.target.value; else delete sel.source; }},
          el('option', {value: '', text: 'any document (the dice and the station draw)'}),
          ...(sel.source ? [el('option', {value: sel.source, text: sel.source, selected: true})] : []));
        props.append(field('source document the round opens from', pick));
        request('/api/speakbox').then(got => {
          for (const f of (got && got.files) || []) {
            if (!f || !f.name || f.name === sel.source) continue;
            pick.append(el('option', {value: f.name, text: f.name + (f.weight === 0 ? ' (switched off)' : '')}));
          }
        }).catch(() => { /* the list is a convenience; the pin still saves */ });
      }
      if (cycle) {
        props.append(field('speaker', el('select', {onchange: e => { sel.speaker = e.target.value; repaint(); }},
            ...['initiator', 'responder_a', 'responder_b', 'frame'].map(sp => el('option', {value: sp, text: sp.replace('_', ' '), selected: sel.speaker === sp})))),
          el('label', 's3-row', el('input', {type: 'checkbox', checked: !!sel.optional, onchange: e => { sel.optional = e.target.checked; }}), 'optional'));
      } else {
        props.append(field('place', el('select', {onchange: e => { sel.place = e.target.value; repaint(); }},
            ...['open', 'middle', 'close'].map(pl => el('option', {value: pl, text: pl, selected: sel.place === pl})))),
          field('seat', el('select', {onchange: e => { sel.seat = e.target.value; repaint(); }},
            ...['A', 'B', 'C', 'D', 'E', 'alternate'].map(x => el('option', {value: x, text: x === 'alternate' ? 'alternating' : 'seat ' + x, selected: sel.seat === x})))),
          field('what this leg does - the act the writer is given', el('textarea', {value: sel.act || '', oninput: e => { sel.act = e.target.value; }})));
      }
      if (cycle || st.kind === 'line') props.append(el('h4', {text: 'Split'}), splitBox(sel, repaint, cycle ? 'step' : 'leg'));   /* [s3-split] */
      const d = segSel.draw >= 0 ? (sel.draws || [])[segSel.draw] : null;
      if (d) {
        const items = segTableItems(d.family);
        props.append(el('h4', {text: d.family + ' draw'}),
          el('label', 's3-row', el('input', {type: 'checkbox', checked: d.fixed === undefined,
            onchange: e => { if (e.target.checked) delete d.fixed; else d.fixed = (items[0] || {}).id || ''; repaint(); }}), 'roulette on - roll it every time'),
          d.fixed !== undefined ? field('pinned to (the roulette is off)', el('select', {onchange: e => { d.fixed = e.target.value; repaint(); }},
            ...items.map(it => el('option', {value: it.id, text: it.label, selected: it.id === d.fixed})))) : null,
          /* [s3-flow] a static node: its category pinned, the item inside it still rolled */
          d.fixed === undefined ? field('static category - the item inside it still rolls', el('select', {onchange: e => { if (e.target.value) d.category = e.target.value; else delete d.category; repaint(); }},
            el('option', {value: '', text: 'any category (the roulette picks)'}),
            ...segTableCats(d.family).map(c => el('option', {value: c.id, text: c.label, selected: c.id === d.category})))) : null,
          d.family === 'FL' ? el('label', 's3-row', el('input', {type: 'checkbox', checked: !!d.closes, onchange: e => { d.closes = e.target.checked; repaint(); }}), 'closing moves only') : null,
          field('tables - blank means every table of the family', el('input', {type: 'text', value: (d.tables || []).join(', '),
            onchange: e => { const t = e.target.value.split(',').map(x => x.trim()).filter(Boolean); if (t.length) d.tables = t; else delete d.tables; repaint(); }})));
      }
    }
    const nodeCard = (n, i) => {
      const card = el('div', {class: 's3-seg-node' + (i === segSel.node ? ' sel' : ''), draggable: true,
        onclick: () => { if (segSel.node !== i || segSel.draw !== -1) { segSel = {node: i, draw: -1}; repaint(); } },
        ondragstart: e => { segDrag = {kind: 'move', from: i}; e.stopPropagation(); },
        ondragend: () => { segDrag = null; },
        ondragover: e => { if (segDrag && (segDrag.kind === 'draw' || segDrag.kind === 'mark')) { e.preventDefault(); card.classList.add('s3-drop-into'); } },
        ondragleave: () => card.classList.remove('s3-drop-into'),
        ondrop: e => { card.classList.remove('s3-drop-into'); if (!segDrag) return; e.preventDefault(); e.stopPropagation();
          if (segDrag.kind === 'draw') { n.draws = n.draws || []; n.draws.push(segDrag.family === 'FL' ? {family: 'FL', tables: ['FL2']} : {family: segDrag.family}); segSel = {node: i, draw: n.draws.length - 1}; }
          else if (segDrag.kind === 'mark') { n.speakerbox = (n.speakerbox || []).filter(m => m !== segDrag.mark).concat([segDrag.mark]); }
          segDrag = null; repaint(); }});
      const head = el('div', 's3-row', el('b', {text: n.label || n.id || (cycle ? 'step' : 'leg')}),
        cycle ? el('span', {class: 's3-pill', text: String(n.speaker || '').replace('_', ' ')}) : el('span', {class: 's3-pill', text: n.place || 'middle'}),
        cycle ? null : el('span', {class: 's3-pill', text: n.seat === 'alternate' ? 'alternating' : 'seat ' + (n.seat || 'A')}),
        n.splits === true ? el('span', {class: 's3-pill', style: `border-color:${FAM.SPLIT}`, text: 'split x' + (n.max_splits || 3),   /* [s3-split] */
          title: 'a long read on this node is shared out, up to ' + (n.max_splits || 3) + ' split(s)'}) : null,
        ...(n.speakerbox || []).map(m => el('span', {class: 's3-pill', style: `border-color:${FAM.SPEAKERBOX}`, text: m,
          onclick: e => { e.stopPropagation(); n.speakerbox = n.speakerbox.filter(x => x !== m); repaint(); }, title: 'tap to remove the mark'})),
        el('span', {style: 'flex:1'}),
        btn('up', e => { e.stopPropagation(); if (i) { [nodes[i - 1], nodes[i]] = [nodes[i], nodes[i - 1]]; segSel = {node: i - 1, draw: -1}; repaint(); } }),
        btn('down', e => { e.stopPropagation(); if (i < nodes.length - 1) { [nodes[i + 1], nodes[i]] = [nodes[i], nodes[i + 1]]; segSel = {node: i + 1, draw: -1}; repaint(); } }),
        btn('x', e => { e.stopPropagation(); nodes.splice(i, 1); segSel = {node: -1, draw: -1}; repaint(); }, {'aria-label': 'remove node'}));
      const draws = el('div', 's3-row', ...(n.draws || []).map((d, k) => el('span', {class: 's3-draw' + (d.fixed !== undefined ? ' locked' : ''), style: `--fam:${FAM[d.family] || 'var(--obs)'}`,
          onclick: e => { e.stopPropagation(); segSel = {node: i, draw: k}; repaint(); }},
        el('span', {class: 's3-dice', title: d.fixed !== undefined ? 'roulette off: pinned to ' + d.fixed + ' - tap for the properties' : d.category ? 'static category ' + d.category + ' - the item still rolls' : 'roulette on - tap to pin a value',
          text: d.fixed !== undefined ? 'pin' : 'd100', onclick: e => { e.stopPropagation(); segSel = {node: i, draw: k}; if (d.fixed === undefined) d.fixed = (segTableItems(d.family)[0] || {}).id || ''; else delete d.fixed; repaint(); }}),
        d.family + (d.tables ? ':' + d.tables.join('/') : '') + (d.closes ? ' closes' : '') + (d.fixed !== undefined ? ' = ' + d.fixed : d.category ? ' in ' + d.category : ''),
        btn('x', e => { e.stopPropagation(); n.draws.splice(k, 1); segSel = {node: i, draw: -1}; repaint(); }, {'aria-label': 'remove draw', style: 'padding:0 5px'}))),
        (n.draws || []).length ? null : el('span', {class: 's3-muted', text: 'no draws - drop a family here'}));
      card.append(head, cycle ? null : el('div', {class: 's3-muted', text: n.act || ''}), draws);
      return card;
    };
    const gap = (i) => el('div', {class: 's3-seg-gap', text: '↓',
      ondragover: e => { if (segDrag && (segDrag.kind === 'node' || segDrag.kind === 'move')) { e.preventDefault(); e.currentTarget.classList.add('s3-drop-here'); } },
      ondragleave: e => e.currentTarget.classList.remove('s3-drop-here'),
      ondrop: e => { e.currentTarget.classList.remove('s3-drop-here'); if (!segDrag) return; e.preventDefault();
        if (segDrag.kind === 'node') {
          nodes.splice(i, 0, cycle ? {id: 'step' + Date.now().toString(36), label: 'New step', speaker: 'responder_a', draws: [{family: 'ES'}, {family: 'RS'}], speakerbox: []}
            : {id: 'leg' + Date.now().toString(36), label: 'New leg', place: 'middle', seat: 'alternate', act: 'answers the line before.', draws: [{family: 'ES'}, {family: 'RS'}]});
          segSel = {node: i, draw: -1};
        } else if (segDrag.kind === 'move') { const from = segDrag.from; const [m] = nodes.splice(from, 1); const to = i > from ? i - 1 : i; nodes.splice(to, 0, m); segSel = {node: to, draw: -1}; }
        segDrag = null; repaint(); }});
    const list = el('div', 's3-seg-nodes');
    nodes.forEach((n, i) => { list.append(gap(i), nodeCard(n, i)); });
    list.append(gap(nodes.length));
    if (!nodes.length) list.append(para('No nodes yet - drag "+ leg" here.', 's3-muted'));
    const isVariant = segRoad.includes('~');
    const base = segRoad.split('~')[0];
    const roadSel = el('select', {'aria-label': 'segment', onchange: e => { segRoad = e.target.value; segNodes = null; repaint(); }},
      ...roads.map(r => el('option', {value: r, selected: r === segRoad,
        text: r === 'banter' ? 'banter (the cycle)' : (r.includes('~') ? ' ' + r.split('~')[0] + ' variant: ' + ((segStructures()[r] || {}).label || r) : r + ' (' + ((segStructures()[r] || {}).kind || 'legs') + ')')})));
    const bar = el('div', 's3-seg-bar', el('label', {class: 's3-muted', text: 'segment'}), roadSel,
      cycle ? null : btn('Duplicate as variant', async () => {
        const name = prompt('Name for the variant of ' + base + ':', (st.label || base) + ' B'); if (!name) return;
        const n = Object.keys(segStructures()).filter(k => k.startsWith(base + '~v')).length + 1;
        const key = base + '~v' + n;
        try { const res = await send('/api/system3/structures/' + encodeURIComponent(key), 'PUT', {...st, legs: nodes, graph: segGraph, label: name, weight: 1, enabled: true, variant_of: base});
          await loadConfig(); segRoad = key; segNodes = null; repaint(); saved('variant ' + key, res); } catch (e) { report(e); }
      }),
      isVariant ? el('label', 's3-row', 'weight', el('input', {type: 'number', min: 0, max: 50, step: 0.1, value: st.weight == null ? 1 : st.weight, style: 'width:72px', onchange: e => { st.weight = +e.target.value; }})) : null,
      isVariant ? el('label', 's3-row', el('input', {type: 'checkbox', checked: st.enabled !== false, onchange: e => { st.enabled = e.target.checked; }}), 'runs on the station') : null,
      btn('Save segment', async () => { try {
          let res;
          if (cycle) { nodes.forEach((x, i) => { x.id = x.id || 'step' + i; }); res = await send('/api/system3/structure', 'PUT', {steps: nodes, initiator: segInitiator ?? (st.initiator || ''), graph: segGraph}); }   /* [s3-flow] */
          else { nodes.forEach((lg, i) => { lg.id = lg.id || 'leg' + i; }); res = await send('/api/system3/structures/' + encodeURIComponent(segRoad), 'PUT', {...st, legs: nodes, graph: segGraph}); }
          await loadConfig(); segNodes = null; repaint(); saved(cycle ? 'the banter cycle' : 'the ' + segRoad + ' segment', res); } catch (e) { report(e); } }),
      btn('Discard', () => { segNodes = null; repaint(); }),
      isVariant ? btn('Delete variant', async () => { if (!confirm('Delete ' + segRoad + '?')) return;
        try { const res = await send('/api/system3/structures/' + encodeURIComponent(segRoad), 'DELETE'); await loadConfig(); segRoad = base; segNodes = null; repaint(); saved('- deleted variant ' + (res && res.deleted || segRoad), res); } catch (e) { report(e); } }) : null,
      el('span', {class: 's3-muted', text: cycle ? 'The banter cycle loops for the segment; each step is a node with its own draws.'
        : `Turn budget ${st.min_turns || '?'}-${st.max_turns || '?'}. ${isVariant ? 'This variant' : 'Every variant'} rolls against the base by weight (VARIANT) each time the road runs.`}));
    fill(body, el('div', 's3-seg', el('div', 's3-seg-side', el('div', 's3-card', palette), el('div', 's3-card', el('h2', {text: 'Properties'}), props)),
      el('div', 's3-seg-main', el('div', 's3-card', el('h2', {text: (st.label || segRoad) + ' - segment'}), bar),
        segGraphView(repaint), list)));
  }

  /* ---------------- prompts: every model call, as tiles --------------------- */
  let promptRows = [], promptModels = [], promptModel = '', promptsTimer = 0;
  const promptOpen = new Map();
  async function loadPrompts() {
    try { const got = await request('/api/prompt-history?limit=40' + (promptModel ? '&model=' + encodeURIComponent(promptModel) : ''));
      promptRows = got.rows || []; if ((got.models || []).length) promptModels = got.models; } catch (e) { report(e); }
  }
  function promptBody(r, d) {
    if (d.error && !d.request) return para(String(d.error), 's3-error');
    const parts = promptParts(d);
    const box = (title, kid, pre = true) => el('div', 's3-tile-box', el('h4', {text: title}), pre ? el('pre', {text: kid || '(none)'}) : kid);
    /* [s3-rolodex] "in front of system prompt put a section showing the
       rolodex result and the dice rolls on each row for why this prompt is
       being made" - first in the grid, the full width. */
    const rolodex = el('div', {class: 's3-muted', text: 'finding the round this call wrote...'});
    const grid = el('div', 's3-tile-grid', el('div', 's3-tile-box s3-rolodex-box', el('h4', {text: 'Rolodex'}), rolodex),
      box('System prompt', readablePromptText(parts.sys || (parts.user ? NO_SYSTEM : '')), false), box('Prompt', readablePromptText(parts.user), false), box('LLM settings', json(parts.opts)),
      box('Result', d.error ? String(d.error) : (parts.text || (d.state === 'running' ? 'still running' : '(empty)'))));
    rolodexFor(r, d, rolodex);
    return grid;
  }
  /* The round this call wrote: the rounds planned in the fifteen minutes
     before it, newest first, the first whose running order is in this
     prompt word for word; a writer call with no such round falls back to
     the nearest by time and says so. */
  async function rolodexFor(r, d, into) {
    try {
      const list = await request('/api/system3/conversations?limit=60');
      const at = Number(r.at || 0);
      const text = normWs(promptText(d));
      const cands = (list.conversations || []).filter(c => Number(c.created || 0) <= at + 2 && at - Number(c.created || 0) < 2400).sort((a, b) => Number(b.created) - Number(a.created));
      if (!cands.length) { fill(into, para(rolodexNone(r), 's3-muted')); return; }
      let conv = null, why = '', lit = null;
      for (const c of cands.slice(0, 10)) {
        let full;
        try { full = await cachedConversation(request, c.conversation_id); } catch (e) { continue; }
        const mark = normWs(sheetMark(full));
        const segs = rowSegments(text);
        const mine = new Set((full.turns || []).filter(t => { const h = rowHead(full, t); return (h && text.includes(h)) || turnRowIn(text, full, t, segs); }).map(t => t.turn_id));
        if (mine.size) { conv = full; lit = mine; why = `this call wrote message${mine.size > 1 ? 's' : ''} ${(full.turns || []).filter(t => mine.has(t.turn_id)).map(t => t.index + 1).join(', ')} - their rows of the running order are in this prompt`; break; }
        if (mark && text.includes(mark)) { conv = full; why = 'its running order is in this prompt'; break; }
      }
      if (!conv) {
        if (!WRITER_PURPOSE.test(String(r.purpose || ''))) { fill(into, para(rolodexNone(r), 's3-muted')); return; }
        const c = cands[0];
        conv = await cachedConversation(request, c.conversation_id);
        why = `planned ${num(at - Number(c.created || 0), 1)} s before this call - matched by time; its running order is not in this prompt word for word`;
      }
      if (!into.isConnected) return;
      const rows = rolodexRows(conv, v.api, lit ? {turns: lit} : {});
      const id = (conv.identity || {}).conversation_id || '';
      fill(into, el('div', {class: 's3-muted', text: `${(conv.identity || {}).road_kind || ''} round ${id} - ${why} - ${(conv.decision_events || []).filter(e => !e.stage).length} rolls. Tap a tick for what the roll means for the prompt.`}),
        rows, el('div', 's3-row', btn('Open this round in the Director', () => { stopExtras(); tab = 'director'; paint(); load(id); })));
      rows.roll();
    } catch (e) { fill(into, para('could not read the round: ' + e.message, 's3-muted')); }
  }
  function promptTile(r) {
    const open = promptOpen.has(r.id);
    const tile = el('details', {class: 's3-tile', open});
    tile.dataset.id = r.id;
    let bodyNode = null;
    const openBody = async () => {
      if (bodyNode) bodyNode.remove();
      bodyNode = para('Loading...', 's3-muted'); tile.append(bodyNode);
      let d = promptOpen.get(r.id);
      if (!d || d === 'loading') {
        promptOpen.set(r.id, 'loading');
        try { const got = await request('/api/prompt-history/' + encodeURIComponent(r.id)); d = got.row || got; } catch (err) { d = {error: err.message}; }
        promptOpen.set(r.id, d);
      }
      if (!tile.open || !tile.isConnected) return;
      const made = promptBody(r, d); bodyNode.replaceWith(made); bodyNode = made;   /* in place: nothing else moves */
    };
    tile.addEventListener('toggle', () => {
      if (!tile.open) { promptOpen.delete(r.id); if (bodyNode) { bodyNode.remove(); bodyNode = null; } return; }
      openBody();
    });
    tile.append(el('summary', null, el('b', {text: r.model || '?'}), el('span', {class: 's3-muted', text: r.purpose || ''}),
      el('span', {class: 's3-state s3-state-' + (r.state || 'done'), text: r.state || ''}), el('span', {class: 's3-muted', text: clock(Number(r.at || 0))}),
      el('span', {class: 's3-muted s3-took', text: r.finished && r.at ? num(Number(r.finished) - Number(r.at), 1) + ' s' : ''}),
      el('span', {class: 's3-muted', style: 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap', text: r.preview || ''})));
    if (open) openBody();
    return tile;
  }
  function paintPromptsList() {
    const listNode = body.querySelector('.s3-feed'); if (!listNode) return;
    promptPending = [];
    fill(listNode, ...promptRows.map(promptTile));
  }
  let promptPending = [];
  /* [s3-hold] a poll never rebuilds the list: it refreshes the state of the
     tiles on the page and adds new calls at the top only when the list is
     at its top and nobody is reading - otherwise they wait behind the pill. */
  function promptArrive(rows) {
    const listNode = body.querySelector('.s3-feed'); if (!listNode) return;
    const have = new Map([...listNode.querySelectorAll('.s3-tile')].map(t => [t.dataset.id, t]));
    const fresh = [];
    for (const r of rows) {
      const t = have.get(r.id);
      if (!t) { fresh.push(r); continue; }
      const st = t.querySelector('.s3-state'); if (st && st.textContent !== (r.state || '')) { st.textContent = r.state || ''; st.className = 's3-state s3-state-' + (r.state || 'done'); }
      const took = t.querySelector('.s3-took'); if (took && r.finished && r.at) took.textContent = num(Number(r.finished) - Number(r.at), 1) + ' s';
    }
    promptRows = rows;
    if (!fresh.length) return;
    const show = () => { const pill = listNode.querySelector(':scope > .s3-newpill'); if (pill) pill.remove();
      const first = listNode.firstChild; for (const r of promptPending.slice().reverse()) listNode.insertBefore(promptTile(r), listNode.firstChild);
      promptPending = []; if (first) { /* the reader stays where they were: nothing below moved */ } };
    fresh.sort((a, b) => Number(a.at || 0) - Number(b.at || 0));
    promptPending.push(...fresh.filter(r => !promptPending.some(x => x.id === r.id)));
    if (!reading() && scrolledTop(listNode)) show(); else newPill(listNode, promptPending.length, show);
  }
  async function paintPrompts() {
    fill(body, el('div', 's3-card', el('h2', {text: 'Prompts - every model call, newest first'}), el('div', 's3-row',
        el('select', {'aria-label': 'model', onchange: async e => { promptModel = e.target.value; await loadPrompts(); paintPromptsList(); }},
          el('option', {value: '', text: 'all models'}), ...promptModels.map(m => el('option', {value: m, text: m, selected: m === promptModel}))),
        btn('Refresh', async () => { await loadPrompts(); paintPromptsList(); }),
        el('span', {class: 's3-muted', text: 'Each tile opens into the system prompt, the prompt, the LLM settings, the result, and the roulette results of the round System 3 planned for it.'})),
      el('div', 's3-feed')));
    await loadPrompts(); paintPromptsList();
    clearInterval(promptsTimer);
    promptsTimer = setInterval(async () => { if (tab !== 'prompts' || document.hidden) return;
      try { const got = await request('/api/prompt-history?limit=40' + (promptModel ? '&model=' + encodeURIComponent(promptModel) : '')); promptArrive(got.rows || []); } catch (e) { /* next tick */ } }, 6000);
  }

  /* ---------------- audit: everything System 3 does, latest first ----------- */
  let auditEvents = [], auditHead = 0, auditTimer = 0, auditFilter = {family: '', conversation: ''}, menuNode = null;
  const auditRoads = new Map();
  async function auditRoadsLoad() {
    try { const list = await request('/api/system3/conversations?limit=60'); for (const c of (list.conversations || [])) auditRoads.set(c.conversation_id, c); } catch (e) { /* the log still reads */ }
  }
  async function auditLoad(initial) {
    try {
      if (initial) {
        const head = await request('/api/system3/events?after=0&limit=1'); const top = Number(head.head || 0);
        const got = await request('/api/system3/events?after=' + Math.max(0, top - 400) + '&limit=400');
        auditEvents = got.events || []; auditHead = Number(got.cursor || top); return true;
      }
      const got = await request('/api/system3/events?after=' + auditHead + '&limit=200');
      if ((got.events || []).length) { auditEvents.push(...got.events); auditHead = Number(got.cursor || auditHead); if (auditEvents.length > 800) auditEvents.splice(0, auditEvents.length - 800); return got.events; }
    } catch (e) { report(e); }
    return false;
  }
  let auditPending = [];
  /* [s3-hold] fresh events are drawn at the top only when the list is at its
     top and nobody is reading; otherwise they wait behind the pill, and the
     rows the operator is reading never move. */
  function auditArrive(fresh) {
    const listNode = body.querySelector('.s3-audit'); if (!listNode) return;
    const rows = [];
    for (const e of fresh) {
      if ((auditFilter.family && e.family !== auditFilter.family) || (auditFilter.conversation && e.conversation_id !== auditFilter.conversation)) continue;
      let prev = null; const at = auditEvents.indexOf(e);
      for (let i = at - 1; i >= 0; i -= 1) if (auditEvents[i].conversation_id === e.conversation_id) { prev = auditEvents[i]; break; }
      rows.push(auditRow(e, prev));
    }
    if (!rows.length) return;
    auditPending.push(...rows);
    const show = () => { const pill = listNode.querySelector(':scope > .s3-newpill'); if (pill) pill.remove();
      for (const row of auditPending) listNode.insertBefore(row, listNode.firstChild);   /* oldest first, so the newest ends on top */
      auditPending = []; };
    if (!reading() && scrolledTop(listNode)) show(); else newPill(listNode, auditPending.length, show);
  }
  function auditLabel(e) {
    if (e.kind === 'observation') return String(e.stage || e.family || '') + (e.line ? ': ' + String(e.line).slice(0, 80) : e.door ? ': ' + e.door : '');
    const sel = e.selected || {}; return String(sel.label || sel.id || (e.meta && e.meta.why) || '').slice(0, 90);
  }
  async function auditOpen(e) {
    try { const conv = await request('/api/system3/conversation/' + encodeURIComponent(e.conversation_id));
      const ev = (conv.decision_events || []).find(x => x.event_id === e.event_id) || (conv.observations_air || []).find(x => x.event_id === e.event_id) || e;
      openDecision(conv, ev, (conv.turns || []).find(t => t.turn_id === ev.turn_id) || null, v.api); } catch (err) { report(err); }
  }
  function auditMenu(x, y, e, prev) {
    if (menuNode) menuNode.remove();
    const close = () => { if (menuNode) menuNode.remove(); menuNode = null; document.removeEventListener('pointerdown', away, true); };
    const away = ev => { if (menuNode && !menuNode.contains(ev.target)) close(); };
    const item = (label, fn) => btn(label, () => { close(); fn(); });
    menuNode = el('div', {class: 's3-menu', style: `left:${Math.max(4, Math.min(x, window.innerWidth - 240))}px;top:${Math.max(4, Math.min(y, window.innerHeight - 220))}px`},
      item('Open the decision card', () => auditOpen(e)),
      item('Open the round in the Director', () => { stopExtras(); tab = 'director'; paint(); load(e.conversation_id); }),
      prev ? item('Open the previous command', () => auditOpen(prev)) : null,
      item('Only this round', () => { auditFilter.conversation = e.conversation_id; paintAuditList(); }),
      item('Only ' + (e.family || ''), () => { auditFilter.family = e.family || ''; paintAuditList(); }),
      item('Copy the event id', () => { try { navigator.clipboard.writeText(e.event_id || ''); } catch (_) { /* no clipboard */ } }));
    document.body.append(menuNode);
    if (window.pineCloseX) window.pineCloseX(menuNode, close, {label: 'Close the menu', reserve: 'top'});   // [closex:s3-audit-menu]
    setTimeout(() => document.addEventListener('pointerdown', away, true), 0);
  }
  function auditRow(e, prev) {
    const c = auditRoads.get(e.conversation_id) || {};
    const fam = e.family || '';
    const road = c.road || c.road_kind || '';
    const row = el('details', {class: 's3-audit-row', style: `--fam:${FAM[fam] || 'var(--obs)'}`});
    row.append(el('summary', null, el('span', {class: 's3-muted', text: clock(Number(e.at || 0))}), el('span', {class: 'fam', text: fam + (e.kind === 'observation' ? ' obs' : '')}),
      el('span', {text: auditLabel(e)}), el('span', {class: 's3-muted', text: road + ' ' + String(e.conversation_id || '').slice(0, 8)})));
    const took = prev ? Number(e.at || 0) - Number(prev.at || 0) : null;
    row.append(el('div', 's3-audit-body',
      el('div', null, el('b', {text: 'operation'}), (e.kind === 'observation' ? 'observed at air: ' : 'decided: ') + fam + ' - ' + auditLabel(e)
        + (Number(e.turn_index) >= 0 ? ` (turn ${Number(e.turn_index) + 1})` : ' (before the first turn)')),
      el('div', null, el('b', {text: 'originator'}), `${road || 'a'} round ${e.conversation_id || ''}` + (c.topic ? ' - ' + String(c.topic).slice(0, 80) : '') + (e.engine ? ' - ' + e.engine : '')),
      el('div', null, el('b', {text: 'time taken'}), took == null ? 'the first recorded step of this round' : `${num(took * 1000, 0)} ms after the step before it`),
      el('div', null, el('b', {text: 'previous connected command'}), prev ? btn((prev.family || '') + ' ' + auditLabel(prev) + ' (' + prev.event_id + ')', () => auditOpen(prev), {class: 's3-pill'}) : 'none - this round starts here'),
      el('div', 's3-row', btn('Open decision', () => auditOpen(e)), btn('Open round in the Director', () => { stopExtras(); tab = 'director'; paint(); load(e.conversation_id); }),
        btn('Only this round', () => { auditFilter.conversation = e.conversation_id; paintAuditList(); }), btn('Only ' + fam, () => { auditFilter.family = fam; paintAuditList(); }))));
    row.addEventListener('contextmenu', ev => { ev.preventDefault(); auditMenu(ev.clientX, ev.clientY, e, prev); });
    let press = 0;
    row.addEventListener('pointerdown', ev => { if (ev.pointerType === 'mouse') return; clearTimeout(press); press = setTimeout(() => auditMenu(ev.clientX, ev.clientY, e, prev), 550); });
    ['pointerup', 'pointercancel', 'pointermove'].forEach(n => row.addEventListener(n, () => clearTimeout(press)));
    return row;
  }
  function paintAuditList() {
    const listNode = body.querySelector('.s3-audit'); if (!listNode) return;
    const prevOf = new Map(); const lastIn = new Map();
    for (const e of auditEvents) { prevOf.set(e, lastIn.get(e.conversation_id) || null); lastIn.set(e.conversation_id, e); }
    const shown = auditEvents.filter(e => (!auditFilter.family || e.family === auditFilter.family) && (!auditFilter.conversation || e.conversation_id === auditFilter.conversation)).slice(-300).reverse();
    auditPending = [];
    fill(listNode, ...shown.map(e => auditRow(e, prevOf.get(e))));
    const f = body.querySelector('.s3-audit-filter'); if (f) f.textContent = (auditFilter.family || auditFilter.conversation) ? `filter: ${auditFilter.family || ''} ${auditFilter.conversation || ''}` : '';
  }
  async function paintAudit() {
    fill(body, el('div', 's3-card', el('h2', {text: 'Audit - everything System 3 does, latest first'}), el('div', 's3-row',
        btn('Clear filter', () => { auditFilter = {family: '', conversation: ''}; paintAuditList(); }), el('span', 's3-muted s3-audit-filter'),
        el('span', {class: 's3-muted', text: 'Open an entry for the operation, its originator, the time it took and the command before it. Right-click or long-press for the menu.'})),
      el('div', 's3-audit')));
    await auditRoadsLoad(); await auditLoad(true); paintAuditList();
    clearInterval(auditTimer);
    auditTimer = setInterval(async () => { if (tab !== 'audit' || document.hidden) return;
      const fresh = await auditLoad(false); if (fresh && fresh.length) { await auditRoadsLoad(); auditArrive(fresh); } }, 3000);
  }

  /* The visual prompt follows one recorded turn into the actual writer call.
     Nodes are evidence from the conversation and prompt history, never new draws. */
  let visualScene = null, visualCid = conversationId, visualTurn = '', visualToken = 0, visualPreview = null;
  let visualBanterRows = null, visualPromptConfig = null;
  let visualSidebarOpen = true;
  try { visualSidebarOpen = localStorage.getItem('s3.visualSidebarOpen') !== '0'; } catch (_) { /* optional */ }
  const visualCalls = new Map(), visualCallDetails = new Map();
  const readablePrompt = readablePromptText;
  function visualGraph(conv, turn, writer, promptConfig = {}) {
    const nodes = [], edges = [];
    const add = (id, label, kind, detail, x, y, z = 0, data = null) => nodes.push({id, label, kind, detail, x, y, z, data});
    const link = (a, b, kind = 'flow') => edges.push({a, b, kind});
    const subject = conv.subject || {}, carry = conv.carry || null;
    const landing = carry && carry.landing || {};
    add('prior', 'Previous knowledge', 'source', carry ? `Carried from the prior round: ${landing.text || 'conversation state and emotion'}` : 'No previous round was carried into this one.', -13.5, 4, -1, carry);
    add('topic', 'Topic / initial tile', 'source', subject.topic || '(no subject)', -13.5, 1, -1, subject);
    const databaseInputs = conv.inputs || {};
    add('database', 'Database / road inputs', 'source', 'The recorded source files, topic bank, schedule and availability supplied to this round.', -13.5, -5, -1, databaseInputs);
    const previous = (conv.turns || []).find(t => t.index === turn.index - 1);
    const promptHasPrevious = previous && previous.text && writer.detail && promptText(writer.detail).includes(previous.text);
    add('previous', promptHasPrevious ? 'Previous reply in prompt' : 'Previous turn / state', 'source',
      previous ? (previous.text || 'Previous turn is planned; words are not recorded.') +
        (promptHasPrevious ? ' Its words appear in this model request.' : ' Its exact words were not found in this model request; System 3 still planned this turn from earlier state.')
        : 'This is the first turn of the round.', -13.5, -2, -1, previous);
    add('state', 'Conversation state', 'assembly', 'The phase, tension, speaker emotions, unresolved points, and prior turns that condition the next System 3 decisions.', -9.5, .4, -.3,
      (turn.decisions || []).length ? ((conv.decision_events || []).find(e => e.event_id === turn.decisions[0].event_id) || {}).state_before : conv.dynamics);
    const events = (conv.decision_events || []).filter(e => !e.stage && (e.turn_id === turn.turn_id || (!e.turn_id && turn.index === 0)));
    // Cards are 1.23 units tall. Keep adjacent draws apart so their
    // coplanar faces never overlap and flicker while the graph moves.
    const eventStep = 1.6;
    const eventTop = Math.max(3, (events.length - 1) * eventStep / 2);
    events.forEach((ev, i) => {
      const id = 'event-' + ev.event_id;
      const drawn = !!(ev.rng || (ev.stages || []).some(s => s.draw));
      add(id, `${ev.family}  ${landedWords(ev, conv)}`, drawn ? 'roll' : 'decision', `${eventLine(ev, conv).text}`, -5.2, eventTop - i * eventStep, .4, ev);
      link('state', id, 'input'); link(id, 'assembly', drawn ? 'roll' : 'state');
    });
    const material = (conv.material || []).filter(m => events.some(e => e.event_id === m.decided_by));
    const eventBottom = eventTop - (events.length - 1) * eventStep;
    add('material', 'Speakerbox / sources', 'source', material.length ? material.map(m => (m.selected || {}).file || 'selected passage').join(', ') : 'No passage selected for this turn.', -5.2, Math.min(-3, eventBottom - eventStep), -.5, material);
    add('assembly', 'Turn instructions', 'assembly', sheetRowOf((conv.plan || {}).sheet || '', turn) || 'No running-order row recorded.', -.5, 1, 1, turn);
    add('system', 'System prompt', 'prompt', writer.parts ? (writer.parts.sys || NO_SYSTEM) : 'No writer call found.', 4, 3.2, .5, 'system');
    add('prompt', 'Prompt / conversation', 'prompt', writer.parts ? writer.parts.user : 'No writer call found.', 4, -.6, .5, 'user');
    const previewLayers = ((writer.detail || {}).layers) || {};
    if (previewLayers.station) {
      add('standing', 'Standing instructions', 'source', previewLayers.station, -.5, 4.8, .4);
      link('standing', 'prompt', 'input');
    }
    if ((previewLayers.personas || []).length) {
      add('personas', 'Speaker personas', 'source', previewLayers.personas.join('\n'), -.5, -2.5, .4);
      link('personas', 'prompt', 'input');
    }
    add('model', writer.sharedTurns > 1 ? `LLM call · ${writer.sharedTurns} turns` : 'LLM call', 'model', writer.row ? `${writer.row.model || 'model'} · ${writer.row.purpose || 'writer'}` : 'No matched model call.', 8.5, 1.3, 1, writer);
    add('reply', `${turn.name || turn.speaker} replies`, 'reply', turn.text || (writer.parts ? 'The model returned a draft, but no reply matched this turn and speaker.' : 'No reply text recorded.'), 12.7, 1.3, .5, turn);
    if (carry) link('prior', 'state', 'input');
    link('topic', 'state', 'input');
    if (Object.keys(databaseInputs).length) link('database', 'state', 'input');
    if (previous) link('previous', 'state', 'input');
    link('state', 'assembly', 'input');
    if (material.length) link('material', 'assembly', 'input');
    link('assembly', 'prompt'); link('system', 'model'); link('prompt', 'model'); link('model', 'reply');
    if ((conv.turns || []).some(t => t.index === turn.index + 1)) {
      add('next', writer.sharedTurns > 1 ? 'Next planned turn' : 'Next turn', 'next',
        writer.sharedTurns > 1 ? 'These turns were in one model request. The next turn was planned from conversation state; this reply was not separately sent back before that call.'
          : 'The next turn can receive this reply as prior conversation when written in a later model call.', 16.8, 1.3, -.6);
      link('reply', 'next');
    }
    const dispatch = (writer.detail || {}).properties || {};
    const sourceSettings = (promptConfig.nodes || []).map(n => {
      let saved = dispatch;
      for (const part of n.path || []) saved = saved && saved[part];
      return {...n, capturedValue: typeof saved === 'string' ? saved : n.value,
        capturedFromDispatch: typeof saved === 'string'};
    }).filter(n => typeof n.capturedValue === 'string' && n.capturedValue.length >= 40);
    for (const [key, label] of [['agent_prompt', 'Agent prompt at dispatch'],
                                ['schedule_prompt', 'Schedule prompt at dispatch']]) {
      const value = key === 'agent_prompt' ? (dispatch.agent_prompt || {}).prompt : dispatch.schedule_prompt;
      if (typeof value === 'string' && value.length >= 40 && !sourceSettings.some(n => n.capturedValue === value))
        sourceSettings.push({path: ['dispatch', key], label, capturedValue: value,
          capturedFromDispatch: true, origin: 'snapshot'});
    }
    const sysMessages = (((writer.detail || {}).request || {}).messages || []).filter(m => m && m.role === 'system');
    const captured = sysMessages.length ? sysMessages.map(m => String(m.content || '')) :
      (writer.parts && writer.parts.sys ? [writer.parts.sys] : []);
    let sourceIndex = 0;
    const origin = (label, detail, data, parent = 'system') => {
      const id = `system-origin-${sourceIndex}`;
      add(id, label, 'source', detail, 4, 6.5 + sourceIndex * 1.65, -.5, data);
      link(id, parent, 'input'); sourceIndex += 1;
      return id;
    };
    captured.forEach((content, messageIndex) => {
      if (content.startsWith('OPERATOR WORDING PREFERENCES')) {
        const split = content.indexOf('\n');
        const intro = split >= 0 ? content.slice(0, split) : content;
        const builder = origin('Operator wording policy', intro,
          {origin: 'compiled', path: 'app.py · line_review_guidance()', value: intro,
            control_path: ['dj', 'operator_wording_examples']});
        let examples = null;
        try { examples = JSON.parse(content.slice(split + 1)); } catch (_) { /* show unparsed evidence below */ }
        if (Array.isArray(examples)) {
          examples.forEach((example, i) => origin(`Review ${i + 1} · ${example.gate || 'gate'} · ${example.action || 'decision'}`,
            json(example), {origin: 'review', review_id: example.review_id, captured: example,
              path: `data/line_review.sqlite3 · line_reviews.id=${example.review_id}`}, builder));
        } else if (split >= 0) origin('Review evidence · captured text', content.slice(split + 1),
          {origin: 'unresolved', path: 'line-review database · exact record not parsed'} , builder);
        return;
      }
      let remainder = content;
      for (const setting of [...sourceSettings].sort((a, b) => b.capturedValue.length - a.capturedValue.length)) {
        if (!remainder.includes(setting.capturedValue)) continue;
        origin(setting.label || setting.path.join(' / '), setting.capturedValue,
          {origin: setting.origin || 'setting', path: setting.path, setting});
        remainder = remainder.replace(setting.capturedValue, '');
      }
      const sections = remainder.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
      sections.forEach((section, i) => origin(`Captured system text ${messageIndex + 1}.${i + 1}`, section,
        {origin: 'unresolved', path: 'Captured model request · origin not recorded'}));
    });
    const userContent = writer.parts && writer.parts.user || '';
    for (const [marker, label, path, control] of [
      ['your own show-notes', 'Distilled show notes', 'data/crystal_notes.json · latest two notes', ['dj', 'system3_crystal_notes']],
      ['the conversation so far', 'Recent aired dialogue', 'live _RADIO.chat · last eight speaker lines', null]]) {
      const at = userContent.indexOf(marker);
      if (at < 0) continue;
      const end = userContent.indexOf('\n', at);
      origin(label, userContent.slice(at, end < 0 ? at + 650 : Math.min(end, at + 650)),
        {origin: control ? 'memory' : 'live-memory', path, control_path: control}, 'prompt');
    }
    // Keep every card's face clear, even if a future source or draw adds
    // another node to a lane. Depth does not exempt a card from this check:
    // two faces at different z positions can still obscure each other.
    const cardWidth = 3.7, cardHeight = 1.23, gap = .3;
    nodes.forEach((node, index) => {
      let clash;
      do {
        clash = nodes.slice(0, index).find(other =>
          Math.abs(node.x - other.x) < cardWidth + gap &&
          Math.abs(node.y - other.y) < cardHeight + gap);
        if (clash) node.y = clash.y - cardHeight - gap - .01;
      } while (clash);
    });
    return {nodes, edges, events};
  }
  function visualThree(THREE, canvas, graph, onSelect) {
    const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, .1, 200);
    const cameraRise = 1.75;
    camera.position.set(-1, cameraRise, 25); camera.lookAt(-1, 0, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 1.25));
    const colors = {source: 0x86bfab, roll: 0xf2c77f, decision: 0xc7b693, assembly: 0xbba2e9, prompt: 0x8dbdff, model: 0xf5a6c8, reply: 0x91dfa9, next: 0x98aaa9};
    const pick = [], positions = new Map(), packets = [];
    function cardTexture(node) {
      const c = document.createElement('canvas'); c.width = 512; c.height = 170;
      const g = c.getContext('2d'); g.fillStyle = '#17252c'; g.fillRect(0, 0, 512, 170);
      g.strokeStyle = '#' + colors[node.kind].toString(16).padStart(6, '0'); g.lineWidth = 7; g.strokeRect(4, 4, 504, 162);
      g.fillStyle = '#f0f5f1'; g.font = 'bold 29px system-ui';
      const words = node.label.split(' '); let line = '', y = 70;
      for (const word of words) {
        if (g.measureText(line + ' ' + word).width > 465 && line) { g.fillText(line, 22, y); y += 37; line = word; }
        else line = line ? line + ' ' + word : word;
      }
      g.fillText(line, 22, y);
      g.font = '20px system-ui'; g.fillStyle = '#a9bcbd'; g.fillText(node.kind === 'roll' ? 'recorded draw · click to inspect' : 'click to inspect', 22, 145);
      return new THREE.CanvasTexture(c);
    }
    graph.nodes.forEach(n => {
      const p = new THREE.Vector3(n.x, n.y, n.z); positions.set(n.id, p);
      const mat = new THREE.MeshBasicMaterial({map: cardTexture(n), transparent: true, side: THREE.DoubleSide});
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(3.7, 1.23), mat);
      mesh.position.copy(p); mesh.userData.node = n; scene.add(mesh); pick.push(mesh);
    });
    graph.edges.forEach(e => {
      const a = positions.get(e.a), b = positions.get(e.b); if (!a || !b) return;
      const start = a.clone().add(new THREE.Vector3(1.86, 0, -.35));
      const end = b.clone().add(new THREE.Vector3(-1.86, 0, -.35));
      const curve = new THREE.CubicBezierCurve3(start,
        start.clone().add(new THREE.Vector3(Math.max(1, (end.x - start.x) * .4), 0, -.3)),
        end.clone().add(new THREE.Vector3(-Math.max(1, (end.x - start.x) * .4), 0, -.3)), end);
      const color = e.kind === 'roll' ? 0xf2c77f : e.kind === 'input' ? 0x6fae99 : 0x9ac7e6;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(24)),
        new THREE.LineBasicMaterial({color, transparent: true, opacity: .56})); scene.add(line);
      if (e.kind === 'roll' || e.kind === 'flow') {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(.075, 9, 7), new THREE.MeshBasicMaterial({color}));
        scene.add(dot); packets.push({dot, curve, phase: packets.length * .137});
      }
    });
    const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
    const floor = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    const fingers = new Map();
    let press = null, pinch = null, moved = false, alive = true, raf = 0;
    const pointAt = (x, y) => {
      const rect = canvas.getBoundingClientRect();
      pointer.set((x - rect.left) / rect.width * 2 - 1, -(y - rect.top) / rect.height * 2 + 1);
      camera.updateMatrixWorld(); ray.setFromCamera(pointer, camera);
      return ray.ray.intersectPlane(floor, new THREE.Vector3());
    };
    const pan = (from, to) => {
      const a = pointAt(from.x, from.y), b = pointAt(to.x, to.y);
      if (!a || !b) return;
      camera.position.x += a.x - b.x; camera.position.y += a.y - b.y;
      camera.lookAt(camera.position.x, camera.position.y - cameraRise, 0);
    };
    const zoom = (x, y, scale) => {
      const before = pointAt(x, y);
      camera.position.z = Math.max(5, Math.min(100, camera.position.z * scale));
      camera.lookAt(camera.position.x, camera.position.y - cameraRise, 0);
      const after = pointAt(x, y);
      if (before && after) {
        camera.position.x += before.x - after.x; camera.position.y += before.y - after.y;
        camera.lookAt(camera.position.x, camera.position.y - cameraRise, 0);
      }
    };
    const pinchMeasure = () => {
      const [a, b] = [...fingers.values()];
      return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2,
        distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y))};
    };
    const down = e => {
      e.preventDefault(); fingers.set(e.pointerId, {x: e.clientX, y: e.clientY});
      canvas.setPointerCapture(e.pointerId);
      if (fingers.size === 1) { press = {x: e.clientX, y: e.clientY, last: {x: e.clientX, y: e.clientY}}; moved = false; }
      else if (fingers.size === 2) { pinch = pinchMeasure(); moved = true; }
    };
    const move = e => {
      if (!fingers.has(e.pointerId)) return;
      const last = fingers.get(e.pointerId);
      fingers.set(e.pointerId, {x: e.clientX, y: e.clientY});
      if (fingers.size === 2) {
        const next = pinchMeasure();
        if (pinch) {
          zoom(next.x, next.y, pinch.distance / next.distance);
          pan({x: pinch.x, y: pinch.y}, {x: next.x, y: next.y});
        }
        pinch = next; moved = true;
      } else if (fingers.size === 1 && press) {
        if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 4) moved = true;
        if (moved) pan(last, {x: e.clientX, y: e.clientY});
        press.last = {x: e.clientX, y: e.clientY};
      }
    };
    const end = (e, cancelled = false) => {
      if (!fingers.has(e.pointerId)) return;
      const clicked = !cancelled && fingers.size === 1 && !moved;
      fingers.delete(e.pointerId); pinch = null;
      if (fingers.size === 1) {
        const remaining = [...fingers.values()][0];
        press = {x: remaining.x, y: remaining.y, last: remaining}; moved = true;
      } else if (!fingers.size) { press = null; moved = false; }
      if (clicked) {
        pointAt(e.clientX, e.clientY);
        const hit = ray.intersectObjects(pick)[0]; if (hit) onSelect(hit.object.userData.node);
      }
    };
    const up = e => end(e);
    const cancel = e => end(e, true);
    const wheel = e => { e.preventDefault(); zoom(e.clientX, e.clientY, Math.exp(e.deltaY * .001)); };
    canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', cancel);
    canvas.addEventListener('wheel', wheel, {passive: false});
    const resize = () => { const w = Math.max(1, canvas.clientWidth), h = Math.max(1, canvas.clientHeight);
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
    const observer = new ResizeObserver(resize); observer.observe(canvas); resize();
    const animate = (time) => { if (!alive) return;
      if (!reduced()) packets.forEach(p => p.dot.position.copy(p.curve.getPoint((time * .00009 + p.phase) % 1)));
      renderer.render(scene, camera); raf = requestAnimationFrame(animate); };
    animate(0);
    return {
      focus(id) { const p = positions.get(id); if (!p) return;
        camera.position.set(p.x, p.y + cameraRise, 18); camera.lookAt(p.x, p.y, 0); },
      fit() { camera.position.set(1, cameraRise, 34); camera.lookAt(1, 0, 0); },
      stop() { alive = false; cancelAnimationFrame(raf); observer.disconnect();
      canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', cancel); canvas.removeEventListener('wheel', wheel);
      scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); } }); renderer.dispose(); }};
  }
  async function paintVisual() {
    const token = ++visualToken;
    if (visualScene) { visualScene.stop(); visualScene = null; }
    if (!visualBanterRows) {
      try { visualBanterRows = (await request('/api/system3/conversations?limit=60&road=banter')).conversations || []; }
      catch (_) { visualBanterRows = []; }
    }
    if (token !== visualToken || tab !== 'visual') return;
    const cid = visualCid || (visualBanterRows[0] && visualBanterRows[0].conversation_id) ||
      (v.conv && v.conv.identity && v.conv.identity.conversation_id) || (list[0] && list[0].conversation_id);
    if (!cid) { fill(body, el('div', 's3-card', el('h2', {text: 'Visual Prompt'}), para('No recorded conversations yet. Plan a round in the Director to see its prompt flow.', 's3-muted'))); return; }
    const shell = el('div', 's3-vp');
    fill(body, shell, para('Loading the recorded conversation...', 's3-muted'));
    try {
      const conv = visualPreview && cid === visualPreview.identity.conversation_id ? visualPreview : await cachedConversation(request, cid);
      if (token !== visualToken || tab !== 'visual') return;
      visualCid = cid;
      const turns = conv.turns || [];
      const turn = turns.find(t => t.turn_id === visualTurn) || turns[0];
      if (!turn) { fill(body, para('This round has no planned turns.', 's3-muted')); return; }
      visualTurn = turn.turn_id;
      const key = cid + ':' + turn.turn_id;
      if (!visualCalls.has(key)) visualCalls.set(key, conv.preview_call
        ? {row: conv.preview_call, detail: conv.preview_call, exact: true, why: 'Off-air preview call using the newly assembled prompt.'}
        : conv.mode === 'simulation'
        ? {row: null, detail: null, why: 'Decision preview only: this plan was not sent to an LLM.'}
        : await findWriterCall(request, conv, turn, visualCallDetails));
      if (token !== visualToken || tab !== 'visual') return;
      const writer = visualCalls.get(key) || {};
      writer.parts = writer.row ? promptParts(writer.detail || {}) : null;
      writer.sharedTurnNumbers = writer.parts ? turns.filter(t => {
        const text = normWs(promptText(writer.detail));
        return (rowHead(conv, t) && text.includes(rowHead(conv, t))) || turnRowIn(text, conv, t);
      }).map(t => t.index + 1) : [];
      writer.sharedTurns = writer.sharedTurnNumbers.length;
      if (writer.parts && writer.parts.sys && !visualPromptConfig) {
        try { visualPromptConfig = await request('/api/prompt-history/config'); }
        catch (_) { visualPromptConfig = {nodes: []}; }
      }
      if (token !== visualToken || tab !== 'visual') return;
      const graph = visualGraph(conv, turn, writer, visualPromptConfig || {});
      const otherRoads = list.filter(c => c.road !== 'banter');
      const conversationSelect = el('select', {onchange: e => { visualCid = e.target.value; visualTurn = ''; paintVisual(); }, 'aria-label': 'Conversation'},
        ...(visualPreview ? [el('option', {value: visualPreview.identity.conversation_id, selected: visualPreview.identity.conversation_id === cid,
          text: `Preview · ${visualPreview.subject.topic}`})] : []),
        ...(visualBanterRows.some(c => c.conversation_id === cid) || otherRoads.some(c => c.conversation_id === cid) || visualPreview && visualPreview.identity.conversation_id === cid ? []
          : [el('option', {value: cid, selected: true, text: `${(conv.identity || {}).road_kind || 'round'} · ${(conv.subject || {}).topic || cid}`})]),
        el('optgroup', {label: 'Banter rounds · roulette inside the exchange'},
          ...visualBanterRows.map(c => el('option', {value: c.conversation_id, selected: c.conversation_id === cid,
            text: `${c.topic || '(no topic)'} · ${day(c.created)}`}))),
        el('optgroup', {label: 'Separate lines and record talk'},
          ...otherRoads.map(c => el('option', {value: c.conversation_id, selected: c.conversation_id === cid,
            text: `${c.road || 'line'} · ${c.topic || '(no topic)'} · ${day(c.created)}`}))));
      const turnSelect = el('select', {onchange: e => { visualTurn = e.target.value; paintVisual(); }, 'aria-label': 'Turn'},
        ...turns.map(t => el('option', {value: t.turn_id, selected: t.turn_id === turn.turn_id,
          text: `${t.index + 1}. ${t.name || t.speaker} · ${t.step_label || 'turn'}`})));
      const canvas = el('canvas', {class: 's3-vp-canvas', 'aria-label': '3D prompt assembly graph'});
      const detail = el('div', 's3-vp-detail');
      const selected = {id: 'system'};
      const nodeSelect = el('select', {'aria-label': 'Prompt node', onchange: e => {
        const node = graph.nodes.find(n => n.id === e.target.value);
        if (node) { inspect(node); if (visualScene) visualScene.focus(node.id); }
      }}, ...graph.nodes.map(n => el('option', {value: n.id, selected: n.id === selected.id, text: n.label})));
      const phraseTools = () => {
        const phrase = el('input', {type: 'text', placeholder: 'e.g. feeding the beast', 'aria-label': 'Recurring phrase'});
        const results = el('div', 's3-vp-phrase-results');
        const trace = btn('Trace phrase', async () => {
          const q = phrase.value.trim();
          if (q.length < 2) { fill(results, para('Enter at least two characters.', 's3-muted')); return; }
          fill(results, para('Tracing saved prompts, memory, scripts and code...', 's3-muted'));
          try {
            const got = await request('/api/phrase/trace?q=' + encodeURIComponent(q));
            const capturedReviews = graph.nodes.filter(n => n.data && n.data.origin === 'review' &&
              json(n.data.captured || {}).toLowerCase().includes(q.toLowerCase()));
            fill(results, para(got.say || 'Trace complete.'),
              ...capturedReviews.map(n => el('div', 's3-vp-phrase-source',
                el('b', {text: n.data.path}),
                para('This exact review example was in the captured system message. Select its graph node to inspect or exclude it.', 's3-muted'))),
              ...((got.layers || []).filter(layer => layer.count).map(layer =>
                el('details', {open: layer.layer === 'prompts'},
                  el('summary', {text: `${layer.label}: ${layer.count} source(s)`}),
                  ...layer.sources.map(source => el('div', 's3-vp-phrase-source',
                    el('b', {text: `${source.store} · ${source.file || source.key || ''}`}),
                    para(source.snippet || '', 's3-muted')))))),
              btn(got.banned ? 'Phrase already blocked' : 'Stop this phrase from airing', async e => {
                if (got.banned) return;
                e.target.disabled = true;
                try {
                  const saved = await request('/api/phrase/ban', {method: 'POST',
                    body: JSON.stringify({phrase: q, scope: 'everywhere', reason: 'Stopped from Visual Prompt source trace'})});
                  e.target.textContent = 'Phrase blocked';
                  fill(results, para(saved.say || 'The phrase is blocked in future prompts and at air.'));
                } catch (error) { e.target.disabled = false; results.append(para('Could not block phrase: ' + (error.message || error), 's3-error')); }
              }, {disabled: !!got.banned}));
          } catch (error) { fill(results, para('Trace failed: ' + (error.message || error), 's3-error')); }
        });
        return el('details', 's3-vp-phrase-tools', el('summary', {text: 'Trace or stop a recurring phrase'}),
          el('div', 's3-row', phrase, trace), results);
      };
      const inspect = node => {
        selected.id = node.id;
        nodeSelect.value = node.id;
        const extras = [];
        if (node.kind === 'roll' || node.kind === 'decision') {
          const ev = node.data, stages = ev.stages || [];
          const reel = rollRow(ev, conv);
          extras.push(reel);
          extras.push(el('p', {text: `Recorded result: ${landedWords(ev, conv)}. ${eventLine(ev, conv).text}`}));
          for (const s of stages) {
            extras.push(el('details', {class: 's3-vp-stage', open: s.stage === 'item' || s.stage === 'dice'},
              el('summary', {text: `${s.stage}: ${s.selected || 'none'}${s.draw && s.draw.dice != null ? ' · d100 ' + s.draw.dice : ''}`}),
              (s.candidates || []).length ? el('div', 's3-vp-candidates', ...s.candidates.map(c => el('div', {class: c.id === s.selected ? 'hit' : ''},
                el('b', {text: c.label || c.id}), el('span', {text: `${pct(c.p)} · weight ${num(c.weight)}`})))) : para(s.rule || s.threshold != null ? `Threshold ${s.threshold}` : 'No candidate list recorded.', 's3-muted')));
          }
          extras.push(btn('Open this decision and its weight table', () => openDecision(conv, ev, turn, v.api)));
          setTimeout(() => { if (reel.isConnected) reel.roll(800); }, 50);
        } else if (node.id.startsWith('system-origin-')) {
          const source = node.data || {};
          extras.push(el('p', {text: `Origin: ${Array.isArray(source.path) ? source.path.join(' / ') : source.path || 'unknown'}`}));
          extras.push(el('h4', {text: 'Value in the captured request'}), readablePrompt(node.detail));
          if (source.origin === 'setting' && source.setting) {
            let was = source.setting.value;
            const area = el('textarea', {value: was, rows: 7, 'aria-label': 'Future value of ' + node.label});
            const status = para(source.setting.capturedFromDispatch
              ? 'The captured value came from the configuration saved at dispatch. Editing the current value affects future calls only.'
              : 'Changes affect future writer calls. This captured prompt stays unchanged.', 's3-muted');
            extras.push(el('h4', {text: 'Current saved value'}), area,
              btn('Save future value', async e => {
                e.target.disabled = true;
                try {
                  const got = await request('/api/prompt-history/config', {method: 'POST',
                    body: JSON.stringify({path: source.path, value: area.value, was})});
                  was = area.value; source.setting.value = was; visualPromptConfig = null;
                  status.textContent = got.say || 'Saved for future calls.';
                } catch (error) { status.textContent = 'Not saved: ' + (error.message || error); }
                e.target.disabled = false;
              }), status);
          } else if (source.origin === 'snapshot') {
            extras.push(para('This value was captured in the writer call’s dispatch snapshot. The current configuration may have changed since then.', 's3-muted'));
          } else if (source.origin === 'review' && source.review_id) {
            const reviewHost = el('div', 's3-vp-review', para('Loading the current review record...', 's3-muted'));
            extras.push(reviewHost);
            request('/api/orchestrator/rejections/' + encodeURIComponent(source.review_id)).then(review => {
              if (!reviewHost.isConnected) return;
              const decision = review.decision || {};
              const status = para('Only the operator note is editable here. The source, candidate, decision and aired effect remain recorded evidence.', 's3-muted');
              const area = el('textarea', {value: decision.note || '', rows: 5, maxLength: 320, 'aria-label': 'Operator guidance note'});
              let revision = review.revision;
              const exclude = el('input', {type: 'checkbox', checked: review.prompt_excluded === true,
                onchange: async e => {
                  const excluded = !!e.target.checked;
                  e.target.disabled = true;
                  try {
                    const got = await request('/api/orchestrator/rejections/' + encodeURIComponent(source.review_id) + '/guidance',
                      {method: 'POST', body: JSON.stringify({excluded, expected_revision: revision})});
                    revision = got.review.revision;
                    status.textContent = excluded ? 'Excluded from future prompt examples. The recorded review is retained.'
                      : 'Eligible for future prompt examples again.';
                  } catch (error) { e.target.checked = !excluded; status.textContent = 'Not saved: ' + (error.message || error); }
                  e.target.disabled = false;
                }});
              fill(reviewHost,
                el('h4', {text: 'Current database record'}),
                readablePrompt(json({review_id: review.id, gate: review.gate, kind: (review.context || {}).kind,
                  source: review.source, candidate: review.candidate, reasons: review.reasons,
                  decision: review.decision, revision: review.revision})),
                el('label', 's3-vp-edit-label', exclude, ' Exclude this review from future prompt examples'),
                el('label', 's3-vp-edit-label', 'Operator guidance note', area),
                btn('Save guidance for future prompts', async e => {
                  e.target.disabled = true;
                  try {
                    const got = await request('/api/orchestrator/rejections/' + encodeURIComponent(source.review_id) + '/guidance',
                      {method: 'POST', body: JSON.stringify({note: area.value, expected_revision: revision})});
                    revision = got.review.revision;
                    status.textContent = got.say || 'Saved for future prompts.';
                  } catch (error) { status.textContent = 'Not saved: ' + (error.message || error); }
                  e.target.disabled = false;
                }), status);
            }).catch(error => { if (reviewHost.isConnected) fill(reviewHost,
              para('Could not load source record: ' + (error.message || error), 's3-error')); });
          } else if (source.origin === 'compiled' || source.origin === 'memory') {
            extras.push(para(source.origin === 'memory'
              ? 'These notes come from the data crystal. System 3 carries its own prior state; this switch controls whether its future prompts also receive the distilled notes.'
              : 'This policy text is assembled by application code from the review examples linked below. Open a review node to edit its future guidance note.', 's3-muted'));
            const control = (visualPromptConfig && visualPromptConfig.nodes || []).find(n =>
              json(n.path) === json(source.control_path));
            if (control) {
              let was = control.value;
              const status = para('This switch controls whether future calls receive these examples.', 's3-muted');
              const box = el('input', {type: 'checkbox', checked: was === true, onchange: async e => {
                const value = !!e.target.checked;
                try {
                  const got = await request('/api/prompt-history/config', {method: 'POST',
                    body: JSON.stringify({path: control.path, value, was})});
                  was = value; control.value = value; status.textContent = got.say || 'Saved.';
                } catch (error) { e.target.checked = was; status.textContent = 'Not saved: ' + (error.message || error); }
              }});
              extras.push(el('label', 's3-vp-edit-label', box,
                source.origin === 'memory' ? ' Include distilled notes in future System 3 prompts'
                  : ' Include operator wording examples in future system prompts'), status);
            }
          } else if (source.origin === 'live-memory') {
            extras.push(para('These lines were already aired when this request was captured. New rounds receive the latest live conversation; System 3 also records its own carry between rounds.', 's3-muted'));
          } else {
            extras.push(para('The captured request contains these bytes, but its writer history does not identify a stored property for them.', 's3-muted'));
          }
        } else if (node.id === 'system' || node.id === 'prompt') {
          extras.push(readablePrompt(node.detail));
        } else if (node.id === 'assembly') {
          extras.push(readablePrompt(node.detail), block('Whole running order', (conv.plan || {}).sheet || '(none)'));
        } else if (node.id === 'model') {
          extras.push(el('p', {text: writer.why || 'No recorded call.'}), writer.row ? el('p', {text: `${writer.row.model || '?'} · ${writer.row.purpose || ''} · ${day(Number(writer.row.at || 0))}`}) : null,
            writer.sharedTurns ? el('p', {text: `This captured request carries the running-order rows for turns ${writer.sharedTurnNumbers.join(', ')}.`}) : null);
        } else if (node.id === 'reply') {
          extras.push(el('p', {text: node.detail}));
        } else if (node.data && typeof node.data === 'object') extras.push(readablePrompt(json(node.data)));
        else extras.push(el('p', {text: node.detail}));
        if (['system', 'standing', 'personas', 'prompt'].includes(node.id)) extras.push(
          btn('Edit standing instructions and personas', () => {
            const fold = shell.querySelector('.s3-pfold');
            if (fold) { fold.open = true; fold.scrollIntoView({block: 'nearest'}); }
          }));
        if (['assembly', 'prompt'].includes(node.id)) extras.push(
          btn('Edit turn instruction nodes', () => { stopExtras(); tab = 'segments'; paint(); }));
        if (['database', 'material'].includes(node.id)) extras.push(
          btn('Edit source controls', () => { stopExtras(); tab = 'controls'; paint(); }));
        if (['system', 'prompt', 'reply'].includes(node.id) || node.id.startsWith('system-origin-'))
          extras.push(phraseTools());
        fill(detail, el('h3', {text: node.label}), el('p', {class: 's3-muted', text: node.id.startsWith('system-origin-') ? 'A seed found in this captured system prompt.' : node.kind === 'roll' ? 'An actual recorded draw from this turn.' : node.kind === 'decision' ? 'A recorded decision without an RNG draw.' : node.kind === 'prompt' ? (conv.preview_call ? 'Prompt submitted to the preview writer; it may add runtime guidance and model options.' : 'Captured model request, if a writer call was found.') : 'Recorded input or output for this turn.'}), ...extras);
      };
      const confidence = conv.preview_call ? `Off-air LLM preview · ${(conv.preview_call || {}).matched_turns} of ${(conv.preview_call || {}).planned_turns} turns matched their speaker slots`
        : writer.row ? (writer.exact ? 'Writer call matched by this turn’s words' : 'Writer call inferred: ' + writer.why) : writer.why;
      const stage = el('div', 's3-vp-stage-wrap',
        el('div', 's3-vp-toolbar', nodeSelect,
          btn('Focus node', () => visualScene && visualScene.focus(selected.id)),
          btn('Fit all', () => visualScene && visualScene.fit())), canvas,
        el('div', 's3-vp-key', 'Previous knowledge + topic + previous reply → recorded draws → turn instructions → system prompt + conversation prompt → LLM → reply'));
      const visualLayout = el('div', 's3-vp-layout', stage);
      const toggleSidebar = btn('', () => {
        visualSidebarOpen = !visualSidebarOpen;
        syncSidebar();
        try { localStorage.setItem('s3.visualSidebarOpen', visualSidebarOpen ? '1' : '0'); } catch (_) { /* optional */ }
      }, {class: 's3-vp-collapse'});
      const sidebar = el('aside', 's3-vp-sidebar', toggleSidebar, detail);
      visualLayout.append(sidebar);
      const syncSidebar = () => {
        visualLayout.classList.toggle('collapsed', !visualSidebarOpen);
        sidebar.classList.toggle('collapsed', !visualSidebarOpen);
        detail.hidden = !visualSidebarOpen;
        toggleSidebar.textContent = visualSidebarOpen ? '›' : '‹';
        toggleSidebar.title = visualSidebarOpen ? 'Collapse details' : 'Show details';
        toggleSidebar.setAttribute('aria-label', toggleSidebar.title);
        toggleSidebar.setAttribute('aria-expanded', String(visualSidebarOpen));
      };
      syncSidebar();
      fill(shell,
        el('div', 's3-card', el('h2', {text: 'Visual Prompt · System 3 assembly'}),
          el('p', {class: 's3-muted', text: 'Choose a turn, then click any node. Gold nodes had recorded RNG draws; gray decisions had no roll. Drag to pan; pinch or scroll to zoom.'}),
          el('div', 's3-row', conversationSelect, turnSelect),
          el('p', {class: 's3-vp-evidence', text: confidence || 'No writer call recorded for this round.'})),
        visualLayout,
        el('div', 's3-card', el('h3', {text: 'Change what future prompts receive'}),
          el('div', 's3-row',
            btn('Edit node order', () => { stopExtras(); tab = 'segments'; paint(); }),
            btn('Edit Rolodex weights', () => { stopExtras(); tab = 'tables'; paint(); }),
            btn('Edit controls and sources', () => { stopExtras(); tab = 'controls'; paint(); }),
            btn('Preview updated dialogue', async e => {
              e.target.disabled = true;
              try {
                const next = await send('/api/system3/preview', 'POST', {
                  conversation_id: conv.preview_source || cid});
                visualPreview = next; visualCid = next.identity.conversation_id; visualTurn = '';
                visualCalls.clear(); paintVisual();
              } catch (err) { report(err); e.target.disabled = false; }
            }, {disabled: (conv.identity || {}).road_kind !== 'banter',
              title: 'Dialogue preview currently supports banter rounds.'})),
          para('Preview replans this banter round with the saved settings, then asks the station writer for a fresh draft. The draft stays off air.', 's3-muted'),
          promptFold(request, {writerByTurn: new Map([[turn.turn_id, writer]]), callCache: new Map()}, conv, turn)));
      inspect(graph.nodes.find(n => n.id === selected.id));
      try { const THREE = await threeLoad(); if (token === visualToken && canvas.isConnected) visualScene = visualThree(THREE, canvas, graph, inspect); }
      catch (e) { fill(canvas.parentElement, para('3D view unavailable: ' + e.message, 's3-error'),
        el('div', 's3-vp-fallback', ...graph.nodes.map(n => btn(n.label, () => inspect(n))))); }
    } catch (e) { if (token === visualToken) fill(body, para('Visual prompt could not load: ' + e.message, 's3-error')); }
  }

  /* ---------------- Sys3: the circuit, in three.js -------------------------- */
  let sys3 = null;
  function threeLoad() {
    if (window.THREE) return Promise.resolve(window.THREE);
    if (threeLoad.p) return threeLoad.p;
    const src = (typeof window.pineThreeUrl === 'function') ? window.pineThreeUrl() : '/vendor/three.min.js';
    threeLoad.p = new Promise((res, rej) => { const sc = document.createElement('script'); sc.src = src; sc.onload = () => res(window.THREE);
      sc.onerror = () => { threeLoad.p = null; rej(new Error('three.js did not load from ' + src)); }; document.head.append(sc); });
    return threeLoad.p;
  }
  /* [s3-scene-nav] THE SCENE YOU CAN WALK AROUND, AND ASK.
     "Allow me to pinch and pull and to navigate around this scene." "I want to
     tap on bubbles and elements in this in order to bring up a sidebar that
     brings up details on that element and allowing me to inspect each element
     in depth and make edits to it." (the operator, 2026-09-29)
     Navigation is our own small orbit rig on pointer events (no OrbitControls
     is vendored): one finger / left-drag ORBITS; two fingers PAN and PINCH
     zoom about their midpoint; right-drag, middle-drag, shift-drag and
     space-drag pan on the desk; the wheel zooms about the pointer; a
     double-tap, the frame button or 0 frames everything. The camera eases
     toward where the hand put it (damping) inside a fixed box and a zoom
     range, so it cannot fly off. touch-action is none on the canvas ONLY, so
     the page never scrolls under a gesture; the canvas carries pine-gestures
     so a corner swipe that starts on it is never a hot corner.
     A TAP (not a drag) picks the element under it - System 3, a road, a
     room, a packet, a paper airplane - rings it and opens the inspector
     docked in the pane. Edits go through the existing System 3 doors only
     (PUT /api/system3/tables/{id}, PUT /api/system3/config/section/{name},
     POST /api/system3/settings for the register's roads); each shows what it
     will change, waits for Confirm, reports the live config hash, and Undo
     writes the previous version's part back (GET /api/system3/config?hash=). */
  async function paintSys3() {
    const host = el('div', 's3-sys3');
    const canvas = el('canvas', {class: 'pine-gestures', tabindex: '0', role: 'application',
      'aria-label': 'System 3 scene. Drag to orbit; two fingers, right-drag or space-drag to pan; pinch or wheel to zoom; double-tap or 0 to frame all; tap an element to inspect it.'});
    host.append(canvas);
    const nowNode = el('div', 's3-sys3-now', 'waiting for the line on air...');
    host.append(nowNode, el('div', 's3-sys3-legend', el('span', {text: 'centre: System 3'}), el('span', {text: 'ring: the roads (lit = directed by System 3)'}),
      el('span', {text: 'right: the writer, the recording room, the ledger, the air'}), el('span', {text: 'paper airplanes: decisions landing; packets: the circuits'}),
      el('span', {class: 's3-sys3-hint', text: 'drag: orbit · two fingers / right-drag / space-drag: pan · pinch / wheel: zoom · double-tap: frame all · tap: inspect'})));
    fill(body, el('div', 's3-card', el('h2', {text: 'Sys3 - System 3 and the systems it directs, live'}), host));
    if (sys3) { sys3.stop(); sys3 = null; }
    let THREE; try { THREE = await threeLoad(); } catch (e) { report(e); return; }
    if (tab !== 'sys3' || !canvas.isConnected) return;
    sys3 = sys3Scene(THREE, canvas, nowNode, host);
  }
  function sys3Scene(THREE, canvas, nowNode, host) {
    const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
    camera.position.set(0, 9, 22); camera.lookAt(0, 0, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const light = new THREE.PointLight(0xffffff, 1.0); light.position.set(6, 12, 10); scene.add(light);
    const colour = css => { const name = String(css).replace(/^var\(|\)$/g, ''); const got = getComputedStyle(root).getPropertyValue(name).trim(); return new THREE.Color(got || '#8ac6ac'); };
    const label = (text, p, dy, opacity) => { const c = document.createElement('canvas'); c.width = 256; c.height = 48; const cx = c.getContext('2d');
      cx.fillStyle = '#dfe6e4'; cx.font = '600 22px sans-serif'; cx.textAlign = 'center'; cx.fillText(text, 128, 32);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, opacity})); sp.scale.set(2.8, 0.52, 1); sp.position.copy(p).add(new THREE.Vector3(0, dy, 0)); scene.add(sp); };
    const roads = (status && status.roads) || []; const n = Math.max(1, roads.length); const R = 8;
    const nodes = new Map(); const pickables = [];
    const pickable = (m, kind, radius, data) => { m.userData = Object.assign(m.userData || {}, {kind}, data || {}); pickables.push({m, kind, radius}); return m; };
    const core = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.6, 1.6), new THREE.MeshStandardMaterial({color: 0x8ac6ac, emissive: 0x1f3a33})); scene.add(core); nodes.set('system3', core);
    pickable(core, 'system3', 1.15, {id: 'system3'});
    const lineMat = (c, o) => new THREE.LineBasicMaterial({color: c, transparent: true, opacity: o});
    const circuits = [];
    roads.forEach((r, i) => { const a = (i / n) * Math.PI * 2; const p = new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R * 0.55);
      const on = r.mode === 'active';
      const m = new THREE.Mesh(new THREE.SphereGeometry(on ? 0.42 : 0.3, 16, 12), new THREE.MeshStandardMaterial({color: on ? 0x54d18b : 0x35414c, emissive: on ? 0x10331f : 0x000000}));
      m.position.copy(p); m.userData = {road: r.id, on}; scene.add(m); nodes.set(r.id, m); pickable(m, 'road', on ? 0.5 : 0.4, {id: r.id});
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), p]), lineMat(on ? 0x54d18b : 0x35414c, on ? 0.45 : 0.15)));
      circuits.push({from: new THREE.Vector3(0, 0, 0), to: p, phase: Math.random(), speed: 0.12 + Math.random() * 0.1, on, a: 'system3', b: r.id});
      label(r.id, p, -0.8, on ? 0.95 : 0.5); });
    const rooms = [['writer', 'the writer', 0xf0a6ca], ['voice', 'recording room', 0x87bfff], ['ledger', 'script ledger', 0xe7bf78], ['air', 'on air', 0x7fe0d6]];
    let prevRoom = null, prevId = 'system3';
    rooms.forEach(([id, text, col], i) => { const p = new THREE.Vector3(R + 4.5, 3.4 - i * 2.2, -2 + i * 0.4);
      const m = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.7, 0.7), new THREE.MeshStandardMaterial({color: col})); m.position.copy(p); scene.add(m); nodes.set(id, m);
      pickable(m, 'room', 0.7, {id, text});
      label(text, p, -0.75, 0.95);
      const from = prevRoom ? prevRoom.position.clone() : new THREE.Vector3(0, 0, 0);
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, p]), lineMat(col, 0.5)));
      circuits.push({from, to: p, phase: Math.random(), speed: 0.2, on: true, a: prevId, b: id}); prevRoom = m; prevId = id; });
    const packets = circuits.map((c, i) => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 6), new THREE.MeshBasicMaterial({color: 0xffffff})); m.visible = c.on; scene.add(m);
      pickable(m, 'packet', 0.16, {circuit: i}); return m; });
    const planes = []; const planeGeo = new THREE.ConeGeometry(0.22, 0.7, 4);
    const roadOf = new Map(); let cursor = 0, alive = true, raf = 0, lastText = '', thumbSprite = null;
    const ring = [], aired = [];                  /* what this scene saw land: the rooms' recent items */
    const fly = (target, col, ev, road) => { const m = new THREE.Mesh(planeGeo, new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.95})); m.position.set(0, 0.9, 0); scene.add(m);
      pickable(m, 'plane', 0.4, {event: ev, road});
      planes.push({m, to: target.position.clone().add(new THREE.Vector3(0, 0.6, 0)), t: 0}); if (planes.length > 40) { const old = planes.shift(); scene.remove(old.m); } };
    const thumb = (text, dice) => { if (thumbSprite) { scene.remove(thumbSprite); thumbSprite = null; } if (!text) return;
      const c = document.createElement('canvas'); c.width = 512; c.height = 128; const cx = c.getContext('2d');
      cx.fillStyle = '#0b1215ee'; cx.fillRect(0, 0, 512, 128); cx.strokeStyle = '#8ac6ac'; cx.strokeRect(1, 1, 510, 126);
      cx.fillStyle = '#dfe6e4'; cx.font = '20px sans-serif'; let line = '', y = 34;
      for (const w of text.split(' ')) { if (cx.measureText(line + ' ' + w).width > 480) { cx.fillText(line, 16, y); line = w; y += 26; if (y > 86) break; } else line = line ? line + ' ' + w : w; }
      if (y <= 86) cx.fillText(line, 16, y);
      (dice || []).slice(0, 16).forEach((d, i) => { cx.fillStyle = '#87bfff'; const h = Math.max(3, (Number(d) || 0) / 100 * 28); cx.fillRect(16 + i * 30, 120 - h, 22, h); });
      thumbSprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true})); thumbSprite.scale.set(8, 2, 1); thumbSprite.position.set(0, 4.2, 0); scene.add(thumbSprite); };
    async function poll() {
      if (!alive) return;
      try {
        /* the live edge only: a first read from 0 walked the whole ledger from its oldest event */
        if (!cursor) { const head = await request('/api/system3/events?after=0&limit=1'); cursor = Number(head.head || head.cursor || 0); }
        const feed = await request('/api/system3/events?after=' + cursor + '&limit=60');
        if(!alive)return;
        for (const e of (feed.events || [])) {
          let road = e.round || roadOf.get(e.conversation_id);
          if (road === undefined) { try { const c = await request('/api/system3/conversation/' + encodeURIComponent(e.conversation_id)); road = (c.identity || {}).road_kind || ''; } catch (_) { road = ''; } roadOf.set(e.conversation_id, road); }
          if(!alive)return;
          ring.push(Object.assign({}, e, {road})); if (ring.length > 200) ring.shift();
          fly(nodes.get(road) || nodes.get('writer'), e.kind === 'observation' ? 0x7fe0d6 : colour(FAM[e.family] || 'var(--obs)').getHex(), e, road);
        }
        cursor = Number(feed.cursor || feed.head || cursor);
        const live = await request('/api/system3/now'); const s3 = live && live.system3; const line = live && live.line;
        const text = line ? `${line.name || line.who || ''}: ${line.text || ''}` : '';
        if (text !== lastText) { lastText = text; thumb(text ? text.slice(0, 220) : '', s3 && s3.turn ? (s3.turn.rolls || []).map(r => r.dice).filter(x => x != null) : []);
          if (text) { aired.push({at: Date.now() / 1000, text, line, road: s3 ? s3.road : ''}); if (aired.length > 30) aired.shift(); }
          nowNode.textContent = text ? (s3 ? `${s3.road} round · turn ${(s3.turn || {}).turn || '?'} of ${s3.turns} · ` : 'not directed by System 3 · ') + text.slice(0, 160) : 'nothing on air'; }
        nodes.forEach((m, id) => { if (m.userData && m.userData.road) m.material.emissive.setHex(s3 && s3.road === id && text ? 0x2a6b3f : (m.userData.on ? 0x10331f : 0x000000)); });
      } catch (e) { /* the scene keeps turning */ }
      if (alive) setTimeout(poll, 2000);
    }

    /* ---- the camera rig: goal (where the hand put it) and cur (eased toward it) ---- */
    const V = (x, y, z) => new THREE.Vector3(x, y, z);
    const LIM = {rMin: 3.5, rMax: 70, phiMin: 0.12, phiMax: 2.3, box: new THREE.Box3(V(-20, -10, -18), V(26, 12, 18))};
    const goal = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2}, cur = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2};
    let home = {target: V(0, 0.5, 0), r: 23.6, theta: 0, phi: 1.2}, drift = true;
    const clampGoal = () => { goal.r = Math.min(LIM.rMax, Math.max(LIM.rMin, goal.r)); goal.phi = Math.min(LIM.phiMax, Math.max(LIM.phiMin, goal.phi)); LIM.box.clampPoint(goal.target, goal.target); };
    const place = st => { const s = Math.sin(st.phi); camera.position.set(st.target.x + st.r * s * Math.sin(st.theta), st.target.y + st.r * Math.cos(st.phi), st.target.z + st.r * s * Math.cos(st.theta)); camera.lookAt(st.target); camera.updateMatrixWorld(); };
    const hand = () => { drift = false; };
    function frameAll(snap) {                     /* double-tap, 0, the frame button: everything in view */
      const box = new THREE.Box3(); const tmp = V(0, 0, 0);
      pickables.forEach(it => { if (it.kind === 'system3' || it.kind === 'road' || it.kind === 'room') box.expandByPoint(it.m.getWorldPosition(tmp)); });
      box.expandByPoint(V(0, 4.8, 0)); box.expandByPoint(V(0, -1.2, 0));
      const sz = box.getSize(V(0, 0, 0)), mid = box.getCenter(V(0, 0, 0));
      const vf = camera.fov * Math.PI / 180; const hf = 2 * Math.atan(Math.tan(vf / 2) * Math.max(0.2, camera.aspect));
      const fit = Math.max((sz.y / 2 + 1.2) / Math.tan(vf / 2), (sz.x / 2 + 1.6) / Math.tan(hf / 2)) + sz.z / 2;
      home = {target: mid, r: Math.min(LIM.rMax, Math.max(8, fit)), theta: 0, phi: 1.2};
      goal.target.copy(home.target); goal.r = home.r; goal.theta = 0; goal.phi = home.phi; clampGoal(); drift = true;
      if (snap) { cur.target.copy(goal.target); cur.r = goal.r; cur.theta = goal.theta; cur.phi = goal.phi; }
    }
    const pos = e => { const r = canvas.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
    const raycaster = new THREE.Raycaster();
    function panPx(dx, dy) {
      const h = canvas.clientHeight || 400; const per = 2 * goal.r * Math.tan(camera.fov * Math.PI / 360) / h;
      const right = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 0), up = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 1);
      goal.target.addScaledVector(right, -dx * per).addScaledVector(up, dy * per); clampGoal(); hand();
    }
    function zoomAt(s, p) {                       /* about the pointer: o1 = p - (p - o0) * s */
      const r1 = Math.min(LIM.rMax, Math.max(LIM.rMin, goal.r * s)); const k = r1 / goal.r;
      if (p && canvas.clientWidth) {
        raycaster.setFromCamera(new THREE.Vector2(p.x / canvas.clientWidth * 2 - 1, -(p.y / canvas.clientHeight) * 2 + 1), camera);
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(V(0, 0, 0)), goal.target);
        const hit = raycaster.ray.intersectPlane(plane, V(0, 0, 0));
        if (hit) goal.target.sub(hit).multiplyScalar(k).add(hit);
      }
      goal.r = r1; clampGoal(); hand();
    }
    /* ---- picking: nearest element on screen, relative to its projected size plus a finger's slop ---- */
    function pickAt(p, touch) {
      const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1; const f = h / 2 / Math.tan(camera.fov * Math.PI / 360);
      const wp = V(0, 0, 0); let best = null;
      for (const it of pickables) {
        if (!it.m.visible || !it.m.parent) continue;
        it.m.getWorldPosition(wp); const dist = camera.position.distanceTo(wp); const q = wp.clone().project(camera);
        if (q.z > 1 || q.z < -1) continue;
        const sx = (q.x + 1) / 2 * w, sy = (1 - q.y) / 2 * h; const pr = it.radius * f / Math.max(0.01, dist);
        const reach = pr + (touch ? 22 : 8); const d = Math.hypot(sx - p.x, sy - p.y);
        if (d > reach) continue;
        const score = d / reach;                  /* a packet tapped dead-on beats the sphere it passes */
        if (!best || score < best.score - 0.02 || (Math.abs(score - best.score) <= 0.02 && dist < best.dist)) best = {it, score, dist};
      }
      return best ? best.it : null;
    }
    const halo = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const cx = c.getContext('2d');
      cx.strokeStyle = '#ffd36b'; cx.lineWidth = 9; cx.beginPath(); cx.arc(64, 64, 52, 0, Math.PI * 2); cx.stroke();
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, depthTest: false})); sp.visible = false; sp.renderOrder = 9; scene.add(sp); return sp; })();
    let sel = null;
    /* ---- the hand ---- */
    const ptrs = new Map(); let mode = '', tapC = null, lastTap = null, multi = false, space = false, over = false, hoverAt = 0;
    const editable = t => !!(t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '')));
    function onDown(e) {
      if (e.pointerType === 'mouse' && e.button > 2) return;
      e.preventDefault(); e.stopPropagation();
      try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* old engine */ }
      try { canvas.focus({preventScroll: true}); } catch (_) { /* old engine */ }
      const p = pos(e); ptrs.set(e.pointerId, p);
      if (ptrs.size === 1) {
        multi = false;
        mode = (e.pointerType === 'mouse' && (e.button === 1 || e.button === 2 || space || e.shiftKey)) ? 'pan' : 'orbit';
        tapC = (e.pointerType !== 'mouse' || e.button === 0) && !space ? {id: e.pointerId, x: p.x, y: p.y, t: performance.now(), touch: e.pointerType !== 'mouse'} : null;
      } else { multi = true; tapC = null; mode = 'pinch'; }
      canvas.classList.toggle('s3-grabbing', mode !== 'orbit' || e.pointerType === 'mouse');
    }
    function onMove(e) {
      const p = pos(e);
      if (!ptrs.has(e.pointerId)) {
        if (e.pointerType === 'mouse' && performance.now() - hoverAt > 60) { hoverAt = performance.now(); canvas.style.cursor = space ? 'grab' : pickAt(p, false) ? 'pointer' : 'grab'; }
        return;
      }
      e.preventDefault(); e.stopPropagation();
      const was = ptrs.get(e.pointerId);
      if (tapC && tapC.id === e.pointerId) {
        if (Math.hypot(p.x - tapC.x, p.y - tapC.y) <= (tapC.touch ? 10 : 5)) return;   /* still a tap: the camera holds */
        tapC = null;
      }
      if (mode === 'pinch' && ptrs.size >= 2) {
        const other = [...ptrs.entries()].find(([id]) => id !== e.pointerId)[1];
        const d0 = Math.hypot(was.x - other.x, was.y - other.y), d1 = Math.hypot(p.x - other.x, p.y - other.y);
        const m0 = {x: (was.x + other.x) / 2, y: (was.y + other.y) / 2}, m1 = {x: (p.x + other.x) / 2, y: (p.y + other.y) / 2};
        if (d0 > 2 && d1 > 2) zoomAt(d0 / d1, m1);
        panPx(m1.x - m0.x, m1.y - m0.y);
      } else if (ptrs.size === 1) {
        const dx = p.x - was.x, dy = p.y - was.y; const h = canvas.clientHeight || 400;
        if (mode === 'pan') panPx(dx, dy);
        else { goal.theta -= 2 * Math.PI * dx / h * 0.7; goal.phi -= 2 * Math.PI * dy / h * 0.7; clampGoal(); hand(); }
      }
      ptrs.set(e.pointerId, p);
    }
    function onUp(e) {
      if (!ptrs.has(e.pointerId)) return;
      e.stopPropagation();
      ptrs.delete(e.pointerId);
      try { canvas.releasePointerCapture(e.pointerId); } catch (_) { /* gone */ }
      if (e.type === 'pointerup' && tapC && tapC.id === e.pointerId && !multi && performance.now() - tapC.t < 700) onTap(pos(e), tapC.touch);
      tapC = null;
      mode = ptrs.size === 1 ? 'orbit' : ptrs.size ? mode : '';
      if (!ptrs.size) canvas.classList.remove('s3-grabbing');
    }
    function onTap(p, touch) {
      const now = performance.now();
      if (lastTap && now - lastTap.t < 360 && Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 30) { lastTap = null; frameAll(); return; }
      lastTap = {t: now, x: p.x, y: p.y};
      const it = pickAt(p, touch);
      if (it) select(it);
    }
    const onWheel = e => { e.preventDefault(); e.stopPropagation(); const d = e.deltaY * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1); zoomAt(Math.exp(Math.max(-300, Math.min(300, d)) * 0.0015), pos(e)); };
    const noMenu = e => e.preventDefault();
    const stopTouch = e => { e.preventDefault(); e.stopPropagation(); };   /* an old WebView still scrolls on touch without this */
    const onKey = e => {
      if (e.key === 'Escape' && !side.hidden) { e.preventDefault(); e.stopPropagation(); closeSide(); return; }
      if (editable(e.target) || !(over || document.activeElement === canvas)) return;
      if (e.key === ' ') { e.preventDefault(); if (!space) { space = true; canvas.style.cursor = 'grab'; } }
      else if (e.key === '0' || e.key === 'f' || e.key === 'F') { e.preventDefault(); frameAll(); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(0.8, null); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAt(1.25, null); }
    };
    const onKeyUp = e => { if (e.key === ' ') space = false; };
    const onBlur = () => { space = false; };
    const onOver = () => { over = true; }, onOut = () => { over = false; };
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('lostpointercapture', onUp);
    canvas.addEventListener('wheel', onWheel, {passive: false});
    canvas.addEventListener('contextmenu', noMenu);
    canvas.addEventListener('touchstart', stopTouch, {passive: false});
    canvas.addEventListener('touchmove', stopTouch, {passive: false});
    canvas.addEventListener('pointerenter', onOver); canvas.addEventListener('pointerleave', onOut);
    window.addEventListener('keydown', onKey, true);          /* window capture: before any document-level Escape */
    window.addEventListener('keyup', onKeyUp, true);
    window.addEventListener('blur', onBlur);
    const frameBtn = el('button', {type: 'button', class: 's3-sys3-frame', title: 'Frame all (double-tap, or 0)', 'aria-label': 'Frame all',
      onclick: () => frameAll()});
    { const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:maximize') : ''; if (svg) frameBtn.innerHTML = svg; else frameBtn.textContent = 'Frame'; }
    host.append(frameBtn);

    /* ---- the inspector, docked in the pane ---- */
    const sideKind = el('span', 's3-pill'), sideTitle = el('h3'), sideNote = el('div', 's3-sys3-snote'), sideBody = el('div', 's3-sys3-sbody');
    const xBtn = el('button', {type: 'button', class: 's3-sys3-x', title: 'Close the inspector (Esc)', 'aria-label': 'Close the inspector', onclick: () => closeSide()});
    { const svg = typeof window.pineIcon === 'function' ? window.pineIcon('c:close--filled') : ''; if (svg) xBtn.innerHTML = svg; else xBtn.textContent = '×'; }
    const side = el('aside', {class: 's3-sys3-side', role: 'complementary', 'aria-label': 'Inspector'},
      el('header', 's3-sys3-shead', sideKind, sideTitle, xBtn), sideNote, sideBody);
    side.hidden = true;
    host.append(side);
    const offBack = window.PineDismiss && typeof window.PineDismiss.onBack === 'function'
      ? window.PineDismiss.onBack(() => (side.hidden || !side.isConnected ? null : {node: side, close: closeSide})) : null;
    let insp = 0;
    /* the inspector spans only the part of the scene on the glass: in a short pane the scene's
       foot can sit below the fold, and a sidebar reaching down there would hide its own buttons */
    const fitSide = () => { if (side.hidden) return; const r = host.getBoundingClientRect(); const vh = window.innerHeight || r.bottom;
      side.style.top = Math.max(0, Math.round(-r.top)) + 'px'; side.style.bottom = Math.max(0, Math.round(r.bottom - vh)) + 'px'; };
    window.addEventListener('scroll', fitSide, true); window.addEventListener('resize', fitSide);
    function closeSide() {
      side.hidden = true; host.classList.remove('s3-side-open'); sel = null; halo.visible = false; insp += 1;
      try { canvas.focus({preventScroll: true}); } catch (_) { /* gone */ }
    }
    function select(it, keepNote) {
      sel = it; halo.visible = true;
      side.hidden = false; host.classList.add('s3-side-open'); fitSide(); if (!keepNote) fill(sideNote);
      const d = it.m.userData || {};
      const token = ++insp;
      const put2 = (kind, title, ...kids) => { if (token !== insp) return; sideKind.textContent = kind; sideTitle.textContent = title; fill(sideBody, ...kids); };
      const later = (node, fn) => { Promise.resolve().then(fn).then(kids => { if (token === insp && node.isConnected) fill(node, ...[].concat(kids || [])); },
        e => { if (token === insp && node.isConnected) fill(node, para('Could not read: ' + (e && e.message || e), 's3-error')); }); return node; };
      if (it.kind === 'road') put2('road', d.id, ...roadView(d.id, later));
      else if (it.kind === 'system3') put2('System 3', 'the conversation director', ...coreView(later));
      else if (it.kind === 'room') put2('room', d.text || d.id, ...roomView(d.id, later));
      else if (it.kind === 'packet') put2('packet', 'a circuit', ...packetView(circuits[d.circuit] || {}, later));
      else if (it.kind === 'plane') put2('paper airplane', 'a decision landing', ...planeView(d.event || {}, d.road || '', later));
    }
    /* the inspector's parts */
    const sec = (title, ...kids) => el('section', 's3-sys3-sec', el('h4', {text: title}), ...kids);
    const kv = pairs => el('table', 's3-sys3-kv', el('tbody', null, ...pairs.filter(p => p && p[1] != null && p[1] !== '').map(([k, v]) =>
      el('tr', null, el('th', {text: k}), el('td', null, v && v.nodeType ? v : String(v))))));
    const wait = () => el('p', {class: 's3-muted', text: 'reading...'});
    const fold = (title, value) => el('details', 's3-sys3-fold', el('summary', {text: title}), el('pre', {text: json(value)}));
    const goTab = (id, prep) => { try { if (prep) prep(); } catch (_) { /* the tab opens anyway */ } stopExtras(); tab = id; paint(); };
    const link = (text, fn, title) => btn(text, fn, {class: 's3-sys3-link', title: title || text});
    const cfgNow = () => (config && config.config) || {};
    const liveHash = () => (config && config.hash) || (status && status.config_hash) || '';
    const PREFIX = {caller: ['call'], ad: ['ad', 'ads'], ad_spot: ['ad', 'ads'], manager: ['manager', 'upstairs'], upstairs: ['upstairs', 'manager'],
      banter: ['banter', 'host', 'seat', 'heat'], h3_speak: ['h3'], station_id: ['station', 'dj.station_ids'], interject: ['dj.interject_phrases'],
      request: ['dj.request_phrases'], open: ['dj.open_phrases'], open_show: ['dj.intro_phrases'], sfxguy: ['sfxguy'], track_talk: ['records']};
    const prefixes = id => [id].concat(PREFIX[id] || []);
    const underPrefix = (cid, id) => prefixes(id).some(p => cid === p || cid.startsWith(p + '.'));
    let listsCache = null;
    const listsOf = () => (listsCache ||= request('/api/system3/lists').then(g => (g && g.lists) || [], () => []));
    let segCache = null;
    const segmentsOf = () => { if (!segCache || Date.now() - segCache.at > 30000) segCache = {at: Date.now(), p: request('/api/system3/segments?limit=40')}; return segCache.p; };

    /* EDITS: what will change -> Confirm -> saved (hash) -> Undo (the previous version's part) */
    function flatDiff(a, b, path, out) {
      if (out.length > 60) return out;
      if (a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b)) {
        const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
        keys.forEach(k => flatDiff(a[k], b[k], path ? path + '.' + k : k, out));
      } else if (JSON.stringify(a) !== JSON.stringify(b)) out.push([path || '(all)', a, b]);
      return out;
    }
    const show = v => v === undefined ? '(none)' : typeof v === 'object' ? JSON.stringify(v).slice(0, 80) : String(v);
    function propose({title, changes, apply, undo, after}) {
      if (!changes.length) { fill(sideNote, el('div', 's3-sys3-edit', para('Nothing changed - nothing to save.', 's3-muted'))); return; }
      const card = el('div', {class: 's3-sys3-edit', role: 'alertdialog', 'aria-label': 'Confirm the edit'},
        el('b', {text: title}), el('p', {class: 's3-muted', text: 'This will change:'}),
        el('ul', null, ...changes.slice(0, 40).map(([k, a, b]) => el('li', null, el('code', {text: k}), ' ', show(a), ' -> ', el('b', {text: show(b)})))),
        changes.length > 40 ? para('... and ' + (changes.length - 40) + ' more', 's3-muted') : null);
      const was = liveHash();
      const confirmB = btn('Confirm', async () => {
        confirmB.disabled = true; cancelB.disabled = true;
        try {
          const res = await apply();
          const h = (res && res.hash) || '';
          try { await loadConfig(); await refreshStatus(); } catch (_) { /* the save stands */ }
          saved(title, res);
          const undoB = btn('Undo', async () => {
            undoB.disabled = true;
            try {
              const back = await undo(was);
              try { await loadConfig(); await refreshStatus(); } catch (_) { /* the undo stands */ }
              fill(card, el('b', {text: 'Undone: ' + title}), para('Put back as it was' + (back && back.hash ? ' - live config ' + back.hash : '') + (was ? ' (the version before was ' + was + ').' : '.'), 's3-ok'));
              if (after) after();
            } catch (e) { undoB.disabled = false; card.append(para('Undo failed: ' + e.message, 's3-error')); }
          }, {class: 's3-sys3-undo', title: 'Write the previous version back'});
          fill(card, el('b', {text: 'Saved: ' + title}),
            para(h ? 'Live config ' + h + (was ? ' (was ' + was + ')' : '') + '. The desk uses it from the next round.' : 'Saved (settings are not part of the config; config stays ' + (liveHash() || '?') + ').', 's3-ok'),
            el('div', 's3-row', undoB));
          if (after) after();
        } catch (e) { confirmB.disabled = false; cancelB.disabled = false; card.append(para('Not saved: ' + e.message, 's3-error')); }
      }, {class: 's3-sys3-confirm'});
      const cancelB = btn('Cancel', () => fill(sideNote), {class: 's3-sys3-cancel'});
      card.append(el('div', 's3-row', confirmB, cancelB));
      fill(sideNote, card);
      try { side.scrollTop = 0; } catch (_) { /* fine */ }
    }
    const prevPart = async (was, pick) => { if (!was) throw new Error('no previous version is known'); const got = await request('/api/system3/config?hash=' + encodeURIComponent(was)); return pick(got.config || {}); };
    function tableEditor(t, onlyCats) {                 /* weight, on/off, category weights (and a pool's options) */
      const d = JSON.parse(JSON.stringify(t));
      const cats = (d.categories || []).filter(c => !onlyCats || onlyCats(c.id));
      const numIn = (obj, key, step) => el('input', {type: 'number', min: 0, step: step || 0.1, value: obj[key] == null ? '' : obj[key], class: 's3-sys3-num',
        'aria-label': key, oninput: e => { obj[key] = e.target.value === '' ? obj[key] : +e.target.value; }});
      const catRow = c => {
        const items = (c.items || []).slice(0, 30).map(it => el('li', null, el('label', 's3-row',
          el('input', {type: 'checkbox', checked: it.enabled !== false, 'aria-label': 'on: ' + (it.label || it.id), onchange: e => { it.enabled = e.target.checked; }}),
          el('span', {text: it.label || it.id}), 'odds' in it ? numIn(it, 'odds', 0.05) : ('weight' in it ? numIn(it, 'weight') : null))));
        return el('li', {class: 's3-sys3-cat', 'data-cat': c.id}, el('div', 's3-row', el('span', {text: c.label || c.id}),
          'odds' in c ? numIn(c, 'odds', 0.05) : numIn(c, 'weight')),
          items.length ? el('details', null, el('summary', {text: (c.items || []).length + ' options'}), el('ul', null, ...items)) : null);
      };
      const review = btn('Review the change', () => propose({
        title: 'table ' + t.id, changes: flatDiff(t, d, '', []),
        apply: () => send('/api/system3/tables/' + encodeURIComponent(t.id), 'PUT', d),
        undo: async was => { const old = await prevPart(was, c => (c.tables || []).find(x => x.id === t.id)); if (!old) throw new Error('table ' + t.id + ' was not in ' + was); return send('/api/system3/tables/' + encodeURIComponent(t.id), 'PUT', old); },
        after: () => { if (sel) select(sel, true); }}), {class: 's3-sys3-review', title: 'See what will change before it is saved'});
      return el('details', {class: 's3-sys3-table', 'data-table': t.id},
        el('summary', null, el('b', {text: t.id}), ' ', el('span', {class: 's3-muted', text: (t.family || '') + ' · v' + (t.version || 1) + (t.enabled === false ? ' · off' : '')})),
        el('p', {class: 's3-muted', text: t.label || t.description || ''}),
        el('div', 's3-row', el('label', 's3-row', el('input', {type: 'checkbox', checked: d.enabled !== false, 'aria-label': 'table on', onchange: e => { d.enabled = e.target.checked; }}), 'on'),
          el('span', {text: 'weight'}), numIn(d, 'weight')),
        cats.length ? el('ul', 's3-sys3-cats', ...cats.map(catRow)) : para('No categories here.', 's3-muted'),
        el('div', 's3-row', review, link('Open in Tables', () => goTab('tables', () => { listId = ''; tableId = t.id; draft = null; }), 'Open this table in the Tables tab')));
    }

    function roadView(id, later) {
      const r = ((status && status.roads) || []).find(x => x.id === id) || {id};
      const c = cfgNow(); const st = id === 'banter' ? c.structure : (c.structures || {})[id];
      const legList = st ? (st.legs || st.steps || []) : [];
      const fams = new Set(), named = new Set();
      legList.forEach(l => (l.draws || []).forEach(dr => { if (dr.family) fams.add(dr.family); (dr.tables || []).forEach(x => named.add(x)); }));
      const tbls = (c.tables || []).filter(t => named.has(t.id) || fams.has(t.family) || (t.roads || []).includes(id));
      const pools = (c.tables || []).filter(t => (t.family === 'POOL' || t.family === 'CHANCE') && (t.categories || []).some(k => underPrefix(k.id, id)));
      const sset = settings && settings.settings; const canToggle = !!(sset && (settings.roads || []).includes(id));
      const inList = !!(sset && (sset.roads || []).includes(id));
      const toggle = canToggle ? btn(inList ? 'Stand this road aside' : 'Direct this road', () => {
        const before = (sset.roads || []).slice(); const next = inList ? before.filter(x => x !== id) : before.concat([id]);
        propose({title: 'register: ' + id + (inList ? ' stands aside' : ' directed'), changes: [['settings.roads', before, next]],
          apply: async () => { const res = await send('/api/system3/settings', 'POST', {roads: next}); settings.settings = res.settings; return res; },
          undo: async () => { const res = await send('/api/system3/settings', 'POST', {roads: before}); settings.settings = res.settings; return res; },
          after: () => { if (sel) select(sel, true); }});
      }, {class: 's3-sys3-toggle', title: 'The selected-roads list the "active on selected roads" mode directs'}) : null;
      return [
        sec('Register',
          kv([['label', r.label], ['id', r.id], ['shape', r.shape], ['mode', el('span', {class: 's3-pill ' + (r.mode === 'active' ? 'active' : r.mode === 'shadow' ? 'shadow' : 'off'), text: r.mode || '?'})],
            ['directed', r.mode === 'active' ? 'yes - directed by System 3' : (r.label_air || 'no')], ['what', r.what], ['writer', r.writer], ['hook', r.hook], ['structure', r.structure],
            ['selected list', sset ? (inList ? 'in it' : 'not in it') + (sset.mode !== 'active_selected_roads' ? ' (mode is ' + sset.mode + '; the list decides only in active on selected roads)' : '') : '']]),
          el('div', 's3-row', toggle, link('Segments editor', () => goTab('segments', () => { if (!segNodes || segRoadOf !== id) { segNodes = null; segLoad(id); } segRoad = id; segSel = {node: -1, draw: -1}; }), 'Open this road in the Segments node editor'),
            link('Structure', () => goTab('structure', () => { if (structRoad !== id) { structRoad = id; steps = null; legs = null; } }), 'Open this road on the Structure tab'))),
        sec('Legs' + (st ? ' - ' + (st.label || st.id || '') + ' v' + (st.version || 1) : ''),
          legList.length ? el('ol', 's3-sys3-legs', ...legList.map(l => el('li', null, el('b', {text: l.label || l.id}), ' ',
            el('span', {class: 's3-muted', text: [l.seat || l.speaker, l.place, l.optional ? 'optional' : ''].filter(Boolean).join(' · ')}),
            el('div', {class: 's3-sys3-draws', text: (l.draws || []).map(dr => dr.family + (dr.tables ? '[' + dr.tables.join(',') + ']' : '') + (dr.fixed ? '=' + dr.fixed : '') + (dr.closes ? ' closes' : '')).join('  ') || 'no draws'}))))
            : para(r.shape === 'line' || r.shape === 'node' ? 'A single-voice road: one node, no legs.' : 'No structure saved for this road.', 's3-muted')),
        sec('Tables', tbls.length ? el('div', null, ...tbls.map(t => tableEditor(t))) : para('No table is drawn by this road.', 's3-muted')),
        sec('Pools', pools.length ? el('div', null, ...pools.map(t => tableEditor(t, cid => underPrefix(cid, id)))) : para('No pool rows are named for this road.', 's3-muted'),
          later(el('div'), async () => { const ls = (await listsOf()).filter(l => underPrefix(l.id, id));
            return ls.length ? el('ul', 's3-sys3-lists', ...ls.map(l => el('li', null, el('b', {text: l.label}), ' ', el('span', {class: 's3-muted', text: l.family + ' · ' + (l.count || 0) + ' rows'}), ' ',
              link('Open', () => goTab('tables', () => { listId = l.id; listView.q = ''; listView.state = ''; listView.offset = 0; }), 'Open this list in the Tables tab')))) : null; })),
        sec('Recent lines and their rolls', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=3&road=' + encodeURIComponent(id));
          const convs = (got.conversations || []).slice(0, 2); if (!convs.length) return para('No round recorded on this road in the ledger.', 's3-muted');
          const out = [];
          for (const cv of convs) {
            const full = await request('/api/system3/conversation/' + encodeURIComponent(cv.conversation_id));
            const lines = (full.lines || []).slice(-3);
            out.push(el('div', 's3-sys3-conv', el('div', {class: 's3-muted', text: day(cv.created) + ' · ' + cv.mode + ' · ' + cv.turns + ' turns · ' + (cv.status || '')}),
              lines.length ? el('ul', null, ...lines.map(ln => el('li', null, el('b', {text: (ln.who || '') + ': '}), String(ln.text || '').slice(0, 180),
                later(el('div', 's3-sys3-rolls'), async () => { const o = await request('/api/system3/origin/' + encodeURIComponent(ln.line_id));
                  const rolls = (o.nodes || []).filter(x => x.node === 'roll').slice(0, 8);
                  return rolls.length ? rolls.map(x => el('span', {class: 's3-sys3-roll', title: x.picked || '', text: (x.table || '') + ' ' + (x.dice == null ? '' : 'd' + x.dice) + ' ' + String(x.picked || x.path || '').slice(0, 40)}))
                    : el('span', {class: 's3-muted', text: o.verdict ? o.verdict + (o.why ? ' - ' + o.why : '') : 'no rolls recorded'}); }))))
                : para('planned; no line written to air yet', 's3-muted')));
          }
          return out;
        })),
        sec('Rates and failures', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=40&road=' + encodeURIComponent(id)); const cs = got.conversations || [];
          if (!cs.length) return para('Nothing in the ledger for this road.', 's3-muted');
          const count = f => cs.reduce((m, x) => { const k = f(x) || 'none'; m[k] = (m[k] || 0) + 1; return m; }, {});
          const span = (cs[0].created - cs[cs.length - 1].created) / 3600;
          const fmt = o => Object.entries(o).map(([k, v]) => k + ' ' + v).join(' · ');
          return kv([['rounds read', cs.length], ['rate', span > 0 ? num(cs.length / span, 1) + ' per hour' : '-'], ['status', fmt(count(x => x.status))],
            ['verdicts', fmt(count(x => x.verdict))], ['failed', cs.filter(x => /fail|abandon/.test(String(x.status || '')) || x.verdict === 'non_compliant').length],
            ['station faults (all roads)', (status && status.metrics && status.metrics.failures) || 0], ['last fault', status && status.metrics && status.metrics.last_failure]]);
        })),
        sec('Hour segments', later(wait(), async () => {
          const got = await segmentsOf(); const rows = (got.segments || []).filter(sg => (sg.conversations || []).some(cv => cv.road === id));
          const now = got.now ? el('p', {class: 's3-muted', text: 'on now: ' + (got.now.label || got.now.id)}) : null;
          return [now, rows.length ? el('ul', 's3-sys3-segs', ...rows.slice(0, 12).map(sg => el('li', null, el('b', {text: sg.label || sg.template}), ' ',
            el('span', {class: 's3-muted', text: day(sg.start) + ' · ' + (sg.conversations || []).filter(cv => cv.road === id).length + ' of ' + (sg.conversations || []).length + ' conversations'}))))
            : para('This road went out in none of the last three hours\' segments.', 's3-muted')];
        })),
        fold('register entry (raw)', r)];
    }
    function coreView(later) {
      const m = (status && status.metrics) || {}, stc = (status && status.store) || {}, s = (status && status.settings) || {};
      const c = cfgNow(); const SECTIONS = ['speakerbox', 'sfx', 'sfxguy', 'split', 'handoff', 'personalities', 'blocks'];
      let secName = 'speakerbox';
      const area = el('textarea', {class: 's3-sys3-json', rows: 10, 'aria-label': 'section JSON', value: json(c[secName] || {})});
      const pick = el('select', {'aria-label': 'config section', onchange: e => { secName = e.target.value; area.value = json(cfgNow()[secName] || {}); }},
        ...SECTIONS.map(x => el('option', {value: x, text: x})));
      const review = btn('Review the change', () => {
        let next; try { next = JSON.parse(area.value); } catch (e) { fill(sideNote, el('div', 's3-sys3-edit', para('Not JSON: ' + e.message, 's3-error'))); return; }
        const name = secName; const before = cfgNow()[name] || {};
        propose({title: 'section ' + name, changes: flatDiff(before, next, name, []),
          apply: () => send('/api/system3/config/section/' + name, 'PUT', next),
          undo: async was => send('/api/system3/config/section/' + name, 'PUT', await prevPart(was, cc => cc[name] || before)),
          after: () => { area.value = json(cfgNow()[name] || {}); }});
      }, {class: 's3-sys3-review', title: 'See what will change before it is saved'});
      const active = (c.tables || []).filter(t => t.enabled !== false);
      return [
        sec('Now', kv([['mode', (s.mode || '').replaceAll('_', ' ')], ['selected roads', (s.roads || []).join(', ')], ['engine', status && status.engine], ['config', liveHash()],
          ['planned', m.planned], ['active', m.active], ['shadow', m.shadow], ['plan', num(m.plan_ms_ema, 1) + ' ms'], ['max plan', num(m.plan_ms_max, 1) + ' ms'],
          ['open rounds', status && status.open_rounds], ['lines linked', m.lines_linked], ['failures', m.failures], ['last fault', m.last_failure],
          ['ledger', (stc.conversations || 0) + ' conversations · ' + (stc.events || 0) + ' events · ' + (stc.lines || 0) + ' lines']]),
          el('div', 's3-row', link('Controls', () => goTab('controls'), 'Mode, roads and behaviour controls'), link('Director', () => goTab('director'), 'The conversations, the Rolodex and the script'))),
        sec('Active tables (' + active.length + ')', el('div', null, ...active.map(t => tableEditor(t)))),
        sec('Config sections', el('div', 's3-row', pick, review), area),
        sec('Versions', el('ul', 's3-sys3-vers', ...((config && config.versions) || []).slice(0, 8).map(v => el('li', null, el('code', {text: v.hash}), ' ',
          el('span', {class: 's3-muted', text: day(v.created) + ' · ' + (v.note || '')}), v.hash === liveHash() ? el('span', {class: 's3-pill active', text: 'live'}) : null)))),
        fold('status (raw)', status || {})];
    }
    function roomView(id, later) {
      const m = (status && status.metrics) || {}, stc = (status && status.store) || {};
      const evRow = e => el('li', null, el('span', {class: 's3-muted', text: day(e.at) + ' '}), el('b', {text: (e.family || e.kind || '') + ' '}),
        String(e.label || e.stage || e.key || '').slice(0, 80), e.dice != null ? ' d' + e.dice : '', e.road ? el('span', {class: 's3-muted', text: ' · ' + e.road}) : '');
      const recent = (f, empty) => { const rows = ring.filter(f).slice(-12).reverse(); return rows.length ? el('ul', 's3-sys3-recent', ...rows.map(evRow)) : para(empty, 's3-muted'); };
      if (id === 'writer') return [
        sec('Queue', kv([['open rounds', status && status.open_rounds], ['rounds planned', m.planned], ['lines planned', m.lines_planned], ['lines bound', m.lines_bound],
          ['material resolved', m.material_resolved], ['material timeouts', m.material_timeouts], ['turn-by-turn beats', m.mode_b_beats], ['repairs', m.repairs], ['fallbacks', m.fallbacks]])),
        sec('Recent rounds handed to the writer', later(wait(), async () => { const g = await request('/api/system3/conversations?limit=10'); const cs = g.conversations || [];
          return cs.length ? el('ul', 's3-sys3-recent', ...cs.map(cv => el('li', null, el('span', {class: 's3-muted', text: day(cv.created) + ' '}), el('b', {text: cv.road + ' '}),
            (cv.status || '') + ' · ' + cv.turns + ' turns · ', el('span', {class: 's3-muted', text: String(cv.topic || '').slice(0, 70)})))) : para('Nothing recorded.', 's3-muted'); })),
        link('Director', () => goTab('director'), 'The conversations, the Rolodex and the script')];
      if (id === 'voice') return [
        sec('Queue', kv([['voice from ES', m.perf_applied], ['SFX directed', m.sfx_directed], ['SFX extra', m.sfx_extra], ['SFX observed', m.sfx_observed],
          ['SFX Guy directed', m.sfxguy_directed], ['SFX Guy spoke', m.sfxguy_spoke]])),
        sec('Recent voice rolls this scene saw', recent(e => /^voice\.|^sfx/.test(String(e.key || '')) || e.family === 'SFX', 'None since the scene opened.')),
        link('Controls', () => goTab('controls'), 'The sfx, sfxguy and split sections')];
      if (id === 'ledger') return [
        sec('Queue', kv([['writes pending', m.pending_writes], ['dropped', m.writes_dropped], ['conversations', stc.conversations], ['events', stc.events], ['lines', stc.lines],
          ['segments', stc.segments], ['size', ((stc.bytes || 0) / 1e6).toFixed(1) + ' MB'],
          ['modes', Object.entries(stc.modes || {}).map(([k, v]) => k + ' ' + v).join(' · ')], ['verdicts 24 h', Object.entries(stc.verdicts_24h || {}).map(([k, v]) => k + ' ' + v).join(' · ')]])),
        sec('Recent script-ledger commits', recent(e => e.family === 'COMMIT' || e.stage === 'script-ledger', 'None since the scene opened.')),
        link('Audit', () => goTab('audit'), 'Every recorded decision and observation')];
      return [
        sec('On air now', el('p', {text: lastText || 'nothing on air'})),
        sec('Recent lines on air this scene saw', aired.length ? el('ul', 's3-sys3-recent', ...aired.slice(-12).reverse().map(a => el('li', null,
          el('span', {class: 's3-muted', text: day(a.at) + ' '}), a.road ? el('b', {text: a.road + ' '}) : '', a.text.slice(0, 160),
          a.line && (a.line.id || a.line.line_id) ? later(el('div', 's3-sys3-rolls'), () => originView(a.line.id || a.line.line_id)) : null))) : para('None since the scene opened.', 's3-muted'))];
    }
    async function originView(lineId) {
      const o = await request('/api/system3/origin/' + encodeURIComponent(lineId));
      const rolls = (o.nodes || []).filter(x => x.node === 'roll');
      return [kv([['verdict', o.verdict], ['why', o.why], ['road', o.road], ['text', String(o.text || '').slice(0, 200)]]),
        rolls.length ? el('div', null, ...rolls.slice(0, 12).map(x => el('span', {class: 's3-sys3-roll', title: x.picked || '', text: (x.table || '') + ' ' + (x.dice == null ? '' : 'd' + x.dice) + ' ' + String(x.picked || x.path || '').slice(0, 48)}))) : null,
        fold('origin record (raw)', o)];
    }
    async function replayView(cid) {
      const r = await send('/api/system3/replay/' + encodeURIComponent(cid), 'POST');
      return kv([['replay', r.ok ? 'every draw reproduced' : 'differs'], ['events', r.events], ['replayed', r.replayed], ['first difference', r.first_difference ? JSON.stringify(r.first_difference).slice(0, 120) : ''], ['why', r.why]]);
    }
    const replayBtn = (cid, box) => btn('Replay the rolls', e => { e.target.disabled = true; fill(box, wait()); replayView(cid).then(k => fill(box, k), err => fill(box, para('Replay: ' + err.message, 's3-error'))); },
      {class: 's3-sys3-replay', title: 'Re-draw every decision of this round from its inputs, seed and config'});
    function packetView(cc, later) {
      const road = cc.a === 'system3' && cc.b && !rooms.some(x => x[0] === cc.b) ? cc.b : '';
      const names = {system3: 'System 3', writer: 'the writer', voice: 'the recording room', ledger: 'the script ledger', air: 'the air'};
      const what = road ? 'System 3 hands this road its plan (the rolls of each leg) and the road hands its words back to be bound.'
        : ({writer: 'System 3 hands the writer the running order: each turn\'s decisions as the prompt\'s blocks.',
          voice: 'The writer\'s words go to the recording room with the performance the ES row set.',
          ledger: 'Rendered lines take their place in the script ledger (block, ord).', air: 'The ledger plays out: a line goes to air and the air receipt comes back.'})[cc.b] || '';
      const rb = el('div');
      return [sec('Circuit', kv([['from', names[cc.a] || cc.a], ['to', names[cc.b] || cc.b], ['carries', what], ['live', cc.on ? 'yes' : 'no (road not directed)']])),
        road ? el('div', 's3-row', link('Inspect the road', () => { const it = pickables.find(p => p.kind === 'road' && p.m.userData.id === road); if (it) select(it); }, 'Open this road in the inspector')) : null,
        sec('Its latest decision and origin', later(wait(), async () => {
          const got = await request('/api/system3/conversations?limit=1' + (road ? '&road=' + encodeURIComponent(road) : '')); const cv = (got.conversations || [])[0];
          if (!cv) return para('Nothing recorded on this circuit.', 's3-muted');
          const full = await request('/api/system3/conversation/' + encodeURIComponent(cv.conversation_id));
          const ln = (full.lines || [])[(full.lines || []).length - 1]; const ev = (full.decision_events || [])[(full.decision_events || []).length - 1];
          return [kv([['round', cv.road + ' · ' + cv.conversation_id], ['when', day(cv.created)], ['status', cv.status], ['decisions', cv.events]]),
            ev ? fold('latest decision ' + (ev.family || '') + ' (raw)', ev) : null,
            ln ? later(el('div'), () => originView(ln.line_id)) : para('No line of it reached the ledger yet.', 's3-muted'),
            el('div', 's3-row', replayBtn(cv.conversation_id, rb)), rb];
        }))];
    }
    function planeView(ev, road, later) {
      const rb = el('div'); const real = ev.conversation_id && !String(ev.conversation_id).startsWith('station:');
      const lineIds = ev.lines || [];
      return [sec('Decision', kv([['kind', ev.kind], ['family', ev.family], ['what', ev.label || ev.stage || ev.key], ['key', ev.key], ['dice', ev.dice], ['odds', ev.odds],
          ['hit', ev.hit == null ? '' : ev.hit ? 'yes' : 'no'], ['why', ev.why], ['road', road || ev.round], ['conversation', ev.conversation_id], ['when', day(ev.at)], ['cursor', ev.cursor]])),
        sec('Origin record', lineIds.length ? later(wait(), () => originView(lineIds[0]))
          : real ? later(wait(), async () => { const full = await request('/api/system3/conversation/' + encodeURIComponent(ev.conversation_id));
            const ln = (full.lines || [])[0]; return ln ? originView(ln.line_id) : para('Its round has no line in the ledger yet.', 's3-muted'); })
            : para('A station roll: it belongs to the station\'s hour, not to one line.', 's3-muted')),
        real ? el('div', 's3-row', replayBtn(ev.conversation_id, rb), link('Audit', () => goTab('audit', () => { auditFilter = {family: '', conversation: ev.conversation_id}; }), 'This round in the Audit log')) : null, rb,
        fold('event (raw)', ev)];
    }

    let framed = false;
    const size = () => { const w = canvas.clientWidth || 640, h = canvas.clientHeight || 400; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
      if (framed && drift && !ptrs.size) frameAll(false); };   /* untouched: the pane's new shape is framed again */
    size(); window.addEventListener('resize', size);
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => size()) : null; if (ro) ro.observe(canvas);
    frameAll(true); framed = true;
    const t0 = performance.now(); const origin = new THREE.Vector3(0, 0.9, 0); let tPrev = t0, frozen = false;
    const hp = V(0, 0, 0);
    function frame() {
      if (!alive) return; raf = requestAnimationFrame(frame);
      const now = performance.now(); const t = (now - t0) / 1000; const dt = Math.min(0.1, (now - tPrev) / 1000); tPrev = now;
      core.rotation.y = t * 0.6; core.rotation.x = Math.sin(t * 0.5) * 0.4;
      circuits.forEach((c, i) => { if (!c.on) return; const u = (t * c.speed + c.phase) % 1; packets[i].position.lerpVectors(c.from, c.to, u); packets[i].position.y += Math.sin(u * Math.PI) * 0.5; });
      for (let i = planes.length - 1; i >= 0; i -= 1) { const p = planes[i]; if (!frozen) p.t += 0.016; const u = Math.min(1, p.t / 1.6);
        p.m.position.lerpVectors(origin, p.to, u); p.m.position.y += Math.sin(u * Math.PI) * 2.2; p.m.lookAt(p.to); p.m.rotateX(Math.PI / 2);
        if (u >= 1) { p.m.material.opacity -= 0.05; if (p.m.material.opacity <= 0) { scene.remove(p.m); planes.splice(i, 1); } } }
      for (let i = pickables.length - 1; i >= 0; i -= 1) if (pickables[i].kind === 'plane' && !pickables[i].m.parent && pickables[i] !== sel) pickables.splice(i, 1);
      if (drift) goal.theta = home.theta + Math.sin(t * 0.1) * 0.13;   /* the old idle sway, until a hand moves the camera */
      const k = 1 - Math.exp(-dt * 9);
      cur.target.lerp(goal.target, k); cur.r += (goal.r - cur.r) * k; cur.theta += (goal.theta - cur.theta) * k; cur.phi += (goal.phi - cur.phi) * k;
      place(cur);
      if (sel && halo.visible) { const ok = sel.m.visible && !!sel.m.parent; halo.material.opacity = ok ? 1 : 0; if (ok) { sel.m.getWorldPosition(hp); halo.position.copy(hp); halo.scale.setScalar(sel.radius * 3.2); } }
      renderer.render(scene, camera);
    }
    frame(); poll();
    /* the harness's handle: the camera goal and picking, read without the GPU */
    const api = {
      stop() {
        alive = false; cancelAnimationFrame(raf); window.removeEventListener('resize', size); if (ro) ro.disconnect();
        window.removeEventListener('keydown', onKey, true); window.removeEventListener('keyup', onKeyUp, true); window.removeEventListener('blur', onBlur);
        window.removeEventListener('scroll', fitSide, true); window.removeEventListener('resize', fitSide);
        if (offBack) { try { offBack(); } catch (_) { /* gone */ } }
        try { scene.traverse(o=>{o.geometry?.dispose();for(const material of (Array.isArray(o.material)?o.material:[o.material])){if(!material)continue;material.map?.dispose();material.dispose();}});renderer.dispose();renderer.forceContextLoss(); } catch (_) { /* gone */ }
      },
      view: () => ({r: goal.r, theta: goal.theta, phi: goal.phi, target: goal.target.toArray(), drift, home: {r: home.r, target: home.target.toArray()}, open: !side.hidden, sel: sel ? sel.kind + ':' + (sel.m.userData.id ?? sel.m.userData.circuit ?? '') : ''}),
      screenOf: (kind, id) => { const it = pickables.find(p => p.kind === kind && (id == null || p.m.userData.id === id || p.m.userData.circuit === id)); if (!it) return null;
        const q = it.m.getWorldPosition(V(0, 0, 0)).project(camera); const r = canvas.getBoundingClientRect();
        return {x: r.left + (q.x + 1) / 2 * r.width, y: r.top + (1 - q.y) / 2 * r.height}; },
      screens: kind => pickables.filter(p => p.kind === kind && p.m.visible && p.m.parent).map(p => { const q = p.m.getWorldPosition(V(0, 0, 0)).project(camera); const r = canvas.getBoundingClientRect();
        return {id: p.m.userData.id ?? p.m.userData.circuit, x: r.left + (q.x + 1) / 2 * r.width, y: r.top + (1 - q.y) / 2 * r.height}; }),
      fly: ev => fly(nodes.get(ev.round || '') || nodes.get('writer'), 0x7fe0d6, ev, ev.round || ''),
      freeze: () => { frozen = true; circuits.forEach(c => { c.speed = 0; c.phase = 0.5; }); planes.forEach(p => { p.t = 0.8; }); }};
    host.pineSys3 = api;
    return api;
  }

  /* ---------------- controls ---------------------------------------------- */
  const CONTROL_HELP = {
    emotional_volatility: 'how readily a speaker leaves the emotion they are in',
    disagreement: 'weight on arguing, pushing back and refusing premises',
    escalation: 'weight on turning the heat up', tangent: 'weight on wandering off the point',
    callback: 'weight on calling back to earlier moments', speakerbox_density: 'scales the prepend/append odds',
    sfx_aggression: 'restrained (0) to deliberately chaotic (1) - never below the two-line cadence',
    novelty: 'weight on fresh subjects and moves', closure_aggressiveness: 'how early the scene starts landing',
    favorites: 'the odds a line the operator liked comes up in a round or single line (0.25 = one in four)'};   /* [s3-cast] */
  function paintControls() {
    const s = JSON.parse(JSON.stringify(settings.settings));
    const cfg = JSON.parse(JSON.stringify(config.config));
    const sliders = Object.keys(s.controls).map(k => {
      const out = el('span', {text: num(s.controls[k])});
      return el('div', 's3-slider', el('label', {title: CONTROL_HELP[k] || '', text: k.replaceAll('_', ' ')}),
        el('input', {type: 'range', min: 0, max: 1, step: 0.05, value: s.controls[k], 'aria-label': k,
          oninput: e => { s.controls[k] = +e.target.value; out.textContent = num(+e.target.value); }}), out);
    });
    const mode = el('select', {onchange: e => { s.mode = e.target.value; }}, ...settings.modes.map(m => el('option', {value: m, text: m.replaceAll('_', ' '), selected: m === s.mode})));
    const roads = settings.roads.map(r => el('label', 's3-row', el('input', {type: 'checkbox', checked: s.roads.includes(r),
      onchange: e => { s.roads = s.roads.filter(x => x !== r); if (e.target.checked) s.roads.push(r); }}), r));
    const gen = el('select', {onchange: e => { s.generation_mode = e.target.value; }}, ...settings.generation_modes.map(m => el('option', {value: m, text: m === 'batch' ? 'planned scene (batch)' : 'turn by turn (banked rounds)', selected: m === s.generation_mode})));
    const seed = el('input', {type: 'text', value: s.test_seed, placeholder: 'blank: a fresh seed per conversation', oninput: e => { s.test_seed = e.target.value; }});
    const repair = el('label', 's3-row', el('input', {type: 'checkbox', checked: s.repair, onchange: e => { s.repair = e.target.checked; }}), 'repair banked rounds that ignored the running order');
    const verb = el('select', {onchange: e => { s.debug_verbosity = e.target.value; }}, ...['quiet', 'normal', 'full'].map(v => el('option', {value: v, text: v, selected: v === s.debug_verbosity})));
    /* [s3-live-event] the station's activatable events: while one is on, its
       rows join the wheels; off, they are invisible to the dice. */
    const eventsCard = () => el('div', 's3-card', el('h2', {text: 'Station events'}),
      el('p', {class: 's3-muted', text: 'An activatable event (MX Live) whose rows sit in the tables tagged with it (Tables tab: MXLIVE1, MXLIVECTS1, MXLIVETRACK1, MXLIVEID1, MXLIVEANGLE1, MXLIVECALL1). While the event is on, those rows are eligible in their wheels at their own weights; while it is off they are filtered out before any weight is computed, so no draw moves. A pinelive event follows the PineLive switch (the mic on the status bar); a roll that lands on one of its rows says so in the Rolodex.'}),
      ((status && status.events) || []).length ? el('table', 's3-table',
        el('thead', null, el('tr', null, ...['event', 'source', 'now', 'tables'].map(h => el('th', {text: h})))),
        el('tbody', null, ...((status && status.events) || []).map(ev => el('tr', null,
          el('td', null, el('b', {text: ev.name}), el('div', {class: 's3-muted', text: ev.id + (ev.what ? ' - ' + ev.what : '')})),
          el('td', {text: ev.source}),
          el('td', null, el('span', {class: 's3-pill ' + (ev.on ? 'active' : 'off'), text: ev.on ? (ev.stage || 'on') : 'off'})),
          el('td', {class: 's3-muted', text: (ev.tables || []).join(', ') || 'no tables carry it'})))))
        : para('No station events are registered.', 's3-muted'));
    /* [s3-roads] every road that puts words on air, and what System 3 is for it now */
    const roadsCard = () => el('div', 's3-card s3-roads', el('h2', {text: 'Roads'}),
      el('p', {class: 's3-muted', text: 'Every road that puts words on air, and what System 3 is for it right now: its structure is on the Structure tab. A road standing aside is labelled "not directed by System 3" wherever its lines show.'}),
      el('table', 's3-roads-table',
        el('thead', null, el('tr', null, ...['road', 'shape', 'mode', 'what', 'writer -> hook'].map(h => el('th', {text: h})))),
        el('tbody', null, ...((status && status.roads) || []).map(r => el('tr', null,
          el('td', null, el('b', {text: r.label}), el('div', {class: 's3-muted', text: r.id})),
          el('td', {text: r.shape}),
          el('td', null, el('span', {class: 's3-pill ' + (r.mode === 'active' ? 'active' : r.mode === 'shadow' ? 'shadow' : 'off'), text: r.mode + (r.label_air ? ' · ' + r.label_air : '')})),
          el('td', {text: r.what}),
          el('td', {class: 's3-muted', text: r.writer + (r.hook ? ' -> ' + r.hook : '')}))))));
    /* [s3-save] every saved version of the tables and structures, newest first,
       the live one marked - what the desk is actually running */
    const versionsCard = () => {
      const rows = ((config && config.versions) || []).slice(0, 40);
      const live = (config && config.hash) || '';
      return el('div', 's3-card', el('h2', {text: 'Config versions'}),
        el('p', {class: 's3-muted', text: 'Every save of a table, the banter cycle or a segment is a version in the ledger. The live one is what the roulette plans from right now; a graph that is not in this list is not on the station.'}),
        rows.length ? el('table', 's3-table', el('thead', null, el('tr', null, el('th', {text: 'when'}), el('th', {text: 'hash'}), el('th', {text: 'note'}))),
          el('tbody', null, ...rows.map(r => el('tr', {class: r.hash === live ? 's3-live' : ''},
            el('td', {text: r.created ? new Date(r.created * 1000).toLocaleString() : ''}),
            el('td', null, el('code', {text: r.hash}), r.hash === live ? el('span', {class: 's3-pill active', text: 'live'}) : null),
            el('td', {text: r.note || ''}))))) : para('No saved versions yet - the defaults are live.', 's3-muted'));
    };
    const section = (name, help) => {
      const area = el('textarea', {value: json(cfg[name] || {})});
      return el('div', 's3-card', el('h2', {text: name}), el('p', {class: 's3-muted', text: help}), area,
        btn('Save ' + name, async () => { try { const res = await send('/api/system3/config/section/' + name, 'PUT', JSON.parse(area.value)); await loadConfig(); saved(name, res); } catch (e) { report(e); } }));
    };
    fill(body, el('div', 's3-grid2',
      el('div', 's3-card', el('h2', {text: 'Authority'}),
        el('p', {class: 's3-muted', text: 'Off: the legacy station. Shadow: System 3 plans every round beside the legacy writer and nothing it decides reaches air. Active on selected roads: it directs only the roads ticked here. Active: every supported road.'}),
        el('div', 's3-row', 'mode', mode), el('div', 's3-row', 'roads', ...roads), el('div', 's3-row', 'generation', gen),
        el('div', 's3-row', 'test seed', seed), repair, el('div', 's3-row', 'debug verbosity', verb)),
      el('div', 's3-card', el('h2', {text: 'Behaviour controls'}),
        el('p', {class: 's3-muted', text: 'Each control multiplies the documented weight of the outcomes tagged with it by 0.5x to 2x (0.5 is neutral). They move weights, never hidden prompt text.'}),
        ...sliders),
      el('div', 's3-card', el('div', 's3-row',
        btn('Save settings', async () => { try { settings.settings = (await send('/api/system3/settings', 'POST', s)).settings; await refreshStatus(); paint(); quiet(); } catch (e) { report(e); } }),
        btn('Reset controls to defaults', async () => { try { settings.settings = (await send('/api/system3/settings', 'POST', {reset: true})).settings; paint(); } catch (e) { report(e); } }),
        btn('Reset tables and structure to defaults', async () => { if (!confirm('Replace the live tables and structure with the defaults? The current version stays in the ledger.')) return; try { await send('/api/system3/config/reset', 'POST'); await loadConfig(); paint(); } catch (e) { report(e); } }))),
      eventsCard(),                                   /* [s3-live-event] */
      roadsCard(),
      versionsCard(),
      section('speakerbox', 'Mode weights for a hit (verbatim / reference / callback), the inline passage budget per round, and passage length.'),
      section('sfx', 'The SFX Guy: planned-clip probability at aggression 0 and 1, the first-exchange clip, and the arousal and comedy boosts. The station\'s cadence stays the floor.'),
      section('sfxguy', 'The SFX Guy\'s mouth: his node on every host turn. rate_by_dial uses the desk\'s interjections dial for whether he pipes up; reaction_by_warp uses the invention dial for how often a line is fired back at the one just said; news_share is the wire; never_over_callers keeps him off a caller\'s turn.'),
      handoffPolicyEditor(cfg.handoff, async next => { const res = await send('/api/system3/config/section/handoff', 'PUT', next); await loadConfig(); saved('handoff', res); }),
      section('split', 'The SPLIT node: a read past threshold_seconds at its voice\'s pace (pace, or paces by role; else the pace the station measured) is shared out on a node whose split box is ticked, into at most max_splits + 1 parts. who weighs each member of the studio (dj, cohost, third, drop) for the roll that picks who carries it on; again is the weight for someone who already read a part; min_share keeps a cut from leaving a scrap.'),   /* [s3-split] */
      section('personalities', 'Per seat tag multipliers, e.g. {"A": {"disagreement": 1.4}, "B": {"humor": 1.3}}.'),
      /* [s3-blocks] */
      section('blocks', 'Every block a writer prompt may carry, and what System 3 does with it: kind "obligation" (always sent, recorded), "roll" (a die at odds, or the desk dial named in odds_from), "tint" (only while a crystal is on and the tint pass is wanted) or "off". A block whose name is not here is a wedge and is stripped. The Prompt tab shows each prompt’s blocks as decided.')));
  }

  /* ---------------- plumbing ---------------------------------------------- */
  async function loadConfig() { config = await request('/api/system3/config'); }
  async function refreshStatus() { status = await request('/api/system3/status'); paintStatus(); }

  /* [s3-focus] a window openSystem3Focus opened is focused on one message: its
     lens (the block at the end of this file) paints the tabs zeroed in on it,
     and hands a tab back to this router when the operator asks for all of
     System 3. Null for every other window. The handles are onto this mount's
     own state, so the lens opens the window's own editors on the right part. */
  const focus = s3FocusLens(root, {request, send, tabs, body, controlHelp: CONTROL_HELP,
    tab: () => tab,
    go: id => { stopExtras(); tab = id; paint(); },
    config: () => config,
    settings: () => settings,
    /* a lever saved: the live config again, and the editor's draft of that part dropped (it is the old version) */
    loadConfig: async (kind, id) => {
      await loadConfig();
      if (kind === 'table' && draft && draft.id === id) draft = null;
      if (kind === 'structure') {
        if (segRoadOf === id) segNodes = null;
        if (legsRoad === id) legs = null;
        if (id === 'banter') steps = null;
      }
    },
    visual: (cid, turnId) => { visualPreview = null; visualCid = cid; visualTurn = turnId || ''; },
    director: (cid, turnId) => load(cid).then(() => { if (turnId) v.select(turnId, '', null); }),
    table: (id, list) => {
      if (list) { listId = list; listView.q = ''; listView.state = ''; listView.offset = 0; return; }
      listId = '';
      if (id) tableId = id;
    },
    segment: (road, index) => {
      if (!segNodes || segRoadOf !== road) { segNodes = null; segLoad(road); }
      segRoad = road;
      segSel = {node: index >= 0 ? index : -1, draw: -1};
    },
    structure: road => { if (structRoad !== road) { structRoad = road; steps = null; legs = null; } },
    audit: cid => { auditFilter = {family: '', conversation: cid}; }});
  function paint() {
    paintTabs();
    try {
      if (focus && focus.paint(tab)) return;                       /* [s3-focus] */
      if (tab === 'director') { fill(body, director); paintDirector(); }
      else if (tab === 'visual') paintVisual();
      else if (tab === 'tables') paintTables();
      else if (tab === 'segments') paintSegments();
      else if (tab === 'prompts') paintPrompts();
      else if (tab === 'audit') paintAudit();
      else if (tab === 'sys3') paintSys3();
      else if (tab === 'structure') paintStructure();
      else paintControls();
    } catch (e) { report(e); }
  }

  let polling = false;
  async function poll() {
    if (!alive || document.hidden || polling) return;
    if (reading()) return;                                  /* [s3-hold] */
    polling = true;
    try {
      const feed = await request('/api/system3/events?' + new URLSearchParams({after: cursor, limit: 500}));
      const fresh = feed.events || [];
      cursor = feed.cursor || cursor;
      if (fresh.length && tab === 'director') {
        const cids = [...new Set(fresh.map(e => e.conversation_id))];
        await refreshList();
        const mine = v.conv && cids.includes(v.conv.identity.conversation_id);
        const newest = list[0] && list[0].conversation_id;
        if(follow&&newest&&newest!==lastLoaded){
          if(v.playing){deferredBuildCid=newest;if(mine)await keepPlace(()=>load(v.conv.identity.conversation_id,false,{refresh:true}));}
          else await keepPlace(()=>load(newest,true));
        }else if(mine)await keepPlace(()=>load(v.conv.identity.conversation_id,false,{refresh:true}));   /* [s3-still] */
      }
      await refreshStatus();
    } catch (e) { if(alive)report(e); } finally { polling=false; }
  }

  let initializing = false;
  async function initialize() {
    if(!alive||initializing)return;initializing=true;retryStartup.disabled=true;quiet();
    try {
    await Promise.all([refreshStatus(), loadConfig(), request('/api/system3/settings').then(s => { settings = s; })]);
    if(!alive)return;
    const head = await request('/api/system3/events?after=0&limit=1');
    if(!alive)return;
    cursor = head.head || 0;
    await refreshList();
    if(!alive)return;
    if(tab!=='sys3'||!sys3)paint();
    if (tab==='director' && list[0] && !(focus && !focus.full())) await load(list[0].conversation_id);   /* [s3-focus] a focused window reads its own round */
    else if(tab==='director')paintDirector();
    } catch (e) { if(alive){report(e);message.append(' ',retryStartup);paintTabs();} }
    finally {initializing=false;retryStartup.disabled=false;}
  }
  paintTabs();if(tab==='sys3')paintSys3().catch(report);
  initialize().catch(report);
  timers.push(setInterval(poll, 2000));
  return {dispose() { alive = false; v.alive = false; timers.forEach(clearInterval); stopExtras(); fill(root); }};
}

/* [s3-dice] A DIE ON THE FEED, TAPPED: the decision card of the roll it
   shows - its stages, the candidates and their weights, the d100 - with the
   table it drew from a tap away in the Tables tab. A roll with no event of
   its own (the SFX Guy's draw at air) opens the line's whole story. */
export async function openRoll({request, conversationId = '', eventId = '', turnId = '', lineId = ''} = {}) {
  request ||= defaultRequest();
  let conv = null;
  try { conv = conversationId ? await request('/api/system3/conversation/' + encodeURIComponent(conversationId)) : null; } catch (e) { conv = null; }
  const ev = conv && eventId ? (conv.decision_events || []).find(e => e.event_id === eventId) : null;
  if (conv && ev) {
    const turn = (conv.turns || []).find(t => t.turn_id === (ev.turn_id || turnId)) || null;
    const v = makeViews({request});
    v.setConversation(conv);
    return openDecision(conv, ev, turn, v.api);
  }
  return openLineStory({request, lineId});
}

export function openLineStory({request, lineId = ''} = {}) {
  request ||= defaultRequest();
  const back = el('div', {class: 's3 s3-modal-back'});
  const before = document.activeElement;
  let story = null;
  const close = () => {
    back.remove(); document.removeEventListener('keydown', onKey, true);
    if (story && story.dispose) { try { story.dispose(); } catch (e) { /* gone */ } }
    if (before && before.focus) before.focus();
  };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const shut = btn('Close', close, {class: 's3-modal-close', 'aria-label': 'Close'});
  const host = el('div', 's3-story-modal');
  back.append(movableModal(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How System 3 built this line'}, shut, host)));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-line-story', window.PineDuck.REPORT, back);
  mountLineStory(host, {request, lineId}).then(x => { story = x; }, () => {});
  shut.focus({preventScroll: true});
  return close;
}

/* ======================================================================== */
/* [s3-rolodex] THE ROLODEX IN FRONT OF THE PROMPT.
 *
 * "in front of system prompt put a section showing the rolodex result and
 *  the dice rolls on each row for why this prompt is being made. Call the
 *  section Rolodex. Show a line for each rolodex result and show the node
 *  that was used for that prompting that prompt. On the right side show a
 *  dice that rolls and pops into the final number showing the result of
 *  the dice roll. put ticks on each entry allowing it to expand and show
 *  more information about the command and what it means for the prompt
 *  and system."
 *
 * One row per recorded roll of the round, in the order they were rolled:
 * the family, what landed, the node (the leg or step) whose draw it was
 * and the message it made, and the d100 on the right - rolled on show,
 * landing on the recorded number. The tick opens the row into what the
 * family decides, the command the writer was given (the item's own words
 * and the row it made in the running order), the performance it set, the
 * candidates with the weights the engine used, and the decision card. */
function landedWords(ev, conv) {
  const sel = ev.selected || {};
  const line = eventLine(ev, conv);
  const sb = sbOutcome(ev);
  if (sb) return sb.won ? `${sb.label} - ${String(sel.id || '').toLowerCase()}` : `${sb.label} - no passage`;
  if (sel.table) {
    const cat = String(sel.category_label || sel.category || '').toUpperCase();
    const inten = sel.intensity != null ? ` (.${String(Math.round(sel.intensity * 100)).padStart(2, '0')})` : '';
    return `${cat ? cat + ' - ' : ''}${sel.label || sel.id || ''}${inten}`;
  }
  if (ev.family === 'TOPIC') return sel.id === 'NONE' ? 'nothing off the board' : `"${sel.label || sel.id}"`;
  return String(sel.label || sel.id || line.text || '');
}
function sheetMark(conv) {
  const sheet = String(((conv || {}).plan || {}).sheet || '').trim();
  return sheet ? (sheet.split('\n').map(x => x.trim()).filter(x => x.length > 24)[0] || '') : '';
}
function rolodexRows(conv, api, opts = {}) {
  const turns = (conv && conv.turns) || [];
  const byTurn = new Map(turns.map(t => [t.turn_id, t]));
  const sheet = String(((conv || {}).plan || {}).sheet || '');
  const mine = opts.turns instanceof Set ? opts.turns : (opts.turn ? new Set([String(opts.turn.turn_id || '')]) : null);
  const evs = ((conv && conv.decision_events) || []).filter(e => !e.stage);
  const rows = [];
  for (const ev of evs) {
    const t = byTurn.get(ev.turn_id) || null;
    const line = eventLine(ev, conv);
    const sel = ev.selected || {};
    const item = stage(ev, 'item'), cat = stage(ev, 'category'), tab = stage(ev, 'table'), inten = stage(ev, 'intensity'), dice = stage(ev, 'dice'), place = stage(ev, 'placement');
    const face = die(line.dice);
    const sb = sbOutcome(ev);
    if (sb && !sb.won) { face.classList.add('miss'); face.title = sb.why; }
    const node = t ? `node "${t.step_label || t.step}" - message ${t.index + 1}, ${t.name || t.speaker}`
      : ev.family === 'VARIANT' ? 'the round itself - which structure runs' : ev.family === 'TOPIC' ? 'the round itself - the topics board' : 'the round itself';
    const what = (FAMILY_WHAT[ev.family] || [ev.family, 'A roll System 3 made for this round.'])[1];
    const told = String(sel.text || '').trim();
    const row = t ? sheetRowOf(sheet, t) : '';
    const perf = (t && ev.family === 'ES' && t.performance) || null;
    const facts = [];
    if (tab && tab.draw) facts.push(['table', `${tab.selected} - d100 ${tab.draw.dice}, ${tab.selected_index} of ${tab.of}`]);
    else if (sel.table) facts.push(['table', sel.table]);
    if (cat) facts.push(['category', `${cat.selected}${cat.draw ? ` - d100 ${cat.draw.dice}` : ''}${cat.of ? `, ${cat.selected_index} of ${cat.of}` : ''}`]);
    if (item) facts.push(['item', `${item.selected}${item.draw ? ` - d100 ${item.draw.dice}` : ''}${item.of ? `, ${item.selected_index} of ${item.of}` : ''}`]);
    if (inten) facts.push(['intensity', `${num(inten.selected)}${inten.draw ? ` - d100 ${inten.draw.dice}` : ''}`]);
    if (dice) facts.push([ev.family === 'SFX' ? 'clip' : 'dice', `${dice.selected}${dice.draw ? ` - d100 ${dice.draw.dice}` : ''}${dice.threshold != null ? ` against ${num(dice.threshold, dice.threshold > 1 ? 0 : 2)}` : ''}`]);
    if (place) facts.push(['placement', String(place.selected || '')]);
    if (ev.rng) facts.push(['u', `${num(ev.rng.u, 6)} (${ev.rng.label || ''})`]);
    const cands = (item && item.candidates) || (cat && !item ? cat.candidates : []) || [];
    const hitId = item ? item.selected : cat ? cat.selected : null;
    const body = el('div', 's3-rx-body',
      para(what, 's3-muted'),
      facts.length ? kv(facts) : null,
      told ? el('div', 's3-rx-told', el('b', {text: 'The command to the writer: '}), told) : null,
      row ? el('div', 's3-story-row', el('b', {text: 'The row it made in the running order: '}), row.trim()) : null,
      perf ? el('div', {class: 's3-muted', text: `For the voice: ${perf.emotion || ''}` + (perf.intensity != null ? ` at ${num(perf.intensity)}` : '') + (perf.pace ? `, pace ${perf.pace}` : '') + (perf.pause_style ? `, pauses ${perf.pause_style}` : '')}) : null,
      ...((ev.stages || []).map(st => el('details', {class: 's3-rx-cands-fold', open: true},
        el('summary', {text: `${st.stage || 'draw'}: ${(st.candidates || []).length} options; ${(st.excluded || []).length} excluded`}),
        drumAnimated2(st.candidates || [], st.selected), ...stageStory(st, ev, conv, t)))),
      ev.meta ? kv(Object.entries(ev.meta).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)])) : null,
      el('div', 's3-row', btn('How this was decided', () => openDecision(conv, ev, t, api), {class: 's3-rx-how'})));
    const d = el('details', {class: 's3-rx' + (mine ? (mine.has(String(ev.turn_id || '')) ? ' mine' : ' other') : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`},
      el('summary', {class: 's3-rx-row', title: line.text}, el('span', {class: 's3-rx-tick', 'aria-hidden': 'true'}),
        el('span', {class: 's3-dfam', text: ev.family}),
        el('span', 's3-rx-what', el('b', {text: landedWords(ev, conv)}), el('span', {class: 's3-muted', text: ' - ' + node})),
        face),
      body);
    d.face = face;
    rows.push(d);
  }
  const wrap = el('div', 's3-rx-list', ...rows);
  if (!rows.length) wrap.append(para('No roll was recorded on this round.', 's3-muted'));
  wrap.roll = () => { rows.forEach((d, k) => { if (d.face && d.face.roll) d.face.roll(reduced() ? 0 : 600 + (k % 6) * 110); }); };
  return wrap;
}
/* rounds read for the Rolodex, kept a minute: a tile opened twice, or two
   beats of one round, do not fetch the round again */
const CONV_CACHE = new Map();
async function cachedConversation(request, cid) {
  const hit = CONV_CACHE.get(cid);
  if (hit && Date.now() - hit.at < 60000) return hit.conv;
  const conv = await request('/api/system3/conversation/' + encodeURIComponent(cid));
  if (CONV_CACHE.size > 40) CONV_CACHE.delete(CONV_CACHE.keys().next().value);
  CONV_CACHE.set(cid, {at: Date.now(), conv});
  return conv;
}
function rolodexNone(r) {
  const p = String((r || {}).purpose || '');
  if (/vision/i.test(p)) return 'No Rolodex on this call: it is the station reading a picture (a vision call), not a writer call. The gallery round that follows is planned by System 3, and its rolls sit on the writer call after this one.';
  if (/writ/i.test(p)) return 'No System 3 round was planned in the fifteen minutes before this writer call - a road System 3 does not write yet.';
  return 'No Rolodex on this call: not a writer call (' + (p || 'no purpose recorded') + '). System 3 rolls only for the rounds it plans; the writer call for a round carries them.';
}

/* ======================================================================== */
/* [s3-line-tabs] A TAPPED MESSAGE, OPENED INTO ITS PARTS.
 *
 * "when i tap a message, I want this popup to have tabs for showing.
 *  system 3 - the rolodox and dice animated result for the dialog selected
 *  node view - the node that the dialog was created from
 *  prompt view - the prompt that created the message and the exchange with
 *    the ability to scroll back and forth on messages
 *  table view - the tables that built up the result along with the dice
 *    rolls that got them and sliders to adjust the values for the next
 *    time and the ability to scroll back and forth on nodes"
 *
 * One cursor for all four panes: the round the line belongs to and the
 * turn it is. The message arrows move the cursor along the round's turns;
 * the node arrows (Tables) move it along the turn's draws. Everything
 * shown is what was recorded: the events, the dice, the structure the
 * round was planned from, the model call whose prompt carries this round's
 * running order. A weight moved here is saved through the same door as the
 * Tables tab - a new config version; the round keeps the one it was
 * planned under. */
function lineOfTurn(conv, t) {
  if (!conv || !t) return '';
  const row = (conv.lines || []).find(l => l.turn_id === t.turn_id);
  return row ? String(row.line_id || '') : '';
}

/* The structure a round's turn was planned from: the desk's current copy
   of the road's structure (or the variant the VARIANT roll chose), with
   the node the turn names. The round keeps the version it was planned
   under; when the desk has moved on, the pane says so. */
function turnNode(conv, t, config) {
  const cfg = (config && config.config) || {};
  const road = String(((conv || {}).identity || {}).road_kind || '');
  const rs = (conv || {}).road_structure || {};
  const variant = ((conv || {}).variant_roll || {}).structure || '';
  const cycle = !rs.id && (road === 'banter' || !road);
  const key = variant || road;
  const st = cycle ? (cfg.structure || {}) : ((cfg.structures || {})[key] || null);
  const nodes = cycle ? (st.steps || []) : ((st && st.legs) || []);
  const src = (t && t.split_of && ((conv || {}).turns || []).find(x => x.turn_id === t.split_of)) || t;   /* [s3-split] a part taken over is its read's node */
  const wanted = String((src || {}).leg || (src || {}).step || '');
  let index = nodes.findIndex(n => String(n.id || '') === wanted);
  if (index < 0 && nodes.length) index = nodes.findIndex(n => String(n.label || '') === String((t || {}).step_label || ''));
  return {cycle, key, structure: st, nodes, index, node: index >= 0 ? nodes[index] : null,
    moved: !!(st && rs.version && st.version && Number(st.version) !== Number(rs.version)),
    version: rs.version, now: st && st.version};
}

/* A node card in the segments editor's dress, read-only, with the dice this
   turn rolled on each of its draws. */
function nodeCard(conv, t, info, api, opts = {}) {
  const n = info.node || {id: t.step, label: t.step_label, place: t.place, seat: t.speaker, act: t.protocol,
    draws: (t.decisions || []).map(d => ({family: d.family}))};
  const evs = turnEvents(conv, t);
  const byFam = new Map();
  for (const ev of evs) { if (!byFam.has(ev.family)) byFam.set(ev.family, []); byFam.get(ev.family).push(ev); }
  const head = el('div', 's3-row', el('b', {text: n.label || n.id || (info.cycle ? 'step' : 'leg')}),
    info.cycle ? el('span', {class: 's3-pill', text: String(n.speaker || t.speaker || '').replace('_', ' ')}) : el('span', {class: 's3-pill', text: n.place || t.place || 'middle'}),
    info.cycle ? null : el('span', {class: 's3-pill', text: n.seat === 'alternate' ? 'alternating - ' + t.speaker + ' here' : 'seat ' + (n.seat || t.speaker || 'A')}),
    ...(n.speakerbox || []).map(m => el('span', {class: 's3-pill', style: `border-color:${FAM.SPEAKERBOX}`, text: m})),
    el('span', {style: 'flex:1'}),
    el('span', {class: 's3-muted', text: opts.where || ''}));
  const draws = el('div', 's3-row');
  const used = new Set();
  const liveChip = (d, ev) => {
    const line = ev ? eventLine(ev, conv) : null;
    const pinned = d && d.fixed !== undefined;
    return el('span', {class: 's3-draw' + (pinned ? ' locked' : '') + (ev ? ' s3-draw-live' : ''), style: `--fam:${FAM[(d || ev).family] || 'var(--obs)'}`,
      title: ev ? line.text + ' - tap for how it was decided' : pinned ? 'roulette off: pinned to ' + d.fixed : 'no roll recorded on this draw',
      role: ev ? 'button' : null, tabindex: ev ? '0' : null,
      onclick: ev ? () => openDecision(conv, ev, t, api) : null,
      onkeydown: ev ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDecision(conv, ev, t, api); } } : null},
      el('span', {class: 's3-dice', text: pinned ? 'pin' : (line && line.dice != null ? String(line.dice) : 'd100')}),
      (d || ev).family + (d && d.tables ? ':' + d.tables.join('/') : '') + (d && d.closes ? ' closes' : ''),
      ev ? el('span', {class: 's3-draw-got', text: '→ ' + landedWords(ev, conv)}) : null);
  };
  for (const d of n.draws || []) {
    const list = byFam.get(d.family) || [];
    const ev = list.find(e => !used.has(e.event_id)) || null;
    if (ev) used.add(ev.event_id);
    draws.append(liveChip(d, ev));
  }
  for (const ev of evs) if (!used.has(ev.event_id)) draws.append(liveChip(null, ev));
  if (!(n.draws || []).length && !evs.length) draws.append(el('span', {class: 's3-muted', text: 'no draws on this node'}));
  return el('div', {class: 's3-seg-node s3-node-card' + (opts.sel ? ' sel' : '')}, head,
    info.cycle ? null : el('div', {class: 's3-muted s3-node-act', text: n.act || t.protocol || ''}), draws);
}

/* THE TABLE A DRAW CAME FROM, with the landed item lit, the effective
   weights the engine used, and sliders on the desk's copy for next time. */
function tableStory(conv, ev, t, config, api, send, onSaved) {
  const cfg = (config && config.config) || {};
  const sel = ev.selected || {};
  const table = (cfg.tables || []).find(x => x.id === sel.table) || null;
  const item = stage(ev, 'item'), cat = stage(ev, 'category'), tab = stage(ev, 'table');
  const line = eventLine(ev, conv);
  const dieRow = (label, st) => {
    if (!st || !st.draw) return null;
    const of = st.of ? ` - ${st.selected_index || '?'} of ${st.of}` : '';
    return el('div', 's3-tstory-die', el('span', {class: 's3-muted', text: label}), die(st.draw.dice),
      el('b', {text: String(st.selected == null ? '' : st.selected) + of}));
  };
  const rows = [dieRow('table', tab), dieRow('category', cat), dieRow('item', item), dieRow('intensity', stage(ev, 'intensity')),
    dieRow(ev.family === 'SFX' ? 'clip' : 'dice', stage(ev, 'dice')), dieRow('placement', stage(ev, 'placement'))].filter(Boolean);
  if (!rows.length && ev.rng) rows.push(el('div', 's3-tstory-die', el('span', {class: 's3-muted', text: 'd100'}), die(ev.rng.dice), el('b', {text: line.text})));
  const head = el('div', 's3-dhead', el('span', {class: 's3-dfam', text: ev.family}),
    el('div', null, el('b', {text: (FAMILY_WHAT[ev.family] || [ev.family])[0]}), el('div', {class: 's3-muted', text: line.text})));
  const out = el('div', {class: 's3-dcard s3-tstory', style: `--fam:${FAM[ev.family] || 'var(--obs)'}`}, head, el('div', 's3-tstory-dice', ...rows),
    btn('How this was decided', () => openDecision(conv, ev, t, api), {class: 's3-tstory-how'}));
  if (!table) {
    const cands = (item && item.candidates) || [];
    if (cands.length) {
      out.append(sectionOf('The candidates in the draw (no desk table behind this one)', el('div', 's3-rx-cands',
        ...cands.map(c => el('div', {class: 's3-rx-cand' + (c.id === item.selected ? ' hit' : '')},
          el('b', {text: c.label || c.id}), el('span', {class: 's3-muted', text: `w ${num(c.weight)} - ${pct(c.p)}`}))))));
    } else {
      out.append(para(ev.family === 'SFX' ? 'A chance, not a table: the clip odds were built from the dials and this line.'
        : ev.family === 'SPEAKERBOX' ? 'A chance against your speaker-box dial, not a table.'
        : 'This draw did not come from a desk table.', 's3-muted'));
    }
    return out;
  }
  const draft = JSON.parse(JSON.stringify(table));
  const eff = new Map(((item && item.candidates) || []).map(c => [c.id, c]));
  const effCat = new Map(((cat && cat.candidates) || []).map(c => [c.id, c]));
  const note = el('span', {class: 's3-muted', text: `${draft.id} - ${draft.label || ''} - version ${draft.version || '?'} on the desk`});
  const save = btn('Save ' + draft.id + ' for next time', async () => {
    save.disabled = true;
    try {
      await send('/api/system3/tables/' + encodeURIComponent(draft.id), 'PUT', draft);
      note.textContent = 'saved - a new config version; this round keeps the one it was planned under';
      if (onSaved) await onSaved();
    } catch (e) { note.textContent = 'not saved: ' + ((e && e.message) || e); save.disabled = false; }
  }, {disabled: true});
  const dirty = () => { save.disabled = false; note.textContent = 'moved - not saved yet'; };
  const slider = (value, set, max = 5) => {
    const o = el('span', {text: num(value)});
    return [el('input', {type: 'range', min: 0, max, step: 0.05, value, 'aria-label': 'weight', oninput: e => { set(+e.target.value); o.textContent = num(+e.target.value); dirty(); }}), o];
  };
  const body = el('div', 's3-tstory-table');
  for (const c of draft.categories || []) {
    const hitCat = c.id === sel.category;
    const ec = effCat.get(c.id);
    const box = el('details', {class: 's3-cat s3-tstory-cat' + (hitCat ? ' hit' : ''), open: hitCat});
    box.append(el('summary', null, el('b', {text: c.label || c.id}),
      el('span', {class: 's3-muted', text: `${(c.items || []).length} items - w${num(c.weight)}` + (ec ? ` - in the draw: ${num(ec.weight)} (${pct(ec.p)})` : '')}),
      hitCat && cat && cat.draw ? el('span', {class: 's3-pill hit', text: 'landed - d100 ' + cat.draw.dice}) : null));
    box.append(el('div', 's3-slider', el('label', null, el('b', {text: 'category weight'})), ...slider(c.weight, v => { c.weight = v; })));
    for (const it of c.items || []) {
      const hit = it.id === sel.id;
      const e = eff.get(it.id);
      box.append(el('div', {class: 's3-tstory-item' + (hit ? ' hit' : '') + (it.enabled === false ? ' off' : '')},
        el('div', 's3-tstory-item-head', hit && item && item.draw ? die(item.draw.dice) : el('span', {class: 's3-die none', text: '—'}),
          el('b', {text: it.label || it.id}), el('span', {class: 's3-muted', text: e ? `in the draw: w ${num(e.weight)} - ${pct(e.p)}` + ((e.why || []).length ? ' - ' + e.why.join('; ') : '') : (hitCat ? 'not in this draw' : '')})),
        el('div', 's3-slider', el('label', {class: 's3-muted', text: 'weight next time'}), ...slider(it.weight == null ? 1 : it.weight, v => { it.weight = v; })),
        it.text ? el('div', {class: 's3-muted s3-tstory-text', text: it.text}) : null));
    }
    body.append(box);
  }
  out.append(sectionOf(`The table: ${draft.id} - ${draft.label || ''}`, body), el('div', 's3-row', save, note));
  return out;
}

/* THE MODEL CALL THAT WROTE THE ROUND: the writer call whose prompt carries
   this round's running order, found in the prompt history by time and
   proven by its words. Pages back through the history until it is past
   the round's planning time. */
function promptText(d) {
  const req = (d && d.request) || {};
  const msgs = Array.isArray(req.messages) ? req.messages : [];
  return msgs.map(m => String((m && m.content) || '')).join('\n\n') || String(req.prompt || '');
}
function promptParts(d) {
  const req = (d && d.request) || {};
  const msgs = Array.isArray(req.messages) ? req.messages : [];
  const sys = msgs.filter(m => m.role === 'system').map(m => m.content).join('\n\n') || req.system || '';
  const user = msgs.filter(m => m.role !== 'system').map(m => (m.role ? m.role + ': ' : '') + (m.content || '')).join('\n\n') || req.prompt || '';
  const res = (d && d.response) || {};
  const text = (res.message && res.message.content) || res.response || res.text || (typeof res === 'string' ? res : '');
  const opts = {model: req.model, ...(req.options || {}), think: req.think, keep_alive: req.keep_alive, stream: req.stream};
  return {sys, user, text, opts};
}
/* Human-readable display only. The original request remains available below
   every rendering, and this never changes the bytes sent to the model. */
function readablePromptText(value) {
  const raw = String(value || '').trim();
  if (!raw) return para('(none)', 's3-muted');
  const out = el('div', 's3-vp-readable');
  const field = (name, val, depth = 0) => {
    if (val && typeof val === 'object' && depth < 8) {
      const pairs = Object.entries(val);
      return el('details', {class: 's3-vp-json', open: depth < 2},
        el('summary', {text: `${name} · ${pairs.length} ${Array.isArray(val) ? 'items' : 'fields'}`}),
        el('div', 's3-vp-json-in', ...pairs.map(([k, v]) => field(k, v, depth + 1))));
    }
    return el('div', 's3-vp-field', el('b', {text: name}), el('span', {text: val == null ? '(empty)' : String(val)}));
  };
  const parse = text => { try { return JSON.parse(text); } catch (_) { return null; } };
  const entire = parse(raw);
  if (entire && typeof entire === 'object') out.append(field('Prompt data', entire));
  else {
    const chunks = raw.split(/(```(?:json)?\s*[\s\S]*?```)/g).filter(Boolean);
    for (const chunk of chunks) {
      const fenced = chunk.startsWith('```');
      const data = parse(fenced ? chunk.replace(/^```(?:json)?\s*|\s*```$/g, '') : chunk.trim());
      if (data && typeof data === 'object') { out.append(field('Prompt data', data)); continue; }
      if (fenced) { out.append(el('pre', {text: chunk})); continue; }
      for (const part of chunk.split(/\n\s*\n/).filter(Boolean)) {
        const lines = part.split('\n').map(s => s.trim()).filter(Boolean);
        if (!lines.length) continue;
        const heading = lines.length > 1 && lines[0].length < 110 && (/:$/.test(lines[0]) || /^[A-Z][A-Z\s\/–—-]{5,}$/.test(lines[0]));
        out.append(el('section', 's3-vp-prose', heading ? el('h4', {text: lines.shift()}) : null,
          el('div', {text: lines.join('\n')})));
      }
    }
  }
  out.append(el('details', 's3-vp-raw', el('summary', {text: 'Original captured text'}), el('pre', {text: raw})));
  return out;
}
const NO_SYSTEM = '(none - this call sends everything as one user message; the station builds no system message for it)';
const normWs = text => String(text || '').replace(/\s+/g, ' ').trim();
/* The message's own row of the running order, as a prompt would carry it:
   whitespace collapsed, the first 88 characters - rows share a template
   prefix ("answers what Host just said, feeling"), the feeling and the act
   tell them apart. */
function rowHead(conv, t) {
  const row = normWs(sheetRowOf(String(((conv || {}).plan || {}).sheet || ''), t));
  return row.length > 12 ? row.slice(0, 88) : '';
}
const WRITER_PURPOSE = /beat|round|caller|writ/i;
/* The rows of a running order as a prompt carries them, whitespace
   collapsed: "N S - words", each running to the next row. */
function rowSegments(text) {
  const re = /(?:^|\s)(\d{1,2}) ([A-E]) [-\u2013\u2014] /g;
  const found = [];
  let m;
  while ((m = re.exec(text))) found.push({n: Number(m[1]), seat: m[2], at: m.index + (m[0].charAt(0) === ' ' ? 1 : 0), end: re.lastIndex});
  return found.map((r, i) => ({...r, text: text.slice(r.end, i + 1 < found.length ? found[i + 1].at : Math.min(text.length, r.end + 600))}));
}
/* A message's row in a prompt, proven by the turn's own decisions: the row
   with its number and seat carries the emotion the ES roll set and one of
   its acts (RS / IRS / FL). A beat in turn mode writes its rows from the
   turns as they stand, so the round's sheet may not carry them word for
   word; the decisions do. */
function turnRowIn(text, conv, t, segs) {
  segs = segs || rowSegments(text);
  const seg = segs.find(r => r.n === t.index + 1 && r.seat === t.speaker);
  if (!seg) return '';
  const low = seg.text.toLowerCase();
  const es = (t.decisions || []).find(d => d.family === 'ES');
  const acts = (t.decisions || []).filter(d => ['RS', 'IRS', 'FL'].includes(d.family));
  if (!es && !acts.length) return '';
  if (es && es.label && !low.includes(String(es.label).toLowerCase())) return '';
  if (acts.length) {
    const evs = new Map(((conv || {}).decision_events || []).map(e => [e.event_id, e]));
    const ok = acts.some(a => {
      const ev = evs.get(a.event_id);
      return [((ev || {}).selected || {}).text, a.label].filter(Boolean).map(x => String(x).toLowerCase()).some(w => w.length > 3 && low.includes(w));
    });
    if (!ok) return '';
  }
  return `${seg.n} ${seg.seat} - ${seg.text}`.trim();
}
/* The calls in the prompt history from the round's planning time on, for
   forty minutes: a banter round in turn mode is written a beat at a time. */
async function callsSince(request, created, span = 2400) {
  const cands = [];
  let before = 0;
  for (let page = 0; page < 10; page += 1) {
    let got;
    try { got = await request('/api/prompt-history?limit=100' + (before ? '&before=' + before : '')); } catch (e) { break; }
    const rows = (got && got.rows) || [];
    if (!rows.length) break;
    for (const r of rows) { const at = Number(r.at || 0); if (at >= created - 3 && at <= created + span) cands.push(r); }
    if (Number(rows[rows.length - 1].at || 0) < created - 3 || !got.next) break;
    before = got.next;
  }
  cands.sort((a, b) => Number(a.at) - Number(b.at));
  const writers = cands.filter(r => WRITER_PURPOSE.test(String(r.purpose || '')));
  return writers.concat(cands.filter(r => !writers.includes(r)));
}
async function callDetail(request, r, cache) {
  if (cache && cache.has(r.id)) return cache.get(r.id);
  let d = null;
  try { const got = await request('/api/prompt-history/' + encodeURIComponent(r.id)); d = got.row || got; } catch (e) { d = null; }
  if (cache && d) cache.set(r.id, d);
  return d;
}
/* THE MODEL CALL THAT WROTE THIS MESSAGE: the first call after the round
   was planned whose prompt carries the message's own row of the running
   order (a beat, or the whole round); failing that the call carrying the
   round's head line; failing that the nearest writer call by time. */
async function findWriterCall(request, conv, turn = null, cache = null) {
  const created = Number((conv || {}).created || 0);
  if (!created) return {row: null, detail: null, why: 'the round has no planning time on record'};
  const mark = normWs(sheetMark(conv));
  const head = turn ? rowHead(conv, turn) : '';
  const order = await callsSince(request, created);
  let roundHit = null, looked = 0;
  for (const r of order) {
    if (looked >= 24) break;
    looked += 1;
    const d = await callDetail(request, r, cache);
    if (!d) continue;
    const text = normWs(promptText(d));
    if (head && text.includes(head)) return {row: r, detail: d, why: 'its prompt carries this message\'s row of the running order', exact: true};
    if (turn && turnRowIn(text, conv, turn)) return {row: r, detail: d, why: 'its prompt carries this message\'s row of the running order, as the beat wrote it from the turn\'s own rolls', exact: true};
    if (!roundHit && mark && text.includes(mark)) roundHit = {row: r, detail: d};
  }
  if (roundHit) return {row: roundHit.row, detail: roundHit.detail, exact: !head,
    why: head ? 'its prompt carries this round\'s running order (this message\'s own row is not in it word for word - the round was re-planned after the call, or the row was rewritten)' : 'its prompt carries this round\'s running order'};
  const writers = order.filter(r => WRITER_PURPOSE.test(String(r.purpose || '')));
  if (writers.length) {
    const r = writers[0];
    const d = await callDetail(request, r, cache);
    return {row: r, detail: d, exact: false, why: `the nearest writer call, ${num(Number(r.at) - created, 1)} s after the round was planned - its prompt carries neither this message's row nor the round's running order word for word (re-planned or re-written after it was sent)`};
  }
  return {row: null, detail: null, why: 'no writer call in the prompt history after this round was planned - a road System 3 plans but does not write through the writers\' door, or the history was trimmed'};
}

/* [s3-prompt-fold] THE PROMPT BEHIND THE LINE, UNDER THE ROLODEX.
 *
 * "put a section on the system 3 tab below the rolodex able to be expanded
 *  with a tri that shows the prompt to the LLM for generating the content
 *  (if applicable) and also the system prompt able to be read and edited"
 *
 * Folded shut until opened. Open, it finds the call that wrote this
 * message (findWriterCall - proven by the message's row) and shows the
 * prompt with the row marked, the system prompt as it was sent, and then
 * the layers the station builds a system prompt from - the station's
 * standing instructions (the station_system layer of the radio prompt
 * desk, with its on/off) and the persona of the seat that spoke - each a
 * textarea saved through /api/prompt-history/config, the desk's own door:
 * a save is for future calls, historical calls are unchanged, and a value
 * that moved under the editor is refused (409) rather than overwritten. */
const SEAT_PERSONA = {A: ['dj', 'persona'], B: ['dj', 'cohost_persona'], D: ['dj', 'third_persona']};
const SEAT_KEY = {A: 'dj', B: 'cohost', D: 'third'};
const SEAT_WORDS = {A: 'the host', B: 'the co-host', D: 'the third seat'};
/* [s3-blocks] every block of a prompt, as System 3 decided it: sent (an
   obligation, a roll that hit, a tint block while the tint is on) or stripped
   (switched off, a roll that missed, a wedge no node claims) - with its reason */
function promptBlocksBox(request, userText) {
  const box = el('div', 's3-tile-box s3-blocks', el('h4', {text: 'Every block of this prompt, as System 3 decided it'}),
    para('Asking System 3...', 's3-muted'));
  (async () => {
    let got;
    try { got = await request('/api/system3/prompt-blocks', {method: 'POST', body: JSON.stringify({text: String(userText || '')})}); }
    catch (e) { fill(box, el('h4', {text: 'Every block of this prompt'}), para('System 3 could not be asked: ' + ((e && e.message) || e), 's3-error')); return; }
    const rows = ((got && got.prompt && got.prompt.blocks) || []);
    if (!rows.length) {
      fill(box, el('h4', {text: 'Every block of this prompt'}), para(got && got.prompt ? 'This prompt carried no marked blocks.'
        : 'System 3 holds no block record for this prompt - it was written before prompt blocks were nodes, or on a road System 3 does not decide.', 's3-muted'));
      return;
    }
    const rules = (got && got.rules) || {};
    fill(box, el('h4', {text: `Every block of this prompt, as System 3 decided it (${rows.filter(b => b.keep).length} sent, ${rows.filter(b => !b.keep).length} stripped)`}),
      ...rows.map(b => el('div', 's3-block ' + (b.keep ? 's3-block-kept' : 's3-block-stripped'),
        el('div', 's3-row', el('b', {text: b.label || b.name}),
          el('span', {class: 's3-pill', text: b.kind === 'wedge' ? 'wedge - no node' : b.kind}),
          el('span', {class: 's3-muted', text: (b.keep ? 'sent' : 'stripped') + ' - ' + (b.why || '')}),
          el('span', {class: 's3-muted', text: (rules[b.name] && rules[b.name].helper) ? 'from ' + rules[b.name].helper : 'helper: ' + b.name})),
        !b.keep && b.text ? el('div', 's3-block-text', b.text) : null)));
  })();
  return box;
}

function promptFold(request, state, conv, t, opts = {}) {
  const send = (path, method, body) => request(path, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  const body = el('div', 's3-pfold-body');
  const fold = el('details', {class: 's3-dsec s3-pfold', open: !!opts.open},
    el('summary', {text: 'The prompt to the writer, and the system prompt - read it, edit the layers it is built from'}), body);
  let painted = false;
  const paint = async () => {
    if (painted) return;
    painted = true;
    fill(body, para('Looking for the model call that wrote this message...', 's3-muted'));
    if (!state.writerByTurn.has(t.turn_id)) state.writerByTurn.set(t.turn_id, await findWriterCall(request, conv, t, state.callCache));
    if (!body.isConnected) { painted = false; return; }
    const w = state.writerByTurn.get(t.turn_id) || {};
    const parts = w.row ? promptParts(w.detail || {}) : null;
    const inPrompt = w.row ? sheetRowOf(promptText(w.detail || {}), t).trim() : '';
    const call = w.row ? el('div', 's3-pfold-call',
      el('div', 's3-row', el('b', {text: `${w.row.model || '?'} - ${w.row.purpose || ''}`}), el('span', {class: 's3-state s3-state-' + (w.row.state || 'done'), text: w.row.state || ''}),
        el('span', {class: 's3-muted', text: day(Number(w.row.at || 0)) + (w.row.finished && w.row.at ? ` - took ${num(Number(w.row.finished) - Number(w.row.at), 1)} s` : '')}),
        el('span', {class: 's3-pill ' + (w.exact ? 'active' : 'shadow'), text: w.exact ? 'proven by its words' : 'nearest by time'}),
        el('span', {class: 's3-muted', text: w.why || ''})),
      inPrompt ? el('div', 's3-story-row', el('b', {text: 'This turn in the captured prompt: '}), inPrompt) : null,
      el('div', 's3-tile-grid',
        el('div', 's3-tile-box', el('h4', {text: 'The prompt to the writer'}), readablePromptText(parts.user)),
        el('div', 's3-tile-box', el('h4', {text: 'The system prompt, as it was sent'}), readablePromptText(parts.sys || (parts.user ? NO_SYSTEM : '(none)')))),
      parts.user ? promptBlocksBox(request, parts.user) : null)   /* [s3-blocks] */
      : para((w.why ? 'No prompt for this message: ' + w.why : 'No prompt for this message.') + ' The layers below still build the system prompt of the next call.', 's3-muted');
    /* the editable layers, from the desk's own door */
    const layers = el('div', 's3-pfold-layers', para('Reading the prompt layers...', 's3-muted'));
    fill(body, call, sectionOf('The layers the system prompt is built from - edit for future calls', layers));
    let cfg;
    try { cfg = await request('/api/prompt-history/config'); } catch (e) { fill(layers, para('The prompt layers could not be read: ' + ((e && e.message) || e), 's3-error')); return; }
    if (!layers.isConnected) return;
    const nodes = (cfg && cfg.nodes) || [];
    const nodeAt = path => nodes.find(n => JSON.stringify(n.path) === JSON.stringify(path)) || null;
    /* one layer: the current text, a textarea, a save through the inspector's
       own door (/api/paperwork/field - the same store the inspector edits,
       receipted in the station's actions) */
    const editor = (current, title, help, scope, key) => {
      let was = String(current || '');
      const area = el('textarea', {value: was, rows: 6, 'aria-label': title});
      const note = el('span', {class: 's3-muted', text: help || ''});
      const save = btn('Save for future calls', async () => {
        save.disabled = true;
        try {
          const got = await send('/api/paperwork/field', 'POST', {scope, key, value: area.value, was, line_id: opts.lineId || '', apply: 'future'});
          was = area.value;
          note.textContent = (got && got.say) || 'saved for future calls';
        } catch (e) { note.textContent = 'Not saved: ' + String((e && e.message) || e); }
        save.disabled = false;
      });
      return el('div', 's3-pfold-layer', el('h4', {text: title}), area, el('div', 's3-row', save, note));
    };
    const toggle = (node, title) => {
      if (!node) return null;
      let was = node.value;
      const note = el('span', {class: 's3-muted', text: ''});
      const box = el('input', {type: 'checkbox', checked: node.value === true, onchange: async e => {
        const value = !!e.target.checked;
        try { const got = await send('/api/prompt-history/config', 'POST', {path: node.path, value, was}); was = value; node.value = value; note.textContent = (got && got.say) || 'saved'; }
        catch (err) { e.target.checked = was === true; note.textContent = 'not saved: ' + String((err && err.message) || err); }
      }});
      return el('label', 's3-row', box, title, note);
    };
    const seat = String(t.speaker || 'A');
    const personaPath = SEAT_PERSONA[seat] || null;
    const personaNode = personaPath ? nodeAt(personaPath) : null;
    const stationNode = nodeAt(['dj', 'radio_prompt_overrides', 'station_system']);
    fill(layers,
      editor(stationNode ? stationNode.value : '', 'The station\'s standing instructions (the station system prompt)',
        'Folded into every writer\'s head when the station follows its prompt; empty means the pair are simply themselves.', 'station', ''),
      toggle(nodeAt(['dj', 'radio_prompt_enabled', 'station_system']), 'the station system layer is on'),
      personaPath ? editor(personaNode ? personaNode.value : '', `The persona of ${SEAT_WORDS[seat] || 'seat ' + seat} - ${t.name || seat}`, 'The character this seat is written as.', 'persona', SEAT_KEY[seat])
        : para(`Seat ${seat} has no persona setting on the desk.`, 's3-muted'),
      para('Every save goes through the inspector\'s own door: kept for future calls and receipted in the station\'s actions. Calls already made keep the prompt they had.', 's3-muted'));
  };
  fold.addEventListener('toggle', () => { if (fold.open) paint(); });
  if (opts.open) paint();
  return fold;
}

export async function mountLineTabs(root, {request, lineId = '', tab = 'system3', onLine = null, onSaved = null} = {}) {
  request ||= defaultRequest();
  const send = (path, method, body) => request(path, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  root.classList.add('s3', 's3-ltabs');
  fill(root, para('Asking System 3 about this line...', 's3-muted'));
  const cur = {lineId: String(lineId || ''), got: null, conv: null, turn: null, node: 0, config: null, writer: null, alive: true};
  const writerByTurn = new Map(), callCache = new Map();
  const foldState = {writerByTurn, callCache};
  const v = makeViews({request});
  v.quiet = true;
  const tell = () => { try { if (typeof onLine === 'function') onLine({lineId: cur.lineId, conv: cur.conv, turn: cur.turn}); } catch (e) { /* the host's own */ } };

  async function load(id) {
    cur.lineId = String(id || '');
    cur.got = null; cur.conv = null; cur.turn = null; cur.node = 0; cur.writer = null;
    try { cur.got = await request('/api/system3/line?line_id=' + encodeURIComponent(cur.lineId)); } catch (e) { cur.got = null; }
    if (cur.got && cur.got.conversation) {
      try { cur.conv = await request('/api/system3/conversation/' + encodeURIComponent(cur.got.conversation.conversation_id)); } catch (e) { cur.conv = null; }
    }
    if (cur.conv) {
      v.setConversation(cur.conv);
      const want = cur.got.turn ? cur.got.turn.turn_id : '';
      cur.turn = (cur.conv.turns || []).find(x => x.turn_id === want) || null;
      if (!cur.turn && cur.got.sfxguy && cur.got.sfxguy.turn) cur.turn = (cur.conv.turns || []).find(x => x.turn_id === cur.got.sfxguy.turn.turn_id) || null;
    }
    if (!cur.config) { try { cur.config = await request('/api/system3/config'); } catch (e) { cur.config = null; } }
    tell();
  }
  const reloadConfig = async () => {
    try { cur.config = await request('/api/system3/config'); } catch (e) { /* keep the old */ }
    if (onSaved) { try { await onSaved(); } catch (e) { /* the host's own */ } }
  };
  const moveTo = (t) => { cur.turn = t; cur.node = 0; cur.lineId = lineOfTurn(cur.conv, t) || cur.lineId; cur.writer = cur.writer; tell(); };

  /* the message arrows: the cursor moves along the round's turns */
  function stepTurn(dir) {
    if (!cur.conv || !cur.turn) return false;
    const turns = cur.conv.turns || [];
    const i = turns.findIndex(x => x.turn_id === cur.turn.turn_id);
    const j = i + dir;
    if (j < 0 || j >= turns.length) return false;
    moveTo(turns[j]);
    return true;
  }
  function turnArrows(cls) {
    const turns = (cur.conv && cur.conv.turns) || [];
    const i = cur.turn ? turns.findIndex(x => x.turn_id === cur.turn.turn_id) : -1;
    return el('div', 's3-ltabs-nav ' + (cls || ''),
      btn('‹ earlier message', () => { if (stepTurn(-1)) paint(); }, {disabled: i <= 0, class: 's3-ltabs-arrow'}),
      el('span', {class: 's3-muted', text: i >= 0 ? `message ${i + 1} of ${turns.length} in this ${String((cur.conv.identity || {}).road_kind || '')} round - ${cur.turn.name || cur.turn.speaker}` : ''}),
      btn('later message ›', () => { if (stepTurn(1)) paint(); }, {disabled: i < 0 || i >= turns.length - 1, class: 's3-ltabs-arrow'}));
  }

  let current = String(tab || 'system3');
  let story = null;
  const panes = {};

  function notDirected() {
    const got = cur.got || {}, conv = cur.conv;
    if (conv && !cur.turn) {
      const who = String((got.line || {}).who || '');
      return para(`Part of a System 3 round (${(conv.identity || {}).road_kind || 'a'} round ${(conv.identity || {}).conversation_id || ''}) but not one of its planned turns: `
        + (who === 'drop' ? 'the SFX Guy\'s line; its draw was not recorded on this row.' : who === 'board' ? 'a board clip. The dice for the clip are on the turn it punctuates.'
          : 'a line the station put into the round at air, which no node made.'), 's3-muted');
    }
    return para('Not directed by System 3. This line came from a road System 3 does not run yet, or from a round written before it was switched on. Nothing was rolled for it, and nothing in its prompt came from the Rolodex.', 's3-muted');
  }

  async function paintSystem3(host) {
    if (story && story.dispose) { try { story.dispose(); } catch (e) { /* gone */ } story = null; }
    const box = el('div');
    fill(host, cur.conv && cur.turn ? turnArrows() : null, box);
    story = await mountLineStory(box, cur.conv && cur.turn ? {request, lineId: cur.lineId, conv: cur.conv, turn: cur.turn} : {request, lineId: cur.lineId});
    if (cur.conv && cur.turn && box.isConnected) {
      /* [s3-prompt-fold] under the Rolodex: the prompt and the system prompt, folded */
      const rolo = [...box.querySelectorAll('.s3-dsec')].find(sec => /^The Rolodex/.test(((sec.querySelector('h3') || {}).textContent) || ''));
      const fold = promptFold(request, foldState, cur.conv, cur.turn, {lineId: cur.lineId});
      if (rolo) rolo.after(fold); else box.append(fold);
    }
  }

  function paintNode(host) {
    if (!cur.conv || !cur.turn) { fill(host, notDirected()); return; }
    const conv = cur.conv, t = cur.turn;
    const info = turnNode(conv, t, cur.config);
    const list = el('div', 's3-seg-nodes s3-ltabs-nodes');
    if (info.nodes.length) {
      info.nodes.forEach((n, i) => {
        if (i === info.index) list.append(nodeCard(conv, t, info, v.api, {sel: true, where: `node ${i + 1} of ${info.nodes.length} - this message`}));
        else {
          const others = (conv.turns || []).filter(x => String(x.leg || x.step || '') === String(n.id || ''));
          const go = () => { if (others.length) { moveTo(others[0]); paint(); } };
          list.append(el('div', {class: 's3-seg-node s3-node-other', role: others.length ? 'button' : null, tabindex: others.length ? '0' : null,
              title: others.length ? 'the message this node made - tap to move there' : 'no message came from this node in this round',
              onclick: go, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }},
            el('div', 's3-row', el('b', {text: n.label || n.id}),
              info.cycle ? el('span', {class: 's3-pill', text: String(n.speaker || '').replace('_', ' ')}) : el('span', {class: 's3-pill', text: n.place || 'middle'}),
              el('span', {style: 'flex:1'}),
              el('span', {class: 's3-muted', text: others.length ? `message${others.length > 1 ? 's' : ''} ${others.map(x => x.index + 1).join(', ')}` : 'not used this round'}),
              ...((n.draws || []).map(d => el('span', {class: 's3-draw' + (d.fixed !== undefined ? ' locked' : ''), style: `--fam:${FAM[d.family] || 'var(--obs)'}`},
                el('span', {class: 's3-dice', text: d.fixed !== undefined ? 'pin' : 'd100'}), d.family))))));
        }
        if (i < info.nodes.length - 1) list.append(el('div', {class: 's3-seg-gap', text: '↓'}));
      });
    } else {
      list.append(nodeCard(conv, t, info, v.api, {sel: true, where: 'as recorded on the turn'}));
    }
    const rs = conv.road_structure || {};
    const stName = info.cycle ? 'the banter cycle' : (rs.id || info.key || '') + (info.key && info.key.includes('~') ? ' (variant ' + info.key + ')' : '');
    const head = el('div', 's3-ltabs-head',
      el('b', {text: `${String((conv.identity || {}).road_kind || '')} round - ${stName}`}),
      el('span', {class: 's3-muted', text: info.node ? `this message came from node "${info.node.label || info.node.id}" (${info.index + 1} of ${info.nodes.length})`
        : `the turn names node "${t.step_label || t.step}", which the desk's copy of the structure no longer has`}),
      info.moved ? el('span', {class: 's3-pill bad', text: `planned under structure version ${info.version}; the desk now holds version ${info.now}`}) : null);
    fill(host, turnArrows(), head, list, el('div', 's3-row',
      btn('Edit this segment in System 3', () => openSystem3({request, tab: 'segments'}), {class: 's3-ltabs-edit'}),
      el('span', {class: 's3-muted', text: 'Tap a die for how that draw was decided. Other nodes: tap to move to the message they made.'})));
    if (!reduced()) {
      host.querySelectorAll('.s3-node-card .s3-draw-live .s3-dice').forEach((d, k) => {
        d.classList.add('rolling');
        setTimeout(() => { d.classList.remove('rolling'); d.classList.add('pop'); setTimeout(() => d.classList.remove('pop'), 400); }, 500 + k * 140);
      });
    }
  }

  async function paintPrompt(host) {
    if (!cur.conv || !cur.turn) { fill(host, notDirected()); return; }
    const conv = cur.conv, t = cur.turn;
    const exchange = el('div', 's3-chat s3-ltabs-exchange');
    for (const x of conv.turns || []) {
      const b = v.bubble(x, {conv});
      if (x.turn_id === t.turn_id) b.classList.add('sel');
      b.addEventListener('click', e => { e.stopPropagation(); moveTo(x); paint(); }, true);
      exchange.append(b);
    }
    const rolodex = rolodexRows(conv, v.api, {turn: t});
    const promptBox = el('div', {class: 's3-muted', text: 'Looking for the model call that wrote this round...'});
    fill(host, turnArrows(), sectionOf('The exchange - tap a message to move to it', exchange),
      sectionOf('Rolodex - every roll behind this prompt; this message\'s rows are lit', rolodex),
      sectionOf('The prompt that created this message', promptBox),
      el('div', 's3-row', btn('Open this round in Visual Prompt', () => openSystem3({request, tab: 'visual', conversationId: conv.identity.conversation_id}))));
    rolodex.roll();
    const mine = exchange.querySelector('.s3-msg.sel');
    if (mine && mine.scrollIntoView) { try { mine.scrollIntoView({block: 'nearest'}); } catch (e) { /* older engine */ } }
    if (!writerByTurn.has(t.turn_id)) writerByTurn.set(t.turn_id, await findWriterCall(request, conv, t, callCache));
    if (!cur.alive || !promptBox.isConnected) return;
    const w = writerByTurn.get(t.turn_id);
    if (!w.row) { fill(promptBox, para(w.why, 's3-muted')); return; }
    const parts = promptParts(w.detail || {});
    /* the row as the writer was given it (a beat rewrites it from the turn as
       it stands), else the round's sheet row */
    const inPrompt = sheetRowOf(promptText(w.detail || {}), t).trim();
    const row = inPrompt || sheetRowOf(String((conv.plan || {}).sheet || ''), t).trim();
    const box = (title, text, hit) => {
      /* the row is marked where the prompt carries it; a beat's copy may
         differ after the first words, so the mark falls back to the head */
      const hits = [hit, hit ? hit.slice(0, 60) : '', hit ? hit.slice(0, 40) : ''].filter(Boolean);
      const found = text ? hits.find(h => text.includes(h)) : '';
      return el('div', 's3-tile-box', el('h4', {text: title}), el('pre', null, ...(found ? markIn(text, found) : [text || '(none)'])));
    };
    const r = w.row;
    fill(promptBox,
      el('div', 's3-row', el('b', {text: `${r.model || '?'} - ${r.purpose || ''}`}), el('span', {class: 's3-state s3-state-' + (r.state || 'done'), text: r.state || ''}),
        el('span', {class: 's3-muted', text: day(Number(r.at || 0)) + (r.finished && r.at ? ` - took ${num(Number(r.finished) - Number(r.at), 1)} s` : '')}),
        el('span', {class: 's3-pill ' + (w.exact ? 'active' : 'shadow'), text: w.exact ? 'proven by its words' : 'nearest by time'}),
        el('span', {class: 's3-muted', text: w.why})),
      row ? el('div', 's3-story-row', el('b', {text: inPrompt ? 'The row the writer was given for this message: ' : 'This message\'s row in the running order (the prompt does not carry it word for word): '}), row) : null,
      el('div', 's3-tile-grid', el('div', 's3-tile-box', el('h4', {text: 'System prompt'}), readablePromptText(parts.sys || (parts.user ? NO_SYSTEM : ''))),
        el('div', 's3-tile-box', el('h4', {text: 'Prompt'}), readablePromptText(parts.user)), box('LLM settings', json(parts.opts)),
        box('Result - what came back', parts.text || (r.state === 'running' ? 'still running' : '(empty)'), String(t.text || '').trim().slice(0, 60))),
      el('div', 's3-row', btn('Open every call in the Prompts tab', () => openSystem3({request, tab: 'prompts'}))),
      promptFold(request, foldState, conv, t, {lineId: cur.lineId}));
  }

  function paintTables(host) {
    if (!cur.conv || !cur.turn) { fill(host, notDirected()); return; }
    const conv = cur.conv, t = cur.turn;
    const evs = turnEvents(conv, t).filter(e => !e.stage);
    if (!evs.length) { fill(host, turnArrows(), para('No roll was recorded on this message.', 's3-muted')); return; }
    cur.node = Math.max(0, Math.min(cur.node, evs.length - 1));
    const ev = evs[cur.node];
    const turns = conv.turns || [];
    const ti = turns.findIndex(x => x.turn_id === t.turn_id);
    const strip = el('div', 's3-ltabs-nodes-strip', ...evs.map((e, i) => {
      const line = eventLine(e, conv);
      return el('button', {type: 'button', class: 's3-draw' + (i === cur.node ? ' sel' : ''), style: `--fam:${FAM[e.family] || 'var(--obs)'}`, title: line.text,
        'aria-pressed': String(i === cur.node), onclick: () => { cur.node = i; paint(); }},
        el('span', {class: 's3-dice', text: line.dice != null ? String(line.dice) : '-'}), e.family);
    }));
    const nav = el('div', 's3-ltabs-nav',
      btn('‹ earlier node', () => { if (cur.node > 0) { cur.node -= 1; paint(); } else if (stepTurn(-1)) { cur.node = 1e9; paint(); } },
        {class: 's3-ltabs-arrow', disabled: cur.node <= 0 && ti <= 0}),
      el('span', {class: 's3-muted', text: `node ${cur.node + 1} of ${evs.length} on message ${t.index + 1} - ${t.name || t.speaker}`}),
      btn('later node ›', () => { if (cur.node < evs.length - 1) { cur.node += 1; paint(); } else if (stepTurn(1)) { cur.node = 0; paint(); } },
        {class: 's3-ltabs-arrow', disabled: cur.node >= evs.length - 1 && (ti < 0 || ti >= turns.length - 1)}));
    fill(host, turnArrows('s3-ltabs-nav-top'), nav, strip, tableStory(conv, ev, t, cur.config, v.api, send, reloadConfig));
    host.querySelectorAll('.s3-tstory .s3-die').forEach((d, k) => { if (d.roll) d.roll(reduced() ? 0 : 600 + k * 120); });
  }

  /* ---- [s3-timing] TIMING AND A PROFILER SNAPSHOT --------------------------
     "how long the command took and ... a profiler snapshot of the performance
     of the system with that line". The clocks of this line from plan to air,
     each step with its own duration; then what the station was doing while
     it was made: the loop stalls in that window (/api/pulse since/until), the
     model calls that overlapped it and how long the one writer lane was held,
     the render, and System 3's own planning and material times. */
  const epoch = x => { const n = Number(x); if (!isFinite(n) || n <= 0) return 0; return n > 1e12 ? n / 1000 : n; };
  const clockOf = x => { const t = epoch(x); if (!t) return typeof x === 'string' && x ? x : ''; const d = new Date(t * 1000); const two = n => (n < 10 ? '0' : '') + n; return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds()); };
  const secs = x => (x == null || !isFinite(x) ? '' : x >= 100 ? Math.round(x) + ' s' : x >= 10 ? x.toFixed(1) + ' s' : x >= 1 ? x.toFixed(2) + ' s' : Math.round(x * 1000) + ' ms');
  async function paintTiming(host) {
    const conv = cur.conv, t = cur.turn;
    fill(host, conv && t ? turnArrows() : null, para('Reading the clocks...', 's3-muted'));
    const soft = pr => pr.then(x => x, () => null);
    const id = encodeURIComponent(cur.lineId);
    const [why, prov] = await Promise.all([soft(request('/api/said/why/' + id)), soft(request('/api/dj/provenance/' + id))]);
    if (!host.isConnected || !cur.alive) return;
    let w = null;
    if (conv && t) {
      if (!writerByTurn.has(t.turn_id)) writerByTurn.set(t.turn_id, await findWriterCall(request, conv, t, callCache));
      w = writerByTurn.get(t.turn_id) || null;
      if (!host.isConnected || !cur.alive) return;
    }
    const planned = conv ? epoch(conv.created) : 0;
    const evAts = conv ? (conv.decision_events || []).map(e => epoch(e.at)).filter(Boolean) : [];
    const rolledFrom = evAts.length ? Math.min(...evAts) : 0, rolledTo = evAts.length ? Math.max(...evAts) : 0;
    const writeAt = w && w.row ? epoch(w.row.at) : 0, writeEnd = w && w.row ? epoch(w.row.finished) : 0;
    const render = (prov && prov.render) || {};
    const flow = (why && why.flow) || [];
    const flowAt = step => { const f = flow.find(x => x.step === step); return f ? f.at : ''; };
    const airAt = epoch(why && why.air_at) || 0;
    const airClock = airAt ? clockOf(airAt) : (flowAt('published') || flowAt('handed') || '');
    const rows = [];
    const add = (name, when, took, what) => rows.push({name, when, took, what});
    if (conv) add('planned by System 3', clockOf(planned), (conv.plan || {}).plan_ms != null ? secs(Number(conv.plan.plan_ms) / 1000) : '', `${(conv.decision_events || []).length} decisions recorded${rolledFrom && rolledTo ? ` over ${secs(rolledTo - rolledFrom)}` : ''}${conv.mode ? ` - ${conv.mode}` : ''}`);
    for (const m of (conv && conv.material) || []) add('passage fetched', '', secs(Number(m.ms || 0) / 1000), `${(m.selected || {}).file || 'a document'} through the station's speakbox_quote`);
    if (w && w.row) add('written by the model', clockOf(writeAt), writeEnd && writeAt ? secs(writeEnd - writeAt) : (w.row.state === 'running' ? 'still running' : ''), `${w.row.model || '?'} - ${w.row.purpose || ''}${w.exact ? '' : ' (nearest call by time)'}${planned && writeAt ? ` - ${secs(Math.max(0, writeAt - planned))} after the plan` : ''}`);
    else if (conv) add('written by the model', '', '', (w && w.why) || 'no model call was found for this message');
    if (render.ms != null || render.engine) add('rendered to voice', flowAt('rendered') || '', render.ms != null ? secs(Number(render.ms) / 1000) : '', `${render.engine || '?'}${render.voice ? ' ' + render.voice : ''}${render.seconds ? ` - ${secs(Number(render.seconds))} of audio` : ''}${render.kb ? `, ${render.kb} KB` : ''}${render.fallback ? ' - fallback: ' + render.fallback : ''}`);
    for (const f of flow) if (!['called', 'rendered'].includes(f.step)) add(f.label || f.step, f.at ? clockOf(f.at) : '', '', f.detail || '');
    if (airClock) add('on air', airClock, why && why.seconds ? secs(Number(why.seconds)) : '', why ? `${why.seconds ? 'spoken - ' : ''}${why.aired || ''}${why.kind ? ' - ' + why.kind : ''}${why.withdrawn_why ? ' - ' + why.withdrawn_why : ''}` : '');
    const first = [planned, writeAt].filter(Boolean).length ? Math.min(...[planned, writeAt].filter(Boolean)) : 0;
    const last = Math.max(airAt || 0, writeEnd || 0, rolledTo || 0) || (first ? first + 600 : 0);
    const table = el('div', 's3-timeline', ...rows.map(r => el('div', 's3-tl-row',
      el('span', {class: 's3-tl-when', text: r.when || '-'}), el('b', {text: r.name}),
      el('span', {class: 's3-tl-took', text: r.took || ''}), el('span', {class: 's3-muted', text: r.what || ''}))));
    const total = first && airAt ? para(`${secs(airAt - first)} from ${planned && planned <= writeAt ? 'the plan' : 'the write'} to the air.`, 's3-muted') : null;
    /* the profiler snapshot: the window this line was made in */
    const prof = el('div', 's3-prof', para('Reading the station\'s pulse for that window...', 's3-muted'));
    fill(host, conv && t ? turnArrows() : null,
      sectionOf('The clocks of this line', el('div', null, table, total)),
      sectionOf('What the station was doing while it was made', prof));
    if (!first) { fill(prof, para('No plan or model call is on record for this line, so there is no window to profile.', 's3-muted')); return; }
    const since = first - 3, until = (last || first) + 3;
    const [pulse, hist, status] = await Promise.all([
      soft(request(`/api/pulse?since=${since.toFixed(0)}&until=${until.toFixed(0)}`)).then(x => x || soft(request('/api/pulse'))),
      soft(request('/api/prompt-history?limit=150')),
      soft(request('/api/system3/status'))]);
    if (!prof.isConnected || !cur.alive) return;
    const stalls = ((pulse && pulse.recent) || []).filter(r => { const a = epoch(r.at); return a >= since && a <= until; });
    const windowed = !!(pulse && pulse.since != null);
    const calls = ((hist && hist.rows) || []).filter(r => { const a = epoch(r.at), b = epoch(r.finished) || a; return a && b >= since && a <= until; })
      .sort((a, b) => epoch(a.at) - epoch(b.at));
    const busy = calls.reduce((acc, r) => acc + Math.max(0, Math.min(until, epoch(r.finished) || until) - Math.max(since, epoch(r.at))), 0);
    const span = Math.max(1, until - since);
    const gc = (pulse && pulse.gc) || {};
    const m = (status && status.metrics) || {};
    fill(prof,
      kv([['window', `${clockOf(since)} - ${clockOf(until)} (${secs(span)})`],
        ['loop stalls in it', windowed ? `${stalls.length}${stalls.length ? ', worst ' + secs(Math.max(...stalls.map(r => Number(r.seconds) || 0))) : ''}` : `${stalls.length} (of the last 10 min - this station cannot window its pulse yet)`],
        ['the writer lane', `${calls.length} model call${calls.length === 1 ? '' : 's'} overlapped it, holding the lane ${Math.round(100 * Math.min(1, busy / span))}% of the window`],
        ['gc', gc.gen2_collections != null ? `${gc.gen2_collections} gen-2 collections, ${gc.frozen != null ? gc.frozen + ' objects frozen' : ''}` : ''],
        ['System 3 lately', m.plan_ms_ema != null ? `plans in ${secs(Number(m.plan_ms_ema) / 1000)} (ema), material in ${secs(Number(m.material_ms_ema || 0) / 1000)}; ${m.withheld || 0} withheld, ${m.failures || 0} failures` : ''],
        ['pulse reading', (pulse && pulse.reading) || 'unavailable']]),
      stalls.length ? el('details', {open: stalls.length <= 6}, el('summary', {text: `the ${stalls.length} stall${stalls.length === 1 ? '' : 's'} - where the loop was`}),
        el('div', 's3-timeline', ...stalls.map(r => el('div', 's3-tl-row s3-tl-ev', el('span', {class: 's3-tl-when', text: clockOf(r.at)}), el('b', {class: 's3-tl-took', text: secs(Number(r.seconds) || 0)}),
          el('span', {class: 's3-muted', text: String(r.top || '')}), el('span', {class: 's3-muted s3-frames', text: (r.frames || []).slice(1, 5).join(' < ')}))))) : para(windowed ? 'The loop never stalled past 1.5 s while this line was made.' : '', 's3-muted'),
      calls.length ? el('details', {open: calls.length <= 8}, el('summary', {text: `the ${calls.length} model call${calls.length === 1 ? '' : 's'} in the window`}),
        el('div', 's3-timeline', ...calls.map(r => el('div', 's3-tl-row s3-tl-ev' + (w && w.row && r.id === w.row.id ? ' mine' : ''), el('span', {class: 's3-tl-when', text: clockOf(r.at)}),
          el('b', {class: 's3-tl-took', text: r.finished && r.at ? secs(epoch(r.finished) - epoch(r.at)) : (r.state || '')}), el('span', {text: `${r.model || '?'} - ${r.purpose || ''}`}),
          el('span', {class: 's3-muted', text: w && w.row && r.id === w.row.id ? 'this line\'s write' : (r.error ? 'error: ' + String(r.error).slice(0, 60) : '')}))))) : null,
      para('Stalls are the event loop held past 1.5 s (py-spy names the frame); the lane is the one local model slot every writer shares. A line made while the lane was full waited for it - that wait is the gap between "planned" and "written" above.', 's3-muted'));
  }

  /* ---- [s3-params] EVERY PARAMETER THAT PAINTED THIS LINE ---------------------
     "a collapsed panel of all the parameters that painted it and their values
     allowing me to click them and see what they pertain to and to alter /
     change / toggle their values". Each is a fold: its name and value shut,
     what it pertains to and its control open. Every control goes through
     the door that already owns the value (System 3's settings and config
     sections, the DJ desk's dials, the orchestrator's policy book). */
  const PARAM_HELP = {
    emotional_volatility: 'how readily a speaker leaves the emotion they are in (the ES roll)',
    disagreement: 'weight on arguing, pushing back and refusing premises (RS / IRS rolls)',
    escalation: 'weight on turning the heat up', tangent: 'weight on wandering off the point (FL rolls)',
    callback: 'weight on calling back to earlier moments', speakerbox_density: 'multiplies the prepend / append / full dials: 0.5 leaves them, 1.0 doubles them',
    sfx_aggression: 'the SFX Guy\'s odds of a clip at a turn - restrained (0) to deliberately chaotic (1); never below the two-line cadence',
    novelty: 'weight on fresh subjects and moves', closure_aggressiveness: 'how early the scene starts landing',
    topics: 'how often something off your topics board comes up: 0.5 = 40% of rounds, 1.0 = 80%, 0 = never',
    shock_beat: 'the odds of one open reaction turn in a round ("openly shocked at what the other just said")',
    interjections: 'the odds of an interjection forced in edgewise while one seat goes on a roll',
    track_talk: 'the odds that a live banter round includes one brief comment tied to the record currently playing; banked rounds do not use a record title',
    mention: 'the odds the station\'s own name is worked into the round',
    tint: 'which lines the crystal tint may rhyme: 0.5 = half of them, 1.0 = every eligible line, 0 = none (the pass itself is a station switch)',
    repair: 'whether a round that misses its target goes back to the writer for one rewrite: 0.5 = half of such rounds, 0 = never (it stands as written)',
    room: 'whether the Writers\' Room may add to or rewrite this round later: 0.5 = half of the rounds, 0 = never'};
  const TOPIC_ROAD = {key: 'topics_by_rng', verb: 'topics', on: 'rng', off: 'auto', name: 'Topics only through the roulette',
    what: 'on (rng): the topics board reaches a round only through System 3\'s TOPIC roll and CTS1\'s topics database; off (auto): the station\'s own topic roads spring topics by themselves again (banter, callers, the memo, the SFX Guy).'};
  function paramFold(name, value, help, control, cls) {
    return el('details', {class: 's3-param ' + (cls || '')},
      el('summary', null, el('span', {class: 's3-param-name', text: name}), el('b', {class: 's3-param-value', text: value == null || value === '' ? '-' : String(value)})),
      el('div', 's3-param-body', help ? para(help, 's3-muted') : null, control || null));
  }
  async function paintParams(host) {
    const conv = cur.conv, t = cur.turn;
    fill(host, conv && t ? turnArrows() : null, para('Reading the parameters...', 's3-muted'));
    const soft = pr => pr.then(x => x, () => null);
    const [settings, dials, policy] = await Promise.all([soft(request('/api/system3/settings')), soft(v.api.dials()), soft(v.api.policy(true))]);
    if (!host.isConnected || !cur.alive) return;
    const live = (settings && settings.settings) || {};
    const liveControls = live.controls || {};
    const planControls = ((conv && conv.settings) || {}).controls || {};
    const status = el('span', 's3-muted');
    const say = txt => { status.textContent = txt; };
    /* 1. System 3's behaviour controls: the value at planning, the live value, a slider */
    const controls = Object.keys({...planControls, ...liveControls}).map(k => {
      const was = planControls[k], now = liveControls[k];
      const out = el('b', {text: num(now)});
      const input = el('input', {type: 'range', min: 0, max: 1, step: 0.05, value: now == null ? 0.5 : now, 'aria-label': k,
        oninput: e => { out.textContent = num(+e.target.value); }});
      const save = btn('Save', async () => { save.disabled = true; say('saving ' + k + '...');
        try { const got = await send('/api/system3/settings', 'POST', {controls: {...liveControls, [k]: +input.value}}); liveControls[k] = +input.value; Object.assign(liveControls, ((got || {}).settings || {}).controls || {}); say(k + ' saved - the next round rolls with it');
          const fold = save.closest('.s3-param'); const val = fold && fold.querySelector('.s3-param-value'); if (val) val.textContent = `${num(was)} at planning - now ${num(liveControls[k])}`; if (fold) fold.classList.toggle('changed', was != null && Math.abs(Number(liveControls[k]) - Number(was)) > 0.001); }
        catch (e) { say('not saved: ' + ((e && e.message) || e)); } save.disabled = false; });
      return paramFold(k.replace(/_/g, ' '), `${num(was)} at planning${now != null && Math.abs(Number(now) - Number(was)) > 0.001 ? ` - now ${num(now)}` : ''}`,
        (PARAM_HELP[k] || 'a System 3 behaviour control: multiplies the weight of the outcomes tagged with it by 0.5x to 2x (0.5 is neutral)') + '. Recorded on this round at planning; the slider is the live value.',
        el('div', 's3-row', input, out, save), was != null && now != null && Math.abs(Number(now) - Number(was)) > 0.001 ? 'changed' : '');
    });
    /* 2. the DJ desk dials System 3 read for this round */
    const rates = ((conv && conv.inputs) || {}).speakerbox_rates || {};
    const dialRows = [];
    if (dials) {
      const vals = {...dials};
      const dialFold = (label, key, recorded, help, max = 1, step = 0.01, fmt = pct) => {
        const out = el('b', {text: fmt(vals[key])});
        const input = el('input', {type: 'range', min: 0, max, step, value: vals[key], 'aria-label': label, oninput: e => { vals[key] = +e.target.value; out.textContent = fmt(vals[key]); }});
        const save = btn('Save to the station', async () => { save.disabled = true; say('saving...');
          try { const done = await v.api.saveDials(dials, vals); Object.assign(dials, vals); say(done.length ? `saved ${done.join(', ')}` : 'nothing changed'); }
          catch (e) { say('not saved: ' + ((e && e.message) || e)); } save.disabled = false; });
        return paramFold(label, recorded != null ? `${fmt(recorded)} at planning${Math.abs(Number(vals[key]) - Number(recorded)) > 0.001 ? ' - now ' + fmt(vals[key]) : ''}` : fmt(vals[key]), help, el('div', 's3-row', input, out, save));
      };
      dialRows.push(dialFold('Prepend dial (DJ desk)', DIAL_KEY.prepend, rates.prepend, 'the odds a speaker-box passage is read word for word BEFORE a marked line; a d100 must land above 100 - odds'));
      dialRows.push(dialFold('Append dial (DJ desk)', DIAL_KEY.append, rates.append, 'the odds a passage is read AFTER a marked line'));
      dialRows.push(dialFold('Full-swath dial (DJ desk)', DIAL_KEY.full, rates.full, 'the odds turn 1 opens on a speaker-box monologue'));
      dialRows.push(dialFold('Passages per round', 'max_inline', ((cur.config && cur.config.config && cur.config.config.speakerbox) || {}).max_inline, 'a winning roll places nothing once the round holds this many passages', 8, 1, x => String(Math.round(Number(x) || 0))));
    } else dialRows.push(para('The DJ desk\'s dials could not be read.', 's3-muted'));
    /* 3. the config sections (speaker-box, SFX) */
    const cfg = (cur.config && cur.config.config) || {};
    const sectionFold = (name, help) => {
      const area = el('textarea', {value: json(cfg[name] || {}), rows: 8, 'aria-label': name});
      const save = btn('Save ' + name, async () => { save.disabled = true; say('saving ' + name + '...');
        try { await send('/api/system3/config/section/' + name, 'PUT', JSON.parse(area.value)); await reloadConfig(); say(name + ' saved'); }
        catch (e) { say('not saved: ' + ((e && e.message) || e)); } save.disabled = false; });
      return paramFold(name + ' section', Object.keys(cfg[name] || {}).length + ' keys', help, el('div', null, area, el('div', 's3-row', save)));
    };
    /* 4. the station's switches */
    const roads = [...CUT_ROADS, TOPIC_ROAD];
    const switches = roads.map(road => {
      const on = policy ? (policy[road.key] !== false && (road.key !== 'topics_by_rng' || policy[road.key] !== false)) : true;
      const b = btn(on ? 'ON - turn off' : 'OFF - turn on', async () => { b.disabled = true; say('switching...');
        try { await v.api.setPolicy(road, !on); say(road.name + (on ? ' is off' : ' is on')); await paint(); } catch (e) { say('not changed: ' + ((e && e.message) || e)); b.disabled = false; } },
        {class: 's3-cut-toggle' + (on ? '' : ' off')});
      return paramFold(road.name, on ? 'ON' : 'OFF', road.what, el('div', 's3-row', b));
    });
    /* 5. the round itself */
    const gen = live.generation_mode || (conv && conv.generation_mode) || 'batch';
    const genBtn = btn(gen === 'turn' ? 'turn by turn - switch to whole rounds' : 'whole rounds - switch to turn by turn', async () => { genBtn.disabled = true;
      try { await send('/api/system3/settings', 'POST', {generation_mode: gen === 'turn' ? 'batch' : 'turn'}); say('generation mode saved'); await paint(); } catch (e) { say('not saved: ' + ((e && e.message) || e)); genBtn.disabled = false; } });
    const rs = (conv && conv.road_structure) || (conv && conv.call_structure) || {};
    const inputs = (conv && conv.inputs) || {};
    const roundRows = conv ? [
      paramFold('generation', conv.generation_mode || gen, 'whole rounds (batch): the running order is planned whole before the write; turn by turn: each reply is planned after the last one is written, so it answers it. This round was planned ' + (conv.generation_mode || 'batch') + '.', el('div', 's3-row', genBtn)),
      paramFold('structure', rs.id ? `${rs.id} v${rs.version || 1}` : 'the banter cycle', 'the legs (nodes) this round was built from; each leg has its act, seat, place and draws. Edit them in the Segments tab of System 3.', el('div', 's3-row', btn('Open the segments editor', () => openSystem3({request, tab: 'segments'})))),
      paramFold('mode and roads', `${live.mode || conv.mode} - ${(live.roads || []).join(', ') || 'every road'}`, 'off: the legacy station; shadow: System 3 records what it would have done; active: it directs the roads listed.', el('div', 's3-row', btn('Open the Controls tab', () => openSystem3({request, tab: 'director'})))),
      paramFold('seed', conv.seed, 'the root of this round\'s random numbers: draw n is sha256(seed|n|label), so the same seed, config and questions give the same answers. A test seed on the Controls tab pins it.', null),
      paramFold('config', conv.config_hash + (cur.config && cur.config.hash && cur.config.hash !== conv.config_hash ? ` - the desk now holds ${cur.config.hash}` : ''), 'the hash of the tables, structures and sections this round was planned under.', null),
      paramFold('the inputs', `${inputs.road || ''} - ${(inputs.seats || []).join('')} - ${inputs.turns || '?'} turns - ${inputs.target_seconds ? Math.round(inputs.target_seconds) + ' s' : 'no target'}`,
        'what the road told System 3 when it asked: the seats and names, the turn budget and target length, the material available and the subject.', el('pre', {class: 's3-param-pre', text: json({seats: inputs.seats, names: inputs.names, turns: inputs.turns, target_seconds: inputs.target_seconds, availability: inputs.availability, subject: conv.subject, seed_file: inputs.seed_file, bank: inputs.bank, approach: inputs.approach, dice_hosts: inputs.dice_hosts, round_rolls: inputs.round_rolls})})),
    ] : [para('This line was not directed by System 3; only the station\'s live parameters are shown.', 's3-muted')];
    fill(host, conv && t ? turnArrows() : null,
      el('div', 's3-row', el('span', {class: 's3-muted', text: 'Each parameter is a fold: tap it for what it pertains to and its control. Every change goes through the door that owns the value.'}), status),
      sectionOf('System 3 behaviour controls', el('div', 's3-params', ...controls)),
      sectionOf('The DJ desk dials System 3 read', el('div', 's3-params', ...dialRows)),
      sectionOf('Config sections', el('div', 's3-params', sectionFold('speakerbox', 'mode weights for a speaker-box hit, passages per round, passage lengths'), sectionFold('sfx', 'the SFX Guy\'s clip odds at aggression 0 and 1, the first-exchange rule, arousal and humour boosts'))),
      sectionOf('The station\'s switches', el('div', 's3-params', ...switches)),
      sectionOf('This round', el('div', 's3-params', ...roundRows)));
  }

  const PAINT = {system3: paintSystem3, node: paintNode, prompt: paintPrompt, tables: paintTables, timing: paintTiming, params: paintParams};
  async function paint() {
    if (!cur.alive) return;
    const which = PAINT[current] ? current : 'system3';
    if (!panes[which]) panes[which] = el('div', 's3-ltabs-pane s3-ltabs-' + which);
    for (const [k, node] of Object.entries(panes)) node.hidden = k !== which;
    fill(root, ...Object.values(panes));
    try { await PAINT[which](panes[which]); }
    catch (e) { fill(panes[which], para('This pane could not be drawn: ' + String((e && e.message) || e), 's3-error')); }
  }
  await load(cur.lineId);
  await paint();
  return {
    show(name) { current = String(name || 'system3'); return paint(); },
    async open(id) { if (String(id || '') === cur.lineId) return; await load(id); await paint(); },
    line() { return cur.lineId; },
    directed() { return !!(cur.conv && cur.turn); },
    dispose() { cur.alive = false; v.alive = false; if (story && story.dispose) { try { story.dispose(); } catch (e) { /* gone */ } } fill(root); }
  };
}

export async function openSystem3({request, onClose, tab = '', table = '', conversationId = ''} = {}) {
  const backdrop = el('div', 's3-backdrop');
  const root = el('section', {role: 'dialog', 'aria-modal': 'true', 'aria-label': 'System 3 conversation director'});
  backdrop.append(root); document.body.append(backdrop);
  const before = document.activeElement; let view, closed = false;
  const close = () => { if (closed) return; closed = true; view && view.dispose(); backdrop.remove(); document.removeEventListener('keydown', key); before && before.focus && before.focus(); onClose && onClose(); };
  const key = event => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', key);
  backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });
  view = await mount(root, {request, onClose: close, tab, table, conversationId});
  if (!closed && window.pineCloseX) window.pineCloseX(root, close, {label: 'Close System 3'});   // [closex:s3-window]
  if (closed) view.dispose(); else { const b = root.querySelector('button'); b && b.focus(); }
  return {element: backdrop, close};
}

/* ======================================================================== */
/* [s3-segment-nodes] A SCHEDULED SEGMENT, AS THE NODES THAT BUILT IT.
 *
 * "add an icon ... for converting the convo view ... into a nodal view of how
 *  the segment was constructed. I want to see the nodes with RNG and roulette
 *  results in a conversation chain representing how it was constructed with
 *  system prompts / prompts, memory inserts, insets, gold, sponetanity systems
 *  (if applicable), vertically." And: "expand and select and investigate and
 *  inspect other segments via the right click menu and be able to trace the
 *  nodes of how the segments are constructed via roulette RNG and System 3"
 *  (the operator, 2026-09-28).
 *
 * A segment is one entry of the station's running order as it went on air -
 * System2's occurrence, stamped on every line of the script when the line took
 * its place there (GET /api/system3/segment/{id}). Every conversation that went
 * out in it is chained inside it: a round, or a single line - an interjection,
 * a station ID, an ad spot is a one-turn conversation IN the segment, never a
 * segment of its own. The chain reads top to bottom in the order the segment
 * was built: its scheduling (what the plan bound to the entry, why), then each
 * conversation - the round's own rolls (the spontaneity systems: tempers,
 * shocks, interjections, events, favourites, directives, the station's dice),
 * its prompt (the system prompt, the writer's prompt and every block of it as
 * System 3 decided it, memory inserts among them), and turn by turn the rolls
 * with their dice and the rows they landed on, the insets (speaker-box
 * passages, stings, the SFX Guy's line, gold and re-airs where a line carries
 * the stamp), the words written and the air. Every die is the recorded d100;
 * a node opens the decision card that shows how it was decided. Nothing here
 * moves the page: a pick of another segment is the only scroll, and it is the
 * operator's. */
const SG_SPONTANEITY = new Set(['TEMPER', 'SHOCK', 'INTERJECT', 'MENTION', 'EVENT', 'FAV', 'DIRECTIVE', 'CARRY']);
const SG_REWRITE = new Set(['TINT', 'REPAIR', 'ROOM']);
const sgHm = t => (t ? new Date(Number(t) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '');
const sgWindow = seg => (seg && seg.start ? `${sgHm(seg.start)} - ${sgHm(seg.ends)}` : '');
const sgOf = x => String((x && typeof x === 'object' ? x.id : x) || '');
function sgIcon(ref, label, onclick, extra = {}, short = '') {
  const b = el('button', {type: 'button', class: 's3-ibtn', title: label, 'aria-label': label, onclick, ...extra});
  const svg = typeof window.pineIcon === 'function' ? window.pineIcon(ref) : '';
  if (svg) b.innerHTML = svg; else { b.textContent = short || label; b.classList.add('txt'); }
  return b;
}
function sgName(seg) {
  if (!seg) return 'no segment';
  return `${seg.label || seg.kind || 'segment'}${seg.kind && seg.label && seg.label.toLowerCase() !== seg.kind ? ` (${seg.kind})` : ''}`;
}
async function sgTrace(request, id, {full = true, scheduling = false} = {}) {
  return request('/api/system3/segment/' + encodeURIComponent(id) + `?full=${full ? 1 : 0}&scheduling=${scheduling ? 1 : 0}`);
}
/* The segment a conversation or a line went out in: its lines' own segment
   (the block they took their place in), else the one on air when it was
   planned. '' when neither is on the record. */
async function sgResolve(request, {segment = '', conversation = '', lineId = ''} = {}) {
  if (sgOf(segment)) return sgOf(segment);
  let cid = String(conversation || '');
  if (!cid && lineId) {
    try {
      const got = await request('/api/system3/line?line_id=' + encodeURIComponent(lineId));
      if (got && got.line && got.line.segment) return String(got.line.segment);
      cid = String((got && got.line && got.line.conversation_id) || '');
    } catch (e) { return ''; }
  }
  if (!cid) return '';
  try {
    const conv = await cachedConversation(request, cid);
    const lined = (conv.lines || []).find(l => l.segment);
    return String((lined && lined.segment) || ((conv.identity || {}).segment || {}).id || '');
  } catch (e) { return ''; }
}

/* One node on the spine: a dot in its family's colour, its die when it was a
   draw, the family, what it landed on and the facts under it. */
function sgNode({fam = '', dice, label = '', text = '', sub = '', cls = '', onOpen = null, title = ''} = {}, ...kids) {
  const face = dice === undefined ? null : die(dice == null || dice === '' ? null : Number(dice));
  const node = el('div', {class: 's3-sgn' + (cls ? ' ' + cls : '') + (onOpen ? ' s3-sgn-open' : ''), style: `--fam:${FAM[fam] || 'var(--obs)'}`,
      role: onOpen ? 'button' : null, tabindex: onOpen ? '0' : null, title: title || (onOpen ? 'tap for how this was decided' : null),
      onclick: onOpen ? e => {
        /* a control inside the node keeps its own tap; a fold the node sits in does not count */
        const hit = e.target.closest('a, button, summary, details, input, select, video, audio');
        if (hit && hit !== e.currentTarget && e.currentTarget.contains(hit)) return;
        e.stopPropagation(); onOpen(e);
      } : null,
      onkeydown: onOpen ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(e); } } : null},
    el('span', {class: 's3-sgn-dot', 'aria-hidden': 'true'}),
    el('div', 's3-sgn-body',
      el('div', 's3-sgn-line', face, el('b', {class: 's3-sgn-fam', text: label || fam}),
        text ? el('span', {class: 's3-sgn-text', text}) : null),
      sub ? el('div', {class: 's3-sgn-sub s3-muted', text: sub}) : null, ...kids));
  node.face = face;
  return node;
}

/* A recorded decision as a node: its d100, what it landed on, where in the
   draw, and the table it came from. */
function sgRoll(conv, ev, t, api) {
  const line = eventLine(ev, conv);
  const sb = sbOutcome(ev);
  const sel = ev.selected || {};
  const item = stage(ev, 'item') || stage(ev, 'mode');
  const where = item && item.of ? `${item.selected_index || '?'} of ${item.of}` : '';
  const what = (FAMILY_WHAT[ev.family] || [ev.family])[0];
  const node = sgNode({fam: ev.family, dice: line.dice, text: String(landedWords(ev, conv) || line.text || '').replace(/\s+/g, ' ').slice(0, 220),
    sub: [where, sel.table ? 'table ' + sel.table : '', what !== ev.family ? what : '', sb ? sb.why : ''].filter(Boolean).join(' · '),
    cls: 's3-sgn-roll' + (sb && !sb.won ? ' miss' : '') + (SG_SPONTANEITY.has(ev.family) ? ' s3-sgn-spont' : ''),
    onOpen: () => openDecision(conv, ev, t, api)});
  node.dataset.event = ev.event_id || '';
  if (sb && !sb.won && node.face) node.face.classList.add('miss');
  return node;
}
/* The same from the compact record, when the whole conversation is not held:
   its card is fetched when it is opened. */
function sgCompactRoll(request, cid, r, t, api) {
  return sgNode({fam: r.family, dice: r.dice == null ? null : r.dice, text: String(r.label || '').slice(0, 220),
    sub: [r.index && r.of ? `${r.index} of ${r.of}` : '', r.table ? 'table ' + r.table : '', r.rule || ''].filter(Boolean).join(' · '),
    cls: 's3-sgn-roll' + (SG_SPONTANEITY.has(r.family) ? ' s3-sgn-spont' : ''),
    onOpen: r.event_id ? async () => {
      try {
        const conv = await cachedConversation(request, cid);
        const ev = (conv.decision_events || []).find(e => e.event_id === r.event_id);
        if (ev) openDecision(conv, ev, (conv.turns || []).find(x => x.turn_id === ev.turn_id) || t || null, api);
      } catch (e) { /* the conversation is past retention */ }
    } : null});
}

function sgTextFold(title, text) {
  const body = String(text || '');
  return el('details', 's3-sgn-fold', el('summary', {text: `${title} (${body.length} characters)`}), el('pre', {text: body || '(none)'}));
}
/* THE PROMPT: the writer call whose prompt carries this round's running order
   (found as the tapped line's Prompt tab finds it), folded shut until opened -
   the system prompt as sent, the prompt, what came back, and every block of it
   as System 3 decided it (sent, rolled, stripped). */
function sgPrompt(request, conv, state) {
  const body = el('div', 's3-sgn-prompt-body');
  const fold = el('details', {class: 's3-sgn s3-sgn-prompt', style: '--fam:var(--line)'},
    el('summary', null, el('span', {class: 's3-sgn-dot', 'aria-hidden': 'true'}), el('b', {class: 's3-sgn-fam', text: 'PROMPT'}),
      el('span', {class: 's3-sgn-text', text: 'the system prompt, the prompt to the writer, and every block as System 3 decided it'})),
    body);
  let painted = false;
  fold.addEventListener('toggle', async () => {
    if (!fold.open || painted) return;
    painted = true;
    fill(body, para('Looking for the writer call that wrote it...', 's3-muted'));
    let w;
    try { w = await findWriterCall(request, conv, null, state.callCache); } catch (e) { w = {row: null, why: (e && e.message) || String(e)}; }
    if (!w || !w.row) { fill(body, para('No prompt: ' + ((w && w.why) || 'the prompt history holds none for it'), 's3-muted')); return; }
    const parts = promptParts(w.detail || {});
    fill(body,
      el('div', 's3-row', el('b', {text: `${w.row.model || '?'} - ${w.row.purpose || ''}`}),
        el('span', {class: 's3-muted', text: day(Number(w.row.at || 0))}),
        el('span', {class: 's3-pill ' + (w.exact ? 'active' : 'shadow'), text: w.exact ? 'proven by its words' : 'nearest by time'}),
        el('span', {class: 's3-muted', text: w.why || ''})),
      sgTextFold('The system prompt, as it was sent', parts.sys || NO_SYSTEM),
      sgTextFold('The prompt to the writer', parts.user),
      sgTextFold('What the writer sent back', parts.text),
      parts.user ? promptBlocksBox(request, parts.user) : null);
  });
  return fold;
}

/* A sting on the ledger, as the node it was: the category die, the clip die,
   the clip and its poster. */
function sgSting(line) {
  const roll = line.sfx_roll && typeof line.sfx_roll === 'object' ? line.sfx_roll : {};
  const dice = [roll.category, roll.clip].filter(r => r && typeof r === 'object');
  const kids = dice.map((r, i) => el('span', {class: 's3-sgn-chipdie'}, die(r.dice == null || r.dice === '' ? null : Number(r.dice)),
    el('span', {class: 's3-muted', text: `${i ? 'clip' : 'category'}: ${String(r.label || '').slice(0, 40)}${r.of ? ' of ' + r.of : ''}`})));
  const poster = typeof line.poster === 'string' && line.poster
    ? el('img', {class: 's3-sgn-poster', src: stationUrl(line.poster), alt: boardName(line) || 'the clip', loading: 'lazy', decoding: 'async',
      onerror: e => { e.currentTarget.hidden = true; }}) : null;
  const node = sgNode({fam: 'SFX', label: 'STING', text: boardName(line) || 'a clip off the board', cls: 's3-sgn-inset'},
    kids.length ? el('div', 's3-sgn-dice', ...kids) : null, poster);
  node.dataset.line = line.line_id || '';
  return node;
}

/* The air, for the lines a turn has in this segment: heard, withdrawn (and
   why), waiting, or no receipt yet. Filled when the receipts arrive. */
/* [s3-inject] A forced node on the segment's spine: no die - nothing rolled
   it onto the air; the card says who injected it, why, and when. */
function sgInject(o) {
  return sgNode({fam: 'INJECT', label: o.standing ? 'STANDING' : 'FORCED',
    text: o.card || ('forced: no roll - injected by ' + (o.by || 'the station') + ' because ' + (o.why || 'no reason was recorded')),
    sub: [o.at ? 'at ' + clock(Number(o.at)) : '', o.anchored ? 'filed on ' + o.anchored : ''].filter(Boolean).join(' \u00b7 '),
    cls: 's3-sgn-inset s3-sgn-inject'});
}
function sgAirWord(lines, air) {
  if (!lines.length) return {word: 'no line of it in this segment', cls: ''};
  const got = airOfLines(lines, air);
  if (got === 'aired') {
    const a = lines.map(l => air.get(l.line_id)).find(x => airOn(x)) || {};
    return {word: 'heard' + (a.at ? ' ' + a.at : ''), cls: 'heard'};
  }
  if (got === 'off') {
    const a = lines.map(l => air.get(l.line_id)).find(x => airOff(x)) || {};
    return {word: 'not heard: ' + (a.cut_why || a.withdrawn_why || a.aired || 'withdrawn'), cls: 'gone'};
  }
  if (got === 'waiting') return {word: 'waiting its turn on the air', cls: ''};
  return {word: 'no air receipt yet', cls: ''};
}

/* [s3graphix] THE CHAIN, EXCHANGE BY EXCHANGE: the gates the walk rolled
   drawn as forks between the messages (every way out, the taken one lit),
   the handoff and its raffle between two messages, the same voice twice
   said why (an EXPANSION edge, or one turn's pieces as NAME (CONT'D)), the
   copied stamps named for what they are, and the message node that opens
   in place into the tables that composed it. ES5; no timers; no scrolling. */
var SGX_TURN_FAMS = {ES: 1, RS: 1, IRS: 1, FL: 1, CTS: 1, SPEAKERBOX: 1, SFX: 1, SFXGUY: 1, SPLIT: 1, IL: 1, TRACK_TALK: 1};
var SGX_CAST = {initiator: 1, speaker: 1, reaction_order: 1, reply_speaker: 1};
var SGX_GATE = {branch: 1, chance: 1};
var SGX_WHO_SEAT = {dj: 'A', host: 'A', a: 'A', cohost: 'B', b: 'B', third: 'D', guest: 'D', d: 'D'};
var SGX_PLAN = new WeakMap();
function sgxSeq(ev) {
  var n = parseInt(String((ev && ev.event_id) || '').split(':').pop(), 10);
  return isNaN(n) ? -1 : n;
}
function sgxNorm(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
function sgxClip(s, n) { return String(s || '').replace(/\s+/g, ' ').trim().slice(0, n || 600); }
function sgxWordsOf(id) { return String(id || '').replace(/_/g, ' '); }
function sgxSeatName(conv, seat) {
  var ts = (conv && conv.turns) || [];
  for (var i = 0; i < ts.length; i += 1) if (ts[i].speaker === seat && ts[i].name) return String(ts[i].name);
  return String(seat || '');
}
function sgxVoice(who) {
  var w = String(who || '');
  return String(castName(w) || w || 'somebody');
}
function sgxShare(st, c) {
  if (c.p != null) return pct(c.p);
  var total = 0;
  (st.candidates || []).forEach(function (x) { total += Number(x.weight) || 0; });
  return total > 0 ? pct((Number(c.weight) || 0) / total) : '-';
}
function sgxStageDice(st) { return st && st.draw && st.draw.dice != null ? st.draw.dice : null; }
/* Where each GRAPH draw sits: between the turn before it and the first turn
   whose own draws come after it in the round's recorded order. */
function sgxPlan(conv) {
  if (SGX_PLAN.has(conv)) return SGX_PLAN.get(conv);
  var turns = conv.turns || [], evs = conv.decision_events || [];
  var at = {}, anchor = [], gaps = [], placed = {}, cast = {};
  var i;
  for (i = 0; i < turns.length; i += 1) { at[turns[i].turn_id] = i; anchor.push(Infinity); }
  for (i = 0; i <= turns.length; i += 1) gaps.push([]);
  evs.forEach(function (e) {
    if (!e.turn_id || !SGX_TURN_FAMS[e.family] || at[e.turn_id] == null) return;
    var s = sgxSeq(e);
    if (s >= 0 && s < anchor[at[e.turn_id]]) anchor[at[e.turn_id]] = s;
  });
  evs.forEach(function (e) {
    if (e.family !== 'GRAPH' || e.stage || e.kind === 'observation' || (e.meta || {}).superseded_by_revision) return;
    if (e.turn_id) {
      var t = turns[at[e.turn_id]], st = (e.stages || [])[0] || {};
      if (t && SGX_CAST[st.stage]) cast[t.turn_id] = e;
      return;
    }
    var s = sgxSeq(e), k = turns.length;
    for (var j = 0; j < turns.length; j += 1) if (anchor[j] !== Infinity && anchor[j] > s) { k = j; break; }
    gaps[k].push(e);
    placed[e.event_id] = 1;
  });
  gaps.forEach(function (g, k) {
    g.sort(function (a, b) { return sgxSeq(a) - sgxSeq(b); });
    if (k >= turns.length) return;
    g.forEach(function (e) {
      var st = (e.stages || [])[0] || {};
      if (SGX_CAST[st.stage]) cast[turns[k].turn_id] = e;
    });
  });
  var plan = {gaps: gaps, placed: placed, cast: cast};
  SGX_PLAN.set(conv, plan);
  return plan;
}
function sgxPlaced(conv, ev) { return !!(conv && ev && ev.family === 'GRAPH' && sgxPlan(conv).placed[ev.event_id]); }

/* What one way out of a gate does to the loop. */
function sgxRole(id, gate) {
  id = String(id || '');
  if (id === 'end' || id === 'close' || id === 'wrap') return {kind: 'exit', word: 'ends the round'};
  if (id === 'topic_change') return gate === 'exit_gate' ? {kind: 'ext', word: 'goes round again: a new chapter'} : {kind: 'exit', word: 'ends the chapter'};
  if (id === 'exit_gate' || id === 'exit') return {kind: 'exit', word: 'ends the chapter'};
  if (id === 'skip') return {kind: 'exit', word: 'skips this seat'};
  if (id === 'start') return {kind: 'ext', word: 'another chapter'};
  if (id === 'speak' || /^(reply|answer|call)/.test(id)) return {kind: 'ext', word: 'extends the exchange'};
  if (id === 'rebuttal') return {kind: 'ext', word: 'moves on to the rebuttal'};
  return {kind: 'ext', word: 'goes to ' + sgxWordsOf(id)};
}
function sgxEdge(label, share, role, taken, dice, extra) {
  return el('div', {class: 's3-sgx-edge ' + (taken ? 'taken' : 'not') + ' ' + role.kind, 'data-role': role.kind, title: extra || null},
    el('span', {class: 's3-sgx-wire', 'aria-hidden': 'true'}),
    el('b', {class: 's3-sgx-to', text: label}),
    share ? el('span', {class: 's3-sgx-share', text: share}) : null,
    el('span', {class: 's3-sgx-role', text: role.word}),
    taken ? el('span', {class: 's3-sgx-took'}, dice === undefined ? null : die(dice), el('span', {text: dice == null ? 'taken - no roll' : 'taken'}))
      : el('span', {class: 's3-sgx-took s3-muted', text: 'not taken'}));
}
/* A gate the walk rolled: one line per way out. */
function sgxFork(conv, ev, api) {
  var st = (ev.stages || [])[0] || {};
  var gate = String((ev.meta || {}).node || '');
  var d = sgxStageDice(st);
  var ends = false;
  var edges = (st.candidates || []).map(function (c) {
    var role = sgxRole(c.id, gate);
    if (role.kind === 'exit') ends = true;
    return sgxEdge(String(c.label || sgxWordsOf(c.id)), sgxShare(st, c), role, c.id === st.selected, d);
  });
  var node = sgNode({fam: 'GRAPH', dice: d, label: (ev.meta || {}).kind || 'GRAPH',
    text: sgxWordsOf(gate || 'gate') + ': ' + (ends ? (gate === 'exit_gate' ? 'the round could end here' : 'the loop could end here') : 'the chain branches here'),
    sub: st.stage + ' - d100 ' + (d == null ? '-' : d) + ' over the weights - tap for the card',
    cls: 's3-sgn-roll s3-sgx-fork', onOpen: function () { openDecision(conv, ev, null, api); }},
    el('div', 's3-sgx-edges', edges));
  node.dataset.event = ev.event_id || '';
  node.dataset.gate = gate;
  return node;
}
/* The subject's loop (CTS): carried on, or ended with a new subject drawn. */
function sgxCtsFork(conv, ev, t, api) {
  var sel = ev.selected || {};
  var cont = sel.id === 'CONTINUE' || sel.authority === 'continuing';
  var d = eventLine(ev, conv).dice;
  var why = (ev.meta || {}).why || '';
  var edges = [
    sgxEdge('the subject carries on', '', {kind: 'ext', word: 'extends the chapter'}, cont, cont ? null : undefined, cont ? why : ''),
    sgxEdge(cont ? 'a new subject off the table' : 'a new subject: ' + sgxClip(landedWords(ev, conv), 90), '', {kind: 'exit', word: 'ends the chapter'}, !cont, cont ? undefined : d)];
  var node = sgNode({fam: 'CTS', dice: cont ? undefined : d, label: 'CTS',
    text: 'turn ' + (t.index + 1) + ': the chapter ' + (cont ? 'carried on' : 'ended - a new subject was drawn'),
    sub: cont ? (why || 'no roll: the subject continued') : 'd100 ' + (d == null ? '-' : d) + ' - tap for the card',
    cls: 's3-sgn-roll s3-sgx-fork s3-sgx-ctsfork', onOpen: function () { openDecision(conv, ev, t, api); }},
    el('div', 's3-sgx-edges', edges));
  node.dataset.event = ev.event_id || '';
  node.dataset.gate = 'cts';
  return node;
}
/* The handoff between two messages - or, one voice twice, the EXPANSION. */
function sgxHand(conv, prev, next, cast, gapEvs, api) {
  var same = !!prev && prev.speaker === next.speaker;
  var st = cast ? ((cast.stages || [])[0] || {}) : null;
  var d = st ? sgxStageDice(st) : null;
  var name = String(next.name || next.speaker || '?'), was = prev ? String(prev.name || prev.speaker || '?') : '';
  var pool = st ? (st.candidates || []).map(function (c) { return sgxSeatName(conv, c.id) + ' ' + sgxShare(st, c); }).join(' / ') : '';
  var how = st ? (st.stage === 'initiator' ? 'opened the round' : 'won the seat') + ': d100 ' + (d == null ? '-' : d) + ' in a pool of ' + pool
    : "by the structure's seat order - no raffle";
  var why = '';
  if (same) {
    var fork = null;
    (gapEvs || []).forEach(function (e) {
      var s = (e.stages || [])[0] || {};
      if (SGX_GATE[s.stage] && (s.candidates || []).length > 1) fork = e;
    });
    var fs = fork ? (fork.stages || [])[0] : null;
    why = st ? 'cast again: ' + name + ' ' + how
      : fork ? 'the chain extended at ' + sgxWordsOf((fork.meta || {}).node) + ' (d100 ' + sgxStageDice(fs) + ' -> ' + sgxWordsOf(fs.selected) + ') and the seat stayed with ' + name
      : 'the running order put ' + name + ' on again: ' + (next.step_label || next.step || 'the next step') + ' - no roll';
  }
  var body = el('div', 's3-sgx-handbody',
    same ? para('Why the same voice again: ' + why + '. This is a new turn of its own - not one turn split in pieces (those read NAME (CONT\'D)).', 's3-sgx-why') : null,
    st ? stageStory(st, cast, conv, null) : para('No raffle is on the record for this seat: the road\'s structure hands the mic on in its own order.', 's3-muted'),
    cast ? el('div', 's3-row', btn('The full card', function () { openDecision(conv, cast, next, api); }, {class: 's3-sgx-card'})) : null);
  var box = el('details', {class: 's3-sgn s3-sgx-hand' + (same ? ' s3-sgx-expand' : ''), style: '--fam:' + (same ? 'var(--fl)' : 'var(--topic)'),
      'data-from': prev ? prev.turn_id : '', 'data-to': next.turn_id},
    el('summary', null, el('span', {class: 's3-sgn-dot', 'aria-hidden': 'true'}),
      st ? die(d) : null,
      el('b', {class: 's3-sgn-fam', text: same ? 'EXPANSION' : 'HANDOFF'}),
      el('span', {class: 's3-sgn-text', text: same ? name + ' again - ' + why
        : (prev ? was + ' held the mic -> ' + name + ' ' : 'the mic opens: ' + name + ' ') + how})),
    body);
  return box;
}
/* Where the round stopped. */
function sgxEnd(conv) {
  var turns = conv.turns || [];
  if (turns.length < 2) return null;
  var len = (conv.decision_events || []).filter(function (e) { return e.family === 'LENGTH'; })[0] || null;
  var last = turns[turns.length - 1], prof = conv.graph_profile || null;
  var why = len ? 'the length roll set the round: ' + sgxClip(landedWords(len, conv), 80) + ' (d100 ' + (eventLine(len, conv).dice == null ? '-' : eventLine(len, conv).dice) + ')'
    : last.graph_node ? 'the graph walk stopped at ' + sgxWordsOf(last.graph_node) + (prof && prof.closed === false ? ' before its end node - the time budget' : '')
    : 'the structure ran out of turns';
  var node = sgNode({fam: 'COMMIT', label: 'END', text: 'the round ends after ' + turns.length + ' turns', sub: why, cls: 's3-sgx-end'},
    el('div', 's3-sgx-edges', sgxEdge('ends here', '', {kind: 'exit', word: 'ends the round'}, true, undefined),
      sgxEdge('another turn', '', {kind: 'ext', word: 'extends the exchange'}, false)));
  return node;
}
/* The spine between turn `prev` and turn `next` (next null: after the last). */
function sgxGap(ctx, conv, prev, next, evs) {
  var out = [], cast = null;
  (evs || []).forEach(function (ev) {
    var st = (ev.stages || [])[0] || {};
    if (SGX_GATE[st.stage] && (st.candidates || []).length > 1) out.push(sgxFork(conv, ev, ctx.api));
    else if (SGX_CAST[st.stage] && next) cast = ev;
    else out.push(sgRoll(conv, ev, null, ctx.api));
  });
  if (next) {
    turnEvents(conv, next).forEach(function (ev) {
      var sel = ev.selected || {};
      if (ev.family === 'CTS' && sel.id !== 'OBLIGATED' && sel.authority !== 'obligated') out.push(sgxCtsFork(conv, ev, next, ctx.api));
    });
    if (prev || cast) out.push(sgxHand(conv, prev, next, cast, evs, ctx.api));
  } else if (prev) {
    var end = sgxEnd(conv);
    if (end) out.push(end);
  }
  if (!out.length) return null;
  return el('div', {class: 's3-sgx-gap', 'data-gap': next ? next.turn_id : 'end'}, out);
}
/* After the round's turns are on the spine: the gap before each turn goes in
   front of its group, the round's close right after the last one. */
function sgxInterleave(ctx, conv, box) {
  var plan = sgxPlan(conv), turns = conv.turns || [], groups = {}, last = null;
  for (var c = box.firstElementChild; c; c = c.nextElementSibling) {
    if (c.classList.contains('s3-sgn-turn') && c.getAttribute('data-turn') && !groups[c.getAttribute('data-turn')]) groups[c.getAttribute('data-turn')] = c;
  }
  for (var i = 0; i < turns.length; i += 1) {
    var node = groups[turns[i].turn_id];
    if (!node) continue;
    var g = sgxGap(ctx, conv, i ? turns[i - 1] : null, turns[i], plan.gaps[i]);
    if (g) box.insertBefore(g, node);
    last = node;
  }
  var tail = last ? sgxGap(ctx, conv, turns[turns.length - 1], null, plan.gaps[turns.length]) : null;
  if (tail) last.after(tail);
}

/* One turn's lines in this segment, in ledger order, as pieces: runs of the
   turn's own words (its seat's voice, words found in the turn as written)
   cut where a sting or Sam's line came between; lines that only carry the
   turn's stamp are marked copies. */
function sgxSameSeat(l, t) {
  var seat = SGX_WHO_SEAT[String(l.who || '').toLowerCase()];
  if (seat && t.speaker) return seat === t.speaker;
  return sgxNorm(sgxVoice(l.who)) === sgxNorm(t.name);
}
/* A ledger row written before the stamp fix carries dice copied by AUDIO
   CHUNK, not by turn: its own dice.s3.turn_id may name another turn while
   its system3.turn_id (the line's turn_id here) is right. The row stays on
   its system3 turn; the dice are said to be unreliable, never shown as
   this turn's roll. */
function sgxBadDice(l) {
  var s3 = l && l.dice && l.dice.s3;
  var other = s3 && s3.turn_id ? String(s3.turn_id) : '';
  return other && other !== String(l.turn_id || '') ? other : '';
}
function sgxTurnRun(ctx, conv, t, here, slot) {
  var rows = (conv.lines || []).filter(function (l) {
    return l.turn_id === t.turn_id && here.has(l.line_id) && (isSpoken(l) || l.who === 'drop');
  });
  var stings = slot ? slot.before.concat(slot.after).filter(function (l) { return here.has(l.line_id); }) : [];
  var all = rows.concat(stings).sort(byLedger);
  var whole = sgxNorm(lineText(conv, t));
  var parts = [], pending = [], seen = {};
  all.forEach(function (l) {
    if (isBoard(l) || l.who === 'drop') { pending.push(l); return; }
    var words = sgxNorm(l.text);
    var genuine = sgxSameSeat(l, t) && (l.cont === true || !whole || !words || whole.indexOf(words.slice(0, 48)) >= 0);
    var last = parts.length ? parts[parts.length - 1] : null;
    var again = genuine && !!words && !!seen[words];
    if (last && !pending.length && genuine && last.genuine && !again && !last.again && last.block === l.block && last.who === l.who) {
      if (!last.badDice) last.badDice = sgxBadDice(l);
      last.lines.push(l);
      last.text += ' ' + String(l.text || '');
      if (words) seen[words] = 1;
      return;
    }
    parts.push({lines: [l], text: String(l.text || ''), who: l.who, block: l.block, genuine: genuine, again: again,
      cut: pending, blockChanged: !!last && last.block !== l.block, cont: l.cont === true, badDice: sgxBadDice(l)});
    pending = [];
    if (genuine && words) seen[words] = 1;
  });
  return {parts: parts, drawn: new Set(), split: parts.length > 1};
}
function sgxCutWords(p, prev) {
  if (prev && !prev.genuine) {
    return 'resumed after ' + sgxVoice(prev.who) + '\'s line that carries the same stamp (a copy)' +
      (p.cut.length ? ' and ' + sgxCutWords({cut: p.cut, cont: p.cont}, null).replace(/^split around /, '') : '');
  }
  var said = p.cut.map(function (l) {
    return isBoard(l) ? 'a sting (' + (boardName(l) || 'a clip') + ')' : sgxVoice(l.who) + '\'s line ("' + sgxClip(l.text, 60) + '")';
  });
  if (said.length) return 'split around ' + said.join(' and ') + (p.cont ? ' (the ledger marks it cont)' : '');
  if (p.cont) return 'the ledger marks it a continuation (cont)';
  return p.blockChanged ? 'picked up again in block ' + p.block : 'carried on in the next ledger row';
}
/* The message node(s) of a turn: the LINE node as it always was when the
   turn aired whole; its pieces as one continued turn when it was split. */
function sgxWords(ctx, conv, t, group, run, lineNode) {
  if (!run.split) { sgxMsg(ctx, conv, t, lineNode); group.append(lineNode); return; }
  var first = -1, k;
  for (k = 0; k < run.parts.length; k += 1) if (run.parts[k].genuine) { first = k; break; }
  var pieces = run.parts.filter(function (p) { return p.genuine; }).length;
  if (first < 0) { sgxMsg(ctx, conv, t, lineNode); group.append(lineNode); }
  var n = 0;
  run.parts.forEach(function (p, i) {
    p.cut.forEach(function (l) { if (isBoard(l)) { group.append(sgSting(l)); run.drawn.add(l.line_id); } });
    var name = sgxVoice(p.who).toUpperCase();
    if (p.genuine) n += 1;
    if (i === first) {
      var tx = lineNode.querySelector('.s3-sgn-text'), sub = lineNode.querySelector('.s3-sgn-sub');
      if (tx) tx.textContent = sgxClip(p.text, 600);
      if (sub) sub.textContent = 'piece 1 of ' + pieces + ' of one turn - block ' + p.block +
        (p.badDice ? ' - the dice on its row name ' + p.badDice + ' (copied by audio chunk): unreliable, not a roll of this turn' : '');
      lineNode.dataset.piece = '1';
      sgxMsg(ctx, conv, t, lineNode);
      group.append(lineNode);
      return;
    }
    if (p.genuine) {
      group.append(el('div', {class: 's3-sgx-contd-edge', 'data-piece': String(n)},
        el('span', {class: 's3-sgx-wire', 'aria-hidden': 'true'}),
        el('b', {text: '(CONT\'D)'}),
        el('span', {text: 'the same turn, ' + sgxCutWords(p, i ? run.parts[i - 1] : null) + ' - no roll'})));
      var node = sgNode({fam: 'LINE', label: name + ' (CONT\'D)', text: sgxClip(p.text, 600),
        sub: (p.again ? 'the same words aired again (block ' + p.block + '): a re-air, not new words - ' : '') + 'piece ' + n + ' of ' + pieces + ' of turn ' + (t.index + 1) +
          (p.badDice ? ' - the dice on its row name ' + p.badDice + ' (copied by audio chunk): unreliable, not a roll of this turn' : ''),
        cls: 's3-sgn-words s3-sgx-contd' + (p.again ? ' s3-sgx-again' : '')});
      node.dataset.piece = String(n);
      sgxMsg(ctx, conv, t, node);
      group.append(node);
      return;
    }
    var copy = sgNode({fam: 'LINE', label: name, text: sgxClip(p.text, 600),
      sub: 'carries turn ' + (t.index + 1) + '\'s stamp, but ' + (sgxSameSeat(p.lines[0], t) ? 'these words are not the turn\'s' : 'not the voice of its seat') +
        ' - a copied stamp: drawn under the turn it claims, not an exchange of its own (block ' + p.block + ')' +
        (p.badDice ? '; its own dice name ' + p.badDice + ' (unreliable)' : ''),
      cls: 's3-sgx-copy'});
    copy.dataset.line = p.lines[0].line_id || '';
    group.append(copy);
  });
}

/* The message node opens in place: the breakdown goes INSIDE the node, and
   comes out again leaving the node exactly as it was. */
function sgxMsg(ctx, conv, t, node) {
  node.classList.add('s3-sgn-open');
  node.classList.add('s3-sgx-msg');
  node.setAttribute('role', 'button');
  node.setAttribute('tabindex', '0');
  node.setAttribute('aria-expanded', 'false');
  node.title = 'Tap to open the tables that composed this message; tap again to fold it back';
  node.addEventListener('click', function (e) {
    var hit = e.target && e.target.closest ? e.target.closest('a, button, summary, details, input, select, video, audio, .s3-sgx-exp') : null;
    /* a control inside the node keeps its own tap - also the fold button,
       whose own click has already taken the breakdown out of the page */
    if (hit && hit !== node && (node.contains(hit) || !hit.isConnected)) return;
    e.stopPropagation();
    sgxToggle(ctx, conv, t, node);
  });
  node.addEventListener('keydown', function (e) {
    if (e.target !== node || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    sgxToggle(ctx, conv, t, node);
  });
}
function sgxToggle(ctx, conv, t, node) {
  var body = node.querySelector('.s3-sgn-body');
  if (!body) return;
  if (node.getAttribute('aria-expanded') === 'true') {
    if (node.sgxBox && node.sgxBox.parentNode) node.sgxBox.parentNode.removeChild(node.sgxBox);
    node.classList.remove('s3-sgx-open');
    node.setAttribute('aria-expanded', 'false');
    return;
  }
  if (!node.sgxBox) node.sgxBox = sgxBreakdown(ctx, conv, t, function () { sgxToggle(ctx, conv, t, node); });
  body.appendChild(node.sgxBox);
  node.classList.add('s3-sgx-open');
  node.setAttribute('aria-expanded', 'true');
}
/* One draw as the node's breakdown shows it: the family, the table, every
   stage with the pick and its d100, the weights folded. */
function sgxDraw(conv, ev, t, api) {
  var sel = ev.selected || {};
  var line = eventLine(ev, conv);
  var what = (FAMILY_WHAT[ev.family] || [ev.family])[0];
  var steps = [];
  if (sel.table) steps.push(el('span', {class: 's3-sgx-step'}, el('i', {text: 'table'}), ' ', el('b', {text: String(sel.table)})));
  (ev.stages || []).forEach(function (st) {
    if (st.stage === 'table' && sel.table && String(st.selected) === String(sel.table)) return;
    var c = (st.candidates || []).filter(function (x) { return x.id === st.selected; })[0];
    var lab = c ? String(c.label || c.id) : (st.selected == null ? '' : String(st.selected));
    var d = sgxStageDice(st);
    var of = (st.candidates || []).length;
    if (steps.length) steps.push(el('span', {class: 's3-sgx-arrow', 'aria-hidden': 'true', text: '->'}));
    steps.push(el('span', {class: 's3-sgx-step'}, el('i', {text: st.stage}), ' ', el('b', {text: sgxClip(lab, 80)}),
      of > 1 ? el('span', {class: 's3-muted', text: ' of ' + of}) : null,
      d != null ? die(d) : el('span', {class: 's3-muted', text: of === 1 ? ' (the only one)' : ' (no roll)'})));
  });
  var weighed = (ev.stages || []).filter(function (st) { return (st.candidates || []).length > 1; });
  var fold = null;
  if (weighed.length) {
    var inner = el('div', 's3-sgx-weights-body');
    fold = el('details', 's3-sgx-weights', el('summary', {text: 'the weights (' + weighed.length + ' table' + (weighed.length === 1 ? '' : 's') + ')'}), inner);
    fold.addEventListener('toggle', function () {
      if (fold.open && !inner.childElementCount) {
        var kids = [];
        weighed.forEach(function (st) { kids.push(el('div', {class: 's3-muted', text: st.stage})); stageStory(st, ev, conv, t).forEach(function (k) { kids.push(k); }); });
        fill(inner, kids);
      }
    });
  }
  var perf = ev.family === 'ES' && t && t.performance ? t.performance : null;
  return el('div', {class: 's3-sgx-draw', style: '--fam:' + (FAM[ev.family] || 'var(--obs)'), 'data-event': ev.event_id || '', 'data-family': ev.family},
    el('div', 's3-sgx-drawhead', die(line.dice), el('b', {class: 's3-sgn-fam', text: ev.family}),
      el('span', {class: 's3-sgx-landed', text: sgxClip(landedWords(ev, conv) || line.text, 160)}),
      btn('Card', function () { openDecision(conv, ev, t, api); }, {class: 's3-sgx-card', title: 'the full decision card for this draw'})),
    el('div', {class: 's3-muted', text: what}),
    steps.length ? el('div', 's3-sgx-path', steps) : para((ev.meta || {}).why || (sel.authority ? 'not drawn: ' + sel.authority : 'decided by a rule, not a roll'), 's3-muted'),
    perf ? el('div', {class: 's3-sgx-voice s3-muted', text: 'the voice it asked for: pace ' + num(perf.pace) + ', energy ' + num(perf.energy) + ', warmth ' + num(perf.warmth) + ', pauses ' + (perf.pause_style || '-')}) : null,
    fold);
}
function sgxBreakdown(ctx, conv, t, fold) {
  var cast = sgxPlan(conv).cast[t.turn_id] || null;
  var cst = cast ? ((cast.stages || [])[0] || {}) : null;
  var evs = turnEvents(conv, t).slice().sort(function (a, b) {
    return (a.family === 'ES' ? -1 : 0) - (b.family === 'ES' ? -1 : 0) || sgxSeq(a) - sgxSeq(b);
  });
  var who = String(t.name || t.speaker || '?');
  var rows = [
    el('div', 's3-sgx-exphead', el('b', {text: 'What composed this message'}),
      el('span', {class: 's3-muted', text: ['turn ' + (t.index + 1), who, t.step_label || t.step || '', t.phase || '', t.graph_node ? 'node ' + sgxWordsOf(t.graph_node) : ''].filter(Boolean).join(' - ')})),
    el('div', 's3-sgx-cast', el('b', {class: 's3-sgn-fam', text: 'CAST'}), cst ? die(sgxStageDice(cst)) : null,
      el('span', {text: cst ? who + ' ' + (cst.stage === 'initiator' ? 'opened the round' : 'won the seat') + ' in a pool of ' +
        (cst.candidates || []).map(function (c) { return sgxSeatName(conv, c.id) + ' ' + sgxShare(cst, c); }).join(' / ')
        : who + ' held this seat by the structure\'s order - no raffle on the record'}))];
  if (!evs.length) rows.push(para('No draw is recorded on this turn.', 's3-muted'));
  evs.forEach(function (ev) { rows.push(sgxDraw(conv, ev, t, ctx.api)); });
  var dirs = (t.directions || []).map(function (d) { return d && d.text; }).filter(Boolean);
  if (dirs.length) rows.push(el('div', 's3-sgx-dirs', el('b', {text: 'What it told the writer: '}), dirs.join('; ')));
  if (t.protocol) rows.push(el('div', {class: 's3-sgx-dirs s3-muted', text: 'the node\'s protocol: ' + sgxClip(t.protocol, 400)}));
  if (t.text) rows.push(el('details', 's3-sgx-weights', el('summary', {text: 'the turn as written'}), el('blockquote', {class: 's3-dquote', text: t.text})));
  rows.push(el('div', 's3-row', btn('Fold back to the message', fold, {class: 's3-sgx-fold'})));
  return el('div', {class: 's3-sgx-exp', role: 'group', 'aria-label': 'what composed this message'}, rows);
}

function sgTurn(ctx, conv, t, here, elsewhere) {
  const lines = (conv.lines || []).filter(l => l.turn_id === t.turn_id && here.has(l.line_id));
  const spoken = lines.filter(isSpoken);
  const idx = scriptIndexOf(conv, t);
  const perf = t.performance || {};
  const away = !lines.length && elsewhere;
  const group = el('div', {class: 's3-sgn-turn' + (away ? ' away' : ''), 'data-turn': t.turn_id});
  group.append(sgNode({fam: 'COMMIT', label: `TURN ${t.index + 1}`,
    text: `${t.name || t.speaker} · ${t.step_label || t.leg || t.step || ''}${t.phase ? ' · ' + t.phase : ''}`,
    sub: [replyCaption(t), perf.emotion ? `${perf.emotion} ${num(perf.intensity)}` : '', away ? 'its line went out in another segment' : '',
      (t.directions || []).map(d => d.text).join('; ')].filter(Boolean).join(' · '), cls: 's3-sgn-turnhead'}));
  for (const ev of turnEvents(conv, t)) group.append(sgRoll(conv, ev, t, ctx.api));
  /* the insets: what came into the turn from outside the writer's words */
  for (const sb of (t.speakerbox || []).filter(s => s.mode && s.mode !== 'NONE')) {
    const mat = sb.material || {};
    const ev = (conv.decision_events || []).find(e => e.event_id === sb.event_id);
    group.append(sgNode({fam: 'SPEAKERBOX', label: 'INSET', text: `${String(sb.mode).toLowerCase().replace('_', ' ')} - ${mat.file || sb.unmet || 'no passage fetched'}`,
      sub: (SB_WORD[sb.mode] || '') + (mat.text ? ': "' + String(mat.text).replace(/\s+/g, ' ').slice(0, 260) + '"' : ''),
      cls: 's3-sgn-inset', onOpen: ev ? () => openDecision(conv, ev, t, ctx.api) : null}));
  }
  if (t.topic_material && t.topic_material.text) {
    group.append(sgNode({fam: 'TOPIC', label: 'INSET', text: 'a second subject - ' + (t.topic_material.file || ''),
      sub: String(t.topic_material.text).replace(/\s+/g, ' ').slice(0, 260), cls: 's3-sgn-inset'}));
  }
  const slot = boardPlan(conv).get(t.turn_id);
  const sgxRun = sgxTurnRun(ctx, conv, t, here, slot);   /* [s3graphix] */
  for (const l of slot ? slot.before : []) if (here.has(l.line_id) && !sgxRun.drawn.has(l.line_id)) group.append(sgSting(l));
  const said = idx == null ? [] : (conv.observations_air || []).filter(o => o.family === 'SFXGUY' && o.turn_index === idx);
  /* gold bars, re-airs and anything else that carries a line into this turn with its own stamp */
  const stamped = lines.filter(l => !isSpoken(l) && !isBoard(l) && l.who !== 'drop' &&
    (l.gold || l.replay_of || /gold|replay|re-?air/i.test(String(l.kind || l.who || ''))));
  const words = lineText(conv, t) || spoken.map(l => l.text).join(' ');
  const sgxLine = (sgNode({fam: 'LINE', label: 'LINE', text: words ? String(words).replace(/\s+/g, ' ').slice(0, 600) : 'no words - ' + (t.status || 'planned'),
    sub: spoken.length ? `${spoken.length} line${spoken.length === 1 ? '' : 's'} in the script (block ${spoken[0].block})` : '',
    cls: 's3-sgn-words'}));
  sgxWords(ctx, conv, t, group, sgxRun, sgxLine);   /* [s3graphix] the message node(s) */
  for (const l of slot ? slot.after : []) if (here.has(l.line_id) && !sgxRun.drawn.has(l.line_id)) group.append(sgSting(l));
  for (const o of said) {
    const draws = o.draws || [];
    const last = draws[draws.length - 1] || null;
    group.append(sgNode({fam: 'SFXGUY', label: 'SFX GUY', dice: last ? last.dice : null, text: o.line || '(no words)',
      sub: [SFXGUY_KIND[o.kind] || o.kind || '', last ? `${last.index} of ${last.of} in the ${last.pool} pool` : String(o.how || '')].filter(Boolean).join(' · '),
      cls: 's3-sgn-inset'}));
  }
  for (const l of stamped) {
    group.append(sgNode({fam: 'TINT', label: l.replay_of ? 'RE-AIR' : 'GOLD', text: String(l.text || '').slice(0, 300),
      sub: [l.replay_of ? 'first aired as ' + l.replay_of : '', l.gold && typeof l.gold === 'object' ? 'from ' + (l.gold.conversation_id || '') + ' ' + (l.gold.turn_id || '') : ''].filter(Boolean).join(' · '),
      cls: 's3-sgn-inset'}));
  }
  for (const o of (conv.observations_air || []).filter(o => o.family === 'INJECT' && o.turn_id === t.turn_id)) group.append(sgInject(o));   /* [s3-inject] */
  const airNode = sgNode({fam: 'COMMIT', label: 'AIR', text: lines.length ? 'reading the receipts...' : sgAirWord(lines, ctx.air).word, cls: 's3-sgn-air'});
  airNode.dataset.lines = lines.map(l => l.line_id).join(',');
  group.append(airNode);
  return group;
}

/* One conversation of the segment, chained in the order it was built. */
function sgConversation(ctx, c) {
  const conv = c.conversation || null;
  const single = !!c.single;
  const planned = c.planned_in || {};
  const seg = ctx.segment || {};
  const facts = [
    c.created ? 'planned ' + clock(Number(c.created)) : '',
    planned.id && planned.id !== seg.id ? `while ${sgName(planned)} was on air` : '',
    c.bank ? 'written ahead for the bank' : (c.created ? 'written live' : ''),
    c.prepared_for ? (c.prepared_for === seg.id ? 'System2 wrote it for this entry' : 'System2 wrote it for ' + c.prepared_for) : '',
    c.structure && c.structure.id ? 'structure ' + c.structure.id + (c.structure.version ? ' v' + c.structure.version : '') + (c.structure.variant ? ' (variant ' + c.structure.variant + ')' : '') : '',
    c.length ? `length ${c.length.turns} turns (band ${c.length.lo}-${c.length.hi})` : '',
    c.verdict ? 'checker: ' + c.verdict : ''].filter(Boolean);
  const box = el('section', {class: 's3-sgn-conv' + (single ? ' single' : ''), 'data-conv': c.conversation_id || ''});
  box.append(sgNode({fam: single ? 'LINE' : 'CTS', label: String(c.road || 'conversation').toUpperCase().replace(/_/g, ' '),
    text: (single ? 'a single line' : `a round of ${(c.turns || []).length} turns`) + ` · ${c.mode || ''} · ${c.lines || 0} line${c.lines === 1 ? '' : 's'} in this segment`,
    sub: facts.join(' · '), cls: 's3-sgn-convhead'},
    c.topic ? el('div', {class: 's3-sgn-topic', text: c.topic}) : null));
  if (c.gone) { box.append(sgNode({fam: 'COMMIT', label: 'GONE', text: c.why || 'past retention'})); return box; }
  const cid = c.conversation_id;
  if (!conv) {
    /* the compact record: the rolls and the turns, each card fetched when opened */
    for (const r of (c.rolls || []).filter(x => x.family !== 'STATION')) box.append(sgCompactRoll(ctx.request, cid, r, null, ctx.api));
    for (const t of c.turns || []) {
      const g = el('div', 's3-sgn-turn');
      g.append(sgNode({fam: 'COMMIT', label: `TURN ${Number(t.index) + 1}`, text: `${t.name || t.speaker || ''} · ${t.step || ''}`, cls: 's3-sgn-turnhead'}));
      for (const r of t.rolls || []) g.append(sgCompactRoll(ctx.request, cid, r, null, ctx.api));
      if (t.text) g.append(sgNode({fam: 'LINE', label: 'LINE', text: String(t.text).slice(0, 600), cls: 's3-sgn-words'}));
      box.append(g);
    }
    return box;
  }
  const evs = (conv.decision_events || []).filter(e => !e.turn_id && !e.stage && e.kind !== 'observation');
  const own = evs.filter(e => e.family !== 'STATION' && !sgxPlaced(conv, e));   /* [s3graphix] */
  const station = evs.filter(e => e.family === 'STATION');
  const spont = own.filter(e => SG_SPONTANEITY.has(e.family)).length;
  if (own.length) {
    box.append(el('div', {class: 's3-sgn-caption s3-muted', text: (single ? 'its own rolls' : "the round's own rolls") +
      (spont ? ` - ${spont} of them its spontaneity (tempers, shocks, interjections, events, favourites, directives, the carry)` : '')}));
    for (const ev of own) box.append(sgRoll(conv, ev, null, ctx.api));
  }
  if (station.length) {
    /* the station's own dice, rolled on this task before the round was planned:
       folded to a count, opened on a tap */
    const list = el('div', 's3-sgn-station-list');
    const fold = el('details', {class: 's3-sgn s3-sgn-station', style: '--fam:var(--obs)'},
      el('summary', null, el('span', {class: 's3-sgn-dot', 'aria-hidden': 'true'}), el('b', {class: 's3-sgn-fam', text: 'STATION'}),
        el('span', {class: 's3-sgn-text', text: `${station.length} roll${station.length === 1 ? '' : 's'} the station made before this was planned`})),
      list);
    fold.addEventListener('toggle', () => { if (fold.open && !list.childElementCount) fill(list, ...station.map(ev => sgRoll(conv, ev, null, ctx.api))); });
    box.append(fold);
  }
  const plan = conv.plan || {};
  if (plan.line != null && plan.choice != null) {
    /* a line drawn off its road's own list: no writer wrote it, the LINE draw chose it */
    box.append(sgNode({fam: 'LINE', label: 'NO WRITER', text: `the words were drawn off its list - ${Number(plan.choice) + 1} of ${((conv.inputs || {}).candidates || []).length || '?'}`,
      sub: (conv.inputs || {}).candidates_from ? 'the list: ' + conv.inputs.candidates_from : 'the LINE roll below chose them'}));
  } else if (!single || plan.sheet) {
    box.append(sgPrompt(ctx.request, conv, ctx.state));
  }
  const here = new Set(c.line_ids || []);
  const elsewhere = new Set((conv.lines || []).filter(l => l.turn_id && !here.has(l.line_id)).map(l => l.turn_id));
  for (const t of conv.turns || []) box.append(sgTurn(ctx, conv, t, here, elsewhere.has(t.turn_id)));
  {   /* [s3-inject] a forced node that names no turn of this round joins it after the turns */
    const tids = new Set((conv.turns || []).map(t => t.turn_id));
    for (const o of (conv.observations_air || []).filter(o => o.family === 'INJECT' && !tids.has(o.turn_id))) box.append(sgInject(o));
  }
  const val = conv.validation || {};
  if (val.verdict) {
    box.append(sgNode({fam: 'REPAIR', label: 'CHECKED', text: `${val.verdict} ${num(val.score)}`,
      sub: [val.written != null ? `${val.written} of ${val.planned} turns written` : '', val.seat_order != null ? 'seat order ' + pct(val.seat_order) : ''].filter(Boolean).join(' · ')}));
  }
  sgxInterleave(ctx, conv, box);   /* [s3graphix] forks, handoffs, expansions between the turns */
  return box;
}

/* The segment itself: the entry the clock put on air, and why it held what it
   held - filled when the director has answered. */
function sgSegmentHead(tr) {
  const seg = tr.segment || {};
  const convs = tr.conversations || [];
  const lines = (tr.blocks || []).reduce((a, b) => a + (Number(b.lines) || 0), 0);
  const decision = el('div', 's3-sgn-decision', para('Asking the director how this entry was scheduled...', 's3-muted'));
  const node = sgNode({fam: 'COMMIT', label: 'SEGMENT', text: `${sgName(seg)} · ${sgWindow(seg)}`,
    sub: [seg.engine === 'system2' ? `System2's entry ${Number(seg.index || 0) + 1} of the hour ${seg.hour || ''}` : 'the running order',
      tr.registered === false ? (tr.why || 'nothing of it has reached the script yet')
        : `${tr.rounds || 0} round${tr.rounds === 1 ? '' : 's'}, ${tr.singles || 0} single line${tr.singles === 1 ? '' : 's'}, ${lines} line${lines === 1 ? '' : 's'} in the script`]
      .filter(Boolean).join(' · '), cls: 's3-sgn-seghead'}, decision);
  node.fillDecision = (sched, prepared) => {
    const e = (sched && sched.entry) || null;
    const o = (e && e.orchestration) || {};
    const census = (sched && sched.census) || null;
    const mine = census && (census.entries || []).find(x => x.label === (e && e.label) || x.label === seg.label);
    const rows = [];
    if (e) {
      rows.push(el('div', 's3-row', el('span', {class: 's3-pill', text: e.state || '?'}),
        el('span', {class: 's3-muted', text: `${num((Number(e.deadline) - Number(e.start)) / 60, 1)} min owned · ${num(e.own_seconds, 0)} s of its own on air of ${num(e.aired_seconds, 0)} s heard in its window`})));
      if (o.target) rows.push(kv([['the plan asked', `${o.target.lines ?? '?'} lines, ${num(o.target.seconds, 0)} s`],
        ['it had', `${(o.have || {}).lines ?? '?'} lines, ${num((o.have || {}).seconds, 0)} s`],
        ['short', `${(o.short || {}).lines ?? '?'} lines, ${num((o.short || {}).seconds, 0)} s`]]));
      const dir = e.direction || {};
      if (dir.clause || (dir.standing || []).length) rows.push(el('div', 's3-sgn-sub', el('b', {text: 'Direction in force: '}), dir.clause || (dir.standing || []).map(x => x.text).join('; ')));
      if (e.review && e.review.state) rows.push(el('div', {class: 's3-sgn-sub s3-muted', text: 'review: ' + e.review.state}));
      if (e.prompt) rows.push(sgTextFold('The entry\'s standing instruction', e.prompt));
    }
    if (census) {
      rows.push(el('div', 's3-sgn-sub', el('b', {text: `The ${census.kind || seg.kind} road's census now: `}), census.say || ''));
      if (mine) rows.push(el('div', {class: 's3-sgn-sub s3-muted', text: `${mine.label}: ${mine.commit || ''} - ${mine.why || ''}`}));
    }
    if ((prepared || []).length) rows.push(el('div', {class: 's3-sgn-sub s3-muted', text: `System2 wrote ${prepared.length} for it: ` +
      prepared.map(p => `${p.road} (${p.status || '?'})`).join(', ')}));
    for (const w of (sched && sched.why) || []) rows.push(para(w, 's3-muted'));
    if (sched && sched.note) rows.push(para(sched.note + ' (' + clock(Number(sched.read_at || 0)) + ')', 's3-muted'));
    fill(decision, ...(rows.length ? rows : [para('The director holds nothing for this entry.', 's3-muted')]));
  };
  return node;
}

/* Roll the dice on show once, a little staggered, when motion is allowed. */
function sgRollIn(root) {
  if (reduced()) return;
  const faces = [...root.querySelectorAll('.s3-sgn-line > .s3-die:not(.none)')].slice(0, 48);
  faces.forEach((f, k) => { const n = f.closest('.s3-sgn'); if (n && n.face && n.face.roll) setTimeout(() => n.face.roll(420 + (k % 8) * 70), 60 + k * 35); });
}

export async function mountSegmentNodes(root, {request, segment = '', conversation = '', lineId = '', onSegment = null} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-sgn-root');
  const v = makeViews({request});
  const state = {callCache: new Map(), alive: true, id: '', trace: null, settled: Promise.resolve()};
  fill(root, para('Finding the segment...', 's3-muted'));
  /* The chain is drawn as soon as the segment is read; the director's answer
     and the air's receipts fill their own nodes when they come, in place -
     nothing above the reader grows or moves for them. */
  async function show(id) {
    const want = String(id || '');
    state.id = want;
    state.settled = Promise.resolve();
    if (!want) { fill(root, para('This was not stamped with a scheduled segment - it went out before the segment stamp, or while the station ran no schedule.', 's3-muted')); return null; }
    fill(root, para('Reading the segment ' + want + '...', 's3-muted'));
    const asked = sgTrace(request, want, {full: false, scheduling: true});
    asked.catch(() => {});
    let tr;
    try { tr = await sgTrace(request, want, {full: true, scheduling: false}); }
    catch (e) {
      if (state.alive && state.id === want) fill(root, para('The segment could not be read: ' + String((e && e.message) || e), 's3-error'));
      return null;
    }
    if (!state.alive || state.id !== want) return null;
    state.trace = tr;
    const ctx = {request, api: v.api, air: v.air, state, segment: tr.segment};
    const head = sgSegmentHead(tr);
    const chain = el('div', 's3-sgn-chain', head, ...(tr.conversations || []).map(c => sgConversation(ctx, c)));
    if (!(tr.conversations || []).length) chain.append(para(tr.registered === false ? 'Nothing of this segment is in the script yet.' : 'No System 3 conversation went out in this segment.', 's3-muted'));
    fill(root, chain);
    sgRollIn(chain);
    if (onSegment) { try { onSegment(tr); } catch (e) { /* the host's own */ } }
    const live = () => state.alive && state.id === want;
    const decided = asked.then(got => { if (live()) head.fillDecision((got || {}).scheduling, tr.prepared_for || []); },
      err => { if (live()) head.fillDecision({why: ['the director could not be asked: ' + String((err && err.message) || err)]}, tr.prepared_for || []); });
    /* the air's receipts, for the blocks this segment holds: three asks at a
       time, each block's AIR nodes filled as its answer lands */
    const paintAir = () => {
      for (const n of chain.querySelectorAll('.s3-sgn-air')) {
        const ids = String(n.dataset.lines || '').split(',').filter(Boolean);
        if (!ids.length || !ids.some(x => v.air.has(x))) continue;
        const got = sgAirWord(ids.map(x => ({line_id: x})), v.air);
        const t = n.querySelector('.s3-sgn-text');
        if (t) t.textContent = got.word;
        n.classList.toggle('heard', got.cls === 'heard');
        n.classList.toggle('gone', got.cls === 'gone');
      }
    };
    const heard = (async () => {
      const blocks = (tr.blocks || []).slice(0, 16).map(x => x.block);
      let next = 0;
      const worker = async () => {
        while (next < blocks.length && live()) {
          const b = blocks[next++];
          try {
            const got = await request('/api/segment/inspect?block=' + encodeURIComponent(b));
            for (const l of (got && got.lines) || []) v.air.set(l.line_id, l);
          } catch (e) { /* that block's receipts stay unread */ }
          if (live()) paintAir();
        }
      };
      await Promise.all([worker(), worker(), worker()]);
      if (!live()) return;
      for (const n of chain.querySelectorAll('.s3-sgn-air')) {
        const t = n.querySelector('.s3-sgn-text');
        if (t && /reading the receipts/.test(t.textContent)) t.textContent = 'no air receipt yet';
      }
    })();
    state.settled = Promise.allSettled([decided, heard]);
    return tr;
  }
  const first = await sgResolve(request, {segment, conversation, lineId});
  await show(first);
  return {
    show,
    segment: () => state.id,
    trace: () => state.trace,
    settled: () => state.settled,             /* the director's answer and the receipts, filled */
    dispose() { state.alive = false; v.alive = false; fill(root); }
  };
}

/* THE INSPECTOR: the chain of one segment, and every other segment to pick -
   the ones the script went through, in its order, and the entries still to
   come on the director's sheet. */
export async function mountSegmentInspector(root, {request, segment = '', conversation = '', lineId = '', hours = 6, pick: choose = false} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-sgi');
  const pick = el('select', {class: 's3-sgi-pick', 'aria-label': 'the segment to inspect'});
  const prev = sgIcon('c:caret--left', 'The segment before', () => step(-1), {}, 'Before');
  const next = sgIcon('c:caret--right', 'The segment after', () => step(1), {}, 'After');
  const note = el('span', {class: 's3-muted s3-sgi-note'});
  const scroller = el('div', 's3-sgi-body');
  const bar = el('div', 's3-sgi-bar', el('b', {text: 'Segment'}), prev, pick, next, note);
  fill(root, bar, scroller);
  let list = [], nodes = null, alive = true;
  const optionOf = s => el('option', {value: s.id, text: `${sgHm(s.start)} ${sgName(s)}` + (s.rounds != null ? ` - ${s.rounds} round${s.rounds === 1 ? '' : 's'}, ${s.singles} single line${s.singles === 1 ? '' : 's'}` : '')});
  async function readList() {
    let got = {};
    try { got = await request('/api/system3/segments?' + new URLSearchParams({since: String(Date.now() / 1000 - hours * 3600), limit: '120', plan: '1'})); }
    catch (e) { note.textContent = 'the segment list could not be read: ' + e.message; }
    const seen = new Set();
    list = (got.segments || []).map(s => { seen.add(s.id); return s; });
    const now = got.now && got.now.id ? got.now : null;
    const ahead = (((got.plan || {}).entries) || []).filter(e => e.occurrence && !seen.has(e.occurrence) && Number(e.deadline) > Date.now() / 1000)
      .map(e => ({id: e.occurrence, label: e.label, kind: e.kind, start: e.start, ends: e.deadline, state: e.state}));
    const aired = el('optgroup', {label: 'in the script, in its order'}, ...list.map(optionOf));
    const coming = ahead.length ? el('optgroup', {label: 'on the sheet, still to come'}, ...ahead.map(s => optionOf(s))) : null;
    if (now && !seen.has(now.id) && !ahead.some(x => x.id === now.id)) aired.append(optionOf(now));
    fill(pick, aired, coming);
    list = [...list, ...(now && !seen.has(now.id) ? [now] : []), ...ahead.filter(x => !now || x.id !== now.id)];
    return got;
  }
  function paintPick(id) {
    if (![...pick.options].some(o => o.value === id) && id) pick.prepend(el('option', {value: id, text: id}));
    pick.value = id;
    const i = list.findIndex(s => s.id === id);
    prev.disabled = i <= 0;
    next.disabled = i < 0 || i >= list.length - 1;
  }
  /* the operator picked another segment: the one scroll here brings its chain
     to the top of whatever scrolls the inspector */
  function toTop() {
    for (let p = root.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight) {
        p.scrollTop = Math.max(0, p.scrollTop + root.getBoundingClientRect().top - p.getBoundingClientRect().top);
        return;
      }
    }
    if (/(auto|scroll)/.test(getComputedStyle(root).overflowY)) root.scrollTop = 0;
  }
  async function open(id, picked = false) {
    if (!alive) return;
    if (picked) toTop();
    if (nodes) nodes.dispose();
    const host = el('div');
    fill(scroller, host);
    nodes = await mountSegmentNodes(host, {request, segment: id});
    paintPick(nodes.segment());
  }
  function step(d) {
    const i = list.findIndex(s => s.id === pick.value);
    const to = list[i + d];
    if (to) open(to.id, true);
  }
  /* "Inspect other segments": the picker opens out as the list of them to pick
     from, and folds back to one line when one is picked */
  const unfold = () => {
    const n = pick.options.length + pick.querySelectorAll('optgroup').length;
    pick.size = Math.max(2, Math.min(10, n));
    pick.classList.add('open');
    pick.focus({preventScroll: true});
  };
  pick.addEventListener('change', () => {
    if (pick.size > 1) { pick.size = 1; pick.classList.remove('open'); }
    open(pick.value, true);
  });
  const [, first] = await Promise.all([readList(), sgResolve(request, {segment, conversation, lineId})]);
  await open(first || (list.length ? list[list.length - 1].id : ''));
  if (choose && alive) unfold();
  return {
    open: id => open(id, true),
    choose: unfold,
    settled: () => (nodes ? nodes.settled() : Promise.resolve()),
    segment: () => (nodes ? nodes.segment() : ''),
    async refresh() { await readList(); paintPick(nodes ? nodes.segment() : ''); },
    dispose() { alive = false; if (nodes) nodes.dispose(); fill(root); }
  };
}

/* The inspector in a sheet over the page: Escape, the close button or a tap
   outside it closes it; the broadcast ducks to the report level while it is
   open. Returns the close function. */
export function openSegmentInspector({request, segment = '', conversation = '', lineId = '', pick = false} = {}) {
  request ||= defaultRequest();
  const back = el('div', {class: 's3 s3-modal-back s3-sgi-back'});
  const before = document.activeElement;
  let view = null, closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    back.remove(); document.removeEventListener('keydown', onKey, true);
    if (view) view.dispose();
    if (before && before.focus) before.focus({preventScroll: true});      /* never a scroll the operator did not make */
  };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const shut = btn('Close', close, {class: 's3-modal-close', 'aria-label': 'Close'});
  const host = el('div', 's3-sgi-host');
  back.append(movableModal(el('section', {class: 's3-modal s3-sgi-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How the segment was built'}, shut, host)));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-segment-inspector', window.PineDuck.REPORT, back);
  mountSegmentInspector(host, {request, segment, conversation, lineId, pick}).then(x => { view = x; if (closed) x.dispose(); }, () => {});
  shut.focus({preventScroll: true});
  return close;
}

/* [s3-segment-nodes] THE HEADER'S NODE TOGGLE: a Carbon icon that turns a
   section's body into its node chain in place, and back. The section keeps its
   height's neighbours still: the body is hidden, not removed, so the
   conversation comes back exactly as it was. Returns the button for a header
   to carry. */
export function segmentNodesToggle({request, segment = '', conversation = '', body = null, onToggle = null} = {}) {
  request ||= defaultRequest();
  let nodes = null, host = null, on = false;
  const b = sgIcon('c:chart--network', 'Show how this segment was built, as its nodes', async e => {
    if (e) e.stopPropagation();
    on = !on;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', String(on));
    b.title = on ? 'Back to the conversation' : 'Show how this segment was built, as its nodes';
    if (!body) return;
    if (on) {
      host = host || el('div', 's3-sgn-inline');
      body.hidden = true;
      body.after(host);
      if (!nodes) nodes = await mountSegmentNodes(host, {request, segment, conversation});
    } else {
      if (host) host.remove();
      body.hidden = false;
    }
    if (onToggle) onToggle(on);
  }, {class: 's3-ibtn s3-sgn-toggle', 'aria-pressed': 'false'}, 'Nodes');
  b.dispose = () => { if (nodes) nodes.dispose(); if (host) host.remove(); if (body) body.hidden = false; };
  return b;
}


/* ======================================================================== */
/* [s3-focus] ONE MESSAGE, ZEROED IN.
 *
 * "And the examinate in depth window offer a three icon at the top, just
 *  like the one in the viewport, that when clicked switches the view over to
 *  the system three view focused on this. I want to tab over to a system
 *  three system that is focused on the message at hand, but encompasses all
 *  of the views shown here, but zeroed in on the message at hand and how
 *  these elements played into it, allowing me to edit and prevent it from
 *  happening again and also to see what events contributed to it and what
 *  prompts bu built it and how it came to be." (operator, 2026-09-28)
 *
 * openSystem3Focus({request, lineId, onBack}) opens the System 3 window -
 * mount(), its tabs and its editors - on one line. A bar under the window's
 * head names the message and holds the two ways out: back to the Examine
 * window (Close, Escape and the backdrop do the same), and all of System 3.
 * The tabs keep their names; each one zeroes in on the message:
 *
 *   This message   how it came to be, station by station: the road and the
 *                  round, the round's rolls, the node, the dice on its
 *                  turn, the row System 3 wrote, the prompt, the words,
 *                  the air - each with its lever and a way to its tab
 *   Visual Prompt  the window's own Visual Prompt, opened on its round and turn
 *   Tables         every decision that built its turn - table, category,
 *                  item, the d100 and u, the weight share, the threshold or
 *                  rule, and why - then the round's rolls and the station's
 *   Segments       its segment's node graph with its node lit, and the
 *                  round as a chain of nodes, one per message
 *   Prompts        the model call that wrote it, the prompt blocks as System
 *                  3 decided them (the system prompt, memory, insets, the
 *                  running order, what was rolled), the spontaneity rolls
 *                  and gold, the prompt as sent, and the layers to edit
 *   Audit          the ledger's events that made it, in ledger order
 *   Sys3           the circuit it travelled, lit where it went, replayable
 *   Director       its round, the running order with its row marked, the
 *                  exchange around it and the script ledger around it on air
 *   Structure      its road's structure with its leg lit
 *   Controls       the behaviour controls its rolls answered to
 *
 * THE PREVENT LEVERS go through doors that already exist and are pressed
 * by hand - nothing is written until a Save: an item or a pool option
 * switched off or weighed down (PUT /api/system3/tables/<id>, the Tables
 * editor's), a station roll's odds (the same, STATION1), a list row's
 * words, switch or removal (/api/system3/lists/<id>/rows/<row>, which
 * writes at once, as the lists editor does), a node's act or draws (PUT
 * /api/system3/structures/<road> or /structure, the Segments editor's), a
 * prompt block's kind (PUT /api/system3/config/section/blocks), a control
 * (POST /api/system3/settings) and the system prompt's layers (POST
 * /api/paperwork/field, the inspector's own door). A save is for the next
 * round; this message keeps the version it was planned under, and says so.
 *
 * Nothing here scrolls on its own and nothing polls: a save updates its own
 * lever in place, and the page stays where the reader left it.
 *
 * mount() reaches this through one call, s3FocusLens(root, ctx), made only
 * for a root openSystem3Focus registered, and one line in its tab router. */
const FOCUS_OF = new WeakMap();          /* the window's root -> the line it was opened on */
const FX_TABS_HELP = {
  focus: 'How this message came to be, station by station, with the lever on each part that shaped it.',
  tables: 'Every decision that built this message - table, category, item, the dice and why - and the round\'s rolls. Switch a row off or weigh it down for next time.',
  segments: 'The segment this message came from, node by node, with its node lit - and the round as the chain of nodes the roulette built.',
  structure: 'The road\'s structure as the desk holds it, with the leg this message came from lit.',
  prompts: 'The model call that wrote it, every prompt block as System 3 decided it, what was rolled, and the layers the next system prompt is built from.',
  audit: 'The ledger\'s events that made this message, in the order the ledger holds them.',
  sys3: 'The circuit this message travelled - System 3, its road, its node, its dice, the writer, the recording room, the ledger and the air.',
  director: 'The round it belongs to, the running order with its row marked, the exchange around it and the script ledger around it on air.',
  controls: 'The behaviour controls its rolls answered to - the value when it was planned, the value now, and the slider.'};
/* the prompt blocks, by what they are to the writer ([s3-blocks] rules name them) */
const FX_BLOCK_GROUPS = [
  ['system', 'The system prompt and the seat', ['system_prompt', 'persona', 'cohost', 'third', 'disposition', 'desk_instruction', 'lessons', 'review_guidance', 'accent', 'perf']],
  ['memory', 'Memory inserts', ['show_memory', 'avoid_reruns', 'brief_lesson', 'paper']],
  ['insets', 'Insets - what was put in front of the writer', ['aside', 'flavor', 'crystal', 'context', 'playing', 'tail_lists', 'day', 'heat', 'theme', 'modifiers', 'plot', 'schedule', 'angle', 'topic_contract', 'call_flow', 'battle', 'seat_away', 'turn_rules', 'pace']],
  ['sheet', 'System 3\'s running order', ['sheet']]];
const FX_KINDS = [['obligation', 'always sent'], ['roll', 'rolled at odds'], ['tint', 'only with the crystal tint'], ['off', 'never sent']];
/* the families that are chance rather than content: the "spontaneity systems" */
const FX_SPONT = new Set(['SHOCK', 'INTERJECT', 'MENTION', 'FAV', 'EVENT', 'TOPIC', 'TEMPER', 'DIRECTIVE', 'SFXGUY', 'SFX', 'SPEAKERBOX', 'TINT', 'REPAIR', 'ROOM', 'TRACK_TALK']);
/* a station roll's key names what it governs; these shaped the air around a line on any road */
const FX_NEAR = /^(line|station|voice|speakbox|sting|sfx|sfxguy|writer|gold|host)\./;
const FX_ROAD_KEYS = {ad_spot: /^ad\./, ad: /^ad\./, gallery: /^gallery\./, caller: /^call\./, banter: /^banter\./, manager: /^manager\./,
  upstairs: /^manager\./, memo: /^manager\./, news: /^story\./};

export async function openSystem3Focus({request, lineId = '', said = '', onBack = null, tab = 'focus'} = {}) {
  request ||= defaultRequest();
  const backdrop = el('div', 's3-backdrop s3-fx-backdrop');
  const root = el('section', {role: 'dialog', 'aria-modal': 'true', 'aria-label': 'System 3, focused on one message'});
  backdrop.append(root); document.body.append(backdrop);
  const before = document.activeElement;
  let view = null, closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', key);
    if (offBack) { try { offBack(); } catch (e) { /* gone */ } }
    try { if (view) view.dispose(); } catch (e) { /* gone */ }
    backdrop.remove();
    try { if (typeof onBack === 'function') onBack(); } catch (e) { /* the host's own */ }
    try { if (before && before.isConnected && before.focus) before.focus({preventScroll: true}); } catch (e) { /* gone */ }
  };
  /* Escape is "back": a decision card over the window takes its own Escape first */
  const key = e => { if (e.key === 'Escape' && !document.querySelector('.s3-modal-back')) { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', key);
  backdrop.addEventListener('click', e => { if (e.target === backdrop) close(); });
  /* [#1450c] the tablet's BACK closes the topmost overlay: this window is one (a decision card over it sits higher) */
  const offBack = window.PineDismiss && typeof window.PineDismiss.onBack === 'function'
    ? window.PineDismiss.onBack(() => (closed ? null : {node: backdrop, close})) : null;
  FOCUS_OF.set(root, {lineId: String(lineId || ''), said: String(said || ''), back: close});
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-focus', window.PineDuck.REPORT, backdrop);
  view = await mount(root, {request, onClose: close, tab: tab || 'focus'});
  if (!closed && window.pineCloseX) window.pineCloseX(root, close, {label: 'Close System 3'});   // [closex:s3-focus]
  if (closed) { try { view.dispose(); } catch (e) { /* gone */ } }
  else { const b = root.querySelector('.s3-fx-back'); if (b) b.focus({preventScroll: true}); }
  return {element: backdrop, close};
}

function s3FocusLens(root, ctx) {
  const spec = FOCUS_OF.get(root);
  if (!spec) return null;
  const request = ctx.request, send = ctx.send;
  const S = {full: false, resolved: false, got: null, conv: null, turn: null, sg: null, why: '', paintN: 0,
    memo: new Map(), drafts: new Map(), dirty: new Set(), levers: new Map(), blocksDraft: null, structDraft: new Map(), structDirty: new Set(),
    writerByTurn: new Map(), callCache: new Map(), events: [], mine: new Set(), where: new Map()};
  const v = makeViews({request, details: true});
  v.quiet = true;
  const soft = p => Promise.resolve(p).then(x => x, () => null);
  const once = (key, fn) => {
    if (!S.memo.has(key)) S.memo.set(key, Promise.resolve().then(fn).catch(e => { S.memo.delete(key); throw e; }));
    return S.memo.get(key);
  };
  const live = () => (((ctx.config() || {}).config) || {});
  const cid = () => ((S.conv && S.conv.identity) || {}).conversation_id || '';
  const road = () => String(((S.conv && S.conv.identity) || {}).road_kind || '');
  const directed = () => !!(S.conv && S.turn);
  const icon3 = () => {
    const html = typeof window.pineIcon === 'function' ? window.pineIcon('c:number--3') : '';
    return html ? el('span', {class: 's3-fx-mark', innerHTML: html}) : el('span', {class: 's3-fx-mark s3-fx-mark-t', text: '3'});
  };

  /* ---- what the station holds on the line -------------------------------- */
  function resolve() {
    return once('line', async () => {
      try { S.got = await request('/api/system3/line?line_id=' + encodeURIComponent(spec.lineId)); }
      catch (e) { S.got = null; S.why = (e && e.message) || String(e); }
      if (S.got && S.got.conversation) {
        try { S.conv = await request('/api/system3/conversation/' + encodeURIComponent(S.got.conversation.conversation_id)); }
        catch (e) { S.conv = null; S.why = 'its round could not be read: ' + ((e && e.message) || e); }
      }
      if (S.conv) {
        v.setConversation(S.conv);
        const want = S.got.turn ? S.got.turn.turn_id : '';
        S.turn = (S.conv.turns || []).find(x => x.turn_id === want) || null;
        S.sg = S.got.sfxguy || null;
        if (!S.turn && S.sg && S.sg.turn) S.turn = (S.conv.turns || []).find(x => x.turn_id === S.sg.turn.turn_id) || null;
        const c = S.conv;
        S.events = [...(c.decision_events || []).map(e => (e.kind ? e : {...e, kind: 'decision'})), ...(c.observations_air || [])]
          .sort((a, b) => (Number(a.cursor) || 0) - (Number(b.cursor) || 0) || (Number(a.at) || 0) - (Number(b.at) || 0));
        const own = S.turn ? turnEvents(c, S.turn) : [];
        S.mine = new Set(own.map(e => e.event_id));
        S.mineFams = new Set(own.map(e => e.family));
      }
      S.resolved = true;
      paintBar();
      return S;
    });
  }
  const whyOf = () => once('why', () => soft(request('/api/said/why/' + encodeURIComponent(spec.lineId))));
  async function blockNo() {
    const ln = (S.got && S.got.line) || {};
    if (ln.block != null && ln.block !== '') return {block: ln.block, ord: ln.ord};
    const why = await whyOf();
    for (const f of (why && why.flow) || []) {
      const m = f && f.step === 'ledger' ? /block (\d+), line (\d+)/.exec(String(f.label || '')) : null;
      if (m) return {block: Number(m[1]), ord: Number(m[2]) - 1};
    }
    return null;
  }
  const inspectOf = () => once('inspect', async () => {
    const at = await blockNo();
    return at ? soft(request('/api/segment/inspect?block=' + encodeURIComponent(at.block))) : null;
  });
  const listsOf = () => once('lists', () => soft(request('/api/system3/lists')).then(g => (g && g.lists) || []));
  const writerOf = () => once('writer', async () => {
    if (!directed()) return {row: null, detail: null, why: 'no System 3 turn made this line'};
    const w = await findWriterCall(request, S.conv, S.turn, S.callCache);
    S.writerByTurn.set(S.turn.turn_id, w);
    return w;
  });
  /* the PROMPT record the writer was sent for this message: the one whose
     beat covers its turn (a beat's mark counts turns from 1), the retry last;
     a round with one prompt, that one; else asked by the prompt's own words */
  const blocksOf = () => once('blocks', async () => {
    const prompts = ((S.conv && S.conv.observations_air) || []).filter(o => o && o.family === 'PROMPT' && o.digest);
    const n = S.turn ? S.turn.index + 1 : 0;
    const covers = prompts.filter(o => { const m = o.mark || {}; return m.from != null && m.until != null && n >= Number(m.from) && n <= Number(m.until); });
    let obs = covers.length ? covers[covers.length - 1] : prompts.length === 1 ? prompts[0] : null;
    let how = covers.length ? `the prompt of the beat that wrote turns ${covers[covers.length - 1].mark.from}-${covers[covers.length - 1].mark.until}` + (covers.length > 1 ? ` (the last of ${covers.length} tries)` : '')
      : prompts.length === 1 ? 'the round\'s one prompt' : '';
    let got = null;
    if (obs) got = await soft(request('/api/system3/prompt-blocks?digest=' + encodeURIComponent(obs.digest)));
    if (!obs || !(got && got.prompt)) {
      const w = await writerOf();
      const parts = w && w.row ? promptParts(w.detail || {}) : null;
      if (parts && parts.user) {
        const byText = await soft(request('/api/system3/prompt-blocks', {method: 'POST', body: JSON.stringify({text: String(parts.user)})}));
        if (byText && byText.prompt) { got = byText; how = 'found by the words of the prompt that wrote it'; obs = obs || byText.prompt; }
      }
    }
    const rec = (got && got.prompt) || null;
    if (got && got.rules) S.blockRules = got.rules;
    return {rows: (rec && rec.blocks) || (obs && obs.blocks) || [], rules: (got && got.rules) || {}, digest: (rec && rec.digest) || (obs && obs.digest) || '',
      at: Number((rec || obs || {}).at || 0), how, prompts: prompts.length};
  });

  /* ---- the events -------------------------------------------------------- */
  /* the round's ledger - decisions and what was observed at air - in the ledger's own order (its cursor) */
  const events = () => S.events;
  const idxOf = turnId => { const t = ((S.conv && S.conv.turns) || []).find(x => x.turn_id === turnId); return t ? t.index : -1; };
  function whereOf(e) {
    if (!S.where.has(e)) S.where.set(e, whereIs(e));
    return S.where.get(e);
  }
  function whereIs(e) {
    const t = S.turn;
    if (e.kind === 'observation') {
      if (e.family === 'COMMIT') return (e.lines || []).includes(spec.lineId) ? 'mine-air' : 'round-air';
      if (e.family === 'PROMPT') { const m = e.mark || {}; const n = t ? t.index + 1 : -1;
        return (m.from == null || (n >= Number(m.from) && n <= Number(m.until))) ? 'mine-prompt' : 'round-prompt'; }
      if (t && e.turn_index != null && Number(e.turn_index) === Number(t.script_index)) return 'mine-air';
      if (e.family === 'CARRY' || e.family === 'REPAIR') return 'round-air';
      return 'round-air';
    }
    if (t && S.mine.has(e.event_id)) return 'mine';
    /* the same turn drawn again: a turn-by-turn round re-plans the turns ahead of the one written,
       so an earlier draw of a family the turn now carries was replaced; a round roll that landed here (a topic, a favourite) is its own */
    if (t && e.turn_id === t.turn_id) return S.mineFams.has(e.family) ? 'replanned' : 'mine';
    if (!e.turn_id || Number(e.turn_index) < 0) {
      if (e.family !== 'STATION') return 'round';
      const k = String((e.meta || {}).key || (e.selected || {}).key || '');
      return FX_NEAR.test(k) || (FX_ROAD_KEYS[road()] && FX_ROAD_KEYS[road()].test(k)) ? 'station' : 'station-other';
    }
    const i = idxOf(e.turn_id);
    return t && i >= 0 && i < t.index ? 'before' : 'after';
  }
  const WHERE_WORDS = {'mine': 'this message', 'replanned': 'this turn, drawn before a re-plan replaced it', 'mine-air': 'this message, at air', 'mine-prompt': 'the prompt that wrote it',
    'round': 'the round - every turn', 'station': 'a station roll for the air around it', 'station-other': 'a station roll for another road',
    'before': 'an earlier turn - the state it was planned from', 'after': 'a later turn', 'round-air': 'the round, at air', 'round-prompt': 'another beat\'s prompt'};
  const SHAPED = new Set(['mine', 'mine-air', 'mine-prompt', 'round', 'station', 'before', 'replanned']);

  /* ---- the bar and the tabs ------------------------------------------------ */
  let bar = null;
  function paintBar() {
    if (!bar) {
      bar = el('div', {class: 's3-fx-bar', role: 'region', 'aria-label': 'The message System 3 is focused on'});
      const head = root.querySelector(':scope > .s3-head');
      if (head) head.after(bar); else root.prepend(bar);
    }
    const t = S.turn, conv = S.conv;
    const ln = (S.got && S.got.line) || {};
    const words = String(ln.text || (t && t.text) || spec.said || '').trim();
    const where = conv ? [t ? (t.name || t.speaker) : String(ln.who || ''), `${road() || 'a'} round ${cid().slice(0, 8)}`,
      t ? `turn ${t.index + 1} of ${(conv.turns || []).length}` : 'not one of its turns', t && t.step_label ? `node "${t.step_label}"` : '',
      S.sg ? castName('sfx') + '\'s line after it' : ''].filter(Boolean).join(' · ')
      : (S.resolved ? 'not directed by System 3' : 'reading the line...');
    const back = btn('‹ Back to Examine', () => spec.back(), {class: 's3-fx-back', title: 'close System 3 and go back to the Examine window, as you left it'});
    const all = S.full
      ? btn('Focus on the message again', () => { S.full = false; ctx.go(ctx.tab()); }, {class: 's3-fx-refocus'})
      : btn('Show all of System 3', () => { const at = ctx.tab() === 'focus' ? 'director' : ctx.tab();
          goFull(at, at === 'director' && S.conv ? () => ctx.director(cid(), S.turn ? S.turn.turn_id : '') : null); },
        {class: 's3-fx-all', title: 'every tab as it is, without the focus - the message stays held here, one tap away'});
    fill(bar, icon3(),
      el('div', 's3-fx-what',
        el('div', 's3-fx-line1', el('b', {text: S.full ? 'Showing all of System 3' : 'Focused on one message'}), el('span', {class: 's3-muted', text: where})),
        words ? el('q', {class: 's3-fx-said', text: words.length > 320 ? words.slice(0, 320) + '...' : words}) : null),
      el('div', 's3-fx-go', back, all));
    root.classList.toggle('s3-fx-focused', !S.full);
  }
  function decorate(tab) {
    const tabs = ctx.tabs;
    tabs.classList.toggle('s3-fx-tabs', !S.full);
    let mine = tabs.querySelector(':scope > .s3-fx-tab');
    if (!mine) {
      mine = btn('This message', () => { S.full = false; ctx.go('focus'); }, {class: 's3-fx-tab', title: 'how this message came to be'});
      tabs.prepend(mine);
    }
    if (tab === 'focus') S.full = false;              /* the full window has no such tab: it is the focus */
    mine.setAttribute('aria-pressed', String(tab === 'focus'));
  }
  function goFull(tab, then) {
    S.full = true;
    if (typeof then === 'function') { try { then(); } catch (e) { /* the editor's own */ } }
    ctx.go(tab);
    paintBar();
  }
  /* the window's own editor, opened on this message's part, then lit */
  function openEditor(tab, set, lit) {
    goFull(tab, set);
    if (typeof lit === 'function') setTimeout(() => { try { lit(ctx.body); } catch (e) { /* drawn differently */ } }, 120);
  }
  const litOnce = node => { if (!node) return; node.classList.add('s3-fx-lit'); setTimeout(() => node.classList.remove('s3-fx-lit'), 2600);
    try { node.scrollIntoView({block: 'nearest'}); } catch (e) { /* older engine */ } };   /* a tap asked for it: it is brought into view once */

  const PAINT = {focus: paintOverview, tables: paintTables, segments: h => paintNodes(h, 'segments'), structure: h => paintNodes(h, 'structure'),
    prompts: paintPrompts, audit: paintAudit, sys3: paintCircuit, director: paintDirector, controls: paintControls};
  function paint(tab) {
    decorate(tab);
    paintBar();
    if (S.full) return false;
    if (tab === 'visual') {                           /* the window's own Visual Prompt, on its round and turn */
      if (!S.resolved) {
        fill(ctx.body, para('Reading this message...', 's3-muted'));
        resolve().then(() => { if (ctx.tab() === 'visual' && !S.full) ctx.go('visual'); });
        return true;
      }
      if (S.conv) { ctx.visual(cid(), S.turn ? S.turn.turn_id : ''); return false; }
      fill(ctx.body, el('div', 's3-fx-pane', notDirected()));
      return true;
    }
    const painter = PAINT[tab];
    if (!painter) return false;
    const n = ++S.paintN;
    const host = el('div', 's3-fx-pane s3-fx-' + tab);
    fill(ctx.body, host);
    fill(host, para('Reading this message...', 's3-muted'));
    resolve().then(() => {
      if (n !== S.paintN || !host.isConnected) return null;
      fill(host);
      if (FX_TABS_HELP[tab]) host.append(el('p', {class: 's3-fx-help', text: FX_TABS_HELP[tab]}));
      if (!S.conv) { host.append(notDirected()); return null; }
      return painter(host);
    }).catch(e => { if (host.isConnected) fill(host, para('This view could not be drawn: ' + ((e && e.message) || e), 's3-error')); });
    return true;
  }

  function notDirected() {
    const ln = (S.got && S.got.line) || {};
    const words = S.conv
      ? `Part of a System 3 round (${road() || 'a'} round ${cid()}) but not one of its planned turns: `
        + (ln.who === 'drop' ? `${castName('sfx')}'s line; its draw was not recorded on this row.` : ln.who === 'board' ? 'a board clip - the dice for the clip are on the turn it punctuates.'
          : 'a line the station put into the round at air - a passage dealt in front, a caller\'s hello - which no node made.')
      : 'Not directed by System 3. This line came from a road System 3 does not run yet, or from a round written before it was switched on: nothing was rolled for it and nothing in its prompt came from the Rolodex.'
        + (S.why ? ` (the station said: ${S.why})` : '');
    return el('div', 's3-card s3-fx-none', el('h2', {text: S.conv ? 'Not one of the round\'s turns' : 'Not directed by System 3'}), para(words),
      el('div', 's3-row', btn('Show all of System 3', () => goFull('director', S.conv ? () => ctx.director(cid(), '') : null)), btn('‹ Back to Examine', () => spec.back()),
        S.conv ? btn('Open its round in the Director', () => goFull('director', () => ctx.director(cid(), ''))) : null));
  }

  /* ---- reading one decision ----------------------------------------------- */
  const pickOf = st => (st.candidates || []).find(c => String(c.id) === String(st.selected)) || null;
  function stageRow(st, ev) {
    const pick = pickOf(st);
    const cands = st.candidates || [];
    const total = st.total != null ? Number(st.total) : cands.reduce((a, c) => a + (Number(c.weight) || 0), 0);
    const d = st.draw || null;
    const label = st.stage === 'intensity' ? num(st.selected, 3) : String((pick && (pick.label || pick.id)) || st.selected || '');
    const facts = [];
    if (cands.length > 1) facts.push(`${st.selected_index || '?'} of ${st.of || cands.length}`);
    if (pick && cands.length) facts.push(`share ${pct(pick.p)} - weight ${num(pick.weight, 2)} of ${num(total, 2)}`);
    if (d && d.dice != null) facts.push(`d100 ${d.dice}${d.u != null ? ' · u ' + num(d.u, 6) : ''}`);
    else if (!cands.length || cands.length === 1) facts.push(cands.length === 1 ? 'the only one eligible - no draw' : 'no random number');
    if (st.threshold != null) facts.push(ev.family === 'SPEAKERBOX' ? `needs over ${st.threshold}` : `threshold ${num(st.threshold, st.threshold > 1 ? 0 : 2)}`);
    const why = [...((pick && pick.why) || []), ...(Array.isArray(st.why) ? st.why : [])].filter(Boolean);
    return el('div', 's3-fx-stage',
      el('span', {class: 's3-fx-stname', text: STAGE_NAME[st.stage] || st.stage}),
      die(d ? d.dice : null),
      el('div', 's3-fx-sgbody',
        el('div', null, el('b', {text: label}), el('span', {class: 's3-muted', text: '  ' + facts.join(' · ')})),
        st.rule ? el('div', {class: 's3-fx-rule', text: 'rule: ' + st.rule}) : null,
        why.length ? el('div', {class: 's3-fx-why', text: 'why: ' + why.join('; ')}) : null,
        (st.excluded || []).length ? el('div', {class: 's3-fx-why', text: 'not eligible: ' + st.excluded.map(x => `${x.label || x.id} (${x.why})`).join('; ')}) : null,
        cands.length > 1 ? el('details', 's3-fx-cands', el('summary', {text: `the ${cands.length} candidates and their weight shares`}),
          el('div', 's3-rx-cands', ...cands.map(c => el('div', {class: 's3-rx-cand' + (String(c.id) === String(st.selected) ? ' hit' : '')},
            el('b', {text: c.label || c.id}), el('span', {class: 's3-muted', text: `w ${num(c.weight)} - ${pct(c.p)}` + ((c.why || []).length ? ' - ' + c.why.join(', ') : '')}))))) : null));
  }
  function decisionHead(ev, extra) {
    const line = eventLine(ev, S.conv);
    const sb = sbOutcome(ev);
    const face = die(line.dice);
    if (sb && !sb.won) face.classList.add('miss');
    return el('div', 's3-fx-dhead',
      el('span', {class: 's3-dfam', text: ev.family}), face,
      el('div', 's3-fx-dwhat', el('b', {text: String(landedWords(ev, S.conv) || line.text || '').replace(/\s+/g, ' ')}),
        el('span', {class: 's3-muted', text: (FAMILY_WHAT[ev.family] || [ev.family])[0] + (extra ? ' · ' + extra : '')})),
      btn('How it was decided', e => { e.stopPropagation(); openDecision(S.conv, ev, S.turn && ev.turn_id === S.turn.turn_id ? S.turn : ((S.conv.turns || []).find(x => x.turn_id === ev.turn_id) || null), v.api); }, {class: 's3-fx-how'}));
  }
  /* opts: where (a word on the head), dim, compact (the path and the lever folded, for the overview), fold (the lever folded), open (the lever open) */
  function fxCard(ev, opts = {}) {
    const meta = ev.meta || {}, sel = ev.selected || {};
    const told = String(sel.text || '').trim();
    const stages = ev.stages || [];
    const path = el('div', 's3-fx-path', ...stages.map(st => stageRow(st, ev)),
      !stages.length ? para('Not a draw: ' + (meta.why || (sel.authority ? sel.authority : 'decided by a rule, not a random number')) + '.', 's3-muted') : null,
      meta.why && stages.length ? el('div', {class: 's3-fx-why', text: 'recorded: ' + meta.why}) : null,
      told && told !== sel.label ? el('div', 's3-rx-told', el('b', {text: 'What the writer was told: '}), told) : null);
    const card = el('div', {class: 's3-fx-dec' + (opts.dim ? ' dim' : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`, 'data-event': ev.event_id},
      decisionHead(ev, opts.where),
      opts.compact ? el('details', {class: 's3-fx-pathfold'}, el('summary', {text: `how the dice fell - ${stages.length || 'no'} stage${stages.length === 1 ? '' : 's'}`}), path) : path);
    const lever = leverFor(ev);
    if (lever) card.append(opts.compact || opts.fold ? el('details', {class: 's3-fx-levfold', open: !!opts.open}, el('summary', {text: 'Prevent it - change it for next time'}), lever) : lever);
    return card;
  }

  /* ---- the levers ----------------------------------------------------------
     A desk table is edited on a draft copy of the LIVE table (what the desk
     holds now), shared by every lever of that table on screen; reading never
     makes a draft, the first change does, and a Save sends the whole table
     through the Tables editor's own door. */
  const lnorm = s => String(s == null ? '' : s).toLowerCase().replace(/\s+/g, ' ').trim();
  function findTable(id) { return (live().tables || []).find(t => t.id === id) || null; }
  const peekTable = id => S.drafts.get(id) || findTable(id);
  function draftOf(id) {
    if (!S.drafts.has(id)) { const t = findTable(id); if (!t) return null; S.drafts.set(id, JSON.parse(JSON.stringify(t))); }
    return S.drafts.get(id);
  }
  function inTable(table, catId, itemId) {
    let cat = null, item = null;
    for (const c of (table && table.categories) || []) {
      const it = (c.items || []).find(i => String(i.id) === String(itemId));
      if (it) { if (!item || c.id === catId) { cat = c; item = it; } if (c.id === catId) break; }
    }
    if (!cat && catId) cat = ((table && table.categories) || []).find(c => c.id === catId) || null;
    return {cat, item};
  }
  /* one table's levers share its draft and its dirty flag, wherever they are drawn */
  function leverWatch(id, fn) { if (!S.levers.has(id)) S.levers.set(id, new Set()); S.levers.get(id).add(fn); }
  function leverTell(id, state, words) {
    for (const fn of [...(S.levers.get(id) || [])]) { if (fn(state, words) === false) S.levers.get(id).delete(fn); }
  }
  const dirty = id => { S.dirty.add(id); leverTell(id, 'dirty', 'changed - not saved yet'); };
  function saveRow(id, labelText) {
    const note = el('span', {class: 's3-muted s3-fx-note', text: S.dirty.has(id) ? 'changed - not saved yet' : ''});
    const save = btn('Save ' + id, async () => {
      const d = S.drafts.get(id);
      if (!d || !S.dirty.has(id)) return;
      leverTell(id, 'saving', 'saving...');
      try {
        const res = await send('/api/system3/tables/' + encodeURIComponent(id), 'PUT', d);
        S.drafts.delete(id); S.dirty.delete(id);
        await ctx.loadConfig('table', id);
        leverTell(id, 'saved', `saved ${id}${res && res.table ? ' v' + res.table.version : ''}${res && res.hash ? ' - live config ' + res.hash : ''}. The next round rolls with it; this message keeps the version it was planned under.`);
      } catch (e) { leverTell(id, 'dirty', 'not saved: ' + ((e && e.message) || e)); }
    }, {class: 's3-fx-save', disabled: !S.dirty.has(id)});
    const discard = btn('Discard', () => { S.drafts.delete(id); S.dirty.delete(id); leverTell(id, 'clean', 'discarded - the desk as it is'); },
      {class: 's3-fx-small', hidden: !S.dirty.has(id)});
    leverWatch(id, (state, words) => {
      if (!save.isConnected) return false;
      save.disabled = state !== 'dirty';
      discard.hidden = state !== 'dirty';
      note.textContent = words;
      note.classList.toggle('s3-fx-ok', state === 'saved');
      return true;
    });
    const open = btn('Open ' + id + ' in the Tables editor', () => openEditor('tables', () => ctx.table(id),
      body => { const inputs = [...body.querySelectorAll('.s3-item input[aria-label="label"]')];
        const hit = inputs.find(x => lnorm(x.value) === lnorm(labelText)); litOnce(hit && hit.closest('.s3-item-row')); }), {class: 's3-fx-open'});
    return el('div', 's3-row s3-fx-saverow', save, discard, open, note);
  }
  /* a control bound to one value of the table: it reads the draft (or the desk), a change writes the draft */
  function bound(id, input, read) {
    leverWatch(id, state => {
      if (!input.isConnected) return false;
      if (state === 'clean' || state === 'saved') read();
      return true;
    });
    return input;
  }
  function weightSlider(id, peek, write, max = 5) {
    const val = () => { const x = peek(); return x == null ? 1 : Number(x); };
    const out = el('b', {text: num(val())});
    const input = el('input', {type: 'range', min: 0, max, step: 0.05, value: val(), 'aria-label': 'weight',
      oninput: e => { write(+e.target.value); out.textContent = num(+e.target.value); dirty(id); }});
    bound(id, input, () => { input.value = val(); out.textContent = num(val()); });
    const half = btn('halve', () => { const w = Math.round(Number(input.value) * 50) / 100; write(w); input.value = w; out.textContent = num(w); dirty(id); },
      {class: 's3-fx-small', title: 'weigh it down: half as likely next time'});
    return [input, out, half];
  }
  function oddsRow(id, peek, write) {
    const val = () => Number(peek() || 0);
    const out = el('b', {text: pct(val())});
    const input = el('input', {type: 'range', min: 0, max: 1, step: 0.01, value: val(), 'aria-label': 'odds',
      oninput: e => { write(+e.target.value); out.textContent = pct(+e.target.value); dirty(id); }});
    bound(id, input, () => { input.value = val(); out.textContent = pct(val()); });
    return el('div', 's3-fx-w', el('span', {class: 's3-muted', text: 'its odds'}), input, out);
  }
  /* an item of a desk table: ES1, RS2, TEMPER1, FAV1, DIRECTIVE1, CALLEVENT1 - a POOLS1 option - a STATION1 roll */
  function itemLever(tableId, catId, itemId, fam, opts = {}) {
    const t0 = peekTable(tableId);
    if (!t0) return para(`Its table ${tableId} is no longer on the desk.`, 's3-muted');
    const at0 = inTable(t0, catId, itemId);
    if (!at0.item) return para(`"${itemId}" is no longer in ${tableId} on the desk - it was removed or renamed after this round was planned.`, 's3-muted');
    const peek = () => inTable(peekTable(tableId), catId, itemId);
    const cur = () => inTable(draftOf(tableId), catId, itemId);
    const label = at0.item.label || at0.item.id;
    const on = el('input', {type: 'checkbox', checked: at0.item.enabled !== false, 'aria-label': opts.chance ? 'the roll is on' : 'in the draw',
      onchange: e => { cur().item.enabled = e.target.checked; dirty(tableId); }});
    bound(tableId, on, () => { on.checked = (peek().item || {}).enabled !== false; });
    const rows = [el('label', 's3-row s3-fx-on', on, el('span', null, opts.chance ? 'the roll is on (off: it never hits): ' : 'in the draw: ', el('b', {text: label})))];
    if (!opts.chance) {
      rows.push(el('div', 's3-fx-w', el('span', {class: 's3-muted', text: 'its weight'}),
        ...weightSlider(tableId, () => (peek().item || {}).weight, w => { cur().item.weight = w; })));
      if (at0.cat && at0.cat.weight != null && fam !== 'POOL') rows.push(el('div', 's3-fx-w', el('span', {class: 's3-muted', text: `its category ${at0.cat.label || at0.cat.id}`}),
        ...weightSlider(tableId, () => (peek().cat || {}).weight, w => { cur().cat.weight = w; })));
    }
    if (fam !== 'ES' && !opts.chance && (at0.item.text != null || fam === 'POOL')) {
      const text = el('input', {type: 'text', value: at0.item.text || '', 'aria-label': 'what the writer is told', oninput: e => { cur().item.text = e.target.value; dirty(tableId); }});
      bound(tableId, text, () => { text.value = (peek().item || {}).text || ''; });
      rows.push(el('label', 's3-fx-text', el('span', {class: 's3-muted', text: fam === 'POOL' ? 'the option, word for word' : 'what the writer is told'}), text));
    }
    if (at0.item.dial) rows.push(para(`Its odds follow the desk dial "${at0.item.dial}" - set them where that dial is.`, 's3-muted'));
    else if (at0.item.odds != null) rows.push(oddsRow(tableId, () => (peek().item || {}).odds, x => { cur().item.odds = x; }));
    return el('div', 's3-fx-lever', el('div', {class: 's3-fx-levh', text: `Next time - ${tableId} on the desk`}), ...rows, saveRow(tableId, label));
  }
  /* where a table lives: CHANCE items are keyed by the roll, POOL categories by the list */
  function chanceHome(key) {
    for (const t of live().tables || []) {
      if (t.family !== 'CHANCE') continue;
      for (const c of t.categories || []) if ((c.items || []).some(i => i.id === key)) return {table: t.id, cat: c.id};
    }
    return null;
  }
  function poolHome(key) {
    for (const t of live().tables || []) if (t.family === 'POOL' && (t.categories || []).some(c => c.id === key)) return {table: t.id, cat: key};
    return null;
  }
  function chanceLever(key) {
    const home = chanceHome(key);
    if (!home) return para('Its row is not on the desk yet: STATION1 adds a roll the first time the station makes it.', 's3-muted');
    return itemLever(home.table, home.cat, key, 'CHANCE', {chance: true});
  }
  function poolLever(key, landed) {
    const home = poolHome(key);
    if (!home) return para('Its options are the station\'s own list, not a list on the desk: nothing here can switch one off.', 's3-muted');
    const cat0 = ((peekTable(home.table) || {}).categories || []).find(c => c.id === key) || {items: []};
    const opt = (cat0.items || []).find(i => lnorm(i.text) === lnorm(landed) || lnorm(i.label) === lnorm(landed));
    if (!opt) return para(`"${landed}" is no longer among ${key}'s options on the desk.`, 's3-muted');
    return itemLever(home.table, key, opt.id, 'POOL');
  }
  /* a list row: the lists doors write at once, as the lists editor does */
  function listLever(listId, rowId, words, opts = {}) {
    const box = el('div', 's3-fx-lever s3-fx-list', para('Reading the list...', 's3-muted'));
    (async () => {
      const lists = await listsOf();
      const meta = lists.find(l => l.id === listId) || {id: listId, label: listId, can: {}};
      const base = '/api/system3/lists/' + encodeURIComponent(listId);
      let row = null;
      const got = await soft(request(base + '?' + new URLSearchParams({q: String(words || rowId || '').slice(0, 80), limit: 20})));
      const rows = (got && got.rows) || [];
      row = rows.find(r => String(r.id) === String(rowId)) || rows.find(r => lnorm(r.text) === lnorm(words)) || (opts.loose ? rows[0] : null) || null;
      if (!box.isConnected) return;
      if (!row) { fill(box, para(`${meta.label || listId}: no row holds these words now - it was reworded or removed.`, 's3-muted')); return; }
      const can = meta.can || {};
      const note = el('span', {class: 's3-muted s3-fx-note'});
      const say = (t, ok) => { note.textContent = t; note.classList.toggle('s3-fx-ok', !!ok); };
      const path = base + '/rows/' + encodeURIComponent(row.id);
      const text = el('input', {type: 'text', value: row.text || '', disabled: !can.edit, 'aria-label': 'the words'});
      const put = async (body, done) => {
        say('writing...');
        try { const r = await send(path, 'PUT', body); if (r && r.id) row.id = r.id; say(done, true); }
        catch (e) { say('not changed: ' + ((e && e.message) || e)); }
      };
      fill(box, el('div', {class: 's3-fx-levh', text: `Next time - the ${meta.label || listId} (a list: changes are written at once)`}),
        el('div', 's3-fx-text', text, can.edit ? btn('Save the words', () => { const t = text.value.trim(); if (t && t !== row.text) put({text: t}, 'reworded in the store' + (meta.family === 'BANK' ? ' - it is recorded again before it can air' : '')); }, {class: 's3-fx-save'}) : null),
        el('div', 's3-row',
          can.switch ? el('label', 's3-row s3-fx-on', el('input', {type: 'checkbox', checked: row.on !== false, 'aria-label': 'on',
            onchange: e => put({on: e.target.checked}, e.target.checked ? 'switched on - back in the draw' : 'switched off - kept, never picked')}), 'in the draw') : null,
          can.remove ? btn('Remove it', async () => {
            if (!confirm('Remove "' + String(row.text || '').slice(0, 80) + '" from ' + (meta.label || listId) + '?')) return;
            say('removing...');
            try { await send(path, 'DELETE'); say('removed from the store', true); text.disabled = true; } catch (e) { say('not removed: ' + ((e && e.message) || e)); }
          }, {class: 's3-fx-small'}) : null,
          btn('Open the list', () => openEditor('tables', () => ctx.table('', listId)), {class: 's3-fx-open'}), note),
        row.why || row.note ? para([row.why, row.note].filter(Boolean).join(' · '), 's3-muted') : null);
    })().catch(e => { if (box.isConnected) fill(box, para('The list could not be read: ' + ((e && e.message) || e), 's3-muted')); });
    return box;
  }
  /* a prompt block's rule: the blocks section, saved whole (the Controls tab's door) */
  function blockLever(name) {
    const rules0 = (S.blocksDraft || live().blocks || {});
    const rule = rules0[name] || (S.blockRules || {})[name];
    if (!rule) return para(`"${name}" has no rule on the desk: a block no node claims is a wedge and is stripped.`, 's3-muted');
    const cur = () => {
      if (!S.blocksDraft) S.blocksDraft = JSON.parse(JSON.stringify(live().blocks || {}));
      if (!S.blocksDraft[name]) S.blocksDraft[name] = JSON.parse(JSON.stringify(rule));
      return S.blocksDraft[name];
    };
    const note = el('span', {class: 's3-muted s3-fx-note'});
    const pctOut = el('b', {text: pct(rule.odds == null ? 1 : rule.odds)});
    const odds = el('input', {type: 'range', min: 0, max: 1, step: 0.01, value: rule.odds == null ? 1 : Number(rule.odds), 'aria-label': 'odds',
      oninput: e => { cur().odds = +e.target.value; pctOut.textContent = pct(+e.target.value); mark(); }});
    const oddsBox = el('span', {class: 's3-row', hidden: rule.kind !== 'roll'}, odds, pctOut);
    const kind = el('select', {'aria-label': 'what System 3 does with this block', onchange: e => { cur().kind = e.target.value; oddsBox.hidden = e.target.value !== 'roll'; mark(); }},
      ...FX_KINDS.map(([k, w]) => el('option', {value: k, text: `${k} - ${w}`, selected: k === (rule.kind || 'obligation')})));
    const save = btn('Save the blocks', async () => {
      if (!S.blocksDraft) { save.disabled = true; note.textContent = 'saved with the other block changes'; return; }
      save.disabled = true; note.textContent = 'saving...';
      try { const res = await send('/api/system3/config/section/blocks', 'PUT', S.blocksDraft); S.blocksDraft = null; await ctx.loadConfig('blocks', '');
        note.textContent = 'saved' + (res && res.hash ? ' - live config ' + res.hash : '') + '. The next prompt is decided with it.'; note.classList.add('s3-fx-ok'); }
      catch (e) { note.textContent = 'not saved: ' + ((e && e.message) || e); save.disabled = false; }
    }, {class: 's3-fx-save', disabled: true});
    function mark() { save.disabled = false; note.textContent = 'changed - not saved yet'; note.classList.remove('s3-fx-ok'); }
    return el('div', 's3-fx-lever s3-fx-blev', el('span', {class: 's3-muted', text: 'next time:'}), kind, oddsBox, save, note);
  }
  /* the operator controls a roll answered to: named in its weights' reasons, or its family's */
  function controlsOf(ev) {
    const out = new Set();
    for (const st of ev.stages || []) {
      for (const c of st.candidates || []) for (const w of c.why || []) { const m = /\b([a-z_]+) control\b/.exec(String(w)); if (m) out.add(m[1]); }
      for (const w of Array.isArray(st.why) ? st.why : []) { if (/^aggression\b/.test(String(w))) out.add('sfx_aggression'); const m = /\b([a-z_]+) control\b/.exec(String(w)); if (m) out.add(m[1]); }
    }
    const planned = ((S.conv && S.conv.settings) || {}).controls || {};
    for (const k of DIAL_FOR[ev.family] || []) if (k in planned) out.add(k);
    return [...out];
  }
  function controlHint(keys) {
    const planned = ((S.conv && S.conv.settings) || {}).controls || {};
    const now = (((ctx.settings() || {}).settings) || {}).controls || {};
    return el('div', 's3-fx-lever s3-fx-ctl', el('span', {class: 's3-muted', text: 'set by '}),
      ...keys.map(k => el('span', {class: 's3-pill', text: `${k.replace(/_/g, ' ')} ${num(planned[k])}${now[k] != null && Math.abs(Number(now[k]) - Number(planned[k])) > 0.001 ? ' (now ' + num(now[k]) + ')' : ''}`})),
      btn('Change it in Controls', () => ctx.go('controls'), {class: 's3-fx-open'}));
  }
  function leverFor(ev) {
    const sel = ev.selected || {}, meta = ev.meta || {}, fam = ev.family;
    if (fam === 'BLOCK') return blockLever(sel.block);
    if (fam === 'STATION') {
      const key = String(meta.key || sel.key || '');
      if (stage(ev, 'dice')) return chanceLever(key);
      const item = stage(ev, 'item');
      return item ? poolLever(key, item.selected) : null;
    }
    if (fam === 'TOPIC' && sel.id && sel.id !== 'NONE') return el('div', null, listLever('topics.board', sel.id, sel.label), controlHint(controlsOf(ev)));
    if (sel.table && findTable(sel.table)) return itemLever(sel.table, sel.category, sel.id, fam);
    const tab = stage(ev, 'table');
    if (tab && tab.selected && findTable(tab.selected)) return itemLever(tab.selected, sel.category, sel.id, fam);
    const keys = controlsOf(ev);
    return keys.length ? controlHint(keys) : null;
  }

  /* ---- This message: how it came to be ------------------------------------- */
  function station(n, title, lit, body, tab, tabLabel) {
    return el('section', {class: 's3-fx-st' + (lit ? ' lit' : ' dim')},
      el('div', 's3-fx-sthead', el('span', {class: 's3-fx-stn', text: String(n)}), el('h3', {text: title}), el('span', {style: 'flex:1'}),
        tab ? btn(tabLabel || 'Open', () => ctx.go(tab), {class: 's3-fx-open'}) : null),
      el('div', 's3-fx-stbody', ...[].concat(body).filter(Boolean)));
  }
  async function paintOverview(host) {
    const conv = S.conv, t = S.turn, id = conv.identity || {};
    if (!t) { host.append(notDirected()); }
    const roundEvs = events().filter(e => e.kind !== 'observation' && whereOf(e) === 'round' && e.family !== 'BLOCK');
    const stationN = events().filter(e => e.family === 'STATION').length;
    const cfgNow = (ctx.config() || {}).hash || '';
    const chain = el('div', 's3-fx-chain');
    host.append(chain);
    /* 1. the road and the round */
    chain.append(station(1, 'The road and the round', true, [
      kv([['road', id.road_kind], ['round', id.conversation_id], ['mode', [conv.mode, conv.generation_mode].filter(Boolean).join(' · ')],
        ['planned', day(Number(conv.created || 0))], ['engine', conv.engine], ['config', conv.config_hash + (cfgNow && cfgNow !== conv.config_hash ? ' (the desk now holds ' + cfgNow + ')' : '')],
        ['subject', String((conv.subject || {}).topic || '').slice(0, 160)], ['verdict', conv.validation ? `${conv.validation.verdict} ${num(conv.validation.score)}` : '']])], 'director', 'The round in the Director'));
    /* 2. the round's rolls */
    chain.append(station(2, 'The round\'s rolls - one draw for every turn', roundEvs.length > 0,
      roundEvs.length ? el('div', 's3-fx-mini-list', ...roundEvs.map(e => miniRoll(e)),
        stationN ? para(`and ${stationN} station roll${stationN === 1 ? '' : 's'} recorded with the round (the air around it) - on the Tables tab`, 's3-muted') : null)
        : para('No round roll was recorded on this round.', 's3-muted'), 'tables', 'Every roll, with its lever'));
    if (t) {
      /* 3. the node */
      const info = turnNode(conv, t, ctx.config());
      chain.append(station(3, 'The node it came from', true, [
        nodeStrip(info, t),
        para(info.node ? `Node "${info.node.label || info.node.id}", ${info.index + 1} of ${info.nodes.length} in ${info.cycle ? 'the banter cycle' : (info.key || 'its segment')}${info.cycle && t.cycle != null ? ` (cycle ${Number(t.cycle) + 1})` : ''} - ${t.phase || ''}.`
          : `The turn names node "${t.step_label || t.step}", which the desk's structure no longer has.`, 's3-muted'),
        info.moved ? el('span', {class: 's3-pill bad', text: `planned under structure v${info.version}; the desk now holds v${info.now}`}) : null], 'segments', 'The segment\'s graph'));
      /* 4. the dice on its turn */
      const evs = turnEvents(conv, t).filter(e => !e.stage);
      chain.append(station(4, `The dice on its turn - ${evs.length} roll${evs.length === 1 ? '' : 's'}`, evs.length > 0,
        evs.length ? el('div', 's3-fx-decs', ...evs.map(e => fxCard(e, {compact: true}))) : para('No roll was recorded on this turn.', 's3-muted'), 'tables', 'The tables behind them'));
      if (S.sg) chain.append(station('4b', castName('sfx') + '\'s line', true, [sfxGuyStory(conv, S.sg, v), guyLever()], 'tables'));
      /* 5. the row */
      chain.append(station(5, 'What System 3 told the writer', true, dropTold(conv, t), 'director', 'The running order'));
      /* 6. the prompt (the model call is looked up) */
      const promptBox = el('div', null, para('Looking for the model call that wrote it...', 's3-muted'));
      chain.append(station(6, 'The prompt that wrote it', true, promptBox, 'prompts', 'Every block, with its lever'));
      Promise.all([writerOf(), blocksOf()]).then(([w, b]) => {
        if (!promptBox.isConnected) return;
        const kept = b.rows.filter(x => x.keep).length, rolled = b.rows.filter(x => x.odds != null || x.u != null).length;
        fill(promptBox, w && w.row ? el('div', 's3-fx-line', el('b', {text: `${w.row.model || '?'} - ${w.row.purpose || ''}`}),
          el('span', {class: 's3-muted', text: ` ${day(Number(w.row.at || 0))}${w.row.finished && w.row.at ? ' - took ' + num(Number(w.row.finished) - Number(w.row.at), 1) + ' s' : ''}`}),
          el('span', {class: 's3-pill ' + (w.exact ? 'active' : 'shadow'), text: w.exact ? 'proven by its words' : 'nearest by time'})) : para('No model call found: ' + ((w && w.why) || 'the prompt history has no call for it'), 's3-muted'),
          b.rows.length ? para(`${b.rows.length} prompt blocks: ${kept} sent, ${b.rows.length - kept} stripped, ${rolled} rolled${b.how ? ' - ' + b.how : ''}.`, 's3-muted')
            : para('System 3 holds no block record for this prompt.', 's3-muted'));
      }).catch(e => { if (promptBox.isConnected) fill(promptBox, para('The prompt could not be read: ' + ((e && e.message) || e), 's3-muted')); });
      /* 7. the words */
      const val = conv.validation || {};
      const checks = (((val.turns || []).find(r => r.turn_id === t.turn_id) || {}).checks) || [];
      chain.append(station(7, 'The words that came back', !!(t.text || (S.got.line || {}).text), [
        el('blockquote', {class: 's3-dquote', text: String((S.got.line || {}).text || t.text || '(no words recorded)')}),
        checks.length ? kv(checks.map(c => [c.what, `${c.result}${c.how ? ' - ' + c.how : ''}`])) : null], 'director'));
      chain.append(station('7a', 'Length and handoffs', true, handoffReceipt(conv, t, ev => openDecision(conv, ev, t, v.api)), 'controls', 'Handoff policy'));
    }
    /* 8. the air */
    const airBox = el('div', null, para('Reading the script ledger...', 's3-muted'));
    chain.append(station(8, 'On the air', true, airBox, 'director', 'The ledger around it'));
    Promise.all([whyOf(), inspectOf(), blockNo()]).then(([why, ins, at]) => {
      if (!airBox.isConnected) return;
      const ln = ((ins && ins.lines) || []).find(l => l.line_id === spec.lineId) || {};
      fill(airBox, kv([['state', (why && why.aired) || ln.aired || ''], ['heard', ln.heard_at ? day(Number(ln.heard_at)) : ln.at || ''],
        ['ledger', at ? `block ${at.block}, line ${Number(at.ord) + 1}` : 'not on the script ledger'], ['voice', (why && why.voice) || ln.voice || ''],
        ['seconds', ln.seconds != null ? num(ln.seconds, 1) : ''], ['the hour', ins && ins.hour]]),
        why && why.say ? para(why.say, 's3-muted') : null);
    });
  }
  function miniRoll(e) {
    const line = eventLine(e, S.conv);
    return el('div', {class: 's3-fx-mini', style: `--fam:${FAM[e.family] || 'var(--obs)'}`, role: 'button', tabindex: '0', title: 'how it was decided',
        onclick: () => openDecision(S.conv, e, null, v.api), onkeydown: k => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); openDecision(S.conv, e, null, v.api); } }},
      die(line.dice), el('b', {text: e.family}), el('span', {text: String(landedWords(e, S.conv) || line.text || '').replace(/\s+/g, ' ').slice(0, 120)}));
  }
  /* his line, when it came off a list: the shelf of quips, or the speech bank */
  function guyLever() {
    const obs = (S.sg || {}).line || {};
    const kind = String(obs.kind || '');
    const words = String(obs.line || (S.got.line || {}).text || '').replace(/^[^\p{L}\p{N}]+/u, '').replace(/^\d+\s+/, '').trim();
    if (!words) return null;
    if (kind === 'quip') return listLever('sfxguy.quips', '', words);
    if (kind === 'bank') return listLever('sfxguy.bank', '', words);
    return para(kind === 'news' ? 'A story off the wire, written at air - not a row on a list. Whether he speaks is his node\'s die and the desk\'s interjections dial.'
      : 'Written at air, fired back at the line - not a row on a list. Whether he speaks is his node\'s die and the desk\'s interjections dial.', 's3-muted');
  }
  function nodeStrip(info, t) {
    const nodes = info.nodes || [];
    if (!nodes.length) return null;
    return el('div', 's3-fx-strip', ...nodes.flatMap((n, i) => [i ? el('span', {class: 's3-fx-arrow', text: '→'}) : null,
      el('span', {class: 's3-fx-node' + (i === info.index ? ' on' : ''), title: i === info.index ? 'this message came from this node' : 'a node of the same segment', text: n.label || n.id})]).filter(Boolean));
  }

  /* ---- Tables: every decision -------------------------------------------- */
  async function paintTables(host) {
    const conv = S.conv, t = S.turn;
    const all = events().filter(e => e.kind !== 'observation');
    const mine = t ? turnEvents(conv, t).filter(e => !e.stage) : [];
    const mineSet = new Set(mine.map(e => e.event_id));
    const onTurn = t ? all.filter(e => whereOf(e) === 'mine' && !mineSet.has(e.event_id)) : [];
    const replaced = t ? all.filter(e => whereOf(e) === 'replanned') : [];
    const round = all.filter(e => whereOf(e) === 'round' && e.family !== 'BLOCK');
    const near = all.filter(e => whereOf(e) === 'station');
    const far = all.filter(e => whereOf(e) === 'station-other');
    host.append(
      t ? sectionOf(`The decisions that built its turn (${mine.length})`, el('div', 's3-fx-decs', ...mine.map(e => fxCard(e, {open: true}))),
        mine.length ? null : para('No roll was recorded on this turn.', 's3-muted')) : null,
      onTurn.length ? sectionOf(`Rolls that landed on its turn (${onTurn.length})`, para('Drawn for the round, and the draw chose this turn.', 's3-muted'),
        el('div', 's3-fx-decs', ...onTurn.map(e => fxCard(e, {open: true})))) : null,
      replaced.length ? el('details', 's3-fx-more', el('summary', {text: `${replaced.length} earlier draws of this turn - replaced when the round was re-planned turn by turn (they did not build it)`}),
        el('div', 's3-fx-decs', ...replaced.map(e => fxCard(e, {fold: true, dim: true})))) : null,
      sectionOf(`The round's rolls (${round.length}) - one draw for every turn`, round.length ? el('div', 's3-fx-decs', ...round.map(e => fxCard(e, {fold: true})))
        : para('No round roll was recorded.', 's3-muted')),
      near.length || far.length ? sectionOf(`The station's rolls recorded with the round (${near.length + far.length})`,
        para('Rolled by the station for the air before this round was planned. Their key names what each one governs; these are the ones that govern the air around a line like this one.', 's3-muted'),
        el('div', 's3-fx-decs', ...near.map(e => fxCard(e, {fold: true}))),
        far.length ? el('details', 's3-fx-more', el('summary', {text: `${far.length} more, for other roads (recorded with the round, not shaping this line)`}),
          el('div', 's3-fx-decs', ...far.map(e => fxCard(e, {fold: true, dim: true})))) : null) : null);
  }

  /* ---- Segments / Structure: the node graph -------------------------------- */
  function structKey(info) { return info.cycle ? 'banter' : info.key; }
  function structDraft(info) {
    const key = structKey(info);
    if (!S.structDraft.has(key)) S.structDraft.set(key, JSON.parse(JSON.stringify(info.cycle ? (live().structure || {}) : ((live().structures || {})[key] || {}))));
    return S.structDraft.get(key);
  }
  async function paintNodes(host, mode) {
    const conv = S.conv, t = S.turn;
    if (!t) { host.append(para('This line is not one of the round\'s turns, so no node made it.', 's3-muted')); return; }
    const info = turnNode(conv, t, ctx.config());
    const rs = conv.road_structure || {};
    const stName = info.cycle ? 'the banter cycle' : (rs.id || info.key || '') + (info.key && info.key.includes('~') ? ' (variant ' + info.key + ')' : '');
    const head = el('div', 's3-card s3-fx-nodehead',
      el('h2', {text: `${road()} round - ${stName}`}),
      para(info.node ? `This message came from node "${info.node.label || info.node.id}" (${info.index + 1} of ${info.nodes.length}).`
        : `The turn names node "${t.step_label || t.step}", which the desk's copy of the structure no longer has.`, 's3-muted'),
      info.moved ? el('span', {class: 's3-pill bad', text: `planned under structure version ${info.version}; the desk now holds version ${info.now}`}) : null,
      mode === 'structure' && info.structure && (info.structure.head || info.structure.tail) ? el('details', null, el('summary', {text: 'the structure\'s own words to the writer (head and tail)'}),
        el('pre', {text: [info.structure.head, info.structure.tail].filter(Boolean).join('\n\n')})) : null);
    const list = el('div', 's3-seg-nodes s3-fx-nodes');
    if (info.nodes.length) {
      info.nodes.forEach((n, i) => {
        if (i === info.index) list.append(nodeCard(conv, t, info, v.api, {sel: true, where: `node ${i + 1} of ${info.nodes.length} - this message`}));
        else {
          const made = (conv.turns || []).filter(x => String(x.leg || x.step || '') === String(n.id || ''));
          list.append(el('div', {class: 's3-seg-node s3-node-other', title: made.length ? 'the messages this node made in this round' : 'no message came from this node in this round'},
            el('div', 's3-row', el('b', {text: n.label || n.id}),
              info.cycle ? el('span', {class: 's3-pill', text: String(n.speaker || '').replace('_', ' ')}) : el('span', {class: 's3-pill', text: n.place || 'middle'}),
              el('span', {style: 'flex:1'}),
              el('span', {class: 's3-muted', text: made.length ? `message${made.length > 1 ? 's' : ''} ${made.map(x => x.index + 1).join(', ')}` : 'not used this round'}),
              ...(n.draws || []).map(d => el('span', {class: 's3-draw' + (d.fixed !== undefined ? ' locked' : ''), style: `--fam:${FAM[d.family] || 'var(--obs)'}`},
                el('span', {class: 's3-dice', text: d.fixed !== undefined ? 'pin' : 'd100'}), d.family))),
            mode === 'structure' && n.act ? el('div', {class: 's3-muted s3-node-act', text: n.act}) : null));
        }
        if (i < info.nodes.length - 1) list.append(el('div', {class: 's3-seg-gap', text: '↓'}));
      });
    } else list.append(nodeCard(conv, t, info, v.api, {sel: true, where: 'as recorded on the turn'}));
    /* the round, as the chain of nodes the roulette built: one per message */
    const turns = conv.turns || [];
    const chainBox = el('div', 's3-fx-exnodes', ...turns.map(x => {
      const es = (x.decisions || []).find(d => d.family === 'ES');
      return el('span', {class: 's3-fx-exnode' + (x.turn_id === t.turn_id ? ' on' : ''), title: `turn ${x.index + 1} - ${x.name || x.speaker} - ${x.step_label || x.step || ''}`},
        el('b', {text: String(x.index + 1)}), el('span', {text: `${x.speaker} · ${x.step_label || x.step || ''}`}), es ? el('i', {text: es.label || ''}) : null);
    }));
    host.append(head, sectionOf(mode === 'structure' ? 'The structure, leg by leg' : 'The segment\'s node graph', list),
      sectionOf(`The round as the roulette built it - ${turns.length} message${turns.length === 1 ? '' : 's'}, one node each`, chainBox),
      info.node ? nodeEditor(info, t, mode) : null);
    if (!reduced()) host.querySelectorAll('.s3-node-card .s3-draw-live .s3-dice').forEach((d, k) => {
      d.classList.add('rolling'); setTimeout(() => { d.classList.remove('rolling'); d.classList.add('pop'); setTimeout(() => d.classList.remove('pop'), 400); }, 450 + k * 130); });
  }
  function nodeEditor(info, t, mode) {
    const key = structKey(info);
    const draft = structDraft(info);
    const nodes = info.cycle ? (draft.steps || []) : (draft.legs || []);
    const n = nodes[info.index];
    if (!n) return null;
    const note = el('span', {class: 's3-muted s3-fx-note', text: S.structDirty.has(key) ? 'changed - not saved yet' : ''});
    const save = btn('Save the segment', async () => {
      save.disabled = true; note.textContent = 'saving...';
      try {
        const res = info.cycle ? await send('/api/system3/structure', 'PUT', {steps: draft.steps, initiator: draft.initiator || ''})
          : await send('/api/system3/structures/' + encodeURIComponent(key), 'PUT', {...draft, legs: draft.legs});
        S.structDraft.delete(key); S.structDirty.delete(key);
        await ctx.loadConfig('structure', key);
        discard.hidden = true;
        note.textContent = 'saved' + (res && res.structure && res.structure.version ? ' v' + res.structure.version : '') + (res && res.hash ? ' - live config ' + res.hash : '') + '. The next round runs it; this message keeps the one it was planned under.';
        note.classList.add('s3-fx-ok');
      } catch (e) { note.textContent = 'not saved: ' + ((e && e.message) || e); save.disabled = false; }
    }, {class: 's3-fx-save', disabled: !S.structDirty.has(key)});
    /* a discard puts the desk's copy back: the one repaint here, and the reader's own press */
    const discard = btn('Discard', () => { S.structDraft.delete(key); S.structDirty.delete(key); ctx.go(ctx.tab()); }, {class: 's3-fx-small', hidden: !S.structDirty.has(key)});
    const mark = () => { S.structDirty.add(key); save.disabled = false; discard.hidden = false; note.textContent = 'changed - not saved yet'; note.classList.remove('s3-fx-ok'); };
    const evs = turnEvents(S.conv, t).filter(e => !e.stage);
    const drawRows = (n.draws || []).map((d, k) => {
      const ev = evs.find(e => e.family === d.family) || null;
      const items = (live().tables || []).filter(x => x.family === d.family && (!d.tables || d.tables.includes(x.id)))
        .flatMap(x => (x.categories || []).flatMap(c => (c.items || []).map(it => ({id: it.id, label: `${x.id} · ${c.label || c.id} · ${it.label || it.id}`}))));
      const gone = el('span', {class: 's3-muted', text: 'off the node - Save to keep it off, Discard to put it back', hidden: true});
      const pick = el('select', {'aria-label': d.family + ' draw', onchange: e => {
        const val = e.target.value;
        if (val === '__roll') delete d.fixed;
        else if (val === '__off') { n.draws = (n.draws || []).filter(x => x !== d); e.target.disabled = true; gone.hidden = false; }
        else d.fixed = val;
        mark();
      }},
      el('option', {value: '__roll', text: 'roulette on - rolled every time', selected: d.fixed === undefined}),
      el('option', {value: '__off', text: 'take this draw off the node'}),
      ...items.map(it => el('option', {value: it.id, text: 'pinned to ' + it.label, selected: d.fixed === it.id})));
      return el('div', 's3-fx-w s3-fx-drawrow', el('span', {class: 's3-draw', style: `--fam:${FAM[d.family] || 'var(--obs)'}`}, el('span', {class: 's3-dice', text: ev ? String(eventLine(ev, S.conv).dice ?? '-') : 'd100'}), d.family),
        el('span', {class: 's3-muted', text: ev ? 'landed ' + String(landedWords(ev, S.conv) || '').replace(/\s+/g, ' ').slice(0, 60) : 'no roll recorded here'}), pick, gone);
    });
    return el('div', 's3-card s3-fx-lever s3-fx-nodeedit',
      el('div', {class: 's3-fx-levh', text: `Next time - node "${n.label || n.id}" of ${info.cycle ? 'the banter cycle' : key}`}),
      info.cycle ? null : el('label', 's3-fx-text', el('span', {class: 's3-muted', text: 'what this leg does - the act the writer is given'}),
        el('textarea', {value: n.act || '', rows: 2, 'aria-label': 'the act', oninput: e => { n.act = e.target.value; mark(); }})),
      drawRows.length ? para('Its draws: take one off the node, or pin it to a value (the roulette is then off for it) - "pinned to" another value is how this one never lands here again.', 's3-muted') : null,
      ...drawRows,
      el('div', 's3-row', save, discard,
        btn(mode === 'structure' ? 'Open the Structure editor' : 'Open in the Segments editor', () => mode === 'structure'
          ? openEditor('structure', () => ctx.structure(key))
          : openEditor('segments', () => ctx.segment(key, info.index), body => litOnce(body.querySelector('.s3-seg-node.sel'))), {class: 's3-fx-open'}), note));
  }

  /* ---- Prompts ---------------------------------------------------------- */
  async function paintPrompts(host) {
    const conv = S.conv, t = S.turn;
    if (!t) { host.append(para('No System 3 turn made this line, so System 3 holds no prompt for it.', 's3-muted')); return; }
    const callBox = el('div', null, para('Looking for the model call that wrote this message...', 's3-muted'));
    const blockBox = el('div', null, para('Reading the prompt blocks...', 's3-muted'));
    const all = events().filter(e => e.kind !== 'observation');
    const spont = all.filter(e => FX_SPONT.has(e.family) && ['mine', 'round'].includes(whereOf(e)));
    const lineRolls = all.filter(e => e.family === 'STATION' && whereOf(e) === 'station' && /^(line|station|speakbox|voice|sting)\./.test(String((e.meta || {}).key || '')));
    const gold = all.filter(e => e.family === 'STATION' && /^gold\./.test(String((e.meta || {}).key || '')));
    const carry = (conv.observations_air || []).filter(o => o.family === 'CARRY');
    host.append(sectionOf('The model call that wrote it', callBox),
      t ? sectionOf('Length and handoffs', handoffReceipt(conv, t, ev => openDecision(conv, ev, t, v.api))) : null,
      sectionOf('The prompt blocks, as System 3 decided them', blockBox),
      sectionOf(`The spontaneity systems - what was rolled for it (${spont.length + lineRolls.length})`,
        spont.length || lineRolls.length ? el('div', 's3-fx-decs', ...[...spont, ...lineRolls].map(e => fxCard(e, {fold: true, where: WHERE_WORDS[whereOf(e)]})))
          : para('Nothing chance-driven was rolled for it.', 's3-muted')),
      sectionOf('Gold', gold.length ? el('div', 's3-fx-decs', ...gold.map(e => fxCard(e, {fold: true})))
        : para('No gold roll was recorded with this round: no banked bar was in play for it.', 's3-muted')),
      sectionOf('Memory - what was carried in', carry.length ? el('div', 's3-fx-mini-list', ...carry.map(o => el('div', 's3-fx-line',
        el('b', {text: 'CARRY '}), el('span', {text: `${o.stage || ''}: ${o.why || ((o.landing || {}).text ? 'landed on "' + o.landing.text + '"' : '')}`}))))
        : para('Nothing was carried from the round before.', 's3-muted'),
        conv.carry ? el('details', null, el('summary', {text: 'the carry this round started from'}), el('pre', {text: json(conv.carry)})) : null),
      layersBox(t));
    const [w, b] = await Promise.all([writerOf(), blocksOf()]);
    if (!host.isConnected) return;
    const parts = w && w.row ? promptParts(w.detail || {}) : null;
    if (w && w.row) {
      const r = w.row;
      /* its row as the writer got it - only from a call proven by its words: the nearest call by time may be another round's */
      const inPrompt = w.exact ? sheetRowOf(promptText(w.detail || {}), t).trim() : '';
      fill(callBox, el('div', 's3-row', el('b', {text: `${r.model || '?'} - ${r.purpose || ''}`}), el('span', {class: 's3-state s3-state-' + (r.state || 'done'), text: r.state || ''}),
          el('span', {class: 's3-muted', text: day(Number(r.at || 0)) + (r.finished && r.at ? ` - took ${num(Number(r.finished) - Number(r.at), 1)} s` : '')}),
          el('span', {class: 's3-pill ' + (w.exact ? 'active' : 'shadow'), text: w.exact ? 'proven by its words' : 'nearest by time'})),
        para(w.why || '', 's3-muted'),
        inPrompt ? el('div', 's3-story-row', el('b', {text: 'Its row, as the writer was given it: '}), inPrompt) : null,
        el('details', {class: 's3-fx-fold'}, el('summary', {text: 'The system prompt, as it was sent'}), readablePromptText(parts.sys || (parts.user ? NO_SYSTEM : ''))),
        el('details', {class: 's3-fx-fold'}, el('summary', {text: 'The prompt to the writer, as it was sent'}), readablePromptText(parts.user)),
        el('details', {class: 's3-fx-fold'}, el('summary', {text: 'What came back'}), el('pre', {text: parts.text || '(empty)'})));
    } else fill(callBox, para('No prompt for this message: ' + ((w && w.why) || 'no model call was found.'), 's3-muted'));
    const rows = b.rows || [];
    if (!rows.length) { fill(blockBox, para('System 3 holds no block record for this prompt - written before prompt blocks were nodes, on a road System 3 does not decide, or aged out.', 's3-muted')); return; }
    const evs = new Map(all.filter(e => e.family === 'BLOCK').map(e => [e.event_id, e]));
    const rules = b.rules || {};
    const groups = FX_BLOCK_GROUPS.map(([k, title, names]) => [k, title, rows.filter(x => names.includes(x.name) && x.odds == null && x.u == null && x.kind !== 'roll')]);
    const rolled = rows.filter(x => x.odds != null || x.u != null || x.kind === 'roll');
    const placed = new Set([...groups.flatMap(g => g[2]), ...rolled]);
    const rest = rows.filter(x => !placed.has(x));
    const blockRow = x => {
      const ev = x.event_id ? evs.get(x.event_id) : null;
      const dice = ev && ev.rng && ev.rng.dice != null ? ev.rng.dice : x.u != null ? Math.floor(Number(x.u) * 100) + 1 : null;
      return el('div', {class: 's3-fx-block ' + (x.keep ? 'kept' : 'stripped')},
        el('div', 's3-row', el('span', {class: 's3-drop-state', text: x.keep ? 'sent' : 'stripped'}), (x.odds != null || x.u != null) ? die(dice) : null,
          el('b', {text: x.label || (rules[x.name] || {}).label || x.name}), el('code', {text: x.name}),
          el('span', {class: 's3-muted', text: [x.kind === 'wedge' ? 'a wedge - no node claims it' : x.kind, x.odds != null ? `rolled at ${pct(x.odds)}` : '', x.why].filter(Boolean).join(' - ')}),
          ev ? btn('How', () => openDecision(S.conv, ev, null, v.api), {class: 's3-fx-small'}) : null),
        (rules[x.name] || {}).helper ? para('built by ' + rules[x.name].helper, 's3-muted') : null,
        !x.keep && x.text ? el('details', null, el('summary', {text: 'the text it would have sent'}), el('pre', {text: String(x.text)})) : null,
        blockLever(x.name));
    };
    fill(blockBox, para(`${rows.length} blocks: ${rows.filter(x => x.keep).length} sent, ${rows.filter(x => !x.keep).length} stripped, ${rolled.length} rolled`
        + (b.at ? ` - decided ${clock(b.at)}` : '') + (b.how ? ` - ${b.how}` : '') + '. Each block\'s kind is its rule for the next prompt.', 's3-muted'),
      ...groups.filter(g => g[2].length).map(([k, title, list]) => el('details', {class: 's3-fx-bgroup', open: k !== 'system' || list.length <= 6},
        el('summary', {text: `${title} (${list.length})`}), ...list.map(blockRow))),
      rolled.length ? el('details', {class: 's3-fx-bgroup', open: true}, el('summary', {text: `Rolled - the prompt's own spontaneity (${rolled.length})`}), ...rolled.map(blockRow)) : null,
      rest.length ? el('details', {class: 's3-fx-bgroup', open: true}, el('summary', {text: `The rest (${rest.length})`}), ...rest.map(blockRow)) : null);
  }
  /* the layers the next system prompt is built from: the inspector's own door */
  function layersBox(t) {
    const box = el('div', null, para('Reading the prompt layers...', 's3-muted'));
    (async () => {
      const cfg = await soft(request('/api/prompt-history/config'));
      if (!box.isConnected) return;
      const nodes = (cfg && cfg.nodes) || [];
      const nodeAt = path => nodes.find(n => JSON.stringify(n.path) === JSON.stringify(path)) || null;
      const editor = (current, title, help, scope, key) => {
        let was = String(current || '');
        const area = el('textarea', {value: was, rows: 5, 'aria-label': title});
        const note = el('span', {class: 's3-muted s3-fx-note', text: help || ''});
        const save = btn('Save for future calls', async () => {
          save.disabled = true;
          try { const got = await send('/api/paperwork/field', 'POST', {scope, key, value: area.value, was, line_id: spec.lineId, apply: 'future'});
            was = area.value; note.textContent = (got && got.say) || 'saved for future calls'; note.classList.add('s3-fx-ok'); }
          catch (e) { note.textContent = 'Not saved: ' + ((e && e.message) || e); }
          save.disabled = false;
        }, {class: 's3-fx-save'});
        return el('div', 's3-pfold-layer', el('h4', {text: title}), area, el('div', 's3-row', save, note));
      };
      const seat = String(t.speaker || 'A');
      const personaPath = SEAT_PERSONA[seat] || null;
      const personaNode = personaPath ? nodeAt(personaPath) : null;
      const stationNode = nodeAt(['dj', 'radio_prompt_overrides', 'station_system']);
      fill(box,
        editor(stationNode ? stationNode.value : '', 'The station\'s standing instructions (the station system prompt)', 'Folded into every writer\'s head when the station follows its prompt.', 'station', ''),
        personaPath ? editor(personaNode ? personaNode.value : '', `The persona of ${SEAT_WORDS[seat] || 'seat ' + seat} - ${t.name || seat}`, 'The character this seat is written as.', 'persona', SEAT_KEY[seat])
          : para(`Seat ${seat} has no persona setting on the desk.`, 's3-muted'),
        para('Kept for future calls and receipted in the station\'s actions. This message keeps the prompt it had.', 's3-muted'));
    })().catch(e => { if (box.isConnected) fill(box, para('The prompt layers could not be read: ' + ((e && e.message) || e), 's3-error')); });
    return sectionOf('Edit the layers the next system prompt is built from', box);
  }

  /* ---- Audit: the ledger's events, in order -------------------------------- */
  async function paintAudit(host) {
    const all = events();
    const rows = el('div', 's3-fx-arows');
    let whole = false;
    const toggle = el('label', 's3-row', el('input', {type: 'checkbox', onchange: e => { whole = e.target.checked; draw(); }}), 'the whole round, not only what shaped this message');
    const count = el('span', 's3-muted');
    function row(e) {
      const where = whereOf(e);
      const line = eventLine(e, S.conv);
      const r = el('details', {class: 's3-fx-arow s3-fx-' + where, style: `--fam:${FAM[e.family] || 'var(--obs)'}`},
        el('summary', null, el('span', {class: 's3-muted', text: e.cursor != null ? '#' + e.cursor : ''}), el('span', {class: 's3-muted', text: clock(Number(e.at || 0))}),
          el('span', {class: 'fam', text: e.family + (e.kind === 'observation' ? ' obs' : '')}), die(line.dice),
          el('span', {class: 's3-fx-awhat', text: e.kind === 'observation' ? line.text : String(landedWords(e, S.conv) || line.text || '').replace(/\s+/g, ' ').slice(0, 140)}),
          el('span', {class: 's3-fx-where', text: WHERE_WORDS[where] || where})));
      let built = false;
      r.addEventListener('toggle', () => {
        if (!r.open || built) return;
        built = true;
        r.append(e.kind === 'observation' ? el('div', 's3-fx-abody', fxObsCard(e)) : el('div', 's3-fx-abody', fxCard(e, {fold: true})));
      });
      return r;
    }
    function draw() {
      const shown = whole ? all : all.filter(e => SHAPED.has(whereOf(e)));
      /* the turns before it (the state it was planned from) and the station's rolls
         for the air around it fold into one row each - opened, their events in order */
      const out = [];
      let group = null;
      for (const e of shown) {
        const w = whereOf(e);
        const gk = whole ? '' : w === 'before' ? 'b:' + e.turn_id : w === 'station' ? 'station' : '';
        if (gk) {
          if (!group || group.key !== gk) {
            const tt = w === 'before' ? ((S.conv.turns || []).find(x => x.turn_id === e.turn_id) || {}) : null;
            group = {key: gk, box: el('div', 's3-fx-decs'), n: 0, head: el('summary', {text: ''}),
              label: tt ? `turn ${Number(tt.index) + 1} - ${tt.name || tt.speaker || ''} (${tt.step_label || ''})` : 'the station rolls recorded with the round',
              tail: tt ? ' before it - the state this message was planned from' : ' - the air around it; their odds and options are STATION1 / POOLS1'};
            out.push(el('details', {class: 's3-fx-arow s3-fx-agroup s3-fx-' + w}, group.head, group.box));
          }
          group.n += 1;
          group.head.textContent = `${group.label}: ${group.n} roll${group.n === 1 ? '' : 's'}${group.tail}`;
          group.box.append(row(e));
          continue;
        }
        group = null;
        out.push(row(e));
      }
      fill(rows, ...out, out.length ? null : para('Nothing on the ledger shaped this message.', 's3-muted'));
      count.textContent = `${shown.length} of ${all.length} events on this round's ledger`;
    }
    host.append(el('div', 's3-row', toggle, count, btn('Open the whole round in Audit', () => openEditor('audit', () => ctx.audit(cid())), {class: 's3-fx-open'})), rows);
    draw();
  }
  function fxObsCard(o) {
    const plain = Object.entries(o).filter(([k, val]) => !['kind', 'family', 'conversation_id', 'blocks', 'body'].includes(k) && (typeof val !== 'object' || val === null));
    return el('div', 's3-fx-dec', el('div', 's3-fx-dhead', el('span', {class: 's3-dfam', text: o.family}), el('div', 's3-fx-dwhat', el('b', {text: eventLine(o, S.conv).text}))),
      kv(plain.map(([k, val]) => [k.replace(/_/g, ' '), val])),
      o.family === 'PROMPT' ? para(`${(o.blocks || []).length} blocks - on the Prompts tab`, 's3-muted') : null,
      el('details', null, el('summary', {text: 'the raw record'}), el('pre', {text: json(o)})));
  }

  /* ---- Sys3: the circuit it travelled ------------------------------------- */
  async function paintCircuit(host) {
    const conv = S.conv, t = S.turn;
    const [w, why, at] = await Promise.all([writerOf().catch(() => null), whyOf(), blockNo()]);
    if (!host.isConnected) return;
    const evs = t ? turnEvents(conv, t).filter(e => !e.stage) : [];
    const aired = String((why && why.aired) || '');
    const stops = [
      ['System 3', 'the conversation director', true],
      ['the ' + (road() || '?') + ' road', `${conv.mode || ''} · ${conv.generation_mode || ''}`, true],
      ['node', t ? (t.step_label || t.step || '') : 'no turn', !!t],
      ['the dice', evs.map(e => `${e.family} ${eventLine(e, conv).dice ?? '-'}`).join(' · ') || 'none', evs.length > 0],
      ['running order', t ? `row ${t.index + 1}, seat ${t.speaker}` : '', !!t && !!sheetRowOf(String((conv.plan || {}).sheet || ''), t)],
      ['the writer', w && w.row ? `${w.row.model || '?'}` : 'not found', !!(w && w.row)],
      ['recording room', why && why.voice ? String(why.voice) : '', !!(why && (why.voice || why.engine))],
      ['script ledger', at ? `block ${at.block}.${Number(at.ord) + 1}` : '', !!at],
      ['on air', aired || '', ['stream', 'box', 'both', 'airing', 'page', 'published'].includes(aired)]];
    const track = el('div', 's3-fx-circuit');
    const dots = stops.map(([name, sub, lit], i) => {
      const node = el('div', {class: 's3-fx-cstop' + (lit ? ' lit' : '')}, el('span', {class: 's3-fx-cdot', text: String(i + 1)}), el('b', {text: name}), el('span', {class: 's3-muted', text: sub}));
      track.append(node);
      if (i < stops.length - 1) track.append(el('span', {class: 's3-fx-cwire' + (lit && stops[i + 1][2] ? ' lit' : '')}));
      return node;
    });
    const log = el('div', 's3-fx-flight', ...events().filter(e => ['mine', 'mine-air', 'mine-prompt'].includes(whereOf(e))).map(e => {
      const line = eventLine(e, conv);
      return el('div', {class: 's3-fx-fl', style: `--fam:${FAM[e.family] || 'var(--obs)'}`}, el('span', {class: 's3-muted', text: clock(Number(e.at || 0))}), die(line.dice),
        el('b', {text: e.family}), el('span', {text: String(e.kind === 'observation' ? line.text : landedWords(e, conv) || line.text || '').replace(/\s+/g, ' ').slice(0, 110)}));
    }));
    const replay = btn('Replay how it came to be', async () => {
      replay.disabled = true;
      const ms = reduced() ? 0 : 420;
      dots.forEach(d => d.classList.remove('pass'));
      for (let i = 0; i < dots.length; i += 1) {
        if (!dots[i].isConnected) break;
        dots[i].classList.add('pass');
        if (i === 3) for (const f of log.querySelectorAll('.s3-die')) if (f.roll) f.roll(ms);
        if (ms) await sleep(ms);
      }
      replay.disabled = false;
    }, {class: 's3-fx-replay'});
    host.append(el('div', 's3-card', el('div', 's3-row', el('h2', {text: 'The circuit this message travelled'}), el('span', {style: 'flex:1'}), replay), track,
      para('Lit: the record shows the message passed through it. The live circuit of every road is on Sys3 in all of System 3.', 's3-muted')),
      sectionOf('Its flight log - the ledger\'s events for this message, in order', log.childNodes.length ? log : para('No event names this message.', 's3-muted')),
      el('div', 's3-row', btn('The live circuit (all of System 3)', () => goFull('sys3'), {class: 's3-fx-open'})));
  }

  /* ---- Director: the round and the running order --------------------------- */
  async function paintDirector(host) {
    const conv = S.conv, t = S.turn, id = conv.identity || {};
    const turns = conv.turns || [];
    const cfgNow = (ctx.config() || {}).hash || '';
    let whole = false;
    const exBox = el('div', 's3-chat s3-fx-exchange');
    const drawEx = () => {
      const i = t ? t.index : 0;
      const show = whole || !t ? turns : turns.filter(x => Math.abs(x.index - i) <= 2);
      fill(exBox, ...show.map(x => { const b = v.bubble(x, {conv}); if (t && x.turn_id === t.turn_id) b.classList.add('sel', 's3-fx-me'); return b; }));
    };
    const moreBtn = btn('Show the whole round', () => { whole = !whole; moreBtn.textContent = whole ? 'Only the messages around it' : 'Show the whole round'; drawEx(); }, {class: 's3-fx-small'});
    const airBox = el('div', null, para('Reading the script ledger...', 's3-muted'));
    host.append(
      el('div', 's3-card', el('div', 's3-row', el('h2', {text: String((conv.subject || {}).topic || 'Conversation ' + id.conversation_id).slice(0, 140)}),
          el('span', {class: 's3-pill ' + conv.mode, text: conv.mode})),
        kv([['road', id.road_kind], ['round', id.conversation_id], ['revision', id.revision], ['generation', conv.generation_mode], ['planned', day(Number(conv.created || 0))],
          ['engine', conv.engine], ['config', conv.config_hash + (cfgNow && cfgNow !== conv.config_hash ? ' - the desk now holds ' + cfgNow : '')], ['seed', conv.seed],
          ['schedule slot', id.system2_slot_id], ['verdict', conv.validation ? `${conv.validation.verdict} ${num(conv.validation.score)}` : ''], ['turns', turns.length]]),
        el('div', 's3-row', btn('Open this round in the Director', () => goFull('director', () => ctx.director(cid(), t ? t.turn_id : '')), {class: 's3-fx-open'}),
          btn('Open it in Visual Prompt', () => goFull('visual', () => ctx.visual(cid(), t ? t.turn_id : '')), {class: 's3-fx-open'}))),
      t ? sectionOf('The running order System 3 wrote - its row marked', dropTold(conv, t)) : null,
      sectionOf(t ? `The exchange around it - message ${t.index + 1} of ${turns.length}` : 'The exchange', el('div', 's3-row', moreBtn), exBox),
      sectionOf('On the air - the script ledger around it', airBox));
    drawEx();
    const [why, ins, at] = await Promise.all([whyOf(), inspectOf(), blockNo()]);
    if (!airBox.isConnected) return;
    const lines = (ins && ins.lines) || [];
    const flow = (why && why.flow) || [];
    fill(airBox,
      ins ? kv([['block', ins.block], ['the hour', ins.hour], ['the round', ins.round ? `${ins.round.road || ''} ${ins.round.sid || ''} - committed ${ins.round.committed || ''}` : ''],
        ['heard', ins.timing ? `${ins.timing.heard || 0} of ${ins.timing.of || lines.length} - ${ins.timing.from || ''} to ${ins.timing.to || ''}` : ''],
        ['the prompt', ins.prompt_say || ins.prompt_kind || ''], ['seed document', ins.seed_doc]]) : para(at ? 'The script ledger could not be read.' : 'This line is not on the script ledger.', 's3-muted'),
      lines.length ? el('ol', 's3-fx-ledger', ...lines.map(l => el('li', {class: l.line_id === spec.lineId ? 'on' : (l.heard ? 'heard' : '')},
        el('span', {class: 's3-muted', text: `${Number(l.ord) + 1}. ${l.at || ''}`}), el('b', {text: l.name || l.who || ''}), el('span', {text: String(l.text || '').slice(0, 180)}),
        el('span', {class: 's3-muted', text: [l.kind, l.seconds != null ? num(l.seconds, 1) + ' s' : '', l.heard ? 'heard' : (l.aired || '')].filter(Boolean).join(' · ')})))) : null,
      (ins && (ins.holes || []).length) ? para('Holes in the air: ' + ins.holes.map(h => `${h.from}-${h.to} (${num(h.seconds, 0)} s)`).join(', '), 's3-muted') : null,
      flow.length ? el('div', 's3-timeline', ...flow.map(f => el('div', 's3-tl-row', el('span', {class: 's3-tl-when', text: f.at || '-'}), el('b', {text: f.label || f.step}),
        el('span', {class: 's3-tl-took', text: ''}), el('span', {class: 's3-muted', text: f.detail || ''})))) : null,
      (ins && (ins.modifiers || []).length) ? el('details', null, el('summary', {text: `what was in force on the desk (${ins.modifiers.length})`}),
        el('ul', 's3-dlist', ...ins.modifiers.map(m => el('li', {text: `${m.kind}: ${m.says || m.label || m.name}`})))) : null);
  }

  /* ---- Controls: what its rolls answered to -------------------------------- */
  async function paintControls(host) {
    const conv = S.conv;
    const all = events().filter(e => e.kind !== 'observation' && ['mine', 'round'].includes(whereOf(e)));
    const moved = new Map();
    for (const e of all) for (const k of controlsOf(e)) { if (!moved.has(k)) moved.set(k, []); moved.get(k).push(e); }
    host.append(handoffPolicyEditor(live().handoff, async next => { await send('/api/system3/config/section/handoff', 'PUT', next); await ctx.loadConfig('handoff', ''); }));
    const planned = (conv.settings || {}).controls || {};
    const settings = ctx.settings() || {};
    const liveControls = {...(((settings.settings) || {}).controls || {})};
    const help = ctx.controlHelp || {};
    const note = el('span', 's3-muted s3-fx-note');
    const cards = [...moved.entries()].map(([k, evs]) => {
      const was = planned[k], now = liveControls[k];
      const out = el('b', {text: num(now)});
      const input = el('input', {type: 'range', min: 0, max: 1, step: 0.05, value: now == null ? 0.5 : now, 'aria-label': k, oninput: e => { out.textContent = num(+e.target.value); }});
      const save = btn('Save', async () => {
        save.disabled = true; note.textContent = 'saving ' + k + '...';
        try { const got = await send('/api/system3/settings', 'POST', {controls: {...liveControls, [k]: +input.value}});
          Object.assign(liveControls, (((got || {}).settings) || {}).controls || {[k]: +input.value});
          if (settings.settings) settings.settings.controls = {...liveControls};
          note.textContent = `${k} saved - the next round rolls with it`; note.classList.add('s3-fx-ok'); }
        catch (e) { note.textContent = 'not saved: ' + ((e && e.message) || e); }
        save.disabled = false;
      }, {class: 's3-fx-save'});
      return el('div', 's3-card s3-fx-ctlcard',
        el('div', 's3-row', el('b', {text: k.replace(/_/g, ' ')}), el('span', {class: 's3-muted', text: `${num(was)} when it was planned${now != null && Math.abs(Number(now) - Number(was)) > 0.001 ? ' - ' + num(now) + ' now' : ''}`})),
        help[k] ? para(help[k], 's3-muted') : null,
        el('div', 's3-row', input, out, save),
        el('div', 's3-fx-mini-list', ...evs.map(e => miniRoll(e))));
    });
    host.append(cards.length ? el('div', 's3-fx-ctlgrid', ...cards) : para('None of its rolls answered to a behaviour control: their weights were the tables\' own.', 's3-muted'),
      el('div', 's3-row', note, btn('Open the Controls tab', () => goFull('controls'), {class: 's3-fx-open'})));
  }

  resolve();
  return {paint, full: () => S.full};
}
