const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/rejection-review.js'),'utf8');
const start=source.indexOf('  function acceptLearning('),end=source.indexOf('  function paintLearning()',start);
assert.ok(start>=0&&end>start);
const data=(revision=3,extra={})=>({ok:true,status:{revision,enabled:false,mode:'strict',automation_paused:false,...extra},history:{items:[]}});
const clone=value=>JSON.parse(JSON.stringify(value));
function harness(request){
 const context={LEARNING:'/api/orchestrator/prompt-learning',disposed:false,mutation:'',
  learning:{data:null,draft:null,dirty:false,loading:false,read:0,feedback:'',error:false},
  get:route=>request(route,{method:'GET'}),request,paintLearning(){},paintMutations(){},label:String};
 vm.createContext(context);vm.runInContext(source.slice(start,end),context);return context;
}
test('loading is GET-only and retains edited settings across saved-status refresh',async()=>{
 const calls=[];let reply=data();const c=harness(async(route,options)=>{calls.push({route,...options});return reply;});
 await c.loadLearning();assert.equal(calls[0].method,'GET');assert.deepEqual(clone(c.learning.draft),{enabled:false,mode:'strict'});
 c.learning.draft={enabled:true,mode:'fluid'};c.learning.dirty=true;reply=data(4);
 await c.loadLearning();assert.equal(c.learning.data.status.revision,4);assert.deepEqual(clone(c.learning.draft),{enabled:true,mode:'fluid'});
 assert.match(c.learning.feedback,/unsaved.*retained/);assert.ok(calls.every(x=>x.method==='GET'));
});
test('explicit save sends the current revision once and shares the global mutation lock',async()=>{
 const calls=[];let finish;const c=harness(async(route,options)=>{calls.push({route,body:JSON.parse(options.body)});return new Promise(resolve=>finish=resolve);});
 c.acceptLearning(data());c.learning.draft={enabled:true,mode:'fluid'};c.learning.dirty=true;
 const pending=c.changeLearning('save');await c.changeLearning('save');await c.changeLearning('refresh');
 assert.equal(calls.length,1);assert.deepEqual(calls[0].body,{expected_revision:3,enabled:true,mode:'fluid'});assert.equal(c.mutation,'learning');
 finish(data(4,{enabled:true,mode:'fluid'}));await pending;
 assert.equal(c.mutation,'');assert.equal(c.learning.dirty,false);assert.match(c.learning.feedback,/Saved revision 4/);
 assert.match(c.learning.feedback,/not replayed/);
});
test('an older GET cannot replace a newer committed revision or its draft',()=>{
 const c=harness(async()=>data());c.acceptLearning(data(9,{mode:'fluid'}));c.acceptLearning(data(4));
 assert.equal(c.learning.data.status.revision,9);assert.equal(c.learning.draft.mode,'fluid');
});
test('lost response reloads committed state and preserves the explicit unsaved draft',async()=>{
 const calls=[];const c=harness(async(route,options)=>{calls.push({route,method:options.method});if(options.method==='POST')throw Error('Response lost after commit');return data(4,{enabled:true,mode:'fluid'});});
 c.acceptLearning(data());c.learning.draft={enabled:true,mode:'fluid'};c.learning.dirty=true;
 await c.changeLearning('save');assert.deepEqual(calls.map(x=>x.method),['POST','GET']);
 assert.equal(c.learning.data.status.revision,4);assert.equal(c.learning.dirty,true);assert.equal(c.learning.draft.mode,'fluid');
 assert.match(c.learning.feedback,/not confirmed.*draft is retained/);assert.equal(c.mutation,'');
});
test('conflict recovery advances the revision but a retry remains an explicit action',async()=>{
 const calls=[];let first=true;const c=harness(async(route,options)=>{calls.push({route,method:options.method,body:options.body&&JSON.parse(options.body)});if(options.method==='GET')return data(8);if(first){first=false;throw Error('Revision conflict');}return data(9,{enabled:true,mode:'fluid'});});
 c.acceptLearning(data());c.learning.draft={enabled:true,mode:'fluid'};c.learning.dirty=true;
 await c.changeLearning('save');assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.equal(c.learning.draft.mode,'fluid');
 await c.changeLearning('save');assert.equal(calls.at(-1).body.expected_revision,8);assert.equal(c.learning.data.status.revision,9);
});
test('rollback pause, resume and observation refresh send only their scoped payloads',async()=>{
 const calls=[];let rev=3;const c=harness(async(route,options)=>{const body=JSON.parse(options.body);calls.push({route,body});return {...data(++rev,{automation_paused:route.endsWith('/rollback')}),observed:17};});
 c.acceptLearning(data());await c.changeLearning('rollback',1);
 assert.deepEqual(calls[0],{route:'/api/orchestrator/prompt-learning/rollback',body:{expected_revision:3,revision:1}});
 assert.equal(c.learning.data.status.automation_paused,true);assert.match(c.learning.feedback,/paused/);
 await c.changeLearning('resume');assert.deepEqual(calls[1].body,{expected_revision:4,resume:true});
 await c.changeLearning('refresh');assert.deepEqual(calls[2],{route:'/api/orchestrator/prompt-learning/refresh',body:{expected_revision:5}});
 assert.match(c.learning.feedback,/Reviewed 17 retained/);
});
test('other mutations and missing loaded revision prevent writes',async()=>{
 let writes=0;const c=harness(async()=>{writes++;return data();});await c.changeLearning('save');assert.equal(writes,0);
 c.acceptLearning(data());c.mutation='decision';await c.changeLearning('save');assert.equal(writes,0);
});
