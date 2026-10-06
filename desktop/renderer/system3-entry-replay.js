(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else{root.PineSystem3EntryReplay=api;if(root.PINE_NATIVE_TOOLS)api.enhance();}})(typeof window==='object'?window:globalThis,function(root){
 'use strict';let active=null,loading=null;
 function composition(conversation,turnId,scope='conversation'){
  const turns=conversation?.turns||[],target=turns.find(t=>t.turn_id===turnId);if(!target)throw Error('No recorded turn is linked to this entry.');
  const indexes=new Map(turns.map(t=>[t.turn_id,Number(t.index)]));
  const events=(conversation.decision_events||[]).filter(e=>{if(!e.turn_id&&Number(e.turn_index)<0)return true;const index=indexes.get(e.turn_id)??Number(e.turn_index);return scope==='line'?e.turn_id===turnId||index===Number(target.index):index>=0&&index<=Number(target.index);});
  return {events,target,scope};
 }
 function node(tag,cls,text){const n=root.document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}
 async function ready(){if(!loading){const base=[...root.document.scripts].find(s=>/system3-entry-replay[.]js/.test(s.src))?.src||root.location.href;
  loading=new Promise((resolve,reject)=>{const css=node('link');css.rel='stylesheet';css.href=new URL('system3-message-tile.css',base).href;root.document.head.append(css);const js=node('script');js.src=new URL('system3-message-tile.js',base).href;js.onload=resolve;js.onerror=reject;root.document.body.append(js);}).catch(e=>{loading=null;throw e;});}await loading;}
 function inspect(element,rows,index,which){
  element.tabIndex=0;element.title='Inspect the recorded roulette';
  const show=()=>{root.document.getElementById('spRrPop')?.remove();const row=rows[index],reel=which==='sub'?row.sub:row.main;if(!reel)return;
   const back=node('div','s3-replay-inspector');back.id='spRrPop';const box=node('section','s3-replay-inspector-box'),close=node('button','','Close');
   close.onclick=()=>back.remove();box.append(node('strong','',row.tableLabel||row.table||row.fam),close,node('p','','RNG '+(reel.dice??'?')+' landed on '+reel.label));
   const list=node('ol');(reel.opts||[]).forEach((text,i)=>list.append(node('li','',text+(i===reel.hit?' (landed)':''))));box.append(list);if(typeof row.prompt==='string')box.append(node('p','',row.prompt));
   back.append(box);back.onclick=e=>{if(e.target===back)back.remove();};back.onkeydown=e=>{if(e.key==='Escape')back.remove();};root.document.body.append(back);close.focus();
  };element.addEventListener('click',show);element.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show();}});
 }
 async function open(entry,anchor,button){
  if(active?.entry.id===entry.id){active.close();return;}active?.close();
  const panel=node('section','s3-entry-rollout'),bar=node('header'),scope=node('select'),restart=node('button','','Replay'),close=node('button','','Close'),host=node('div','s3-entry-rollout-host');
  for(const [value,text]of [['conversation','Conversation up to this line'],['line','Selected line']]){const o=node('option','',text);o.value=value;scope.append(o);}scope.setAttribute('aria-label','Replay scope');
  bar.append(node('strong','','System3 rollout'),scope,restart,close);panel.append(bar,host);anchor.insertAdjacentElement('afterend',panel);button?.setAttribute('aria-expanded','true');host.textContent='Loading recorded System3 composition';
  let dead=false,tile=null,data=null;
  const view={entry,close(){dead=true;tile?.dispose();const popup=root.document.getElementById('spRrPop');if(popup?.classList.contains('s3-replay-inspector'))popup.remove();panel.remove();button?.setAttribute('aria-expanded','false');if(active===view)active=null;},element:panel,state:()=>tile?.state()};active=view;close.onclick=view.close;
  async function play(){
   tile?.dispose();host.replaceChildren();if(dead||!data)return;
   const selected=composition(data.conversation,data.turnId,scope.value),rows=selected.events.map(root.PineSystem3MessageTile.decisionRow).filter(Boolean);
   tile=root.PineSystem3MessageTile.mount(host,{make:node,load:async()=>({answered:true,rows}),wireEntry:inspect,rollBudget:records=>Math.max(6000,records.length*1800),options:{followPlayback:false,mode:'hold',fontSize:13}});
   tile.receive({now:{id:entry.id,text:entry.text},rows:[{id:entry.id,text:entry.text}],station:{paused:false}});
  }
  restart.onclick=()=>play().catch(e=>{host.textContent=e.message;});scope.onchange=restart.onclick;
  try{
   await ready();const origin=await root.pineDesktop.get('/api/system3/origin/'+encodeURIComponent(entry.id));
   const link=(origin.nodes||[]).find(n=>n.node==='conversation'&&n.conversation_id&&n.turn_id);if(!link)throw Error('No recorded System3 conversation is linked to this entry.');
   const conversation=await root.pineDesktop.get('/api/system3/conversation/'+encodeURIComponent(link.conversation_id));if(dead)return;data={conversation,turnId:link.turn_id};await play();
  }catch(e){if(!dead)host.textContent=e.message||String(e);}return view;
 }
 function enhance(){
  const document=root.document;if(document.__system3ReplayEnhancer)return;document.__system3ReplayEnhancer=true;
  const css=node('style');css.textContent='.s3-entry-rollout{background:#111b21;color:#d8e5eb;border:1px solid #3c5864;border-radius:8px;margin:8px 0;padding:10px;font:13px system-ui;--sp-text:#d8e5eb;--sp-muted:#8fa0ad}.s3-entry-rollout>header{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}.s3-entry-rollout>header strong{margin-right:auto}.s3-entry-rollout button,.s3-entry-rollout select{color:#d8e5eb;background:#18262e;border:1px solid #3c5864;border-radius:4px;padding:4px 8px}.s3-entry-rollout .pip-system3-stage{max-height:65vh;overflow:auto}.s3-replay-inspector{position:fixed;inset:0;display:grid;place-items:center;background:#0008;z-index:2147483647}.s3-replay-inspector-box{background:#10191f;color:#d8e5eb;border:1px solid #65c7da;border-radius:10px;padding:16px;width:min(600px,90vw);max-height:80vh;overflow:auto;font:13px system-ui}.s3-replay-inspector-box>button{float:right}.s3-replay-inspector-box li{padding:5px}';document.head.append(css);
  function add(control){
   const row=control.previousElementSibling;if(!row?.matches('.scp-dia:not(.scp-ins)')||!row.id.startsWith('sp-ln-')||control.querySelector('.scp-system3-replay'))return;
   const button=node('button','scp-system3-replay','System3 rollout');button.title='Replay the recorded roulette showing how this entry was composed';button.setAttribute('aria-expanded','false');button.onclick=e=>{e.stopPropagation();open({id:row.id.slice(6),text:row.textContent},control,button);};control.append(button);
  }
  document.querySelectorAll('.scp-ctl').forEach(add);
  new MutationObserver(records=>{if(active&&!active.element.isConnected)active.close();for(const record of records)for(const added of record.addedNodes){if(added.nodeType!==1||added.closest('.s3-entry-rollout'))continue;if(added.matches('.scp-ctl'))add(added);added.querySelectorAll?.('.scp-ctl').forEach(add);}}).observe(document.body,{childList:true,subtree:true});
 }
 return {composition,open,enhance};
});
