# Linux handoff - 2026-09-24

## Repositories

- Station workspace: `\\10.89.1.246\ehm_eckx\pinevoice-stack\spark-agent`
- Station local branch: `master`; GitHub destination: `pinestack/main`
- PineTab workspace: `C:\_tools\pinebox-android\PineBoxKiosk`
- PineTab local branch: `main`; GitHub destination: `pinestack/android/main`
- Both repositories had no branches left unmerged into their current heads at handoff time.

## Runtime

- Station UI/API: `http://10.89.1.246:8096`
- Public stream: `http://10.89.1.246:8097`
- Station container restart: `ssh spark 'docker restart spark-agent'`
- Broadcast health: `curl http://10.89.1.246:8096/api/broadcast/health`
- H3 queue: `curl http://10.89.1.246:8096/api/comfy/workshop/parody-queue`

The PineApp and PineTab use the same station-served video editor and project
format. The Electron package also bundles the editor files as recovery assets.
The final 2026-09-24 deployment includes the searchable media bin, timeline
editing, source trimming, transitions, audio controls, overlay tracks, masks,
and SFX-ad export work.

## Builds

Build the Electron unpacked application from Windows (a mapped temporary drive
is required because the workspace is a UNC path):

```powershell
cmd.exe /d /s /c "pushd \\10.89.1.246\ehm_eckx\pinevoice-stack\spark-agent && call npm.cmd run desktop:pack"
```

The output is `dist-desktop/win-unpacked`. Linux packaging is available through
`npm run desktop:dist:linux` after rebooting into Linux.

Build, platform-sign, install, and verify PineTab:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' 'C:\_tools\pinebox-android\PineBoxKiosk\deploy.sh'
& 'C:\_tools\android-sdk\platform-tools\adb.exe' -s 10.89.1.154:5555 shell ime enable com.pinebox.kiosk/.audio.PineVoiceImeService
```

The platform signing material is local deployment state and is intentionally
not stored in Git.

## Tablet inspection

After reinstalling the APK, recreate the WebView debugging forward because the
application PID changes:

```powershell
$adb = 'C:\_tools\android-sdk\platform-tools\adb.exe'
$pid = (& $adb -s 10.89.1.154:5555 shell pidof com.pinebox.kiosk).Trim()
& $adb -s 10.89.1.154:5555 forward --remove tcp:9222
& $adb -s 10.89.1.154:5555 forward tcp:9222 "localabstract:webview_devtools_remote_$pid"
node tools/tablet-audio-inspect.cjs
```

The selected recognition service should be
`com.pinebox.kiosk/com.pinebox.kiosk.audio.PineRecognitionService`, and the
enabled voice IME should be
`com.pinebox.kiosk/.audio.PineVoiceImeService`.

## Operational expectations

- A music level of zero persists, keeps music silent, and pauses the record.
- Video/gallery playback ducks station audio and begins unmuted.
- The recovery control diagnoses the smallest failing layer first, including
  stream playback and wired-audio routing, before considering a server restart.
- Content gates and tinting remain disabled until the operator explicitly
  enables them through the orchestrator controls.
- H3 submissions always enter the durable queue; active and historical render
  progress remain visible without a blocking dialog.
- Broadcast exports target `\\10.89.1.125\QuickSwap\PineBoxRecordings` when
  the recording-folder destination is selected.
