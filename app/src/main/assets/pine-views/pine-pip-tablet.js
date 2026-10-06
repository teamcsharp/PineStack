/* PineTab adapter for the shared desktop Pine PiP renderer. */
(function(root){
  'use strict';
  if(root.PinePipTabletApi)return;
  var listener=null,state={active:false};
  function bridge(){return root.pineDesktop||{};}
  function publish(){if(listener)listener(state);}
  function read(){return Promise.resolve(bridge().get('/api/pip/config')).then(function(got){state=Object.assign({},got&&got.settings||got||{},{active:!!state.active});return state;});}
  var api={get:function(path){return bridge().get(path);},post:function(path,body){return bridge().post(path,body);},readConfig:function(){return bridge().readConfig();},
    pipState:function(){return read();},onPipState:function(fn){listener=fn;},
    pipEnter:function(){state.active=true;root.document.body.classList.add('pine-pip-tablet');return read().then(function(next){next.active=true;state=next;publish();return state;});},
    pipExit:function(){state.active=false;root.document.body.classList.remove('pine-pip-tablet');if(root.PineViewRail)root.PineViewRail.closeAll();publish();return Promise.resolve(state);},
    pipUpdate:function(next){return bridge().post('/api/pip/config',next).then(function(got){state=Object.assign({},got&&got.settings||got||state,{active:!!state.active});publish();return state;});},
    pipMenu:function(){return Promise.resolve(state);},
    cameraWhere:function(){return Promise.resolve(bridge().pineCam('state')).then(function(got){return Object.assign({},got||{},{ok:!!(got&&got.on),running:!!(got&&got.on)});});},
    cameraPip:function(){return Promise.resolve({ok:false,why:'This PineTab camera source is not available in the desktop PiP view.'});},
    replayHold:function(){return Promise.resolve();},
    onPipAction:function(){},onPipPlayback:function(){}
  };
  root.PinePipTabletApi=api;
  var mounted=null,observer=null;
  function watch(){if(!mounted||!root.PinePip)return;var open=mounted.classList.contains('open');if(open&&!state.active)root.PinePip.enter().catch(function(){});else if(!open&&state.active)api.pipExit();}
  root.PinePipTablet={mount:function(host){mounted=host;if(observer)observer.disconnect();observer=new MutationObserver(watch);observer.observe(host,{attributes:true,attributeFilter:['class']});watch();},refresh:read,close:function(){return api.pipExit();}};
})(window);
