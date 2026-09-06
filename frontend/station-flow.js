/* The station's observed content flow. Three.js draws the graph; equivalent
 * native controls work without WebGL. Only journal events animate packets. */
const POSITIONS = {
  schedule:[0,0], speakerbox:[1,0], pivots:[2,0], draft:[3,0], conversation:[4,0], gazette:[6,0],
  repair:[1,1], tint_judge:[2,1], rewrite:[3,1], crystal:[4,1], paper_tint:[6,1],
  tts:[2,2], pantry:[3,2], repeat:[4,2], publish:[5,2], edition:[6,2],
  ended:[2,3], playing:[3,3], canplay:[4,3], received:[5,3], error:[6,3],
  reflection:[2,4], watchdog:[3,4],
};
const LANE_TITLES = ["01  SOURCES & CONVERSATION", "02  CRYSTAL & JUDGMENT", "03  RECORD & PUBLISH", "04  LISTENER PLAYBACK", "05  REFLECT & CONTINUE"];
const ICON_PATHS = {
  schedule:'<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h3m-3 3h6"/>',
  speakerbox:'<path d="M4 4h7l3 3h6v14H4zM8 11h8m-8 4h8m-8 3h5"/>',
  pivots:'<path d="M4 5h4c7 0 1 14 8 14h4M4 19h4c7 0 1-14 8-14h4m-3-3 3 3-3 3m0 8 3 3-3 3"/>',
  draft:'<path d="m4 20 4-1L20 7l-4-4L4 15v5zm9-14 4 4M3 23h18"/>',
  conversation:'<path d="M3 4h16v11H9l-5 4v-4H3zM7 8h8m-8 3h5m3 7h5l2 3V9"/>',
  crystal:'<path d="m12 2 8 6-3 12H7L4 8zm-8 6h16m-8-6L8 8l4 12 4-12z"/>',
  rewrite:'<path d="M4 7h13l-3-3m3 3-3 3M20 17H7l3 3m-3-3 3-3M4 12h8m4 0h4"/>',
  tint_judge:'<path d="m12 2 9 5v7c0 5-9 9-9 9s-9-4-9-9V7zm-5 10 3 3 7-7"/>',
  repair:'<path d="M19 8a7 7 0 1 0 1 7M19 3v5h-5m-6 4h8m-4-4v8"/>',
  tts:'<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v4m-4 0h8"/>',
  pantry:'<path d="M3 4h18v16H3zM3 12h18M7 8h2m6 0h2M7 16h2m6 0h2"/>',
  publish:'<path d="M5 15a5 5 0 0 1 0-10 7 7 0 0 1 13-1 5 5 0 0 1 1 11m-7 6V10m-4 4 4-4 4 4"/>',
  received:'<path d="M4 3h16v18H4zm8 1v10m-4-4 4 4 4-4m-9 8h10"/>',
  canplay:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 6-7"/>',
  playing:'<path d="m3 9 4 0 5-5v16l-5-5H3zm13-2c3 3 3 7 0 10m3-13c5 5 5 11 0 16"/>',
  ended:'<circle cx="12" cy="12" r="9"/><path d="M8 8h8v8H8z"/>',
  error:'<path d="m12 2 11 19H1zm0 6v6m0 3v1"/>',
  watchdog:'<path d="M2 12h4l3-7 5 15 3-8h5"/><circle cx="12" cy="12" r="10"/>',
  reflection:'<path d="M3 3h8v18H3zm11 1h5v16h-5M6 7v6m8-2h7m-3-3 3 3-3 3"/>',
  repeat:'<path d="M4 10V6h15l-4-4m4 4-4 4m5 4v4H5l4 4m-4-4 4-4"/>',
  gazette:'<path d="M4 3h16v19H4zM8 7h8M8 11h3v4H8zm6 0h2m-2 4h2m-8 4h8"/>',
  paper_tint:'<path d="M3 3h13v7M3 3v18h14v-4m-11-9h6m-6 4h5m7-3 5 4-5 8-5-8z"/>',
  edition:'<path d="M5 2h15v19H5zM5 7H2v14h18M9 6h7m-7 4h7m-7 4h2m3 0h2m-7 3h7"/>',
};
const STATUS_COLOR = {fail:0xf19379,error:0xf19379,held:0xcaa675,start:0xa8e6b4,playing:0xb7f3aa,ok:0x84cbb3,ended:0x84cbb3};
const MAX_EVENTS = 5000;

export function mergeFlowEvents(existing, incoming, sessionChanged=false) {
  const rows = new Map((sessionChanged ? [] : existing).map(row => [Number(row.id), row]));
  for (const row of incoming || []) {
    if (Number.isSafeInteger(Number(row.id)) && Number(row.id) > 0) rows.set(Number(row.id), row);
  }
  return Array.from(rows.values()).sort((a,b) => Number(a.id)-Number(b.id));
}
export function flowEventEdge(event, events, edges) {
  const parent = event.parent_id == null ? null : events.find(row => String(row.id) === String(event.parent_id));
  const from = event.from || (parent && parent.node);
  if (!from || from === event.node) return null;
  return edges.find(edge => edge.from === from && edge.to === event.node) || null;
}
export function filterFlowEvents(events, node, query) {
  const needle = String(query || "").trim().toLowerCase();
  return events.filter(row => (!node || row.node === node) && (!needle ||
    [row.id,row.node,row.status,row.summary,row.trace_id,JSON.stringify(row.details || {})].join(" ").toLowerCase().includes(needle)));
}
export function flowNodePosition(id, index=0) {
  const xy = POSITIONS[id] || [index % 6, 5 + Math.floor(index/6)];
  return {x:xy[0]*175, y:-xy[1]*145};
}
function dom(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = String(text);
  return node;
}
function time(at) {
  return at ? new Date(Number(at)*1000).toLocaleTimeString([], {hour12:false}) : "—";
}
function json(value) { return JSON.stringify(value == null ? {} : value, null, 2); }
function detailsBlock(label, value, open=false) {
  const block = dom("details"); block.open = open;
  block.append(dom("summary", "", label), dom("pre", "", typeof value === "string" ? value : json(value)));
  return block;
}

export async function openStationFlow({request, onClose=()=>{}}={}) {
  if (typeof request !== "function") request = async (path, options={}) => {
    const response = await fetch(path, {cache:"no-store",...options});
    if (!response.ok) throw new Error(`Flow journal: HTTP ${response.status}`);
    return response.json();
  };
  const returnFocus = document.activeElement;
  let alive=true, sceneView=null, timer=null, cursor=0, session="", allEvents=[], nodes=[], edges=[], selected=null;
  let showing=150, firstPull=true, pausedMotion=matchMedia("(prefers-reduced-motion: reduce)").matches, listMode=false;
  let lastResponse=0, lastPayload=null, pollInFlight=false, historyMore=false, historyBusy=false;
  const pendingRequests=new Set();
  async function journal(path){
    const controller=new AbortController();pendingRequests.add(controller);
    const timeout=setTimeout(()=>controller.abort(),15000);
    try{return await request(path,{signal:controller.signal});}
    finally{clearTimeout(timeout);pendingRequests.delete(controller);}
  }
  const shade=dom("div","sf-shade"), dialog=dom("section","sf-dialog");
  shade.id="stationFlowModal";
  dialog.setAttribute("role","dialog");dialog.setAttribute("aria-modal","true");dialog.setAttribute("aria-labelledby","sfTitle");
  const header=dom("header","sf-header"), title=dom("div","sf-title");
  const h2=dom("h2","","The station, in motion"); h2.id="sfTitle";
  title.append(dom("div","sf-kicker","Pine Box / content observatory"),h2,dom("div","sf-subtitle","Every source, decision, rewrite and audible delivery. Select any step to inspect its evidence."));
  const live=dom("span","sf-live","Connecting"), closeBtn=dom("button","","Close ×");
  closeBtn.setAttribute("aria-label","Close station flow");closeBtn.onclick=close;
  header.append(title,live,closeBtn);
  const health=dom("div","sf-health"), main=dom("div","sf-main"), left=dom("div","sf-left"), controls=dom("nav","sf-controls");
  controls.setAttribute("aria-label","Flow map controls");
  const fitBtn=dom("button","","Fit all"), zoomIn=dom("button","","+"), zoomOut=dom("button","","−"), motionBtn=dom("button"), listBtn=dom("button","","List view"), connectionsBtn=dom("button","","Connections");
  zoomIn.setAttribute("aria-label","Zoom in");zoomOut.setAttribute("aria-label","Zoom out");
  fitBtn.onclick=()=>sceneView?.fit();zoomIn.onclick=()=>sceneView?.zoom(1.22);zoomOut.onclick=()=>sceneView?.zoom(1/1.22);
  function motionLabel(){motionBtn.textContent=pausedMotion ? "Motion paused" : "Pause motion";motionBtn.setAttribute("aria-pressed",String(pausedMotion));}
  motionLabel();motionBtn.onclick=()=>{pausedMotion=!pausedMotion;motionLabel();};
  listBtn.onclick=()=>{listMode=!listMode;stage.classList.toggle("sf-list",listMode);listBtn.setAttribute("aria-pressed",String(listMode));listBtn.textContent=listMode?"Map view":"List view";sceneView?.resize();};
  connectionsBtn.onclick=()=>{
    selected=null;inspector.replaceChildren(dom("div","sf-kicker","Process connections"),dom("h3","","Every handoff and loop"),dom("p","","Select a connection to inspect its purpose and observed handoffs."));
    for(const edge of edges){const button=dom("button","sf-detail-event",`${nodeName(edge.from)} → ${nodeName(edge.to)}${edge.feedback?" · feedback":""}`);button.onclick=()=>selectEdge(edge.id);inspector.append(button);}markSelection();
  };
  controls.append(fitBtn,zoomOut,zoomIn,motionBtn,listBtn,connectionsBtn,dom("span","sf-hint","Drag to pan · scroll to zoom · click to inspect"));
  const stage=dom("div","sf-stage"), labels=dom("div","sf-labels"), placeholder=dom("div","sf-empty","Waiting for the station journal…");
  stage.setAttribute("role","group");stage.setAttribute("aria-label","Interactive station process map");stage.append(labels,placeholder);
  const legend=dom("div","sf-legend");legend.append(dom("span","","Process connection"),dom("span","sf-feedback","Repair / feedback"),dom("span","sf-dot","Observed event"));
  left.append(controls,stage,legend);
  const sidebar=dom("aside","sf-sidebar"), inspector=dom("section","sf-inspector"), eventsHead=dom("div","sf-events-head"), count=dom("small");
  inspector.setAttribute("aria-label","Selected step or event details");
  inspector.append(dom("div","sf-kicker","Inspect the evidence"),dom("h3","","Follow a piece of content"),dom("p","sf-empty-detail","Select a step for its current state and history, or an event below for the exact source, text, judgments, retries and playback acknowledgments recorded by the station."),dom("p","sf-empty-detail","Moving packets represent reported events. A published file has not aired until audible playback is acknowledged."));
  const filters=dom("div","sf-filters"), nodeSelect=dom("select"), search=dom("input");
  nodeSelect.setAttribute("aria-label","Filter events by pipeline step");nodeSelect.append(new Option("All steps",""));
  search.type="search";search.placeholder="Find text or trace ID";search.setAttribute("aria-label","Search event text, trace ID and details");
  nodeSelect.onchange=()=>{showing=150;renderEvents();};search.oninput=()=>{showing=150;renderEvents();};filters.append(nodeSelect,search);
  eventsHead.append(dom("strong","","EVENT JOURNAL"),count,filters);
  const log=dom("div","sf-events");log.setAttribute("aria-label","Station event journal");
  const footer=dom("div","sf-footer"), footnote=dom("span","","Live journal · waiting"), more=dom("button","","More"), earlier=dom("button","","Earlier"), exportBtn=dom("button","","Export");
  more.onclick=()=>{showing+=150;renderEvents();};earlier.onclick=loadEarlier;
  exportBtn.title="Download the loaded event journal and graph as JSON";
  exportBtn.onclick=()=>{
    const blob=new Blob([json({exported_at:new Date().toISOString(),session,cursor,nodes,edges,events:allEvents,health:lastPayload?.health,journal:lastPayload?.journal})],{type:"application/json"});
    const url=URL.createObjectURL(blob), a=dom("a");a.href=url;a.download="pine-station-flow.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  footer.append(footnote,more,earlier,exportBtn);sidebar.append(inspector,eventsHead,log,footer);main.append(left,sidebar);dialog.append(header,health,main);shade.append(dialog);document.body.append(shade);closeBtn.focus();
  shade.addEventListener("pointerdown",event=>{if(event.target===shade)close();});
  const keydown=event=>{
    if(event.key==="Escape"){event.preventDefault();event.stopImmediatePropagation();close();return;}
    if(event.key!=="Tab")return;
    const focusable=Array.from(dialog.querySelectorAll("button,input,select,summary,[tabindex='0']")).filter(node=>!node.disabled&&node.getClientRects().length);
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  };
  document.addEventListener("keydown",keydown,true);
  const buttons=new Map();
  function nodeName(id){return nodes.find(row=>row.id===id)?.label||id||"Station";}
  function selectNode(id){
    selected={type:"node",id};inspector.replaceChildren();const node=nodes.find(row=>row.id===id);if(!node)return;
    inspector.append(dom("div","sf-kicker","Pipeline step / "+node.id),dom("h3","",node.label),dom("p","",node.description||"No description recorded."),dom("div","sf-meta",`${node.status||"idle"} · ${node.count||0} observed events\nLast event ${time(node.last_at)}`));
    const actions=dom("div","sf-detail-actions"), filter=dom("button","","Show this step's events"), clear=dom("button","","Show all steps");
    filter.onclick=()=>{nodeSelect.value=id;showing=150;renderEvents();};clear.onclick=()=>{nodeSelect.value="";search.value="";renderEvents();};actions.append(filter,clear);inspector.append(actions,detailsBlock("Current step details",node.details||{},true));
    const related=allEvents.filter(row=>row.node===id).slice(-6).reverse();
    if(!related.length)inspector.append(dom("p","sf-empty-detail","No recorded events for this step in the loaded journal."));
    for(const row of related){const btn=dom("button","sf-detail-event",`${time(row.at)} · ${row.status} · ${row.summary}`);btn.onclick=()=>selectEvent(row.id);inspector.append(btn);}
    markSelection();
  }
  function selectEvent(id){
    const event=allEvents.find(row=>Number(row.id)===Number(id));if(!event)return;
    selected={type:"event",id:Number(id),node:event.node};inspector.replaceChildren();
    inspector.append(dom("div","sf-kicker",`Event ${event.id} / ${event.status}`),dom("h3","",nodeName(event.node)),dom("p","",event.summary),dom("div","sf-meta",`${new Date(Number(event.at)*1000).toLocaleString()}\nTrace: ${event.trace_id||"not recorded"}${event.parent_id?"\nParent event: "+event.parent_id:""}`));
    const actions=dom("div","sf-detail-actions");
    if(event.trace_id){const trace=dom("button","","Follow this trace");trace.onclick=()=>{nodeSelect.value="";search.value=event.trace_id;showing=150;renderEvents();};actions.append(trace);}
    const step=dom("button","","Inspect step");step.onclick=()=>selectNode(event.node);actions.append(step);
    if(event.parent_id){const parent=dom("button","","Inspect parent event");parent.disabled=!allEvents.some(row=>String(row.id)===String(event.parent_id));parent.onclick=()=>selectEvent(event.parent_id);actions.append(parent);}
    inspector.append(actions,detailsBlock("Event evidence",event.details||{},true),detailsBlock("Complete event record",event));markSelection();
  }
  function selectEdge(id){
    const edge=edges.find(row=>row.id===id);if(!edge)return;
    selected={type:"edge",id};inspector.replaceChildren(dom("div","sf-kicker",edge.feedback?"Feedback connection":"Process connection"),dom("h3","",`${nodeName(edge.from)} → ${nodeName(edge.to)}`),dom("p","",edge.label||"Content moves between these steps when the station reports a handoff."));
    const actions=dom("div","sf-detail-actions");
    for(const nodeId of [edge.from,edge.to]){const button=dom("button","",nodeName(nodeId));button.onclick=()=>selectNode(nodeId);actions.append(button);}
    inspector.append(actions,detailsBlock("Connection record",edge));
    const related=allEvents.filter(row=>flowEventEdge(row,allEvents,edges)?.id===id).slice(-10).reverse();
    if(!related.length)inspector.append(dom("p","sf-empty-detail","No explicitly linked handoff has been recorded for this connection in the loaded journal."));
    for(const row of related){const button=dom("button","sf-detail-event",`${time(row.at)} · ${row.summary}`);button.onclick=()=>selectEvent(row.id);inspector.append(button);}markSelection();
  }
  function markSelection(){
    for(const [id,btn]of buttons)btn.setAttribute("aria-pressed",String(id===(selected?.node||selected?.id)));
    for(const btn of log.querySelectorAll("[data-event]"))btn.setAttribute("aria-pressed",String(selected?.type==="event"&&Number(btn.dataset.event)===selected.id));
  }
  function renderEvents(){
    const filtered=filterFlowEvents(allEvents,nodeSelect.value,search.value), rows=filtered.slice(-showing).reverse();
    const scroll=log.scrollTop;log.replaceChildren();count.textContent=`${filtered.length} / ${allEvents.length}`;
    if(!rows.length)log.append(dom("p","sf-events-note",allEvents.length?"No events match this filter.":"No events have been reported yet. The map stays still until the station reports activity."));
    for(const row of rows){
      const button=dom("button","sf-event");button.dataset.event=String(row.id);button.dataset.status=row.status;
      const label=dom("b","",nodeName(row.node));label.append(dom("i","",row.status));
      button.append(dom("time","",time(row.at)),label,dom("span","",row.summary));button.title=`Event ${row.id}: ${row.summary}`;button.onclick=()=>selectEvent(row.id);log.append(button);
    }
    more.hidden=filtered.length<=showing;earlier.hidden=!historyMore;earlier.disabled=historyBusy;log.scrollTop=scroll;markSelection();
  }
  async function loadEarlier(){
    if(historyBusy||!allEvents.length)return;historyBusy=true;earlier.disabled=true;
    const requestedSession=session;
    try{
      const payload=await journal(`/api/dj/flow?before=${allEvents[0].id}&limit=300`);
      if(!alive||session!==requestedSession||payload.session!==session)return;
      // This is a history page, never a change to the live polling cursor.
      allEvents=mergeFlowEvents(allEvents,payload.events).slice(0,MAX_EVENTS);historyMore=!!payload.history_more;showing+=300;renderEvents();
      footnote.textContent=`${allEvents.length} loaded${allEvents.length>=MAX_EVENTS?" · 5,000-event view limit; export to retain this page":""}`;
    }catch(error){if(alive)footnote.textContent=String(error?.message||error);}
    finally{historyBusy=false;if(alive)earlier.disabled=false;}
  }
  function renderHealth(payload){
    const h=payload.health||{};health.replaceChildren();
    const gap=h.talk_gap_seconds==null?NaN:Number(h.talk_gap_seconds),target=h.talk_gap_target==null?NaN:Number(h.talk_gap_target);
    for(const [label,alert] of [[h.paused?"STATION PAUSED":h.on?"STATION ON":"STATION OFF",false],[`Speech gap ${Number.isFinite(gap)?gap.toFixed(1)+"s":"unknown"} / ${Number.isFinite(target)?target+"s":"—"}`,h.on&&!h.paused&&gap>target],[`Last audible speech ${time(typeof h.last_speech==="object"?h.last_speech?.at:h.last_speech)}`,false],[`Crystal coverage target ${h.coverage_target??"—"}%`,false]])health.append(dom("span",alert?"sf-alert":"",label));
    if(payload.journal?.error)health.append(dom("span","sf-alert",payload.journal.error));
  }
  function renderNodes(){
    const options=new Set(Array.from(nodeSelect.options).map(row=>row.value));
    for(const node of nodes){
      let button=buttons.get(node.id);
      if(!button){
        button=dom("button","sf-node");button.dataset.node=node.id;
        const icon=dom("span","sf-icon");icon.setAttribute("aria-hidden","true");
        icon.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+(ICON_PATHS[node.id]||'<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>')+'</svg>';
        button.append(icon,dom("b","",node.label),dom("small"));button.onclick=()=>selectNode(node.id);buttons.set(node.id,button);labels.append(button);
      }
      button.dataset.status=node.status||"idle";button.querySelector("b").textContent=node.label;button.querySelector("small").textContent=`${node.status||"idle"} · ${node.count||0}`;button.title=`${node.description||node.label}\n${node.count||0} recorded events; last ${time(node.last_at)}`;
      button.setAttribute("aria-label",`${node.label}, ${node.status||"idle"}, ${node.count||0} observed events. Inspect details.`);
      if(!options.has(node.id)){nodeSelect.append(new Option(node.label,node.id));options.add(node.id);}
    }
    markSelection();
  }
  async function pull(){
    if(!alive||pollInFlight)return;pollInFlight=true;
    let nextDelay=1800;
    try{
      const payload=await journal(`/api/dj/flow?after=${cursor}&limit=300`);if(!alive)return;
      if(!Array.isArray(payload.nodes)||!Array.isArray(payload.events))throw new Error("The station did not return a flow journal.");
      const changed=!!session&&session!==payload.session;
      const oldIds=new Set((changed?[]:allEvents).map(row=>Number(row.id)));
      if(changed){cursor=0;selected=null;firstPull=true;}
      nodes=payload.nodes;edges=payload.edges||[];session=payload.session||session;
      allEvents=mergeFlowEvents(allEvents,payload.events,changed).slice(-MAX_EVENTS);cursor=Number(payload.cursor)||cursor;lastResponse=Date.now();lastPayload=payload;
      historyMore=payload.oldest!=null?(allEvents.length>0&&Number(payload.oldest)<Number(allEvents[0].id)):!!payload.history_more;
      placeholder.remove();renderNodes();renderEvents();renderHealth(payload);sceneView?.sync(nodes,edges);
      // Loaded history is inspectable; only arrivals from the present animate.
      if(!firstPull)for(const event of payload.events){
        if(oldIds.has(Number(event.id))||Number(payload.now)-Number(event.at)>10)continue;
        sceneView?.pulse(event,flowEventEdge(event,allEvents,edges));
      }
      firstPull=false;live.textContent="Live journal";live.dataset.status="ok";
      footnote.textContent=`${allEvents.length} loaded · updated ${time(payload.now)}${payload.truncated?" · catching up":""}`;
      if(payload.truncated&&payload.events.length)nextDelay=60;
      if(!sceneView&&!listMode)sceneView=await createScene();
    }catch(error){
      if(!alive)return;live.textContent="Journal unavailable";live.dataset.status="error";footnote.textContent=String(error?.message||error);
      if(!allEvents.length)placeholder.textContent=`The journal is unavailable. ${error?.message||error} Retrying…`;
    }finally{pollInFlight=false;if(alive)timer=setTimeout(pull,nextDelay);}
  }
  async function createScene(){
    let THREE,renderer;
    try{THREE=await import("/vendor/three.module.js");if(!alive)return null;renderer=new THREE.WebGLRenderer({alpha:true,antialias:true});}
    catch(error){
      if(!alive)return null;listMode=true;stage.classList.add("sf-list");listBtn.textContent="List view";listBtn.disabled=true;
      for(const btn of [fitBtn,zoomIn,zoomOut,motionBtn])btn.disabled=true;
      left.insertBefore(dom("div","sf-error-banner","3D rendering is unavailable. Every step, event and detail remains accessible in the list."),stage);return null;
    }
    if(!alive){renderer.dispose();return null;}
    const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-600,600,380,-380,.1,500);
    camera.position.set(475,-290,100);camera.lookAt(475,-290,0);
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));stage.insertBefore(renderer.domElement,labels);renderer.domElement.setAttribute("aria-hidden","true");
    let width=1,height=1,scale=1,pan={x:475,y:-290},raf=0,lastFrame=0,disposed=false,dirty=true,signature="",graph=new THREE.Group();scene.add(graph);
    const nodeMeshes=new Map(),edgeMeshes=new Map(),packets=[],lanes=[];
    LANE_TITLES.forEach((label,index)=>{const lane=dom("span","sf-lane",label);labels.append(lane);lanes.push({el:lane,x:-72,y:52-index*145});});
    const material=(color,opacity=1)=>new THREE.MeshBasicMaterial({color,transparent:opacity<1,opacity,depthWrite:false});
    function disposeObject(object){object.traverse(child=>{child.geometry?.dispose();if(Array.isArray(child.material))child.material.forEach(m=>m.dispose());else child.material?.dispose();});}
    function build(nextNodes,nextEdges){
      const nextSignature=JSON.stringify([nextNodes.map(n=>n.id),nextEdges.map(e=>[e.id,e.from,e.to,e.feedback])]);
      if(nextSignature!==signature){
        disposeObject(graph);scene.remove(graph);graph=new THREE.Group();scene.add(graph);nodeMeshes.clear();edgeMeshes.clear();signature=nextSignature;
        nextNodes.forEach((node,index)=>{
          const at=flowNodePosition(node.id,index),color=STATUS_COLOR[node.status]||0x528f91;
          const shape=new THREE.Mesh(new THREE.RingGeometry(17,18.5,32),material(color,.45));shape.position.set(at.x-51,at.y,1);graph.add(shape);nodeMeshes.set(node.id,{mesh:shape,at,active:0});
        });
        nextEdges.forEach(edge=>{
          const from=nodeMeshes.get(edge.from),to=nodeMeshes.get(edge.to);if(!from||!to)return;
          const a=new THREE.Vector3(from.at.x,from.at.y,0),b=new THREE.Vector3(to.at.x,to.at.y,0),dx=b.x-a.x,dy=b.y-a.y;
          const horizontal=Math.abs(dx)>Math.abs(dy)*1.15;
          if(horizontal){a.x+=Math.sign(dx)*77;b.x-=Math.sign(dx)*77;}else{a.y+=Math.sign(dy)*42;b.y-=Math.sign(dy)*42;}
          const sameRow=Math.abs(dy)<1&&Math.abs(dx)>240;
          if(sameRow){a.set(from.at.x,from.at.y+(edge.feedback?-42:42),0);b.set(to.at.x,to.at.y+(edge.feedback?-42:42),0);}
          const c1=a.clone(),c2=b.clone();
          if(sameRow){const bend=edge.feedback?-67:67;c1.y+=bend;c2.y+=bend;}
          else if(edge.feedback){const bend=64+(edge.from.length%3)*13;c1.y-=bend;c2.y-=bend;}
          else if(horizontal){c1.x+=(b.x-a.x)*.48;c2.x-=(b.x-a.x)*.48;}
          else{c1.y+=(b.y-a.y)*.48;c2.y-=(b.y-a.y)*.48;}
          const curve=new THREE.CubicBezierCurve3(a,c1,c2,b),geometry=new THREE.BufferGeometry().setFromPoints(curve.getPoints(44));
          const mat=edge.feedback?new THREE.LineDashedMaterial({color:0x9e805e,dashSize:4,gapSize:5,transparent:true,opacity:.6}):new THREE.LineBasicMaterial({color:0x416c70,transparent:true,opacity:.7});
          const line=new THREE.Line(geometry,mat);line.userData.flowEdge=edge.id;line.computeLineDistances();graph.add(line);
          const point=curve.getPoint(.97),tangent=curve.getTangent(.97),arrow=new THREE.Mesh(new THREE.ConeGeometry(2.6,8,3),material(edge.feedback?0xbc9b70:0x679d9e,.9));
          arrow.position.copy(point);arrow.rotation.z=Math.atan2(tangent.y,tangent.x)-Math.PI/2;graph.add(arrow);edgeMeshes.set(edge.id,{curve,line,edge});
        });
      }
      for(const node of nextNodes){const item=nodeMeshes.get(node.id);if(item)item.mesh.material.color.setHex(STATUS_COLOR[node.status]||0x528f91);}
      dirty=true;project();
    }
    function project(){
      camera.left=-width/(2*scale);camera.right=width/(2*scale);camera.top=height/(2*scale);camera.bottom=-height/(2*scale);camera.position.set(pan.x,pan.y,100);camera.updateProjectionMatrix();camera.updateMatrixWorld();
      for(const [id,button]of buttons){const at=nodeMeshes.get(id)?.at;if(!at)continue;button.style.left=`${width/2+(at.x-pan.x)*scale}px`;button.style.top=`${height/2-(at.y-pan.y)*scale}px`;button.style.transform=`translate(-50%,-50%) scale(${scale})`;}
      for(const lane of lanes){lane.el.style.left=`${width/2+(lane.x-pan.x)*scale}px`;lane.el.style.top=`${height/2-(lane.y-pan.y)*scale}px`;lane.el.style.transform=`translateY(-50%) scale(${scale})`;}
      dirty=true;
    }
    function fit(){
      const positions=Array.from(nodeMeshes.values()).map(row=>row.at);
      const minX=Math.min(0,...positions.map(row=>row.x))-88,maxX=Math.max(1050,...positions.map(row=>row.x))+88;
      const minY=Math.min(-580,...positions.map(row=>row.y))-45,maxY=Math.max(0,...positions.map(row=>row.y))+114;
      scale=Math.max(.12,Math.min((width-35)/(maxX-minX),(height-30)/(maxY-minY),1.35));pan={x:(minX+maxX)/2,y:(minY+maxY)/2};project();
    }
    function zoom(factor){scale=Math.max(.25,Math.min(2.5,scale*factor));project();}
    function resize(){if(disposed)return;width=Math.max(1,stage.clientWidth);height=Math.max(1,stage.clientHeight);renderer.setSize(width,height);if(lastFrame===0)fit();else project();}
    const ro=new ResizeObserver(resize);ro.observe(stage);
    let drag=null;
    const pointerDown=event=>{if(event.target.closest("button"))return;drag={x:event.clientX,y:event.clientY,pan:{...pan}};stage.setPointerCapture(event.pointerId);};
    const pointerMove=event=>{if(!drag||listMode)return;pan.x=drag.pan.x-(event.clientX-drag.x)/scale;pan.y=drag.pan.y+(event.clientY-drag.y)/scale;project();};
    const raycaster=new THREE.Raycaster();raycaster.params.Line.threshold=5;
    const pointerUp=event=>{
      if(drag&&!listMode&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<5){
        const rect=stage.getBoundingClientRect(),point=new THREE.Vector2((event.clientX-rect.left)/width*2-1,-(event.clientY-rect.top)/height*2+1);
        raycaster.setFromCamera(point,camera);const hit=raycaster.intersectObjects(Array.from(edgeMeshes.values()).map(row=>row.line))[0];
        if(hit)selectEdge(hit.object.userData.flowEdge);
      }
      drag=null;
    };
    const wheel=event=>{if(listMode)return;event.preventDefault();zoom(Math.exp(-event.deltaY*.001));};
    stage.addEventListener("pointerdown",pointerDown);stage.addEventListener("pointermove",pointerMove);stage.addEventListener("pointerup",pointerUp);stage.addEventListener("pointercancel",pointerUp);stage.addEventListener("wheel",wheel,{passive:false});
    function pulse(event,edge){
      if(disposed||pausedMotion||listMode)return;
      const item=nodeMeshes.get(event.node);if(item)item.active=1;
      buttons.get(event.node)?.querySelector(".sf-icon")?.animate([
        {transform:"scale(1)",color:"#a2d3be"},{transform:"scale(1.22)",color:"#f0ffe8"},{transform:"scale(1)",color:"#a2d3be"}
      ],{duration:1250,easing:"ease-out"});
      const wire=edge&&edgeMeshes.get(edge.id);if(!wire)return;
      const packet=new THREE.Mesh(new THREE.SphereGeometry(3.6,8,6),material(STATUS_COLOR[event.status]||0xaaf0c5));packet.position.copy(wire.curve.getPoint(0));scene.add(packet);
      packets.push({mesh:packet,curve:wire.curve,start:performance.now(),duration:1500});
      if(packets.length>100){const old=packets.shift();scene.remove(old.mesh);disposeObject(old.mesh);}dirty=true;
    }
    function frame(now){
      if(disposed||!alive)return;raf=requestAnimationFrame(frame);if(now-lastFrame<32)return;const dt=Math.min(.2,(now-lastFrame)/1000);lastFrame=now;
      let active=false;
      for(let i=packets.length-1;i>=0;i--){const packet=packets[i],t=(now-packet.start)/packet.duration;if(t>=1||pausedMotion){scene.remove(packet.mesh);disposeObject(packet.mesh);packets.splice(i,1);dirty=true;continue;}packet.mesh.position.copy(packet.curve.getPoint(t));active=true;}
      for(const node of nodeMeshes.values())if(node.active>0){node.active=Math.max(0,node.active-dt*.7);node.mesh.scale.setScalar(1+node.active*.45);node.mesh.material.opacity=.45+node.active*.5;active=true;}
      if(!listMode&&!document.hidden&&(active||dirty)){renderer.render(scene,camera);dirty=false;}
      if(lastResponse&&Date.now()-lastResponse>10000&&live.dataset.status!=="error")live.textContent="Waiting for updates";
    }
    build(nodes,edges);resize();fit();raf=requestAnimationFrame(frame);
    return {sync:build,fit,zoom,resize,pulse,dispose(){
      if(disposed)return;disposed=true;cancelAnimationFrame(raf);ro.disconnect();stage.removeEventListener("pointerdown",pointerDown);stage.removeEventListener("pointermove",pointerMove);stage.removeEventListener("pointerup",pointerUp);stage.removeEventListener("pointercancel",pointerUp);stage.removeEventListener("wheel",wheel);disposeObject(graph);for(const packet of packets)disposeObject(packet.mesh);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();for(const lane of lanes)lane.el.remove();
    }};
  }
  function close(){
    if(!alive)return;alive=false;clearTimeout(timer);for(const controller of pendingRequests)controller.abort();sceneView?.dispose();document.removeEventListener("keydown",keydown,true);shade.remove();if(returnFocus?.isConnected)returnFocus.focus();onClose();
  }
  pull();
  return {close,element:shade};
}
