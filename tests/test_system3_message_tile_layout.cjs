'use strict';
// Run with Electron. This isolated renderer uses only local shared tile assets.
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'system3-pane-layout-')));
app.commandLine.appendSwitch('use-angle','swiftshader');
app.commandLine.appendSwitch('enable-unsafe-swiftshader');
app.on('window-all-closed',()=>{});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let window;
const timeout=setTimeout(()=>{console.error('System3 pane layout test timed out');app.exit(1);},45000);
const run=(fn,arg)=>window.webContents.executeJavaScript('('+fn.toString()+')('+JSON.stringify(arg)+')');
function assertHeaderFixed(reference,sample,label){
  for(const key of ['left','top','width','height'])
    assert(Math.abs(reference.words[key]-sample.words[key])<=1.1,label+': header '+key+' moved');
  assert.equal(sample.stageScroll,0,label+': the live stage must not scroll the header');
}
app.whenReady().then(async()=>{
  window=new BrowserWindow({show:false,width:700,height:500,webPreferences:{backgroundThrottling:false}});
  const css=fs.readFileSync(path.join(root,'desktop/renderer/system3-message-tile.css'),'utf8');
  await window.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#10171b}#host{position:absolute;left:20px;top:20px;width:350px;height:250px}'+css+'</style><div id="host"></div>'));
  await window.webContents.executeJavaScript(fs.readFileSync(path.join(root,'desktop/renderer/system3-message-tile.js'),'utf8'));
  for(const fontSize of [12,18]){
    const baseline=await run(async function(fontSize){
      window.fixture?.instance.dispose();
      const frames=new Map();let next=0,frameTime=1000;
      window.requestAnimationFrame=callback=>{frames.set(++next,callback);return next;};
      window.cancelAnimationFrame=id=>frames.delete(id);
      const rows=Array.from({length:12},(_,index)=>({
        fam:index%2?'RS':'ES',table:'T'+index,event:'initial-'+index,
        main:{dice:10+index,label:'Selected '+index,opts:['Other '+index,'Selected '+index],hit:1},
        sub:index%3===0?{dice:70+index,label:'Detail '+index,opts:['Alternative','Detail '+index],hit:1}:null
      }));
      const older={id:'older',text:'An earlier long reply has its own reading position. '.repeat(50),from:0,until:1,lcdStatus:'Played'};
      const live={id:'live',text:'SFX: beep',from:0,until:1,lcdStatus:'Playing'};
      const payload={now:live,rows:[older,live],station:{stream_now:{at:1000}}};
      const fixture={
        rows,payload,
        async flush(){for(let n=0;n<10;n++)await Promise.resolve();},
        step(ms=100){frameTime+=ms;const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback(frameTime));},
        parts(){const article=this.instance.element.querySelector('.pip-system3-message');return {article,words:article.querySelector('.pip-system3-words'),rolls:article.querySelector('.pip-system3-rolls')};},
        sample(){
          const {article,words,rolls}=this.parts(),rect=element=>{const r=element.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height,bottom:r.bottom};};
          return {words:rect(words),rolls:rect(rolls),article:rect(article),stageScroll:this.instance.element.scrollTop,wordScroll:words.scrollTop,rollScroll:rolls.scrollTop,wordOverflow:words.scrollHeight>words.clientHeight+1,rollOverflow:rolls.scrollHeight>rolls.clientHeight+1,phase:this.instance.state().phase,lineHeight:parseFloat(getComputedStyle(words).lineHeight)*fontSize/12,sizingHeight:article.querySelector('.pip-system3-words-measure')?.getBoundingClientRect().height};
        }
      };
      fixture.instance=PineSystem3MessageTile.mount(document.getElementById('host'),{options:{fontSize},clock:()=>1001000,load:async()=>({rows:fixture.rows})});
      const stage=fixture.instance.element;
      stage.style.setProperty('--pip-message-max-height','250px');stage.style.maxHeight='250px';stage.style.height='250px';
      window.fixture=fixture;fixture.instance.receive(payload);await fixture.flush();fixture.step();
      return fixture.sample();
    },fontSize);
    assert(baseline.words.height<=baseline.lineHeight*2+1.1,'one-line SFX has no four-line whitespace');
    assert(Math.abs(baseline.words.height-baseline.sizingHeight)<=1.1,'a short header fits its complete reply');
    const unfolding=await run(function(){
      const f=window.fixture,samples=[],stages=new Set();
      for(let n=0;n<200&&f.instance.state().phase!=='done';n++){f.step();samples.push(f.sample());stages.add(f.instance.state().rollNow);}
      return {samples,stages:[...stages],last:f.sample()};
    });
    assert.equal(unfolding.last.phase,'done');
    for(const sample of unfolding.samples)assertHeaderFixed(baseline,sample,'unfolding at font '+fontSize);
    assert(unfolding.stages.includes('0:cat-spin')&&unfolding.stages.includes('0:sub-spin')&&unfolding.stages.includes('11:cat-spin'),'every kind of reel unfolds before the last row');
    assert(unfolding.last.rollOverflow&&unfolding.last.rollScroll>0,'later rows scroll inside the roulette pane');
    assert.equal(unfolding.last.wordScroll,0,'short reply position stays fixed while roulettes scroll');
    const manual=await run(function(){
      const f=window.fixture,{words,rolls}=f.parts(),before=f.sample();
      rolls.dispatchEvent(new WheelEvent('wheel',{bubbles:true,deltaY:120}));rolls.scrollTop=37;
      f.step();return {before,after:f.sample(),wordFollow:f.instance.state().wordFollow,rollFollow:f.instance.state().rollFollow};
    });
    assertHeaderFixed(baseline,manual.after,'manual roulette scrolling');
    assert.equal(manual.after.wordScroll,manual.before.wordScroll);
    assert.equal(manual.wordFollow,true);assert.equal(manual.rollFollow,false,'wheel interaction pauses only roulette following');
    window.webContents.sendInputEvent({type:'mouseMove',x:45,y:40});await delay(30);
    const hover=await run(()=>window.fixture.sample());
    assertHeaderFixed(baseline,hover,'hover controls');
    window.webContents.sendInputEvent({type:'mouseMove',x:600,y:300});window.webContents.sendInputEvent({type:'mouseLeave',x:600,y:300});await delay(30);
    const appended=await run(async function(){
      const f=window.fixture;
      f.rows=f.rows.concat({fam:'SFX',table:'Late clip',event:'late',main:{dice:60,label:'Late selected clip',opts:['Other clip','Late selected clip'],hit:1}});
      f.payload={...f.payload,rows:f.payload.rows.concat({id:'live-punct-1',sfx_roll:{category:{dice:60}}})};
      f.instance.receive(f.payload);await f.flush();
      const samples=[f.sample()];
      for(let n=0;n<80&&f.instance.state().phase!=='done';n++){f.step();samples.push(f.sample());}
      return {samples,last:f.sample(),count:f.parts().rolls.querySelectorAll('.sp-rr-t').length};
    });
    assert.equal(appended.count,13);assert.equal(appended.last.phase,'done');
    appended.samples.forEach(sample=>assertHeaderFixed(baseline,sample,'late roulette append'));
    if(fontSize===12){
      fs.mkdirSync(path.join(root,'work'),{recursive:true});
      fs.writeFileSync(path.join(root,'work/system3-message-panes-preview.png'),(await window.webContents.capturePage({x:20,y:20,width:350,height:250})).toPNG());
    }

    const wrapped=await run(function(){
      const f=window.fixture;
      f.payload={...f.payload,now:{...f.payload.now,text:'This reply wraps over several lines and reserves its complete header before typing ends.'}};
      f.instance.receive(f.payload);
      const reserved=f.sample(),samples=[];
      for(let n=0;n<20;n++){f.step();samples.push(f.sample());}
      const {article}=f.parts(),sizer=article.querySelector('.pip-system3-words-measure');
      return {reserved,samples,sizerHidden:sizer?.getAttribute('aria-hidden')==='true'};
    });
    assert(wrapped.sizerHidden,'full-reply sizing is hidden from assistive technology');
    assert(wrapped.reserved.words.height>baseline.words.height+8,'wrapped replies reserve more than a one-line cue');
    wrapped.samples.forEach(sample=>assertHeaderFixed(wrapped.reserved,sample,'complete wrapped reply height is reserved through typed prefixes'));
    const long=await run(function(){
      const f=window.fixture,{rolls}=f.parts(),rollBefore=rolls.scrollTop;
      f.payload={...f.payload,now:{...f.payload.now,text:'A much longer reply scrolls inside the fixed text header while the roulette pane stays independent. '.repeat(70)}};
      f.instance.receive(f.payload);
      const reserved=f.sample(),samples=[];
      for(let n=0;n<60;n++){f.step();samples.push(f.sample());}
      return {...f.sample(),reserved,samples,rollBefore,state:f.instance.state(),wordAtBottom:Math.abs(f.parts().words.scrollHeight-f.parts().words.clientHeight-f.parts().words.scrollTop)<2};
    });
    for(const key of ['left','top','width'])assert(Math.abs(baseline.words[key]-long.words[key])<=1.1,'long replies retain the header '+key);
    long.samples.forEach(sample=>assertHeaderFixed(long.reserved,sample,'reserved long reply header'));
    assert(long.words.height<=100.5,'long reply header uses at most 40% of the physical 250px budget');
    assert(long.wordOverflow&&long.wordScroll>0&&long.wordAtBottom,'long replies follow their own text pane: '+JSON.stringify(long));
    assert.equal(long.rollScroll,long.rollBefore,'typing a long reply does not move roulette scroll');
    assert(long.rolls.height>0&&long.rolls.bottom<=270.5,'the roulette pane remains below the capped text pane');

    const reviewed=await run(async function(){
      const f=window.fixture;
      while(f.instance.state().current!=='older'&&f.instance.state().navigation.canPrevious){f.instance.previous();await f.flush();}
      const older=f.parts(),article=older.article;
      older.words.scrollTop=61;older.rolls.scrollTop=79;const wordBefore=older.words.scrollTop,rollBefore=older.rolls.scrollTop;
      f.instance.next();await f.flush();f.instance.previous();await f.flush();
      const restored=f.parts();
      return {same:restored.article===article,wordBefore,rollBefore,wordScroll:restored.words.scrollTop,rollScroll:restored.rolls.scrollTop,stageScroll:f.instance.element.scrollTop};
    });
    assert.equal(reviewed.same,true);assert.equal(reviewed.wordScroll,reviewed.wordBefore);assert.equal(reviewed.rollScroll,reviewed.rollBefore);assert.equal(reviewed.stageScroll,0,'review restores each pane independently');
    console.log('System3 independent panes: font '+fontSize+', fixed header through '+unfolding.samples.length+' frames, roulette/word scrolling, append, hover and review passed.');
  }
  clearTimeout(timeout);window.destroy();app.quit();
}).catch(error=>{console.error(error);clearTimeout(timeout);app.exit(1);});
