param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference = 'Stop'
try {
  $task = Get-Content -LiteralPath $JobFile -Raw | ConvertFrom-Json
  $scripts = Join-Path $task.workspace 'system\scripts\device'
  . (Join-Path $scripts 'common.ps1')
  function Result($value) { Write-Output ('PINEJSON ' + ($value | ConvertTo-Json -Compress -Depth 8)) }
  if ($task.action -eq 'ports') {
    Result @{ ports = @(Get-SerialDevices | Where-Object { $_.IsEsp32 -and -not $_.IsReachy }) }
  } elseif ($task.action -eq 'identify' -or $task.action -eq 'usb') {
    $port = Find-Esp32Port -Port $task.port
    $tool = @(Ensure-EspTool)
    $info = Get-EspChipInfo -Tool $tool -Port $port
    if (-not $info.Chip -or -not $info.Mac) { throw 'The selected port did not identify as an ESP32 LCD.' }
    if ($task.action -eq 'identify') {
      Result @{ ok=$true; port=$port; chip=$info.Chip; chipId=$info.ChipId; mac=$info.Mac; sizeMB=[int]($info.SizeBytes / 1MB) }
    } else {
      if ($task.identity -and $info.Mac.ToLower() -ne $task.identity.ToLower()) { throw 'USB identity changed; installation stopped.' }
      # Preserve the current flash before the explicitly selected USB update.
      $backupDir = Join-Path (Split-Path $task.workspace) 'firmware-backups'
      New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
      $backupFile = Join-Path $backupDir (($info.Mac -replace ':','') + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bin')
      $backupOk = $false
      if ($info.ChipId -eq 'esp32') {
        # A single uninterrupted stub read avoids the legacy chunk reader's
        # reconnect downgrade to a very slow ROM transfer on CH340 CYD boards.
        $rest = @(Get-EspRest -Tool $tool)
        $backupLog = $backupFile + '.log'
        $previousErrors = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & $tool[0] @rest --port $port --baud 921600 read-flash 0 $info.SizeBytes $backupFile *> $backupLog
        $backupExit = $LASTEXITCODE; $ErrorActionPreference = $previousErrors
        $backupOk = $backupExit -eq 0 -and (Test-Path -LiteralPath $backupFile) -and (Get-Item -LiteralPath $backupFile).Length -eq $info.SizeBytes
        if (-not $backupOk) { Get-Content -LiteralPath $backupLog -Tail 12 | Write-Output }
      } else {
        $backupOk = Read-FlashImage -Tool $tool -Port $port -Size $info.SizeBytes -OutFile $backupFile -NoStub
      }
      if (-not $backupOk) { throw 'Flash backup failed; installation stopped.' }
      & (Join-Path $scripts 'build-flash.ps1') -Board $task.board -Port $port -FlashOnly
      if ($LASTEXITCODE -ne 0) { throw 'USB upload failed.' }
      Result @{ ok=$true; backup=$backupFile }
    }
  } elseif ($task.action -eq 'build') {
    & (Join-Path $scripts 'build-flash.ps1') -Board $task.board -Ssid $task.ssid -Pass $task.pass -BuildOnly
    if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed.' }
  } elseif ($task.action -eq 'ota') {
    $url = 'http://' + $task.host + '/status'
    $status = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5).Content
    if ($status -notmatch ('\bboard=' + [regex]::Escape($task.board) + '\b') -or $status -notmatch ('\bid=' + [regex]::Escape($task.identity) + '\b')) { throw 'LCD identity or board changed; Wi-Fi installation stopped.' }
    if ($status -match '\bota=0\b') { throw 'The running firmware has no OTA partition; use USB.' }
    $arduino = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp32\hardware\esp32'
    $espota = Get-ChildItem -LiteralPath $arduino -Filter espota.py -Recurse | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $espota) { throw 'ESP32 OTA uploader is missing. Build the firmware first.' }
    $ip = ([uri]$url).Host
    & python $espota.FullName -i $ip -p 3232 -f $task.binary
    if ($LASTEXITCODE -ne 0) { throw 'Wi-Fi upload failed; reconnect or use USB.' }
    Result @{ ok=$true }
  }
} catch { Write-Error $_; exit 1 }
