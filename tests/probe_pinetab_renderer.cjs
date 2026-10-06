// ADB-forward the kiosk WebView to :9234. Inject an ADB tap while this runs.
// This deliberately stalls the renderer to verify the native recovery path.
const assert = require('node:assert/strict');
const sleep = ms => new Promise(r=>setTimeout(r,ms));
async function page() {
  return (await (await fetch('http://127.0.0.1:9234/json')).json()).find(p=>p.type==='page');
}
(async()=>{
  const before=await page(); assert.ok(before);
  const ws=new WebSocket(before.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  const armed=new Promise(r=>{ws.onmessage=e=>{if(JSON.parse(e.data).id===1)r()}});
  ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:
    'setTimeout(()=>{const end=Date.now()+45000;while(Date.now()<end){}},1000);true'}}));
  await armed;
  // Chromium suppresses hang detection while a debugger is attached.
  ws.close();
  console.log('Renderer stall armed; send an ADB tap now.');
  const started=Date.now();
  let after;
  while(Date.now()-started<40000) {
    await sleep(1000);
    try {after=await page();if(after&&after.id!==before.id)break;}catch{}
  }
  assert.ok(after&&after.id!==before.id,'stalled renderer rebuilt within 40 seconds');
  console.log(JSON.stringify({rebuilt:true,seconds:(Date.now()-started)/1000}));
})().catch(e=>{console.error(e);process.exitCode=1});
