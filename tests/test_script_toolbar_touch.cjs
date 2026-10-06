'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../desktop/renderer/script-page.js'), 'utf8');
const fn = source.slice(source.indexOf('  function toolbarTouch('), source.indexOf('  function bandController('));
const listeners = {}, bubbles = [];
let under, capture = null;
function button(label) {
  const classes = new Set();
  return {title: label, disabled:false, hidden:false, clicks:0,
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)},
    closest:()=>under, querySelector:()=>null, getAttribute:()=>label,
    focus(){}, click(){this.clicks++;}, classes};
}
const a=button('History'), b=button('Messenger');
const toolbar={contains:n=>n===a||n===b, addEventListener:(n,f)=>listeners[n]=f,
  setPointerCapture:id=>capture=id, hasPointerCapture:id=>capture===id, releasePointerCapture:()=>{capture=null;}};
const context={root:{innerWidth:800},Date,document:{elementFromPoint:()=>under,body:{appendChild:n=>bubbles.push(n)}},
  make:()=>({style:{},setAttribute(){},appendChild(){},remove(){this.removed=true;}})};
vm.createContext(context);vm.runInContext(fn+';toolbarTouch',context)(toolbar);
function event(){return {pointerId:1,button:0,clientX:200,clientY:150,preventDefault(){},stopPropagation(){}};}
under=a;listeners.pointerdown(event());assert.equal(a.clicks,0);assert.ok(a.classes.has('sp-tool-peek'));
under=b;listeners.pointermove(event());assert.ok(!a.classes.has('sp-tool-peek'));assert.ok(b.classes.has('sp-tool-peek'));
listeners.pointerup(event());assert.equal(a.clicks,0);assert.equal(b.clicks,1);assert.equal(capture,null);assert.ok(bubbles.every(n=>n.removed));
listeners.pointerup(event());assert.equal(b.clicks,1,'release selects only once');
under=a;listeners.pointerdown(event());listeners.pointercancel(event());assert.equal(a.clicks,0,'cancel does not select');
under=a;listeners.pointerdown(event());under=null;listeners.pointerup(event());assert.equal(a.clicks,0,'release outside cancels');
b.disabled=true;under=b;listeners.pointerdown(event());assert.equal(capture,null,'disabled control excluded');
console.log('Script toolbar slide selection: passed');
