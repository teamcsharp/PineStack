(function(root,factory){
  'use strict';
  const library=factory();
  if(typeof module==='object'&&module.exports)module.exports=library;
  else {root.PinePipCameraRecovery=library;if(!root.PINE_NATIVE_TOOLS)library.attach(root);}
})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const GRACE_MS=9000, RETRY_MS=45000;
  function create(deps){
    let epoch=0,busy=false,faultSince=null,nextTry=0,attempts=0,lastSource='',lastReading=null;
    let status={phase:'idle',say:'',attempts:0};
    let reason='';   // [cam-why] why there is nothing to reconnect to, kept while the next look waits
    function sentence(text){const t=String(text||'').trim();if(!t)return '';const s=t[0].toUpperCase()+t.slice(1);return /[.!?]$/.test(s)?s:s+'.';}
    function why(got,doctor,tablet){
      if(tablet)return 'Waiting for the PineTab camera link. Check camera power and Wi-Fi.';
      if(doctor&&!doctor.stale&&doctor.camera===false){
        /* [cam-words] what the station knows is that ITS adapter cannot see the camera's network; the
           camera may well be on. Say that, with the evidence, and what would put it back on the air. */
        const name=got&&got.ssid?' ('+got.ssid+')':'';
        const seen=Number.isFinite(Number(doctor.nearby))?Number(doctor.nearby):null;
        const evidence=seen===null?'':seen===0?' Its adapter sees no networks at all right now.':' Its adapter sees '+seen+' other network'+(seen===1?'':'s')+' but not the camera\'s.';
        return 'The camera\'s Wi-Fi'+name+' is not on the air for the Pine Box.'+evidence+' The camera may be on with its Wi-Fi asleep, a phone or the Viidure app may hold its only connection, or it may be more than about 10 m from the adapter. Press its Wi-Fi button and wait for the solid green light.';
      }
      return sentence(got&&got.why)||'Camera not detected. Check camera power and Wi-Fi.';
    }
    const now=deps.now||Date.now;
    const wanted=()=>{const s=deps.state();return !!(s?.active&&(s.cameraOverlay||s.cameraOnly)&&(s.cameraSource||'pine')==='pine');};
    const current=token=>token===epoch&&wanted();
    function report(phase,say){status={phase,say,attempts,nextTry};deps.status?.(status);return {...status};}
    function cancel(){epoch++;faultSince=null;lastReading=null;lastSource='';reason='';return report('idle','');}
    function good(got){return got?.state==='live'&&got.fresh&&!(Number(got.frame_age)>8);}
    async function turn(force=false){
      if(!wanted()){cancel();return {ok:false,say:'Camera recovery is inactive.'};}
      if(busy)return {ok:false,busy:true,say:status.say};
      busy=true;const token=epoch;
      try{
        const got=await deps.read();
        if(!current(token))return {ok:false,cancelled:true};
        lastReading=got;
        const source=got?.source||{};
        // A changed route gets its own settling period. Never change relay preferences.
        const key=String(source.pref||'')+'|'+String(source.use||'')+'|'+String(source.ip||'');
        if(lastSource&&lastSource!==key)faultSince=null;
        lastSource=key;
        if(good(got)&&deps.picture()){
          faultSince=null;attempts=0;reason='';report('live','Live Pine Cam picture restored.');
          return {ok:true,verified:true,say:status.say};
        }
        if(faultSince===null)faultSince=now();
        if(!force&&now()-faultSince<GRACE_MS){report('waiting','Pine Cam is reconnecting...');return {ok:false,waiting:true,say:status.say};}
        if(now()<nextTry){
          const hint=got?.stream?.class==='decode'&&attempts>1?' If it keeps failing, move the camera closer to '+(source.pref==='always'||source.use==='tablet'?'the PineTab.':'the camera adapter.') : '';
          // [cam-why] the reason stays on the glass while it waits, with the seconds left
          report('waiting',reason?reason+' Checking again in '+Math.max(1,Math.ceil((nextTry-now())/1000))+' s.'+hint:'Pine Cam recovery is waiting before retrying.'+hint);
          return {ok:false,waiting:true,say:status.say};
        }
        // A healthy station stream needs only the local image connection rebuilt.
        if(good(got)){
          nextTry=now()+RETRY_MS;
          report('recovering','Reconnecting the Pine Cam picture...');
          await deps.display();
          if(!current(token))return {ok:false,cancelled:true};
          return {ok:true,verified:false,say:'Camera display reconnected; waiting for a fresh picture.'};
        }
        const tablet=source.pref==='always'||source.use==='tablet'||(source.use==='wait'&&source.want_tablet);
        const fault=String(got?.stream?.class||'');
        let route='',seen=null;
        if(got?.state==='dropped'&&['decode','stalled','session-cut','ended','no-start'].includes(fault))route='/api/pinelink/connect';
        else if(tablet){
          if(source.tablet_state==='joined'&&Number(source.report_at)>0&&now()/1000-Number(source.report_at)<75)route='/api/pinelink/connect';
        }else if(got?.state==='live'&&!good(got))route='/api/pinelink/connect';
        else{
          const doctor=await deps.doctor();
          seen=doctor;
          if(!current(token))return {ok:false,cancelled:true};
          if(doctor&&!doctor.stale){
            if(doctor.cure==='reset')route='/api/pinelink/reset-radio';
            else if(doctor.camera)route='/api/pinelink/connect';
          }
        }
        nextTry=now()+Math.min(RETRY_MS*Math.pow(2,attempts),180000);
        if(!route){
          const say=why(got,seen,tablet);   // [cam-why] the station's own reading, not a shrug
          reason=say;report('attention',say);return {ok:false,say};
        }
        attempts++;
        report('recovering',route.endsWith('reset-radio')?'Recovering the Pine Cam radio...':'Reconnecting the Pine Cam stream...');
        const result=await deps.post(route,{});
        if(!current(token))return {ok:false,cancelled:true};
        if(result?.ok===false){report('attention',result.say||'Camera reconnect failed; waiting before retrying.');return {ok:false,say:status.say};}
        await deps.display();
        if(!current(token))return {ok:false,cancelled:true};
        report('waiting','Pine Cam reconnected; waiting for a fresh picture.');
        return {ok:true,verified:false,say:status.say};
      }catch(error){
        if(!current(token))return {ok:false,cancelled:true};
        nextTry=Math.max(nextTry,now()+RETRY_MS);
        report('attention','Cannot reach the camera connection; retrying when it responds.');
        return {ok:false,say:status.say,error:error.message};
      }finally{busy=false;}
    }
    return {tick:()=>turn(),repair:()=>turn(true),cancel,state:()=>({...status,busy,lastReading})};
  }
  function attach(root){
    if(root.__pinePipCameraRecovery)return root.__pinePipCameraRecovery;
    let timer=0,controller=null,detach=null,observer=null,original=null,pipHost=null,disposed=false;
    function boot(){
      if(disposed)return;
      const api=root.pineDesktop,pip=root.PinePip;
      if(!api?.get||!api?.post||!pip?.repairCamera)return;
      original=pip.repairCamera;pipHost=pip;const display=original.bind(pip);
      controller=create({state:()=>pip.state(),read:()=>api.get('/api/pinelink/state'),doctor:()=>api.get('/api/pinelink/doctor'),post:(route,body)=>api.post(route,body),display,
        picture:()=>{const img=root.document.querySelector('.pip-camera img');return !!img&&!img.hidden&&img.naturalWidth>0;},
        status:value=>{const box=root.document.querySelector('.pip-camera'),el=box?.querySelector('[role=status]');if(!box||!el)return;box.dataset.recovery=value.phase;if(value.phase==='live')return;if(value.say&&!el.hidden)el.textContent=value.say;}});
      pip.repairCamera=async()=>{
        const s=pip.state();if(!s?.active||!(s.cameraOverlay||s.cameraOnly)||(s.cameraSource||'pine')!=='pine')return display();
        return controller.repair();
      };
      detach=api.onPipState?.(s=>{if(disposed)return;if(!s?.active||!(s.cameraOverlay||s.cameraOnly)||(s.cameraSource||'pine')!=='pine')controller.cancel();});
      const statusNode=root.document.querySelector('.pip-camera [role=status]');
      if(statusNode&&root.MutationObserver){
        observer=new root.MutationObserver(()=>{const value=controller.state();if(value.phase!=='idle'&&value.phase!=='live'&&value.say&&!statusNode.hidden&&statusNode.textContent!==value.say)statusNode.textContent=value.say;});
        observer.observe(statusNode,{childList:true,characterData:true,subtree:true});
      }
      timer=root.setInterval(()=>controller.tick(),3000);
      controller.tick();
    }
    const handle={state:()=>controller?.state()||{phase:'idle'},repair:()=>controller?.repair(),dispose:()=>{disposed=true;root.clearInterval(timer);if(typeof detach==='function')detach();observer?.disconnect();controller?.cancel();if(pipHost&&original)pipHost.repairCamera=original;delete root.__pinePipCameraRecovery;}};
    root.__pinePipCameraRecovery=handle;
    if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
    return handle;
  }
  return {create,attach};
});
