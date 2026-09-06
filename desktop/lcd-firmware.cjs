// Board-specific builds live in Pine Box userData. Installed Quanta source,
// saved device galleries and unrelated serial devices are never modified.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const {scriptFile} = require('./lcd-runtime.cjs');
const {firmwareReadiness, endpoint} = require('./lcd-agent.cjs');

function pineSource(source) {
  source = source.replace(/\r\n/g, '\n');
  const replace = (before, after) => {
    if (!source.includes(before)) throw new Error('Quanta source changed; Pine firmware patch needs review: ' + before.slice(0, 65));
    source = source.replace(before, after);
  };
  replace('#include <Preferences.h>', '#include <Preferences.h>\n#include <esp_ota_ops.h>\n#include <esp_mac.h>\n'
    + 'static uint32_t gPineLeaseUntil=0;\nstatic bool gPineMode=false;\nstatic bool pineActive(){ return gPineMode && (int32_t)(gPineLeaseUntil-millis())>0; }\n'
    + 'static void pineRemember(){ Preferences p; p.begin("pine",false); p.putBool("mode",gPineMode); p.end(); }\n'
    + 'static String pineIdentity(){ uint8_t m[6]; esp_read_mac(m,ESP_MAC_WIFI_STA); char out[18]; snprintf(out,sizeof(out),"%02x:%02x:%02x:%02x:%02x:%02x",m[0],m[1],m[2],m[3],m[4],m[5]); return String(out); }');
  replace('void drawCornerUI(){', 'void drawCornerUI(){ if(pineActive()) return;');
  // The local Quanta v49 tree defines these only for Elecrow while calling
  // them for every Wi-Fi board. Keep the existing CYD build compilable.
  replace('// Touch API', '#if !defined(QUANTA_STYLE_LUT)\nvoid cornerFlash(const String& message){}\nvoid cycleSendMode(){}\n#endif\n'
    + '#if !defined(QUANTA_TOUCH_GT911)\nstatic int16_t gTouchRawX=0,gTouchRawY=0;\n#endif\n\n// Touch API');
  replace('void pumpHold(){', 'void pumpHold(){ if(pineActive()){ gHoldZone=0; gHoldFired=false; return; }');
  // Quanta skips calibration when a saved gallery exists. Its raw passthrough
  // otherwise reports 12-bit ADC coordinates instead of display pixels.
  replace('if(!gCal.valid){ sx=ry; sy=rx; return true; } // uncalibrated raw passthrough',
    'gTouchRawX=rx; gTouchRawY=ry;\n  if(!gCal.valid){ float nx=constrain((ry-250.0f)/3550.0f,0.0f,1.0f), ny=constrain((rx-250.0f)/3550.0f,0.0f,1.0f); '
    + 'int r=(gfx->getRotation()-QUANTA_ROT+4)&3; float tx=nx; if(r==1){ nx=ny; ny=1-tx; } else if(r==2){ nx=1-nx; ny=1-ny; } else if(r==3){ nx=1-ny; ny=tx; } '
    + 'sx=nx*(gfx->width()-1); sy=ny*(gfx->height()-1); return true; }');
  replace('if(touchReadScreen(x,y) && millis()-gGalTouchLock>400){',
    'if(touchReadScreen(x,y) && !pineActive() && !(x<gfx->width()/5 && y<gfx->height()/4) && millis()-gGalTouchLock>400){');
  replace('if(gMenuOpen){ menuTap(x,y); }', 'if(x < W/5 && y < H/4){ gPineMode=!gPineMode; pineRemember(); gMenuOpen=false; gotContent=false; gLastHostMs=0; gGalFrame=0; gCacheIdx=0; '
    + 'String mode=String("PINEMODE ")+(gPineMode?"pine":"avatar"); pushEvent(mode); Serial.println("QEVT "+mode); } '
    + 'else if(pineActive()){ /* Pine receives the raw event below. */ } else if(gMenuOpen){ menuTap(x,y); }');
  replace('if(line.startsWith("QCMD CLEAR"))',
    'if(line.startsWith("QCMD PINEMODE ")){ gPineMode=line.substring(14).toInt()!=0; pineRemember(); gMenuOpen=false; gotContent=false; gLastHostMs=0; gGalFrame=0; gCacheIdx=0; qResp(String("QACK pinemode ")+(gPineMode?"pine":"avatar")); }\n'
    + '  else if(line.startsWith("QCMD PINELEASE ")){ int s=constrain(line.substring(15).toInt(),0,30); gPineLeaseUntil=s?millis()+s*1000:0; gMenuOpen=false; qResp("QACK pinelease "+String(s)); }\n  else if(line.startsWith("QCMD CLEAR"))');
  replace('+" id="+WiFi.macAddress();', '+" id="+WiFi.macAddress()+" pine=1 display="+String(gPineMode?"pine":"avatar")+" ota="+String(esp_ota_get_next_update_partition(nullptr)?1:0);');
  replace('+" heap="+String(ESP.getFreeHeap());\n}', '+" heap="+String(ESP.getFreeHeap())+" id="+pineIdentity()+" pine=1 display="+String(gPineMode?"pine":"avatar")+" ota="+String(esp_ota_get_next_update_partition(nullptr)?1:0);\n}');
  replace('drawTouchRipple(); //', 'drawTouchRipple(); gfx->fillRect(2,2,23,12,BLACK); gfx->setTextSize(1); gfx->setTextColor(WHITE,BLACK); gfx->setCursor(4,4); gfx->print(gPineMode?"AV":"PB"); //');
  replace('void setup(){', 'void setup(){ { Preferences p; p.begin("pine",true); gPineMode=p.getBool("mode",false); p.end(); }');
  replace('ArduinoOTA.onStart([](){ drawFlashingScreen();', 'ArduinoOTA.onProgress([](unsigned int, unsigned int){ gLoopBeat++; });\n  ArduinoOTA.onStart([](){ gWdPause=true; drawFlashingScreen();');
  replace('ArduinoOTA.onEnd([](){ Serial.println(', 'ArduinoOTA.onEnd([](){ gWdPause=false; Serial.println(');
  replace('ArduinoOTA.onError([](ota_error_t e){ Serial.println(', 'ArduinoOTA.onError([](ota_error_t e){ gWdPause=false; Serial.println(');
  return source;
}

function prepareSource(quantaRoot, destination) {
  const source = path.join(path.resolve(quantaRoot), 'system');
  const firmware = path.join(source, 'firmware', 'quanta-screen');
  const sketch = path.join(destination, 'system', 'firmware', 'quanta-screen');
  const scriptFolder = path.join(destination, 'system', 'scripts', 'device');
  const patched = pineSource(fs.readFileSync(path.join(firmware, 'quanta-screen.ino'), 'utf8'));
  fs.mkdirSync(sketch, {recursive: true}); fs.mkdirSync(scriptFolder, {recursive: true});
  for (const file of fs.readdirSync(firmware)) {
    if (/\.(?:h|ino|json)$/.test(file) && file !== 'quanta_config.h') fs.copyFileSync(path.join(firmware, file), path.join(sketch, file));
  }
  for (const file of ['common.ps1', 'build-flash.ps1', 'identify.ps1']) fs.copyFileSync(path.join(source, 'scripts', 'device', file), path.join(scriptFolder, file));
  // Quanta's legacy helper silently falls back to another COM port when one
  // disappears. A programmer must keep the explicitly selected port instead.
  const common = path.join(scriptFolder, 'common.ps1');
  let helper = fs.readFileSync(common, 'utf8');
  const start = helper.indexOf('function Find-Esp32Port {');
  const end = helper.indexOf('\n# ---- toolchain', start);
  if (start < 0 || end < 0) throw new Error('Quanta serial selection helper changed; cannot safely prepare firmware tools.');
  helper = helper.slice(0, start) + `function Find-Esp32Port {
  param([string]$Port)
  if (-not $Port) { throw 'Select a verified LCD COM port explicitly.' }
  $device = @(Get-SerialDevices | Where-Object { $_.Port -eq $Port -and $_.IsEsp32 -and -not $_.IsReachy })
  if ($device.Count -ne 1) { throw 'The selected LCD port is missing or protected; no other port will be used.' }
  return $Port
}
` + helper.slice(end);
  fs.writeFileSync(common, helper, 'utf8');
  fs.writeFileSync(path.join(sketch, 'quanta-screen.ino'), patched, 'utf8');
  return sketch;
}

function sha(file) { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
function validateArtifact(artifact, board, identity = '') {
  if (!artifact || artifact.board !== board || !fs.existsSync(artifact.binary)) throw new Error('Build Pine firmware for this exact board first.');
  if (sha(artifact.binary) !== artifact.sha256) throw new Error('Firmware binary changed since build; rebuild before installing.');
  if (identity && artifact.identity && identity !== artifact.identity) throw new Error('Firmware was prepared for a different LCD identity.');
  return artifact;
}

class LcdFirmware {
  constructor({root, config, agent, run = spawn}) {
    this.root = root; this.config = config; this.agent = agent; this.run = run;
    this.job = null; this.artifact = null; this.usb = null;
    try { this.artifact = JSON.parse(fs.readFileSync(path.join(root, 'artifact.json'), 'utf8')); } catch {}
  }
  state() {
    const base = firmwareReadiness(this.config().quantaRoot, this.agent.device);
    let artifact = this.artifact;
    try { if (artifact) validateArtifact(artifact, artifact.board); } catch { artifact = null; }
    return {...base, networkFlash: base.networkFlash && !/^COM/i.test(this.agent.host), artifact, usb: this.usb, job: this.job,
      flashReady: !!artifact && artifact.board === this.agent.device?.board};
  }
  launch(action, input = {}) {
    if (this.job?.running) throw new Error('A firmware operation is already running.');
    if (!['ports', 'identify', 'build', 'usb', 'ota'].includes(action)) throw new Error('Unknown firmware operation.');
    if (process.platform !== 'win32') throw new Error('Quanta firmware programming currently requires Windows.');
    const root = path.resolve(this.config().quantaRoot);
    const registry = JSON.parse(fs.readFileSync(path.join(root, 'system', 'firmware', 'quanta-screen', 'boards.json'), 'utf8')).boards;
    const board = String(input.board || this.agent.device?.board || '');
    if (!['ports', 'identify'].includes(action) && !registry[board]?.define) throw new Error('Select a supported Quanta board.');
    const port = String(input.port || '');
    if (['identify', 'usb'].includes(action) && !/^COM[1-9][0-9]{0,3}$/.test(port)) throw new Error('Select the LCD USB port.');
    if (action === 'build' && this.agent.device && board !== this.agent.device.board) throw new Error('The selected board differs from the connected LCD.');
    if (['usb', 'ota'].includes(action)) validateArtifact(this.artifact, board, this.agent.device?.identity);
    if (action === 'usb') {
      if (!this.usb?.ok || this.usb.port !== port) throw new Error('Identify this USB port before installing firmware.');
      const expected = this.agent.device?.identity || this.artifact.identity;
      if (expected && String(this.usb.mac).toLowerCase() !== expected) throw new Error('USB identity does not match the connected LCD.');
      if (this.usb.chipId !== registry[board].chip) throw new Error('USB chip family does not match the board profile.');
    }
    if (action === 'ota' && (!this.agent.connected || !this.state().networkFlash)) throw new Error('Connect a matching LCD with OTA support first.');
    const workspace = path.join(this.root, 'build-source');
    const sketch = prepareSource(root, workspace);
    const payload = {action, board, port, workspace, host: action === 'ota' ? endpoint(this.agent.host) : '',
      identity: this.agent.device?.identity || this.usb?.mac || '', binary: this.artifact?.binary || '',
      ssid: String(input.ssid || ''), pass: String(input.pass || '')};
    const taskFile = path.join(this.root, 'job-' + crypto.randomUUID() + '.json');
    fs.writeFileSync(taskFile, JSON.stringify(payload), {mode: 0o600});
    this.job = {action, running: true, started: Date.now(), log: [], error: '', result: null};
    const job = this.job;
    let released = Promise.resolve();
    if (['identify', 'usb', 'ota'].includes(action)) { this.agent.stop(); released = Promise.resolve(this.agent.releaseTransport?.()); }
    let buffer = '';
    const append = (chunk) => {
      buffer += String(chunk); const parts = buffer.split(/\r?\n/); buffer = parts.pop();
      for (const line of parts) {
        if (!line.trim()) continue;
        if (line.startsWith('PINEJSON ')) { try { job.result = JSON.parse(line.slice(9)); } catch {} }
        else job.log.push(line.replaceAll(payload.pass || '\u0000', '[redacted]').slice(0, 1500));
      }
      job.log = job.log.slice(-100);
    };
    const finish = (code, error = '') => {
      if (!job.running) return;
      append('\n'); job.running = false; job.finished = Date.now();
      try {
        if (code !== 0) throw new Error(error || 'Firmware operation failed (exit ' + code + '). See the log.');
        if (action === 'identify') {
          if (!job.result?.ok || !job.result.mac) throw new Error('USB identification did not return a device MAC.');
          this.usb = job.result;
        }
        if (action === 'build') {
          const binary = path.join(sketch, 'build', registry[board].buildSubdir, 'quanta-screen.ino.bin');
          this.artifact = {board, identity: payload.identity.toLowerCase(), version: registry[board].fwVersion,
            pine: 1, binary, sha256: sha(binary), built: Date.now()};
          fs.writeFileSync(path.join(this.root, 'artifact.json'), JSON.stringify(this.artifact, null, 2));
          job.result = this.artifact;
        }
        if (['usb', 'ota'].includes(action)) job.log.push('Upload completed. Connect / test to verify the device after reboot, then Start.');
      } catch (error) { job.error = error.message; }
      try { fs.writeFileSync(path.join(this.root, 'last-job.json'), JSON.stringify(job, null, 2)); } catch {}
      try { fs.unlinkSync(taskFile); } catch {}
      try { fs.unlinkSync(path.join(sketch, 'quanta_config.h')); } catch {}
    };
    released.then(() => {
      const child = this.run('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptFile('lcd-firmware-worker.ps1'), '-JobFile', taskFile],
        {windowsHide: true, cwd: workspace, stdio: ['ignore', 'pipe', 'pipe']});
      child.stdout.on('data', append); child.stderr.on('data', append);
      child.once('error', (error) => finish(-1, error.message)); child.once('close', (code) => finish(code));
    }).catch((error) => finish(-1, error.message));
    return this.state();
  }
}

module.exports = {LcdFirmware, pineSource, prepareSource, validateArtifact};
