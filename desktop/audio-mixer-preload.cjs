const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('audioMixer', {
  get: () => ipcRenderer.invoke('audio-mixer:get'),
  set: values => ipcRenderer.invoke('audio-mixer:set', values),
  close: () => ipcRenderer.invoke('audio-mixer:close')
});
