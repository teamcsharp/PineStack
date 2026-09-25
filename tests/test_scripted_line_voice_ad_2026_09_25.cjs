const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const pairs = [
  ['desktop/renderer/script-page.js', 'app/src/main/assets/pine-views/script-page.js'],
  ['desktop/renderer/script-page.css', 'app/src/main/assets/pine-views/script-page.css'],
  ['desktop/renderer/talk-dot.js', 'app/src/main/assets/pine-views/talk-dot.js'],
  ['desktop/renderer/rail.js', 'app/src/main/assets/pine-views/rail.js'],
  ['desktop/renderer/view-chrome.css', 'app/src/main/assets/pine-views/view-chrome.css']
];

test('tablet shares the scripted storyline, ad completion, and talk-control code', () => {
  for (const [desktop, tablet] of pairs) {
    assert.equal(fs.readFileSync(desktop, 'utf8'), fs.readFileSync(tablet, 'utf8'), tablet);
  }
  const graph = fs.readFileSync(pairs[0][0], 'utf8');
  const talk = fs.readFileSync(pairs[2][0], 'utf8');
  const rail = fs.readFileSync(pairs[3][0], 'utf8');
  const css = fs.readFileSync(pairs[4][0], 'utf8');
  assert.match(graph, /'scripted_line'/);
  assert.match(graph, /function orchestratorStoryline/);
  assert.match(graph, /function graphNodes/);
  assert.match(graph, /Interject a node/);
  assert.match(graph, /Orchestrator storyline/);
  assert.match(graph, /SFX scheduled by the orchestrator/);
  assert.match(talk, /function setEnabled/);
  assert.match(talk, /function voiceAdPopup/);
  assert.match(talk, /purpose \|\| ''\) !== 'voice_ad'/);
  assert.match(rail, /pineViewTab-talk/);
  assert.match(css, /touch-action: none/);
  assert.match(css, /\.pine-voice-ad-popup/);
});
