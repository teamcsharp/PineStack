const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const js = fs.readFileSync('desktop/renderer/script-page.js', 'utf8');
const css = fs.readFileSync('desktop/renderer/script-page.css', 'utf8');

test('segment flow editor is duration-aware and has all requested beat types', () => {
  ['news_mention', 'speakerbox_quote', 'random_topic', 'caller',
   'manager_message', 'sfx', 'ad_drop', 'painting_ad', 'product']
    .forEach((type) => assert.match(js, new RegExp("'" + type + "'")));
  assert.match(js, /function itineraryFlowOpen/);
  assert.match(js, /\/api\/schedule\/flow\/suggest/);
  assert.match(js, /\/api\/schedule\/flow\/slot/);
  assert.match(js, /sp-flow-timing/);
  assert.match(css, /\.sp-flow-graph/);
  assert.match(css, /\.sp-flow-timing-fill/);
});

test('render feed names speakers and exposes source-backed script progress', () => {
  assert.match(js, /speaker \+ ' rendering'/);
  assert.match(js, /script_total/);
  assert.match(js, /sp-msg-render-progress/);
  assert.match(js, /function feedSetActiveMarquee/);
  assert.match(js, /feedDress\(line, ev\)/);
  assert.match(css, /\.sp-msg\.sp-msg-render/);
  assert.match(css, /\.sp-msg-marquee\.is-moving\.sp-msg-marquee-active/);
  assert.match(css, /\.sp-msg-render \.sp-msg-marquee/);
});

test('the live single-line route supplies the feed receipt it creates', () => {
  const app = fs.readFileSync('app.py', 'utf8');
  assert.match(app, /if who and not line:\s*line = uuid\.uuid4\(\)\.hex/);
  assert.match(app, /if who and not script_total:\s*script_index, script_total = 1, 1/);
  assert.match(app, /async def speak\([\s\S]*?script_index: int = 0, script_total: int = 0/);
  assert.match(app, /line=line_id, speaker=booth_actor_name\(who, name\),\s*script_index=1, script_total=1/);
  assert.match(app, /who=who, line=line_id, script_index=1, script_total=1/);
});
