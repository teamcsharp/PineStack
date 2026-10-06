/* Keep the runner current without interrupting the players already on air. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');

async function stageRendererUpdates({ source, mirror, changed, window, pending = new Set(),
  fsImpl = fs.promises, platform = process.platform, pid = process.pid, log = console.log }) {
  const sourcePath = path.resolve(source), mirrorPath = path.resolve(mirror);
  const sameDirectory = sourcePath === mirrorPath
    || (platform === 'win32' && sourcePath.toLowerCase() === mirrorPath.toLowerCase());
  const landed = [];
  for (const name of changed) {
    const staged = path.join(mirror, name + '.pine-hot-' + pid);
    try {
      if (!sameDirectory) {
        await fsImpl.copyFile(path.join(source, name), staged);
        await fsImpl.rename(staged, path.join(mirror, name));
      }
      landed.push(name);
    } catch (error) {
      log('[hot] could not copy ' + name + ': ' + error.message);
      await fsImpl.unlink(staged).catch(() => {});
    }
  }
  const scripts = landed.filter(name => !/\.css$/i.test(name));
  scripts.forEach(name => pending.add(name));
  if (scripts.length) {
    log('[hot] ' + scripts.join(', ') + ' - staged for an explicit reload; '
      + pending.size + ' file(s) pending, live players continue');
  }
  const styles = landed.filter(name => /\.css$/i.test(name));
  if (!styles.length || !window || window.isDestroyed()) return landed;
  const code = `(function(names){names.forEach(function(name){
    document.querySelectorAll('link[rel=stylesheet]').forEach(function(link){
      var href=String(link.getAttribute('href')||'');
      if(href.split('?')[0].split('/').pop()===name)
        link.setAttribute('href',href.split('?')[0]+'?hot='+Date.now());
    });
  });})(${JSON.stringify(styles)});`;
  try {
    await window.webContents.executeJavaScript(code, false);
    log('[hot] ' + styles.join(', ') + ' - swapped');
  } catch (error) {
    log('[hot] styles copied for the next reload; live swap failed: ' + error.message);
  }
  return landed;
}
module.exports = { stageRendererUpdates };