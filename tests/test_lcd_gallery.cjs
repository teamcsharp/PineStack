const {test} = require('node:test');
const assert = require('node:assert/strict');
const {create} = require('../desktop/renderer/lcd-gallery.js');

const settle = () => new Promise(resolve => setImmediate(resolve));
const rows = (...files) => ({generations: files.map(file => ({kind: 'image', status: 'done', files: [file]}))});
function context() {
  const state = [], calls = [];
  return {calls, globalAlpha: 1, globalCompositeOperation: 'source-over', fillStyle: '',
    save() { state.push([this.globalAlpha, this.globalCompositeOperation, this.fillStyle]); },
    restore() { [this.globalAlpha, this.globalCompositeOperation, this.fillStyle] = state.pop(); },
    beginPath() {}, rect(...args) { calls.push(['rect', ...args]); }, clip() {},
    fillRect(...args) { calls.push(['fill', ...args]); },
    drawImage(image, ...args) { assert.equal(image.closed, false); calls.push(['image', image.id, ...args, this.globalAlpha, this.globalCompositeOperation]); },
  };
}
function harness(payload = rows('a.png', 'b.png', 'c.png'), overrides = {}) {
  let clock = 0, calls = 0, active = 0, peak = 0, live = 0, peakLive = 0;
  const loaded = [], images = [], ctx = context();
  const gallery = create({random: () => .99, now: () => clock,
    get: async route => { assert.equal(route, '/api/generations?limit=1000'); calls++; return payload; },
    loadImage: async route => {
      assert.ok(route.startsWith('/api/generations/image/')); active++; peak = Math.max(peak, active);
      loaded.push(route); await settle(); active--; return decodeURIComponent(route.split('/').pop());
    },
    decodeImage: async (id, size) => {
      assert.ok(size.width <= 320 && size.height <= 320);
      live++; peakLive = Math.max(peakLive, live);
      const image = {id, width: 100, height: 200, closed: false,
        close() { assert.equal(this.closed, false); this.closed = true; live--; }};
      images.push(image); return image;
    }, ...overrides});
  return {gallery, ctx, loaded, images,
    async ready() { for (let i = 0; i < 5; i++) await settle(); },
    draw(at = clock, options) { clock = at; return gallery.draw(ctx, 320, 240, clock, options); },
    get calls() { return calls; }, get peak() { return peak; }, get live() { return live; }, get peakLive() { return peakLive; },
  };
}

test('gallery uses image records, excludes paper/video/path traversal, and retains regenerated Gazette-tag pictures', async () => {
  const h = harness({generations: [
    {kind: 'paper', files: ['modern.png']}, {model: 'gazette', files: ['model.jpg']},
    {tags: 'gazette old', files: ['gazette-2026-09-07-01.png']},
    {tags: 'gazette old regenerated', kind: 'image', files: ['regenerated.png']},
    {files: ['second.webp', 'second.webp', 'video.mp4', 'video.webm', '../outside.png', 'sub/file.png', 'a\\b.png', 'null\u0000.png']},
    {files: ['third.JPG']}, null,
  ]});
  assert.equal(h.draw().state, 'loading'); await h.ready();
  const seen = [h.draw().imageId];
  for (let i = 0; i < 2; i++) {
    h.gallery.next(); h.draw(i * 2000 + 1); h.draw(i * 2000 + 1201); await h.ready(); seen.push(h.draw().imageId);
  }
  assert.equal(h.draw().total, 3);
  assert.deepEqual(seen, ['regenerated.png', 'second.webp', 'third.JPG']);
  assert.ok(h.loaded.every(url => /(?:regenerated\.png|second\.webp|third\.JPG)$/.test(url)));
  h.gallery.destroy(); assert.equal(h.live, 0);
});

test('prefetch is serial, holds only two decoded images, and closes evicted and destroyed images', async () => {
  const h = harness(); h.draw(); await h.ready();
  assert.equal(h.loaded.length, 2); assert.equal(h.live, 2);
  h.draw(); h.gallery.next(); h.draw(100); h.draw(1300); await h.ready();
  assert.equal(h.images[0].closed, true); assert.equal(h.live, 2);
  assert.equal(h.peak, 1); assert.equal(h.peakLive, 2);
  h.gallery.destroy(); assert.equal(h.live, 0);
});

test('a shuffled cycle shows every photo without immediate repeats and varies transition effects', async () => {
  const h = harness(rows('a.png', 'b.png', 'c.png'), {random: () => 0});
  h.draw(); await h.ready(); let result = h.draw();
  const seen = [result.imageId], effects = [];
  for (let i = 0; i < 5; i++) {
    h.gallery.next(); result = h.draw(i * 2000 + 10); effects.push(result.transition);
    result = h.draw(i * 2000 + 1210); seen.push(result.imageId); await h.ready();
  }
  assert.equal(new Set(seen.slice(0, 3)).size, 3);
  for (let i = 1; i < seen.length; i++) assert.notEqual(seen[i], seen[i - 1]);
  for (let i = 1; i < effects.length; i++) assert.notEqual(effects[i], effects[i - 1]);
  h.gallery.destroy();
});

test('static paint keys stay stable, timed transitions change them, and drawer pause freezes progress', async () => {
  const h = harness(); h.draw(); await h.ready();
  const first = h.draw(0);
  assert.equal(h.draw(4000).paintKey, first.paintKey);
  h.gallery.next(); const started = h.draw(4100);
  assert.equal(started.transitioning, true);
  const partial = h.draw(4400); assert.notEqual(partial.paintKey, started.paintKey);
  assert.equal(h.draw(4500, {paused: true}).paintKey, partial.paintKey);
  assert.equal(h.draw(50000, {paused: true}).paintKey, partial.paintKey);
  assert.equal(h.draw(50100).paintKey, partial.paintKey);
  assert.equal(h.draw(50999).imageId, first.imageId);
  assert.notEqual(h.draw(51000).imageId, first.imageId);
  assert.equal(h.ctx.globalAlpha, 1); assert.equal(h.ctx.globalCompositeOperation, 'source-over');
  h.gallery.destroy();
});

test('an inactive view returns through at most one transition and a newly loaded image gets a full first hold', async () => {
  const h = harness(); h.draw(); await h.ready();
  const first = h.draw(30000); assert.equal(first.transitioning, false);
  assert.equal(h.draw(37000).paintKey, first.paintKey);
  assert.equal(h.draw(38000).transitioning, true);
  const returned = h.draw(3600000);
  assert.equal(returned.transitioning, false); assert.notEqual(returned.imageId, first.imageId);
  await h.ready(); assert.equal(h.draw(3600000).paintKey, returned.paintKey);
  h.gallery.destroy();
});

test('failed images wait before trying another and never retry hot; a current image survives errors', async () => {
  const attempted = [];
  const h = harness(rows('broken.png', 'good.png', 'later.png'), {loadImage: async url => {
    const name = url.split('/').pop(); attempted.push(name);
    if (name !== 'good.png') throw new Error('Missing photo'); return name;
  }});
  h.draw(); await h.ready(); assert.equal(h.draw().state, 'error');
  for (let i = 0; i < 100; i++) h.draw(100); await h.ready();
  assert.deepEqual(attempted, ['broken.png']);
  h.draw(250); await h.ready(); const good = h.draw(250);
  assert.equal(good.imageId, 'good.png'); assert.equal(good.state, 'ready');
  h.draw(1000); await h.ready();
  assert.equal(h.draw(59000).imageId, 'good.png');
  assert.equal(attempted.filter(name => name === 'broken.png').length, 1);
  assert.equal(attempted.filter(name => name === 'later.png').length, 1);
  h.gallery.destroy();
});

test('catalogue refreshes coalesce for sixty seconds and failure preserves the visible photo', async () => {
  let requests = 0;
  const h = harness(undefined, {get: async () => { if (++requests > 1) throw new Error('Station temporarily unavailable'); return rows('only.png'); }});
  h.draw(); for (let i = 0; i < 10; i++) h.gallery.refresh(); await h.ready();
  const first = h.draw(); assert.equal(first.total, 1);
  h.gallery.next(); assert.equal(h.draw(59000).transitioning, false); assert.equal(requests, 1);
  h.draw(60000); await h.ready();
  const failed = h.draw(60000); assert.equal(requests, 2);
  assert.equal(failed.imageId, first.imageId); assert.equal(failed.paintKey, first.paintKey);
  assert.equal(failed.state, 'ready'); assert.match(failed.error, /temporarily/);
  h.gallery.destroy();
});

test('empty and failed catalogues report honestly, and late decode after teardown closes its bitmap', async () => {
  const empty = harness(rows()); empty.draw(); await empty.ready(); assert.equal(empty.draw().state, 'empty'); empty.gallery.destroy();
  const failed = harness(undefined, {get: async () => { throw new Error('Offline'); }});
  failed.draw(); await failed.ready(); assert.equal(failed.draw().state, 'error'); failed.gallery.destroy();
  let finish, closed = 0;
  const h = harness(rows('a.png'), {decodeImage: () => new Promise(resolve => { finish = resolve; })});
  h.draw(); await h.ready(); h.gallery.destroy();
  finish({width: 320, height: 240, close() { closed++; }}); await h.ready(); assert.equal(closed, 1);
});

test('image-only rendering contains portraits without text and restores the caller canvas state', async () => {
  const h = harness(rows('portrait.png')); h.draw(); await h.ready(); h.ctx.calls.length = 0;
  h.draw();
  assert.deepEqual(h.ctx.calls.find(call => call[0] === 'image').slice(0, 6), ['image', 'portrait.png', 100, 0, 120, 240]);
  assert.ok(h.ctx.calls.some(call => call[0] === 'fill' && call[3] === 320 && call[4] === 240));
  assert.equal(h.ctx.globalAlpha, 1); h.gallery.destroy();
});
