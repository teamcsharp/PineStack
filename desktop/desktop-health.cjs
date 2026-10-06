'use strict';
const fs=require('node:fs'),path=require('node:path');
class DesktopHealth {
  constructor({file,io=fs.promises,maxBytes=1024*1024,now=Date.now}={}) {
    Object.assign(this,{file,io,maxBytes,now});this.pending=Promise.resolve();this.queued=0;
  }
  record(kind,details={}) {
    let line;
    try {
      line=JSON.stringify({at:new Date(this.now()).toISOString(),kind,...details})+'\n';
      if(Buffer.byteLength(line)>8192)line=JSON.stringify({at:new Date(this.now()).toISOString(),kind,details:'diagnostic details exceeded 8 KiB'})+'\n';
    } catch {return Promise.resolve(false);}
    if(this.queued>=64)return Promise.resolve(false);
    this.queued++;
    const task=this.pending.catch(()=>{}).then(async()=>{
      try {
        const file=typeof this.file==='function'?this.file():this.file;
        await this.io.mkdir(path.dirname(file),{recursive:true});
        let size=0;try{size=(await this.io.stat(file)).size;}catch{}
        if(size+Buffer.byteLength(line)>this.maxBytes){
          try{await this.io.rename(file,file+'.previous');}
          catch{await this.io.writeFile(file,'');}
        }
        await this.io.appendFile(file,line,'utf8');return true;
      } catch {return false;}
    }).finally(()=>{this.queued--;});
    this.pending=task;return task;
  }
}
function install({app,getFile,processEvents=process,now=Date.now,everyMs=1000,gapMs=3500}={}) {
  const health=new DesktopHealth({file:getFile,now});
  const title=c=>{try{return String(c.getTitle()).slice(0,200);}catch{return '';}};
  app.on('render-process-gone',(_event,contents,details)=>health.record('renderer-gone',{
    title:title(contents),reason:details.reason,exitCode:details.exitCode}));
  app.on('child-process-gone',(_event,details)=>health.record('child-process-gone',{
    type:details.type,reason:details.reason,exitCode:details.exitCode}));
  app.on('web-contents-created',(_event,contents)=>{
    contents.on('did-finish-load',()=>{let pid=0;try{pid=contents.getOSProcessId();}catch{}health.record('view-loaded',{title:title(contents),pid});});
    contents.on('unresponsive',()=>health.record('window-unresponsive',{title:title(contents)}));
    contents.on('responsive',()=>health.record('window-responsive',{title:title(contents)}));
    contents.on('preload-error',(_event,_file,error)=>health.record('preload-error',{title:title(contents),error:String(error?.stack||error).slice(0,6000)}));
  });
  processEvents.on('uncaughtExceptionMonitor',error=>health.record('main-exception',{error:String(error?.stack||error).slice(0,6000),code:error?.code}));
  let previous=now();
  const timer=setInterval(()=>{const at=now(),elapsed=at-previous;previous=at;if(elapsed>gapMs)health.record('main-loop-gap',{elapsedMs:elapsed});},everyMs);
  timer.unref?.();
  health.stop=()=>clearInterval(timer);
  app.once('will-quit',health.stop);
  app.whenReady().then(()=>health.record('desktop-started',{pid:processEvents.pid}));
  return health;
}
module.exports={DesktopHealth,install};
