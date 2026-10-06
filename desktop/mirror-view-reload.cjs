'use strict';
function reloadMirrorView(contents,{delayMs=750,timeoutMs=10000,timers=globalThis}={}){
  return new Promise((resolve,reject)=>{
    let delay,deadline,settled=false;
    const finish=error=>{if(settled)return;settled=true;timers.clearTimeout(delay);timers.clearTimeout(deadline);
      contents.removeListener('did-finish-load',loaded);contents.removeListener('did-fail-load',failed);
      contents.removeListener('render-process-gone',gone);contents.removeListener('destroyed',destroyed);
      error?reject(error):resolve();};
    const loaded=()=>finish();
    const failed=(_event,code,description,_url,isMainFrame)=>{if(isMainFrame!==false&&code!==-3)finish(Error(description+' ('+code+')'));};
    const gone=()=>finish(Error('the tablet view exited during recovery'));
    const destroyed=()=>finish(Error('the tablet view was closed'));
    deadline=timers.setTimeout(()=>finish(Error('the tablet view reload timed out')),timeoutMs);
    // Windows can still be unwinding the crashed process when its gone event arrives.
    delay=timers.setTimeout(()=>{
      if(settled)return;
      contents.once('did-finish-load',loaded);contents.on('did-fail-load',failed);
      contents.once('render-process-gone',gone);contents.once('destroyed',destroyed);
      try{if(contents.isDestroyed?.())return destroyed();contents.reload();}catch(error){finish(error);}
    },delayMs);
  });
}
module.exports={reloadMirrorView};
