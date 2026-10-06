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
const { contextBridge, clipboard, nativeImage, ipcRenderer } = require("electron");

// Only forward gestures; the remote page never receives desktop IPC access.
window.addEventListener('message', (event) => {
  if (event.source !== window || !event.data) return;
  if (event.data.type === 'pine-pip-count' && Number.isInteger(event.data.count) && event.data.count >= 0 && event.data.count < 100) {
    const slots = Array.isArray(event.data.slots) ? event.data.slots.slice(0, 100).map(slot => ({
      width: Math.max(0, Math.min(16384, Number(slot?.width) || 0)), height: Math.max(0, Math.min(16384, Number(slot?.height) || 0)), poster: String(slot?.poster || '').slice(0, 100000),
      label: String(slot?.label || 'Video').slice(0, 200), source: String(slot?.source || '').slice(0, 200)
    })) : [];
    ipcRenderer.sendToHost('pine-pip-count', event.data.count, slots); return;
  }
  if (event.data.type === 'pine-pip-time') {   /* [pip-playbar] the playing video's clock, or null when none plays */
    const t = event.data.time;
    ipcRenderer.sendToHost('pine-pip-time', t && typeof t === 'object' ? { at: Math.max(0, Number(t.at) || 0), dur: Math.max(0, Number(t.dur) || 0), playing: t.playing === true } : null); return;
  }
  if (event.data.type === 'pine-pip-voices' && Array.isArray(event.data.readings)) {
    ipcRenderer.sendToHost('pine-pip-voices', event.data.readings.slice(0, 16).map(r => ({ who: String(r?.who || '').slice(0, 100), level: Math.max(0, Math.min(1, Number(r?.level) || 0)), bars: Array.isArray(r?.bars) ? r.bars.slice(0, 24).map(n => Math.max(0, Math.min(1, Number(n) || 0))) : [] }))); return;
  }
  if (event.data.type !== 'pine-pip-gesture') return;
  if (event.data.action === 'expand' || event.data.action === 'menu') {
    ipcRenderer.sendToHost('pine-pip-gesture', event.data.action);
  }
});

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

/* #1330: THE PLAYHEAD, OUT OF THE WEBVIEW.
 *
 * The SCRIPT view runs in the desktop CHROME and picks its highlight by
 * matching a position against each row's from/until window. It wanted the
 * DJ voice element's currentTime, because that is the same coordinate as
 * those windows - both are offsets into one welded file - and #1278
 * measured what happens without it: the clock estimate was behind the
 * sound in 81.3% of samples, median -2.99s, with 29.8% of moves skips and
 * 20.5% backward.
 *
 * But it looked for that element with document.querySelectorAll('audio')
 * in the CHROME, and the chrome has exactly one <audio> in it
 * (desktopRadioPlayer). djVoiceAudio0/1 are created by the panel, which
 * is this document, inside a <webview> - a separate DOM the chrome cannot
 * reach. So soundingPlayer() returned null every time, not sometimes, and
 * the view silently ran on the estimator it was written to avoid. The
 * file guard (#1287) and the named-rows preference (#1294) both hang off
 * knowing the filename, so both were dead for the same reason.
 *
 * This is the smallest thing that fixes it: the position and the file,
 * posted to the host. No control, nothing readable by the page, and the
 * host treats a stale reading as no reading at all - so a bridge that
 * goes quiet degrades to the clock rather than freezing the mark. */
const PLAYHEAD_MS = 250;

function soundingVoice() {
  const all = document.querySelectorAll("audio");
  for (let i = 0; i < all.length; i += 1) {
    const a = all[i];
    if (!a || a.paused || a.ended) continue;
    if (!/djVoice/i.test(String(a.id || ""))) continue;
    if (!(Number(a.currentTime) > 0)) continue;
    return a;
  }
  return null;
}

let lastSent = "";

function reportPlayhead() {
  let msg = null;
  try {
    const a = soundingVoice();
    if (a) {
      const src = String(a.currentSrc || a.src || "").split("?")[0];
      msg = {
        id: String(a.id || ""),
        t: Number(a.currentTime) || 0,
        file: src.split("/").pop() || "",
        duration: Number(a.duration) || 0,
        rows: JSON.parse(a.dataset.pineRows || '[]'),
        at: Date.now()
      };
    }
  } catch (err) { msg = null; }
  // The isolated preload cannot read page globals. The panel stamps only
  // upcoming cue identities onto its audio element, alongside the live clip.
  try {
    const carrier = document.querySelector('audio[data-pine-cues]:not([data-pine-cues="[]"])');
    const pending = carrier ? JSON.parse(carrier.dataset.pineCues || '[]') : [];
    if (pending.length) {
      if (!msg) msg = {id: '', t: 0, file: '', duration: 0, rows: [], at: Date.now()};
      msg.pending = pending;
    }
  } catch (err) { /* a malformed cue hint never affects audio */ }
  /* Silence is a reading too: the host has to learn that nothing is
   * sounding, or the last line stays lit after the round has ended. */
  const key = msg ? msg.id + "|" + msg.file : "";
  if (!msg && !lastSent) return;
  lastSent = key;
  try { ipcRenderer.sendToHost("pine-playhead", msg); } catch (err) { /* the clock still covers it */ }
}

try {
  setInterval(reportPlayhead, PLAYHEAD_MS);
} catch (err) { /* without it the view falls back to the clock, as before */ }
