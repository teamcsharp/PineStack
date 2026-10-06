const { app, BrowserWindow, ipcMain, session, shell } = require("electron");
/* [desk-debug-port] a DevTools port for the live desk, bound to this machine, only while
   <userData>/debug-port.txt names one - delete the file and relaunch to close it. */
try { const fs0 = require("node:fs"), path0 = require("node:path"); const port0 = String(fs0.readFileSync(path0.join(app.getPath("userData"), "debug-port.txt"), "utf8")).trim(); if (port0.length >= 4 && port0.length <= 5 && Number.isInteger(Number(port0))) { app.commandLine.appendSwitch("remote-debugging-port", port0); app.commandLine.appendSwitch("remote-allow-origins", "*"); } } catch (_) { /* no flag, no port */ }
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { stageRendererUpdates } = require('./hot-renderer.cjs');
const { fetchJson: readStationJson } = require('./json-request.cjs');
const { LcdAgent, deviceRequest } = require("./lcd-agent.cjs");
const { LcdSerial, usbDisplays } = require("./lcd-serial.cjs");
const { LcdFirmware } = require("./lcd-firmware.cjs");
const { saveLcdSample } = require("./lcd-samples.cjs");
const { TerminalHost } = require("./terminal-host.cjs");
const clipMux = require("./clip-mux.cjs");
/* #1183: THE MPC'S DISK, WHICH ON THIS MACHINE IS A DRIVE LETTER.
 *
 * renderer/sampler.js and renderer/sampler-kits.js have been calling
 * usbState / usbPick / usbSend / usbList / usbRead on this surface for as
 * long as they have existed and getting "This terminal cannot reach a USB
 * disk" every time, because only the tablet bridge answered them. The
 * module says what a "USB device" honestly is here, and what it does not
 * pretend to know. */
const { UsbDisk } = require("./usb-disk.cjs");
/* #1182: THE ROLLING RECORD OF THIS WINDOW.
 *
 * "Only the tablet has a rolling recorder; this window does not, so a local
 * capture still films forwards" - the note at glass:clip, now out of date.
 * The renderer films (renderer/screen-ring.js) and hands finished pieces
 * down; this keeps them on disk and cuts what is asked for out of them. */
const { ScreenRing, HOLD_MIN_S, HOLD_MAX_S, HOLD_DEFAULT_S,
  AUDIO_SOURCE } = require("./screen-ring.cjs");
const screenRing = new ScreenRing();
/* #1205: WHERE THE APPLICATION'S OWN SOUND CAN BE CAPTURED AT ALL.
 *
 * Electron 37.10.3's electron.d.ts, interface Streams: "Specifying a loopback
 * device will capture system audio, and is currently only supported on
 * Windows." One constant, read by the display-media handler and by the road
 * that tells the renderer why a recording is silent, so the two can never
 * disagree about what this machine can do. */
const LOOPBACK_HERE = process.platform === "win32";
/* #1205c: PANEL_FRAME_FOR_AUDIO.
 *
 * The station's own page, as a frame the capture can be pointed at. The
 * broadcast usually plays in the panel; other app sounds also use the shell. This frame
 * is one source in the discovered mix. Kept up to date: the handler
 * runs inside a capture negotiation and must not go searching. */
let panelFrame = null;
// Audio requests are serialized by the trusted recorder. Each selection is
// consumed once, and can name only frames attached to this Pine window.
let ringAudioTarget = 'panel';
const { ReplayAudioFrames } = require('./replay-audio-frames.cjs');
const ringAudioFrames = new ReplayAudioFrames({ getWindow: () => win, getPanel: panelFrameNow,
  onChanged: catalog => {
    try { if (win && !win.isDestroyed()) win.webContents.send('replay-audio-sources-changed', catalog); }
    catch (_) { /* a closing renderer will discover the catalog on its next start */ }
  } });

/* #1205c / #1207: THE LINE THAT CAUGHT THIS.
 *
 * A silent recording has a REASON and until #1205c it lived only in the
 * renderer's console, which nobody can read from outside the app. This
 * appends one line per capture negotiation and one per recorder start to a
 * file a person can open in a text editor. It is what finally showed that
 * getDisplayMedia was being refused outright -
 *
 *     the window would not give up its sound: Error starting capture
 *
 * - after every meter in the app had said the sound was fine. It names BOTH
 * streams now (#1207), because with two rings "the recording is silent" has
 * two possible causes, and the next fault will be found the way this one
 * was: by reading which of them did not start. */
function ringSound(line) {
  try {
    fs.appendFileSync(path.join(os.tmpdir(), "pinebox-ring-sound.log"),
      new Date().toISOString() + " " + String(line) + String.fromCharCode(10));
  } catch (error) { /* a diagnostic may never stop a recording */ }
}

function panelFrameNow() {
  try {
    if (panelFrame && !panelFrame.isDestroyed() && panelFrame.mainFrame) {
      return panelFrame.mainFrame;
    }
  } catch (error) { /* a frame that has gone is not a frame */ }
  return null;
}

function watchPanelFrame(host) {
  if (!host) return;
  try {
    host.on("did-attach-webview", (_event, contents) => {
      const keep = () => {
        try {
          const url = String(contents.getURL() || "");
          /* The station, on whatever host this desk is pointed at. The other
           * webviews in this window are the radio, the guide, System2 and the
           * slides; their audio sources are tracked separately below. */
          if (/\/(?:$|\?)/.test(url) || url.indexOf("/panel") >= 0
              || url === String((readConfig() || {}).baseUrl || "") + "/") {
            panelFrame = contents;
          }
        } catch (error) { /* not fatal */ }
      };
      keep();
      contents.on("did-finish-load", keep);
      contents.on("did-navigate", keep);
      contents.on("destroyed", () => {
        if (panelFrame === contents) panelFrame = null;
      });
      ringAudioFrames.track(contents);
    });
  } catch (error) { /* an older Electron simply never sets it */ }
}

/* Twice the size and sharpened, for every picture taken of the tablet. */
const shotEnhance = require("./shot-enhance.cjs");
const glassParts = require("./terminal-glass.cjs");
/* For the local report: facts about THIS machine, where the tablet's
 * report has getprop and a battery. */
const os = require("node:os");

let win;
require('./audio-mixer.cjs').install({ ipcMain, getWindow: () => win, isToolsSender: e => pinePipTools.isSender(e) });
const stationTroubleshooter = require('./station-troubleshooter.cjs').install({
  getToolsWindow: () => pinePipTools.getWindow(),
  publishTools: state => pinePipTools.getWindow()?.webContents.send('station-troubleshooter:state',state), isToolsSender: e => pinePipTools.isSender(e), ipcMain, getWindow: () => win, restoreDesktop: restorePineWindow,
  audioOutput: repair => require('./audio-output.cjs').inspect(repair),
  request: (route, body) => fetchJson(`${readConfig().baseUrl}${route}`, { signal: AbortSignal.timeout(route === '/api/broadcast/fix/repair' ? 95000 : 45000), ...(body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) }) })
});
const pinePipTools = require('./pip-tools-window.cjs').install({ app, BrowserWindow, ipcMain, getWindow: () => win, rendererDir: path.join(__dirname,'renderer'), preload: path.join(__dirname,'preload.js'), readConfig, writeConfig });
const pinePipWindow = require('./pip-window.cjs').install({
  repairPlayback: () => { stationTroubleshooter.open(); stationTroubleshooter.run('playback').catch(error => console.error('[playback repair] ' + error.message)); },
  openTools: want => pinePipTools.open(want), isToolsSender: e => pinePipTools.isSender(e), publishTools: s => pinePipTools.publish(s),
  ipcMain, getWindow: () => win, readConfig, writeConfig, troubleshoot: () => stationTroubleshooter.open(),
  /* [pip-update] what this app owes itself, and the rebuild that settles it */
  updateOwed: () => pineUpdateOwed(), rebuild: () => reconstituteDesktop()
});
let backend = null;
let backendLog = [];
let reconstituting = false;

const desktopFaults = require("./desktop-health.cjs").install({
  app, getFile: () => path.join(app.getPath("userData"), "pinebox-health.jsonl")
});

// A dead stdout must never take the app down. Launched from a wrapper shell
// whose pipe has closed (or a terminal that went away), any console.* write
// throws EPIPE — and Electron's default uncaught-exception dialog turned a
// harmless log line into a crash popup. Swallow only that; rethrow the rest.
process.on("uncaughtException", (error) => {
  if (error && (error.code === "EPIPE" || error.code === "ERR_STREAM_DESTROYED")) return;
  try {
    const { dialog } = require("electron");
    dialog.showErrorBox(
      "A JavaScript error occurred in the main process",
      (error && (error.stack || error.message)) || String(error));
  } catch {}
});
for (const stream of [process.stdout, process.stderr]) {
  if (stream && typeof stream.on === "function") {
    stream.on("error", () => {});
  }
}

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

// #971 — THE APPLICATION IS CALLED PINE BOX, AND WINDOWS HAS TO KNOW IT.
//
// "make it where I'm able to pin this to the taskbar and load this as an
//  application ... give the program a pine box logo and icon for whenever
//  I pin it to the taskbar and have the application called Pine Box."
//
// Windows groups taskbar buttons, jump lists and pins by AppUserModelID.
// An app that never sets one inherits a default derived from the running
// executable — which here is electron.exe — so the taskbar button was
// "Electron", wearing the Electron icon, and pinning it captured
// electron.exe with NO arguments and the wrong working directory. That
// pin then launched a bare Electron with no app in it. The stale
// Electron.lnk found in the taskbar pin folder was exactly that.
//
// This id is the single string that has to match in three places: here,
// the Start Menu shortcut pine_box.exe writes, and nothing else. If they
// ever disagree, the running window and the pinned button become two
// separate buttons again.
const PINE_AUMID = "local.lilspark.pinebox";
if (process.platform === "win32") {
  try { app.setAppUserModelId(PINE_AUMID); } catch {}
}
// #971: renaming the app RENAMES ITS STATE DIRECTORY, which is not what
// was wanted and is not obvious. Electron derives userData as
// appData/<app.getName()>, so setName("Pine Box") silently moved it from
// %APPDATA%\pinebox-desktop to %APPDATA%\Pine Box - and the five call
// sites below it (the config file, agent-data, agent-venv, the rebuild
// script and its log) all followed, so the app came up with a blank
// config and lost the operator's saveDir. Caught by comparing the two
// files: the old one had saveDir pointing at the QuickSwap recordings
// share, the new one had no saveDir at all.
//
// The display name and the state directory are two different things, so
// they are set as two different things. The name is what Windows shows;
// the path stays exactly where every previous version of this app put it.
const PINE_USER_DATA = path.join(app.getPath("appData"), "pinebox-desktop");
try {
  app.setName("Pine Box");
  app.setPath("userData", PINE_USER_DATA);
} catch {}

// [pine-identity] PINE BOX, BY NAME AND BY ICON, ON EVERY WINDOW.
//
// "Make sure that the Pine Box icon is active everywhere, including in the
//  task manager and in the audio panel and anywhere that there's any mention
//  of this application that it's mentioned by name and mentioned by icon."
//
// Every window this app opens passes through here - including the ones no
// call site dresses (the kit-export and retirement-desk popups) and any
// window added later. Each wears the mark and carries the name. A page's own
// <title> ("The tablet, live") replaces the window title as it loads, so the
// name is added at that moment too; a page with no <title> keeps the window's
// title rather than showing its file name.
//
// Each window also carries the RELAUNCH details, so a pin made from the
// running button is the Start Menu shortcut's app - named Pine Box, wearing
// its icon - never the bare electron.exe #971 found pinned. They are read
// from that shortcut (pine_box.exe rewrites it on every launch), so there is
// one recipe and one versioned icon, not a second copy of them here.
//
// What no window can reach - Task Manager's name, the volume mixer's name
// and icon - lives in electron.exe's own resources and is written there by
// desktop/tools/apply_pinebox_identity.ps1 (pine_box.exe and the rebuild
// both run it; the file keeps its path, so Windows keeps its volume).
const PINE_ICON = path.join(__dirname, "assets", "pinebox.ico");
function pineTitle(title) {
  const t = String(title || "").trim();
  if (!t) return "Pine Box";
  return /\bpine box\b/i.test(t) ? t : "Pine Box - " + t;
}
let pineRelaunch;
function pineRelaunchDetails() {
  if (pineRelaunch !== undefined) return pineRelaunch;
  pineRelaunch = null;
  if (process.platform !== "win32") return pineRelaunch;
  try {
    const lnk = path.join(app.getPath("appData"), "Microsoft", "Windows",
      "Start Menu", "Programs", "Pine Box.lnk");
    const s = shell.readShortcutLink(lnk);
    if (s && s.appUserModelId === PINE_AUMID && s.icon && fs.existsSync(s.icon)) {
      pineRelaunch = {
        appId: PINE_AUMID,
        appIconPath: s.icon,
        appIconIndex: s.iconIndex || 0,
        // The app's absolute path, not ".": a pin made from a window has no
        // working directory to resolve "." against - the #971 blank Electron.
        relaunchCommand: `"${process.execPath}" "${app.getAppPath()}"`,
        relaunchDisplayName: "Pine Box"
      };
    }
  } catch { /* no shortcut yet: Windows falls back to its own lookup */ }
  return pineRelaunch;
}
app.on("browser-window-created", (_event, w) => {
  try { w.setIcon(PINE_ICON); } catch {}
  // The constructor applies the window's own `title` option (or the app
  // name) AFTER this event, so the name is added once it returns. Measured on
  // Electron 37.10.3: a title set here synchronously was replaced by "Find
  // the moment" before `new BrowserWindow` came back, and a page with no
  // <title> raises no page-title-updated at all.
  setImmediate(() => {
    try {
      if (w.isDestroyed()) return;
      const now = w.getTitle();
      if (pineTitle(now) !== now) w.setTitle(pineTitle(now));
    } catch {}
  });
  w.on("page-title-updated", (event, title, explicitSet) => {
    event.preventDefault();
    try { w.setTitle(pineTitle(explicitSet ? title : w.getTitle())); } catch {}
  });
  try {
    const details = pineRelaunchDetails();
    if (details) w.setAppDetails(details);
  } catch {}
});

// #971: one Pine Box, not one per click. A pinned taskbar button is
// pressed to GET to the app, not to start a second copy of it — and
// pine_box.exe is run again on every launch, so without this the shortcut
// and the pin would stack instances. The second instance hands its
// argument list to the first and dies; the first comes to the front.
const pineLock = app.requestSingleInstanceLock();
if (!pineLock) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    restorePineWindow().then(async () => {
      if (argv.includes('--pip')) await win.webContents.executeJavaScript('window.PinePip?.enter()', true);
      if (argv.includes('--recover-playback')) {
        stationTroubleshooter.open();
        const result = await stationTroubleshooter.run('playback');
        fs.writeFileSync(path.join(PINE_USER_DATA, 'station-playback-recovery.json'), JSON.stringify(result, null, 2));
      }
    }).catch(error => console.error('[show Pine] ' + error.message));
  });
}

async function restorePineWindow() {
  if (!win || win.isDestroyed()) {
    createWindow();
    const contents = win.webContents;
    await new Promise((resolve, reject) => {
      const cleanup = () => { clearTimeout(timer); contents.removeListener('did-finish-load', loaded); contents.removeListener('did-fail-load', failed); };
      const loaded = () => { cleanup(); resolve(); };
      const failed = (_event, _code, description, _url, mainFrame) => { if (mainFrame) { cleanup(); reject(new Error(description)); } };
      const timer = setTimeout(() => { cleanup(); reject(new Error('The Pine window did not finish loading.')); }, 30000);
      contents.once('did-finish-load', loaded); contents.on('did-fail-load', failed);
    });
  }
  if (win.isMinimized()) win.restore();
  win.show(); win.focus();
}

const defaults = {
  // The portable pine_box exe lands on ANY machine on the network and taps
  // the live broadcast out of the box: attach to the master DGX agent by
  // default. Launch-local stays one Settings click away.
  baseUrl: process.env.PINE_DESKTOP_BASE_URL || "http://10.89.1.246:8096",
  port: 8096,
  mode: process.env.PINE_DESKTOP_MODE || "attach",
  apiKey: "",
  dataDir: "",
  python: ""
};

function configPath() {
  return path.join(app.getPath("userData"), "pinebox-desktop.json");
}

function readConfig() {
  try {
    const saved = JSON.parse(fs.readFileSync(configPath(), "utf8"));
    return {
      ...defaults,
      ...saved,
      ...(process.env.PINE_DESKTOP_BASE_URL ? { baseUrl: process.env.PINE_DESKTOP_BASE_URL } : {}),
      ...(process.env.PINE_DESKTOP_MODE ? { mode: process.env.PINE_DESKTOP_MODE } : {})
    };
  } catch {
    return { ...defaults };
  }
}

function writeConfig(next) {
  const cfg = { ...readConfig(), ...next };
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2));
  return cfg;
}

const lcdSerial = new LcdSerial();
const lcdAgent = new LcdAgent({read: readConfig, write: writeConfig,
  request: (host, ...args) => /^COM[0-9]+$/i.test(host) ? lcdSerial.request(host, ...args) : deviceRequest(host, ...args)});
lcdAgent.releaseTransport = () => lcdSerial.close();
const lcdFirmware = new LcdFirmware({root: path.join(PINE_USER_DATA, "lcd-firmware"),
  config: () => lcdAgent.config(), agent: lcdAgent});
function lcdState() { return {...lcdAgent.state(), firmware: lcdFirmware.state(), sampleDirectory: readConfig().saveDir || path.join(app.getPath("downloads"), "Pine Box Samples")}; }
async function prepareLcdConnection(host) {
  if (!/^COM[1-9][0-9]{0,3}$/i.test(String(host))) return;
  const port = String(host).toUpperCase();
  let identity = lcdAgent.config().host === port ? lcdAgent.config().identity : '';
  if (!lcdSerial.child) {
    lcdFirmware.launch('identify', {port});
    while (lcdFirmware.job?.running) await new Promise((resolve) => setTimeout(resolve, 200));
    if (lcdFirmware.job?.error) throw new Error(lcdFirmware.job.error);
    identity = lcdFirmware.usb?.mac;
  }
  await lcdSerial.open(port, identity);
}

let knownAgentRoot;
function agentRoot() {
  if (process.env.PINE_AGENT_ROOT) return process.env.PINE_AGENT_ROOT;
  if (app.isPackaged) return path.join(process.resourcesPath, "agent");
  if(knownAgentRoot)return knownAgentRoot;
  const local = path.resolve(__dirname, "..");
  // #828: a bare electron.exe shortcut carries no env, and the local
  // runner's parent is NOT the agent — it has package.json but no
  // app.py. When the guess is wrong, the share is the truth.
  try {
    if (!fs.existsSync(path.join(local, "app.py"))) {
      const share =
        "\\\\10.89.1.246\\ehm_eckx\\pinevoice-stack\\spark-agent";
      return (knownAgentRoot=share); // Source availability is checked asynchronously by each caller.
    }
  } catch { /* offline — keep the local guess */ }
  return (knownAgentRoot=local);
}

async function selfSyncFromShare() {
  // #828: EVERY launch refreshes the app from the share, no matter how
  // it was started — the operator's bare electron.exe shortcut kept
  // them on stale code through a whole day of fixes. Renderer files
  // land before the window loads, so this very boot runs them; a new
  // main.js takes over on the next boot.
  if (process.platform !== "win32"
      || process.env.PINE_NO_SELFSYNC === "1") return;
  try {
    const source = agentRoot();
    const runner = path.resolve(__dirname, "..");
    if (path.resolve(source).toLowerCase() === runner.toLowerCase()) {
      return;                          // running from the share itself
    }
    const srcDesk = path.join(source, "desktop");
    await fs.promises.access(path.join(srcDesk, "main.js"));
    const r=await new Promise((resolve,reject)=>{const child=spawn('robocopy',[srcDesk,path.join(runner,'desktop'),'/MIR','/NFL','/NDL','/NJH','/NJS','/NP'],{windowsHide:true,stdio:'ignore'});const timer=setTimeout(()=>child.kill(),240000);child.once('error',error=>{clearTimeout(timer);reject(error);});child.once('exit',status=>{clearTimeout(timer);resolve({status});});});
    try {
      await fs.promises.copyFile(path.join(source, "package.json"),
        path.join(runner, "package.json"));
    } catch { /* the old one keeps working */ }
    rememberLog(`[desktop] self-synced from ${srcDesk} rc=${r.status}`);
  } catch (err) {
    try {
      rememberLog(`[desktop] self-sync skipped: ${err.message}`);
    } catch { /* logging never blocks a launch */ }
  }
}

function defaultDataDir(root) {
  const localData = path.join(root, "data");
  if (!app.isPackaged && fs.existsSync(localData)) return localData;
  return path.join(app.getPath("userData"), "agent-data");
}

function venvDir() {
  if (app.isPackaged) return path.join(app.getPath("userData"), "agent-venv");
  return path.join(agentRoot(), ".venv");
}

function copyDirIfMissing(source, target) {
  if (!fs.existsSync(source) || fs.existsSync(target)) return;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.cpSync(source, target, { recursive: true });
}

function copyFileIfPresent(source, target) {
  if (!fs.existsSync(source)) return false;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  return true;
}

function rememberLog(line) {
  backendLog.push(line);
  backendLog = backendLog.slice(-500);
  if (win && !win.isDestroyed()) win.webContents.send("backend-log", line);
}

function supportProgress(stage, pct, detail = "") {
  const event = { stage, pct, detail, at: Date.now() };
  rememberLog(`[support] ${stage}${detail ? ` - ${detail}` : ""}\n`);
  if (win && !win.isDestroyed()) win.webContents.send("support-progress", event);
}

function npmCommand() {
  if (process.platform !== "win32") return "npm";
  const dirs = String(process.env.PATH || "").split(path.delimiter);
  for (const dir of dirs) {
    const candidate = path.join(dir, "npm.cmd");
    if (fs.existsSync(candidate)) return candidate;
  }
  return "npm.cmd";
}

function spawnCommand(cmd, args, options = {}) {
  if (process.platform !== "win32") {
    return spawn(cmd, args, {
      cwd: options.cwd || agentRoot(),
      env: { ...process.env, ...(options.env || {}) },
      windowsHide: true
    });
  }
  const quoted = [cmd, ...args].map((part) => {
    const text = String(part);
    return /\s|&|\(|\)|\^|%|!|"/.test(text)
      ? `"${text.replace(/"/g, '""')}"`
      : text;
  }).join(" ");
  return spawn("cmd.exe", ["/d", "/s", "/c", quoted], {
    cwd: options.cwd || agentRoot(),
    env: { ...process.env, ...(options.env || {}) },
    windowsHide: true
  });
}

function runLogged(cmd, args, options = {}) {
  return new Promise((resolve, reject) => {
    if (options.stage) supportProgress(options.stage, options.pct || 0, `${cmd} ${args.join(" ")}`);
    rememberLog(`[support] ${cmd} ${args.join(" ")}\n`);
    const child = spawnCommand(cmd, args, options);
    child.stdout.on("data", (buf) => rememberLog(buf.toString()));
    child.stderr.on("data", (buf) => rememberLog(buf.toString()));
    child.on("error", (err) => {
      supportProgress(options.stage || "command", options.pct || 0,
        `${cmd} failed to spawn: ${err.message}`);
      reject(err);
    });
    child.on("exit", (code) => {
      if (code === 0) resolve({ ok: true });
      else reject(new Error(`${cmd} ${args.join(" ")} exited ${code}`));
    });
  });
}

function syncDesktopSource() {
  const source = process.env.PINE_AGENT_ROOT || agentRoot();
  const target = path.resolve(__dirname, "..");
  const copied = [];
  if (path.resolve(source).toLowerCase() === path.resolve(target).toLowerCase()) {
    return { source, target, copied, skipped: "already running from source" };
  }
  for (const file of ["package.json", "package-lock.json"]) {
    if (copyFileIfPresent(path.join(source, file), path.join(target, file))) {
      copied.push(file);
    }
  }
  const sourceDesktop = path.join(source, "desktop");
  const targetDesktop = path.join(target, "desktop");
  if (fs.existsSync(sourceDesktop)) {
    fs.rmSync(targetDesktop, { recursive: true, force: true });
    fs.cpSync(sourceDesktop, targetDesktop, { recursive: true });
    copied.push("desktop/");
  }
  return { source, target, copied };
}

function removeInside(root, names) {
  const base = path.resolve(root);
  for (const name of names) {
    const target = path.resolve(base, name);
    if (!target.toLowerCase().startsWith(base.toLowerCase() + path.sep)) {
      throw new Error(`Refusing to remove outside runner: ${target}`);
    }
    if (fs.existsSync(target)) {
      fs.rmSync(target, { recursive: true, force: true });
      supportProgress("collapse", 10, `removed ${name}`);
    }
  }
}

function cmdEscape(value) {
  return String(value).replace(/"/g, '""');
}

function writeWindowsRebuildScript(runnerRoot, sourceRoot, cfg) {
  // #827: the old script COLLAPSED node_modules and prayed npm was
  // installed and the network was kind — when npm failed it tried to
  // relaunch the electron.exe it had just deleted, and the operator
  // was stranded outside the app. This is the pine_box.exe recipe:
  // refresh the source, unpack the PREBUILT runtime from the share
  // only if it is missing, and relaunch directly. No npm, no network
  // beyond the share, nothing deleted that the relaunch needs.
  const scriptPath = path.join(app.getPath("userData"), "pinebox-rebuild.cmd");
  const logPath = path.join(app.getPath("userData"), "pinebox-rebuild.log");
  // 2026-09-10: the caches Electron keeps of the code being replaced.
  // Built here, where the real userData path is known - the app is
  // named "Pine Box", so guessing %APPDATA%\\pine-box would have
  // cleared nothing at all.
  const codeCache = cmdEscape(path.join(app.getPath("userData"), "Code Cache"));
  const gpuCache = cmdEscape(path.join(app.getPath("userData"), "GPUCache"));
  const lines = [
    "@echo off",
    "setlocal EnableExtensions",
    `set "RUN_DIR=${cmdEscape(runnerRoot)}"`,
    `set "SOURCE_DIR=${cmdEscape(sourceRoot)}"`,
    `set "BASE_URL=${cmdEscape(cfg.baseUrl)}"`,
    `set "MODE=${cmdEscape(cfg.mode)}"`,
    `set "LOG=${cmdEscape(logPath)}"`,
    "> \"%LOG%\" echo [rebuild] waiting for Electron to exit",
    "timeout /t 3 /nobreak >nul",
    "if not exist \"%SOURCE_DIR%\\package.json\" (",
    ">> \"%LOG%\" echo [rebuild] cannot reach %SOURCE_DIR%",
    "  goto fail",
    ")",
    "if not exist \"%RUN_DIR%\" mkdir \"%RUN_DIR%\"",
    "cd /d \"%RUN_DIR%\" || goto fail",
    ">> \"%LOG%\" echo [rebuild] refreshing the app from the share",
    "copy /Y \"%SOURCE_DIR%\\package.json\" \"%RUN_DIR%\\package.json\" >> \"%LOG%\" 2>&1",
    "if exist \"%SOURCE_DIR%\\package-lock.json\" copy /Y \"%SOURCE_DIR%\\package-lock.json\" \"%RUN_DIR%\\package-lock.json\" >> \"%LOG%\" 2>&1",
    "robocopy \"%SOURCE_DIR%\\desktop\" \"%RUN_DIR%\\desktop\" /MIR /NFL /NDL /NJH /NJS /NP >> \"%LOG%\" 2>&1",
    "if errorlevel 8 goto fail",
    // 2026-09-10: and the caches Electron keeps of the code it just
    // replaced. The non-Windows path has cleared these since #827
    // (removeInside); this one mirrored the source and then relaunched
    // straight into a compiled copy of the OLD renderer. Best effort -
    // a cache that will not delete is not worth failing a rebuild over.
    ">> \"%LOG%\" echo [rebuild] clearing the runtime code caches",
    `if exist "${codeCache}" rmdir /s /q "${codeCache}" >> \"%LOG%\" 2>&1`,
    `if exist "${gpuCache}" rmdir /s /q "${gpuCache}" >> \"%LOG%\" 2>&1`,
    "if not exist \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" (",
    ">> \"%LOG%\" echo [rebuild] unpacking the prebuilt Electron runtime from the share",
    "  powershell -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -Force '%SOURCE_DIR%\\..\\desktop-runtime\\electron-win64.zip' '%RUN_DIR%\\node_modules\\electron'\" >> \"%LOG%\" 2>&1",
    ")",
    "if not exist \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" goto fail",
    "> \"%RUN_DIR%\\node_modules\\electron\\path.txt\" echo electron.exe",
    // [pine-identity] electron.exe wears the Pine Box name and icon in its
    // own resources (Task Manager, the volume mixer), and an unpack above
    // brings back Electron's. The same file at the same path, so the volume
    // Windows keeps for this exe is untouched. It waits for Electron to let
    // go of the exe (the timeout above returns at once with no console
    // input); never fatal - pine_box.exe tries again on the next launch.
    "if exist \"%RUN_DIR%\\desktop\\tools\\apply_pinebox_identity.ps1\" (",
    ">> \"%LOG%\" echo [rebuild] giving electron.exe the Pine Box name and icon",
    "  set \"PINE_STACK=%SOURCE_DIR%\\..\"",
    "  powershell -NoProfile -ExecutionPolicy Bypass -File \"%RUN_DIR%\\desktop\\tools\\apply_pinebox_identity.ps1\" -Exe \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" -NoBackup -WaitSeconds 30 -Quiet >> \"%LOG%\" 2>&1",
    ")",
    ">> \"%LOG%\" echo [rebuild] relaunching Pine Box",
    `set "PINE_AGENT_ROOT=${cmdEscape(sourceRoot)}"`,
    "set \"PINE_DESKTOP_BASE_URL=%BASE_URL%\"",
    "set \"PINE_DESKTOP_MODE=%MODE%\"",
    // A shell spawned from Electron may carry ELECTRON_RUN_AS_NODE,
    // which turns electron.exe into plain Node. Always clear it.
    "set \"ELECTRON_RUN_AS_NODE=\"",
    "start \"Pine Box\" /D \"%RUN_DIR%\" \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" .",
    "exit /b 0",
    ":fail",
    ">> \"%LOG%\" echo [rebuild] FAILED — see above",
    "set \"ELECTRON_RUN_AS_NODE=\"",
    "if exist \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" (",
    "  start \"Pine Box\" /D \"%RUN_DIR%\" \"%RUN_DIR%\\node_modules\\electron\\dist\\electron.exe\" .",
    ") else (",
    "  start \"Pine Box rebuild failed\" cmd /d /k \"echo [rebuild] The Electron runtime is missing and the share bundle could not be unpacked. & echo Double-click \\\\10.89.1.246\\ehm_eckx\\pinevoice-stack\\pine_box.exe to rebuild from scratch, or read: & echo %LOG%\"",
    ")",
    "exit /b 1",
    ""
  ];
  fs.writeFileSync(scriptPath, lines.join("\r\n"));
  return { scriptPath, logPath };
}

function launchDetachedScript(scriptPath) {
  // No manual quotes: node quotes args with spaces itself, and pre-quoting
  // made it escape the embedded quotes — cmd then choked on the space in
  // the profile path and died silently, which is how the rebuild collapsed
  // the app and never brought it back.
  const child = spawn("cmd.exe", ["/d", "/c", scriptPath], {
    detached: true,
    stdio: "ignore",
    windowsHide: true
  });
  child.unref();
}

function authHeaders(cfg = readConfig()) {
  return cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {};
}

async function fetchJson(url, options = {}) {
  const cfg = readConfig();
  return readStationJson(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
      ...(options.headers || {})
    }
  });
}

async function discoverAgentKey() {
  const cfg = readConfig();
  const response = await fetch(`${cfg.baseUrl}/`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const html = await response.text();
  const match = html.match(/const\s+SERVER_KEY\s*=\s*("(?:\\.|[^"\\])*")\s*;/);
  if (!match) return { ok: false, saved: false };
  const key = JSON.parse(match[1]);
  if (!key) return { ok: false, saved: false };
  writeConfig({ apiKey: key });
  return { ok: true, saved: true };
}

async function waitForHealth(baseUrl, ms = 20000) {
  const stop = Date.now() + ms;
  while (Date.now() < stop) {
    try {
      const r = await fetch(`${baseUrl}/healthz`);
      if (r.ok) return true;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

function pythonCommand(cfg) {
  if (cfg.python) return cfg.python;
  if (process.platform === "win32") return "python";
  return "python3";
}

function venvPython(root) {
  const dir = venvDir();
  return process.platform === "win32"
    ? path.join(dir, "Scripts", "python.exe")
    : path.join(dir, "bin", "python");
}

function startBackend() {
  const cfg = readConfig();
  if (backend && backend.exitCode === null) return { running: true, pid: backend.pid };

  const root = agentRoot();
  if (!fs.existsSync(path.join(root, "app.py"))) {
    throw new Error(`Cannot find app.py in ${root}`);
  }

  const py = fs.existsSync(venvPython(root)) ? venvPython(root) : pythonCommand(cfg);
  const dataDir = cfg.dataDir || defaultDataDir(root);
  fs.mkdirSync(dataDir, { recursive: true });
  copyDirIfMissing(path.join(root, "data", "vendor"), path.join(dataDir, "vendor"));

  backend = spawn(py, ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(cfg.port)], {
    cwd: root,
    env: {
      ...process.env,
      SPARK_AGENT_PORT: String(cfg.port),
      SPARK_AGENT_DATA_DIR: dataDir,
      SPARK_PUBLIC_LISTEN: process.env.SPARK_PUBLIC_LISTEN || "false"
    },
    windowsHide: true
  });

  rememberLog(`[desktop] launched agent pid ${backend.pid} in ${root}`);
  backend.stdout.on("data", (buf) => rememberLog(buf.toString()));
  backend.stderr.on("data", (buf) => rememberLog(buf.toString()));
  backend.on("exit", (code, signal) => {
    rememberLog(`[desktop] agent exited code=${code} signal=${signal || ""}`);
    backend = null;
  });
  return { running: true, pid: backend.pid };
}

async function createVenvAndInstall() {
  const cfg = readConfig();
  const root = agentRoot();
  const py = pythonCommand(cfg);
  const venv = venvDir();
  const steps = [
    { cmd: py, args: ["-m", "venv", venv] },
    { cmd: venvPython(root), args: ["-m", "pip", "install", "--upgrade", "pip"] },
    { cmd: venvPython(root), args: ["-m", "pip", "install", "-r", path.join(root, "requirements.txt")] }
  ];

  for (const step of steps) {
    await new Promise((resolve, reject) => {
      rememberLog(`[setup] ${step.cmd} ${step.args.join(" ")}`);
      const child = spawnCommand(step.cmd, step.args, { cwd: root });
      child.stdout.on("data", (buf) => rememberLog(buf.toString()));
      child.stderr.on("data", (buf) => rememberLog(buf.toString()));
      child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`setup failed with exit ${code}`)));
    });
  }
  return { ok: true, python: venvPython(root) };
}

async function reconstituteDesktop() {
  if (reconstituting) return { ok: false, running: true };
  reconstituting = true;
  const cfg = readConfig();
  const runnerRoot = path.resolve(__dirname, "..");
  try {
    supportProgress("ignition", 3, "reconstituting Pine Box");
    if (process.platform === "win32") {
      const sourceRoot = process.env.PINE_AGENT_ROOT || agentRoot();
      supportProgress("collapse", 8, "arming post-exit rebuild script");
      const { scriptPath, logPath } = writeWindowsRebuildScript(runnerRoot, sourceRoot, cfg);
      const runway = [
        [18, "source sync", "mapping latest desktop source"],
        [22, "runtime", "verifying the prebuilt Electron runtime"],
        [26, "no npm needed", "the runtime ships prebuilt on the share"],
        [30, "routing", "restoring Nabu/app station routing"],
        [34, "visualizer", "holding simulation while processes map in"],
        [38, "handoff", `external rebuild log ${logPath}`]
      ];
      for (const [pct, stage, detail] of runway) {
        supportProgress(stage, pct, detail);
        await new Promise((resolve) => setTimeout(resolve, 2500));
      }
      launchDetachedScript(scriptPath);
      supportProgress("exit", 42, "closing Electron so runtime DLLs unlock");
      setTimeout(() => app.exit(0), 700);
      return { ok: true, relaunching: true, external: true, logPath };
    }
    supportProgress("collapse", 6, "clearing local Electron runner");
    removeInside(runnerRoot, [
      "node_modules",
      "dist-desktop",
      ".vite",
      ".electron",
      ".cache"
    ]);
    const sync = syncDesktopSource();
    supportProgress("source sync", 12, `source ${sync.source}`);
    supportProgress("runner sync", 20, `runner ${sync.target}`);
    if (sync.copied && sync.copied.length) {
      supportProgress("desktop source", 28, `copied ${sync.copied.join(", ")}`);
    } else if (sync.skipped) {
      supportProgress("desktop source", 28, sync.skipped);
    }

    await runLogged(npmCommand(), ["install"], {
      cwd: runnerRoot,
      stage: "npm install",
      pct: 38
    });

    try {
      await runLogged(npmCommand(), ["run", "desktop:pack"], {
        cwd: runnerRoot,
        stage: "npx/electron pack",
        pct: 52
      });
    } catch (err) {
      supportProgress("npx/electron pack", 58, `skipped/failed: ${err.message}`);
    }

    if (fs.existsSync(path.join(agentRoot(), "requirements.txt"))) {
      try {
        supportProgress("python deps", 65, "refreshing backend requirements");
        await createVenvAndInstall();
      } catch (err) {
        supportProgress("python deps", 68, `failed: ${err.message}`);
      }
    }

    if (backend && backend.exitCode === null) {
      supportProgress("backend", 72, "stopping local backend");
      backend.kill();
      backend = null;
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
    if (cfg.mode === "launch") {
      supportProgress("backend", 78, "starting local backend");
      startBackend();
      await waitForHealth(readConfig().baseUrl, 30000);
    }

    try {
      supportProgress("routing", 84, "restoring Nabu/app broadcast route");
      await fetchJson(`${readConfig().baseUrl}/api/dj/output`, {
        method: "POST",
        // #855: a rebuild must NOT move the music switch, and must not
        // masquerade as an operator choice. This POSTed music:"off"
        // with no `system` flag, so every rebuild click both silenced
        // the records AND wrote "off" into the operator ledger as
        // though it had been chosen — after which the box vigil
        // faithfully replayed it. The operator was clicking rebuild
        // BECAUSE the radio had gone quiet, which made it quieter.
        body: JSON.stringify({
          voice: "box",
          reply: "box",
          voice_device: "nabu",
          box_talk: true,
          system: true
        })
      });
    } catch (err) {
      supportProgress("routing", 86, `failed: ${err.message}`);
    }

    let repairPct = 88;
    for (const [route, body] of [
      ["/api/pinebox/initialize", { speak: false }],
      ["/api/pinebox/recover", { restart: false }],
      ["/api/pinebox/initialize", { speak: false }]
    ]) {
      try {
        supportProgress("pine support", repairPct, route);
        await fetchJson(`${readConfig().baseUrl}${route}`, {
          method: "POST",
          body: JSON.stringify(body)
        });
      } catch (err) {
        supportProgress("pine support", repairPct, `${route} failed: ${err.message}`);
      }
      repairPct += 3;
    }

    supportProgress("relaunch", 100, "reconstitution complete");
    app.relaunch({
      args: process.argv.slice(1),
      execPath: process.execPath
    });
    setTimeout(() => app.exit(0), 500);
    return { ok: true, relaunching: true };
  } finally {
    reconstituting = false;
  }
}

function createWindow() {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(["media", "microphone", "camera", "fullscreen", "display-capture"].includes(permission));
  });
  // #1355: A REQUEST HANDLER IS NOT THE ONLY THING ASKED.
  //
  // Chromium asks two different questions. getUserMedia raises a
  // permission REQUEST, which the handler above answers. But
  // enumerateDevices, and getUserMedia's own re-checks on a later
  // call, go through the permission CHECK - a separate, synchronous
  // handler that Electron answers on its own if you do not set one.
  // With no check handler the device list comes back with empty
  // labels, which is why a microphone picker had nothing to pick
  // from: the devices were all there and none of them had a name.
  try {
    session.defaultSession.setPermissionCheckHandler(
      (_wc, permission) => [
        "media", "microphone", "audioCapture", "camera", "videoCapture",
        "fullscreen"
      ].includes(permission));
  } catch (err) { /* older Electron: the request handler is enough */ }
  // ...and this one gates which specific device may be opened once the
  // page names it. Default-deny in Electron, so pinning a microphone
  // other than the system default fails silently without it.
  try {
    session.defaultSession.setDevicePermissionHandler(() => true);
  } catch (err) { /* likewise */ }

  // Current replay taps the shell and panel independently and mixes them in
  // the recorder. The historical measurements below explain why window video
  // stays separate and why both frame taps must preserve local speaker playback.
  /* #1182: WHICH SCREEN THE RING RECORDS, DECIDED HERE AND NOWHERE ELSE.
   *
   * getDisplayMedia normally raises a picker. Two reasons it must not here:
   * the recorder starts itself a couple of seconds after the app opens, and
   * a picker nobody is sitting in front of is a feature that never runs; and
   * the wrong choice in that picker would quietly record somebody's email
   * into a ring that gets exported. The answer is decided here, always, and
   * the renderer is given no say in it.
   *
   * ---------------------------------------------------------------------
   * #1207: TWO CAPTURES, TOLD APART BY WHAT EACH ONE ASKED FOR.
   *
   *   "Similar to the tablet, I always want to capture the broadcast audio
   *    of the recording. So any time that I go into the video editor, I need
   *    the audio of the broadcast."
   *
   * #1205 claimed the sound now travelled with the picture. It never did.
   * Measured against this Electron (37.10.3), every pairing that would have
   * put both in one capture is refused:
   *
   *   { video: win, audio: 'loopback' }     -> "Error starting capture".
   *       System loopback is offered for a SCREEN; asked for beside one
   *       window it fails the whole request.
   *   { video: win, audio: <panel frame> }  -> the same refusal. A
   *       diagnostic proved the frame was found and correct (it logged
   *       frame=yes with the station url), so it is the PAIRING that is not
   *       allowed.
   *   { video: <panel frame>, audio: same } -> ACCEPTED, and the piece did
   *       carry a 48 kHz opus track - but the picture becomes the panel's
   *       own control page, with no rail, no menu and not the Listen view he
   *       was watching. A recording of the wrong screen is worse than a
   *       silent recording of the right one.
   *
   * And one more thing was measured, which explains the rest: `video: win`
   * is not a legal answer here at all. Handed a BrowserWindow this Electron
   * throws "video must be a WebFrameMain or DesktopCapturerSource", the
   * whole request fails, and the renderer falls through to its legacy
   * getUserMedia road - which is where the correct picture has been coming
   * from all along. The video branch below is therefore dead wiring that
   * fails safe, and it is left exactly as it is: the picture is right, and
   * the operator's first rule is that it stays right.
   *
   * What IS accepted is a second capture with no picture in it:
   *
   *   { video: false, audio: true } asked for, answered with
   *   { audio: <panel frame>, enableLocalEcho: true }
   *
   * Measured: one audio track labelled "Tab audio", no video track, no
   * gesture needed, and two of them may be live on the same frame at once -
   * which matters, because the window capture is running beside it.
   *
   * enableLocalEcho IS NOT OPTIONAL. Capturing a frame MUTES that frame's
   * local playback unless it is set, and the panel is where the broadcast
   * plays - so without it the recorder silences the station while the
   * operator is listening to it. Verified by listening rather than by
   * reading the flag: with a tone in the panel and the machine's speaker mix
   * read back through a screen-loopback capture, one FFT bin, tone on minus
   * tone off -
   *
   *     nothing capturing the frame          -28.1 dB
   *     capturing it, enableLocalEcho true   -28.0 dB   speakers keep it
   *     capturing it, flag left off          -85.4 dB   speakers lose it
   *
   * The requests are distinguished by videoRequested / audioRequested.
   * The trusted main renderer selects one discovered app frame through IPC
   * before each serialized audio request. Embedded pages cannot select or
   * consume that target. Picture capture uses the separate native window
   * fallback without sound. */
  try {
    session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
      if (!win || win.isDestroyed()) return callback(null);
      const wantsVideo = !!(request && request.videoRequested);
      const wantsAudio = !!(request && request.audioRequested);
      /* The sound ring supplies one selected app frame and preserves its local playback. */
      if (!wantsVideo && wantsAudio) {
        const ownFrame = win.webContents?.mainFrame;
        if (!ownFrame || request.frame !== ownFrame) return callback(null);
        const target = ringAudioTarget;
        ringAudioTarget = 'panel';
        const frame = target === 'shell' ? ownFrame : target === 'panel' ? panelFrameNow() : ringAudioFrames.frame(target);
        ringSound("HANDLER sound wantsVideo=false wantsAudio=true frame="
          + (frame ? "yes" : "no")
          + " panel=" + (frame ? String(frame.url || "") : "(none)"));
        if (!frame) {
          /* Refused, and the renderer says so in words the export sheet
           * prints. Better than answering with a frame that is not the
           * station's and recording the wrong room. */
          return callback(null);
        }
        return callback({ audio: frame, enableLocalEcho: true });
      }
      /* THE PICTURE RING. Left as #1182 wrote it, including the fact that
       * this Electron will refuse it: the renderer's fallback is what films
       * the window, and it films it correctly. `audio: false` is said out
       * loud so nothing can ever attach sound to this capture behind the
       * sound ring's back and put the broadcast in the file twice. */
      ringSound("HANDLER picture wantsVideo=" + wantsVideo
        + " wantsAudio=" + wantsAudio);
      // Cancel cleanly; the renderer then uses its existing window capture fallback.
      callback(null);
    }, { useSystemPicker: false });
  } catch (err) { /* older Electron: getDisplayMedia simply will not start */ }

  // #786: the window comes back EXACTLY as it was left — size and place —
  // and the minimums match the responsive chrome (it genuinely works small).
  const savedBounds = (readConfig().bounds || null);
  win = new BrowserWindow({
    width: savedBounds ? savedBounds.width : 1480,
    height: savedBounds ? savedBounds.height : 940,
    ...(savedBounds && Number.isFinite(savedBounds.x)
      ? { x: savedBounds.x, y: savedBounds.y } : {}),
    minWidth: 520,
    minHeight: 420,
    title: "Pine Box",
    frame: false, // Native drag regions; PiP must contain only video and widgets.
    // #971: the window icon is what alt-tab and the taskbar button show
    // while the app is RUNNING; the .ico on the shortcut is what the pin
    // shows when it is not. Both have to be the same mark or the button
    // changes picture the moment you launch it.
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#101419",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // The optional LCD producer must keep scrolling when Pine Box is
      // minimised; its own loop sleeps while that producer is stopped.
      backgroundThrottling: false,
      webviewTag: true,
      sandbox: false
    }
  });
  let boundsTimer = null;
  const rememberBounds = () => {
    clearTimeout(boundsTimer);
    boundsTimer = setTimeout(() => {
      try {
        if (!win || win.isDestroyed() || win.isMinimized() || win.__pinePip || win.__pinePipSwitching) return;
        writeConfig({ ...readConfig(), bounds: win.getBounds() });
      } catch (error) {}
    }, 600);
  };
  win.on("resize", rememberBounds);
  win.on("move", rememberBounds);
  win.once('closed', () => {
    pipCameraActive = false; pipCameraGeneration++;
    if (camera && (!cameraWindow || cameraWindow.isDestroyed())) {
      const previous = camera; camera = null;
      previous.close().catch(error => console.error('[camera cleanup] ' + error.message));
    }
  });
  pinePipWindow.attach(win);
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.webContents.once("did-finish-load", () => {watchTheShare();setTimeout(()=>{if(win&&!win.isDestroyed())pinePipTools.prepare();},500);});
  watchPanelFrame(win.webContents);                            /* #1205c */
  // A panel reload can end its audio tap. Give the recorder a fresh activation
  // for recovery while keeping an explicitly stopped recorder stopped.
  const ringRecoveryWindow = win;
  const ringRecovery = setInterval(() => {
    if (ringRecoveryWindow.isDestroyed() || ringRecoveryWindow.webContents.isLoading()) return;
    ringRecoveryWindow.webContents.executeJavaScript(
      '(function(){var r=window.PineScreenRing;if(!r)return 0;var s=r.state();'
      + 'if(s.enabled===false)return 0;if(!s.streams.sound.running||s.audio.complete===false){'
      + 'r.startSound({gesture:true});return 1}return 0})()', true
    ).catch(() => {});
  }, 5000);
  ringRecoveryWindow.once('closed', () => clearInterval(ringRecovery));
  /* #1205: THE GESTURE THE RECORDER CANNOT FIND FOR ITSELF.
   *
   * getDisplayMedia requires transient user activation - #1182c measured
   * that and the ring has been opened through the legacy getUserMedia
   * constraints ever since, which is exactly why it was silent: the
   * application's own audio is offered through the display-media handler
   * and nowhere else.
   *
   * executeJavaScript's second argument IS an activation ("some HTML APIs
   * like requestFullScreen can only be invoked by a gesture from the user.
   * Setting userGesture to true will remove this limitation"), so the main
   * process spends one on the recorder's behalf. `start()` returns early
   * when the ring is already running, so this and the renderer's own backstop
   * timer cannot both open a capture.
   *
   * On EVERY finished load, not once: a hot reload (see the note below the
   * window) re-evaluates the renderer, and a ring that only got its sound on
   * the first load would go quiet for the rest of the evening after one CSS
   * save. */
  win.webContents.on("did-finish-load", () => {
    if (hotPending.size) console.log('[hot] staged renderer updates loaded');
    hotPending.clear();
    setTimeout(() => {
      try {
        if (!win || win.isDestroyed()) return;
        win.webContents.executeJavaScript(
          "(function(){try{return window.PineScreenRing"
          + "?window.PineScreenRing.start({gesture:true})&&1:0}catch(e){return -1}})()",
          true);
        /* #1207: A SECOND ACTIVATION, FOR THE SECOND CAPTURE.
         *
         * getDisplayMedia CONSUMES transient activation, so one gesture
         * cannot be relied on to open two captures - and each
         * executeJavaScript(code, true) mints a fresh one, so the sound ring
         * is given its own rather than made to share. It is spent a moment
         * later, not in the same task, because the picture is what must not
         * be put at risk: if the sound's request were to fail in a way that
         * took the activation with it, the window capture has already been
         * opened and is already recording.
         *
         * (Measured: an audio-only display-media request is in fact accepted
         * here with no activation at all. The gesture is spent anyway, since
         * that is not a rule this app gets to depend on staying true, and
         * startSound() returns early when the ring is already running, so the
         * two roads cannot both open a capture.) */
        setTimeout(() => {
          try {
            if (!win || win.isDestroyed()) return;
            win.webContents.executeJavaScript(
              "(function(){try{return window.PineScreenRing"
              + "&&window.PineScreenRing.startSound"
              + "?window.PineScreenRing.startSound({gesture:true})&&1:0}"
              + "catch(e){return -1}})()",
              true);
          } catch (error) { /* the gesture backstop in the page still has it */ }
        }, 900);
      } catch (error) { /* a page that will not take it still films silently */ }
    }, 2500);
  });
}

/* ===========================================================================
   HOT RELOAD: the share is the truth, and the app follows it while running.

   "I want that to be hot reloading and capable of showing changes made
    immediately."

   WHY THIS IS NEEDED AT ALL. The app does not run the share - SMB is far too
   slow for that, which is why pine_box.exe mirrors desktop/ into
   %LOCALAPPDATA%\PineBoxDesktop\runner and runs the copy. The mirror is
   made ONCE, at launch. So every renderer change is invisible until the next
   relaunch, and not even F5 helps: reloading re-reads the same stale mirror.
   That is the documented stale-runner trap (#1148), and it cost an afternoon
   when a fixed sampler layout kept rendering as a black box on this desktop
   while the tablet - which gets a fresh APK every deploy - was already right.

   SO THE MIRROR IS KEPT FRESH WHILE THE APP RUNS. Poll the source renderer
   directory, copy anything newer into the mirror, and then tell the window.

   CSS IS SWAPPED, NOT RELOADED. A stylesheet can be re-applied by bumping
   its href, which repaints without touching the page - so a colour or a
   layout fix lands with the sampler still mounted, the feed still scrolled
   and the pads still loaded. Reloading for a CSS change would throw all of
   that away several times a minute while someone is working on a stylesheet,
   which is precisely when they can least afford it.

   JAVASCRIPT AND HTML ARE STAGED FOR AN EXPLICIT RELOAD. Already evaluated
   modules hold the live players, timers and audio graph. Reloading them
   automatically cuts the broadcast every time a source file is saved.
   Copy the new files into the runner now and log them as pending; they load
   when the operator explicitly reloads Pine Box or performs a handoff.

   MAIN.JS AND PRELOAD.JS ARE NOT HOT. They are this process; changing them
   needs a relaunch, and pretending otherwise is how you get an app running
   half of one version. They are watched only so the log can SAY so.
   =========================================================================== */

const HOT_EVERY_MS = 1500;      /* brisk enough to feel immediate           */
const HOT_SLOW_MS = 5000;       /* when the share is being slow, back off   */
let hotTimer = null;
let hotSeen = null;             /* name -> "mtime:size" of what is mirrored */
const hotPending = new Set();   /* copied JS/HTML waiting for explicit reload */
/* [pip-update] IS THIS APP OLDER THAN ITS SOURCE?
 *
 * "If the Pineapp is out of date, then at the top of the right click menu,
 *  offer an option to update and rebuild."
 *
 * Three things already know. The watcher copies renderer files and holds them
 * for an explicit reload (hotPending). It also sees this process's own files
 * change - main.js, preload.js, the .cjs modules - and until now only wrote a
 * line in the log about it (hotOwed keeps the names). And the build stamp
 * compares the whole running tree with the share whenever it is asked. The
 * PiP menu asks pineUpdateOwed(); it adds nothing of its own. */
const hotOwed = new Set();      /* this process's own files that changed: a relaunch is owed */
let desktopBuildLast = null;    /* the last answer of desktop:build */
function pineUpdateOwed() {
  const relaunch = Array.from(hotOwed), reload = Array.from(hotPending);
  const stale = !!(desktopBuildLast && desktopBuildLast.stale);
  return { owed: relaunch.length > 0 || reload.length > 0 || stale, relaunch, reload, stale };
}
const hotSelf = new Map();      /* main.js / preload.js, which are not hot   */
let hotSaidRelaunch = 0;

function hotSourceDir() {
  const root = process.env.PINE_AGENT_ROOT || agentRoot();
  return path.join(root, "desktop", "renderer");
}

/* One cheap fingerprint per file. Content hashing over SMB would be honest
 * and far too slow; mtime AND size together miss only an edit that changes
 * neither, which a save cannot do. */
function hotScan(dir) {
  const out = new Map();
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    if (!/\.(js|css|html)$/i.test(entry.name)) continue;
    try {
      const info = fs.statSync(path.join(dir, entry.name));
      out.set(entry.name, Math.round(info.mtimeMs) + ":" + info.size);
    } catch {}
  }
  return out;
}

/* The main-process files beside renderer/ - everything this process loads
 * or runs that a reload cannot replace. Read from the SHARE each pass, so
 * a module added tomorrow is watched without anyone remembering to add it
 * here. `source` is .../desktop/renderer; its parent is the tree. */
function hotSelfFiles(source) {
  try {
    return fs.readdirSync(path.join(source, ".."), { withFileTypes: true })
      .filter((entry) => entry.isFile() && /\.(js|cjs|ps1)$/i.test(entry.name))
      .map((entry) => entry.name);
  } catch {
    return ["main.js", "preload.js"];
  }
}

/* [mirror-drop-hotasync] The same two reads, off the main thread's loop.
 * Synchronous, they held the Electron main process for up to 4.5 s on a slow
 * share - and the tablet mirror's frames, which are served from this very
 * process, froze for exactly as long. One await at a time: a slow share then
 * costs one libuv thread, not the loop and not the pool. */
async function hotScanAsync(dir) {
  const out = new Map();
  for (const entry of await fs.promises.readdir(dir, { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    if (!/\.(js|css|html)$/i.test(entry.name)) continue;
    try {
      const info = await fs.promises.stat(path.join(dir, entry.name));
      out.set(entry.name, Math.round(info.mtimeMs) + ":" + info.size);
    } catch {}
  }
  return out;
}

async function hotSelfFilesAsync(source) {
  try {
    return (await fs.promises.readdir(path.join(source, ".."), { withFileTypes: true }))
      .filter((entry) => entry.isFile() && /\.(js|cjs|ps1)$/i.test(entry.name))
      .map((entry) => entry.name);
  } catch {
    return ["main.js", "preload.js"];
  }
}

async function watchTheShare() {
  if (hotTimer) return;
  hotTimer="starting";
  let source;
  try {
    source = hotSourceDir();
    await fs.promises.access(source);
    hotSeen = await hotScanAsync(path.join(__dirname,"renderer"));
    console.log("[hot] watching " + source + " (" + hotSeen.size + " files)");
  } catch (error) {
    console.log("[hot] could not read the share: " + error.message);
    hotTimer=setTimeout(()=>{hotTimer=null;watchTheShare();},HOT_SLOW_MS);return;
  }

  const tick = async () => {
    hotTimer = "busy";  /* [mirror-drop-hottick] a pass in flight still counts */
    let wait = HOT_EVERY_MS;
    try {
      const began = Date.now();
      const now = await hotScanAsync(source);  /* [mirror-drop-hotscan] */
      const changed = [];
      for (const [name, stamp] of now) {
        if (hotSeen.get(name) !== stamp) changed.push(name);
      }
      hotSeen = now;
      if (changed.length){const landed=await applyHot(source,changed);for(const name of changed)if(!landed.includes(name))hotSeen.delete(name);}
      /* THIS PROCESS'S OWN FILES. Not hot - see the header - but the
       * operator should hear about it rather than wonder why the change
       * did nothing.
       *
       * Not two of them. `main.js` requires twenty-one .cjs siblings -
       * lcd-agent, terminal-host, tablet-mirror, clip-mux, shot-enhance,
       * terminal-glass - and shells out to two .ps1 workers, and a
       * change to any of those was exactly as invisible as a main.js
       * change, with not even a line in the log to say a relaunch was
       * owed. Same rule as the tree stamp below: no hand-picked list. */
      for (const name of await hotSelfFilesAsync(source)) {  /* [mirror-drop-hotself] */
        try {
          const at = path.join(source, "..", name);
          const info = await fs.promises.stat(at);  /* [mirror-drop-hotstat] */
          const stamp = Math.round(info.mtimeMs) + ":" + info.size;
          const key = "^" + name;
          if (hotSelf.has(key) && hotSelf.get(key) !== stamp) { hotOwed.add(name); hotSayRelaunch(name); }  /* [pip-update] */
          hotSelf.set(key, stamp);
        } catch {}
      }
      /* A pass that takes a noticeable slice of the interval means the
       * share is busy; asking again immediately makes it worse. Measured
       * after ALL of it, not after the renderer scan alone - this pass now
       * also reads the tree's own directory, and a back-off that ignores
       * half its own cost is not a back-off. */
      if (Date.now() - began > 500) wait = HOT_SLOW_MS;
    } catch (error) {
      /* The share going away must never stop the app - it just stops being
       * watched until it comes back. */
      wait = HOT_SLOW_MS;
    }
    hotTimer = setTimeout(tick, wait);
  };
  hotTimer = setTimeout(tick, HOT_EVERY_MS);
}

async function applyHot(source, changed) {
  return stageRendererUpdates({ source, mirror: path.join(__dirname, 'renderer'),
    changed, window: win, pending: hotPending });
}
/* main.js and preload.js are THIS process. Said once a minute at most, so a
 * long editing session does not become a wall of the same line. */
function hotSayRelaunch(name) {
  const now = Date.now();
  if (now - hotSaidRelaunch < 60000) return;
  hotSaidRelaunch = now;
  console.log("[hot] " + name + " changed - that one needs a relaunch");
}

ipcMain.handle("config:read", () => readConfig());
ipcMain.handle("config:write", (_event, cfg) => writeConfig(cfg));

/* ===================================================================== */
/* #1224: DICTATION ON THE DESK, AND AN OVERLAY ABOVE EVERY WINDOW.      */
/*                                                                       */
/* "Voice dictation through the Pine app on the computer isn't working.  */
/*  I'm able to use dictation with the Pine tab."                        */
/*                                                                       */
/* Measured: the renderer is file://, so its fetch to the station is     */
/* preflighted and the station answers OPTIONS with 405 and no           */
/* Access-Control-Allow-Origin on anything; and talk-dot's where() was   */
/* falling back to http://127.0.0.1:8096, where nothing listens on this  */
/* machine.  Both go away if the request is made out here, which is      */
/* also where the key already is.  The renderer hands over WAV bytes -   */
/* proven against the live route: the same speech as WAV transcribes and */
/* as webm/opus comes back with no words in it.                          */

ipcMain.handle("listen:transcribe", async (_event, bytes) => {  // [#1224]
  try {
    const cfg = readConfig();
    const body = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes || []);
    if (body.length < 2000) {
      return { ok: false, why: "that was too short to hear",
        bytes: body.length };
    }
    const response = await fetch(`${cfg.baseUrl}/api/listen/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream",
        ...authHeaders(cfg) },
      body
    });
    let said = {};
    try { said = await response.json(); } catch { said = {}; }
    if (!response.ok) {
      return { ok: false, status: response.status,
        why: String(said.detail || `${response.status} ${response.statusText}`),
        bytes: body.length };
    }
    /* An empty transcript is not a failure of the road; the station says
     * WHY in `detail` and the dot repeats that rather than guessing. */
    return { ok: true, text: String(said.text || ""),
      heard: !!said.heard, detail: String(said.detail || ""),
      bytes: body.length };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* The spoken reply took the same broken road, for the same two reasons. */
ipcMain.handle("speech:say", async (_event, opts) => {          // [#1224]
  try {
    const cfg = readConfig();
    const want = opts && typeof opts === "object" ? opts : {};
    const response = await fetch(`${cfg.baseUrl}/v1/audio/speech`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(cfg) },
      body: JSON.stringify({
        input: String(want.input || "").slice(0, 600),
        voice: String(want.voice || "piper:en_US-libritts-high"),
        response_format: String(want.format || "mp3")
      })
    });
    if (!response.ok) {
      return { ok: false, status: response.status,
        why: `the voice bench said ${response.status}` };
    }
    const raw = Buffer.from(await response.arrayBuffer());
    if (!raw.length) return { ok: false, why: "the voice bench sent nothing" };
    return { ok: true, bytes: new Uint8Array(raw),
      type: String(response.headers.get("content-type") || "audio/mpeg") };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* --- the overlay ----------------------------------------------------- */
/*                                                                       */
/* "The text overlay isn't on top of all the windows.  So the graphic of */
/*  it responding to my speech needs to be on top of every window."      */
/*                                                                       */
/* A z-index cannot answer that here.  #pineTalkDot is in the main       */
/* window's document and this app opens a dozen other BrowserWindows;    */
/* whichever of them is in front is in front of the dot, and no value in */
/* view-chrome.css reaches outside its own page.  So the dictation       */
/* surface gets a window of its own: frameless, transparent, not         */
/* focusable, click-through, and pinned at the "screen-saver" level,     */
/* which on Windows sits above ordinary always-on-top windows.           */
/*                                                                       */
/* It carries no preload and no node: main pushes state in with          */
/* executeJavaScript, the way glass:still and the replay roads in this   */
/* file already talk to their pages.                                     */

let talkOverlayWin = null;                                      // [#1224]
let talkOverlayLast = null;
let talkOverlayTimer = null;
const TALK_OVERLAY_CEILING_MS = 30000;

const TALK_OVERLAY_HTML = [                                     // [#1224]
  '<!doctype html><html><head><meta charset="utf-8"><style>',
  'html,body{margin:0;height:100%;background:transparent;overflow:hidden;',
  '  -webkit-user-select:none;user-select:none;}',
  'body{display:flex;flex-direction:column;justify-content:flex-end;',
  '  align-items:flex-end;gap:10px;padding:14px;box-sizing:border-box;',
  '  font:13px/1.55 Inter,Segoe UI,system-ui,sans-serif;color:#edf3f5;}',
  '#say{max-width:100%;padding:9px 13px;border:1px solid #35414c;',
  '  border-radius:10px;background:rgba(10,14,18,.96);',
  '  box-shadow:0 14px 34px rgba(0,0,0,.55);display:none;}',
  '#say.bad{border-color:#e46b6b;color:#e46b6b;}',
  '#orb{width:212px;height:74px;border:1px solid #65c7da;border-radius:14px;',
  '  background:rgba(10,14,18,.92);box-shadow:0 14px 34px rgba(0,0,0,.55);',
  '  display:none;align-items:center;justify-content:center;gap:4px;}',
  '#orb.thinking{border-color:#e3be63;}',
  '#orb i{display:block;width:5px;height:6px;border-radius:3px;',
  '  background:#65c7da;transition:height .07s linear;}',
  '#orb.thinking i{background:#e3be63;}',
  '</style></head><body>',
  '<div id="say"></div><div id="orb"></div>',
  '<script>(function(){',
  'var say=document.getElementById("say"),orb=document.getElementById("orb");',
  'var bars=[],i;for(i=0;i<21;i+=1){var b=document.createElement("i");',
  '  orb.appendChild(b);bars.push(b);}',
  'var level=0,shown=0,mode="idle";',
  'function frame(){requestAnimationFrame(frame);',
  '  shown+=(level-shown)*0.25;',
  '  for(var i=0;i<bars.length;i+=1){',
  '    var mid=1-Math.abs(i-(bars.length-1)/2)/((bars.length-1)/2);',
  '    var h=6+shown*54*(0.35+mid*0.65)*(0.7+0.3*Math.sin(i*1.7+Date.now()/160));',
  '    bars[i].style.height=Math.max(4,Math.min(60,h))+"px";}}',
  'requestAnimationFrame(frame);',
  'window.pineTalkPaint=function(s){s=s||{};mode=String(s.mode||"idle");',
  '  level=Math.max(0,Math.min(1,Number(s.level)||0));',
  '  var t=String(s.text||"");say.textContent=t;',
  '  say.style.display=t?"block":"none";',
  '  say.className=s.bad?"bad":"";',
  '  var open=(mode==="listening"||mode==="thinking");',
  '  orb.style.display=open?"flex":"none";',
  '  orb.className=(mode==="thinking")?"thinking":"";',
  '  if(!open)level=0;};',
  '})();<\/script></body></html>'
].join("\n");

function talkOverlayWindow() {                                  // [#1224]
  if (talkOverlayWin && !talkOverlayWin.isDestroyed()) return talkOverlayWin;
  const { screen } = require("electron");
  const area = screen.getPrimaryDisplay().workArea;
  const wide = 560;
  const tall = 260;
  talkOverlayWin = new BrowserWindow({
    width: wide,
    height: tall,
    x: area.x + area.width - wide - 20,
    y: area.y + area.height - tall - 20,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    focusable: false,
    show: false,
    alwaysOnTop: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      /* It has to keep animating while another window holds focus - that
       * is the whole point of it. */
      backgroundThrottling: false
    }
  });
  /* "screen-saver" is the highest ordinary level; plain alwaysOnTop loses
   * to another always-on-top window, and this must lose to nothing. */
  talkOverlayWin.setAlwaysOnTop(true, "screen-saver");
  try {
    talkOverlayWin.setVisibleOnAllWorkspaces(true,
      { visibleOnFullScreen: true });
  } catch { /* not every platform has workspaces */ }
  /* Click-through: it is a readout, not a control.  The dot he presses is
   * still the one in the page. */
  talkOverlayWin.setIgnoreMouseEvents(true, { forward: false });
  talkOverlayWin.loadURL("data:text/html;charset=UTF-8,"
    + encodeURIComponent(TALK_OVERLAY_HTML));
  /* A state that arrived before the document did would be swallowed by
   * the guard in pineTalkPaint, so it is replayed once the page is up. */
  talkOverlayWin.webContents.on("did-finish-load", () => {
    if (talkOverlayLast) talkOverlayPaint(talkOverlayLast);
  });
  talkOverlayWin.on("closed", () => { talkOverlayWin = null; });
  return talkOverlayWin;
}

function talkOverlayPaint(state) {                              // [#1224]
  if (!talkOverlayWin || talkOverlayWin.isDestroyed()) return;
  const payload = JSON.stringify(state);
  talkOverlayWin.webContents
    .executeJavaScript(
      "window.pineTalkPaint && window.pineTalkPaint(" + payload + ")")
    .catch(() => { /* the page is still loading; did-finish-load replays */ });
}

ipcMain.handle("talk:overlay", (_event, want) => {              // [#1224]
  try {
    const state = want && typeof want === "object" ? want : {};
    const mode = String(state.mode || "idle");
    clearTimeout(talkOverlayTimer);
    if (mode === "off") {
      talkOverlayLast = null;
      if (talkOverlayWin && !talkOverlayWin.isDestroyed()) {
        talkOverlayPaint({ mode: "idle", text: "", bad: false, level: 0 });
        talkOverlayWin.hide();
      }
      return { ok: true, shown: false };
    }
    talkOverlayLast = {
      mode,
      text: String(state.text || "").slice(0, 400),
      bad: !!state.bad,
      level: Math.max(0, Math.min(1, Number(state.level) || 0))
    };
    const win = talkOverlayWindow();
    talkOverlayPaint(talkOverlayLast);
    if (!win.isVisible()) win.showInactive();
    /* Re-assert the level: another app going full screen can demote it. */
    win.setAlwaysOnTop(true, "screen-saver");
    /* NOTHING MAY LEAVE IT ON SCREEN.  A renderer that is torn down
     * mid-take never sends the "off", and an overlay stuck over every
     * window is worse than no overlay at all. */
    talkOverlayTimer = setTimeout(() => {
      try {
        if (talkOverlayWin && !talkOverlayWin.isDestroyed()) {
          talkOverlayWin.hide();
        }
      } catch { /* already gone */ }
    }, TALK_OVERLAY_CEILING_MS);
    return { ok: true, shown: true };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});
/* ===================== end #1224 ===================================== */
ipcMain.handle("backend:start", async () => {
  const started = startBackend();
  const ok = await waitForHealth(readConfig().baseUrl);
  return { ...started, ready: ok };
});
ipcMain.handle("backend:stop", () => {
  if (backend) backend.kill();
  return { ok: true };
});
ipcMain.handle("backend:setup", () => createVenvAndInstall());
/* 2026-09-10: IS THIS APP ACTUALLY THE LATEST? ANSWER IT, DO NOT ASSUME IT.
 *
 * "Make sure that this is always rebuilding and loading the latest version
 *  of the app... This is the only button I ever click."
 *
 * The rebuild already refreshes everything unconditionally - the agent
 * first, then a /MIR mirror of the whole desktop tree, then a relaunch.
 * What it never did was PROVE it: from inside the running app there was no
 * way to tell a build made from today's source from one made last week.
 * So the mark had to be taken on faith, and when a fix failed to appear
 * there was no way to know whether the fix was wrong or the app was old.
 *
 * This compares what the runner is RUNNING against what the share HOLDS,
 * file by file, and hands back both stamps. A stale runner becomes visible
 * instead of inferred - which is exactly the trap #1148 was, an old main.js
 * quietly serving an old bridge until somebody happened to relaunch.
 */
const {treeStamp}=require('./build-stamp.cjs');
let desktopBuildInFlight;
ipcMain.handle("desktop:build", () => {
  if(desktopBuildInFlight)return desktopBuildInFlight;
  desktopBuildInFlight=(async()=>{
  const source = path.join(process.env.PINE_AGENT_ROOT || agentRoot(),
                           "desktop");
  const mine = await treeStamp(path.resolve(__dirname));
  let theirs = { newest: 0, bytes: 0, missing: [], counted: 0 };
  let reachable = true;
  try {
    theirs = await treeStamp(source);
    if (!theirs.newest) reachable = false;
  } catch {
    reachable = false;
  }
  /* Bytes as well as times: /MIR preserves mtimes, so two trees differing
   * in content but not in clock would otherwise compare equal. */
  const stale = reachable
    && (theirs.bytes !== mine.bytes || theirs.newest > mine.newest + 1500);
  return {
    running_from: path.resolve(__dirname), source, reachable, stale,
    running_stamp: mine.newest, running_bytes: mine.bytes,
    source_stamp: theirs.newest, source_bytes: theirs.bytes,
    missing: mine.missing,
    /* How many files that verdict is about. A green line over six files
     * read as a green line over the app once already; the number makes
     * the next narrowing visible instead of silent. */
    counted: mine.counted, source_counted: theirs.counted,
    say: !reachable
      ? "the share could not be read, so the app cannot check itself"
      : stale
        ? "THIS APP IS OLDER THAN THE SHARE - press the mark to rebuild"
        : "running the newest source on the share",
  };
  })().then(got=>{desktopBuildLast=got;return got;}).finally(()=>{desktopBuildInFlight=null;});return desktopBuildInFlight;  /* [pip-update] */
});

/* The terminal provisioner: discovery, the restore image, the GSI and
 * the unlock. It owns where adb and fastboot live; every decision it
 * makes lives in terminal.cjs / firmware.cjs / gsi.cjs, which are
 * tested without hardware. */
const terminalHost = new TerminalHost({ readConfig, writeConfig }).install(ipcMain);
/* [pinetab-update] the tablet button: out of date? find it, build it (deploy.sh,
 * platform-signed), install it, look after it - with the stamp checked after. */
const { PinetabUpdate } = require("./pinetab-update.cjs");
const pinetabUpdate = new PinetabUpdate({
  agentRoot,
  readConfig,
  getJson: (route) => fetchJson(`${readConfig().baseUrl}${route}`),
  postJson: (route, body) => fetchJson(`${readConfig().baseUrl}${route}`, {
    method: "POST", body: JSON.stringify(body || {})
  }),
  send: (channel, data) => { if (win && !win.isDestroyed()) win.webContents.send(channel, data); },
  glassStop: async () => {
    try { require("./terminal-glass.cjs").stopPull(true); } catch (error) { /* no pull running */ }
    try { await (await terminalHost.glass()).stopRecording(); } catch (error) { /* nothing recording */ }
  },
  wake: async () => (await terminalHost.glass()).wake(),
  adbFallback: () => {
    try { return require("./terminal-host.cjs").findTools(readConfig().platformTools).adb; } catch (error) { return ""; }
  }
}).install(ipcMain);

/* THREE BUTTONS THAT REACH THE TABLET'S GLASS.
 *
 * "The first takes a picture of what is being displayed on the Pine Box
 *  tablet and copies it to the clipboard. The second makes an MP4... a
 *  default of up to 10 seconds, but expandable up to 30. And the last
 *  allows me to copy diagnostics information... so I can paste it in
 *  conversation about what is going on on the screen currently."
 *
 * The adb work is terminal-glass.cjs's; what is here is the part that can
 * only happen in the main process - the clipboard and the save dialog.
 *
 * EACH ONE CHECKS THAT IT WORKED. A clipboard write that silently does
 * nothing is worse than a failure, because the operator pastes and gets
 * whatever was there before - so the still is read back out of the
 * clipboard, and the clip is not called saved until the file is on disk. */
/* THE MARK-UP WINDOW, and the picture it is waiting for.
 *
 * "If I control click this icon, also copy it to clipboard, but also pop it
 *  up in a window that allows me to do a draw over."
 *
 * The bytes are handed over through this map rather than through the URL or
 * a temp file: a 250 kB data URL does not belong in a query string, and a
 * temp file would need cleaning up after a window someone might leave open
 * all afternoon. The entry is dropped when the window closes. */
const shotWaiting = new Map();

/**
 * Open the mark-up window on [png].
 *
 * [original] is the picture as it came off the tablet, BEFORE any enlarging,
 * and it is kept so the editor's resolution slider can resample from it.
 * Re-enlarging the enlarged copy would compound the interpolation: 2x of a 2x
 * is not 4x of the original.
 */
function openShotEditor(png, original, times, how, map) {
  const editor = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 620,
    minHeight: 460,
    title: "Mark up the tablet's screen",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#0d1217",
    /* Its own window, not a child: the operator marks up a screenshot while
     * reading the panel behind it, and a child window that always floats
     * over its parent makes that impossible. */
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  editor.setMenuBarVisibility(false);
  /* TAKEN WHILE THE WINDOW IS ALIVE. Reading `editor.webContents.id` inside
   * the `closed` handler throws "Object has been destroyed" - the
   * webContents is gone by then - which Electron turns into a crash dialog
   * in the operator's face every time they shut the window. */
  const editorId = editor.webContents.id;
  shotWaiting.set(editorId, { png, original: original || png,
    times: times || 1, how: how || '',
    /* WHAT IS IN THE PICTURE - regions and the station rows behind them,
     * collected at the moment of capture. Inspection mode is built on this
     * and cannot be truthful without it. */
    map: map || null });
  editor.on("closed", () => shotWaiting.delete(editorId));
  editor.loadFile(path.join(__dirname, "renderer", "shot-editor.html"));
  return editor;
}

/* WHAT THE TABLET IS COSTING, asked once for everyone who wants to know.
 *
 * The sidebar polls this and so does the live window, and they must not each
 * run their own sweep: every sweep is an adb round trip of 140-200 ms
 * against a tablet whose load average is already 27, and two readouts that
 * disagree about the same battery are worse than one.
 *
 * So the answer is held for a moment and handed to whoever asks inside that
 * window. See tablet-vitals.cjs for why it is one shell rather than seven. */
let vitals = null;
let vitalsAt = 0;
let vitalsHeld = null;
let vitalsGoing = null;
const VITALS_HOLD = 2500;

function tabletVitals(serialHint = "") {
  if (vitalsHeld && Date.now() - vitalsAt < VITALS_HOLD
      && (!serialHint || (vitals && vitals.serial === serialHint))) {
    return Promise.resolve(vitalsHeld);
  }
  if (vitalsGoing) return vitalsGoing;
  const pending = (async () => {
    const serial = serialHint || await terminalHost.glassSerial();
    if (!serial) {
      vitals = null;
      vitalsHeld = null;
      return { ok: false, why: terminalHost.glassWhy || "no tablet is attached" };   /* [tablet-attach] the reason, when there is one */
    }
    if (!vitals || vitals.serial !== serial) {
      const { Vitals } = require("./tablet-vitals.cjs");
      const tools = terminalHost.tools();
      vitals = new Vitals({ adb: tools.adb, serial,
        run: (args) => new Promise((resolve, reject) => {
          require("node:child_process").execFile(tools.adb, args,
            { timeout: 20000, maxBuffer: 8 * 1024 * 1024, windowsHide: true },
            (error, stdout, stderr) => {
              const text = String(stdout || "") + String(stderr || "");
              if (error && !text) return reject(error);
              resolve(text);
            });
        }) });
    }
    const said = await vitals.read();
    vitalsHeld = said;
    vitalsAt = Date.now();
    return said;
  })().catch(error => ({ ok: false, why: error.message })).finally(() => {
    if (vitalsGoing === pending) vitalsGoing = null;
  });
  vitalsGoing = pending;
  return pending;
}


ipcMain.handle("tablet:vitals", () => tabletVitals());

/* THE TABLET'S SCREEN, LIVE IN A WINDOW OF ITS OWN.
 *
 * One mirror, one window. Clicking the icon again raises what is already
 * open rather than starting a second encoder on the tablet - the tablet is
 * running the station, the rolling recorder and this, and a second copy of
 * this would cost it twice for nothing.
 *
 * The stream itself lives in tablet-mirror.cjs; everything here is the
 * window around it. */
let mirror = null;
let mirrorWindow = null;
const { MirrorLifecycle } = require("./mirror-lifecycle.cjs");
const mirrorLifecycle = new MirrorLifecycle();

function mirrorEncoderOwner() {
  const remembered = String((readConfig() || {}).mirrorEncoderOwner || "");
  if (/^mirror_[a-f0-9]{32}$/i.test(remembered)) return remembered;
  const owner = "mirror_" + require("node:crypto").randomUUID().replaceAll("-", "");
  writeConfig({ mirrorEncoderOwner: owner });
  return owner;
}

function closeTabletMirror(lease) {
  if (!lease) return mirrorLifecycle.closing;
  if (mirror === lease.mirror) mirror = null;
  if (mirrorWindow === lease.window) mirrorWindow = null;
  if (lease.poke) {
    lease.poke.close();
    if (poke === lease.poke) poke = null;
    lease.poke = null;
  }
  return mirrorLifecycle.close(lease, async () => {
    if (!lease.mirror) return;
    try { await lease.mirror.closeGently(); }
    catch (error) { lease.mirror.close(); }
  });
}

// Cancel delayed discovery/measurement before it can create a window or encoder.
// Revival exits directly, so it shares quit's cleanup before releasing the app lock.
let mirrorQuitReady = false;
let mirrorExitCleanup = null;
function prepareTabletMirrorExit(deadlineMs = 2000) {
  if (mirrorExitCleanup) return mirrorExitCleanup;
  mirrorQuitReady = true;
  const lease = mirrorLifecycle.current;
  mirrorLifecycle.stop();
  const cleanup = closeTabletMirror(lease);
  let deadline;
  mirrorExitCleanup = Promise.race([cleanup, new Promise(resolve => {
    deadline = setTimeout(resolve, deadlineMs);
  })]).catch(() => {}).finally(() => {
    clearTimeout(deadline);
    if (lease && lease.mirror) lease.mirror.close();
    for (const closing of mirrorLifecycle.cleaning) {
      if (closing.mirror) closing.mirror.close();
    }
  });
  return mirrorExitCleanup;
}
app.on("before-quit", event => {
  if (mirrorQuitReady) return;
  if (!mirrorLifecycle.current && !mirrorLifecycle.opening && !mirrorLifecycle.cleaning.size) {
    mirrorQuitReady = true;
    mirrorLifecycle.stop();
    return;
  }
  event.preventDefault();
  prepareTabletMirrorExit().finally(() => app.quit());
});

/* [mirror-pip] THE WINDOW IS THE ZOOM.
 *
 * "Inherently the application is at a hundred percent zoom level at all
 * times and I'm able to just scale it to just adjust the amount of scale
 * that I want" - so the mirror carries no magnifier any more. The picture
 * always FITS the window, and making it bigger is done by making the window
 * bigger. Three helpers, kept pure so they can be tested without a window:
 *
 *   mirrorAspectBounds  the aspect-locked bounds for a drag, so resizing
 *                       scales the picture instead of growing letterbox.
 *                       Exact about the control strip, a fixed band that
 *                       setAspectRatio's single ratio cannot express on
 *                       Windows (its extraSize argument is macOS-only).
 *   mirrorOpenBounds    where the window opens: the remembered size and
 *                       place when it still lands on a desk that exists,
 *                       otherwise half the tablet - the original default.
 *   mirrorPresetSize    the 50/75/100% buttons, clamped to the desk so
 *                       "100%" on a small screen means "as big as fits"
 *                       rather than a window hanging off the desk. */
const MIRROR_STRIP = 34;            /* the control strip under the picture */

function mirrorAspectBounds(wants, real, edge, frame) {
  if (!wants || !real || !(real.width > 0) || !(real.height > 0)) return null;
  const fx = frame && Number.isFinite(frame.x) ? frame.x : 0;
  const fy = frame && Number.isFinite(frame.y) ? frame.y : 0;
  const ratio = real.width / real.height;
  /* Dragging the top or bottom edge says the HEIGHT is the intent; every
   * other handle follows the width. */
  const byHeight = edge === "top" || edge === "bottom";
  let pictureW, pictureH;
  if (byHeight) {
    pictureH = Math.max(1, wants.height - fy - MIRROR_STRIP);
    pictureW = Math.round(pictureH * ratio);
  } else {
    pictureW = Math.max(1, wants.width - fx);
    pictureH = Math.round(pictureW / ratio);
  }
  const width = Math.max(240, pictureW + fx);
  const height = Math.max(200, pictureH + MIRROR_STRIP + fy);
  if (width === wants.width && height === wants.height) return null;
  return { x: wants.x, y: wants.y, width: width, height: height };
}

function mirrorOpenBounds(saved, screen_, real, strip) {
  const fallback = {
    width: Math.round(real.width / 2),
    height: Math.round(real.height / 2) + strip
  };
  if (!saved || !Number.isFinite(saved.width) || !Number.isFinite(saved.height)
    || saved.width < 240 || saved.height < 200) return fallback;
  const out = { width: Math.round(saved.width), height: Math.round(saved.height) };
  if (screen_ && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    try {
      /* The nearest display's work area: a place remembered on a monitor
       * that has since been unplugged is CLAMPED back onto a desk that
       * exists, never opened invisibly. */
      const area = screen_.getDisplayMatching(saved).workArea;
      out.width = Math.min(out.width, area.width);
      out.height = Math.min(out.height, area.height);
      out.x = Math.round(Math.min(Math.max(saved.x, area.x),
        area.x + area.width - out.width));
      out.y = Math.round(Math.min(Math.max(saved.y, area.y),
        area.y + area.height - out.height));
    } catch (error) { /* no display to ask: the size still counts */ }
  }
  return out;
}

function mirrorPresetSize(shape, area, frame) {
  const fx = frame && Number.isFinite(frame.x) ? frame.x : 0;
  const fy = frame && Number.isFinite(frame.y) ? frame.y : 0;
  let pictureW = Math.max(240, Math.round(Number(shape && shape.width) || 0));
  let pictureH = Math.max(200 - MIRROR_STRIP,
    Math.round(Number(shape && shape.height) || 0));
  const roomW = area && area.width > 0 ? area.width - fx : Infinity;
  const roomH = area && area.height > 0 ? area.height - fy - MIRROR_STRIP : Infinity;
  const squeeze = Math.min(1, roomW / pictureW, roomH / pictureH);
  if (squeeze < 1) {
    pictureW = Math.max(240, Math.floor(pictureW * squeeze));
    pictureH = Math.max(2, Math.floor(pictureH * squeeze));
  }
  return { width: pictureW, height: pictureH + MIRROR_STRIP };
}

function openTabletMirror(options) {
  const lease = mirrorLifecycle.current;
  if (lease && lease.isCurrent() && mirrorWindow && !mirrorWindow.isDestroyed()) {
    if (mirrorWindow.isMinimized()) mirrorWindow.restore();
    mirrorWindow.focus();
    if (options && options.full) mirrorWindow.setFullScreen(true);
    return Promise.resolve({ ok: true, already: true });
  }
  return mirrorLifecycle.open(lease => createTabletMirror(options || {}, lease));
}

async function createTabletMirror(options, lease) {
  const { Mirror } = require("./tablet-mirror.cjs");

  const tools = terminalHost.tools();
  let serial = await terminalHost.glassSerial();
  if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
  if (!serial) {
    /* On a first run there may be no remembered serial yet. The station's
     * tablet doctor already knows the current LAN address; use that same
     * source to restore the ADB transport without a manual tools detour. */
    try {
      const look = await fetchJson(readConfig().baseUrl + "/api/tablet/look",
        { signal: AbortSignal.timeout(4000) });
      if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
      if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(String(look.host || ""))) {
        const candidate = look.host + ':5555';
        const attached = await new Promise((resolve) => execFile(tools.adb,
          ['connect', candidate], { timeout: 6000, windowsHide: true },
          (error, stdout, stderr) => resolve(!error
            && /\b(?:already )?connected to\b/i.test(
              String(stdout || '') + String(stderr || '')))));
        if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
        if (attached) {
          /* Replace a stale remembered IP before glassSerial checks it. */
          if (readConfig().tabletSerial !== candidate) writeConfig({ tabletSerial: candidate });
          serial = await terminalHost.glassSerial();
        }
      }
    } catch (error) { /* the regular unreachable answer below is enough */ }
  }
  if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
  if (!serial) return { ok: false, why: "no tablet is reachable over adb" };
  /* Remember the selected wireless transport so the next open can restore
   * it after adb loses its local device list. */
  if (/^[^\s:]+:\d+$/.test(serial) && readConfig().tabletSerial !== serial) {
    writeConfig({ tabletSerial: serial });
  }

  if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
  const found = clipMux.findFfmpeg((readConfig() || {}).ffmpeg);
  const instance = new Mirror({ adb: tools.adb, serial, ffmpeg: found.path,
    encoderOwner: mirrorEncoderOwner() });
  lease.mirror = instance;
  mirror = instance;
  const real = instance.real;
  /* [mirror-pip-open] Opens where the operator last left it - remembered
   * size and place, the way the panel window is (#786) - or at half the
   * tablet's size on a first run. The window is CREATED at those bounds,
   * so it pops back up where it was with no flash at a default size first.
   * However big it is, the picture opens FITTED: the whole tablet visible
   * at 100% zoom, and the scale chosen by sizing the window. */
  const cfgAt = readConfig() || {};
  const openAt = mirrorOpenBounds(cfgAt.mirrorBounds,
    require("electron").screen, real, MIRROR_STRIP);
  const window_ = new BrowserWindow({
    width: openAt.width,
    height: openAt.height,
    ...(Number.isFinite(openAt.x) ? { x: openAt.x, y: openAt.y } : {}),
    minWidth: 240,
    minHeight: 200,
    title: "The tablet, live",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#05080b",
    /* PICTURE IN PICTURE: above the panel by default, because the whole
     * point is watching the tablet while working in the app. */
    alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  lease.window = window_;
  mirrorWindow = window_;
  window_.setMenuBarVisibility(false);
  /* [mirror-pip-lock] THE FRAME KEEPS THE TABLET'S SHAPE. Dragging any edge
   * scales the whole picture; without this, most of a drag grows letterbox
   * instead. setAspectRatio is the native guide where Electron has one, but
   * on Windows it cannot carve out the fixed control strip (extraSize is
   * macOS-only), so the exact bounds are written here on every proposed
   * drag, and the native ratio is re-tuned to the shape it settled at.
   * Suspended in fullscreen, where the strip is hidden and the OS owns the
   * window's shape. */
  const mirrorFrameEdge = () => {
    try {
      const outer = window_.getSize();
      const inner = window_.getContentSize();
      return { x: outer[0] - inner[0], y: outer[1] - inner[1] };
    } catch (error) { return { x: 0, y: 0 }; }
  };
  const mirrorHoldRatio = () => {
    if (typeof window_.setAspectRatio !== "function") return;
    try {
      if (window_.isFullScreen()) return window_.setAspectRatio(0);
      const now = window_.getBounds();
      if (now.width > 0 && now.height > 0) {
        window_.setAspectRatio(now.width / now.height);
      }
    } catch (error) { /* a missing guide only softens the drag */ }
  };
  window_.on("will-resize", (event, wants, details) => {
    if (window_.isFullScreen()) return;
    const locked = mirrorAspectBounds(wants, instance.real || real,
      details && details.edge, mirrorFrameEdge());
    if (!locked) return;
    event.preventDefault();
    window_.setBounds(locked);
  });
  window_.on("resized", mirrorHoldRatio);
  window_.on("enter-full-screen", mirrorHoldRatio);
  window_.on("leave-full-screen", mirrorHoldRatio);
  window_.once("ready-to-show", mirrorHoldRatio);
  /* The operator's last size and place, written down the way the panel's
   * is: debounced while it moves, once more as it closes. Fullscreen and
   * minimised are moments, not sizes, and are never written. */
  let mirrorBoundsAt = null;
  const mirrorRemember = () => {
    clearTimeout(mirrorBoundsAt);
    mirrorBoundsAt = setTimeout(() => {
      try {
        if (!window_ || window_.isDestroyed()
          || window_.isMinimized() || window_.isFullScreen()) return;
        writeConfig({ mirrorBounds: window_.getBounds(), mirrorFull: false });
      } catch (error) { /* a forgotten size only costs the next open */ }
    }, 600);
  };
  window_.on("resize", mirrorRemember);
  window_.on("move", mirrorRemember);
  window_.on("close", () => {
    clearTimeout(mirrorBoundsAt);
    try {
      if (window_.isMinimized()) return;
      if (window_.isFullScreen()) {
        /* Closed fullscreen: the windowed bounds underneath are already
         * remembered - fullscreen never overwrote them - so only the flag
         * is written, and the next open comes back fullscreen with the
         * same window waiting behind it. */
        writeConfig({ mirrorFull: true });
      } else {
        writeConfig({ mirrorBounds: window_.getBounds(), mirrorFull: false });
      }
    } catch (error) { /* fine */ }
    closeTabletMirror(lease).catch(() => {});
  });
  window_.on("closed", () => {
    closeTabletMirror(lease).catch(() => {});
  });
  /* [mirror-pause] minimised or hidden is not watching either: the tablet's
   * screenrecord stops (SIGINT, its own clean stop) and comes back when the
   * window does. One encoder on the tablet instead of two whenever the
   * picture is out of sight - see tablet-mirror.cjs pause(). */
  const mirrorAway = () => {
    if (lease.isCurrent()) instance.pause().catch(() => {});
  };
  const mirrorBack = () => {
    if (lease.isCurrent() && !window_.isDestroyed()
      && !window_.isMinimized() && window_.isVisible()) instance.resume();
  };
  window_.on("minimize", mirrorAway);
  window_.on("hide", mirrorAway);
  window_.on("restore", mirrorBack);
  window_.on("show", mirrorBack);
  /* [mirror-pip-refull] A mirror closed fullscreen comes BACK fullscreen,
   * with the remembered windowed bounds waiting underneath - leaving
   * fullscreen lands exactly where it used to. options.full (the
   * double-click open) still asks for it directly. */
  if ((options && options.full) || cfgAt.mirrorFull === true) {
    window_.once("ready-to-show", () => window_.setFullScreen(true));
  }
  // A rejected page load must stay inside this open request, with ownership cleaned up.
  try {
    await window_.loadFile(path.join(__dirname, "renderer", "tablet-mirror.html"));
  } catch (error) {
    desktopFaults.record("mirror-load-failed", { error: String(error.stack || error).slice(0,6000) });
    await closeTabletMirror(lease).catch(() => {});
    if (!window_.isDestroyed()) window_.destroy();
    return { ok: false, why: "the tablet window could not load: " + error.message };
  }
  if (!lease.isCurrent() || window_.isDestroyed()) {
    return { ok: false, cancelled: true, why: "the mirror was closed" };
  }
  desktopFaults.record("mirror-opened", { generation: lease.generation });
  // A crashed renderer leaves its native window alive; reload only the view.
  let viewRecovery = null;
  let viewCrashes = [];
  window_.webContents.on("render-process-gone", (_event, details) => {
    if (!lease.isCurrent() || window_.isDestroyed() || viewRecovery
        || details.reason === "clean-exit") return;
    const now = Date.now();
    viewCrashes = viewCrashes.filter(at => now - at < 60000);
    if (viewCrashes.length >= 2) {
      desktopFaults.record("mirror-view-recovery-stopped", { reason: details.reason });
      closeTabletMirror(lease).catch(() => {});
      if (!window_.isDestroyed()) window_.destroy();
      return;
    }
    viewCrashes.push(now);
    const recovery = Promise.resolve().then(async () => {
      if (!lease.isCurrent() || window_.isDestroyed()) return;
      desktopFaults.record("mirror-view-recovering", { reason: details.reason });
      try {
        const { reloadMirrorView } = require("./mirror-view-reload.cjs");
        for (let attempt = 1; attempt <= 2; attempt++) {
          if (!lease.isCurrent() || window_.isDestroyed()) return;
          try { await reloadMirrorView(window_.webContents); break; }
          catch (error) {
            if (!lease.isCurrent() || window_.isDestroyed()) return;
            if (attempt === 2) throw error;
            desktopFaults.record("mirror-view-reload-retry", { error: error.message });
          }
        }
        if (lease.isCurrent() && !window_.isDestroyed()) desktopFaults.record("mirror-view-recovered");
      } catch (error) {
        desktopFaults.record("mirror-view-recovery-failed", { error: String(error.stack || error).slice(0,6000) });
        await closeTabletMirror(lease).catch(() => {});
        if (!window_.isDestroyed()) window_.destroy();
      }
    }).finally(() => { if (viewRecovery === recovery) viewRecovery = null; });
    viewRecovery = recovery;
  });
  tabletVitals(serial).then(before => {
    if (lease.isCurrent() && !instance.running && vitals && vitals.serial === serial
        && before && before.ok) vitals.mark(before);
  }).catch(() => {});
  const initialShape = { ...instance.real };
  instance.measure(args => {
    if (!lease.isCurrent()) return Promise.resolve("");
    return new Promise(resolve => execFile(tools.adb, args,
      { timeout: 4000, windowsHide: true },
      (error, stdout, stderr) => resolve(String(stdout || "") + String(stderr || ""))));
  }).then(() => {
    if (!lease.isCurrent() || window_.isDestroyed()) return;
    mirrorHoldRatio();
    if (instance.running && (initialShape.width !== instance.real.width
        || initialShape.height !== instance.real.height)) {
      instance.rebuild("tablet display dimensions changed");
    }
  }).catch(() => {});
  return { ok: true };
}

/* TOUCHING THE TABLET THROUGH THE PICTURE.
 *
 * One held `adb shell` for the life of the mirror window - measured at 42 ms
 * a tap against 127 ms for a fresh adb call and 161 ms for raw sendevent.
 * See tablet-input.cjs for why `input` beats `sendevent` here. */
let poke = null;

function tabletPoke() {
  return poke;
}

/* THE MIRROR'S SPEAKER, which is a remote control for the monitor this app
 * already has rather than a second player. `want` null only asks. */
ipcMain.handle("mirror:sound", async (_event, want) => {
  if (!win || win.isDestroyed()) return { ok: false, why: "the panel is not open" };
  try {
    const said = await win.webContents.executeJavaScript(
      "(function () { try { return pineMonitorSay("
      + (want === null || want === undefined ? "null" : (want ? "true" : "false"))
      + "); } catch (error) { return { ok: false, why: error.message }; } })()",
      true);
    return said || { ok: false, why: "the panel did not answer" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* THE CAMERA, IN A WINDOW OF ITS OWN, WITH THE TABLET LEFT ALONE.
 *
 * The tablet streams JPEGs off an ImageReader with no preview and no
 * activity, so the terminal goes on drawing the station while this runs -
 * which is the whole point: looking through the camera must not take a radio
 * station off the air.
 *
 * The older road - putting the preview on the tablet's own screen - is kept
 * on the bridge, because it is the one that needs no adb and is the right
 * one for somebody standing AT the tablet. It is simply not what the icon
 * does any more. */
let camera = null;
let cameraWindow = null;
let pipCameraActive = false, pipCameraGeneration = 0, pipCameraQueue = Promise.resolve();

async function startTabletCamera(facing) {
  const { CameraGlass } = require("./tablet-mirror.cjs");
  const tools = terminalHost.tools();
  const serial = await terminalHost.glassSerial();
  if (!serial) return { ok: false, why: "no tablet is reachable over adb" };

  /* Ask the tablet to put its camera on the socket BEFORE connecting: the
   * service opens the lens when a reader arrives, so the order matters. */
  const glass = await terminalHost.glass();
  await glass.wake().catch(() => ({ ok: false }));
  const told = await glass.say(
    "(async function () { var b = window.pineDesktop;"
    + " if (!b || !b.cameraOpen) return JSON.stringify({ok:false,"
    + " why:'this terminal has no camera stream'});"
    + " return JSON.stringify(await b.cameraOpen({facing: "
    + JSON.stringify(facing === "front" ? "front" : "rear") + "})); })()");
  if (!told || !told.ok) {
    return { ok: false, why: (told && told.why) || "the tablet would not start its camera" };
  }

  if (!camera) camera = new CameraGlass({ adb: tools.adb, serial });
  const where = await camera.open(facing);
  return where;
}

async function openCameraWindow(facing) {
  const where = await startTabletCamera(facing);
  if (!where.ok) return where;

  if (cameraWindow && !cameraWindow.isDestroyed()) {
    cameraWindow.focus();
    return Object.assign({ ok: true, already: true }, where);
  }

  cameraWindow = new BrowserWindow({
    width: 960,
    height: 620,
    minWidth: 320,
    minHeight: 240,
    title: "The tablet's camera",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#05080b",
    alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  cameraWindow.setMenuBarVisibility(false);
  cameraWindow.on("closed", async () => {
    cameraWindow = null;
    /* The lens is released when the last reader goes, but the service is
     * told as well - an open camera nobody is watching is a camera nothing
     * else on the tablet can use. */
    /* THE SERVICE IS LEFT STANDING. Disconnecting is what releases the
     * lens - see PineCameraService - so closing a window needs to do
     * nothing more, and stopping the service would mean the next tap on the
     * icon had to start one and wait for it. "Available whenever I want" is
     * a service that is already there. */
    if (camera && !pipCameraActive) { await camera.close(); camera = null; }
  });
  cameraWindow.loadFile(path.join(__dirname, "renderer", "tablet-camera.html"));
  return Object.assign({ ok: true }, where);
}

ipcMain.handle("tablet:wake", async (_event, want) => {
  try {
    const glass = await terminalHost.glass();
    return (want && want.off) ? await glass.sleep() : await glass.wake();
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("camera:open", async (_event, want) => {
  try {
    /* THE CAMERA NEEDS THE TABLET AWAKE. The capture itself would work on a
     * sleeping device, but the service is started from an activity and a
     * sleeping tablet's activity is not there to start it. */
    const glass = await terminalHost.glass();
    await glass.wake().catch(() => ({ ok: false }));
    return await openCameraWindow((want && want.facing) || "rear");
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle('camera:pip', async (event, want) => {
  if (event.sender !== win?.webContents) throw new Error('Open camera PiP from the Pine desktop.');
  const generation = ++pipCameraGeneration;
  const task = pipCameraQueue.catch(() => {}).then(async () => {
  if (generation !== pipCameraGeneration) return { ok: false, why: 'Camera selection changed.' };
  try {
    if (want?.off) {
      pipCameraActive = false;
      if (camera && (!cameraWindow || cameraWindow.isDestroyed())) { await camera.close(); camera = null; }
      return { ok: true };
    }
    pipCameraActive = true;
    const where = await startTabletCamera(want?.facing);
    if (generation !== pipCameraGeneration) {
      if (!pipCameraActive && camera && (!cameraWindow || cameraWindow.isDestroyed())) { await camera.close(); camera = null; }
      return { ok: false, why: 'Camera selection changed.' };
    }
    if (!where.ok) pipCameraActive = false;
    return where;
  } catch (error) { if (generation === pipCameraGeneration) pipCameraActive = false; return { ok: false, why: error.message }; }
  });
  pipCameraQueue = task;
  return task;
});

/* A CAMERA FRAME ON THE CLIPBOARD, through the same mill the screenshots
 * use so the two look like each other. */
ipcMain.handle("camera:grab", async (_event, want) => {
  const { clipboard, nativeImage } = require("electron");
  try {
    const body = String((want && want.dataUrl) || "").split(",")[1] || "";
    if (!body) return { ok: false, why: "there was no frame" };
    const big = await shotEnhance.enlarge(Buffer.from(body, "base64"),
      { times: Number((want && want.times) || 1),
        ffmpeg: (readConfig() || {}).ffmpeg });
    const image = nativeImage.createFromBuffer(big.png);
    if (!image || image.isEmpty()) {
      return { ok: false, why: "the frame could not be decoded" };
    }
    clipboard.writeImage(image);
    if (clipboard.readImage().isEmpty()) {
      return { ok: false, why: "the clipboard would not take it" };
    }
    const size = image.getSize();
    return { ok: true, width: size.width, height: size.height,
      times: big.times, why: big.why || "" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* A CAMERA CLIP, handed to the export window that already knows how to trim,
 * crop and write it. The frames arrive as discrete JPEGs, so they are written
 * as an image sequence and assembled - the road clip-mux.fromFrames exists
 * for, and the one this app's own window recordings already take. */
ipcMain.handle("camera:clip", async (_event, want) => {
  try {
    const frames = (want && want.frames) || [];
    if (!frames.length) return { ok: false, why: "no frames were recorded" };
    const dir = clipMux.stash();
    let at = 0;
    for (const one of frames) {
      const body = String(one || "").split(",")[1] || "";
      if (!body) continue;
      at += 1;
      fs.writeFileSync(path.join(dir, "f" + String(at).padStart(6, "0") + ".jpg"),
        Buffer.from(body, "base64"));
    }
    if (!at) { clipMux.forget(dir); return { ok: false, why: "no frames decoded" }; }

    const seconds = Math.max(0.5, Number(want.seconds) || (at / 10));
    const out = path.join(dir, "camera.mp4");
    await clipMux.fromFrames({ dir, out, fps: at / seconds },
      { ffmpeg: (readConfig() || {}).ffmpeg });

    /* Into the export window as a recording with no audio: the camera has
     * none of its own, and inventing a track for it would be a lie in the
     * channel list. */
    openClipExport({ mp4: fs.readFileSync(out), seconds,
      audio: {}, notes: ["from the tablet\u2019s camera", at + " frames"] });
    clipMux.forget(dir);
    return { ok: true, frames: at, seconds };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* RECORD AND SAVE, with no editor in between.
 *
 * The ask was for a thing that counts down, records, and saves - so putting
 * the export window in front of the file would be answering a different
 * question. The clip is assembled by the same mill as everything else, so it
 * can still be opened and trimmed afterwards like any other recording. */
ipcMain.handle("camera:record", async (event, want) => {
  const { dialog } = require("electron");
  try {
    const frames = (want && want.frames) || [];
    if (!frames.length) return { ok: false, why: "no frames were recorded" };
    const dir = clipMux.stash();
    let at = 0;
    for (const one of frames) {
      const body = String(one || "").split(",")[1] || "";
      if (!body) continue;
      at += 1;
      fs.writeFileSync(path.join(dir, "f" + String(at).padStart(6, "0") + ".jpg"),
        Buffer.from(body, "base64"));
    }
    if (!at) { clipMux.forget(dir); return { ok: false, why: "no frames decoded" }; }

    const seconds = Math.max(0.5, Number(want.seconds) || (at / 10));
    const made = path.join(dir, "camera.mp4");
    await clipMux.fromFrames({ dir, out: made, fps: at / seconds },
      { ffmpeg: (readConfig() || {}).ffmpeg });

    const when = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    let folder = app.getPath("videos");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: "Save the camera recording",
        defaultPath: path.join(folder, `pinecam-${when}.mp4`),
        filters: [{ name: "MP4 video", extensions: ["mp4"] }]
      });
    if (picked.canceled || !picked.filePath) {
      clipMux.forget(dir);
      return { ok: false, canceled: true };
    }
    fs.copyFileSync(made, picked.filePath);
    const bytes = fs.statSync(picked.filePath).size;
    clipMux.forget(dir);
    shell.showItemInFolder(picked.filePath);
    return { ok: true, path: picked.filePath, bytes, frames: at, seconds };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("camera:where", () => {
  if (!camera) return { ok: false, why: "the camera is not open" };
  return Object.assign({ ok: true }, camera.where(), camera.how());
});

/* THE SENSOR'S DIALS, passed through to the tablet. Gamma and the look stay
 * on the desktop - see pine-looks.js - because they are a decision about the
 * picture rather than about the exposure. */
ipcMain.handle("camera:tune", async (_event, want) => {
  try {
    const glass = await terminalHost.glass();
    const said = await glass.say(
      "(async function () { var b = window.pineDesktop;"
      + " if (!b || !b.cameraTune) return JSON.stringify({ok:false,"
      + " why:'this terminal has no camera dials'});"
      + " return JSON.stringify(await b.cameraTune("
      + JSON.stringify(want || {}) + ")); })()");
    return said || { ok: false, why: "the tablet did not answer" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("camera:face", async (_event, facing) => {
  if (!camera) return { ok: false, why: "the camera is not open" };
  try {
    const glass = await terminalHost.glass();
    const told = await glass.say(
      "(async function () { var b = window.pineDesktop;"
      + " return JSON.stringify(await b.cameraOpen({facing: "
      + JSON.stringify(facing === "front" ? "front" : "rear") + "})); })()");
    if (told && told.ok) camera.facing = facing === "front" ? "front" : "rear";
    return told || { ok: false, why: "the tablet did not answer" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* LOOKING THROUGH THE TABLET'S CAMERA, ON ITS OWN SCREEN.
 *
 * The older road, kept because it needs no adb and suits somebody standing
 * at the tablet. The icon uses camera:open instead. */
ipcMain.handle("tablet:camera", async (_event, want) => {
  try {
    const glass = await terminalHost.glass();
    const facing = (want && want.facing) === "front" ? "front" : "rear";
    const said = await glass.say(
      (want && want.off)
        ? "(async function () { var b = window.pineDesktop;"
          + " if (!b || !b.cameraHide) return JSON.stringify({ok:false,"
          + " why:'this terminal has no camera road'});"
          + " return JSON.stringify(await b.cameraHide()); })()"
        : "(async function () { var b = window.pineDesktop;"
          + " if (!b || !b.cameraShow) return JSON.stringify({ok:false,"
          + " why:'this terminal has no camera road'});"
          + " return JSON.stringify(await b.cameraShow({facing: "
          + JSON.stringify(facing) + "})); })()");
    return said || { ok: false, why: "the tablet did not answer" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("mirror:touch", async (_event, act) => {
  try {
    const lease = mirrorLifecycle.current;
    if (!lease || !lease.isCurrent()) return { ok: false, why: "the mirror is not open" };
    if (!poke) {
      const { TabletInput } = require("./tablet-input.cjs");
      const tools = terminalHost.tools();
      const serial = lease.mirror.serial || await terminalHost.glassSerial();
      if (!serial) return { ok: false, why: terminalHost.glassWhy || "no tablet is attached" };   /* [tablet-attach] */
      if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
      poke = new TabletInput({ adb: tools.adb, serial });
      lease.poke = poke;
    }
    const what = (act && act.do) || "";
    if (what === "tap") return poke.tap(act.x, act.y);
    if (what === "swipe") return poke.swipe(act.x, act.y, act.x2, act.y2, act.ms);
    if (what === "key") return poke.key(act.key);
    if (what === "text") return poke.text(act.text);
    if (what === "how") return Object.assign({ ok: true }, poke.how());
    return { ok: false, why: "nothing to do" };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("mirror:show", async (_event, options) => {
  try {
    return await openTabletMirror(options || {});
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("mirror:open", async (_event, shape) => {
  if (!mirror) return { ok: false, why: "the mirror is not set up" };
  try {
    const instance = mirror;
    const lease = mirrorLifecycle.current;
    const opened = await instance.open(shape || {});
    if (!lease || !lease.isCurrent() || mirror !== instance) {
      return { ok: false, cancelled: true, why: "the mirror was closed" };
    }
    const window_ = lease.window;
    if (window_ && (window_.isDestroyed() || window_.isMinimized() || !window_.isVisible())) {
      await instance.pause();
    }
    mirrorQualityWatch();
    return Object.assign({}, opened, instance.how());
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* [mirror-quality-tab] THE SAME SLIDER, ON THE TABLET. "I need this on the
 * pine tablet" (2026-10-01). The tablet keeps its choice in its page's
 * localStorage (the export sheet's Desk mirror slider); this side asks for it
 * every ten seconds while the mirror is actually showing, and writes the desk
 * window's choice back, so the two sliders agree. A stamp, not a comparison
 * of clocks: whichever side last wrote changes the stamp, and a stamp this
 * side has not seen yet is a choice made on the tablet. */
const MIRROR_QUALITY_EVERY_MS = 10000;
const MIRROR_QUALITY_ASK = "(function () { try { return JSON.stringify({ ok: true,"
  + " q: Number(localStorage.getItem('pine-mirror-quality')) || 0,"
  + " at: String(localStorage.getItem('pine-mirror-quality-at') || '') });"
  + " } catch (e) { return JSON.stringify({ ok: false }); } })()";
let mirrorQualitySeen = "";
let mirrorQualityAsking = false;
let mirrorQualityTimer = null;

async function mirrorQualityFromTablet() {
  if (mirrorQualityAsking || !mirror || !mirror.running || mirror.paused) return;
  mirrorQualityAsking = true;
  const instance = mirror;
  try {
    const said = await (await terminalHost.glass()).say(MIRROR_QUALITY_ASK);
    if (mirror !== instance || !instance.running || instance.paused) return;
    if (said && said.ok && said.at && said.at !== mirrorQualitySeen
        && said.q >= 0.1 && said.q <= 1) {
      mirrorQualitySeen = said.at;
      instance.requality(said.q);
    }
  } catch (error) { /* a sleeping tablet keeps the quality in force */ }
  finally { mirrorQualityAsking = false; }
}

function mirrorQualityWatch() {
  mirrorQualityFromTablet();
  if (mirrorQualityTimer) return;
  mirrorQualityTimer = setInterval(mirrorQualityFromTablet, MIRROR_QUALITY_EVERY_MS);
  if (mirrorQualityTimer.unref) mirrorQualityTimer.unref();
}

async function mirrorQualityToTablet(quality) {
  const at = "desk-" + Date.now();
  mirrorQualitySeen = at;
  try {
    await (await terminalHost.glass()).say("(function () { try {"
      + " localStorage.setItem('pine-mirror-quality', " + JSON.stringify(String(quality)) + ");"
      + " localStorage.setItem('pine-mirror-quality-at', " + JSON.stringify(at) + ");"
      + " return JSON.stringify({ ok: true }); } catch (e) { return JSON.stringify({ ok: false }); } })()");
  } catch (error) { /* the tablet hears it next time the desk writes */ }
}

ipcMain.handle("mirror:size", (_event, size) => {
  if (!mirror) return { ok: false, why: "the mirror is not set up" };
  try {
    return mirror.retune(String(size || ""));
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* [mirror-quality] The window's quality slider: a fraction of the bitrate. */
ipcMain.handle("mirror:quality", (_event, quality) => {
  if (!mirror) return { ok: false, why: "the mirror is not set up" };
  try {
    const said = mirror.requality(quality);
    mirrorQualityToTablet(said.quality);
    return said;
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("mirror:how", () => {
  if (!mirror) return { ok: false, why: "the mirror is not set up" };
  return Object.assign({ ok: true }, mirror.how());
});

ipcMain.handle("mirror:window", (event, shape) => {
  const window_ = BrowserWindow.fromWebContents(event.sender);
  if (!window_ || window_.isDestroyed()) return { ok: false };
  if (window_.isFullScreen()) window_.setFullScreen(false);
  /* [mirror-pip-preset] The strip under the picture is part of the window
   * but not part of the tablet, so it rides on top of the asked-for picture
   * size - and the size is set on the CONTENT, so "100%" is one tablet
   * pixel per screen pixel whatever the OS frame adds. Clamped to the desk
   * this window is on, shrinking both sides together so the picture keeps
   * the tablet's shape. */
  let area = null;
  let frame = null;
  try {
    const { screen } = require("electron");
    area = screen.getDisplayMatching(window_.getBounds()).workArea;
    const outer = window_.getSize();
    const inner = window_.getContentSize();
    frame = { x: outer[0] - inner[0], y: outer[1] - inner[1] };
  } catch (error) { /* no screen to ask: set it unclamped */ }
  const fit = mirrorPresetSize(shape, area, frame);
  window_.setContentSize(fit.width, fit.height);
  return { ok: true };
});

ipcMain.handle("mirror:full", (event, want) => {
  const window_ = BrowserWindow.fromWebContents(event.sender);
  if (!window_ || window_.isDestroyed()) return { ok: false, full: false };
  window_.setFullScreen(!!want);
  return { ok: true, full: window_.isFullScreen() };
});

ipcMain.handle("mirror:ontop", (event) => {
  const window_ = BrowserWindow.fromWebContents(event.sender);
  if (!window_ || window_.isDestroyed()) return { ok: false, onTop: false };
  const want = !window_.isAlwaysOnTop();
  window_.setAlwaysOnTop(want);
  return { ok: true, onTop: want };
});

/* THE RECORDING TO SCRUB THROUGH, waiting for its window.
 *
 * The mp4 goes to a folder rather than through IPC for the same reason the
 * export window's does: the picker PLAYS it, which means it needs a URL, and
 * a thirty-second recording is megabytes that have no business being turned
 * into a data URL. The folder goes when the window does. */
const frameWaiting = new Map();

function openFramePicker(reel) {
  const dir = clipMux.stash();
  const held = { dir, video: path.join(dir, "replay.mp4"),
    seconds: reel.seconds, notes: reel.notes || [] };
  fs.writeFileSync(held.video, reel.mp4);

  const picker = new BrowserWindow({
    width: 1100,
    height: 780,
    minWidth: 640,
    minHeight: 480,
    title: "Find the moment",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#0d1217",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  picker.setMenuBarVisibility(false);
  /* The id while the window is still alive - see openShotEditor. */
  const pickerId = picker.webContents.id;
  frameWaiting.set(pickerId, held);
  picker.on("closed", () => {
    frameWaiting.delete(pickerId);
    clipMux.forget(dir);
  });
  picker.loadFile(path.join(__dirname, "renderer", "frame-pick.html"));
  return picker;
}

ipcMain.handle("frame:pending", (event) => {
  const held = frameWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is no recording waiting for this window" };
  return { ok: true, seconds: held.seconds, notes: held.notes,
    videoUrl: fileUrl(held.video) };
});

ipcMain.handle("frame:done", (event) => {
  const window_ = BrowserWindow.fromWebContents(event.sender);
  if (window_ && !window_.isDestroyed()) window_.close();
  return { ok: true };
});

/* THE CHOSEN FRAME, treated exactly as a fresh screenshot is: onto the
 * clipboard, and into the mark-up window if that is what was asked for. The
 * picker closes behind it - it has done its job, and leaving it open would
 * put a second window between the operator and the drawing. */
ipcMain.handle("frame:pick", async (event, choice) => {
  const { clipboard, nativeImage } = require("electron");
  try {
    const body = String((choice && choice.dataUrl) || "").split(",")[1] || "";
    if (!body) return { ok: false, why: "there was no picture in the frame" };
    /* THE SAME DOUBLING AS A LIVE SCREENSHOT, and it matters more here: the
     * rolling recorder films at half size to be cheap, so a picked frame is
     * 670x400. Doubling brings it to 1340x800 - parity with a screenshot
     * rather than half of one. */
    const big = await shotEnhance.enlarge(Buffer.from(body, "base64"),
      { times: 2, ffmpeg: (readConfig() || {}).ffmpeg });
    const png = big.png;
    const image = nativeImage.createFromBuffer(png);
    if (!image || image.isEmpty()) {
      return { ok: false, why: "the frame could not be decoded" };
    }
    clipboard.writeImage(image);
    if (clipboard.readImage().isEmpty()) {
      return { ok: false, why: "the clipboard would not take the frame" };
    }
    let edited = false;
    if (choice && choice.edit) {
      try {
        openShotEditor(png, Buffer.from(body, "base64"), big.times, big.how);
        edited = true;
      } catch (error) { edited = false; }
    }
    const window_ = BrowserWindow.fromWebContents(event.sender);
    if (window_ && !window_.isDestroyed()) window_.close();
    const size = image.getSize();
    return { ok: true, edited, width: size.width, height: size.height,
      grew: big.times, grewWhy: big.why || "",
      back: Number(choice && choice.back) || 0 };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("shot:image", (event) => {
  const held = shotWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is no picture waiting for this window" };
  const { nativeImage } = require("electron");
  /* The ORIGINAL's size, because that is what the resolution slider
   * multiplies - and what the editor needs to work out how far it can go
   * before the canvas area limit bites. */
  const source = nativeImage.createFromBuffer(held.original).getSize();
  return { ok: true,
    dataUrl: "data:image/png;base64," + held.png.toString("base64"),
    /* The regions, and what the station knows about each - see Glass.map. */
    map: held.map || null,
    times: held.times,
    how: held.how || shotEnhance.WAYS[0].id,
    source,
    ways: shotEnhance.WAYS.map((way) =>
      ({ id: way.id, name: way.name, note: way.note })) };
});

/* THE SLIDER AND THE DROPDOWN, answered from the ORIGINAL every time. */
ipcMain.handle("shot:resample", async (event, want) => {
  const held = shotWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is no picture waiting for this window" };
  try {
    const times = Math.max(1, Math.min(8, Math.round(Number(want && want.times) || 1)));
    const big = await shotEnhance.enlarge(held.original,
      { times, how: want && want.how, ffmpeg: (readConfig() || {}).ffmpeg });
    held.png = big.png;
    held.times = big.times;
    held.how = big.how;
    return { ok: true, times: big.times, how: big.how, why: big.why || "",
      dataUrl: "data:image/png;base64," + big.png.toString("base64") };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* ============================================ inspecting a screenshot ====
 *
 * A region of a picture, turned back into the thing it was a picture OF.
 * The map that makes this possible is collected at the shutter - see
 * Glass.map - and every route below is one the station already serves.
 */

/** Where the sound for a region lives, and nothing invented. */
function regionAudio(region) {
  const cfg = readConfig();
  const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
  if (!region) return null;

  /* A track. The station serves music by id, and the row's own id carries
   * the `music:` prefix the page uses. */
  if (region.kind === "music" && region.track) {
    return { url: base + "/music/" + encodeURIComponent(region.track),
      what: "the track" };
  }
  /* THE CUT OF THIS LINE, which is what "play this line" means. */
  if (region.clip_media) {
    return { url: base + region.clip_media
      + (region.clip_sig ? (region.clip_media.includes("?") ? "&" : "?")
        + "t=" + encodeURIComponent(region.clip_sig) : ""),
      what: "this line" };
  }
  /* The whole recording behind it. */
  if (region.media) {
    return { url: base + region.media
      + (region.sig ? (region.media.includes("?") ? "&" : "?")
        + "t=" + encodeURIComponent(region.sig) : ""),
      what: "the recording" };
  }
  /* NOTHING STORED YET, so ask the booth to cut it. This is the road the
   * sampler already uses. */
  if (region.id) {
    return { url: base + "/api/booth/clip?line=" + encodeURIComponent(region.id),
      what: "this line, cut by the booth", cuttable: true };
  }
  return null;
}

/**
 * THE WHOLE ROUND THIS LINE CAME FROM.
 *
 * "Right click the script line and choose to download the entire playthrough
 *  of that script that took place."
 *
 * `whole=1` is the station's own word for it: the booth answers with the
 * surrounding WELDED round rather than the single turn, which is the thing
 * that was actually said around this line in one file. No new route - only
 * a parameter, and a label that does not pretend it is the same as the line.
 */
function roundAudio(region) {
  const cfg = readConfig();
  const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
  if (!region || !region.id) return null;
  return { url: base + "/api/booth/clip?line=" + encodeURIComponent(region.id)
    + "&whole=1", what: "the whole round it came from" };
}

ipcMain.handle("inspect:play", (_event, region) => {
  const heard = regionAudio(region);
  if (!heard) return { ok: false, why: "there is no sound behind this one" };
  if (!win || win.isDestroyed()) return { ok: false, why: "the panel is not open" };
  try {
    /* IN THE PANEL, because that is where this application makes noise and
     * where its volume and routing already live. */
    win.webContents.executeJavaScript(
      "(function () { try { return pineInspectPlay("
      + JSON.stringify(heard.url) + "); } catch (error) { return String(error); } })()",
      true);
    return { ok: true, url: heard.url, what: heard.what };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("inspect:download", async (event, region, options) => {
  const { dialog } = require("electron");
  /* One line, or the whole round it sat in - different lengths of the same
   * recording, so they are asked for separately and named apart. */
  const heard = (options && options.whole)
    ? roundAudio(region) : regionAudio(region);
  if (!heard) return { ok: false, why: "there is nothing to download for this one" };
  try {
    const response = await fetch(heard.url, { headers: authHeaders() });
    if (!response.ok) {
      return { ok: false, why: "the station said " + response.status };
    }
    const body = Buffer.from(await response.arrayBuffer());
    /* THE EXTENSION FOLLOWS WHAT CAME BACK, not what was asked for.
     * /api/booth/clip answers mp3 OR wav depending on what it had to do. */
    const type = String(response.headers.get("content-type") || "");
    const ext = type.includes("wav") ? "wav" : type.includes("mpeg") ? "mp3"
      : (heard.url.match(/\.(mp3|wav|m4a|ogg)\b/i) || [, "mp3"])[1];
    const name = (region.who || region.kind || "line")
      + ((options && options.whole) ? "-round-" : "-")
      + String(region.id || "").slice(0, 8);
    let folder = app.getPath("music");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: "Save " + heard.what,
        defaultPath: path.join(folder, name.replace(/[^\w.-]+/g, "-") + "." + ext)
      });
    if (picked.canceled || !picked.filePath) return { ok: false, canceled: true };
    fs.writeFileSync(picked.filePath, body);
    shell.showItemInFolder(picked.filePath);
    return { ok: true, path: picked.filePath, bytes: body.length };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* EVERYTHING THE STATION KNOWS ABOUT THIS ONE.
 *
 * The region already carries what the FEED knew. This adds what the booth
 * kept: the prompt as sent, the script that came back, the model, the
 * schedule slot - /api/dj/provenance answers for lines still in the live
 * ring and 404s past it, which is a real limit and is reported as one
 * rather than hidden behind an empty panel. */
ipcMain.handle("inspect:deep", async (_event, region) => {
  const cfg = readConfig();
  const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
  const id = region && region.id;
  if (!id) return { ok: false, why: "this one has no id to ask about" };
  const out = { ok: true, id, provenance: null, why: "" };
  try {
    const response = await fetch(base + "/api/dj/provenance/"
      + encodeURIComponent(id), { headers: authHeaders(cfg) });
    if (response.ok) {
      out.provenance = await response.json();
    } else if (response.status === 404) {
      out.why = "that line is no longer in the booth's live ring, so its "
        + "paperwork is gone - the feed's own record above is what remains";
    } else {
      out.why = "the station said " + response.status;
    }
  } catch (error) {
    out.why = error.message;
  }
  return out;
});

/* HOW A LINE CAME TO BE, in a window of its own.
 *
 * The provenance is fetched HERE rather than in the editor, so the window
 * opens with its facts already in hand - a chart that draws itself empty and
 * then fills in is a chart somebody screenshots halfway. */
const flowWaiting = new Map();

ipcMain.handle("inspect:flow", async (_event, region) => {
  const cfg = readConfig();
  const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
  let provenance = null;
  let why = "";
  if (region && region.id) {
    try {
      const response = await fetch(base + "/api/dj/provenance/"
        + encodeURIComponent(region.id), { headers: authHeaders(cfg) });
      if (response.ok) provenance = await response.json();
      else if (response.status === 404) {
        why = "The booth keeps a line's paperwork only while it is in the live "
          + "ring, and this one has passed out of it - the chart below is what "
          + "the feed still knows.";
      } else why = "The station said " + response.status + ".";
    } catch (error) { why = error.message; }
  }

  /* THE CONVERSATION AROUND IT, off the same feed the booth draws.
   *
   * Not /api/director/script/{sid}: that answers 404 once a round has aired
   * and been retired, which is exactly the case somebody inspects. The feed
   * carries sid/turn/turns on every row, so the round is the rows sharing
   * that sid in turn order - the same data the station said it from. */
  let chain = [];
  let around = [];
  let feedWhy = "";
  try {
    const feed = await fetchJson(base + "/api/dj");
    const rows = (feed.chat || []).filter((r) => r && r.id);
    const at = rows.findIndex((r) => r.id === (region && region.id));
    const thin = (r) => ({
      id: r.id, who: r.who, name: r.name, kind: r.kind, text: r.text,
      sid: r.sid, turn: r.turn, turns: r.turns, ts: r.ts, air_at: r.air_at,
      aired: r.aired, voice: r.voice, engine: r.engine, seconds: r.seconds,
      media: r.media, clip_media: r.clip_media, round: r.round
    });
    const sid = String((region && region.sid)
      || (at >= 0 ? rows[at].sid : "") || "");
    if (sid) {
      chain = rows.filter((r) => String(r.sid || "") === sid)
        .sort((a, b) => (Number(a.turn) || 0) - (Number(b.turn) || 0))
        .map(thin);
    }
    /* Broadcast order, because "what was next" is what was HEARD next and
     * not what the script had planned. */
    if (at >= 0) {
      around = rows.slice(Math.max(0, at - 12), at + 13).map(thin);
    }
  } catch (error) {
    feedWhy = "the feed would not answer: " + error.message;
  }

  const window_ = new BrowserWindow({
    width: 1420,
    height: 860,
    minWidth: 900,
    minHeight: 560,
    title: "Inspect the line",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#0d1217",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  window_.setMenuBarVisibility(false);
  const flowId = window_.webContents.id;
  flowWaiting.set(flowId, { region, provenance, why, chain, around,
    feedWhy });
  window_.on("closed", () => flowWaiting.delete(flowId));
  window_.loadFile(path.join(__dirname, "renderer", "script-flow.html"));
  return { ok: true, had: !!provenance, why };
});

/* ------------------------------------------------------------------ */
/* What the prompts may no longer carry                                 */
/* ------------------------------------------------------------------ */

/* "I want an X that allows me to actually remove this data from being part
 *  of the data chunking that's being added in there... going forward, I can
 *  maybe remove some of this stuff from being weight on the system prompt."
 *
 * THE STATION HOLDS THE LIST, not this app. It is a standing decision about
 * every future round, and it has to outlive this window, this desktop, and
 * the forty-eight hours a line's paperwork survives.
 *
 * All three answer with the whole list afterwards, so the window never has
 * to guess what the station now holds. */
ipcMain.handle("prompt:cuts", async () => {
  try {
    const cfg = readConfig();
    return await fetchJson(`${cfg.baseUrl}/api/prompt/cuts`);
  } catch (error) {
    return { ok: false, why: error.message, cuts: [] };
  }
});

ipcMain.handle("prompt:cut", async (_event, what) => {
  try {
    const cfg = readConfig();
    return await fetchJson(`${cfg.baseUrl}/api/prompt/cuts`, {
      method: "POST", body: JSON.stringify(what || {})
    });
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("prompt:keep", async (_event, what) => {
  try {
    const cfg = readConfig();
    return await fetchJson(`${cfg.baseUrl}/api/prompt/cuts/remove`, {
      method: "POST", body: JSON.stringify(what || {})
    });
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* ------------------------------------------------------------------ */
/* Hearing and keeping what the inspector is showing                    */
/* ------------------------------------------------------------------ */

/**
 * One line's audio, as the booth cuts it.
 *
 * Answers mp3 OR wav depending on what the cut needed, and says which in
 * Content-Type - so this reads that rather than assuming. `whole` asks for
 * the welded burst the line sat in instead of the row alone.
 */
async function boothCut(id, whole) {
  const cfg = readConfig();
  const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
  const url = base + "/api/booth/clip?line=" + encodeURIComponent(id)
    + (whole ? "&whole=1" : "");
  const response = await fetch(url, { headers: authHeaders(cfg) });
  if (!response.ok) {
    throw new Error("the booth would not cut that line ("
      + response.status + ")");
  }
  const kind = String(response.headers.get("content-type") || "");
  const body = Buffer.from(await response.arrayBuffer());
  if (!body.length) throw new Error("the cut came back empty");
  return {
    bytes: body,
    /* THE EXTENSION FOLLOWS THE BYTES. A .mp3 that is really a wav is a
     * file that fails an hour later in whatever opens it. */
    ext: kind.includes("wav") ? "wav" : "mp3",
    exact: response.headers.get("x-pine-exact") === "1",
    cut: String(response.headers.get("x-pine-cut") || "")
  };
}

/* ------------------------------------------------------------------ */
/* Changing a line: rewrite, revise, tint, re-record, vote              */
/* ------------------------------------------------------------------ */

/* Each of these is a thin pass-through. The station owns what they mean;
 * this only carries them and hands back what it said, so a refusal arrives
 * as the station's own words rather than as a shrug from here. */
function lineDoor(name, road, body) {
  ipcMain.handle(name, async (_event, what) => {
    try {
      const cfg = readConfig();
      const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
      const sid = String((what && what.sid) || "");
      if (road.includes("{sid}") && !sid) {
        return { ok: false, why: "that line carries no round to change" };
      }
      const said = await fetchJson(
        base + road.replace("{sid}", encodeURIComponent(sid)),
        { method: "POST", body: JSON.stringify(body(what || {})) });
      return Object.assign({ ok: true }, said || {});
    } catch (error) {
      return { ok: false, why: error.message };
    }
  });
}

lineDoor("line:edit", "/api/director/script/{sid}/turn", (w) => ({
  index: Number(w.index) || 0, text: String(w.text || ""),
  /* The text being REPLACED, so the station can refuse if the round moved
   * underneath rather than overwriting somebody else's edit. */
  was: String(w.was || "")
}));

lineDoor("line:revise", "/api/director/script/{sid}/revise", (w) => ({
  note: String(w.note || ""), standing: w.standing !== false
}));

lineDoor("line:tint", "/api/director/script/{sid}/tint", (w) => ({
  index: Number(w.index) || 0
}));

lineDoor("line:record", "/api/director/script/{sid}/record", (w) => ({
  bypass: !!w.bypass, who: "operator"
}));

lineDoor("line:vote", "/api/dj/line/vote", (w) => ({
  id: String(w.id || ""), vote: w.up ? "up" : "down"
}));

/* inspect:play is registered ABOVE, at the shot editor's inspection
 * mode, and plays the line in the panel where this application's
 * volume and routing live. A second handler for one channel makes
 * Electron throw in the main process, which takes the whole app down
 * before any window opens - so there is deliberately not one here. */

ipcMain.handle("inspect:export", async (event, what) => {
  const { dialog } = require("electron");
  try {
    const id = String((what && what.id) || "");
    if (!id) return { ok: false, why: "no line was named" };
    const how = String((what && what.how) || "line");

    let got = null;
    let many = 0;
    if (how === "segment") {
      /* WHAT THE SIDEBAR IS SHOWING, in the order it is showing it - not a
       * fresh read of the feed, which could hand back a different set of
       * rows than the ones being looked at. */
      const ids = ((what && what.ids) || []).filter(Boolean);
      if (!ids.length) return { ok: false, why: "there is no segment to save" };
      const parts = [];
      let ext = "mp3";
      for (const one of ids) {
        /* One at a time - twenty-five rows is twenty-five cuts, and this
         * station has been starved by clients asking all at once. */
        try {
          const piece = await boothCut(one, false);
          parts.push(piece.bytes);
          ext = piece.ext;
          many += 1;
        } catch (error) { /* a row with no audio is not a failed export */ }
      }
      if (!parts.length) return { ok: false, why: "none of those lines had audio" };
      got = { bytes: Buffer.concat(parts), ext };
    } else {
      got = await boothCut(id, how === "round");
      many = 1;
    }

    const when = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    let folder = app.getPath("music");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const named = { line: "line", round: "conversation", segment: "segment" };
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: "Save " + (named[how] || how),
        defaultPath: path.join(folder,
          "pine-" + (named[how] || how) + "-" + when + "." + got.ext),
        filters: [{ name: got.ext.toUpperCase() + " audio",
          extensions: [got.ext] }]
      });
    if (picked.canceled || !picked.filePath) return { ok: true, canceled: true };
    fs.writeFileSync(picked.filePath, got.bytes);
    shell.showItemInFolder(picked.filePath);
    return { ok: true, path: picked.filePath, bytes: got.bytes.length,
      lines: many, exact: got.exact, cut: got.cut };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* #1356: A STILL, OR A CLIP, OFF THE CAMERA - SAVED WHERE YOU WANT IT.
 *
 * The renderer cannot do this itself. It is a file:// document, so a
 * fetch to the station needs the key that lives out here; and a
 * download started by a page is a download into the browser's own
 * folder, which is not what "save a video from the camera" means.
 *
 * So the page names a station route and a filename, and this fetches
 * the bytes with the key attached and puts a Save As in front of them.
 * Deliberately generic over the route: the still and the cut clip are
 * the same act with a different extension, and two near-identical
 * handlers is how they drift apart.
 */
ipcMain.handle("cam:save", async (event, opts) => {
  const { dialog } = require("electron");
  try {
    const cfg = readConfig();
    const route = String((opts && opts.url) || "");
    if (!route.startsWith("/api/pinelink/")) {
      return { ok: false, why: "that is not a camera route" };
    }
    const response = await fetch(`${cfg.baseUrl}${route}`, {
      headers: authHeaders(cfg)
    });
    if (!response.ok) {
      return { ok: false,
        why: `the station said ${response.status} ${response.statusText}` };
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!bytes.length) {
      return { ok: false, why: "the station sent nothing" };
    }
    const video = String((opts && opts.kind) || "") === "video";
    const ext = video ? "mp4" : "jpg";
    const when = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    /* #1118: the Pine Cam preference names the export folder; the Save
       As opens there. Anything else falls back to the old defaults. */
    let folder = String((opts && opts.dir) || "");
    try { if (folder) fs.mkdirSync(folder, { recursive: true }); }
    catch { folder = ""; }
    if (!folder) folder = app.getPath(video ? "videos" : "pictures");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: video ? "Save the camera clip" : "Save the camera picture",
        defaultPath: path.join(folder,
          String((opts && opts.name) || `pinecam-${when}.${ext}`)),
        filters: [{ name: video ? "MP4 video" : "JPEG image",
          extensions: [ext] }]
      });
    if (picked.canceled || !picked.filePath) {
      return { ok: true, canceled: true };
    }
    fs.writeFileSync(picked.filePath, bytes);
    shell.showItemInFolder(picked.filePath);
    return { ok: true, path: picked.filePath, bytes: bytes.length };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* #1118: THE CLIPS FOLDER, IN EXPLORER; A FOLDER PICKER FOR THE PREFERENCE
 * SHEET. #1112: reveal one sample. #1115: a picture of this window.
 *
 * shell.openPath resolves to '' on success and to a reason on failure -
 * the reason is what the renderer prints, so it is handed back as `why`. */
ipcMain.handle("open:folder", async (_event, target) => {
  try {
    const where = String(target || "");
    if (!where) return { ok: false, why: "no folder was named" };
    const why = await shell.openPath(where);
    return why ? { ok: false, why } : { ok: true, path: where };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("show:in-folder", (_event, target) => {
  try {
    const where = String(target || "");
    if (!where) return { ok: false, why: "no file was named" };
    shell.showItemInFolder(where);
    return { ok: true, path: where };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("pick:folder", async (event, opts) => {
  const { dialog } = require("electron");
  try {
    const picked = await dialog.showOpenDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: String((opts && opts.title) || "Choose a folder"),
        defaultPath: String((opts && opts.defaultPath) || "") || undefined,
        properties: ["openDirectory", "createDirectory"]
      });
    if (picked.canceled || !picked.filePaths || !picked.filePaths[0]) {
      return { ok: true, canceled: true };
    }
    return { ok: true, path: picked.filePaths[0] };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});


/* ====================================================================== */
/* #1183: THE ROADS THE DESK'S OWN RENDERER HAS BEEN CALLING AND NOT       */
/* GETTING - saving a file, keeping a clip, and bringing itself round.     */
/* ====================================================================== */

/* "Basically the Pine Box app needs the same feature set as what we have
 *  going on with the Pine Box tab. So it needs feature parity, so there's
 *  nothing left out."
 *
 * These are not new features. Every one of them is a name that
 * desktop/renderer/*.js already calls, that only the TABLET's bridge
 * answered, so the code has been running its "this terminal cannot do that"
 * branch on the desk for as long as it has existed:
 *
 *   saveText  sampler-kits.js:216  - the kit exporter's whole write path
 *   saveBytes sampler-kits.js:511  - the MPC kit's seventeen files
 *   keepClip  line-actions.js:846  - "Download it to the recording folder"
 *   revive    deaf-watch.js:126    - "this build has no way to revive itself"
 *   usb*      sampler.js:1369      - see usb-disk.cjs
 *
 * THE SHAPES ARE THE TABLET'S SHAPES, field for field, because the SAME
 * renderer file reads both answers - see bridge/PineDesktopBridge.kt. Where
 * the two machines genuinely differ, the difference is in WHERE a file
 * lands, never in what an answer looks like.
 *
 * AND NOTHING HERE REJECTS. The tablet's rule, followed exactly: a road that
 * cannot do its job RESOLVES with {ok:false, detail:"..."}. A rejection
 * arrives in the page as a crashed handler, and the callers above read
 * `got.detail` to tell the operator what went wrong - a thrown error gives
 * them nothing to print.
 */

/* A FILENAME WINDOWS WILL ACTUALLY TAKE.
 *
 * Ported from audio/ClipSaver.safeName, with two additions that Android does
 * not need and Windows does: a name may not end in a dot or a space (the
 * shell silently trims them, so "line ." and "line" become the same file),
 * and the reserved device names are refused outright - a file called CON.wav
 * cannot be created at all, and the failure is an EINVAL nobody can read.
 *
 * The cap is on the STEM and the extension is kept, which is a deliberate
 * difference from ClipSaver: it caps the whole string, so a very long line
 * of speech could lose its ".mp3" there. On Android that is cosmetic. On
 * Windows a file with no extension is a file nothing will open. */
const WINDOWS_DEVICE_NAMES = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;

function safeFileName(raw, fallback) {
  const whole = String(raw == null ? "" : raw);
  const dot = whole.lastIndexOf(".");
  /* A "." in the last five characters is an extension; one in the middle of
   * a spoken line is a full stop and part of the name. */
  const hasExt = dot > 0 && whole.length - dot <= 5;
  let stem = hasExt ? whole.slice(0, dot) : whole;
  let ext = hasExt ? whole.slice(dot) : "";
  const clean = (text) => String(text)
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  stem = clean(stem).replace(/[. ]+$/, "");
  ext = clean(ext).replace(/[. ]+$/, "");
  if (stem.length > 120) stem = stem.slice(0, 120).trim();
  if (!stem) stem = String(fallback || "pine box clip");
  if (WINDOWS_DEVICE_NAMES.test(stem)) stem = stem + " file";
  return stem + ext;
}

/* THE FILE IS NAMED AFTER WHAT IT SAYS.
 *
 * ClipSaver.nameFor, exactly: the first seven words of the line, then six
 * characters of its id in brackets so two takes of the same words are
 * different files. The operator searches his recordings folder for words he
 * remembers hearing, not for a hex id. */
function clipFileName(said, id, ext) {
  const words = String(said || "").trim().split(/\s+/).filter(Boolean)
    .slice(0, 7).join(" ");
  const stem = words || "pine box line";
  const tail = String(id || "").slice(0, 6);
  return safeFileName(stem + " (" + tail + ")." + ext, "pine box line");
}

/* WHERE A KEPT FILE LANDS.
 *
 * The tablet's two destinations, in the desk's terms:
 *
 *   'recordings' - "the working folder you extract into", line-actions.js:226.
 *                  That is cfg.saveDir, the folder the operator named in
 *                  #1114 and the one the courier already carries to, so this
 *                  is replayFolder() and not a second opinion about it.
 *   anything else - Downloads / Pine Box, which is what the tablet's
 *                  "Download it to the tablet" choice means and what the
 *                  MPC exporter's folder paths are relative to. */
function downloadsRoot() {
  try { return app.getPath("downloads"); } catch (error) { return os.tmpdir(); }
}

function keepFolder(where) {
  if (String(where || "") === "recordings") return replayFolder();
  return path.join(downloadsRoot(), "Pine Box");
}

/**
 * Bytes onto disk, answering in ClipSaver.Kept's shape.
 *
 * {ok, where, bytes, detail} - `where` is the full path (the tablet shows
 * "Download/Pine Box/x.wav" for the same reason: it is the thing the
 * operator can go and look at), `bytes` is a count, `detail` is "" on
 * success and the reason on failure.
 */
function keepBytes(folder, name, bytes) {
  try {
    if (!bytes || !bytes.length) {
      return { ok: false, where: "", bytes: 0, detail: "there was nothing to save" };
    }
    fs.mkdirSync(folder, { recursive: true });
    const full = path.join(folder, name);
    fs.writeFileSync(full, bytes);
    return { ok: true, where: full, bytes: bytes.length, detail: "" };
  } catch (error) {
    return { ok: false, where: "", bytes: 0,
      detail: String(error && error.message ? error.message : error) };
  }
}

/**
 * saveText - sampler-kits.js:216, exportKit().
 *
 * {name, text, where} in, {ok, where, bytes, detail} out. A sampler preset
 * carries the AUDIO rather than references (a line id resolves for 48 hours
 * and the media is then swept, so a kit of references would rot into a grid
 * of dead pads), which makes a kit large - but it is still JSON, so it comes
 * through as a string.
 *
 * NO SAVE DIALOG, deliberately, and this is the one decision here worth
 * arguing about. The desk has dialog.showSaveDialog and uses it for cam:save.
 * But the tablet writes straight to a known folder, sampler-kits.js prints
 * `got.where` as a statement of fact - "Exported to ..." - and exportMpc
 * below calls its sibling seventeen times in a row for one kit. A dialog
 * would make that seventeen dialogs. So both of these land where the
 * operator was told they land, and openFolder/showInFolder are the roads
 * that take him there.
 */
ipcMain.handle("file:save-text", (_event, opts) => {
  try {
    const text = String((opts && opts.text) || "");
    if (!text) {
      return { ok: false, where: "", bytes: 0, detail: "there was nothing to write" };
    }
    const name = safeFileName(String((opts && opts.name) || "pine-box-kit.json"),
      "pine-box-kit");
    return keepBytes(keepFolder(opts && opts.where), name, Buffer.from(text, "utf8"));
  } catch (error) {
    return { ok: false, where: "", bytes: 0,
      detail: String(error && error.message ? error.message : error) };
  }
});

/**
 * saveBytes - sampler-kits.js:511, writeFile() inside exportMpc().
 *
 * {folder, name, mime, base64} in, {ok, where, bytes, detail} out. An MPC
 * kit is a FOLDER of WAVs beside an .xpm program, so the bytes are real
 * audio and arrive as base64: a WAV put through a JSON string comes out
 * corrupted, silently, and the MPC would refuse the kit with no clue why.
 *
 * `folder` is RELATIVE, always under Downloads - "Pine Box/<kit name>" is
 * what exportMpc builds - and that is the same root usbSend copies from, so
 * the two halves of the MPC road agree about where the kit is without either
 * of them being told.
 *
 * `mime` is accepted and ignored. On the tablet it is load-bearing:
 * MediaStore CORRECTS a filename whose extension does not match the type it
 * was given, and declaring the program as application/xml had it written as
 * "<name>.xpm.xml" - a file the MPC will never show, because it browses for
 * .xpm. That was measured. Nothing on Windows renames a file you write, so
 * the extension in `name` is the extension on disk, and the guard
 * sampler-kits.js:618 keeps for that failure can never trip here.
 */
ipcMain.handle("file:save-bytes", (_event, opts) => {
  try {
    const b64 = String((opts && opts.base64) || "");
    if (!b64) {
      return { ok: false, where: "", bytes: 0, detail: "there was nothing to write" };
    }
    const asked = String((opts && opts.folder) || "Pine Box");
    /* A relative folder from the page is still a path, and ".." in it is how
     * a kit export becomes a write into C:\Windows. Each part is cleaned the
     * same way a filename is, and a part that tries to climb ends the road. */
    const parts = asked.split(/[\\/]+/).filter(Boolean);
    for (const part of parts) {
      if (part === "." || part === "..") {
        return { ok: false, where: "", bytes: 0,
          detail: "that is not a folder this app may write to" };
      }
    }
    const folder = path.join(downloadsRoot(),
      ...(parts.length ? parts.map((part) => safeFileName(part, "Pine Box")) : ["Pine Box"]));
    const name = safeFileName(String((opts && opts.name) || "pine-box.bin"),
      "pine-box");
    return keepBytes(folder, name, Buffer.from(b64, "base64"));
  } catch (error) {
    return { ok: false, where: "", bytes: 0,
      detail: String(error && error.message ? error.message : error) };
  }
});

/**
 * keepClip - line-actions.js:846, the two "Download it to ..." choices.
 *
 * {route, said, id, where} in, {ok, where, bytes, detail} out.
 *
 * THE BYTES NEVER ENTER THE PAGE. line-actions.js:842 says so and its
 * progress bar sweeps rather than counting because of it: this process
 * fetches the clip and writes it, so there is no Content-Length for the page
 * to count against. It is audio, the page does not want it, and base64
 * through the bridge would cost a third more for nothing.
 *
 * THE EXTENSION FOLLOWS THE BYTES, from the Content-Type the booth answered
 * with - the same mapping the tablet uses. A .mp3 that is really a wav is a
 * file that fails an hour later in whatever opens it.
 */
ipcMain.handle("line:keep-clip", async (_event, opts) => {
  try {
    const route = String((opts && opts.route) || "");
    if (!route) {
      return { ok: false, where: "", bytes: 0, detail: "no clip was named" };
    }
    /* The page names the route because the page knows which line it is
     * looking at - but it may only name a station route, not an arbitrary
     * URL this process would then fetch with the operator's API key
     * attached. The same guard cam:save keeps at its own door. */
    if (!route.startsWith("/api/")) {
      return { ok: false, where: "", bytes: 0, detail: "that is not a station route" };
    }
    const cfg = readConfig();
    const base = String(cfg.baseUrl || "").replace(/\/+$/, "");
    const response = await fetch(base + route, { headers: authHeaders(cfg) });
    if (!response.ok) {
      return { ok: false, where: "", bytes: 0,
        detail: "the station said " + response.status + " " + response.statusText };
    }
    const kind = String(response.headers.get("content-type") || "");
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!bytes.length) {
      return { ok: false, where: "", bytes: 0, detail: "the station sent nothing" };
    }
    const ext = kind.includes("mpeg") || kind.includes("mp3") ? "mp3"
      : kind.includes("wav") ? "wav"
      : kind.includes("ogg") ? "ogg"
      : "audio";
    const name = clipFileName(opts && opts.said, opts && opts.id, ext);
    return keepBytes(keepFolder(opts && opts.where), name, bytes);
  } catch (error) {
    return { ok: false, where: "", bytes: 0,
      detail: String(error && error.message ? error.message : error) };
  }
});

/* ---------------------------------------------------------------------- */
/* #1183: THE DESK, BRINGING ITSELF ROUND                                  */
/* ---------------------------------------------------------------------- */

/* renderer/deaf-watch.js:126 has been finding nothing here and writing "(this
 * build has no way to revive itself)" into its own state. See net/Revive.kt
 * for what was measured on the tablet: Chromium's network stack inside a
 * renderer can die while everything else stays up - the bridge still answers,
 * the feed still updates, every view still paints, and not one fetch,
 * <audio> or <video> works. A RELOAD does not cure it, because the network
 * service lives in the process; a fresh process does, on the instant.
 *
 * On the desk that means app.relaunch() followed by app.exit().
 *
 * THE REST PERIOD IS THE WHOLE POINT OF THIS, AND IT IS OWNED HERE.
 *
 * The caller is a page, and the fault this exists for is a page that has
 * gone wrong. A page that has gone wrong in a slightly different way asks
 * for a revival every few seconds - deaf-watch looks every 30s, but nothing
 * stops a wedged timer, or some future caller, from asking far faster than
 * that. If the page held the rest period, a restart loop would be one bug
 * away, and a restart loop is strictly worse than a silent window: the
 * operator can read a silent window.
 *
 * So there are four gates, and a page cannot reach past any of them:
 *
 *   1. FIVE MINUTES between revivals. Asked sooner, this answers
 *      {ok:false} and nothing happens.
 *   2. THREE IN A ROW and it stops trying. A revival that did not help must
 *      not repeat for ever.
 *   3. THE RUN IS FORGOTTEN after thirty minutes. Whatever that episode
 *      was, it is not the same episode any more.
 *   4. ON DISK, not in a field. A field is born again with the process it
 *      lives in - so the process that came back would have had a clean
 *      slate and revived again, and again. The count has to outlive the
 *      thing it is counting. It goes in the same config store the rest of
 *      the desk uses, written with writeConfig BEFORE the exit, because
 *      after the exit there is no us.
 *
 * Which caps the damage at three relaunches in half an hour no matter what
 * the page does, and at zero after that until the episode has aged out.
 *
 * Plus an in-process flag, which the tablet does not need and this does: the
 * desk opens several windows (the mirror, the camera, the editors) and each
 * is a renderer that could in principle ask. One relaunch is a relaunch;
 * three at once is a race over who gets the single-instance lock. */
const REVIVE_REST_MS = 5 * 60 * 1000;
const REVIVE_GIVE_UP_AFTER = 3;
const REVIVE_RUN_WINDOW_MS = 30 * 60 * 1000;
let reviveGoing = false;

function reviveSinceMs() {
  const at = Number((readConfig() || {}).reviveAt || 0);
  return at ? Date.now() - at : -1;
}

function reviveInARow() {
  const cfg = readConfig() || {};
  const at = Number(cfg.reviveAt || 0);
  if (!at) return 0;
  if (Date.now() - at >= REVIVE_RUN_WINDOW_MS) return 0;
  return Number(cfg.reviveRun || 0);
}

function reviveRested() {
  if (reviveGoing) return false;
  const since = reviveSinceMs();
  if (since < 0) return true;
  if (since < REVIVE_REST_MS) return false;
  /* Past the window the run is forgotten - whatever it was, it is not the
   * same episode any more. */
  if (since >= REVIVE_RUN_WINDOW_MS) return true;
  return reviveInARow() < REVIVE_GIVE_UP_AFTER;
}

/**
 * revive - deaf-watch.js:126 and :133.
 *
 * With no argument, or {now:false}, this REPORTS and changes nothing:
 *   {ok:true, rested, sinceMs, inARow}
 * `sinceMs` is -1 when there has never been one, which is Revive.sinceMs's
 * own convention and not a zero dressed up.
 *
 * {now:true, why} actually does it. When it declines, the answer is
 * {ok:false, say:"..."} - and deaf-watch.js:140 reads exactly that: "an
 * answer at all means it declined - a revival does not return, because the
 * process is gone".
 */
ipcMain.handle("app:revive", async (_event, opts) => {
  try {
    const why = String((opts && opts.why) || "");
    if (!opts || !opts.now) {
      return { ok: true, rested: reviveRested(), sinceMs: reviveSinceMs(),
        inARow: reviveInARow() };
    }
    if (!reviveRested()) {
      const run = reviveInARow();
      const say = run >= REVIVE_GIVE_UP_AFTER
        ? "not reviving: " + run + " in a row already and it did not help"
        : "too soon since the last one";
      console.log("[revive] declined - " + say);
      return { ok: false, say };
    }
    reviveGoing = true;
    try {
      writeConfig({ reviveAt: Date.now(), reviveRun: reviveInARow() + 1 });
    } catch (error) {
      console.log("[revive] could not remember this revival: " + error.message);
    }
    console.log("[revive] bringing the desk round (" + reviveInARow()
      + " in this run): " + why);
    /* THE LOCK IS LET GO BY HAND.
     *
     * #971 put a single-instance lock on this app, and app.relaunch() spawns
     * the new copy as this one exits. Those two are a race: the replacement
     * asks for a lock the dying process may not have released yet, sees it
     * held, hands its arguments to a process that is on its way out, and
     * quits - leaving nothing running at all. That is the same class of
     * failure the tablet measured at #1317c, where a launch that landed
     * inside the old process's teardown came back half dead. Releasing the
     * lock here closes the window rather than hoping the timing is kind. */
    try {
      app.relaunch();
    } catch (error) {
      /* NOTHING WILL BRING IT BACK, SO IT DOES NOT GO AWAY. A silent window
       * is bad; a window that is simply gone until somebody walks over to
       * the machine is worse. Revive.kt refuses to exit for exactly this
       * reason when no alarm could be armed. */
      reviveGoing = false;
      return { ok: false,
        say: "the app could not arrange to come back: " + error.message };
    }
    await prepareTabletMirrorExit(12000);
    try { app.releaseSingleInstanceLock(); } catch (error) { /* never held */ }
    /* Not reached by the caller - the process is gone before this answer can
     * be delivered - but deaf-watch reads `say` if it ever were. */
    app.exit(0);
    return { ok: true, say: "reviving" };
  } catch (error) {
    reviveGoing = false;
    return { ok: false, say: String(error && error.message ? error.message : error) };
  }
});

/* ---------------------------------------------------------------------- */
/* #1183: THE MPC'S DISK - see usb-disk.cjs for what a "USB device" is on   */
/* this machine and why this is a real road rather than a pretend one.      */
/* ---------------------------------------------------------------------- */

const usbDisk = new UsbDisk({
  read: readConfig,
  write: writeConfig,
  /* The root the kit exporter wrote into. file:save-bytes above puts
   * "Pine Box/<kit>" under this exact folder, so the two halves of the MPC
   * road agree without either of them being told. */
  downloads: downloadsRoot
});

ipcMain.handle("usb:state", async () => {
  try { return await usbDisk.state(); }
  catch (error) {
    return { ok: false, chosen: false, name: "", canHost: true,
      anyRemovable: false, volumes: [],
      detail: String(error && error.message ? error.message : error) };
  }
});

ipcMain.handle("usb:pick", async (event) => {
  try {
    const { dialog } = require("electron");
    return await usbDisk.pick(async ({ defaultPath }) => {
      const picked = await dialog.showOpenDialog(
        BrowserWindow.fromWebContents(event.sender), {
          title: "Point at the MPC's disk",
          buttonLabel: "Use this disk",
          defaultPath: defaultPath || undefined,
          properties: ["openDirectory", "createDirectory"]
        });
      if (picked.canceled || !picked.filePaths || !picked.filePaths[0]) return "";
      return picked.filePaths[0];
    });
  } catch (error) {
    return { ok: false, name: "",
      detail: String(error && error.message ? error.message : error) };
  }
});

ipcMain.handle("usb:send", (_event, opts) => {
  try { return usbDisk.send(opts || {}); }
  catch (error) {
    return { ok: false, files: 0, bytes: 0, where: "",
      detail: String(error && error.message ? error.message : error) };
  }
});

ipcMain.handle("usb:list", (_event, opts) => {
  try { return usbDisk.list((opts && opts.path) || ""); }
  catch (error) {
    return { ok: false, path: String((opts && opts.path) || ""),
      detail: String(error && error.message ? error.message : error) };
  }
});

ipcMain.handle("usb:read", (_event, opts) => {
  try {
    return usbDisk.read((opts && opts.path) || "", (opts && opts.offset) || 0,
      (opts && opts.length) || 0);
  } catch (error) {
    return { ok: false, path: String((opts && opts.path) || ""),
      offset: Number((opts && opts.offset) || 0),
      detail: String(error && error.message ? error.message : error) };
  }
});
ipcMain.handle("shot:view", async (event) => {
  try {
    const win = BrowserWindow.fromWebContents(event.sender);
    const image = await win.webContents.capturePage();
    return { ok: true, dataUrl: image.toDataURL() };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* ===================================================================== */
/* #1182: THE SCREEN RING'S ROADS.
 *
 * The same names the tablet answers to, because the same renderer calls
 * them: hot-corners.js checks typeof on each one and draws the export sheet
 * out of what it finds. Until tonight it found nothing here and said so on
 * the sheet - "no screen recording road on this surface" - which is what the
 * operator photographed.
 *
 * The shapes are the tablet's shapes, documented in the kiosk's
 * pine-bridge.js. Where the two machines genuinely differ, the difference is
 * in WHERE a file lands, never in what an answer looks like.
 */

/* Where a finished recording goes. The operator's own recordings folder
 * first - that is the one he named in #1114 and the one the courier already
 * carries to - then the system's videos folder, then downloads. No save
 * dialog: this is the end of a corner swipe, not a menu. */
function replayFolder() {
  const cfg = readConfig() || {};
  const tries = [cfg.saveDir, (() => { try { return app.getPath("videos"); } catch (e) { return ""; } })(),
    (() => { try { return app.getPath("downloads"); } catch (e) { return ""; } })()];
  for (const dir of tries) {
    if (!dir) continue;
    try { fs.mkdirSync(dir, { recursive: true }); return dir; } catch (e) { /* next */ }
  }
  return os.tmpdir();
}

function replayName(seconds) {
  const when = new Date();
  const two = (n) => String(n).padStart(2, "0");
  const stamp = String(when.getFullYear()) + two(when.getMonth() + 1) + two(when.getDate())
    + "-" + two(when.getHours()) + two(when.getMinutes()) + two(when.getSeconds());
  return "pinebox-screen-" + stamp + "-" + Math.round(seconds) + "s.mp4";
}

/* The renderer, saying a piece is finished. The only road that carries
 * bytes upward, and it carries them as an ArrayBuffer rather than base64:
 * a two-second piece is about 400 KB, and base64 would make every one of
 * them a third larger for no reason at all. */
ipcMain.handle("replay:push", (_event, buffer, meta) => {
  try { return screenRing.take(Buffer.from(buffer), meta || {}); }
  catch (error) { return { ok: false, why: error.message }; }
});

/* #1182c: WHICH SOURCE, WITHOUT ASKING FOR A GESTURE.
 *
 * getDisplayMedia needs transient user activation, and the ring starts
 * itself a couple of seconds after the app opens, when nothing has been
 * pressed. getMediaSourceId names THIS window, and getUserMedia with the
 * chromeMediaSource constraints opens it with no activation at all. The
 * renderer is told which source rather than choosing one, for the same
 * reason the display-media handler answers with this window and no picker:
 * the wrong choice would quietly record somebody else's screen into a ring
 * that gets exported. */
ipcMain.handle("replay:audio-target", (event, target) => {
  if (!win || win.isDestroyed() || event.sender !== win.webContents
      || event.senderFrame !== win.webContents.mainFrame) {
    throw new Error('Recording audio selection belongs to the Pine desktop.');
  }
  if (!['shell', 'panel'].includes(target) && !ringAudioFrames.targets().includes(target)) {
    throw new Error('Unknown recording audio source.');
  }
  ringAudioTarget = target;
  return { ok: true, target };
});

ipcMain.handle("replay:audio-sources", event => {
  if (!win || win.isDestroyed() || event.sender !== win.webContents
      || event.senderFrame !== win.webContents.mainFrame) {
    throw new Error('Recording audio discovery belongs to the Pine desktop.');
  }
  return { ok: true, targets: ringAudioFrames.targets(), revision: ringAudioFrames.revision };
});

ipcMain.handle("replay:source", () => {
  try {
    if (!win || win.isDestroyed()) return { ok: false, detail: "no window" };
    /* #1205: `loopback` travels with the source id so the renderer can say,
     * in the one place a person will read it, whether a silent recording is
     * this platform's limit or a gesture it never got. */
    const bounds = win.getBounds();
    const scale = require('electron').screen.getDisplayMatching(bounds).scaleFactor || 1;
    return { ok: true, id: win.getMediaSourceId(), loopback: LOOPBACK_HERE,
      width: Math.max(1, Math.round(bounds.width * scale)),
      height: Math.max(1, Math.round(bounds.height * scale)),
      platform: process.platform,
      detail: LOOPBACK_HERE ? "" : "System loopback is unavailable on "
        + process.platform + "; application audio uses separate frame taps" };
  } catch (error) {
    return { ok: false, detail: error.message };
  }
});

ipcMain.handle("replay:begin", (_event, opts) => {
  /* 2026-09-15 (#1205c): a silent recording has a REASON and until now it
   * lived only in the renderer's console, which nobody can read from
   * outside the app. The ring reports its sound here on every start; this
   * writes that one line where it can be read with a text editor. It is a
   * single small append on a road that fires once per capture, not per
   * piece. */
  /* #1207: BOTH STREAMS NAMED, not just the sound's verdict. With two rings
   * a silent recording can mean the panel had no frame, the sound capture
   * was refused, or the sound recorder died while the picture carried on -
   * and one line that says only "present: false" cannot tell them apart. */
  try {
    const a = (opts && opts.audio) || null;
    const streams = (opts && opts.streams) || null;
    ringSound("BEGIN audio=" + JSON.stringify(a)
      + " streams=" + JSON.stringify(streams));
  } catch (error) { /* a diagnostic may never stop a recording */ }
  try {
    const cfg = readConfig() || {};
    const held = Number(cfg.replayHoldSeconds || 0) || HOLD_MAX_S;
    return screenRing.begin({ holdSeconds: held, ...(opts || {}) });
  } catch (error) { return { ok: false, why: error.message }; }
});

ipcMain.handle("replay:stop", (_event, why) => {
  try { return screenRing.stop(why); }
  catch (error) { return { ok: false, why: error.message }; }
});

ipcMain.handle("replay:state", () => {
  try {
    const got = screenRing.state();
    /* The bounds ride along so the preference control can draw its own
     * limits from the thing that enforces them, rather than carrying a
     * second copy of two numbers that would go stale. */
    /* `atLeast` is the tablet's word for the DESIGN FLOOR, and the sheet
     * prints it as "the ring holds N s (at least M s)". On the tablet the
     * ring is bounded by bytes, so it routinely holds several times its
     * floor; here it is bounded by seconds as well, so the floor and the
     * hold are the same number. Said anyway, because the sheet reads it.
     *
     * #1205: `audio` was null here, and that used to be the honest answer -
     * the ring recorded picture only. It records the desk's own mix now, so
     * the recorder's own words come back instead: hot-corners.js:1553 prints
     * `audio.state` and `audio.detail` into the export sheet, which is where
     * the operator decides whether to tick "Allow video without complete
     * audio". That line has to be true BEFORE the cut, not only after it. */
    return { ...got, atLeast: got.holds,
      /* #1207: `loopback_supported` is kept for the sheet that reads it, but
       * it no longer decides anything: the sound is the panel's own frame,
       * not the machine's loopback, and it is captured on every platform
       * this app runs on. The honest answer about whether THIS desk is
       * recording sound is got.audio.state, which the recorder reports. */
      audio: { ...(got.audio || {}), loopback_supported: LOOPBACK_HERE },
      min: HOLD_MIN_S, max: HOLD_MAX_S, fallback: HOLD_DEFAULT_S };
  } catch (error) { return { ok: false, running: false, seconds: 0, holds: 0,
    bytes: 0, detail: error.message }; }
});

/* How long the ring keeps. Persisted, because a hold the operator set has to
 * survive the app closing. */
ipcMain.handle("replay:hold", (_event, seconds) => {
  try {
    const set = screenRing.setHold(seconds);
    writeConfig({ replayHoldSeconds: set });
    return { ok: true, holds: set, min: HOLD_MIN_S, max: HOLD_MAX_S };
  } catch (error) { return { ok: false, why: error.message }; }
});

/* #1182d: FINISH THE PIECE YOU ARE ON, THEN CUT.
 *
 * Measured against the live ring: a ten-second ask came back as eight
 * seconds ending two seconds ago, and a five-second scrub strip spanned 1.8
 * seconds with no frame at "now". The piece being recorded has not reached
 * the disk yet, so the newest cuttable moment is up to one whole piece old -
 * and the moment worth keeping is nearly always the one that just happened.
 *
 * This asks the recorder to close the piece it is on. The renderer stops its
 * MediaRecorder, which emits immediately and starts the next, and we wait
 * for both streams and preceding writes to be acknowledged. The ceiling is short: a
 * recorder that has died must cost a cut a few hundred milliseconds, never
 * hang it, so the cut goes ahead with whatever is on disk and the answer
 * still says honestly where the window landed. */
function replayFlush(ms) {
  return new Promise((resolve) => {
    if (!win || win.isDestroyed() || !screenRing.running) return resolve(false);
    let done = false;
    const finish = got => {
      if (done) return;
      done = true; clearTimeout(timeout); resolve(!!got);
    };
    const timeout = setTimeout(() => finish(false), Math.max(200, Number(ms) || 1500));
    try {
      // The renderer resolves after BOTH current streams have reached disk.
      // A picture counter alone can advance while the latest sound is in flight.
      Promise.resolve(win.webContents.executeJavaScript(
        'window.PineScreenRing ? window.PineScreenRing.flush() : false', true
      )).then(result => finish(result === true || result?.ok === true), () => finish(false));
    } catch (error) { finish(false); }
  });
}


ipcMain.handle("replay:frames", async (_event, want) => {
  const endAt = Date.now();
  try {
    const asked = want || {};
    /* THE SCRUB STRIP MAY NOT ASK PAST THE OLD END. `back` is clamped to
     * what the ring actually holds, and the unclamped ask is echoed back as
     * `asked_back` with `clamped` beside it, because the strip draws its
     * slider from those two: a slider that can travel where there is no
     * video is a slider that lies. The edge default is 640, which is the
     * tablet's SCRUB_EDGE - the strip sizes its thumbnails from what comes
     * back, so a different default here would make the two surfaces look
     * like different features. */
    /* The strip is dragged, so it asks often; a flush is only worth its
     * few hundred milliseconds for the window that ends at NOW. A window
     * that ends in the past is already whole on disk. */
    if (!(Number(asked.back) > 1)) await replayFlush(700);
    const state = screenRing.state();
    const seconds = Math.max(1, Math.min(30, Number(asked.seconds) || 5));
    const askedBack = Math.max(0, Number(asked.back) || 0);
    const back = Math.min(askedBack, Math.max(0, (state.seconds || 0) - seconds));
    const got = await screenRing.frames(
      { seconds, count: asked.count, edge: Number(asked.edge) || 640, back, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    return { ...got, asked_back: askedBack,
      clamped: !!got.clamped || (askedBack - back > 0.6) };
  } catch (error) {
    return { ok: false, held: 0, detail: error.message };
  }
});

/* [pip-export-bar] An export tells the window that asked how far it is; the bar at the
 * foot of Pine (pine-pip.js) draws it with the words over it. ratio null = unknown. */
function replayProgressTeller(sender, want, view) {
  let last = -1, lastAt = 0;
  const tell = (stage, ratio, extra) => {
    try {
      if (!sender || sender.isDestroyed()) return;
      const now = Date.now(), share = Number.isFinite(ratio) ? Math.max(0, Math.min(1, ratio)) : null;
      if (stage === 'encode' && share !== null && share - last < .01 && now - lastAt < 400) return;
      if (share !== null) last = share;
      lastAt = now;
      sender.send("replay:progress", { view: view || (want?.view === 'pip' ? 'pip' : 'app'), audio: want?.audio_only === true,
        stage, ratio: share, at: now, ...(extra || {}) });
    } catch (_) { /* a window that has gone */ }
  };
  return { tell };
}

ipcMain.handle("replay:export", async (_event, want) => {
  const endAt = Date.now();
  const asked = Math.max(1, Number((want || {}).seconds) || 30);
  const teller = replayProgressTeller(_event.sender, want);   /* [pip-export-bar] */
  try {
    teller.tell('flush', .02);
    await replayFlush(900);
    /* #1205: `video_only` reaches the CUT now rather than only the dressing
     * step. The sound is in the pieces, so "video only" has to mean "do not
     * carry it through the concat" - stripping it afterwards would be a
     * second encode of a file that already had what was refused in it. */
    const audioOnly = want?.audio_only === true;
    const made = await screenRing[audioOnly ? 'cutAudio' : 'cut']({ seconds: asked, back: (want || {}).back || 0,
      video_only: !!((want || {}).video_only), view: want?.view === 'pip' ? 'pip' : undefined, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg, onProgress: share => teller.tell('encode', .05 + share * .85) });
    if (!made.ok) { teller.tell('failed', null, { detail: made.detail }); return { ok: false, detail: made.detail, held: made.held }; }
    /* The buffered mix is the sound that played during this picture.
     * Missing captured audio requires an explicit opt-out. */
    const dressed = audioOnly ? { path: made.out, audio: made.audio } : await replayWithSound(made, !!((want || {}).video_only));
    if (!want?.video_only && want?.require_audio !== false
        && (!dressed.audio?.present || !dressed.audio?.complete)) {
      clipMux.forget(made.dir);
      teller.tell('failed', null, { detail: 'the complete audio mix is not in the buffer yet' });
      return { ok: false, detail: 'The saved buffer does not contain the complete audio mix heard during this video. Let the audio buffer fill and try again, or choose picture only.', audio: dressed.audio };
    }
    made.out = dressed.path;
    made.bytes = fs.statSync(dressed.path).size;
    const folder = replayFolder();
    const name = String((want || {}).name || "") || (audioOnly ? replayName(made.seconds).replace('screen-', 'mix-').replace(/\.mp4$/, '.wav') : replayName(made.seconds));
    const where = path.join(folder, name.replace(/[^\w.-]+/g, "-"));
    teller.tell('save', .93);
    try {
      await fs.promises.copyFile(made.out, where);
    } catch (error) {
      clipMux.forget(made.dir);
      return { ok: false, detail: "could not write " + where + ": " + error.message };
    }
    /* The station's export courier, when asked for. A courier that is not
     * there is uploaded:{ok:false} with a reason - never a failed save. The
     * file on this machine is already written by the time this runs. */
    let uploaded = null;
    if (want && want.upload) {
      teller.tell('upload', .96);
      uploaded = { ok: false, detail: "not attempted" };
      try {
        const cfg = readConfig() || {};
        const url = cfg.baseUrl + "/api/export/upload?what=screen&seconds="
          + encodeURIComponent(made.seconds) + "&name=" + encodeURIComponent(path.basename(where));
        const response = await fetch(url, { method: "PUT",
          headers: { "Content-Type": "video/mp4", ...authHeaders(cfg) },
          body: fs.readFileSync(where) });
        const text = await response.text();
        let body = {};
        try { body = text ? JSON.parse(text) : {}; } catch (e) { body = { text }; }
        uploaded = response.ok
          ? { ok: true, id: body.id || body.name || null, dest: body.where || body.path || null }
          : { ok: false, detail: (body.detail || body.error || response.status + " " + response.statusText) };
      } catch (error) {
        uploaded = { ok: false, detail: error.message };
      }
    }
    clipMux.forget(made.dir);
    teller.tell('done', 1, { seconds: made.seconds, where });
    return { ok: true, where, bytes: made.bytes, asked,
      seconds: made.seconds, held: made.held, clamped: !!made.clamped,
      uploaded, audio: dressed.audio, video: made.video || null, detail: "" };
  } catch (error) {
    teller.tell('failed', null, { detail: error.message });
    return { ok: false, detail: error.message };
  }
});

/* THE SAME CUT, BUT INTO THE STATION'S VIDEO EDITOR.
 *
 * This is NOT the desk's own clip window. hot-corners.js takes the answer's
 * `source_id` straight to openVideoEditor(), which loads the STATION's
 * /video-editor/?source=<32 hex characters> in an iframe - so the cut has to
 * reach the station and come back as an identity, exactly as it does from
 * the tablet. Returning a local window's success here would have left the
 * renderer calling openVideoEditor(undefined) and the operator looking at a
 * broken frame.
 *
 * The captured application mix stays under the same recorded interval
 * before upload, preserving the levels heard at playback time.
 * `video_only` explicitly skips that sound.
 *
 * And if the upload fails the captured moment is still written to the
 * recordings folder, said as `original_saved` and `where`. The tablet does
 * the same thing for the same reason: the recording is the part that cannot
 * be taken again. */

/* OkHttp will not carry a non-ASCII header and neither will this one. JSON
 * escapes keep the unicode and the device details without letting a control
 * character into a header - the tablet's VideoEditorContract.audioHeader,
 * word for word, because the station parses what both of them send. */
function asciiHeader(value) {
  let out = "";
  const text = String(value == null ? "" : value);
  for (const ch of text) {
    const code = ch.codePointAt(0);
    if (code >= 32 && code <= 126) out += ch;
    else out += "\\u" + code.toString(16).padStart(4, "0");
  }
  return out;
}

function videoIdentity(value) {
  const id = String(value || "");
  if (!/^[0-9a-f]{32}$/.test(id)) throw new Error("invalid video editor identity");
  return id;
}

/* Recent recordings carry the application mix saved at playback time.
 * Keep that audio and its measured coverage intact. A later source-file or
 * sampler reconstruction cannot reproduce the levels and sound that were heard. */
async function replayWithSound(made, videoOnly) {
  const fromRing = made?.audio || null;
  return { path: made.out, dir: made.dir,
    audio: fromRing || { source: AUDIO_SOURCE, present: false, complete: false,
      state: "unavailable", detail: videoOnly ? "video only, as asked" : "The recorded audio mix is unavailable.",
      coverage_ratio: 0, gaps: 0, video_only_explicit: !!videoOnly },
    notes: [] };
}

ipcMain.handle("replay:edit", async (_event, want) => {
  const endAt = Date.now();
  const opts = want || {};
  const asked = Math.max(1, Math.min(HOLD_MAX_S, Number(opts.seconds) || 60));
  let made = null;
  let file = "";
  try {
    await replayFlush(900);
    made = await screenRing.cut({ seconds: asked, back: opts.back || 0,
      video_only: !!opts.video_only, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
    const dressed = await replayWithSound(made, !!opts.video_only);
    if (!opts.video_only && opts.require_audio !== false
        && (!dressed.audio?.present || !dressed.audio?.complete)) {
      clipMux.forget(made.dir);
      return { ok: false, detail: "The saved buffer does not contain the complete audio mix heard during this video. Let the audio buffer fill and try again, or choose picture only.", audio: dressed.audio };
    }
    file = dressed.path;
    const bytes = fs.statSync(file).size;
    if (!bytes || bytes > 256 * 1024 * 1024) {
      throw new Error("the capture must be between 1 byte and 256 MiB (it is "
        + bytes + ")");
    }
    const cfg = readConfig() || {};
    const name = replayName(made.seconds);
    const response = await fetch(cfg.baseUrl + "/api/video-editor/sources", {
      method: "POST",
      headers: { "Content-Type": "video/mp4", Accept: "application/json",
        "X-Capture-Audio": asciiHeader(JSON.stringify(dressed.audio)),
        "X-Capture-Name": name.replace(/[^ -~]/g, " ").slice(0, 120),
        ...authHeaders(cfg) },
      body: fs.readFileSync(file)
    });
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch (e) { body = { text }; }
    if (!response.ok) {
      throw new Error(body.detail || body.error || (response.status + " " + response.statusText));
    }
    const source = videoIdentity(body.source_id || body.id);
    clipMux.forget(made.dir);
    return { ...body, ok: true, source_id: source, id: source,
      editor_url: "/video-editor/?source=" + source,
      seconds: made.seconds, audio: dressed.audio, notes: dressed.notes };
  } catch (error) {
    /* The moment is the part that cannot be taken again. */
    let kept = { ok: false, where: "" };
    try {
      if (file && fs.existsSync(file) && fs.statSync(file).size > 0) {
        const where = path.join(replayFolder(),
          "pinebox-original-" + Date.now() + ".mp4");
        fs.copyFileSync(file, where);
        kept = { ok: true, where };
      }
    } catch (e) { kept = { ok: false, where: "" }; }
    if (made && made.dir) clipMux.forget(made.dir);
    return { ok: false, detail: error.message,
      original_saved: !!kept.ok, where: kept.where, audio: null };
  }
});

/* THE EDITED VIDEO, KEPT.
 *
 * renderer/video-editor.js:292 has been calling this on a surface that never
 * had it - a desk-only file reaching for a road only the tablet implemented.
 * The station does the editing; this fetches the finished export and puts it
 * in the operator's recordings folder, which is the half a browser cannot
 * do. A file that is not finished is refused by name rather than saved
 * half-written. */
ipcMain.handle("replay:keep-edited", async (_event, want) => {
  const opts = want || {};
  try {
    const exportId = videoIdentity(opts.export_id || opts.exportId);
    const cfg = readConfig() || {};
    const info = await fetchJson(cfg.baseUrl + "/api/video-editor/exports/" + exportId);
    if (String(info.status || "") !== "complete") {
      return { ok: false, detail: "the edited video is not ready to save ("
        + String(info.status || "no status") + ")", export_id: exportId };
    }
    const response = await fetch(cfg.baseUrl + "/api/video-editor/exports/"
      + exportId + "/file", { headers: { ...authHeaders(cfg) } });
    if (!response.ok) {
      throw new Error(response.status + " " + response.statusText);
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    let name = String(opts.name || info.name || ("pine-edited-" + exportId + ".mp4"));
    if (!/\.mp4$/i.test(name)) name += ".mp4";
    const where = path.join(replayFolder(), name.replace(/[^\w.-]+/g, "-"));
    fs.writeFileSync(where, bytes);
    return { ok: true, where, bytes: bytes.length, export_id: exportId,
      detail: "kept to " + where };
  } catch (error) {
    return { ok: false, detail: error.message };
  }
});

/* THE CORNER PREFERENCES, WHICH THE DESK HAS NEVER HAD.
 *
 * hot-corners.js:1835 and :1885 have been calling these on a surface that
 * answers neither, so the desk's corner settings lived only until the app
 * closed. Read, or merge-and-persist; either way what settles is
 * {enabled, tl, tr, bl, br, activationZonePx, sensitivity, ring} and a set pushes that same object back
 * into the page, exactly as the tablet's HotCorners.kt does. `ring` is the
 * screen ring's hold and is read-only here - replayHold is the road that
 * changes it. */
const CORNER_KEYS = ["tl", "tr", "bl", "br"];
const CORNER_ZONE_MIN = 20;
const CORNER_ZONE_MAX = 120;
const CORNER_ZONE_DEFAULT = 42;
const CORNER_SENSITIVITY_MIN = 0;
const CORNER_SENSITIVITY_MAX = 100;
const CORNER_SENSITIVITY_DEFAULT = 50;

function boundedCornerNumber(value, fallback, minimum, maximum) {
  const number = Number(value);
  return Number.isFinite(number)
    ? Math.max(minimum, Math.min(maximum, Math.round(number)))
    : fallback;
}

function cornersRead() {
  const cfg = readConfig() || {};
  const held = cfg.hotCorners || {};
  const out = {
    enabled: held.enabled !== false,
    activationZonePx: boundedCornerNumber(held.activationZonePx, CORNER_ZONE_DEFAULT,
      CORNER_ZONE_MIN, CORNER_ZONE_MAX),
    sensitivity: boundedCornerNumber(held.sensitivity, CORNER_SENSITIVITY_DEFAULT,
      CORNER_SENSITIVITY_MIN, CORNER_SENSITIVITY_MAX),
    ring: screenRing.state().holds,
  };
  for (const key of CORNER_KEYS) out[key] = String(held[key] || "");
  return out;
}

ipcMain.handle("corners:read", () => cornersRead());

ipcMain.handle("corners:set", (_event, patch) => {
  try {
    const cfg = readConfig() || {};
    const held = { ...(cfg.hotCorners || {}) };
    const given = patch || {};
    if (Object.prototype.hasOwnProperty.call(given, "enabled")) {
      held.enabled = !!given.enabled;
    }
    for (const key of CORNER_KEYS) {
      if (Object.prototype.hasOwnProperty.call(given, key)) {
        held[key] = String(given[key] || "");
      }
    }
    for (const [key, fallback, minimum, maximum] of [
      ["activationZonePx", CORNER_ZONE_DEFAULT, CORNER_ZONE_MIN, CORNER_ZONE_MAX],
      ["sensitivity", CORNER_SENSITIVITY_DEFAULT, CORNER_SENSITIVITY_MIN, CORNER_SENSITIVITY_MAX],
    ]) {
      if (Object.prototype.hasOwnProperty.call(given, key)) {
        held[key] = boundedCornerNumber(given[key], fallback, minimum, maximum);
      }
    }
    writeConfig({ hotCorners: held });
    const settled = cornersRead();
    /* The page is told, so a preference changed in one window is the
     * preference the gesture uses in the next second rather than after a
     * reload. */
    try {
      if (win && !win.isDestroyed()) {
        win.webContents.executeJavaScript(
          "try{window.PineHotCorners&&window.PineHotCorners.configure("
          + JSON.stringify(settled) + ")}catch(e){}", true);
      }
    } catch (err) { /* a page that will not take it is not a failed save */ }
    return settled;
  } catch (error) {
    return { ...cornersRead(), detail: error.message };
  }
});

/* The local trim window receives the original recorded MP4 and embedded mix,
 * just like the station editor. Audio stays stereo at its captured levels;
 * the trim/export window can explicitly change those settings afterward. */
ipcMain.handle("replay:local-edit", async (_event, want) => {
  const endAt = Date.now();
  const opts = want || {};
  const asked = Math.max(1, Number(opts.seconds) || 30);
  let made = null;
  try {
    await replayFlush(900);
    made = await screenRing.cut({ seconds: asked, back: opts.back || 0,
      video_only: !!opts.video_only, end_at: endAt },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
    if (!opts.video_only && opts.require_audio !== false
        && (!made.audio?.present || !made.audio?.complete)) {
      clipMux.forget(made.dir);
      return { ok: false, detail: "The saved buffer does not contain the complete audio mix heard during this video. Let the audio buffer fill and try again, or choose picture only.", audio: made.audio || null };
    }
    const notes = ["this window was recorded, not the tablet",
      "cut out of the rolling ring - " + made.seconds.toFixed(1) + "s ending "
      + (made.to <= 0.6 ? "now" : made.to.toFixed(1) + "s ago")];
    if (made.clamped) {
      notes.push("the ring did not reach the whole way back - it holds "
        + Math.round(made.held) + "s");
    }
    const embeddedAudio = made.audio?.present === true && !opts.video_only;
    if (embeddedAudio) notes.push("the captured audio mix stays at its recorded levels");
    const mp4 = fs.readFileSync(made.out);
    clipMux.forget(made.dir);
    openClipExport({ ok: true, mp4, bytes: mp4.length, seconds: made.seconds,
      at: endAt, audio: { broadcast: null, mic: null },
      audioMeta: made.audio || null, embeddedAudio, notes });
    return { ok: true, seconds: made.seconds, bytes: mp4.length, held: made.held,
      clamped: !!made.clamped, notes, audio: made.audio || null,
      broadcast: embeddedAudio, mic: false };
  } catch (error) {
    if (made?.dir) clipMux.forget(made.dir);
    return { ok: false, detail: error.message };
  }
});

/* #1114 / #1118: THE COURIER.
 *
 * "ive been saving pine box recordings to \\10.89.1.125\QuickSwap\
 *  PineBoxRecordings when i export a file. When i tell the pine box i want
 *  to export a broadcast, I want it placed there."
 *
 * The station cannot put it there: that share is mounted READ-ONLY in its
 * container (docker inspect: rw=false). This app, on the Windows machine,
 * can. So the station keeps a ledger of copies owed (/api/export/courier:
 * spoken exports bound for `export_desk_dir`, and kept Pine Cam clips when
 * the camera preference says carry) and this rounds it every twenty
 * seconds: fetch the bytes with the station key, write them beside a
 * .part name, rename into place, and report back - so a copy that failed
 * is said, not assumed. A file already there at the same size is not
 * fetched again. */
const COURIER_MS = 20000;
let courierBusy = false;

async function courierRound() {
  if (courierBusy) return;
  courierBusy = true;
  try {
    const cfg = readConfig();
    if (!cfg.baseUrl) return;
    const got = await fetchJson(`${cfg.baseUrl}/api/export/courier`);
    const jobs = (got && got.pending) || [];
    for (const job of jobs.slice(0, 4)) {
      let out = { ok: false, why: "" };
      /* 2026-09-14: a DELETE owed - a clip set on the QuickSwap share,
         which the station's container can only read. Each path is
         removed if it exists; the job is done when none is left. */
      if (job.what === "delete") {
        const left = [];
        let why = "";
        for (const p of (job.paths || [])) {
          const where = String(p || "");
          if (!/^(\\\\[^\\]+\\[^\\]+|[A-Za-z]:\\)/.test(where)) { why = "not a Windows path: " + where; left.push(where); continue; }
          try { fs.rmSync(where, { force: true }); } catch (error) { why = error.message; }
          if (fs.existsSync(where)) left.push(where);
        }
        out = left.length ? { ok: false, why: (why || "still there") + ": " + left.join("; ") }
                          : { ok: true, path: (job.paths || []).join("; ") };
        try {
          await fetchJson(`${cfg.baseUrl}/api/export/courier/done`, {
            method: "POST", body: JSON.stringify({ id: job.id, ...out }) });
        } catch (error) {
          rememberLog(`[courier] could not report ${job.id}: ${error.message}`);
        }
        rememberLog(`[courier] delete ${job.name} -> ${out.ok ? "gone" : "failed: " + out.why}`);
        continue;
      }
      try {
        const dest = String(job.dest || "");
        if (!/^(\\\\[^\\]+\\[^\\]+|[A-Za-z]:\\)/.test(dest)) {
          throw new Error("not a Windows folder: " + dest);
        }
        fs.mkdirSync(dest, { recursive: true });
        const target = path.join(dest, String(job.name || "export"));
        let already = false;
        try {
          const st = fs.statSync(target);
          already = !job.force && Number(job.bytes) > 0 && st.size === Number(job.bytes);
        } catch { already = false; }
        if (!already) {
          const response = await fetch(`${cfg.baseUrl}${job.url}`,
            { headers: authHeaders(cfg) });
          if (!response.ok) throw new Error(`the station said ${response.status}`);
          const bytes = Buffer.from(await response.arrayBuffer());
          if (!bytes.length) throw new Error("the station sent nothing");
          const part = target + ".part";
          fs.writeFileSync(part, bytes);
          fs.renameSync(part, target);
        }
        out = { ok: true, path: target };
      } catch (error) {
        out = { ok: false, why: error.message };
      }
      try {
        await fetchJson(`${cfg.baseUrl}/api/export/courier/done`, {
          method: "POST", body: JSON.stringify({ id: job.id, ...out }) });
      } catch (error) {
        rememberLog(`[courier] could not report ${job.id}: ${error.message}`);
      }
      rememberLog(`[courier] ${job.name} -> ${out.ok ? out.path : "failed: " + out.why}`);
    }
  } catch (error) {
    /* the station is away; the next round asks again */
  } finally {
    courierBusy = false;
  }
}

ipcMain.handle("flow:pending", (event) => {
  const held = flowWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is nothing waiting for this window" };
  return { ok: true, region: held.region, provenance: held.provenance,
    why: held.why };
});

ipcMain.handle("shot:save", async (event, dataUrl) => {
  const { dialog } = require("electron");
  try {
    const body = String(dataUrl || "").split(",")[1] || "";
    if (!body) return { ok: false, why: "there was nothing to save" };
    const when = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    let folder = app.getPath("pictures");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: "Save the marked-up picture",
        defaultPath: path.join(folder, `pinetab-${when}.png`),
        filters: [{ name: "PNG image", extensions: ["png"] }]
      });
    if (picked.canceled || !picked.filePath) return { ok: false, canceled: true };
    fs.writeFileSync(picked.filePath, Buffer.from(body, "base64"));
    return { ok: true, path: picked.filePath };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* IS THERE A TABLET ON THE END OF ADB AT ALL? Asked BEFORE a capture is
 * attempted rather than after it has failed, so the button can fall back
 * instead of reporting an error the operator can do nothing about. */
async function tabletIsThere() {
  try { return !!(await terminalHost.glassSerial()); }
  catch (error) { return false; }
}

/* Which machine a capture should be of. `want` is the renderer's reading of
 * the roster - who owns the air - and the fallback is this process's reading
 * of the cable. */
async function captureTarget(want) {
  if (want === "app") return { where: "app", why: "chosen" };
  if (await tabletIsThere()) return { where: "tablet", why: "" };
  return { where: "app", why: "the tablet is not reachable" };
}

/* The window's own composited output: what is actually on the glass here,
 * including anything drawn over the page. */
async function localStill() {
  if (!win || win.isDestroyed()) throw new Error("there is no window to capture");
  const image = await win.webContents.capturePage();
  if (!image || image.isEmpty()) throw new Error("the window would not capture");
  return image;
}

/* THIS APP'S OWN ACCOUNT OF ITSELF, in the same shape as the tablet's so the
 * two can be read side by side. The machine facts differ - there is no
 * battery, no jack, no logcat - and saying so is better than inventing
 * equivalents. */
async function localReport() {
  const stamp = new Date().toLocaleString();
  const L = [];
  L.push("PINE BOX DESKTOP - what this window is doing");
  L.push("taken " + stamp + " from the Pine Box app itself");
  L.push("");
  L.push("MACHINE");
  L.push("  host        " + os.hostname() + "  (" + process.platform + " "
    + os.release() + ")");
  L.push("  electron    " + process.versions.electron
    + "   chromium " + process.versions.chrome);
  L.push("  memory      " + Math.round(os.freemem() / 1048576) + " MB free of "
    + Math.round(os.totalmem() / 1048576) + " MB");
  L.push("  up          " + Math.round(os.uptime() / 60) + " min");
  const bounds = win && !win.isDestroyed() ? win.getBounds() : null;
  if (bounds) L.push("  window      " + bounds.width + "x" + bounds.height);
  L.push("");
  L.push("ON THE GLASS");
  try {
    const raw = await win.webContents.executeJavaScript(glassParts.GLASS_QUESTION, true);
    const state = JSON.parse(String(raw));
    if (state.page) {
      L.push("  showing     " + (state.page.title || "(untitled)")
        + "  " + (state.page.size || ""));
    }
    if (state.views) {
      L.push("  view open   " + (state.views.open || "panel")
        + "   (of: " + (state.views.all || "") + ")");
    }
    if (state.sampler && state.sampler.mounted) {
      L.push("  sampler     " + (state.sampler.onScreen ? "on screen"
        : "mounted but NOT on screen")
        + " - bank " + state.sampler.bank + ", " + state.sampler.padsFilled
        + " pads loaded, engine " + state.sampler.engine);
      L.push("              feed " + state.sampler.feedRows + " rows"
        + (state.sampler.tally ? " - " + state.sampler.tally : ""));
    } else if (state.sampler) {
      L.push("  sampler     not mounted");
    }
    if (state.station && state.station.present) {
      L.push("  station     " + (state.station.rows != null
        ? state.station.rows + " feed rows" : "feed present"));
      if (state.station.now) L.push("              now: " + state.station.now);
      if (state.station.speaking) L.push("              speaking: " + state.station.speaking);
    }
    if (state.sound) {
      L.push("  sound       " + state.sound.playing + " of " + state.sound.elements
        + " players going, context " + state.sound.context);
      for (const what of (state.sound.what || [])) L.push("              " + what);
    }
  } catch (error) {
    L.push("  (this window could not be asked: " + error.message + ")");
  }
  L.push("");
  L.push("WHAT THIS APP HAS BEEN COMPLAINING ABOUT");
  const log = (backendLog || []).slice(-14);
  if (!log.length) L.push("  nothing in this session's log");
  for (const line of log) L.push("  " + String(line).slice(0, 200));
  return L.join("\n");
}

/* THE LOCAL RECORDER. No encoder here, so stills are taken off the window on
 * a timer and ffmpeg is handed the sequence.
 *
 * JPEG rather than PNG on purpose: a 1480x940 PNG is around a megabyte and
 * takes long enough to write that the timer starts slipping, which shows up
 * as a clip that runs short. The frames are an intermediate that is thrown
 * away after encoding, so the quality that matters is the x264 pass. */
/* THE WINDOW'S OWN RECORDER, AND THE WAY OUT OF IT. Set by glass:stop; the
 * frame loop reads it each tenth of a second and the frames already taken are
 * still muxed, so stopping gives a shorter clip rather than nothing. */
let stopLocalClip = false;

async function localClipFrames(seconds, dir) {
  const fps = 10;
  const every = Math.round(1000 / fps);
  const want = Math.max(1, Math.round(seconds * fps));
  let taken = 0;
  const startedAt = Date.now();
  while (taken < want) {
    if (stopLocalClip) break;
    const due = startedAt + taken * every;
    const wait = due - Date.now();
    if (wait > 0) await new Promise((done) => setTimeout(done, wait));
    if (!win || win.isDestroyed()) break;
    let image;
    try { image = await win.webContents.capturePage(); }
    catch (error) { break; }
    if (!image || image.isEmpty()) break;
    fs.writeFileSync(path.join(dir, "f" + String(taken + 1).padStart(6, "0") + ".jpg"),
      image.toJPEG(82));
    taken += 1;
  }
  return { frames: taken, fps, seconds: taken / fps, startedAt,
    endedAt: Date.now() };
}

/* THE PICTURE, TAKEN NOW.
 *
 * Its own function because there are two roads to it: the button, and the
 * fallback when the operator asked to scrub back but there is no rolling
 * recording to scrub through. */
async function plainStill(options, aim) {
  const { clipboard, nativeImage } = require("electron");
  let image = null;
  let shot = { bytes: 0, how: "", size: null };
  let grew = 0;
  let grewWhy = "";
  if (aim.where === "app") {
    image = await localStill();
    const png = image.toPNG();
    shot = { bytes: png.length, how: "this window", size: image.getSize() };
  } else {
    /* THE PICTURE AND WHAT IS IN IT, TOGETHER.
     *
     * The map has to be collected at the moment of the shutter or it
     * describes a different screen - and it costs a page session of its
     * own, so it is fetched alongside rather than after. See Glass.map. */
    const glass = await terminalHost.glass();
    const [took, chart] = await Promise.all([
      glass.still(),
      glass.map().catch((error) => ({ ok: false, why: error.message }))
    ]);
    shot = took;
    if (!shot.ok) return shot;
    shot.map = chart && chart.ok ? chart : null;
    shot.mapWhy = chart && chart.ok ? '' : ((chart && chart.why) || 'no map');
    /* TWICE THE SIZE, SHARPENED. The tablet's panel is 1340x800, which is a
     * small picture to paste into a conversation and a smaller one to draw
     * arrows on. Nothing is added that was not there - but the viewer's own
     * scaler stops being the thing that decides how the text reads, and the
     * mark-up window gets four times the room. See shot-enhance.cjs for why
     * lanczos-then-unsharp and not something else.
     *
     * This window's own capture is deliberately NOT enlarged: it is already
     * at this monitor's real resolution. */
    /* THE CALLER CHOOSES HOW FAR. A plain click asks for two - generous for
     * pasting into a conversation. Shift+click asks for three, because that
     * is the road that ends in the mark-up window and an arrow head wants
     * pixels to sit in. */
    /* Kept for the editor's resolution slider - see openShotEditor. */
    shot.raw = shot.png;
    const big = await shotEnhance.enlarge(shot.png,
      { times: Number((options && options.times) || 2),
        ffmpeg: (readConfig() || {}).ffmpeg });
    shot.how = big.how;
    if (big.times > 1) {
      shot.png = big.png;
      shot.bytes = big.png.length;
      /* The size now comes from the image itself - the one the tablet
       * reported describes the frame before it was enlarged. */
      shot.size = null;
      grew = big.times;
    }
    grewWhy = big.why || "";
    image = nativeImage.createFromBuffer(shot.png);
  }
  if (!image || image.isEmpty()) {
    return { ok: false, why: "the picture could not be decoded" };
  }
  clipboard.writeImage(image);
  if (clipboard.readImage().isEmpty()) {
    return { ok: false, why: "the clipboard would not take the picture" };
  }
  const size = shot.size || image.getSize();
  /* The clipboard copy happens either way. The editor is an ADDITION to
   * it, not an alternative - "also copy it to clipboard, but also pop it
   * up in a window" - so a Ctrl+click that never gets marked up has still
   * done what a plain click would have done. */
  let edited = false;
  if (options && options.edit) {
    try {
      openShotEditor(aim.where === "app" ? image.toPNG() : shot.png,
        aim.where === "app" ? image.toPNG() : shot.raw, grew || 1, shot.how,
        shot.map);
      edited = true;
    } catch (error) { edited = false; }
  }
  return { ok: true, width: size.width, height: size.height,
    bytes: shot.bytes, how: shot.how, edited,
    /* How many things in this picture can be inspected, and why none can
     * when that is the answer. */
    regions: shot.map ? (shot.map.regions || []).length : 0,
    mapWhy: shot.mapWhy || "",
    /* What it was enlarged by, and why it was not - the status line says
     * both rather than quietly handing over a smaller picture. */
    grew, grewWhy,
    where: aim.where, why: aim.why };
}

ipcMain.handle("glass:still", async (_event, options) => {
  try {
    const aim = await captureTarget(options && options.target);

    /* SCRUB BACK TO THE MOMENT FIRST.
     *
     * Only the tablet has a rolling recording, and only a Ctrl+click asks to
     * scrub through it - so this window's own capture, and a tablet whose
     * ring is still empty, both fall through to taking the picture now,
     * which is what the button did before. */
    if (options && options.scrub && aim.where !== "app") {
      const reel = await (await terminalHost.glass())
        .clip_fromReplay(options.seconds, { silent: true });
      if (reel && reel.ok && reel.mp4 && reel.mp4.length > 0) {
        openFramePicker(reel);
        return { ok: true, picking: true, seconds: reel.seconds,
          where: aim.where, why: aim.why };
      }
      const now = await plainStill(options, aim);
      if (!now.ok) return now;
      /* Said, not swallowed: the operator asked to scrub and got a plain
       * screenshot instead, and the reason for that matters. */
      return Object.assign({}, now, { picking: false,
        instead: (reel && reel.why) || "the rolling recording is not available" });
    }

    return await plainStill(options, aim);
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* THE RECORDING, WAITING TO BE CUT.
 *
 * The three pieces are written to a folder of their own rather than carried
 * around in memory: the export window plays the video, which means it needs a
 * URL rather than bytes, and a 30-second recording plus two WAVs is tens of
 * megabytes to hold in an object that exists only to be handed to ffmpeg.
 * The folder is removed when the window closes. */
const clipWaiting = new Map();

function openClipExport(made) {
  const dir = clipMux.stash();
  const held = { dir, video: path.join(dir, "screen.mp4"), broadcast: null,
    mic: null, seconds: made.seconds, notes: made.notes || [],
    broadcastOffset: 0, micOffset: 0, micQuiet: false,
    embeddedAudio: made.embeddedAudio === true && made.audioMeta?.present === true };
  fs.writeFileSync(held.video, made.mp4);
  const audio = made.audio || {};
  if (!held.embeddedAudio && audio.broadcast && audio.broadcast.wav && audio.broadcast.wav.length > 44) {
    held.broadcast = path.join(dir, "broadcast.wav");
    fs.writeFileSync(held.broadcast, audio.broadcast.wav);
    held.broadcastOffset = audio.broadcast.offset || 0;
  }
  if (audio.mic && audio.mic.wav && audio.mic.wav.length > 44) {
    held.mic = path.join(dir, "mic.wav");
    fs.writeFileSync(held.mic, audio.mic.wav);
    held.micOffset = audio.mic.offset || 0;
    held.micQuiet = !!audio.mic.quiet;
  }

  const window_ = new BrowserWindow({
    width: 1080,
    height: 820,
    minWidth: 720,
    minHeight: 560,
    title: "Export the tablet clip",
    icon: path.join(__dirname, "assets", "pinebox.ico"),
    backgroundColor: "#0d1217",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  window_.setMenuBarVisibility(false);
  /* The id, not the window - see openShotEditor. Worse here than there: the
   * throw happened BEFORE clipMux.forget below, so every cancelled export
   * also left its screen recording and both WAVs behind in the temp folder. */
  const clipId = window_.webContents.id;
  clipWaiting.set(clipId, held);
  window_.on("closed", () => {
    clipWaiting.delete(clipId);
    /* The pieces existed only to be cut. Keeping them would fill the temp
     * folder with hundreds of megabytes nobody will ever look for again. */
    clipMux.forget(dir);
  });
  window_.loadFile(path.join(__dirname, "renderer", "clip-export.html"));
  return window_;
}

/* file:// for the window to play and decode. It is a file:// page itself, so
 * these load without any protocol handler - and the alternative, tens of
 * megabytes of data: URL through IPC, is what this exists to avoid. */
function fileUrl(where) {
  return where ? "file:///" + String(where).replace(/\\/g, "/") : null;
}

ipcMain.handle("clip:pending", (event) => {
  const held = clipWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is no recording waiting for this window" };
  return {
    ok: true,
    seconds: held.seconds,
    notes: held.notes,
    videoUrl: fileUrl(held.video),
    broadcastUrl: fileUrl(held.broadcast),
    micUrl: fileUrl(held.mic),
    broadcastOffset: held.broadcastOffset,
    micOffset: held.micOffset,
    micQuiet: held.micQuiet,
    embeddedAudio: held.embeddedAudio
  };
});

ipcMain.handle("clip:done", (event) => {
  const window_ = BrowserWindow.fromWebContents(event.sender);
  if (window_ && !window_.isDestroyed()) window_.close();
  return { ok: true };
});

ipcMain.handle("clip:export", async (event, choices) => {
  const { dialog } = require("electron");
  const held = clipWaiting.get(event.sender.id);
  if (!held) return { ok: false, why: "there is no recording waiting for this window" };
  try {
    const when = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    let folder = app.getPath("videos");
    try { if (!folder || !fs.existsSync(folder)) folder = app.getPath("downloads"); }
    catch { folder = app.getPath("downloads"); }
    const picked = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender), {
        title: "Save the tablet clip",
        defaultPath: path.join(folder, `pinetab-${when}.mp4`),
        filters: [{ name: "MP4 video", extensions: ["mp4"] }]
      });
    if (picked.canceled || !picked.filePath) return { ok: false, canceled: true };

    const use = (choices && choices.use) || {};
    const done = await clipMux.mux({
      video: held.video,
      embeddedAudio: held.embeddedAudio && use.broadcast !== false,
      broadcast: !held.embeddedAudio && use.broadcast && held.broadcast
        ? { path: held.broadcast, offset: held.broadcastOffset } : null,
      mic: use.mic && held.mic ? { path: held.mic, offset: held.micOffset } : null,
      inPoint: choices.inPoint,
      outPoint: choices.outPoint,
      /* Null unless the operator actually moved the box - see the note in
       * clip-mux.cjs on why a crop that does nothing is still a risk. */
      crop: choices.crop || null,
      /* Denoise, motion-compensated interpolation and upres - see the chain
       * note in clip-mux.cjs on why the order is not arbitrary. */
      enhance: choices.enhance || null,
      gains: choices.gains || {},
      mono: !!choices.mono,
      out: picked.filePath
    }, { ffmpeg: (readConfig() || {}).ffmpeg });

    /* "After exporting a video, open the folder in Windows Explorer,
     *  allowing me to see the video selected." */
    try { shell.showItemInFolder(done.path); } catch (error) { /* not fatal */ }
    return done;
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

/* THE LOCAL RECORDING, assembled into the same shape the tablet's comes back
 * in - an mp4 buffer plus whatever audio was caught - so the export window
 * cannot tell the two apart and needed no change at all. */
async function localClip(seconds) {
  const dir = clipMux.stash();
  const notes = [];
  try {
    const took = await localClipFrames(seconds, dir);
    if (!took.frames) throw new Error("the window would not give up any frames");
    if (took.frames < Math.round(seconds * took.fps) * 0.8) {
      notes.push("the window could not be captured fast enough - "
        + took.seconds.toFixed(1) + "s of the " + seconds + "s asked for");
    }
    const out = path.join(dir, "screen.mp4");
    try {
      await clipMux.fromFrames({ dir, pattern: "f%06d.jpg", fps: took.fps, out },
        { ffmpeg: (readConfig() || {}).ffmpeg });
    } catch (error) {
      /* Say what was on disk when the encoder refused it. "No packets" reads
       * like the frames are missing, and every time so far they were not. */
      let listed = [];
      try { listed = fs.readdirSync(dir).slice(0, 3); } catch (e) { listed = ["unreadable"]; }
      let first = 0;
      try { first = fs.statSync(path.join(dir, listed[0] || "")).size; } catch (e) { first = 0; }
      throw new Error(error.message + "  [" + took.frames + " frames, first "
        + listed[0] + " " + first + " bytes, in " + dir + "]");
    }
    const mp4 = fs.readFileSync(out);

    /* The broadcast comes out of PineAir's ring, exactly as it does on the
     * tablet - the module runs in this renderer too. */
    const audio = { broadcast: null, mic: null };
    try {
      const askedAt = Date.now();
      const fromAgo = (askedAt - took.startedAt) / 1000;
      const toAgo = Math.max(0, (askedAt - took.endedAt) / 1000);
      const raw = await win.webContents.executeJavaScript(
        glassParts.broadcastQuestion(fromAgo.toFixed(3), toAgo.toFixed(3)), true);
      const got = JSON.parse(String(raw));
      if (got && got.ok) {
        audio.broadcast = { wav: Buffer.from(got.b64, "base64"), offset: 0 };
      } else {
        notes.push("no broadcast audio: " + ((got && got.why) || "the ring did not answer"));
      }
    } catch (error) {
      notes.push("no broadcast audio: " + error.message);
    }
    notes.push("this window was recorded, not the tablet");
    return { ok: true, mp4, bytes: mp4.length, seconds: took.seconds,
      at: Date.now(), audio, notes };
  } finally {
    clipMux.forget(dir);
  }
}

/* CLICKING IT AGAIN STOPS THE PULL. What comes back is a complete, shorter
 * clip rather than the bytes that happened to arrive - see the note in
 * terminal-glass.cjs on why a truncated MP4 is not a short one. */
ipcMain.handle("glass:stop", async () => {
  /* THREE ROADS BEHIND ONE ICON, and the stop has to reach all of them or it
   * is a button that lies on two thirds of its presses. Each yields a
   * complete shorter clip - see the notes on stopRecording and
   * clip_fromReplay for why that is the whole point. */
  const glass = require("./terminal-glass.cjs");
  glass.stopPull(true);
  stopLocalClip = true;
  try {
    /* The tablet's screenrecord, if one is running. Harmless if not. */
    await (await terminalHost.glass()).stopRecording();
  } catch (error) { /* nothing recording is the ordinary case */ }
  return { ok: true };
});

const tabletReplayExport = require('./tablet-replay-export.cjs').createTabletReplayExporter({
  glass: () => terminalHost.glass(), mux: clipMux, folder: replayFolder, config: readConfig
});
ipcMain.handle('tablet:replay-export', async (event, want) => {
  if(event.sender!==win?.webContents)throw Error('Tablet exports belong to the Pine desktop.');
  /* [pip-export-bar] the tablet's cut has no clock to read: the bar sweeps until it is saved */
  const teller = replayProgressTeller(event.sender, want, 'tablet');
  teller.tell('encode', null);
  try {
    const made = await tabletReplayExport(want);
    if (made?.ok) teller.tell('done', 1, { seconds: made.seconds, where: made.where });
    else teller.tell('failed', null, { detail: made?.detail || made?.why || 'PineTab recording unavailable' });
    return made;
  } catch (error) { teller.tell('failed', null, { detail: error.message }); throw error; }
});

ipcMain.handle("glass:clip", async (_event, seconds, options) => {
  try {
    /* Cleared at the start, not at the end: a stop that arrived after the
     * last one finished must not silently cancel the next one. */
    stopLocalClip = false;
    const aim = await captureTarget(options && options.target);
    /* CTRL+CLICK REACHES BACKWARDS. The tablet has been recording itself all
     * along, so "the last thirty seconds" is a read rather than a wait. Only
     * the tablet has a rolling recorder; this window does not, so a local
     * capture still films forwards. */
    /* A REPLAY PULL MAY ASK FOR EVERYTHING. `seconds` null or 0 means the
     * whole buffer; the forward recording still needs a real number because
     * it is a thing the operator waits for. */
    const wantsReplay = !!(options && options.replay) && aim.where !== "app";
    const made = wantsReplay
      ? await (await terminalHost.glass()).clip_fromReplay(seconds)
      : aim.where === "app"
        ? await localClip(seconds)
        : await (await terminalHost.glass()).clip(seconds, options);
    if (!made.ok) return made;
    /* Only a FALLBACK is worth saying. "chosen" is the operator's own
     * decision handed back to them as news. */
    if (aim.why && aim.why !== "chosen") {
      (made.notes = made.notes || []).push(aim.why);
    }
    /* Straight into the export window rather than into a save dialog. The
     * cutting, the channels and the gains are all decisions that need the
     * recording in front of you, and a file written before any of them is a
     * file that has to be written again. */
    openClipExport(made);
    return { ok: true, seconds: made.seconds, bytes: made.bytes,
      notes: made.notes || [], where: aim.where,
      broadcast: !!(made.audio && made.audio.broadcast),
      mic: !!(made.audio && made.audio.mic) };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("glass:report", async (_event, options) => {
  const { clipboard } = require("electron");
  try {
    const aim = await captureTarget(options && options.target);
    if (aim.where === "app") {
      const text = await localReport();
      clipboard.writeText(text);
      return { ok: true, lines: text.split("\n").length, bytes: text.length,
        page: true, where: aim.where, why: aim.why };
    }
    const said = await (await terminalHost.glass()).report();
    if (!said.ok) return said;
    clipboard.writeText(said.text);
    return { ok: true, lines: said.text.split("\n").length,
      bytes: said.text.length, page: said.page, pid: said.pid,
      where: aim.where, why: aim.why };
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("desktop:reconstitute", () => reconstituteDesktop());
ipcMain.handle("backend:log", () => backendLog);
ipcMain.handle("agent:discover-key", () => discoverAgentKey());
ipcMain.handle("agent:get", (_event, route) => fetchJson(`${readConfig().baseUrl}${route}`));
ipcMain.handle("agent:post", (_event, route, body) => fetchJson(`${readConfig().baseUrl}${route}`, {
  method: "POST",
  body: JSON.stringify(body || {})
}));
ipcMain.handle("agent:put", (_event, route, body) => fetchJson(`${readConfig().baseUrl}${route}`, {
  method: "PUT",
  body: JSON.stringify(body || {})
}));
ipcMain.handle("agent:del", (_event, route, body) => fetchJson(`${readConfig().baseUrl}${route}`, {
  method: "DELETE",
  body: JSON.stringify(body || {})
}));
ipcMain.handle("open:external", (_event, url) => shell.openExternal(url));
/* [pinestream] PineStream: this window, a few JPEGs a second, to the station -
 * only while renderer/pinestream.js keeps saying `run` and the station keeps
 * answering keep. See pinestream-push.cjs. */
const { PineStreamPush } = require("./pinestream-push.cjs");
const pineStreamPush = new PineStreamPush({
  getWin: () => win,
  baseUrl: () => readConfig().baseUrl,
  headers: () => authHeaders(),
});
ipcMain.handle("pinestream:push", (_event, verb, opts) => pineStreamPush.verb(String(verb || "state"), opts || {}));

// #1052: only the desktop chrome owns the physical LCD producer. Embedded
// newspaper/article pages cannot obtain a device-control IPC surface.
function lcdHandle(name, handler) {
  ipcMain.handle("lcd:" + name, (event, payload) => {
    if (!win || event.sender.id !== win.webContents.id) throw new Error("LCD control belongs to the Pine Box desktop.");
    return handler(payload || {});
  });
}
lcdHandle("state", () => lcdState());
lcdHandle("configure", async (cfg) => {
  lcdAgent.configure(cfg);
  await lcdAgent.syncSettings();
  return lcdState();
});
lcdHandle("discover", async () => {
  const [network, usb] = await Promise.allSettled([lcdAgent.discover(), usbDisplays()]);
  const devices = [...(network.value?.devices || []), ...(usb.value || [])];
  return {devices, error: devices.length ? '' : network.value?.error || 'No LCD displays found.'};
});
lcdHandle("connect", async (body) => { await prepareLcdConnection(body.host); return lcdAgent.connect(body.host); });
lcdHandle("start", async (body) => {
  if (lcdFirmware.job?.running) throw new Error("Wait for the firmware operation to finish before streaming.");
  await prepareLcdConnection(lcdAgent.config().host);
  return lcdAgent.start({automatic: !!body.automatic});
});
lcdHandle("stop", () => lcdAgent.stop());
lcdHandle("disconnect", async () => {
  let releaseWarning = '';
  try { if (lcdAgent.connected && lcdAgent.device?.hostTouch) await lcdAgent.displayMode('avatar'); }
  catch (error) { releaseWarning = 'USB released. The display could not confirm avatar mode: ' + error.message; }
  finally { lcdAgent.stop(); await lcdSerial.close(); lcdAgent.connected = false; }
  return {...lcdState(), releaseWarning};
});
lcdHandle("frame", (body) => lcdAgent.frame(body.jpeg));
lcdHandle("events", () => lcdAgent.events());
lcdHandle("control", (body) => lcdAgent.control(body.action, body.value));
lcdHandle("display-mode", (body) => lcdAgent.displayMode(body.mode));
lcdHandle("paper-image", async (body) => {
  const cfg = readConfig(), base = new URL(cfg.baseUrl), url = new URL(String(body.url || ''), base);
  if (url.origin !== base.origin || !url.pathname.startsWith('/api/')) throw new Error("LCD paper images must come from the station.");
  const response = await fetch(url, {headers: authHeaders(cfg), signal: AbortSignal.timeout(15000)});
  const type = String(response.headers.get('content-type') || '').split(';')[0];
  if (!response.ok || !/^image\/(jpeg|png|webp)$/.test(type)) throw new Error("Newspaper image unavailable.");
  const chunks = []; let length = 0;
  for await (const part of response.body) { length += part.length; if (length > 5 * 1024 * 1024) throw new Error("LCD paper image too large."); chunks.push(Buffer.from(part)); }
  return 'data:' + type + ';base64,' + Buffer.concat(chunks).toString('base64');
});
lcdHandle("firmware", async (body) => {
  if (body.action && body.action !== "tools") return lcdFirmware.launch(body.action, body);
  const firmware = lcdAgent.state().firmware;
  if (!firmware.available) return {ok: false, why: "Quanta is not installed at the configured path."};
  // Open the existing interactive firmware manager. This does not select a
  // serial port, install a toolchain, erase or flash any attached device.
  const error = await shell.openPath(firmware.tool);
  return {ok: !error, why: error || firmware.reason};
});
lcdHandle("download", async (body) => {
  const result = await saveLcdSample({id: body.id, at: body.at, config: readConfig(),
    defaultDirectory: path.join(app.getPath("downloads"), "Pine Box Samples")});
  writeConfig({saveDir: result.directory});
  return result;
});
lcdHandle("sample-directory", async () => {
  const result = await require("electron").dialog.showOpenDialog(win, {title: "LCD sound samples", defaultPath: lcdState().sampleDirectory,
    properties: ["openDirectory", "createDirectory"]});
  if (!result.canceled && result.filePaths[0]) writeConfig({saveDir: result.filePaths[0]});
  return lcdState();
});
app.on("before-quit", () => { lcdAgent.stop(); lcdSerial.close(); });

// #809: F5 pressed while focus is INSIDE a panel webview never
// reaches the chrome's keydown handler — the webview swallows it.
// Catch it at the source and reload that webview directly.
// #817: anything saved out of the app (radio cache mp3s, exports)
// reveals itself — when the download lands, File Explorer opens on
// the file so it is in hand, not lost in a Downloads pile.
app.on("session-created", (sess) => {
  sess.on("will-download", (ev, item) => {
    // #808: the save dialog OPENS in the folder you last saved to —
    // exports, broadcast grabs, clips all land where the last one went.
    try {
      const last = readConfig().saveDir;
      if (last && fs.existsSync(last)) {
        item.setSaveDialogOptions({
          defaultPath: path.join(last, item.getFilename()),
        });
      }
    } catch { /* the dialog falls back to Downloads */ }
    item.once("done", (e2, state) => {
      if (state === "completed") {
        // …and every completed save re-remembers its folder.
        try {
          writeConfig({ saveDir: path.dirname(item.getSavePath()) });
        } catch { /* remember next time */ }
        try { shell.showItemInFolder(item.getSavePath()); }
        catch { /* explorer said no; the file still saved */ }
      }
    });
  });
});

app.on("web-contents-created", (event, contents) => {
  if (contents.getType() !== "webview") return;
  // #1147: a popup from a webview is a separate BrowserWindow that no
  // volume, mute, pause or FM-off logic ever reaches - one click on the
  // panel's open-the-station link made an ungoverned third copy of the
  // broadcast playing behind the main window. Links open in the system
  // browser; the app's own windows stay the app's.
  contents.setWindowOpenHandler(({ url }) => {
    const u = String(url || "");
    // An empty/about:blank popup is page-authored content (the PDF
    // export writes into one) - it plays no broadcast and stays.
    if (!u || u === "about:blank") return { action: "allow" };
    // #1148: the kit-export window is the app's own page - a progress
    // view (plexus clouds + a loading bar) that plays no broadcast, so
    // it lives as an app window. Everything else keeps the #1147 rule.
    try {
      const base = new URL(readConfig().baseUrl || "");
      const target = new URL(u);
      // 2026-09-08: ...and the retirement desk (/cupboard/retire), the
      // page where rounds about to leave the cupboard wait for a decision.
      // It plays no broadcast either.
      const own = {
        "/export/kit": {width: 940, height: 640, title: "Pine Box - packing the kit"},
        "/cupboard/retire": {width: 1160, height: 840, title: "Pine Box - the retirement desk"},
      };
      if (target.origin === base.origin && own[target.pathname]) {
        return {
          action: "allow",
          overrideBrowserWindowOptions: {
            ...own[target.pathname], autoHideMenuBar: true,
            backgroundColor: "#04060b",
          },
        };
      }
    } catch { /* not a parseable URL - treat it as a plain link */ }
    try {
      if (/^https?:/i.test(u)) shell.openExternal(u);
    } catch { /* a link that will not open is still not a rogue player */ }
    return { action: "deny" };
  });
  contents.on("before-input-event", (ev, input) => {
    if (input.type === "keyDown" && input.key === "F5") {
      ev.preventDefault();
      contents.reload();
    }
  });
});

// #1047 — A PICTURE ON THE CLIPBOARD NEEDS A SECURE ORIGIN.
//
// "when i click copy, I want to copy all the pages of the paper as an image
//  to clipboard allowing me to paste it anywhere."
//
// navigator.clipboard.write() — the only road that puts an IMAGE on the
// clipboard — is gated behind window.isSecureContext, and the panel is
// served over plain http on the LAN. Chromium will treat named origins as
// secure anyway when it is told to; this is that telling, scoped to the
// origins this launcher actually loads (the configured base url and the
// loopback pair a launch-local run uses) so nothing else gains anything.
//
// It is a belt for the braces: inside the Pine Box window the panel is a
// file:// page and Copy goes through pineDesktop.copyImage in preload.js,
// which needs no flag. This is what makes the same click work when the
// panel is opened over http instead.
app.commandLine.appendSwitch(
  "unsafely-treat-insecure-origin-as-secure",
  (() => {
    const origins = new Set(["http://10.89.1.246:8096", "http://127.0.0.1:8096",
      "http://localhost:8096"]);
    try {
      const cfg = readConfig();
      for (const u of [cfg.baseUrl, `http://127.0.0.1:${cfg.port}`,
        `http://localhost:${cfg.port}`]) {
        try { origins.add(new URL(u).origin); } catch {}
      }
    } catch {}
    return Array.from(origins).join(",");
  })()
);

app.whenReady().then(async () => {
  await selfSyncFromShare();
  if (!win || win.isDestroyed()) createWindow();
  if (process.argv.includes('--pip') || readConfig().pip?.enabled === true) {
    win.webContents.once('did-finish-load', async () => {
      try { await win.webContents.executeJavaScript('window.PinePip?.enter()', true); win.show(); win.focus(); }
      catch (error) { console.error('[PiP startup] ' + error.message); }
    });
  }
  if (process.argv.includes('--recover-audio') || process.argv.includes('--recover-playback')) {
    win.webContents.once('did-finish-load', () => setTimeout(() => {
      stationTroubleshooter.open();
      const playback = process.argv.includes('--recover-playback');
      stationTroubleshooter.run(playback ? 'playback' : 'audio').then(result => {
        fs.writeFileSync(path.join(PINE_USER_DATA, playback ? 'station-playback-recovery.json' : 'station-audio-recovery.json'), JSON.stringify(result, null, 2));
      }).catch(error => console.error('[audio recovery] ' + error.message));
    }, 2000));
  }
  const { PineLens } = require('./pinelens.cjs');
  const lens = new PineLens({electron: require('electron'), read: readConfig, write: writeConfig,
    exportFolder: replayFolder,
    upload: async made => {
      const cfg = readConfig();
      const response = await fetch(cfg.baseUrl + '/api/export/upload?what=screen&seconds=' +
        encodeURIComponent(made.seconds) + '&name=' + encodeURIComponent(path.basename(made.path)),
        {method: 'PUT', headers: {'Content-Type': 'video/mp4', ...authHeaders(cfg)},
          body: fs.readFileSync(made.path), signal: AbortSignal.timeout(120000)});
      if (!response.ok) throw new Error('Lens video saved locally; upload failed: HTTP ' + response.status);
      return response.json();
    },
    window: () => win, python: () => pythonCommand(readConfig()),
    request: (route, body) => fetchJson(readConfig().baseUrl + route,
      {method: 'POST', body: JSON.stringify(body), signal: AbortSignal.timeout(5000)})});
  ipcMain.handle('pinelens:preview', () => lens.capture(true));
  ipcMain.handle('pinelens:save', (_event, value) => lens.save(value));
  ipcMain.handle('pinelens:state', () => lens.state());
  lens.round();
  app.on('before-quit', () => lens.close());
  /* #1114: the courier starts once the window is up and rounds forever. */
  setTimeout(courierRound, 8000);
  setInterval(courierRound, COURIER_MS);
  if (process.env.PINE_DESKTOP_PLAYBACK_PROBE === "1") {
    delete process.env.PINE_DESKTOP_PLAYBACK_PROBE;
    require("./playback-probe.cjs").capture({lcdState, lcdFrame: () => lcdAgent.lastFrame})
      .catch(error => rememberLog(`[playback observation] ${error.message}`));
  }
  const cfg = readConfig();
  if (cfg.mode === "launch") {
    try {
      startBackend();
      await waitForHealth(cfg.baseUrl, 12000);
    } catch (err) {
      rememberLog(`[desktop] launch failed: ${err.message}`);
    }
  }
});

app.on("window-all-closed", () => {
  if (backend) backend.kill();
  if (process.platform !== "darwin") app.quit();
});
