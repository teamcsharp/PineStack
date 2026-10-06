'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../desktop/pip-window.cjs'),'utf8');
function setup(favorites,withTools=true,repairPlayback){
 const handlers=new Map(),opened=[],sent=[];let template;
 const webContents={send:(...args)=>sent.push(args)},window={__pinePip:true,webContents};
 const fakeElectron={screen:{},Menu:{buildFromTemplate(value){template=value;return {popup(){}};}}};
 const module={exports:{}};vm.runInNewContext(source,{module,exports:module.exports,require:name=>{assert.equal(name,'electron');return fakeElectron;},setTimeout,clearTimeout});
 module.exports.install({ipcMain:{handle:(channel,handler)=>handlers.set(channel,handler)},getWindow:()=>window,readConfig:()=>({pip:{popupFavorites:favorites}}),writeConfig:()=>{throw Error('Menu selection must not rewrite preferences');},repairPlayback,...(withTools?{openTools:value=>opened.push(value)}:{})});
 return {template:()=>template,menu:payload=>{handlers.get('pip:menu')({sender:webContents},payload);return template.find(item=>item.label==='Favorites');},opened,sent};
}
test('the first PiP item runs complete playback recovery immediately',()=>{
 let repairs=0;const h=setup([],true,()=>{repairs++;});h.menu();
 assert.equal(h.template()[0].label,'Resolve playback + restore DJs');
 assert.equal(h.template()[1].label,'Troubleshoot station...');
 h.template()[0].click();assert.equal(repairs,1);
 const legacy=setup([],false);legacy.menu();legacy.template()[0].click();
 assert.equal(legacy.sent[0][1],'repair-playback');
});
test('PiP Favorites lists saved tools in order with plain catalog labels and opens their exact IDs',()=>{
 const h=setup(['module:PineCam','scene:graph','module:PineCam']);
 const menu=h.menu({favorites:[{id:'scene:graph',label:'Dialogue Mind'},{id:'module:PineCam',label:'Cam'},{id:'scene:unfavorited',label:'Do not display'}]});
 assert.deepEqual(Array.from(menu.submenu,item=>item.label),['Cam','Dialogue Mind']);
 menu.submenu[1].click();assert.deepEqual(h.opened.map(value=>value.id),['scene:graph']);
 assert(!menu.submenu.some(item=>item.label.startsWith('\u2605')));
});
test('Favorites uses a disabled empty-state entry and readable labels for late catalog items',()=>{
 const empty=setup([]).menu();assert.equal(empty.submenu.length,1);assert.equal(empty.submenu[0].enabled,false);
 const late=setup(['module:PineFlowChart']).menu({favorites:[{id:'module:PineFlowChart',label:null}]});assert.equal(late.submenu[0].label,'Flow Chart');
});
test('favorite selection falls back to a renderer action with the saved ID',()=>{
 const h=setup(['view:books'],false);h.menu({favorites:[{id:'view:books',label:'Book Mode'}]}).submenu[0].click();
 assert.equal(h.sent[0][0],'pip:action');assert.equal(h.sent[0][1].type,'favorite');assert.equal(h.sent[0][1].id,'view:books');
});
