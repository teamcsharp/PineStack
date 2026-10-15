/* PineTab uses the shared PiP widgets and the existing native broadcast player. */
(function(root){
  'use strict';
  if(root.PinePipTabletApi)return;
  var KEY='pine-pip-tablet-layout-v1',listener=null,state={active:false},mounted,observer,loadFlight,controls;
  function bridge(){return root.pineDesktop;}
  function publish(){if(listener)listener(state);}
  function merge(base,next){
    var out=Object.assign({},base,next);
    ['widgets','docks','order','voiceStyles','cameraBounds','messageBounds','messageTile','roulettePosition','musicPosition'].forEach(function(k){out[k]=Object.assign({},base[k],next[k]);});
    return out;
  }
  function saved(){try{return JSON.parse(localStorage.getItem(KEY)||'null');}catch(e){return null;}}
  function remember(){var copy=Object.assign({},state);delete copy.active;localStorage.setItem(KEY,JSON.stringify(copy));}
  function read(force){
    if(loadFlight)return loadFlight;
    loadFlight=bridge().get('/api/pip/config').then(function(got){
      var prefs=got.settings||got,local=force?null:saved();
      state=Object.assign({},merge(prefs,local||{}),{active:state.active});
      if(force)remember();
      return state;
    }).catch(function(e){var local=saved();if(force||!local)throw e;state=Object.assign({},local,{active:state.active});return state;}).finally(function(){loadFlight=null;});
    return loadFlight;
  }
  function report(e){if(!controls)return;var note=controls.querySelector('[role=status]');if(!note){note=document.createElement('p');note.setAttribute('role','status');controls.appendChild(note);}note.textContent=e.message||String(e);}
  var api={get:function(p){return bridge().get(p);},post:function(p,b){return bridge().post(p,b);},readConfig:function(){return bridge().readConfig();},
    pipState:function(){return read();},onPipState:function(fn){listener=fn;},
    pipEnter:async function(){
      await read();
      if(mounted&&!mounted.classList.contains('open'))return state;
      await bridge().videoWall('pip',{on:true});
      state=Object.assign({},state,{active:true});root.document.body.classList.add('pine-pip-tablet');
      return state;
    },
    pipExit:async function(){
      if(mounted&&mounted.classList.contains('open'))document.getElementById('pineViewTab-pip')?.click();
      state=Object.assign({},state,{active:false});root.document.body.classList.remove('pine-pip-tablet','ppt-editing');
      await bridge().videoWall('pip',{on:false});
      return state;
    },
    pipUpdate:function(next){
      if(Object.prototype.hasOwnProperty.call(next,'layout')){
        var layout=next.layout===null?{}:Object.assign({},state.layout);
        Object.keys(next.layout||{}).forEach(function(key){var entry=next.layout[key];if(entry===null)delete layout[key];else layout[key]=Object.assign({},layout[key],entry);});
        next=Object.assign({},next,{layout:layout});
      }
      state=Object.assign({},merge(state,next),{active:state.active});
      try{remember();}catch(e){report(e);return Promise.reject(e);}
      publish();return Promise.resolve(state);
    },
    pipMenu:function(){showSettings();return Promise.resolve(state);},
    cameraWhere:function(){return Promise.resolve({ok:false,why:'Choose Pine Cam for the station camera.'});},
    cameraPip:function(){return Promise.resolve({ok:false,why:'Choose Pine Cam for the station camera.'});},
    replayHold:function(){return Promise.resolve();},onPipAction:function(){},onPipPlayback:function(){}
  };
  root.PinePipTabletApi=api;
  function button(parent,title,fn){var b=document.createElement('button');b.type='button';b.textContent=title;b.onclick=function(){Promise.resolve().then(fn).catch(report);};parent.appendChild(b);return b;}
  var names={messages:'Message tile',voices:'DJ voices',music:'Music',cast:'DJ portraits',dialogue:'Dialogue + dice',chat:'Live feed',task:'Task status',audit:'Station status',production:'Production',rec:'Recorder'};
  function showSettings(){
    var panel=controls.querySelector('.ppt-settings');
    if(panel){panel.remove();return;}
    panel=document.createElement('section');panel.className='ppt-settings';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','PineTab PiP settings');
    var head=document.createElement('header');head.textContent='PineTab PiP';panel.appendChild(head);button(head,'Close',function(){panel.remove();});
    var note=document.createElement('p');note.textContent='Changes are saved on this tablet. Drag handles to move elements; drag their edges to resize.';panel.appendChild(note);
    button(panel,'Use desktop layout',async function(){await read(true);publish();panel.remove();showSettings();});
    button(panel,'Colors & transparency',function(){root.PinePip.appearance();panel.remove();});
    button(panel,state.ui===false?'Show overlays':'Hide overlays',function(){api.pipUpdate({ui:state.ui===false});panel.remove();showSettings();});
    button(panel,'Message style',function(){root.PinePip.messageSettings();panel.remove();});
    Object.keys(names).concat(['camera']).forEach(function(key){
      var row=document.createElement('div');row.className='ppt-setting-row';
      var label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=key==='camera'?state.cameraOverlay:!!state.widgets[key];
      check.onchange=function(){api.pipUpdate(key==='camera'?{cameraOverlay:check.checked,cameraSource:'pine'}:{widgets:{[key]:check.checked}}).catch(report);};
      label.append(check,document.createTextNode(names[key]||'Pine Cam'));row.appendChild(label);
      button(row,'Layout',function(){root.PinePip.adjust(key);panel.remove();});panel.appendChild(row);
    });
    var styles=['Cyan bars','Green wave','Amber equalizer','Purple wave','Red blocks','Blue spikes','Green blocks','Gold wave','Violet spikes','Teal filled wave','Pink blocks','Sky bars','Lime bars','Orange spikes','Cyan dots','Violet bars'];
    [['host','Host'],['cohost','Co-host'],['sfx','SFX'],['callers','Callers']].forEach(function(pair){
      var label=document.createElement('label');label.className='ppt-setting-row';label.textContent=pair[1]+' style';
      var select=document.createElement('select');select.setAttribute('aria-label',pair[1]+' voice style');
      styles.forEach(function(title,i){var option=document.createElement('option');option.value=i;option.textContent=title;select.appendChild(option);});
      select.value=state.voiceStyles[pair[0]]||0;select.onchange=function(){api.pipUpdate({voiceStyles:{[pair[0]]:Number(select.value)}}).catch(report);};label.appendChild(select);panel.appendChild(label);
    });
    var status=document.createElement('p');status.setAttribute('role','status');panel.appendChild(status);controls.appendChild(panel);
  }
  var transitioning=Promise.resolve();
  function watch(){
    transitioning=transitioning.then(async function(){
      var open=mounted.classList.contains('open');
      if(open&&!state.active)await root.PinePip.enter();
      else if(!open&&state.active)await root.PinePip.exit();
    }).catch(report);
  }
  root.PinePipTablet={mount:function(host){
    mounted=host;
    root.PinePipBootstrap();
    if(!controls){
      controls=document.createElement('div');controls.id='pinePipTabletControls';
      button(controls,'PiP settings',showSettings);
      var edit=button(controls,'Edit layout',function(){var on=document.body.classList.toggle('ppt-editing');edit.textContent=on?'Done editing':'Edit layout';});
      button(controls,'Exit PiP',function(){document.getElementById('pineViewTab-pip')?.click();});
      document.body.appendChild(controls);
    }
    if(observer)observer.disconnect();observer=new MutationObserver(watch);observer.observe(host,{attributes:true,attributeFilter:['class']});watch();
  },refresh:function(){return read(true).then(function(){publish();return state;});},close:function(){root.PineViewRail.closeAll();}};
})(window);
