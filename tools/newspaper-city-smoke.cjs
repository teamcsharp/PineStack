const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const folder = process.argv[2];
app.setPath('userData', path.join(folder, 'browser-profile'));
app.whenReady().then(async () => {
  let win;
  try {
    win = new BrowserWindow({show:false, width:1100, height:1450,
      webPreferences:{offscreen:true, contextIsolation:true, backgroundThrottling:false}});
    await win.loadURL(pathToFileURL(path.join(folder, 'edition.html')).href);
    await win.webContents.executeJavaScript('document.fonts.ready.then(()=>true)');
    await win.webContents.executeJavaScript("document.querySelectorAll('img').forEach(img=>img.loading='eager')");
    await new Promise(resolve=>setTimeout(resolve, 4500));
    const metrics = await win.webContents.executeJavaScript(String.raw`(() => {
      const pages = [...document.querySelectorAll('.page')];
      const cards = pages.flatMap(p=>[...p.querySelectorAll('.classifieds .ad')]);
      const texts = cards.map(n=>n.innerText.trim());
      const imageCards = cards.filter(n=>n.querySelector('img'));
      const repeatedPageFillers = pages.flatMap(p=>{
        const seen=new Set(); return [...p.querySelectorAll('.filler:not(.rule),.ad')].map(n=>n.textContent.replace(/\s+/g,' ').trim().slice(0,120)).filter(t=>{
          if(seen.has(t))return true;seen.add(t);return false;
        });
      });
      const target = pages.slice().sort((a,b)=>b.querySelectorAll('.ad img').length-a.querySelectorAll('.ad img').length)[0];
      pages.forEach(p=>{if(p!==target)p.style.display='none';});
      if(target){target.style.transform='none';target.style.margin='0 auto';}
      return {pages:pages.length, cards:cards.length, uniqueCards:new Set(texts).size,
        imageCards:imageCards.length, loadedImages:imageCards.filter(n=>n.querySelector('img').naturalWidth>0).length,repeatedPageFillers,
        presenterPatter:texts.some(t=>/Listen up|holding up|Available to talk/i.test(t)),
        targetIndex:pages.indexOf(target),
        targetHeight:target?.getBoundingClientRect().height||0};
    })()`);
    if (metrics.presenterPatter || metrics.cards !== metrics.uniqueCards || metrics.repeatedPageFillers.length || !metrics.loadedImages) throw new Error(JSON.stringify(metrics));
    await new Promise(resolve=>setTimeout(resolve, 250));
    fs.writeFileSync(path.join(folder,'city-page.png'), (await win.webContents.capturePage()).toPNG());
    fs.writeFileSync(path.join(folder,'browser-result.json'), JSON.stringify({ok:true,...metrics},null,2));
    console.log(JSON.stringify({ok:true,...metrics}));
    win.destroy(); app.quit();
  } catch(error) {
    console.error(error); if(win)win.destroy(); app.exit(1);
  }
});
