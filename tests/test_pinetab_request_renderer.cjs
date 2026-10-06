'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function node(){return {hidden:false,childNodes:[],classList:{toggle(){},add(){},contains(){return false;}},setAttribute(){},addEventListener(){},appendChild(n){this.childNodes.push(n);},removeChild(n){this.childNodes.splice(this.childNodes.indexOf(n),1);},scrollTop:0,scrollHeight:0};}
(async()=>{
 let record={open:true,state:'asked',ask_at:1}, modes=[],repairs=[],intervals=[],brokenReplies=0;
 const api={readConfig:()=>({baseUrl:'http://station'}),pinetabCheck:async()=>({wanted:'aaaaaaaaaaaa'}),pinetabUpdate:async mode=>{modes.push(mode);return mode==='prepare'?{ok:true,ready:true}:{ok:true,after:'latest',relaunched:true};},pinetabAction:async name=>{repairs.push(name);return {ok:true};}};
 const root={pineDesktop:api,setInterval:(f,ms)=>intervals.push({f,ms}),setTimeout,clearTimeout};
 const ctx={window:root,document:{getElementById:()=>node(),createElement:()=>node(),body:node()},Promise,Date,JSON,AbortController,fetch:async(_,opts)=>{
  if(opts&&opts.body){const body=JSON.parse(opts.body);record={...record,...body};if(body.state==='running'&&brokenReplies===0){brokenReplies++;return {ok:true,json:async()=>{throw new Error('interrupted JSON response');}};}}
  return {ok:true,json:async()=>({...record})};
 }};
 vm.runInNewContext(fs.readFileSync(require.resolve('../desktop/renderer/pinetab-button.js'),'utf8'),ctx);
 async function drain(){for(let i=0;i<15;i++)await new Promise(setImmediate);}
 await drain();assert.deepEqual(modes,['prepare']);assert.equal(brokenReplies,1);assert.equal(record.state,'ready','final reports recover after a broken JSON response');assert.deepEqual(repairs,[],'prepare must not restart the tablet');assert.equal(record.wanted,'aaaaaaaaaaaa','desktop publishes the source version');
 const watch=intervals.find(i=>i.ms===5000).f;
 watch();await drain();assert.deepEqual(modes,['prepare'],'ready waits for second tap');
 record.state='install-requested';watch();await drain();assert.deepEqual(modes,['prepare','install']);assert.equal(record.state,'done');
 watch();await drain();assert.equal(modes.length,2,'completed request not taken twice');
 console.log('Tablet request renderer: prepare, wait for tap, install exactly once passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
