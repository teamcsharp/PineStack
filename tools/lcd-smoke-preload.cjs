// Used only by the explicit, hidden physical LCD test process.
const {contextBridge, ipcRenderer} = require('electron');
const call = (name, ...args) => ipcRenderer.invoke('lcd-smoke', name, ...args);
contextBridge.exposeInMainWorld('pineDesktop', Object.fromEntries([
  'lcdState', 'lcdConfigure', 'lcdFrame', 'lcdEvents', 'lcdControl',
  'lcdDisplayMode', 'lcdPaperImage', 'get',
].map(name => [name, (...args) => call(name, ...args)])));
