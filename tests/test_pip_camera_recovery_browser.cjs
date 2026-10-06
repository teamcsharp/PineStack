const {app,BrowserWindow,nativeImage}=require('electron'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{pathToFileURL}=require('node:url');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'pine-cam-recovery-'));app.setPath('userData',temp);let win;const delay=ms=>new Promise(r=>setTimeout(r,ms));const deadline=setTimeout(()=>app.exit(1),40000);
app.whenReady().then(async()=>{
 const image=nativeImage.createFromBitmap(Buffer.from([50,100,150,255]),{width:1,height:1}).toDataURL(),file=path.join(temp,'index.html'),resource=pathToFileURL(path.resolve(__dirname,'../desktop/renderer/pine-pip-camera-recovery.js')).href;
 fs.writeFileSync(file,`<html><body><section class="pip-camera"><img hidden><div role="status">Pine Cam offline - packets are arriving damaged</div></section><script>
 window.fixture={pip:{active:true,cameraOverlay:true,cameraSource:'pine'},reading:{state:'dropped',fresh:true,stream:{class:'decode'},source:{pref:'always',use:'tablet'}},posts:[],displays:0};
 window.pineDesktop={get:async route=>{if(route.includes('doctor'))throw Error('Relay must not reset dongle');return fixture.reading},post:async(route,body)=>{fixture.posts.push(route);fixture.reading={state:'live',fresh:true,frame_age:.1,source:{pref:'always',use:'tablet'}};return {ok:true}},onPipState:cb=>{fixture.onState=cb;return ()=>fixture.onState=null}};
 window.PinePip={state:()=>fixture.pip,repairCamera:async()=>{fixture.displays++;const img=document.querySelector('img');img.onload=()=>{img.hidden=false;document.querySelector('[role=status]').hidden=true};img.src=${JSON.stringify(image)};return {ok:true}}};
 </script><script src="${resource}"></script></body></html>`);
 win=new BrowserWindow({show:false,width:400,height:250,webPreferences:{offscreen:true,sandbox:false}});await win.loadFile(file);
 assert.equal(await win.webContents.executeJavaScript('fixture.posts.length'),0,'watchdog first lets supervisor retry');
 await delay(12500);
 let result=await win.webContents.executeJavaScript(`({posts:fixture.posts,displays:fixture.displays,picture:!document.querySelector('img').hidden&&document.querySelector('img').naturalWidth>0,recovery:__pinePipCameraRecovery.state().phase})`);
 assert.deepEqual(result,{posts:['/api/pinelink/connect'],displays:1,picture:true,recovery:'live'});
 await win.webContents.executeJavaScript(`fixture.reading={state:'dropped',fresh:true,stream:{class:'decode'},source:{pref:'always',use:'tablet'}};document.querySelector('img').hidden=true;document.querySelector('[role=status]').hidden=false;fixture.pip.cameraSource='tab-front';fixture.onState(fixture.pip);`);
 await delay(3200);assert.equal(await win.webContents.executeJavaScript('fixture.posts.length'),1,'changing camera source stops Pine Cam recovery');
 await win.webContents.executeJavaScript(`__pinePipCameraRecovery.dispose();true`);assert.equal(await win.webContents.executeJavaScript('!!window.__pinePipCameraRecovery'),false,'cleanup detaches watchdog');
 console.log('PiP camera browser recovery passed: damaged stream automatically reconnects, fresh image verified, tablet route retained, source change cancels and cleanup completes.');win.destroy();clearTimeout(deadline);app.exit(0);
}).catch(e=>{console.error(e);clearTimeout(deadline);app.exit(1)});
