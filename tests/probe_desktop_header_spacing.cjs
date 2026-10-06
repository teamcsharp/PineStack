const { chromium } = require('C:/_tools/pinebox-playwright/node_modules/playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:800}});
    const css = ['styles.css','script-page.css','pine-pip.css'].map(name => fs.readFileSync(path.join(root,'desktop/renderer',name),'utf8')).join('\n');
    await page.setContent('<style>'+css+'</style><div class="pine-window-bar"><span>Pine Box</span></div><section class="pine-view-host open sp-page"><div class="sp-left"><button>Review all / controls</button></div><div class="sp-right"><div class="sp-script-top">THE SCRIPT</div><div id="spScript">Script content</div></div></section><style>.pine-view-host{position:fixed;inset:0;z-index:2147483000}.pine-view-host.open{display:block}</style>');
    for (const height of [800,420]) {
      await page.setViewportSize({width:1280,height});
      await page.locator('body').evaluate(el=>el.className='pine-frameless');
      const bounds = await page.evaluate(()=>{
        const host=document.querySelector('.pine-view-host').getBoundingClientRect();
        const bar=document.querySelector('.pine-window-bar').getBoundingClientRect();
        const button=document.querySelector('.sp-left button').getBoundingClientRect();
        return {top:host.top,bottom:host.bottom,height:host.height,barBottom:bar.bottom,buttonTop:button.top};
      });
      assert.equal(bounds.top,30); assert.equal(bounds.height,height-30); assert.equal(bounds.bottom,height);
      assert.ok(bounds.buttonTop>=bounds.barBottom,'review controls clear the title bar');
    }
    // Tablet/native-frame layouts continue to use the full viewport.
    await page.locator('body').evaluate(el=>el.className='');
    assert.equal(await page.locator('.pine-view-host').evaluate(el=>el.getBoundingClientRect().top),0);
    await page.locator('body').evaluate(el=>el.className='pine-frameless pine-pip');
    assert.equal(await page.locator('.pine-view-host').evaluate(el=>el.getBoundingClientRect().top),0);
    console.log('Desktop header spacing passed: title bar clears controls, view stays within viewport, tablet and PiP keep full height');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
