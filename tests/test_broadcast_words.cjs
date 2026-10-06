const test=require('node:test'),assert=require('node:assert/strict'),{create}=require('../desktop/renderer/broadcast-words.js');
test('broadcast cloud excludes unaired, chat and future words; repeated snapshots do not inflate counts',()=>{
 const m=create(),rows=[{id:'a',aired:'box',air_at:10,text:'Water water repairs bridge'},{id:'b',aired:'none',air_at:11,text:'Draft document'},{id:'c',aired:'stream',kind:'chat',air_at:12,text:'Operator settings'},{id:'d',aired:'box',air_at:50,text:'Future broadcast'}];
 m.ingest(rows,20);m.ingest(rows,20);assert.equal(m.state().total,4);assert.equal(m.ranked(10,20).find(w=>w.word==='water').count,2);assert(!m.ranked().some(w=>['draft','operator','future'].includes(w.word)));
 m.ingest([{id:'e',heard_ack_at:23,air_at:22,text:'Fresh neighbourhood water'}],30);assert.equal(m.state().total,7);assert.equal(m.ranked().find(w=>w.word==='water').count,3);
});
