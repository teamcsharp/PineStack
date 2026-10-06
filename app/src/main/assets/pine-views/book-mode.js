/* Book Mode: one playback owner, ordered completion receipts, bounded reader DOM. */
(function(root){
  'use strict';
  var scriptHost=null, scriptPane=null, bookHost=null, locatedLine=null, findGeneration=0, findOffset=0;
  var ui={}, state=null, libraryOpen=false, playing=false, generation=0, current=null, next=null, audio=null, second=null, timer=0;
  var receipts=Promise.resolve();var prepared=Object.create(null);var shelfFirstOffset=0;var listOffset=0, listTotal=0, query='', loading=false, readerBook='', readerOffset=0, readerTotal=0, follow=true;
  function node(tag,cls,text){var n=document.createElement(tag); if(cls)n.className=cls; if(text!=null)n.textContent=text; return n;}
  function base(){if(/^https?:$/.test(root.location.protocol))return ''; return String(root.pineStationBase?root.pineStationBase():'http://127.0.0.1:8096').replace(/\/$/,'');}
  function key(){try{if(typeof root.key==='function')return root.key(); if(typeof SERVER_KEY!=='undefined')return SERVER_KEY;}catch(e){} return root.PINE_KEY||'';}
  function api(path,body){
    var bridge=root.pineDesktop;
    if(bridge)return body===undefined?bridge.get(path):bridge.post(path,body);
    var headers={}; if(key())headers.Authorization='Bearer '+key();
    if(body!==undefined)headers['Content-Type']='application/json';
    return root.fetch(base()+path,{method:body===undefined?'GET':'POST',headers:headers,body:body===undefined?undefined:JSON.stringify(body)}).then(function(r){return r.json().then(function(v){if(!r.ok)throw new Error(v.detail||String(r.status));return v;});});
  }
  function voiceVolume(){try{return Math.min(1,Math.max(0,root.pineLevels?root.pineLevels.effective().voice:1));}catch(e){return 1;}}
  function source(clip){return base()+clip.path+(clip.sig?(clip.path.indexOf('?')<0?'?':'&')+'t='+encodeURIComponent(clip.sig):'');}
  function say(text){if(ui.status)ui.status.textContent=text;}
  function button(label,fn){var b=node('button','',label); b.type='button'; b.onclick=function(){Promise.resolve().then(fn).catch(function(e){say(e.message);});};return b;}
  function stop(){prepared=Object.create(null);if(ui.video){ui.video.pause();ui.video.hidden=true;}playing=false;generation++; clearTimeout(timer);if(audio){audio.pause();audio.removeAttribute('src');audio.load();}if(second){second.pause();second.removeAttribute('src');second.load();}audio=null;second=null;current=null;next=null;paintPlayback();}
  function paintPlayback(){
    if(ui.play)ui.play.textContent=playing?'Pause reading':'Read';
    if(ui.start){ui.start.innerHTML=playing?'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12M16 6v12"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 11 7-11 7z"/></svg>';ui.start.title=playing?'Pause reading':'Start reading selected book';ui.start.setAttribute('aria-label',ui.start.title);ui.start.setAttribute('aria-pressed',String(playing));}
    if(ui.transport)ui.transport.textContent=state&&state.active?(playing?'Book reading · FM paused':'Book reading paused · FM paused'):'Browsing books · Pine Box FM continues';
  }
  function focusCover(book){
    Array.prototype.forEach.call(ui.books.children,function(card){var chosen=card.dataset.book===book;card.classList.toggle('bm-selected',chosen);var cover=card.querySelector('.bm-cover');if(cover)cover.setAttribute('aria-pressed',String(chosen));});
  }
  function paintState(s){
    state=s;document.body.classList.toggle('pine-book-mode',!!s.active);ui.panel.hidden=!libraryOpen;
    if(scriptPane)scriptPane.classList.toggle('sp-book-reading',libraryOpen&&ui.panel.parentNode===scriptPane);
    ui.toggle.title=libraryOpen?'Close book library':'Book Mode';ui.toggle.setAttribute('aria-label',ui.toggle.title);ui.toggle.setAttribute('aria-pressed',String(libraryOpen));ui.toggle.setAttribute('aria-expanded',String(libraryOpen));paintPlayback();focusCover(s.book);
    ui.title.textContent=s.title||'Choose a book';ui.speed.value=s.preferences.speed;ui.gap.value=s.preferences.gap_ms;ui.blend.value=s.preferences.blend_ms;
    if(ui.scan)ui.scan.value=s.preferences.scan_seconds||300;if(ui.buffer)ui.buffer.value=s.preferences.buffer_lines||4;ui.routing.value=s.preferences.routing;ui.scope.value=s.preferences.scope;ui.show.value=s.preferences.show;
    ui.research.checked=s.preferences.research;ui.sfx.checked=s.preferences.sfx;if(ui.nodeName)ui.nodeName.value=s.preferences.reader_node.label;
    Object.keys(ui.readers).forEach(function(r){ui.readers[r].checked=s.preferences.readers.indexOf(r)>=0;});
    try{if(root.PineSfxTv)root.PineSfxTv.veil(s.active);}catch(e){}
    root.dispatchEvent(new CustomEvent('pine-book-mode',{detail:s}));
    if(ui.badge){ui.badge.hidden=!s.active;ui.badge.textContent='📖 '+(s.title||'Book library')+' · '+(s.preferences.show==='read'?'Narration':'Book discussion')+' · Radio banking';}
  }
  async function pref(values){var resets=['readers','reader_node','routing','scope','show','research','sfx'].some(function(k){return k in values;});var resume=playing&&resets;if(resets){stop();await receipts.catch(function(){});receipts=Promise.resolve();}var p=await api('/api/books/preferences',values);state.preferences=p;if(resets)state=await api('/api/books/state');paintState(state);if(audio)audio.playbackRate=p.speed;if(second)second.playbackRate=p.speed;if(resume)await play();}
  async function toggle(){
    if(ui.ready)await ui.ready;
    if(scriptPane&&ui.panel.parentNode!==scriptPane)place(scriptPane);
    if(libraryOpen){libraryOpen=false;paintState(state);return;}
    await enable();
  }
  async function returnToFm(){
    stop();await receipts.catch(function(){});receipts=Promise.resolve();
    if(state&&state.active)paintState(await api('/api/books/mode',{active:false}));
    var dedicated=ui.panel.parentNode===bookHost;libraryOpen=false;paintState(state);
    if(dedicated){if(root.PineViewRail)root.PineViewRail.open('script');else if(root.PineViewChrome)root.PineViewChrome.show('script');}
  }
  async function library(reset,offset){
    if(loading)return;loading=true;
    try{
      if(reset){listOffset=Math.max(0,offset||0);shelfFirstOffset=listOffset;ui.books.replaceChildren();}
      var q=query,got=await api('/api/books?q='+encodeURIComponent(q)+'&offset='+listOffset+'&limit=40');
      if(q!==query)return;
      listTotal=got.total;listOffset+=got.books.length;
      got.books.forEach(function(book){
        var card=node('div','bm-card');card.dataset.book=book.id;
        var face=button('',function(){return select(book.id,false);});face.className='bm-cover';face.setAttribute('aria-label','Select '+book.title);face.setAttribute('aria-pressed',String(book.id===state.book));
        var fallback=node('span','bm-cover-title',book.title),cover=node('img','');cover.alt=book.title;cover.loading='lazy';cover.decoding='async';face.appendChild(fallback);face.appendChild(cover);card.appendChild(face);
        cover.onload=function(){face.classList.add('bm-cover-loaded');};
        function jsonCover(){return api(book.cover||'/api/books/'+book.id+'/cover').then(function(c){if(!c.svg)throw Error('Cover is unavailable');cover.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(c.svg);});}
        var retried=false;cover.onerror=function(){face.classList.remove('bm-cover-loaded');if(book.cover_url&&!retried){retried=true;jsonCover().catch(function(){face.title='Title cover · '+book.title;});}else face.title='Title cover · '+book.title;};
        if(book.cover_url)cover.src=/^https?:\/\//.test(book.cover_url)?book.cover_url:base()+book.cover_url;else jsonCover().catch(function(){face.title='Title cover · '+book.title;});
        var title=button(book.title,function(){return select(book.id,false);});title.className='bm-card-title';card.appendChild(title);
        card.appendChild(node('small','', (book.author?book.author+' · ':'')+book.kind.toUpperCase()+(book.bookmark?' · resume at sentence '+(book.bookmark.last_line+2):'')));
        var read=button('Read',function(){return select(book.id,true);});read.className='bm-read';card.appendChild(read);card.appendChild(button('Preview',function(){return preview(book.id,book.title);}));ui.books.appendChild(card);
      });
      while(ui.books.children.length>200){ui.books.firstChild.remove();shelfFirstOffset++;}   /* [book-shelf] */
      focusCover(state.book);
      ui.count.textContent=got.total+' books · alphabetical · DGX scans every '+((state.preferences.scan_seconds||300)/60)+' min'; if(!got.total&&got.scanning){say('The DGX is scanning the book library…');setTimeout(function(){if(libraryOpen)library(true).catch(function(e){say(e.message);});},4000);}else if((got.errors||[]).length)say(got.errors.join(' · '));else if(!got.total)say('No books available. Check the source folders, then refresh.');
    }finally{loading=false;if(q!==query)setTimeout(function(){library(true).catch(function(e){say(e.message);});},0);}
  }
  function popup(title){var d=node('dialog','bm-dialog'),h=node('h2','',title),body=node('div','bm-dialog-body');d.appendChild(h);d.appendChild(body);d.appendChild(button('Close',function(){d.close();d.remove();}));document.body.appendChild(d);d.showModal();d.addEventListener('cancel',function(){d.remove();});return {dialog:d,body:body};}
  async function select(book,startReading){
    stop();await receipts.catch(function(){});receipts=Promise.resolve();var got=await api('/api/books/'+book+'/select',{});
    if(got.confirm_resume){
      var p=popup('Resume this book?');p.body.appendChild(node('p','', 'Last completed: page '+got.page+', sentence '+(got.last_line+1)));
      p.body.appendChild(node('blockquote','',got.last_text));p.body.appendChild(node('p','', 'Resume with: '+got.next_text));
      if(got.changed)p.body.appendChild(node('p','', 'The source file changed. Start from the beginning after reviewing it.'));
      if(!got.changed)p.body.appendChild(button('Resume at sentence '+(got.resume_line+1),function(){p.dialog.close();p.dialog.remove();return finishSelect(book,{confirm:true},startReading);}));
      p.body.appendChild(button('Start from beginning',function(){p.dialog.close();p.dialog.remove();return finishSelect(book,{start:true},startReading);}));return;
    }
    await selected(got,startReading);
  }
  async function finishSelect(book,payload,startReading){await selected(await api('/api/books/'+book+'/select',payload),startReading);}
  async function selected(s,startReading){findGeneration++;ui.matches.replaceChildren();ui.find.value='';locatedLine=null;ui.readHere.hidden=true;paintState(s);readerBook=s.book;ui.shelf.open=false;follow=true;await reader(Math.max(0,s.position-10),true);say('Ready at sentence '+(s.position+1)+'. Click Read or the round start button to begin.');if(startReading)await play();}
  function sentence(row,previewing){
    var n=node('p','bm-sentence');n.dataset.line=row.line;n.appendChild(node('small','', 'Page '+row.page+' · '+(row.line+1)+' '));
    row.text.split(/(\s+)/).forEach(function(word){if(/^\s+$/.test(word)){n.appendChild(document.createTextNode(word));return;}var w=node('span','bm-word',word);w.oncontextmenu=function(e){if(previewing)return;e.preventDefault();pronunciation(row,word);};n.appendChild(w);});
    if(!previewing){n.tabIndex=0;n.title='Double click to read from here. Right click a word to review its pronunciation.';n.ondblclick=function(){seek(row.line).catch(function(e){say(e.message);});};n.onkeydown=function(e){if(e.key==='Enter')seek(row.line).catch(function(err){say(err.message);});};}
    return n;
  }
  async function reader(offset,reset){
    if(!readerBook)return;var selectedBook=readerBook;var got=await api('/api/books/'+readerBook+'/sentences?offset='+offset+'&limit=100');
    if(selectedBook!==readerBook)return;
    if(reset){ui.reader.replaceChildren();readerOffset=offset;}
    readerTotal=got.total;got.lines.forEach(function(r){ui.reader.appendChild(sentence(r,false));});readerOffset=offset+got.lines.length;
    // Bound the live feed while allowing explicit page jumps and backward paging.
    while(ui.reader.children.length>300){var first=ui.reader.firstChild;var height=first.getBoundingClientRect().height;first.remove();ui.reader.scrollTop=Math.max(0,ui.reader.scrollTop-height);}
    highlight(state.position);
  }
  async function locate(line){
    locatedLine=line;follow=false;await reader(Math.max(0,line-5),true);
    var target=ui.reader.querySelector('[data-line="'+line+'"]');
    if(target){target.classList.add('bm-located');target.scrollIntoView({block:'center'});}
    ui.readHere.hidden=false;say('Located sentence '+(line+1)+'. Choose Read from here or double-click the sentence.');
  }
  async function findText(reset){
    var phrase=ui.find.value.trim(),book=readerBook,gen=++findGeneration;
    if(reset){findOffset=0;ui.matches.replaceChildren();}
    ui.moreMatches.hidden=true;if(!phrase||!book){ui.findCount.textContent=book?'':'Select a book to search its text';return;}
    var got=await api('/api/books/'+book+'/find?q='+encodeURIComponent(phrase)+'&offset='+findOffset+'&limit=30');
    if(gen!==findGeneration||book!==readerBook||phrase!==ui.find.value.trim())return;
    got.matches.forEach(function(row){var match=button('Page '+row.page+' · sentence '+(row.line+1)+' — '+row.text,function(){return locate(row.line);});match.className='bm-match';ui.matches.appendChild(match);});
    findOffset+=got.matches.length;ui.findCount.textContent=got.total+' matching sentences';ui.moreMatches.hidden=findOffset>=got.total;
    while(ui.matches.children.length>90)ui.matches.firstChild.remove();
  }
  function highlight(line){
    Array.prototype.forEach.call(ui.reader.querySelectorAll('.bm-current'),function(n){n.classList.remove('bm-current');});
    var n=ui.reader.querySelector('[data-line="'+line+'"]');if(n){n.classList.add('bm-current');if(follow)n.scrollIntoView({block:'center',behavior:'smooth'});}
    ui.position.textContent='Sentence '+(line+1)+' / '+readerTotal;
  }
  async function seek(line){stop();await receipts.catch(function(){});receipts=Promise.resolve();paintState(await api('/api/books/seek',{line:line}));follow=true;await reader(Math.max(0,line-10),true);await play();}
  async function preview(book,title){
    var p=popup(title||'Book preview');p.dialog.classList.add('bm-preview-dialog');
    var loading=node('p','bm-preview-loading','Opening book preview…');p.body.appendChild(loading);
    var frame=null;
    function clean(){if(frame){frame.src='about:blank';frame.remove();frame=null;}p.dialog.remove();}
    p.dialog.addEventListener('close',clean,{once:true});p.dialog.addEventListener('cancel',clean,{once:true});
    try{
      var doc=await api('/api/books/'+encodeURIComponent(book)+'/document');
      if(!p.dialog.isConnected)return;
      p.dialog.querySelector('h2').textContent=doc.title||title||'Book preview';
      frame=node('iframe','bm-preview-frame');frame.title=(doc.title||title||'Book')+' · two-page preview';
      frame.src=base()+(doc.preview_url||('/books/read/'+encodeURIComponent(book)));
      p.body.replaceChildren(frame);
    }catch(error){if(p.dialog.isConnected)loading.textContent='Preview could not be opened: '+error.message;}
  }
  function pronunciation(row,word){
    var p=popup('Pronunciation in context');p.body.appendChild(node('blockquote','',row.text));p.body.appendChild(node('p','', 'Word: '+word));
    var spoken=node('input','');spoken.placeholder='Optional phonetic spelling for this sentence';p.body.appendChild(spoken);var sense=node('input','');sense.placeholder='Optional meaning to reuse this pronunciation (e.g. lead = metal)';sense.style.width='95%';p.body.appendChild(sense);
    p.body.appendChild(button('Mark / save correction',async function(){if(spoken.value){stop();await receipts.catch(function(){});receipts=Promise.resolve();}await api('/api/books/pronunciation',{line:row.line,word:word.replace(/^[^\w]+|[^\w]+$/g,''),spoken:spoken.value,sense:sense.value});if(spoken.value)paintState(await api('/api/books/state'));p.dialog.close();p.dialog.remove();say(spoken.value?'Context-specific correction saved. Replay the sentence to hear it.':'Word marked for pronunciation review.');}));
    p.body.appendChild(button('Ask for pronunciation guidance',async function(){say('Checking pronunciation context…');var got=await api('/api/books/pronunciation/suggest',{line:row.line,word:word});p.body.appendChild(node('p','',got.guidance));}));
  }
  function prepare(line){if(!prepared[line]){prepared[line]=api('/api/books/next',{session:state.session,line:line});prepared[line].catch(function(){});}return prepared[line];}
  function event(item){var n=node('div','bm-event');n.appendChild(node('b','',item.name+' · '+state.preferences.routing+' reader node'));n.appendChild(node('p','',item.text));
    if(item.reader_node){var dec=item.reader_node;var roll=node('small','bm-roll',dec.label+' · '+(dec.draw?'d100: '+dec.draw.dice:'ordered')+' → '+dec.selected);n.appendChild(roll);n.appendChild(node('small','',dec.candidates.map(function(c){return c.label+' '+Math.round(c.p*100)+'%';}).join(' · ')));}
    if(item.source_node)n.appendChild(node('small','', 'Book roulette: '+item.source_node.label+' · d100 '+item.source_node.draw.dice+' · '+item.source_node.of+' indexed books'));
    n.appendChild(node('small','', 'Book → System 3 reader node → contextual emotion → voice → playback receipt'));ui.feed.prepend(n);while(ui.feed.children.length>40)ui.feed.lastChild.remove();}
  function makeAudio(item){var a=new Audio();a.addEventListener('ended',function(){a._bookEnded=true;});a.preload='auto';a.src=source(item.clip);a.playbackRate=state.preferences.speed;a.preservesPitch=true;a.volume=voiceVolume();return a;}
  function video(item){if(!item.sfx)return;ui.video.src=source(item.sfx);ui.video.muted=true;ui.video.hidden=false;ui.video.play().catch(function(){});ui.video.onended=function(){ui.video.hidden=true;};}
  async function play(){
    if(playing){stop();say('Narration paused. The unfinished sentence will replay.');return;}
    if(!state||!state.book){say('Choose a book first.');return;}
    playing=true;paintPlayback();var gen=++generation;
    try{await receipts.catch(function(){});receipts=Promise.resolve();if(!state.active){var activated=await api('/api/books/mode',{active:true});if(gen!==generation)return;paintState(activated);}var claimed=await api('/api/books/claim',{});if(gen!==generation)return;paintState(claimed);var item=await prepare(state.position);if(gen!==generation)return;if(item.end){stop();say('End of book');return;}current=item;audio=makeAudio(item);await run(item,audio,gen);}
    catch(e){if(gen===generation){stop();say(e.message);}}
  }
  async function run(item,a,gen){
    if(gen!==generation)return;
    current=item;audio=a;highlight(item.line);event(item);video(item);say(item.name+' is reading page '+item.page);
    var prefetch=prepare(item.line+1).then(function(v){if(gen!==generation)return null;next=v; if(!v.end)second=makeAudio(v);return v;});
    // Never let a failed prefetch advance the bookmark or become unhandled.
    prefetch.catch(function(){});for(var ahead=2;ahead<=(state.preferences.buffer_lines||4);ahead++){if(item.line+ahead<item.total)prepare(item.line+ahead);}
    var completing=false,overlap=false;
    a.ontimeupdate=function(){
      var blend=Math.min(state.preferences.blend_ms/1000,second&&second.duration?second.duration/second.playbackRate/2:0);
      if(blend>0&&!overlap&&second&&second.readyState>=3&&a.duration&&a.duration-a.currentTime<=blend*a.playbackRate){
        overlap=true;second.volume=0;second.play().catch(function(){overlap=false;});
      }
      if(overlap&&second){var remaining=(a.duration-a.currentTime)/a.playbackRate;var fraction=Math.min(1,Math.max(0,remaining/Math.max(.001,blend)));a.volume=fraction*voiceVolume();second.volume=(1-fraction)*voiceVolume();}
    };
    a.onended=async function(){
      if(gen!==generation||completing)return;completing=true;
      try{
        receipts=receipts.then(function(){return api('/api/books/heard',{token:item.token});});
        receipts.catch(function(e){if(gen===generation){stop();say('Progress could not be saved: '+e.message);}});
        if(gen!==generation)return;state.position=item.line+1;delete prepared[item.line];
        var n=await prefetch;if(gen!==generation)return;
        if(!n||n.end){await receipts;if(gen!==generation)return;stop();say('End of book · progress saved');return;}
        var nextAudio=second||makeAudio(n);second=null;nextAudio.volume=voiceVolume();
        if(!ui.reader.querySelector('[data-line="'+n.line+'"]'))await reader(Math.max(0,n.line-10),true);
        timer=setTimeout(function(){run(n,nextAudio,gen).catch(function(e){if(gen===generation){stop();say(e.message);}});},overlap?0:state.preferences.gap_ms);
      }catch(e){if(gen===generation){stop();say(e.message);}}
    };
    a.onerror=function(){if(gen===generation){stop();say('Audio could not play. Retry this sentence; progress was not advanced.');}};
    if(a._bookEnded){await a.onended();}else {await a.play();api('/api/books/started',{token:item.token}).catch(function(){});}
  }
  async function question(){var q=ui.question.value.trim();if(!q)return; say('Searching book passages…');var got=await api('/api/books/question',{question:q,scope:state.preferences.scope});var p=popup('Book answer');p.body.appendChild(node('p','',got.answer));got.citations.forEach(function(c){var block=node('blockquote','',c.quote);block.appendChild(node('small','',c.title+' · page '+c.page));if(c.book)block.appendChild(button('Open book',function(){return preview(c.book,c.title);}));p.body.appendChild(block);});say('Answer ready');}
  function field(parent,label,input){var l=node('label','');l.appendChild(node('span','',label));l.appendChild(input);parent.appendChild(l);return input;}
  function selectControl(parent,label,options,setting){var s=node('select','');options.forEach(function(o){var opt=node('option','',o[1]);opt.value=o[0];s.appendChild(opt);});field(parent,label,s);s.onchange=function(){var v={};v[setting]=s.value;pref(v).catch(function(e){say(e.message);});};return s;}
  function mount(host,bar){
    if(ui.panel){scriptHost=host;scriptPane=host.querySelector('.sp-right')||host;bar=host.querySelector('.sp-band-restore')||bar;bar.appendChild(ui.toggle);watchHosts();place(scriptPane);return;}scriptHost=host;scriptPane=host.querySelector('.sp-right')||host;bar=host.querySelector('.sp-band-restore')||bar;ui.toggle=button('',toggle);ui.toggle.className='sp-btn bm-toggle';ui.toggle.title='Book Mode';ui.toggle.setAttribute('aria-label','Book Mode');ui.toggle.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v15M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2z"/></svg>';bar.appendChild(ui.toggle);
    ui.panel=node('section','bm-panel');ui.panel.hidden=true;scriptPane.appendChild(ui.panel);ui.panel.classList.add('bm-inline');
    var top=node('header','bm-top');ui.panel.appendChild(top);ui.title=node('h2','','Choose a book');top.appendChild(ui.title);ui.start=button('',play);ui.start.className='bm-start';top.appendChild(ui.start);ui.transport=node('small','bm-transport');top.appendChild(ui.transport);top.appendChild(button('Book View tab',function(){return showBookView();}));var back=button('Back to Pine Box FM',returnToFm);back.className='bm-return';top.appendChild(back);
    ui.shelf=node('details','bm-shelf');ui.shelf.open=true;ui.shelf.appendChild(node('summary','','Book library'));ui.panel.appendChild(ui.shelf);
    var search=node('div','bm-search');ui.search=node('input','');ui.search.type='search';ui.search.placeholder='Search EPUB and PDF titles';ui.search.setAttribute('aria-label','Search book titles');search.appendChild(ui.search);ui.count=node('small','');search.appendChild(ui.count);search.appendChild(button('Refresh folders',async function(){say('Scanning book folders…');await api('/api/books/refresh',{});await library(true);}));ui.panel.insertBefore(search,ui.shelf);
    ui.books=node('div','bm-books');ui.shelf.appendChild(ui.books);ui.books.onscroll=function(){var b=ui.books;if(b.scrollTop<30&&b.scrollLeft<30&&shelfFirstOffset>0){library(true,Math.max(0,shelfFirstOffset-40)).catch(function(e){say(e.message);});return;}if((b.scrollTop+b.clientHeight>b.scrollHeight-250||b.scrollLeft+b.clientWidth>b.scrollWidth-250)&&listOffset<listTotal)library(false).catch(function(e){say(e.message);});};   /* [book-shelf] the wall scrolls down as well as along */
    var debounce;ui.search.oninput=function(){query=ui.search.value;clearTimeout(debounce);debounce=setTimeout(function(){library(true).catch(function(e){say(e.message);});},250);};
    var controls=node('div','bm-controls');ui.panel.appendChild(controls);ui.play=button('Read',play);controls.appendChild(ui.play);
    ui.speed=selectControl(controls,'Speed',[1,2,4,6,8,16].map(function(v){return [v,v+'x'];}),'speed');
    ['gap','blend'].forEach(function(name){ui[name]=node('input','');ui[name].type='number';ui[name].min=0;ui[name].max=10000;ui[name].step=50;field(controls,name==='gap'?'Sentence gap (ms)':'Crossfade (ms)',ui[name]);ui[name].onchange=function(){var v={};v[name+'_ms']=Number(ui[name].value);pref(v).catch(function(e){say(e.message);});};});
    controls.appendChild(button('Follow current sentence',function(){follow=true;highlight(state.position);}));
    var prefs=node('details','bm-preferences');prefs.appendChild(node('summary','','Reader node and book show preferences'));ui.panel.appendChild(prefs);var settings=node('div','bm-settings');prefs.appendChild(settings);
    ui.nodeName=node('input','');field(settings,'Custom reader node name',ui.nodeName);ui.nodeName.onchange=function(){pref({reader_node:{...state.preferences.reader_node,label:ui.nodeName.value}}).catch(function(e){say(e.message);});};
    ui.scan=selectControl(settings,'Automatically scan folders',[[30,'Every 30 seconds'],[60,'Every minute'],[120,'Every 2 minutes'],[300,'Every 5 minutes'],[900,'Every 15 minutes'],[3600,'Every hour']],'scan_seconds');
    ui.buffer=selectControl(settings,'Read-ahead sentences',[[1,'1'],[4,'4'],[8,'8'],[16,'16'],[32,'32']],'buffer_lines');
    ui.routing=selectControl(settings,'Next reader node',[['sequential','Take turns in order'],['roulette','Cast roulette'],['single','One reader']],'routing');
    ui.show=selectControl(settings,'Show',[['read','Read book verbatim'],['discuss','Discuss book passages']],'show');ui.scope=selectControl(settings,'Source universe',[['book','Only this book'],['library','All indexed books']],'scope');
    ui.readers={};['host','cohost','third','sfx','manager','caller'].forEach(function(role){var c=node('input','');c.type='checkbox';ui.readers[role]=c;field(settings,(root.pineCastName?root.pineCastName(role,role):role),c);
      var weight=node('input','');weight.type='number';weight.min=0;weight.max=100;weight.value=1;weight.title=role+' roulette weight';weight.style.width='50px';settings.appendChild(weight);weight.onchange=function(){var weights={...state.preferences.reader_node.weights};weights[role]=Number(weight.value);pref({reader_node:{...state.preferences.reader_node,weights:weights}}).catch(function(e){say(e.message);});};
      c.onchange=function(){var readers=Object.keys(ui.readers).filter(function(r){return ui.readers[r].checked;});pref({readers:readers}).catch(function(e){say(e.message);paintState(state);});};});
    ['research','sfx'].forEach(function(k){ui[k]=node('input','');ui[k].type='checkbox';field(settings,k==='research'?'Research related book topics online':'Contextual SFX video',ui[k]);ui[k].onchange=function(){var v={};v[k]=ui[k].checked;pref(v).catch(function(e){say(e.message);});};});
    var find=node('div','bm-find');ui.find=node('input','');ui.find.type='search';ui.find.placeholder='Find a phrase in this book';ui.find.setAttribute('aria-label','Search within selected book');find.appendChild(ui.find);find.appendChild(button('Find in book',function(){return findText(true);}));ui.findCount=node('small','');find.appendChild(ui.findCount);ui.panel.appendChild(find);
    ui.find.onkeydown=function(e){if(e.key==='Enter')findText(true).catch(function(err){say(err.message);});};
    ui.matches=node('div','bm-matches');ui.panel.appendChild(ui.matches);ui.moreMatches=button('More matches',function(){return findText(false);});ui.moreMatches.hidden=true;ui.panel.appendChild(ui.moreMatches);
    var ask=node('div','bm-ask');ui.question=node('input','');ui.question.placeholder='Ask a question about the selected book universe';ask.appendChild(ui.question);ask.appendChild(button('Ask books',question));ui.panel.appendChild(ask);
    ui.status=node('div','bm-status');ui.status.setAttribute('role','status');ui.panel.appendChild(ui.status);
    var workspace=node('div','bm-workspace');ui.panel.appendChild(workspace);var feed=node('aside','bm-live');feed.appendChild(node('h3','','Book production feed'));ui.feed=node('div','bm-events');feed.appendChild(ui.feed);ui.video=node('video','bm-video bm-global-video');ui.video.controls=true;ui.video.hidden=true;document.body.appendChild(ui.video);workspace.appendChild(feed);
    var readerWrap=node('section','bm-reader-wrap'),nav=node('nav','bm-reader-nav');ui.position=node('span','');nav.appendChild(ui.position);ui.readHere=button('Read from here',function(){return seek(locatedLine);});ui.readHere.hidden=true;nav.appendChild(ui.readHere);nav.appendChild(button('Earlier sentences',function(){var first=ui.reader.firstChild;return reader(Math.max(0,Number(first?first.dataset.line:0)-100),true);}));var jump=node('input','');jump.type='number';jump.min=1;jump.placeholder='Sentence';nav.appendChild(jump);nav.appendChild(button('Browse to sentence',function(){follow=false;return reader(Math.max(0,Number(jump.value)-1),true);}));readerWrap.appendChild(nav);ui.reader=node('div','bm-reader');ui.reader.onwheel=function(){follow=false;};ui.reader.ontouchstart=function(){follow=false;};ui.reader.onscroll=function(){if(ui.reader.scrollTop+ui.reader.clientHeight>ui.reader.scrollHeight-200&&readerOffset<readerTotal&&!ui.readerLoading){ui.readerLoading=true;reader(readerOffset,false).catch(function(e){say(e.message);}).finally(function(){ui.readerLoading=false;});}};readerWrap.appendChild(ui.reader);workspace.appendChild(readerWrap);
    ui.badge=node('button','bm-global-badge');ui.badge.hidden=true;ui.badge.onclick=function(){showBookView();};document.body.appendChild(ui.badge);
    ui.ready=api('/api/books/state').then(function(s){libraryOpen=!!s.active;paintState(s);if(s.active){library(true);if(s.book){readerBook=s.book;reader(Math.max(0,s.position-10),true);}}}).catch(function(e){say(e.message);});
    if(root.PineStationFeed&&root.PineStationFeed.subscribe){root.PineStationFeed.subscribe(function(payload){
      var remote=((payload&&payload.station)||payload||{}).book_mode;if(!remote||!state||remote.epoch<state.epoch)return;
      if(playing&&remote.session!==state.session){stop();say('Book playback changed on another station screen.');}
      if(!playing&&remote.epoch>=state.epoch){var prior=state;paintState(remote);if(remote.active&&remote.book&&remote.book!==readerBook){readerBook=remote.book;reader(Math.max(0,remote.position-10),true).catch(function(e){say(e.message);});}if(remote.active&&remote.live){highlight(remote.live.line);if(!prior.live||prior.live.at!==remote.live.at)video(remote.live);}}
    });}
    if(root.pineLevels&&root.pineLevels.onApply)root.pineLevels.onApply(function(){if(audio)audio.volume=voiceVolume();if(second)second.volume=voiceVolume();});
    watchHosts();root.addEventListener('beforeunload',stop);
  }
  function place(host){
    if(!ui.panel||!host)return;
    if(scriptPane)scriptPane.classList.remove('sp-book-reading');
    if(ui.panel.parentNode!==host)host.appendChild(ui.panel);var inline=host===scriptPane;ui.panel.classList.toggle('bm-inline',inline);ui.panel.classList.toggle('bm-dedicated',!inline);
    if(inline&&libraryOpen)scriptPane.classList.add('sp-book-reading');
  }
  async function enable(){
    if(ui.ready)await ui.ready;
    if(!state)paintState(await api('/api/books/state'));
    libraryOpen=true;paintState(state);if(!state.active)say('Browse and select a title. Pine Box FM continues until you click Read.');
    await library(true);if(state.book&&readerBook!==state.book){readerBook=state.book;await reader(Math.max(0,state.position-10),true);}
  }
  async function openBook(host){
    bookHost=host;
    if(!ui.panel){var script=document.getElementById('script');if(!script){script=node('section','view sc-view');script.id='script';document.body.appendChild(script);}if(!root.PineScriptPage)throw Error('Script view has not loaded');await root.PineScriptPage.mount(script);}
    watchHosts();place(host);await enable();
  }
  function showBookView(){
    if(root.PineViewRail)return root.PineViewRail.open('books');
    var tab=document.getElementById('pineViewTab-books')||document.querySelector('[data-view="books"]');
    if(tab){tab.click();return;}
    if(root.PineViewChrome)root.PineViewChrome.show('books');
  }
  var observers=[];
  function watchHosts(){
    observers.forEach(function(o){o.disconnect();});observers=[];if(!root.MutationObserver)return;
    [scriptHost,bookHost].filter(Boolean).forEach(function(host){var observer=new MutationObserver(function(){if(!host.classList.contains('open')&&!host.classList.contains('active'))return;if(host===scriptHost)place(scriptPane);else{place(bookHost);enable().catch(function(e){say(e.message);});}});observer.observe(host,{attributes:true,attributeFilter:['class']});observers.push(observer);});
  }
  root.PineBookView={mount:function(host){openBook(host).catch(function(e){say(e.message);});}};
  root.PineBookMode={mount:mount,stop:stop,preview:preview,api:api};
  if(typeof module==='object'&&module.exports)module.exports=root.PineBookMode;
})(typeof window!=='undefined'?window:globalThis);
