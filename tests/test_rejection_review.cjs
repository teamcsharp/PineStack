const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../frontend/rejection-review.js'), 'utf8');
const modulePromise = import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

test('initial rejection snapshot establishes a baseline even though next_after is zero', async () => {
  const {eventCursor} = await modulePromise;
  assert.equal(eventCursor({events: [], next_after: 0, latest_cursor: 987, events_has_more: false}), 987);
});
test('rejection burst cursor acknowledges only delivered events, never unseen server head', async () => {
  const {eventCursor} = await modulePromise;
  assert.equal(eventCursor({events: [{seq: 101},{seq: 150}], next_after: 150, latest_cursor: 350, events_has_more: true}, 100), 150);
  assert.equal(eventCursor({events: [], next_after: 150, latest_cursor: 350, events_has_more: true}, 150), 150);
  assert.equal(eventCursor({events: [{seq: 180}], next_after: null, latest_cursor: 350}, 150), 180);
});
test('stale rejection pages cannot move a saved cursor backwards', async () => {
  const {eventCursor} = await modulePromise;
  assert.equal(eventCursor({next_after: 40, latest_cursor: 80}, 100), 100);
});
test('initial empty store keeps zero until the first real event arrives', async () => {
  const {eventCursor} = await modulePromise;
  const empty = eventCursor({events: [], next_after: 0, latest_cursor: 0, events_has_more: false});
  assert.equal(empty, 0);
  assert.equal(eventCursor({events: [{id:'first',seq:1}], next_after:1, latest_cursor:1, events_has_more:false}, empty), 1);
  assert.equal(eventCursor({events: [{id:'first',seq:1}], next_after:1, latest_cursor:101, events_has_more:true}, empty), 1);
});
// [#1208] THE SMALLEST SHELL THE FRAMING TOUCHES. openDesktopRejectionReview
// no longer walks to the Radio view; it raises the radio section where it
// stands, which means a body class, one <style> in the head and a watcher on a
// timer. The vm context grows exactly those so the two cases below still run
// the real function out of renderer.js rather than a description of it.
function shellStub() {
  const inHead = new Map();
  const classes = new Set();
  const made = () => ({id: '', textContent: '', type: '', onclick: null, style: {}});
  return {
    createElement: made,
    getElementById: (id) => inHead.get(id) || null,
    addEventListener: () => {},
    head: {append: (node) => { if (node && node.id) inHead.set(node.id, node); }},
    body: {
      append: () => {},
      classList: {
        toggle: (name, on) => { if (on) classes.add(name); else classes.delete(name); },
        contains: (name) => classes.has(name)
      }
    }
  };
}

test('[#1208] the desktop review opener raises the review in place and never changes the view', async () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../desktop/renderer/renderer.js'), 'utf8');
  const script = desktop.slice(desktop.indexOf('let desktopRejectionOpenToken = 0;'), desktop.indexOf('function routeKeyFromState('));
  const calls = [], selected = [];
  const document = shellStub();
  const context = {setTimeout, document,
    setInterval: () => 1, clearInterval: () => {},
    selectView: value => selected.push(value),
    $: () => ({executeJavaScript: async (code, gesture) => {calls.push({code,gesture}); return true;}})};
  vm.createContext(context); vm.runInContext(script, context);
  await context.openDesktopRejectionReview('cut-"quoted\\identifier');
  // "Clicking this makes the viewport change when really I just need to pop up
  //  the pop-up that this is related to."
  assert.deepEqual(selected, [],
    'the opener changed the view; the whole point of #1208 is that it must not');
  assert.ok(document.body.classList.contains('pine-review-modal'),
    'the review was not raised over what he was reading');
  assert.equal(calls.length, 1); assert.equal(calls[0].gesture, false);
  const guest = {window: {PineRejectionReview: {open: id => {guest.opened = id;}}}};
  await vm.runInNewContext(calls[0].code, guest);
  assert.equal(guest.opened, 'cut-"quoted\\identifier');
  assert.doesNotMatch(calls[0].code, /\.play\(|\/api\/dj\//);
});

test('desktop notification opener preserves the exact occurrence reference', async () => {
  const desktop = fs.readFileSync(path.join(__dirname, '../desktop/renderer/renderer.js'), 'utf8');
  const script = desktop.slice(desktop.indexOf('let desktopRejectionOpenToken = 0;'), desktop.indexOf('function routeKeyFromState('));
  const calls = [];
  // [#1208] same shell stub: the opener frames the review instead of walking to it.
  const context = {setTimeout,document:shellStub(),setInterval:()=>1,clearInterval:()=>{},
    selectView(){},$:()=>({executeJavaScript:async(code,gesture)=>{calls.push({code,gesture});return true;}})};
  vm.createContext(context);vm.runInContext(script,context);
  await context.openDesktopRejectionReview({id:'cut-quoted"',event_seq:417});
  const guest = {window:{PineRejectionReview:{open:value=>{guest.opened=value;}}}};
  await vm.runInNewContext(calls[0].code,guest);
  assert.deepEqual(JSON.parse(JSON.stringify(guest.opened)),{id:'cut-quoted"',event_seq:417});
  assert.equal(calls[0].gesture,false);
});

// Exercise the real private batch controller with explicit API/storage mocks;
// the Electron fixture owns DOM, focus, policy-switch and layout coverage.
function batchHarness(request, extra = {}) {
  const storage = new Map(), messages = [];
  const start = source.indexOf('  function rememberBatch(');
  const end = source.indexOf('  function dismissNotice(', start);
  assert.ok(start >= 0 && end > start, 'The batch controller is present');
  const context = {crypto, Uint8Array, BASE:'/api/orchestrator/rejections',
    batchKey:'test-batch',batchRequestId:'',batchFeedback:null,mutation:'',
    unreviewed:65,policy:{enabled:true,revision:4},panel:null,dialog:false,detail:null,selected:null,selection:0,
    gate:'audio_duration',status:'pending',rows:new Map([['only-visible-row',{}]]),
    sessionStorage:{setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    say:(_node,text,error)=>messages.push({text,error}),
    label:value=>String(value).replace(/_/g,' '), paintMutations(){},paintPolicy(){},badge(){},
    loadQueue:async()=>{},request,...extra};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  return {context,storage,messages};
}

test('approve current sends one server snapshot UUID regardless of visible filter and blocks duplicate clicks', async () => {
  const calls=[];let finish;
  const {context,storage,messages}=batchHarness(async(path,options)=>{
    calls.push({path,body:JSON.parse(options.body)});
    return new Promise(resolve=>{finish=resolve;});
  });
  const running=context.approveCurrent();
  await context.approveCurrent();
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/orchestrator/rejections/approve-current');
  assert.deepEqual(Object.keys(calls[0].body),['request_id']);
  assert.match(calls[0].body.request_id,/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i);
  assert.equal(context.mutation,'batch');
  assert.equal(storage.get('test-batch'),calls[0].body.request_id);
  finish({ok:true,approved:63,skipped:2,skip_reasons:{technical:1,review_changed:1},
    queued:61,awaiting_recovery:1,needs_context:1,remaining_pending:2,policy:{enabled:true,revision:4}});
  await running;
  assert.equal(context.mutation,'');
  assert.equal(storage.has('test-batch'),false);
  assert.equal(context.unreviewed,2);
  assert.equal(context.policy.enabled,true);
  assert.match(messages.at(-1).text,/Approved 63/);
  assert.match(messages.at(-1).text,/Skipped 2/);
  assert.match(messages.at(-1).text,/1 awaiting recovery/);
  assert.match(messages.at(-1).text,/technical: 1/);
  assert.match(messages.at(-1).text,/future rejections are unchanged/);
});

test('uncertain batch retry keeps its UUID and cannot roll back a newer policy snapshot', async () => {
  const ids=[];let fail=true,reloads=0;
  const {context,storage,messages}=batchHarness(async(_path,options)=>{
    ids.push(JSON.parse(options.body).request_id);
    if(fail){fail=false;throw new Error('Response lost after server commit');}
    return {ok:true,approved:1,skipped:0,remaining_pending:0,policy:{enabled:true,revision:1}};
  });
  await context.approveCurrent();
  assert.match(messages.at(-1).text,/not confirmed/);
  assert.equal(storage.get('test-batch'),ids[0]);
  context.policy={enabled:false,revision:9};
  context.dialog=true;
  context.loadQueue=async()=>{reloads++;context.unreviewed=2;};
  await context.approveCurrent();
  assert.equal(ids.length,2);
  assert.equal(ids[1],ids[0]);
  assert.equal(context.policy.enabled,false);
  assert.equal(context.policy.revision,9);
  assert.equal(context.unreviewed,2);
  assert.equal(reloads,1);
  assert.equal(storage.has('test-batch'),false);
});

test('UUID fallback uses cryptographic bytes and denied browser storage preserves the retry ID', () => {
  const {context}=batchHarness(async()=>({ok:true}),{
    crypto:{getRandomValues:bytes=>{bytes.fill(255);return bytes;}},
    sessionStorage:{setItem(){throw new Error('Storage denied');},removeItem(){throw new Error('Storage denied');}},
  });
  const id=context.newBatchId();
  assert.match(id,/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i);
  context.rememberBatch(id);
  assert.equal(context.batchRequestId,id);
  context.rememberBatch('');
  assert.equal(context.batchRequestId,'');
});
