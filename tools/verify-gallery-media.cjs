const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const key = process.env.PINE_API_KEY;
  const base = (process.env.PINE_URL || 'http://10.89.1.246:8096').replace(/\/$/, '');
  const chromium = process.env.CHROMIUM_PATH;
  const playwright = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
  if (!key || !chromium) throw new Error('PINE_API_KEY and CHROMIUM_PATH are required');
  const headers = {Authorization: 'Bearer ' + key};
  const listing = await fetch(base + '/api/generations?limit=200', {headers});
  if (!listing.ok) throw new Error('Generation list HTTP ' + listing.status);
  const rows = (await listing.json()).generations || [];
  let chosen;
  for (const row of rows) {
    if (!row.prompt_id || !(row.files || []).some((file) => /\.mp4$/i.test(file))) continue;
    const result = await fetch(base + '/api/comfy/workshop/reference/'
      + encodeURIComponent(row.prompt_id), {headers});
    if (!result.ok) continue;
    const reference = await result.json();
    if (reference.available && reference.kind === 'video') {
      chosen = {row, reference, file: row.files.find((file) => /\.mp4$/i.test(file))};
      break;
    }
  }
  if (!chosen) throw new Error('No generated/reference video pair is available');
  const browser = await playwright.chromium.launch({headless: true, executablePath: chromium,
    args: ['--autoplay-policy=no-user-gesture-required']});
  const output = process.env.PINE_SCREENSHOT_DIR || 'C:/_tools/pinebox-validation';
  fs.mkdirSync(output, {recursive: true});
  const results = [];
  try {
    for (const viewport of [{width: 1366, height: 768}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport});
      await page.goto(base + '/', {waitUntil: 'domcontentloaded', timeout: 45000});
      await page.evaluate((secret) => {
        document.getElementById('apiKey').value = secret;
        localStorage.setItem('sparkAgentKey', secret);
      }, key);
      await page.evaluate(({file, row}) => showLightbox(file, row), chosen);
      await page.waitForFunction(() => {
        const original = document.getElementById('lightboxRefVid');
        const generated = document.getElementById('lightboxVid');
        return !document.getElementById('lbReferencePane').hidden
          && original.videoWidth > 0 && generated.videoWidth > 0;
      }, null, {timeout: 60000});
      const before = await page.evaluate(() => {
        const a = document.getElementById('lightboxRefVid');
        const b = document.getElementById('lightboxVid');
        return {original: {width: a.videoWidth, height: a.videoHeight, poster: a.poster,
          cover: document.querySelector('#lbReferenceCover img').src},
        generated: {width: b.videoWidth, height: b.videoHeight, poster: b.poster,
          cover: document.querySelector('#lbGeneratedCover img').src},
        panes: [...document.querySelectorAll('.lb-pane')].map((node) => {
          const rect = node.getBoundingClientRect();
          return {width: rect.width, height: rect.height, left: rect.left};
        })};
      });
      const label = viewport.width > 600 ? 'desktop' : 'mobile';
      const screenshot = path.join(output, 'gallery-' + label + '.png');
      await page.screenshot({path: screenshot, fullPage: false});
      await page.locator('#lbPlayBoth').click();
      await page.waitForFunction(() =>
        document.getElementById('lightboxRefVid').currentTime > 0.25
        && document.getElementById('lightboxVid').currentTime > 0.25,
      null, {timeout: 20000});
      const after = await page.evaluate(() => ({
        original_s: document.getElementById('lightboxRefVid').currentTime,
        generated_s: document.getElementById('lightboxVid').currentTime
      }));
      let editor = null;
      {
        const editReplies = [];
        page.on('response', (response) => {
          if (response.url().includes('/api/video-editor/parody/open'))
            editReplies.push(response.status());
        });
        const [popup] = await Promise.all([
          page.waitForEvent('popup', {timeout: 20000}),
          page.locator('#lbParodyEdit').click()
        ]);
        try {
          await popup.waitForURL(/\/video-editor\//, {timeout: 45000});
        } catch (error) {
          const status = await page.locator('#status').textContent();
          throw new Error('Edit popup failed: ' + status + ' (responses '
            + editReplies.join(',') + '): ' + error.message);
        }
        await popup.waitForFunction(() => {
          const a = document.getElementById('parodyOriginalVideo');
          const b = document.getElementById('parodyGeneratedVideo');
          return a && b && a.videoWidth > 0 && b.videoWidth > 0;
        }, null, {timeout: 90000});
        const editorScreenshot = path.join(output, 'parody-editor-' + label + '.png');
        await popup.screenshot({path: editorScreenshot, fullPage: false});
        editor = await popup.evaluate(() => ({
          originalWidth: document.getElementById('parodyOriginalVideo').videoWidth,
          generatedWidth: document.getElementById('parodyGeneratedVideo').videoWidth
        }));
        async function playSource(videoId, coverId, buttonId) {
          if (await popup.locator(coverId).isVisible()) {
            await popup.locator(buttonId).click();
          } else {
            const video = popup.locator(videoId);
            const box = await video.boundingBox();
            await video.click({position: {x: 24, y: box.height - 48}});
          }
        }
        await playSource('#parodyOriginalVideo', '#parodyOriginalCover', '#parodyPlayOriginal');
        await popup.waitForFunction(() =>
          document.getElementById('parodyOriginalVideo').currentTime > 0.2,
        null, {timeout: 20000});
        editor.originalPlayed = true;
        await popup.evaluate(() => document.getElementById('parodyOriginalVideo').pause());
        await playSource('#parodyGeneratedVideo', '#parodyGeneratedCover', '#parodyPlayGenerated');
        await popup.waitForFunction(() =>
          document.getElementById('parodyGeneratedVideo').currentTime > 0.2,
        null, {timeout: 20000});
        editor.generatedPlayed = true;
        editor.screenshot = editorScreenshot;
        await popup.close();
      }
      await page.evaluate(() => closeLightbox());
      await page.evaluate(() => genAdsOpen());
      await page.waitForSelector('.pga-row', {timeout: 30000});
      await page.waitForSelector('.pga-stage canvas', {timeout: 30000});
      const adScreenshot = path.join(output, 'gen-ads-' + label + '.png');
      await page.screenshot({path: adScreenshot, fullPage: false});
      await page.getByRole('button', {name: 'Play ad'}).click();
      await page.waitForFunction(() => document.querySelector('.pga-video').currentTime > 0.2,
        null, {timeout: 20000});
      const ad = await page.evaluate(() => ({
        count: document.querySelectorAll('.pga-row').length,
        videoWidth: document.querySelector('.pga-video').videoWidth,
        canvasWidth: document.querySelector('.pga-stage canvas').width,
        playing: !document.querySelector('.pga-video').paused
      }));
      results.push({viewport, before, after, screenshot, editor, ad, adScreenshot});
      await page.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({file: chosen.file, reference: chosen.reference.name,
    results}, null, 2) + '\n');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
