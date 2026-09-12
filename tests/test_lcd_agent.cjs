const assert = require('node:assert/strict');
const {test} = require('node:test');
const {LcdAgent, endpoint, parseStatus, firmwareReadiness} = require('../desktop/lcd-agent.cjs');
const status = 'QUANTA-SCREEN ok ver=49 board=cyd_2432s028r 10.1.2.3 320x240 anims=2 mode=comm jpeg=1 up=20 id=dc:b4:d9:23:11:78';
const jpeg = Buffer.from([255, 216, 1, 2, 3, 255, 217]).toString('base64');
function fixture(request) {
  let config = {lcd: {host: '10.1.2.3'}};
  const agent = new LcdAgent({read: () => config, write: (next) => { config = {...config, ...next}; },
    request: request || (async (_, route) => route === '/status' ? status : route === '/events' ? '' : 'QACK img 320x240 heap 123 via=wifi'),
    discover: async () => ['10.1.2.3'], candidates: () => []});
  return agent;
}

test('gallery selection persists independently from newspaper overlay and avatar settings', () => {
  let requests = 0;
  const agent = fixture(async () => { requests++; throw new Error('Configuration must not contact the device'); });
  assert.equal(agent.config().galleryIntervalSeconds, 8);
  const selected = agent.configure({mode: 'gallery', galleryIntervalSeconds: 12, chatOverlay: false});
  assert.equal(selected.config.mode, 'gallery');
  assert.equal(selected.config.galleryIntervalSeconds, 12);
  assert.equal(selected.config.chatOverlay, false);
  assert.equal(selected.config.screensaverEnabled, false);
  for (const mode of ['paper', 'dialogue', 'cupboard', 'gallery']) {
    assert.equal(agent.configure({mode}).config.mode, mode);
    assert.equal(agent.config().galleryIntervalSeconds, 12);
    assert.equal(agent.config().chatOverlay, false);
  }
  assert.equal(agent.configure({mode: 'unknown'}).config.mode, 'paper');
  assert.equal(requests, 0);
});

test('gallery timing is bounded on write and on persisted configuration restore', () => {
  const agent = fixture();
  for (const [value, expected] of [[0, 3], [-20, 3], [3, 3], [8.6, 9], ['15', 15], [60, 60], [1000, 60], [NaN, 8], [Infinity, 8], ['', 8], [null, 8]]) {
    assert.equal(agent.configure({galleryIntervalSeconds: value}).config.galleryIntervalSeconds, expected);
    const restored = new LcdAgent({read: () => ({lcd: {mode: 'gallery', galleryIntervalSeconds: value}})});
    assert.equal(restored.config().galleryIntervalSeconds, expected);
    assert.equal(restored.config().mode, 'gallery');
  }
  const restored = new LcdAgent({read: () => ({lcd: {mode: 'invalid', chatOverlay: null}})});
  assert.equal(restored.config().mode, 'paper');
  assert.equal(restored.config().chatOverlay, true);
  assert.equal(restored.config().galleryIntervalSeconds, 8);
});

test('only verified LAN Quanta identities are accepted', () => {
  assert.equal(endpoint('http://10.1.2.3:8080'), '10.1.2.3:8080');
  assert.equal(endpoint('quanta-screen.local'), 'quanta-screen.local');
  for (const host of ['https://example.com', '127.0.0.1', 'http://10.1.2.3/firmware', 'http://user:pass@10.1.2.3']) assert.throws(() => endpoint(host));
  assert.equal(parseStatus(status).identity, 'dc:b4:d9:23:11:78');
  assert.throws(() => parseStatus('ok 320x240'));
  assert.throws(() => parseStatus(status.replace(/ id=.*$/, '')));
  assert.throws(() => parseStatus(status.replace('jpeg=1', 'jpeg=0')));
});

test('connecting identifies the device without sending a frame', async () => {
  const routes = [];
  const agent = fixture(async (_, route) => { routes.push(route); return status; });
  await agent.connect('10.1.2.3');
  assert.deepEqual(routes, ['/status']);
  assert.equal(agent.connected, true); assert.equal(agent.running, false);
  assert.equal(agent.config().identity, 'dc:b4:d9:23:11:78');
});

test('one in-flight frame, base64 wire payload, success only after draw ACK', async () => {
  let release, body;
  const agent = fixture(async (_, route, payload) => {
    if (route === '/status') return status;
    if (route === '/events') return '';
    body = payload; return new Promise((resolve) => { release = resolve; });
  });
  await agent.start();
  const first = agent.frame('data:image/jpeg;base64,' + jpeg);
  assert.equal((await agent.frame(jpeg)).busy, true);
  assert.equal(agent.frames, 0);
  assert.equal(body, jpeg);
  release('QACK img 320x240 heap 20000 via=wifi');
  assert.equal((await first).ok, true); assert.equal(agent.frames, 1); assert.ok(agent.lastAck);
});

test('HTTP response without a valid draw acknowledgment is a failure', async () => {
  const agent = fixture(async (_, route) => route === '/status' ? status : route === '/events' ? '' : 'QACK skip badjpg');
  await agent.start();
  const result = await agent.frame(jpeg);
  assert.equal(result.ok, false); assert.equal(agent.frames, 0); assert.equal(agent.connected, false);
  assert.match(result.why, /did not acknowledge/);
});

test('CYD frames exceeding its HTTP memory budget never reach the device', async () => {
  let imageRequests = 0;
  const agent = fixture(async (_, route) => {
    if (route === '/status') return status;
    if (route === '/events') return '';
    imageRequests++; return 'QACK img 320x240';
  });
  await agent.start();
  const large = Buffer.alloc(13 * 1024, 1); large[0] = 255; large[1] = 216;
  large[large.length - 2] = 255; large[large.length - 1] = 217;
  const result = await agent.frame(large.toString('base64'));
  assert.equal(result.ok, false); assert.equal(imageRequests, 0);
  assert.match(result.why, /13312 bytes/); assert.equal(agent.state().lastFrameBytes, 13312);
  assert.equal(agent.state().frameBudget, 12288);
});

test('old touch events are drained and new taps are delivered once', async () => {
  let events = '10 TOUCH down 40 80\n11 TOUCH up\n';
  const agent = fixture(async (_, route) => route === '/status' ? status : events);
  await agent.start();
  assert.deepEqual((await agent.events()).events, []);
  events += '15 TOUCH down 210 180\n16 TOUCH up\n';
  const fresh = (await agent.events()).events;
  assert.deepEqual(fresh, [{kind: 'touch', at: 15, x: 210, y: 180}]);
  assert.deepEqual((await agent.events()).events, []);
});

test('automatic reconnect rejects a changed physical device', async () => {
  const agent = fixture();
  await agent.connect('10.1.2.3');
  agent.request = async () => status.replace('dc:b4:d9:23:11:78', 'dc:b4:d9:23:11:79');
  await assert.rejects(agent.start({automatic: true}), /identity changed/);
  assert.equal(agent.running, false); assert.equal(agent.connected, false);
});

test('stopping invalidates a late acknowledgment and prevents new frames', async () => {
  let release;
  const agent = fixture(async (_, route) => route === '/status' ? status : route === '/events' ? '' : new Promise((resolve) => { release = resolve; }));
  await agent.start();
  const sending = agent.frame(jpeg); agent.stop(); release('QACK img 320x240 via=wifi');
  assert.equal((await sending).ok, false); assert.equal(agent.frames, 0);
  assert.equal((await agent.frame(jpeg)).ok, false);
});

test('discovery returns only verified Quanta results and unknown firmware is not flash ready', async () => {
  const agent = fixture(async (host) => host === '10.1.2.3' ? status : 'ordinary device');
  const result = await agent.discover();
  assert.equal(result.devices.length, 1);
  const firmware = firmwareReadiness('/nonexistent/quanta', parseStatus(status));
  assert.equal(firmware.networkFlash, false); assert.equal(firmware.flashReady, false);
});

test('avatar mode consumes no frames and top-left mode events resume Pine', async () => {
  let events = '', writes = 0;
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status + ' pine=1 display=avatar ota=1';
    if (route === '/events') return events;
    if (body === 'QCMD PINELEASE 15') return 'QACK pinelease 15';
    if (body === 'QCMD PINEMODE 1') return 'QACK pinemode pine';
    if (body === 'QCMD PINEMODE 0') return 'QACK pinemode avatar';
    writes++; return 'QACK img 320x240 via=wifi';
  });
  await agent.start(); await agent.displayMode('avatar');
  assert.equal((await agent.frame(jpeg)).avatar, true); assert.equal(writes, 0);
  events = '40 PINEMODE pine\n41 TOUCH down 10 10';
  assert.equal((await agent.events()).events[0].mode, 'pine');
  assert.equal((await agent.frame(jpeg)).ok, true); assert.equal(writes, 1);
});

test('discovery probes bounded candidates read-only and reconnect follows identity after a DHCP change', async () => {
  const agent = fixture();
  agent.candidates = () => ['10.1.2.4'];
  await agent.start(); agent.connected = false;
  agent.request = async (host, route) => {
    if (host !== '10.1.2.4') throw new Error('offline');
    if (route === '/status') return status;
    return 'QACK img 320x240';
  };
  assert.equal((await agent.frame(jpeg)).ok, true);
  assert.equal(agent.host, '10.1.2.4');
  assert.equal(agent.config().identity, 'dc:b4:d9:23:11:78');
});

test('firmware source provides one compatible top-left switch while retaining gallery and Quanta commands', () => {
  const {pineSource} = require('../desktop/lcd-firmware.cjs');
  const source = '#include <Preferences.h>\n// Touch API\nvoid drawCornerUI(){ }\nvoid pumpHold(){ }\n'
    + 'if(!gCal.valid){ sx=ry; sy=rx; return true; } // uncalibrated raw passthrough\n'
    + 'if(touchReadScreen(x,y) && millis()-gGalTouchLock>400){ }\n'
    + 'if(gMenuOpen){ menuTap(x,y); }\nif(line.startsWith("QCMD CLEAR")){}\n'
    + '+" id="+WiFi.macAddress();\n+" heap="+String(ESP.getFreeHeap());\n}\n'
    + 'ArduinoOTA.onStart([](){ drawFlashingScreen();\nArduinoOTA.onEnd([](){ Serial.println(\nArduinoOTA.onError([](ota_error_t e){ Serial.println(\n'
    + 'drawTouchRipple(); // event\nif(gRipX<0) return; uint32_t age=millis()-gRipMs;\nQCMD GALPLAY QSAVEBEGIN QSAVEEND\nvoid setup(){ }\n'
    + 'void pumpTouch(){ int16_t x,y; bool down=touchReadScreen(x,y); }\nvoid hGalFrame(){ }\nserver.begin();\nserver.handleClient();\npumpGallery(); //\n'
    + 'gfx->fillRect(3,3,7,9,BLACK);       gfx->setCursor(3,3);     gfx->print("R");\n'
    + '// ---- color JPEG\nbool jpgOutput( ){ int s = gJpgScale; t->draw16bitRGBBitmap(x,y,bitmap,w,h); }\n'
    + 'void drawJpegBuf(){ } // host frame takes over (+ note when, for idle-resume)\n// On-screen "copying" overlay\n'
    + 'void drawCopyOverlay(){ int W = gfx->width(); gfx->fillRect(0, 0, W, 26, BLACK); gfx->drawFastHLine(0, 26, W, AC); gfx->setCursor(4, 3); gfx->setCursor(4, 14); if (d.length() > 38) d = "..." + d.substring(d.length() - 35); gfx->fillRect(1, 24, pw, 2, AC); }\n// CANONICAL glyphy face';
  const patched = pineSource(source);
  assert.match(patched, /gPineStartX<gfx->width\(\)\/5 && gPineStartY<gfx->height\(\)\/4/);
  assert.match(patched, /pineView\(!gPineMode,true\)/);
  assert.match(patched, /pineBlitOutsideCorner\(t, x,y,bitmap,w,h\)/);
  assert.match(patched, /pineDrawCorner\(fb!=nullptr\)/);
  assert.doesNotMatch(patched, /gfx->print\("R"\)/);
  assert.match(patched, /if\(!pineRippleOutsideCorner\(gRipX,gRipY,85\)\)\{gRipX=-1;return;\}/);
  assert.match(patched, /gfx->fillRect\(X, 0, W, 26, BLACK\)/);
  assert.match(patched, /gfx->setCursor\(X\+4, 3\)/);
  assert.match(patched, /int chars=max\(3,\(W-8\)\/6-8\)/);
  assert.match(patched, /pine=1 display=/);
  assert.match(patched, /QCMD GALPLAY QSAVEBEGIN QSAVEEND/);
  assert.doesNotMatch(patched, /uncalibrated raw passthrough/);
  assert.match(patched, /!pineActive\(\) && !gPineSaver && y>=40/);
  assert.match(patched, /PINE_MAX_JPEG=24576/);
  assert.match(patched, /pineServer.begin\(\)/);
  assert.match(patched, /pineTouch\(down,x,y\)/);
  assert.match(patched, /gPineWakeConsumed\)\{gPineWakeConsumed=false;return true;/);
  assert.throws(() => pineSource('unknown firmware'), /needs review/);
});

test('protocol 2 negotiates binary frames and preserves measured draw acknowledgments', async () => {
  let binaryBytes, httpImages = 0;
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status + ' pine=1 pineproto=2 stream=3233 maxjpg=24576 gesture=1';
    if (route === '/events') return '';
    if (body === 'QCMD PINELEASE 15') return 'QACK pinelease 15';
    if (body === 'QCMD PINEMODE 1') return 'QACK pinemode pine';
    if (body === 'QCMD PINEIDLE 0') return 'QACK pineidle 0';
    httpImages++; return 'QACK img 320x240';
  });
  agent.streamFactory = ({identity}) => ({close() {}, async frame(bytes) {
    assert.equal(identity, 'dc:b4:d9:23:11:78');binaryBytes = bytes;
    return 'QACK img 320x240 seq=1 dec=73 draw=0 rx=4 via=stream';
  }});
  await agent.start();
  assert.equal((await agent.frame(jpeg)).ok, true);
  assert.equal(httpImages, 0); assert.deepEqual(binaryBytes, Buffer.from(jpeg, 'base64'));
  assert.equal(agent.state().transport, 'binary-tcp');assert.equal(agent.state().frameBudget, 24576);
  assert.equal(agent.state().timing.decodeAndDrawMs, 73);
});

test('idle configuration is synchronized only when changed and manual mode preserves choices', async () => {
  const commands = [];
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status + ' pine=1 pineproto=2';
    if (route === '/events') return '';
    commands.push(body);
    if (body === 'QCMD PINELEASE 15') return 'QACK pinelease 15';
    if (body === 'QCMD PINEMODE 1') return 'QACK pinemode pine';
    return body.replace('QCMD PINEIDLE', 'QACK pineidle');
  });
  agent.configure({screensaverEnabled: true, screensaverSeconds: 90, paperStyle: 'tabloid', chatOverlay: false});
  await agent.start(); await agent.syncSettings(); await agent.syncSettings();
  assert.equal(commands.filter((s) => s === 'QCMD PINEIDLE 90').length, 1);
  agent.configure({screensaverSeconds: 120}); await agent.syncSettings();
  assert.equal(commands.at(-1), 'QCMD PINEIDLE 120');
  assert.equal(agent.config().paperStyle, 'tabloid'); assert.equal(agent.config().chatOverlay, false);
});

test('protocol 2 ignores contact-down, delivers swipe/tap once and consumes screensaver wake', async () => {
  let events = '';
  const agent = fixture(async (_, route) => route === '/status' ? status + ' pineproto=2 gesture=1'
    : route === '/cmd' ? 'QACK pineidle 0' : events);
  await agent.start();
  events = '1 TOUCH down 8 8\n2 SWIPE down 70 80\n3 TOUCH tap 100 100\n4 PINEMODE avatar\n5 PINESAVER 1';
  assert.deepEqual((await agent.events()).events.map((row) => row.kind), ['swipe','touch','mode','screensaver']);
  assert.equal(agent.device.screensaver, true);
  events += '\n6 PINEMODE pine\n7 PINEWAKE\n8 SWIPE up 80 40';
  const fresh = (await agent.events()).events;
  assert.deepEqual(fresh.map((row) => row.kind), ['mode','wake','swipe']);
  assert.equal(fresh.at(-1).direction, 'up'); assert.equal(agent.device.screensaver, false);
  assert.deepEqual((await agent.events()).events, []);
});

test('avatar input polling renews the lease and discovers a reboot without sending a JPEG', async () => {
  let mode = 'avatar', uptime = 40, leases = 0, idleWrites = 0;
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status.replace('up=20', 'up=' + uptime) + ' pine=1 pineproto=2 display=' + mode;
    if (route === '/events') return '';
    if (body === 'QCMD PINELEASE 15') {leases++;return 'QACK pinelease 15';}
    if (body === 'QCMD PINEIDLE 0') {idleWrites++;return 'QACK pineidle 0';}
    throw new Error('Unexpected frame or mode write: ' + body);
  });
  await agent.connect('10.1.2.3');agent.running = true;
  await agent.events();assert.equal(leases, 1);assert.equal(agent.frames, 0);
  mode = 'pine';uptime = 2;agent.nextStatusPoll = 0;
  const result = await agent.events();
  assert.equal(result.device.displayMode, 'pine');assert.equal(leases, 2);assert.equal(idleWrites, 1);
  assert.deepEqual(result.events, [{kind:'mode',mode:'pine'}]);assert.equal(agent.frames, 0);
});

test('avatar reconnect refuses another physical identity', async () => {
  const agent = fixture();await agent.connect('10.1.2.3');agent.running = true;agent.connected = false;agent.nextStatusPoll = 0;
  agent.request = async () => status.replace('dc:b4:d9:23:11:78', 'dc:b4:d9:23:11:79');
  await assert.rejects(agent.events(), /identity changed/);assert.equal(agent.connected, false);
});

test('disabling an armed saver wakes it, while a manual avatar or disabled preview is preserved', async () => {
  const commands = [];
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status + ' pineproto=2 idle=90 saver=1 display=avatar';
    commands.push(body);return body === 'QCMD PINEIDLE 0' ? 'QACK pineidle 0' : 'QACK pinesaver 0';
  });
  await agent.connect('10.1.2.3');await agent.syncSettings();
  assert.deepEqual(commands, ['QCMD PINEIDLE 0','QCMD PINESAVER 0']);assert.equal(agent.device.displayMode, 'pine');
  agent.device.displayMode = 'avatar';agent.device.screensaver = false;await agent.syncSettings();
  assert.equal(agent.device.displayMode, 'avatar');assert.equal(commands.length, 2);
  agent.device.screensaver = true;await agent.syncSettings();
  assert.equal(agent.device.screensaver, true);assert.equal(commands.length, 2);
});

test('USB retains its proven 12 KB cap even when firmware advertises a network binary port', async () => {
  const agent = fixture(async () => status + ' pineproto=2 stream=3233 maxjpg=24576');
  await agent.connect('COM8');assert.equal(agent.state().transport, 'usb');assert.equal(agent.state().frameBudget, 12288);
});

test('intentional avatar transition closes an in-flight binary frame without a false disconnect', async () => {
  let rejectFrame;
  const agent = fixture(async (_, route, body) => {
    if (route === '/status') return status + ' pineproto=2 stream=3233 maxjpg=24576';
    if (route === '/cmd') return 'QACK pineidle 0';
    return '';
  });
  agent.streamFactory = () => ({close() {}, frame: () => new Promise((_, reject) => {rejectFrame = reject;})});
  await agent.start();const pending = agent.frame(jpeg);
  agent.device.displayMode = 'avatar';rejectFrame(new Error('LCD frame connection closed.'));
  assert.equal((await pending).avatar, true);assert.equal(agent.failed, 0);assert.equal(agent.frames, 0);assert.equal(agent.connected, true);
});

test('LCD sample download saves actual audio in the selected folder and rejects station errors', async () => {
  const fs = require('node:fs/promises'); const os = require('node:os'); const path = require('node:path');
  const {saveLcdSample} = require('../desktop/lcd-samples.cjs');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'pine-sample-test-'));
  try {
    const input = {id: 'booth:42', config: {baseUrl: 'http://station', saveDir: directory, apiKey: 'test-token'},
      fetcher: async (url, opts) => {
        assert.match(url, /line=booth%3A42/); assert.equal(opts.headers.Authorization, 'Bearer test-token');
        return new Response(Buffer.from('audio bytes'), {headers: {'content-type': 'audio/wav', 'x-pine-exact': '1'}});
      }};
    const result = await saveLcdSample(input);
    assert.equal(result.exact, true); assert.equal(path.dirname(result.file), directory);
    assert.equal(await fs.readFile(result.file, 'utf8'), 'audio bytes');
    await assert.rejects(saveLcdSample({...input, fetcher: async () => new Response('error', {status: 404})}), /HTTP 404/);
    assert.equal((await fs.readdir(directory)).length, 1);
  } finally { await fs.rm(directory, {recursive: true}); }
});

test('LCD shows a current long spoken turn before completed chat exists', () => {
  const {stationRows} = require('../desktop/renderer/lcd-dialogue.js');
  const result = stationRows({chat: [], speaking_now: {id: 'live', who: 'dj', text: 'The first syllable', aired: 'airing'}});
  assert.equal(result[0].id, 'live'); assert.equal(result[0].lcdStatus, 'Playing'); assert.equal(result[0].lcdAudio, true);
});

test('LCD follows round timing and keeps prepared activity distinct from real audio', () => {
  const {stationRows} = require('../desktop/renderer/lcd-dialogue.js');
  const station = {chat: [{id: 'a', text: 'First', aired: 'prepared'}, {id: 'b', text: 'Second', aired: 'prepared'},
    {id: 'info', text: 'An image arrived', aired: 'analysis'}], stream_now: {at: 100, length: 180, rows: [
      {id: 'a', text: 'First', from: 0, until: 90}, {id: 'b', text: 'Second', from: 90, until: 180}]}};
  const early = stationRows(station, 101000);
  assert.equal(early.at(-1).id, 'a'); assert.equal(early.at(-1).lcdStatus, 'Playing');
  assert.equal(early.find((r) => r.id === 'b').lcdAudio, false);
  assert.equal(early.find((r) => r.id === 'info').lcdStatus, 'Booth activity');
  const next = stationRows(station, 191000);
  assert.equal(next.at(-1).id, 'b'); assert.equal(next.at(-1).air_at, 190);
  assert.equal(next.filter((r) => r.id === 'b').length, 1);
  assert.equal(stationRows(station, 290000).some((r) => r.lcdStatus === 'Playing'), false);
});
