const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('stationTroubleshooter', {
  state: () => ipcRenderer.invoke('station-troubleshooter:state'),
  run: action => ipcRenderer.invoke('station-troubleshooter:run', action),
  onState: callback => ipcRenderer.on('station-troubleshooter:state', (_event, state) => callback(state))
});
