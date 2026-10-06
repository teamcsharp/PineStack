(function(root){
  'use strict';
  var api = root.pineDesktop;
  function ask(route, body) {
    if (api && api.get) return body === undefined ? api.get(route) : api.post(route, body);
    return Promise.reject(new Error('PineLens requires the Pine desktop or PineTab app'));
  }
  function make(tag, text, parent) { var el = document.createElement(tag); if(text) el.textContent=text; if(parent) parent.appendChild(el); return el; }
  // The same Three.js particle positions, colours and timing as PinePiP.
  function makeAmbient(host){
    var w=root,background=make('div','',host);background.className='pl-ambient';
    var logo=make('img','',background);logo.className='pl-ambient-logo';logo.alt='Pine Box';logo.src='data:image/png;base64,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';
    var enabled=false,model=null,raf=0,generation=0,loading=null,frames=0;
    function createParticles(T) {
      const renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(w.devicePixelRatio || 1, 1.5));
      background.appendChild(renderer.domElement);
      const scene = new T.Scene(), camera = new T.PerspectiveCamera(48, 1, .1, 100);
      camera.position.z = 9;
      const count = 1800, positions = new Float32Array(count * 3), seeds = new Float32Array(count * 4);
      for (let i = 0; i < count; i++) { seeds[i * 4] = (Math.random() - .5) * 16; seeds[i * 4 + 1] = Math.random() * Math.PI * 2; seeds[i * 4 + 2] = Math.random() * 2; seeds[i * 4 + 3] = Math.random() * Math.PI * 2; }
      const geo = new T.BufferGeometry(); geo.setAttribute('position', new T.BufferAttribute(positions, 3));
      const mat = new T.PointsMaterial({ color: 0x9bddb3, size: .035, transparent: true, opacity: .65, blending: T.AdditiveBlending, depthWrite: false });
      const cloud = new T.Points(geo, mat); scene.add(cloud);
      let size = '';
      return { draw(t) {
        const width = host.clientWidth, height = host.clientHeight, next = width + ':' + height;
        if (size !== next) { size = next; renderer.setSize(width, height); camera.aspect = width / Math.max(1, height); camera.updateProjectionMatrix(); }
        for (let i = 0; i < count; i++) {
          const x = seeds[i * 4], a = seeds[i * 4 + 1], r = seeds[i * 4 + 2], phase = seeds[i * 4 + 3];
          const clump = .25 + .75 * (.5 + .5 * Math.sin(t * .19 + x * .38 + phase));
          positions[i * 3] = x + Math.sin(t * .13 + a) * .7;
          positions[i * 3 + 1] = Math.sin(x * .55 + t * .45) * .65 + Math.cos(a + t * .12) * r * clump - 1;
          positions[i * 3 + 2] = Math.sin(a + t * .09) * r * clump;
        }
        geo.attributes.position.needsUpdate = true; cloud.rotation.z = Math.sin(t * .08) * .14;
        renderer.render(scene, camera);
      }, dispose() { geo.dispose(); mat.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); } };
    }

    function three(){
      if(root.THREE)return Promise.resolve(root.THREE);
      if(!loading)loading=new Promise(function(resolve,reject){var tag=document.createElement('script');tag.src=root.pineThreeUrl?root.pineThreeUrl():'/vendor/three.min.js';tag.onload=function(){root.THREE?resolve(root.THREE):reject(Error('Three.js unavailable'));};tag.onerror=function(){loading=null;reject(Error('Three.js unavailable'));};document.head.appendChild(tag);});
      return loading;
    }
    function draw(t){if(!enabled||!model)return;raf=root.requestAnimationFrame(draw);model.draw(t/1000);background.dataset.frames=String(++frames);}
    return {set:function(on){on=!!on;if(on===enabled)return;enabled=on;background.hidden=!on;generation++;var gen=generation;root.cancelAnimationFrame(raf);if(model){model.dispose();model=null;}if(on)three().then(function(T){if(enabled&&gen===generation){model=createParticles(T);raf=root.requestAnimationFrame(draw);}}).catch(function(){});}};
  }
  root.PineLens = {mount: function(host) {
    var bar=make('div','',host); bar.className='pl-bar';
    make('strong','PineLens',bar);
    var choice=make('select','',bar); choice.setAttribute('aria-label','Pine desktop');
    var stage=make('div','',host); stage.className='pl-stage'; stage.tabIndex=0; stage.setAttribute('aria-label','Remote desktop');
    var ambient=makeAmbient(stage);
    var img=make('img','',stage); img.alt='Live Pine desktop'; img.draggable=false;
    img.onload=function(){var entering=!stage.classList.contains('pl-live')||(root.PineVcr&&root.PineVcr.state(img)==='out');stage.classList.add('pl-live');ambient.set(false);if(entering&&root.PineVcr)root.PineVcr.set(img,true);};
    img.onerror=function(){stage.classList.remove('pl-live');ambient.set(active);};
    function clearFrame(){ambient.set(active);var hide=function(){stage.classList.remove('pl-live');img.removeAttribute('src');};if(stage.classList.contains('pl-live')&&root.PineVcr)root.PineVcr.set(img,false,{hide:hide});else hide();}
    var selection=make('div','',stage); selection.className='pl-selection'; selection.hidden=true;
    var status=make('div','Choose a Pine desktop to connect.',host); status.className='pl-status';
    var current='', frame=null, drawing=false, preview=null, start=null, crop=null;
    var pointers=new Map(), touchTimer=0, down=false, active=false, epoch=0, timer=0, zoom=1, panX=0, panY=0, panMode=false, lastMove=0;
    var queue=Promise.resolve(), button='left', gesture=null;
    function say(err) {status.textContent=err && err.message || String(err);}
    function enqueue(cmd) {
      var target=current, revision=frame && frame.revision;
      queue=queue.catch(function(){}).then(function(){
        return ask('/api/pinelens/hosts/'+encodeURIComponent(target)+'/command',Object.assign({revision:revision},cmd));
      }).catch(say);
      return queue;
    }
    function command(cmd) {if(current && frame && !drawing) return enqueue(cmd);}
    function release(){clearTimeout(touchTimer);touchTimer=0;if(down) command({type:'release'});down=false;pointers.clear();gesture=null;}
    function applyView(){
      var r=img.getBoundingClientRect(), box=stage.getBoundingClientRect();
      var limitX=Math.max(0,(r.width-box.width)/2),limitY=Math.max(0,(r.height-box.height)/2);
      panX=Math.max(-limitX,Math.min(limitX,panX));panY=Math.max(-limitY,Math.min(limitY,panY));
      img.style.transform='translate('+panX+'px,'+panY+'px) scale('+zoom+')';
    }
    function resetView(){zoom=1;panX=panY=0;img.style.transform='';}
    function changeZoom(value){zoom=Math.max(1,Math.min(4,value));img.style.transform='translate('+panX+'px,'+panY+'px) scale('+zoom+')';applyView();}
    function btn(text, action){var b=make('button',text,bar);b.type='button';b.onclick=function(){Promise.resolve().then(action).catch(say);};return b;}
    btn('Refresh desktops',loadHosts);
    btn('Full display',function(){release();drawing=false;preview=null;selection.hidden=true;stage.classList.remove('pl-drawing');frame=null;clearFrame();resetView();return enqueue({type:'full'});});
    btn('Saved lens',function(){release();frame=null;clearFrame();resetView();return enqueue({type:'lens'});});
    btn('Fullscreen',function(){if(document.fullscreenElement)return document.exitFullscreen();return host.requestFullscreen();});
    var right=btn('Left click',function(){button=button==='left'?'right':'left';right.textContent=button==='left'?'Left click':'Right click';});
    btn('Zoom −',function(){changeZoom(zoom-.25);});
    btn('Zoom +',function(){changeZoom(zoom+.25);});
    var pan=btn('Pan view',function(){release();panMode=!panMode;pan.textContent=panMode?'Control desktop':'Pan view';pan.setAttribute('aria-pressed',String(panMode));});
    btn('Reset view',resetView);
    var text=make('input','',bar);text.placeholder='Type on desktop';text.setAttribute('aria-label','Text to type on the remote desktop');
    var minutes=make('input','',bar);minutes.type='number';minutes.min='0.1';minutes.max='10';minutes.step='0.1';minutes.value='5';
    minutes.setAttribute('aria-label','Minutes of Pine Lens history to export');minutes.style.cssText='width:4em;min-width:4em;flex:0';
    btn('Export last minutes',async function(){
      var seconds=Number(minutes.value)*60;
      if(!current||!Number.isFinite(seconds)||seconds<=0)throw new Error('Choose a desktop and a positive duration.');
      var out=await ask('/api/pinelens/export',{host:current,seconds:seconds});say(out.say);
    });
    btn('Send text',function(){if(text.value){command({type:'text',text:text.value});text.value='';}});
    ['Enter','Tab','Backspace','Escape'].forEach(function(key){btn(key,function(){command({type:'key',key:key});});});
    if(api && api.lensPreview) {
      btn('Draw lens',async function(){
        release();preview=await api.lensPreview();drawing=true;crop=null;resetView();
        img.src='data:image/jpeg;base64,'+preview.jpeg;selection.hidden=true;stage.classList.add('pl-drawing');
        say('Draw a rectangle over the desktop, then Save lens.');
      });
      btn('Save lens',async function(){
        if(!drawing||!crop) throw new Error('Draw a lens area first');
        await api.lensSave({crop:crop,display:preview.display});drawing=false;preview=null;selection.hidden=true;stage.classList.remove('pl-drawing');frame=null;
        say('Lens saved · reconnecting to the cropped desktop…');
      });
      btn('Clear lens',async function(){await api.lensSave({crop:null});drawing=false;preview=null;selection.hidden=true;stage.classList.remove('pl-drawing');frame=null;});
    }
    function point(e){
      var r=img.getBoundingClientRect();if(!r.width||!r.height)return null;
      var x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
      return x>=0&&x<=1&&y>=0&&y<=1?{x:x,y:y}:null;
    }
    function pointer(action,p){if(p)command({type:'pointer',action:action,button:button,x:p.x,y:p.y});}
    function draw(p){
      if(!start||!p)return;crop={x:Math.min(start.x,p.x),y:Math.min(start.y,p.y),width:Math.abs(start.x-p.x),height:Math.abs(start.y-p.y)};
      var r=img.getBoundingClientRect(),s=stage.getBoundingClientRect();selection.hidden=false;
      Object.assign(selection.style,{left:(r.left-s.left+crop.x*r.width)+'px',top:(r.top-s.top+crop.y*r.height)+'px',width:(crop.width*r.width)+'px',height:(crop.height*r.height)+'px'});
    }
    stage.onpointerdown=function(e){
      var p=point(e);if(!p)return;e.preventDefault();stage.focus();stage.setPointerCapture(e.pointerId);
      if(drawing){start=p;draw(p);return;}
      pointers.set(e.pointerId,{e:e,p:p});
      if(pointers.size===2){clearTimeout(touchTimer);touchTimer=0;if(down)command({type:'release'});down=false;gesture=gestureMeasure();return;}
      if(panMode){gesture={x:e.clientX,y:e.clientY,d:0};return;}
      if(e.pointerType==='touch')touchTimer=setTimeout(function(){touchTimer=0;if(pointers.size===1){pointer('down',p);down=true;}},110);
      else {button=e.button===2?'right':button;pointer('down',p);down=true;}
    };
    function gestureMeasure(){var pts=Array.from(pointers.values());if(pts.length<2)return null;var a=pts[0].e,b=pts[1].e;return {x:(a.clientX+b.clientX)/2,y:(a.clientY+b.clientY)/2,d:Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)};}
    stage.onpointermove=function(e){
      var p=point(e);if(drawing){if(start)draw(p);return;}
      if(pointers.has(e.pointerId))pointers.set(e.pointerId,{e:e,p:p});
      if(pointers.size>1){var g=gestureMeasure();if(gesture&&g){
        var dx=g.x-gesture.x,dy=g.y-gesture.y,oldZoom=zoom;
        if(gesture.d>0)zoom=Math.max(1,Math.min(4,zoom*g.d/gesture.d));
        if(panMode||zoom>1||oldZoom>1){
          var box=stage.getBoundingClientRect(),ratio=zoom/oldZoom;
          var cx=gesture.x-box.left-box.width/2,cy=gesture.y-box.top-box.height/2;
          panX=cx-(cx-panX)*ratio+dx;panY=cy-(cy-panY)*ratio+dy;
          img.style.transform='translate('+panX+'px,'+panY+'px) scale('+zoom+')';applyView();
        }else if(Math.abs(dy)>12){command({type:'wheel',delta:dy>0?1:-1});}
        if(zoom>1||panMode||Math.abs(dy)>12)gesture=g;
      }return;}
      if(panMode){if(pointers.has(e.pointerId)&&gesture){panX+=e.clientX-gesture.x;panY+=e.clientY-gesture.y;applyView();gesture={x:e.clientX,y:e.clientY,d:0};}return;}
      if(p&&Date.now()-lastMove>45){lastMove=Date.now();pointer('move',p);}
    };
    stage.onpointerup=function(e){
      if(drawing){draw(point(e));start=null;return;}
      var held=pointers.get(e.pointerId);if(!held)return;
      clearTimeout(touchTimer);touchTimer=0;
      var p=point(e)||held.p;
      if(pointers.size===1&&!gesture&&!panMode){if(!down)pointer('down',p);pointer('up',p);}
      else if(down)command({type:'release'});
      down=false;pointers.delete(e.pointerId);if(!pointers.size)gesture=null;
    };
    stage.onpointercancel=release;
    stage.oncontextmenu=function(e){e.preventDefault();};
    stage.onwheel=function(e){e.preventDefault();var p=point(e);if(p){pointer('move',p);command({type:'wheel',delta:e.deltaY>0?-1:1});}};
    stage.onkeydown=function(e){
      if(drawing||!frame||['Control','Shift','Alt','Meta'].includes(e.key))return;
      if(e.key.length!==1&&!/^(Enter|Tab|Escape|Backspace|Delete|Arrow.*|Home|End|PageUp|PageDown|F\d{1,2})$/.test(e.key))return;
      e.preventDefault();e.stopPropagation();var mods=[];if(e.ctrlKey)mods.push('ctrl');if(e.shiftKey)mods.push('shift');if(e.altKey)mods.push('alt');if(e.metaKey)mods.push('meta');
      command({type:'key',key:e.key,modifiers:mods});
    };
    choice.onchange=function(){release();current=choice.value;resetView();frame=null;clearFrame();try{localStorage.setItem('pineLensHost',current);}catch(e){};};
    async function loadHosts(){
      var out=await ask('/api/pinelens/hosts');choice.textContent='';
      var own=api&&api.lensState?await api.lensState():null;var remembered='';try{remembered=localStorage.getItem('pineLensHost')||'';}catch(e){}
      (out.hosts||[]).forEach(function(h){var option=make('option',h.name,choice);option.value=h.id;});
      var ids=(out.hosts||[]).map(function(h){return h.id;});
      var selected=ids.includes(current)?current:ids.includes(remembered)?remembered:own&&ids.includes(own.id)?own.id:ids[0]||'';
      if(selected!==current){release();frame=null;}current=selected;choice.value=current;
      if(!current)say('No Pine desktop is connected. Start Pine on the host computer.');
    }
    async function poll(generation){
      if(!active||generation!==epoch)return;
      try{
        if(!current)await loadHosts();
        if(current&&!drawing){var id=current;var out=await ask('/api/pinelens/hosts/'+encodeURIComponent(id)+'/view');
          if(active&&generation===epoch&&id===current&&!drawing){frame=out.frame;
            if(frame)img.src='data:image/jpeg;base64,'+frame.jpeg;
            else clearFrame();
            var exported=out.info.export, exportText=exported?(exported.state==='done'?' · Lens video saved'+(exported.partial?' (available history)':''):exported.state==='failed'?' · '+exported.error:' · Exporting Lens video'):'';
            var held=out.info.history&&out.info.history.seconds;
            say(out.info.error||(frame?(out.info.control?'Connected · tap or drag to control · pinch to zoom ? two fingers pan when zoomed ? Pan view for one-finger panning':'View only · desktop input unavailable'):'Connecting to the desktop…')+(held?' · '+Math.floor(held)+'s recorded':'')+exportText);}}
      }catch(err){frame=null;clearFrame();say(err);}
      if(active&&generation===epoch)timer=setTimeout(function(){poll(generation);},180);
    }
    function visibility(){var want=host.classList.contains('open')&&!document.hidden;
      if(want===active)return;if(!want)release();active=want;ambient.set(active&&!stage.classList.contains('pl-live'));if(root.PineSfxTv&&root.PineSfxTv.viewChanged)root.PineSfxTv.viewChanged();epoch++;clearTimeout(timer);if(active)poll(epoch);else{frame=null;clearFrame();}}
    new MutationObserver(visibility).observe(host,{attributes:true,attributeFilter:['class']});
    document.addEventListener('visibilitychange',visibility);root.addEventListener('blur',release);
    visibility();
  }};
})(window);
