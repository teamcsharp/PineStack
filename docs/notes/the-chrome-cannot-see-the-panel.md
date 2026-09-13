---
name: the-chrome-cannot-see-the-panel
description: "The SCRIPT view's read position was never wrong - it was never there: the chrome's document holds one <audio>, and the panel's players live inside the <webview>, a DOM it cannot reach"
metadata:
  type: project
---

2026-09-13. **The SCRIPT view places its highlight by matching a position
against each row's `from`/`until` window.** Those are offsets into one
welded file, so the position must be the DJ voice element's `currentTime` -
not a clock. Measured over **308 samples**, the clock estimate was behind
the sound in **81.3%** of them, off by more than 3s in **58.5%**, median
**-2.99s**, with **29.8%** of its moves skips and **20.5%** backward.

**But it looked for that element with
`document.querySelectorAll('audio')` in the Electron CHROME**, whose
document holds exactly one `<audio>`: `desktopRadioPlayer`.
`djVoiceAudio0/1` are created by the panel, and the panel runs inside
`<webview id="radioFrame">` - a separate DOM the chrome cannot reach. So
the scan returned null **EVERY** time, not sometimes, and the view
silently ran on the estimator that three tickets existed to replace. The
file guard and the named-row preference both hang off knowing the
filename, so both were dead for the same reason.

**The tell is that it is not intermittent.** A timing bug wanders; this
was a clean **0%**. When a renderer feature works on the tablet and never
on the desktop, ask **which document it is running in** before measuring
anything else.

**The cure.** `webview-preload.js` posts `{id, t, file, duration}` every
250ms; `renderer.js` stamps it on arrival; `window.pinePlayhead()` returns
null once the stamp is older than 1200ms. **Stale must mean absent** - a
bridge that keeps handing back its last value pins the mark to one line
and looks like it is working, which is strictly worse than no bridge at
all.

**Deployment:** `webview-preload.js` is a PRELOAD. It needs a full desktop
relaunch, not a page reload.

See [pinebox-desktop-launcher](pinebox-desktop-launcher.md) (why a relaunch is the only way new code loads),
[panel-ui-debugging](panel-ui-debugging.md) (how to look at the panel from outside),
[script-ledger-and-the-reading-order](script-ledger-and-the-reading-order.md) (what the highlight is matching against),
[floor-and-paced-air](floor-and-paced-air.md) (the other family of leaked-element faults).
