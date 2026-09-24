const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

let playwright;
try { playwright = require('playwright'); } catch (_) {
  const cache = path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx');
  if (fs.existsSync(cache)) for (const name of fs.readdirSync(cache)) {
    const candidate = path.join(cache, name, 'node_modules', 'playwright');
    if (fs.existsSync(candidate)) { playwright = require(candidate); break; }
  }
}
const root = path.resolve(__dirname, '..');
const files = {
  '/sfx-tv.js': ['desktop/renderer/sfx-tv.js', 'application/javascript'],
  '/sfx-tv.css': ['desktop/renderer/sfx-tv.css', 'text/css'],
  '/sample.mp4': ['tests/gen-ads-visual.mp4', 'video/mp4'],
};

test('parody trims and queues without refusing; dictation appends',
  {skip: !playwright, timeout: 120000}, async () => {
    const server = http.createServer((request, response) => {
      const pathname = new URL(request.url, 'http://localhost').pathname;
      if (pathname === '/') {
        response.writeHead(200, {'Content-Type': 'text/html'});
        response.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
          <link rel="stylesheet" href="/sfx-tv.css"></head><body>
          <script>
            window.sent = [];
            window.queueState = {jobs:[],live:{up:true,observed:true,busy:true},
              admission:{ok:false,why:'ComfyUI is busy rendering; its active work will finish first',
                available_gb:27.3,required_gb:60}};
            window.pineDesktop = {
              get: async path => path === '/api/comfy/workshop/parody-queue' ? queueState
                : path.startsWith('/api/sfx/history') ? {rows:[]} : {generations:[]},
              post: async (path, body) => {
                window.sent.push({path,body});
                if (path === '/api/comfy/workshop') {
                  queueState.jobs = [{id:'durable-1',status:'queued',position:1,
                    direction:body.prompt,frames:body.frames,created:Date.now()/1000,
                    reason:'ComfyUI is busy rendering'}];
                  return {queued:true,queue_id:'durable-1',status:'queued'};
                }
                return {done:false,why:'ComfyUI is rendering; no cache was freed'};
              }
            };
            window.PineTalkDot = {state:()=>window.listening ? 'listening' : 'idle',
              captureNext:fn=>{window.dictated=fn;window.listening=true;return Promise.resolve()},
              finish:()=>{window.listening=false;window.dictated('from microphone')}};
          </script><script src="/sfx-tv.js"></script>
          <script>window.PineSfxTv.openParody({id:'reference-1',url:'/sample.mp4',video:true,sting:'Reference'});</script>
          </body></html>`);
        return;
      }
      const file = files[pathname];
      if (!file) { response.writeHead(404); response.end(); return; }
      response.writeHead(200, {'Content-Type': file[1]});
      fs.createReadStream(path.join(root, file[0])).pipe(response);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    let browser;
    try {
      browser = await playwright.chromium.launch({headless:true});
      for (const viewport of [{width:1280,height:800}, {width:390,height:844}]) {
        const page = await browser.newPage({viewport});
        try {
          await page.goto('http://127.0.0.1:' + server.address().port + '/');
          await page.getByRole('slider', {name:'Trim in point'}).waitFor();
          await page.waitForFunction(() => !document.querySelector('.sfx-tv-parody-trim').hidden);
          await page.getByText('27.3 GB free / 60 GB needed').waitFor();
          const prompt = page.getByRole('textbox');
          await prompt.fill('Typed direction');
          await page.getByRole('button', {name:'Dictate the H3 prompt'}).click();
          await page.getByRole('button', {name:'Dictate the H3 prompt'}).click();
          assert.equal(await prompt.inputValue(), 'Typed direction from microphone');
          assert.equal(await prompt.evaluate(el => document.activeElement === el), true);
          const sliders = page.locator('.sfx-tv-parody-trim input[type=range]');
          await sliders.nth(0).evaluate(el => { el.value = '4'; el.dispatchEvent(new Event('input')); });
          await sliders.nth(1).evaluate(el => { el.value = '28'; el.dispatchEvent(new Event('input')); });
          await page.getByRole('button', {name:'Send to H3'}).click();
          await page.getByText('Stinger saved in the server queue').waitFor();
          const body = await page.evaluate(() => sent.find(item =>
            item.path === '/api/comfy/workshop')?.body);
          assert.equal(body.trim_in_s, 0.4);
          assert.equal(body.trim_out_s, 2.8);
          assert.equal(await page.locator('.sfx-tv-parody-stage video').evaluate(el =>
            getComputedStyle(el).objectFit), 'contain');
          const box = await page.locator('.sfx-tv-parody').boundingBox();
          assert.ok(box.x >= 0 && box.x + box.width <= viewport.width + 1);
          await page.screenshot({path:path.join(os.tmpdir(),
            `parody-stinger-${viewport.width}.png`)});
        } finally { await page.close(); }
      }
    } finally {
      if (browser) await browser.close();
      await new Promise(resolve => server.close(resolve));
    }
  });
