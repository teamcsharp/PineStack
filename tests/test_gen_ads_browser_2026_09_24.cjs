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
const mime = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
  '.mp4': 'video/mp4', '.png': 'image/png'};

test('generated ads render real video pixels and fit desktop and mobile', {skip: !playwright}, async () => {
  const server = http.createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const file = pathname === '/spark/asset/pinebox.png'
      ? path.join(root, 'desktop', 'assets', 'pinebox.png')
      : path.resolve(root, '.' + pathname);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {
      response.writeHead(404); response.end(); return;
    }
    response.writeHead(200, {'Content-Type': mime[path.extname(file)] || 'application/octet-stream'});
    fs.createReadStream(file).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await playwright.chromium.launch({headless: true, args: ['--enable-unsafe-swiftshader']});
    const url = 'http://127.0.0.1:' + server.address().port + '/tests/gen-ads-visual.html';
    for (const viewport of [{width: 1280, height: 800}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport, deviceScaleFactor: 1});
      let releaseVideo;
      const videoGate = new Promise((resolve) => { releaseVideo = resolve; });
      let firstVideo = true;
      await page.route('**/tests/gen-ads-visual.mp4', async (route) => {
        if (firstVideo) { firstVideo = false; await videoGate; }
        await route.continue();
      });
      await page.goto(url, {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => {
        const poster = document.querySelector('.pga-poster');
        return poster && poster.complete && poster.naturalWidth > 0;
      });
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.pga-video')).visibility), 'hidden');
      assert.equal(await page.locator('.pga-poster').isVisible(), true);
      releaseVideo();
      await page.waitForFunction(() => window.__pgaRender && window.__pgaRender.pixels.some(
        (pixel) => pixel[0] + pixel[1] + pixel[2] > 60), {timeout: 10000});
      assert.equal(await page.locator('.pga-poster').isVisible(), false);
      const layout = await page.evaluate(() => {
        const box = (selector) => {
          const rect = document.querySelector(selector).getBoundingClientRect();
          return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
            width: rect.width, height: rect.height};
        };
        return {dialog: box('.pga-dialog'), close: box('.pga-header-actions button:last-child'),
          stage: box('.pga-stage'), send: box('.pga-send'),
          pixels: window.__pgaRender.pixels, renders: window.__pgaRender.count};
      });
      assert.ok(layout.dialog.left >= -1 && layout.dialog.right <= viewport.width + 1,
        'dialog outside ' + viewport.width + ': ' + JSON.stringify(layout));
      assert.ok(layout.close.right <= viewport.width && layout.close.left >= 0,
        'close button clipped: ' + JSON.stringify(layout));
      assert.ok(layout.stage.width > 100 && layout.stage.height > 100);
      assert.ok(layout.send.right <= viewport.width && layout.send.left >= 0);
      assert.ok(layout.pixels.some((pixel) => pixel[0] + pixel[1] + pixel[2] > 60));
      await page.screenshot({path: path.join(os.tmpdir(), 'gen-ads-final-' + viewport.width + '.png')});
      if (viewport.width === 1280) {
        assert.ok(layout.pixels[0][0] + layout.pixels[0][1] + layout.pixels[0][2] < 30,
          'wide stage should letterbox the full clip');
        assert.ok(layout.pixels[2][0] + layout.pixels[2][1] + layout.pixels[2][2] > 60);
      }
      await page.getByRole('button', {name: 'Play ad'}).click();
      await page.waitForFunction((before) => window.__pgaRender.count > before + 1, layout.renders);
      assert.deepEqual(await page.evaluate(() => ({broadcast: document.getElementById('broadcast').volume,
        preview: document.querySelector('.pga-video').volume, muted: document.querySelector('.pga-video').muted})),
      {broadcast: 0.1, preview: 1, muted: false});
      await page.getByRole('button', {name: 'Pause ad'}).click();
      await page.waitForFunction(() => document.getElementById('broadcast').volume === 0.8);
      assert.equal(await page.evaluate(() => document.getElementById('broadcast').volume), 0.8);
      const pausedAt = await page.evaluate(() => window.__pgaRender.count);
      await page.getByRole('button', {name: 'Play ad'}).click();
      await page.waitForFunction((before) => window.__pgaRender.count > before, pausedAt);
      await page.locator('.pga-row').nth(1).click();
      await page.waitForFunction(() => document.querySelector('.pga-poster').naturalWidth > 0);
      const fallback = await page.evaluate(() => {
        const poster = document.querySelector('.pga-poster');
        const rect = poster.getBoundingClientRect();
        return {src: poster.src, width: rect.width, height: rect.height,
          native: getComputedStyle(document.querySelector('.pga-video')).visibility};
      });
      assert.match(fallback.src, /\/spark\/asset\/pinebox\.png$/);
      assert.ok(fallback.width <= 128 && Math.abs(fallback.width - fallback.height) < 1);
      assert.equal(fallback.native, 'hidden');
      await page.getByRole('button', {name: 'Close generated ads'}).click();
      const stopped = await page.evaluate(() => ({renders: window.__pgaRender.count,
        disposed: window.__pgaRender.disposed, stillOpen: !!document.querySelector('.pga-dialog')}));
      await page.waitForTimeout(200);
      assert.equal(stopped.stillOpen, false);
      assert.ok(stopped.disposed >= 1);
      assert.equal(await page.evaluate(() => window.__pgaRender.count), stopped.renders);
      assert.equal(await page.evaluate(() => document.getElementById('broadcast').volume), 0.8);
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
