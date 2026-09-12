// Hidden Chromium visual check of the actual typesetter output. No station mutations.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const folder = process.argv[2];
app.setPath('userData', path.join(folder, 'browser-profile'));
app.whenReady().then(async () => {
  let win;
  try {
    win = new BrowserWindow({show:false,width:1114,height:1750,
      webPreferences:{offscreen:true,contextIsolation:true,backgroundThrottling:false}});
    const results=[];
    for(const style of ['broadsheet','tabloid']) {
      await win.loadURL(pathToFileURL(path.join(folder,style+'.html')).href);
      await win.webContents.executeJavaScript(`document.fonts.ready.then(()=>{document.querySelectorAll('img').forEach(i=>i.loading='eager');return true})`);
      await new Promise(resolve=>setTimeout(resolve,3500));
      const result=await win.webContents.executeJavaScript(`(() => {
        const page=document.querySelector('.page'), lead=document.querySelector('.reference-lead');
        const overlay=document.querySelector('.reference-overlay'), photo=document.querySelector('.reference-photo');
        const flows=[...document.querySelectorAll('.flow')];
        const overflows=flows.filter(f=>{
          const e=f.querySelector(':scope > .fitend');if(!e)return false;
          const r=f.getBoundingClientRect(),b=e.getBoundingClientRect();
          return b.right>r.right+2 || b.top>r.bottom+2;
        }).map(f=>({page:f.closest('.page')?.dataset.page,class:f.className,
          width:f.clientWidth,height:f.clientHeight,scrollWidth:f.scrollWidth}));
        const images=[...document.querySelectorAll('img')];
        return {style:document.body.dataset.style,pages:document.querySelectorAll('.page').length,
          geometry:{width:page.offsetWidth,height:page.offsetHeight},
          masthead:document.querySelector('h1')?.textContent.replace(/\\s+/g,' ').trim(),
          fontLoaded:document.fonts.check('94px "Pine Gazette Blackletter"'),
          imageCount:images.length,loadedImages:images.filter(i=>i.naturalWidth>0).length,
          referenceLead:!!lead,overlayFits:!overlay||overlay.offsetHeight<=photo.offsetHeight,
          overlayHeight:overlay?.offsetHeight,photoHeight:photo?.offsetHeight,overflows,
          articleCount:document.querySelectorAll('article').length};
      })()`);
      results.push(result);
      fs.writeFileSync(path.join(folder,style+'-front.png'),(await win.webContents.capturePage()).toPNG());
      await win.webContents.executeJavaScript(`document.querySelectorAll('.page').forEach((p,i)=>p.style.display=i===1?'':'none');document.querySelector('.sheetwrap').style.padding='0';`);
      await new Promise(resolve=>setTimeout(resolve,300));
      fs.writeFileSync(path.join(folder,style+'-inside.png'),(await win.webContents.capturePage()).toPNG());
      if(style==='broadsheet') {
        win.setSize(390,740);
        await win.webContents.executeJavaScript(`document.querySelectorAll('.page').forEach((p,i)=>p.style.display=i===0?'':'none');window.dispatchEvent(new Event('resize'));`);
        await new Promise(resolve=>setTimeout(resolve,200));
        result.narrow=await win.webContents.executeJavaScript(`({width:document.documentElement.clientWidth,pageRight:document.querySelector('.page').getBoundingClientRect().right,scrollWidth:document.documentElement.scrollWidth})`);
        fs.writeFileSync(path.join(folder,'broadsheet-narrow.png'),(await win.webContents.capturePage()).toPNG());
        win.setSize(1114,1750);
      }
    }
    fs.writeFileSync(path.join(folder,'browser-result.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(results));
    if(results.some(r=>!r.loadedImages||!r.overlayFits||r.overflows.length||r.narrow?.pageRight>r.narrow?.width)) throw Error('Missing images or clipped page content');
    win.destroy(); app.quit();
  } catch(error) {console.error(error);if(win)win.destroy();app.exit(1);}
});
