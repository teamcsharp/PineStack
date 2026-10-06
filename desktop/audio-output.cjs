const { execFile } = require('node:child_process');
const path = require('node:path');
function inspect(repair = false, appProcessId = process.pid) {
  if (process.platform !== 'win32') return Promise.resolve({ ok: false, say: 'Check the app volume in your operating system sound settings.', changed: [], peak: 0 });
  return new Promise(resolve => {
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path.join(__dirname, 'audio-output.ps1'), '-AppProcessId', String(appProcessId), ...(repair ? ['-Repair'] : [])],
      { windowsHide: true, timeout: 20000, maxBuffer: 512 * 1024 }, (error, stdout) => {
        try { const result = JSON.parse(String(stdout).trim()); resolve(result); }
        catch { resolve({ ok: false, say: error?.message || 'Windows audio diagnostics did not return a result.', changed: [], peak: 0 }); }
      });
  });
}
module.exports = { inspect };