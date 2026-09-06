const { contextBridge, ipcRenderer, clipboard, nativeImage } = require("electron");

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
  openExternal: (url) => ipcRenderer.invoke("open:external", url),
  /* #990: THE COPY BUTTON DID NOTHING.
   *
   * The window is loaded from file://, which is not a secure context, so
   * navigator.clipboard is undefined there - and both copy sites called
   * it with an empty rejection handler, so the click failed in complete
   * silence. Electron's own clipboard has no such restriction and is
   * available right here in the preload. */
  copyText: (text) => {
    try {
      clipboard.writeText(String(text == null ? "" : text));
      return true;
    } catch (err) {
      return false;
    }
  },
  /* #1047: THE COPY BUTTON HAS TO COPY A PICTURE.
   *
   * "when i click copy, I want to copy all the pages of the paper as an
   *  image to clipboard allowing me to paste it anywhere."
   *
   * The Gazette window stitches every page into one tall PNG and hands it
   * here as a data URL. navigator.clipboard.write is refused on a file://
   * page exactly as writeText was in #990; Electron's clipboard is not,
   * and nativeImage reads a PNG data URL directly. */
  copyImage: (dataUrl) => {
    try {
      const png = nativeImage.createFromDataURL(String(dataUrl || ""));
      if (!png || png.isEmpty()) return false;
      clipboard.writeImage(png);
      return true;
    } catch (err) {
      return false;
    }
  }
});
