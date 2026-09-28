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
const FAM = {CTS: 'var(--cts)', ES: 'var(--es)', RS: 'var(--rs)', IRS: 'var(--irs)', FL: 'var(--fl)', TRACK_TALK: 'var(--topic)',
  SPEAKERBOX: 'var(--sb)', SFX: 'var(--sfx)', TOPIC: 'var(--topic)', SFXGUY: 'var(--sfxguy)', LINE: 'var(--line)',
  COMMIT: 'var(--obs)', REPAIR: 'var(--repair)', TINT: 'var(--tint)', ROOM: 'var(--room)',   /* [s3-rewrite] */
  FAV: 'var(--fav)', DIRECTIVE: 'var(--directive)', EVENT: 'var(--repair)', STATION: 'var(--obs)',   /* [s3-cast] [s3-events] [s3-dice-door] */
  TEMPER: 'var(--es)', SHOCK: 'var(--rs)', INTERJECT: 'var(--fl)', MENTION: 'var(--cts)', CARRY: 'var(--es)'};   /* [s3-rounds] [s3-carry] */
const SIDE = {A: 'left', B: 'right', D: 'left', C: 'right', E: 'right'};
const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const json = value => JSON.stringify(value, null, 2);
const clock = t => t ? new Date(t * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '';
const day = t => t ? new Date(t * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
const pct = x => (x == null ? '-' : Math.round(x * 100) + '%');
const num = (x, d = 2) => (x == null || Number.isNaN(+x) ? '-' : (+x).toFixed(d));

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
  if (ev.kind === 'observation' || ev.stage) return observationLine(ev);
  if (fam === 'CTS' && !ev.rng) return {fam, dice: null, text: (sel.id || '').toLowerCase() + ' → ' + (sel.label || '')};
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
    return {fam, dice: null, text: `at air (${o.due}) ${cand}${clip ? clip.clip : 'nothing played'}${(o.sfx_guy || []).length ? ' + SFX Guy' : ''}`};
  }
  if (fam === 'SPEAKERBOX') return {fam, dice: null,
    text: `door ${o.door}: ${o.applies === false ? 'did not apply' : `roll ${num(o.roll, 3)} vs ${num((o.rate || 0) + (o.lift || 0), 2)} → ${o.hit ? 'HIT ' + (o.file || '') : 'miss'}`} (${o.rolled_by})`};
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
  const line = eventLine(ev, conv);
  const face = die(line.dice);
  const sb = sbOutcome(ev);
  if (sb && !sb.won) face.classList.add('miss');
  const item = stage(ev, 'item') || stage(ev, 'mode');
  const pick = String(landedWords(ev, conv) || '').replace(/\s+/g, ' ').slice(0, 48);
  const reel = item && (item.candidates || []).length > 1 ? drum(item.candidates, item.selected)
    : el('span', {class: 's3-rl-pick', text: pick});
  const chip = el('span', {class: 's3-rl-chip' + (sb && !sb.won ? ' miss' : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`,
      'data-event': ev.event_id, role: 'button', tabindex: '0', title: `${ev.family} - tap for how it was decided`, onclick,
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
    face, el('b', {text: ev.family}), reel);
  chip.roll = ms => Promise.all([face.roll(ms * 0.85), reel.roll ? reel.roll(ms) : null]);
  return chip;
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
  SFXGUY: ["The SFX Guy's mouth",
    "Whether the SFX Guy pipes up after this line, at the desk's own interjections dial, and what kind of line: a story off the wire, a reaction fired back at this very line, or a saying off his shelf. The line itself is drawn at air from the first kind that has something to say, and that draw - every candidate and the die - is recorded under his line."],
  LINE: ['Line draw',
    'A single-voice road handed System 3 its list - the stock lines, the ad book - and one entry was drawn here, every candidate and its weight recorded. This is the Rolodex where the station used to call random.choice().'],
  SPEAKERBOX: ['Speaker-box',
    "Whether a passage from your speakerbox documents is read with this line - before it (prepend), after it (append), worked in, or as an opening monologue. A d100 against your slider decides whether; the station's own rotation (locks, themes, cooldowns) decides which document."],
  SFX: ['SFX Guy',
    "Whether the SFX guy wants a clip at this line, before or after it, and what it should be about. The station's matcher and rotation choose the real file from the indexed book; the two-line cadence is never reduced."],
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
const DIAL_FOR = {ES: ['emotional_volatility'], RS: ['disagreement', 'escalation', 'tangent', 'callback', 'novelty'],
  IRS: ['disagreement', 'escalation'], FL: ['tangent', 'callback', 'novelty', 'closure_aggressiveness', 'escalation'],
  SPEAKERBOX: ['speakerbox_density'], SFX: ['sfx_aggression'], CTS: ['novelty'], TOPIC: ['topics'],
  TINT: ['tint'], REPAIR: ['repair'], ROOM: ['room'], FAV: ['favorites'],
  SHOCK: ['shock_beat'], INTERJECT: ['interjections'], MENTION: ['mention'], TRACK_TALK: ['track_talk']};   /* [s3-rounds] */

function kv(pairs) {
  return el('div', 's3-kv', ...pairs.filter(p => p && p[1] !== undefined && p[1] !== null && p[1] !== '')
    .map(([k, val]) => el('div', null, el('span', {text: k}), el('b', {text: String(val)}))));
}
function sectionOf(title, ...kids) { return el('section', 's3-dsec', el('h3', {text: title}), ...kids); }
function para(text, cls) { return el('p', {class: cls || '', text}); }

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
    : ({table: 'Which table', category: 'Which category', item: 'Which outcome', mode: 'Which way', dice: 'Whether', turn: 'Which turn'}[st.stage] || st.stage);
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
      el('td', {text: c.label || c.id}),
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
    const rolled = rollRow(ev, conv);
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
    node('SFX Guy', `${sfxAired} played`, `${sfxPlanned} scheduled`));
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
function typewriter(node, text, ms) {
  const total = Math.max(500, Math.min(2600, ms || String(text).length * 20));
  const t0 = performance.now();
  node.textContent = '';
  node.classList.add('typing');
  return new Promise(resolve => {
    const step = now => {
      const k = Math.min(1, (now - t0) / total);
      node.textContent = String(text).slice(0, Math.ceil(String(text).length * k));
      if (k < 1 && node.isConnected) requestAnimationFrame(step);
      else { node.textContent = text; node.classList.remove('typing'); resolve(); }
    };
    requestAnimationFrame(step);
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
      role: 'button', tabindex: '0', title: 'how The SFX Guy came to schedule this clip',
      onclick: e => { e.stopPropagation(); v.select(t.turn_id, ev.event_id, e.currentTarget); openDecision(conv, ev, t, v.api); },
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }},
    sfxAvatar(),
    el('span', 's3-sysrow-text', el('b', {text: 'The SFX Guy'}),
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
  const node = el('article', {class: 's3-msg left s3-sfxguy', 'data-turn': t.turn_id,
      title: 'tap for what to do with this clip'},
    el('div', 'who', sfxAvatar(), el('b', {text: 'The SFX Guy'}), el('span', {text: `${due} · after turn ${t.index + 1}`})),
    el('div', 's3-bubble s3-sfx-bubble',
      quips.length ? el('div', {class: 's3-words', text: quips.join(' ')}) : null,
      played ? sfxClipCard(played, v) : el('div', {class: 's3-muted', text: 'no clip played - his line only'}),
      why ? el('div', {class: 's3-sfx-why', text: why}) : null));
  node.s3 = {conv, t, obs, played};
  node.addEventListener('click', e => {
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
  const node = el('article', {class: 's3-msg left s3-sfxguy s3-sfxguy-line', 'data-turn': t.turn_id,
      title: 'the SFX Guy\'s line: how System 3 drew it'},
    el('div', 'who', sfxAvatar(), el('b', {text: 'The SFX Guy'}), el('span', {text: `${kind} · after turn ${t.index + 1}`})),
    el('div', 's3-bubble',
      el('span', {class: 's3-words', text: obs.line || ''}),
      el('span', {class: 'dir', text: fell + how + planned}),
      last && last.candidates && last.candidates.length > 1
        ? el('div', {class: 's3-muted s3-reel-text', text: 'rolled through: ' + last.candidates.join(' · ')}) : null));
  node.s3 = {conv, t, obs};
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
    const img = el('img', {alt: 'the clip The SFX Guy played'});
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
/* The three views, shared by the full instrument (mount) and the Script
   tab's embedded Messenger / Technical views (mountEmbedded). One renderer,
   so the two hosts can never disagree about what a roll looked like. */
function makeViews({request, onSelect} = {}) {
  const v = {conv: null, convs: new Map(), air: new Map(), sel: {turn: '', event: ''}, speed: 1, playing: false, open: new Set(),
    token: 0, alive: true, onBuildState: null,
    paneA: el('section', {class: 's3-pane', 'aria-label': 'Conversation view'}),
    paneB: el('section', {class: 's3-pane', 'aria-label': 'Technical RNG Rolodex'}),
    paneC: el('section', {class: 's3-pane', 'aria-label': 'Final script and provenance'})};
  const inspectCache = new Map();
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
  v.airStage = (key, conv, t) => {
    if (!conv || conv.mode === 'shadow' || conv.mode === 'simulation') return 'written';
    const lines = key.startsWith('sfx:') ? (conv.lines || []).filter(l => 'sfx:' + l.line_id === key) : turnLines(conv, t);
    const got = airOfLines(lines, v.air);
    if (got === 'aired') return 'written';
    if (got === 'off') return 'skipped';
    if (got === 'waiting') return 'upcoming';
    return Date.now() / 1000 - convAt(conv) > STALE_S ? 'written' : 'upcoming';
  };
  v.stageOf = (key, conv, t) => (v.sequenced ? v.airStage(key, conv, t) : 'written');
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

  /* A. conversation view */
  v.bubble = (t, opts = {}) => {
    const conv = opts.conv || v.convOf(t);
    /* [s3-messenger] not on air yet: its roulette, never its words */
    const stg = opts.slot ? '' : v.stageOf(t.turn_id, conv, t);
    if (stg === 'upcoming') return v.card(t, conv);
    const st = v.turnStatus(t, conv);
    const perf = t.performance || {};
    const whole = v.wordsOf(t, conv);
    /* on air: only as many of its words as the audio has reached */
    const text = stg === 'live' ? whole.slice(0, Math.max(0, v.revealed(t.turn_id, whole.length))) : whole;
    const planned = !whole;
    const directions = (t.directions || []).map(d => d.text).join('; ');
    const plan = `${perf.emotion ? perf.emotion + ' · ' : ''}${directions || t.step_label}`;
    const body = el('div', {class: 's3-bubble' + (planned ? ' planned' : '')},
      planned ? `${perf.emotion ? 'in ' + perf.emotion + ': ' : ''}${directions || t.step_label}` : el('span', {class: 's3-words', text}),
      !planned ? el('span', {class: 'dir', text: (conv.mode === 'shadow' ? 'System 3 would have directed: ' : '') + plan}) : null);
    const reacts = el('div', 's3-reacts', ...turnEvents(conv, t).map(ev => {
      const chip = chipOf(ev, conv);
      return el('span', {class: 's3-diamond' + (chip.miss ? ' miss' : ''), style: `--fam:${FAM[ev.family]}`, 'data-event': ev.event_id, 'data-turn': t.turn_id,
        title: chip.title, text: chip.text,
        role: 'button', tabindex: '0',
        onclick: e => { e.stopPropagation(); v.select(t.turn_id, ev.event_id, e.currentTarget); openDecision(conv, ev, t, v.api); },
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }});
    }));
    if (!opts.slot && turnEvents(conv, t).length) {
      reacts.append(el('button', {type: 'button', class: 's3-replay-btn', innerHTML: PLAY_SVG,
        title: 'replay how this line was decided - the Rolodex, the roulette and the dice',
        'aria-label': 'replay how this line was decided', onclick: e => { e.stopPropagation(); v.replayTurn(node, conv, t); }}));
    }
    const sb = (t.speakerbox || []).filter(s => s.mode !== 'NONE');
    const chips = el('div', 's3-chips',
      el('span', {text: t.phase}), perf.emotion ? el('span', {text: `${perf.emotion} ${num(perf.intensity)}`}) : null,
      sb.length ? el('span', {text: 'speakerbox ' + sb.map(s => s.mode.toLowerCase()).join(', ')}) : null,
      t.sfx && t.sfx.play ? el('span', {text: 'SFX ' + t.sfx.placement}) : null,
      t.sfxguy && t.sfxguy.speak ? el('span', {text: 'SFX Guy: ' + (t.sfxguy.kind || 'speaks')}) : null,
      el('span', {text: '~' + num(t.estimated_seconds, 0) + 's'}), el('span', {class: st.cls, text: st.word}));
    /* A line a speaker-box passage went into opens, in place, into its
       parts: the passages above and below it and the setup row. A line
       whose roll lost opens to its odds and the dials behind them. */
    const composed = !opts.slot && canCompose(conv, t);
    const passages = composed && (sbWon(t) || !!dealtBy(conv, scriptIndexOf(conv, t)) || opensOnSeed(conv, t));
    const open = composed && v.open.has(t.turn_id);
    if (composed) {
      chips.append(el('button', {type: 'button', class: 's3-sbopen', 'aria-expanded': String(open),
        text: open ? (passages ? 'close the passages' : 'close the odds') : (passages ? 'open the passages' : 'see the speaker-box odds'),
        onclick: e => { e.stopPropagation(); v.toggle(t, node); }}));
    }
    const cutWhy = st.air && (st.air.cut_why || (st.air.aired === 'withdrawn' ? st.air.withdrawn_why : ''));
    /* [s3-messenger] struck out only on the air's own word; aired, it is past */
    const skipTitle = stg === 'skipped' ? 'not heard: ' + (offWhy(conv, turnLines(conv, t)) || 'withdrawn or cut before air') : null;
    const node = el('article', {class: `s3-msg ${SIDE[t.speaker] || 'left'} seat-${t.speaker}${opts.slot ? ' building' : ''}` +
      `${composed ? (passages ? ' has-sb' : ' sb-miss') : ''}${open ? ' open' : ''}` +
      `${stg === 'live' ? ' live' : stg === 'past' ? ' past' : stg === 'skipped' ? ' skipped' : ''}`,
      'data-turn': t.turn_id, 'data-key': opts.slot ? null : t.turn_id, 'data-stage': stg || null,
      title: skipTitle || (composed ? (open ? 'tap to close' : passages ? 'tap to open this line with its speaker-box passages'
        : 'tap to see why no speaker-box passage won this line, and turn the odds') : null),
      onclick: e => {
        v.select(t.turn_id, '', e.currentTarget);
        if (!composed || e.target.closest(KEEP_OPEN)) return;
        const pick = window.getSelection ? window.getSelection() : null;
        if (pick && !pick.isCollapsed && node.contains(pick.anchorNode)) return;   /* selecting words, not tapping */
        v.toggle(t, node);
      }},
      el('div', 'who', el('b', {text: t.name || t.speaker}), el('span', {text: `${t.step_label} · turn ${t.index + 1}`})),
      opts.slot || (open ? composeLine(conv, t, v.api) : body), opts.slot ? null : reacts, opts.slot ? null : chips,
      !opts.slot && cutWhy ? cutNote(cutWhy, v) : null);
    node.fill = () => { node.classList.remove('building'); fill(node, node.firstChild, body, reacts, chips); };
    if (stg && v.dressItem) v.dressItem(node, t.turn_id, stg);
    return node;
  };

  /* [s3-messenger] THE ROULETTE CARD: a turn not yet on air, as the rolls
     that made it - who speaks, the step, each recorded decision as its die
     and what it landed on - and whether its words are written yet. The
     words are not in it anywhere, not even in a title. On air the card pops,
     its dice roll, and it turns into the written message. */
  v.card = (t, conv) => {
    const evs = turnEvents(conv, t);
    const lines = turnLines(conv, t);
    const hint = airOfLines(lines, v.air) === 'off' ? 'withdrawn - it will not air'
      : lineText(conv, t) ? 'written - waiting its turn' : 'being written';
    const chips = evs.map(ev => rouletteChip(ev, conv, e => { e.stopPropagation(); v.select(t.turn_id, ev.event_id, e.currentTarget); openDecision(conv, ev, t, v.api); }));
    const node = el('article', {class: `s3-msg ${SIDE[t.speaker] || 'left'} seat-${t.speaker} s3-upcoming`,
        'data-turn': t.turn_id, 'data-key': t.turn_id, 'data-stage': 'upcoming',
        onclick: e => v.select(t.turn_id, '', e.currentTarget)},
      el('div', 'who', el('b', {text: t.name || t.speaker}), el('span', {text: `${t.step_label} · turn ${t.index + 1}`})),
      el('div', 's3-bubble s3-roulette', chips.length ? el('div', 's3-rl-dice', ...chips) : null,
        el('span', {class: 's3-rl-hint', text: hint})),
      chips.length ? el('div', 's3-reacts', el('button', {type: 'button', class: 's3-replay-btn', innerHTML: PLAY_SVG,
        title: 'replay how this line was decided - the Rolodex, the roulette and the dice',
        'aria-label': 'replay how this line was decided', onclick: e => { e.stopPropagation(); v.replayTurn(node, conv, t); }})) : null);
    /* the dice roll together, a little staggered, inside the time given */
    node.roll = async (ms) => {
      if (!chips.length || ms <= 0) return;
      const each = ms * 0.7, step = chips.length > 1 ? (ms * 0.3) / (chips.length - 1) : 0;
      await Promise.all(chips.map((c, i) => sleep(i * step).then(() => c.roll(each))));
    };
    return node;
  };

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
    const name = boardName(line);
    const played = pair && pair.played;
    const quips = pair ? ((pair.obs.sfx_guy || []).map(q => q && q.text).filter(Boolean)) : [];
    const why = played && played.why ? `matched on "${played.why}"` : '';
    let poster = null;
    if (!upcoming && typeof line.poster === 'string' && line.poster) {
      poster = el('img', {class: 's3-sfxposter' + (stg === 'live' ? ' s3-popin' : ''), src: stationUrl(line.poster), alt: name || 'the clip',
        loading: 'lazy', decoding: 'async', onerror: e => { e.currentTarget.hidden = true; }});
    }
    const node = el('article', {class: `s3-msg left s3-sfxguy s3-sfxnode${upcoming ? ' s3-upcoming' : ''}` +
        `${stg === 'live' ? ' live' : stg === 'past' ? ' past' : stg === 'skipped' ? ' skipped' : ''}`,
        'data-turn': t.turn_id, 'data-line': line.line_id, 'data-key': key, 'data-stage': stg,
        title: stg === 'skipped' ? 'not heard: ' + (offWhy(conv, [line]) || 'withdrawn or cut before air') : null},
      el('div', 'who', sfxAvatar(), el('b', {text: 'SFX'}), el('span', {text: `a sting after turn ${t.index + 1}`})),
      el('div', 's3-bubble s3-sfx-bubble' + (upcoming ? ' s3-roulette' : ''),
        dice.length ? el('div', 's3-rl-dice', ...dice) : null,
        upcoming ? el('span', {class: 's3-rl-hint', text: dice.length ? 'picked - waiting its turn' : 'a sting - waiting its turn'}) : null,
        poster || (!upcoming && played ? sfxClipCard(played, v) : null),
        !upcoming && name ? el('div', {class: 's3-clip-name', text: name}) : null,
        !upcoming && quips.length ? el('div', {class: 's3-words', text: quips.join(' ')}) : null,
        !upcoming && why ? el('div', {class: 's3-sfx-why', text: why}) : null));
    node.s3 = {conv, t, obs: pair ? pair.obs : null, played: played || null, line};
    node.addEventListener('click', e => {
      if (e.target.closest(KEEP_OPEN + ', .s3-vthumb, .s3-aplayer')) return;
      e.stopPropagation();
      if (pair && !upcoming) openSfxMenu(conv, t, pair.obs, played, v, node, e);
    });
    /* the category die, then the clip die */
    node.roll = async (ms) => {
      if (ms <= 0) return;
      for (const f of faces) await f.roll(ms / Math.max(1, faces.length));
    };
    if (v.dressItem) v.dressItem(node, key, stg);
    return node;
  };
  /* Open or close one line where it stands, keeping what the host painted on it. */
  v.toggle = (t, node) => {
    if (v.open.has(t.turn_id)) v.open.delete(t.turn_id); else v.open.add(t.turn_id);
    const fresh = v.bubble(t);
    v.keepPaint(node, fresh);
    const hadFocus = node.contains(document.activeElement);
    node.replaceWith(fresh);
    const b = hadFocus && fresh.querySelector('.s3-sbopen');
    if (b) b.focus({preventScroll: true});
  };
  v.keepPaint = (from, to) => {
    /* [s3-messenger] in a Messenger the builder draws the stage (past, skipped); only the host's marks carry over */
    for (const c of v.sequenced ? ['sel', 'onair'] : ['sel', 'onair', 'past', 'skipped']) if (from.classList.contains(c)) to.classList.add(c);
    if (!v.sequenced && from.classList.contains('skipped')) to.title = from.title;
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
    return [...s.before, v.bubble(t, {conv}), ...s.after];
  };
  v.roundChat = (conv) => el('div', 's3-chat', ...v.turnsInOrder(conv).flatMap(t => v.turnNodes(conv, t)));   /* [s3-still] newest first when asked */

  v.paintConversation = () => {
    const conv = v.conv;
    const chat = conv ? v.roundChat(conv) : el('div', 's3-chat');
    fill(v.paneA, el('h2', null, 'Conversation', el('span', {class: 's3-muted', text: conv ? `${conv.turns.length} turns` : ''})),
      conv && conv.mode === 'shadow' ? el('p', {class: 's3-muted', text: 'Shadow: System 3 planned this round beside the legacy writer and none of its plan reached air. Each bubble shows the words that were written for that seat, with what System 3 would have directed underneath.'}) : null,
      chat);
    return chat;
  };

  /* One round built from its recorded rolls, message by message: the slot
     appears, each decision rolls its drum and die, and the message converts
     into its text - the dialogue typing itself in when the writer's words are
     there, the direction the writer was given when they are not yet.
     `latest` hands back the round as it stands now, so words that landed
     while it was building are the ones it converts into. */
  v.buildRound = async (conv, chat, {base = 700 / v.speed, live = () => true, grow = null, latest = null, settled = null, quiet = false} = {}) => {
    const now = () => (latest ? latest() : conv) || conv;
    for (const first of conv.turns) {
      if (!v.alive || !live()) return false;
      const c0 = now();
      const t0 = c0.turns.find(x => x.turn_id === first.turn_id) || first;
      if (quiet) {
        /* [s3-roads] the round takes its place without the show: the
           Rolodex turns when each line is HEARD (the air reveal), not when the
           plan lands - that is what was out of step with the audio. */
        const made = v.turnNodes(c0, t0);
        chat.append(...made);
        if (settled) settled(c0, t0);
        if (grow) grow(made[made.length - 1]);
        continue;
      }
      const slot = el('div', 's3-bubble', el('span', 's3-typing', el('i'), el('i'), el('i')));
      const node = v.bubble(t0, {slot, conv: c0});
      chat.append(node);
      if (grow) grow(node);
      await sleep(reduced() ? 0 : base * 0.5);
      const rolls = el('div');
      fill(slot, rolls);
      for (const ev of turnEvents(c0, t0)) {
        if (!v.alive || !live()) return false;
        const row = rollRow(ev, c0);
        rolls.append(row);
        if (grow) grow(node);
        await row.roll(reduced() ? 0 : base);
      }
      await sleep(reduced() ? 0 : base * 0.4);
      const c1 = now();
      const t1 = c1.turns.find(x => x.turn_id === first.turn_id) || t0;
      const nodes = v.turnNodes(c1, t1);
      node.replaceWith(...nodes);
      if (settled) settled(c1, t1);
      const bubble = nodes.find(n => n.classList.contains('s3-msg') && !n.classList.contains('s3-sfxguy'));   /* [s3-messenger] a sting can stand before it now */
      if (bubble && !reduced()) {
        bubble.classList.add('arriving');
        setTimeout(() => bubble.classList.remove('arriving'), 2400);
        const words = typable(bubble) && bubble.querySelector('.s3-words');
        if (grow) grow(nodes[nodes.length - 1]);
        if (words) await typewriter(words, words.textContent, Math.min(1800, words.textContent.length * 14));
      }
      if (grow) grow(nodes[nodes.length - 1]);
    }
    return true;
  };

  /* One tile built again where it stands, the way the live feed builds it:
     the dice and the Rolodex roll into place, one slate per decision, then
     step aside and the words type in. The now-playing card's tap lands here. */
  v.rebuildTurn = async (node, conv, t, base = 700 / v.speed) => {
    if (!node || node.dataset.replaying) return null;
    const slot = el('div', 's3-bubble', el('span', 's3-typing', el('i'), el('i'), el('i')));
    const tile = v.bubble(t, {slot, conv});
    tile.dataset.replaying = '1';
    v.keepPaint(node, tile);
    node.replaceWith(tile);
    let fresh = null;
    try {
      await sleep(reduced() ? 0 : base * 0.4);
      const rolls = el('div');
      fill(slot, rolls);
      for (const ev of turnEvents(conv, t)) {
        if (!tile.isConnected) break;
        const row = rollRow(ev, conv);
        rolls.append(row);
        await row.roll(reduced() ? 0 : base);
      }
      await sleep(reduced() ? 0 : base * 0.5);
    } finally {
      if (tile.isConnected) {
        fresh = v.bubble(t, {conv});
        v.keepPaint(tile, fresh);
        tile.replaceWith(fresh);
        const words = typable(fresh) && fresh.querySelector('.s3-words');
        if (words && !reduced()) {
          fresh.classList.add('arriving');
          setTimeout(() => fresh.classList.remove('arriving'), 2400);
          await typewriter(words, words.textContent, Math.min(1800, words.textContent.length * 14));
        }
      }
    }
    return fresh;
  };

  /* One message replayed where it stands: each decision's roulette, dice
     and Rolodex with its arithmetic, then the words type back in. */
  v.replayTurn = async (node, conv, t) => {
    if (node.dataset.replaying) return;
    node.dataset.replaying = '1';
    const body = [...node.children].find(n => n.classList.contains('s3-bubble') || n.classList.contains('s3-compose'));
    const panel = el('div', {class: 's3-bubble s3-replay', 'data-keep': ''});
    if (body) body.replaceWith(panel); else node.append(panel);
    try {
      for (const ev of turnEvents(conv, t)) {
        if (!node.isConnected) break;
        const card = replayCard(ev, conv, t, v.api);
        panel.append(card);
        await card.play(reduced() ? 0 : 620 / v.speed);
      }
      await sleep(reduced() ? 0 : 600);
    } finally {
      if (node.isConnected) {
        const fresh = v.bubble(t, {conv});
        v.keepPaint(node, fresh);
        node.replaceWith(fresh);
        const words = typable(fresh) && fresh.querySelector('.s3-words');
        if (words && !reduced()) {
          fresh.classList.add('arriving');
          typewriter(words, words.textContent);
          setTimeout(() => fresh.classList.remove('arriving'), 2400);
        }
      }
    }
  };

  /* Words arriving for a turn that was only a direction: the direction steps
     down to its small line and the dialogue types itself in. */
  v.arrive = (node, conv, t) => {
    const fresh = v.bubble(t, {conv});
    v.keepPaint(node, fresh);
    fresh.classList.add('arriving');
    node.replaceWith(fresh);
    const words = typable(fresh) && fresh.querySelector('.s3-words');
    if (words && !reduced()) typewriter(words, words.textContent);
    setTimeout(() => fresh.classList.remove('arriving'), 2800);
    return fresh;
  };

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

  v.paintRolodex = () => {
    const conv = v.conv;
    const out = [el('h2', null, 'Technical / RNG Rolodex', el('span', {class: 's3-muted', text: conv ? `${(conv.decision_events || []).length} recorded decisions` : ''}))];
    if (!conv) { fill(v.paneB, ...out); return; }
    if (conv.mode === 'shadow') out.push(el('p', {class: 's3-muted', text: 'Shadow: every roll below is recorded, and none of them reached air.'}));
    const pre = (conv.decision_events || []).filter(e => !e.turn_id);
    if (pre.length) out.push(el('div', 's3-turnhead', 'BEFORE THE FIRST TURN'), ...pre.map(e => v.eventCard(e)));
    for (const t of v.turnsInOrder(conv)) {
      out.push(el('div', {class: 's3-turnhead', 'data-turn': t.turn_id, text: `SYSTEM 3 — TURN ${String(t.index + 1).padStart(4, '0')} · ${t.speaker} ${t.name || ''} · ${t.step_label} · ${t.phase}`}));
      for (const ev of turnEvents(conv, t)) out.push(v.eventCard(ev, t));
      for (const o of (conv.observations_air || []).filter(o => o.turn_id === t.turn_id || ((o.family === 'SFX' || o.family === 'SFXGUY') && t.script_index != null && o.turn_index === t.script_index))) out.push(v.eventCard(o, t));
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

  /* "For each message, I want to see the message slot appear for the
     person, then a Rolodex effect ... and a dice next to each entry that
     animates rolling then does a pop effect as it lands on a value." */
  v.build = async () => {
    if (!v.conv || v.playing) return;
    const token = ++v.token, subject = v.conv;
    v.playing = true;
    if (v.onBuildState) v.onBuildState(true);
    const chat = el('div', 's3-chat');
    fill(v.paneA, el('h2', null, 'Conversation', el('span', {class: 's3-muted', text: 'building from the recorded rolls'})), chat);
    try {
      await v.buildRound(subject, chat, {base: 700 / v.speed, live: () => token === v.token && v.conv === subject,
        grow: node => { if (!v.quiet) node.scrollIntoView({block: 'nearest'}); }});
    } finally {
      v.playing = false;
      if (v.onBuildState) v.onBuildState(false);
      if (v.conv && v.alive) { v.paintConversation(); v.select(v.sel.turn, v.sel.event, null); }
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
   AIR, ONE LINE AT A TIME" below). The view follows the line on air, kept
   near the bottom like a text thread; scrolled up by hand it stays put and
   offers "Back to the line on air" (scrolling back down to the air, or 20 s
   of stillness, resumes the follow). It reads the station's event cursor (one small request every few
   seconds, only while the view is on screen) and fetches a round only when
   it has news - never a request per line, never a repaint of the feed. */
export async function mountEmbedded(root, {request, view = 'conversation', onSelect, onOpenFull, chrome} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-embed');
  const v = makeViews({request, onSelect: (conv, turnId, eventId) => {
    if (!onSelect) return;
    onSelect({conversation: conv.identity.conversation_id, turn: turnId, event: eventId,
      lines: (conv.lines || []).filter(l => l.turn_id === turnId).map(l => l.line_id)});
  }});
  let current = view === 'rolodex' || view === 'technical' ? 'rolodex' : 'conversation';
  let cid = '', note = '';
  let liveTurn = '', liveLine = '', handAt = 0, selfUntil = 0;
  /* [s3-messenger] THE VIEW FOLLOWS THE AIR, not the bottom of the feed: the
     line on air stays in sight near the bottom, the way a text thread keeps
     its newest message, with what comes next peeking under it. A hand
     scrolling up stops the follow; scrolling back down to the air, the
     jump button, the on-air pill or 20 s with no scrolling resumes it. */
  let follow = true;
  let liveKey = '';                            /* the item the host's focus is on: a turn id, or 'sfx:<line>' */
  let hold = null;                             /* a finger held down on something */
  let unseen = 0;                              /* lines that went on air while the view was not following */
  const FOLLOW_AGAIN = 20000;
  const title = el('b', 's3-embed-title');
  const facts = el('span', 's3-muted s3-embed-facts');
  const onAir = el('button', {type: 'button', class: 's3-pill s3-embed-air', title: 'take me to the line on air',
    onclick: () => { toAir(); }});
  /* The line on air, in whichever of the two views is up. In the Messenger
     the pill puts the view back on the air and it STAYS there, following
     (it used to stop the follow - the next line was then left behind). */
  function toAir() {
    if (current === 'rolodex') {
      const n = nodesFor(liveTurn)[0];
      if (!n) return false;
      selfUntil = Date.now() + 800;
      n.scrollIntoView({block: 'center', behavior: reduced() ? 'auto' : 'smooth'});
      n.classList.remove('s3-flash'); void n.offsetWidth; n.classList.add('s3-flash');
      return true;
    }
    const n = itemNode(liveKey) || nodesFor(liveTurn)[0];
    if (!n) return false;
    follow = true; unseen = 0;
    toAnchor(true);
    n.classList.remove('s3-flash'); void n.offsetWidth; n.classList.add('s3-flash');
    paintJump();
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
      const fresh = await v.rebuildTurn(node, entry.conv, t);
      if (fresh) dressAir();
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
  const jumpBtn = iconBtn('c:download', 'Back to the line on air', () => { follow = true; unseen = 0; toAnchor(true); paintJump(); },
    {class: 's3-ibtn s3-embed-follow', hidden: true}, 'On air');   /* [s3-messenger] */
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
  const tools = el('span', 's3-bar-tools', jumpBtn, turnBtn, cutBtn, playBtn, fullBtn);
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

  /* ---- following the air ------------------------------------------------- */
  const atBottom = () => root.scrollHeight - root.scrollTop - root.clientHeight < 90;
  function toBottom(smooth) {
    if (current !== 'conversation' || hold) return;
    selfUntil = Date.now() + (smooth ? 700 : 120);
    if (smooth && !reduced()) root.scrollTo({top: root.scrollHeight, behavior: 'smooth'});
    else root.scrollTop = root.scrollHeight;
  }
  /* [s3-messenger] The line on air near the bottom of the view, a peek of
     what comes next under it; a line taller than the view shows its head.
     With nothing on air yet, the newest message, as before. */
  function toAnchor(smooth) {
    if (current !== 'conversation' || hold) return;
    const n = itemNode(liveKey);
    if (!n) { toBottom(smooth); return; }
    const box = root.getBoundingClientRect(), r = n.getBoundingClientRect();
    if (!box.height || !r.height) return;
    const cover = head && head.isConnected ? head.offsetHeight : 0;     /* the sticky bar over the top of the view */
    const lip = Math.min(140, root.clientHeight * 0.22);
    let top = root.scrollTop + (r.bottom - box.top) - (root.clientHeight - lip);
    if (r.height > root.clientHeight - lip - cover - 16) top = root.scrollTop + (r.top - box.top) - cover - 8;
    top = Math.max(0, Math.min(root.scrollHeight - root.clientHeight, Math.round(top)));
    if (Math.abs(top - root.scrollTop) < 2) return;
    selfUntil = Date.now() + (smooth && !reduced() ? 700 : 160);
    if (smooth && !reduced()) root.scrollTo({top, behavior: 'smooth'});
    else root.scrollTop = top;
  }
  /* the line on air is in sight, at or above the bottom of the view */
  const airInSight = () => {
    const n = itemNode(liveKey);
    if (!n) return false;
    const box = root.getBoundingClientRect(), r = n.getBoundingClientRect();
    return r.bottom <= box.bottom + 4 && r.bottom >= box.top;
  };
  function refollow() {
    if (follow || hold || current !== 'conversation' || Date.now() - handAt < FOLLOW_AGAIN) return;
    follow = true; unseen = 0;
    toAnchor(true);
    paintJump();
  }
  function paintJump() {
    jumpBtn.hidden = follow || current !== 'conversation';
    jumpBtn.dataset.count = unseen ? String(unseen > 99 ? '99+' : unseen) : '';
    jumpBtn.title = unseen ? `Back to the line on air (${unseen} went on air since)` : 'Back to the line on air';
  }
  let lastTop = 0;
  root.addEventListener('scroll', () => {
    const top = root.scrollTop, up = top < lastTop - 1;
    lastTop = top;
    if (Date.now() < selfUntil) return;
    handAt = Date.now();
    /* [s3-messenger] a hand scrolling up stops the follow; back down to the air (or the bottom), it follows again */
    if (up) follow = false;
    else if (atBottom() || airInSight()) follow = true;
    if (follow) unseen = 0;
    paintJump();
  }, {passive: true});

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
    if (!e.target.closest('.s3-msg, .s3-sysrow, .s3-clip, .s3-round-head')) return;
    e.preventDefault();
    heldAt = Date.now();
    holdMenu(e.target, {x: e.clientX, y: e.clientY});
  });
  /* the tap that ends a hold is not also a tap on what was held */
  root.addEventListener('click', e => { if (Date.now() - heldAt < 700) { e.stopPropagation(); e.preventDefault(); } }, true);

  async function holdMenu(target, at) {
    const la = window.PineLineActions;
    const headEl = target.closest('.s3-round-head');
    if (headEl) {
      /* by its own id: the header is redrawn whenever the round has news,
         and a hold can outlast the node it started on */
      const entry = feed.get(headEl.dataset.conv);
      if (entry) roundMenu(entry);
      return;
    }
    const sfxNode = target.closest('.s3-sfxguy');
    if (sfxNode && sfxNode.s3) {
      const {conv, t, obs, played, line} = sfxNode.s3;
      const media = played ? await v.api.sfxMedia(played) : null;
      const board = line || boardLineFor(conv, t, media);          /* [s3-messenger] a sting node knows its own row */
      if (la && typeof la.open === 'function' && board) {
        sfxNode.pineItem = {tag: 'sting', sfx: (media && media.id) || (played && played.sample_id) || '', line: board.line_id,
          deleted: false, text: (media && media.name) || board.text};
        sfxNode.dataset.line = board.line_id;
        try { la.open({id: board.line_id, said: 'A sting off the board: ' + ((media && media.name) || board.text), node: sfxNode}); return; }
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
    const line = (conv.lines || []).find(l => l.turn_id === t.turn_id);
    if (la && typeof la.open === 'function' && line) {
      try { la.open({id: line.line_id, said: line.text || lineText(conv, t), node: msg}); return; } catch (e) { /* System 3's menu */ }
    }
    turnMenu(conv, t, msg);
  }

  /* What to do with a segment: its node graph, how it was assembled, its
     build again, the full instrument. */
  function roundMenu(entry) {
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
      btn('How System 3 assembled it', () => { close(); openAssembly(conv, v.air); }),
      btn('Replay this round\'s build, message by message', () => { close(); replay(entry); }),
      onOpenFull ? btn('Open it in System 3', () => { close(); onOpenFull(conv.identity.conversation_id); }) : null];
    back.append(movableModal(el('section', {class: 's3-modal s3-holdmenu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this segment?'},
      el('b', {text: 'What would you like to do with this segment?'}),
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
  if (window.ResizeObserver) new ResizeObserver(() => { if (follow && !replaying && current === 'conversation') toAnchor(false); }).observe(feedBox);
  const grew = () => { if (follow && !replaying) toAnchor(false); };

  /* ---- the feed ---------------------------------------------------------- */
  const FEED_MAX = 14;             /* 40 kept 316 messages and 58k nodes on the tablet */
  const feed = new Map();                     /* conversation id -> entry */
  const queue = [];                           /* rounds waiting to be added, message by message */
  let pumping = false, cursor = null, timer = 0, busy = false;
  let seqCache = null;                        /* [s3-messenger] the air's order of every item on show */
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
    boardSig(conv, t), airOfLines(turnLines(conv, t), v.air)].join('|');

  function roundHead(conv) {
    const lines = (conv.lines || []).length;
    const written = conv.turns.filter(t => lineText(conv, t)).length;
    const state = conv.status === 'planned' ? 'planned - waiting for the writer'
      : lines ? `${lines} line${lines === 1 ? '' : 's'} in the script`
        : written ? `${written} of ${conv.turns.length} turns written` : String(conv.status || '');
    return el('div', {class: 's3-round-head', 'data-conv': conv.identity.conversation_id, title: 'tap and hold for what to do with this segment'},
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
    return el('div', {class: 's3-round-rolls', 'data-keep': ''}, ...pre.map(ev => {
      const chip = chipOf(ev, conv);
      return el('span', {class: 's3-diamond' + (chip.miss ? ' miss' : ''), style: `--fam:${FAM[ev.family] || 'var(--obs)'}`, 'data-event': ev.event_id,
        title: chip.title, text: chip.text, role: 'button', tabindex: '0',
        onclick: e => { e.stopPropagation(); openDecision(conv, ev, null, v.api); },
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } }});
    }));
  }

  /* [s3-messenger] A ROUND'S PLACE IN THE FEED IS ITS PLACE ON THE AIR. The
     script ledger's block is the order the air takes, so a round in the
     script sits by its first block; a round not in the script yet (being
     written) comes after every round that is, newest last - it can only air
     after them. A round that never reached the script and is long past
     (written and never aired) keeps its place in time. Nothing new is ever
     slotted in above the line on air by a later plan: a plan joins the end. */
  const blockOf = c => { let b = Infinity; for (const l of c.lines || []) { const n = Number(l.block); if (n > 0 && n < b) b = n; } return b; };
  const ghost = c => blockOf(c) === Infinity && Date.now() / 1000 - convTime(c) > STALE_S;
  function airsAfter(a, b) {
    const x = blockOf(a), y = blockOf(b);
    if (x !== Infinity && y !== Infinity && x !== y) return x > y;
    if ((x === Infinity) !== (y === Infinity) && !ghost(x === Infinity ? a : b)) return x === Infinity;
    return convTime(a) > convTime(b);
  }
  function place(entry) {
    const later = [...feedBox.children].map(n => feed.get(n.dataset.conv))
      .find(e => e && e !== entry && airsAfter(e.conv, entry.conv));
    if (later) { if (entry.section.nextElementSibling !== later.section) feedBox.insertBefore(entry.section, later.section); }
    else if (feedBox.lastElementChild !== entry.section) feedBox.append(entry.section);
    seqCache = null;
  }
  function mountRound(conv) {
    const id = conv.identity.conversation_id;
    const entry = {conv, section: el('section', {class: 's3-round', 'data-conv': id}), headEl: roundHead(conv),
      chat: el('div', 's3-chat'), building: false, dirty: false, pending: null, fetchedAt: Date.now(), airAt: Date.now(), sig: new Map()};
    entry.section.append(entry.headEl, entry.chat);
    feed.set(id, entry);
    place(entry);
    v.remember(conv);
    emptyBox.hidden = true;
    return entry;
  }

  function paintRound(entry) {
    seqCache = null;
    fill(entry.chat, ...entry.conv.turns.flatMap(t => v.turnNodes(entry.conv, t)));
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
    if (feed.has(id) || queue.some(j => j.conv.identity.conversation_id === id)) return;
    const conv = await fetchRound(id);
    if (feed.has(id) || queue.some(j => j.conv.identity.conversation_id === id) || conv.mode === 'simulation') return;
    if (animate && !reduced()) { queue.push({conv}); pump(); return; }
    const entry = mountRound(conv);
    paintRound(entry);
    trim();
    dressAir();
  }

  /* News for a round on show: only the turns whose words, status, SFX or
     speaker-box state moved are redrawn, where they stand. A turn that just
     got its words types them over its direction. Nothing here scrolls. */
  function patchRound(entry, next) {
    if (entry.building) { entry.pending = next; return; }
    const before = entry.conv;
    entry.conv = next;
    v.remember(next);
    if (cid === next.identity.conversation_id) v.conv = next;
    seqCache = null;
    if (blockOf(before) !== blockOf(next)) place(entry);      /* [s3-messenger] it reached the script: its place on the air */
    if (before.turns.map(t => t.turn_id).join() !== next.turns.map(t => t.turn_id).join()) {
      paintRound(entry);
    } else {
      for (const t of next.turns) {
        const sig = sigOf(next, t);
        const old = entry.sig.get(t.turn_id) || '';
        if (old === sig) continue;
        const was = before.turns.find(x => x.turn_id === t.turn_id);
        const hadWords = old.startsWith('w|') || !!(was && lineText(before, was));
        const group = [...entry.chat.children].filter(n => n.dataset && n.dataset.turn === t.turn_id);
        const oldBubble = group.find(n => n.classList.contains('s3-msg') && !n.classList.contains('s3-sfxguy'));
        const fresh = v.turnNodes(next, t);
        if (group.length) { group[0].before(...fresh); group.forEach(n => n.remove()); } else entry.chat.append(...fresh);
        const bubble = fresh.find(n => n.classList.contains('s3-msg') && !n.classList.contains('s3-sfxguy'));
        if (oldBubble && bubble) v.keepPaint(oldBubble, bubble);
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
    dressAir();
  }

  /* [s3-messenger] Rounds go from the top, above the air only: a round at
     or after the line on air (what is airing, what comes next) is never
     dropped, and a round the operator holds (a pick, an open line) is kept. */
  function trim() {
    while (feed.size > FEED_MAX) {
      const onAirHere = e => e.conv.turns.some(t => t.turn_id === liveTurn || t.turn_id === airHead) ||
        (airHead.startsWith('sfx:') && (e.conv.lines || []).some(l => 'sfx:' + l.line_id === airHead));
      const held = e => e.building || e.conv.turns.some(t => t.turn_id === v.sel.turn || v.open.has(t.turn_id));
      const order = [...feedBox.children].map(n => feed.get(n.dataset.conv)).filter(Boolean);
      const air = order.findIndex(onAirHere);
      const victim = (air < 0 ? order : order.slice(0, air)).find(e => !held(e));
      if (!victim) break;
      const above = victim.section.getBoundingClientRect().bottom <= root.getBoundingClientRect().top + 1;
      const keep = root.scrollHeight - root.scrollTop;          /* dropping from above the view keeps the view still */
      victim.section.remove();
      feed.delete(victim.conv.identity.conversation_id);
      v.forget(victim.conv.identity.conversation_id);
      seqCache = null;
      if (above) { selfUntil = Date.now() + 120; root.scrollTop = root.scrollHeight - keep; }
    }
  }

  async function seed() {
    let rows = [];
    try { rows = (await request('/api/system3/conversations?limit=4')).conversations || []; } catch (e) { rows = []; }
    for (const row of rows.slice().reverse()) {
      if (row.mode === 'simulation') continue;
      try { await addRound(row.conversation_id); } catch (e) { /* that round is skipped */ }
    }
    if (cid && !feed.has(cid)) { try { await addRound(cid); } catch (e) { /* keep going */ } }
    paintHead();
    follow = true;
    toAnchor(false);
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
    onAir.hidden = !t;
    onAir.textContent = !t ? '' : liveKey.startsWith('sfx:') ? 'on air: a sting after turn ' + (t.index + 1)
      : 'on air: turn ' + (t.index + 1) + ' · ' + (t.name || t.speaker);
  }

  /* The Technical view keeps the old manners: it follows the lit turn of
     the round on show, gently, and not for 8 s after a hand scroll. */
  function placeRolodex(force) {
    if (current !== 'rolodex' || !liveTurn) return;
    if (!force && Date.now() - handAt < 8000) return;
    const target = nodesFor(liveTurn)[0];
    if (!target) return;
    selfUntil = Date.now() + 700;
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
     written, and the new one pops: its dice roll for a sliver of the line
     (15 %, at most 1.2 s) and it turns into its message, the words coming
     in as far as the audio has got (face.clock: this line's own position
     and length; the turn's earlier lines are already whole). With no clock
     the words come at about 14 characters a second, so they never stall.
     Every tick touches the one live node, nothing else. The host's focus
     can go BACK (a line tapped in the script): the ON AIR mark follows it,
     nothing is re-played and nothing already shown is hidden again. */
  const PACE = 14, ROLL_SHARE = 0.15, ROLL_MAX = 1200, CLOCK_FRESH = 2500;
  let clockAt = {line: '', at: 0, total: 0, when: 0};
  let airHead = '';                  /* the furthest item the air has reached */
  let rv = null;                     /* the reveal running on the head */
  let raf = 0;
  const doneBars = new Set();        /* items that played out here: their bar stays, full */
  const mmss = x => { const n = Math.max(0, Math.floor(Number(x) || 0)); return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0'); };
  const sfxKey = l => 'sfx:' + l.line_id;
  /* every item on show -> its place in the air's order (rebuilt when the feed changes) */
  function seqPos() {
    if (seqCache) return seqCache;
    const pos = new Map();
    let i = 0;
    for (const sec of feedBox.children) {
      const entry = feed.get(sec.dataset.conv);
      if (!entry) continue;
      const plan = boardPlan(entry.conv);
      for (const t of entry.conv.turns || []) {
        const slot = plan.get(t.turn_id);
        if (slot) for (const l of slot.before) pos.set(sfxKey(l), i++);
        pos.set(t.turn_id, i++);
        if (slot) for (const l of slot.after) pos.set(sfxKey(l), i++);
      }
    }
    seqCache = pos;
    return pos;
  }
  function itemNode(key) {
    if (!key) return null;
    return v.paneA.querySelector(key.startsWith('sfx:') ? '.s3-sfxnode[data-key="' + CSS.escape(key) + '"]'
      : '.s3-msg[data-key="' + CSS.escape(key) + '"]:not(.s3-sfxguy)');
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
      const t = (entry.conv.turns || []).find(x => x.turn_id === key);
      if (t) return {entry, conv: entry.conv, t, line: null};
    }
    return null;
  }

  /* the stage of any item, from the air's head (the window's receipts-only
     reading while the air has not been seen yet) */
  v.sequenced = true;
  v.stageOf = (key, conv, t) => {
    const base = v.airStage(key, conv, t);
    if (!conv || conv.mode === 'shadow' || conv.mode === 'simulation') return 'written';
    if (rv && rv.key === key) return rv.phase === 'roll' ? 'upcoming' : 'live';
    if (!airHead) return base;
    const pos = seqPos(), at = pos.get(key), h = pos.get(airHead);
    if (at == null || h == null) return base;
    if (at > h) return 'upcoming';
    return base === 'skipped' ? 'skipped' : 'past';
  };
  const charsOf = (r, len) => (r.k >= 1 ? len : Math.floor(r.k * len));
  v.revealed = (key, len) => (rv && rv.key === key && rv.phase === 'words' ? charsOf(rv, len) : len);
  /* the bar goes across the message, inside it, along its bottom edge; its
     clock sits small in the header line */
  v.dressItem = (node, key, stg) => {
    const bubble = [...node.children].find(n => n.classList.contains('s3-bubble'));
    if (!bubble || (stg !== 'live' && !(stg === 'past' && doneBars.has(key)))) return;
    const live = stg === 'live';
    bubble.classList.add('has-bar');
    bubble.append(el('div', {class: 's3-airbar' + (live ? '' : ' done'), 'aria-hidden': 'true',
      style: '--k:' + (live && rv ? barOf(rv, performance.now()) : 1).toFixed(4)}, el('i')));
    const who = node.querySelector(':scope > .who');
    if (live && who) who.append(el('span', {class: 's3-airclock', 'aria-hidden': 'true'}));
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
    const next = k != null ? k : r.k + Math.max(0, now - r.lastT) / 1000 / r.secs;      /* no clock: paced */
    r.lastT = now;
    r.k = Math.max(r.k, Math.min(1, next));
    if (k != null) r.bar = Math.max(r.bar || 0, k);
  }
  function paintReveal(now) {
    const r = rv;
    if (!r || r.phase !== 'words') return;
    if (!r.node || r.node.dataset.key !== r.key || r.node.dataset.stage !== 'live' || !v.paneA.contains(r.node)) r.node = itemNode(r.key);
    const node = r.node;
    if (!node || node.dataset.stage !== 'live' || node.dataset.replaying) return;
    const words = r.text ? node.querySelector(':scope > .s3-bubble > .s3-words') : null;
    if (words) {
      const n = charsOf(r, r.text.length);
      if (n !== r.n || words.textContent.length !== n) { words.textContent = r.text.slice(0, n); r.n = n; }
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
    if (rv.k < 1) raf = requestAnimationFrame(frame);
  }
  function tickReveal() {
    if (!rv || rv.phase !== 'words') return;
    const now = performance.now();
    stepK(rv, now);
    paintReveal(now);
    if (!raf && rv.k < 1) raf = requestAnimationFrame(frame);
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

  /* Every node on show brought to the stage the air says: drawn-whole
     stages (written, past, skipped) change in place; a card that must
     become words, or words that must become a card, are drawn again with
     their turn. Cheap: it runs when the air moves or a round has news. */
  const WHOLE = ['written', 'past', 'skipped'];
  function restage() {
    for (const entry of feed.values()) {
      if (entry.building) continue;
      const redo = new Set();
      for (const n of entry.chat.querySelectorAll(':scope > [data-key]')) {
        if (n.dataset.replaying) continue;
        const t = entry.conv.turns.find(x => x.turn_id === n.dataset.turn);
        if (!t) continue;
        const want = v.stageOf(n.dataset.key, entry.conv, t), have = n.dataset.stage || 'written';
        if (want === have) continue;
        if (WHOLE.includes(want) && WHOLE.includes(have) && !(want === 'past' && doneBars.has(n.dataset.key))) {
          n.classList.toggle('past', want === 'past');
          n.classList.toggle('skipped', want === 'skipped');
          n.dataset.stage = want;
          if (want === 'skipped') n.title = 'not heard: withdrawn or cut before air';
          continue;
        }
        redo.add(t);
      }
      for (const t of redo) regroup(entry, t);
    }
  }
  /* one turn's nodes (its stings and the SFX Guy's rows with it) drawn again where they stand */
  function regroup(entry, t) {
    const group = [...entry.chat.children].filter(n => n.dataset && n.dataset.turn === t.turn_id);
    const fresh = v.turnNodes(entry.conv, t);
    const marks = new Map(group.filter(n => n.dataset.key).map(n => [n.dataset.key, n]));
    for (const f of fresh) { const was = f.dataset && marks.get(f.dataset.key); if (was) v.keepPaint(was, f); }
    if (group.length) { group[0].before(...fresh); group.forEach(n => n.remove()); } else entry.chat.append(...fresh);
  }
  /* one item's node drawn again where it stands: the card that becomes its message */
  function swapItem(key) {
    const it = itemAt(key);
    const node = itemNode(key);
    if (!it || !it.t || !node) return null;
    const fresh = it.line ? v.sfxRows(it.conv, it.t)[it.side].find(n => n.dataset && n.dataset.key === key)
      : v.bubble(it.t, {conv: it.conv});
    if (!fresh) return null;
    v.keepPaint(node, fresh);
    node.replaceWith(fresh);
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
    } else if (isSpoken(row)) key = row.turn_id;
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
    const pos = seqPos(), at = pos.get(key), h = airHead ? pos.get(airHead) : null;
    if (at == null || (h != null && at <= h)) return true;       /* reached already, or behind the air */
    const c = clockAt, sounding = c.total > 0 && performance.now() - c.when < CLOCK_FRESH;
    if (sounding ? c.line !== lineId : (h != null && at > h + 3 && performance.now() - pendingAt < 4000)) return false;
    airReached(key);
    return true;
  }

  /* The air reached `key` (a line of it is on air). */
  function airReached(key) {
    if (rv && rv.key === key) return;                        /* the next line of the same turn: its clock takes over */
    const pos = seqPos();
    const at = pos.get(key), h = airHead ? pos.get(airHead) : null;
    if (at == null) return;
    if (h != null && at <= h) return;                        /* behind the air: the operator's focus, nothing re-plays */
    finishReveal();                                          /* never two at once: the last one is finished first */
    startReveal(key);
  }
  async function startReveal(key) {
    const it = itemAt(key);
    if (!it || !it.t) return;
    airHead = key;
    const lines = it.line ? [it.line] : turnLines(it.conv, it.t);
    const w = lines.map(l => Math.max(1, String(l.text || '').length));
    const before = [];
    let sum = 0;
    for (const x of w) { before.push(sum); sum += x; }
    const text = it.line ? '' : v.wordsOf(it.t, it.conv);
    const receipt = it.line ? v.air.get(it.line.line_id) : null;
    const secs = it.line ? Math.max(2, Number((receipt && receipt.seconds) || 5)) : Math.max(2, (text.length || 40) / PACE);
    const me = rv = {key, text, idx: new Map(lines.map((l, i) => [l.line_id, i])), w, before, sum: sum || 1, secs,
      k: 0, bar: 0, n: -1, phase: 'roll', lastT: performance.now(), node: null};
    /* everything before it drawn whole, everything after it its card - this one its card, about to pop */
    restage();
    dressAir();
    if (follow) toAnchor(!reduced()); else { unseen += 1; paintJump(); }
    const card = itemNode(key);
    const c = clockAt;
    const len = c.total > 0 && me.idx.has(c.line) && performance.now() - c.when < CLOCK_FRESH ? c.total
      : receipt && receipt.seconds ? Number(receipt.seconds) : me.secs;
    const ms = current === 'conversation' && !reduced() && card && typeof card.roll === 'function'
      ? Math.min(ROLL_MAX, len * 1000 * ROLL_SHARE) : 0;
    if (ms > 0) {
      card.classList.add('s3-popin');
      await Promise.race([card.roll(ms), frameSleep(ms + 400)]);
    }
    if (rv !== me) return;                                   /* the next item came first: this one was finished already */
    me.phase = 'words';
    me.lastT = performance.now();
    const fresh = swapItem(key);
    if (fresh && ms > 0) { fresh.classList.add('arriving'); setTimeout(() => fresh.classList.remove('arriving'), 1600); }
    dressAir();
    tickReveal();
    if (follow) toAnchor(false);
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
    fill(entry.chat);
    /* [s3-messenger] the build is watched where it grows; the follow picks up the air after it */
    replaying = true;
    follow = true;
    try {
      await v.buildRound(entry.conv, entry.chat, {base: 700 / v.speed, live: () => v.alive && feed.get(entry.conv.identity.conversation_id) === entry,
        grow: n => { if (follow && n && n.isConnected && !hold) { selfUntil = Date.now() + 160; n.scrollIntoView({block: 'nearest'}); } },
        latest: () => entry.pending || entry.conv});
    } finally {
      replaying = false;
      entry.building = false;
      if (entry.pending) { entry.conv = entry.pending; entry.pending = null; }
      paintRound(entry);
      dressAir();
      if (follow) toAnchor(false);
      playBtn.disabled = false;
    }
  }

  paintHead();
  paintBody();
  readTurn();
  schedule(50);
  const face = {
    setView(next) {
      current = next === 'rolodex' || next === 'technical' ? 'rolodex' : 'conversation';
      paintHead(); paintBody();
      if (current === 'conversation') { follow = true; toAnchor(false); schedule(50); } else placeRolodex(true);
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
      refollow();
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
      refollow();
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
      /* a video taken out of the page keeps decoding until it is collected */
      for (const vid of root.querySelectorAll('video, audio')) { try { vid.pause(); } catch (e) { /* gone */ } }
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
    el('b', {text: "The SFX Guy's line" + (t ? ` - after turn ${t.index + 1} (${t.name || t.speaker})` : '')}),
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
  if (got && got.conversation && !conv) {
    try { conv = await request('/api/system3/conversation/' + encodeURIComponent(got.conversation.conversation_id)); } catch (e) { conv = null; }
  }
  const t = conv && got.turn ? (conv.turns || []).find(x => x.turn_id === got.turn.turn_id) : null;
  const tell = (directed, why) => { try { if (typeof onResolved === 'function') onResolved({directed, why, got, conv, turn: t}); } catch (e) { /* the host's own */ } };
  if (conv && got && got.sfxguy) {
    /* [s3-link] the SFX Guy's row: his node and the draw that chose it */
    const v = makeViews({request});
    v.conv = conv;
    fill(root, sfxGuyStory(conv, got.sfxguy, v));
    tell(true, 'the SFX Guy\'s node on the turn he followed');
    return {dispose() { fill(root); }};
  }
  if (conv && !t) {
    const cid = (conv.identity || {}).conversation_id || '';
    const who = String((got.line || {}).who || '');
    const old = conv.engine && conv.engine !== 'system3-engine/3';
    say(`Part of a System 3 round (${(conv.identity || {}).road_kind || 'a'} round ${cid}) but not one of its planned turns: `
      + (who === 'drop' ? (old ? 'the SFX Guy spoke here before he had a node (this round was planned by ' + conv.engine + '), so the dial\'s own random chose the line.'
          : 'the SFX Guy\'s line; its draw was not recorded on this row.')
        : who === 'board' ? 'a board clip. The dice for the clip are on the turn it punctuates.'
        : 'a line the station put into the round at air - a passage dealt in front by the old door, a caller\'s hello - which no node made. The dice for the round are on its turns.'));
    tell(false, 'in a System 3 round, but not one of its turns');
    return {dispose() { fill(root); }};
  }
  if (!conv || !t) {
    say('Not directed by System 3. This line came from a road System 3 does not run yet - a gold bar replayed as filler, '
      + 'a punctuation row on a single line - or from a round written before it was switched on. Nothing '
      + 'was rolled for it, and nothing in its prompt came from the Rolodex.');
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

  const rolls = el('div', 's3-story-rolls');
  for (const ev of evs) {
    const row = rollRow(ev, conv);
    const line = eventLine(ev, conv);
    rolls.append(el('div', {class: 's3-story-roll', role: 'button', tabindex: '0', title: 'how this was decided',
        onclick: () => openDecision(conv, ev, t, v.api),
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDecision(conv, ev, t, v.api); } }},
      row, el('div', {class: 's3-muted s3-story-why', text: line.text})));
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
    sectionOf('The checks on this turn', verdict));
  // the tile builds itself again as the section opens: the dice, then the words
  const first = tile.querySelector('.s3-msg');
  if (first && !reduced()) setTimeout(() => { if (first.isConnected) v.rebuildTurn(first, conv, t); }, 250);
  for (const r of rolls.querySelectorAll('.s3-roll')) if (r.roll) r.roll(reduced() ? 0 : 900);
  return {dispose() { v.alive = false; fill(root); }};
}

/* ======================================================================== */
export async function mount(root, {request, onClose, tab: startTab = '', table: startTable = '', conversationId = ''} = {}) {
  request ||= defaultRequest();
  /* [s3-cast] 'tables:DIRECTIVE1' opens a tab on a table - the Mind desk's buttons use it */
  if (typeof startTab === 'string' && startTab.includes(':') && !startTable) [startTab, startTable] = startTab.split(':', 2);
  const send = (path, method, body) => request(path, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  root.classList.add('s3');
  let alive = true, tab = startTab || 'director', view = 'split', cursor = 0, follow = false;   /* [s3-still] follow live only when asked */
  let status = null, list = [], config = null, settings = null, lastLoaded = '';
  const timers = [];
  const v = makeViews({request});
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
  let readingAt = 0;
  const reading = () => Date.now() - readingAt < 25000 || !!document.querySelector('.s3-modal-back');
  const noteReading = () => { readingAt = Date.now(); };
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
  const quiet = () => { message.className = ''; message.textContent = ''; };
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
  v.onBuildState = () => paintHead();

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

  async function load(cid, animate = false) {
    try {
      const c = await request('/api/system3/conversation/' + encodeURIComponent(cid));
      const air = c.lines && c.lines.length ? await v.inspectBlocks(c) : new Map();
      v.setConversation(c, air);
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
  const TABLE_FAMILIES = ['CTS', 'ES', 'RS', 'IRS', 'FL', 'TEMPER', 'SHOCK', 'INTERJECT', 'FAV', 'DIRECTIVE', 'EVENT', 'CHANCE', 'POOL'];
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
  function poolFields(item) {
    /* a directive's odds and lifetime; a favourite's origin */
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
    if (draft.family === 'FAV') {
      const when = item.at ? new Date(item.at * 1000).toLocaleString() : '';
      return el('div', 's3-row s3-pool', el('span', {class: 's3-muted',
        text: `said by ${item.name || item.who || 'the cast'}${when ? ' · liked ' + when : ''}${item.line_id ? ' · line ' + item.line_id : ''}${item.source ? ' · ' + item.source : ''}`}));
    }
    return null;
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
      el('p', {class: 's3-muted', text: draft.description || ''}));
    for (const cat of draft.categories) {
      /* [s3-window] each category folds; it can be dropped, or consolidated into another */
      const foldKey = draft.id + '/' + cat.id;
      const others = draft.categories.filter(c => c !== cat);
      const box = el('details', {class: 's3-cat', open: !foldedCats.has(foldKey),
        ontoggle: e => { if (e.target !== box) return; if (box.open) foldedCats.delete(foldKey); else foldedCats.add(foldKey); }});
      box.append(el('summary', null, el('b', {text: cat.label || cat.id}),
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
      for (const item of cat.items) {
        const row = el('div', 's3-item',
          el('input', {type: 'text', value: item.label, 'aria-label': 'label', oninput: e => { item.label = e.target.value; }}),
          ...slider(item.weight ?? 1, v => { item.weight = v; }),
          el('label', 's3-row', el('input', {type: 'checkbox', checked: item.enabled !== false, onchange: e => { item.enabled = e.target.checked; }}), 'on'),
          el('input', {type: 'text', class: 'txt', value: item.text || '', placeholder: draft.family === 'DIRECTIVE' ? 'the directive, as the writer is told it' : draft.family === 'FAV' ? 'the line, word for word' : 'what the writer is told this turn does', oninput: e => { item.text = e.target.value; }}),
          poolFields(item),
          /* [s3-flow] follow-on odds: after what the turn before rolled, this row weighs more (or less) */
          ['CTS', 'ES', 'RS', 'IRS', 'FL', 'EVENT'].includes(draft.family) ? el('input', {type: 'text', class: 'txt s3-after',
            value: Object.entries(item.after || {}).map(([k, m]) => `${k}=${m}`).join(', '),
            placeholder: 'follow-on odds, e.g. RS:argue=1.6, ES:anger=0.5 (after the turn before rolled it)',
            onchange: e => { const got = {}; for (const part of e.target.value.split(',')) { const [k, m] = part.split('=').map(x => (x || '').trim()); if (k && m && !isNaN(+m)) got[k] = +m; }
              if (Object.keys(got).length) item.after = got; else delete item.after; }}) : null);
        /* [s3-window] drag to reorder inside the category; x removes */
        const wrap = el('div', {class: 's3-item-row', draggable: true,
          ondragstart: e => { tableDrag = {cat, item}; wrap.classList.add('s3-dragging'); try { e.dataTransfer.setData('text/plain', item.id); } catch (_) { /* older engine */ } },
          ondragend: () => { wrap.classList.remove('s3-dragging'); tableDrag = null; },
          ondragover: e => { if (tableDrag && tableDrag.cat === cat && tableDrag.item !== item) { e.preventDefault(); wrap.classList.add('s3-drop-before'); } },
          ondragleave: () => wrap.classList.remove('s3-drop-before'),
          ondrop: e => { wrap.classList.remove('s3-drop-before'); if (!tableDrag || tableDrag.cat !== cat) return; e.preventDefault();
            const from = cat.items.indexOf(tableDrag.item); if (from < 0) return; const [moved] = cat.items.splice(from, 1);
            const to = cat.items.indexOf(item); cat.items.splice(to < 0 ? cat.items.length : to, 0, moved); tableDrag = null; paintTables(); }},
          el('span', {class: 's3-grip', title: 'drag to reorder', text: '\u22ee\u22ee'}), row,
          btn('x', () => { cat.items.splice(cat.items.indexOf(item), 1); paintTables(); }, {'aria-label': 'remove item', style: 'padding:0 6px'}));
        box.append(wrap);
      }
      const adv = el('textarea', {value: json(Object.fromEntries(Object.entries(cat).filter(([k]) => !['items', 'label', 'weight', 'id'].includes(k))))});
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
    fill(body, el('div', 's3-edit', listNode, editor));
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
        draws, el('div', 's3-row',
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
        draws, el('div', 's3-row', mark('prepend'), mark('append'),
          btn('up', () => { if (i) { [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]]; paintStructure(); } }),
          btn('down', () => { if (i < steps.length - 1) { [steps[i + 1], steps[i]] = [steps[i], steps[i + 1]]; paintStructure(); } }),
          btn('remove', () => { steps.splice(i, 1); paintStructure(); }))));
      nodes.append(el('div', 's3-arrow'));
    });
    nodes.append(el('div', 's3-node', el('b', {text: 'Closing turn'}), el('div', 's3-muted',
      'The last turn of every scene draws: ' + structure.closing.draws.map(d => d.family + (d.closes ? ' (closing moves only)' : '')).join(', '))),
      el('div', 's3-loop', 'Handoff initiator role to the other party → loop the cycle for the segment duration. The structure loops, not the dialogue.'));
    fill(body, el('div', 's3-card', el('h2', {text: structure.label + ' structure'}), roadPicker(),
      el('p', {class: 's3-muted', text: 'Mark the lines that roll for a speakerbox insertion before (prepend) or after (append) them. The odds are the prepend and append sliders on the DJ desk, scaled by the Speakerbox density control.'}),
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
  let segRoad = '', segNodes = null, segRoadOf = '', segSel = {node: -1, draw: -1}, segDrag = null;
  let segInitiator = null;   /* [s3-flow] who opens the banter cycle (null: as saved) */
  const SEG_FAMS = ['CTS', 'ES', 'RS', 'IRS', 'FL'];
  function segStructures() { return config.config.structures || {}; }
  function segLoad(road) {
    if (segNodes && segRoadOf === road) return;
    segRoadOf = road; segSel = {node: -1, draw: -1};
    segNodes = road === 'banter' ? JSON.parse(JSON.stringify(config.config.structure.steps || []))
      : JSON.parse(JSON.stringify((segStructures()[road] || {}).legs || []));
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
    const props = el('div', 's3-seg-props');
    if (cycle) props.append(el('label', null, 'who opens the round ',   /* [s3-flow] */
      el('select', {onchange: e => { segInitiator = e.target.value; }},
        ...[['', 'the first seat (as always)'], ['A', 'seat A (the host)'], ['B', 'seat B (the co-host)'], ['D', 'seat D (the third seat)']]
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
        try { const res = await send('/api/system3/structures/' + encodeURIComponent(key), 'PUT', {...st, legs: nodes, label: name, weight: 1, enabled: true, variant_of: base});
          await loadConfig(); segRoad = key; segNodes = null; repaint(); saved('variant ' + key, res); } catch (e) { report(e); }
      }),
      isVariant ? el('label', 's3-row', 'weight', el('input', {type: 'number', min: 0, max: 50, step: 0.1, value: st.weight == null ? 1 : st.weight, style: 'width:72px', onchange: e => { st.weight = +e.target.value; }})) : null,
      isVariant ? el('label', 's3-row', el('input', {type: 'checkbox', checked: st.enabled !== false, onchange: e => { st.enabled = e.target.checked; }}), 'runs on the station') : null,
      btn('Save segment', async () => { try {
          let res;
          if (cycle) { nodes.forEach((x, i) => { x.id = x.id || 'step' + i; }); res = await send('/api/system3/structure', 'PUT', {steps: nodes, initiator: segInitiator ?? (st.initiator || '')}); }   /* [s3-flow] */
          else { nodes.forEach((lg, i) => { lg.id = lg.id || 'leg' + i; }); res = await send('/api/system3/structures/' + encodeURIComponent(segRoad), 'PUT', {...st, legs: nodes}); }
          await loadConfig(); segNodes = null; repaint(); saved(cycle ? 'the banter cycle' : 'the ' + segRoad + ' segment', res); } catch (e) { report(e); } }),
      btn('Discard', () => { segNodes = null; repaint(); }),
      isVariant ? btn('Delete variant', async () => { if (!confirm('Delete ' + segRoad + '?')) return;
        try { const res = await send('/api/system3/structures/' + encodeURIComponent(segRoad), 'DELETE'); await loadConfig(); segRoad = base; segNodes = null; repaint(); saved('- deleted variant ' + (res && res.deleted || segRoad), res); } catch (e) { report(e); } }) : null,
      el('span', {class: 's3-muted', text: cycle ? 'The banter cycle loops for the segment; each step is a node with its own draws.'
        : `Turn budget ${st.min_turns || '?'}-${st.max_turns || '?'}. ${isVariant ? 'This variant' : 'Every variant'} rolls against the base by weight (VARIANT) each time the road runs.`}));
    fill(body, el('div', 's3-seg', el('div', 's3-seg-side', el('div', 's3-card', palette), el('div', 's3-card', el('h2', {text: 'Properties'}), props)),
      el('div', 's3-seg-main', el('div', 's3-card', el('h2', {text: (st.label || segRoad) + ' - segment'}), bar), list)));
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
  async function paintSys3() {
    const host = el('div', 's3-sys3'); const canvas = el('canvas'); host.append(canvas);
    const nowNode = el('div', 's3-sys3-now', 'waiting for the line on air...');
    host.append(nowNode, el('div', 's3-sys3-legend', el('span', {text: 'centre: System 3'}), el('span', {text: 'ring: the roads (lit = directed by System 3)'}),
      el('span', {text: 'right: the writer, the recording room, the ledger, the air'}), el('span', {text: 'paper airplanes: decisions landing; packets: the circuits'})));
    fill(body, el('div', 's3-card', el('h2', {text: 'Sys3 - System 3 and the systems it directs, live'}), host));
    if (sys3) { sys3.stop(); sys3 = null; }
    let THREE; try { THREE = await threeLoad(); } catch (e) { report(e); return; }
    if (tab !== 'sys3' || !canvas.isConnected) return;
    sys3 = sys3Scene(THREE, canvas, nowNode);
  }
  function sys3Scene(THREE, canvas, nowNode) {
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
    const nodes = new Map();
    const core = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.6, 1.6), new THREE.MeshStandardMaterial({color: 0x8ac6ac, emissive: 0x1f3a33})); scene.add(core); nodes.set('system3', core);
    const lineMat = (c, o) => new THREE.LineBasicMaterial({color: c, transparent: true, opacity: o});
    const circuits = [];
    roads.forEach((r, i) => { const a = (i / n) * Math.PI * 2; const p = new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R * 0.55);
      const on = r.mode === 'active';
      const m = new THREE.Mesh(new THREE.SphereGeometry(on ? 0.42 : 0.3, 16, 12), new THREE.MeshStandardMaterial({color: on ? 0x54d18b : 0x35414c, emissive: on ? 0x10331f : 0x000000}));
      m.position.copy(p); m.userData = {road: r.id, on}; scene.add(m); nodes.set(r.id, m);
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), p]), lineMat(on ? 0x54d18b : 0x35414c, on ? 0.45 : 0.15)));
      circuits.push({from: new THREE.Vector3(0, 0, 0), to: p, phase: Math.random(), speed: 0.12 + Math.random() * 0.1, on});
      label(r.id, p, -0.8, on ? 0.95 : 0.5); });
    const rooms = [['writer', 'the writer', 0xf0a6ca], ['voice', 'recording room', 0x87bfff], ['ledger', 'script ledger', 0xe7bf78], ['air', 'on air', 0x7fe0d6]];
    let prevRoom = null;
    rooms.forEach(([id, text, col], i) => { const p = new THREE.Vector3(R + 4.5, 3.4 - i * 2.2, -2 + i * 0.4);
      const m = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.7, 0.7), new THREE.MeshStandardMaterial({color: col})); m.position.copy(p); scene.add(m); nodes.set(id, m);
      label(text, p, -0.75, 0.95);
      const from = prevRoom ? prevRoom.position.clone() : new THREE.Vector3(0, 0, 0);
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, p]), lineMat(col, 0.5)));
      circuits.push({from, to: p, phase: Math.random(), speed: 0.2, on: true}); prevRoom = m; });
    const packets = circuits.map(c => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 6), new THREE.MeshBasicMaterial({color: 0xffffff})); m.visible = c.on; scene.add(m); return m; });
    const planes = []; const planeGeo = new THREE.ConeGeometry(0.22, 0.7, 4);
    const roadOf = new Map(); let cursor = 0, alive = true, raf = 0, lastText = '', thumbSprite = null;
    const fly = (target, col) => { const m = new THREE.Mesh(planeGeo, new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.95})); m.position.set(0, 0.9, 0); scene.add(m);
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
        const feed = await request('/api/system3/events?after=' + cursor + '&limit=60');
        if (cursor && (feed.events || []).length) {
          for (const e of feed.events) {
            let road = roadOf.get(e.conversation_id);
            if (road === undefined) { try { const c = await request('/api/system3/conversation/' + encodeURIComponent(e.conversation_id)); road = (c.identity || {}).road_kind || ''; } catch (_) { road = ''; } roadOf.set(e.conversation_id, road); }
            fly(nodes.get(road) || nodes.get('writer'), e.kind === 'observation' ? 0x7fe0d6 : colour(FAM[e.family] || 'var(--obs)').getHex());
          }
        }
        cursor = Number(feed.cursor || feed.head || cursor);
        const live = await request('/api/system3/now'); const s3 = live && live.system3; const line = live && live.line;
        const text = line ? `${line.name || line.who || ''}: ${line.text || ''}` : '';
        if (text !== lastText) { lastText = text; thumb(text ? text.slice(0, 220) : '', s3 && s3.turn ? (s3.turn.rolls || []).map(r => r.dice).filter(x => x != null) : []);
          nowNode.textContent = text ? (s3 ? `${s3.road} round · turn ${(s3.turn || {}).turn || '?'} of ${s3.turns} · ` : 'not directed by System 3 · ') + text.slice(0, 160) : 'nothing on air'; }
        nodes.forEach((m, id) => { if (m.userData && m.userData.road) m.material.emissive.setHex(s3 && s3.road === id && text ? 0x2a6b3f : (m.userData.on ? 0x10331f : 0x000000)); });
      } catch (e) { /* the scene keeps turning */ }
      if (alive) setTimeout(poll, 2000);
    }
    const size = () => { const w = canvas.clientWidth || 640, h = canvas.clientHeight || 400; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
    size(); window.addEventListener('resize', size);
    const t0 = performance.now(); const origin = new THREE.Vector3(0, 0.9, 0);
    function frame() {
      if (!alive) return; raf = requestAnimationFrame(frame);
      const t = (performance.now() - t0) / 1000; core.rotation.y = t * 0.6; core.rotation.x = Math.sin(t * 0.5) * 0.4;
      circuits.forEach((c, i) => { if (!c.on) return; const u = (t * c.speed + c.phase) % 1; packets[i].position.lerpVectors(c.from, c.to, u); packets[i].position.y += Math.sin(u * Math.PI) * 0.5; });
      for (let i = planes.length - 1; i >= 0; i -= 1) { const p = planes[i]; p.t += 0.016; const u = Math.min(1, p.t / 1.6);
        p.m.position.lerpVectors(origin, p.to, u); p.m.position.y += Math.sin(u * Math.PI) * 2.2; p.m.lookAt(p.to); p.m.rotateX(Math.PI / 2);
        if (u >= 1) { p.m.material.opacity -= 0.05; if (p.m.material.opacity <= 0) { scene.remove(p.m); planes.splice(i, 1); } } }
      camera.position.x = Math.sin(t * 0.1) * 3; camera.lookAt(0, 0.5, 0); renderer.render(scene, camera);
    }
    frame(); poll();
    return {stop() { alive = false; cancelAnimationFrame(raf); window.removeEventListener('resize', size); try { renderer.dispose(); } catch (_) { /* gone */ } }};
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
      roadsCard(),
      versionsCard(),
      section('speakerbox', 'Mode weights for a hit (verbatim / reference / callback), the inline passage budget per round, and passage length.'),
      section('sfx', 'The SFX Guy: planned-clip probability at aggression 0 and 1, the first-exchange clip, and the arousal and comedy boosts. The station\'s cadence stays the floor.'),
      section('sfxguy', 'The SFX Guy\'s mouth: his node on every host turn. rate_by_dial uses the desk\'s interjections dial for whether he pipes up; reaction_by_warp uses the invention dial for how often a line is fired back at the one just said; news_share is the wire; never_over_callers keeps him off a caller\'s turn.'),
      section('personalities', 'Per seat tag multipliers, e.g. {"A": {"disagreement": 1.4}, "B": {"humor": 1.3}}.'),
      /* [s3-blocks] */
      section('blocks', 'Every block a writer prompt may carry, and what System 3 does with it: kind "obligation" (always sent, recorded), "roll" (a die at odds, or the desk dial named in odds_from), "tint" (only while a crystal is on and the tint pass is wanted) or "off". A block whose name is not here is a wedge and is stripped. The Prompt tab shows each prompt’s blocks as decided.')));
  }

  /* ---------------- plumbing ---------------------------------------------- */
  async function loadConfig() { config = await request('/api/system3/config'); }
  async function refreshStatus() { status = await request('/api/system3/status'); paintStatus(); }

  function paint() {
    paintTabs();
    try {
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

  async function poll() {
    if (!alive || document.hidden) return;
    if (reading()) return;                                  /* [s3-hold] */
    try {
      const feed = await request('/api/system3/events?' + new URLSearchParams({after: cursor, limit: 500}));
      const fresh = feed.events || [];
      cursor = feed.cursor || cursor;
      if (fresh.length && tab === 'director') {
        const cids = [...new Set(fresh.map(e => e.conversation_id))];
        await refreshList();
        const mine = v.conv && cids.includes(v.conv.identity.conversation_id);
        const newest = list[0] && list[0].conversation_id;
        if (follow && newest && newest !== lastLoaded && !v.playing) await keepPlace(() => load(newest, true));
        else if (mine && !v.playing) await keepPlace(() => load(v.conv.identity.conversation_id));   /* [s3-still] */
      }
      await refreshStatus();
    } catch (e) { report(e); }
  }

  try {
    await Promise.all([refreshStatus(), loadConfig(), request('/api/system3/settings').then(s => { settings = s; })]);
    const head = await request('/api/system3/events?after=0&limit=1');
    cursor = head.head || 0;
    await refreshList();
    paint();
    if (list[0]) await load(list[0].conversation_id);
    else paintDirector();
  } catch (e) { report(e); paintTabs(); }
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
      cands.length ? el('details', {class: 's3-rx-cands-fold'}, el('summary', {text: `the ${cands.length} candidates and the weights the engine used`}),
        el('div', 's3-rx-cands', ...cands.map(c => el('div', {class: 's3-rx-cand' + (c.id === hitId ? ' hit' : '')},
          el('b', {text: c.label || c.id}), el('span', {class: 's3-muted', text: `w ${num(c.weight)} - ${pct(c.p)}`}))))) : null,
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
  const wanted = String((t || {}).leg || (t || {}).step || '');
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
  if (closed) view.dispose(); else { const b = root.querySelector('button'); b && b.focus(); }
  return {element: backdrop, close};
}
