const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

let playwright;
try { playwright = require('playwright'); } catch (_) {
  const cache = path.join(os.homedir(), 'AppData', 'Local', 'npm-cache', '_npx');
  if (fs.existsSync(cache)) {
    for (const name of fs.readdirSync(cache)) {
      const candidate = path.join(cache, name, 'node_modules', 'playwright');
      if (fs.existsSync(candidate)) { playwright = require(candidate); break; }
    }
  }
}

const root = path.resolve(__dirname, '..');
const files = {
  '/frontend/comfy-workshop.css': ['frontend/comfy-workshop.css', 'text/css'],
  '/frontend/comfy-workshop.js': ['frontend/comfy-workshop.js', 'application/javascript'],
  '/spark/asset/pinebox.png': ['desktop/assets/pinebox-256.png', 'image/png'],
  '/sample.mp4': ['tests/gen-ads-visual.mp4', 'video/mp4'],
};

test('Workshop preview uses a logo cover, fitted video, and keyboard controls',
  {skip: !playwright}, async () => {
    const server = http.createServer((request, response) => {
      const pathname = new URL(request.url, 'http://localhost').pathname;
      if (pathname === '/') {
        response.writeHead(200, {'Content-Type': 'text/html'});
        response.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
          <link rel="stylesheet" href="/frontend/comfy-workshop.css"></head><body>
          <script type="module">
            import {openComfyWorkshop} from '/frontend/comfy-workshop.js';
            const video = {id:'good',name:'Wide reference',kind:'video',video:true,
              url:'/sample.mp4',poster:'/broken-poster.png'};
            const missing = {id:'missing',name:'Unavailable reference',kind:'video',video:true,
              url:'/missing.mp4',poster:'/broken-poster.png'};
            window.workshop = await openComfyWorkshop({request:async path =>
              path === '/api/comfy/workshop'
                ? {admission:{ok:true},recent:[video,missing],clips:[],gallery:[],dialogue:[],jobs:[]}
                : {generations:[]}});
          </script></body></html>`);
        return;
      }
      const entry = files[pathname];
      if (!entry) { response.writeHead(404); response.end(); return; }
      response.writeHead(200, {'Content-Type': entry[1]});
      fs.createReadStream(path.join(root, entry[0])).pipe(response);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    let browser;
    try {
      browser = await playwright.chromium.launch({headless:true});
      for (const viewport of [{width:1280,height:800}, {width:390,height:844}]) {
        const page = await browser.newPage({viewport});
        let releaseVideo;
        const gate = new Promise(resolve => { releaseVideo = resolve; });
        await page.route('**/sample.mp4', async route => {
          await gate;
          await route.continue();
        });
        try {
          await page.goto('http://127.0.0.1:' + server.address().port + '/');
          await page.getByRole('button', {name:/Wide reference/}).click();
          await page.waitForFunction(() => document.querySelector('.cw-video-fallback img')?.naturalWidth > 0);
          const loading = await page.evaluate(() => ({
            logo: document.querySelector('.cw-video-fallback img').getAttribute('src'),
            thumb: document.querySelector('.cw-source img').getAttribute('src'),
            visibility: getComputedStyle(document.querySelector('.cw-preview video')).visibility,
            cover: document.querySelector('.cw-video-fallback').hidden,
            logoWidth: document.querySelector('.cw-video-fallback img').getBoundingClientRect().width,
          }));
          assert.equal(loading.logo, '/spark/asset/pinebox.png');
          assert.equal(loading.thumb, '/spark/asset/pinebox.png');
          assert.equal(loading.visibility, 'hidden');
          assert.equal(loading.cover, false);
          assert.ok(loading.logoWidth >= 70, `logo too small: ${loading.logoWidth}`);
          await page.screenshot({path:path.join(os.tmpdir(), `comfy-workshop-loading-${viewport.width}.png`)});

          const slider = page.getByRole('slider', {name:'Preview size'});
          await slider.focus();
          await slider.press('End');
          assert.equal(await slider.inputValue(), '480');
          const expanded = await page.locator('.cw-preview').evaluate(el => el.getBoundingClientRect().height);
          await slider.press('Home');
          assert.equal(await slider.inputValue(), '160');
          const compact = await page.locator('.cw-preview').evaluate(el => el.getBoundingClientRect().height);
          assert.ok(expanded > compact + 100, `${viewport.width}: ${expanded} vs ${compact}`);

          releaseVideo();
          await page.getByRole('button', {name:'Play preview'}).click();
          await page.waitForFunction(() => document.querySelector('.cw-preview video')?.dataset.ready === 'true');
          const ready = await page.evaluate(() => {
            const stage = document.querySelector('.cw-preview');
            const video = stage.querySelector('video');
            const sr = stage.getBoundingClientRect();
            const vr = video.getBoundingClientRect();
            return {videoWidth:video.videoWidth, videoHeight:video.videoHeight,
              objectFit:getComputedStyle(video).objectFit,
              visibility:getComputedStyle(video).visibility, controls:video.controls,
              muted:video.muted,
              cover:stage.querySelector('.cw-video-fallback').hidden,
              inside:vr.left >= sr.left && vr.right <= sr.right && vr.top >= sr.top && vr.bottom <= sr.bottom,
              stageRight:sr.right};
          });
          assert.ok(ready.videoWidth > 0 && ready.videoHeight > 0);
          assert.equal(ready.objectFit, 'contain');
          assert.equal(ready.visibility, 'visible');
          assert.equal(ready.controls, true);
          assert.equal(ready.muted, false);
          assert.equal(ready.cover, true);
          assert.equal(ready.inside, true);
          assert.ok(ready.stageRight <= viewport.width + 1);
          await page.screenshot({path:path.join(os.tmpdir(), `comfy-workshop-${viewport.width}.png`)});

          await page.getByRole('button', {name:'Pause preview'}).click();
          assert.equal(await page.locator('.cw-preview video').evaluate(el => el.paused), true);
          await page.getByRole('button', {name:/Unavailable reference/}).click();
          const missingPlay = page.getByRole('button', {name:'Play preview'});
          if (await missingPlay.isVisible().catch(() => false)) {
            await missingPlay.click().catch(() => {});
          }
          await page.getByText('Video preview unavailable').waitFor();
          assert.equal(await page.locator('.cw-video-fallback').isVisible(), true);
          if (viewport.width === 390) await page.setViewportSize({width:390,height:500});
          const prompt = page.getByRole('textbox', {name:'Video prompt'});
          await prompt.fill('A quiet station');
          if (viewport.width === 390) {
            assert.equal(await page.locator('.cw-dialog').evaluate(el => el.classList.contains('cw-editing')), true);
            assert.equal(await page.locator('.cw-library').isVisible(), false);
            const bottom = await prompt.evaluate(el => el.getBoundingClientRect().bottom);
            assert.ok(bottom <= 500, `prompt obscured in compact viewport: ${bottom}`);
            await page.screenshot({path:path.join(os.tmpdir(), 'comfy-workshop-editing-390.png')});
          }
          await page.evaluate(() => {
            window.promptNode = document.querySelector('.cw-prompt');
            window.sourceBefore = document.querySelector('.cw-source');
            document.querySelector('.cw-header button').click();
          });
          await page.waitForFunction(() => !window.sourceBefore.isConnected);
          assert.equal(await page.evaluate(() =>
            document.querySelector('.cw-prompt') === window.promptNode &&
            document.activeElement === window.promptNode), true);
          await page.evaluate(() => {
            const host = document.createElement('div');
            document.body.append(host);
            host.append(document.getElementById('comfyWorkshopModal'));
          });
          await page.waitForFunction(() => document.activeElement === window.promptNode);
          await prompt.press('End');
          await page.keyboard.type(' after moving');
          assert.equal(await prompt.inputValue(), 'A quiet station after moving');
          await page.evaluate(() => {
            const field = document.querySelector('.cw-prompt');
            field.value += ' dictated';
            field.dispatchEvent(new Event('input', {bubbles:true}));
            field.focus();
          });
          assert.equal(await prompt.inputValue(), 'A quiet station after moving dictated');
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('#comfyWorkshopModal').count(), 1);
          await page.getByRole('button', {name:'Close'}).focus();
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('#comfyWorkshopModal').count(), 0);
        } finally {
          releaseVideo();
          await page.close();
        }
      }
    } finally {
      if (browser) await browser.close();
      await new Promise(resolve => server.close(resolve));
    }
  });
