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
  assert.match(css, /\.sp-msg\.sp-msg-render/);
  assert.match(css, /\.sp-msg-render \.sp-msg-marquee/);
});
