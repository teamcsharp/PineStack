const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer',
  'video-editor.js'), 'utf8');
const body = source.slice(source.indexOf('async function deliverToShare('),
  source.indexOf('async function finishSave('));
assert.ok(body.startsWith('async function deliverToShare('));

function harness(states) {
  const calls = [];
  const context = {
    encodeURIComponent,
    Date,
    status(message) { calls.push(['status', message]); },
    exportHold() { return Promise.resolve(); },
    async api(method, url) {
      calls.push([method, url]);
      return method === 'POST' ? {ok: true} : states.shift();
    },
  };
  vm.runInNewContext(body, context);
  return {deliver: context.deliverToShare, calls};
}

test('save requests courier once and waits for verified share delivery', async () => {
  const h = harness([{status: 'not_requested'}, {status: 'pending'},
    {status: 'delivered', path: '\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings\\clip.mp4'}]);
  const delivered = await h.deliver({id: 'abc'});
  assert.equal(delivered.status, 'delivered');
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 1);
  assert.ok(h.calls.some((call) => call[0] === 'status' && call[1].includes('Waiting')));
});

test('an unavailable share never becomes a saved claim or courier request', async () => {
  const h = harness([{status: 'unavailable', error: 'share not mounted'}]);
  await assert.rejects(h.deliver({id: 'abc'}), /share not mounted/);
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 0);
});

test('an already verified export is not queued a second time', async () => {
  const h = harness([{status: 'delivered', path: '\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings\\clip.mp4'}]);
  assert.equal((await h.deliver({id: 'abc'})).status, 'delivered');
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 0);
});

test('a failed courier can be requeued, but only verified delivery succeeds', async () => {
  const h = harness([{status: 'failed'}, {status: 'pending'},
    {status: 'conflict', error: 'different file'}]);
  await assert.rejects(h.deliver({id: 'abc'}), /different file/);
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 1);
});

test('render completion hides the overlay before share delivery', () => {
  const finish = source.slice(source.indexOf('async function finishSave('),
    source.indexOf('async function save('));
  assert.match(finish, /await deliverToShare\(result\)/);
  assert.match(finish, /bridge\.replayKeepEdited/);
  assert.match(finish, /bridge\.saveBytes/);
  assert.match(finish, /A separate device copy was kept/);
  assert.ok(finish.indexOf('await deliverToShare(result)') <
    finish.indexOf("notify('pine-video-editor-export'"));
  assert.match(source, /result\.id = result\.id \|\| id;\s*exportHide\(\)/);
});
