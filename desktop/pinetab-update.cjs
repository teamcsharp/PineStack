/* [pinetab-update] THE TABLET BUTTON: is the PineTab out of date, and one press to
 * find it, build it, install it and look after it.
 *
 * "Put an icon of a tablet here that represents updating the tablet. Have it pulse
 * if the tablet is out of date ... if I click the button, have it locate the tablet
 * and update the firmware with the latest version after compiling it, if there's a
 * version that needs to be pushed ... any and all troubleshooting whenever it comes
 * to the tablet."                                          - the operator, 2026-10-01
 *
 * OUT OF DATE means the APK on the tablet was built from different inputs than the
 * source would build now: deploy.sh stamps every build (tools/pinetab-stamp.sh, the
 * versionName 1.0.0+<stamp>), the kiosk says it in its user agent, and
 * pinetab-stamp.cjs computes the stamp the source would get. The shared views ship
 * INSIDE the APK, so a renderer change makes the tablet stale too.
 *
 * THE UPDATE is deploy.sh and nothing else - it is the only road that platform-signs
 * (a debug-signed APK silently loses MODIFY_AUDIO_ROUTING and DUMP), verifies every
 * asset, runs the read-only preflight and releases the replay encoder before the
 * install ([venc-safe]). This module only finds the tablet, connects adb, stops the
 * desk's own screenrecord first, runs the script through Git Bash with its output
 * streamed to the button's panel ("pinetab-progress"), and checks the stamp after.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFile } = require('child_process');
const { stampOf } = require('./pinetab-stamp.cjs');
const { stampAsync } = require('./pinetab-stamp-async.cjs');

const crypto = require('crypto');
const PKG = 'com.pinebox.kiosk';

function exists(p) { try { return !!p && fs.existsSync(p); } catch (e) { return false; } }

/* A Windows path as Git Bash takes it: \\host\share\x -> //host/share/x, C:\x -> /c/x */
function bashPath(p) {
  const s = String(p || '');
  if (process.platform !== 'win32') return s;
  if (s.startsWith('\\\\')) return '//' + s.slice(2).replace(/\\/g, '/');
  const m = /^([A-Za-z]):[\\/](.*)$/.exec(s);
  return m ? '/' + m[1].toLowerCase() + '/' + m[2].replace(/\\/g, '/') : s.replace(/\\/g, '/');
}

function findBash(configured) {
  if (process.platform !== 'win32') return 'bash';
  const local = process.env.LOCALAPPDATA || '';
  const pf = process.env.ProgramFiles || 'C:\\Program Files';
  for (const p of [configured, path.join(pf, 'Git', 'bin', 'bash.exe'), path.join(pf, 'Git', 'usr', 'bin', 'bash.exe'),
    path.join(local, 'Programs', 'Git', 'bin', 'bash.exe'), 'C:\\_tools\\Git\\bin\\bash.exe']) {
    if (exists(p)) return p;
  }
  return '';
}

/* deploy.sh's own adb first, so the button and the script talk to one server */
function findAdb(configured, fallback) {
  if (process.platform !== 'win32') return configured || 'adb';
  for (const p of [configured, 'C:\\_tools\\android-sdk\\platform-tools\\adb.exe', fallback]) {
    if (exists(p)) return p;
  }
  return fallback || 'adb.exe';
}

function run(exe, args, timeout) {
  return new Promise((resolve) => {
    execFile(exe, args, { timeout: timeout || 30000, maxBuffer: 16 * 1024 * 1024, windowsHide: true },
      (error, stdout, stderr) => resolve({ ok: !error, code: error ? (error.code || 1) : 0,
        text: String(stdout || '') + String(stderr || '') }));
  });
}

class PinetabUpdate {
  /* deps: agentRoot(), getJson(route), postJson(route, body), send(channel, data),
   * glassStop(), wake(), readConfig(), adbFallback() */
  constructor(deps) {
    this.d = deps;
    this.job = null;
    this.last = null;
    this.ready = null;
  }

  cfg() { try { return this.d.readConfig() || {}; } catch (e) { return {}; } }
  adb() { return findAdb(this.cfg().pinetabAdb, this.d.adbFallback ? this.d.adbFallback() : ''); }
  emit(step, line, state) {
    const ev = { at: Date.now(), step: String(step || ''), line: String(line || ''), state: state || 'run' };
    if (this.job) this.job.log.push(ev);
    /* [tablet-update-ask] on disk too: the panel's log dies with the window, and a
     * build that stops after fifteen seconds has to be readable afterwards. */
    try {
      fs.appendFileSync(path.join(os.tmpdir(), 'pinetab-update.log'),
        new Date(ev.at).toISOString() + ' [' + ev.state + '] ' + ev.step + ': ' + ev.line + '\n');
    } catch (e) { /* a log is never worth failing the update for */ }
    try { this.d.send('pinetab-progress', ev); } catch (e) { /* the window may be gone */ }
  }

  wanted(fresh = false) {
    const root = this.d.agentRoot();
    return (this.d.sampleStamp || stampAsync)(root, path.join(root, 'desktop', 'renderer'), {fresh});
  }

  async look() {
    try { return await this.d.getJson('/api/tablet/look'); } catch (e) { return { why: e.message }; }
  }

  async installedByAdb(dev) {
    const got = await run(this.adb(), ['-s', dev, 'shell', 'dumpsys', 'package', PKG], 20000);
    const m = /versionName=(\S+)/.exec(got.text);
    return { name: m ? m[1] : '', stamp: stampOf(m ? 'versionName=' + m[1] : '') };
  }

  /* Is the tablet out of date? Cheap: the station's last sight of the kiosk (its user
   * agent carries the stamp); adb only when asked. */
  async check(opts) {
    const out = { at: Date.now() };
    try {
      const w = await this.wanted(!!(opts && opts.adb));
      out.wanted = w.stamp;
      out.files = w.files;
    } catch (e) {
      out.wanted = '';
      out.why = 'the source could not be read: ' + e.message;
    }
    const look = await this.look();
    out.host = look.host || '';
    out.port = look.port || 5555;
    out.on_network = !!look.on_network;
    out.adb_open = !!(look.adb_port_open || (look.adb && look.adb.open));
    const agent = (look.seen && look.seen.agent) || '';
    out.installed = stampOf(agent);
    out.via = out.installed ? 'its user agent' : '';
    if (!out.installed && opts && opts.adb && out.host) {
      const dev = out.host + ':' + out.port;
      await run(this.adb(), ['connect', dev], 15000);
      const got = await this.installedByAdb(dev);
      out.installed = got.stamp;
      out.installed_name = got.name;
      out.via = got.name ? 'adb' : '';
    }
    out.stale = !!(out.wanted && out.installed !== out.wanted);
    out.say = !out.wanted ? (out.why || 'cannot read the source')
      : !out.installed ? 'the tablet\'s build carries no stamp yet - one update brings it in line'
      : out.stale ? 'the tablet is on ' + out.installed + '; the source builds ' + out.wanted
      : 'the tablet is up to date (' + out.installed + ')';
    out.busy = !!(this.job && this.job.running);
    this.last = out;
    return out;
  }

  async locate() {
    this.emit('locate', 'asking the station where the tablet is');
    let look = await this.look();
    if (!look.on_network) {
      this.emit('locate', 'not where the station last saw it - sweeping the network');
      try { await this.d.getJson('/api/tablet/find?deep=1'); } catch (e) { /* the look says what it found */ }
      look = await this.look();
    }
    if (!look.host) throw new Error('the station does not know where the tablet is: ' + (look.why || look.verdict || 'no host'));
    const dev = look.host + ':' + (look.port || 5555);
    this.emit('locate', 'the tablet is at ' + dev + (look.verdict ? ' - ' + look.verdict : ''), 'ok');
    this.emit('connect', 'connecting adb to ' + dev);
    const c = await run(this.adb(), ['connect', dev], 20000);
    this.emit('connect', c.text.trim() || (c.ok ? 'connected' : 'adb connect failed'));
    const st = await run(this.adb(), ['-s', dev, 'get-state'], 10000);
    if (st.text.trim() !== 'device') {
      throw new Error('adb cannot reach the tablet (' + (st.text.trim() || 'no answer') + '). If it was rebooted, '
        + 'wireless debugging may need enabling again over USB.');
    }
    this.emit('connect', 'adb has the tablet', 'ok');
    return dev;
  }

  deploy(dev, mode) {
    return new Promise((resolve) => {
      const bash = findBash(this.cfg().gitBash);
      if (!bash) {
        this.emit('build', 'Git Bash was not found - deploy.sh needs it (set gitBash in the desk config)', 'fail');
        return resolve(false);
      }
      const root = (mode === 'prepare' || mode === 'install') && this.ready && this.ready.root
        ? this.ready.root : this.d.agentRoot();
      const script = bashPath(path.join(root, 'deploy.sh'));
      const args = [script].concat(mode === 'resign' ? ['--no-build'] : mode === 'prepare' ? ['--prepare'] : mode === 'install' ? ['--install-only'] : []);
      this.emit('build', 'running deploy.sh' + (mode === 'resign' ? ' --no-build (re-sign and install)' : '')
        + (mode === 'prepare' ? ' - building and preparing the signed update' : mode === 'install' ? ' - installing the prepared update' : ' - building, platform-signing, verifying and installing'));
      const env = Object.assign({}, process.env, {
        PINE_TAB: dev,
        PINE_PREPARED_APK: bashPath((mode === 'prepare' || mode === 'install') && this.ready ? this.ready.apk : '')
      });
      // Keep dependency downloads cached, but avoid another build locking the
      // shared task-output cache while this isolated preparation runs.
      if (mode === 'prepare') env.GRADLE_OPTS = (env.GRADLE_OPTS || '') + ' -Dorg.gradle.caching=false';
      const child = spawn(bash, args, { cwd: os.tmpdir(), windowsHide: true, env });
      this.job.child = child;
      let step = 'build';
      const consume = (line) => {
        line = line.replace(/\r$/, '');
        if (!line.trim()) return;
        const head = /^== (.*)$/.exec(line);
        if (head) { step = head[1].slice(0, 60); this.emit(step, line.slice(3), 'step'); return; }
        this.emit(step, line, /REFUSING|FAILED|ERROR/.test(line) ? 'warn' : 'run');
      };
      const attach = (stream) => {
        let pending = '';
        stream.setEncoding('utf8');
        stream.on('data', (buf) => {
          const lines = (pending + buf).split('\n');
          pending = lines.pop();
          lines.forEach(consume);
        });
        stream.on('end', () => { if (pending) consume(pending); });
      };
      attach(child.stdout);
      attach(child.stderr);
      child.on('error', (e) => { this.emit('build', 'deploy.sh could not start: ' + e.message, 'fail'); resolve(false); });
      child.on('close', (code) => {
        this.emit('build', code === 0 ? 'deploy.sh finished' : 'deploy.sh stopped (exit ' + code + ')', code === 0 ? 'ok' : 'fail');
        resolve(code === 0);
      });
    });
  }

  /* The media stream's volume, or -1 when it cannot be read. */
  async volume(dev) {
    const got = await run(this.adb(), ['-s', dev, 'shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--get'], 15000);
    const m = /volume is (\d+)/.exec(got.text);
    return m ? Number(m[1]) : -1;
  }

  async relaunch(dev) {
    this.emit('relaunch', 'opening the PineBox app on the tablet again');
    const got = await run(this.adb(), ['-s', dev, 'shell', 'am', 'start', '-n', PKG + '/.MainActivity'], 20000);
    this.emit('relaunch', got.ok ? 'the app is open - it rejoins the broadcast by itself' : 'could not open it: ' + got.text.trim(),
      got.ok ? 'ok' : 'warn');
  }

  /* The operator's level is theirs: never raise it. Only a level the install raised is
   * brought back DOWN, with volume-down presses (`--set` does nothing on this GSI). */
  async volumeNotRaised(dev, before) {
    if (before < 0) return;
    await new Promise((r) => setTimeout(r, 4000));
    for (let round = 0; round < 3; round += 1) {
      const now = await this.volume(dev);
      if (now < 0 || now <= before) {
        if (round) this.emit('volume', 'the volume is back to ' + now, 'ok');
        return;
      }
      this.emit('volume', 'the install raised the volume ' + before + ' -> ' + now + ' - pressing it back down', 'warn');
      for (let i = 0; i < now - before; i += 1) {
        await run(this.adb(), ['-s', dev, 'shell', 'input', 'keyevent', '25'], 10000);
      }
    }
  }

  /* mode: "update" (only if out of date), "force" (build and install regardless),
   * "resign" (re-sign and install the APK already built) */
  async snapshotSource(dir) {
    const source = this.d.agentRoot();
    const project = path.join(dir, 'project');
    const io = fs.promises;
    for (const sub of ['app', 'gradle', 'tools', 'desktop/renderer']) {
      await io.mkdir(path.join(project, sub), { recursive: true });
    }
    const files = ['build.gradle.kts', 'settings.gradle.kts', 'gradle.properties', 'deploy.sh',
      'app/build.gradle.kts', 'app/proguard-rules.pro', 'gradle/libs.versions.toml',
      'tools/pinetab-stamp.sh', 'tools/kiosk-preflight.sh'];
    await Promise.all(files.map(file => io.copyFile(path.join(source, file), path.join(project, file))));
    await io.cp(path.join(source, 'app/src'), path.join(project, 'app/src'), { recursive: true, dereference: true });
    // Copy the canonical assets this APK declares, without copying build outputs.
    for (const kind of ['pine-views', 'pine-sampler']) {
      const assets = await io.readdir(path.join(project, 'app/src/main/assets', kind), { withFileTypes: true });
      for (const asset of assets) {
        if (!asset.isFile()) continue;
        const canonical = path.join(source, 'desktop/renderer', asset.name);
        try {
          if ((await io.stat(canonical)).isFile()) {
            await io.copyFile(canonical, path.join(project, 'desktop/renderer', asset.name));
          }
        } catch (e) { if (e.code !== 'ENOENT') throw e; }
      }
    }
    return { root: project, stamp: (await (this.d.sampleStamp || stampAsync)(project, path.join(project, 'desktop', 'renderer'), {fresh:true})).stamp };
  }

  async prepare() {
    if (this.job && this.job.running) return { ok: false, why: 'an update is already running' };
    this.job = { running: true, started: Date.now(), log: [], mode: 'prepare' };
    this.ready = null;
    const result = { ok: false };
    try {
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pinetab-ready-'));
        this.ready = { apk: path.join(dir, 'pine-platform.apk') };
        this.emit('snapshot', 'copying the latest source into an isolated background build directory (attempt ' + attempt + '/3)');
        const snapshot = await this.snapshotSource(dir);
        if (snapshot.stamp !== (await this.wanted(true)).stamp) {
          if (attempt === 3) throw new Error('source is still being edited - wait for the edits to finish, then tap to retry');
          this.emit('queue', 'source changed while copying - automatically queuing a fresh snapshot', 'warn');
          continue;
        }
        const wanted = snapshot.stamp;
        this.ready.root = snapshot.root;
        this.ready.wanted = wanted;
        this.emit('build', 'building the latest workspace source ' + wanted);
        if (!(await this.deploy('', 'prepare'))) throw new Error('build failed - see the console output');
        if (!exists(this.ready.apk)) throw new Error('the build did not produce the prepared APK');
        if ((await this.wanted(true)).stamp !== wanted) {
          if (attempt === 3) throw new Error('source is still changing during compilation - wait for edits to finish, then tap to retry');
          this.emit('queue', 'source changed during compilation - automatically building the newer version', 'warn');
          continue;
        }
        this.ready.digest = crypto.createHash('sha256').update(fs.readFileSync(this.ready.apk)).digest('hex');
        result.ok = true;
        result.ready = true;
        result.wanted = wanted;
        this.emit('ready', 'update compiled and signed - tap the tablet update button to install', 'ok');
        break;
      }
    } catch (e) {
      this.ready = null;
      result.why = e.message;
      this.emit('fail', e.message, 'fail');
    } finally {
      this.job.running = false;
      this.job.result = result;
    }
    return result;
  }

  async update(mode) {
    if (mode === 'prepare') return this.prepare();
    if (this.job && this.job.running) return { ok: false, why: 'an update is already running', log: this.job.log };
    this.job = { running: true, started: Date.now(), log: [], mode: mode || 'update' };
    const result = { ok: false, mode: this.job.mode };
    try {
      const wanted = (await this.wanted(true)).stamp;
      if (mode === 'install') {
        if (!this.ready || !this.ready.digest || !exists(this.ready.apk)) throw new Error('no compiled update is ready - build it first');
        if (this.ready.wanted !== wanted) throw new Error('source changed after compilation - build the latest version first');
        const digest = crypto.createHash('sha256').update(fs.readFileSync(this.ready.apk)).digest('hex');
        if (digest !== this.ready.digest) throw new Error('the prepared APK changed - build it again');
      }
      result.wanted = wanted;
      this.emit('check', 'the source builds ' + wanted);
      const dev = await this.locate();
      const before = await this.installedByAdb(dev);
      result.before = before.stamp || before.name;
      this.emit('check', 'the tablet has ' + (before.name || 'no PineBox app'), 'ok');
      if (this.job.mode === 'update' && before.stamp && before.stamp === wanted) {
        this.emit('done', 'already up to date - nothing to build', 'ok');
        result.ok = true;
        result.skipped = true;
        return result;
      }
      const volBefore = await this.volume(dev);
      if (volBefore >= 0) this.emit('check', 'the tablet\'s media volume is ' + volBefore + ' - the install must not raise it');
      this.emit('release', 'stopping the desk mirror\'s screenrecord before the install (two encoders crash the tablet)');
      try { await this.d.glassStop(); } catch (e) { /* nothing was recording */ }
      if (!(await this.deploy(dev, this.job.mode))) {
        result.why = 'deploy.sh did not finish - its last lines say why';
        return result;
      }
      const after = await this.installedByAdb(dev);
      result.after = after.stamp || after.name;
      const good = this.job.mode === 'resign' ? !!after.name : after.stamp === wanted;
      this.emit('verify', 'the tablet now has ' + (after.name || 'nothing') + (good ? '' : ' - not the build that was wanted'),
        good ? 'ok' : 'warn');
      try { await this.d.wake(); } catch (e) { /* the script woke it already */ }
      /* [tablet-update-ask] deploy.sh installs and stops: the install killed the kiosk
       * and nothing opened it again, so the tablet sat on its home screen with the air
       * untaken. Open it, then make sure the install did not raise the volume. */
      await this.relaunch(dev);
      result.relaunched = true;
      await this.volumeNotRaised(dev, volBefore);
      result.ok = good;
      if (good && mode === 'install') this.ready = null;
      this.emit('done', good ? 'the tablet is up to date' : 'finished, but the stamp does not match', good ? 'ok' : 'warn');
      return result;
    } catch (e) {
      this.emit('fail', e.message, 'fail');
      result.why = e.message;
      return result;
    } finally {
      this.job.running = false;
      this.job.result = result;
    }
  }

  async preflight() {
    const bash = findBash(this.cfg().gitBash);
    if (!bash) return { ok: false, text: 'Git Bash was not found' };
    let dev = '';
    try { dev = await this.locate(); } catch (e) { return { ok: false, text: e.message }; }
    return new Promise((resolve) => {
      const script = bashPath(path.join(this.d.agentRoot(), 'tools', 'kiosk-preflight.sh'));
      execFile(bash, [script], { cwd: os.tmpdir(), timeout: 120000, windowsHide: true,
        env: Object.assign({}, process.env, { PINE_TAB: dev, ADB: bashPath(this.adb()) }) },
      (error, stdout, stderr) => resolve({ ok: !error, text: String(stdout || '') + String(stderr || '') }));
    });
  }

  /* The troubleshooting ladder, one place: the station's own doctor and adb. */
  async action(name) {
    const n = String(name || '');
    try {
      if (n === 'look') return { ok: true, look: await this.look() };
      if (n === 'find') return { ok: true, found: await this.d.getJson('/api/tablet/find?deep=1') };
      if (['sweep', 'adopt', 'wake-station', 'ping'].indexOf(n) >= 0) {
        return { ok: true, got: await this.d.postJson('/api/tablet/doctor/' + n.replace('-station', ''), {}) };
      }
      if (n === 'connect') return { ok: true, dev: await this.locate() };
      if (n === 'wake') return await this.d.wake();
      const dev = await this.locate();
      if (n === 'reboot') return await run(this.adb(), ['-s', dev, 'reboot'], 20000);
      if (n === 'restart-app') {
        await run(this.adb(), ['-s', dev, 'shell', 'am', 'force-stop', PKG], 15000);
        return await run(this.adb(), ['-s', dev, 'shell', 'monkey', '-p', PKG, '-c', 'android.intent.category.LAUNCHER', '1'], 15000);
      }
      if (n === 'grant') {
        await run(this.adb(), ['-s', dev, 'shell', 'pm', 'grant', PKG, 'android.permission.RECORD_AUDIO'], 15000);
        await run(this.adb(), ['-s', dev, 'shell', 'pm', 'grant', PKG, 'android.permission.CAMERA'], 15000);
        return await run(this.adb(), ['-s', dev, 'shell', 'dumpsys', 'package', PKG], 20000);
      }
      if (n === 'version') return { ok: true, installed: await this.installedByAdb(dev), wanted: (await this.wanted(true)).stamp };
      return { ok: false, why: 'no such action: ' + n };
    } catch (e) {
      return { ok: false, why: e.message };
    }
  }

  install(ipcMain) {
    ipcMain.handle('pinetab:check', (_e, opts) => this.check(opts || {}));
    ipcMain.handle('pinetab:update', (_e, mode) => this.update(mode));
    ipcMain.handle('pinetab:preflight', () => this.preflight());
    ipcMain.handle('pinetab:action', (_e, name) => this.action(name));
    ipcMain.handle('pinetab:job', () => (this.job ? { running: this.job.running, mode: this.job.mode,
      log: this.job.log.slice(-400), result: this.job.result || null } : null));
    return this;
  }
}

module.exports = { PinetabUpdate, bashPath, findBash, findAdb };
