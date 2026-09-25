const assert = require('node:assert/strict');
const test = require('node:test');

global.window = global;
const changelog = require('../desktop/renderer/changelog.js');

test('major changelog changes start at four edited files', () => {
  assert.equal(changelog.isMajor({file_count: 3}), false);
  assert.equal(changelog.isMajor({file_count: 4}), true);
  assert.equal(changelog.isMajor({major: true}), true);
});

test('elapsed telemetry presents unknown and measured work without guessing', () => {
  assert.equal(changelog.elapsed(null), 'not recorded');
  assert.equal(changelog.elapsed(640), '640 ms');
  assert.equal(changelog.elapsed(4300), '4.3 s');
  assert.equal(changelog.elapsed(65000), '1 m 5 s');
});
