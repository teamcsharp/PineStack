/* Completed Comfy media: one real Polaroid at a time, with an owned review window. */
(function(root){
  'use strict';
  const DEVELOP_MS=600, ENTER_MS=550, HOLD_MS=3000, EXIT_MS=650;
  function exitChoice(random=Math.random){
    const directions=['right','left','up','down'],modes=['linear','rotate','mixed'];
    const direction=directions[Math.min(3,Math.floor(random()*4))],mode=modes[Math.min(2,Math.floor(random()*3))];
    return {direction,mode,rotation:mode==='linear'?0:(random()<.5?-1:1)*(55+Math.floor(random()*110))};
  }
  class MediaQueue {
    constructor({clock=Date.now,set=setTimeout,clear=clearTimeout,present=()=>{},phase=()=>{},remove=()=>{},random=Math.random}={}){
      Object.assign(this,{clock,set,clear,present,onPhase:phase,remove,random});this.queue=[];this.seen=new Set();this.active=null;this.timer=null;this.visible=true;this.paused=false;this.remaining=0;
    }
    enqueue(items){for(const item of items||[]){if(!item?.id||this.seen.has(item.id))continue;this.seen.add(item.id);this.queue.push(item);}this.next();}
    next(){if(this.active||!this.visible||!this.queue.length)return;this.active=this.queue.shift();this.paused=false;this.phase='loading';this.onPhase('loading',this.active);const id=this.active.id;Promise.resolve(this.present(this.active)).catch(()=>{}).then(()=>{if(this.active?.id===id)this.enterPhase('develop',DEVELOP_MS);});}
    schedule(ms){this.clear(this.timer);this.timer=null;this.remaining=ms;if(!this.visible||(this.paused&&this.phase==='hold'))return;this.deadline=this.clock()+ms;this.timer=this.set(()=>{this.timer=null;this.remaining=0;this.advance();},ms);}
    enterPhase(phase,ms){this.phase=phase;this.exit=phase==='exit'?exitChoice(this.random):null;this.onPhase(phase,this.active,this.exit);this.schedule(ms);}
    advance(){if(!this.active)return;if(this.phase==='develop')this.enterPhase('enter',ENTER_MS);else if(this.phase==='enter')this.enterPhase('hold',HOLD_MS);else if(this.phase==='hold')this.enterPhase('exit',EXIT_MS);else if(this.phase==='exit')this.finish();}
    finish(){this.clear(this.timer);this.timer=null;if(this.active)this.remove(this.active);this.active=null;this.phase='idle';this.onPhase('idle',null);this.next();}
    pause(on){if(this.paused===!!on)return;this.paused=!!on;if(this.phase!=='hold')return;if(on&&this.timer!==null){this.remaining=Math.max(0,this.deadline-this.clock());this.clear(this.timer);this.timer=null;}else if(!on)this.schedule(this.remaining);}
    setVisible(on){if(this.visible===!!on)return;this.visible=!!on;if(!on&&this.timer!==null){this.remaining=Math.max(0,this.deadline-this.clock());this.clear(this.timer);this.timer=null;}else if(on){if(this.active&&this.phase!=='loading')this.schedule(this.remaining);else this.next();}}
    state(){return {phase:this.phase,active:this.active?.id||'',pending:this.queue.length,paused:this.paused,remaining:this.remaining};}
  }
  function videoPayload(item,prompt,preset){const image=item.kind==='image';return {mode:image?'frame':item.kind==='video'||item.kind==='audio'?'reference':'text',source:image||item.kind==='video'||item.kind==='audio'?item.file:'',source_type:image||item.kind==='video'||item.kind==='audio'?'generation':'',source_generation:item.prompt_id||'',prompt:preset?prompt.replace(/\{goal\}/g,preset.goal||''):prompt,air_it:false,...(preset?{speech:preset.speech||'',style:preset.style||'',h3_brief:{audio_direction:preset.audio_direction||'',constraints:preset.constraints||''},h3_prompts:{preset:preset.name||preset.id||'',prompts:preset}}:{})};}
  const exported={MediaQueue,exitChoice,videoPayload,DEVELOP_MS,ENTER_MS,HOLD_MS,EXIT_MS};
  if(typeof module!=='undefined')module.exports=exported;
  const doc=root.document;if(!doc||root.PineGeneratedMedia)return;
  const make=(tag,cls,text)=>{const n=doc.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;};
  const api=()=>root.pineDesktop;
  function url(path){return root.pineMediaUrl?.(path)||root.desktopMusicUrl?.(path)||path;}
  function button(text,run){const b=make('button','',text);b.type='button';b.onclick=e=>{e.stopPropagation();Promise.resolve().then(run).catch(err=>console.error('[Generated media]',err));};return b;}
  let dock,tile,queue,busy=false,cursor='',pollTimer,started=false;
  let review=null,reviewTicket=0;
  function remember(){try{root.sessionStorage?.setItem('pineGeneratedMediaCursor',cursor);}catch(e){}}
  function loadSeen(){try{return JSON.parse(root.sessionStorage?.getItem('pineGeneratedMediaSeen')||'[]');}catch(e){return [];}}
  function saveSeen(){try{root.sessionStorage?.setItem('pineGeneratedMediaSeen',JSON.stringify([...queue.seen].slice(-10000)));root.sessionStorage?.setItem('pineGeneratedMediaPending',JSON.stringify([...(queue.active?[queue.active]:[]),...queue.queue]));}catch(e){}}
  async function preview(item,host){
    let poster=item.poster;
    if(!poster&&item.poster_request){try{const out=await api().get(item.poster_request);poster=out.poster;}catch(e){}}
    if(poster){const im=make('img');im.alt=item.title||item.file;im.draggable=false;host.append(im);await new Promise(resolve=>{const timer=root.setTimeout(()=>{im.onload=im.onerror=null;resolve();},5000);im.onload=()=>{root.clearTimeout(timer);resolve();};im.onerror=()=>{root.clearTimeout(timer);im.remove();host.append(make('span','gm-preview-note','Preview unavailable · click to inspect'));resolve();};im.src=url(poster);});}
    else host.append(make('span','gm-preview-note',item.kind==='audio'?'♪ AUDIO':item.kind==='video'?'▶ VIDEO':'GENERATED FILE'));
  }
  function build(){if(dock)return;dock=make('aside','gm-dock');dock.id='pineGeneratedMediaDock';dock.setAttribute('aria-label','New generated media');doc.body.append(dock);
    queue=new MediaQueue({clock:()=>Date.now(),set:(fn,ms)=>root.setTimeout(fn,ms),clear:id=>root.clearTimeout(id),
      present:async item=>{tile=make('button','gm-polaroid');tile.type='button';tile.setAttribute('aria-label','Open generated '+item.kind+': '+item.title);const picture=make('span','gm-polaroid-picture');tile.append(picture,make('b','gm-polaroid-title',item.title||item.file),make('small','gm-polaroid-kind',(item.purpose||item.kind)+' · click to review'));dock.append(tile);tile.onpointerenter=()=>queue.pause(true);tile.onpointerleave=()=>queue.pause(false);tile.onfocus=()=>queue.pause(true);tile.onblur=()=>queue.pause(false);tile.onclick=e=>{e.preventDefault();e.stopPropagation();const chosen=item;queue.finish();openReview(chosen).catch(console.error);};await preview(item,picture);},
      phase:(phase,item,exit)=>{saveSeen();if(!tile)return;tile.dataset.phase=phase;if(exit){tile.dataset.exit=exit.direction;tile.dataset.motion=exit.mode;tile.style.setProperty('--gm-exit-rotation',exit.rotation+'deg');}},
      remove:()=>{tile?.remove();tile=null;}
    });for(const id of loadSeen())queue.seen.add(id);queue.setVisible(!doc.hidden);try{const pending=JSON.parse(root.sessionStorage?.getItem('pineGeneratedMediaPending')||'[]');for(const item of pending)queue.seen.delete(item.id);queue.enqueue(pending);}catch(e){}
  }
  async function poll(){if(busy||!api()?.get)return;busy=true;try{const out=await api().get('/api/generated-media/events?limit=100'+(cursor?'&cursor='+encodeURIComponent(cursor):''));build();queue.enqueue(out.events||[]);cursor=out.cursor||cursor;remember();saveSeen();if(out.archive_gap)console.warn('Older generated media is available in the gallery archive.');if(out.more){root.clearTimeout(pollTimer);pollTimer=root.setTimeout(poll,0);}}catch(e){/* Keep cursor and queue through a temporary disconnect. */}finally{busy=false;}}
  function boot(){if(started||root.PINE_NATIVE_TOOLS)return;started=true;try{cursor=root.sessionStorage?.getItem('pineGeneratedMediaCursor')||'';}catch(e){}build();poll();root.setInterval(poll,2500);doc.addEventListener('visibilitychange',()=>{queue.setVisible(!doc.hidden);if(!doc.hidden)poll();});}
  function release(media){if(!media)return;try{media.pause?.();media.removeAttribute('src');media.load?.();}catch(e){}}
  function closeReview(){reviewTicket++;if(!review)return;release(review.media);review.element.remove();const prior=review.focus;review=null;if(prior?.isConnected)prior.focus?.();}
  async function openReview(initial={}){
    if(root.PinePip?.state?.()?.active&&!root.PINE_NATIVE_TOOLS&&api()?.pipToolsOpen)return api().pipToolsOpen({media:initial});
    closeReview();const ticket=++reviewTicket,focus=doc.activeElement;
    const shade=make('div','gm-review-shade pip-popup-visible');shade.setAttribute('role','presentation');
    const box=make('section','gm-review');box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Generated media review');
    const header=make('header','gm-review-header');const heading=make('h2','','Generated media');const close=button('×',closeReview);close.setAttribute('aria-label','Close generated media');header.append(heading,close);box.append(header);
    const viewer=make('div','gm-review-viewer'),message=make('p','gm-review-status');message.setAttribute('role','status');const controls=make('div','gm-review-controls');
    const prompt=make('textarea','gm-review-prompt');prompt.rows=6;prompt.setAttribute('aria-label','Generation prompt');prompt.placeholder='Describe the new image or H3 video';
    const historyBar=make('div','gm-review-history');const history=make('select');history.setAttribute('aria-label','Previous generation or saved H3 prompt');const first=make('option','','Use a previous prompt…');first.value='';history.append(first);
    const older=button('Older prompts',()=>loadHistory());const apply=button('Assign prompt',()=>{const entry=historyEntries.get(history.value);if(entry){prompt.value=entry.text;selectedPreset=entry.preset||null;message.textContent='Prompt assigned. Edit it before regenerating.';}});historyBar.append(history,apply,older);
    const actions=make('div','gm-review-actions'),analysis=make('pre','gm-review-analysis');
    const detail=make('details','gm-review-recipe');detail.append(make('summary','','Original request and render recipe'));const recipe=make('pre');detail.append(recipe);
    controls.append(make('label','','Prompt'),prompt,historyBar,actions,message,analysis,detail);box.append(viewer,controls);shade.append(box);doc.body.append(shade);review={element:shade,media:null,focus};
    shade.onclick=e=>{if(e.target===shade)closeReview();};shade.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeReview();}else if(e.key==='Tab'){const buttons=[...box.querySelectorAll('button,input,textarea,select,a[href]')].filter(n=>!n.disabled&&!n.hidden);if(e.shiftKey&&doc.activeElement===buttons[0]){e.preventDefault();buttons.at(-1)?.focus();}else if(!e.shiftKey&&doc.activeElement===buttons.at(-1)){e.preventDefault();buttons[0]?.focus();}}};close.focus();
    let item={...initial},selectedPreset=null,before='',historyLoading=false;const historyEntries=new Map();
    function addHistory(key,label,text,preset){if(!text||historyEntries.has(key))return;historyEntries.set(key,{text,preset});const o=make('option','',label.slice(0,150));o.value=key;history.append(o);}
    async function loadHistory(){if(historyLoading)return;historyLoading=true;older.disabled=true;try{const out=await api().get('/api/generations/history?limit=60'+(before?'&before='+encodeURIComponent(before):''));if(ticket!==reviewTicket)return;for(const r of out.generations||[])addHistory('generation:'+r.prompt_id,(r.kind||'Media')+' · '+(r.request||r.tags||r.prompt_id),r.tags||r.request);before=out.next||'';older.hidden=!before;}catch(e){if(ticket===reviewTicket)message.textContent='Prompt history: '+e.message;}finally{historyLoading=false;older.disabled=false;}}
    async function render(kind){const words=prompt.value.trim();if(!words){message.textContent='Enter or assign a prompt.';prompt.focus();return;}for(const b of actions.querySelectorAll('button'))b.disabled=true;message.textContent='Submitting '+(kind==='video'?'H3 video':'image')+'…';try{const out=await api().post(kind==='video'?'/api/comfy/workshop':'/api/generate',kind==='video'?videoPayload(item,words,selectedPreset):{prompt:words});if(ticket===reviewTicket)message.textContent=(out.queued?'Queued':'Rendering')+' · '+(out.prompt_id||out.queue_id||out.model||kind);}catch(e){if(ticket===reviewTicket)message.textContent=e.message;}finally{if(ticket===reviewTicket)for(const b of actions.querySelectorAll('button'))b.disabled=false;}}
    const image=button('Regenerate image',()=>render('image')),video=button('Regenerate video (H3)',()=>render('video'));
    const examine=button('Analyze',async()=>{if(!item.id){message.textContent='This output has no generation identity.';return;}examine.disabled=true;message.textContent='Analyzing this '+item.kind+'…';try{const out=await api().post('/api/generated-media/analyze/'+encodeURIComponent(item.id),{});if(ticket===reviewTicket){analysis.textContent=out.analysis||'';message.textContent='Analysis complete.';}}catch(e){if(ticket===reviewTicket)message.textContent=e.message;}finally{examine.disabled=false;}});
    actions.append(image,video,examine,button('H3 / Supercuts',async()=>{if(!root.PineAdViewer&&root.pineLoadTool)await root.pineLoadTool('PineAdViewer');closeReview();root.PineAdViewer?.open(item,true);}));
    try{if(item.id)item=await api().get('/api/generated-media/item/'+encodeURIComponent(item.id));if(ticket!==reviewTicket)return;heading.textContent=item.title||item.file||'Generated media';prompt.value=initial.prompt||item.tags||item.request||'';analysis.textContent=item.analysis||'';recipe.textContent=JSON.stringify({request:item.request,prompt:item.tags,model:item.model,purpose:item.purpose,file:item.file,h3_prompts:item.h3_prompts},null,2);
      const media=make(item.kind==='image'?'img':item.kind==='video'?'video':item.kind==='audio'?'audio':'a','gm-review-media');
      if(item.kind==='image')media.alt=item.title||item.file;
      else if(item.kind==='video'||item.kind==='audio'){media.controls=true;media.preload='metadata';media.playsInline=true;media.autoplay=false;media.addEventListener('error',()=>{if(ticket===reviewTicket)message.textContent='This media could not be loaded. Reopen it to retry.';});}
      else{media.textContent='Open generated file';media.href=url(item.url);media.target='_blank';media.rel='noopener';}
      if(item.kind!=='file')media.src=url(item.url);viewer.append(media);review.media=media;examine.disabled=item.kind==='file';
      addHistory('this','This render’s prompt',item.tags||item.request);await Promise.allSettled([loadHistory(),api().get('/api/h3/prompts').then(out=>{if(ticket!==reviewTicket)return;for(const p of out.presets||[]){const fields=[p.goal,p.clip,p.gallery,p.host,p.clip_prompt,p.image_prompt,p.gallery_prompt,p.host_prompt,p.prompt,p.direction,p.visual_direction].filter(v=>typeof v==='string'&&v.trim());for(let i=0;i<fields.length;i++)addHistory('preset:'+p.id+':'+i,'H3 preset · '+p.name+(fields.length>1?' · '+(i+1):''),fields[i],p);}})]);
    }catch(e){if(ticket===reviewTicket)message.textContent=e.message;}
    return {element:shade,close:closeReview};
  }
  root.PineGeneratedMediaReview={open:openReview,close:closeReview};
  root.PineGeneratedMedia={openReview,poll,state:()=>({cursor,...queue?.state()}),enqueue:items=>{build();queue.enqueue(items);saveSeen();},...exported};
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',boot);else boot();
})(typeof window!=='undefined'?window:globalThis);
