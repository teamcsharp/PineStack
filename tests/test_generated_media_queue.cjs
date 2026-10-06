const assert=require('node:assert/strict');
const {MediaQueue,exitChoice,videoPayload}=require('../desktop/renderer/generated-media.js');
async function main(){
 let now=0,id=0;const timers=new Map(),phases=[],shown=[],removed=[];
 const clock={clock:()=>now,set:(fn,ms)=>{timers.set(++id,{fn,at:now+ms});return id;},clear:key=>timers.delete(key)};
 function advance(ms){const end=now+ms;for(;;){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;now=next[1].at;timers.delete(next[0]);next[1].fn();}now=end;}
 const q=new MediaQueue({...clock,present:item=>shown.push(item.id),phase:p=>phases.push(p),remove:item=>removed.push(item.id),random:()=>.1});
 q.enqueue([{id:'image'},{id:'video'},{id:'image'},{id:'stinger'}]);await Promise.resolve();await Promise.resolve();assert.equal(q.state().phase,'develop');assert.deepEqual(shown,['image']);assert.equal(q.state().pending,2);
 advance(600);assert.equal(q.state().phase,'enter');advance(550);assert.equal(q.state().phase,'hold');
 advance(2999);assert.equal(q.state().phase,'hold','stable hold lasts full three seconds');advance(1);assert.equal(q.state().phase,'exit');advance(650);await Promise.resolve();await Promise.resolve();assert.deepEqual(removed,['image']);assert.deepEqual(shown,['image','video']);
 advance(1150);advance(1000);q.pause(true);advance(8000);assert.equal(q.state().phase,'hold','hover and keyboard focus prevent disappearance');assert.equal(q.state().remaining,2000);q.pause(false);advance(1999);assert.equal(q.state().phase,'hold');advance(1);assert.equal(q.state().phase,'exit');
 q.setVisible(false);advance(9000);assert.equal(q.state().phase,'exit','hidden pages keep queued notices');q.setVisible(true);advance(650);await Promise.resolve();await Promise.resolve();assert.deepEqual(shown,['image','video','stinger']);
 q.finish();q.enqueue([{id:'image'},{id:'video'}]);assert.equal(q.state().pending,0,'completed old files never cycle back');
 const modes=new Set(),directions=new Set();for(let a=0;a<4;a++)for(let b=0;b<3;b++){const values=[(a+.1)/4,(b+.1)/3,.2,.8];const exit=exitChoice(()=>values.shift());modes.add(exit.mode);directions.add(exit.direction);if(exit.mode==='linear')assert.equal(exit.rotation,0);else assert.ok(Math.abs(exit.rotation)>=55);}assert.equal(modes.size,3);assert.equal(directions.size,4);
 const img=videoPayload({kind:'image',file:'real.png',prompt_id:'p'},'New shot');assert.equal(img.mode,'frame');assert.equal(img.source,'real.png');assert.equal(img.source_type,'generation');assert.equal(img.air_it,false);
 for(const kind of ['video','audio'])assert.equal(videoPayload({kind,file:'clip.'+kind},'New shot').mode,'reference');
 const previous=videoPayload({kind:'image',file:'real.png'},'Show {goal}',{goal:'a rotary phone',speech:'Buy it',style:'retro',audio_direction:'Music',constraints:'No overlays'});assert.equal(previous.prompt,'Show a rotary phone');assert.equal(previous.speech,'Buy it');assert.equal(previous.h3_brief.constraints,'No overlays');
 console.log('Generated media queue: ordered outputs, exact 3-second hold, hover/focus pause, hidden queue, dedup, all random exits, and H3 history/source payload passed.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
