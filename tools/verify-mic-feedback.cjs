const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

(async function () {
  const root = path.resolve(__dirname, '..');
  const script = process.env.PINE_TALK_SCRIPT || path.join(root, 'desktop/renderer/talk-dot.js');
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH});
  try {
    for (const viewport of [{width:1366,height:768},{width:390,height:844}]) {
      const page=await browser.newPage({viewport});
      await page.setContent('<input aria-label="Dictation field">');
      await page.addStyleTag({path:path.join(root,'desktop/renderer/view-chrome.css')});
      await page.evaluate(()=>{
        window.signal=.04;
        window.PineDuck={hold(){},release(){}};
        window.pineDesktop={micStart:async()=>({ok:true}),micStop:async()=>({ok:true,text:''}),micCancel:async()=>({ok:true}),
          micLevel:()=>signal,micMetrics:()=>({peak:signal,rms:signal/2,bands:Array(24).fill(signal),threshold:.03,
            vad_state:signal>.03?'speech':'silence',speech_probability:signal>.03?1:0,silence_elapsed_ms:0,endpoint_timeout_ms:4200,remaining_ms:4200})};
      });
      await page.addScriptTag({path:script});
      await page.evaluate(()=>PineTalkDot.captureNext(()=>{}));
      await page.waitForFunction(()=>Number(document.querySelector('[role=meter]')?.getAttribute('aria-valuenow'))>0);
      const low=await page.locator('[role=meter]').getAttribute('aria-valuenow');
      await page.evaluate(()=>signal=.4);
      await page.waitForFunction(value=>Number(document.querySelector('[role=meter]').getAttribute('aria-valuenow'))>Number(value),low);
      const reading=await page.locator('#pineTalkTelemetry').evaluate(node=>{
        const box=node.getBoundingClientRect();
        return {width:box.width,height:box.height,inside:box.left>=0&&box.right<=innerWidth&&box.top>=0&&box.bottom<=innerHeight,
          bands:node.querySelectorAll('.pine-talk-band').length,raised:parseFloat(node.querySelector('.pine-talk-band i').style.height)>0,
          hidden:node.hidden,ariaHidden:node.getAttribute('aria-hidden')};
      });
      assert.equal(reading.inside,true); assert.equal(reading.bands,24); assert.equal(reading.raised,true);
      assert.equal(reading.hidden,false); assert.equal(reading.ariaHidden,'false');
      await page.evaluate(()=>signal=0);
      await page.waitForFunction(()=>Number(document.querySelector('[role=meter]').getAttribute('aria-valuenow'))===0);
      await page.evaluate(()=>PineTalkDot.cancel());
      assert.equal(await page.locator('#pineTalkTelemetry').isVisible(),false);
      await page.evaluate(()=>{
        window.context=new AudioContext();
        const oscillator=context.createOscillator();
        const gain=context.createGain(); gain.gain.value=.15; oscillator.connect(gain); oscillator.start();
        window.stopInput=PineTalkDot.monitorInput(gain,context);
      });
      await page.waitForFunction(()=>Number(document.querySelector('[role=meter]').getAttribute('aria-valuenow'))>0);
      assert.equal(await page.locator('#pineTalkTelemetry').isVisible(),true);
      await page.evaluate(async()=>{stopInput();await context.close();});
      assert.equal(await page.locator('#pineTalkTelemetry').isVisible(),false);
      console.log(JSON.stringify({viewport,reading,quietAndLoud:true,recorderSignal:true,cleanup:true}));
      await page.close();
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
