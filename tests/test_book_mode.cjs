const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const repo=process.env.PINE_BOOK_TEST_ROOT||path.resolve(__dirname,'..');
const artifacts=process.env.PINE_BOOK_TEST_OUTPUT||path.join(repo,'artifacts');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const thumbnailRequests=[];
const coverSvg='<svg xmlns="http://www.w3.org/2000/svg" width="300" height="420"><rect width="300" height="420" fill="#345"/><text x="24" y="80" fill="white">A Demonstration Book</text></svg>';
const server=http.createServer((req,res)=>{
 thumbnailRequests.push(req.url);
 if(req.url==='/signed/demo.svg?t=mock-auth'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end(coverSvg);return;}
 res.writeHead(404);res.end();
});
app.disableHardwareAcceleration();app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'pine-book-test-')));
let win;
app.whenReady().then(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const stationBase='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1154,height:690,webPreferences:{offscreen:true,nodeIntegration:true,contextIsolation:false}});
 const evaluate=(fn,...args)=>win.webContents.executeJavaScript('('+fn.toString()+')('+JSON.stringify(args).slice(1,-1)+')');
 async function waitFor(fn,message,timeout=3500){
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){if(await evaluate(fn))return;await sleep(30);}
  throw new Error('Timed out: '+message);
 }
 const code=fs.readFileSync(path.join(repo,'desktop/renderer/book-mode.js'),'utf8');
 const css=fs.readFileSync(path.join(repo,'desktop/renderer/book-mode.css'),'utf8');
 const sharedCss=['styles.css','script.css','view-chrome.css','script-page.css'].map(file=>fs.readFileSync(path.join(repo,'desktop/renderer',file),'utf8')).join('\n');
 const chromeCode=fs.readFileSync(path.join(repo,'desktop/renderer/view-chrome.js'),'utf8');
 const railCode=fs.readFileSync(path.join(repo,'desktop/renderer/rail.js'),'utf8');
 await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<html><style>'+sharedCss+'</style><style>'+css+'</style><style>html,body{width:100%;height:100%;margin:0}body{display:block;background:#101b22}#script{position:fixed;inset:0}.bm-view{position:fixed;inset:0;background:#101b22}.bm-view:not(.open){display:none}</style><body><section class="pine-view-host sc-view open sp-page sp-tl-on" id="script"><div class="sp-left"><div class="sp-bar" id="bar"></div><div>Station player and feed remain visible</div></div><div class="sp-right"><div class="sp-script-top"><div class="sp-script-title-row"><div class="sp-scripthead"><b>The Script</b><i class="sp-scriptwhy"> Pine Box FM</i></div><div class="sp-prompt-dock"></div></div><div class="sp-band-restore" id="scriptTools"></div></div><div id="spScript" class="sp-script">FM script</div></div></section><section id="books" class="bm-view"></section></body></html>'));
 await evaluate((stationBase,coverSvg)=>{
  window.pineStationBase=()=>stationBase;
  window.calls=[];window.heard=[];window.audioStarts=[];
  window.mockBooks=[
   {id:'demo',title:'A Demonstration Book: A Long Title About Human History and the Stories We Share',author:'Alexandra Montgomery and Christopher Alexander Robertson',kind:'epub',cover:'/api/books/demo/cover',cover_url:'/signed/demo.svg?t=mock-auth',bookmark:{last_line:1}},
   {id:'absolute',title:'A Fully Qualified Cover URL and a Long Subtitle About Its Signed Thumbnail',author:'Elizabeth Catherine Pennington',kind:'epub',cover:'/api/books/absolute/cover',cover_url:stationBase+'/signed/demo.svg?t=mock-auth',bookmark:{last_line:1}},
   {id:'legacy',title:'A Legacy Title: The Complete Illustrated Guide to Everyday Discoveries',author:'Susan Weinschenk and Stephen Le',kind:'pdf',cover:'/api/books/legacy/cover',bookmark:{last_line:1}},
   {id:'broken',title:'A Visible Title When Artwork Fails: Keeping a Long Book Name Available to Browse',author:'Guillaume Henri Delacroix and Maria Francesca Bellini',kind:'epub',cover:'/api/books/broken/cover',cover_url:'/signed/missing.svg?t=mock-auth',bookmark:{last_line:1}},
   ...Array.from({length:43},(_,i)=>({id:'book-'+i,title:'Book '+String(i+1).padStart(2,'0')+': A Very Long Subtitle About the Ancient World and Its Remarkable People',author:'Alexandra Montgomery and Christopher Alexander Robertson',kind:'epub',cover:'/api/books/book-'+i+'/cover',bookmark:{last_line:1}}))
  ];
  window.modeState={active:false,book:'',position:0,epoch:1,session:'one',title:'',preferences:{speed:1,gap_ms:0,blend_ms:0,readers:['host','cohost','third'],routing:'sequential',scope:'book',show:'read',research:false,sfx:true,reader_node:{id:'book-reader',label:'Next book reader',weights:{}}},events:[],errors:[]};
  window.pineDesktop={
   get:async function(url){
    calls.push(url);
    if(url==='/api/books/state')return structuredClone(modeState);
    if(url.startsWith('/api/books?')){
     const params=new URLSearchParams(url.split('?')[1]),q=params.get('q')||'';
     const books=mockBooks.filter(b=>b.title.toLowerCase().includes(q.toLowerCase()));
     const offset=Number(params.get('offset')||0),limit=Number(params.get('limit')||40);
     return {books:structuredClone(books.slice(offset,offset+limit)),total:books.length,errors:[]};
    }
    if(url.includes('/find?'))return {total:2,matches:[{line:1,page:1,text:'The lead pipe was heavy.'},{line:2,page:1,text:'They lead the expedition.'}]};
    if(url.endsWith('/cover')){if(url.includes('/broken/'))throw Error('Artwork unavailable');return {svg:coverSvg};}
    if(url.includes('/sentences'))return {total:6,lines:Array.from({length:6},(_,i)=>({line:i,page:1,text:['Dr. Smith opened the book.','The lead pipe was heavy.','They lead the expedition.','The cast takes turns reading.','Every completed line is remembered.','The book closes here.'][i]}))};
    if(url.endsWith('/document'))return {title:'Demo',kind:'epub',url:''};
    throw Error(url);
   },
   post:async function(url,p){
    calls.push({url,p:structuredClone(p)});
    if(url==='/api/books/mode'){if(p.active&&!modeState.book)throw Error('Select a book before activation');modeState={...modeState,active:p.active,epoch:modeState.epoch+1};return structuredClone(modeState);}
    if(url.endsWith('/select')){
     const id=url.split('/')[3],book=mockBooks.find(b=>b.id===id);
     if(!p.confirm&&!p.start)return {confirm_resume:true,last_line:1,resume_line:2,last_text:'The lead pipe was heavy.',next_text:'They lead the expedition.',page:1};
     modeState={...modeState,book:id,title:book.title,position:p.start?0:2,epoch:modeState.epoch+1};
     return structuredClone(modeState);
    }
    if(url==='/api/books/preferences'){modeState.preferences={...modeState.preferences,...p};return structuredClone(modeState.preferences);}
    if(url==='/api/books/pronunciation')return {status:'needs_review'};
    if(url==='/api/books/seek'){modeState.position=p.line;return structuredClone(modeState);}
    if(url==='/api/books/claim'){if(!modeState.active)throw Error('Playback claim before explicit activation');return structuredClone(modeState);}
    if(url==='/api/books/next'){
     if(!modeState.active)throw Error('Narration requested while browsing');
     if(p.line>=6)return {end:true};
     return {token:'token-'+p.line,line:p.line,page:1,text:'Narrated sentence '+p.line,reader:p.line%2?'cohost':'host',name:p.line%2?'Skip':'Dill',clip:{path:'/media/mock.wav',sig:'signed'},sfx:null,total:6,session:'one',reader_node:{label:'Next book reader',selected:p.line%2?'cohost':'host',draw:null,candidates:[]}};
    }
    if(url==='/api/books/started')return {ok:true};
    if(url==='/api/books/heard'){
     await new Promise(resolve=>setTimeout(resolve,60));
     const line=Number(p.token.split('-')[1]);
     if(line!==modeState.position)throw Error('Out of order bookmark receipt: '+line+' expected '+modeState.position);
     heard.push(line);modeState.position=line+1;return structuredClone(modeState);
    }
    throw Error(url);
   }
  };
  window.Audio=class extends EventTarget{
   constructor(){super();this.duration=.2;this.currentTime=0;this.playbackRate=1;this.readyState=4;this.volume=1;this._timer=null;}
   play(){
    if(this._timer||this._bookEnded)return Promise.resolve();audioStarts.push(Date.now());
    this._timer=setInterval(()=>{this.currentTime=Math.min(this.duration,this.currentTime+.005*this.playbackRate);if(this.ontimeupdate)this.ontimeupdate();if(this.currentTime>=this.duration){clearInterval(this._timer);this._timer=null;this.dispatchEvent(new Event('ended'));if(this.onended)this.onended();}},5);
    return Promise.resolve();
   }
   pause(){clearInterval(this._timer);this._timer=null;}removeAttribute(){}load(){}
  };
  window.PineScriptPage={mount:()=>Promise.resolve(true)};
 },stationBase,coverSvg);
 await win.webContents.executeJavaScript(code+'\nPineBookMode.mount(document.getElementById("script"),document.getElementById("bar"));');
 await waitFor(()=>calls.includes('/api/books/state'),'initial state');
 await evaluate(()=>document.querySelector('.bm-toggle').click());
 await waitFor(()=>document.querySelectorAll('.bm-card').length===40,'browse shelf');
 await waitFor(()=>Array.from(document.querySelectorAll('.bm-card img')).slice(0,3).every(img=>img.complete&&img.naturalWidth>0),'signed and JSON thumbnails');
 await waitFor(()=>document.querySelector('[data-book="broken"] .bm-cover')?.title.includes('Title cover'),'visible fallback after signed and JSON artwork failure');
 const shelf=await evaluate(()=>{
  const panel=document.querySelector('.bm-panel'),cards=Array.from(document.querySelectorAll('.bm-card'));
  const flow=document.querySelector('.bm-books'),start=document.querySelector('.bm-start');
  return {active:modeState.active,bodyActive:document.body.classList.contains('pine-book-mode'),visible:!panel.hidden,inline:panel.parentNode.classList.contains('sp-right'),toolbar:document.querySelector('.bm-toggle').parentNode.id,display:getComputedStyle(flow).display,overflowX:getComputedStyle(flow).overflowX,scrollWidth:flow.scrollWidth,width:flow.clientWidth,signed:cards[0].querySelector('img').src,absolute:cards[1].querySelector('img').src,legacy:cards[2].querySelector('img').src,brokenText:cards[3].querySelector('.bm-cover').textContent,brokenVisible:getComputedStyle(cards[3].querySelector('.bm-cover-title')).visibility,readFits:cards.every(card=>{const read=card.querySelector('.bm-read').getBoundingClientRect(),shelf=flow.getBoundingClientRect();return read.top>=shelf.top-1&&read.bottom<=shelf.bottom+1;}),previewFits:cards.every(card=>{const preview=Array.from(card.querySelectorAll('button')).find(button=>button.textContent==='Preview').getBoundingClientRect(),shelf=flow.getBoundingClientRect();return preview.top>=shelf.top-1&&preview.bottom<=shelf.bottom+1;}),metadata:cards.every(card=>card.querySelector('small').textContent.includes(' · ')),start:!!start,stationMutations:calls.filter(c=>typeof c==='object'&&['/api/books/mode','/api/books/claim','/api/books/next'].includes(c.url))};
 });
 assert.equal(shelf.active,false);assert.equal(shelf.bodyActive,false);assert.equal(shelf.visible,true);assert.equal(shelf.inline,true);assert.equal(shelf.toolbar,'scriptTools');
 assert.equal(shelf.start,true);assert.equal(shelf.display,'flex');assert.match(shelf.overflowX,/auto|scroll/);assert.ok(shelf.scrollWidth>shelf.width,'book covers form a horizontal shelf');
 assert.equal(shelf.signed,stationBase+'/signed/demo.svg?t=mock-auth');assert.equal(shelf.absolute,stationBase+'/signed/demo.svg?t=mock-auth');assert.equal(shelf.brokenVisible,'visible');assert.equal(shelf.readFits,true,'all Read buttons fit the real Script pane at 1154×690');assert.equal(shelf.previewFits,true,'all Preview buttons fit the real Script pane at 1154×690');assert.equal(shelf.metadata,true,'long author metadata remains rendered');assert.match(shelf.legacy,/^data:image\/svg\+xml/);assert.match(shelf.brokenText,/A Visible Title When Artwork Fails/);assert.deepEqual(shelf.stationMutations,[]);
 assert.ok(thumbnailRequests.includes('/signed/demo.svg?t=mock-auth'),'signed cover is fetched directly by the image');
 fs.mkdirSync(artifacts,{recursive:true});fs.writeFileSync(path.join(artifacts,'book-mode-library.png'),(await win.webContents.capturePage()).toPNG());
 await evaluate(()=>document.querySelector('.bm-start').click());await sleep(80);
 assert.equal(await evaluate(()=>calls.some(c=>c.url==='/api/books/mode')),false,'radial start requires a selected book');
 await evaluate(()=>{const flow=document.querySelector('.bm-books');flow.scrollLeft=flow.scrollWidth;flow.dispatchEvent(new Event('scroll'));});
 await waitFor(()=>document.querySelectorAll('.bm-card').length===47,'horizontal next page');
 await evaluate(()=>{const flow=document.querySelector('.bm-books');flow.scrollLeft=0;document.querySelector('.bm-toggle').click();});
 await sleep(80);
 assert.equal(await evaluate(()=>document.querySelector('.bm-panel').hidden),true,'toolbar closes browsing');
 assert.equal(await evaluate(()=>calls.some(c=>c.url==='/api/books/mode')),false,'closing browsing does not change FM');
 await evaluate(()=>document.querySelector('.bm-toggle').click());
 await waitFor(()=>!document.querySelector('.bm-panel').hidden&&document.querySelectorAll('.bm-card').length>=40,'reopened shelf');

 await evaluate(()=>document.querySelector('.bm-cover').click());
 await waitFor(()=>!!document.querySelector('dialog'),'cover selection resume choice');
 const resumeText=await evaluate(()=>document.querySelector('dialog').textContent);
 assert.match(resumeText,/Resume with/);
 assert.equal(await evaluate(()=>modeState.active),false,'cover selection stays in browse mode');
 await evaluate(()=>Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent.startsWith('Resume at')).click());
 await waitFor(()=>document.querySelector('.bm-current')?.dataset.line==='2','selected book reader');
 const reader=await evaluate(()=>({lines:document.querySelectorAll('.bm-sentence').length,height:document.querySelector('.bm-reader').getBoundingClientRect().height,navHeight:document.querySelector('.bm-reader-nav').getBoundingClientRect().height,workspaceHeight:document.querySelector('.bm-workspace').getBoundingClientRect().height,active:modeState.active,calls:calls.filter(c=>c.url==='/api/books/mode'||c.url==='/api/books/claim'||c.url==='/api/books/next')}));
 fs.writeFileSync(path.join(artifacts,'book-mode-selected.png'),(await win.webContents.capturePage()).toPNG());
 assert.equal(reader.lines,6);assert.ok(reader.height>50,'selected reader has usable height at tablet zoom: '+JSON.stringify(reader));assert.equal(reader.active,false);assert.deepEqual(reader.calls,[]);
 await evaluate(()=>{
  document.querySelector('.bm-find input').value='lead';document.querySelector('.bm-find button').click();
 });
 await waitFor(()=>document.querySelectorAll('.bm-match').length===2,'passage search');
 await evaluate(()=>document.querySelector('.bm-match').click());
 await waitFor(()=>document.querySelector('.bm-located')?.dataset.line==='1','locate passage');
 assert.equal(await evaluate(()=>modeState.position),2,'search browsing must not seek or save progress');
 assert.equal(await evaluate(()=>modeState.active),false);
 await evaluate(()=>{document.querySelector('.bm-word').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));});
 assert.equal(await evaluate(()=>!!document.querySelector('dialog')),true,'pronunciation review remains available while browsing');
 await evaluate(()=>{document.querySelector('dialog').close();document.querySelector('dialog').remove();});

 await win.webContents.executeJavaScript(chromeCode+'\n'+railCode+'\n__pineViewRail();PineViewChrome.show("books");void 0;');
 await waitFor(()=>document.querySelector('.bm-panel').parentNode.id==='books','Books rail shared library');
 const rail=await evaluate(()=>({tab:!!document.getElementById('pineViewTab-books'),open:PineViewRail.openIds().includes('books'),panels:document.querySelectorAll('.bm-panel').length,active:modeState.active,calls:calls.filter(c=>c.url==='/api/books/mode'||c.url==='/api/books/claim'||c.url==='/api/books/next')}));
 assert.equal(rail.tab,true);assert.equal(rail.open,true);assert.equal(rail.panels,1);assert.equal(rail.active,false);assert.deepEqual(rail.calls,[]);
 await evaluate(()=>PineViewRail.open('script'));
 await waitFor(()=>document.querySelector('.bm-panel').parentNode.classList.contains('sp-right'),'return to inline script pane');
 assert.equal(await evaluate(()=>modeState.active),false,'view switching preserves FM');
 await evaluate(()=>{const input=document.querySelector('.bm-search input');input.value='Demonstration';input.dispatchEvent(new Event('input'));});
 await waitFor(()=>document.querySelectorAll('.bm-card').length===1,'title search');
 assert.equal(await evaluate(()=>modeState.active),false,'title search preserves FM');

 // Top radial starts only after selection; both start controls pause the same narrator.
 await evaluate(()=>{document.querySelector('.bm-shelf').open=true;document.querySelector('.bm-card-title').click();});
 await waitFor(()=>!!document.querySelector('dialog'),'title selection resume choice');
 assert.equal(await evaluate(()=>modeState.active),false,'title selection remains browse-only');
 await evaluate(()=>Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent.startsWith('Resume at')).click());
 await waitFor(()=>!document.querySelector('dialog')&&document.querySelector('.bm-current')?.dataset.line==='2','title selected without playback');
 assert.equal(await evaluate(()=>calls.some(c=>c.url==='/api/books/mode'||c.url==='/api/books/claim'||c.url==='/api/books/next')),false,'title selection never activates narration');
 await evaluate(()=>document.querySelector('.bm-start').click());
 await waitFor(()=>modeState.active&&audioStarts.length>0,'top radial narration start');
 await evaluate(()=>document.querySelector('.bm-controls button').click());
 await waitFor(()=>/paused/i.test(document.querySelector('.bm-status').textContent),'controls pause radial narration');
 assert.equal(await evaluate(()=>modeState.active),true,'pause retains the explicitly activated book session');
 await evaluate(()=>document.querySelector('.bm-toggle').click());await sleep(80);
 assert.equal(await evaluate(()=>document.querySelector('.bm-panel').hidden),true);
 assert.equal(await evaluate(()=>modeState.active),true,'toolbar close retains a book session');
 await evaluate(()=>document.querySelector('.bm-toggle').click());
 await waitFor(()=>!document.querySelector('.bm-panel').hidden,'reopen active book UI');
 await evaluate(()=>document.querySelector('.bm-controls button').click());
 await waitFor(()=>audioStarts.length===2,'controls resume narration');
 await evaluate(()=>document.querySelector('.bm-start').click());
 await waitFor(()=>/paused/i.test(document.querySelector('.bm-status').textContent),'radial pauses controls narration');
 await evaluate(()=>document.querySelector('.bm-return').click());
 await waitFor(()=>!modeState.active,'explicit FM return');
 assert.equal(await evaluate(()=>document.body.classList.contains('pine-book-mode')),false);
 assert.equal(await evaluate(()=>document.querySelector('.bm-panel').hidden&&!document.querySelector('.sp-right').classList.contains('sp-book-reading')),true,'FM return restores the script pane');

 // Read on a card selects, honors the resume choice, activates, and immediately narrates.
 await evaluate(()=>{heard=[];audioStarts=[];document.querySelector('.bm-toggle').click();});
 await waitFor(()=>!document.querySelector('.bm-panel').hidden&&!!document.querySelector('.bm-read'),'shelf after returning to FM');
 await evaluate(()=>{
  const speed=Array.from(document.querySelectorAll('select')).find(s=>Array.from(s.options).some(o=>o.text==='16x'));speed.value='16';speed.dispatchEvent(new Event('change'));
 });
 await waitFor(()=>Number(modeState.preferences.speed)===16,'16x speed');
 await evaluate(()=>document.querySelector('.bm-read').click());
 await waitFor(()=>!!document.querySelector('dialog'),'Read resume choice');
 assert.equal(await evaluate(()=>modeState.active),false,'Read waits for resume choice before activation');
 await evaluate(()=>Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent.startsWith('Resume at')).click());
 await waitFor(()=>heard.length===4&&/End of book.*progress saved/.test(document.querySelector('.bm-status').textContent),'ordered fast playback and bookmark receipts');
 const playback=await evaluate(()=>({heard,starts:audioStarts,position:modeState.position,active:modeState.active,status:document.querySelector('.bm-status').textContent}));
 assert.deepEqual(playback.heard,[2,3,4,5]);assert.equal(playback.position,6);assert.equal(playback.active,true);assert.ok(playback.starts[3]-playback.starts[0]<180,'audio must continue without waiting on bookmark network writes');

 fs.mkdirSync(artifacts,{recursive:true});
 fs.writeFileSync(path.join(artifacts,'book-mode-desktop.png'),(await win.webContents.capturePage()).toPNG());
 await evaluate(()=>PineViewChrome.show('books'));
 await waitFor(()=>document.querySelector('.bm-panel').parentNode.id==='books','dedicated screenshot');
 win.setSize(700,1000);await sleep(100);
 assert.ok(await evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'tablet avoids page overflow');
 fs.writeFileSync(path.join(artifacts,'book-mode-tablet.png'),(await win.webContents.capturePage()).toPNG());
 await evaluate(()=>document.querySelector('.bm-return').click());
 await waitFor(()=>!modeState.active,'final explicit FM return');
 assert.equal(await evaluate(()=>document.querySelector('.bm-panel').hidden&&document.querySelector('.bm-panel').parentNode.classList.contains('sp-right')),true,'dedicated FM return restores the inline script pane');
 const modes=await evaluate(()=>calls.filter(c=>c.url==='/api/books/mode').map(c=>c.p.active));
 assert.deepEqual(modes,[true,false,true,false],'only explicit start and FM return change station mode');
 console.log('Book Mode Electron QA passed: browse-only icon and Books rail, signed and JSON thumbnails, title fallback, horizontal paging, cover selection, search, radial and Read start, shared pause/resume, ordered 16x playback, FM return, desktop and tablet layout.');
 win.destroy();server.close();app.quit();
}).catch(error=>{console.error(error);if(win&&!win.isDestroyed())win.destroy();server.close();app.exit(1);});

