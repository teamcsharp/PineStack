const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/src/main/assets/pine-views/pine-pip-tablet.js'),'utf8');
function harness(){
 const stored=new Map(),classes=new Set(),calls=[];
 const desktop={widgets:{messages:true,voices:true,music:false},docks:{messages:'top'},order:{messages:1},theme:'plum',layout:{messages:{x:.6,y:.1}},messageTile:{fontSize:12}};
 const root={document:{body:{classList:{add:(...v)=>v.forEach(x=>classes.add(x)),remove:(...v)=>v.forEach(x=>classes.delete(x))}}},pineDesktop:{get:async p=>{calls.push(['get',p]);return {settings:desktop};},post:async(...a)=>{calls.push(['post',...a]);},videoWall:async(...a)=>{calls.push(['wall',...a]);return {on:true};}},PineViewRail:{closeAll:()=>calls.push(['close'])}};
 vm.runInNewContext(source,{window:root,localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)}});
 return {api:root.PinePipTabletApi,root,calls,classes,stored,desktop};
}
test('entry imports desktop appearance without writing desktop config or starting another player',async()=>{
 const h=harness();const state=await h.api.pipEnter();assert.equal(state.theme,'plum');assert.equal(state.active,true);assert(h.classes.has('pine-pip-tablet'));assert.deepEqual(h.calls.filter(c=>c[0]==='wall').map(c=>c[1]),['pip']);assert(!h.calls.some(c=>c[0]==='post'));
});
test('tablet edits merge partial widget preferences, survive re-entry, and leave desktop alone',async()=>{
 const h=harness();await h.api.pipEnter();await h.api.pipUpdate({theme:'amber',widgets:{music:true}});await h.api.pipExit();const state=await h.api.pipEnter();assert.equal(state.theme,'amber');assert.equal(state.widgets.messages,true);assert.equal(state.widgets.music,true);assert.equal(h.desktop.theme,'plum');assert.equal(h.desktop.widgets.music,false);assert(!h.calls.some(c=>c[0]==='post'));
});
test('copy desktop replaces tablet overrides without changing the active view',async()=>{
 const h=harness();await h.api.pipEnter();await h.api.pipUpdate({theme:'amber',layout:{}});const state=await h.root.PinePipTablet.refresh();assert.equal(state.active,true);assert.equal(state.theme,'plum');assert.equal(state.layout.messages.x,.6);
});
test('exit restores compositor and does not close a newly selected rail view',async()=>{
 const h=harness();await h.api.pipEnter();const state=await h.api.pipExit();assert.equal(state.active,false);assert(!h.classes.has('pine-pip-tablet'));assert.equal(h.calls.at(-1)[1],'pip');assert.equal(h.calls.at(-1)[2].on,false);assert(!h.calls.some(c=>c[0]==='close'));
});

test('entry and exit do not mutate state already held by the renderer',async()=>{
 const h=harness();const before=await h.api.pipState();const active=await h.api.pipEnter();assert.equal(before.active,false);assert.notEqual(before,active);await h.api.pipExit();assert.equal(active.active,true);
});
test('layout edits preserve other widgets and support per-widget and full resets',async()=>{
 const h=harness();await h.api.pipEnter();await h.api.pipUpdate({layout:{camera:{s:1.2}}});let state=await h.api.pipUpdate({layout:{camera:{o:.7}}});assert.equal(state.layout.messages.x,.6);assert.equal(state.layout.camera.s,1.2);assert.equal(state.layout.camera.o,.7);
 state=await h.api.pipUpdate({layout:{camera:null}});assert(!state.layout.camera);assert(state.layout.messages);state=await h.api.pipUpdate({layout:null});assert.equal(Object.keys(state.layout).length,0);
});
test('saved tablet preferences remain usable during a station outage',async()=>{
 const h=harness();await h.api.pipEnter();await h.api.pipUpdate({theme:'amber'});await h.api.pipExit();h.root.pineDesktop.get=async()=>{throw Error('offline');};assert.equal((await h.api.pipEnter()).theme,'amber');await assert.rejects(h.root.PinePipTablet.refresh(),/offline/);
});
