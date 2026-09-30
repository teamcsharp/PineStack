// [onecard-moment] ONE MOMENT, ONE CARD. "when building these cards. I dont
// want the info being moved to another card. I need a single card to show the
// entire roulette rolodex result. One card." (the operator, 2026-09-30)
// The road that decides which card owns a roll: a moment is its System 3 turn
// AND the line it is part of (a sting "<line>-punct-1" has no turn of its own);
// every member's rolls land on the moment's card - live, after a twin, and in
// the Result pin of any member.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.css'), 'utf8');
for (const dir of ['app/src/main/assets/pine-views', 'C:/_tools/pinebox-android/PineBoxKiosk/app/src/main/assets/pine-views']) {
  const k = path.isAbsolute(dir) ? dir : path.join(root, dir);
  if (!fs.existsSync(k)) continue;
  assert.strictEqual(fs.readFileSync(path.join(k, 'script-page.js'), 'utf8'), src, dir + ': the kiosk copy is the renderer, byte for byte');
  assert.strictEqual(fs.readFileSync(path.join(k, 'script-page.css'), 'utf8'), css, dir + ': the kiosk css is the renderer\'s');
}

const grab = re => { const m = src.match(re); assert(m, 'missing ' + re); return m[0]; };
const road = grab(/  var MV_MATES = 3;[\s\S]*?\n  function mvPinReveal\(cur\) \{[\s\S]*?\n  \}\n/);
const merge = grab(/  function mvMerge\(a, b\) \{[\s\S]*?\n  \}\n/);

// ---- the contract, read off the source
assert(!/mvTurnHost/.test(src), 'the turn-only host is gone');
assert(/mvAsk\(item\)\.then\(function \(data\) \{\s*mvMomentLand\(cur,/.test(src), 'a live card lands on its moment');
assert(/var rows = \(data\.rows \|\| \[\]\)\.slice\(\);/.test(src), 'no cap of 6 tables on a card');
assert(!/\.slice\(0, 6\)/.test(grab(/  function mvPlan\(cur, data\) \{[\s\S]*?\n  \}\n/)), 'mvPlan keeps every row');
assert(/if \(cur\.sheet\) \{ cur\.sheet\.keep = true; cur\.sheet\.box\.classList\.add\('sp-rr-keep'\); \}/.test(src), 'mvPlan keeps every table in view as the next rolls');
assert(!/cur\.sheet\.keep = false/.test(src), 'nothing folds the tables away again');
const after = grab(/  function mvHistoryAfterAppend\(stage, node, item\) \{[\s\S]*?\n  \}\n/);
assert(/'\.sp-mv-item\[data-mv-key="'/.test(after) && /n === node/.test(after), 'one card per id: live twins go too');
const pin = grab(/  function mvPin\(cur, hop\) \{[\s\S]*?\n  \}\n/);
assert(/mvMomentGather\(cur\)/.test(pin) && /mvPin\(got\.card, cur\)/.test(pin), 'the pin replays the moment on the moment\'s card');
assert(/cur\.joined && cur\.joined\.node && cur\.joined\.node\.isConnected \? cur\.joined : cur/.test(grab(/  function mvPinToggle\(cur\) \{[\s\S]*?\n  \}\n/)), 'a joined card pins its moment\'s card');
assert(/mv\.pin\.from === cur/.test(src) && /from: hop \|\| null/.test(pin), 'the card tapped, handed on, still stops the pin with its own tap');
assert(/node\.__mvCur = cur;/.test(src) && /cur\.node\.__mvCur = cur;/.test(src), 'live and history cards are found off their nodes');
assert(/\.sp-mv-past\.sp-mv-joined \.sp-mv-rolls \{ display: flex !important; \}/.test(css), 'the moment\'s card keeps its tally in view');

// ---- a small list the road runs on
function Stage() { this.kids = []; }
Stage.prototype.querySelectorAll = function () { return this.kids.slice(); };
Stage.prototype.getBoundingClientRect = function () { return {top: 0, bottom: 300}; };
Stage.prototype.add = function (n) { n.parent = this; this.kids.push(n); return n; };
Stage.prototype.drop = function (n) { this.kids.splice(this.kids.indexOf(n), 1); n.parent = null; };
function el() {
  const e = {style: {}, kids: [], cls: new Set(), textContent: '',
    classList: {add: c => e.cls.add(c), remove: c => e.cls.delete(c), contains: c => e.cls.has(c)},
    appendChild: k => { e.kids.push(k); return k; }};
  Object.defineProperty(e, 'textContent', {get: () => '', set: () => { e.kids = []; }});
  return e;
}
function node(stage) {
  const n = el();
  Object.defineProperty(n, 'isConnected', {get: () => !!n.parent && n.parent.kids.includes(n)});
  Object.defineProperty(n, 'previousElementSibling', {get: () => n.parent ? n.parent.kids[n.parent.kids.indexOf(n) - 1] || null : null});
  Object.defineProperty(n, 'nextElementSibling', {get: () => n.parent ? n.parent.kids[n.parent.kids.indexOf(n) + 1] || null : null});
  if (stage) stage.add(n);
  return n;
}

function world() {
  const answers = {};
  const feed = [];
  const W = {answers, feed, planned: []};
  const mv = {stage: new Stage(), cur: null, turnCards: Object.create(null), turnOrder: []};
  const env = {
    mv, root: {requestAnimationFrame: () => 0, PineStationFeed: {rows: () => feed}},
    make: (tag, cls, text) => ({tag, cls, text}),
    mvStatic: r => ({row: r, addEventListener() {}}),
    mvRrSheet: (cur, rows) => ({box: el(), rows: rows.slice(), tables: rows.map((r, i) => ({at: i * 100})), keep: false}),
    mvRrAt: () => 'results', mvRrResults: s => { s.done = true; },
    mvPlan: (cur, data) => { cur.data = data; W.planned.push({cur, rows: data.rows.slice()}); },
    feedDiceOpen() {},
    mvHistItem: row => ({key: 'l:' + row.id, kind: 'clip', lid: String(row.id), row, name: 'CLIP', text: ''}),
    mvAsk: item => Promise.resolve(answers[item.lid] || null),
  };
  const names = Object.keys(env);
  // eslint-disable-next-line no-new-func
  const build = new Function(...names, merge + road +
    '\nreturn {mvBaseLid, mvMomentKeys, mvMomentOf, mvMomentLand, mvMomentGather, mvMomentRows, mvMomentCard};');
  Object.assign(W, build(...names.map(k => env[k])), {mv});
  W.card = (lid, kind, name, text, extra) => {
    const n = node(mv.stage);
    const cur = Object.assign({item: {key: 'l:' + lid, lid, kind, name, text}, node: n, rolls: el(), all: el(), still: true}, extra || {});
    n.__mvCur = cur;
    return cur;
  };
  return W;
}
const row = (fam, table, dice, label, event) => ({fam, table, event: event || '', main: {dice, label}, sub: null});
const ES1 = row('ES', 'ES1', 14, 'ANGER', 'e-es1');
const RS1 = row('RS', 'RS1', 2, 'Comedic', 'e-rs1');
const SFX = row('SFX', 'SFX', 60, 'no clip', 'e-sfx');
const BOOK = row('SFX', 'book', 79, 'sfx_ads');           // the sting's own roll, off its row (no event)
const GUY = row('SFXGUY', 'SFXGUY', 33, 'react', 'e-guy');

(async () => {
  // the ids off the tablet: #049af8d7 and its sting "#049af8d7-p1"
  {
    const W = world();
    const L = '049af8d7e05643b89742708cdd730c9e';
    assert.strictEqual(W.mvBaseLid(L + '-punct-1'), L);
    assert.strictEqual(W.mvBaseLid(L + '-p2'), L);
    assert.strictEqual(W.mvBaseLid(L), L);
    assert.deepStrictEqual(W.mvMomentKeys({lid: L + '-punct-1'}, {tid: ''}), ['l:' + L], 'a sting with no turn is its line\'s moment');
  }

  // LIVE: the line, then its sting, then the SFX Guy's reaction - one card
  {
    const W = world();
    const line = W.card('L1', 'speech', 'Crochet Ashley', 'Oh, for crying out loud!');
    W.mv.cur = line;
    W.mvMomentLand(line, {rows: [ES1, RS1, SFX], tid: 'T1', cid: 'C1', sources: {}});
    assert.deepStrictEqual(line.data.rows.map(r => r.table), ['ES1', 'RS1', 'SFX']);

    const sting = W.card('L1-punct-1', 'clip', 'CLIP', '');
    W.mv.cur = sting;
    W.mvMomentLand(sting, {rows: [BOOK], tid: '', sources: {}});
    assert.strictEqual(sting.joined, line, 'the sting\'s roll goes to the line\'s card, not its own');
    assert.deepStrictEqual(sting.data.rows, [], 'the clip card keeps its picture, no roulette');
    assert.deepStrictEqual(line.data.rows.map(r => r.table), ['ES1', 'RS1', 'SFX', 'book']);
    assert.deepStrictEqual(line.sheet.rows.map(r => r.table), ['ES1', 'RS1', 'SFX', 'book'], 'ONE sheet on the line\'s card holds every table');
    assert.strictEqual(line.sheet.keep, true);
    assert(line.node.cls.has('sp-mv-joined'));
    assert.strictEqual(line.rolls.kids.length, 1, 'never a second sheet beside the first');

    const guy = W.card('G1', 'speech', 'SFX GUY', '');
    W.mv.cur = guy;
    W.mvMomentLand(guy, {rows: [GUY, ES1], tid: 'T1', sources: {}});
    assert.strictEqual(guy.joined, line);
    assert.strictEqual(guy.node.style.display, 'none', 'a roll-only card is not made');
    assert.deepStrictEqual(line.data.rows.map(r => r.table), ['ES1', 'RS1', 'SFX', 'book', 'SFXGUY'], 'each roll once');

    // the line comes back on air: its old card goes, the new one is the moment's card with EVERY roll
    W.mv.stage.drop(line.node);
    const again = W.card('L1', 'speech', 'Crochet Ashley', 'Oh, for crying out loud!');
    W.mv.cur = again;
    W.mvMomentLand(again, {rows: [ES1, RS1, SFX], tid: 'T1', cid: 'C1', sources: {}});
    assert(!again.joined, 'the new card IS the moment\'s card');
    assert.deepStrictEqual(again.data.rows.map(r => r.table).sort(), ['ES1', 'RS1', 'SFX', 'SFXGUY', 'book'].sort(), 'nothing the moment rolled is lost with the old card');
  }

  // THE PIN / HISTORY: tapping any member replays the whole moment on its first card
  {
    const W = world();
    W.card('X0', 'speech', 'DILL', 'I take your point.');
    const L = W.card('L2', 'speech', 'Crochet Ashley', 'Seriously?!');
    const R = W.card('R2', 'speech', 'SKIP', 'Oh, wait!');
    const O = W.card('O2', 'speech', 'DILL', 'Say more.');
    W.answers.X0 = {rows: [row('ES', 'ES1', 5, 'JOY', 'e-x')], tid: 'T0', sources: {}};
    W.answers.L2 = {rows: [ES1, RS1, SFX], tid: 'T2', cid: 'C2', sources: {}};
    W.answers.R2 = {rows: [GUY], tid: 'T2', cid: 'C2', sources: {}};
    W.answers.O2 = {rows: [row('RS', 'RS1', 7, 'Curious', 'e-o')], tid: 'T3', sources: {}};
    W.feed.push({id: 'L2-punct-1', who: 'board', kind: 'sfx'});
    W.answers['L2-punct-1'] = {rows: [BOOK], tid: '', sources: {}};

    const got = await W.mvMomentGather(R);
    assert.strictEqual(got.card, L, 'the Result on the reaction pins the line\'s card');
    assert.deepStrictEqual(got.data.rows.map(r => r.table), ['ES1', 'RS1', 'SFX', 'book', 'SFXGUY'],
      'the moment\'s every roll, in the order it aired - the line, its sting, the reaction');
    assert(!got.data.rows.some(r => r.event === 'e-x' || r.event === 'e-o'), 'the neighbours of other moments stay on their own cards');

    const same = await W.mvMomentGather(L);
    assert.strictEqual(same.card, L);
    assert.deepStrictEqual(same.data.rows.map(r => r.table), ['ES1', 'RS1', 'SFX', 'book', 'SFXGUY']);

    const other = await W.mvMomentGather(O);
    assert.strictEqual(other.card, O);
    assert.deepStrictEqual(other.data.rows.map(r => r.event), ['e-o']);
  }

  console.log('onecard-moment ok: one moment -> one card (live, sting, reaction, twin, pin, history)');
})().catch(e => { console.error(e); process.exit(1); });
