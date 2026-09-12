/* #1052: one optional LCD canvas producer. It keeps running when its panel
 * closes, and never queues a frame behind another frame. No CDN required. */
(() => {
  const bridge = window.pineDesktop;
  const entry = document.getElementById('lcdBtn');
  if (!entry || !bridge?.lcdState) return;
  let state = null, panel = null, timer = null, autoRetry = null, looping = false, running = false;
  let station = {}, editions = [], edition = null, latestPaper = '', manualEdition = false;
  let paperLines = [], paperHeight = 1, scroll = 0, lastFrame = 0, lastPoll = 0;
  let drawer = false, inputTimer = null, inputPolling = false;
  let pointerStart = null, suppressClickUntil = 0;
  // The cupboard view (paused): every stored round, the desk and the grader.
  let cupboard = null, cupboardLines = [], cupboardHeight = 1, cupboardScroll = 0, lastCupboard = 0;
  let selected = null, hitRows = [], localMessage = '', messageUntil = 0;
  let editionRequest = 0, actionBusy = false, polling = false;
  let stationSkew = 0;
  let currentId = '', currentBegan = 0;
  // 2026-09-08: the last spoken line is held this long after it ends, then
  // the screen goes idle - it never falls back to the feed.
  const LCD_HOLD_MS = 6000;
  let heldRow = null, heldUntil = 0, heldPan = 0, selectedBegan = 0, selectedId = '';
  const rows = new Map(), liked = new Set();
  const paperImages = new Map();
  const wrapCache = new Map(), paperTiles = new Map();
  const controls = window.PineLcdControls;
  const gallery = window.PineLcdGallery?.create({get: route => bridge.get(route), loadImage: url => bridge.lcdPaperImage(url)});
  let galleryFrame = null, lastGalleryAckKey = '', lastGalleryAckAt = 0;
  const canvas = document.createElement('canvas');
  canvas.width = 320; canvas.height = 240;
  canvas.style.cssText = 'width:100%;height:auto;max-height:55vh;object-fit:contain;background:#07121b;image-rendering:auto';
  // Every delivered frame is read back for JPEG encoding. Prefer a CPU canvas
  // to avoid waiting for GPU synchronization on each export in the normal app.
  const ctx = canvas.getContext('2d', {alpha: false, willReadFrequently: true});
  const node = (tag, text = '') => { const el = document.createElement(tag); el.textContent = text; return el; };
  const note = (text) => { localMessage = String(text); messageUntil = Date.now() + 6500; paintStatus(); };
  const review = window.PineLcdReview?.create({get: route => bridge.get(route),post: (route,body) => bridge.post(route,body),
    onChange: () => { lastGalleryAckKey = ''; paintStatus(); },
    onClose: () => { selected = null; lastFrame = 0; paintStatus(); }});
  window.PineLcdReviewController = review;
  window.PineLcdReviewHits = [];
  const fontSize = () => Math.max(12, Math.round(canvas.width / 30));
  const headerHeight = () => controls.corner(canvas.width, canvas.height).h;
  const plain = (text) => String(text || '').replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*_`#]/g, '').trim();
  const color = (who) => ({dj: '#9de3ef', cohost: '#ffcf8a', third: '#d4b7ff', caller: '#aceda8', caller2: '#fad0e7'}[who] || '#cbe1ee');

  function wrap(text, width, font) {
    const key = width + '\n' + font + '\n' + text;
    if (wrapCache.has(key)) return wrapCache.get(key);
    ctx.font = font;
    const out = []; let line = '';
    for (const word of String(text || '').split(/\s+/)) {
      if (!word) continue;
      const next = line ? line + ' ' + word : word;
      if (line && ctx.measureText(next).width > width) { out.push(line); line = word; }
      else line = next;
    }
    if (line) out.push(line);
    wrapCache.set(key, out);
    while (wrapCache.size > 800) wrapCache.delete(wrapCache.keys().next().value);
    return out;
  }

  function layoutPaper(reset = false) {
    paperTiles.clear();
    paperLines = []; const size = fontSize(); let y = size * 2;
    const tabloid = state?.config?.paperStyle === 'tabloid';
    const add = (text, title = false) => {
      const font = (title ? 'bold ' : '') + (title ? size * (tabloid ? 1.6 : 1.25) : size) + (tabloid && title ? 'px sans-serif' : 'px Georgia');
      const height = size * (title ? (tabloid ? 1.9 : 1.6) : 1.4);
      for (const line of wrap(plain(text), canvas.width - 24, font)) {
        paperLines.push({text: line, y, font, height, title}); y += height;
      }
      y += size;
    };
    add(tabloid ? 'THE PINE BOX TABLOID' : edition?.masthead || 'The Pine Box Gazette', true);
    if (!edition) add('The next newspaper will appear here when it is published.');
    for (const article of (edition?.articles || [])) {
      if (tabloid && (article.meta?.flash || article.meta?.kicker)) add(String(article.meta.flash || article.meta.kicker).toUpperCase(), true);
      add(article.meta?.headline || article.headline || '', true);
      if (article.meta?.deck) add(article.meta.deck);
      for (const url of [...new Set([article.meta?.image, ...(article.meta?.images || []).map((row) => row.url)])].filter(Boolean).slice(0, 2)) {
        const picture = paperImages.get(url);
        if (picture) { const height = Math.min(canvas.height, (canvas.width - 24) * picture.height / picture.width); paperLines.push({image: picture, y, height}); y += height + size; }
      }
      for (const paragraph of String(article.body || '').split(/\n\s*\n/)) {
        if (paragraph.trim()) add(paragraph);
      }
    }
    paperHeight = Math.max(canvas.height, y + canvas.height * 0.3);
    scroll = reset ? 0 : scroll % paperHeight;
  }

  // Cache short paper segments. Scrolling copies tiles instead of rasterizing
  // every visible glyph; eight tiles bound host memory even for long editions.
  function paperTile(index, overlay) {
    const tileHeight = 384, key = index + ':' + overlay;
    if (paperTiles.has(key)) return paperTiles.get(key);
    const tile = document.createElement('canvas'); tile.width = canvas.width; tile.height = tileHeight;
    const ink = tile.getContext('2d', {alpha: false, willReadFrequently: true});
    const tabloid = state?.config?.paperStyle === 'tabloid';
    ink.fillStyle = overlay ? '#07121b' : '#efe6cf'; ink.fillRect(0, 0, tile.width, tile.height);
    for (const row of paperLines) {
      const y = row.y - index * tileHeight;
      if (y < -row.height || y > tileHeight + row.height) continue;
      if (row.image) { ink.globalAlpha = overlay ? .35 : 1; ink.drawImage(row.image, 12, y, tile.width - 24, row.height); ink.globalAlpha = 1; }
      else { ink.font = row.font; ink.fillStyle = overlay ? row.title ? '#82969d' : '#4f6672' : tabloid && row.title ? '#a22222' : '#211e19'; ink.fillText(row.text, 12, y); }
    }
    paperTiles.set(key, tile);
    while (paperTiles.size > 8) paperTiles.delete(paperTiles.keys().next().value);
    return tile;
  }

  function drawPaper(dt, width, height, overlay) {
    if (state?.config?.scrollEnabled !== false && !drawer && !selected) scroll = (scroll + dt * (state?.config?.speed || 12)) % paperHeight;
    const header = headerHeight();
    ctx.save(); ctx.beginPath(); ctx.rect(0, header, width, height - header); ctx.clip();
    for (const base of [header + 6 - scroll, paperHeight + header + 6 - scroll]) {
      const first = Math.max(0, Math.floor((header - base) / 384));
      const last = Math.min(Math.ceil(paperHeight / 384) - 1, Math.floor((height - base) / 384));
      for (let index = first; index <= last; index++) {
        const tile = paperTile(index, overlay), count = Math.min(384, paperHeight - index * 384);
        ctx.drawImage(tile, 0, 0, width, count, 0, base + index * 384, width, count);
      }
    }
    ctx.restore();
  }

  function layoutCupboard() {
    cupboardLines = []; let y = 0; const size = fontSize();
    const add = (text, kind = 'body', tone = '', reviewRef = null) => {
      const font = (kind === 'title' ? 'bold ' : '') + (kind === 'title' ? size * 1.15 : kind === 'small' ? size * 0.85 : size) + 'px sans-serif';
      const height = size * (kind === 'title' ? 1.55 : kind === 'small' ? 1.2 : 1.35);
      for (const line of wrap(plain(text), canvas.width - 24, font)) {
        cupboardLines.push({text: line, y, font, height, kind, tone, reviewRef}); y += height;
      }
    };
    const c = cupboard || {};
    const t = c.tint || {}, cov = t.coverage || {}, w = c.writers || {}, prep = c.preparing || {};
    add('PAUSED · THE CUPBOARD', 'title', 'head');
    add('Crystal ' + ((t.crystals || []).join(', ') || 'off') + ' · hold ' + (t.hold ? 'on' : 'off') + ' · grade ' + (t.grade || '?')
      + ' · this hour ' + (cov.tinted || 0) + ' bars passed, ' + (cov.refused || 0) + ' refused, ' + (cov.rounds || 0) + ' rounds', 'small', 'dim');
    const jobs = (w.jobs || []).map((j) => (j.purpose || '').replace('station:', '') + ' ' + Math.round(j.seconds || 0) + 's').join(' · ');
    add('Desk: ' + (w.active || 0) + ' writing, ' + (w.waiting || 0) + ' waiting' + (jobs ? ' · ' + jobs : ''), 'small', 'dim');
    if (prep.kind) add('Recording room: ' + prep.kind + ' · ' + (prep.stage || '') + (prep.made != null ? ' · ' + prep.made + '/' + (prep.lines || '?') + ' lines' : ''), 'small', 'dim');
    if (c.recovery?.why) add('Repair: ' + c.recovery.why, 'small', 'dim');
    y += size * 0.6;
    add('THE GRADER · last verdicts', 'title', 'head');
    for (const j of (c.judgements || []).slice().reverse().slice(0, 8)) {
      add((j.ok ? '✓ ' : '✗ ') + (j.candidate || ''), 'body', j.ok ? 'ok' : 'no');
      if (!j.ok && (j.faults || []).length) add('   ' + j.faults.join('; '), 'small', 'dim');
    }
    y += size * 0.6;
    // 2026-09-08: a life timer on every round, its airings, and whether it
    // waits on the retirement desk.
    const lifeText = (sec) => { sec = Math.max(0, Math.round(Number(sec) || 0));
      return sec >= 172800 ? Math.floor(sec / 86400) + 'd ' + Math.floor((sec % 86400) / 3600) + 'h'
        : sec >= 3600 ? Math.floor(sec / 3600) + 'h ' + Math.floor((sec % 3600) / 60) + 'm' : Math.floor(sec / 60) + 'm'; };
    const waiting = (c.rounds || []).filter((r) => r.retire === 'pending').length;
    add('THE CUPBOARD · ' + (c.rounds || []).length + ' rounds' + (waiting ? ' · ' + waiting + ' WAIT FOR YOUR DECISION' : ''), 'title', 'head');
    for (const r of (c.rounds || [])) {
      add((r.kind || '').toUpperCase() + (r.label ? ' · ' + r.label : '') + ' · ' + (r.state || '') + ' · audio ' + (r.audio || '') + (r.cut ? ' · cut ' + r.cut : '') + ' · ' + (r.grade || '')
        + (r.life_left != null ? ' · ⏳ ' + lifeText(r.life_left) : '') + (r.innings > 1 ? ' · ' + (r.aired || 0) + '/' + r.innings + ' airings' : ''), 'body', 'head');
      if (r.retire === 'pending') add('   ⏳ waits on the retirement desk - decide on the panel (⏳) or /cupboard/retire', 'small', 'no');
      for (const l of (r.lines || [])) add((l.mark === 'cut' ? 'CUT · ' : l.rhyme ? '♪ ' : '· ') + (l.who || '') + ': ' + (l.text || ''),
        'body', l.mark === 'cut' ? 'no' : l.rhyme ? 'ok' : 'dim', l.mark === 'cut' ? l : null);
      y += size * 0.4;
    }
    y += size * 0.6;
    add('THE DESK · what just happened', 'title', 'head');
    for (const f of (c.feed || []).slice().reverse().slice(0, 20)) add('[' + (f.kind || '') + '] ' + (f.text || ''), 'small', 'dim');
    cupboardHeight = Math.max(canvas.height, y + canvas.height * 0.3);
    if (cupboardScroll > cupboardHeight) cupboardScroll = 0;
  }

  function drawCupboard(dt, width, height, size) {
    ctx.fillStyle = '#07121b'; ctx.fillRect(0, 0, width, height);
    if (state?.config?.scrollEnabled !== false && !drawer) cupboardScroll = (cupboardScroll + dt * (state?.config?.speed || 12)) % cupboardHeight;
    const header = headerHeight();
    ctx.save(); ctx.beginPath(); ctx.rect(0, header, width, height - header); ctx.clip();
    for (const base of [-cupboardScroll + header + size + 4, cupboardHeight - cupboardScroll + header + size + 4]) {
      for (const row of cupboardLines) {
        const y = base + row.y;
        if (y < -row.height || y > height + row.height) continue;
        ctx.font = row.font;
        ctx.fillStyle = row.tone === 'head' ? '#9de3ef' : row.tone === 'ok' ? '#d9f7c8' : row.tone === 'no' ? '#ffb3a7' : '#8ea6b3';
        ctx.fillText(row.text, 12, y);
        if (row.reviewRef && y > header && y-row.height < height-16) {
          const hit = {row:row.reviewRef,x1:8,x2:width-8,y1:Math.max(header,y-row.height+2),y2:Math.min(height-16,y+3),review:true};
          hitRows.push(hit);
          window.PineLcdReviewHits.push({review_id:row.reviewRef.review_id || '',review_seq:row.reviewRef.review_seq || 0,
            x1:hit.x1,x2:hit.x2,y1:hit.y1,y2:hit.y2});
        }
      }
    }
    ctx.restore();
    drawHeader('PAUSED · THE CUPBOARD', 'Behind the scenes');
    ctx.fillStyle = '#87a2b2'; ctx.font = Math.max(9, size - 2) + 'px sans-serif';
    ctx.fillText(running ? 'Pine Box LCD · unpause to return to the show' : 'Preview · LCD not streaming', 10, height - 5);
  }

  async function showEdition(id) {
    if (!id || edition?.id === id) return;
    const request = ++editionRequest;
    const loaded = await bridge.get('/api/paper/' + encodeURIComponent(id));
    if (request !== editionRequest) return;
    edition = {...loaded, id}; layoutPaper(true);
    note('Newspaper ' + id);
    if (bridge.lcdPaperImage) {
      const urls = [...new Set((edition.articles || []).flatMap((article) => [article.meta?.image, ...(article.meta?.images || []).map((row) => row.url)]))].filter(Boolean).slice(0, 24);
      Promise.allSettled(urls.map(async (url) => {
        if (paperImages.has(url)) return;
        const data = await bridge.lcdPaperImage(url); const picture = new Image();
        await new Promise((resolve, reject) => { picture.onload = resolve; picture.onerror = reject; picture.src = data; });
        const width = Math.min(canvas.width, picture.width);
        const bitmap = await createImageBitmap(picture, {resizeWidth: width, resizeHeight: Math.max(1, Math.round(width * picture.height / picture.width))});
        paperImages.set(url, bitmap);
      })).then(() => { if (request === editionRequest) layoutPaper(); while (paperImages.size > 36) paperImages.delete(paperImages.keys().next().value); });
    }
  }
  async function stepEdition(delta) {
    if (!editions.length) { note('No newspaper editions yet.'); return; }
    const current = Math.max(0, editions.findIndex((row) => row.id === edition?.id));
    // Shelf is newest first. Right moves towards newer, left towards older.
    const index = (current - delta + editions.length) % editions.length;
    manualEdition = true; selected = null;
    await showEdition(editions[index].id);
  }

  async function pollStation() {
    const [djResult, shelfResult, deviceResult] = await Promise.allSettled([
      bridge.get('/api/dj'), bridge.get('/api/paper'), bridge.lcdState()]);
    if (djResult.status === 'fulfilled') {
      station = djResult.value || {};
      stationSkew = Number(station.server_ms || Date.now()) - Date.now();
      if ((station.paused || state?.config?.mode === 'cupboard') && Date.now() - lastCupboard > 2500) {
        lastCupboard = Date.now();
        bridge.get('/api/cupboard').then((got) => { cupboard = got || null; layoutCupboard(); }).catch(() => {});
      }
    }
    if (deviceResult.status === 'fulfilled') {
      state = deviceResult.value; running = state.running;
      if (state.device && (canvas.width !== state.device.width || canvas.height !== state.device.height)) {
        canvas.width = state.device.width; canvas.height = state.device.height; layoutPaper(); layoutCupboard();
      }
    }
    if (shelfResult.status === 'fulfilled') {
      const shelf = shelfResult.value || {};
      editions = shelf.editions || [];
      const newId = String(shelf.latest || editions[0]?.id || '');
      if (newId !== latestPaper) {
        latestPaper = newId;
        if (!manualEdition || !edition) await showEdition(newId);
      }
    }
    if (djResult.status === 'rejected') note('Station connection unavailable: ' + djResult.reason.message);
    syncOptions(); paintStatus();
  }

  function paintStatus() {
    if (!panel) return;
    const link = panel.querySelector('[data-lcd-status]');
    const dev = state?.device;
    link.textContent = localMessage && Date.now() < messageUntil ? localMessage
      : state?.error ? state.error
      : running && state?.device?.screensaver ? 'Avatar screensaver · tap anywhere on the LCD to wake'
      : running && state?.device?.displayMode === 'avatar' ? 'Quanta avatar slideshow · tap top-left or swipe down for Pine Box'
      : running && state?.lastAck ? 'Streaming · ' + state.frames + ' drawn frames · last acknowledgment '
        + Math.max(0, Math.round((Date.now() - state.lastAck) / 1000)) + 's ago'
      : state?.connected ? 'Connected · ready to stream' : 'Disconnected · enter a display address or discover Quanta';
    panel.querySelector('[data-lcd-board]').textContent = dev
      ? dev.board + ' · ' + dev.width + '×' + dev.height + ' · firmware ' + dev.version + ' · ' + dev.identity : 'No display identified';
    const log = panel.querySelector('[data-lcd-log]');
    log.textContent = (state?.log || []).slice(-18).map((row) => new Date(row.at).toLocaleTimeString()
      + ' ' + row.kind + ': ' + row.detail).join('\n');
    const detail = panel.querySelector('[data-lcd-detail]');
    detail.textContent = state?.config?.mode === 'gallery' ? 'Pine Box gallery pictures only, with shuffled images and randomized transitions. Tap the right side for the next image, or swipe down to change the view.'
      : selected ? (selected.name || selected.who || 'Booth') + ': ' + selected.text
      : 'Tap a visible dialogue bubble to select it. Tap the left/right screen edges for older/newer issues.';
    for (const button of panel.querySelectorAll('[data-lcd-paper-action]')) button.hidden = state?.config?.mode === 'gallery';
    const hint = panel.querySelector('[data-lcd-hint]');
    if (hint) hint.textContent = state?.config?.mode === 'gallery'
      ? 'Swipe down for Newspaper only or Pine gallery. AV / PB switches to Quanta avatars and back. Close this panel to keep the slideshow running.'
      : 'Tap the AV / PB button in the top-left header to switch between Quanta avatars and Pine Box. Swipe down for Quick settings. Tap the middle left/right edges for issues and dialogue bubbles for actions. Close this panel to keep streaming.';
    panel.querySelector('[data-lcd-stop]').disabled = !running;
    const fw = state?.firmware;
    panel.querySelector('[data-lcd-firmware-note]').textContent = (fw?.expectedVersion
      ? 'Installed ' + fw.installedVersion + ' / available ' + fw.expectedVersion + '. ' : '')
      + (fw?.reason || 'Firmware requires Quanta’s board-specific USB tools.');
    const firmwareLog = panel.querySelector('[data-lcd-firmware-log]');
    if (firmwareLog) firmwareLog.textContent = fw?.job ? fw.job.action + (fw.job.running ? ' running…' : fw.job.error ? ' failed: ' + fw.job.error : ' completed')
      + '\n' + (fw.job.log || []).join('\n') : fw?.artifact ? 'Pine firmware built for ' + fw.artifact.board + ' · ' + new Date(fw.artifact.built).toLocaleString() : 'Build a board-specific Pine firmware to give LCD taps exclusively to Pine Box while streaming.';
    const portSelect = panel.querySelector('[data-lcd-port]');
    const ports = fw?.job?.action === 'ports' ? fw.job.result?.ports : null;
    if (portSelect && ports && JSON.stringify(ports) !== portSelect.dataset.ports) {
      portSelect.dataset.ports = JSON.stringify(ports); portSelect.replaceChildren();
      for (const row of ports) { const option = node('option', row.Port + ' · ' + row.Chip); option.value = row.Port; portSelect.appendChild(option); }
      if (!ports.length) { const option = node('option', 'No supported USB display ports'); option.value = ''; portSelect.appendChild(option); }
    }
    for (const button of panel.querySelectorAll('[data-lcd-firmware-action]')) button.disabled = !!fw?.job?.running;
    const samples = panel.querySelector('[data-lcd-sample-dir]');
    if (samples) samples.textContent = 'Sound samples: ' + (state?.sampleDirectory || 'your Pine Box save folder');
  }

  function draw(timestamp) {
    const width = canvas.width, height = canvas.height, size = fontSize();
    hitRows = [];
    window.PineLcdReviewHits = [];
    galleryFrame = null;
    const reviewState = review?.snapshot();
    canvas.dataset.lcdReviewOpen = String(!!reviewState?.open);
    canvas.dataset.lcdReviewId = reviewState?.selectedId || '';
    canvas.dataset.lcdReviewPage = String(reviewState?.page || 0);
    canvas.dataset.lcdView = controls.view(state?.config);
    const dt = lastFrame ? Math.min(0.15, Math.max(0, (timestamp - lastFrame) / 1000)) : 0; lastFrame = timestamp;
    if (reviewState?.open) { review.draw(ctx,width,height); drawModeButton(); return; }
    const overlay = state?.config?.chatOverlay !== false || !!selected || state?.config?.mode === 'dialogue';
    ctx.fillStyle = overlay ? '#07121b' : '#efe6cf'; ctx.fillRect(0, 0, width, height);
    if (state?.device?.displayMode === 'avatar' && !drawer) {
      ctx.fillStyle = '#07121b'; ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = '#a1dec0'; ctx.font = 'bold ' + size * 1.5 + 'px sans-serif';
      ctx.fillText(state.device.screensaver ? 'Avatar screensaver' : 'Quanta avatars', 18, height * .4, width - 36);
      ctx.font = size + 'px sans-serif'; ctx.fillStyle = '#d7e3e3';
      ctx.fillText('Slideshow playing on the LCD', 18, height * .55, width - 36);
      ctx.fillText(state.device.screensaver ? 'Tap anywhere to wake' : 'Top-left tap or swipe down for Pine Box', 18, height * .7, width - 36);
      drawHeader(state.device.screensaver ? 'Avatar screensaver' : 'Quanta avatars', state.device.screensaver ? 'Tap anywhere to wake' : 'Tap PB to return to Pine Box');
      drawModeButton();
      return;
    }
    if (state?.config?.mode === 'gallery') {
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, width, height);
      galleryFrame = gallery?.draw(ctx, width, height, timestamp, {
        intervalSeconds: Number(state.config.galleryIntervalSeconds) || 8, paused: drawer,
      }) || {state: 'error', paintKey: 'unavailable'};
      canvas.dataset.lcdGalleryState = galleryFrame.state;
      canvas.dataset.lcdGalleryImage = galleryFrame.imageId || '';
      canvas.dataset.lcdGalleryTransition = galleryFrame.transition || '';
      if (galleryFrame.state !== 'ready') {
        const message = galleryFrame.state === 'empty' ? 'No gallery pictures yet'
          : galleryFrame.state === 'error' ? 'Gallery unavailable · retrying' : 'Loading Pine Box gallery…';
        ctx.fillStyle = '#d7e3e3'; ctx.font = size + 'px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(message, width / 2, height * .6, width - 24); ctx.textAlign = 'left';
      }
      if (drawer) drawDrawer();
      drawModeButton();
      return;
    }
    // Paused: the cupboard takes the screen - every stored line, what is
    // being tinted and generated, and the grader's verdicts.
    if ((state?.config?.mode === 'cupboard' || station?.paused && state?.config?.pausedCupboard !== false) && cupboardLines.length && !selected) {
      drawCupboard(dt, width, height, size); if (drawer) drawDrawer(); drawModeButton(); return;
    }
    const mode = state?.config?.mode || 'paper';
    if (mode === 'paper') {
      drawPaper(dt, width, height, overlay);
    }
    const top = mode === 'paper' ? Math.max(headerHeight() + 6, Math.round(height * 0.36)) : headerHeight() + 4;
    hitRows = [];
    if (overlay) {
    ctx.fillStyle = 'rgba(4,12,20,.89)'; ctx.fillRect(5, top, width - 10, height - top);
    hitRows = [];
    for (const row of rows.values()) if (row.lcdStatus === 'Playing') row.lcdStatus = 'Recently playing';
    for (const row of window.PineLcdDialogue.stationRows(station, Date.now() + stationSkew)) {
      if (row.lcdStatus === 'Playing') rows.delete(row.id);
      rows.set(row.id, row);
    }
    while (rows.size > 180) rows.delete(rows.keys().next().value);
    if (selected && rows.has(selected.id)) selected = rows.get(selected.id);
    const recent = [...rows.values()].slice(-5);
    const current = recent.findLast((row) => row.lcdStatus === 'Playing');
    // 2026-09-08: the screen shows what is being SAID. A new line
    // re-baselines the pan; with nothing on the air the last line is held
    // a beat (the clip's tail is still in the room), then the screen goes
    // idle and says so. Before this the idle screen was the newest five
    // feed rows - booth activity, recorded/waiting - panning on the wall
    // clock, so the text scrolled and jumped while nothing was being said.
    if (current && current.id !== currentId) { currentId = current.id; currentBegan = timestamp; }
    if (!current) currentId = '';
    if (current) { heldRow = current; heldUntil = timestamp + LCD_HOLD_MS; heldPan = timestamp - currentBegan; }
    const held = !current && heldRow && timestamp < heldUntil ? heldRow : null;
    if (!current && !held) heldRow = null;
    const visible = selected ? [selected] : current ? [current] : held ? [held] : [];
    const blocks = visible.map((row) => {
      const text = wrap(row.text, width - 38, size + 'px sans-serif');
      return {row, text, height: size * 1.35 * (text.length + 1) + 12};
    });
    const available = height - top - (selected ? 36 : 20);
    const full = blocks.reduce((sum, b) => sum + b.height, 0);
    // Slowly reveal every part of long messages; pin the selected message
    // until the operator closes it or chooses an action. The pan runs on
    // the spoken line's own clock and freezes when nothing is spoken.
    const overflow = Math.max(0, full - available);
    if (selected && selected.id !== selectedId) { selectedId = selected.id; selectedBegan = timestamp; }
    if (!selected) selectedId = '';
    const panMs = selected ? timestamp - selectedBegan : current ? timestamp - currentBegan : held ? heldPan : 0;
    const pan = overflow ? (panMs / 70) % (overflow + available * 0.5) : 0;
    let y = top + size + 4 - Math.min(overflow, pan);
    ctx.save(); ctx.beginPath(); ctx.rect(8, top + 1, width - 16, available); ctx.clip();
    if (!blocks.length) {
      ctx.font = size + 'px sans-serif'; ctx.fillStyle = '#c3d4df';
      const spinning = station?.now && (station.now.title || station.now.artist);
      const waits = Number(station?.dialogue_flow?.retire?.pending || 0);
      const idle = (station?.paused ? 'Paused · nothing is being said'
        : spinning ? '♪ ' + [station.now.artist, station.now.title].filter(Boolean).join(' - ')
        : station?.on === false ? 'Off the air' : 'On the air · nothing is being said')
        + (waits ? ' · ⏳ ' + waits + ' round' + (waits === 1 ? '' : 's') + ' wait for your decision at the retirement desk' : '');
      wrap(idle, width - 32, ctx.font).forEach((line) => {
        ctx.fillText(line, 16, y); y += size * 1.5;
      });
    }
    for (const block of blocks) {
      const start = y - size;
      ctx.font = 'bold ' + size + 'px sans-serif'; ctx.fillStyle = color(block.row.who);
      ctx.fillText((liked.has(block.row.id) ? '★ ' : '') + (block.row.name || block.row.who || 'Booth') + ' · ' + block.row.lcdStatus, 15, y, width - 30);
      y += size * 1.35; ctx.fillStyle = '#eef6fa'; ctx.font = size + 'px sans-serif';
      for (const line of block.text) { ctx.fillText(line, 17, y); y += size * 1.35; }
      y += 12;
      if (y > top && start < top + available) hitRows.push({row: block.row, y1: Math.max(top, start), y2: Math.min(top + available, y)});
    }
    ctx.restore();
    }
    const title = selected ? '× Close dialogue' : mode === 'paper' ? state?.config?.paperStyle === 'tabloid' ? 'Tabloid' : 'Gazette' : 'PINE BOX · LIVE BOOTH';
    drawHeader(title, selected ? 'Tap here to close' : mode === 'paper' ? '‹ ' + (edition?.id || 'Waiting for the paper') + ' ›' : 'Swipe down for controls');
    if (selected) {
      ctx.fillStyle = '#1d3a48'; ctx.fillRect(0, height - 30, width, 30);
      ctx.fillStyle = '#f4e5ab'; ctx.font = 'bold ' + size + 'px sans-serif';
      ctx.fillText(selected.lcdAudio ? '★ Favorite' : selected.lcdStatus, width * 0.21, height - 11, width * 0.55);
      if (selected.lcdAudio) ctx.fillText('↓ Download', width * 0.53, height - 11, width * 0.27);
    } else {
      ctx.fillStyle = overlay ? '#07121b' : '#efe6cf'; ctx.fillRect(0, height - 16, width, 16);
      ctx.fillStyle = overlay ? '#87a2b2' : '#4f493e'; ctx.font = Math.max(9, size - 2) + 'px sans-serif';
      ctx.fillText(running ? 'Swipe down for controls' : 'Preview · swipe down for controls', 10, height - 5);
    }
    if (localMessage && Date.now() < messageUntil) {
      ctx.fillStyle = '#244039'; ctx.fillRect(4, height - 49, width - 8, 18);
      ctx.fillStyle = '#edfff2'; ctx.font = Math.max(10, size - 2) + 'px sans-serif';
      ctx.fillText(localMessage, 10, height - 36, width - 20);
    }
    if (drawer) drawDrawer();
    drawModeButton();
  }

  function drawHeader(title, subtitle) {
    const region = controls.corner(canvas.width, canvas.height), x = region.w + 10, available = canvas.width - x - 8;
    ctx.fillStyle = '#102636'; ctx.fillRect(0, 0, canvas.width, region.h);
    ctx.fillStyle = '#ecf7ef'; ctx.font = 'bold ' + fontSize() + 'px sans-serif';
    ctx.fillText(title, x, region.h * .43, available);
    ctx.fillStyle = '#9bb6b7'; ctx.font = Math.max(10, fontSize() - 1) + 'px sans-serif';
    ctx.fillText(subtitle, x, region.h * .76, available);
  }

  // The mode switch owns this space in every view, including the quick drawer.
  // Native firmware reserves the same rectangle against incoming image writes.
  function drawModeButton() {
    const region = controls.corner(canvas.width, canvas.height), b = region.badge;
    const label = state?.device?.displayMode === 'avatar' ? 'PB' : 'AV';
    ctx.save();
    ctx.fillStyle = '#102636'; ctx.fillRect(0, 0, region.w, region.h);
    ctx.fillStyle = '#102632'; ctx.strokeStyle = '#a1dec0'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 6); ctx.fill(); ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#edfff2'; ctx.font = 'bold ' + Math.min(24, Math.max(16, b.w * .38)) + 'px monospace';
    ctx.fillText(label, b.x + b.w / 2, b.y + b.h * .39, b.w - 6);
    ctx.fillStyle = '#a1dec0'; ctx.font = '9px monospace';
    ctx.fillText('SWAP', b.x + b.w / 2, b.y + b.h * .78, b.w - 6);
    ctx.restore();
    canvas.dataset.lcdSwap = label;
  }

  function icon(kind, x, y, active) {
    ctx.save(); ctx.translate(x, y); ctx.strokeStyle = active ? '#153b32' : '#b9d2cf';
    ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 1.8; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath();
    if (kind === 'chat') { ctx.roundRect(1, 2, 21, 15, 4); ctx.moveTo(6, 17); ctx.lineTo(6, 22); ctx.lineTo(12, 17); }
    else if (kind === 'paper' || kind === 'tabloid') {
      ctx.roundRect(2, 1, 19, 22, 2); ctx.moveTo(6, 6); ctx.lineTo(17, 6);
      ctx.moveTo(6, 11); ctx.lineTo(11, 11); ctx.moveTo(6, 15); ctx.lineTo(11, 15);
      ctx.moveTo(6, 19); ctx.lineTo(17, 19); ctx.rect(14, 10, 3, 5);
    } else if (kind === 'avatar') { ctx.arc(12, 7, 5, 0, Math.PI * 2); ctx.moveTo(2, 23); ctx.bezierCurveTo(2, 11, 22, 11, 22, 23); }
    else if (kind === 'gallery') { ctx.roundRect(1, 2, 22, 20, 3); ctx.moveTo(3, 18); ctx.lineTo(9, 11); ctx.lineTo(14, 16); ctx.lineTo(18, 12); ctx.lineTo(22, 17); ctx.moveTo(18, 7); ctx.arc(16, 7, 2, 0, Math.PI * 2); }
    else if (kind === 'moon') { ctx.arc(12, 12, 10, -.6, 4.5); ctx.bezierCurveTo(3, 15, 14, 23, 20, 6); }
    else { ctx.moveTo(7, 3); ctx.lineTo(7, 21); ctx.moveTo(3, 7); ctx.lineTo(7, 3); ctx.lineTo(11, 7); ctx.moveTo(17, 3); ctx.lineTo(17, 21); ctx.lineTo(13, 17); ctx.moveTo(17, 21); ctx.lineTo(21, 17); }
    ctx.stroke(); ctx.restore();
  }

  function drawDrawer() {
    const width = canvas.width, height = canvas.height, config = state?.config || {};
    ctx.save(); ctx.scale(width / 320, height / 240);
    ctx.fillStyle = '#101d22'; ctx.fillRect(0, 0, 320, 240);
    ctx.fillStyle = '#536e73'; ctx.beginPath(); ctx.roundRect(137, 6, 46, 4, 2); ctx.fill();
    ctx.fillStyle = '#ecf7ef'; ctx.font = 'bold 18px sans-serif'; ctx.fillText('Quick settings', 76, 30, 206);
    ctx.fillStyle = '#9bb6b7'; ctx.font = '10px sans-serif'; ctx.fillText('Swipe up to close', 76, 49);
    ctx.font = '22px sans-serif'; ctx.fillText('×', 289, 35);
    for (const tile of controls.tiles(config)) {
      ctx.fillStyle = tile.active ? '#a1dec0' : '#293c44'; ctx.beginPath(); ctx.roundRect(tile.x, tile.y, tile.w, tile.h, 14); ctx.fill();
      icon(tile.icon, tile.x + 9, tile.y + 4, tile.active);
      ctx.fillStyle = tile.active ? '#102e29' : '#e3eded'; ctx.font = 'bold 12px sans-serif';
      ctx.fillText(tile.label, tile.x + 39, tile.y + 21, tile.w - 44);
    }
    ctx.fillStyle = '#293c44'; ctx.beginPath(); ctx.roundRect(8, 210, 197, 26, 12); ctx.fill();
    ctx.fillStyle = '#cee7dd'; ctx.font = '11px sans-serif';
    ctx.fillText('Avatar timer: ' + controls.timerLabel(Number(config.screensaverSeconds) || 300) + '  ›', 20, 228);
    ctx.fillText('Done  ↑', 248, 228);
    ctx.restore();
    canvas.dataset.lcdDrawer = 'open';
  }

  async function configure(change) {
    review?.close();
    state = await bridge.lcdConfigure(change);
    if ('paperStyle' in change || 'mode' in change) layoutPaper();
    lastGalleryAckKey = ''; lastGalleryAckAt = 0;
    if (change.mode && state?.device?.displayMode === 'avatar' && state?.connected) state = await bridge.lcdDisplayMode('pine');
    selected = null; syncOptions(); paintStatus();
  }

  function syncOptions() {
    if (!panel) return;
    const config = state?.config || {};
    for (const input of panel.querySelectorAll('[data-lcd-setting]')) {
      const key = input.dataset.lcdSetting;
      if (document.activeElement === input) continue;
      if (input.type === 'checkbox') input.checked = key === 'chatOverlay' && config.mode === 'gallery' ? false : config[key] !== false && (key !== 'screensaverEnabled' || !!config[key]);
      else if (key === 'view') input.value = controls.view(config);
      else {
        const value = String(config[key] ?? (key === 'galleryIntervalSeconds' ? 8 : 300));
        if (key === 'galleryIntervalSeconds' && !Array.from(input.options).some(option => option.value === value)) {
          const option = node('option', 'Each picture: ' + value + ' sec'); option.value = value; input.appendChild(option);
        }
        input.value = value;
      }
    }
  }

  async function quickAction(id) {
    if (id === 'close') { drawer = false; canvas.dataset.lcdDrawer = 'closed'; return; }
    if (id === 'avatar') {
      state = await bridge.lcdDisplayMode('avatar'); drawer = false; selected = null;
      note('Quanta avatars · tap top-left or swipe down for Pine Box'); return;
    }
    const patch = controls.change(id, state?.config);
    if (patch) await configure(patch);
  }

  async function swipe(direction, physical = false) {
    if (review?.snapshot().open) { review.swipe(direction); return; }
    if (direction === 'down') {
      if (!physical && state?.device?.displayMode === 'avatar') state = await bridge.lcdDisplayMode('pine');
      drawer = true; selected = null;
    }
    else if (direction === 'up') { drawer = false; canvas.dataset.lcdDrawer = 'closed'; }
  }

  async function favorite() {
    if (review?.snapshot().open) return;
    if (!selected) { note('Select a dialogue bubble first.'); return; }
    if (!selected.lcdAudio) { note('This booth entry has no aired audio yet.'); return; }
    if (liked.has(selected.id)) { note('This dialogue is already favorited.'); return; }
    const row = selected;
    await bridge.post('/api/dj/saved', {text: row.text, source: 'LCD favorite · booth ' + row.id});
    liked.add(row.id); note('Dialogue saved to the station’s favorites.');
  }
  async function download() {
    if (review?.snapshot().open) return;
    if (!selected) { note('Select a dialogue bubble first.'); return; }
    if (!selected.lcdAudio) { note('This booth entry has no aired audio yet.'); return; }
    const result = await bridge.lcdDownload(String(selected.id), Number(selected.air_at || selected.ts || 0));
    note(result.ok ? (result.exact ? 'Sample saved' : 'Surrounding audio saved') + (result.directory ? ' · ' + result.directory : '') : result.why);
  }
  async function touch(x, y, physical = false) {
    if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) return;
    if (state?.device?.screensaver) {
      review?.close();
      if (!physical) state = await bridge.lcdControl('screensaver', false);
      drawer = false; selected = null; lastFrame = 0; note('Pine Box resumed'); return;
    }
    // Firmware consumes physical corner contacts. The preview sends exactly one
    // mode command, ahead of drawer/content handling, even during a slow action.
    if (controls.cornerHit(x, y, canvas.width, canvas.height)) {
      review?.close();
      if (!physical) state = await bridge.lcdDisplayMode(state?.device?.displayMode === 'avatar' ? 'pine' : 'avatar');
      drawer = false; canvas.dataset.lcdDrawer = 'closed'; selected = null; lastFrame = 0; paintStatus(); return;
    }
    if (review?.snapshot().open) { review.tap(x,y,canvas.width,canvas.height); return; }
    if (actionBusy) return;
    if (drawer) {
      actionBusy = true;
      try { await quickAction(controls.hit(x, y, canvas.width, canvas.height, state?.config)); }
      finally { actionBusy = false; }
      return;
    }
    if (physical && state?.device?.displayMode === 'avatar') return;
    if (state?.config?.mode === 'gallery') {
      if (x > canvas.width * .65 && y > headerHeight()) gallery?.next();
      return;
    }
    const cut = hitRows.find(row => row.review && x >= row.x1 && x <= row.x2 && y >= row.y1 && y <= row.y2);
    if (cut && review) { selected = null; drawer = false; void review.open(cut.row); return; }
    if (selected) {
      if (y < headerHeight()) { selected = null; paintStatus(); return; }
      if (y > canvas.height - 32 && x > canvas.width * 0.2 && x < canvas.width * 0.8) {
        actionBusy = true;
        try { await (x < canvas.width / 2 ? favorite() : download()); }
        finally { actionBusy = false; }
        return;
      }
    }
    if (y > canvas.height * 0.25 && y < canvas.height * 0.75) {
      if (x < canvas.width * 0.13) { await stepEdition(-1); return; }
      if (x > canvas.width * 0.87) { await stepEdition(1); return; }
    }
    const hit = hitRows.find((row) => y >= row.y1 && y <= row.y2);
    if (hit) { selected = hit.row; paintStatus(); }
  }
  canvas.onclick = (event) => {
    if (Date.now() < suppressClickUntil) return;
    const box = canvas.getBoundingClientRect();
    touch((event.clientX - box.left) / box.width * canvas.width,
      (event.clientY - box.top) / box.height * canvas.height).catch((error) => note(error.message));
  };
  const point = event => { const box = canvas.getBoundingClientRect(); return {x: (event.clientX - box.left) / box.width * canvas.width, y: (event.clientY - box.top) / box.height * canvas.height}; };
  canvas.style.touchAction = 'none';
  canvas.onpointerdown = event => { pointerStart = point(event); try { canvas.setPointerCapture?.(event.pointerId); } catch {} };
  canvas.onpointercancel = () => { pointerStart = null; };
  canvas.onpointerup = event => {
    if (!pointerStart) return;
    const end = point(event), kind = controls.gesture(pointerStart, end, canvas.width, canvas.height);
    pointerStart = null; suppressClickUntil = Date.now() + 500;
    if (state?.device?.screensaver || kind === 'tap') touch(end.x, end.y).catch(error => note(error.message));
    else if (kind) swipe(kind).catch(error => note(error.message));
  };
  canvas.onwheel = event => {
    if (review?.snapshot().open) { event.preventDefault(); review.scroll(event.deltaY > 0 ? 1 : -1); }
  };

  // Input has its own bounded poll. A slow image ACK never holds a gesture
  // behind the frame loop, and there is never more than one input request.
  async function pollInput() {
    inputTimer = null;
    if (!running || inputPolling) return;
    inputPolling = true;
    try {
      const result = await bridge.lcdEvents();
      for (const event of result.events || []) {
        if (event.kind === 'touch') await touch(event.x, event.y, true);
        else if (event.kind === 'swipe') await swipe(event.direction, true);
        else if (event.kind === 'wake') { if (state?.device) { state.device.displayMode = 'pine'; state.device.screensaver = false; } drawer = false; selected = null; lastFrame = 0; note('Pine Box resumed'); }
        else if (event.kind === 'screensaver') { review?.close(); if (state?.device) { state.device.displayMode = 'avatar'; state.device.screensaver = true; } drawer = false; selected = null; }
        else if (event.kind === 'nav' && review?.snapshot().open) review.scroll(event.direction === 'next' ? 1 : -1);
        else if (event.kind === 'nav' && !drawer && state?.device?.displayMode !== 'avatar') await stepEdition(event.direction === 'next' ? 1 : -1);
        else if (event.kind === 'mode') { review?.close(); if (state?.device) state.device.displayMode = event.mode; selected = null; if (event.mode === 'avatar') drawer = false; lastFrame = 0; paintStatus(); }
      }
      if (result.device && state) state.device = result.device;
    } catch (error) { note('LCD input: ' + error.message); }
    finally { inputPolling = false; if (running) inputTimer = setTimeout(pollInput, state?.device?.pineProtocol >= 2 ? 80 : 250); }
  }

  async function tick() {
    if (looping || (!running && !panel)) return;
    looping = true;
    const began = performance.now();
    let failed = false;
    try {
      const now = Date.now();
      if (now - lastPoll > 1000 && !polling) {
        lastPoll = now; polling = true;
        pollStation().catch((error) => note(error.message)).finally(() => { polling = false; });
      }
      const renderAt = performance.now();
      draw(Date.now());
      const renderMs = performance.now() - renderAt;
      if (running && !inputTimer && !inputPolling) pollInput();
      // Held gallery pictures need only a one-second heartbeat to retain the
      // native host view. Transitions still use the full acknowledged cadence.
      const galleryKey = galleryFrame && !drawer ? galleryFrame.paintKey : '';
      const sendFrame = !galleryKey || galleryKey !== lastGalleryAckKey || Date.now() - lastGalleryAckAt >= 1000;
      if (running && state?.device?.displayMode !== 'avatar' && sendFrame) {
        const device = state?.transport === 'usb' ? {...state.device, streamPort: 0} : state?.device;
        const encodeAt = performance.now(), frame = window.PineLcdFrame.encode(canvas, device);
        const encodeMs = performance.now() - encodeAt, sendAt = performance.now();
        const sent = await bridge.lcdFrame(frame.jpeg);
        window.PineLcdMetrics = {at: Date.now(), renderMs, encodeMs, ackMs: performance.now() - sendAt,
          jpegBytes: frame.bytes, encodes: frame.encodes, drawn: !!sent.ok && !sent.skipped && !sent.avatar,
          view: state?.config?.mode, paperStyle: state?.config?.paperStyle, chatOverlay: state?.config?.mode !== 'gallery' && state?.config?.chatOverlay !== false,
          gallery: galleryFrame ? {imageId: galleryFrame.imageId, transition: galleryFrame.transition, transitioning: galleryFrame.transitioning, state: galleryFrame.state} : undefined};
        if (sent.ok && !sent.skipped && !sent.avatar && !sent.busy) { lastGalleryAckKey = galleryKey; lastGalleryAckAt = Date.now(); }
        if (!sent.ok && !sent.busy) { failed = true; note(sent.why); }
      }
    } catch (error) { failed = true; note(error.message); }
    finally {
      looping = false; clearTimeout(timer);
      const interval = failed ? 500 : state?.device?.displayMode === 'avatar' ? 160 : galleryFrame && !galleryFrame.transitioning && !drawer ? 100 : 1000 / 30;
      if (running || panel) timer = setTimeout(tick, Math.max(1, interval - (performance.now() - began)));
    }
  }
  async function start(automatic = false) {
    clearTimeout(autoRetry);
    state = await bridge.lcdStart(automatic); running = !!state.running;
    if (state.device) { canvas.width = state.device.width; canvas.height = state.device.height; layoutPaper(); }
    lastPoll = 0; note('Connected; waiting for the first drawn-frame acknowledgment.'); tick();
  }
  async function stop() { clearTimeout(autoRetry); await bridge.lcdStop(); running = false; state = await bridge.lcdState(); note('LCD producer stopped.'); }

  async function resumeWhenAvailable() {
    const latest = await bridge.lcdState();
    if (!latest.config.autoStart || !latest.config.identity || running) return;
    try { await start(true); }
    catch (error) {
      entry.title = 'LCD disconnected: ' + error.message;
      note(error.message);
      autoRetry = setTimeout(() => resumeWhenAvailable().catch(() => {}), 12000);
    }
  }

  async function open() {
    if (panel) { panel.focus(); return; }
    state = await bridge.lcdState();
    const shade = node('div'); shade.id = 'pineLcdPanel';
    shade.style.cssText = 'position:fixed;inset:0;background:#02080ce8;z-index:720;display:grid;place-items:center;padding:18px';
    const card = node('section'); card.tabIndex = -1;
    card.style.cssText = 'background:#101e29;border:1px solid #3e687b;border-radius:12px;padding:18px;width:min(860px,96vw);max-height:94vh;overflow:auto;color:#e5eff5;font:13px/1.5 sans-serif';
    const heading = node('div'); heading.style.cssText = 'display:flex;justify-content:space-between;align-items:center';
    heading.appendChild(node('h2', 'Pine Box LCD'));
    const close = node('button', 'Close'); close.onclick = () => { shade.remove(); panel = null; }; heading.appendChild(close); card.appendChild(heading);
    const form = node('div'); form.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px';
    const host = node('input'); host.placeholder = 'Display LAN IP, quanta-screen.local or COM8'; host.value = state.config.host;
    host.style.cssText = 'min-width:220px;flex:1'; host.setAttribute('aria-label', 'LCD host'); form.appendChild(host);
    const action = (label, run) => { const button = node('button', label); button.onclick = async () => {
      button.disabled = true;
      try { await run(); } catch (error) { note(error.message); }
      finally { button.disabled = false; paintStatus(); }
    }; form.appendChild(button); return button; };
    const found = node('select'); found.style.display = 'none'; found.setAttribute('aria-label', 'Discovered Quanta display');
    action('Discover', async () => {
      const result = await bridge.lcdDiscover(); found.replaceChildren();
      for (const device of result.devices || []) { const option = node('option', device.board + ' · ' + device.host); option.value = device.host; found.appendChild(option); }
      found.style.display = result.devices?.length ? '' : 'none';
      if (result.devices?.length) host.value = found.value;
      note(result.error || result.devices.length + ' Quanta display(s) discovered.');
    });
    found.onchange = () => { host.value = found.value; }; form.appendChild(found);
    action('Connect / test', async () => { state = await bridge.lcdConnect(host.value); running = false;
      canvas.width = state.device.width; canvas.height = state.device.height; layoutPaper();
      note('Identified ' + state.device.board + ' · no frames sent yet.'); });
    action('Start', async () => { await bridge.lcdConfigure({host: host.value}); await start(); });
    const halt = action('Stop', stop); halt.dataset.lcdStop = '';
    action('Quanta avatars / Pine Box', async () => { state = await bridge.lcdDisplayMode(state?.device?.displayMode === 'avatar' ? 'pine' : 'avatar'); selected = null; note('Display mode: ' + state.device.displayMode); });
    action('Release USB to Quanta', async () => { clearTimeout(autoRetry); state = await bridge.lcdDisconnect(); running = false; selected = null; note(state.releaseWarning || 'Quanta avatars resumed; USB is free for Quanta. Start reconnects Pine Box.'); });
    card.appendChild(form);
    const options = node('div'); options.style.cssText = 'display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-bottom:10px';
    const mode = node('select'); mode.setAttribute('aria-label', 'LCD content');
    mode.dataset.lcdSetting = 'view';
    for (const [value, label] of [['newspaper', 'Newspaper only'], ['paper', 'Newspaper + live dialogue'], ['tabloid', 'Tabloid'], ['gallery', 'Pine Box gallery · images only'], ['dialogue', 'Live dialogue only'], ['cupboard', 'Behind the scenes']]) {
      const option = node('option', label); option.value = value; mode.appendChild(option);
    }
    mode.value = controls.view(state.config);
    mode.onchange = () => configure(controls.change(mode.value, state.config) || {mode: mode.value, pausedCupboard: false}).catch(error => note(error.message));
    options.appendChild(mode);
    const cycle = node('button', 'Cycle newspaper / gallery');
    cycle.onclick = () => configure(controls.cycle(state.config)).catch(error => note(error.message)); options.appendChild(cycle);
    const galleryDuration = node('select'); galleryDuration.dataset.lcdSetting = 'galleryIntervalSeconds'; galleryDuration.setAttribute('aria-label', 'Gallery image duration');
    for (const seconds of [3, 5, 8, 15, 30, 60]) { const option = node('option', 'Each picture: ' + seconds + ' sec'); option.value = String(seconds); galleryDuration.appendChild(option); }
    galleryDuration.onchange = () => configure({galleryIntervalSeconds: Number(galleryDuration.value)}).catch(error => note(error.message)); options.appendChild(galleryDuration);
    const nextPicture = node('button', 'Next gallery image'); nextPicture.onclick = async () => {
      try { if (state?.config?.mode !== 'gallery') await configure(controls.change('gallery', state.config)); else gallery?.next(); }
      catch (error) { note(error.message); }
    }; options.appendChild(nextPicture);
    const autoLabel = node('label', 'Resume on app launch '); const auto = node('input'); auto.type = 'checkbox'; auto.checked = state.config.autoStart;
    auto.onchange = async () => { state = await bridge.lcdConfigure({autoStart: auto.checked}); }; autoLabel.appendChild(auto); options.appendChild(autoLabel);
    const speedLabel = node('label', 'Scroll '); const speed = node('input'); speed.type = 'range'; speed.min = '2'; speed.max = '50'; speed.value = state.config.speed;
    speed.onchange = async () => { state = await bridge.lcdConfigure({speed: Number(speed.value)}); }; speedLabel.appendChild(speed); options.appendChild(speedLabel);
    card.appendChild(options);
    const quick = node('div'); quick.style.cssText = 'display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px';
    const showControls = node('button', 'Quick settings ▾'); showControls.onclick = () => swipe(drawer ? 'up' : 'down').catch(error => note(error.message)); quick.appendChild(showControls);
    for (const [key, label] of [['chatOverlay', 'Chat overlay'], ['scrollEnabled', 'Auto-scroll'], ['screensaverEnabled', 'Avatar screensaver'], ['pausedCupboard', 'Behind the scenes when paused']]) {
      const item = node('label', label + ' '), input = node('input'); input.type = 'checkbox'; input.dataset.lcdSetting = key; input.setAttribute('aria-label', label);
      input.onchange = () => configure(key === 'chatOverlay' ? controls.change('chat', state.config) : {[key]: input.checked}).catch(error => note(error.message)); item.appendChild(input); quick.appendChild(item);
    }
    const timeout = node('select'); timeout.dataset.lcdSetting = 'screensaverSeconds'; timeout.setAttribute('aria-label', 'Avatar screensaver timer');
    for (const seconds of [15, 30, 60, 300, 900, 1800, 3600]) { const option = node('option', 'After ' + controls.timerLabel(seconds)); option.value = String(seconds); timeout.appendChild(option); }
    timeout.onchange = () => configure({screensaverSeconds: Number(timeout.value)}).catch(error => note(error.message)); quick.appendChild(timeout);
    const saverNow = node('button', 'Preview screensaver'); saverNow.onclick = () => bridge.lcdControl('screensaver', true).then(got => { state = got; drawer = false; note('Avatar screensaver · tap anywhere on the LCD to wake'); }).catch(error => note(error.message)); quick.appendChild(saverNow);
    card.appendChild(quick);
    const status = node('p'); status.dataset.lcdStatus = ''; status.setAttribute('role', 'status'); card.appendChild(status);
    const board = node('p'); board.dataset.lcdBoard = ''; board.style.color = '#9bb5c5'; card.appendChild(board);
    const grid = node('div'); grid.style.cssText = 'display:grid;grid-template-columns:minmax(160px,1.25fr) minmax(160px,1fr);gap:16px';
    const preview = node('div'); preview.appendChild(canvas); grid.appendChild(preview);
    const details = node('div');
    const detail = node('p'); detail.dataset.lcdDetail = ''; detail.style.cssText = 'max-height:200px;overflow:auto;white-space:pre-wrap'; details.appendChild(detail);
    for (const [label, run] of [['‹ Older issue', () => stepEdition(-1)], ['Newer issue ›', () => stepEdition(1)],
      ['Follow newest', async () => { manualEdition = false; await showEdition(latestPaper); }], ['★ Favorite', favorite], ['↓ Download', download]]) {
      const button = node('button', label); button.dataset.lcdPaperAction = ''; button.style.margin = '3px'; button.onclick = () => Promise.resolve(run()).catch((error) => note(error.message)); details.appendChild(button);
    }
    const hint = node('p', 'Tap the AV / PB button in the top-left header to switch between Quanta avatars and Pine Box. Swipe down for Quick settings. Tap the middle left/right edges for issues and dialogue bubbles for actions. Close this panel to keep streaming.');
    hint.dataset.lcdHint = '';
    hint.style.cssText = 'font-size:11px;color:#9bb5c5'; details.appendChild(hint); grid.appendChild(details); card.appendChild(grid);
    const ownership = node('p', 'For both apps at once, connect Pine Box over Wi-Fi and Quanta over USB. With Pine on USB, “Release USB to Quanta” hands that exclusive port back; Start reconnects Pine afterward.');
    ownership.style.cssText = 'font-size:11px;color:#9bb5c5'; card.appendChild(ownership);
    const log = node('pre'); log.dataset.lcdLog = ''; log.style.cssText = 'max-height:130px;overflow:auto;white-space:pre-wrap;font-size:10px;background:#07121b;padding:9px'; card.appendChild(log);
    const fwNote = node('p'); fwNote.dataset.lcdFirmwareNote = ''; fwNote.style.cssText = 'font-size:11px;color:#9bb5c5'; card.appendChild(fwNote);
    const fw = node('button', 'Open Quanta firmware tools'); fw.onclick = async () => {
      try { const result = await bridge.lcdFirmware(); note(result.why || 'Quanta firmware tools opened.'); } catch (error) { note(error.message); }
    }; card.appendChild(fw);
    const firmware = node('details'); firmware.style.marginTop = '12px'; firmware.appendChild(node('summary', 'Program and manage the display'));
    const fwForm = node('div'); fwForm.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;padding:10px 0;align-items:center';
    const quanta = node('input'); quanta.value = state.config.quantaRoot || 'C:\\_tools\\Quanta'; quanta.setAttribute('aria-label', 'Quanta installation folder'); quanta.style.minWidth = '200px'; fwForm.appendChild(quanta);
    const boardChoice = node('select'); boardChoice.setAttribute('aria-label', 'Firmware board');
    for (const board of state.firmware?.boards || []) { const option = node('option', board.label || board.id); option.value = board.id; boardChoice.appendChild(option); }
    if (state.device?.board) boardChoice.value = state.device.board;
    fwForm.appendChild(boardChoice);
    const port = node('select'); port.dataset.lcdPort = ''; port.setAttribute('aria-label', 'LCD USB port');
    const emptyPort = node('option', 'Find USB displays first'); emptyPort.value = ''; port.appendChild(emptyPort); fwForm.appendChild(port);
    const ssid = node('input'); ssid.placeholder = 'Wi-Fi network for firmware'; ssid.setAttribute('aria-label', 'Firmware Wi-Fi SSID'); fwForm.appendChild(ssid);
    const pass = node('input'); pass.type = 'password'; pass.autocomplete = 'new-password'; pass.placeholder = 'Wi-Fi password'; pass.setAttribute('aria-label', 'Firmware Wi-Fi password'); fwForm.appendChild(pass);
    const fwAction = (label, action) => {
      const button = node('button', label); button.dataset.lcdFirmwareAction = action;
      button.onclick = async () => {
        button.disabled = true;
        try {
          await bridge.lcdConfigure({quantaRoot: quanta.value});
          const result = await bridge.lcdFirmware({action, board: boardChoice.value, port: port.value, ssid: ssid.value, pass: pass.value});
          pass.value = ''; state.firmware = result; lastPoll = 0; note(label + ' started.');
        } catch (error) { note(error.message); }
        finally { paintStatus(); }
      };
      fwForm.appendChild(button);
    };
    fwAction('Find USB displays', 'ports'); fwAction('Identify selected USB display', 'identify');
    fwAction('Build Pine firmware', 'build'); fwAction('Install via USB', 'usb'); fwAction('Install via Wi-Fi', 'ota');
    firmware.appendChild(fwForm);
    firmware.appendChild(node('p', 'Choose the exact board, build, then install. USB identification briefly reboots the selected display; USB installation backs up its current flash first. Wi-Fi installation requires an OTA partition. Saved galleries are preserved. Keep the display powered during installation.'));
    const firmwareLog = node('pre'); firmwareLog.dataset.lcdFirmwareLog = ''; firmwareLog.style.cssText = 'max-height:170px;overflow:auto;white-space:pre-wrap;font-size:11px'; firmware.appendChild(firmwareLog);
    const hardwareControls = node('div'); hardwareControls.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap';
    const brightnessLabel = node('label', 'Brightness '); const brightness = node('input'); brightness.type = 'range'; brightness.min = '1'; brightness.max = '255'; brightness.value = '200';
    brightness.onchange = () => bridge.lcdControl('brightness', Number(brightness.value)).then((got) => { state = got; note('Brightness updated.'); }).catch((error) => note(error.message));
    brightnessLabel.appendChild(brightness); hardwareControls.appendChild(brightnessLabel);
    const rotation = node('select'); rotation.setAttribute('aria-label', 'Display rotation');
    for (let n = 0; n < 4; n++) { const option = node('option', 'Rotation ' + (n * 90) + '°'); option.value = String(n); rotation.appendChild(option); }
    rotation.onchange = () => bridge.lcdControl('rotation', Number(rotation.value)).then((got) => { state = got; lastPoll = 0; note('Rotation updated.'); }).catch((error) => note(error.message)); hardwareControls.appendChild(rotation);
    firmware.appendChild(hardwareControls); card.appendChild(firmware);
    const samples = node('p'); samples.dataset.lcdSampleDir = ''; card.appendChild(samples);
    const chooseSamples = node('button', 'Choose sound sample folder'); chooseSamples.onclick = async () => {
      try { state = await bridge.lcdSampleDirectory(); paintStatus(); } catch (error) { note(error.message); }
    }; card.appendChild(chooseSamples);
    shade.appendChild(card); shade.onclick = (event) => { if (event.target === shade) close.click(); };
    shade.onkeydown = (event) => { if (event.key === 'Escape') close.click(); };
    document.body.appendChild(shade); panel = shade; card.focus(); layoutPaper(); syncOptions(); paintStatus(); lastPoll = 0; tick();
  }
  entry.onclick = () => open().catch((error) => { entry.title = 'LCD: ' + error.message; });
  bridge.lcdState().then(async (got) => {
    state = got;
    if (got.running) {
      running = true;
      if (got.device) { canvas.width = got.device.width; canvas.height = got.device.height; }
      layoutPaper(); tick();
    } else if (got.config.autoStart) await resumeWhenAvailable();
  }).catch(() => {});
})();
