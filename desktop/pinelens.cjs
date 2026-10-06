'use strict';
const {randomUUID} = require('node:crypto');
const {spawn} = require('node:child_process');
const path = require('node:path');
const os = require('node:os');

function normalizeCrop(crop) {
  if (crop == null) return null;
  const {x, y, width, height} = crop;
  if (![x, y, width, height].every(Number.isFinite) || x < 0 || y < 0 ||
      width < .005 || height < .005 || x + width > 1.000001 || y + height > 1.000001) {
    throw new Error('Draw a rectangle inside the display');
  }
  return {x, y, width, height};
}

function mapPoint(region, x, y) {
  if (![x, y].every(Number.isFinite) || x < 0 || y < 0 || x > 1 || y > 1) throw new Error('Outside the lens');
  return {x: Math.round(region.x + x * (region.width - 1)),
    y: Math.round(region.y + y * (region.height - 1))};
}

class PineLens {
  constructor({electron, read, write, request, window, python, exportFolder, upload}) {
    Object.assign(this, {electron, read, write, request, window, python, exportFolder, upload});
    this.ring = new (require('./pinelens-recording.cjs').LensRecording)();
    this.exportJobs = new Set();
    this.recording = !!(read().pineLens || {}).crop;
    const saved = read().pineLens || {};
    this.id = saved.id || randomUUID();
    write({pineLens: {...saved, id: this.id}});
    this.session = randomUUID();
    this.revision = randomUUID();
    this.full = false;
    this.region = null;
    this.ready = false;
    this.error = '';
    this.closed = false;
    this.active = false;
    this.pressedAt = 0;
    this.startInput();
  }

  startInput() {
    this.worker = spawn(this.python(), ['-u', path.join(__dirname, 'pinelens-input.py')], {windowsHide: true});
    this.worker.stdin.on('error', err => {this.ready = false; this.error = err.message;});
    let pending = '';
    this.worker.stdout.on('data', bytes => {
      pending += bytes.toString();
      const rows = pending.split('\n'); pending = rows.pop();
      for (const line of rows) {
        try { const status = JSON.parse(line); if (status.ready) this.ready = true;
          if (status.error) this.error = status.error; } catch {}
      }
    });
    this.worker.stderr.on('data', bytes => { this.error = bytes.toString().slice(0, 200); });
    this.worker.on('error', err => { this.ready = false; this.error = err.message; });
    this.worker.on('exit', () => { this.ready = false; });
  }

  state() {
    return {id: this.id, name: os.hostname(), control: this.ready, error: this.error,
      crop: (this.read().pineLens || {}).crop || null, display: this.display?.id,
      revision: this.revision, full: this.full, recording: !!this.recording,
      history: this.ring?.state(), export: this.exportStatus};
  }

  async capture(preview = false) {
    const {screen, desktopCapturer} = this.electron;
    const saved = this.read().pineLens || {};
    const owner = this.window();
    if (!owner || owner.isDestroyed()) throw new Error('Pine window is closed');
    const displays = screen.getAllDisplays();
    const display = saved.crop && !this.full && !preview
      ? displays.find(d => String(d.id) === String(saved.display))
      : screen.getDisplayMatching(owner.getBounds());
    if (!display) throw new Error('The saved lens display is disconnected. Draw a new lens or choose Full display.');
    const bounds = display.bounds;
    const sources = await desktopCapturer.getSources({types: ['screen'],
      thumbnailSize: {width: Math.round(bounds.width * display.scaleFactor), height: Math.round(bounds.height * display.scaleFactor)}});
    const source = sources.find(s => s.display_id === String(display.id)) ||
      (sources.length === 1 && displays.length === 1 ? sources[0] : null);
    if (!source || source.thumbnail.isEmpty()) throw new Error('This display could not be captured');
    const size = source.thumbnail.getSize();
    const crop = preview || this.full ? null : normalizeCrop(saved.crop || null);
    const pixel = crop ? {x: Math.round(crop.x * size.width), y: Math.round(crop.y * size.height),
      width: Math.max(1, Math.floor(crop.width * size.width)), height: Math.max(1, Math.floor(crop.height * size.height))}
      : {x: 0, y: 0, ...size};
    pixel.width = Math.min(pixel.width, size.width - pixel.x);
    pixel.height = Math.min(pixel.height, size.height - pixel.y);
    let image = source.thumbnail.crop(pixel);
    const capturedSize = image.getSize();
    const reduction = Math.min(1, 1600 / capturedSize.width, 1200 / capturedSize.height);
    if (reduction < 1) image = image.resize({width: Math.round(capturedSize.width * reduction), height: Math.round(capturedSize.height * reduction)});
    const dipRegion = crop ? {x: bounds.x + crop.x * bounds.width, y: bounds.y + crop.y * bounds.height,
      width: crop.width * bounds.width, height: crop.height * bounds.height} : {...bounds};
    // Windows' input worker is DPI aware. X11 coordinates are native pixels.
    const physical = screen.dipToScreenPoint ? screen.dipToScreenPoint({x: Math.round(dipRegion.x), y: Math.round(dipRegion.y)})
      : {x: Math.round(dipRegion.x * display.scaleFactor), y: Math.round(dipRegion.y * display.scaleFactor)};
    const region = {...physical, width: Math.round(dipRegion.width * display.scaleFactor),
      height: Math.round(dipRegion.height * display.scaleFactor)};
    if (!preview) {
      const signature = JSON.stringify(region);
      if (signature !== this.signature) { this.release(); this.revision = randomUUID(); this.signature = signature; }
      this.region = region; this.display = display;
    }
    return {id: randomUUID(), jpeg: image.toJPEG(65).toString('base64'), display: display.id};
  }

  save(value) {
    const crop = normalizeCrop(value.crop);
    const saved = this.read().pineLens || {};
    if (crop && !this.electron.screen.getAllDisplays().some(d => String(d.id) === String(value.display))) {
      throw new Error('The selected display is disconnected');
    }
    this.release();
    this.write({pineLens: {...saved, crop, display: crop ? value.display : null}});
    this.full = false; this.revision = randomUUID(); this.region = null;
    return this.state();
  }

  send(cmd) {
    if (this.ready && this.worker.stdin.writable) this.worker.stdin.write(JSON.stringify(cmd) + '\n');
  }
  release() { this.send({type: 'release'}); this.pressedAt = 0; }

  command(cmd) {
    if (cmd.type === 'full' || cmd.type === 'lens') {
      this.release(); this.full = cmd.type === 'full'; this.revision = randomUUID(); this.region = null; return;
    }
    if (!this.region || cmd.revision !== this.revision) { this.release(); return; }
    if (cmd.type === 'pointer') {
      cmd = {...cmd, ...mapPoint(this.region, cmd.x, cmd.y)};
      if (cmd.action === 'down') this.pressedAt = Date.now();
      if (cmd.action === 'up') this.pressedAt = 0;
    }
    this.send(cmd);
  }

  async round() {
    if (this.closed) return;
    let delay = 2000;
    try {
      if (this.active) this.recording = true;
      const frame = this.active || this.recording ? await this.capture() : undefined;
      if (frame) this.ring.add(frame);
      if (frame && this.ready) this.error = '';
      const out = await this.request('/api/pinelens/hosts/' + this.id + '/exchange',
        {session: this.session, info: this.state(), ...(frame ? {frame} : {})});
      this.active = !!out.active;
      if (!this.active || (this.pressedAt && Date.now() - this.pressedAt > 5000)) this.release();
      for (const cmd of out.commands || []) this.command(cmd);
      for (const job of out.exports || []) this.exportHistory(job);
      delay = this.active ? 120 : this.recording ? 250 : 2000;
    } catch (err) {
      this.error = err.message; this.release(); this.region = null; this.revision = randomUUID();
      // Still advertise capture failures so the tablet can switch to full display.
      try {
        const out = await this.request('/api/pinelens/hosts/' + this.id + '/exchange', {session: this.session, info: this.state()});
        for (const cmd of out.commands || []) this.command(cmd);
        this.active = !!out.active;
      } catch {}
    }
    if (!this.closed) this.timer = setTimeout(() => this.round(), delay);
  }

  async exportHistory(job) {
    if (this.exportJobs.has(job.id)) {
      if (this.exportStatus?.id === job.id && this.exportStatus.state !== 'exporting') {
        try { await this.request('/api/pinelens/hosts/' + this.id + '/export-done',
          {session: this.session, ...this.exportStatus}); } catch {}
      }
      return;
    }
    this.exportJobs.add(job.id);
    this.exportStatus = {id: job.id, state: 'exporting'};
    try {
      const made = await this.ring.export(job.seconds, this.exportFolder(), this.read().ffmpeg);
      const uploaded = await this.upload(made);
      this.exportStatus = {id: job.id, state: 'done', seconds: made.seconds,
        partial: made.partial, path: made.path, uploaded};
    } catch (err) { this.exportStatus = {id: job.id, state: 'failed', error: err.message}; }
    try { await this.request('/api/pinelens/hosts/' + this.id + '/export-done',
      {session: this.session, ...this.exportStatus}); } catch {}
  }
  close() { this.closed = true; clearTimeout(this.timer); this.release(); this.worker?.stdin.end(); this.ring?.close(); }
}
module.exports = {PineLens, normalizeCrop, mapPoint};
