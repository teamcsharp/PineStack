/* #1052: one optional LCD canvas producer. It keeps running when its panel
 * closes, and never queues a frame behind another frame. No CDN required. */
(() => {
  const bridge = window.pineDesktop;
  const entry = document.getElementById('lcdBtn');
  if (!entry || !bridge?.lcdState) return;
  let state = null, panel = null, timer = null, autoRetry = null, looping = false, running = false;
  let station = {}, editions = [], edition = null, latestPaper = '', manualEdition = false;
  let paperLines = [], paperHeight = 1, scroll = 0, lastFrame = 0, lastPoll = 0, lastEvents = 0;
  let selected = null, hitRows = [], localMessage = '', messageUntil = 0;
  let editionRequest = 0, actionBusy = false, polling = false;
  let stationSkew = 0;
  let currentId = '', currentBegan = 0;
  const rows = new Map(), liked = new Set();
  const paperImages = new Map();
  const canvas = document.createElement('canvas');
  canvas.width = 320; canvas.height = 240;
  canvas.style.cssText = 'width:100%;height:auto;max-height:55vh;object-fit:contain;background:#07121b;image-rendering:auto';
  const ctx = canvas.getContext('2d', {alpha: false});
  const node = (tag, text = '') => { const el = document.createElement(tag); el.textContent = text; return el; };
  const note = (text) => { localMessage = String(text); messageUntil = Date.now() + 6500; paintStatus(); };
  const fontSize = () => Math.max(12, Math.round(canvas.width / 30));
  const plain = (text) => String(text || '').replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*_`#]/g, '').trim();
  const color = (who) => ({dj: '#9de3ef', cohost: '#ffcf8a', third: '#d4b7ff', caller: '#aceda8', caller2: '#fad0e7'}[who] || '#cbe1ee');

  function wrap(text, width, font) {
    ctx.font = font;
    const out = []; let line = '';
    for (const word of String(text || '').split(/\s+/)) {
      if (!word) continue;
      const next = line ? line + ' ' + word : word;
      if (line && ctx.measureText(next).width > width) { out.push(line); line = word; }
      else line = next;
    }
    if (line) out.push(line);
    return out;
  }

  function layoutPaper() {
    paperLines = []; let y = 0; const size = fontSize();
    const add = (text, title = false) => {
      const font = (title ? 'bold ' : '') + (title ? size * 1.25 : size) + 'px Georgia';
      const height = size * (title ? 1.6 : 1.4);
      for (const line of wrap(plain(text), canvas.width - 24, font)) {
        paperLines.push({text: line, y, font, height, title}); y += height;
      }
      y += size;
    };
    add(edition?.masthead || 'The Pine Box Gazette', true);
    if (!edition) add('The next newspaper will appear here when it is published.');
    for (const article of (edition?.articles || [])) {
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
    paperHeight = Math.max(canvas.height, y + canvas.height * 0.3); scroll = 0;
  }

  async function showEdition(id) {
    if (!id || edition?.id === id) return;
    const request = ++editionRequest;
    const loaded = await bridge.get('/api/paper/' + encodeURIComponent(id));
    if (request !== editionRequest) return;
    edition = {...loaded, id}; layoutPaper();
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
    }
    if (deviceResult.status === 'fulfilled') {
      state = deviceResult.value; running = state.running;
      if (state.device && (canvas.width !== state.device.width || canvas.height !== state.device.height)) {
        canvas.width = state.device.width; canvas.height = state.device.height; layoutPaper();
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
    paintStatus();
  }

  function paintStatus() {
    if (!panel) return;
    const link = panel.querySelector('[data-lcd-status]');
    const dev = state?.device;
    link.textContent = localMessage && Date.now() < messageUntil ? localMessage
      : state?.error ? state.error
      : running && state?.device?.displayMode === 'avatar' ? 'Quanta avatar slideshow · tap the top-left corner for Pine Box'
      : running && state?.lastAck ? 'Streaming · ' + state.frames + ' drawn frames · last acknowledgment '
        + Math.max(0, Math.round((Date.now() - state.lastAck) / 1000)) + 's ago'
      : state?.connected ? 'Connected · ready to stream' : 'Disconnected · enter a display address or discover Quanta';
    panel.querySelector('[data-lcd-board]').textContent = dev
      ? dev.board + ' · ' + dev.width + '×' + dev.height + ' · firmware ' + dev.version + ' · ' + dev.identity : 'No display identified';
    const log = panel.querySelector('[data-lcd-log]');
    log.textContent = (state?.log || []).slice(-18).map((row) => new Date(row.at).toLocaleTimeString()
      + ' ' + row.kind + ': ' + row.detail).join('\n');
    const detail = panel.querySelector('[data-lcd-detail]');
    detail.textContent = selected ? (selected.name || selected.who || 'Booth') + ': ' + selected.text
      : 'Tap a visible dialogue bubble to select it. Tap the left/right screen edges for older/newer issues.';
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
    const dt = lastFrame ? Math.min(0.6, (timestamp - lastFrame) / 1000) : 0; lastFrame = timestamp;
    ctx.fillStyle = '#07121b'; ctx.fillRect(0, 0, width, height);
    const mode = state?.config?.mode || 'paper';
    if (mode === 'paper') {
      scroll = (scroll + dt * (state?.config?.speed || 12)) % paperHeight;
      ctx.save(); ctx.beginPath(); ctx.rect(0, 24, width, height - 24); ctx.clip();
      for (const base of [-scroll + 30, paperHeight - scroll + 30]) {
        for (const row of paperLines) {
          const y = base + row.y;
          if (y < -row.height || y > height + row.height) continue;
          if (row.image) { ctx.globalAlpha = 0.35; ctx.drawImage(row.image, 12, y, width - 24, row.height); ctx.globalAlpha = 1; continue; }
          ctx.font = row.font; ctx.fillStyle = row.title ? '#82969d' : '#4f6672'; ctx.fillText(row.text, 12, y);
        }
      }
      ctx.restore();
    }
    const top = mode === 'paper' ? Math.round(height * 0.36) : 28;
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
    if ((current?.id || '') !== currentId) { currentId = current?.id || ''; currentBegan = timestamp; }
    const visible = selected ? [selected] : current ? [current] : recent;
    const blocks = visible.map((row) => {
      const text = wrap(row.text, width - 38, size + 'px sans-serif');
      return {row, text, height: size * 1.35 * (text.length + 1) + 12};
    });
    const available = height - top - (selected ? 36 : 20);
    const full = blocks.reduce((sum, b) => sum + b.height, 0);
    // Slowly reveal every part of long messages; pin the selected message
    // until the operator closes it or chooses an action.
    const overflow = Math.max(0, full - available);
    const pan = overflow ? ((current ? timestamp - currentBegan : timestamp) / 70) % (overflow + available * 0.5) : 0;
    let y = top + size + 4 - Math.min(overflow, pan);
    ctx.save(); ctx.beginPath(); ctx.rect(8, top + 1, width - 16, available); ctx.clip();
    if (!blocks.length) {
      ctx.font = size + 'px sans-serif'; ctx.fillStyle = '#c3d4df';
      wrap('Waiting for booth activity.', width - 32, ctx.font).forEach((line) => {
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
    ctx.fillStyle = '#102636'; ctx.fillRect(0, 0, width, 24);
    ctx.font = 'bold ' + Math.max(11, size - 1) + 'px sans-serif'; ctx.fillStyle = '#9de3ef';
    const title = selected ? '× Close dialogue' : mode === 'paper' ? '‹ Gazette · ' + (edition?.id || 'waiting') + ' ›' : 'PINE BOX · LIVE BOOTH';
    ctx.fillText(title, 9, 16, width - 18);
    if (selected) {
      ctx.fillStyle = '#1d3a48'; ctx.fillRect(0, height - 30, width, 30);
      ctx.fillStyle = '#f4e5ab'; ctx.font = 'bold ' + size + 'px sans-serif';
      ctx.fillText(selected.lcdAudio ? '★ Favorite' : selected.lcdStatus, width * 0.21, height - 11, width * 0.55);
      if (selected.lcdAudio) ctx.fillText('↓ Download', width * 0.53, height - 11, width * 0.27);
    } else {
      ctx.fillStyle = '#87a2b2'; ctx.font = Math.max(9, size - 2) + 'px sans-serif';
      ctx.fillText(running ? 'Pine Box LCD · tap a line' : 'Preview · LCD not streaming', 10, height - 5);
    }
    if (localMessage && Date.now() < messageUntil) {
      ctx.fillStyle = '#244039'; ctx.fillRect(4, height - 49, width - 8, 18);
      ctx.fillStyle = '#edfff2'; ctx.font = Math.max(10, size - 2) + 'px sans-serif';
      ctx.fillText(localMessage, 10, height - 36, width - 20);
    }
  }

  async function favorite() {
    if (!selected) { note('Select a dialogue bubble first.'); return; }
    if (!selected.lcdAudio) { note('This booth entry has no aired audio yet.'); return; }
    if (liked.has(selected.id)) { note('This dialogue is already favorited.'); return; }
    const row = selected;
    await bridge.post('/api/dj/saved', {text: row.text, source: 'LCD favorite · booth ' + row.id});
    liked.add(row.id); note('Dialogue saved to the station’s favorites.');
  }
  async function download() {
    if (!selected) { note('Select a dialogue bubble first.'); return; }
    if (!selected.lcdAudio) { note('This booth entry has no aired audio yet.'); return; }
    const result = await bridge.lcdDownload(String(selected.id), Number(selected.air_at || selected.ts || 0));
    note(result.ok ? (result.exact ? 'Sample saved' : 'Surrounding audio saved') + (result.directory ? ' · ' + result.directory : '') : result.why);
  }
  async function touch(x, y, physical = false) {
    if (actionBusy) return;
    if (state?.device?.hostTouch && x < canvas.width * 0.2 && y < canvas.height * 0.25) {
      if (!physical) state = await bridge.lcdDisplayMode(state.device.displayMode === 'avatar' ? 'pine' : 'avatar');
      selected = null; paintStatus(); return;
    }
    if (physical && state?.device?.displayMode === 'avatar') return;
    if (selected) {
      if (y < 28) { selected = null; paintStatus(); return; }
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
    const box = canvas.getBoundingClientRect();
    touch((event.clientX - box.left) / box.width * canvas.width,
      (event.clientY - box.top) / box.height * canvas.height).catch((error) => note(error.message));
  };

  async function tick() {
    if (looping || (!running && !panel)) return;
    looping = true;
    try {
      const now = Date.now();
      if (now - lastPoll > 1000 && !polling) {
        lastPoll = now; polling = true;
        pollStation().catch((error) => note(error.message)).finally(() => { polling = false; });
      }
      draw(Date.now());
      if (running) {
        const sent = await bridge.lcdFrame(window.PineLcdFrame.encode(canvas, state?.device).jpeg);
        if (!sent.ok && !sent.busy) note(sent.why);
        if (Date.now() - lastEvents > 800) {
          lastEvents = Date.now();
          try {
            for (const event of (await bridge.lcdEvents()).events || []) {
              if (event.kind === 'touch') touch(event.x, event.y, true).catch((error) => note(error.message));
              else if (event.kind === 'nav' && state?.device?.displayMode !== 'avatar') stepEdition(event.direction === 'next' ? 1 : -1).catch((error) => note(error.message));
              else if (event.kind === 'mode') { if (state?.device) state.device.displayMode = event.mode; selected = null; note(event.mode === 'avatar' ? 'Quanta avatars · tap top-left for Pine Box' : 'Pine Box · tap top-left for avatars'); }
            }
          } catch (error) { note('LCD input: ' + error.message); }
        }
      }
    } catch (error) { note(error.message); }
    finally { looping = false; clearTimeout(timer); if (running || panel) timer = setTimeout(tick, 200); }
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
    for (const [value, label] of [['paper', 'Newspaper + live dialogue'], ['dialogue', 'Live dialogue only']]) {
      const option = node('option', label); option.value = value; mode.appendChild(option);
    }
    mode.value = state.config.mode; mode.onchange = async () => { state = await bridge.lcdConfigure({mode: mode.value}); selected = null; };
    options.appendChild(mode);
    const autoLabel = node('label', 'Resume on app launch '); const auto = node('input'); auto.type = 'checkbox'; auto.checked = state.config.autoStart;
    auto.onchange = async () => { state = await bridge.lcdConfigure({autoStart: auto.checked}); }; autoLabel.appendChild(auto); options.appendChild(autoLabel);
    const speedLabel = node('label', 'Scroll '); const speed = node('input'); speed.type = 'range'; speed.min = '2'; speed.max = '50'; speed.value = state.config.speed;
    speed.onchange = async () => { state = await bridge.lcdConfigure({speed: Number(speed.value)}); }; speedLabel.appendChild(speed); options.appendChild(speedLabel);
    card.appendChild(options);
    const status = node('p'); status.dataset.lcdStatus = ''; status.setAttribute('role', 'status'); card.appendChild(status);
    const board = node('p'); board.dataset.lcdBoard = ''; board.style.color = '#9bb5c5'; card.appendChild(board);
    const grid = node('div'); grid.style.cssText = 'display:grid;grid-template-columns:minmax(160px,1.25fr) minmax(160px,1fr);gap:16px';
    const preview = node('div'); preview.appendChild(canvas); grid.appendChild(preview);
    const details = node('div');
    const detail = node('p'); detail.dataset.lcdDetail = ''; detail.style.cssText = 'max-height:200px;overflow:auto;white-space:pre-wrap'; details.appendChild(detail);
    for (const [label, run] of [['‹ Older issue', () => stepEdition(-1)], ['Newer issue ›', () => stepEdition(1)],
      ['Follow newest', async () => { manualEdition = false; await showEdition(latestPaper); }], ['★ Favorite', favorite], ['↓ Download', download]]) {
      const button = node('button', label); button.style.margin = '3px'; button.onclick = () => Promise.resolve(run()).catch((error) => note(error.message)); details.appendChild(button);
    }
    const hint = node('p', 'Tap the top-left corner to switch between Quanta avatars and Pine Box. Tap the middle left/right edges for issues and dialogue bubbles for actions. Pine-compatible firmware preserves Quanta and its stored slideshow. Close this panel to keep streaming.');
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
    const controls = node('div'); controls.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap';
    const brightnessLabel = node('label', 'Brightness '); const brightness = node('input'); brightness.type = 'range'; brightness.min = '1'; brightness.max = '255'; brightness.value = '200';
    brightness.onchange = () => bridge.lcdControl('brightness', Number(brightness.value)).then((got) => { state = got; note('Brightness updated.'); }).catch((error) => note(error.message));
    brightnessLabel.appendChild(brightness); controls.appendChild(brightnessLabel);
    const rotation = node('select'); rotation.setAttribute('aria-label', 'Display rotation');
    for (let n = 0; n < 4; n++) { const option = node('option', 'Rotation ' + (n * 90) + '°'); option.value = String(n); rotation.appendChild(option); }
    rotation.onchange = () => bridge.lcdControl('rotation', Number(rotation.value)).then((got) => { state = got; lastPoll = 0; note('Rotation updated.'); }).catch((error) => note(error.message)); controls.appendChild(rotation);
    firmware.appendChild(controls); card.appendChild(firmware);
    const samples = node('p'); samples.dataset.lcdSampleDir = ''; card.appendChild(samples);
    const chooseSamples = node('button', 'Choose sound sample folder'); chooseSamples.onclick = async () => {
      try { state = await bridge.lcdSampleDirectory(); paintStatus(); } catch (error) { note(error.message); }
    }; card.appendChild(chooseSamples);
    shade.appendChild(card); shade.onclick = (event) => { if (event.target === shade) close.click(); };
    shade.onkeydown = (event) => { if (event.key === 'Escape') close.click(); };
    document.body.appendChild(shade); panel = shade; card.focus(); layoutPaper(); paintStatus(); lastPoll = 0; tick();
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
