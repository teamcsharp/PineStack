'use strict';
const fs=require('node:fs'),path=require('node:path');
const DURATIONS=new Set([60,120,180,300,600,900,1800,3600]);
function createTabletReplayExporter({glass,mux,folder,config,now=()=>Date.now()}){
  let busy=false;
  return async function(want={}){
    const seconds=Number(want.seconds);
    if(!DURATIONS.has(seconds))return {ok:false,detail:'Unknown tablet recording duration.'};
    if(busy)return {ok:false,detail:'A tablet recording is already being exported.'};
    busy=true;let dir;
    try{
      const videoOnly=want.video_only===true;
      const made=await (await glass()).clip_fromReplay(seconds,{video_only:videoOnly});
      if(!made?.ok)return {ok:false,detail:made?.why||made?.detail||'PineTab recording unavailable.'};
      if(!made.mp4?.length)return {ok:false,detail:'The tablet returned an empty recording.'};
      if(!videoOnly&&(!made.audioMeta?.present||!made.audioMeta?.complete))return {ok:false,detail:made.audioMeta?.detail||'The tablet recording does not contain the complete audio mix heard during this video.',audio:made.audioMeta};
      dir=mux.stash();const video=path.join(dir,'tablet.mp4');await fs.promises.writeFile(video,made.mp4);
      const destination=folder();await fs.promises.mkdir(destination,{recursive:true});
      const where=path.join(destination,'pinebox-tablet-'+now()+'-'+Math.round(made.seconds)+'s.mp4');
      await fs.promises.copyFile(video,where);
      const stat=await fs.promises.stat(where);
      return {ok:true,where,seconds:made.seconds,asked:seconds,clamped:made.seconds+.5<seconds,bytes:stat.size,audio:made.audioMeta,notes:made.notes||[]};
    }catch(error){return {ok:false,detail:error.message};}
    finally{busy=false;if(dir)mux.forget(dir);}
  };
}
module.exports={createTabletReplayExporter,DURATIONS};
