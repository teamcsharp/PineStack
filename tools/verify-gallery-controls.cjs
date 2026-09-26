const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

async function main() {
  const root = path.resolve(__dirname, '..');
  const talkScript = process.env.PINE_TALK_SCRIPT || path.join(root, 'desktop/renderer/talk-dot.js');
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH});
  const results = [];
  try {
    for (const viewport of [{width:1366, height:768}, {width:1154, height:690}, {width:390, height:844}]) {
      const page = await browser.newPage({viewport});
      await page.setContent('<style>body{margin:0;background:#101719;color:white}*{box-sizing:border-box}</style>');
      await page.addStyleTag({path: path.join(root, 'desktop/renderer/view-chrome.css')});
      await page.evaluate(() => {
        const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
        window.__pineLogo = pixel;
        window.desktopMusicUrl = () => pixel;
        window.pineIcon = () => '<span aria-hidden="true">+</span>';
        window.requests = [];
        window.PineDuck = {level:1, hold(_id, n) {this.level=n;}, release() {this.level=1;}};
        window.pineDesktop = {
          get(url) {
            if (url.includes('/hourly')) return Promise.resolve({enabled:true, seconds_remaining:1500, period_seconds:3600});
            if (url.includes('/reference/')) return Promise.resolve({available:false});
            return Promise.resolve({generations:[{prompt_id:'image-job',files:['one.png','two.png'],request:'A gallery image'}], sig:{'one.png':'s','two.png':'s'}});
          },
          post(url, body) {window.requests.push({url,body}); return Promise.resolve({queue_id:'queued'});}
        };
      });
      await page.addScriptTag({path:talkScript});
      await page.addScriptTag({path:path.join(root, 'desktop/renderer/ad-viewer.js')});
      await page.evaluate(() => PineAdViewer.openGallery());
      const field = page.getByRole('textbox', {name:'H3 prompt or dialogue'});
      await field.fill('Welcome back to Pine Box.');
      await page.getByRole('combobox', {name:'H3 input type'}).selectOption('dialogue');
      await page.getByRole('button', {name:'Render H3 video', exact:true}).click();
      await page.waitForFunction(() => document.querySelector('.pav-status').textContent.includes('queued for H3'));
      const request = await page.evaluate(() => requests[0]);
      assert.equal(request.body.source, 'one.png');
      assert.equal(request.body.source_type, 'gallery');
      assert.equal(request.body.speech, 'Welcome back to Pine Box.');
      assert.equal(request.body.duration_mode, 'at_least');
      assert.equal(request.body.frames, undefined);
      assert.equal(await page.evaluate(() => PineDuck.level), .05);
      await page.getByRole('button', {name:'two.png', exact:true}).click();
      assert.equal(await field.inputValue(), '');
      await field.fill('A gentle camera move.');
      await page.getByRole('button', {name:'Render H3 video', exact:true}).click();
      assert.equal(await page.evaluate(() => requests.at(-1).body.source), 'two.png');
      await page.getByRole('button', {name:'one.png', exact:true}).click();
      assert.equal(await field.inputValue(), 'Welcome back to Pine Box.');

      async function micInside() {
        await field.focus();
        return field.evaluate(input => {
          const mic = input.parentElement.querySelector('.pine-field-mic');
          const a=input.getBoundingClientRect(), b=mic.getBoundingClientRect();
          return {inside:b.left>=a.left && b.top>=a.top && b.right<=a.right+1 && b.bottom<=a.bottom+1,
            fieldWidth:a.width, micWidth:b.width, sameParent:mic.parentElement===input.parentElement};
        });
      }
      assert.equal((await micInside()).inside, true);
      await page.evaluate(() => {
        const card=document.querySelector('.pine-voice-ad-card');
        card.style.transform='scale(.8)';
        card.scrollTop=card.scrollHeight;
      });
      assert.equal((await micInside()).inside, true, 'scaled and scrolled gallery keeps mic inside field');
      await page.evaluate(() => document.querySelector('.pine-voice-ad-card').style.transform='');
      const bounds = await page.evaluate(() => {
        const card=document.querySelector('.pine-voice-ad-card');
        const box=card.getBoundingClientRect();
        const buttons=[...card.querySelectorAll('footer button,footer a')].map(n=>n.getBoundingClientRect());
        return {overflow:card.scrollWidth>card.clientWidth+1, buttonsFit:buttons.every(b=>b.left>=box.left && b.right<=box.right+1)};
      });
      assert.equal(bounds.overflow, false);
      assert.equal(bounds.buttonsFit, true);
      await page.getByRole('button', {name:'Close ad viewer', exact:true}).click();
      assert.equal(await page.evaluate(() => PineDuck.level), 1);
      assert.equal(await page.locator('.pine-field-mic').count(), 0, 'closing the window removes its mic');

      await page.setContent('<style>body{margin:0}button{min-height:36px}.panel{width:90%;margin:20px;overflow:auto;height:250px;transform:translateZ(0)}.panel>input{width:100%;height:31px;margin-bottom:6px}.full{position:fixed;inset:0;width:auto;margin:0;height:auto}.spacer{height:800px}</style><div class="panel"><input aria-label="Filter properties"><div class="spacer"></div></div>');
      await page.addScriptTag({path:talkScript});
      const filter=page.getByRole('textbox',{name:'Filter properties'});
      const before=await filter.boundingBox();
      await filter.fill('voice');
      const after=await filter.boundingBox();
      assert.ok(Math.abs(before.width-after.width)<2, 'wrapping preserves the input width');
      await page.evaluate(() => document.querySelector('.panel').classList.add('full'));
      const fullscreen=await filter.evaluate(input=>{
        const a=input.getBoundingClientRect(), b=input.parentElement.querySelector('.pine-field-mic').getBoundingClientRect();
        return b.right<=a.right+1 && b.top>=a.top && b.bottom<=a.bottom+1;
      });
      assert.equal(fullscreen,true);
      await page.evaluate(() => document.querySelector('.panel').classList.remove('full'));
      assert.ok(Math.abs((await filter.boundingBox()).width-before.width)<2);
      await page.evaluate(() => document.querySelector('.panel').scrollTop=200);
      const clipped=await page.locator('.pine-field-mic').evaluate(mic=>mic.hidden || mic.getBoundingClientRect().bottom<0);
      assert.equal(clipped,true,'the mic scrolls out with its input instead of sticking over other rows');
      results.push({viewport, imageRender:true, independentDrafts:true, duckRestore:true, fieldMic:true, fullscreen:true, bounds});
      await page.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify(results,null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
