// ADB-forward the kiosk WebView DevTools socket to this port first.
// Simulates a camera state change in the view only; the stream keeps running.
const assert = require('node:assert/strict');
(async () => {
  const port = Number(process.env.PINE_CDP_PORT || 9234);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const page = pages.find(p => p.type === 'page' && /8096/.test(p.url));
  assert.ok(page, 'kiosk WebView is available');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const timer = setTimeout(() => { ws.close(); console.error('probe timed out'); process.exitCode = 1; }, 40000);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const expression = `(async()=>{
    if(!PineCam.close.toString().includes('forReconnect')) throw Error('old PineCam asset');
    const bridge=window.pineDesktop, original=bridge.get;
    const before=localStorage.getItem('pineCamView');
    const state=await original.call(bridge,'/api/pinelink/state');
    if(!state.fresh||state.state!=='live') throw Error('camera must be live before probe');
    const sleep=ms=>new Promise(r=>setTimeout(r,ms));
    let simulated=null;
    bridge.get=function(route){return route==='/api/pinelink/state'&&simulated
      ?Promise.resolve(simulated):original.apply(this,arguments)};
    try {
      PineCam.open(false);
      const box=document.querySelector('.pine-cam-box');
      const isShown=()=>box&&!box.hidden;
      if(!isShown()) throw Error('picture did not open');
      simulated=Object.assign({},state,{state:'joining',fresh:false});
      await sleep(6500);
      const hidden=!isShown(), intent=JSON.parse(localStorage.getItem('pineCamView')||'{}').open;
      simulated=state;
      await sleep(6500);
      const restored=isShown(), bare=PineCam.native().bare;
      simulated=Object.assign({},state,{state:'joining',fresh:false});
      await sleep(6500);
      PineCam.close();
      simulated=state;
      await sleep(6500);
      return {hidden,intent,restored,bare,explicitCloseStayedClosed:!isShown()};
    } finally {
      bridge.get=original;
      const pref=JSON.parse(before||'{}');
      if(pref.open) PineCam.open(pref.bare); else PineCam.close();
      if(before===null)localStorage.removeItem('pineCamView');else localStorage.setItem('pineCamView',before);
    }
  })()`;
  const reply = new Promise(resolve => { ws.onmessage = e => { const m=JSON.parse(e.data); if(m.id===1) resolve(m); }; });
  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true,userGesture:true}}));
  const result = await reply;
  clearTimeout(timer); ws.close();
  assert.equal(result.result?.exceptionDetails, undefined, JSON.stringify(result.result?.exceptionDetails));
  const state = result.result?.result?.value;
  console.log(JSON.stringify(state));
  assert.deepEqual(state,{hidden:true,intent:true,restored:true,bare:false,explicitCloseStayedClosed:true});
})().catch(error => { console.error(error); process.exitCode=1; });
