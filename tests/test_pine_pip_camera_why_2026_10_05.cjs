'use strict';
/* [cam-why] The Pine Cam popup says why, and keeps saying it while it waits (#1582, 2026-10-05).
 * Run on local disk, never from the share:  node --test tests/test_pine_pip_camera_why_2026_10_05.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { create } = require(path.join(__dirname, '..', 'desktop', 'renderer', 'pine-pip-camera-recovery.js'));

function rig(over) {
  const said = [];
  let clock = 1000000;
  const state = { got: { state: 'no-link', fresh: true, ssid: 'H88_5c8e8bddfab1', why: "the camera's network is not being broadcast, or the join failed",
                         source: { pref: 'never', use: 'dongle', ip: '10.89.1.154' }, stream: { class: '' } },
                  doctor: { camera: false, stale: false, verdict: 'the radio is fine - it can see 11 other network(s) - so the camera is out of range or asleep' },
                  posts: [], ...over };
  const controller = create({
    now: () => clock,
    state: () => ({ active: true, cameraOverlay: true, cameraSource: 'pine' }),
    read: async () => state.got, doctor: async () => state.doctor,
    post: async (route) => { state.posts.push(route); return { ok: true }; },
    display: async () => {}, picture: () => false,
    status: (value) => said.push(value.say),
  });
  return { controller, said, state, advance: (ms) => { clock += ms; } };
}

test('a camera whose network is not on the air is named, with what to do', async () => {
  const r = rig();
  await r.controller.tick();                 // inside the grace: reconnecting
  r.advance(10000);
  const got = await r.controller.tick();     // past the grace: nothing to reconnect to
  assert.equal(got.ok, false);
  assert.match(got.say, /H88_5c8e8bddfab1/);
  assert.match(got.say, /not on the air/);
  assert.match(got.say, /Press its Wi-Fi button/);
  assert.deepEqual(r.state.posts, []);       // nothing is posted at a camera that is not there
});

test('the reason stays up while it waits, with the seconds left', async () => {
  const r = rig();
  await r.controller.tick();
  r.advance(10000);
  await r.controller.tick();
  r.advance(3000);
  const waiting = await r.controller.tick();
  assert.equal(waiting.waiting, true);
  assert.match(waiting.say, /not on the air/);
  assert.match(waiting.say, /Checking again in 42 s\./);
  assert.doesNotMatch(waiting.say, /recovery is waiting before retrying/);
  r.advance(30000);
  assert.match((await r.controller.tick()).say, /Checking again in 12 s\./);
});

test('without a doctor reading the station\'s own why is given as a sentence', async () => {
  const r = rig({ doctor: { stale: true } });
  await r.controller.tick();
  r.advance(10000);
  const got = await r.controller.tick();
  assert.equal(got.say, "The camera's network is not being broadcast, or the join failed.");
});

test('a camera that is seen is still reconnected, and a live picture clears the reason', async () => {
  const r = rig({ doctor: { camera: true, stale: false } });
  await r.controller.tick();
  r.advance(10000);
  const got = await r.controller.tick();
  assert.deepEqual(r.state.posts, ['/api/pinelink/connect']);
  assert.match(got.say, /reconnected/);
  const idle = rig();
  await idle.controller.tick(); idle.advance(10000); await idle.controller.tick();
  assert.equal(idle.controller.cancel().say, '');
  idle.advance(50000);                       // past the wait the first fault set
  await idle.controller.tick(); idle.advance(10000); await idle.controller.tick(); idle.advance(3000);
  assert.match((await idle.controller.tick()).say, /Checking again in/);   // a new fault earns its own reason
});
