const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ScreenRing}=require('../desktop/screen-ring.cjs');
test('PinePiP export selects its latest continuous run even after expansion',()=>{
  const r=new ScreenRing(), at=Date.now()-20000;
  const p=(i,view)=>({at:at+i*2000,ms:2000,w:800,h:450,view});
  r.pieces=[p(0,'pip'),p(1,'app'),p(2,'transition'),p(3,'pip'),p(4,'pip'),p(5,'app')];
  const cut=r.window(60,0,undefined,'pip');
  assert.equal(cut.ok,true);assert.equal(cut.pieces.length,2);
  assert.equal(cut.pieces[0],r.pieces[3]);assert.equal(cut.pieces[1],r.pieces[4]);
  assert.equal(cut.end,at+10000);assert.equal(cut.seconds,4);assert.equal(cut.clamped,true);
});
test('an ordinary screen buffer cannot be silently exported as PinePiP',()=>{
  const r=new ScreenRing();r.pieces=[{at:Date.now()-2000,ms:2000,w:800,h:450,view:'app'}];
  const cut=r.window(60,0,undefined,'pip');assert.equal(cut.ok,false);
  assert.match(cut.detail,/No PinePiP display/);
});
