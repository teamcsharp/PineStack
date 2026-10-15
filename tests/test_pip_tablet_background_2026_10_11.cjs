const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
function actual(file,name){
  const source=fs.readFileSync(path.join(__dirname,'../desktop/renderer',file),'utf8');
  const start=source.indexOf('function '+name+'(');
  assert(start>=0);
  let depth=0;
  for(let i=source.indexOf('{',start);i<source.length;i++){
    if(source[i]==='{')depth++;
    if(source[i]==='}'&&--depth===0)return source.slice(start,i+1);
  }
  throw Error('Unterminated '+name);
}
test('background covers loading, steps aside for a visible frame, and returns at clip end',()=>{
  let layouts=0;
  const panel=new Function('layout',`let nativeCovered=false; ${actual('pine-pip.js','nativePicture')}; return {update:nativePicture,covered:()=>nativeCovered};`)(()=>layouts++);
  const frame={on:true,visible:true,playing:'clip',first_frame_id:'clip',frames_rendered:1};
  panel.update({...frame,frames_rendered:0});assert.equal(panel.covered(),false);
  panel.update({...frame,first_frame_id:'previous-clip'});assert.equal(panel.covered(),false);
  panel.update(frame);assert.equal(panel.covered(),true);
  panel.update({...frame,frames_rendered:20});assert.equal(layouts,1);
  panel.update({...frame,on:false});assert.equal(panel.covered(),false);
  panel.update(frame);assert.equal(panel.covered(),true);
  panel.update({...frame,visible:false});assert.equal(panel.covered(),false);
  panel.update(frame);panel.update(null);assert.equal(panel.covered(),false);
});
test('native state reads update the tablet background for both bridge response formats',()=>{
  const seen=[];
  const root={PinePipTabletApi:{},PinePipPanel:{nativePicture:s=>seen.push(s)}};
  const read=new Function('root',actual('sfx-tv.js','wallState')+';return wallState;')(root);
  const on={on:true},off={on:false};
  assert.equal(read(on),on);assert.deepEqual(read(JSON.stringify(off)),off);
  assert.deepEqual(seen,[on,off]);assert.equal(read('not JSON'),null);
  delete root.PinePipTabletApi;read(on);assert.equal(seen.length,2);
});
