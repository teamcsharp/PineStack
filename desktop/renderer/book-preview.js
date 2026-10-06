/* A preview reader: it never selects a title or changes the station transport. */
(function(root){
  'use strict';
  var config=JSON.parse(document.getElementById('bp-config').textContent),manifest=null;
  var current={kind:'',chapterIndex:0,pageIndex:0,pageCount:0,spreadCount:0,zoom:100,fit:''};
  var stage=document.querySelector('.bp-stage'),spread=document.querySelector('.bp-spread'),frame=document.getElementById('bp-epub');
  var prev=document.getElementById('bp-prev'),next=document.getElementById('bp-next'),pageInput=document.getElementById('bp-page-input');
  var chapterSelect=document.getElementById('bp-chapter'),zoomSelect=document.getElementById('bp-zoom'),status=document.getElementById('bp-status'),message=document.getElementById('bp-message');
  var pdfSlots=[document.querySelector('.bp-pdf-left'),document.querySelector('.bp-pdf-right')];
  var numbers=[document.getElementById('bp-left-number'),document.getElementById('bp-right-number')];
  var controller=new AbortController(),destroyed=false,chapterGeneration=0,resizeTimer=0,step=0,chapterLoading=false,resizeObserver,pendingChapter=null;
  var readyResolve,readyReject,ready=new Promise(function(resolve,reject){readyResolve=resolve;readyReject=reject;});
  // Catch here as well so an unopened parent console never gets an unhandled rejection.
  ready.catch(function(){});
  function showMessage(text){message.textContent=text;message.hidden=!text;}
  function fail(error){showMessage(error.message||String(error));status.textContent='Preview could not be opened';}
  function state(){return Object.assign({},current);}
  function paint(){
    var start=current.pageIndex+1,end=Math.min(current.pageCount,current.pageIndex+2);
    pageInput.value=start;pageInput.max=current.pageCount||1;
    document.getElementById('bp-page-total').textContent='/ '+current.pageCount;
    prev.disabled=!current.pageIndex&&(current.kind!=='epub'||!current.chapterIndex);
    next.disabled=current.pageIndex+2>=current.pageCount&&(current.kind!=='epub'||current.chapterIndex+1>=manifest.chapters.length);
    chapterSelect.value=current.chapterIndex;
    numbers[0].textContent=start;numbers[1].textContent=end>start?end:'';
    status.textContent=(current.kind==='epub'?'Chapter '+(current.chapterIndex+1)+' of '+manifest.chapters.length+' · ':'')+'Pages '+start+(end>start?'–'+end:'')+' of '+current.pageCount+(current.kind==='epub'?' · Reflowed preview':' · Original PDF pages');
  }
  function dimensions(ratios,scale){
    var gutter=20,availableWidth=Math.max(140,stage.clientWidth-28),availableHeight=Math.max(90,stage.clientHeight-28);
    var fitted=Math.min(availableHeight,(availableWidth-gutter)/(ratios[0]+ratios[1]));
    /* [book-fill] "Fit width": the facing pages take the whole width of the window and the page scrolls. */
    if(current.fit==='width'&&current.kind==='pdf'){scale=Math.max(1,(availableWidth-gutter)/(ratios[0]+ratios[1])/fitted);current.zoom=Math.round(scale*100);}
    var height=fitted*scale;
    var left=height*ratios[0],right=height*ratios[1];
    spread.style.width=(left+right+gutter)+'px';spread.style.height=height+'px';
    spread.style.setProperty('--bp-page-width',left+'px');spread.style.setProperty('--bp-right-width',right+'px');spread.style.setProperty('--bp-gutter',gutter+'px');
    return {width:left+right+gutter,height:height,pageWidth:left,gutter:gutter};
  }
  function pdfFeedback(){
    var images=pdfSlots.map(function(slot){return slot.querySelector('img');}).filter(function(img){return !img.hidden;});
    var failed=images.find(function(img){return img.dataset.loadState==='error';});
    if(failed)showMessage('Page '+failed.dataset.page+' could not be rendered. Try another page or reopen the preview.');
    else showMessage(images.some(function(img){return img.dataset.loadState==='loading';})?'Rendering pages…':'');
  }
  function layoutPdf(){
    if(!manifest||destroyed)return;
    var pages=manifest.pages,left=pages[current.pageIndex],right=pages[current.pageIndex+1]||left;
    dimensions([left.width/left.height,right.width/right.height],current.zoom/100);
    pdfSlots.forEach(function(slot,index){
      var page=pages[current.pageIndex+index],img=slot.querySelector('img');slot.hidden=false;img.hidden=!page;
      if(page){
        img.alt='Page '+(current.pageIndex+index+1)+' of '+manifest.title;
        if(img.getAttribute('src')!==page.url){
          img.dataset.loadState='loading';img.dataset.page=page.index+1;
          img.onload=function(){if(!destroyed&&img.getAttribute('src')===page.url&&current.pageIndex+index===page.index){img.dataset.loadState='loaded';pdfFeedback();}};
          img.onerror=function(){if(!destroyed&&current.pageIndex+index===page.index){img.dataset.loadState='error';pdfFeedback();}};
          img.src=page.url;
        }
      }else{img.removeAttribute('src');img.alt='';delete img.dataset.loadState;}
    });
    spread.hidden=false;paint();pdfFeedback();
  }
  function important(style,key,value){style.setProperty(key,value,'important');}
  function layoutEpub(){
    if(destroyed||chapterLoading||!frame.contentDocument||!frame.contentDocument.body)return;
    /* [book-fill] A reflowed book has no page shape of its own: at "Fit width" its two pages spread across the whole window. */
    var wide=current.fit==='width'?Math.max(.71,(Math.max(140,stage.clientWidth-28)-20)/2/Math.max(90,stage.clientHeight-28)):.71;
    var doc=frame.contentDocument,body=doc.body,scale=current.zoom/100,box=dimensions([wide,wide],1);
    var marginX=Math.max(12,Math.min(38,box.pageWidth*.075)),marginY=Math.max(22,Math.min(35,box.height*.06));
    var textWidth=(box.pageWidth-2*marginX)/scale,textHeight=(box.height-2*marginY)/scale,gap=(2*marginX+box.gutter)/scale;
    frame.style.left=marginX+'px';frame.style.top=marginY+'px';frame.style.width=(box.width-2*marginX)+'px';frame.style.height=(box.height-2*marginY)+'px';
    body.classList.add('bp-reflow');
    var bounds=doc.getElementById('bp-pagination-bounds');
    if(!bounds){bounds=doc.createElement('style');bounds.id='bp-pagination-bounds';doc.head.appendChild(bounds);}
    bounds.textContent='body.bp-reflow img,body.bp-reflow svg{max-height:'+textHeight+'px!important}body.bp-reflow figure{max-height:'+textHeight+'px!important}';
    var values={width:textWidth+'px',height:textHeight+'px','min-width':'0','min-height':'0','max-width':'none','max-height':'none',margin:'0',padding:'0',overflow:'visible',position:'relative','column-width':textWidth+'px','column-count':'auto','column-gap':gap+'px','column-fill':'auto','column-rule':'none',background:'transparent',zoom:String(scale),transform:'none','transform-origin':'0 0',boxSizing:'border-box'};
    Object.keys(values).forEach(function(key){important(body.style,key==='boxSizing'?'box-sizing':key,values[key]);});
    step=textWidth+gap;
    current.pageCount=Math.max(1,Math.round((body.scrollWidth+gap)/step));current.spreadCount=Math.ceil(current.pageCount/2);
    current.pageIndex=Math.max(0,Math.min(current.pageIndex,2*(current.spreadCount-1)));
    important(body.style,'transform','translateX('+(-current.pageIndex*step)+'px)');
    spread.hidden=false;showMessage('');paint();
  }
  function anchor(){
    try{
      var doc=frame.contentDocument;
      var elements=Array.from(doc.body.querySelectorAll('p,h1,h2,h3,h4,li,figure,table,blockquote,div'));
      return elements.find(function(el){var rect=el.getBoundingClientRect();return rect.width&&rect.height&&rect.left>=-1&&rect.left<frame.clientWidth/2&&rect.bottom>0&&rect.top<frame.clientHeight;})||null;
    }catch(_){return null;}
  }
  function relayout(){
    if(current.kind==='pdf')layoutPdf();
    else if(current.kind==='epub'&&!chapterLoading){
      var passage=anchor();layoutEpub();
      if(passage){var left=passage.getBoundingClientRect().left/(current.zoom/100)+current.pageIndex*step;current.pageIndex=Math.max(0,Math.floor(left/step/2)*2);layoutEpub();}
    }
  }
  function settle(doc){
    var assets=Array.from(doc.images).map(function(img){if(img.complete)return Promise.resolve();return new Promise(function(resolve){img.addEventListener('load',resolve,{once:true});img.addEventListener('error',resolve,{once:true});});});
    if(doc.fonts)assets.push(doc.fonts.ready);
    return Promise.race([Promise.all(assets),new Promise(function(resolve){setTimeout(resolve,3500);})]).then(function(){return new Promise(function(resolve){root.requestAnimationFrame(function(){root.requestAnimationFrame(resolve);});});});
  }
  async function loadChapter(index,last){
    if(destroyed)return;
    index=Math.max(0,Math.min(manifest.chapters.length-1,Number(index)||0));
    if(pendingChapter){pendingChapter();pendingChapter=null;}
    var generation=++chapterGeneration;chapterLoading=true;current.chapterIndex=index;current.pageIndex=0;
    prev.disabled=true;next.disabled=true;showMessage('Opening chapter…');frame.hidden=false;spread.hidden=true;
    await new Promise(function(resolve,reject){
      pendingChapter=resolve;frame.onload=function(){pendingChapter=null;resolve();};frame.onerror=function(){pendingChapter=null;reject(new Error('This chapter could not be opened'));};frame.src=manifest.chapters[index].url;
    });
    if(destroyed||generation!==chapterGeneration)return;
    var doc=frame.contentDocument;
    if(!doc||!doc.body)throw new Error('This chapter could not be opened');
    frame.title=manifest.chapters[index].title||'Book chapter';
    var defaults=doc.createElement('style');defaults.textContent='html{margin:0!important;padding:0!important;overflow:hidden!important;background:transparent!important;min-width:0!important;height:100%!important}body{color:#24211d;font-family:Georgia,serif;line-height:1.5}body.bp-reflow{color-scheme:light;orphans:2;widows:2}img,svg,video{max-width:100%!important;max-height:100%!important;object-fit:contain}figure,table,pre{max-width:100%!important;box-sizing:border-box}h1,h2,h3,h4,h5,h6{break-after:avoid;break-inside:avoid}figure,table{break-inside:avoid}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:inherit}';
    // Defaults precede publisher CSS; pagination constraints use !important.
    doc.head.insertBefore(defaults,doc.head.firstChild);
    doc.addEventListener('keydown',keyboard);
    doc.addEventListener('wheel',wheel,{passive:false});doc.addEventListener('touchstart',touchStart,{passive:true});doc.addEventListener('touchend',touchEnd,{passive:true});   /* [book-scroll] */
    doc.addEventListener('click',function(event){
      var link=event.target.closest('a');if(!link)return;event.preventDefault();
      try{
        var url=new URL(link.href,frame.src),target=new URL(frame.src);
        function visitAnchor(){var activeDoc=frame.contentDocument,element=activeDoc&&activeDoc.getElementById(decodeURIComponent(url.hash.slice(1)));if(element){var x=element.getBoundingClientRect().left/(current.zoom/100)+current.pageIndex*step;goToPage(Math.floor(x/step)+1);}}
        if(url.pathname===target.pathname&&url.hash)visitAnchor();
        else{var linkedChapter=manifest.chapters.findIndex(function(chapter){return new URL(chapter.url,root.location.href).pathname===url.pathname;});if(linkedChapter>=0)loadChapter(linkedChapter,false).then(function(){if(url.hash)visitAnchor();}).catch(fail);} 
      }catch(_){}
    });
    chapterLoading=false;layoutEpub();
    await settle(doc);
    if(destroyed||generation!==chapterGeneration)return;
    layoutEpub();if(last){current.pageIndex=2*(current.spreadCount-1);layoutEpub();}
    // Images that arrive after the timeout can still change pagination.
    if(doc.fonts)doc.fonts.addEventListener('loadingdone',function(){if(!destroyed&&generation===chapterGeneration)relayout();});
    Array.from(doc.images).forEach(function(img){if(!img.complete){img.addEventListener('load',relayout,{once:true});img.addEventListener('error',relayout,{once:true});}});
    chapterSelect.value=index;
  }
  async function move(direction){
    if(!manifest||chapterLoading||destroyed)return;
    var target=current.pageIndex+direction*2;
    if(current.kind==='epub'&&target<0&&current.chapterIndex>0)return loadChapter(current.chapterIndex-1,true);
    if(current.kind==='epub'&&target>=current.pageCount&&current.chapterIndex+1<manifest.chapters.length)return loadChapter(current.chapterIndex+1,false);
    current.pageIndex=Math.max(0,Math.min(target,2*(current.spreadCount-1)));
    if(current.kind==='pdf')layoutPdf();else layoutEpub();
  }
  function goToPage(number){if(!manifest||chapterLoading)return;current.pageIndex=2*Math.floor((Math.max(1,Math.min(current.pageCount,Number(number)||1))-1)/2);if(current.kind==='pdf')layoutPdf();else layoutEpub();}
  /* [book-scroll] THE WHEEL, A TRACKPAD AND A FINGER TURN THE PAGES.
   *
   * "allow me to swipe or scroll the pages to change pages. I want to be able
   *  to scroll pages endlessly."
   *
   * While the page still has more to show - a zoomed page taller than the
   * window - a scroll moves down the page, as it always did. At the foot of
   * the page the same scroll carries on into the next two pages (and starts
   * at their head); at the head, into the two before (and starts at their
   * foot). So one gesture reads the whole book, and across an EPUB's
   * chapters, without reaching for a button.
   *
   * A trackpad keeps sending movement after the fingers lift. One push is one
   * turn: after a turn nothing more is taken until the stream has paused, or
   * for a little over half a second if it never does. */
  var turnLoad=0,turnDirection=0,turnAt=0,turnHeldUntil=0,wheelAt=0,pageMovedAt=0,touch=null,turning=false;
  function canScroll(direction){return direction>0?stage.scrollTop+stage.clientHeight<stage.scrollHeight-2:stage.scrollTop>2;}
  function canPan(direction){return direction>0?stage.scrollLeft+stage.clientWidth<stage.scrollWidth-2:stage.scrollLeft>2;}
  function hasMore(direction){
    if(!manifest)return false;
    if(direction>0)return current.pageIndex+2<current.pageCount||(current.kind==='epub'&&current.chapterIndex+1<manifest.chapters.length);
    return current.pageIndex>0||(current.kind==='epub'&&current.chapterIndex>0);
  }
  function turn(direction){
    if(turning||chapterLoading||destroyed||!hasMore(direction))return Promise.resolve(false);
    turning=true;
    return move(direction).then(function(){
      /* carry on reading where the eye is: the head of the next pages, the foot of the ones before */
      stage.scrollTop=direction>0?0:stage.scrollHeight;
      spread.classList.remove('bp-turn-next','bp-turn-prev');void spread.offsetWidth;spread.classList.add(direction>0?'bp-turn-next':'bp-turn-prev');
      return true;
    }).catch(function(error){fail(error);return false;}).then(function(done){turning=false;return done;});
  }
  function wheel(event){
    if(event.ctrlKey||event.metaKey||!manifest)return;                 /* a pinch, or the browser's own zoom */
    var dx=event.deltaX,dy=event.deltaY;
    if(event.deltaMode===1){dx*=32;dy*=32;}else if(event.deltaMode===2){dx*=stage.clientWidth;dy*=stage.clientHeight;}
    if(event.shiftKey&&!dx){dx=dy;dy=0;}
    var sideways=Math.abs(dx)>Math.abs(dy)*1.2,amount=sideways?dx:dy,direction=amount>0?1:-1,time=Date.now(),flowing=time-wheelAt<140;
    wheelAt=time;
    if(!amount)return;
    var inside=event.target&&event.target.ownerDocument===document&&stage.contains(event.target);
    if(inside&&(sideways?canPan(direction):canScroll(direction))){turnLoad=0;pageMovedAt=time;return;}   /* the page itself has more to show */
    event.preventDefault();
    if(!flowing)turnHeldUntil=0;                                       /* the stream paused: the push that turned the page is over */
    if(time<turnHeldUntil)return;                                      /* the tail of the push that already turned the page */
    turnLoad=(direction===turnDirection&&time-turnAt<260?turnLoad:0)+Math.abs(amount);turnDirection=direction;turnAt=time;
    /* a scroll that has only just reached the foot of the page has not asked for the next one yet: that takes a firmer push */
    if(turnLoad<(time-pageMovedAt<450?260:Math.abs(amount)<40?90:50))return;
    turnLoad=0;turnHeldUntil=time+650;
    turn(direction);
  }
  function touchStart(event){var point=event.touches&&event.touches.length===1?event.touches[0]:null;touch=point?{x:point.clientX,y:point.clientY,at:Date.now(),up:canScroll(-1),down:canScroll(1)}:null;}
  function touchEnd(event){
    var from=touch,point=event.changedTouches&&event.changedTouches[0];touch=null;
    if(!from||!point||Date.now()-from.at>900)return;
    var dx=point.clientX-from.x,dy=point.clientY-from.y;
    if(Math.abs(dx)>=50&&Math.abs(dx)>Math.abs(dy)*1.3&&!canPan(dx<0?1:-1))turn(dx<0?1:-1);                     /* a swipe to the left is the next page */
    else if(Math.abs(dy)>=70&&Math.abs(dy)>Math.abs(dx)*1.3&&!(dy<0?from.down:from.up))turn(dy<0?1:-1);       /* a swipe up at the foot of the page, too */
  }
  /* [book-fill] TWO FITS. "Fit page" keeps both pages whole in the window; "Fit width" gives them the whole
   * width of it and lets the page scroll. The choice between the two is remembered; a zoom step is not. */
  function rememberFit(){try{root.localStorage.setItem('pineBookPreviewFit',current.fit==='width'?'width':'page');}catch(_){}}
  function savedFit(){try{return root.localStorage.getItem('pineBookPreviewFit')==='width'?'width':'';}catch(_){return '';}}
  function showFit(){stage.classList.toggle('bp-fit-width',current.fit==='width'&&current.kind==='pdf');zoomSelect.value=current.fit==='width'?'width':String(current.zoom);}
  function setZoom(number){
    var passage=current.kind==='epub'?anchor():null,width=number==='width';
    if(width||Number(number)===100)current.fit=width?'width':'';else current.fit='';
    if(width||Number(number)===100)rememberFit();
    current.zoom=width?100:Math.max(100,Math.min(200,Number(number)||100));showFit();
    if(current.kind==='pdf')layoutPdf();else if(!chapterLoading){layoutEpub();if(passage){var x=passage.getBoundingClientRect().left/(current.zoom/100)+current.pageIndex*step;goToPage(Math.floor(x/step)+1);}}
  }
  function selectChapter(index){return loadChapter(index,false);}
  function keyboard(event){if((event.target.matches&&event.target.matches('input,select,textarea'))||event.altKey||event.ctrlKey||event.metaKey)return;if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();move(1).catch(fail);}if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();move(-1).catch(fail);}
    /* [book-scroll] the keys any reader has: Space reads on (Shift+Space back), Home and End are the covers */
    if((event.key===' '||event.key==='Spacebar')&&!(event.target.matches&&event.target.matches('button,a'))){event.preventDefault();var way=event.shiftKey?-1:1;if(canScroll(way))stage.scrollBy({top:way*stage.clientHeight*.85,behavior:'smooth'});else turn(way);}
    if(event.key==='Home'){event.preventDefault();if(current.kind==='epub'&&current.chapterIndex>0)loadChapter(0,false).catch(fail);else goToPage(1);}
    if(event.key==='End'){event.preventDefault();if(current.kind==='epub'&&current.chapterIndex+1<manifest.chapters.length)loadChapter(manifest.chapters.length-1,true).catch(fail);else goToPage(current.pageCount);}}
  function destroy(){if(destroyed)return;destroyed=true;chapterGeneration++;if(pendingChapter){pendingChapter();pendingChapter=null;}controller.abort();clearTimeout(resizeTimer);if(resizeObserver)resizeObserver.disconnect();root.removeEventListener('keydown',keyboard);frame.onload=null;frame.removeAttribute('src');pdfSlots.forEach(function(slot){slot.querySelector('img').removeAttribute('src');});}
  prev.onclick=function(){move(-1).catch(fail);};next.onclick=function(){move(1).catch(fail);};
  pageInput.onchange=function(){goToPage(pageInput.value);};pageInput.onkeydown=function(event){if(event.key==='Enter')goToPage(pageInput.value);};
  zoomSelect.onchange=function(){setZoom(zoomSelect.value);};chapterSelect.onchange=function(){selectChapter(chapterSelect.value).catch(fail);};
  /* [book-scroll] [book-fill] the page itself: scroll or swipe to turn, double click to swap the two fits */
  stage.addEventListener('wheel',wheel,{passive:false});stage.addEventListener('touchstart',touchStart,{passive:true});stage.addEventListener('touchend',touchEnd,{passive:true});
  stage.addEventListener('dblclick',function(event){if(event.target.closest&&event.target.closest('a,button,input,select'))return;setZoom(current.fit==='width'?100:'width');});
  root.addEventListener('keydown',keyboard);root.addEventListener('pagehide',destroy,{once:true});
  resizeObserver=new ResizeObserver(function(){clearTimeout(resizeTimer);resizeTimer=setTimeout(relayout,100);});resizeObserver.observe(stage);
  root.PineBookPreview={ready:ready,next:function(){return move(1);},previous:function(){return move(-1);},turn:turn,setZoom:setZoom,goToPage:goToPage,selectChapter:selectChapter,state:state,destroy:destroy};
  (async function(){
    var response=await root.fetch(config.manifestUrl,{signal:controller.signal});
    if(!response.ok)throw new Error('Book preview is unavailable ('+response.status+')');
    manifest=await response.json();current.kind=manifest.kind;document.title=manifest.title;document.getElementById('bp-title').textContent=manifest.title;
    current.fit=savedFit();showFit();   /* [book-fill] the fit that was chosen last time */
    if(current.kind==='pdf'){
      if(!manifest.pages.length)throw new Error('This PDF has no pages');current.pageCount=manifest.pages.length;current.spreadCount=Math.ceil(current.pageCount/2);layoutPdf();
    }else{
      if(!manifest.chapters.length)throw new Error('This EPUB has no readable chapters');document.getElementById('bp-chapter-label').hidden=false;
      manifest.chapters.forEach(function(chapter,index){var option=document.createElement('option');option.value=index;option.textContent=chapter.title||'Chapter '+(index+1);chapterSelect.appendChild(option);});
      await loadChapter(0,false);
    }
    readyResolve(state());
  })().catch(function(error){if(!destroyed)fail(error);readyReject(error);});
})(window);
