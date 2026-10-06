/* Real Electron layout coverage for browse-only, two-page book previews. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const repo=process.env.PINE_BOOK_TEST_ROOT||path.resolve(__dirname,'..');
const artifacts=process.env.PINE_BOOK_TEST_OUTPUT||path.join(repo,'artifacts');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const requests=[],messages=[];
const fixtureToken='fixture-auth',version='fixture-v1';
const resourceBase='/api/books/epub/preview/resource/';
const svgFigure='<svg xmlns="http://www.w3.org/2000/svg" width="340" height="135"><rect width="340" height="135" fill="#d4e8ed"/><path d="M18 103 L90 40 L158 93 L240 24 L319 103" fill="none" stroke="#4c5277" stroke-width="7"/><text x="19" y="122" font-size="16" fill="#2a3646">Original illustrated chapter figure</text></svg>';
const coverSvg='<svg xmlns="http://www.w3.org/2000/svg" width="300" height="420"><rect width="300" height="420" fill="#345"/><text x="22" y="80" fill="white">An Illustrated Book</text></svg>';
const fontFile=[
 'C:\\Windows\\Fonts\\georgia.ttf',
 '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
 '/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf'
].find(file=>fs.existsSync(file));
const authorCss='@font-face{font-family:PreviewSerif;src:url("'+resourceBase+'font.ttf?t='+fixtureToken+'&v='+version+'")}body{font-family:PreviewSerif,Georgia,serif;line-height:1.62;color:#26303b}h1.chapter-title{font-size:1.6em;color:rgb(72,41,119);font-weight:700}p{margin:0 0 .9em;text-indent:1.2em}p.epigraph{font-style:italic;text-indent:0;border-left:3px solid #8c8fb1;padding-left:1em}em{font-style:italic}ul,ol{padding-left:1.7em}table{border-collapse:collapse;width:100%}th,td{border:1px solid #788590;padding:.25em}figure{margin:1em 0}figcaption{font-size:.85em;font-style:italic}img{max-width:100%;height:auto}';
function chapterHtml(index){
 const intro='<h1 class="chapter-title">Chapter '+(index+1)+': The Original Page</h1><p class="epigraph">The book keeps its own visual voice.</p><h2 id="chapter-anchor">A readable opening</h2><p id="styled-paragraph">A proper reader preserves <em id="styled-emphasis">emphasis and typography</em>, paragraph spacing, headings, lists, tables, and illustrations from the original book.</p><ul><li>First original list item</li><li>Second original list item</li></ul><table><thead><tr><th>Place</th><th>Year</th></tr></thead><tbody><tr><td>Pine Valley</td><td>1924</td></tr></tbody></table><figure><img id="original-figure" alt="Original illustration" src="'+resourceBase+'figure.svg?t='+fixtureToken+'&v='+version+'"/><figcaption>Figure 1. The original book illustration.</figcaption></figure>';
 const links='<p><a id="next-chapter-link" href="/api/books/epub/preview/chapter/1?t='+fixtureToken+'&v='+version+'#chapter-anchor">Continue to the next original chapter</a> &middot; <a id="same-chapter-link" href="#passage-20">See passage twenty</a></p>';
 const paragraphs=Array.from({length:index===0?78:31},(_,i)=>'<p id="passage-'+(i+1)+'" data-paragraph="'+i+'">Passage '+(i+1)+'. Across the quiet valley the readers followed the story through the changing seasons. Every page carried its own details, the sounds of distant water, the small observations of the characters, and the history that gave those observations meaning. The printed paragraphs should flow naturally across facing pages while preserving the rhythm of the source.</p>').join('');
 return '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Chapter '+(index+1)+'</title><link rel="stylesheet" href="'+resourceBase+'author.css?t='+fixtureToken+'&v='+version+'"></head><body><article>'+intro+links+paragraphs+'</article></body></html>';
}
function manifest(id){
 if(id==='pdf-error'){const result=manifest('pdf');result.title='PDF Rendering Failure';result.pages=result.pages.slice(0,2);result.page_count=2;result.pages[0].url='/missing-pdf-page.svg';result.pages[1].url+='&slow=1';return result;}
 if(id==='epub-cover')return {kind:'epub',title:'A Tall Original Cover',version,chapter_count:1,chapters:[{index:0,title:'Original cover',url:'/api/books/epub-cover/preview/chapter/0?t='+fixtureToken+'&v='+version}]};
 if(id==='pdf')return {kind:'pdf',title:'Original Illustrated PDF',version,page_count:5,pages:Array.from({length:5},(_,index)=>({index,width:612,height:792,url:'/api/books/pdf/preview/page/'+index+'?t='+fixtureToken+'&v='+version}))};
 return {kind:'epub',title:'An Illustrated Book',version,chapter_count:2,chapters:[0,1].map(index=>({index,title:'Chapter '+(index+1)+': The Original Page',url:'/api/books/epub/preview/chapter/'+index+'?t='+fixtureToken+'&v='+version}))};
}
function renderViewer(id,base){
 const template=fs.readFileSync(path.join(repo,'desktop/renderer/book-preview.html'),'utf8');
 return template.replace(/__BOOK_PREVIEW_CONFIG__/g,JSON.stringify({book:id,title:manifest(id).title,manifestUrl:base+'/api/books/'+id+'/preview?t='+fixtureToken}).replace(/</g,'\\u003c'))
  .replace(/__BOOK_PREVIEW_CSS_URL__/g,base+'/desktop/renderer/book-preview.css')
  .replace(/__BOOK_PREVIEW_JS_URL__/g,base+'/desktop/renderer/book-preview.js');
}
const server=http.createServer((req,res)=>{
 requests.push(req.url);
 const url=new URL(req.url,'http://127.0.0.1'),route=url.pathname;
 const send=(type,body)=>{res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});res.end(body);};
 if(/^\/(?:reader|books\/read)\/(?:epub|pdf|epub-cover|pdf-error)$/.test(route)){send('text/html; charset=utf-8',renderViewer(route.split('/').pop(),'http://127.0.0.1:'+server.address().port));return;}
 if(/^\/api\/books\/(?:epub|pdf|epub-cover|pdf-error)\/preview$/.test(route)){send('application/json',JSON.stringify(manifest(route.split('/')[3])));return;}
 if(route==='/api/books/epub-cover/preview/chapter/0'){send('text/html; charset=utf-8','<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="'+resourceBase+'author.css?t='+fixtureToken+'&v='+version+'"></head><body><figure style="margin:0"><img id="original-cover" width="600" height="1200" alt="Original tall cover art" src="'+resourceBase+'tall-cover.svg?t='+fixtureToken+'&v='+version+'"></figure></body></html>');return;}
 if(route===resourceBase+'tall-cover.svg'){send('image/svg+xml','<svg xmlns="http://www.w3.org/2000/svg" width="600" height="1200"><rect width="600" height="1200" fill="#4e617d"/><rect x="38" y="38" width="524" height="1124" fill="none" stroke="#f4e9c8" stroke-width="8"/><text x="300" y="210" text-anchor="middle" font-family="Georgia" font-size="46" fill="#fff4d8">Original Cover</text><text x="300" y="1055" text-anchor="middle" font-family="Georgia" font-size="30" fill="#fff4d8">Both edges remain visible</text></svg>');return;}
 if(route==='/missing-pdf-page.svg'){res.writeHead(404);res.end();return;}
 if(/^\/api\/books\/epub\/preview\/chapter\/[01]$/.test(route)){send('text/html; charset=utf-8',chapterHtml(Number(route.split('/').pop())));return;}
 if(route===resourceBase+'author.css'){send('text/css; charset=utf-8',authorCss);return;}
 if(route===resourceBase+'figure.svg'){send('image/svg+xml',svgFigure);return;}
 if(route===resourceBase+'font.ttf'&&fontFile){send('font/ttf',fs.readFileSync(fontFile));return;}
 if(/^\/api\/books\/pdf\/preview\/page\/[0-4]$/.test(route)){
  const index=Number(route.split('/').pop());
  const pageBody='<svg xmlns="http://www.w3.org/2000/svg" width="612" height="792"><rect width="612" height="792" fill="#fffdf7"/><rect x="50" y="50" width="512" height="692" fill="none" stroke="#75644f" stroke-width="2"/><text x="78" y="119" font-family="Georgia" font-size="27" fill="#34324d">Original PDF page '+(index+1)+'</text><text x="78" y="164" font-family="Georgia" font-size="17" fill="#34324d">Original layout, illustrations, and typography</text><rect x="80" y="210" width="452" height="200" fill="'+['#d4e8ed','#ead8d1','#d6e7d2','#e6dfc8','#e3dcef'][index]+'"/><path d="M105 372 L196 248 L309 360 L430 246 L510 377" fill="none" stroke="#685978" stroke-width="7"/><text x="304" y="720" text-anchor="middle" font-family="Georgia" font-size="16">'+(index+1)+'</text></svg>';
  if(url.searchParams.has('slow'))setTimeout(()=>send('image/svg+xml',pageBody),120);else send('image/svg+xml',pageBody);
  return;
 }
 if(route==='/signed/cover.svg'){send('image/svg+xml',coverSvg);return;}
 if(/^\/desktop\/renderer\/book-preview\.(?:html|css|js)$/.test(route)){
  const file=path.basename(route),type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html';
  send(type+'; charset=utf-8',fs.readFileSync(path.join(repo,'desktop/renderer',file)));return;
 }
 if(/^\/book-preview\.(?:html|css|js)$/.test(route)){
  const file=path.basename(route),type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html';
  send(type+'; charset=utf-8',fs.readFileSync(path.join(repo,'desktop/renderer',file)));return;
 }
 if(route==='/shell'){send('text/html; charset=utf-8','<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>');return;}
 res.writeHead(404,{'Content-Type':'text/plain'});res.end('Unknown fixture route: '+route);
});
app.disableHardwareAcceleration();
app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'pine-book-preview-test-')));
let win;
app.whenReady().then(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const stationBase='http://127.0.0.1:'+server.address().port;
 win=new BrowserWindow({show:false,width:1154,height:690,webPreferences:{offscreen:true,nodeIntegration:true,contextIsolation:false}});
 win.webContents.on('console-message',event=>messages.push(event.message));
 const evaluate=(fn,...args)=>win.webContents.executeJavaScript('('+fn.toString()+')('+JSON.stringify(args).slice(1,-1)+')');
 async function waitFor(fn,message,timeout=7000){
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){if(await evaluate(fn))return;await sleep(30);}
  throw new Error('Timed out: '+message+'; console: '+messages.slice(-8).join(' | '));
 }
 async function openViewer(id){
  await win.loadURL(stationBase+'/reader/'+id);
  await waitFor(()=>!!window.PineBookPreview,'viewer API');
  await evaluate(()=>PineBookPreview.ready);
  await waitFor(()=>PineBookPreview.state().pageCount>0,'reader pagination');
 }
 async function screenshot(name){
  fs.mkdirSync(artifacts,{recursive:true});
  fs.writeFileSync(path.join(artifacts,name),(await win.webContents.capturePage()).toPNG());
 }
 async function layout(){
  return evaluate(()=>{
   const viewer=document.querySelector('.bp-viewer').getBoundingClientRect(),spread=document.querySelector('.bp-spread').getBoundingClientRect(),toolbar=document.querySelector('.bp-toolbar').getBoundingClientRect(),stage=document.querySelector('.bp-stage');
   return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,viewer:{left:viewer.left,top:viewer.top,right:viewer.right,bottom:viewer.bottom},spread:{left:spread.left,top:spread.top,right:spread.right,bottom:spread.bottom,width:spread.width,height:spread.height},toolbar:{left:toolbar.left,top:toolbar.top,right:toolbar.right,bottom:toolbar.bottom},stage:{scrollWidth:stage.scrollWidth,width:stage.clientWidth,overflowX:getComputedStyle(stage).overflowX},state:PineBookPreview.state()};
  });
 }
 function assertLayout(details,label){
  assert.ok(details.scrollWidth<=details.width+1,label+' avoids outer horizontal overflow: '+JSON.stringify(details));
  assert.ok(details.viewer.left>=-1&&details.viewer.right<=details.width+1&&details.viewer.bottom<=details.height+1,label+' reader fits viewport');
  assert.ok(details.spread.width>400&&details.spread.height>200,label+' facing pages have usable dimensions');
  if(details.state.kind==='pdf'&&details.state.zoom>100){assert.match(details.stage.overflowX,/auto|scroll/,label+' zoomed PDF pans within its stage');}else{assert.ok(details.spread.left>=-1&&details.spread.right<=details.width+1,label+' spread stays inside viewport');}
  assert.ok(details.toolbar.top>=-1&&details.toolbar.bottom<=details.height+1,label+' toolbar remains accessible');
 }
 async function epubSnapshot(){
  return evaluate(()=>{
   const frame=document.getElementById('bp-epub'),doc=frame.contentDocument;
   const styled=doc.getElementById('styled-paragraph'),title=doc.querySelector('.chapter-title'),em=doc.getElementById('styled-emphasis'),figure=doc.getElementById('original-figure');
   const columns=Array.from(doc.querySelectorAll('*')).filter(el=>{const style=frame.contentWindow.getComputedStyle(el);return style.columnWidth!=='auto'||Number(style.columnCount)>1;}).map(el=>({tag:el.tagName,id:el.id,width:el.getBoundingClientRect().width,columnWidth:frame.contentWindow.getComputedStyle(el).columnWidth,columnCount:frame.contentWindow.getComputedStyle(el).columnCount,columnGap:frame.contentWindow.getComputedStyle(el).columnGap,transform:frame.contentWindow.getComputedStyle(el).transform,scrollWidth:el.scrollWidth}));
   return {sandbox:frame.getAttribute('sandbox'),frame:{width:frame.getBoundingClientRect().width,height:frame.getBoundingClientRect().height},title:frame.contentWindow.getComputedStyle(title).color,em:frame.contentWindow.getComputedStyle(em).fontStyle,font:frame.contentWindow.getComputedStyle(styled).fontFamily,lineHeight:frame.contentWindow.getComputedStyle(styled).lineHeight,paragraphs:doc.querySelectorAll('p').length,lists:doc.querySelectorAll('li').length,tables:doc.querySelectorAll('table').length,captions:doc.querySelectorAll('figcaption').length,imageLoaded:figure.complete&&figure.naturalWidth>0,columns,state:PineBookPreview.state()};
  });
 }
 await openViewer('epub');
 await waitFor(()=>document.getElementById('bp-epub')?.contentDocument?.getElementById('original-figure')?.complete,'EPUB illustration');
 const epub=await epubSnapshot();
 assert.equal(epub.sandbox,'allow-same-origin','EPUB author markup has no script execution privilege');
 assert.equal(epub.title,'rgb(72, 41, 119)','author stylesheet preserves original heading color');
 assert.equal(epub.em,'italic','original inline emphasis is rendered');
 assert.match(epub.font,/PreviewSerif|Georgia/,'source typography is retained');
 assert.ok(epub.paragraphs>=80&&epub.lists===2&&epub.tables===1&&epub.captions===1,'original rich chapter structure remains');
 assert.equal(epub.imageLoaded,true,'original chapter illustration renders');
 assert.ok(epub.columns.length>0,'EPUB uses real CSS pagination');
 assert.ok(epub.state.pageCount>2&&epub.state.spreadCount>1,'long chapter paginates beyond its first facing pages');
 assert.equal(epub.state.pageIndex,0);
 assertLayout(await layout(),'desktop EPUB');
 await screenshot('book-preview-epub-desktop.png');
 await evaluate(()=>document.getElementById('bp-epub').contentDocument.body.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true})));
 await waitFor(()=>PineBookPreview.state().pageIndex===2,'EPUB keyboard next from focused source iframe');
 await evaluate(()=>document.getElementById('bp-epub').contentDocument.body.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true})));
 await waitFor(()=>PineBookPreview.state().pageIndex===0,'EPUB keyboard previous from focused source iframe');
 await evaluate(()=>document.getElementById('bp-epub').contentDocument.getElementById('same-chapter-link').click());
 await waitFor(()=>PineBookPreview.state().pageIndex>0,'EPUB original same-chapter anchor link');
 await evaluate(()=>PineBookPreview.goToPage(1));
 await evaluate(()=>document.getElementById('bp-next').click());
 await waitFor(()=>PineBookPreview.state().pageIndex===2,'EPUB next facing pages');
 assert.equal(await evaluate(()=>document.getElementById('bp-page-input').value),'3');
 await evaluate(()=>document.getElementById('bp-prev').click());
 await waitFor(()=>PineBookPreview.state().pageIndex===0,'EPUB previous facing pages');
 await evaluate(()=>{const input=document.getElementById('bp-page-input');input.value='7';input.dispatchEvent(new Event('change',{bubbles:true}));});
 await waitFor(()=>PineBookPreview.state().pageIndex===6,'EPUB jump to selected spread');
 const beforeZoom=await evaluate(()=>PineBookPreview.state());
 await evaluate(()=>{const zoom=document.getElementById('bp-zoom');zoom.value='150';zoom.dispatchEvent(new Event('change',{bubbles:true}));});
 await waitFor(()=>PineBookPreview.state().zoom===150,'EPUB zoom');
 await waitFor(()=>PineBookPreview.state().pageCount>0,'EPUB repagination after zoom');
 const afterZoom=await evaluate(()=>PineBookPreview.state());
 assert.ok(afterZoom.pageCount>beforeZoom.pageCount,'larger original content repaginates into more pages');
 assertLayout(await layout(),'zoomed desktop EPUB');
 await evaluate(()=>{const chapter=document.getElementById('bp-chapter');chapter.value='1';chapter.dispatchEvent(new Event('change',{bubbles:true}));});
 await waitFor(()=>PineBookPreview.state().chapterIndex===1&&PineBookPreview.state().pageIndex===0&&document.getElementById('bp-epub')?.contentDocument?.querySelector('h1')?.textContent.includes('Chapter 2'),'EPUB chapter selector');
 assert.match(await evaluate(()=>document.getElementById('bp-epub').contentDocument.querySelector('h1').textContent),/Chapter 2/);
 await evaluate(()=>PineBookPreview.selectChapter(0));
 await evaluate(()=>document.getElementById('bp-epub').contentDocument.getElementById('next-chapter-link').click());
 await waitFor(()=>PineBookPreview.state().chapterIndex===1&&document.getElementById('bp-epub')?.contentDocument?.querySelector('h1')?.textContent.includes('Chapter 2'),'EPUB original cross-chapter link');
 await evaluate(()=>PineBookPreview.selectChapter(0));
 await evaluate(()=>PineBookPreview.setZoom(100));
 win.setSize(700,1000);
 await sleep(150);
 await waitFor(()=>PineBookPreview.state().pageCount>0,'tablet EPUB repagination');
 const tabletEpub=await epubSnapshot();
 assert.ok(tabletEpub.columns.length>0&&tabletEpub.frame.width>400,'tablet keeps facing-page EPUB pagination');
 assertLayout(await layout(),'tablet EPUB');
 await screenshot('book-preview-epub-tablet.png');
 await openViewer('epub-cover');
 await waitFor(()=>document.getElementById('bp-epub')?.contentDocument?.getElementById('original-cover')?.complete,'original tall cover image');
 const cover=await evaluate(()=>{
  const frame=document.getElementById('bp-epub'),img=frame.contentDocument.getElementById('original-cover'),rect=img.getBoundingClientRect();
  return {loaded:img.naturalWidth>0,height:rect.height,top:rect.top,bottom:rect.bottom,frameHeight:frame.clientHeight};
 });
 assert.equal(cover.loaded,true);
 assert.ok(cover.height<=cover.frameHeight+1&&cover.top>=-1&&cover.bottom<=cover.frameHeight+1,'tall publisher cover fits its tablet page without clipping: '+JSON.stringify(cover));
 await screenshot('book-preview-epub-cover-tablet.png');
 win.setSize(1154,690);
 await openViewer('pdf');
 await waitFor(()=>Array.from(document.querySelectorAll('.bp-pdf-page img')).filter(img=>img.src).every(img=>img.complete&&img.naturalWidth>0),'original PDF page images');
 const pdf=await evaluate(()=>{
  const slots=Array.from(document.querySelectorAll('.bp-pdf-page')),imgs=slots.map(slot=>slot.querySelector('img'));
  return {slots:slots.length,state:PineBookPreview.state(),sources:imgs.map(img=>img.src),bounds:slots.map(slot=>{const r=slot.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};})};
 });
 assert.equal(pdf.slots,2,'PDF reader renders exactly two facing page slots');
 assert.equal(pdf.state.pageCount,5);
 assert.equal(pdf.state.spreadCount,3);
 assert.match(pdf.sources[0],/\/page\/0\?/);
 assert.match(pdf.sources[1],/\/page\/1\?/);
 assert.ok(pdf.bounds[0].right<=pdf.bounds[1].left+2,'PDF pages are side by side');
 assert.ok(Math.abs(pdf.bounds[0].top-pdf.bounds[1].top)<3,'PDF facing pages align vertically');
 assertLayout(await layout(),'desktop PDF');
 await screenshot('book-preview-pdf-desktop.png');
 await evaluate(()=>document.getElementById('bp-next').click());
 await waitFor(()=>PineBookPreview.state().pageIndex===2,'PDF next facing pages');
 await waitFor(()=>document.querySelector('.bp-pdf-page img').src.includes('/page/2?'),'PDF next page source');
 await evaluate(()=>document.getElementById('bp-next').click());
 await waitFor(()=>PineBookPreview.state().pageIndex===4,'odd last PDF spread');
 const odd=await evaluate(()=>{
  const slots=Array.from(document.querySelectorAll('.bp-pdf-page')),imgs=slots.map(slot=>slot.querySelector('img'));
  return {count:slots.length,src:imgs.map(img=>img?.getAttribute('src')||''),hidden:imgs.map(img=>!img||img.hidden||getComputedStyle(img).display==='none'),disabled:document.getElementById('bp-next').disabled};
 });
 assert.equal(odd.count,2,'odd last spread preserves two-page geometry');
 assert.match(odd.src[0],/\/page\/4\?/);
 assert.ok(!odd.src[1]||odd.hidden[1],'odd last spread leaves the second page blank');
 assert.equal(odd.disabled,true,'reader stops at the final spread');
 await screenshot('book-preview-pdf-final-spread.png');
 await evaluate(()=>document.getElementById('bp-prev').click());
 await waitFor(()=>PineBookPreview.state().pageIndex===2,'PDF previous spread');
 await evaluate(()=>{const input=document.getElementById('bp-page-input');input.value='1';input.dispatchEvent(new Event('change',{bubbles:true}));});
 await waitFor(()=>PineBookPreview.state().pageIndex===0,'PDF page selector');
 await evaluate(()=>{const zoom=document.getElementById('bp-zoom');zoom.value='125';zoom.dispatchEvent(new Event('change',{bubbles:true}));});
 await waitFor(()=>PineBookPreview.state().zoom===125,'PDF zoom');
 assertLayout(await layout(),'zoomed desktop PDF');
 win.setSize(700,1000);
 await sleep(150);
 const tabletPdf=await evaluate(()=>Array.from(document.querySelectorAll('.bp-pdf-page')).map(slot=>{const r=slot.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};}));
 assert.ok(tabletPdf[0].right<=tabletPdf[1].left+2,'tablet PDF keeps two side-by-side pages');
 assertLayout(await layout(),'tablet PDF');
 await screenshot('book-preview-pdf-tablet.png');
 await openViewer('pdf-error');
 await waitFor(()=>document.querySelector('.bp-pdf-right img')?.complete&&document.querySelector('.bp-pdf-right img')?.naturalWidth>0,'healthy PDF facing page after sibling render failure');
 await sleep(150);
 assert.match(await evaluate(()=>document.getElementById('bp-message').textContent),/Page 1 could not be rendered/,'PDF render error stays visible after the facing page loads');
 assert.equal(await evaluate(()=>document.getElementById('bp-message').hidden),false,'failed PDF page shows a visible reader error');
 // Exercise the actual shelf Preview entry point while the FM state remains inactive.
 win.setSize(1154,690);
 await win.loadURL(stationBase+'/shell');
 const bookMode=fs.readFileSync(path.join(repo,'desktop/renderer/book-mode.js'),'utf8');
 const bookCss=fs.readFileSync(path.join(repo,'desktop/renderer/book-mode.css'),'utf8');
 await evaluate((base,css,coverSvg)=>{
  document.head.innerHTML='<style>'+css+'</style><style>html,body{margin:0;width:100%;height:100%;background:#101b22}#script{position:fixed;inset:0}.sp-right{height:100%}</style>';
  document.body.innerHTML='<section id="script"><div class="sp-right"><div id="bar"></div></div></section>';
  window.pineStationBase=()=>base;
  window.calls=[];window.audioStarts=0;
  window.modeState={active:false,book:'',position:0,epoch:1,session:'one',title:'',preferences:{speed:1,gap_ms:0,blend_ms:0,readers:['host','cohost','third'],routing:'sequential',scope:'book',show:'read',research:false,sfx:true,reader_node:{id:'book-reader',label:'Next book reader',weights:{}}},events:[],errors:[]};
  window.pineDesktop={
   get:async url=>{
    calls.push(url);
    if(url==='/api/books/state')return structuredClone(modeState);
    if(url.startsWith('/api/books?'))return {books:[{id:'epub',title:'An Illustrated Book',author:'The Original Author',kind:'epub',cover_url:'/signed/cover.svg'},{id:'pdf',title:'Original Illustrated PDF',kind:'pdf',cover_url:'/signed/cover.svg'}],total:2,errors:[]};
    if(url.endsWith('/document')){const id=url.split('/')[3];return {kind:id==='pdf'?'pdf':'epub',title:id==='pdf'?'Original Illustrated PDF':'An Illustrated Book',url:'',preview_url:'/books/read/'+id+'?t=fixture-auth'};}
    if(url.endsWith('/cover'))return {svg:coverSvg};
    throw new Error('Unexpected browsing API read: '+url);
   },
   post:async(url,p)=>{calls.push({url,p});throw new Error('Preview must not mutate station state: '+url);}
  };
  window.Audio=class{play(){audioStarts++;return Promise.resolve();}pause(){}removeAttribute(){}load(){}};
 },stationBase,bookCss,coverSvg);
 await win.webContents.executeJavaScript(bookMode+'\nPineBookMode.mount(document.getElementById("script"),document.getElementById("bar"));');
 await waitFor(()=>calls.includes('/api/books/state'),'book shelf state');
 await evaluate(()=>document.querySelector('.bm-toggle').click());
 await waitFor(()=>document.querySelectorAll('.bm-card').length===2,'book preview shelf');
 await evaluate(()=>Array.from(document.querySelector('[data-book="epub"]').querySelectorAll('button')).find(button=>button.textContent==='Preview').click());
 await waitFor(()=>!!document.querySelector('dialog iframe'),'shelf preview reader iframe');
 await waitFor(()=>document.querySelector('dialog iframe')?.contentWindow?.PineBookPreview?.state().pageCount>0,'shelf preview actual reader pagination');
 assert.equal(await evaluate(()=>modeState.active),false,'EPUB preview leaves Pine Box FM active');
 assert.equal(await evaluate(()=>document.body.classList.contains('pine-book-mode')),false);
 await screenshot('book-preview-shelf-dialog.png');
 await evaluate(()=>document.querySelector('dialog iframe').contentWindow.PineBookPreview.next());
 await waitFor(()=>document.querySelector('dialog iframe')?.contentWindow?.PineBookPreview?.state().pageIndex===2,'shelf preview navigation');
 await evaluate(()=>Array.from(document.querySelectorAll('dialog button')).find(button=>button.textContent==='Close'||button.title==='Close preview').click());
 await waitFor(()=>!document.querySelector('dialog'),'preview close removes dialog and iframe');
 await evaluate(()=>Array.from(document.querySelector('[data-book="pdf"]').querySelectorAll('button')).find(button=>button.textContent==='Preview').click());
 await waitFor(()=>document.querySelector('dialog iframe')?.contentWindow?.PineBookPreview?.state().kind==='pdf','PDF shelf preview');
 await evaluate(()=>document.querySelector('dialog').dispatchEvent(new Event('cancel',{cancelable:true})));
 await waitFor(()=>!document.querySelector('dialog'),'Escape cleanup removes PDF preview');
 const mutations=await evaluate(()=>calls.filter(call=>typeof call==='object'));
 assert.deepEqual(mutations,[],'opening, navigating, and closing previews never calls mode/select/claim/next/seek/started/heard');
 assert.equal(await evaluate(()=>audioStarts),0,'book preview never starts narration');
 assert.equal(await evaluate(()=>modeState.active),false);
 assert.ok(requests.some(url=>url.startsWith(resourceBase+'author.css?')),'reader fetches original source stylesheet');
 assert.ok(requests.some(url=>url.startsWith(resourceBase+'figure.svg?')),'reader fetches original chapter illustration');
 if(fontFile)assert.ok(requests.some(url=>url.startsWith(resourceBase+'font.ttf?')),'reader fetches original book font');
 assert.ok(!requests.some(url=>url.includes('/sentences')),'preview preserves source document instead of simplifying to sentences');
 console.log('Book preview Electron QA passed: original EPUB formatting, CSS, images and fonts; facing pages, pagination, chapters, original links, frame keyboard, page selection and zoom; tall cover fits; original PDF page images, odd final blank page and persistent load errors; desktop/tablet layout; browse-only shelf preview with close/Escape cleanup and no narration mutations.');
 win.destroy();server.close();app.quit();
}).catch(error=>{
 console.error(error);
 if(win&&!win.isDestroyed())win.destroy();
 server.close();app.exit(1);
});


