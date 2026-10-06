/* Access existing Pine tools while the compact window keeps playing. */
(function(root){
  'use strict';
  const doc=root.document;if(!doc||root.PinePipPopups)return;
  let dock,bar,list,status,title,filter,current=null,entries=[],favorites=[],active=false,opened=false,sequence=0;
  let observed=null,paintQueued=false,sceneAsked=false,selectionId="",focusRevision=0;
  const sidebarRows=new Map();
  // A user interaction during loading owns focus; asynchronous tool mounts do not.
  for(const name of ["pointerdown","keydown"])doc.addEventListener(name,()=>{focusRevision++;},true);
  const promoted=new Map();let baseline=new Map();
  const stamp=el=>(String(el.className).replace(/\bpip-popup-visible\b/g,'').trim())+'|'+(el.getAttribute('style')||'')+'|'+el.hidden;
  const views=['script','books','listen','music','presentation','sampler','slideshow','pinelens'];
  const contextual=new Set(['PineLineActions','PineLineDeep','PineLineRepeat']);
  let selectedLine=null,lineHistory=[],lineLeave=null;
  const excluded=new Set(['PineBootSplash','PinePipPopups','PinePip','PinePopBack','PinePulseTip','PineViewRail','PineViewChrome','PineRejectionReview']);
  function node(tag,cls,text){const n=doc.createElement(tag);n.className=cls||'';if(text)n.textContent=text;return n;}
  function button(label,fn){const b=node('button','',label);b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(report);return b;}
  function message(entry,words,retry){let host=doc.getElementById('pinePipPopupMessage');if(!host){host=node('aside','pip-popup-message');host.id='pinePipPopupMessage';host.setAttribute('role','status');doc.body.appendChild(host);}host.replaceChildren(node('h2','',entry.label),node('p','',words));if(retry)host.appendChild(button('Retry',()=>select(entry.id)));host.appendChild(button('Close tool',()=>closeCurrent()));promote();return host;}
  function forgetMessage(){const host=doc.getElementById('pinePipPopupMessage');if(host){promoted.delete(host);host.remove();}}
  function report(e){if(status)status.textContent=e?.message||String(e);}
  function label(key){return key.replace(/^Pine/,'').replace(/([a-z])([A-Z])/g,'$1 $2').replace('Orch Glass','Orchestra controls');}
  function context(){const selection=root.getSelection?.()?.anchorNode?.parentElement;const line=selection?.closest?.('[data-line-id],[data-line],[data-dialogue-id],[data-msg-id]');if(line)return line;const rows=doc.querySelectorAll('[data-line-id],[data-line],[data-dialogue-id],[data-msg-id]');return rows[rows.length-1];}
  function stopLineContext(){lineLeave?.();lineLeave=null;}
  function recentLines(key){
    const byId=new Map(),rows=[...lineHistory,...(root.PineStationFeed?.rows?.()||[])].slice(-400);
    for(const row of rows){const id=String(row.id||row.line_id||''),said=String(row.said||row.text||'').trim();
      if(!/^[a-f0-9]{6,32}$/i.test(id)||!said||row.music||row.image||row.analysis)continue;
      if(key!=='PineLineActions'&&(row.sfx||row.video))continue;
      byId.set(id,{id,said,who:row.name||row.who||'',row});}
    return [...byId.values()].reverse().slice(0,100);
  }
  function lineContext(api,key){
    const row=context(),fromRow=row&&(root.PineLineActions?.lineAt?.(row)||{id:row.dataset.lineId||row.dataset.line||row.dataset.dialogueId||row.dataset.msgId,said:row.dataset.said||row.textContent,node:row});
    let lines=recentLines(key),line=fromRow?.id?fromRow:lines.find(item=>item.id===selectedLine?.id)||lines[0];
    const expected=current;
    function launch(chosen){
      if(current!==expected)return;
      stopLineContext();
      for(const [el]of promoted)if(!el.isConnected)promoted.delete(el);
      api.close?.();
      if(chosen){selectedLine=chosen;api.open(chosen);}
      else{const empty=node('aside','pip-line-empty');empty.id='pinePipLineEmpty';empty.setAttribute('role','dialog');empty.appendChild(node('p','','No recent dialogue is available. Refresh the lines or wait for the station to speak.'));empty.appendChild(button('Close line tool',()=>closeCurrent()));doc.body.appendChild(empty);}
      const panel=chosen?doc.querySelector(key==='PineLineActions'?'.la-sheet':key==='PineLineDeep'?'.ld-box':'.lr-sheet'):doc.getElementById('pinePipLineEmpty');
      if(!panel)throw Error('The line tool did not create its panel.');
      if(chosen)doc.getElementById('pinePipLineEmpty')?.remove();
      const bar=node('div','pip-line-context'),search=node('input',''),pick=node('select','');
      search.type='search';search.placeholder='Search recent lines';search.setAttribute('aria-label','Search recent lines');pick.setAttribute('aria-label','Choose a line');
      const note=node('span','pip-line-note');
      function fill(){
        lines=recentLines(key);const query=search.value.toLowerCase(),visible=lines.filter(item=>(item.said+' '+item.who+' '+item.id).toLowerCase().includes(query));
        pick.replaceChildren();const blank=node('option','','Choose a line');blank.value='';pick.appendChild(blank);
        for(const item of visible){const option=node('option','',(item.who?item.who+': ':'')+item.said.slice(0,150));option.value=item.id;pick.appendChild(option);}
        pick.value=chosen?.id||'';note.textContent=lines.length+' recent lines';
      }
      search.addEventListener('input',fill);pick.addEventListener('change',()=>{const next=lines.find(item=>item.id===pick.value);if(doc.body.getAttribute('data-pine-editing')==='line-deep'){pick.value=chosen?.id||'';note.textContent='Finish or cancel the current edit before choosing another line.';return;}if(next)launch(next);});
      const refresh=button('Refresh lines',async()=>{refresh.disabled=true;note.textContent='Reading recent dialogue...';try{const got=await root.pineDesktop.get('/api/airlog?limit=120');if(current!==expected||!bar.isConnected)return;lineHistory=Array.isArray(got)?got:got.events||got.rows||got.items||[];fill();if(!chosen){const first=recentLines(key)[0];if(first)launch(first);}}catch(error){if(bar.isConnected)note.textContent=error.message||'The station did not answer.';}finally{refresh.disabled=false;}});
      bar.append(search,pick,refresh,note);panel.prepend(bar);fill();
      if(root.PineStationFeed?.subscribe)lineLeave=root.PineStationFeed.subscribe(()=>{if(bar.isConnected)fill();});
      promote();
    }
    launch(line);
    return true;
  }
  function flowPanel(api){
    const host=node('aside','pip-flowchart');host.id='pinePipFlowChart';host.setAttribute('role','dialog');host.setAttribute('aria-label','Conversation flowchart');
    const closeButton=button('Close flowchart',()=>closeCurrent());closeButton.setAttribute('aria-label','Close flowchart');
    const pane=node('div','');host.append(closeButton,pane);doc.body.appendChild(host);api.show(pane,true);return true;
  }
  function catalog(){
    const got=[];for(const [key,label]of [['mixer','Audio mixer'],['troubleshoot','Troubleshoot station']])if(root.pineDesktop?.audioMixerGet)got.push({id:'native:'+key,label,group:'Native windows',open:()=>root.pineToolsNativeMount?.(key),close:()=>root.pineToolsNativeClose?.()});
    for(const key of [...new Set([...Object.keys(root).filter(k=>/^Pine[A-Z]/.test(k)),...(root.PineLocalPopupCatalog||[]).map(e=>e.key)])].sort()){
      const api=root[key],lazy=(root.PineLocalPopupCatalog||[]).some(e=>e.key===key);if(excluded.has(key)||(!lazy&&typeof api?.open!=='function'))continue;
      got.push({id:'module:'+key,label:label(key),group:'Popups',open:async()=>{const expected=current;const api=root.pineLoadTool?await root.pineLoadTool(key):root[key];if(current!==expected)return;if(typeof api?.open!=='function')throw Error('This tool does not have a popup.');
        if(key==='PineAlbum'){const feed=root.PineStationFeed,latest=feed?.latest?.();const playing=latest?.station?.now||feed?.state?.()?.now;const row=[...(latest?.rows||feed?.rows?.()||[])].reverse().find(r=>r.music);const track=playing?.id||playing?.album?playing:row?{...row,id:String(row.id||'').replace(/^music:/,''),title:row.title||row.text,artist:row.artist||row.name}:null;return api.open(track);}
        if(key==='PineFlowChart')return flowPanel(api);
        if(contextual.has(key))return lineContext(api,key);
        return api.open();
      },close:()=>{stopLineContext();doc.getElementById('pinePipLineEmpty')?.remove();if(key==='PineFlowChart'){root[key]?.show?.(null,false);doc.getElementById('pinePipFlowChart')?.remove();}else root[key]?.close?.();}});
    }
    if(root.PineThreeFull?.openOrchestrator)got.push({id:'orchestra:3js',label:'3JS orchestra',group:'Orchestra',open:async()=>{if(root.pineLoadTool)return (await root.pineLoadTool('PineOrchGlass')).open();return root.PineThreeFull.openOrchestrator();},close:()=>root.PineOrchGlass?.close?.()});
    for(const method of ['topicWindow'])if(typeof root.PineSegments?.[method]==='function')got.push({id:'segments:'+method,label:method==='topicWindow'?'Topic bank':'Plot and segment editor',group:'Orchestra',open:()=>root.PineSegments[method](),close:()=>root.PineSegments.close?.()});
    if(root.PineSegments?.pane)got.push({id:'segments:editor',label:'Segments and system prompts',group:'Orchestra',open:async()=>{
      const host=node('aside','pip-segments-editor');host.id='pinePipSegmentEditor';host.setAttribute('role','dialog');
      const closeButton=button('Close',()=>host.remove());closeButton.setAttribute('aria-label','Close segment editor');host.appendChild(closeButton);doc.body.appendChild(host);await root.PineSegments.pane(host);
    },close:()=>doc.getElementById('pinePipSegmentEditor')?.remove()});
    for(const id of views)got.push({id:'view:'+id,label:id==='books'?'Book Mode':id[0].toUpperCase()+id.slice(1),group:'Views',open:()=>{if(root.PineViewRail)return root.PineViewRail.open(id);else return root.PineViewChrome?.show(id);},close:()=>{root.PineViewChrome?.show('control');root.PineViewRail?.close?.();}});
    const scenes=Array.isArray(root.PinePopupScenes)?root.PinePopupScenes:[];
    for(const scene of scenes)if(root.pineToolsSceneOpen)got.push({id:'scene:'+scene.key,label:scene.name||scene.label||scene.key,group:'3JS',local:true,open:()=>root.pineToolsSceneOpen(scene.key),close:()=>root.pineToolsSceneClose()});else if(scene.key!=='off')got.push({id:'scene:'+scene.key,label:scene.name||scene.label||scene.key,group:'3JS',open:()=>root.PineThreeFull.show(scene.key),close:()=>root.PineThreeFull.close()});
    for(const key of root.PineStationPopups||[])if(!got.some(e=>e.id==='module:'+key))got.push({id:'station-popup:'+key,label:label(key),group:'Station popups',local:!!root.pineToolsStationPopupOpen,open:async()=>{if(root.pineToolsStationPopupOpen)return root.pineToolsStationPopupOpen(key);await root.pineEnsureToolsFrame?.();await guestTools(true);const result=await doc.getElementById('controlFrame').executeJavaScript('Promise.resolve(window['+JSON.stringify(key)+']?.open()).then(()=>true)');if(!result)throw Error('This station popup is unavailable.');},close:async()=>{if(root.pineToolsStationPopupOpen)return root.pineToolsSceneClose();await doc.getElementById('controlFrame')?.executeJavaScript('window['+JSON.stringify(key)+']?.close?.()');root.pineReleaseToolsFrame?.();}});
    const byId=new Map(got.map(e=>[e.id,e]));
    for(const e of entries)if(e.group==='3JS'&&!byId.has(e.id))byId.set(e.id,e);
    entries=[...byId.values()];return entries;
  }
  function promote(){
    if(!opened||!active)return;
    const candidates=[...doc.body.children];const main=doc.querySelector('main');if(main)candidates.push(...main.children);
    for(const el of candidates){
      if(el===dock||el===bar||el.hidden||el.style.display==='none'||/^(SCRIPT|STYLE|LINK)$/.test(el.tagName))continue;
      const isScene=el.id===root.PineThreeFull?.HOST_ID||(current?.local&&(root.pineToolsSceneRoots?.()||[]).some(owned=>owned===el||el.contains(owned)));
      const isEditor=(current?.local&&!/^(MAIN|NAV)$/.test(el.tagName)&&(el.matches('.s3-backdrop,.cw-shade,.sf-shade,.wc-root,.pine-win')||el.querySelector('[role=dialog]')))||el.id==='pinePipPopupMessage'||el.id==='pinePipSegmentEditor'||el.id==='pinePipNativePane'||(current?.id==='module:PineCam'&&el.matches('#pineCamBox,.pine-cam-box'))||(current?.id==='module:PineConsoleLine'&&el.id==='pineConsoleLine')||el.id==='pinePipFlowChart'||el.id==='pinePipLineEmpty'||(current?.id?.startsWith('module:')&&el.matches('.fm-pop,.la-sheet,.ld-box,.lr-sheet'));
      const isCarrier=!current?.local&&(current?.group==='3JS'||current?.group==='Station popups')&&el.id==='control';
      const isView=current?.id.startsWith('view:')&&(el.id===current.id.slice(5)||el.dataset.view===current.id.slice(5));
      if(!isCarrier&&!isEditor&&!isScene&&!isView&&!root.PinePopBack?.isPopup(el))continue;
      if(!isCarrier&&!isScene&&!isView&&!promoted.has(el)&&baseline.has(el)&&baseline.get(el)===stamp(el))continue;
      if(!promoted.has(el)){promoted.set(el,{style:el.getAttribute('style')});el.classList.add('pip-popup-visible');}
    }
  }
  function queuePromote(){if(paintQueued)return;paintQueued=true;root.requestAnimationFrame(()=>{paintQueued=false;promote();});}
  function restore(){for(const [el,old]of promoted){el.classList.remove('pip-popup-visible');if(old.style===null)el.removeAttribute('style');else el.setAttribute('style',old.style);}promoted.clear();}
  async function guestTools(on){const frame=doc.getElementById('controlFrame');if(!frame?.executeJavaScript)return;try{await frame.executeJavaScript('window.__pinePipTools='+!!on+';document.documentElement.classList.toggle("pine-pip-tools",'+!!on+');if(!document.getElementById("pinePipToolsStyle")){const s=document.createElement("style");s.id="pinePipToolsStyle";s.textContent=".pine-pip-tools #pine-pip-panel{display:none!important}";document.head.appendChild(s);}');}catch(e){report(e);}}
  async function closeCurrent(nextGroup){stopLineContext();sequence++;forgetMessage();const was=current;current=null;const closers=(!was?.close||(was?.id?.startsWith('module:')&&typeof root[was.id.slice(7)]?.close!=='function'&&was.id!=='module:PineFlowChart'))?[...promoted.keys()].map(el=>el.querySelector('[aria-label^="close" i],[title^="close" i],[data-pine-close]')).filter(Boolean):[];restore();if(root.PINE_NATIVE_TOOLS&&!was?.local&&['3JS','Station popups'].includes(was?.group)&&!['3JS','Station popups'].includes(nextGroup)){root.pineReleaseToolsFrame?.();return;}try{await was?.close?.();for(const closer of closers)if(closer.isConnected)closer.click();await guestTools(false);}catch(e){report(e);}finally{root.pineToolsReleaseContexts?.();}}
  async function select(id){
    const entry=entries.find(e=>e.id===id);if(!entry)return;selectionId=id;paintList();focusSelected(true);const focusTicket=focusRevision;if(current?.id===id&&current.completed)return;title.textContent=entry.label;status.textContent='Opening '+entry.label+'…';
    const ticket=sequence+1;await closeCurrent(entry.group);if(ticket!==sequence)return;baseline=new Map([...doc.body.children,...(doc.querySelector('main')?.children||[])].map(el=>[el,stamp(el)]));current=entry;title.textContent=entry.label;status.textContent='Opening '+entry.label+'…';
    const loadingPane=message(entry,'Loading '+entry.label+'…');
    try{if(entry.group==='3JS'&&!entry.local){await root.pineEnsureToolsFrame?.();await guestTools(true);}else if(entry.group!=='Station popups')root.pineReleaseToolsFrame?.();const result=entry.open();promote();const said=await result;if(ticket!==sequence)return;if(entry.group==='3JS'&&!entry.local&&typeof said==='string'&&said!==entry.id.slice(6))throw Error(said);promote();if(entry.group==='Popups'&&![...promoted.keys()].some(el=>el!==loadingPane&&el.isConnected))throw Error('This popup did not open. It may need a selected item.');forgetMessage();current.completed=true;status.textContent='Right-click an item to add it to the quick bar.';paintList();}catch(e){if(ticket===sequence){report(e);message(entry,e?.message||String(e),true);}}
    if(ticket===sequence&&focusTicket===focusRevision)focusSelected(false);
  }
  function star(id){const exists=favorites.includes(id);favorites=exists?favorites.filter(f=>f!==id):favorites.concat(id);paintBar();paintList();root.pineDesktop?.pipUpdate({popupFavorites:favorites}).catch(report);}
  function item(entry,quick){const b=button((!quick&&favorites.includes(entry.id)?'★ ':'')+entry.label,()=>{if(!root.PINE_NATIVE_TOOLS&&root.pineDesktop?.pipToolsOpen)return root.pineDesktop.pipToolsOpen({id:entry.id});if(!opened)open();return select(entry.id);});b.dataset.popup=entry.id;b.title=(quick?'Open ':'')+entry.label+' · Right-click to '+(favorites.includes(entry.id)?'remove favorite':'favorite');b.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();star(entry.id);};return b;}
  function paintBar(){if(!bar)return;bar.replaceChildren();for(const id of favorites){const entry=entries.find(e=>e.id===id)||{id,label:label(id.slice(id.indexOf(':')+1))};bar.appendChild(item(entry,true));}bar.hidden=!root.PINE_NATIVE_TOOLS||!active||!bar.children.length;layoutFavorites();}
  function layoutFavorites(){
    if(!root.PINE_NATIVE_TOOLS||!bar)return;
    const height=bar.hidden?0:Math.ceil(bar.getBoundingClientRect().height);
    doc.body.style.setProperty('--pip-tools-top',(height+4)+'px');
  }
  function paintList(){
    if(!list)return;
    const q=(filter.value||'').toLowerCase(),scroll=list.scrollTop,focused=list.contains(doc.activeElement)?doc.activeElement:null;
    const visible=entries.filter(e=>(e.label+' '+e.group).toLowerCase().includes(q)),ids=new Set(visible.map(e=>e.id));
    // Keep each button mounted across selection, catalog and preference updates.
    for(const row of [...list.children])if(!ids.has(row.dataset.popup))row.remove();
    let next=list.firstElementChild;
    for(const entry of visible){
      let row=sidebarRows.get(entry.id);
      if(!row){row=item(entry,false);row.appendChild(node('small','',entry.group));sidebarRows.set(entry.id,row);}
      const text=(favorites.includes(entry.id)?'\u2605 ':'')+entry.label;
      if(row.firstChild.nodeValue!==text)row.firstChild.nodeValue=text;
      const group=row.querySelector('small');if(group.textContent!==entry.group)group.textContent=entry.group;
      row.title=entry.label+' \u00b7 Right-click to '+(favorites.includes(entry.id)?'remove favorite':'favorite');
      row.classList.toggle('selected',selectionId===entry.id);
      row.setAttribute('aria-pressed',String(selectionId===entry.id));
      if(row!==next)list.insertBefore(row,next);else next=next.nextElementSibling;
    }
    const available=new Set(entries.map(e=>e.id));for(const id of sidebarRows.keys())if(!available.has(id))sidebarRows.delete(id);
    if(focused?.isConnected&&doc.activeElement!==focused)focused.focus({preventScroll:true});
    list.scrollTop=scroll;
  }
  function focusSelected(reveal){
    const row=sidebarRows.get(selectionId);if(!opened||!row?.isConnected)return;
    row.focus({preventScroll:true});
    if(reveal){const box=list.getBoundingClientRect(),item=row.getBoundingClientRect();if(item.top<box.top)list.scrollTop-=box.top-item.top;else if(item.bottom>box.bottom)list.scrollTop+=item.bottom-box.bottom;}
  }
  function build(){if(dock)return;bar=node('nav','pip-popup-favorites');bar.id='pinePipFavorites';bar.setAttribute('aria-label','Favorite Pine tools');doc.body.appendChild(bar);
    if(root.ResizeObserver){const observer=new root.ResizeObserver(layoutFavorites);observer.observe(bar);}else root.addEventListener('resize',layoutFavorites);
    dock=node('aside','pip-popup-dock');dock.id='pinePipPopupDock';dock.hidden=true;
    const heading=node('header','');title=node('b','','Pine tools');heading.append(title,button('‹',()=>cycle(-1)),button('›',()=>cycle(1)),button('×',close));dock.appendChild(heading);
    filter=node('input','');filter.type='search';filter.placeholder='Find a popup, view or 3JS window';filter.setAttribute('aria-label','Find Pine tools');filter.oninput=paintList;filter.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();list.querySelector('button')?.click();}else if(e.key==='ArrowDown'){e.preventDefault();list.querySelector('button')?.focus();}};dock.appendChild(filter);
    list=node('nav','pip-popup-list');list.setAttribute('aria-label','Pine popups');status=node('p','pip-popup-status','Right-click an item to favorite it.');dock.append(list,status);doc.body.appendChild(dock);
    dock.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();};
  }
  function cycle(step){const rows=entries.filter(e=>(e.label+' '+e.group).toLowerCase().includes((filter.value||'').toLowerCase()));if(!rows.length)return;const at=rows.findIndex(e=>e.id===selectionId);select(rows[(at+step+rows.length)%rows.length].id).catch(report);}
  function open(){if(!root.PINE_NATIVE_TOOLS&&root.pineDesktop?.pipToolsOpen){return root.pineDesktop.pipToolsOpen().catch(report);}const wasOpened=opened;build();opened=true;doc.body.classList.add('pip-popups-open');dock.hidden=false;catalog();paintBar();paintList();promote();if(!wasOpened){if(selectionId)focusSelected(true);else filter.focus();}
    if(!observed&&root.MutationObserver){observed=new MutationObserver(queuePromote);observed.observe(doc.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','hidden','style']});}
    if(!root.PINE_NATIVE_TOOLS&&!sceneAsked&&root.PineThreeFull?.list){sceneAsked=true;root.PineThreeFull.list().then(result=>{if(result?.ok){for(const scene of result.rows||[])if(!entries.some(e=>e.id==='scene:'+scene.key))entries.push({id:'scene:'+scene.key,label:scene.label||scene.key,group:'3JS',open:()=>root.PineThreeFull.show(scene.key),close:()=>root.PineThreeFull.close()});paintList();paintBar();}}).catch(report);}
  }
  async function close(){opened=false;observed?.disconnect();observed=null;await closeCurrent();root.pineReleaseToolsFrame?.();doc.body.classList.remove('pip-popups-open');if(dock)dock.hidden=true;}
  function sync(state){active=!!state?.active;favorites=Array.isArray(state?.popupFavorites)?state.popupFavorites:[];if(active){build();catalog();paintBar();if(opened)paintList();}else{close();if(bar)bar.hidden=true;}}
  root.addEventListener('keydown',e=>{if(!opened)return;if(e.key==='Escape'){e.preventDefault();close();}if(e.altKey&&(e.key==='ArrowDown'||e.key==='ArrowUp')){e.preventDefault();cycle(e.key==='ArrowDown'?1:-1);}});
  root.PinePipPopups={open,close,clear:closeCurrent,sync,select,cycle,favorite:star,catalog,state:()=>({opened,current:current?.id,selected:selectionId,favorites:[...favorites],count:entries.length})};
})(window);
