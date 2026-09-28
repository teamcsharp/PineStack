// [changelog-cache] The panel says how current its saved history is.
const assert = require('node:assert/strict');
const test = require('node:test');

global.window = global;
const changelog = require('../desktop/renderer/changelog.js');

test('the header names the count and the as-of time of the saved history', () => {
  assert.equal(changelog.countLine({total: 839, as_of_label: '09-28-26 / 2:15 AM CST'}),
    '839 committed changes · as of 09-28-26 / 2:15 AM CST');
  assert.equal(changelog.countLine({total: 3}), '3 committed changes');
  assert.equal(changelog.countLine({total: 0, as_of_label: ''}), '');
  assert.equal(changelog.countLine(null), '');
});

test('the earlier panel contract still holds', () => {
  assert.equal(typeof changelog.open, 'function');
  assert.equal(typeof changelog.close, 'function');
  assert.equal(changelog.isMajor({file_count: 4}), true);
});
