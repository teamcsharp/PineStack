const {spawn, execFile} = require('node:child_process');
const path = require('node:path');
const {promisify} = require('node:util');
const {scriptFile} = require('./lcd-runtime.cjs');
const execute = promisify(execFile);

async function usbDisplays() {
  if (process.platform !== 'win32') return [];
  const {stdout} = await execute('powershell.exe', ['-NoProfile', '-Command',
    "@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match '\\(COM\\d+\\)' -and $_.DeviceID -match 'VID_(1A86&PID_7523|10C4|303A)' } | ForEach-Object { if ($_.Name -match '\\((COM\\d+)\\)') { @{host=$Matches[1];board='USB LCD candidate';transport='usb';name=$_.Name} } }) | ConvertTo-Json -Compress"],
    {windowsHide: true, timeout: 12000});
  const data = JSON.parse(stdout.trim() || '[]'); return Array.isArray(data) ? data : [data];
}

class LcdSerial {
  constructor() { this.child = null; this.port = ''; this.identity = ''; this.selfIdentified = false; this.events = []; this.pending = null; this.tail = Promise.resolve(); }
  async open(port, identity) {
    if (!/^COM[1-9][0-9]{0,3}$/.test(port)) throw new Error('Invalid LCD COM port.');
    if (!(await usbDisplays()).some((row) => row.host === port)) throw new Error('The selected USB display is missing or protected.');
    if (this.child && this.port === port) return;
    await this.close(); this.port = port; this.identity = String(identity || '').toLowerCase(); this.events = []; this.requireSelfIdentity = false;
    const child = this.child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptFile('lcd-serial.ps1'), '-Port', port],
      {windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
    await new Promise((resolve, reject) => {
      let buffer = '', ready = false;
      const timer = setTimeout(() => { reject(new Error('USB display did not open.')); this.close(); }, 12000);
      child.stdout.on('data', (chunk) => {
        if (this.child !== child) return;
        buffer += String(chunk); const lines = buffer.split(/\r?\n/); buffer = lines.pop();
        for (const raw of lines) {
          let row; try { row = JSON.parse(raw); } catch { continue; }
          if (row.ready) { ready = true; clearTimeout(timer); resolve(); }
          if (row.error) { if (!ready) { clearTimeout(timer); reject(new Error(row.error)); } this.fail(row.error); }
          if (row.line) {
            if (/^QEVT /.test(row.line)) {
              this.events.push(Date.now() + ' ' + row.line.slice(5)); this.events = this.events.slice(-100);
            }
            if (this.pending?.match.test(row.line)) { const pending = this.pending; this.pending = null; clearTimeout(pending.timer); pending.resolve(row.line); }
          }
        }
      });
      child.on('error', (error) => { clearTimeout(timer); reject(error); if (this.child === child) this.fail(error.message); });
      child.on('close', () => { clearTimeout(timer); if (!ready) reject(new Error('USB bridge closed.')); if (this.child === child) { this.child = null; this.fail('USB display disconnected.'); } });
    });
  }
  fail(message) { if (this.pending) { const job = this.pending; this.pending = null; clearTimeout(job.timer); job.reject(new Error(message)); } }
  close() {
    const child = this.child; this.child = null; this.fail('USB bridge closed.');
    if (!child || child.exitCode !== null) return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(() => { if (child.exitCode === null) child.kill(); }, 1500);
      child.once('close', () => { clearTimeout(timer); resolve(); });
      try { child.stdin.end('{"close":true}\n'); } catch { child.kill(); }
    });
  }
  request(host, route, body = null, timeout = 4000) {
    const task = async () => {
      if (!this.child && host === this.port && this.selfIdentified) { await this.open(host, this.identity); this.requireSelfIdentity = true; }
      for (let attempt = 0; ; attempt++) {
        try { return await this._request(host, route, body, timeout); }
        catch (error) { if (route !== '/status' || attempt >= 2 || !/timed out/.test(error.message)) throw error; }
      }
    };
    const job = this.tail.then(task, task); this.tail = job.catch(() => {}); return job;
  }
  async _request(host, route, body, timeout) {
    if (!this.child || host !== this.port) throw new Error('Connect this USB LCD first.');
    if (route === '/events') return this.events.join('\n');
    let message, match;
    if (route === '/status') { message = {command: 'QCMD STAT'}; match = /^QINFO /; }
    else if (route === '/image') { message = {jpeg: body}; match = /^QACK (?:img|skip|err) /; }
    else if (route === '/cmd' && /^QCMD [A-Z]+(?: [0-9]+)?$/.test(body)) {
      message = {command: body}; match = new RegExp('^QACK ' + body.split(' ')[1].toLowerCase() + ' ');
    } else throw new Error('Unsupported USB LCD request.');
    const line = await new Promise((resolve, reject) => {
      this.pending = {resolve, reject, match, timer: setTimeout(() => this.fail('USB LCD acknowledgment timed out.'), timeout)};
      this.child.stdin.write(JSON.stringify(message) + '\n', (error) => { if (error) this.fail(error.message); });
    });
    if (route !== '/status') return line;
    const reportedIdentity = line.match(/\bid=([^ ]+)/)?.[1];
    if (this.requireSelfIdentity && !reportedIdentity) throw new Error('USB firmware does not report its identity; identify and reconnect it manually.');
    const mac = reportedIdentity || this.identity;
    this.selfIdentified = /\bid=/.test(line);
    if (!mac) throw new Error('Identify this USB LCD before connecting.');
    return 'QUANTA-SCREEN ok ' + line.slice(6).replace(/\bres=/, '') + (/\bid=/.test(line) ? '' : ' id=' + mac);
  }
}
module.exports = {LcdSerial, usbDisplays};
