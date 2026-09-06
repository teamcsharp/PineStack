const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
// External PowerShell cannot read Electron's virtual app.asar filesystem.
// Electron reads the packaged script and materializes it for the worker.
function scriptFile(name) {
  if (!['lcd-serial.ps1', 'lcd-firmware-worker.ps1'].includes(name)) throw new Error('Unknown LCD worker.');
  const folder = path.join(os.tmpdir(), 'pine-box-lcd-workers');
  fs.mkdirSync(folder, {recursive: true});
  const file = path.join(folder, name);
  fs.writeFileSync(file, fs.readFileSync(path.join(__dirname, name)));
  return file;
}
module.exports = {scriptFile};
