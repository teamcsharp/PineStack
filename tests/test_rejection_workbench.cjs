const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/rejection-review.js'), 'utf8');
const modulePromise = import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

test('review detail URL pins the precise occurrence and safely encodes the record identity', async () => {
  const {reviewDetailPath} = await modulePromise;
  assert.equal(reviewDetailPath('cut/one?two', 42), '/api/orchestrator/rejections/cut%2Fone%3Ftwo?event_seq=42');
  assert.equal(reviewDetailPath('cut-one', null), '/api/orchestrator/rejections/cut-one');
});

test('occurrence extraction rejects invalid identities and preserves explicit historical event sequence', async () => {
  const {reviewOccurrence} = await modulePromise;
  assert.equal(reviewOccurrence({event_seq:12, seq:15}), 12);
  assert.equal(reviewOccurrence({review_seq:12}), 12);
  assert.equal(reviewOccurrence({seq:15}), 15);
  for (const event_seq of [undefined, null, 0, -1, 1.5, 'wrong', Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(reviewOccurrence({event_seq}), null);
  }
});

test('only pending work is polled; failed and expired requests require an explicit new attempt', async () => {
  const {workbenchPending} = await modulePromise;
  for (const status of ['pending','queued','running','applying']) assert.equal(workbenchPending({status}), true);
  for (const status of ['completed','failed','lease_expired','expired','cancelled']) assert.equal(workbenchPending({status}), false);
  assert.equal(workbenchPending({status:'pending',lease_expired:true}), false);
  assert.equal(workbenchPending(null), false);
});

test('saved evidence list accepts paged entries without inventing omitted content', async () => {
  const {workbenchItems} = await modulePromise;
  const items = [{prompt:'complete captured request',response:'complete recorded result'}];
  assert.deepEqual(workbenchItems({items,has_more:true}),items);
  assert.deepEqual(workbenchItems(items),items);
  assert.deepEqual(workbenchItems({available:false,note:'not captured'}),[]);
});
