/* [book-scroll] [book-fill] The book reader turns pages on a scroll or a swipe, and can fill the window (2026-10-05).
 *
 * Run with Electron, on local disk:   electron tests/test_book_reader_scroll_2026_10_05.cjs [SHOT_DIR]
 * A hidden, offscreen window and a local fixture station; nothing here reaches the live backend.
 * PINE_BOOK_TEST_ROOT may point at another tree that holds desktop/renderer/book-preview.*.
 */
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), http = require('node:http'), assert = require('node:assert/strict');
const repo = process.env.PINE_BOOK_TEST_ROOT || path.resolve(__dirname, '..');
const shots = process.argv.find((arg, i) => i > 1 && !arg.startsWith('-') && !arg.endsWith('.cjs')) || '';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const requests = [], writes = [];
const PAGES = 9;
function manifest(id) {
  if (id === 'pdf') return { kind: 'pdf', title: 'Nine Original Pages', version: 'v', page_count: PAGES,
    pages: Array.from({ length: PAGES }, (_, index) => ({ index, width: 612, height: 792, url: '/api/books/pdf/preview/page/' + index + '?t=x' })) };
  return { kind: 'epub', title: 'Two Chapters', version: 'v', chapter_count: 2,
    chapters: [0, 1].map(index => ({ index, title: 'Chapter ' + (index + 1), url: '/api/books/epub/preview/chapter/' + index + '?t=x' })) };
}
const chapter = index => '<!DOCTYPE html><html><head><meta charset="utf-8"><title>c</title></head><body><h1>Chapter ' + (index + 1) + '</h1>'
  + Array.from({ length: 36 }, (_, i) => '<p id="p' + i + '">Passage ' + (i + 1) + ' of chapter ' + (index + 1) + '. The readers followed the story across the quiet valley, through every changing season, and the page kept its own measure all the way down.</p>').join('') + '</body></html>';
const page = index => '<svg xmlns="http://www.w3.org/2000/svg" width="612" height="792"><rect width="612" height="792" fill="#fffdf7"/><rect x="40" y="40" width="532" height="712" fill="none" stroke="#75644f" stroke-width="2"/>'
  + '<text x="306" y="400" text-anchor="middle" font-size="120" fill="#345">' + (index + 1) + '</text></svg>';
const server = http.createServer((req, res) => {
  requests.push(req.method + ' ' + req.url);
  if (req.method !== 'GET') writes.push(req.method + ' ' + req.url);
  const url = new URL(req.url, 'http://127.0.0.1'), route = url.pathname, base = 'http://127.0.0.1:' + server.address().port;
  const send = (type, body) => { res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store' }); res.end(body); };
  if (/^\/books\/read\/(?:pdf|epub)$/.test(route)) {
    const id = route.split('/').pop();
    /* the reader runs under the station's own policy for this page (book_mode.py): no inline script, no inline style */
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Security-Policy':
      "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'" });
    return res.end(fs.readFileSync(path.join(repo, 'desktop/renderer/book-preview.html'), 'utf8')
      .replace(/__BOOK_PREVIEW_CONFIG__/g, JSON.stringify({ book: id, title: manifest(id).title, manifestUrl: '/api/books/' + id + '/preview?t=x' }))
      .replace(/__BOOK_PREVIEW_CSS_URL__/g, '/assets/book-preview.css').replace(/__BOOK_PREVIEW_JS_URL__/g, '/assets/book-preview.js'));
  }
  if (/^\/assets\/book-preview\.(?:css|js)$/.test(route)) return send(route.endsWith('.css') ? 'text/css' : 'text/javascript', fs.readFileSync(path.join(repo, 'desktop/renderer', path.basename(route))));
  if (/^\/api\/books\/(?:pdf|epub)\/preview$/.test(route)) return send('application/json', JSON.stringify(manifest(route.split('/')[3])));
  if (/^\/api\/books\/pdf\/preview\/page\/\d+$/.test(route)) return send('image/svg+xml', page(Number(route.split('/').pop())));
  if (/^\/api\/books\/epub\/preview\/chapter\/[01]$/.test(route)) return send('text/html; charset=utf-8', chapter(Number(route.split('/').pop())));
  res.writeHead(404); res.end('no ' + route);
});
app.disableHardwareAcceleration();
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-book-scroll-test-')));
let win;
const failTimer = setTimeout(() => { console.error('book reader scroll test timed out'); app.exit(1); }, 150000);
app.whenReady().then(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  win = new BrowserWindow({ show: false, width: 1300, height: 720, webPreferences: { offscreen: true } });
  const errors = [];
  win.webContents.on('console-message', event => { if (event.level === 'error') errors.push(String(event.message).slice(0, 200)); });
  const run = code => win.webContents.executeJavaScript(code).catch(error => { console.error('the page script failed: ' + String(code).slice(0, 240)); throw error; });
  const state = () => run('PineBookPreview.state()');
  async function until(code, what, timeout = 6000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { if (await run(code)) return; await sleep(30); }
    throw new Error('Timed out: ' + what + ' | state ' + JSON.stringify(await state()));
  }
  async function open(id) {
    await win.loadURL(base + '/books/read/' + id);
    await until('!!window.PineBookPreview', 'the reader'); await run('PineBookPreview.ready'); await until('PineBookPreview.state().pageCount>0', 'its pages');
  }
  /* an offscreen window hands back its last painted frame: give the page a moment to paint the state being pictured */
  const shot = async name => { if (shots) { await sleep(450); fs.mkdirSync(shots, { recursive: true }); fs.writeFileSync(path.join(shots, name + '.png'), (await win.webContents.capturePage()).toPNG()); } };
  /* a wheel push as the page sees it: down is positive. Returns whether the reader kept it for itself. */
  const push = (deltaY, deltaX = 0, where = `document.querySelector('.bp-stage')`) =>
    run(`(()=>{const e=new WheelEvent('wheel',{deltaY:${deltaY},deltaX:${deltaX},bubbles:true,cancelable:true});(${where}).dispatchEvent(e);return e.defaultPrevented;})()`);
  const swipe = (dx, dy, where = `document.querySelector('.bp-stage')`) =>
    run(`(()=>{const el=(${where}),a=new Event('touchstart',{bubbles:true}),b=new Event('touchend',{bubbles:true});Object.defineProperty(a,'touches',{value:[{clientX:600,clientY:360}]});
      Object.defineProperty(b,'changedTouches',{value:[{clientX:600+(${dx}),clientY:360+(${dy})}]});el.dispatchEvent(a);el.dispatchEvent(b);})()`);
  const geometry = () => run(`(()=>{const s=document.querySelector('.bp-stage'),p=document.querySelector('.bp-spread').getBoundingClientRect();
    return {stageW:s.clientWidth,stageH:s.clientHeight,scrollH:s.scrollHeight,scrollTop:Math.round(s.scrollTop),spreadW:Math.round(p.width),spreadH:Math.round(p.height),
      slots:document.querySelectorAll('.bp-pdf-page').length,zoom:document.getElementById('bp-zoom').value,sources:[...document.querySelectorAll('.bp-pdf-page img')].map(i=>(i.getAttribute('src')||'').replace(/^.*page\\/(\\d+).*$/,'$1'))};})()`);

  /* ---- 1. a scroll turns the pages, and one push is one turn ---- */
  await open('pdf');
  assert.deepEqual({ fit: (await state()).fit, zoom: (await state()).zoom, page: (await state()).pageIndex }, { fit: '', zoom: 100, page: 0 }, 'it opens as it always did');
  const fitted = await geometry();
  assert.equal(fitted.slots, 2); assert.ok(fitted.scrollH <= fitted.stageH + 1, 'both pages whole in the window');
  assert.equal(await push(120), true, 'the reader takes the push');
  await until('PineBookPreview.state().pageIndex===2', 'a push down is the next two pages');
  assert.deepEqual((await geometry()).sources, ['2', '3']);
  await push(120); await push(120); await sleep(120);
  assert.equal((await state()).pageIndex, 2, 'the rest of the same push does not turn again');
  await sleep(220);
  await push(120); await until('PineBookPreview.state().pageIndex===4', 'a new push turns again');
  await sleep(220); await push(-120); await until('PineBookPreview.state().pageIndex===2', 'a push up is the two before');
  await sleep(220); await push(0, 140); await until('PineBookPreview.state().pageIndex===4', 'a sideways push turns too');
  /* a trackpad: many small movements make one turn */
  await sleep(220);
  for (let n = 0; n < 5; n++) { await push(20); await sleep(16); }
  await until('PineBookPreview.state().pageIndex===6', 'small movements add up to a turn');
  for (let n = 0; n < 12; n++) { await push(14); await sleep(16); }
  assert.equal((await state()).pageIndex, 6, 'and the glide after it does not turn another');
  /* the real wheel, through the window's own input */
  await sleep(300);
  const box = await run(`(()=>{const r=document.querySelector('.bp-stage').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`);
  win.webContents.sendInputEvent({ type: 'mouseMove', x: box.x, y: box.y });
  win.webContents.sendInputEvent({ type: 'mouseWheel', x: box.x, y: box.y, deltaX: 0, deltaY: -120, canScroll: true });
  await until('PineBookPreview.state().pageIndex===8', 'a real wheel notch reaches the reader');
  /* the last page is the last page */
  await sleep(700); await push(120); await sleep(150);
  assert.equal((await state()).pageIndex, 8); assert.equal(await run(`document.getElementById('bp-next').disabled`), true);
  await shot('reader-1-last-spread');

  /* ---- 2. a finger ---- */
  await swipe(120, 5); await until('PineBookPreview.state().pageIndex===6', 'a swipe to the right is the two before');
  await swipe(-120, -8); await until('PineBookPreview.state().pageIndex===8', 'a swipe to the left is the next two');
  await swipe(0, 120); await until('PineBookPreview.state().pageIndex===6', 'a swipe down, with the page at its head, turns back');
  await swipe(20, 10); await sleep(120); assert.equal((await state()).pageIndex, 6, 'a touch is not a swipe');

  /* ---- 3. the keys ---- */
  await run(`document.querySelector('.bp-stage').dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true,cancelable:true}))`);
  await until('PineBookPreview.state().pageIndex===0', 'Home is the first page');
  await run(`document.querySelector('.bp-stage').dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}))`);
  await until('PineBookPreview.state().pageIndex===8', 'End is the last');
  await run(`document.querySelector('.bp-stage').dispatchEvent(new KeyboardEvent('keydown',{key:' ',shiftKey:true,bubbles:true,cancelable:true}))`);
  await until('PineBookPreview.state().pageIndex===6', 'Shift+Space reads back');
  await run(`PineBookPreview.goToPage(1)`);
  await run(`document.querySelector('.bp-stage').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}))`);
  await until('PineBookPreview.state().pageIndex===2', 'the arrows still turn'); await run(`PineBookPreview.goToPage(1)`);

  /* ---- 4. fit width: the pages take the window, the page scrolls, and the scroll runs on into the next pages ---- */
  await run(`(()=>{const z=document.getElementById('bp-zoom');z.value='width';z.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await until(`PineBookPreview.state().fit==='width'`, 'fit width');
  const wide = await geometry();
  assert.equal(wide.zoom, 'width'); assert.equal(wide.slots, 2, 'still exactly two facing pages');
  assert.ok(Math.abs(wide.spreadW - (wide.stageW - 28)) <= 2, 'the pages take the whole width: ' + JSON.stringify(wide));
  assert.ok(wide.spreadW > fitted.spreadW * 1.3, 'and are larger than the whole-page fit'); assert.ok(wide.scrollH > wide.stageH + 50, 'so the page scrolls');
  assert.ok((await state()).zoom > 100);
  await shot('reader-2-fit-width');
  assert.equal(await push(120), false, 'while the page has more to show, the scroll is the page\'s own');
  assert.equal((await state()).pageIndex, 0);
  await run(`(()=>{const s=document.querySelector('.bp-stage');s.scrollTop=s.scrollHeight;})()`);
  assert.equal(await push(120), true); await sleep(120);
  assert.equal((await state()).pageIndex, 0, 'arriving at the foot of the page is not yet a request for the next');
  await sleep(520);
  await push(120); await until('PineBookPreview.state().pageIndex===2', 'a push past the foot is the next two pages');
  assert.equal((await geometry()).scrollTop, 0, 'which start at their head');
  await sleep(700);
  await push(-120); await until('PineBookPreview.state().pageIndex===0', 'and a push past the head goes back');
  const back = await geometry();
  assert.ok(back.scrollTop + back.stageH >= back.scrollH - 3, 'to the foot of the pages before: ' + JSON.stringify(back));
  win.setSize(1000, 640); await sleep(350);
  const resized = await geometry();
  assert.ok(Math.abs(resized.spreadW - (resized.stageW - 28)) <= 2, 'the fit follows the window: ' + JSON.stringify(resized));
  win.setSize(1300, 720); await sleep(350);

  /* ---- 5. the fit is remembered; a zoom step is not; a double click swaps the two fits ---- */
  await open('pdf');
  assert.equal((await state()).fit, 'width', 'the next book opens the way this one was left'); assert.equal((await geometry()).zoom, 'width');
  await run(`document.querySelector('.bp-spread').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);
  await until(`PineBookPreview.state().fit===''&&PineBookPreview.state().zoom===100`, 'a double click goes back to the whole page');
  assert.ok((await geometry()).scrollH <= (await geometry()).stageH + 1);
  await run(`PineBookPreview.setZoom(150)`); await open('pdf');
  assert.deepEqual({ fit: (await state()).fit, zoom: (await state()).zoom }, { fit: '', zoom: 100 }, 'a zoom step belongs to the book that was open');
  await run(`document.querySelector('.bp-spread').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);
  await until(`PineBookPreview.state().fit==='width'`, 'and a double click fills the window');

  /* ---- 6. a reflowed book: the wheel turns its pages from inside the page, and on into the next chapter ---- */
  await open('epub');
  const inside = `document.getElementById('bp-epub').contentDocument.body`;
  const frameWide = await run(`document.getElementById('bp-epub').getBoundingClientRect().width`);
  const stageWide = await run(`document.querySelector('.bp-stage').clientWidth`);
  assert.ok(frameWide > stageWide * .8, 'at fit width its two pages spread across the window: ' + frameWide + ' of ' + stageWide);
  await shot('reader-3-epub-fit-width');
  assert.equal(await push(120, 0, inside), true); await until('PineBookPreview.state().pageIndex===2', 'a push inside the page turns it');
  let turns = 0;
  while ((await state()).chapterIndex === 0 && turns++ < 60) { await sleep(700); const before = (await state()).pageIndex; await push(120, 0, inside); await sleep(120);
    if ((await state()).chapterIndex === 0) assert.ok((await state()).pageIndex >= before); }
  await until(`PineBookPreview.state().chapterIndex===1&&PineBookPreview.state().pageIndex===0&&PineBookPreview.state().pageCount>0`, 'the scroll runs on into the next chapter');
  assert.match(await run(`document.getElementById('bp-epub').contentDocument.querySelector('h1').textContent`), /Chapter 2/);
  await sleep(800);
  await push(-120, 0, `document.getElementById('bp-epub').contentDocument.body`);
  await until(`PineBookPreview.state().chapterIndex===0&&PineBookPreview.state().pageIndex>0`, 'and back to the end of the chapter before');
  const last = await state();
  assert.equal(last.pageIndex, 2 * (last.spreadCount - 1), 'at its last two pages');
  await swipe(-120, 0, `document.getElementById('bp-epub').contentDocument.body`);
  await until(`PineBookPreview.state().chapterIndex===1`, 'a swipe inside the page crosses chapters too');
  await run(`PineBookPreview.setZoom(100)`);
  assert.equal((await state()).fit, '');

  assert.deepEqual(writes, [], 'turning pages never writes to the station');
  assert.deepEqual(errors.filter(line => !/Electron Security Warning|favicon/.test(line)), [], 'no errors in the reader');
  clearTimeout(failTimer);
  console.log('Book reader: scroll, trackpad, real wheel, swipe and keys turn the pages; fit width fills the window and scrolls on into the next pages; the fit is remembered; a reflowed book turns across chapters - passed.');
  win.destroy(); server.close(); app.quit();
}).catch(error => { console.error(error); clearTimeout(failTimer); if (win && !win.isDestroyed()) win.destroy(); server.close(); app.exit(1); });
