const {test} = require('node:test');
const assert = require('node:assert/strict');
const {create, geometry} = require('../desktop/renderer/lcd-review.js');

const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject}; }
function detail(id = 'cut-a', seq = 12, revision = 3, extra = {}) {
  return {id, event_seq: seq, seq, revision, gate: 'tint', review_status: 'pending', technical: false,
    source: 'The complete original turn about the station clock.',
    candidate: 'The revised turn about the clock and its copper bell.',
    reasons: ['The rewrite changed the original meaning.'], context: {kind: 'banter', marker: 'A', turn: 2}, ...extra};
}
function context() {
  const calls = [], target = {calls, font: '12px sans-serif',
    measureText(text) { return {width: String(text).length * 6.5}; },
  };
  return new Proxy(target, {get(object, key) {
    if (key in object) return object[key];
    return (...args) => {calls.push([key, ...args]);};
  }});
}
function harness(overrides = {}) {
  let clock = 0;
  const reads = [], writes = [], changes = [], closes = [], ctx = context();
  const ui = create({now: () => clock,
    get: async route => {reads.push(route); const id = decodeURIComponent(route.split('/').pop().split('?')[0]); return detail(id);},
    post: async (route, body) => {writes.push({route, body}); return {ok: true, row: detail('cut-a', 12, 4, {review_status: body.action === 'allow' ? 'allowed' : 'kept'}), effect: {status: 'awaiting_recovery'}};},
    onChange: state => changes.push(state), onClose: () => closes.push(true), ...overrides});
  return {ui, reads, writes, changes, closes, ctx,
    tick(ms) {clock += ms;}, draw() {return ui.draw(ctx, 320, 240);},
    async open(ref = {review_id: 'cut-a', review_seq: 12, text: 'Never use display text as identity'}) {
      await ui.open(ref); await settle();
    },
    async arm() {await settle(); ui.draw(ctx, 320, 240); clock += 400; ui.draw(ctx, 320, 240);},
    tap(name) {const box = geometry(320, 240)[name]; return ui.tap(box.x + box.w / 2, box.y + box.h / 2, 320, 240);},
  };
}

test('LCD review binds exact event and revision, and cannot accept the opening double tap', async () => {
  const h = harness(); await h.open();
  assert.deepEqual(h.reads, ['/api/orchestrator/rejections/cut-a?event_seq=12']);
  h.tap('accept'); await settle(); assert.equal(h.writes.length, 0);
  h.draw(); h.tick(349); h.tap('accept'); await settle(); assert.equal(h.writes.length, 0);
  h.tick(2); h.draw(); assert.equal(h.ui.snapshot().armed, true);
  h.tap('accept'); await settle();
  assert.equal(h.writes.length, 1);
  assert.equal(h.writes[0].route, '/api/orchestrator/rejections/cut-a');
  assert.deepEqual(h.writes[0].body, {action: 'allow', expected_revision: 3, expected_event_seq: 12, note: 'LCD review'});
});

test('outside tap closes and consumes the popup without posting or reaching another action', async () => {
  const h = harness(); await h.open(); await h.arm();
  assert.equal(h.ui.tap(200, 58, 320, 240), true);
  assert.equal(h.ui.snapshot().open, false);
  assert.equal(h.closes.length, 1); assert.equal(h.writes.length, 0);
});

test('full detail scrolls both ways and drawing preserves the native 64 by 60 corner', async () => {
  const h = harness({get: async () => detail('cut-a', 12, 3, {
    source: Array.from({length: 40}, (_, i) => `Original sentence number ${i} with its full retained detail.`).join(' '),
    candidate: 'Exact candidate ending with UNIQUE-END-MARKER.',
  })});
  await h.open(); await h.arm();
  assert.ok(h.ui.snapshot().totalLines > 10);
  h.tap('next'); h.draw(); const advanced = h.ui.snapshot().offset; assert.ok(advanced > 0);
  h.tap('previous'); h.draw(); assert.ok(h.ui.snapshot().offset < advanced);
  h.ui.swipe('up'); h.draw(); assert.ok(h.ui.snapshot().offset > 0);
  h.ui.scroll(100000); h.draw();
  assert.ok(h.ui.snapshot().offset < h.ui.snapshot().totalLines);
  h.ui.scroll(-100000); h.draw(); assert.equal(h.ui.snapshot().offset, 0);
  for (const [operation, x, y, w, height] of h.ctx.calls) {
    if (!['fillRect', 'clearRect', 'strokeRect'].includes(operation)) continue;
    assert.ok(!(x < 64 && y < 60 && x + w > 0 && y + height > 0), `${operation} must not erase the native mode button`);
  }
  assert.equal(h.writes.length, 0);
});

test('technical details remain inspectable but only Reject can submit a decision', async () => {
  const h = harness({get: async () => detail('cut-a', 12, 7, {technical: true, reasons: ['The recorded media file is missing.']})});
  await h.open(); await h.arm();
  assert.equal(h.ui.snapshot().canAccept, false);
  assert.equal(h.ui.snapshot().canReject, true);
  h.tap('accept'); await settle(); assert.equal(h.writes.length, 0);
  h.tap('reject'); await settle();
  assert.equal(h.writes.length, 1);
  assert.deepEqual(h.writes[0].body, {action: 'keep', expected_revision: 7, expected_event_seq: 12, note: 'LCD review'});
});

test('a pending vote cannot duplicate or land on a different popup after close and reopen', async () => {
  const pending = deferred(), writes = [];
  const h = harness({post: (route, body) => {writes.push({route, body}); return pending.promise;},
    get: async route => route.includes('cut-b') ? detail('cut-b', 18, 5) : detail()});
  await h.open(); await h.arm(); h.tap('accept'); h.tap('accept'); await settle();
  assert.equal(writes.length, 1); assert.equal(h.ui.snapshot().busy, true);
  h.ui.close(); await h.open({review_id: 'cut-b', review_seq: 18}); await h.arm();
  h.tap('reject'); await settle(); assert.equal(writes.length, 1);
  pending.resolve({ok: true, row: detail('cut-a', 12, 4, {review_status: 'allowed'}), effect: {status: 'awaiting_recovery'}});
  await settle();
  assert.equal(h.ui.snapshot().selectedId, 'cut-b');
  assert.equal(h.ui.snapshot().detail.id, 'cut-b');
  assert.equal(writes[0].route, '/api/orchestrator/rejections/cut-a');
});

test('a slow earlier detail fetch cannot replace the currently selected rejection', async () => {
  const first = deferred();
  const h = harness({get: route => route.includes('cut-a') ? first.promise : Promise.resolve(detail('cut-b', 18, 5))});
  const original = h.ui.open({review_id: 'cut-a', review_seq: 12});
  await h.open({review_id: 'cut-b', review_seq: 18});
  first.resolve(detail()); await original; await settle();
  assert.equal(h.ui.snapshot().selectedId, 'cut-b');
  assert.equal(h.ui.snapshot().detail.id, 'cut-b');
  assert.equal(h.ui.snapshot().revision, 5); assert.equal(h.writes.length, 0);
});

test('missing or invalid review identity is never inferred from visible words', async () => {
  const h = harness(); await h.open({text: 'Looks exactly like a rejected line', gate: 'tint'}); await h.arm();
  h.tap('accept'); h.tap('reject'); await settle();
  assert.equal(h.reads.length, 0); assert.equal(h.writes.length, 0);
  assert.equal(h.ui.snapshot().canAccept, false); assert.equal(h.ui.snapshot().canReject, false);
  assert.ok(h.ui.snapshot().error || h.ui.snapshot().message);
});

test('Why and System tabs expose complete reasons and pipeline evidence without traversing long wording', async () => {
  const h = harness({get: async () => detail('cut-a',12,3,{source:'A long original sentence. '.repeat(100),
    reasons:['UNIQUE-EDITORIAL-REASON'],evaluation:{machine_ok:false,original_check:'UNIQUE-MACHINE-EVIDENCE'},
    system_path:'UNIQUE-WRITING-RECORDING-PATH',effect:{status:'held',say:'UNIQUE-RECOVERY-EFFECT'}})});
  await h.open(); await h.arm(); h.tap('why'); h.draw();
  assert.equal(h.ui.snapshot().section,'why');
  h.ui.scroll(10000);h.draw();
  let ink=h.ctx.calls.filter(row=>row[0]==='fillText').map(row=>String(row[1])).join(' ');
  assert.match(ink,/UNIQUE-EDITORIAL-REASON/);assert.match(ink,/UNIQUE-MACHINE-EVIDENCE/);
  h.tap('system');h.draw();assert.equal(h.ui.snapshot().section,'system');
  for(let i=0;i<8;i++){h.ui.scroll(1);h.draw();}
  ink=h.ctx.calls.filter(row=>row[0]==='fillText').map(row=>String(row[1])).join(' ');
  assert.match(ink,/UNIQUE-WRITING-RECORDING-PATH/);assert.match(ink,/UNIQUE-RECOVERY-EFFECT/);
  assert.equal(h.writes.length,0);
});

test('an old occurrence and a stale vote never switch identity or automatically retry a POST', async () => {
  const old = harness({get:async()=>detail('cut-a',12,9,{occurrence_current:false})});
  await old.open();await old.arm();old.tap('accept');old.tap('reject');await settle();
  assert.equal(old.ui.snapshot().canAccept,false);assert.equal(old.ui.snapshot().canReject,false);assert.equal(old.writes.length,0);
  const writes=[];
  const h=harness({post:async(route,body)=>{writes.push({route,body});throw new Error('HTTP 409: This cut changed');}});
  await h.open();await h.arm();h.tap('accept');await settle();await h.arm();
  h.tap('accept');h.tap('reject');await settle();
  assert.equal(writes.length,1);assert.equal(h.ui.snapshot().selectedId,'cut-a');
  assert.equal(h.ui.snapshot().canAccept,false);assert.equal(h.ui.snapshot().canReject,false);
  assert.match(h.ui.snapshot().message,/changed|updated/i);
});

test('an unconfirmed network vote retries only a GET and then uses the fresh saved revision', async () => {
  let reads=0;const writes=[];
  const h=harness({get:async()=>{reads++;return detail('cut-a',12,reads===1?3:4,{review_status:reads===1?'pending':'allowed'});},
    post:async(route,body)=>{writes.push({route,body});if(writes.length===1)throw new Error('Network connection interrupted');
      return{ok:true,row:detail('cut-a',12,5,{review_status:'kept'}),effect:{status:'kept'}};}});
  await h.open();await h.arm();h.tap('accept');await settle();
  h.tap('accept');await settle();assert.equal(reads,2);assert.equal(writes.length,1);
  assert.equal(h.ui.snapshot().detail.review_status,'allowed');
  h.tap('reject');await settle();assert.equal(writes.length,1,'Reloaded detail must be drawn and armed again');
  await h.arm();h.tap('reject');await settle();
  assert.equal(writes.length,2);assert.equal(writes[1].body.action,'keep');assert.equal(writes[1].body.expected_revision,4);
});

test('a delayed reopen GET cannot roll back a confirmed decision to an older revision', async () => {
  const vote=deferred(),reload=deferred();let reads=0;
  const h=harness({get:()=>++reads===1?Promise.resolve(detail()):reload.promise,post:()=>vote.promise});
  await h.open();await h.arm();h.tap('accept');await settle();h.ui.close();
  const reopened=h.ui.open({review_id:'cut-a',review_seq:12});
  vote.resolve({ok:true,row:detail('cut-a',12,4,{review_status:'allowed'}),effect:{status:'awaiting_recovery'}});await settle();
  reload.resolve(detail('cut-a',12,3));await reopened;await settle();await h.arm();
  assert.equal(h.ui.snapshot().revision,4);assert.equal(h.ui.snapshot().detail.review_status,'allowed');
  assert.equal(h.ui.snapshot().canAccept,false);assert.equal(h.ui.snapshot().canReject,true);
});

test('a backend must confirm the pinned event before any vote is armed', async () => {
  const h=harness({get:async()=>{const row=detail();delete row.event_seq;delete row.seq;return row;}});
  await h.open();await h.arm();h.tap('accept');h.tap('reject');await settle();
  assert.equal(h.writes.length,0);assert.equal(h.ui.snapshot().canAccept,false);assert.equal(h.ui.snapshot().canReject,false);
  assert.match(h.ui.snapshot().error,/confirm|occurrence|event/i);
});
