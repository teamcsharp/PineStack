const {test} = require('node:test');
const assert = require('node:assert/strict');
const diagnostics = require('../desktop/renderer/script-diagnostics.js');

function sample(at, extra = {}) {
  return {at_ms: at, highlight_id: 'shared-prefix-line-one', active_id: 'shared-prefix-line-one',
    document_revision: 'r1', element_index: 20, block: 1, ord: 0,
    scroll_top_px: 100, lit_top_px: 20, follow: true, paused: false,
    audio: {source: 'bridge', file: 'clip-one.wav', position_s: at / 1000}, ...extra};
}

test('playhead evidence reads t, never bridge arrival milliseconds', () => {
  const got = diagnostics.readAudio({t: 2.5, at: 1789443693773, file: 'clip.wav'}, null, 80);
  assert.equal(got.position_s, 2.5);
  assert.equal(got.observed_at_ms, 1789443693773);
  assert.equal(got.source, 'bridge');
});

test('local audio remains a read source without the desktop bridge', () => {
  const got = diagnostics.readAudio(null, {currentTime: 9, currentSrc: 'http://host/media/clip.wav?x=1'}, 50);
  assert.equal(got.position_s, 9); assert.equal(got.file, 'clip.wav'); assert.equal(got.source, 'local');
  assert.equal(diagnostics.readAudio(null, null, 50).source, 'estimated');
  assert.equal(diagnostics.readAudio(null, null, -1).source, 'unavailable');
});

test('local audio state is allowlisted and unavailable bridge state stays explicit', () => {
  const local = diagnostics.readAudio(null, {currentTime: 9, currentSrc: 'http://host/clip.wav', volume: 0.25,
    muted: true, readyState: 3, networkState: 2, buffered: {length: 1, start: () => 0, end: () => 12}, unrelated: 'private'}, -1);
  assert.equal(local.volume, 0.25); assert.equal(local.muted, true); assert.equal(local.ready_state, 3);
  assert.equal(local.network_state, 2); assert.equal(local.buffered_end_s, 12);
  assert.equal(local.player_state_available, true); assert.ok(!('unrelated' in local));
  const bridge = diagnostics.readAudio({t: 2, file: 'clip.wav', at: 1000}, null, -1);
  assert.equal(bridge.player_state_available, false); assert.equal(bridge.muted, null);
});

test('long files retain only nearby cues plus both claimed identities, including wrong-file claims', () => {
  const rows = Array.from({length: 150}, (_, i) => ({id: 'cue-' + i, clip_media: 'long.wav', clip_from: i * 5, clip_until: (i + 1) * 5}));
  rows.push({id: 'wrong-file-active', clip_media: 'old.wav', clip_from: 0, clip_until: 10});
  rows.push({id: 'wrong-file-highlight', clip_media: 'older.wav', clip_from: 0, clip_until: 10});
  const got = diagnostics.selectMappings(rows, {file: 'long.wav', position_s: 502}, 'wrong-file-active', 'wrong-file-highlight');
  assert.equal(got.rows.length, 9); assert.equal(got.total, 152); assert.equal(got.omitted, 143);
  assert.equal(got.matching_file_total, 150);
  assert.deepEqual(got.rows.map(r => r.id), ['wrong-file-active', 'wrong-file-highlight', ...Array.from({length: 7}, (_, i) => 'cue-' + (97 + i))]);
  assert.equal(rows[0].id, 'cue-0', 'selection does not reorder the feed');
});

test('unlit context follows the active line, then the visible page instead of the old hour', () => {
  assert.equal(diagnostics.contextIndex(500, 900, 1200, 2000), 500);
  assert.equal(diagnostics.contextIndex(-1, 900, 1200, 2000), 900);
  assert.equal(diagnostics.contextIndex(-1, -1, 1200, 2000), 1200);
  assert.equal(diagnostics.contextIndex(-1, -1, -1, 2000), -1);
  assert.equal(diagnostics.contextIndex(-1, 2500, 1200, 2000), 1200);
});

test('normal progress coalesces without losing measured endpoints', () => {
  const rec = diagnostics.createRecorder();
  for (let at = 0; at <= 5000; at += 250) rec.observe(sample(at));
  const got = rec.capture(5000, 'tap', 'incident');
  assert.equal(got.events.length, 1); assert.equal(got.events[0].samples, 21);
  assert.equal(got.events[0].audio.position_start_s, 0);
  assert.equal(got.events[0].audio.position_end_s, 5);
  assert.ok(!JSON.stringify(got).includes('_points'));
});

test('line, file, source, seek and document changes survive coalescing', () => {
  const rec = diagnostics.createRecorder();
  rec.observe(sample(10000));
  rec.observe(sample(10250, {highlight_id: 'shared-prefix-line-two'}));
  rec.observe(sample(10500, {document_revision: 'r2', element_index: 19}));
  rec.observe(sample(10750, {audio: {source: 'bridge', file: 'clip-two.wav', position_s: 0}}));
  rec.observe(sample(11000, {audio: {source: 'estimated', file: '', position_s: 11}}));
  rec.observe(sample(11250, {audio: {source: 'estimated', file: '', position_s: 3}}));
  const events = rec.capture(11250, 'tap', 'incident').events;
  assert.equal(events.length, 6);
  assert.equal(events[1].highlight_id, 'shared-prefix-line-two');
  assert.equal(events[2].document_revision, 'r2');
  assert.equal(events[5].audio_discontinuity, true);
});

test('rolling retention and post boundaries preserve exact sample counts', () => {
  const rec = diagnostics.createRecorder();
  for (let at = 0; at <= 70000; at += 250) rec.observe(sample(at));
  const before = rec.capture(70000, 'tap', 'incident');
  assert.equal(before.events[0].first_ms, 10000);
  assert.equal(before.events[0].samples, 241);
  for (let at = 70250; at <= 80000; at += 250) rec.observe(sample(at));
  const after = rec.capture(80000, 'post', 'incident', 70001);
  assert.equal(after.events.length, 1); assert.equal(after.events[0].first_ms, 70250);
  assert.equal(after.events[0].samples, 40); assert.equal(after.events[0].audio.position_start_s, 70.25);
});

test('overlapping taps each retain a full minute and post windows never repeat pre-tap samples', () => {
  const rec = diagnostics.createRecorder();
  for (let at = 0; at <= 60000; at += 250) rec.observe(sample(at));
  const first = rec.capture(60000, 'tap', 'first');
  for (let at = 60250; at <= 61000; at += 250) rec.observe(sample(at));
  const second = rec.capture(61000, 'tap', 'second');
  assert.equal(first.events[0].first_ms, 0); assert.equal(first.events[0].samples, 241);
  assert.equal(second.events[0].first_ms, 1000); assert.equal(second.events[0].samples, 241);
  for (let at = 61250; at <= 70000; at += 250) rec.observe(sample(at));
  const firstPost = rec.capture(70000, 'post', 'first', 60001);
  for (let at = 70250; at <= 71000; at += 250) rec.observe(sample(at));
  const secondPost = rec.capture(71000, 'post', 'second', 61001);
  assert.equal(firstPost.events[0].first_ms, 60250); assert.equal(firstPost.events[0].samples, 40);
  assert.equal(secondPost.events[0].first_ms, 61250); assert.equal(secondPost.events[0].samples, 40);
  assert.equal(first.events[0].last_ms, 60000); assert.equal(second.events[0].last_ms, 61000);
});

test('full IDs stay distinct and text is stored once with explicit truncation', () => {
  const rec = diagnostics.createRecorder();
  const ids = ['12345678-one', '12345678-two'];
  rec.observe(sample(0, {highlight_id: ids[0], active_id: ids[1]}), ids.map(id => ({id, text: 'x'.repeat(300)})));
  const got = rec.capture(0, 'tap', 'incident');
  assert.deepEqual(Object.keys(got.rows), ids);
  assert.equal(got.rows[ids[0]].text.length, 240); assert.equal(got.rows[ids[0]].text_truncated, true);
  assert.equal(got.bounds.truncated_texts, 2);
  assert.ok(!JSON.stringify(got.events).includes('xxxx'));
});

test('context elements are kept under separate identities from heard line candidates', () => {
  const rec = diagnostics.createRecorder(), line = 'full-id', action = 'element:full-id';
  rec.observe(sample(0, {highlight_id: line, active_id: line, snapshot: {nearby: [{id: action}]}}),
    [{id: line, text: 'spoken'}, {id: action, element_id: line, kind: 'action', text: 'music starts'}]);
  const got = rec.capture(0, 'tap', 'incident');
  assert.equal(got.rows[action].text, 'music starts'); assert.equal(got.rows[line].text, 'spoken');
  assert.equal(got.events[0].active_id, line); assert.notEqual(got.events[0].active_id, action);
});

test('capacity loss and missing referenced rows are reported', () => {
  const rec = diagnostics.createRecorder({events_limit: 2, rows_limit: 1});
  for (let n = 0; n < 3; n += 1) rec.observe(sample(n * 250, {highlight_id: 'line-' + n, active_id: 'line-' + n}), [{id: 'line-' + n, text: 'kept'}]);
  const got = rec.capture(500, 'tap', 'incident');
  assert.equal(got.events.length, 2); assert.equal(got.bounds.dropped_events, 1);
  assert.equal(got.bounds.dropped_rows, 2); assert.equal(got.bounds.missing_rows, 1);
});

test('document revision is stable across identical polls and changes with content or order', () => {
  const rows = [{id: 'a', line: 'one', text: 'first'}, {id: 'b', line: 'two', text: 'second'}];
  assert.equal(diagnostics.revision(rows), diagnostics.revision(JSON.parse(JSON.stringify(rows))));
  assert.equal(diagnostics.revision(rows), diagnostics.revision(rows.map(r => ({...r, aired: 'published'}))));
  assert.notEqual(diagnostics.revision(rows), diagnostics.revision(rows.slice().reverse()));
  assert.notEqual(diagnostics.revision(rows), diagnostics.revision([{...rows[0], text: 'revised'}, rows[1]]));
});

test('observing and capturing never mutates callers or prior captures', () => {
  const rec = diagnostics.createRecorder(), row = Object.freeze({id: 'shared-prefix-line-one', text: 'original'});
  const point = Object.freeze(sample(0, {snapshot: {nearby: [{id: row.id}]}}));
  rec.observe(point, [row]); const before = rec.capture(0, 'tap', 'incident');
  rec.observe(sample(250), [{id: row.id, text: 'changed'}]);
  assert.equal(before.rows[row.id].text, 'original');
  assert.equal(before.events[0].last_ms, 0);
});

test('the report posts its tap before requesting an image, then attaches only the post window', async () => {
  const fs = require('node:fs'), vm = require('node:vm');
  const source = fs.readFileSync(require('node:path').join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');
  const start = source.indexOf('  function reportFire('), end = source.indexOf('  function fireVideo(', start);
  const order = [], timers = [], finished = [], captures = [];
  const ctx = {
    reportTurn: 0, Date, Math, String, Promise, Object,
    root: {crypto: {randomUUID: () => 'incident-id'}},
    api: () => ({post: (path, body) => { order.push('post'); assert.equal(body.view.phase, 'tap'); return Promise.resolve({ok: true, id: 99, file: 'data/script_reports/script_unique.md'}); }}),
    reportGather: (phase, incident, since) => { captures.push({phase, since}); return {phase, captured_at_ms: 1000}; },
    reportImage: () => { order.push('image'); return Promise.resolve({image: null, screenshot_error: 'unavailable'}); },
    reportShutter: () => {}, say: () => {},
    finishReport: (name, body) => { finished.push({name, body}); return Promise.resolve({ok: true}); },
    setTimeout: (callback, delay) => { timers.push({callback, delay}); return timers.length; }
  };
  vm.createContext(ctx); vm.runInContext(source.slice(start, end), ctx);
  ctx.reportFire({classList: {add() {}, remove() {}, toggle() {}}}, 'jump');
  assert.deepEqual(order, ['post', 'image']);
  assert.equal(finished.length, 0);
  timers.find(t => t.delay === 10000).callback();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(finished.length, 1); assert.equal(finished[0].name, 'script_unique.md');
  assert.equal(finished[0].body.view.phase, 'post');
  assert.equal(captures[1].since, 1001);
});
