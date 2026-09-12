/* THE TABLET'S GLASS, FROM THE DESKTOP.
 *
 * "I want three buttons added to the sidebar. The first takes a picture of
 *  what is being displayed on the Pine Box tablet and copies it to the
 *  clipboard. The second makes an MP4 from what is being displayed on the
 *  Pine Box tablet... a default of up to 10 seconds, but expandable up to 30.
 *  And the last allows me to copy diagnostics information of what's happening
 *  with the Pine Box tablet to my clipboard so I can paste it in conversation
 *  about what is going on on the screen currently."
 *
 * Three things the tablet can be asked for and the desktop can hold: a still,
 * a clip, and an account of itself.
 *
 * NOTHING HERE KNOWS ABOUT ELECTRON. It is handed a way to run adb and hands
 * back bytes and text; the clipboard and the save dialog are main.js's
 * business. That is what makes this exercisable without a window, and it is
 * the same split terminal.cjs and firmware.cjs already use.
 *
 * THE REPORT IS THE INTERESTING ONE. A picture shows what the screen looks
 * like and says nothing about why, so the report answers the questions a
 * picture raises: which view is open, what the sampler is holding, whether
 * the station feed is arriving, what is actually making sound, and what the
 * app has been complaining about. Most of that is not visible to adb at all -
 * it lives in the WebView - so the report goes in through the same DevTools
 * door the panel is debugged with and asks the page directly.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { parseProps, parseBattery } = require('./terminal.cjs');

const PACKAGE = 'com.pinebox.kiosk';

/* Written on the tablet, pulled, then deleted. /sdcard because screenrecord
 * cannot write anywhere an app-private path would put it. */
const DEVICE_STILL = '/sdcard/pinebox-glass.png';
const DEVICE_CLIP = '/sdcard/pinebox-glass.mp4';

/* The operator's ten and thirty. Three at the bottom because anything less is
 * a still that took longer to save. */
const CLIP_DEFAULT = 10;
const CLIP_MIN = 3;
const CLIP_MAX = 30;

/* 6 Mbit for a 1340x800 tablet screen: screenrecord's own default is 20 Mbit,
 * which on a mostly-static UI spends four times the bytes on the same picture
 * and makes a thirty-second clip too big to hand anyone. */
const CLIP_BITRATE = '6000000';

/* The DevTools forward. Deliberately not 9222 - that is the port a person
 * debugging by hand will already have taken, and stealing it mid-session
 * would be a rude way to answer a diagnostics click. */
const GLASS_PORT = 9333;

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47]);

function looksPng(buffer) {
  return Buffer.isBuffer(buffer) && buffer.length > 24 &&
    buffer.subarray(0, 4).equals(PNG_MAGIC);
}

/* Width and height out of the IHDR, which is always the first chunk. Saves
 * decoding the image just to be able to say how big it is. */
function pngSize(buffer) {
  try {
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  } catch (error) {
    return null;
  }
}

function clampSeconds(seconds) {
  const want = Math.round(Number(seconds));
  if (!isFinite(want)) return CLIP_DEFAULT;
  return Math.max(CLIP_MIN, Math.min(CLIP_MAX, want));
}

function tempFile(suffix) {
  return path.join(os.tmpdir(),
    'pinebox-glass-' + Date.now() + '-' + Math.floor(Math.random() * 1e6) + suffix);
}

function dropTemp(file) {
  try { fs.unlinkSync(file); } catch (error) { /* it was a temp file */ }
}

/* ---------------------------------------------------------------- the page */

/* WHAT THE PAGE IS ASKED. One expression, every answer in its own try, so a
 * view that has not been built yet costs that line and not the report.
 *
 * It reports what cannot be seen from outside the WebView and what a
 * screenshot cannot tell you: which view is open rather than which is on top,
 * what the sampler is actually holding, whether the feed is arriving, and
 * which media elements are making sound - the last being the question behind
 * most "why can I hear two things" reports. */
const GLASS_QUESTION = `(function () {
  var out = {};
  var say = function (name, fn) {
    try { out[name] = fn(); } catch (err) { out[name] = { error: String(err && err.message || err) }; }
  };
  say('page', function () {
    return { title: document.title, url: String(location.href).slice(0, 160),
             size: window.innerWidth + 'x' + window.innerHeight,
             dpr: window.devicePixelRatio };
  });
  say('views', function () {
    var hosts = [].slice.call(document.querySelectorAll('.pine-view-host'));
    var open = hosts.filter(function (h) { return h.classList.contains('open'); });
    return { open: open.map(function (h) { return h.id || '?'; }).join(', ') || 'panel',
             all: hosts.map(function (h) { return h.id || '?'; }).join(' ') };
  });
  say('sampler', function () {
    var S = window.PineSampler;
    if (!S || !S.isMounted || !S.isMounted()) return { mounted: false };
    var pick = function (id) {
      var el = document.getElementById(id);
      return el ? String(el.textContent || '').trim() : '';
    };
    var on = function (sel) {
      return [].slice.call(document.querySelectorAll(sel)).map(function (e) {
        return String(e.textContent || '').trim();
      }).filter(Boolean).join(',');
    };
    var feed = document.getElementById('pbFeed');
    var host = document.getElementById('sampler');
    return {
      mounted: true,
      /* MOUNTED IS NOT THE SAME AS ON SCREEN. The sampler stays built and
       * loaded behind whichever view is open, so this is the difference
       * between "what you are looking at" and "what is still holding
       * audio". */
      onScreen: !!(host && host.offsetWidth > 0 && host.offsetHeight > 0),
      bank: on('.pb-bank.active') || '?',
      padsFilled: document.querySelectorAll('.pb-pad.filled').length,
      modesOn: on('.pb-mode.on') || 'none',
      feedRows: feed ? feed.children.length : 0,
      feedScroll: feed ? Math.round(feed.scrollTop) : 0,
      tally: pick('pbTally'),
      note: pick('pbNote'),
      memory: pick('pbFoot'),
      engine: window.pineSampler ? 'native oboe' :
              (window.PineSamplerEngine ? 'web audio' : 'none')
    };
  });
  say('station', function () {
    var F = window.PineStationFeed;
    if (!F) return { present: false };
    var out2 = { present: true };
    /* A row, said the way a person would read it. speaking_now is the whole
     * chat row - printed straight it comes out as [object Object]. */
    var readable = function (row, cap) {
      if (!row) return '';
      if (typeof row === 'string') return row.slice(0, cap || 70);
      var who = row.name || row.who || row.kind || 'someone';
      var text = String(row.text || '').replace(/\s+/g, ' ').trim();
      return text ? who + ': ' + text.slice(0, cap || 70) : who;
    };
    var rows = [];
    try { rows = (F.rows ? F.rows() : []) || []; } catch (err) { rows = []; }
    try {
      var st = F.state ? F.state() : null;
      if (st) {
        out2.speaking = readable(st.speaking_now);
        if (st.chat) out2.rows = st.chat.length;
      }
    } catch (err) { out2.stateError = String(err && err.message); }
    if (rows.length) out2.rows = rows.length;
    try { if (F.subscribers) out2.subscribers = F.subscribers(); } catch (err) {}
    try {
      /* now() is a PLAYHEAD - {id, from, until} - so the id is looked up in
       * the feed rather than printed, which is all the first version did. */
      var now = F.now ? F.now() : null;
      if (now && now.id) {
        var hit = null;
        for (var i = rows.length - 1; i >= 0; i--) {
          if (rows[i] && rows[i].id === now.id) { hit = rows[i]; break; }
        }
        out2.now = hit ? readable(hit, 60) : ('line ' + String(now.id).slice(0, 8));
        if (typeof now.from === 'number' && typeof now.until === 'number') {
          out2.now += '  [' + now.from.toFixed(1) + '-' + now.until.toFixed(1) + 's]';
        }
      }
    } catch (err) {}
    return out2;
  });
  say('sound', function () {
    var media = [].slice.call(document.querySelectorAll('audio,video'));
    var live = media.filter(function (m) { return !m.paused && !m.ended; });
    return {
      elements: media.length,
      playing: live.length,
      what: live.slice(0, 6).map(function (m) {
        return (m.id || m.className || m.tagName).toString().slice(0, 28)
          + ' ' + (m.currentTime || 0).toFixed(1) + 's'
          + ' vol ' + (m.volume != null ? m.volume.toFixed(2) : '?')
          + (m.muted ? ' MUTED' : '');
      }),
      context: window.pineAudioCtx
        ? window.pineAudioCtx.state + ' @' + window.pineAudioCtx.sampleRate
        : 'none'
    };
  });
  return JSON.stringify(out);
})()`;

/* Runtime.evaluate over one short-lived socket. Node has had a WebSocket of
 * its own since 22 and Electron 37 carries it, but a runtime without one must
 * say so rather than fail as though the tablet were the problem. */
function evaluate(wsUrl, expression, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (typeof WebSocket !== 'function') {
      return reject(new Error('this build has no WebSocket, so the page cannot be asked'));
    }
    let socket;
    try { socket = new WebSocket(wsUrl); }
    catch (error) { return reject(error); }
    const done = (fn, value) => {
      clearTimeout(timer);
      try { socket.close(); } catch (error) { /* already gone */ }
      fn(value);
    };
    const timer = setTimeout(
      () => done(reject, new Error('DevTools did not answer in time')), timeoutMs || 9000);
    socket.addEventListener('open', () => {
      socket.send(JSON.stringify({
        id: 1,
        method: 'Runtime.evaluate',
        params: { expression, returnByValue: true, awaitPromise: true }
      }));
    });
    socket.addEventListener('message', (event) => {
      let message;
      try { message = JSON.parse(String(event.data)); } catch (error) { return; }
      if (message.id !== 1) return;
      const result = message.result || {};
      if (result.exceptionDetails) {
        return done(reject, new Error('the page threw while answering'));
      }
      done(resolve, result.result ? result.result.value : null);
    });
    socket.addEventListener('error',
      () => done(reject, new Error('DevTools refused the connection')));
    socket.addEventListener('close', () => clearTimeout(timer));
  });
}

/* -------------------------------------------------------------- formatting */

function humanBytes(n) {
  const bytes = Number(n) || 0;
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1073741824).toFixed(2) + ' GB';
  if (bytes >= 1024 * 1024) return (bytes / 1048576).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + ' kB';
  return bytes + ' B';
}

function humanSpan(seconds) {
  const whole = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  if (h) return h + 'h ' + String(m).padStart(2, '0') + 'm';
  if (m) return m + 'm ' + String(whole % 60).padStart(2, '0') + 's';
  return whole + 's';
}

function stamp(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

/* meminfo and df both print a table; these pull the one number each that is
 * worth a line in a report someone has to read. */
function memFree(text) {
  const total = /MemTotal:\s+(\d+)/.exec(text || '');
  const avail = /MemAvailable:\s+(\d+)/.exec(text || '');
  if (!total || !avail) return null;
  return { total: Number(total[1]) * 1024, free: Number(avail[1]) * 1024 };
}

function diskFree(text) {
  const line = String(text || '').split('\n').find((l) => /\d+%/.test(l));
  if (!line) return null;
  const cells = line.trim().split(/\s+/);
  const size = Number(cells[1]), avail = Number(cells[3]);
  if (!isFinite(size) || !isFinite(avail)) return null;
  return { total: size * 1024, free: avail * 1024 };
}

function appPss(text) {
  const hit = /TOTAL(?:\s+PSS)?:?\s+(\d+)/i.exec(String(text || ''));
  return hit ? Number(hit[1]) * 1024 : null;
}

/* THE LOG, CUT DOWN TO WHAT IS WORTH PASTING. A full logcat dump is tens of
 * thousands of lines and nobody reads it; what earns its place in a report is
 * the app's own errors and whatever the page has been shouting about. */
function interestingLog(text, pid) {
  const out = [];
  const seen = new Set();
  let frames = 0;
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trimEnd();
    if (!line) continue;
    const mine = pid && line.includes(' ' + pid + ' ');
    const loud = /\s[EWF]\s/.test(line);
    const console = /chromium|PineBox|pine-|Console|JavaScript/i.test(line);
    if (!(loud && (mine || console)) && !(mine && console)) continue;
    /* One of each. A repeating error is worth knowing about once; four
     * hundred copies of it is what buried the ANR last time. */
    const key = line.replace(/^\S+\s+\S+\s+\d+\s+\d+\s+/, '').slice(0, 120);
    if (seen.has(key)) continue;
    seen.add(key);
    /* A JAVA STACK TRACE IS ONE FACT, NOT NINE. Two frames name the road;
     * the rest is the framework, and printing all of it means one exception
     * crowds out everything else the app was trying to say. Measured: a
     * single IOException took five of the thirty lines on the first run. */
    if (/^\s*at /.test(key)) {
      if (frames >= 2) continue;
      frames += 1;
    } else {
      frames = 0;
    }
    out.push(line.length > 200 ? line.slice(0, 197) + '...' : line);
    if (out.length >= 30) break;
  }
  return out;
}

/* ------------------------------------------------------------------ Glass */

class Glass {
  constructor({ run, runBinary, serial, now } = {}) {
    this.run = run;
    this.runBinary = runBinary;
    this.serial = serial || '';
    this.now = now || (() => Date.now());
  }

  target(args) {
    return this.serial ? ['-s', this.serial].concat(args) : args.slice();
  }

  async shell(command, timeoutMs) {
    return this.run(this.target(['shell', command]), timeoutMs);
  }

  /* A question whose answer is allowed to be "no". Every line of the report
   * is optional; none of them may take the report down with it. */
  async maybe(command, timeoutMs) {
    try { return await this.shell(command, timeoutMs); }
    catch (error) { return ''; }
  }

  /* ------------------------------------------------------------- the still */

  async still() {
    /* `exec-out` keeps bytes as bytes. `adb shell` runs them through a pty
     * that turns every 0x0A into 0x0D 0x0A, which corrupts a PNG in a way
     * that still looks like a file - so this road is taken first and checked
     * by its magic number rather than trusted. */
    let png = null;
    try {
      png = await this.runBinary(this.target(['exec-out', 'screencap', '-p']), 30000);
    } catch (error) { png = null; }

    let how = 'exec-out';
    if (!looksPng(png)) {
      /* Older or stricter builds refuse exec-out. Writing on the tablet and
       * pulling the file is slower and always works. */
      how = 'screencap and pull';
      const local = tempFile('.png');
      try {
        await this.shell('screencap -p ' + DEVICE_STILL, 30000);
        await this.run(this.target(['pull', DEVICE_STILL, local]), 60000);
        png = fs.readFileSync(local);
      } catch (error) {
        return { ok: false, why: 'the tablet would not take a screenshot: ' + error.message };
      } finally {
        dropTemp(local);
        await this.maybe('rm -f ' + DEVICE_STILL, 15000);
      }
    }

    if (!looksPng(png)) {
      return { ok: false, why: 'the tablet answered, but not with a PNG' };
    }
    return { ok: true, png, bytes: png.length, size: pngSize(png), how, at: this.now() };
  }

  /* -------------------------------------------------------------- the clip */

  async clip(seconds) {
    const want = clampSeconds(seconds);
    const local = tempFile('.mp4');
    await this.maybe('rm -f ' + DEVICE_CLIP, 15000);

    let said = '';
    try {
      /* screenrecord holds the shell for the whole recording, so the timeout
       * has to outlast the clip with room for the encoder to finish writing
       * the container - a truncated mp4 is a file that exists and will not
       * play. */
      said = await this.shell(
        'screenrecord --time-limit ' + want + ' --bit-rate ' + CLIP_BITRATE
        + ' ' + DEVICE_CLIP,
        (want + 40) * 1000);
    } catch (error) {
      return { ok: false, why: 'the tablet could not record: ' + error.message };
    }
    /* screenrecord reports its refusals on stdout and still exits zero. */
    if (/error|denied|not supported|failed/i.test(said || '')) {
      return { ok: false, why: 'the tablet refused to record: ' + said.trim().slice(0, 200) };
    }

    try {
      await this.run(this.target(['pull', DEVICE_CLIP, local]), 120000);
      const mp4 = fs.readFileSync(local);
      if (!mp4 || mp4.length < 1024) {
        return { ok: false, why: 'the recording came back empty' };
      }
      return { ok: true, mp4, bytes: mp4.length, seconds: want, at: this.now() };
    } catch (error) {
      return { ok: false, why: 'the recording could not be fetched: ' + error.message };
    } finally {
      dropTemp(local);
      await this.maybe('rm -f ' + DEVICE_CLIP, 15000);
    }
  }

  /* ------------------------------------------------------------ the report */

  async pid() {
    const said = await this.maybe('pidof ' + PACKAGE, 15000);
    const first = String(said || '').trim().split(/\s+/)[0];
    return /^\d+$/.test(first) ? first : '';
  }

  /* The WebView's own account of itself, through the DevTools port. This is
   * the half of the report adb cannot reach: everything interesting about
   * this terminal happens inside one very large web page. */
  async askThePage(pid) {
    if (!pid) return { ok: false, why: 'the kiosk app is not running' };
    const forward = 'tcp:' + GLASS_PORT;
    const socket = 'localabstract:webview_devtools_remote_' + pid;
    try {
      await this.run(this.target(['forward', forward, socket]), 20000);
    } catch (error) {
      return { ok: false, why: 'could not open a DevTools forward: ' + error.message };
    }
    try {
      const response = await fetch('http://127.0.0.1:' + GLASS_PORT + '/json',
        { signal: AbortSignal.timeout(8000) });
      const targets = await response.json();
      const page = (targets || []).find(
        (t) => t && t.webSocketDebuggerUrl && t.type === 'page') || (targets || [])[0];
      if (!page || !page.webSocketDebuggerUrl) {
        return { ok: false, why: 'the app is running but has no debuggable page' };
      }
      const raw = await evaluate(page.webSocketDebuggerUrl, GLASS_QUESTION, 9000);
      let state = null;
      try { state = JSON.parse(String(raw)); } catch (error) { state = null; }
      if (!state) return { ok: false, why: 'the page answered with nothing readable' };
      return { ok: true, state };
    } catch (error) {
      return { ok: false, why: 'the page could not be reached: ' + error.message };
    } finally {
      await this.run(this.target(['forward', '--remove', forward]), 15000).catch(() => {});
    }
  }

  async report() {
    const at = this.now();
    const pid = await this.pid();

    /* Everything adb can answer at once. These are independent questions and
     * the tablet is on Wi-Fi; asked one after another they cost a second and
     * a half of somebody's attention for no reason. */
    const [props, battery, uptime, meminfo, df, pss, focus, switches, log, page] =
      await Promise.all([
        this.maybe('getprop', 30000),
        this.maybe('dumpsys battery', 20000),
        this.maybe('cat /proc/uptime', 15000),
        this.maybe('cat /proc/meminfo', 15000),
        this.maybe('df /data', 15000),
        pid ? this.maybe('dumpsys meminfo ' + PACKAGE + ' | grep -i -m2 TOTAL', 25000) : '',
        this.maybe('dumpsys window | grep -m3 -E "mCurrentFocus|mFocusedApp"', 25000),
        this.maybe('dumpsys input | grep -i -m2 SwitchValues', 25000),
        this.run(this.target(['logcat', '-d', '-t', '600']), 40000).catch(() => ''),
        this.askThePage(pid)
      ]);

    const prop = parseProps(props || {});
    /* parseBattery answers a PERCENTAGE, not a record - the first version
     * read `.level` off a number and silently dropped the whole line. What
     * it does not answer is read here. */
    const charge = parseBattery(battery || '');
    const charging = /^\s*(AC|USB|Wireless|Dock) powered:\s*true/m.test(battery || '');
    const tempRaw = /^\s*temperature:\s*(-?\d+)/m.exec(battery || '');
    const memory = memFree(meminfo);
    const disk = diskFree(df);
    const up = Number(String(uptime || '').trim().split(/\s+/)[0]);

    const L = [];
    L.push('PINE BOX TABLET - what the glass is doing');
    L.push('taken ' + stamp(at) + ' from the Pine Box desktop app');
    L.push('');

    L.push('TABLET');
    L.push('  adb         ' + (this.serial || '(the only device attached)'));
    if (prop['ro.product.model']) {
      L.push('  model       ' + prop['ro.product.model']
        + ' / ' + (prop['ro.product.device'] || '?'));
    }
    if (prop['ro.build.version.release']) {
      L.push('  android     ' + prop['ro.build.version.release']
        + ' (sdk ' + (prop['ro.build.version.sdk'] || '?') + ')');
    }
    if (prop['ro.build.display.id']) L.push('  build       ' + prop['ro.build.display.id']);
    if (isFinite(up)) L.push('  up          ' + humanSpan(up));
    if (charge != null) {
      /* dumpsys reports tenths of a degree. */
      const degrees = tempRaw ? (Number(tempRaw[1]) / 10).toFixed(1) + 'C' : '';
      L.push('  battery     ' + charge + '% '
        + (charging ? 'on the charger' : 'on battery')
        + (degrees ? ', ' + degrees : ''));
    }
    if (memory) {
      L.push('  memory      ' + humanBytes(memory.free) + ' free of '
        + humanBytes(memory.total));
    }
    if (disk) {
      L.push('  storage     ' + humanBytes(disk.free) + ' free of '
        + humanBytes(disk.total));
    }
    /* The jack, because it is the one piece of this tablet that has needed
     * looking at most often, and `SwitchValues: 4` is the whole answer. */
    const jack = /SwitchValues:\s*(\d+)/.exec(switches || '');
    if (jack) {
      L.push('  jack        SwitchValues ' + jack[1]
        + (Number(jack[1]) & 4 ? ' (a cable is in)' : ' (nothing in the socket)'));
    }
    L.push('');

    L.push('KIOSK APP');
    L.push('  package     ' + PACKAGE + (pid ? '  pid ' + pid : '  NOT RUNNING'));
    const pssBytes = appPss(pss);
    if (pssBytes) L.push('  memory      ' + humanBytes(pssBytes) + ' PSS');
    const focused = String(focus || '').trim().split('\n')
      .map((l) => l.trim()).filter(Boolean).slice(0, 2);
    for (const line of focused) L.push('  focus       ' + line.slice(0, 120));
    /* An ANR dialog owning the focus is the answer to "why is it frozen", and
     * it is worth saying in words rather than leaving in a dumpsys line. */
    if (/Application Not Responding|anr/i.test(focus || '')) {
      L.push('  ! an ANR dialog has the focus - the app is wedged, not slow');
    }
    L.push('');

    L.push('ON THE GLASS');
    if (!page.ok) {
      L.push('  (could not ask the page: ' + page.why + ')');
    } else {
      const s = page.state || {};
      if (s.page) {
        L.push('  showing     ' + (s.page.title || '(untitled)')
          + '  ' + (s.page.size || '') + (s.page.dpr ? ' @' + s.page.dpr + 'x' : ''));
        if (s.page.url) L.push('  url         ' + s.page.url);
      }
      if (s.views) L.push('  view open   ' + (s.views.open || '?')
        + '   (of: ' + (s.views.all || '') + ')');
      if (s.sampler) {
        if (s.sampler.mounted) {
          L.push('  sampler     ' + (s.sampler.onScreen
              ? 'on screen' : 'mounted but NOT on screen')
            + ' - bank ' + s.sampler.bank
            + ', ' + s.sampler.padsFilled + ' pads loaded'
            + ', engine ' + s.sampler.engine);
          L.push('              modes on: ' + s.sampler.modesOn);
          L.push('              feed ' + s.sampler.feedRows + ' rows'
            + ' (scroll ' + s.sampler.feedScroll + ')'
            + (s.sampler.tally ? ' - ' + s.sampler.tally : ''));
          if (s.sampler.memory) L.push('              pads hold ' + s.sampler.memory);
          if (s.sampler.note) L.push('              last note: ' + s.sampler.note);
        } else if (s.sampler.error) {
          L.push('  sampler     could not be read: ' + s.sampler.error);
        } else {
          L.push('  sampler     not mounted');
        }
      }
      if (s.station) {
        if (s.station.present) {
          L.push('  station     ' + (s.station.rows != null ? s.station.rows + ' feed rows' : 'feed present')
            + (s.station.subscribers != null ? ', ' + s.station.subscribers + ' subscribers' : ''));
          if (s.station.now) L.push('              now: ' + s.station.now);
          if (s.station.speaking) L.push('              speaking: ' + s.station.speaking);
          if (s.station.stateError) L.push('              ! feed state threw: ' + s.station.stateError);
        } else {
          L.push('  station     the shared feed is not on this page');
        }
      }
      if (s.sound) {
        L.push('  sound       ' + s.sound.playing + ' of ' + s.sound.elements
          + ' players going, context ' + s.sound.context);
        for (const what of (s.sound.what || [])) L.push('              ' + what);
      }
    }
    L.push('');

    const noise = interestingLog(log, pid);
    L.push('WHAT THE APP HAS BEEN COMPLAINING ABOUT'
      + (noise.length ? ' (one of each, newest last)' : ''));
    if (!noise.length) L.push('  nothing - no errors or warnings from this app in the log');
    for (const line of noise) L.push('  ' + line);

    const text = L.join('\n');
    return { ok: true, text, at, pid, page: page.ok };
  }
}

module.exports = {
  Glass, GLASS_QUESTION, GLASS_PORT,
  CLIP_DEFAULT, CLIP_MIN, CLIP_MAX,
  clampSeconds, looksPng, pngSize, memFree, diskFree, appPss, interestingLog,
  humanBytes, humanSpan
};
