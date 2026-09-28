// [cast-names] the views' one answer to "what is he called": pineCastName in
// desktop/renderer/sampler-feed.js reads dj_names off the shared /api/dj
// poll, and says Dill / Skip / Sam before the first poll lands. Run: node --test
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function feed(state) {
  const ctx = {console, Date, setInterval: () => 1, clearInterval: () => {}};
  ctx.globalThis = ctx;
  ctx.window = ctx;
  ctx.pineDesktop = {get: async () => state};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(
    path.join(__dirname, '..', 'desktop', 'renderer', 'sampler-feed.js'), 'utf8'), ctx);
  return ctx;
}

test('before the first poll: the station cast', () => {
  const c = feed({}).pineCastName;
  assert.deepEqual([c('host'), c('dj'), c('cohost'), c('sfx'), c('drop'), c('sfxguy')],
    ['Dill', 'Dill', 'Skip', 'Sam', 'Sam', 'Sam']);
  assert.equal(c('third', 'Third seat'), 'Third seat');
  assert.equal(c('caller'), '');
});

test('after a poll: the names the station answers', async () => {
  const ctx = feed({dj_names: {host: 'Rex', cohost: 'Moe', sfx: 'Zed', third: '', guest: 'Ann'}});
  await ctx.PineStationFeed.refresh();
  const c = ctx.pineCastName;
  assert.deepEqual([c('host'), c('dj'), c('cohost'), c('drop'), c('sfxguy')],
    ['Rex', 'Rex', 'Moe', 'Zed', 'Zed']);
  assert.equal(c('third', 'Third seat'), 'Ann', 'the guest fills the third seat');
  assert.equal(ctx.PineStationFeed.castName('sfx'), 'Zed');
});
