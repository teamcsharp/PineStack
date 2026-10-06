// [reply-gap:buildup] ONE TIMING CONTRACT: the station schedules a card's
// buildup from reply_gap.py's BUILD_* and the System 3 record; the Script view
// rolls the card from MV_BUILD and the same record. This holds the two equal:
// the numbers, the sheet's own arithmetic, and - on real System 3
// conversations (tests/fixtures_reply_gap_buildup.json) - every table the
// page draws against every table the station counts, and the ms between them.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {spawnSync} = require('child_process');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8').replace(/\r\n/g, '\n');
const py = fs.readFileSync(path.join(root, 'reply_gap.py'), 'utf8');
const sharedTile = require(path.join(root, 'desktop/renderer/system3-message-tile.js'));
const sharedSource = fs.readFileSync(path.join(root, 'desktop/renderer/system3-message-tile.js'), 'utf8');
const engineSource = src + '\n' + sharedSource;
const convs = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures_reply_gap_buildup.json'), 'utf8'));

// 1. The numbers.
const B = sharedTile.BUILD;
assert(src.includes('var MV_BUILD = root.PineSystem3MessageTile.BUILD;'), 'the feed uses the shared timing contract');
const num = name => Number((new RegExp('^' + name + ' = ([0-9.]+)', 'm').exec(py) || [])[1]);
const tup = name => (new RegExp('^' + name + ' = \\(([^)]*)\\)', 'm').exec(py) || [])[1].split(',').map(Number);
assert.strictEqual(B.per, num('BUILD_PER_MS'));
assert.deepStrictEqual(B.one, tup('BUILD_ONE'));
assert.deepStrictEqual(B.two, tup('BUILD_TWO'));
assert.strictEqual(B.rejEach, num('BUILD_REJ_EACH_MS'));
assert.strictEqual(B.rejBase, num('BUILD_REJ_BASE_MS'));
assert.strictEqual(B.rejCap, num('BUILD_REJ_CAP'));
assert.strictEqual(B.rejMax, num('BUILD_REJ_MAX'));
assert.strictEqual(B.fail, num('BUILD_FAIL_MS'));
assert.strictEqual(B.between, num('BUILD_BETWEEN_MS'));
assert.strictEqual(B.hold, num('BUILD_HOLD_MS'));

// 2. The sheet's own arithmetic is the contract's (the fractions, the reject
//    time, the failure, the 40 ms between, the 1.5 s hold), and a card with a
//    scheduled buildup rolls at the contract's pace and is fitted to it.
for (const needle of ['T.dIn = per * 0.08;', 'T.dDie = per * (two ? 0.12 : 0.18);', 'T.dSpin = per * (two ? 0.27 : 0.6);',
  'T.dPop = per * 0.06;', 'T.dDie2 = two ? per * 0.12 : 0;', 'T.dSpin2 = two ? per * 0.27 : 0;',
  'T.dPop2 = two ? per * 0.06 : 0;', 'T.dFail = T.r.failed ? 420 : 0;', 'at = T.end + MV_BUILD.between;',
  "return {box: box, rows: recorded, tables: tables, rolled: at, total: at + MV_BUILD.hold, now: '', elapsed: 0};",
  'if (fit && fit.ms > 0) per = MV_BUILD.per;', 'if (fit && fit.ms > 0) at = mvBuildFit(tables, Math.max(from, Number(fit.from) || 0), fit.ms, at);']) {
  assert(engineSource.includes(needle), 'the sheet: ' + needle);
}
assert(/return n \? Math\.min\(per \* 0\.4, 260 \* n \+ 140\) : 0;/.test(engineSource), 'the rejected rolls\' time');
assert(src.includes('var RR_REJ_MAX = 6;'));

// 3. The page's tables, off the real records.
const grab = name => {
  const g = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(g, 'missing ' + name);
  return g[0];
};
const names = ['mvStageOf', 'mvReel', 'mvDecisionRow', 'mvRrRejOf', 'mvRrVerdicts', 'mvRrFailed', 'mvMerge'];
// eslint-disable-next-line no-new-func
const page = {mvStageOf:sharedTile.stageOf,mvReel:sharedTile.reel,mvDecisionRow:sharedTile.decisionRow,
  mvRrRejOf:sharedTile.rejected,mvRrVerdicts:sharedTile.verdicts,mvRrFailed:sharedTile.failed};
page.mvBuildFit = sharedTile.createRenderer().buildFit;
const rejMs = n => (n ? Math.min(B.per * B.rejCap, B.rejEach * n + B.rejBase) : 0);
const tableMs = t => B.per * (t.sub ? B.two : B.one).reduce((a, b) => a + b, 0)
  + rejMs(t.rej) + (t.sub ? rejMs(t.rej2) : 0) + (t.failed ? B.fail : 0);
const buildMs = spec => (spec.length ? Math.round(spec.reduce((a, t) => a + tableMs(t) + B.between, 0) + B.hold) : 0);

const pageSpecs = [];
for (const c of convs) {
  const evs = Object.create(null);
  c.decision_events.forEach(e => { evs[e.event_id] = e; });
  for (const t of c.turns) {
    const ids = new Set();
    (t.decisions || []).forEach(d => ids.add(d.event_id));
    (t.speakerbox || []).forEach(d => ids.add(d.event_id));
    if (t.sfx) ids.add(t.sfx.event_id);
    if (t.sfxguy) ids.add(t.sfxguy.event_id);
    const spec = [];
    c.decision_events.filter(e => ids.has(e.event_id)).forEach(ev => {
      const r = page.mvDecisionRow(ev);
      if (!r) return;
      spec.push({sub: !!r.sub, rej: ((r.main && r.main.rej) || []).length + (r.vrej || []).length,
        rej2: r.sub ? ((r.sub.rej) || []).length : 0, failed: !!r.failed});
    });
    pageSpecs.push({cid: c.identity.conversation_id, tid: t.turn_id, spec, ms: buildMs(spec)});
  }
}
assert(pageSpecs.some(s => s.spec.length >= 3), 'the fixture has cards with several tables');

// 4. The station's, off the same records (reply_gap.turn_spec / buildup_ms).
const script = [
  'import json, sys',
  'sys.path.insert(0, ' + JSON.stringify(root) + ')',
  'import reply_gap as rg',
  'convs = json.load(open(' + JSON.stringify(path.join(__dirname, 'fixtures_reply_gap_buildup.json')) + ', encoding="utf-8"))',
  'out = []',
  'for c in convs:',
  '    for t in c["turns"]:',
  '        spec = rg.turn_spec(c, t["turn_id"], "dj", claim=False)',
  '        out.append({"cid": c["identity"]["conversation_id"], "tid": t["turn_id"],',
  '                    "spec": [{k: s[k] for k in ("sub", "rej", "rej2", "failed")} for s in spec],',
  '                    "ms": rg.buildup_ms(spec)})',
  'print(json.dumps(out))'].join('\n');
let res = null;
for (const exe of ['python3', 'python']) {
  res = spawnSync(exe, ['-c', script], {encoding: 'utf8'});
  if (res.status === 0) break;
}
assert.strictEqual(res.status, 0, 'the station\'s reckoning ran: ' + (res.stderr || ''));
const station = JSON.parse(res.stdout);
assert.strictEqual(station.length, pageSpecs.length);
let tables = 0;
station.forEach((s, i) => {
  const p = pageSpecs[i];
  assert.strictEqual(s.tid, p.tid);
  assert.deepStrictEqual(s.spec, p.spec, 'turn ' + p.tid + ': the tables the page draws are the tables the station counts');
  assert.strictEqual(s.ms, p.ms, 'turn ' + p.tid + ': the same buildup to the ms');
  tables += p.spec.length;
});
assert(tables >= 10, 'enough tables to mean something: ' + tables);

// 5. The fit: fresh tables laid out again to end exactly on the scheduled ms.
{
  const T = (at, per, two) => {
    const f = two ? B.two : B.one;
    const t = {at, dIn: per * f[0], dRej: 0, dDie: per * f[1], dSpin: per * f[2], dPop: per * f[3],
      dRej2: 0, dDie2: two ? per * f[4] : 0, dSpin2: two ? per * f[5] : 0, dPop2: two ? per * f[6] : 0, dFail: 0};
    t.end = at + t.dIn + t.dDie + t.dSpin + t.dPop + t.dDie2 + t.dSpin2 + t.dPop2;
    return t;
  };
  const a = T(0, 1500, true), b = T(a.end + 40, 1500, false);
  const tables2 = [a, b];
  const at = page.mvBuildFit(tables2, 0, 7000, b.end + 40);
  assert(Math.abs(at + B.hold - 7000) < 1e-6, 'the whole sheet ends on the scheduled ms: ' + (at + B.hold));
  assert(Math.abs(tables2[1].at - (tables2[0].end + 40)) < 1e-9, 'tables in turn, 40 ms apart');
  const c1 = T(0, 1800, false), c2 = T(c1.end + 40, 1800, true);
  const at2 = page.mvBuildFit([c1, c2], 1, 4000, c2.end + 40);
  assert.strictEqual(c1.at, 0, 'a table already rolled is not moved');
  assert(Math.abs(at2 + B.hold - (c2.at + 4000)) < 1e-6, 'a joined card\'s fresh tables fill its own buildup');
}

// 6. The card engine: the next card builds first, starts buildup ms before
//    its words, its reels keep their geometry, its tally stays under the words.
for (const needle of ['function mvBubbleStart(item, redraw, pre) {', 'cur.t0 = pre.audioAt - pre.ms;',
  'cur.buildFit = {ms: pre.ms, from: 0};', 'cur.keepRolls = true;', 'if (cur.sheet) mvRrReserve(cur.sheet);',
  'cur.accEnd = Math.max(cur.accEnd, cur.preroll.ms);', 'var mvUp = mvUpcomingNow(now);',
  'mvBubbleStart(mvUp.item, false, mvUp);', "host.buildFit = cur.preroll ? {ms: cur.preroll.ms, from: existing ? sheet.tables.length : 0} : null;"]) {
  assert(src.includes(needle), 'the card engine: ' + needle);
}
console.log('reply-gap buildup contract: ok (' + tables + ' tables on ' + pageSpecs.length + ' turns)');
