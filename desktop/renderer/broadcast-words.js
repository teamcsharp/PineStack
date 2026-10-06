/* Counts only confirmed broadcast speech; repeated snapshots do not add counts. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PineBroadcastWords=api;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 const stop=new Set('the and that this with from have your you are for was were has had but not all can its our their they them into just then than what when where who how why will would could should been being about there here some said says say did does doing very more much also only really like know now get got one two any out off over back want need going think dont cant thats these those through which'.split(' '));
 function create(){const seen=new Map(),words=new Map();let total=0;
  function ingest(rows,now=Date.now()/1000){let changed=false;for(const row of rows||[]){if(!row||!(row.heard_ack_at||['box','stream','both'].includes(row.aired))||['chat','marker','image_analysis','song_analysis','drop','hangup','sfx'].includes(row.kind))continue;
   const at=Number(row.air_at||row.ts||0);if(at>now)continue;const id=String(row.id||row.line_id||'')||[at,row.who,row.text].join(':');if(seen.has(id))continue;seen.set(id,at);changed=true;
   for(const raw of String(row.text||'').toLowerCase().match(/[\p{L}][\p{L}\p{N}'-]*/gu)||[]){const word=raw.replace(/['-]+$/g,'');if(word.length<3||stop.has(word))continue;const old=words.get(word)||{word,count:0,last:0};old.count++;old.last=Math.max(old.last,at);words.set(word,old);total++;}
  }if(seen.size>20000)for(const [id,at]of seen){if(at<now-172860)seen.delete(id);}return changed;}
  function ranked(limit=240,now=Date.now()/1000){return [...words.values()].map(w=>({...w,recency:Math.exp(-Math.max(0,now-w.last)/1800)})).sort((a,b)=>(b.count+8*b.recency)-(a.count+8*a.recency)||a.word.localeCompare(b.word)).slice(0,limit);}
  return {ingest,ranked,state:()=>({distinct:words.size,total,lines:seen.size})};
 }
 return {create};
});
