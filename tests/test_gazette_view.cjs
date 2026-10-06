const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const view = require('../desktop/renderer/gazette-view.js');
test('published shelf sorts chronologically with extras and unique ids', () => {
  assert.deepEqual(view.issuesOf({editions:[{id:'z',at:3},{id:'a',since:1},{id:'extra',at:2},null,{id:''},{id:'a',at:9}]}).map(x=>x.id), ['a','extra','z']);
  assert.deepEqual(view.issuesOf({}), []);
});
test('top bar scrub reaches every archived issue and clamps beyond the edges', () => {
  assert.equal(view.indexAt(20,20,100,5),0); assert.equal(view.indexAt(120,20,100,5),4);
  assert.equal(view.indexAt(70,20,100,5),2); assert.equal(view.indexAt(-20,20,100,5),0);
  assert.equal(view.indexAt(200,20,100,5),4); assert.equal(view.indexAt(200,20,0,5),0);
  assert.equal(view.indexAt(200,20,100,0),0);
});
test('HTML carries the station base for signed image/audio/reader assets', () => {
  const html=view.documentFor('<!doctype html><html><head><title>Gazette</title></head><body><img src="/image.png"></body></html>','http://station:8096');
  assert(html.includes('<head><base href="http://station:8096/">'));
  assert.equal((html.match(/<base/g)||[]).length,1);
  assert(view.documentFor('<p>Issue</p>','http://station:8096/').includes('href="http://station:8096/"'));
});
test('desktop and tablet load the identical reader before mounting Script', () => {
  const root=path.resolve(__dirname,'..');
  for(const name of ['gazette-view.js','gazette-view.css','script-page.js']) {
    assert.deepEqual(fs.readFileSync(path.join(root,'desktop/renderer',name)),fs.readFileSync(path.join(root,'app/src/main/assets/pine-views',name)));
  }
  const desktop=fs.readFileSync(path.join(root,'desktop/renderer/index.html'),'utf8');
  const tablet=fs.readFileSync(path.join(root,'app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt'),'utf8');
  assert(desktop.indexOf('./gazette-view.js')<desktop.indexOf('./script-page.js'));
  assert(tablet.indexOf('"gazette-view.js"')<tablet.indexOf('"script-page.js"'));
  assert(desktop.includes('./gazette-view.css')); assert(tablet.includes('"gazette-view.css"'));
});
