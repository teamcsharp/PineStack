/* The Gazette control also upgrades already-cached native newspaper scenes. */
(function(root){'use strict';if(root.__pineGazetteHourlyControl)return;
 const request=(path,options={})=>root.pineDesktop[(options.method||'GET').toLowerCase()](path,options.body);
 const mounted=new WeakSet();
 function upgrade(){for(const box of document.querySelectorAll('.pip-popup-visible')){
  if(!box.textContent.includes('The Gazette')||mounted.has(box)||box.querySelector('.paper-hourly-switch'))continue;
  const old=[...box.querySelectorAll('button')].find(b=>/^Hourly press/.test(b.title));if(!old)continue;mounted.add(box);
  const button=document.createElement('button');button.className='paper-hourly-switch';button.setAttribute('role','switch');button.setAttribute('aria-label','Gazette hourly generation');button.style.cssText='display:inline-flex;align-items:center;gap:7px;padding:5px 9px;min-height:30px';
  const dial=document.createElement('span');dial.style.cssText='width:13px;height:13px;border-radius:50%;border:2px solid currentColor;display:inline-block;box-sizing:border-box';const label=document.createElement('span');label.textContent='Hourly: loading';button.append(dial,label);button.disabled=true;old.replaceWith(button);
  function paint(on){button.setAttribute('aria-checked',String(on));label.textContent='Hourly: '+(on?'On':'Off');dial.style.background=on?'#69d6a4':'transparent';button.title=on?'Generate the Gazette every hour. Click to turn off.':'Hourly generation is off. Click to turn on.';}
  button.onclick=async()=>{button.disabled=true;try{const settings=await request('/api/settings');await request('/api/settings',{method:'PUT',body:{...settings,dj:{...settings.dj,paper_hourly:settings.dj?.paper_hourly===false}}});paint((await request('/api/settings')).dj?.paper_hourly!==false);}catch(e){button.title=e.message;}finally{button.disabled=false;}};
  request('/api/settings').then(s=>{paint(s.dj?.paper_hourly!==false);button.disabled=false;}).catch(e=>{label.textContent='Hourly: unavailable';button.title=e.message;});
 }}
 const observer=new MutationObserver(upgrade);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});root.__pineGazetteHourlyControl={disconnect:()=>observer.disconnect()};upgrade();
})(window);
