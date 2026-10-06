const {test}=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../desktop/renderer/pine-pip-camera-recovery.js');
function fixture(overrides={}){
 const f={clock:1800000000000,pip:{active:true,cameraOverlay:true,cameraSource:'pine'},reading:{state:'dropped',fresh:true,stream:{class:'decode'},source:{pref:'always',use:'tablet'}},picture:false,posts:[],displays:0,doctors:0,statuses:[]};
 const deps={state:()=>f.pip,now:()=>f.clock,read:async()=>f.reading,picture:()=>f.picture,doctor:async()=>{f.doctors++;return {camera:false}},post:async(route,body)=>{f.posts.push({route,body});return {ok:true}},display:async()=>{f.displays++},status:s=>f.statuses.push(s),...overrides};
 f.controller=create(deps);return f;
}
test('corrupt relay waits for normal supervisor recovery, then reconnects the stream without resetting the dongle',async()=>{
 const f=fixture();await f.controller.tick();assert.equal(f.posts.length,0);f.clock+=9000;const got=await f.controller.tick();assert.equal(got.verified,false);assert.equal(got.ok,true);assert.deepEqual(f.posts,[{route:'/api/pinelink/connect',body:{}}]);assert.equal(f.displays,1);assert.equal(f.doctors,0);
});
test('a fresh picture proves recovery; a historical decode fault on a healthy stream never reconnects',async()=>{
 const f=fixture();await f.controller.repair();f.reading={...f.reading,state:'live',fresh:true,frame_age:.2};f.picture=true;const got=await f.controller.tick();assert.equal(got.verified,true);assert.equal(f.controller.state().phase,'live');assert.equal(f.controller.state().attempts,0);assert.equal(f.posts.length,1);
});
test('early recovery avoids any kick and repeated failure is throttled with increasing delay',async()=>{
 const f=fixture();await f.controller.tick();f.reading={state:'live',fresh:true};f.picture=true;f.clock+=3000;await f.controller.tick();assert.equal(f.posts.length,0);
 f.reading={state:'dropped',fresh:true,stream:{class:'decode'}};f.picture=false;await f.controller.tick();f.clock+=9000;await f.controller.tick();for(let i=0;i<5;i++){f.clock+=3000;await f.controller.tick();}assert.equal(f.posts.length,1);
 f.clock+=30000;await f.controller.tick();assert.equal(f.posts.length,2);f.clock+=45000;await f.controller.tick();assert.equal(f.posts.length,2);assert.match(f.controller.state().say,/move the camera closer/);
});
test('healthy station with broken display reconnects only the image',async()=>{
 const f=fixture();f.reading={state:'live',fresh:true,frame_age:.5};await f.controller.repair();assert.equal(f.posts.length,0);assert.equal(f.doctors,0);assert.equal(f.displays,1);
});
test('inactive PiP and tablet front/rear cameras do not trigger Pine Cam repair',async()=>{
 for(const pip of [{active:false,cameraOverlay:true},{active:true,cameraOverlay:false,cameraOnly:false},{active:true,cameraOnly:true,cameraSource:'tab-front'},{active:true,cameraOverlay:true,cameraSource:'tab-rear'}]){const f=fixture();f.pip=pip;await f.controller.repair();assert.equal(f.posts.length,0);assert.equal(f.displays,0);}
});
test('source switch during diagnosis cancels the queued reconnect',async()=>{
 let finish;const f=fixture({read:()=>new Promise(r=>finish=r)});const pending=f.controller.repair();f.pip.cameraSource='tab-front';finish(f.reading);assert.equal((await pending).cancelled,true);assert.equal(f.posts.length,0);
});
test('closing and reopening invalidates an earlier diagnosis',async()=>{
 let finish;const f=fixture({read:()=>new Promise(r=>finish=r)});const pending=f.controller.repair();f.controller.cancel();finish(f.reading);assert.equal((await pending).cancelled,true);assert.equal(f.posts.length,0);
});
test('a camera dismissed during POST stays dismissed',async()=>{
 let finish;const f=fixture({post:()=>new Promise(r=>finish=r)});const pending=f.controller.repair();await new Promise(setImmediate);f.pip.active=false;finish({ok:true});assert.equal((await pending).cancelled,true);assert.equal(f.displays,0);
});
test('only a fresh dead-radio diagnosis resets a dongle; always-tablet never does',async()=>{
 for(const stale of [false,true]){const f=fixture({doctor:async()=>({cure:'reset',stale})});f.reading={state:'no-link',fresh:true,source:{pref:'never',use:'dongle'}};await f.controller.repair();assert.deepEqual(f.posts.map(p=>p.route),stale?[]:['/api/pinelink/reset-radio']);}
 const f=fixture({doctor:async()=>{throw Error('Dongle doctor must not be called')}});f.reading={state:'waiting-tablet',fresh:true,source:{pref:'always',use:'wait',tablet_state:'requesting'}};const got=await f.controller.repair();assert.equal(got.ok,false);assert.equal(f.posts.length,0);assert.match(got.say,/PineTab/);
});
test('a joined tablet with a failed relay can reconnect without changing preferences',async()=>{
 const f=fixture();f.reading={state:'waiting-tablet',fresh:true,source:{pref:'always',use:'wait',tablet_state:'joined',report_at:f.clock/1000}};await f.controller.repair();assert.deepEqual(f.posts.map(p=>p.route),['/api/pinelink/connect']);
});
test('POST failures are honest and rate limited, and unrelated missing hardware is not reset',async()=>{
 const f=fixture({post:async()=>({ok:false,say:'Host bridge unavailable'})});const got=await f.controller.repair();assert.equal(got.ok,false);assert.equal(f.displays,0);assert.match(got.say,/Host bridge/);await f.controller.repair();assert.equal(f.controller.state().attempts,1);
 const off=fixture();off.reading={state:'no-link',fresh:true};await off.controller.repair();assert.equal(off.posts.length,0);
});
test('camera-only recovers too, and stale live frames are not accepted as success',async()=>{
 const f=fixture();f.pip={active:true,cameraOnly:true,cameraSource:'pine'};f.reading={state:'live',fresh:true,frame_age:20};f.picture=true;const got=await f.controller.repair();assert.equal(got.verified,false);assert.equal(f.posts.length,1);
});
