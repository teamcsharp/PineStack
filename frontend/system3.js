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
const FAM = {CTS: 'var(--cts)', ES: 'var(--es)', RS: 'var(--rs)', IRS: 'var(--irs)', FL: 'var(--fl)',
  TEMPER: 'var(--es)', SHOCK: 'var(--rs)', INTERJECT: 'var(--fl)', MENTION: 'var(--cts)', CARRY: 'var(--es)',   /* [s3-rounds] [s3-carry] */
  SPEAKERBOX: 'var(--sb)', SFX: 'var(--sfx)', TOPIC: 'var(--topic)', SFXGUY: 'var(--sfxguy)', LINE: 'var(--line)',
  COMMIT: 'var(--obs)', REPAIR: 'var(--warn)'};
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
  if (fam === 'TOPIC') {
    const meta = ev.meta || {};
    const d = stage(ev, 'dice');
    if (meta.applies === false) return {fam, dice: null, text: 'not rolled: ' + (meta.why || 'the round has its own subject')};
    return {fam, dice: d && d.draw ? d.draw.dice : null,
      text: sel.id === 'NONE' ? `${pct(meta.rate)} odds → nothing off the board`
        : `${pct(meta.rate)} odds → "${sel.label}" → turn ${Number(meta.turn_index) + 1}`};
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
  REPAIR: ['Repair', 'The written script ignored the running order badly enough that one bounded rewrite was asked for (banked rounds only).'],
};
const DIAL_FOR = {ES: ['emotional_volatility'], RS: ['disagreement', 'escalation', 'tangent', 'callback', 'novelty'],
  IRS: ['disagreement', 'escalation'], FL: ['tangent', 'callback', 'novelty', 'closure_aggressiveness', 'escalation'],
  SPEAKERBOX: ['speakerbox_density'], SFX: ['sfx_aggression'], CTS: ['novelty'], TOPIC: ['topics'],
  SHOCK: ['shock_beat'], INTERJECT: ['interjections'], MENTION: ['mention']};   /* [s3-rounds] */

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

function openDecision(conv, ev, turn, api) {
  if (!conv || !ev) return null;
  const back = el('div', {class: 's3 s3-modal-back'});
  const before = document.activeElement;
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); if (before && before.focus) before.focus(); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  const shut = btn('Close', close, {class: 's3-modal-close', 'aria-label': 'Close'});
  const panel = el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How this was decided'},
    shut, decisionCard(conv, ev, turn, api));
  back.append(panel);
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
  back.append(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How this segment was assembled'},
    shut, assemblyCard(conv, air || new Map())));
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
  back.append(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'The systems that cut lines'},
    btn('Close', close, {class: 's3-modal-close'}),
    el('div', 's3-dcard',
      el('div', 's3-dhead', el('div', null, el('b', {text: 'The systems that cut lines'}),
        el('div', {class: 's3-muted', text: 'Each one is a switch in the station\'s policy book. A line one of them cut shows why on its message, with this same switch.'}))),
      list)));
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
    const st = v.turnStatus(t, conv);
    const perf = t.performance || {};
    const aired = v.aired(t, conv);
    const text = t.text || (aired && aired.text) || '';
    const planned = !text;
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
    const node = el('article', {class: `s3-msg ${SIDE[t.speaker] || 'left'} seat-${t.speaker}${opts.slot ? ' building' : ''}` +
      `${composed ? (passages ? ' has-sb' : ' sb-miss') : ''}${open ? ' open' : ''}`,
      'data-turn': t.turn_id, title: composed ? (open ? 'tap to close' : passages ? 'tap to open this line with its speaker-box passages'
        : 'tap to see why no speaker-box passage won this line, and turn the odds') : null,
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
    for (const c of ['sel', 'onair', 'past', 'skipped']) if (from.classList.contains(c)) to.classList.add(c);
    if (from.classList.contains('skipped')) to.title = from.title;
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
    for (const o of played) after.push(sfxEntry(conv, t, o, v));
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
           Rolodex turns when each line is HEARD (spinOnAir), not when the
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
      const bubble = nodes.find(n => n.classList.contains('s3-msg'));
      if (bubble && !reduced()) {
        bubble.classList.add('arriving');
        setTimeout(() => bubble.classList.remove('arriving'), 2400);
        const words = bubble.querySelector('.s3-words');
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
        const words = fresh.querySelector('.s3-words');
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
        const words = fresh.querySelector('.s3-words');
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
    const words = fresh.querySelector('.s3-words');
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
   message waits for it. Words the writer delivers later type over their
   direction where the message stands. The view sticks to the bottom and
   never moves anywhere else on its own: scrolled up, it stays put and offers
   "Jump to latest"; the on-air pill takes you to the line on air only when
   tapped. It reads the station's event cursor (one small request every few
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
  let stick = true;                            /* the view is pinned to the newest message */
  let hold = null;                             /* a finger held down on something */
  let unseen = 0;                              /* messages added while scrolled up */
  const lit = new Set();
  const title = el('b', 's3-embed-title');
  const facts = el('span', 's3-muted s3-embed-facts');
  const onAir = el('button', {type: 'button', class: 's3-pill s3-embed-air', title: 'take me to the line on air',
    onclick: () => { toAir(); }});
  /* The line on air, in whichever of the two views is up. */
  function toAir() {
    const n = nodesFor(liveTurn)[0];
    if (!n) return false;
    stick = false; selfUntil = Date.now() + 800;
    n.scrollIntoView({block: 'center', behavior: reduced() ? 'auto' : 'smooth'});
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
    if (node && t && !entry.building) {
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
  const jumpBtn = iconBtn('c:download', 'Jump to the latest message', () => { stick = true; unseen = 0; toBottom(true); paintJump(); },
    {class: 's3-ibtn s3-embed-follow', hidden: true}, 'Latest');
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

  /* ---- sticking to the bottom -------------------------------------------- */
  const atBottom = () => root.scrollHeight - root.scrollTop - root.clientHeight < 90;
  function toBottom(smooth) {
    if (current !== 'conversation' || hold) return;
    selfUntil = Date.now() + (smooth ? 700 : 120);
    if (smooth && !reduced()) root.scrollTo({top: root.scrollHeight, behavior: 'smooth'});
    else root.scrollTop = root.scrollHeight;
  }
  function paintJump() {
    jumpBtn.hidden = stick || current !== 'conversation';
    jumpBtn.dataset.count = unseen ? String(unseen > 99 ? '99+' : unseen) : '';
    jumpBtn.title = unseen ? `Jump to the latest message (${unseen} new)` : 'Jump to the latest message';
  }
  root.addEventListener('scroll', () => {
    if (Date.now() < selfUntil) return;
    handAt = Date.now();
    stick = atBottom();
    if (stick) unseen = 0;
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
      const {conv, t, obs, played} = sfxNode.s3;
      const media = played ? await v.api.sfxMedia(played) : null;
      const board = boardLineFor(conv, t, media);
      if (la && typeof la.open === 'function' && board) {
        sfxNode.pineItem = {tag: 'sting', sfx: (media && media.id) || (played && played.sample_id) || '', line: board.line_id,
          deleted: false, text: (media && media.name) || board.text};
        sfxNode.dataset.line = board.line_id;
        try { la.open({id: board.line_id, said: 'A sting off the board: ' + ((media && media.name) || board.text), node: sfxNode}); return; }
        catch (e) { /* the SFX TV's menu instead */ }
      }
      openSfxMenu(conv, t, obs, played, v, sfxNode, {clientX: at.x, clientY: at.y});
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
    back.append(el('section', {class: 's3-modal s3-holdmenu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this segment?'},
      el('b', {text: 'What would you like to do with this segment?'}),
      el('p', {class: 's3-muted', text: `${conv.identity.road_kind} · ${clock(convTime(conv))} · ` + String((conv.subject || {}).topic || '').replace(/\s+/g, ' ').slice(0, 140)}),
      note, el('div', 's3-holdmenu-items', ...items.filter(Boolean)), btn('Close', close)));
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
    back.append(el('section', {class: 's3-modal s3-holdmenu', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'What would you like to do with this line?'},
      el('b', {text: 'What would you like to do with this?'}),
      el('p', {class: 's3-muted', text: (t.name || t.speaker) + ', turn ' + (t.index + 1) + ': ' +
        (lineText(conv, t) || 'no words yet - ' + ((t.directions || []).map(d => d.text).join('; ') || t.step_label))}),
      el('div', 's3-holdmenu-items', ...items.filter(Boolean)), btn('Close', close)));
    back.addEventListener('click', e => { if (e.target === back) close(); });
    document.addEventListener('keydown', key, true);
    document.body.append(back);
  }
  /* Whatever grows the feed - a message arriving, words typing in, a picture
     loading - the bottom stays in view while the view is pinned to it. */
  if (window.ResizeObserver) new ResizeObserver(() => { if (stick && current === 'conversation') toBottom(false); }).observe(feedBox);
  const grew = () => { if (stick) toBottom(false); else { unseen += 1; paintJump(); } };

  /* ---- the feed ---------------------------------------------------------- */
  const FEED_MAX = 14;             /* 40 kept 316 messages and 58k nodes on the tablet */
  const feed = new Map();                     /* conversation id -> entry */
  const queue = [];                           /* rounds waiting to be added, message by message */
  let pumping = false, cursor = null, timer = 0, busy = false;
  const convTime = c => Number(c.created || (c.inputs || {}).at || 0);
  const byTime = () => [...feed.values()].sort((a, b) => convTime(a.conv) - convTime(b.conv));
  const sfxCount = (conv, t) => {
    const idx = scriptIndexOf(conv, t);
    return idx == null ? 0 : (conv.observations_air || []).filter(o => (o.family === 'SFX' || o.family === 'SFXGUY') && o.turn_index === idx).length;
  };
  const sigOf = (conv, t) => [lineText(conv, t) ? 'w' : '-', v.turnStatus(t, conv).word, sfxCount(conv, t),
    (t.speakerbox || []).map(s => s.mode + (s.material ? '+' : '')).join(','), v.open.has(t.turn_id) ? 'o' : ''].join('|');

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
      el('span', {class: 's3-round-topic', text: String((conv.subject || {}).topic || '').replace(/\s+/g, ' ').slice(0, 150)}));
  }

  /* A round's place in the feed: at the bottom when it is the newest (every
     round the station plans from now on), in time order when it is older
     (seeded on open, or asked for by the air). */
  function mountRound(conv) {
    const id = conv.identity.conversation_id;
    const entry = {conv, section: el('section', {class: 's3-round', 'data-conv': id}), headEl: roundHead(conv),
      chat: el('div', 's3-chat'), building: false, dirty: false, pending: null, fetchedAt: Date.now(), airAt: Date.now(), sig: new Map()};
    entry.section.append(entry.headEl, entry.chat);
    const later = byTime().find(e => convTime(e.conv) > convTime(conv));
    if (later) feedBox.insertBefore(entry.section, later.section); else feedBox.append(entry.section);
    feed.set(id, entry);
    v.remember(conv);
    emptyBox.hidden = true;
    return entry;
  }

  function paintRound(entry) {
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
        if (!hadWords && lineText(next, t) && bubble && !v.open.has(t.turn_id)) {
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

  function trim() {
    while (feed.size > FEED_MAX) {
      const held = e => e.building || e.conv.turns.some(t => t.turn_id === liveTurn || t.turn_id === v.sel.turn || v.open.has(t.turn_id));
      const victim = byTime().find(e => !held(e));
      if (!victim) break;
      const keep = root.scrollHeight - root.scrollTop;          /* dropping from the top keeps the view still */
      victim.section.remove();
      feed.delete(victim.conv.identity.conversation_id);
      v.forget(victim.conv.identity.conversation_id);
      if (!stick) { selfUntil = Date.now() + 120; root.scrollTop = root.scrollHeight - keep; }
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
    stick = true;
    toBottom(false);
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

  function dressAir() {
    const c = [...feed.values()].map(e => e.conv).find(x => x.turns.some(t => t.turn_id === liveTurn)) || v.conv;
    if (c) {
      const order = c.turns.map(t => t.turn_id);
      const at = order.indexOf(liveTurn);
      for (const t of c.turns) {
        const i = order.indexOf(t.turn_id);
        const skipped = at >= 0 && i < at && !lit.has(t.turn_id);
        for (const n of nodesFor(t.turn_id)) {
          n.classList.toggle('onair', t.turn_id === liveTurn);
          n.classList.toggle('past', at >= 0 && i < at && lit.has(t.turn_id));
          n.classList.toggle('skipped', skipped);
          if (skipped) n.title = 'not heard: the air stepped over this turn (withdrawn, cut or never rendered)';
        }
      }
    }
    for (const n of (current === 'rolodex' ? v.paneB : v.paneA).querySelectorAll('.onair')) {
      if (n.dataset.turn !== liveTurn) n.classList.remove('onair');
    }
    const t = c && c.turns.find(x => x.turn_id === liveTurn);
    onAir.hidden = !t;
    onAir.textContent = t ? 'on air: turn ' + (t.index + 1) + ' · ' + (t.name || t.speaker) : '';
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

  /* ---- the line on air, in step with the audio ----------------------------
     "When a message is being spoken in the messenger view, I want to see it
      scroll through the rolodex then transition into the final result
      showing the dialogue it generated with loading bar on the bottom as
      it is playing on the station in sync with the audio indicating the
      length of the clip." (operator, 2026-09-27)
     The page says which line is on air (face.live) and, every tick, where
     the clip has got to (face.clock). The spin starts the moment the line
     is heard and takes a fifth of the clip, so the words stand while most
     of it still plays; the bar under the message follows the page's own
     clock for that line. Nothing here invents a number: the reels are the
     recorded candidates, the die is the recorded d100. */
  let clockAt = {line: '', at: 0, total: 0, when: 0};
  let spun = '';
  const mmss = x => { const n = Math.max(0, Math.floor(Number(x) || 0)); return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0'); };
  const liveBubble = () => liveTurn ? nodesFor(liveTurn).find(n => n.classList.contains('s3-msg') && !n.classList.contains('s3-sfxguy')) || null : null;
  function paintClock() {
    const live = liveBubble();
    for (const bar of root.querySelectorAll('.s3-airbar')) if (!live || !live.contains(bar)) bar.remove();
    if (!live) return;
    const fresh = clockAt.line && clockAt.line === liveLine && clockAt.total > 0 && Date.now() - clockAt.when < 4000;
    let bar = live.querySelector('.s3-airbar');
    if (!fresh) { if (bar) bar.remove(); return; }
    if (!bar) { bar = el('div', {class: 's3-airbar', 'aria-hidden': 'true'}, el('i'), el('b')); live.append(bar); }
    const k = Math.max(0, Math.min(1, clockAt.at / clockAt.total));
    bar.style.setProperty('--k', k.toFixed(4));
    bar.querySelector('b').textContent = mmss(clockAt.at) + ' / ' + mmss(clockAt.total);
  }
  async function spinOnAir(turnId) {
    if (current !== 'conversation' || reduced() || !turnId || spun === turnId) return;
    spun = turnId;
    const entry = [...feed.values()].find(e => (e.conv.turns || []).some(t => t.turn_id === turnId));
    const t = entry && entry.conv.turns.find(x => x.turn_id === turnId);
    const node = liveBubble();
    if (!entry || !t || !node || entry.building || node.dataset.replaying) return;
    const secs = Math.max(2, Number((clockAt.line === liveLine && clockAt.total) || t.estimated_seconds || 6));
    const n = Math.max(1, turnEvents(entry.conv, t).length);
    const base = Math.max(140, Math.min(700 / v.speed, (secs * 1000 * 0.2) / n));
    if (stick) toAir();
    const fresh = await v.rebuildTurn(node, entry.conv, t, base);
    if (fresh) { dressAir(); paintClock(); }
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
      if (stick) toBottom(false);
    }
    dressAir();
  }

  /* Play the build: the newest round builds again from its recorded rolls,
     message by message, where it stands. */
  async function replay(which) {
    const entry = which && which.chat ? which : byTime().pop();
    if (!entry || entry.building) return;
    playBtn.disabled = true;
    entry.building = true;
    fill(entry.chat);
    stick = true;
    try {
      await v.buildRound(entry.conv, entry.chat, {base: 700 / v.speed, live: () => v.alive && feed.get(entry.conv.identity.conversation_id) === entry,
        grow: () => grew(), latest: () => entry.pending || entry.conv});
    } finally {
      entry.building = false;
      if (entry.pending) { entry.conv = entry.pending; entry.pending = null; }
      paintRound(entry);
      dressAir();
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
      if (current === 'conversation') { stick = true; toBottom(false); schedule(50); } else placeRolodex(true);
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
      let row = null;
      for (const e of feed.values()) { row = (e.conv.lines || []).find(l => l.line_id === lineId); if (row) break; }
      if (!row && v.conv) row = (v.conv.lines || []).find(l => l.line_id === lineId);
      if (!row) return 'elsewhere';
      if (lineId === liveLine) return 'here';
      liveLine = lineId;
      if (row.turn_id && row.turn_id !== liveTurn) {
        liveTurn = row.turn_id;
        lit.add(liveTurn);
        dressAir();
        placeRolodex(false);
        spinOnAir(liveTurn);                    /* [s3-roads] the Rolodex turns as the line is heard */
      }
      return 'here';
    },
    /* The page's clock for the line on air - where the clip has got to and
       how long it is - so the bar under the live message keeps step with
       the audio. Blank or zero: nothing is sounding. */
    clock(lineId, at, total) {
      clockAt = {line: String(lineId || ''), at: Number(at) || 0, total: Number(total) || 0, when: Date.now()};
      paintClock();
    },
    message(text) { note = text || ''; paintHead(); noteBox.hidden = !note; },
    /* "If I tap on this, jump to the active message in whatever view I have
       up": the host's now-playing card calls this while a System 3 view is
       showing. False when the air is not in this view. */
    jumpToAir(lineId) { return jumpTo(lineId); },
    dispose() {
      v.alive = false; v.token += 1; clearTimeout(timer);
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

export async function mountLineStory(root, {request, lineId = '', prompt = '', onResolved = null} = {}) {
  request ||= defaultRequest();
  root.classList.add('s3', 's3-story');
  const say = text => fill(root, para(text, 's3-muted'));
  say('Asking System 3 about this line...');
  let got = null, conv = null;
  try { got = await request('/api/system3/line?line_id=' + encodeURIComponent(lineId)); } catch (e) { got = null; }
  if (got && got.conversation) {
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
export async function mount(root, {request, onClose, tab: startTab = '', table: startTable = ''} = {}) {
  request ||= defaultRequest();
  const send = (path, method, body) => request(path, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  root.classList.add('s3');
  let alive = true, tab = startTab || 'director', view = 'split', cursor = 0, follow = false;   /* [s3-still] follow live only when asked */
  let status = null, list = [], config = null, settings = null, lastLoaded = '';
  const timers = [];
  const v = makeViews({request});
  v.quiet = true;                                                        /* [s3-still] */
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
  const TABS = [['tables', 'Tables'], ['segments', 'Segments'], ['prompts', 'Prompts'], ['audit', 'Audit'], ['sys3', 'Sys3'],
    ['director', 'Director'], ['structure', 'Structure'], ['controls', 'Controls']];
  function stopExtras() {
    if (sys3) { try { sys3.stop(); } catch (e) { /* gone */ } sys3 = null; }
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
  function paintTables() {
    const tables = config.config.tables;
    if (!draft || draft.id !== tableId) draft = JSON.parse(JSON.stringify(tables.find(t => t.id === tableId) || tables[0]));
    const listNode = el('div', 's3-tlist', el('h2', {text: 'Tables'}),
      ...['CTS', 'ES', 'RS', 'IRS', 'FL'].flatMap(f => [el('h3', {text: f}), ...tables.filter(t => t.family === f).map(t =>
        btn('', () => { tableId = t.id; draft = null; paintTables(); }, {'aria-pressed': String(t.id === draft.id)}))]));
    let i = 0;
    for (const f of ['CTS', 'ES', 'RS', 'IRS', 'FL']) for (const t of tables.filter(x => x.family === f)) {
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
      for (const item of cat.items) {
        const row = el('div', 's3-item',
          el('input', {type: 'text', value: item.label, 'aria-label': 'label', oninput: e => { item.label = e.target.value; }}),
          ...slider(item.weight ?? 1, v => { item.weight = v; }),
          el('label', 's3-row', el('input', {type: 'checkbox', checked: item.enabled !== false, onchange: e => { item.enabled = e.target.checked; }}), 'on'),
          el('input', {type: 'text', class: 'txt', value: item.text || '', placeholder: 'what the writer is told this turn does', oninput: e => { item.text = e.target.value; }}));
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
      box.append(btn('Add item', () => { const id = prompt('New item id'); if (id) { cat.items.push({id, label: id, weight: 1, text: ''}); paintTables(); } }),
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
  const SEG_FAMS = ['CTS', 'ES', 'RS', 'IRS', 'FL'];
  function segStructures() { return config.config.structures || {}; }
  function segLoad(road) {
    if (segNodes && segRoadOf === road) return;
    segRoadOf = road; segSel = {node: -1, draw: -1};
    segNodes = road === 'banter' ? JSON.parse(JSON.stringify(config.config.structure.steps || []))
      : JSON.parse(JSON.stringify((segStructures()[road] || {}).legs || []));
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
    if (!sel) props.append(para('Tap a node to edit it.', 's3-muted'));
    else {
      const field = (label, input) => el('label', null, label, input);
      const labelEl = () => body.querySelector('.s3-seg-node.sel b');
      props.append(el('h4', {text: cycle ? 'Step' : 'Leg'}),
        field('label', el('input', {type: 'text', value: sel.label || sel.id || '', oninput: e => { sel.label = e.target.value; const b = labelEl(); if (b) b.textContent = e.target.value; }})));
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
        el('span', {class: 's3-dice', title: d.fixed !== undefined ? 'roulette off: pinned to ' + d.fixed + ' - tap for the properties' : 'roulette on - tap to pin a value',
          text: d.fixed !== undefined ? 'pin' : 'd100', onclick: e => { e.stopPropagation(); segSel = {node: i, draw: k}; if (d.fixed === undefined) d.fixed = (segTableItems(d.family)[0] || {}).id || ''; else delete d.fixed; repaint(); }}),
        d.family + (d.tables ? ':' + d.tables.join('/') : '') + (d.closes ? ' closes' : '') + (d.fixed !== undefined ? ' = ' + d.fixed : ''),
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
          if (cycle) { nodes.forEach((x, i) => { x.id = x.id || 'step' + i; }); res = await send('/api/system3/structure', 'PUT', {steps: nodes}); }
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
    const req = d.request || {}; const msgs = Array.isArray(req.messages) ? req.messages : [];
    const sys = msgs.filter(m => m.role === 'system').map(m => m.content).join('\n\n') || req.system || '';
    const user = msgs.filter(m => m.role !== 'system').map(m => (m.role ? m.role + ': ' : '') + (m.content || '')).join('\n\n') || req.prompt || '';
    const res = d.response || {}; const text = (res.message && res.message.content) || res.response || res.text || (typeof res === 'string' ? res : '');
    const opts = {model: req.model, ...(req.options || {}), think: req.think, keep_alive: req.keep_alive, stream: req.stream};
    const box = (title, kid, pre = true) => el('div', 's3-tile-box', el('h4', {text: title}), pre ? el('pre', {text: kid || '(none)'}) : kid);
    const roulette = el('div', {class: 's3-muted', text: 'finding the round this call wrote...'});
    const grid = el('div', 's3-tile-grid', box('System prompt', sys), box('Prompt', user), box('LLM settings', json(opts)),
      box('Result', d.error ? String(d.error) : (text || (d.state === 'running' ? 'still running' : '(empty)'))), box('Roulette results', roulette, false));
    rouletteFor(r, roulette);
    return grid;
  }
  async function rouletteFor(r, into) {
    try {
      const list = await request('/api/system3/conversations?limit=30');
      const at = Number(r.at || 0);
      const cands = (list.conversations || []).filter(c => Number(c.created || 0) <= at + 2 && at - Number(c.created || 0) < 240).sort((a, b) => Number(b.created) - Number(a.created));
      const c = cands[0];
      if (!c) { fill(into, para('no System 3 round was planned in the four minutes before this call: a road System 3 does not write, or not a writer call.', 's3-muted')); return; }
      const conv = await request('/api/system3/conversation/' + encodeURIComponent(c.conversation_id));
      const evs = (conv.decision_events || []).filter(e => e.rng);
      fill(into, el('div', {class: 's3-muted', text: `${(conv.identity || {}).road_kind || ''} round ${c.conversation_id}, planned ${num(at - Number(c.created || 0), 1)} s before this call (matched by time) - ${evs.length} rolls`}),
        el('div', 's3-row', ...evs.slice(0, 30).map(e => { const line = eventLine(e, conv);
          return el('span', {class: 's3-draw', style: `--fam:${FAM[e.family] || 'var(--obs)'}`, title: line.text,
            onclick: () => openDecision(conv, e, (conv.turns || []).find(t => t.turn_id === e.turn_id) || null, v.api)},
            el('span', {class: 's3-dice', text: String(line.dice == null ? '-' : line.dice)}), e.family); })),
        btn('Open this round in the Director', () => { stopExtras(); tab = 'director'; paint(); load(c.conversation_id); }));
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
    novelty: 'weight on fresh subjects and moves', closure_aggressiveness: 'how early the scene starts landing'};
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
      section('personalities', 'Per seat tag multipliers, e.g. {"A": {"disagreement": 1.4}, "B": {"humor": 1.3}}.')));
  }

  /* ---------------- plumbing ---------------------------------------------- */
  async function loadConfig() { config = await request('/api/system3/config'); }
  async function refreshStatus() { status = await request('/api/system3/status'); paintStatus(); }

  function paint() {
    paintTabs();
    try {
      if (tab === 'director') { fill(body, director); paintDirector(); }
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
  back.append(el('section', {class: 's3-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'How System 3 built this line'}, shut, host));
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(back);
  if (window.PineDuck && typeof window.PineDuck.hold === 'function') window.PineDuck.hold('s3-line-story', window.PineDuck.REPORT, back);
  mountLineStory(host, {request, lineId}).then(x => { story = x; }, () => {});
  shut.focus({preventScroll: true});
  return close;
}

export async function openSystem3({request, onClose, tab = '', table = ''} = {}) {
  const backdrop = el('div', 's3-backdrop');
  const root = el('section', {role: 'dialog', 'aria-modal': 'true', 'aria-label': 'System 3 conversation director'});
  backdrop.append(root); document.body.append(backdrop);
  const before = document.activeElement; let view, closed = false;
  const close = () => { if (closed) return; closed = true; view && view.dispose(); backdrop.remove(); document.removeEventListener('keydown', key); before && before.focus && before.focus(); onClose && onClose(); };
  const key = event => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', key);
  backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });
  view = await mount(root, {request, onClose: close, tab, table});
  if (closed) view.dispose(); else { const b = root.querySelector('button'); b && b.focus(); }
  return {element: backdrop, close};
}
