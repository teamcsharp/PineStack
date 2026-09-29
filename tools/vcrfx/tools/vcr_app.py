"""[vcrfx] app.py: one CRT effect for every picture the station serves.

- /spark/asset/pine-vcr.js (exact-name allowlist + the listener door's list)
- the panel loads it; the panel's own CRT set (djTvShow) and the render
  lightbox come on / go off through it
- the tune page (what Tailscale / public viewers see) loads it, and:
    * the SFX clip on the gallery stage comes on at its first frame and goes
      off with the CRT collapse (this replaces #1415's random slideshow
      hand-back for the VIDEO - the operator now wants the one effect for
      every picture; the artwork is revealed underneath as before)
    * the Pine Cam window comes on / goes off with it, and replays every
      PineCam-to-live flip it missed (`switch.flips` on /api/pinelink/mine),
      asking every 2.5 s while it is watched in the house or on the tailnet
      (15 s on the car stream / a hidden tab, as before)
    * the PineLive picture (the album art that shows the video feed) comes on
      when a set begins and goes off when it ends, and follows the switch -
      learned from the clock it already polls (clock_extra.pinelive.picture)
- /api/pinelink/mine answers `switch`: {on, flips, armed, yours}
TARGET: app.py
"""
from _vcrlib import Edit, main

EDITS = [
    # ------------------------------------------------------------ the asset
    Edit("asset", '"pine-vcr.js": "application/javascript; charset=utf-8",',
         """    "sfx-tv.css": "text/css; charset=utf-8",
    "wall-transition.js": "application/javascript; charset=utf-8",
""",
         """    "sfx-tv.css": "text/css; charset=utf-8",
    # [vcrfx] the ONE picture on / off effect (the SFX TV's CRT), shared by
    # the panel, the tune page, the desktop and the tablet.
    "pine-vcr.js": "application/javascript; charset=utf-8",
    "wall-transition.js": "application/javascript; charset=utf-8",
"""),
    Edit("door", '"/spark/asset/pine-vcr.js",',
         """               "/spark/asset/sfx-tv.css",
               "/spark/asset/slideshow.css",   # #1415,
""",
         """               "/spark/asset/sfx-tv.css",
               "/spark/asset/pine-vcr.js",     # [vcrfx] the CRT on/off
               "/spark/asset/slideshow.css",   # #1415,
"""),
    # ------------------------------------------------------------ the panel
    Edit("panel-script", '<script src="/spark/asset/pine-vcr.js"></script>\n<script src="/spark/asset/wall-transition.js">',
         """<script src="/spark/asset/wall-transition.js"></script>
""",
         """<script src="/spark/asset/pine-vcr.js"></script>
<script src="/spark/asset/wall-transition.js"></script>
"""),
    Edit("djtv-on", "window.PineVcr.in(tube, {flash: flash});",
         """    tube.classList.add("on");              // dot -> line -> picture
    flash.classList.add("pop");
""",
         """    if (window.PineVcr) window.PineVcr.in(tube, {flash: flash});   // [vcrfx] dot -> line -> picture
    else { tube.classList.add("on"); flash.classList.add("pop"); }
"""),
    Edit("djtv-off", "window.PineVcr.out(tube);",
         """      tube.classList.remove("on");
      void tube.offsetWidth;             // restart the animation, not resume it
      tube.classList.add("off");
""",
         """      if (window.PineVcr) window.PineVcr.out(tube);                // [vcrfx] picture -> line -> dot
      else {
        tube.classList.remove("on");
        void tube.offsetWidth;             // restart the animation, not resume it
        tube.classList.add("off");
      }
"""),
    Edit("lightbox-on", "vcrfx: a video comes on like the SFX TV; a still is simply there",
         """  img.style.display = isVid ? "none" : "block";
  vid.style.display = isVid ? "block" : "none";
""",
         """  img.style.display = isVid ? "none" : "block";
  vid.style.display = isVid ? "block" : "none";
  /* [vcrfx: a video comes on like the SFX TV; a still is simply there] */
  if (window.PineVcr) { if (isVid) window.PineVcr.in(wrap); else window.PineVcr.cancel(wrap); }
"""),
    Edit("lightbox-off", "closeLightbox.vcrBusy",
         """function closeLightbox(event) {
  if (event && event.target !== document.getElementById("lightbox")) return;
""",
         """function closeLightbox(event) {
  if (event && event.target !== document.getElementById("lightbox")) return;
  /* [vcrfx] A VIDEO GOES OFF THE WAY IT CAME ON: paused, collapsed, and
   * only then closed - unless the lightbox was opened again meanwhile. A
   * second close during the collapse closes at once. */
  const vcrWrap = document.getElementById("lbImgWrap");
  const vcrBox = document.getElementById("lightbox");
  if (window.PineVcr && !closeLightbox.vcrBusy && vcrWrap && vcrBox
      && vcrWrap.classList.contains("lb-video") && vcrBox.style.display !== "none") {
    closeLightbox.vcrBusy = true;
    const vcrSerial = lightboxOpenSerial;
    ["lightboxVid", "lightboxRefVid"].forEach((id) => {
      try { document.getElementById(id).pause(); } catch (e) {}
    });
    window.PineVcr.out(vcrWrap).then(() => {
      if (vcrSerial === lightboxOpenSerial) {
        closeLightbox();
        window.PineVcr.cancel(vcrWrap);
      }
      closeLightbox.vcrBusy = false;
    });
    return;
  }
"""),
    # ------------------------------------------------------------ the tune page
    Edit("tune-script", '<script src="/spark/asset/pine-vcr.js"></script>\n<script src="/spark/asset/sfx-tv.js">',
         """<script src="/spark/asset/sfx-tv.js"></script>
""",
         """<script src="/spark/asset/pine-vcr.js"></script>
<script src="/spark/asset/sfx-tv.js"></script>
"""),
    Edit("tune-clock-hook", "window.pineVcrClock(c)",
         """    stateAt = Date.now();
    pineSoloGate(c);                                        // #1008
""",
         """    stateAt = Date.now();
    try { window.pineVcrClock(c); } catch (e) { /* [vcrfx] the show goes on */ }
    pineSoloGate(c);                                        // #1008
"""),
    Edit("tune-cover", "pineVcrCover(cover, now);",
         """    cover.dataset.id = now.id || "";
    cover.onerror = () => { cover.style.display = "none"; };
    cover.onload = () => { cover.style.display = "block"; };
    if (now.art) { cover.src = now.art; } else { cover.style.display = "none"; }
""",
         """    cover.dataset.id = now.id || "";
    pineVcrCover(cover, now);                               /* [vcrfx] */
"""),
    Edit("tune-vcr-fns", "function pineVcrCover(cover, now)",
         """let clockLive = 0;
let clockSeq = 0;
""",
         """/* [vcrfx] THE PINELIVE PICTURE COMES ON AND GOES OFF LIKE THE SFX TV.
 *
 * "if a Pine Box live broadcast begins, show that animate in with the same
 *  V CR effect. And same thing if it goes away ... If a viewer is watching
 *  the telescale broadcast and I'm toggling the Pine Cam toggle off and on,
 *  then they should be seeing a video go in and out with the V C R effect
 *  repeating over and over as I'm flipping the switch over and over."
 *
 * The sleeve IS the live picture during a set (the album art shows the
 * video feed), so: a set beginning brings it on at its first frame, a set
 * ending collapses it before the next record's sleeve takes the frame, and
 * PineCam to live - read off the clock this page already polls - collapses
 * it and brings it back, every flip replayed (`switch.flips`), never faster
 * than the effect can be seen and always ending where the switch is. */
function pineVcrCover(cover, now) {
  const V = window.PineVcr;
  const wasLive = cover.dataset.live === "1";
  const live = !!now.live;
  cover.dataset.live = live ? "1" : "";
  const id = now.id || "";
  const put = () => {
    if (cover.dataset.id !== id) return;          /* a newer record already */
    cover.onerror = () => { cover.style.display = "none"; };
    cover.onload = () => {
      if (live && vcrLiveWant === false) return;   /* switched off: stays down */
      cover.style.display = "block";
      if (live && V && cover.dataset.vcrLit !== id) { cover.dataset.vcrLit = id; V.in(cover); }
    };
    if (now.art) { cover.src = now.art; } else { cover.style.display = "none"; }
  };
  if (wasLive && !live && V && cover.style.display !== "none") {
    vcrLiveWant = null;
    V.out(cover).then(() => { V.cancel(cover); put(); });
    return;
  }
  put();
}
let vcrLiveWant = null;
let vcrLiveFlips = null;
window.pineVcrClock = function (c) {
  const V = window.PineVcr;
  const pl = c && c.pinelive;
  const pic = pl && pl.picture;
  const sw = pic && pic.switch;
  if (!V || !pic || !c.live) { vcrLiveWant = null; vcrLiveFlips = null; return; }
  const flips = sw ? Number(sw.flips || 0) : 0;
  if (sw && vcrLiveFlips !== null && flips !== vcrLiveFlips && window.pineCamAsk) window.pineCamAsk();
  const art = String(pic.art || "");
  const want = !!art;
  const cover = document.getElementById("cover");
  if (!cover) return;
  if (vcrLiveWant === null || vcrLiveFlips === null || flips < vcrLiveFlips) {
    vcrLiveWant = want; vcrLiveFlips = flips;        /* first sight: no replay */
    return;
  }
  /* in the house the picture never left (only the door hides it), so only a
     page through the listener door replays the flips */
  const burst = (typeof AWAY !== "undefined" && AWAY) ? flips - vcrLiveFlips : 0;
  vcrLiveFlips = flips;
  if (!burst && want === vcrLiveWant) return;
  vcrLiveWant = want;
  const o = {
    /* a switched-off picture's stream has ended: asked again with a new
       name for the buster (?t= is the token, never a cache-buster) */
    show: (el) => {
      if (art) el.src = art + (art.indexOf("?") >= 0 ? "&" : "?") + "vcr=" + Date.now();
      el.style.display = "block";
    },
    hide: (el) => { if (!vcrLiveWant) el.style.display = "none"; },
  };
  if (burst > 0) V.flip(cover, want, burst, o); else V.set(cover, want, o);
};

let clockLive = 0;
let clockSeq = 0;
"""),
    Edit("tune-tv-on", "vcrfx: the clip comes on at its first frame",
         """    el.src = v.url;
    el.currentTime = Math.max(0, into);
""",
         """    if (window.PineVcr) {                 /* [vcrfx: the clip comes on at its first frame] */
      const V = window.PineVcr, mine = v.url;
      el.style.visibility = "hidden";
      let lit = false;
      const light = () => {
        if (lit || tvNow !== mine) return;
        lit = true;
        el.style.visibility = "";
        V.in(el);
      };
      el.addEventListener("loadeddata", light, {once: true});
      el.addEventListener("playing", light, {once: true});
      setTimeout(light, 3000);
    }
    el.src = v.url;
    el.currentTime = Math.max(0, into);
"""),
    Edit("tune-tv-off", "tvHideVcr(stage, el); return;",
         """  if (tvHanding) tvHanding();
  const kind = TUNE_TRANSITIONS[""",
         """  if (tvHanding) tvHanding();
  if (window.PineVcr) { tvHideVcr(stage, el); return; }      /* [vcrfx] */
  const kind = TUNE_TRANSITIONS["""),
    Edit("tune-tv-off-fn", "function tvHideVcr(stage, el)",
         """let tvHanding = null;
""",
         """let tvHanding = null;

/* [vcrfx] THE CLIP GOES OFF LIKE THE SFX TV. The artwork is laid back under
 * it (the #1415 `handing` frame keeps both up) and the picture collapses to
 * a line and a dot over it. A clip that came on during the collapse keeps
 * its source; only a stage with nothing on it lets the element go. */
function tvHideVcr(stage, el) {
  const V = window.PineVcr;
  stage.classList.add("handing");
  stage.classList.remove("tv");
  el.style.visibility = "";
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    if (tvHanding === finish) tvHanding = null;
    stage.classList.remove("handing");
    if (tvNow === null) {
      try { el.pause(); el.removeAttribute("src"); el.load(); } catch (e) {}
      try { V.cancel(el); } catch (e) {}
    }
  };
  tvHanding = finish;
  V.out(el).then(finish);
  setTimeout(finish, V.OUT_MS + 400);
}
"""),
    Edit("tune-cam-state", "function camVcr(want, burst)",
         """  var vid = null;
  var lowUrl = "";
  var lowBrokenAt = 0;
""",
         """  var vid = null;
  var lowUrl = "";
  var lowBrokenAt = 0;
  /* [vcrfx] THE WINDOW COMES ON AND GOES OFF LIKE THE SFX TV, every time
   * PineCam to live is flipped - each flip the station counted since the
   * last answer is played (PineVcr.flip), so six fast flips are six
   * collapses and openings, ending where the switch ended. The last frame
   * is kept (hidden) so a replayed opening shows a picture, not a hole. */
  var lastFlips = null;
  function camVcr(want, burst) {
    var V = window.PineVcr;
    if (want) build();
    if (!box) return;
    if (!V) {
      if (want) { box.classList.add("show"); draw(); } else box.classList.remove("show");
      return;
    }
    var o = {
      show: function () { box.classList.add("show"); draw(); },
      hide: function () { if (!mayShow) box.classList.remove("show"); }
    };
    if (burst > 0) V.flip(box, want, burst, o); else V.set(box, want, o);
  }
"""),
    Edit("tune-cam-ask", "var burst = (sw && sw.yours",
         """      if (want !== mayShow) {
        mayShow = want;
        if (want) { build(); box.classList.add("show"); draw(); }
        else if (box) {
          box.classList.remove("show");
          shot.removeAttribute("src");   /* stop the fetches too */
        }
      }
      if (want && lowWanted()) showVideo();
      else dropVideo(false);
""",
         """      /* [vcrfx] the switch's flips since the last answer, for this viewer */
      var sw = (got && got.switch) || null;
      var flips = sw ? Number(sw.flips || 0) : 0;
      var burst = (sw && sw.yours && lastFlips !== null && flips > lastFlips) ? flips - lastFlips : 0;
      /* a flip is news for the live picture too: the clock (15 s apart on
         the stream road) is asked now rather than at its next beat */
      if (sw && lastFlips !== null && flips !== lastFlips && typeof clockPoll === "function") {
        try { clockPoll(); } catch (e) { /* the clock asks again anyway */ }
      }
      if (sw) lastFlips = flips;
      if (want !== mayShow || burst) {
        mayShow = want;                  /* draw() stops asking when false */
        camVcr(want, burst);
      }
      if (want && lowWanted()) showVideo();
      else if (want || !vid) dropVideo(false);
      else setTimeout(function () { if (!mayShow) dropVideo(false); }, 700);
"""),
    Edit("tune-cam-fail", "mayShow = false; camVcr(false, 0);",
         """      if (mayShow && box) { mayShow = false; box.classList.remove("show"); }
""",
         """      if (mayShow && box) { mayShow = false; camVcr(false, 0); }     /* [vcrfx] */
"""),
    Edit("tune-cam-pace", "window.pineCamAsk = function",
         """  function loop() {
    try { ask(); } catch (e) {}
    setTimeout(loop, 15000);
  }
""",
         """  function loop() {
    try { ask(); } catch (e) {}
    /* [vcrfx] a watched page learns the switch within a few seconds (a
     * 300-byte answer: 0.1 kB/s beside an 8 kB/s audio lane); a hidden tab
     * keeps the old quarter-minute. */
    var road = (typeof streamMode !== "undefined" && streamMode) ? 4000 : 2500;
    setTimeout(loop, document.hidden ? 15000 : road);
  }
  window.pineCamAsk = function () { try { ask(); } catch (e) {} };   /* [vcrfx] the clock's nudge */
"""),
    # ------------------------------------------------------------ the camera's answer
    Edit("viewer-ok-sig", "def pinelink_viewer_ok(token: str, switch: bool = True) -> bool:",
         """def pinelink_viewer_ok(token: str) -> bool:
""",
         """def pinelink_viewer_ok(token: str, switch: bool = True) -> bool:
"""),
    Edit("viewer-ok-switch", "if switch and pinelive.public_video_blocked():",
         """    if pinelive.public_video_blocked():       # [pinelive] Tailscale video OFF
        return False
    mode = pinelink_public_mode()
""",
         """    if switch and pinelive.public_video_blocked():   # [pinelive] Tailscale video OFF ([vcrfx] switch=False asks "but for it")
        return False
    mode = pinelink_public_mode()
"""),
    Edit("mine-switch-fn", "def _vcr_switch(t: str) -> dict[str, Any]:",
         """@app.get("/api/pinelink/mine")
""",
         """def _vcr_switch(t: str) -> dict[str, Any]:
    \"\"\"[vcrfx] PineCam to live for a viewer's CRT: on, flips, armed, and
    `yours` - whether this token is one the switch decides for (it would see
    the camera if the switch were on). Only then does the page replay flips.\"\"\"
    sw = pinelive.video_switch()
    try:
        sw["yours"] = bool(t and sw.get("armed") and pinelink_viewer_ok(t, switch=False))
    except Exception:  # noqa: BLE001
        sw["yours"] = False
    return sw


@app.get("/api/pinelink/mine")
"""),
    Edit("mine-switch", '"switch": _vcr_switch(t),',
         """            "small": small,                                 # [#1475]
""",
         """            "small": small,                                 # [#1475]
            "switch": _vcr_switch(t),                       # [vcrfx]
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
