const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("pineDesktop", {
  readConfig: () => ipcRenderer.invoke("config:read"),
  writeConfig: (cfg) => ipcRenderer.invoke("config:write", cfg),
  startBackend: () => ipcRenderer.invoke("backend:start"),
  stopBackend: () => ipcRenderer.invoke("backend:stop"),
  setupBackend: () => ipcRenderer.invoke("backend:setup"),
  reconstituteDesktop: () => ipcRenderer.invoke("desktop:reconstitute"),
  backendLog: () => ipcRenderer.invoke("backend:log"),
  onBackendLog: (callback) => ipcRenderer.on("backend-log", (_event, line) => callback(line)),
  onSupportProgress: (callback) => ipcRenderer.on("support-progress", (_event, data) => callback(data)),
  discoverKey: () => ipcRenderer.invoke("agent:discover-key"),
  get: (route) => ipcRenderer.invoke("agent:get", route),
  post: (route, body) => ipcRenderer.invoke("agent:post", route, body),
  put: (route, body) => ipcRenderer.invoke("agent:put", route, body),
  del: (route, body) => ipcRenderer.invoke("agent:del", route, body),
  openExternal: (url) => ipcRenderer.invoke("open:external", url)
});
