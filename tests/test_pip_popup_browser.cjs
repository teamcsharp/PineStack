const {app,BrowserWindow}=require('electron'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'pine-popup-qa-'));app.setPath('userData',temp);let win;const delay=ms=>new Promise(r=>setTimeout(r,ms));const deadline=setTimeout(()=>app.exit(1),45000);
app.whenReady().then(async()=>{
 const root=path.resolve(__dirname,'..'),file=path.join(temp,'index.html');
 fs.writeFileSync(file,`<html><head><link rel="stylesheet" href="${require('node:url').pathToFileURL(path.join(root,'desktop/renderer/pine-pip.css')).href}"></head><body class="pine-pip"><main><section id="control"></section><section id="script" hidden><button>Adjust script</button></section></main><aside class="test-popup" id="closed" style="position:fixed;display:none"><button aria-label="Close">x</button></aside><script>
 window.saved={};window.pineDesktop={pipUpdate:async p=>{saved=p;return p}};
 window.PinePopBack={isPopup:el=>el.classList.contains('test-popup')};
 window.PineOrchGlass={open(){const d=document.createElement('aside');d.id='orchestra';d.className='test-popup';d.innerHTML='<button aria-label="Close">x</button><input aria-label="Orchestra setting" value="1">';document.body.appendChild(d)},close(){document.getElementById('orchestra')?.remove()}};
 window.PineThreeFull={HOST_ID:'scene',list:async()=>({ok:true,rows:[{key:'extra',label:'Extra scene'}]}),show:async key=>{const n=document.createElement('div');n.id='scene';n.textContent=key;document.body.appendChild(n)},close:async()=>document.getElementById('scene')?.remove()};
 window.PinePopupScenes=[{key:'sys3',name:'System 3'},{key:'flow',name:'Station flow'}];
 window.PineViewChrome={show:id=>{const s=document.getElementById('script');s.hidden=id!=='script'}};
 </script><script src="${require('node:url').pathToFileURL(path.join(root,'desktop/renderer/pine-pip-popups.js')).href}"></script></body></html>`);
 win=new BrowserWindow({show:false,width:1000,height:600,webPreferences:{offscreen:true,sandbox:false}});await win.loadFile(file);
 await win.webContents.executeJavaScript(`PinePipPopups.sync({active:true,popupFavorites:[]});PinePipPopups.open();PinePipPopups.select('module:PineOrchGlass')`);await delay(100);
 assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.getElementById('closed')).display`),'none','closed cached popups stay closed');
 let result=await win.webContents.executeJavaScript(`(()=>{const n=document.getElementById('orchestra'),r=n.getBoundingClientRect();n.querySelector('input').value='adjusted';return {visible:getComputedStyle(n).display,inside:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,input:n.querySelector('input').value,scenes:PinePipPopups.catalog().filter(e=>e.group==='3JS').length}})()`);
 assert.deepEqual(result,{visible:'block',inside:true,input:'adjusted',scenes:3});
 await win.webContents.executeJavaScript(`document.querySelector('[data-popup="module:PineOrchGlass"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));`);
 assert.deepEqual(await win.webContents.executeJavaScript('saved.popupFavorites'),['module:PineOrchGlass']);
 assert.equal(await win.webContents.executeJavaScript(`document.querySelector('#pinePipFavorites [data-popup="module:PineOrchGlass"]').textContent`),'Orchestra controls');
 await win.webContents.executeJavaScript(`PinePipPopups.select('scene:sys3')`);await delay(100);assert.equal(await win.webContents.executeJavaScript(`document.getElementById('scene').textContent`),'sys3');
 await win.webContents.executeJavaScript(`PinePipPopups.select('view:script')`);await delay(100);assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.getElementById('script')).visibility`),'visible');
 win.setSize(320,300);await delay(100);assert.equal(await win.webContents.executeJavaScript(`(()=>{const r=document.getElementById('script').getBoundingClientRect();return r.right<=innerWidth&&r.bottom<=innerHeight&&r.width>0})()`),true,'controls fit a narrow PiP window');
 await win.webContents.executeJavaScript(`PinePipPopups.close()`);assert.equal(await win.webContents.executeJavaScript('PinePipPopups.state().opened'),false);
 console.log('Popup browser QA passed: orchestra adjustment, all/dynamic 3JS entries, sidebar cycling, right-click favorites, quick bar, cached popup isolation, narrow layout and cleanup.');win.destroy();clearTimeout(deadline);app.exit(0);
}).catch(e=>{console.error(e);clearTimeout(deadline);app.exit(1)});
