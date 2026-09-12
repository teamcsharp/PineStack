const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'renderer.js'), 'utf8');
const start = source.indexOf('function paintBoxVolumeOwner(routing) {');
const end = source.indexOf('/* #979:', start);
assert.ok(start >= 0 && end > start);
const box = {dataset: {}, parentElement: {}, checked: true, disabled: false};
const sent = [];
const context = vm.createContext({document: {getElementById: () => box, activeElement: null},
  api: {post: (url, body) => { sent.push({url, body}); return Promise.resolve({}); }},
  noteRouteOk() {}, noteRouteError() {}});
vm.runInContext(source.slice(start, end), context);
context.paintBoxVolumeOwner({voice_device: 'nabu', music_control: true});
assert.equal(box.disabled, true);
assert.equal(box.checked, false, 'an older saved opt-in must not look active on Nabu');
box.checked = true;
box.onchange();
assert.equal(box.checked, false);
assert.equal(sent.length, 0, 'disabled control cannot enable automatic Nabu resets');
assert.match(box.parentElement.title, /physical dial/);
context.paintBoxVolumeOwner({voice_device: 'pine', music_control: false});
assert.equal(box.disabled, false);
box.checked = true;
box.onchange();
assert.equal(sent.length, 1, 'other speakers retain their deliberate opt-in control');
assert.equal(sent[0].body.music_control, true);
console.log('Nabu volume ownership UI checks passed');
