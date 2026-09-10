/* 2026-09-10: THE CLIPBOARD, INSIDE THE PANEL'S OWN WEBVIEW.
 *
 * "I'm clicking them right now and I'm not able to copy this to my
 *  clipboard."
 *
 * #990 and #1047 both diagnosed this correctly and both fixed it in the
 * wrong window. They put copyText and copyImage on `pineDesktop` in
 * preload.js - which is the preload for the desktop CHROME, the file://
 * page that draws the rails and the tiles. The panel does not run there.
 * It runs in a <webview>, and a webview gets its OWN preload or none at
 * all; none of the five in index.html declared one. So inside the Gazette,
 * `window.pineDesktop` was undefined, and paperCopy's three roads played
 * out like this:
 *
 *   1. the desktop bridge   - absent, because this is the webview
 *   2. navigator.clipboard  - refused: the panel is plain http, so
 *                             window.isSecureContext is false
 *   3. the fallback         - download the PNG and copy the WORDS
 *
 * which is why the button appeared to do nothing: it was quietly taking
 * road three every time. The image never reached the clipboard because
 * nothing in that page could put it there.
 *
 * This is deliberately the SMALLEST possible bridge - the clipboard and
 * nothing else. The chrome's preload carries the whole agent API because
 * the chrome is trusted; the panel is a remote http document and gets two
 * functions that can only ever write to the operator's own clipboard.
 */
const { contextBridge, clipboard, nativeImage } = require("electron");

contextBridge.exposeInMainWorld("pineDesktop", {
  /* Named exactly as the chrome's, so every existing caller works with no
   * change: app.py already prefers this road and falls back on its own. */
  copyText: (text) => {
    try {
      clipboard.writeText(String(text == null ? "" : text));
      return true;
    } catch (err) {
      return false;
    }
  },
  copyImage: (dataUrl) => {
    try {
      const png = nativeImage.createFromDataURL(String(dataUrl || ""));
      if (!png || png.isEmpty()) return false;
      clipboard.writeImage(png);
      return true;
    } catch (err) {
      return false;
    }
  },
  /* So a page can tell a real bridge from a stub without trying a copy. */
  clipboardReady: () => true,
});
