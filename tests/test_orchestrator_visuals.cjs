const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../desktop/renderer/orchestrator-glass.js'),'utf8');
const window={};vm.runInNewContext(source.slice(source.indexOf('/* Live 3D station overview.')), {window,Promise});
const model=window.PineOrchViz.model;
test('missing metrics stay missing, measured zero stays zero',()=>{
  const rows=model({live:[],waste:{rendered_ahead_seconds:0},pressure:{readable:false,mem_tier:0}},null);
  assert.equal(rows.length,8);assert.equal(rows[0].rows[0].value,0);
  assert.equal(rows[1].rows[0].value,0);assert.equal(rows[1].rows[1].value,null);
  assert.equal(rows[4].rows[0].value,null);assert.equal(model({},null)[0].rows.length,0);
});
test('charts use independent units and the measured history',()=>{
  const rows=model({live:[{label:'Writing'},{label:'Recording'}],rooms:[{name:'Desk',stuck:3}],waste:{classes:[{name:'Banter',count:7}]},visual_history:{readable:true,mode:'active',dialogue:{rows:[{label:'Committed',value:30}],lines:100,conversations:30},outcomes:[{label:'Joy',value:5}],dice:[{label:'1–10',value:2}]}},null);
  assert.equal(rows[0].rows.length,2);assert.equal(rows[2].rows[0].value,3);
  assert.equal(rows[3].rows[0].value,7);assert.equal(rows[5].rows[0].value,30);
  assert.equal(rows[6].rows[0].value,5);assert.equal(rows[7].rows[0].value,2);
  assert.match(rows[5].note,/active/);
});
test('desktop and Android ship identical overview assets',()=>{
  const path=require('node:path');
  for(const ext of ['js','css'])assert.deepEqual(fs.readFileSync(path.join(__dirname,'../desktop/renderer/orchestrator-glass.'+ext)),fs.readFileSync(path.join(__dirname,'../app/src/main/assets/pine-views/orchestrator-glass.'+ext)));
});
