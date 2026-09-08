const { app, BrowserWindow, ipcMain, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { LcdAgent, deviceRequest } = require("./lcd-agent.cjs");
const { LcdSerial, usbDisplays } = require("./lcd-serial.cjs");
const { LcdFirmware } = require("./lcd-firmware.cjs");
const { saveLcdSample } = require("./lcd-samples.cjs");

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
      { timeout: 25000 });
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
      if (target.origin === base.origin
          && target.pathname === "/export/kit") {
        return {
          action: "allow",
          overrideBrowserWindowOptions: {
            width: 940, height: 640, autoHideMenuBar: true,
            backgroundColor: "#04060b",
            title: "Pine Box - packing the kit",
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
