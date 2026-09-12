// node tools/lcd-package-smoke.cjs <local electron.exe>
// Verify external PowerShell scripts can be materialized from a real app.asar.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {spawnSync} = require('node:child_process');
const asar = require('@electron/asar');
(async () => {
  const electron = process.argv[2];
  if (!electron) throw new Error('Pass a local Electron executable.');
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-lcd-package-'));
  const source = path.join(folder, 'source'); fs.mkdirSync(source);
  for (const name of ['lcd-runtime.cjs', 'lcd-serial.ps1', 'lcd-firmware-worker.ps1']) {
    fs.copyFileSync(path.join(__dirname, '../desktop', name), path.join(source, name));
  }
  fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify({name: 'pine-lcd-package-check', main: 'check.cjs'}));
  fs.writeFileSync(path.join(source, 'check.cjs'), `
const {app}=require('electron');const fs=require('fs');const path=require('path');const assert=require('assert');
const {scriptFile}=require('./lcd-runtime.cjs');app.whenReady().then(()=>{
try { assert(__dirname.includes('app.asar'));const files=['lcd-serial.ps1','lcd-firmware-worker.ps1'].map(name=>{
const file=scriptFile(name);assert(!file.includes('app.asar'));assert.equal(fs.readFileSync(file,'utf8'),fs.readFileSync(path.join(__dirname,name),'utf8'));return file;});
fs.writeFileSync(path.join(process.argv[2],'result.json'),JSON.stringify({ok:true,files}));app.exit(0);
}catch(error){console.error(error);app.exit(1);}});`);
  const archive = path.join(folder, 'app.asar'); await asar.createPackage(source, archive);
  const env = {...process.env}; delete env.ELECTRON_RUN_AS_NODE;
  const result = spawnSync(electron, [archive, folder], {env, windowsHide: true, encoding: 'utf8', timeout: 20000});
  if (result.status !== 0) throw new Error(result.error?.message || result.stderr || 'Packaged LCD check failed.');
  console.log(fs.readFileSync(path.join(folder, 'result.json'), 'utf8'));
})().catch((error) => { console.error(error); process.exitCode = 1; });
