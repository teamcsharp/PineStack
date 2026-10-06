const {chromium}=require('C:/_tools/pinebox-playwright/node_modules/playwright-core');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('path');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage({viewport:{width:650,height:400},hasTouch:true});
  const css=fs.readFileSync(root+'/frontend/system3.css','utf8')+fs.readFileSync(root+'/desktop/renderer/script-page.css','utf8');
  const js=fs.readFileSync(root+'/desktop/renderer/script-page.js','utf8');
  const fn=js.slice(js.indexOf('  function toolbarTouch('),js.indexOf('  function bandController('));
  const icon='<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z" /></svg>';
  await page.setContent('<style>body{margin:0}'+css+'</style><div class="sp-page"><div class="sp-band-restore" id="tools"><div class="sp-tool-grid">'+Array.from({length:10},(_,i)=>'<button class="sp-band-reopen" aria-label="Option '+i+'">'+icon+'</button>').join('')+'</div><div class="sp-gap"><div class="sp-gap-dual"><span class="sp-gap-ic">H</span><div class="sp-gap-track">Track</div></div><button class="sp-gap-hold">cards</button></div><span class="sp-s3-tools"><span class="s3 s3-chrome"><span class="s3-bar-tools">'+Array.from({length:4},(_,i)=>'<button class="s3-ibtn" aria-label="Tool '+i+'">'+icon+'</button>').join('')+'</span></span></span></div></div>');
  await page.addScriptTag({content:'var root=window;function make(tag,cls,text){var n=document.createElement(tag);n.className=cls;if(text)n.textContent=text;return n;}'+fn+'toolbarTouch(document.getElementById("tools"));toolbarLayout(document.getElementById("tools"));window.hits=[];document.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>hits.push(b.getAttribute("aria-label"))));'});
  for (const width of [980,650,360,260,980]) {
    await page.setViewportSize({width,height:400});
    await page.waitForFunction(w => document.getElementById("tools").classList.contains("sp-tools-stacked") === (w < 751), width);
    const boxes=await page.locator('#tools button').evaluateAll(bs=>bs.map(b=>{const r=b.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};}));
    assert.equal(new Set(boxes.slice(0,10).map(b=>b.y)).size,width >= 751 ? 1 : 2);
    if (width >= 751) {
      const sizes=await page.locator(".sp-tool-grid button").evaluateAll(bs=>bs.map(b=>{const r=b.getBoundingClientRect();return [r.width,r.height];}));
      sizes.forEach(size=>assert.deepEqual(size,[34,34]));
    }
    const slider=await page.locator(".sp-gap").boundingBox(); assert.ok(slider.width<=240,"slider must stay bounded");
    for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i],b=boxes[j];assert.ok(a.right<=b.x||b.right<=a.x||a.bottom<=b.y||b.bottom<=a.y,'overlap at '+width);}
    assert.ok(Math.max(...boxes.map(b=>b.right))<=width,'overflow at '+width);
    assert.equal(await page.locator('#tools').evaluate(el=>el.getBoundingClientRect().height),40);
  }
  await page.setViewportSize({width:650,height:400});
  await page.waitForFunction(() => document.getElementById('tools').classList.contains('sp-tools-stacked'));
  await page.locator('.sp-tool-grid button').evaluateAll(bs=>bs.slice(4).forEach(b=>b.hidden=true));
  await page.waitForFunction(() => !document.getElementById('tools').classList.contains('sp-tools-stacked'));
  await page.locator('.sp-tool-grid button').evaluateAll(bs=>bs.forEach(b=>b.hidden=false));
  await page.waitForFunction(() => document.getElementById('tools').classList.contains('sp-tools-stacked'));
  const a=await page.locator('.sp-tool-grid button').nth(0).boundingBox(),b=await page.locator('.sp-tool-grid button').nth(3).boundingBox();
  await page.mouse.move(a.x+a.width/2,a.y+a.height/2);await page.mouse.down();assert.equal(await page.locator('.sp-tool-magnifier').count(),1);
  await page.mouse.move(b.x+b.width/2,b.y+b.height/2);assert.match(await page.locator('.sp-tool-magnifier').innerText(),/Option 3/);
  await page.screenshot({path:root+'/work/toolbar-responsive-magnifier.png'});
  await page.mouse.up();assert.deepEqual(await page.evaluate(()=>hits),['Option 3']);assert.equal(await page.locator('.sp-tool-magnifier').count(),0);
  const session=await page.context().newCDPSession(page);
  await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:a.x+a.width/2,y:a.y+a.height/2}]});
  await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:b.x+b.width/2,y:b.y+b.height/2}]});
  assert.match(await page.locator('.sp-tool-magnifier').innerText(),/Option 3/);
  await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});assert.deepEqual(await page.evaluate(()=>hits),['Option 3','Option 3']);
  await page.screenshot({path:root+'/work/toolbar-responsive-two-rows.png'});
  console.log('Browser toolbar passed: square icons at 980px, two rows at 650/360/260px, expands when controls hide, slider capped at 240px, 40px height, no overlap; mouse and touch slide select once');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
