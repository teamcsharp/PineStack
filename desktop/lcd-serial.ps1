param([Parameter(Mandatory=$true)][string]$Port)
$ErrorActionPreference = 'Stop'
# Windows PowerShell's synchronized Console reader implements ReadLineAsync
# synchronously. Read stdin on a dedicated background thread so awaiting the
# next command never prevents draining the current serial acknowledgment.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Concurrent;
using System.Threading;
public static class PineLcdInput {
  public static readonly ConcurrentQueue<string> Lines = new ConcurrentQueue<string>();
  public static volatile bool Ended;
  public static void Start() {
    var reader = new Thread(() => { try { string line; while ((line = Console.ReadLine()) != null) Lines.Enqueue(line); } finally { Ended = true; } });
    reader.IsBackground = true; reader.Start();
  }
}
'@
$serial = [System.IO.Ports.SerialPort]::new($Port, 921600, 'None', 8, 'One')
$serial.DtrEnable = $false; $serial.RtsEnable = $false
$serial.WriteTimeout = 4000; $serial.ReadTimeout = 50
try {
  $serial.Open()
  Write-Output '{"ready":true}'
  [PineLcdInput]::Start()
  $buffer = ''
  while ($serial.IsOpen) {
    if ($serial.BytesToRead -gt 0) {
      $buffer += $serial.ReadExisting()
      while (($newline = $buffer.IndexOf("`n")) -ge 0) {
        $line = $buffer.Substring(0, $newline).TrimEnd("`r")
        $buffer = $buffer.Substring($newline + 1)
        if ($line -match '^(QINFO |QACK |QEVT |QUANTA-SCREEN )') { Write-Output (@{line=$line} | ConvertTo-Json -Compress) }
      }
      if ($buffer.Length -gt 8192) { $buffer = '' }
    }
    $inputLine = ''
    if ([PineLcdInput]::Lines.TryDequeue([ref]$inputLine)) {
      $message = $inputLine | ConvertFrom-Json
      if ($message.close) { break }
      if ($message.jpeg) {
        $bytes = [Convert]::FromBase64String($message.jpeg)
        $serial.WriteLine('QIMG ' + $bytes.Length)
        $serial.Write($bytes, 0, $bytes.Length)
      } elseif ($message.command) { $serial.WriteLine([string]$message.command) }
    } elseif ([PineLcdInput]::Ended) { break }
    Start-Sleep -Milliseconds 8
  }
} catch { Write-Output (@{error=$_.Exception.Message} | ConvertTo-Json -Compress); exit 1 }
finally { if ($serial.IsOpen) { $serial.Close() }; $serial.Dispose() }
