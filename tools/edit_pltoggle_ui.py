"""[pltoggle] pinelive.js / pinelive.css: three switches in the PineLive header.

  PineCam to live  = the Picture section's "Video to Tailscale listeners"
                     (settings.tailscale_video; off blocks the public picture,
                     the camera, the local preview and the house keep it)
  Pine Live        = the Event section's "MX Live event" - the [plair] switch
                     IS the set: on arms (event mode), off ends it (two taps)
  Album recording  = the Recording section's switch (settings.record),
                     remembered server-side for the next set

Each header switch and its section twin share ONE flip function and ONE
model value. The detection box keeps the header's middle while the row
leaves it room; when a running set's clock crowds it, it steps into the row.

Apply to BOTH copies (desktop/renderer and the kiosk's pine-views):
  python edit_pltoggle_ui.py [--check|--apply] pinelive.js pinelive.css [...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pltoggle_lib  # noqa: E402

JS = [
    # the Event section's switch hands its flip to flipSet (must run before
    # the helper block goes in: the block must not duplicate this anchor)
    ("js.event_switch",
     "      if (!next && model.state && model.state.armed) {\n"
     "        confirmTap('disable', node, 'Tap again to end the set and switch MX Live off', function () {\n"
     "          act('/api/pinelive/event', {enabled: false}, node);\n"
     "        });\n"
     "        return;\n"
     "      }\n"
     "      /* [plair] the switch IS the set: on arms it now, on the chosen road */\n"
     "      var st0 = model.state || {};\n"
     "      var road0 = ui.prefs.road || (st0.source && st0.source.kind) || 'usb';\n"
     "      var body0 = {enabled: next, source: road0};\n"
     "      if (road0 === 'usb' && model.settings && model.settings.device) body0.device = model.settings.device;\n"
     "      act('/api/pinelive/event', body0, node);\n",
     "      /* [plair] the switch IS the set; [pltoggle] one owner with the header's Pine Live */\n"
     "      flipSet(next, node);\n",
     "one owner with the header's Pine Live */"),

    ("js.picture_switch",
     "      /* immediate: the switch moves now, the station stops the picture now,\n"
     "       * and the answer's state puts it right if it refused */\n"
     "      ts.set(next);\n"
     "      if (!model.settings) model.settings = {};\n"
     "      model.settings.tailscale_video = next;\n"
     "      if (model.state && model.state.picture) model.state.picture.tailscale_video = next;\n"
     "      act('/api/pinelive/settings', {tailscale_video: next}, node);\n",
     "      /* [pltoggle] one owner with the header's PineCam to live */\n"
     "      ts.set(next);\n"
     "      flipTailscale(next, node);\n",
     "one owner with the header's PineCam to live */"),

    ("js.record_switch",
     "    var rec = toggle('Write the cuts', 'Every cut is two files: the live input alone in stereo, and the full broadcast mix.', function (next) {\n"
     "      saveSetting('record', next);\n",
     "    var rec = toggle('Album recording', 'Every cut is two files: the live input alone in stereo, and the full broadcast mix. Off: the set still airs and takes the music; nothing is written. Remembered for the next set.', function (next) {\n"
     "      flipAlbum(next);                  /* [pltoggle] one owner with the header's Album recording */\n",
     "one owner with the header's Album recording */"),

    ("js.record_paint",
     "    parts.rec.set(s.record !== undefined ? !!s.record : r.on !== false);\n",
     "    parts.rec.set(albumOn());          /* [pltoggle] */\n",
     "parts.rec.set(albumOn());          /* [pltoggle] */"),

    ("js.record_now",
     "    if (st.armed && r.cut_index) {\n",
     "    if (st.armed && r.cut_index && albumOn()) {   /* [pltoggle] */\n",
     "r.cut_index && albumOn()) {   /* [pltoggle] */"),

    ("js.record_now_off",
     "      setText(parts.nowWords, st.armed ? 'Starting the first cut...' : 'No set running');\n",
     "      setText(parts.nowWords, !st.armed ? 'No set running' : albumOn() ? 'Starting the first cut...'\n"
     "        : 'Album recording is off - the set airs, nothing is written');   /* [pltoggle] */\n",
     "'Album recording is off - the set airs, nothing is written');   /* [pltoggle] */"),

    ("js.head_row",
     "    head.appendChild(ui.phasePill);\n",
     "    head.appendChild(ui.phasePill);\n"
     "    /* [pltoggle] slots 1, 2 and one more: the header's three switches */\n"
     "    var hswRow = make('div', 'pl-hsw-row');\n"
     "    ui.hsw = {row: hswRow,\n"
     "      cam: headSwitch(hswRow, 'pl-hsw-cam', 'PineCam to live', function (next, node) { flipTailscale(next, node); }),\n"
     "      live: headSwitch(hswRow, 'pl-hsw-live', 'Pine Live', function (next, node) { flipSet(next, node); }),\n"
     "      album: headSwitch(hswRow, 'pl-hsw-album', 'Album recording', function (next) { flipAlbum(next); })};\n"
     "    head.appendChild(hswRow);\n",
     "/* [pltoggle] slots 1, 2 and one more: the header's three switches */"),

    ("js.paint_head",
     "    paintDetectBtn();         /* [pldetect] the box's tint follows the state */\n",
     "    paintDetectBtn();         /* [pldetect] the box's tint follows the state */\n"
     "    try { paintHeadSwitches(); }   /* [pltoggle] */\n"
     "    catch (err) { if (root.console) root.console.error('[pinelive] header switches paint failed:', err); }\n",
     "try { paintHeadSwitches(); }   /* [pltoggle] */"),

    ("js.helpers",
     "  /* ================================================== [pltray] the desk's tools */\n",
     "  /* ================================================== [pltoggle] the header's switches */\n"
     "  /* Three switches in the header, each the SAME road as its section twin:\n"
     "   *   PineCam to live = Picture, Video to Tailscale listeners (settings.tailscale_video)\n"
     "   *   Pine Live       = Event, MX Live event - the [plair] switch IS the set\n"
     "   *   Album recording = Recording (settings.record, remembered for the next set)\n"
     "   * One model value paints both twins; one function flips both. */\n"
     "  function tailscaleOn() {\n"
     "    var s = model.settings || {};\n"
     "    var pic = (model.state && model.state.picture) || {};\n"
     "    return s.tailscale_video !== undefined ? !!s.tailscale_video : !!pic.tailscale_video;\n"
     "  }\n"
     "\n"
     "  function albumOn() {\n"
     "    var s = model.settings || {};\n"
     "    var r = (model.state && model.state.recording) || {};\n"
     "    if (s.record !== undefined) return !!s.record;\n"
     "    if (r.album !== undefined) return !!r.album;\n"
     "    return r.on !== false;\n"
     "  }\n"
     "\n"
     "  /* immediate: both switches move now, the station stops the public\n"
     "   * picture now, and the answer's state puts them right if it refused */\n"
     "  function flipTailscale(next, node) {\n"
     "    if (!model.settings) model.settings = {};\n"
     "    model.settings.tailscale_video = next;\n"
     "    if (model.state && model.state.picture) model.state.picture.tailscale_video = next;\n"
     "    paint();\n"
     "    return act('/api/pinelive/settings', {tailscale_video: next}, node);\n"
     "  }\n"
     "\n"
     "  /* the [plair] road: on arms the set now on the chosen road (event mode -\n"
     "   * the interface takes the broadcast as soon as it sounds); off ends it,\n"
     "   * and only on a second tap */\n"
     "  function flipSet(next, node) {\n"
     "    var st = model.state || {};\n"
     "    if (!next && st.armed) {\n"
     "      confirmTap('disable', node, 'Tap again to end the set and switch MX Live off', function () {\n"
     "        act('/api/pinelive/event', {enabled: false}, node);\n"
     "      });\n"
     "      return;\n"
     "    }\n"
     "    var road = ui.prefs.road || (st.source && st.source.kind) || 'usb';\n"
     "    var body = {enabled: next, source: road};\n"
     "    if (road === 'usb' && model.settings && model.settings.device) body.device = model.settings.device;\n"
     "    act('/api/pinelive/event', body, node);\n"
     "  }\n"
     "\n"
     "  /* the station remembers it (settings.record); mid-set it starts or\n"
     "   * suspends the recording from this moment */\n"
     "  function flipAlbum(next) {\n"
     "    saveSetting('record', next);\n"
     "    paint();\n"
     "  }\n"
     "\n"
     "  function headSwitch(parent, cls, labelText, onFlip) {\n"
     "    var b = make('button', 'pl-hsw ' + cls);\n"
     "    b.type = 'button';\n"
     "    b.setAttribute('role', 'switch');\n"
     "    b.setAttribute('aria-checked', 'false');\n"
     "    b.setAttribute('aria-label', labelText);\n"
     "    var word = make('span', 'pl-hsw-label', labelText);\n"
     "    var track = make('span', 'pl-hsw-track');\n"
     "    track.appendChild(make('i'));\n"
     "    b.appendChild(word);\n"
     "    b.appendChild(track);\n"
     "    b.addEventListener('click', function (e) {\n"
     "      e.stopPropagation();\n"
     "      onFlip(b.getAttribute('aria-checked') !== 'true', b);\n"
     "    });\n"
     "    parent.appendChild(b);\n"
     "    return {root: b, label: word, set: function (on) {\n"
     "      var v = on ? 'true' : 'false';\n"
     "      if (b.getAttribute('aria-checked') !== v) b.setAttribute('aria-checked', v);\n"
     "    }};\n"
     "  }\n"
     "\n"
     "  var HSW_PHASE = {arming: 'armed', live: 'LIVE', fallback: 'fallback', stopping: 'ending'};\n"
     "  function paintHeadSwitches() {\n"
     "    var h = ui.hsw;\n"
     "    if (!h) return;\n"
     "    var st = model.state;\n"
     "    var cam = tailscaleOn();\n"
     "    h.cam.set(cam);\n"
     "    h.cam.root.title = cam\n"
     "      ? 'PineCam to live is ON: Tailscale listeners see the Pine Cam during the set. Tap to stop the public picture at once.'\n"
     "      : 'PineCam to live is OFF: the picture stays on your own screens - the camera keeps capturing. Tap to share it on the Tailscale stream.';\n"
     "    var rehearse = !!(st && st.armed && st.event && st.event.rehearse);\n"
     "    var setOn = !!(st && st.armed) && !rehearse;\n"
     "    var phase = setOn ? String(st.phase || 'arming') : 'idle';\n"
     "    var confirming = !!(ui.confirmUntil.disable && Date.now() < ui.confirmUntil.disable);\n"
     "    h.live.set(setOn);\n"
     "    if (h.live.root.getAttribute('data-phase') !== phase) h.live.root.setAttribute('data-phase', phase);\n"
     "    setClass(h.live.root, 'confirm', confirming);\n"
     "    setText(h.live.label, confirming ? 'Tap again to end' : rehearse ? 'Pine Live · test'\n"
     "      : setOn ? 'Pine Live · ' + (HSW_PHASE[phase] || phase) : 'Pine Live');\n"
     "    h.live.root.title = setOn\n"
     "      ? 'Pine Live is ' + (HSW_PHASE[phase] || phase) + ': the set has the station whenever the interface sounds. Tap twice to end the set.'\n"
     "      : 'Pine Live: tap to go live - event mode arms and the interface takes the broadcast as soon as it sounds.';\n"
     "    var album = albumOn();\n"
     "    h.album.set(album);\n"
     "    h.album.root.title = album\n"
     "      ? 'Album recording is ON: the set is written as tracks (split on 10 s of silence), MP3, a folder per set in Live Events. Remembered for the next set.'\n"
     "      : 'Album recording is OFF: the set still airs and takes the music, nothing is written. Remembered for the next set.';\n"
     "    [h.cam, h.live, h.album].forEach(function (x) {\n"
     "      if (!x.root.classList.contains('busy')) x.root.disabled = !st;\n"
     "    });\n"
     "    /* the detection box keeps the middle while the row leaves it room */\n"
     "    var head = h.row.parentNode;\n"
     "    if (head && ui.visible) {\n"
     "      var hr = head.getBoundingClientRect();\n"
     "      var end = Math.max(h.row.getBoundingClientRect().right,\n"
     "        ui.headClock ? ui.headClock.getBoundingClientRect().right : 0);\n"
     "      setClass(head, 'pl-head-crowded', hr.width > 0 && end > hr.left + hr.width / 2 - 32);\n"
     "    }\n"
     "  }\n"
     "\n"
     "  /* ================================================== [pltray] the desk's tools */\n",
     "/* ================================================== [pltoggle] the header's switches */"),
]

CSS = [
    ("css.hsw",
     ".pl-pop .pl-head-mid:empty { display: none; }\n",
     ".pl-pop .pl-head-mid:empty { display: none; }\n"
     "\n"
     "/* ------------------------------ [pltoggle] the header's three switches */\n"
     "/* PineCam to live, Pine Live, Album recording: a label over a small track,\n"
     " * the whole column the tap target. Pine Live tints with the set's phase. */\n"
     ".pl-pop .pl-hsw-row { display: flex; align-items: center; gap: 6px; flex: none; min-width: 0; }\n"
     ".pl-pop .pl-hsw {\n"
     "  display: inline-grid; justify-items: center; align-content: center; gap: 4px; flex: none;\n"
     "  height: 42px; min-width: 44px; margin: 0; padding: 2px 6px;\n"
     "  border: 1px solid transparent; border-radius: 6px; background: transparent; color: #8fa0ad;\n"
     "  -webkit-tap-highlight-color: transparent;\n"
     "}\n"
     ".pl-pop .pl-hsw:hover, .pl-pop .pl-hsw:focus-visible { border-color: #35414c; background: #121e25; }\n"
     ".pl-pop .pl-hsw-live { min-width: 98px; }\n"
     ".pl-hsw-label { font: 600 10.5px/1.1 Inter, Segoe UI, system-ui, sans-serif; white-space: nowrap; }\n"
     ".pl-hsw-track {\n"
     "  position: relative; width: 34px; height: 18px;\n"
     "  border: 1px solid #3a5360; border-radius: 999px; background: #1a252d;\n"
     "}\n"
     ".pl-hsw-track i {\n"
     "  position: absolute; left: 2px; top: 2px; width: 12px; height: 12px; border-radius: 50%;\n"
     "  background: #8fa0ad; transition: transform .15s ease, background .15s ease;\n"
     "}\n"
     ".pl-hsw[aria-checked=\"true\"] { color: #dbe7eb; }\n"
     ".pl-hsw[aria-checked=\"true\"] .pl-hsw-track { background: #1d4b3a; border-color: #54d18b; }\n"
     ".pl-hsw[aria-checked=\"true\"] .pl-hsw-track i { transform: translateX(16px); background: #54d18b; }\n"
     ".pl-hsw-live[data-phase=\"arming\"] .pl-hsw-track, .pl-hsw-live[data-phase=\"stopping\"] .pl-hsw-track { background: #2b2412; border-color: #e3be63; }\n"
     ".pl-hsw-live[data-phase=\"arming\"] .pl-hsw-track i, .pl-hsw-live[data-phase=\"stopping\"] .pl-hsw-track i { background: #e3be63; }\n"
     ".pl-hsw-live[data-phase=\"live\"] { color: #ffb3a8; }\n"
     ".pl-hsw-live[data-phase=\"live\"] .pl-hsw-track { background: #3a1715; border-color: #ff6b5e; }\n"
     ".pl-hsw-live[data-phase=\"live\"] .pl-hsw-track i { background: #ff6b5e; }\n"
     ".pl-hsw-live[data-phase=\"fallback\"] .pl-hsw-track { border-color: #ef6f5e; }\n"
     ".pl-hsw.confirm .pl-hsw-label { color: #ff8f84; }\n"
     ".pl-hsw.busy { opacity: .6; }\n"
     ".pl-hsw:disabled { cursor: default; opacity: .5; }\n"
     "/* a running set's clock crowds the middle: the detection box joins the row */\n"
     ".pl-pop .pl-head.pl-head-crowded .pl-detect-btn { position: static; transform: none; margin-left: auto; margin-right: auto; }\n"
     ".pl-pop .pl-head.pl-head-crowded .pl-close { margin-left: 0; }\n"
     "@media (max-width: 820px) {\n"
     "  .pl-pop .pl-hsw { padding: 2px 3px; }\n"
     "  .pl-pop .pl-hsw-live { min-width: 0; }\n"
     "  .pl-hsw-label { font-size: 9.5px; }\n"
     "}\n",
     "/* ------------------------------ [pltoggle] the header's three switches */"),
]


def edits_for(path):
    if path.endswith(".css"):
        return CSS
    if path.endswith(".js"):
        return JS
    raise SystemExit("not a .js or .css file: %s" % path)


if __name__ == "__main__":
    sys.exit(pltoggle_lib.main(edits_for))
