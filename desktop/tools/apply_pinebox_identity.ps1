<#
.SYNOPSIS
  Give Pine Box Desktop's electron.exe the Pine Box name and icon, IN PLACE.

.DESCRIPTION
  Windows names and draws an app from its executable's own resources in the
  places no window can reach: Task Manager (FileDescription + icon), the
  volume mixer (an audio session with no display name falls back to the
  exe's FileDescription and icon - Chromium's audio service never sets one),
  the microphone/camera "in use" notices, the firewall prompt, and every
  window that does not pass its own icon. electron.exe says "Electron" and
  wears the atom in all of them.

  This rewrites the resources of the SAME file: the first icon group
  becomes the Pine Box mark and FileDescription / ProductName become
  "Pine Box". The file is never renamed or moved. That matters: Windows keeps
  each app's volume per executable PATH (HKCU\...\Audio\PolicyConfig\
  PropertyStore, keyed "<endpoint>|<exe path>"), so a new path would start at
  100 - and this operator keeps Pine Box at 12 on headphones.

  Nothing else is changed: CompanyName, LegalCopyright, versions and
  OriginalFilename stay Electron's.

  The same script is the tool pine_box.exe and the in-app rebuild call on
  every PC, so it is idempotent and quiet when there is nothing to do.

  Exit codes: 0 applied (now or already)   1 failed (restored if it could)
              3 refused: that electron.exe is running
              4 prerequisites missing (rcedit or icon not found, or the
                rcedit binary is not the verified one)

.PARAMETER Exe       electron.exe to change. Default: this PC's runner.
.PARAMETER Icon      .ico to embed. Default: pinebox-exe.ico beside this
                     script, in ..\assets, or in the runner's desktop\assets.
.PARAMETER RcEdit    rcedit-x64.exe. Default: beside this script, then
                     %LOCALAPPDATA%\PineBoxDesktop, then the stack's
                     desktop-runtime folder (copied locally first).
.PARAMETER NoBackup  Skip the one-time copy of the original exe (the
                     unattended roads use this: the runtime zip on the share
                     is the pristine copy).
.PARAMETER WaitSeconds  If the exe is still in use, keep checking for this
                     long before refusing (the rebuild road passes 30: its
                     own `timeout /t 3` returns at once when spawned with no
                     console input, so Electron may still be closing).
.PARAMETER Restore   Put the original back from the backup, then stop.
.PARAMETER WhatIf    Say what would change and change nothing.
.PARAMETER Quiet     Fewer lines (for the launcher's log).

  rcedit provenance: electron/rcedit v2.0.0 release asset rcedit-x64.exe,
  1,360,384 bytes, SHA-256 3e7801db1a5edbec91b49a24a094aad776cb4515488ea5a4ca2289c400eade2a.
  Byte-identical to bin/rcedit-x64.exe in npm rcedit@5.0.0 and @5.0.2
  (both tarballs match the registry's sha512 integrity). Pinned below; any
  other binary is refused.
#>
[CmdletBinding()]
param(
  [string]$Exe = (Join-Path $env:LOCALAPPDATA 'PineBoxDesktop\runner\node_modules\electron\dist\electron.exe'),
  [string]$Icon = '',
  [string]$RcEdit = '',
  [string]$BackupDir = (Join-Path $env:LOCALAPPDATA 'PineBoxDesktop\identity-backup'),
  [switch]$NoBackup,
  [int]$WaitSeconds = 0,
  [switch]$Restore,
  [switch]$WhatIf,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$AppName = 'Pine Box'
$RcEditSha256 = '3E7801DB1A5EDBEC91B49A24A094AAD776CB4515488EA5A4CA2289C400EADE2A'
$Stack = $env:PINE_STACK
if (-not $Stack) { $Stack = '\\10.89.1.246\ehm_eckx\pinevoice-stack' }

function Say([string]$line) { Write-Output "[identity] $line" }
function Detail([string]$line) { if (-not $Quiet) { Write-Output "[identity]   $line" } }

# --- a small read-only view of an exe's icon resources -------------------
if (-not ('PineIdentity.Res' -as [type])) {
  Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace PineIdentity {
  public class Entry { public int Width; public int Bytes; public int Id; }
  public static class Res {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr LoadLibraryEx(string p, IntPtr f, uint flags);
    [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr h);
    delegate bool NameProc(IntPtr h, IntPtr t, IntPtr n, IntPtr p);
    delegate bool LangProc(IntPtr h, IntPtr t, IntPtr n, ushort l, IntPtr p);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumResourceNames(IntPtr h, IntPtr t, NameProc cb, IntPtr p);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumResourceLanguages(IntPtr h, IntPtr t, IntPtr n, LangProc cb, IntPtr p);
    [DllImport("kernel32.dll")] static extern IntPtr FindResourceEx(IntPtr h, IntPtr t, IntPtr n, ushort l);
    [DllImport("kernel32.dll")] static extern IntPtr LoadResource(IntPtr h, IntPtr r);
    [DllImport("kernel32.dll")] static extern IntPtr LockResource(IntPtr d);
    [DllImport("kernel32.dll")] static extern uint SizeofResource(IntPtr h, IntPtr r);
    static byte[] Raw(IntPtr h, IntPtr t, IntPtr n) {
      ushort lang = 0; bool any = false;
      EnumResourceLanguages(h, t, n, delegate (IntPtr m1, IntPtr m2, IntPtr m3, ushort l, IntPtr m4) { if (!any) { lang = l; any = true; } return true; }, IntPtr.Zero);
      if (!any) return null;
      IntPtr r = FindResourceEx(h, t, n, lang);
      if (r == IntPtr.Zero) return null;
      uint size = SizeofResource(h, r);
      byte[] b = new byte[size];
      Marshal.Copy(LockResource(LoadResource(h, r)), b, 0, (int)size);
      return b;
    }
    // The FIRST icon group - the one Windows shows for the file - and, for
    // each entry, the RT_ICON bytes it points at.
    public static List<Entry> FirstGroup(string path, List<byte[]> blobs) {
      IntPtr h = LoadLibraryEx(path, IntPtr.Zero, 0x2 | 0x20);
      if (h == IntPtr.Zero) throw new Exception("cannot open " + path + " (" + Marshal.GetLastWin32Error() + ")");
      try {
        long first = -1; string firstName = null;
        EnumResourceNames(h, (IntPtr)14, delegate (IntPtr m1, IntPtr m2, IntPtr rn, IntPtr m4) {
          long v = rn.ToInt64();
          if ((v >> 16) == 0) first = v; else firstName = Marshal.PtrToStringUni(rn);
          return false;
        }, IntPtr.Zero);
        IntPtr name;
        if (first >= 0) name = (IntPtr)first;
        else if (firstName != null) name = Marshal.StringToHGlobalUni(firstName);
        else return new List<Entry>();
        byte[] g = Raw(h, (IntPtr)14, name);
        List<Entry> list = new List<Entry>();
        int count = BitConverter.ToUInt16(g, 4);
        for (int i = 0; i < count; i++) {
          int o = 6 + 14 * i;
          Entry e = new Entry();
          e.Width = g[o] == 0 ? 256 : g[o];
          e.Bytes = BitConverter.ToInt32(g, o + 8);
          e.Id = BitConverter.ToUInt16(g, o + 12);
          list.Add(e);
          blobs.Add(Raw(h, (IntPtr)3, (IntPtr)e.Id));
        }
        return list;
      } finally { FreeLibrary(h); }
    }
  }
  public static class Paths {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern uint GetLongPathName(string s, System.Text.StringBuilder l, uint n);
    // C:\Users\EHMECK~1\... and C:\Users\Ehm Ecks\... are one file.
    public static string Long(string p) {
      System.Text.StringBuilder sb = new System.Text.StringBuilder(1024);
      uint n = GetLongPathName(p, sb, (uint)sb.Capacity);
      return (n > 0 && n < sb.Capacity) ? sb.ToString() : p;
    }
  }
  public static class Shell {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern void SHChangeNotify(int e, uint f, string a, IntPtr b);
    [DllImport("shell32.dll")]
    static extern void SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);
    // SHCNE_UPDATEITEM for the file itself, then SHCNE_ASSOCCHANGED: the
    // documented "icons may have changed" signal. Neither touches any
    // per-app audio setting.
    public static void Refresh(string path) {
      SHChangeNotify(0x00002000, 0x0005, path, IntPtr.Zero);
      SHChangeNotify(0x08000000, 0x0000, IntPtr.Zero, IntPtr.Zero);
    }
  }
}
'@
}

function Read-IcoFrames([string]$path) {
  $b = [IO.File]::ReadAllBytes($path)
  if ([BitConverter]::ToUInt16($b, 2) -ne 1) { throw "$path is not an .ico" }
  $n = [BitConverter]::ToUInt16($b, 4); $list = @()
  for ($i = 0; $i -lt $n; $i++) {
    $o = 6 + 16 * $i
    $w = [int]$b[$o]; if ($w -eq 0) { $w = 256 }
    $size = [BitConverter]::ToUInt32($b, $o + 8); $off = [BitConverter]::ToUInt32($b, $o + 12)
    $blob = New-Object byte[] $size; [Array]::Copy($b, $off, $blob, 0, $size)
    $list += ,@{ Width = $w; Blob = $blob }
  }
  return ,$list
}

function Get-State([string]$exePath, $frames) {
  $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($exePath)
  $blobs = New-Object 'System.Collections.Generic.List[byte[]]'
  $entries = [PineIdentity.Res]::FirstGroup($exePath, $blobs)
  $iconOk = ($entries.Count -eq $frames.Count)
  $sizes = @()
  for ($i = 0; $i -lt $entries.Count; $i++) {
    $sizes += $entries[$i].Width
    if (-not $iconOk) { continue }
    $want = $frames[$i].Blob; $got = $blobs[$i]
    if ($entries[$i].Width -ne $frames[$i].Width -or $got -eq $null -or
        $got.Length -ne $want.Length -or $entries[$i].Bytes -ne $got.Length -or
        [Convert]::ToBase64String($got) -ne [Convert]::ToBase64String($want)) { $iconOk = $false }
  }
  $namesOk = ($vi.FileDescription -eq $AppName -and $vi.ProductName -eq $AppName)
  return @{ Vi = $vi; IconOk = $iconOk; NamesOk = $namesOk; Sizes = ($sizes -join ',') }
}

function Show-State([string]$label, $s) {
  Detail ("{0}: FileDescription='{1}' ProductName='{2}' FileVersion={3} Company='{4}'" -f $label, $s.Vi.FileDescription, $s.Vi.ProductName, $s.Vi.FileVersion, $s.Vi.CompanyName)
  Detail ("{0}: icon group 1 = [{1}] px, Pine Box mark: {2}" -f $label, $s.Sizes, $(if ($s.IconOk) { 'yes' } else { 'no' }))
}

function Test-InUse([string]$exePath) {
  $full = [PineIdentity.Paths]::Long([IO.Path]::GetFullPath($exePath))
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and ([PineIdentity.Paths]::Long([IO.Path]::GetFullPath($_.ExecutablePath)) -ieq $full) })
  if ($procs.Count -gt 0) { return "running as PID " + (($procs | ForEach-Object { $_.ProcessId }) -join ', ') }
  # The definitive test: a mapped image cannot be opened for writing.
  try { $fs = [IO.File]::Open($full, 'Open', 'ReadWrite', 'ReadWrite'); $fs.Close(); return $null }
  catch { return "locked (" + $_.Exception.Message + ")" }
}

# Native tools run through ProcessStartInfo, not `& tool 2>&1`: in Windows
# PowerShell 5.1 a stderr line under ErrorActionPreference=Stop becomes a
# terminating error half way through the run.
function Invoke-Tool([string]$file, [string[]]$argv, [hashtable]$envAdd, [int]$timeoutMs) {
  $quoted = ($argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
  $psi = New-Object Diagnostics.ProcessStartInfo($file, $quoted)
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  if ($envAdd) { foreach ($k in $envAdd.Keys) { $psi.EnvironmentVariables[$k] = $envAdd[$k] } }
  $p = [Diagnostics.Process]::Start($psi)
  $errTask = $p.StandardError.ReadToEndAsync()
  $stdout = $p.StandardOutput.ReadToEnd()
  if (-not $p.WaitForExit($timeoutMs)) { try { $p.Kill() } catch {}; return @{ Code = -1; Out = $stdout; Err = 'timed out' } }
  return @{ Code = $p.ExitCode; Out = $stdout; Err = $errTask.Result }
}

function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }

# --- resolve inputs -------------------------------------------------------
if (-not (Test-Path -LiteralPath $Exe)) { Say "no electron.exe at $Exe"; exit 4 }
$Exe = [PineIdentity.Paths]::Long((Resolve-Path -LiteralPath $Exe).Path)
# <runner>\node_modules\electron\dist\electron.exe -> <runner>\desktop\assets
$runnerAssets = Join-Path (Split-Path (Split-Path (Split-Path (Split-Path $Exe)))) 'desktop\assets'
if (-not $Icon) {
  foreach ($c in @((Join-Path $PSScriptRoot 'pinebox-exe.ico'), (Join-Path $PSScriptRoot 'icon\pinebox-exe.ico'),
                   (Join-Path $PSScriptRoot '..\assets\pinebox-exe.ico'), (Join-Path $runnerAssets 'pinebox-exe.ico'))) {
    if (Test-Path -LiteralPath $c) { $Icon = (Resolve-Path -LiteralPath $c).Path; break }
  }
}
if (-not $Restore -and (-not $Icon -or -not (Test-Path -LiteralPath $Icon))) { Say "no pinebox-exe.ico found (pass -Icon)"; exit 4 }

if (-not $Restore -and -not $RcEdit) {
  $local = Join-Path $env:LOCALAPPDATA 'PineBoxDesktop\rcedit-x64.exe'
  foreach ($c in @((Join-Path $PSScriptRoot 'rcedit-x64.exe'), $local)) {
    if ((Test-Path -LiteralPath $c) -and ((Get-Sha256 $c) -eq $RcEditSha256)) { $RcEdit = $c; break }
  }
  if (-not $RcEdit) {
    $shared = Join-Path $Stack 'desktop-runtime\rcedit-x64.exe'
    if (Test-Path -LiteralPath $shared) {
      # Copied local first: an exe run off the share can raise the zone prompt.
      New-Item -ItemType Directory -Force (Split-Path $local) | Out-Null
      Copy-Item -LiteralPath $shared -Destination $local -Force
      $RcEdit = $local
    }
  }
}
if (-not $Restore) {
  if (-not $RcEdit -or -not (Test-Path -LiteralPath $RcEdit)) { Say "rcedit-x64.exe not found (pass -RcEdit)"; exit 4 }
  $h = Get-Sha256 $RcEdit
  if ($h -ne $RcEditSha256) { Say "refusing $RcEdit : SHA-256 $h is not the verified rcedit v2.0.0"; exit 4 }
}

Say "exe:  $Exe"
if (-not $Restore) { Detail "icon: $Icon"; Detail "rcedit: $RcEdit (SHA-256 verified)" }

$frames = $null
if ($Icon) { $frames = Read-IcoFrames $Icon }

# --- restore ----------------------------------------------------------------
if ($Restore) {
  $orig = Get-ChildItem -LiteralPath $BackupDir -Filter 'electron.exe.*.orig' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -First 1
  if (-not $orig) { Say "no backup in $BackupDir"; exit 1 }
  $why = Test-InUse $Exe
  if ($why) { Say "refusing: that electron.exe is $why. Close Pine Box first."; exit 3 }
  if ($WhatIf) { Say "would copy $($orig.FullName) back over $Exe"; exit 0 }
  Copy-Item -LiteralPath $orig.FullName -Destination $Exe -Force
  $want = ($orig.Name -split '\.')[2]
  $got = (Get-Sha256 $Exe).Substring(0, 12)
  if ($want -and $got -ne $want.ToUpper()) { Say "restored file hash $got does not match backup name $want"; exit 1 }
  [PineIdentity.Shell]::Refresh($Exe)
  Say "restored the original electron.exe from $($orig.Name)"
  exit 0
}

# --- what is there now ------------------------------------------------------
$before = Get-State $Exe $frames
Show-State 'now' $before
if ($before.IconOk -and $before.NamesOk) {
  Say "already Pine Box - nothing to do"
  exit 0
}

$plan = @()
if (-not $before.IconOk) { $plan += "icon group 1 -> Pine Box mark ($($frames.Count) sizes: $(($frames | ForEach-Object { $_.Width }) -join ','))" }
if ($before.Vi.FileDescription -ne $AppName) { $plan += "FileDescription '$($before.Vi.FileDescription)' -> '$AppName'" }
if ($before.Vi.ProductName -ne $AppName) { $plan += "ProductName '$($before.Vi.ProductName)' -> '$AppName'" }
foreach ($p in $plan) { Say "will change: $p" }

$why = Test-InUse $Exe
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ($why -and -not $WhatIf -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500; $why = Test-InUse $Exe }
if ($why) { Say "refusing: that electron.exe is $why. Close Pine Box first; nothing was changed."; exit 3 }

if ($WhatIf) { Say "WhatIf: nothing changed"; exit 0 }

# --- back up once -------------------------------------------------------------
$backup = $null
if (-not $NoBackup) {
  New-Item -ItemType Directory -Force $BackupDir | Out-Null
  $sha = Get-Sha256 $Exe
  $backup = Join-Path $BackupDir ("electron.exe.{0}.orig" -f $sha.Substring(0, 12))
  if ((Test-Path -LiteralPath $backup) -and ((Get-Sha256 $backup) -eq $sha)) {
    Detail "backup already present: $backup"
  } else {
    Copy-Item -LiteralPath $Exe -Destination $backup -Force
    if ((Get-Sha256 $backup) -ne $sha) { Say "backup copy does not verify; nothing was changed"; exit 1 }
    Set-Content -LiteralPath ($backup + '.sha256') -Value "$sha  electron.exe  (from $Exe)" -Encoding ASCII
    Say "backed up the original to $backup"
  }
}

# --- apply ----------------------------------------------------------------------
$r = Invoke-Tool $RcEdit @($Exe, '--set-icon', $Icon, '--set-version-string', 'FileDescription', $AppName,
                           '--set-version-string', 'ProductName', $AppName) $null 120000
$rc = $r.Code
foreach ($l in (("$($r.Out)`n$($r.Err)") -split "`r?`n")) { if ($l.Trim()) { Detail "rcedit: $l" } }

$after = $null
try { $after = Get-State $Exe $frames } catch { Detail "could not read back: $($_.Exception.Message)" }
$good = ($rc -eq 0) -and $after -and $after.IconOk -and $after.NamesOk -and
        ($after.Vi.FileVersion -eq $before.Vi.FileVersion) -and ($after.Vi.CompanyName -eq $before.Vi.CompanyName)

# The patched binary must still run. ELECTRON_RUN_AS_NODE makes it plain
# Node: no window, no Chromium, no audio session - it prints and exits.
if ($good) {
  $t = Invoke-Tool $Exe @('-e', 'process.stdout.write(process.versions.electron)') @{ ELECTRON_RUN_AS_NODE = '1' } 30000
  $ver = "$($t.Out)".Trim()
  if ($t.Code -ne 0 -or ($ver -ne $before.Vi.ProductVersion -and $ver -ne $before.Vi.FileVersion)) {
    Detail "smoke test failed: exit $($t.Code), printed '$ver' $($t.Err)"; $good = $false
  } else { Detail "smoke test: the patched exe runs (Electron $ver)" }
}

if (-not $good) {
  Say "the change did not verify (rcedit exit $rc)"
  if ($backup -and (Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $backup -Destination $Exe -Force
    Say "restored the original from $backup"
  }
  exit 1
}

Show-State 'after' $after
[PineIdentity.Shell]::Refresh($Exe)
Detail "asked the shell to repaint this file's icon (SHCNE_UPDATEITEM + SHCNE_ASSOCCHANGED)"
Say "done: electron.exe now reads '$AppName' and wears the Pine Box mark, at the same path"
exit 0
