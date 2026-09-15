const { app, BrowserWindow, ipcMain, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
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
/* Twice the size and sharpened, for every picture taken of the tablet. */
const shotEnhance = require("./shot-enhance.cjs");
const glassParts = require("./terminal-glass.cjs");
/* For the local report: facts about THIS machine, where the tablet's
 * report has getprop and a battery. */
const os = require("node:os");

let win;
let backend = null;
let backendLog = [];
let reconstituting = false;

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

// #971: one Pine Box, not one per click. A pinned taskbar button is
// pressed to GET to the app, not to start a second copy of it — and
// pine_box.exe is run again on every launch, so without this the shortcut
// and the pin would stack instances. The second instance hands its
// argument list to the first and dies; the first comes to the front.
const pineLock = app.requestSingleInstanceLock();
if (!pineLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    try {
      if (!win || win.isDestroyed()) return;
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    } catch {}
  });
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

function agentRoot() {
  if (process.env.PINE_AGENT_ROOT) return process.env.PINE_AGENT_ROOT;
  if (app.isPackaged) return path.join(process.resourcesPath, "agent");
  const local = path.resolve(__dirname, "..");
  // #828: a bare electron.exe shortcut carries no env, and the local
  // runner's parent is NOT the agent — it has package.json but no
  // app.py. When the guess is wrong, the share is the truth.
  try {
    if (!fs.existsSync(path.join(local, "app.py"))) {
      const share =
        "\\\\10.89.1.246\\ehm_eckx\\pinevoice-stack\\spark-agent";
      if (fs.existsSync(path.join(share, "package.json"))) return share;
    }
  } catch { /* offline — keep the local guess */ }
  return local;
}

function selfSyncFromShare() {
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
    if (!fs.existsSync(path.join(srcDesk, "main.js"))) return;
    const { spawnSync } = require("node:child_process");
    const r = spawnSync("robocopy", [srcDesk,
      path.join(runner, "desktop"),
      "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
      /* 2026-09-14: 25 s was not enough over the share - measured, a
         launch at 17:33 mirrored NOTHING (sfx-tv.js still the 14:28
         copy, main.js from the day before) and the operator saw none
         of the afternoon's work. A mirror that is killed half way is
         worse than a slow one. */
      { timeout: 240000 });
    try {
      fs.copyFileSync(path.join(source, "package.json"),
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
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(cfg),
      ...(options.headers || {})
    }
  });
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
  if (!response.ok) {
    const detail = body && (body.detail || body.error || body.text);
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return body;
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

  /* #1182: WHICH SCREEN THE RING RECORDS, DECIDED HERE AND NOWHERE ELSE.
   *
   * getDisplayMedia normally raises a picker. Two reasons it must not here:
   * the recorder starts itself a couple of seconds after the app opens, and
   * a picker nobody is sitting in front of is a feature that never runs; and
   * the wrong choice in that picker would quietly record somebody's email
   * into a ring that gets exported. The answer is this window, always, and
   * the renderer is given no say in it.
   *
   * `video: win` hands Electron the BrowserWindow itself rather than a
   * desktopCapturer source id, so the capture follows the window rather
   * than a screen region.
   *
   * #1205: AND THE SOUND COMES WITH IT NOW. The comment that used to stand
   * here said audio was refused deliberately, because "the broadcast is
   * pulled from PineAir's own ring when a clip is cut... and capturing it
   * twice would put it in the file twice". The first half of that was
   * measured and found to be false on this desk: PineAir.start() has exactly
   * one caller in the whole renderer (sampler.js:3247), so on a desk where
   * the sampler is never opened there is no ring at all; and PineAir taps
   * media elements in the document it RUNS in, which is the shell, while the
   * broadcast plays in the panel - `<webview id="controlFrame">` - a separate
   * document in a separate process. Every recording was silent, and the
   * editor said so: "No audio was captured in this recording."
   *
   *   "Similar to the tablet, I always want to capture the broadcast audio
   *    of the recording. So any time that I go into the video editor, I need
   *    the audio of the broadcast."
   *
   * So the sound is captured WITH the picture, the way the tablet does it,
   * and the second half of the old comment becomes the thing to handle: the
   * after-the-fact PineAir road is now a fallback that runs only when the
   * ring carried no sound, so nothing is ever muxed twice. See
   * replayWithSound().
   *
   * WHAT 'loopback' IS, AND WHAT IT IS NOT (read off this Electron's own
   * electron.d.ts, 37.10.3, interface Streams):
   *
   *   "If a string is specified, can be `loopback` or `loopbackWithMute`.
   *    Specifying a loopback device will capture system audio, and is
   *    currently only supported on Windows."
   *
   * So: Windows only, and this desk is Windows. Elsewhere the handler answers
   * `audio: false`, the capture comes back with no audio track, and the
   * renderer reports honest silence with a reason rather than a claim.
   *
   * 'loopback' AND NOT 'loopbackWithMute', AND NOT A WebFrameMain, and that
   * choice is the station's sound. loopbackWithMute mutes local playback
   * while it captures - it would silence the speakers for as long as the ring
   * runs, which is every minute the app is open. Handing the panel's frame
   * instead (`audio: <WebFrameMain>`) would reroute the panel's real playback
   * through the capture path and, per the same typings, mutes it unless
   * enableLocalEcho is set - a live broadcast is not the place to test that.
   * Plain loopback is a passive read of what the machine is already playing:
   * it opens no input device, it takes no microphone, and it changes nothing
   * about the path the sound already travels to the speakers. */
  try {
    session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
      if (!win || win.isDestroyed()) return callback({});
      /* Only when the page asked for it. Electron ignores an audio answer to
       * a request that wanted none, and saying it anyway would make the log
       * read as though every capture had sound. */
      const wantsAudio = request && request.audioRequested !== false;
      callback({ video: win,
        audio: (LOOPBACK_HERE && wantsAudio) ? "loopback" : false });
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
        if (!win || win.isDestroyed() || win.isMinimized()) return;
        writeConfig({ ...readConfig(), bounds: win.getBounds() });
      } catch (error) {}
    }, 600);
  };
  win.on("resize", rememberBounds);
  win.on("move", rememberBounds);
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.webContents.once("did-finish-load", () => watchTheShare());
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
    setTimeout(() => {
      try {
        if (!win || win.isDestroyed()) return;
        win.webContents.executeJavaScript(
          "(function(){try{return window.PineScreenRing"
          + "?window.PineScreenRing.start({gesture:true})&&1:0}catch(e){return -1}})()",
          true);
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

   EVERYTHING ELSE RELOADS, because it has to. Script already evaluated
   cannot be taken back: modules here hold listeners, timers, feed
   subscriptions and an audio graph, and re-running a file over the top would
   leave two of each. A reload is the only honest way to load new JavaScript,
   and it is what F5 would have done if the mirror were fresh.

   MAIN.JS AND PRELOAD.JS ARE NOT HOT. They are this process; changing them
   needs a relaunch, and pretending otherwise is how you get an app running
   half of one version. They are watched only so the log can SAY so.
   =========================================================================== */

const HOT_EVERY_MS = 1500;      /* brisk enough to feel immediate           */
const HOT_SLOW_MS = 5000;       /* when the share is being slow, back off   */
let hotTimer = null;
let hotSeen = null;             /* name -> "mtime:size" of what is mirrored */
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

function watchTheShare() {
  if (hotTimer) return;
  let source;
  try {
    source = hotSourceDir();
    if (!fs.existsSync(source)) {
      console.log("[hot] no source renderer at " + source + " - not watching");
      return;
    }
    hotSeen = hotScan(source);
    console.log("[hot] watching " + source + " (" + hotSeen.size + " files)");
  } catch (error) {
    console.log("[hot] could not read the share: " + error.message);
    return;
  }

  const tick = () => {
    hotTimer = null;
    let wait = HOT_EVERY_MS;
    try {
      const began = Date.now();
      const now = hotScan(source);
      const changed = [];
      for (const [name, stamp] of now) {
        if (hotSeen.get(name) !== stamp) changed.push(name);
      }
      hotSeen = now;
      if (changed.length) applyHot(source, changed);
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
      for (const name of hotSelfFiles(source)) {
        try {
          const at = path.join(source, "..", name);
          const info = fs.statSync(at);
          const stamp = Math.round(info.mtimeMs) + ":" + info.size;
          const key = "^" + name;
          if (hotSelf.has(key) && hotSelf.get(key) !== stamp) hotSayRelaunch(name);
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

function applyHot(source, changed) {
  const mirror = path.join(__dirname, "renderer");
  const landed = [];
  for (const name of changed) {
    try {
      fs.copyFileSync(path.join(source, name), path.join(mirror, name));
      landed.push(name);
    } catch (error) {
      console.log("[hot] could not copy " + name + ": " + error.message);
    }
  }
  if (!landed.length) return;
  if (!win || win.isDestroyed()) return;

  const onlyCss = landed.every((name) => /\.css$/i.test(name));
  console.log("[hot] " + landed.join(", ") + (onlyCss ? " - swapped" : " - reloading"));
  if (onlyCss) {
    /* Bump the href of each stylesheet whose file changed. The browser
     * re-fetches and re-applies it; nothing else on the page moves. */
    const list = JSON.stringify(landed);
    win.webContents.executeJavaScript(
      "(function(names){try{" +
      "  names.forEach(function(name){" +
      "    var links=[].slice.call(document.querySelectorAll('link[rel=stylesheet]'));" +
      "    links.forEach(function(link){" +
      "      var href=String(link.getAttribute('href')||'');" +
      "      if(href.split('?')[0].split('/').pop()!==name) return;" +
      "      link.setAttribute('href', href.split('?')[0] + '?hot=' + Date.now());" +
      "    });" +
      "  });" +
      "}catch(e){}})(" + list + ");", true
    ).catch(() => {});
    return;
  }
  win.webContents.reloadIgnoringCache();
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
function treeStamp(root) {
  /* THE WHOLE TREE, because a list is a blind spot waiting to happen.
   *
   * The first version of this stamped a hand-picked six, back when the
   * renderer WAS renderer.js and a stylesheet; it grew views of its own
   * and the mark went on reporting "newest source" about six files while
   * a dozen others differed. That was fixed by walking renderer/ - and
   * the fix repeated the mistake one level up. `main.js` and
   * `preload.js` were still named by hand, so their twenty-one SIBLINGS
   * were not stamped at all: lcd-agent, terminal-host, tablet-mirror,
   * clip-mux, shot-enhance, terminal-glass, the two .ps1 workers - every
   * one of them `require`d by this process at startup, and every one of
   * them able to differ from the share behind a green line.
   *
   * What the mark is really asked is "is my mirror the share's tree",
   * and the rebuild answers it with `robocopy /MIR` over the WHOLE of
   * desktop/. So that is the question stamped here: all of it, walked,
   * with no list to fall out of date. 131 files against the 97 this
   * stated before - one extra SMB stat per four, once a minute. */
  const wanted = [];
  const walk = (relative) => {
    let entries;
    try {
      entries = fs.readdirSync(path.join(root, relative) || root,
                               { withFileTypes: true });
    } catch {
      return false;
    }
    for (const entry of entries) {
      const name = relative ? relative + "/" + entry.name : entry.name;
      if (entry.isDirectory()) walk(name);
      else if (entry.isFile()) wanted.push(name);
    }
    return true;
  };
  if (!walk("")) {
    /* Unreadable tree: answer something rather than throwing, and let the
     * missing list say which of the originals could not be reached. */
    wanted.push("main.js", "preload.js", "renderer/renderer.js",
                "renderer/index.html", "renderer/webview-preload.js",
                "renderer/styles.css");
  }
  let newest = 0;
  let bytes = 0;
  const missing = [];
  for (const name of wanted) {
    try {
      const info = fs.statSync(path.join(root, name));
      newest = Math.max(newest, info.mtimeMs);
      bytes += info.size;
    } catch {
      missing.push(name);
    }
  }
  return { newest, bytes, missing, counted: wanted.length };
}

ipcMain.handle("desktop:build", () => {
  const source = path.join(process.env.PINE_AGENT_ROOT || agentRoot(),
                           "desktop");
  const mine = treeStamp(path.resolve(__dirname));
  let theirs = { newest: 0, bytes: 0, missing: [], counted: 0 };
  let reachable = true;
  try {
    theirs = treeStamp(source);
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
});

/* The terminal provisioner: discovery, the restore image, the GSI and
 * the unlock. It owns where adb and fastboot live; every decision it
 * makes lives in terminal.cjs / firmware.cjs / gsi.cjs, which are
 * tested without hardware. */
const terminalHost = new TerminalHost({ readConfig, writeConfig }).install(ipcMain);

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

async function tabletVitals() {
  const serial = await terminalHost.glassSerial();
  if (!serial) {
    vitals = null;
    return { ok: false, why: "no tablet is attached" };
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
  if (vitalsHeld && Date.now() - vitalsAt < VITALS_HOLD) return vitalsHeld;
  /* Two callers arriving together share one sweep rather than starting two. */
  if (!vitalsGoing) {
    vitalsGoing = vitals.read().then((said) => {
      vitalsHeld = said;
      vitalsAt = Date.now();
      vitalsGoing = null;
      return said;
    }).catch((error) => {
      vitalsGoing = null;
      return { ok: false, why: error.message };
    });
  }
  return vitalsGoing;
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

async function openTabletMirror(options) {
  const { Mirror } = require("./tablet-mirror.cjs");

  if (mirrorWindow && !mirrorWindow.isDestroyed()) {
    if (mirrorWindow.isMinimized()) mirrorWindow.restore();
    mirrorWindow.focus();
    if (options && options.full) mirrorWindow.setFullScreen(true);
    return { ok: true, already: true };
  }

  const tools = terminalHost.tools();
  const serial = await terminalHost.glassSerial();
  if (!serial) return { ok: false, why: "no tablet is reachable over adb" };

  /* WHAT THE TABLET WAS DRAWING BEFORE THIS OPENED, so the panel can say
   * what watching costs rather than only what the tablet costs. Taken
   * before the encoder starts, which is the only moment it means anything. */
  try {
    const before = await tabletVitals();
    if (vitals && before && before.ok) vitals.mark(before);
  } catch (error) { /* a missing baseline just hides one row */ }

  const found = clipMux.findFfmpeg((readConfig() || {}).ffmpeg);
  mirror = new Mirror({ adb: tools.adb, serial, ffmpeg: found.path });
  /* How big the tablet actually is, asked once, so a third and a half are
   * fractions of the real screen rather than of a guess. */
  await mirror.measure((args) => new Promise((resolve) => {
    require("node:child_process").execFile(tools.adb, args,
      { timeout: 15000, windowsHide: true },
      (error, stdout, stderr) => resolve(String(stdout || "") + String(stderr || "")));
  }));

  const real = mirror.real;
  /* Opens at half the tablet's size on this desk - big enough to read, small
   * enough to sit beside the panel, and the window is resizable from there. */
  mirrorWindow = new BrowserWindow({
    width: Math.round(real.width / 2),
    height: Math.round(real.height / 2) + 34,
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
  mirrorWindow.setMenuBarVisibility(false);
  mirrorWindow.on("closed", () => {
    mirrorWindow = null;
    /* The held input shell belongs to this window. Leaving it open would
     * keep an adb shell alive on the tablet for no reader. */
    if (poke) { poke.close(); poke = null; }
    /* The encoder on the tablet stops when nobody is watching. A mirror
     * left running behind a closed window is a battery being spent on a
     * picture nobody can see. */
    if (mirror) { mirror.close(); mirror = null; }
  });
  mirrorWindow.loadFile(path.join(__dirname, "renderer", "tablet-mirror.html"));
  if (options && options.full) {
    mirrorWindow.once("ready-to-show", () => mirrorWindow.setFullScreen(true));
  }
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

async function openCameraWindow(facing) {
  const { CameraGlass } = require("./tablet-mirror.cjs");
  const tools = terminalHost.tools();
  const serial = await terminalHost.glassSerial();
  if (!serial) return { ok: false, why: "no tablet is reachable over adb" };

  /* Ask the tablet to put its camera on the socket BEFORE connecting: the
   * service opens the lens when a reader arrives, so the order matters. */
  const glass = await terminalHost.glass();
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
    if (camera) { await camera.close(); camera = null; }
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
    if (!poke) {
      const { TabletInput } = require("./tablet-input.cjs");
      const tools = terminalHost.tools();
      const serial = await terminalHost.glassSerial();
      if (!serial) return { ok: false, why: "no tablet is attached" };
      poke = new TabletInput({ adb: tools.adb, serial });
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
    return await mirror.open(shape || {});
  } catch (error) {
    return { ok: false, why: error.message };
  }
});

ipcMain.handle("mirror:size", (_event, size) => {
  if (!mirror) return { ok: false, why: "the mirror is not set up" };
  try {
    return mirror.retune(String(size || ""));
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
  /* The strip under the picture is part of the window but not part of the
   * tablet, so it is added on top of the asked-for picture size. */
  window_.setSize(Math.max(240, Math.round(shape.width)),
    Math.max(200, Math.round(shape.height) + 34));
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
ipcMain.handle("app:revive", (_event, opts) => {
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
    try { app.releaseSingleInstanceLock(); } catch (error) { /* never held */ }
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
ipcMain.handle("replay:source", () => {
  try {
    if (!win || win.isDestroyed()) return { ok: false, detail: "no window" };
    /* #1205: `loopback` travels with the source id so the renderer can say,
     * in the one place a person will read it, whether a silent recording is
     * this platform's limit or a gesture it never got. */
    return { ok: true, id: win.getMediaSourceId(), loopback: LOOPBACK_HERE,
      platform: process.platform,
      detail: LOOPBACK_HERE ? "" : "Electron captures application audio on "
        + "Windows only, so recordings on " + process.platform + " are silent" };
  } catch (error) {
    return { ok: false, detail: error.message };
  }
});

ipcMain.handle("replay:begin", (_event, opts) => {
  try {
    const cfg = readConfig() || {};
    const held = Number(cfg.replayHoldSeconds || 0) || HOLD_DEFAULT_S;
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
 * for the count of landed pieces to move. The ceiling is short on purpose: a
 * recorder that has died must cost a cut a few hundred milliseconds, never
 * hang it, so the cut goes ahead with whatever is on disk and the answer
 * still says honestly where the window landed. */
function replayFlush(ms) {
  return new Promise((resolve) => {
    if (!win || win.isDestroyed() || !screenRing.running) return resolve(false);
    const was = screenRing.taken;
    let done = false;
    const finish = (got) => { if (done) return; done = true; clearInterval(tick);
      clearTimeout(stop); resolve(got); };
    const tick = setInterval(() => { if (screenRing.taken !== was) finish(true); }, 25);
    const stop = setTimeout(() => finish(false), Math.max(200, Number(ms) || 900));
    try { win.webContents.send("replay-flush"); }
    catch (error) { finish(false); }
  });
}

ipcMain.handle("replay:frames", async (_event, want) => {
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
      { seconds, count: asked.count, edge: Number(asked.edge) || 640, back },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    return { ...got, asked_back: askedBack,
      clamped: !!got.clamped || (askedBack - back > 0.6) };
  } catch (error) {
    return { ok: false, held: 0, detail: error.message };
  }
});

ipcMain.handle("replay:export", async (_event, want) => {
  const asked = Math.max(1, Number((want || {}).seconds) || 30);
  try {
    await replayFlush(900);
    /* #1205: `video_only` reaches the CUT now rather than only the dressing
     * step. The sound is in the pieces, so "video only" has to mean "do not
     * carry it through the concat" - stripping it afterwards would be a
     * second encode of a file that already had what was refused in it. */
    const made = await screenRing.cut({ seconds: asked, back: (want || {}).back || 0,
      video_only: !!((want || {}).video_only) },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
    /* The broadcast goes under the picture here too. A screen recording of a
     * radio station with no radio on it is half a recording, and the sheet
     * offers "Allow video without complete audio" precisely because the
     * sound is meant to be there unless it is refused. */
    const dressed = await replayWithSound(made, !!((want || {}).video_only));
    made.out = dressed.path;
    made.bytes = fs.statSync(dressed.path).size;
    const folder = replayFolder();
    const name = String((want || {}).name || "") || replayName(made.seconds);
    const where = path.join(folder, name.replace(/[^\w.-]+/g, "-"));
    try {
      fs.copyFileSync(made.out, where);
    } catch (error) {
      clipMux.forget(made.dir);
      return { ok: false, detail: "could not write " + where + ": " + error.message };
    }
    /* The station's export courier, when asked for. A courier that is not
     * there is uploaded:{ok:false} with a reason - never a failed save. The
     * file on this machine is already written by the time this runs. */
    let uploaded = null;
    if (want && want.upload) {
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
    return { ok: true, where, bytes: made.bytes, asked,
      seconds: made.seconds, held: made.held, clamped: !!made.clamped,
      uploaded, audio: dressed.audio, detail: "" };
  } catch (error) {
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
 * The broadcast is laid under the picture BEFORE the upload, out of
 * PineAir's ring, for the window the video actually covers - the video is a
 * slice of the past, so the sound must be the same slice of the past, not
 * the last N seconds counted from now. `video_only` skips that.
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

/* The picture as it is, with the broadcast laid under it when there is one.
 * Returns {path, dir, audio, notes}.
 *
 * #1205: THE SOUND IS USUALLY ALREADY THERE, AND THEN THIS DOES NOTHING.
 *
 * The ring films with the desk's loopback mix on it, so a cut comes back with
 * the broadcast already under the picture, sample-aligned by construction -
 * one file, one clock, nothing to drift. When that is what happened, this
 * returns the cut untouched and reports the RING's provenance.
 *
 * That is also the rule that keeps the file honest: THE OLD PINEAIR ROAD
 * RUNS ONLY WHEN THE RING CARRIED NOTHING. Muxing both would put the same
 * broadcast in the file twice, a few hundred milliseconds apart - the exact
 * fault the #1182 comment was written to avoid, arriving from the other
 * direction. It is kept as a fallback rather than deleted because it costs
 * nothing when there is no sound to add and because it is the road that
 * works on a surface where these modules are injected into the panel itself
 * (the tablet), where PineAir genuinely can hear the broadcast.
 *
 * On this desk it will almost never fire, and when it does not fire it says
 * why: PineAir.start() has one caller in the whole renderer (sampler.js:3247)
 * and it taps the shell, while the broadcast plays in the panel webview. */
async function replayWithSound(made, videoOnly) {
  const notes = [];
  const fromRing = (made && made.audio) || null;
  if (fromRing && fromRing.present && !videoOnly) {
    return { path: made.out, dir: made.dir, audio: fromRing, notes };
  }
  if (videoOnly) {
    return { path: made.out, dir: made.dir,
      audio: fromRing || { source: AUDIO_SOURCE, present: false, complete: false,
        state: "unavailable", detail: "video only, as asked",
        coverage_ratio: 0, gaps: 0, video_only_explicit: true },
      notes };
  }
  const audio = { ...(fromRing || {}), source: "pine-air-ring", present: false,
    complete: false, state: "unavailable", detail: "",
    ring_detail: (fromRing && fromRing.detail) || "",
    video_only_explicit: !!videoOnly };
  let wav = null;
  try {
    const raw = await win.webContents.executeJavaScript(
      glassParts.broadcastQuestion(made.from.toFixed(3), made.to.toFixed(3)), true);
    const got = JSON.parse(String(raw));
    if (got && got.ok) wav = Buffer.from(got.b64, "base64");
    else audio.detail = String((got && got.why) || "the ring did not answer");
  } catch (error) {
    audio.detail = error.message;
  }
  if (!wav || wav.length <= 44) {
    audio.state = "unavailable";
    if (!audio.detail) audio.detail = "the broadcast ring held nothing for that window";
    /* Both roads are named, because "no audio" with one reason reads like a
     * fault and this is two different ones stacked: the recording had no
     * loopback, and the after-the-fact tap had nothing either. */
    if (audio.ring_detail) audio.detail = audio.ring_detail + "; " + audio.detail;
    notes.push("no broadcast audio: " + audio.detail);
    return { path: made.out, dir: made.dir, audio, notes };
  }
  const wavPath = path.join(made.dir, "broadcast.wav");
  const out = path.join(made.dir, "with-sound.mp4");
  try {
    fs.writeFileSync(wavPath, wav);
    await clipMux.mux({ video: made.out, broadcast: { path: wavPath, offset: 0 },
      mic: null, gains: {}, inPoint: 0, outPoint: made.seconds, out },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    audio.present = true;
    audio.complete = true;
    audio.state = "captured";
    audio.coverage_ratio = 1;
    audio.covered_seconds = made.seconds;
    audio.gaps = 0;
    audio.gap_seconds = 0;
    audio.detail = "the broadcast, from PineAir's ring";
    return { path: out, dir: made.dir, audio, notes };
  } catch (error) {
    /* #1205: "unavailable", not "partial". The file returned here is the
     * ORIGINAL cut - the mux failed, so it has no audio track at all - and
     * "partial" makes the editor print "Audio has gaps", which is a claim
     * that some of the sound is in there. None of it is. */
    audio.state = "unavailable";
    audio.present = false;
    audio.complete = false;
    audio.coverage_ratio = 0;
    audio.detail = "the sound would not lay under the picture: " + error.message;
    notes.push(audio.detail);
    return { path: made.out, dir: made.dir, audio, notes };
  }
}

ipcMain.handle("replay:edit", async (_event, want) => {
  const opts = want || {};
  const asked = Math.max(1, Math.min(HOLD_MAX_S, Number(opts.seconds) || 60));
  let made = null;
  let file = "";
  try {
    await replayFlush(900);
    made = await screenRing.cut({ seconds: asked, back: opts.back || 0,
      video_only: !!opts.video_only },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
    const dressed = await replayWithSound(made, !!opts.video_only);
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
 * {enabled, tl, tr, bl, br, ring} and a set pushes that same object back
 * into the page, exactly as the tablet's HotCorners.kt does. `ring` is the
 * screen ring's hold and is read-only here - replayHold is the road that
 * changes it. */
const CORNER_KEYS = ["tl", "tr", "bl", "br"];

function cornersRead() {
  const cfg = readConfig() || {};
  const held = cfg.hotCorners || {};
  const out = { enabled: held.enabled !== false, ring: screenRing.state().holds };
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

/* THE SAME CUT INTO THE DESK'S OWN TRIM WINDOW - a second road, not a
 * rival. replayEdit above is the one the corner gesture uses, because that
 * is the one the renderer's contract names; this one opens the local clip
 * window (openClipExport) with its trim, its channels and its gains, which
 * is a thing the tablet has no equivalent of and the desk should not lose.
 * It is registered under a name of its own: two handlers on one channel is
 * a throw at startup, not a fallback.
 *
 * openClipExport is the window the forward recorder already opens - trim,
 * channels, gains - and it takes exactly what localClip() returns. So the
 * ring's cut is dressed in that same shape, including the broadcast audio.
 * That is the one piece that has to line up: the video is a slice of the
 * past, so the audio must be the same slice of the past, not the last N
 * seconds counted from now.
 *
 * #1205: AND THE BROADCAST CHANNEL NOW COMES OUT OF THE CUT ITSELF.
 *
 * This window's export runs through clipMux.planArgs, which maps ONLY the
 * channels it is handed and writes `-an` when it is handed none - so a cut
 * that already carries the desk mix would have been exported silent, by a
 * road that was reading the picture and throwing the sound away. The mix is
 * therefore lifted out of the cut into a wav and handed over as the
 * broadcast channel: the operator keeps the checkbox and the gain, the sound
 * is the one that was recorded with the picture, and it is in the file
 * exactly once. PineAir is asked only when the cut had nothing. */
async function ringAudioAsWav(made) {
  const out = path.join(made.dir, "ring-audio.wav");
  const args = ["-hide_banner", "-nostdin", "-y", "-i", made.out,
    "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", out];
  await clipMux.run(clipMux.findFfmpeg((readConfig() || {}).ffmpeg).path, args, 120000);
  const wav = fs.readFileSync(out);
  if (wav.length <= 44) throw new Error("the cut's audio track was empty");
  return wav;
}

ipcMain.handle("replay:local-edit", async (_event, want) => {
  const asked = Math.max(1, Number((want || {}).seconds) || 30);
  try {
    const made = await screenRing.cut({ seconds: asked, back: (want || {}).back || 0,
      video_only: !!((want || {}).video_only) },
      { ffmpeg: (readConfig() || {}).ffmpeg });
    if (!made.ok) return { ok: false, detail: made.detail, held: made.held };
    const notes = ["this window was recorded, not the tablet",
      "cut out of the rolling ring - " + made.seconds.toFixed(1) + "s ending "
      + (made.to <= 0.6 ? "now" : made.to.toFixed(1) + "s ago")];
    if (made.clamped) {
      notes.push("the ring did not reach the whole way back - it holds "
        + Math.round(made.held) + "s");
    }
    const audio = { broadcast: null, mic: null };
    const ring = made.audio || {};
    if (!(want && want.video_only) && ring.present) {
      try {
        audio.broadcast = { wav: await ringAudioAsWav(made), offset: 0 };
        notes.push("the broadcast was recorded with the picture - "
          + String(ring.detail || "the desk mix"));
      } catch (error) {
        notes.push("the recorded sound would not come out of the cut: " + error.message);
      }
    }
    if (!(want && want.video_only) && !audio.broadcast) {
      try {
        const fromAgo = made.from;
        const toAgo = made.to;
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
    }
    const mp4 = fs.readFileSync(made.out);
    clipMux.forget(made.dir);
    openClipExport({ ok: true, mp4, bytes: mp4.length, seconds: made.seconds,
      at: Date.now(), audio, notes });
    return { ok: true, seconds: made.seconds, bytes: mp4.length, held: made.held,
      clamped: !!made.clamped, notes, audio: made.audio || null,
      broadcast: !!audio.broadcast, mic: false };
  } catch (error) {
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
          already = Number(job.bytes) > 0 && st.size === Number(job.bytes);
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
    broadcastOffset: 0, micOffset: 0, micQuiet: false };
  fs.writeFileSync(held.video, made.mp4);
  const audio = made.audio || {};
  if (audio.broadcast && audio.broadcast.wav && audio.broadcast.wav.length > 44) {
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
    micQuiet: held.micQuiet
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
      broadcast: use.broadcast && held.broadcast
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
  selfSyncFromShare();
  createWindow();
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
