// Pine Box LCD transport, speaking the installed Quanta firmware protocol.
const http = require('node:http');
const dns = require('node:dns').promises;
const dgram = require('node:dgram');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {jpegBudget} = require('./renderer/lcd-frame.js');
const {LcdStream} = require('./lcd-stream.cjs');

const LCD_DEFAULTS = {host: '', mode: 'paper', autoStart: false, speed: 12,
  quantaRoot: 'C:\\_tools\\Quanta', identity: '', paperStyle: 'broadsheet', chatOverlay: true,
  scrollEnabled: true, pausedCupboard: true, screensaverEnabled: false, screensaverSeconds: 300,
  galleryIntervalSeconds: 8};
const LCD_MODES = ['paper', 'dialogue', 'cupboard', 'gallery'];
function galleryIntervalSeconds(value) {
  const seconds = Number(value);
  return value !== null && value !== '' && Number.isFinite(seconds)
    ? Math.max(3, Math.min(60, Math.round(seconds))) : LCD_DEFAULTS.galleryIntervalSeconds;
}

function privateAddress(host) {
  const parts = String(host).split('.').map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;
  return parts[0] === 10 || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
    || (parts[0] === 192 && parts[1] === 168) || (parts[0] === 169 && parts[1] === 254);
}

function endpoint(value) {
  const text = String(value || '').trim();
  if (/^COM[1-9][0-9]{0,3}$/i.test(text)) return text.toUpperCase();
  if (!text || text.length > 250) throw new Error('Enter the Quanta display LAN address.');
  let u;
  try { u = new URL(text.includes('://') ? text : 'http://' + text); }
  catch { throw new Error('That display address is invalid.'); }
  if (u.protocol !== 'http:' || u.username || u.password || u.search || u.hash || u.pathname !== '/') {
    throw new Error('Use a LAN hostname or IP and optional port, without a path or credentials.');
  }
  if (!privateAddress(u.hostname) && !/^[a-z0-9-]+\.local$/i.test(u.hostname)) {
    throw new Error('The LCD connection is limited to LAN addresses and .local devices.');
  }
  return u.host;
}

function parseStatus(body) {
  const text = String(body || '').trim();
  if (!/^QUANTA-SCREEN ok\b/.test(text)) throw new Error('This host did not identify as a Quanta screen.');
  const fields = Object.fromEntries([...text.matchAll(/\b([a-z]+)=([^\s]+)/g)].map((m) => [m[1], m[2]]));
  const size = text.match(/\b(\d{2,4})x(\d{2,4})\b/);
  const identity = String(fields.id || fields.mac || '').toLowerCase();
  if (!fields.board || !/^[a-z0-9_]+$/.test(fields.board)
      || !/^(?:[a-f0-9]{2}:){5}[a-f0-9]{2}$/.test(identity) || !size) {
    throw new Error('Quanta identity, board or display dimensions are missing; no frames were sent.');
  }
  const width = Number(size[1]), height = Number(size[2]);
  if (width > 1280 || height > 1280 || Number(fields.jpeg) !== 1) {
    throw new Error('This firmware does not expose a supported JPEG display.');
  }
  return {identity, board: fields.board, version: Number(fields.ver || 0), width, height,
    uptime: Number(fields.up || 0), hostTouch: Number(fields.pine || 0) === 1,
    ota: fields.ota === undefined ? null : Number(fields.ota) === 1,
    displayMode: fields.display === 'avatar' ? 'avatar' : 'pine',
    pineProtocol: Number(fields.pineproto || 1), streamPort: Number(fields.stream) === 3233 ? 3233 : 0,
    maxJpeg: Math.max(0, Math.min(24576, Number(fields.maxjpg) || 0)),
    gestures: fields.gesture === '1', screensaver: fields.saver === '1', idleSeconds: Number(fields.idle || 0),
    cpuMHz: Number(fields.cpu || 0), wifiPowerSave: fields.sleep === undefined ? null : Number(fields.sleep),
    raw: text.slice(0, 1500)};
}

/**
 * WHY THE DISPLAY DID NOT ANSWER, in terms somebody can act on.
 *
 * Asked only after a request has already failed, and bounded to a second, so
 * the ordinary path pays nothing and a diagnosis never becomes a second hang.
 *
 * The distinction that matters: a board that ANSWERS PING but refuses every
 * port is not unreachable and not slow - its network stack is up and its
 * servers have died, and only a power cycle brings those back. Measured on
 * this display: 5 of 6 pings at 4-53ms with 80, 3232 and 3233 all shut.
 */
async function whyUnreachable(address) {
  try {
    const { execFile } = require('node:child_process');
    const alive = await new Promise((resolve) => {
      const done = (v) => resolve(v);
      const child = execFile(
        process.platform === 'win32' ? 'ping' : 'ping',
        process.platform === 'win32'
          ? ['-n', '1', '-w', '900', address]
          : ['-c', '1', '-W', '1', address],
        { timeout: 1500, windowsHide: true },
        (error) => done(!error));
      child.on('error', () => done(null));
    });
    if (alive === true) {
      return ' It answers the network but is refusing connections, which '
        + 'means its servers have stopped rather than the display being '
        + 'unreachable - power-cycle it.';
    }
    if (alive === false) {
      return ' It is not answering the network either, so it is powered off '
        + 'or not on this network.';
    }
  } catch (err) { /* a diagnosis that fails is not a second failure */ }
  return '';
}

async function deviceRequest(host, route, body = null, timeout = 4000) {
  if (/^COM/i.test(String(host))) throw new Error('USB displays require the USB transport.');
  const target = new URL('http://' + endpoint(host));
  let dnsTimer;
  const address = privateAddress(target.hostname) ? target.hostname : await Promise.race([
    dns.lookup(target.hostname, {family: 4}).then((row) => row.address),
    new Promise((_, reject) => { dnsTimer = setTimeout(() => reject(new Error('LCD hostname resolution timed out.')), timeout); }),
  ]).finally(() => clearTimeout(dnsTimer));
  if (!privateAddress(address)) throw new Error('The LCD hostname did not resolve to a LAN address.');
  return new Promise((resolve, reject) => {
    const raw = body == null ? null : Buffer.from(String(body), 'ascii');
    const req = http.request({hostname: address, port: target.port || 80, path: route,
      method: raw ? 'POST' : 'GET', agent: false,
      headers: raw ? {'content-type': 'application/octet-stream', 'content-length': raw.length} : {}}, (res) => {
      const chunks = []; let length = 0;
      res.on('data', (part) => {
        length += part.length;
        if (length > 65536) { req.destroy(new Error('Display response exceeded 64 KB.')); return; }
        chunks.push(part);
      });
      res.on('end', () => {
        const response = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode < 200 || res.statusCode >= 300) reject(new Error('Display HTTP ' + res.statusCode + ': ' + response.slice(0, 160)));
        else resolve(response);
      });
      res.on('error', reject);
    });
    // Socket inactivity alone does not bound TCP establishment or agent queues.
    const deadline = setTimeout(() => req.destroy(new Error('Display timed out.')), timeout);
    req.once('close', () => clearTimeout(deadline));
    req.setTimeout(timeout, () => req.destroy(new Error('Display timed out.')));
    /* SAY WHAT IT MEANS. "Display timed out" is true and cannot be acted on;
     * whether the board still answers ping decides between "power-cycle it"
     * and "it is off", and those are different evenings. */
    req.on('error', (err) => {
      whyUnreachable(address).then((why) => {
        reject(why ? new Error(String(err.message || err) + why) : err);
      }).catch(() => reject(err));
    });
    req.end(raw);
  });
}

// Quanta's own locator falls back to a /24 GET /status scan. Limit this to
// directly attached private subnets and never send commands during discovery.
function lanCandidates(interfaces = os.networkInterfaces()) {
  const bases = new Set();
  for (const [name, addresses] of Object.entries(interfaces)) {
    if (/virtual|vethernet|vmware|virtualbox|bluetooth|loopback/i.test(name)) continue;
    for (const row of addresses || []) {
      if (row.family === 'IPv4' && !row.internal && privateAddress(row.address)
          && !row.address.startsWith('169.254.')) bases.add(row.address.replace(/\.[^.]+$/, '.'));
    }
  }
  return [...bases].slice(0, 4).flatMap((base) => Array.from({length: 254}, (_, i) => base + (i + 1)));
}

// Ask only for the Quanta mDNS name. There is no subnet sweep and no request
// to unrelated HTTP services. QU requests a unicast answer to our socket.
function mdnsCandidates(timeout = 1800) {
  return new Promise((resolve) => {
    const found = new Set(); const socket = dgram.createSocket('udp4');
    let timer, finished = false;
    const done = () => { if (finished) return; finished = true; clearTimeout(timer);
      try { socket.close(); } catch {} resolve([...found]); };
    socket.on('error', done);
    socket.on('message', (packet) => {
      try {
        if (packet.length < 12) return;
        let offset = 12;
        const name = () => {
          let jumps = 0;
          while (offset < packet.length && jumps++ < 128) {
            const n = packet[offset++];
            if (n === 0) return;
            if ((n & 0xc0) === 0xc0) { offset++; return; }
            offset += n;
          }
          throw new Error('bad DNS name');
        };
        const questions = packet.readUInt16BE(4);
        const records = packet.readUInt16BE(6) + packet.readUInt16BE(8) + packet.readUInt16BE(10);
        for (let i = 0; i < questions; i++) { name(); offset += 4; }
        for (let i = 0; i < Math.min(records, 100); i++) {
          name();
          const kind = packet.readUInt16BE(offset), size = packet.readUInt16BE(offset + 8);
          offset += 10;
          if (kind === 1 && size === 4 && offset + 4 <= packet.length) {
            const address = [...packet.subarray(offset, offset + 4)].join('.');
            if (privateAddress(address)) found.add(address);
          }
          offset += size;
        }
      } catch {} // Ignore unrelated or malformed multicast responses.
    });
    socket.bind(0, () => {
      const header = Buffer.alloc(12); header.writeUInt16BE(1, 4);
      const labels = 'quanta-screen.local'.split('.').flatMap((label) => [Buffer.from([label.length]), Buffer.from(label)]);
      const query = Buffer.concat([header, ...labels, Buffer.from([0, 0, 1, 128, 1])]);
      socket.send(query, 5353, '224.0.0.251', (error) => { if (error) done(); });
    });
    timer = setTimeout(done, timeout);
  });
}

function firmwareReadiness(root, device) {
  const folder = path.resolve(String(root || LCD_DEFAULTS.quantaRoot));
  const firmware = path.join(folder, 'system', 'firmware', 'quanta-screen');
  const tool = path.join(folder, 'quanta.exe');
  let registry = {};
  try { registry = JSON.parse(fs.readFileSync(path.join(firmware, 'boards.json'), 'utf8')).boards || {}; } catch {}
  const board = device?.board || '';
  const profile = registry[board];
  const noOta = /PartitionScheme=(?:huge_app|app3M_fat9M_16MB)/.test(profile?.fqbnOptions || '');
  const networkFlash = !!profile?.define && !!device && device.version >= 49 && !noOta && device.ota !== false;
  return {available: fs.existsSync(tool), tool, folder: firmware, board,
    supported: !!profile?.define, expectedVersion: Number(profile?.fwVersion || 0),
    installedVersion: Number(device?.version || 0), networkFlash, flashReady: false,
    hostTouch: !!device?.hostTouch,
    boards: Object.entries(registry).filter(([, row]) => row.define).map(([id, row]) => ({id, label: row.label, touch: row.touch})),
    reason: noOta ? 'This board uses a partition layout without an OTA slot. Build and install through its identified USB port.'
      : networkFlash ? 'Quanta v49 supports Wi-Fi updates on port 3232. Build a matching Pine firmware first; the running partition must support OTA.'
      : 'Build Pine firmware and install through USB. Wi-Fi updates require Quanta v49 or newer and an OTA partition.'};
}

class LcdAgent {
  constructor({request = deviceRequest, discover = mdnsCandidates, candidates = lanCandidates, read = () => ({}), write = () => {}, streamFactory = (options) => new LcdStream(options)} = {}) {
    this.request = request; this.discoverAddresses = discover; this.read = read; this.write = write;
    this.candidates = candidates;
    this.device = null; this.host = ''; this.running = false; this.connected = false;
    this.busy = false; this.frameJob = null; this.sequence = 0; this.nextRetry = 0;
    this.frames = 0; this.failed = 0; this.lastAck = 0; this.error = ''; this.lastFrameBytes = 0;
    this.seen = new Set(); this.eventsPrimed = false; this.log = []; this.leaseUntil = 0;
    this.streamFactory = streamFactory; this.stream = null; this.timings = []; this.settingsKey = '';
    this.nextStatusPoll = 0;
  }
  note(kind, detail) { this.log.push({at: Date.now(), kind, detail: String(detail).slice(0, 500)});
    if (this.log.length > 100) this.log.splice(0, this.log.length - 100); }
  config() {
    const config = {...LCD_DEFAULTS, ...(this.read().lcd || {})};
    if (!LCD_MODES.includes(config.mode)) config.mode = LCD_DEFAULTS.mode;
    config.galleryIntervalSeconds = galleryIntervalSeconds(config.galleryIntervalSeconds);
    if (typeof config.chatOverlay !== 'boolean') config.chatOverlay = LCD_DEFAULTS.chatOverlay;
    return config;
  }
  configure(input = {}) {
    const next = this.config();
    if (input.host !== undefined) next.host = input.host ? endpoint(input.host) : '';
    if (input.mode !== undefined) next.mode = LCD_MODES.includes(input.mode) ? input.mode : 'paper';
    if (input.autoStart !== undefined) next.autoStart = !!input.autoStart;
    if (input.speed !== undefined) next.speed = Math.max(2, Math.min(50, Number(input.speed) || 12));
    if (input.quantaRoot !== undefined) next.quantaRoot = String(input.quantaRoot).slice(0, 1000);
    if (input.paperStyle !== undefined) next.paperStyle = input.paperStyle === 'tabloid' ? 'tabloid' : 'broadsheet';
    for (const key of ['chatOverlay','scrollEnabled','pausedCupboard','screensaverEnabled']) if (input[key] !== undefined) next[key] = !!input[key];
    if (input.screensaverSeconds !== undefined) next.screensaverSeconds = Math.max(15, Math.min(3600, Math.round(Number(input.screensaverSeconds) || 300)));
    if (input.galleryIntervalSeconds !== undefined) next.galleryIntervalSeconds = galleryIntervalSeconds(input.galleryIntervalSeconds);
    this.write({lcd: next}); return this.state();
  }
  state() { return {config: this.config(), connected: this.connected, running: this.running,
    device: this.device, host: this.host, busy: this.busy, frames: this.frames, failed: this.failed,
    lastAck: this.lastAck, error: this.error, lastFrameBytes: this.lastFrameBytes,
    frameBudget: this.frameBudget(), transport: this.binaryEnabled() ? 'binary-tcp' : /^COM/i.test(this.host) ? 'usb' : 'http-base64',
    timing: this.timings.at(-1) || null, timings: this.timings.slice(-60), log: this.log.slice(-40),
    firmware: firmwareReadiness(this.config().quantaRoot, this.device)}; }
  async probe(host, timeout = 4000) { const target = endpoint(host); const row = parseStatus(await this.request(target, '/status', null, timeout));
    return {...row, host: target}; }
  binaryEnabled() { return !/^COM/i.test(this.host) && this.device?.pineProtocol >= 2 && this.device?.streamPort === 3233; }
  frameBudget() { return this.binaryEnabled() ? this.device.maxJpeg || 24576 : jpegBudget({...this.device, streamPort: 0}); }
  async discover({scan = true} = {}) {
    const addresses = new Set(await this.discoverAddresses());
    const configured = this.config().host;
    if (configured && !/^COM/i.test(configured)) addresses.add(configured);
    addresses.add('quanta-screen.local');
    const candidates = [...addresses].slice(0, 12);
    const results = await Promise.allSettled(candidates.map((host) => this.probe(host)));
    const devices = results.filter((row) => row.status === 'fulfilled').map((row) => row.value);
    if (scan) {
      const pending = this.candidates().filter((host) => !addresses.has(host)); let index = 0;
      await Promise.all(Array.from({length: 24}, async () => {
        while (index < pending.length) {
          const host = pending[index++];
          try { devices.push(await this.probe(host, 650)); } catch {}
        }
      }));
    }
    this.note('discovery', devices.length + ' verified Quanta display(s)');
    return {devices: [...new Map(devices.map((row) => [row.identity, row])).values()],
      error: devices.length ? '' : 'No supported Quanta display answered on this LAN. Check its Wi-Fi or enter the IP shown on the LCD.'};
  }
  async connect(host, expectedIdentity = '') {
    this.stop();
    try {
      const device = await this.probe(host);
      if (expectedIdentity && device.identity !== expectedIdentity) throw new Error('The display identity changed; reconnect it manually before sending frames.');
      this.device = device; this.host = device.host; this.connected = true; this.error = '';
      this.seen.clear(); this.eventsPrimed = false;
      this.settingsKey = '';
      this.nextStatusPoll = Date.now() + 5000;
      this.write({lcd: {...this.config(), host: this.host, identity: device.identity}});
      this.note('connected', device.board + ' / ' + device.identity);
      return this.state();
    } catch (error) { this.connected = false; this.error = error.message; this.note('error', error.message); throw error; }
  }
  async start({automatic = false} = {}) {
    const cfg = this.config();
    if (automatic && !cfg.identity) throw new Error('Connect and identify an LCD before enabling automatic streaming.');
    await this.connect(cfg.host, automatic ? cfg.identity : '');
    // Drain historical touches before the first live frame, avoiding a stale
    // screen tap accidentally favouriting/downloading today's dialogue.
    await this.events();
    if (this.device.hostTouch) { await this.renewLease(); if (!automatic || this.device.displayMode !== 'avatar') await this.displayMode('pine'); }
    await this.syncSettings();
    this.running = true; this.note('started', 'Pine Box owns this frame producer');
    return this.state();
  }
  stop() { this.running = false; this.sequence++; this.stream?.close(); this.stream = null;
    this.note('stopped', 'Pine Box frame producer stopped'); return {running: false}; }
  async renewLease() {
    const response = await this.request(this.host, '/cmd', 'QCMD PINELEASE 15');
    if (!/^QACK pinelease 15\b/.test(String(response).trim())) throw new Error('Display did not acknowledge Pine touch control.');
    this.leaseUntil = Date.now() + 10000;
  }
  async displayMode(mode) {
    if (!this.device?.hostTouch) throw new Error('Install Pine-compatible firmware for top-left avatar switching. Quanta galleries and commands are preserved.');
    const target = mode === 'avatar' ? 'avatar' : 'pine';
    const response = await this.request(this.host, '/cmd', 'QCMD PINEMODE ' + (target === 'pine' ? 1 : 0));
    if (!String(response).startsWith('QACK pinemode ' + target)) throw new Error('LCD did not acknowledge its display mode.');
    this.device.displayMode = target; this.device.screensaver = false;
    if (target === 'avatar') {this.stream?.close();this.stream = null;}
    this.note('mode', target); return this.state();
  }
  async syncSettings() {
    if (!this.connected || this.device?.pineProtocol < 2) return this.state();
    const config = this.config(), seconds = config.screensaverEnabled ? config.screensaverSeconds : 0;
    const disabling = !seconds && this.device.idleSeconds > 0;
    const key = this.host + ':' + seconds;
    if (this.settingsKey !== key || this.device.idleSeconds !== seconds) {
      const response = await this.request(this.host, '/cmd', 'QCMD PINEIDLE ' + seconds);
      if (!String(response).startsWith('QACK pineidle ' + seconds)) throw new Error('LCD idle timer was not acknowledged.');
      this.settingsKey = key; this.device.idleSeconds = seconds;
    }
    if (disabling && this.device.screensaver) {
      const response = await this.request(this.host, '/cmd', 'QCMD PINESAVER 0');
      if (!String(response).startsWith('QACK pinesaver 0')) throw new Error('LCD screensaver wake was not acknowledged.');
      this.device.screensaver = false; this.device.displayMode = 'pine';
    }
    return this.state();
  }
  async control(action, value) {
    if (!this.connected) throw new Error('Connect a Quanta LCD first.');
    const device = await this.probe(this.host);
    if (device.identity !== this.device.identity) throw new Error('LCD identity changed; reconnect before changing display settings.');
    let command, ack;
    if (action === 'brightness') { command = 'QCMD BL ' + Math.max(0, Math.min(255, Math.round(Number(value) || 0))); ack = /^QACK bl /; }
    else if (action === 'rotation' && [0, 1, 2, 3].includes(Number(value))) { command = 'QCMD ROT ' + Number(value); ack = /^QACK rot /; }
    else if (action === 'screensaver' && device.pineProtocol >= 2) { command = 'QCMD PINESAVER ' + (value ? 1 : 0); ack = /^QACK pinesaver [01]\b/; }
    else if (action === 'idle' && device.pineProtocol >= 2) { const seconds = Number(value) ? Math.max(15, Math.min(3600, Math.round(Number(value)))) : 0; command = 'QCMD PINEIDLE ' + seconds; ack = new RegExp('^QACK pineidle ' + seconds + '\\b'); }
    else throw new Error('Unsupported LCD control.');
    const result = await this.request(this.host, '/cmd', command);
    if (!ack.test(String(result))) throw new Error('LCD control was not acknowledged.');
    this.device = await this.probe(this.host); this.note('control', result);
    return this.state();
  }
  async frame(data) {
    if (!this.running) return {ok: false, why: 'LCD streaming is stopped.'};
    if (this.busy) return {ok: false, busy: true, why: 'Previous frame has not acknowledged yet.'};
    this.busy = true; const sequence = this.sequence, started = Date.now();
    try {
      if (!this.connected) {
        if (Date.now() < this.nextRetry) return {ok: false, why: this.error};
        this.nextRetry = Date.now() + 5000;
        let found;
        try { found = await this.probe(this.host); }
        catch {
          found = (await this.discover()).devices.find((row) => row.identity === this.device?.identity);
          if (!found) throw new Error('The remembered LCD is offline; reconnecting when it returns.');
          this.host = found.host;
          this.write({lcd: {...this.config(), host: this.host}});
        }
        if (found.identity !== this.device?.identity) throw new Error('Display identity changed; reconnect manually.');
        this.device = found; this.connected = true; this.settingsKey = ''; this.leaseUntil = 0;
        await this.syncSettings();
      }
      const encoded = String(data || '').replace(/^data:image\/jpeg;base64,/, '');
      if (!encoded || encoded.length > 1400000 || !/^[A-Za-z0-9+/=]+$/.test(encoded)) throw new Error('Invalid or oversized LCD JPEG.');
      const jpeg = Buffer.from(encoded, 'base64');
      this.lastFrameBytes = jpeg.length;
      if (jpeg.length > this.frameBudget()) throw new Error('LCD JPEG is ' + jpeg.length
        + ' bytes; this display accepts at most ' + this.frameBudget() + ' bytes per frame.');
      if (jpeg.length < 4 || jpeg[0] !== 255 || jpeg[1] !== 216 || jpeg.at(-2) !== 255 || jpeg.at(-1) !== 217) throw new Error('Frame is not a complete JPEG.');
      if (!this.running || sequence !== this.sequence) return {ok: false, why: 'Producer was stopped.'};
      if (this.device.hostTouch && Date.now() >= this.leaseUntil) await this.renewLease();
      if (this.device.displayMode === 'avatar') return {ok: true, avatar: true};
      const wireAt = Date.now();
      if (this.binaryEnabled() && !this.stream) this.stream = this.streamFactory({host: this.host, identity: this.device.identity, port: this.device.streamPort});
      const response = this.binaryEnabled() ? await this.stream.frame(jpeg) : await this.request(this.host, '/image', encoded);
      if (/^QSKIP mode\b/.test(String(response))) return {ok: true, skipped: true};
      if (!/^QACK img [1-9]\d*x[1-9]\d*\b/.test(String(response).trim())) throw new Error('Display did not acknowledge a drawn image: ' + String(response).slice(0, 120));
      if (sequence !== this.sequence) return {ok: false, why: 'Producer stopped while the frame was in flight.'};
      this.frames++; this.lastAck = Date.now(); this.error = ''; this.lastFrame = encoded;
      const field = (name) => Number(String(response).match(new RegExp('\\b' + name + '=(\\d+)'))?.[1]) || 0;
      this.timings.push({at: this.lastAck, totalMs: this.lastAck - started, wireMs: this.lastAck - wireAt,
        decodeAndDrawMs: field('dec'), flushMs: field('draw'), receiveMs: field('rx'), jpegBytes: jpeg.length});
      if (this.timings.length > 60) this.timings.shift();
      if (this.frames === 1 || this.frames % 100 === 0) this.note('drawn', response);
      return {ok: true, acknowledgment: String(response), frames: this.frames, at: this.lastAck};
    } catch (error) {
      this.stream?.close(); this.stream = null;
      if (sequence !== this.sequence) return {ok: false, why: 'Producer stopped while the frame was in flight.'};
      if (this.device?.displayMode === 'avatar' && /LCD (?:frame|binary) connection (?:closed|ended)/.test(error.message)) return {ok: true, avatar: true};
      this.failed++; this.connected = false; this.error = error.message
        + (this.lastFrameBytes ? ' (JPEG ' + this.lastFrameBytes + ' bytes)' : '');
      this.note('error', error.message); return {ok: false, why: error.message};
    } finally { this.busy = false; }
  }
  async events() {
    const events = [];
    // Avatar mode produces no host JPEGs. Maintain identity, mode and the touch
    // lease here as well, so a reboot cannot strand the renderer in cached avatar.
    if (this.running && this.device && Date.now() >= this.nextStatusPoll && !this.busy) {
      this.nextStatusPoll = Date.now() + 5000;
      const previous = this.device, wasConnected = this.connected;
      try {
        const found = await this.probe(this.host, 2500);
        if (found.identity !== previous.identity) throw new Error('LCD identity changed; reconnect manually.');
        this.device = found; this.connected = true;
        if (!wasConnected || found.uptime < previous.uptime) {
          this.leaseUntil = 0; this.settingsKey = ''; this.eventsPrimed = false; this.seen.clear();
          this.stream?.close();this.stream = null;
        }
        await this.syncSettings();
        if (previous.displayMode !== this.device.displayMode) events.push({kind: 'mode', mode: this.device.displayMode});
        if (previous.screensaver && !this.device.screensaver) events.push({kind: 'wake'});
        this.error = '';
      } catch (error) {this.connected = false;this.error = error.message;throw error;}
    }
    if (!this.connected) return {events, device: this.device};
    if (this.running && this.device.hostTouch && Date.now() >= this.leaseUntil) await this.renewLease();
    let text;
    try {text = await this.request(this.host, '/events', null, 2500);}
    catch (error) {this.connected = false;this.error = error.message;this.nextStatusPoll = Date.now() + 1000;throw error;}
    const lines = String(text).trim().split(/\r?\n/).filter(Boolean).slice(-100);
    for (const line of lines) {
      if (this.eventsPrimed && !this.seen.has(line)) {
        const touch = line.match(this.device?.pineProtocol >= 2 ? /^(\d+) TOUCH tap (\d+) (\d+)/ : /^(\d+) TOUCH down (\d+) (\d+)/);
        const nav = line.match(/^(\d+) NAV (next|prev)/);
        const mode = line.match(/^(\d+) PINEMODE (pine|avatar)/);
        const swipe = line.match(/^(\d+) SWIPE (down|up) (\d+) (\d+)/);
        const wake = line.match(/^(\d+) PINEWAKE\b/), saver = line.match(/^(\d+) PINESAVER 1\b/);
        if (touch) events.push({kind: 'touch', at: Number(touch[1]), x: Number(touch[2]), y: Number(touch[3])});
        else if (nav) events.push({kind: 'nav', at: Number(nav[1]), direction: nav[2]});
        else if (mode) { this.device.displayMode = mode[2]; if (mode[2] === 'avatar') {this.stream?.close();this.stream = null;} events.push({kind: 'mode', mode: mode[2]}); }
        else if (swipe) events.push({kind: 'swipe', direction: swipe[2], at: Number(swipe[1]), x: Number(swipe[3]), y: Number(swipe[4])});
        else if (wake) {this.device.screensaver = false; events.push({kind: 'wake', at: Number(wake[1])});}
        else if (saver) {this.device.screensaver = true; events.push({kind: 'screensaver', active: true, at: Number(saver[1])});}
      }
    }
    this.seen = new Set(lines); this.eventsPrimed = true;
    for (const event of events) this.note('input', JSON.stringify(event));
    return {events, device: this.device};
  }
}

module.exports = {LcdAgent, endpoint, privateAddress, parseStatus, deviceRequest, mdnsCandidates, lanCandidates,
  firmwareReadiness, LCD_DEFAULTS};
