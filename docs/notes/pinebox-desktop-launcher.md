---
name: pinebox-desktop-launcher
description: "How Pine Box Desktop launches on the Windows box — runner cache, direct electron.exe, ELECTRON_RUN_AS_NODE trap"
metadata: 
  node_type: memory
  type: project
  originSessionId: 76060765-7250-4692-8400-1a3022b54df3
  modified: 2026-08-27T12:51:22.450Z
---

Pine Box Desktop (Electron app in `spark-agent/desktop/`) is launched via
`C:\Users\Ehm Ecks\Desktop\Launch Pine Box Desktop.cmd`, which mirrors
`desktop/` + package.json to a local runner cache at
`%LOCALAPPDATA%\PineBoxDesktop\runner` (SMB is too slow to run from).

Two traps fixed 2026-08-17:
- The runner's `node_modules/.bin` is empty (its electron package is
  hand-assembled — no cli.js), so `npm run desktop` fails with "'electron'
  is not recognized". The .cmd now calls
  `node_modules\electron\dist\electron.exe .` directly — keep it that way.
- Shells spawned from VS Code (and my Bash/PowerShell tools) inherit
  `ELECTRON_RUN_AS_NODE=1`, which turns electron.exe into plain Node —
  `app` is undefined at main.js:11. The .cmd clears it before launch.

Env the app expects (set by the .cmd): `PINE_AGENT_ROOT` (SMB agent dir),
`PINE_DESKTOP_BASE_URL=http://10.89.1.246:8096`, `PINE_DESKTOP_MODE=attach`.

**pine_box.exe (2026-08-18, commit e36b07d)** — the ANY-PC launcher:
`\\10.89.1.246\ehm_eckx\pinevoice-stack\pine_box.exe` (8KB C#, source in
repo at desktop/tools/pine_box.cs, rebuild with the framework csc). It
mirrors desktop/+package.json to %LOCALAPPDATA%\PineBoxDesktop\runner,
and on first run unpacks `pinevoice-stack\desktop-runtime\electron-win64.zip`
(142MB, zipped from this PC's runner electron pkg — NO Node/npm needed),
writes path.txt, sets the attach env, clears ELECTRON_RUN_AS_NODE, and
launches electron.exe. Overrides: PINE_STACK, PINE_RUN_DIR, PINE_DRY=1
(stage only — used for testing). GOTCHA: running an unsigned exe off the
UNC share pops a one-time zone security prompt per PC (click Run); in a
headless shell that prompt HANGS invisibly — test from a local copy.
Runtime needs ONLY the electron package (package.json main=desktop/main.js,
zero runtime deps). #808: will-download in main.js now remembers saveDir
(config) and opens save dialogs there via item.setSaveDialogOptions —
main-process change, needs app relaunch, not F5.

**#827 (2026-08-18, c29abbd)**: the rebuild .cmd generator
(writeWindowsRebuildScript) uses the pine_box.exe recipe now — NO npm/node:
refresh source, Expand-Archive the runtime zip only if electron.exe missing,
path.txt, clear ELECTRON_RUN_AS_NODE, direct launch; fail path opens a
visible console pointing at pine_box.exe + the log. The OLD script collapsed
node_modules then ran npm install — its failure deleted the very exe its
fallback needed (how the operator got stranded). Desktop shortcut "Launch
Pine Box Desktop.cmd" now just starts pine_box.exe. NOTE: a running app
carries the OLD generator until relaunched once by pine_box.exe/shortcut.

**The stale-runner trap, generalized (#1148, 2026-08-27):** the RUNNING
shell executes `%LOCALAPPDATA%\PineBoxDesktop\runner\desktop\main.js`,
mirrored from the share only at launch — so a shell launched before a
main.js change behaves like the OLD code until relaunched. That is how the
kit export showed a blank white popup: the running shell predated #1147's
setWindowOpenHandler, so `window.open(zip url)` made a bare BrowserWindow.
When a popup/window behaves unlike current main.js, compare the runner
file's mtime to the share's first. Kit export now opens `/export/kit` (a
media_sign-passed progress page: three plexus clouds + byte bar, polls
`/api/export/kit/progress`, build runs in a thread via
`/api/export/kit/start`); main.js allows THAT same-origin path as an app
window — any future page that should open in-app instead of bouncing to
the external browser must be added to that same carve-out.

The PB-logo "rebuild" flow (main.js reconstituteDesktop) exits the app and
runs a detached `pinebox-rebuild.cmd` from `%APPDATA%\pinebox-desktop\`.
Fixed 2026-08-17: node spawn args must NOT be pre-quoted (cmd choked on the
"Ehm Ecks" space and the app never came back); the script relaunches via
electron.exe directly. Its log: `%APPDATA%\pinebox-desktop\pinebox-rebuild.log`.
See [spark-agent-environment](spark-agent-environment.md), [panel-ui-debugging](panel-ui-debugging.md).

**Relaunch from a tool session (verified 2026-09-06):** the running app
executes the runner mirror, so a renderer change (e.g. desktop/renderer/
lcd.js) is invisible until relaunch. What works from PowerShell:
`Get-Process electron | ? Path -like "*PineBoxDesktop*" | Stop-Process -Force`,
clear `ELECTRON_RUN_AS_NODE`, then `Start-Process "C:\Users\Ehm Ecks\Desktop\
Launch Pine Box Desktop.cmd"` - 30s later the runner file carries the new
code and six electron processes are back; the LCD producer auto-starts.
Other electron processes on this PC (C:\_tools\img_grab\sauce) are a
different app - never touch them. The LCD firmware never needs an update
for a screen-content change: it only displays the JPEG frames the app draws.
